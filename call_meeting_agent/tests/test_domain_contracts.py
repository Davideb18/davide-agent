"""
test_domain_contracts.py — Test di conformità per i contratti di Dominio Puro e Datetime Utils.
Verifica:
  - Robustezza di KnowledgePayload con e senza summary
  - Validazione e pulizia di EmailPayload (inclusi destinatari senza email)
  - Creazione di Contact senza email obbligatoria
  - Calcolo deterministico dell'Idempotency Key SHA-256
  - Localizzazione date e fusi orari thread-safe in datetime_utils
"""
import hashlib
from datetime import datetime, timezone

from src.agent.domain.models import (
    Contact,
    EmailPayload,
    KnowledgePayload,
    CalendarPayload,
    TaskPayload,
    ProposedAction,
    SessionExtractionResult,
)
from src.agent.domain.enums import ActionType, ActionStatus, IntentCategory
from src.agent.domain.datetime_utils import (
    format_localized_slot,
    format_full_localized_slot,
    resolve_timezone,
    is_english,
    get_weekday_label,
    get_month_label,
)


def test_knowledge_payload_summary_fallback():
    """Verifica che KnowledgePayload accetti summary esplicito o default a None senza errori."""
    kp_explicit = KnowledgePayload(
        title="Allineamento Trellis",
        target_person_name="Filippo Calzavara",
        summary="Accordo su pricing e integrazione PMS",
        backlinks=["Trellis", "PMS"],
        bullet_insights=["Quota 15%", "API Sync"],
        markdown_content="# Note",
    )
    assert kp_explicit.summary == "Accordo su pricing e integrazione PMS"
    assert kp_explicit.title == "Allineamento Trellis"

    kp_none = KnowledgePayload(
        title="Sync Rapido",
        target_person_name="Marco Rossi",
        backlinks=["Legal"],
        bullet_insights=["Revisione NDA"],
        markdown_content="# NDA",
    )
    assert kp_none.summary is None
    assert len(kp_none.bullet_insights) == 1


def test_email_payload_empty_recipient_cleaning():
    """Verifica che EmailPayload sanitizzi correttamente indirizzi vuoti, spaziati o validi."""
    # 1. Destinatario senza email (es. Mamma)
    mail_empty = EmailPayload(
        recipient_email="   ",
        recipient_name="Mamma",
        subject="Ti voglio bene",
        body_markdown="Un saluto affettuoso.",
    )
    assert mail_empty.recipient_email == ""
    assert mail_empty.recipient_name == "Mamma"
    assert mail_empty.body == "Un saluto affettuoso."

    # 2. Destinatario con spazi extra attorno all'email
    mail_spaced = EmailPayload(
        recipient_email="  FILIPPO@TRELLIS.SO  ",
        recipient_name="Filippo",
        subject="Follow-up Call",
        body_markdown="Ecco il resoconto.",
    )
    assert mail_spaced.recipient_email == "filippo@trellis.so"

    # 3. Verifica setter/getter proprietà 'body'
    mail_empty.body = "Nuovo corpo aggiornato."
    assert mail_empty.body_markdown == "Nuovo corpo aggiornato."


def test_contact_creation_without_email():
    """Verifica la creazione e serializzazione di Contact quando l'email non è nota."""
    contact_no_email = Contact(
        id="cnt_mamma_001",
        first_name="Mamma",
        last_name="",
        email="",
        company="N/D",
        role="Famiglia",
        aliases=["Mamma", "Madre"],
        tags=["famiglia"],
    )
    assert contact_no_email.id == "cnt_mamma_001"
    assert contact_no_email.email == ""
    assert contact_no_email.role == "Famiglia"

    # Serializzazione e deserializzazione Pydantic v2
    dumped = contact_no_email.model_dump()
    assert dumped["email"] == ""
    recreated = Contact.model_validate(dumped)
    assert recreated.first_name == "Mamma"


def test_idempotency_key_deterministic_hash():
    """Verifica l'invarianza deterministica dell'hash SHA-256 a parità di parametri."""
    session_id = "ses_20261017_001"
    action_type = ActionType.CALENDAR_EVENT.value
    action_id = "act_alpha_99"

    raw_token_1 = f"{session_id}_{action_type}_{action_id}"
    key_1 = f"idemp_{hashlib.sha256(raw_token_1.encode()).hexdigest()[:12]}"

    raw_token_2 = f"{session_id}_{action_type}_{action_id}"
    key_2 = f"idemp_{hashlib.sha256(raw_token_2.encode()).hexdigest()[:12]}"

    assert key_1 == key_2
    assert key_1.startswith("idemp_")
    assert len(key_1) == 18

    # Variazione deterministica al cambiare della sessione
    raw_token_diff = f"ses_OTHER_{action_type}_{action_id}"
    key_diff = f"idemp_{hashlib.sha256(raw_token_diff.encode()).hexdigest()[:12]}"
    assert key_1 != key_diff


def test_datetime_utils_localization_and_tz():
    """Verifica la formattazione bilingue (IT/EN) e la risoluzione fusi orari in datetime_utils."""
    # 14:00 UTC = 16:00 a Roma (CEST, UTC+2)
    dt_utc = datetime(2026, 10, 16, 14, 0, tzinfo=timezone.utc)

    slot_it = format_localized_slot(dt_utc, user_tz="Europe/Rome", lang="it")
    slot_en = format_localized_slot(dt_utc, user_tz="Europe/Rome", lang="en")
    full_it = format_full_localized_slot(dt_utc, user_tz="Europe/Rome", lang="it")

    assert "Ven 16 Ott ore 16:00" == slot_it
    assert "Fri 16 Oct at 16:00" == slot_en
    assert "Venerdì 16 Ottobre ore 16:00" == full_it

    # Verifica helper etichette
    assert get_weekday_label(4, full=True, lang="it") == "Venerdì"
    assert get_weekday_label(4, full=False, lang="en") == "Fri"
    assert get_month_label(10, full=True, lang="it") == "Ottobre"
    assert get_month_label(10, full=False, lang="en") == "Oct"

    # Verifica lingua
    assert is_english("en") is True
    assert is_english("English") is True
    assert is_english("it") is False

    # Risoluzione resiliente fuso orario
    assert resolve_timezone("Europe/Rome").key == "Europe/Rome"
    assert resolve_timezone("America/New_York").key == "America/New_York"
    assert resolve_timezone("Fuso/Inesistente").key == "Europe/Rome"
    assert resolve_timezone("").key == "Europe/Rome"
