from typing import Protocol, List, Optional, Dict, Any
from datetime import datetime

from .models import (
    SessionExtractionResult,
    CalendarPayload,
    CalendarEventItem,
    EmailPayload,
    Contact,
    KnowledgePayload,
    TaskPayload,
)


class LLMExtractorPort(Protocol):
    """Contratto per il motore AI: riceve l'audio e restituisce i dati strutturati."""
    async def extract_from_audio(
        self, audio_bytes: bytes, filename: str, anchor_utc: datetime, user_tz: str = "Europe/Rome"
    ) -> SessionExtractionResult:
        ...


class CalendarServicePort(Protocol):
    """Contratto per il calendario: controllo disponibilità, ricerca slot liberi, lettura agenda ed evento."""
    # ritorna True se sono occupato, False altrimenti
    async def check_is_busy(self, start_utc: datetime, end_utc: datetime) -> bool:
        ...
    
    # cerca i prossimi 3 slot liberi
    async def find_alternative_slots(
        self, requested_start_utc: datetime, duration_minutes: int, count: int = 3
    ) -> List[datetime]:
        ...

    # legge gli impegni esistenti in un intervallo di date (per visualizzare l'agenda)
    async def get_events(self, start_utc: datetime, end_utc: datetime) -> List[CalendarEventItem]:
        ...

    # crea l'evento con la chiave
    async def create_event(self, payload: CalendarPayload, idempotency_key: str) -> str:
        ...


class EmailServicePort(Protocol):
    """Contratto per il servizio email: creazione sicura di bozze (drafts)."""
    async def create_draft(self, payload: EmailPayload, idempotency_key: str) -> str:
        ...


class RepositoryPort(Protocol):
    """Contratto per il database locale (SQLite): lettura contatti e salvataggio delle azioni."""
    # recupera l'intera rubrica locale per permettere all'AI di confrontare i nomi detti a voce
    async def get_contacts(self) -> List[Contact]:
        ...
    
    # recupera la scheda completa di una specifica persona tramite il suo ID univoco
    async def get_contact_by_id(self, contact_id: str) -> Optional[Contact]:
        ...

    # salva nel DB l'intera sessione audio: riassunto, trascrizione e tutte le azioni proposte dall'AI
    async def save_session(self, session: SessionExtractionResult) -> None:
        ...

    # aggiorna lo stato (es. da PROPOSED a APPROVED) di un'azione, gestisce anche logica di idempotenza
    async def update_action_status(
        self, action_id: str, new_status: str, diff_payload: Optional[Dict[str, Any]] = None
    ) -> None:
        ...

    # controlla se un'azione è già stata eseguita in precedenza per impedire invii doppi accidentali
    async def is_idempotency_key_used(self, key: str) -> bool:
        ...

    async def add_contact(self, contact: Contact) -> None:
        ...

    async def delete_contact(self, contact_id: str) -> None:
        ...
    
class KnowledgeServicePort(Protocol):
    """Contratto per il Second Brain: salvataggio note riunione e aggiornamento profili persone."""

    # Salva una nota strutturata dell'incontro
    async def save_meeting_note(self, payload: KnowledgePayload) -> str:
        ...

    # Aggiorna la scheda della persona con le nuove preferenze emerse
    async def update_person_dossier(
        self, person_name: str, new_insights: List[str], meeting_ref: str
    ) -> str:
        ...

    async def append_tasks(self, payload: TaskPayload, meeting_ref: str) -> str:
        ...


