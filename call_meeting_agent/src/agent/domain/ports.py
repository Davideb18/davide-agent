from typing import Protocol, List, Optional, Dict, Any, Tuple
from datetime import datetime

from .models import (
    SessionExtractionResult,
    CalendarPayload,
    CalendarEventItem,
    EmailPayload,
    Contact,
    KnowledgePayload,
    TaskPayload,
    PersonHistorySummary,
    ProposedAction,
    UserProfile,
)


class LLMExtractorPort(Protocol):
    """Contratto per il motore AI: riceve audio o prompt testuale e restituisce i dati strutturati."""
    async def extract_from_audio(
        self,
        audio_bytes: bytes,
        filename: str,
        anchor_utc: datetime,
        user_tz: str = "Europe/Rome",
        user_profile_language: Optional[str] = None,
        user_name: Optional[str] = None,
        user_email: Optional[str] = None,
        known_contacts_summary: Optional[List[str]] = None,
    ) -> SessionExtractionResult:
        ...

    async def extract_from_text(
        self,
        text_prompt: str,
        anchor_utc: datetime,
        user_tz: str = "Europe/Rome",
        user_profile_language: Optional[str] = None,
        user_name: Optional[str] = None,
        user_email: Optional[str] = None,
        known_contacts_summary: Optional[List[str]] = None,
    ) -> SessionExtractionResult:
        ...

    async def regenerate_email_draft(
        self,
        original_payload: EmailPayload,
        new_slot_str: str,
        history: Optional[PersonHistorySummary] = None,
        user_tz: str = "Europe/Rome",
    ) -> EmailPayload:
        ...


class CalendarServicePort(Protocol):
    """Contratto per il calendario: controllo disponibilità, ricerca slot liberi, lettura agenda ed evento."""
    # ritorna True se sono occupato, False altrimenti
    async def check_is_busy(self, start_utc: datetime, end_utc: datetime) -> bool:
        ...
    
    # cerca i prossimi 3 slot liberi
    async def find_alternative_slots(
        self, requested_start_utc: datetime, duration_minutes: int, count: int = 3, user_tz: str = "Europe/Rome"
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


class RemindersServicePort(Protocol):
    """Contratto per l'esportazione verso Apple Reminders (Promemoria macOS)."""
    async def export_tasks(
        self, task_items: List[str], list_name: str = "Executive Tasks"
    ) -> Tuple[bool, str]:
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

    # salva o inserisce una singola azione proposta (es. generata on-demand dalla UI)
    async def save_proposed_action(self, action: ProposedAction) -> None:
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

    async def sync_contacts_from_vault(self, contacts: List[Contact]) -> int:
        """Upserta la lista di contatti da Vault nel DB SQLite. Ritorna il numero di contatti sincronizzati."""
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

    # Recupera lo storico degli incontri e preferenze note della persona
    async def get_person_history(self, person_name: str) -> Optional[PersonHistorySummary]:
        ...

    # Collega atomicamente un meeting al dossier della persona (backlink bidirezionale)
    async def link_meeting_to_person(
        self,
        person_name: str,
        meeting_title: str,
        meeting_rel_path: str,
        summary: str,
        insights: Optional[List[str]] = None,
    ) -> bool:
        ...

    # Registra un'interazione email (bozza o inviata) nel dossier della persona in PEOPLE/
    async def record_email_interaction(
        self,
        person_name: str,
        email_data: EmailPayload,
        status_label: str = "Bozza / Email registrata",
    ) -> bool:
        ...

    # Recupera l'eventuale preferenza linguistica dal profilo utente nel Second Brain
    async def get_user_profile_language(self) -> Optional[str]:
        ...

    # Legge il profilo completo dell'utente da IDENTITY/Profile.md (vault source of truth)
    async def get_user_profile(self) -> Optional[UserProfile]:
        ...

    # Scansiona PEOPLE/*.md e restituisce la lista di Contact dal vault
    async def get_all_contacts(self) -> List[Contact]:
        ...

    # Salva o aggiorna un contatto in PEOPLE/<Name>.md nel vault
    async def save_or_update_contact(self, contact: Contact) -> str:
        ...

    # Costruisce la topologia del Grafo di Conoscenza del Second Brain per la visualizzazione D3.js
    async def get_vault_graph_data(
        self, active_session: Optional[SessionExtractionResult] = None
    ) -> Dict[str, Any]:
        ...




