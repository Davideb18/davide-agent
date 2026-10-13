import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional, Dict

from ...domain.models import CalendarPayload, EmailPayload
from ...application.resolve_conflict import evaluate_calendar_slot


class MockCalendarService:
    """Simulatore di Google Calendar per test deterministici e demo offline senza credenziali."""

    def __init__(self, simulated_busy_slots: Optional[List[Tuple[datetime, datetime]]] = None) -> None:
        # Se non passiamo impegni, ne creiamo uno automatico per OGGI alle 15:00 UTC
        if simulated_busy_slots is not None:
            self.busy_slots = simulated_busy_slots
        else:
            now_base = datetime.now(timezone.utc).replace(hour=14, minute=0, second=0, microsecond=0)
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
