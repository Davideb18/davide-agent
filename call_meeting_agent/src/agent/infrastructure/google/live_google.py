import os
import base64
import threading
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ...domain.models import CalendarPayload, EmailPayload, CalendarEventItem
from ...application.resolve_conflict import evaluate_calendar_slot

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.compose",
]

_CREDENTIALS_LOCK = threading.Lock()
_CACHED_CREDS: Optional[Credentials] = None


def get_google_credentials(
    credentials_path: str = "data/credentials.json",
    token_path: str = "data/token.json",
) -> Optional[Credentials]:
    """Gestisce il flusso OAuth 2.0 per accedere all'account Google personale in modo thread-safe."""
    global _CACHED_CREDS

    # 1. Fast path: token in cache ancora valido (zero lock overhead)
    if _CACHED_CREDS and _CACHED_CREDS.valid:
        return _CACHED_CREDS

    # 2. Concurrency-Safe Refresh & Load con Double-Checked Locking
    with _CREDENTIALS_LOCK:
        if _CACHED_CREDS and _CACHED_CREDS.valid:
            return _CACHED_CREDS

        creds = None
        if os.path.exists(token_path):
            try:
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            except Exception:
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    creds = None

            if not creds or not creds.valid:
                if not os.path.exists(credentials_path):
                    return None
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)

            if creds and creds.valid:
                os.makedirs(os.path.dirname(os.path.abspath(token_path)), exist_ok=True)
                with open(token_path, "w", encoding="utf-8") as token_file:
                    token_file.write(creds.to_json())

        _CACHED_CREDS = creds
        return _CACHED_CREDS


class LiveCalendarService:
    """Implementazione reale di CalendarServicePort su Google Calendar API."""

    def __init__(self, credentials: Optional[Credentials] = None) -> None:
        self.creds = credentials or get_google_credentials()
        if not self.creds:
            raise FileNotFoundError(
                "File data/credentials.json mancante! Segui la guida per scaricarlo da Google Cloud Console."
            )
        self.service = build("calendar", "v3", credentials=self.creds)

    async def check_is_busy(self, start_utc: datetime, end_utc: datetime) -> bool:
        time_min = start_utc.isoformat()
        time_max = end_utc.isoformat()

        events_result = (
            self.service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])
        return len(events) > 0

    async def get_events(self, start_utc: datetime, end_utc: datetime) -> List[CalendarEventItem]:
        """Recupera la lista degli eventi del calendario nell'intervallo temporale."""
        time_min = start_utc.isoformat()
        time_max = end_utc.isoformat()
        try:
            events_result = (
                self.service.events()
                .list(
                    calendarId="primary",
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            raw_items = events_result.get("items", [])
            items: List[CalendarEventItem] = []
            for item in raw_items:
                start_raw = item.get("start", {})
                end_raw = item.get("end", {})
                start_str = start_raw.get("dateTime") or start_raw.get("date")
                end_str = end_raw.get("dateTime") or end_raw.get("date")
                if not start_str:
                    continue
                try:
                    s_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                except Exception:
                    continue
                try:
                    e_dt = (
                        datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                        if end_str
                        else s_dt + timedelta(minutes=30)
                    )
                except Exception:
                    e_dt = s_dt + timedelta(minutes=30)

                att_emails = [a.get("email", "") for a in item.get("attendees", []) if a.get("email")]
                summary = item.get("summary") or "Impegno senza titolo"
                location = item.get("location")
                description = item.get("description")

                # Assegnazione tag cromatico Apple Calendar
                color_tag = "blue"
                summary_lower = summary.lower()
                if any(w in summary_lower for w in ["sprint", "tech", "dev", "review", "architettura"]):
                    color_tag = "purple"
                elif any(w in summary_lower for w in ["sync", "meeting", "call", "allineamento"]):
                    color_tag = "blue"
                elif any(w in summary_lower for w in ["investitori", "board", "pricing", "urgente"]):
                    color_tag = "orange"

                items.append(
                    CalendarEventItem(
                        id=item.get("id", ""),
                        title=summary,
                        start_utc=s_dt,
                        end_utc=e_dt,
                        location=location,
                        attendees=att_emails,
                        description=description,
                        color_tag=color_tag,
                    )
                )
            return items
        except Exception:
            return []

    async def find_alternative_slots(
        self, requested_start_utc: datetime, duration_minutes: int, count: int = 3
    ) -> List[datetime]:
        _, alternatives = await evaluate_calendar_slot(
            self, requested_start_utc, duration_minutes=duration_minutes, max_alternatives=count
        )
        return alternatives

    async def create_event(self, payload: CalendarPayload, idempotency_key: str) -> str:
        note_suffix = chr(10) + chr(10) + f"[Schedulato da Executive AI Agent | Key: {idempotency_key}]"
        desc = payload.description + note_suffix
        event_body = {
            "summary": payload.title,
            "description": desc,
            "start": {
                "dateTime": payload.start_utc.isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": payload.end_utc.isoformat(),
                "timeZone": "UTC",
            },
            "attendees": [{"email": email.strip()} for email in payload.attendees if email.strip()],
        }
        if payload.location:
            event_body["location"] = payload.location

        # Conference link solo se espressamente richiesto o meeting virtuale
        conf_version = 0
        if payload.location == "Google Meet" or (payload.attendees and not payload.location):
            event_body["conferenceData"] = {
                "createRequest": {
                    "requestId": idempotency_key[:20],
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
            conf_version = 1

        insert_kwargs = {"calendarId": "primary", "body": event_body}
        if conf_version > 0:
            insert_kwargs["conferenceDataVersion"] = conf_version

        created_event = (
            self.service.events()
            .insert(**insert_kwargs)
            .execute()
        )
        return created_event.get("id", "unknown_event_id")


class LiveEmailService:
    """Implementazione reale di EmailServicePort su Gmail API (Bozze protette - drafts.create)."""

    def __init__(self, credentials: Optional[Credentials] = None) -> None:
        self.creds = credentials or get_google_credentials()
        if not self.creds:
            raise FileNotFoundError(
                "File data/credentials.json mancante! Segui la guida per scaricarlo da Google Cloud Console."
            )
        self.service = build("gmail", "v1", credentials=self.creds)

    async def create_draft(self, payload: EmailPayload, idempotency_key: str) -> str:
        message = MIMEText(payload.body_markdown, "plain", "utf-8")
        clean_recipient = (payload.recipient_email or "").strip()
        if clean_recipient:
            message["to"] = clean_recipient
        message["subject"] = payload.subject
        if payload.cc:
            clean_ccs = [c.strip() for c in payload.cc if c.strip()]
            if clean_ccs:
                message["cc"] = ", ".join(clean_ccs)

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft_body = {"message": {"raw": encoded_message}}

        draft = (
            self.service.users()
            .drafts()
            .create(userId="me", body=draft_body)
            .execute()
        )
        return draft.get("id", "unknown_draft_id")


class MacMailService:
    """Implementazione reale nativa macOS Apple Mail (zero token, zero mock)."""

    async def create_draft(self, payload: EmailPayload, idempotency_key: str) -> str:
        import subprocess
        escaped_subj = payload.subject.replace('"', '\\"')
        escaped_body = payload.body_markdown.replace('"', '\\"').replace("\n", "\\n")
        escaped_email = (payload.recipient_email or "").strip().replace('"', '\\"')

        # Genera la clausola destinatario SOLO se l'email non è vuota
        recipient_clause = ""
        if escaped_email:
            recipient_clause = f'''
            tell newMsg
                make new to recipient at end of to recipients with properties {{address:"{escaped_email}"}}
            end tell
            '''

        script = f'''
        tell application "Mail"
            set newMsg to (make new outgoing message with properties {{subject:"{escaped_subj}", content:"{escaped_body}", visible:true}})
            {recipient_clause}
            save newMsg
        end tell
        '''
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return f"mac_mail_{idempotency_key[:10]}"
        raise RuntimeError(res.stderr or "Errore creazione bozza Apple Mail")


class LocalCalendarService:
    """Implementazione dinamica in memoria di CalendarServicePort (nessun mock preimpostato)."""

    def __init__(self) -> None:
        self.events: Dict[str, CalendarEventItem] = {}

    async def check_is_busy(self, start_utc: datetime, end_utc: datetime) -> bool:
        for ev in self.events.values():
            if start_utc < ev.end_utc and end_utc > ev.start_utc:
                return True
        return False

    async def get_events(self, start_utc: datetime, end_utc: datetime) -> List[CalendarEventItem]:
        return [
            ev for ev in self.events.values()
            if ev.start_utc < end_utc and ev.end_utc > start_utc
        ]

    async def find_alternative_slots(
        self, requested_start_utc: datetime, duration_minutes: int, count: int = 3
    ) -> List[datetime]:
        _, alternatives = await evaluate_calendar_slot(
            self, requested_start_utc, duration_minutes=duration_minutes, max_alternatives=count
        )
        return alternatives

    async def create_event(self, payload: CalendarPayload, idempotency_key: str) -> str:
        import hashlib
        event_id = f"evt_{hashlib.sha256(idempotency_key.encode()).hexdigest()[:10]}"
        self.events[event_id] = CalendarEventItem(
            id=event_id,
            title=payload.title,
            start_utc=payload.start_utc,
            end_utc=payload.end_utc,
            location=payload.location,
            attendees=payload.attendees,
            description=payload.description,
            color_tag="blue",
        )
        return event_id


class LocalEmailService:
    """Implementazione locale per la persistenza delle bozze email (nessun mock preimpostato)."""

    def __init__(self) -> None:
        self.drafts: Dict[str, EmailPayload] = {}

    async def create_draft(self, payload: EmailPayload, idempotency_key: str) -> str:
        import hashlib
        draft_id = f"draft_{hashlib.sha256(idempotency_key.encode()).hexdigest()[:10]}"
        self.drafts[draft_id] = payload
        return draft_id

