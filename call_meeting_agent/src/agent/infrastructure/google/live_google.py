import os
import base64
from email.mime.text import MIMEText
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ...domain.models import CalendarPayload, EmailPayload
from ...application.resolve_conflict import evaluate_calendar_slot

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.compose",
]


def get_google_credentials(
    credentials_path: str = "data/credentials.json",
    token_path: str = "data/token.json",
) -> Optional[Credentials]:
    """Gestisce il flusso OAuth 2.0 per accedere all'account Google personale."""
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                return None
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return creds


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
            "conferenceData": {
                "createRequest": {
                    "requestId": idempotency_key[:20],
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }

        created_event = (
            self.service.events()
            .insert(
                calendarId="primary",
                body=event_body,
                conferenceDataVersion=1,
            )
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
        message["to"] = payload.recipient_email
        message["subject"] = payload.subject
        if payload.cc:
            message["cc"] = ", ".join(payload.cc)

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft_body = {"message": {"raw": encoded_message}}

        draft = (
            self.service.users()
            .drafts()
            .create(userId="me", body=draft_body)
            .execute()
        )
        return draft.get("id", "unknown_draft_id")
