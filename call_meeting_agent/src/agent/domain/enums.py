from enum import Enum

class ActionStatus(str, Enum):
    """Rappresenta il ciclo di vita e lo stato esatto di ogni singola azione proposta dall'agente."""
    PROPOSED = "PROPOSED"
    CONFLICT_DETECTED = "CONFLICT_DETECTED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    REJECTED = "REJECTED"
    DISCARDED = "DISCARDED"


class ActionType(str, Enum):
    """Identifica il tipo di azione da compiere verso l'esterno."""
    CALENDAR_EVENT = "CALENDAR_EVENT"
    EMAIL_DRAFT = "EMAIL_DRAFT"


class IntentCategory(str, Enum):
    """Categorizza l'intento principale estratto dall'audio."""
    BUSINESS_MEETING = "BUSINESS_MEETING"
    FOLLOW_UP = "FOLLOW_UP"
    CHITCHAT_NOOP = "CHITCHAT_NOOP"
