from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, EmailStr
from .enums import ActionStatus, ActionType, IntentCategory


class Contact(BaseModel):
    """Rappresenta una persona nel nostro Contact Memory Graph locale."""
    id: str
    first_name: str
    last_name: str
    email: EmailStr
    company: str
    role: str
    aliases: List[str] = Field(default_factory=list) # soprannomi
    tags: List[str] = Field(default_factory=list) # tag tematici (per capire di cosa si occupa)
    timezone: str = "Europe/Rome"


class ExtractedEntity(BaseModel):
    """Un'entità (persona) individuata nell'audio prima o durante la disambiguazione."""
    raw_name: str
    context_clues: List[str] = Field(default_factory=list) # indizi di contesto (per capire di cosa si occupa)
    matched_contact_id: Optional[str] = None
    is_ambiguous: bool = False # se è ambiguo, vuol dire che ci sono più contatti con lo stesso nome
    candidate_ids: List[str] = Field(default_factory=list) # possibili candidati tra i quali scegliere in caso di ambiguità


class CalendarPayload(BaseModel):
    """I dati esatti per creare o verificare un evento su Google Calendar."""
    title: str
    start_utc: datetime
    end_utc: datetime
    attendees: List[str] = Field(default_factory=list)
    description: str
    location: Optional[str] = "Google Meet"
    alternative_slots_utc: List[datetime] = Field(default_factory=list) # Slot alternativi per il meeting 


class EmailPayload(BaseModel):
    """I dati esatti per generare la bozza su Gmail."""
    recipient_email: EmailStr # email del destinatario
    recipient_name: str
    subject: str
    body_markdown: str # il testo formattato in markdown
    cc: List[str] = Field(default_factory=list)


class ProposedAction(BaseModel):
    """Una singola azione proposta dal sistema (Calendar o Gmail) con ciclo di vita e chiave di idempotenza."""
    id: str
    session_id: str
    action_type: ActionType # tipo di azione: CALENDAR_EVENT o EMAIL_DRAFT
    status: ActionStatus # stato dell'azione: PROPOSED, CONFLICT_DETECTED, APPROVED, EXECUTED, EXECUTION_FAILED, REJECTED, DISCARDED
    calendar_data: Optional[CalendarPayload] = None
    email_data: Optional[EmailPayload] = None
    idempotency_key: str # chiave unica per ogni azione
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionExtractionResult(BaseModel):
    """Il risultato complessivo dell'analisi dell'audio: trascrizione, entità e azioni proposte."""
    session_id: str
    is_actionable: bool = True # indica se c'è un output sfruttabile (vero) o se è solo rumore/saluti (falso)
    intent_category: IntentCategory = IntentCategory.BUSINESS_MEETING
    summary: str 
    raw_transcript: str
    entities: List[ExtractedEntity] = Field(default_factory=list)
    proposed_actions: List[ProposedAction] = Field(default_factory=list)
