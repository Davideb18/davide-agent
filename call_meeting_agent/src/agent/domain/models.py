import re
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional
from pydantic import BaseModel, Field, EmailStr, field_validator
from .enums import ActionStatus, ActionType, IntentCategory


class Contact(BaseModel):
    """Rappresenta una persona nel nostro Contact Memory Graph locale."""
    id: str
    first_name: str
    last_name: str = ""
    email: str = ""
    company: str = "N/D"
    role: str = "Persona"
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


class CalendarEventItem(BaseModel):
    """Rappresenta un impegno esistente in agenda (per visualizzazione nel calendario Apple)."""
    id: str
    title: str
    start_utc: datetime
    end_utc: datetime
    location: Optional[str] = None
    attendees: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    color_tag: str = "blue"  # "blue", "purple", "orange", "green", "red"
    is_conflict: bool = False


class CalendarPayload(BaseModel):
    """I dati esatti per creare o verificare un evento su Google Calendar."""
    title: str
    start_utc: datetime
    end_utc: datetime
    attendees: List[str] = Field(default_factory=list)
    description: str = ""
    location: Optional[str] = None
    alternative_slots_utc: List[datetime] = Field(default_factory=list) # Slot alternativi per il meeting 



class PersonInteractionRecord(BaseModel):
    """Singola interazione storica recuperata dal Second Brain."""
    meeting_date: str
    title: str
    summary: str
    link: str = ""


class PersonHistorySummary(BaseModel):
    """Riepilogo della memoria storica e delle preferenze del contatto (People Intelligence)."""
    contact_name: str
    last_meeting_date: Optional[str] = None
    key_preferences: List[str] = Field(default_factory=list)
    recent_interactions: List[PersonInteractionRecord] = Field(default_factory=list)


class EmailPayload(BaseModel):
    """I dati esatti per generare la bozza su Gmail."""
    recipient_email: str  # email del destinatario pulita
    recipient_name: str
    subject: str
    body_markdown: str  # il testo formattato in markdown
    cc: List[str] = Field(default_factory=list)
    linked_calendar_action_id: Optional[str] = None
    conflict_reason: Optional[str] = None
    suggested_alternatives: List[str] = Field(default_factory=list)

    @field_validator("recipient_email", mode="before")
    @classmethod
    def clean_recipient_email(cls, v: Any) -> str:
        if isinstance(v, str):
            return re.sub(r"\s+", "", v).lower()
        return str(v)

    def __init__(self, **data):
        if "body" in data and "body_markdown" not in data:
            data["body_markdown"] = data.pop("body")
        super().__init__(**data)

    @property
    def body(self) -> str:
        return self.body_markdown

    @body.setter
    def body(self, value: str) -> None:
        self.body_markdown = value


class KnowledgePayload(BaseModel):
    """I dati esatti per creare o aggiornare una nota nel Second Brain (Obsidian)."""
    title: str
    target_person_name: str
    summary: Optional[str] = None
    backlinks: List[str] = Field(default_factory=list)  # es: ["Filippo Calzavara", "Trellis", "PMS"]
    bullet_insights: List[str] = Field(default_factory=list)  # Punti chiave e preferenze estratte
    markdown_content: str  # Il testo formattato della nota



class TaskPayload(BaseModel):
    """I dati per creare o aggiornare una lista di task operativi (To-Do o Promemoria)."""
    task_items: List[str] = Field(default_factory=list)
    assignee: Optional[str] = None
    target_project: Optional[str] = None
    deadline_utc: Optional[datetime] = None

    def __init__(self, **data):
        if "items" in data and "task_items" not in data:
            data["task_items"] = data.pop("items")
        super().__init__(**data)

    @property
    def items(self) -> List[str]:
        return self.task_items


class ProposedAction(BaseModel):
    """Una singola azione proposta dal sistema con ciclo di vita e chiave di idempotenza."""
    id: str = Field(default_factory=lambda: f"act_{uuid.uuid4().hex[:10]}")
    session_id: str = ""
    action_type: ActionType
    status: ActionStatus = ActionStatus.PROPOSED
    calendar_data: Optional[CalendarPayload] = None
    email_data: Optional[EmailPayload] = None
    knowledge_data: Optional[KnowledgePayload] = None
    task_data: Optional[TaskPayload] = None
    idempotency_key: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionExtractionResult(BaseModel):
    """Il risultato complessivo dell'analisi dell'audio: trascrizione, entità e azioni proposte."""
    session_id: str
    is_actionable: bool = True
    intent_category: IntentCategory = IntentCategory.BUSINESS_MEETING
    summary: str 
    raw_transcript: str
    detected_language: str = Field(default="it", description="Lingua rilevata dall'audio/prompt o impostata dal profilo Second Brain (es. 'it', 'en', 'es', 'de').")
    entities: List[ExtractedEntity] = Field(default_factory=list)
    proposed_actions: List[ProposedAction] = Field(default_factory=list)
    person_history: Optional[PersonHistorySummary] = None
