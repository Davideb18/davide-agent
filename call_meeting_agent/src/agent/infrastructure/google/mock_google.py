import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional, Dict

from ...domain.models import CalendarPayload, EmailPayload, CalendarEventItem
from ...application.resolve_conflict import evaluate_calendar_slot


class MockCalendarService:
    """Simulatore di Google Calendar per test deterministici e demo offline senza credenziali."""

    def __init__(self, simulated_busy_slots: Optional[List[Tuple[datetime, datetime]]] = None) -> None:
        # Se non passiamo impegni, ne creiamo uno automatico per OGGI alle 14:00 UTC
        now_base = datetime.now(timezone.utc).replace(hour=14, minute=0, second=0, microsecond=0)
        if simulated_busy_slots is not None:
            self.busy_slots = simulated_busy_slots
        else:
            self.busy_slots = [
                (now_base, now_base + timedelta(hours=1)),  # Dalle 14:00 alle 15:00 UTC: OCCUPATO!
                (now_base + timedelta(days=1, hours=1), now_base + timedelta(days=1, hours=3)), # Domani: OCCUPATO
            ]
        self.created_events: Dict[str, CalendarPayload] = {}

    async def check_is_busy(self, start_utc: datetime, end_utc: datetime) -> bool:
        """Verifica se l'intervallo richiesto si sovrappone a uno dei blocchi occupati in agenda."""
        for busy_start, busy_end in self.busy_slots:
            # Due intervalli temporali si scontrano se: inizio_A < fine_B E fine_A > inizio_B
            if start_utc < busy_end and end_utc > busy_start:
                return True
        return False

    async def get_events(self, start_utc: datetime, end_utc: datetime) -> List[CalendarEventItem]:
        """Restituisce un'agenda realistica a 3 giorni (Ieri, Oggi, Domani) in stile Apple Calendar."""
        today_midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_midnight = today_midnight - timedelta(days=1)
        tomorrow_midnight = today_midnight + timedelta(days=1)

        all_mock_events: List[CalendarEventItem] = [
            # ── IERI ────────────────────────────────────────────────────────
            CalendarEventItem(
                id="evt_yesterday_1",
                title="Allineamento Architettura & Microservizi",
                start_utc=yesterday_midnight.replace(hour=10, minute=0),
                end_utc=yesterday_midnight.replace(hour=11, minute=0),
                location="Google Meet",
                attendees=["filippo@trellis.so"],
                description="Studio transizione verso Clean Architecture e gestione lock distribuiti.",
                color_tag="purple",
            ),
            CalendarEventItem(
                id="evt_yesterday_2",
                title="Call Review Investitori & Metriche PMS",
                start_utc=yesterday_midnight.replace(hour=15, minute=30),
                end_utc=yesterday_midnight.replace(hour=16, minute=30),
                location="Zoom Call",
                attendees=["investors@syndicate.vc"],
                description="Presentazione KPI trimestrali e retention rate.",
                color_tag="orange",
            ),
            # ── OGGI (GIORNO MEETING / COLLOQUIO) ────────────────────────────
            CalendarEventItem(
                id="evt_today_1",
                title="Daily Standup Engineering",
                start_utc=today_midnight.replace(hour=9, minute=30),
                end_utc=today_midnight.replace(hour=10, minute=0),
                location="Google Meet",
                attendees=["filippo@trellis.so", "team@trellis.so"],
                description="Allineamento rapido del team di ingegneria sulle priorità del rilascio.",
                color_tag="blue",
            ),
            CalendarEventItem(
                id="evt_today_conflict",
                title="Sprint Review Trellis & Roadmap Q4",
                start_utc=today_midnight.replace(hour=14, minute=0),
                end_utc=today_midnight.replace(hour=15, minute=0),
                location="Google Meet",
                attendees=["filippo@trellis.so"],
                description="Revisione avanzamento sprint, architettura PMS e stato delle integrazioni.",
                color_tag="purple",
                is_conflict=True,
            ),
            CalendarEventItem(
                id="evt_today_2",
                title="Sync Contrattuale & Modello Commissioni",
                start_utc=today_midnight.replace(hour=17, minute=0),
                end_utc=today_midnight.replace(hour=17, minute=45),
                location="Milano Office",
                attendees=["marco.rossi@legalstudio.it"],
                description="Chiusura NDA e verifica clausole sul pricing al 3%.",
                color_tag="orange",
            ),
            # ── DOMANI ──────────────────────────────────────────────────────
            CalendarEventItem(
                id="evt_tomorrow_1",
                title="Design Review UI/UX & Design System",
                start_utc=tomorrow_midnight.replace(hour=11, minute=0),
                end_utc=tomorrow_midnight.replace(hour=12, minute=0),
                location="Figma & Google Meet",
                attendees=["marco.bianchi@designstudio.io"],
                description="Revisione componenti Apple-grade e palette colori ad alto contrasto.",
                color_tag="blue",
            ),
            CalendarEventItem(
                id="evt_tomorrow_2",
                title="Sessione Tecnica & Deep Dive Colloquio",
                start_utc=tomorrow_midnight.replace(hour=15, minute=0),
                end_utc=tomorrow_midnight.replace(hour=17, minute=0),
                location="Google Meet",
                attendees=["filippo@trellis.so"],
                description="Approfondimento su State Machine, Concurrency Lock e Idempotenza.",
                color_tag="purple",
            ),
        ]

        # Aggiungiamo eventuali eventi creati dinamicamente dall'utente durante la sessione
        for ev_id, payload in self.created_events.items():
            all_mock_events.append(
                CalendarEventItem(
                    id=ev_id,
                    title=payload.title,
                    start_utc=payload.start_utc,
                    end_utc=payload.end_utc,
                    location=payload.location,
                    attendees=payload.attendees,
                    description=payload.description,
                    color_tag="green",
                )
            )

        # Filtra gli eventi che si sovrappongono all'intervallo richiesto [start_utc, end_utc]
        return [
            ev for ev in all_mock_events
            if ev.start_utc < end_utc and ev.end_utc > start_utc
        ]

    async def find_alternative_slots(
        self, requested_start_utc: datetime, duration_minutes: int, count: int = 3
    ) -> List[datetime]:
        """Utilizza l'algoritmo Sliding Window di resolve_conflict per calcolare gli slot liberi."""
        _, alternatives = await evaluate_calendar_slot(
            self, requested_start_utc, duration_minutes=duration_minutes, max_alternatives=count
        )
        return alternatives

    async def create_event(self, payload: CalendarPayload, idempotency_key: str) -> str:
        """Simula la creazione di un evento su Google Calendar restituendo un ID univoco."""
        event_id = f"mock_cal_{hashlib.sha256(idempotency_key.encode()).hexdigest()[:10]}"
        self.created_events[event_id] = payload
        return event_id


class MockEmailService:
    """Simulatore di Gmail per test deterministici e demo offline."""

    def __init__(self) -> None:
        self.created_drafts: Dict[str, EmailPayload] = {}

    async def create_draft(self, payload: EmailPayload, idempotency_key: str) -> str:
        """Simula la creazione di una bozza su Gmail con verifica idempotenza."""
        draft_id = f"mock_draft_{hashlib.sha256(idempotency_key.encode()).hexdigest()[:10]}"
        self.created_drafts[draft_id] = payload
        return draft_id


# SCRIPT DI COLLAUDO IMMEDIATO
if __name__ == "__main__":
    import asyncio

    async def test():
        calendar = MockCalendarService()
        email_svc = MockEmailService()

        # Proviamo a richiedere proprio lo slot delle 14:00 UTC (che abbiamo programmato come OCCUPATO)
        target_time = datetime.now(timezone.utc).replace(hour=14, minute=0, second=0, microsecond=0)

        print("=" * 65)
        print(f"1. Test disponibilità per le {target_time.strftime('%H:%M')} UTC...")
        is_busy, alternatives = await evaluate_calendar_slot(calendar, target_time, duration_minutes=30)

        if is_busy:
            print("⚠️ CONFLITTO RILEVATO! (Rischio Overbooking alla Trellis)")
            print(f"Top {len(alternatives)} slot alternativi liberi calcolati dalla Sliding Window:")
            for i, slot in enumerate(alternatives, 1):
                print(f"   [{i}] {slot.strftime('%Y-%m-%d %H:%M')} UTC")
        else:
            print("Slot libero.")

        # Test creazione bozza email
        sample_email = EmailPayload(
            recipient_email="filippo@trellis.so",
            recipient_name="Filippo Calzavara",
            subject="Follow-up Call Trellis",
            body_markdown="Ciao Filippo, ecco il riepilogo della nostra call...",
        )
        draft_id = await email_svc.create_draft(sample_email, idempotency_key="key_test_123")
        print(f"2. Bozza Gmail creata con successo! (ID: {draft_id})")
        print("=" * 65)

    asyncio.run(test())
