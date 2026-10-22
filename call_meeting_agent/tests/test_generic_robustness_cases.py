import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from src.agent.domain.models import (
    Contact,
    UserProfile,
    ExtractedEntity,
    ProposedAction,
    CalendarPayload,
    EmailPayload,
    TaskPayload,
    SessionExtractionResult,
)
from src.agent.domain.enums import ActionType, ActionStatus, IntentCategory
from src.agent.domain.datetime_utils import clean_spoken_email
from src.agent.application.process_session import ProcessSessionUseCase
from src.agent.infrastructure.google.live_google import LocalCalendarService, LocalEmailService
from src.agent.infrastructure.knowledge.obsidian_adapter import ObsidianAdapter


@pytest.mark.asyncio
async def test_compound_name_and_affiliation_matching(test_repo, tmp_path):
    """
    Test 1: Verifica disambiguazione generica per Nome + Azienda/Affiliazione.
    'Filippo Trellis' deve essere associato a Filippo Calzavara (Company: Trellis).
    """
    filippo = Contact(
        id="cnt_filippo_trellis",
        first_name="Filippo",
        last_name="Calzavara",
        email="filippo@trellis.so",
        company="Trellis",
        role="Acting CTO",
        aliases=["Filippo", "Fil", "CTO Trellis"],
        tags=["trellis", "engineering"],
    )
    await test_repo.add_contact(filippo)

    vault_dir = tmp_path / "vault_compound"
    vault_dir.mkdir(parents=True, exist_ok=True)
    obsidian = ObsidianAdapter(vault_path=str(vault_dir))

    orchestrator = ProcessSessionUseCase(
        llm_extractor=MagicMock(),
        calendar_service=LocalCalendarService(),
        email_service=LocalEmailService(),
        knowledge_service=obsidian,
        repository=test_repo,
    )

    contacts = await test_repo.get_contacts()
    entity = ExtractedEntity(
        raw_name="Filippo Trellis",
        context_clues=["Tokyo", "sync tecnico", "Trellis"],
    )
    res_ent = orchestrator._disambiguate_entity(entity, contacts)

    assert res_ent.matched_contact_id == "cnt_filippo_trellis"
    assert res_ent.email == "filippo@trellis.so"


@pytest.mark.asyncio
async def test_entity_deduplication_single_user_and_contacts(test_repo, tmp_path):
    """
    Test 2: Verifica che menzioni multiple dell'utente ('Me stesso', 'Davide Berno', 'Me')
    vengano consolidate in un'UNICA entità utente nella sessione.
    """
    user_contact = Contact(
        id="cnt_davide_main",
        first_name="Davide",
        last_name="Berno",
        email="bernodavide8@gmail.com",
        company="Trellis",
        aliases=["Davide", "Me stesso", "Io", "Davide Berno"],
        tags=["utente", "personale"],
    )
    filippo = Contact(
        id="cnt_filippo_main",
        first_name="Filippo",
        last_name="Calzavara",
        email="filippo@trellis.so",
        company="Trellis",
        tags=["trellis"],
    )
    await test_repo.add_contact(user_contact)
    await test_repo.add_contact(filippo)

    mock_session = SessionExtractionResult(
        session_id="ses_dedup_001",
        summary="Test deduplicazione entità",
        raw_transcript="call con filippo trellis e me stesso e bernodavide",
        is_actionable=True,
        primary_intent=IntentCategory.BUSINESS_MEETING,
        entities=[
            ExtractedEntity(raw_name="Me stesso"),
            ExtractedEntity(raw_name="Berno Davide"),
            ExtractedEntity(raw_name="Me"),
            ExtractedEntity(raw_name="Filippo Trellis"),
            ExtractedEntity(raw_name="Filippo"),
        ],
        proposed_actions=[],
    )

    mock_llm = MagicMock()
    mock_llm.extract_from_text = AsyncMock(return_value=mock_session)

    vault_dir = tmp_path / "vault_dedup"
    vault_dir.mkdir(parents=True, exist_ok=True)
    obsidian = ObsidianAdapter(vault_path=str(vault_dir))

    orchestrator = ProcessSessionUseCase(
        llm_extractor=mock_llm,
        calendar_service=LocalCalendarService(),
        email_service=LocalEmailService(),
        knowledge_service=obsidian,
        repository=test_repo,
    )

    res = await orchestrator.execute(text_prompt="call con filippo trellis e me stesso")

    # Ci deve essere esattamente 1 entità per Davide e 1 entità per Filippo
    user_entities = [e for e in res.entities if e.matched_contact_id == "cnt_davide_main"]
    filippo_entities = [e for e in res.entities if e.matched_contact_id == "cnt_filippo_main"]

    assert len(user_entities) == 1, f"Attesa 1 sola entità utente, trovate {len(user_entities)}"
    assert len(filippo_entities) == 1, f"Attesa 1 sola entità Filippo, trovate {len(filippo_entities)}"
    assert len(res.entities) == 2


@pytest.mark.asyncio
async def test_flexible_meeting_auto_shift_on_collision(test_repo, tmp_path):
    """
    Test 3: Quando un appuntamento è flessibile o serale ('intorno a martedì... flessibile')
    e collide con un impegno esistente, il sistema deve automaticamente spostarlo al primo
    slot libero raccomandato senza lasciare il conflitto bloccante.
    """
    cal_service = LocalCalendarService()
    # Inseriamo un impegno esistente (es. lezione universitaria 18:00 - 19:30)
    conflict_start = datetime(2026, 10, 27, 18, 0, tzinfo=timezone.utc)
    conflict_end = datetime(2026, 10, 27, 19, 30, tzinfo=timezone.utc)
    await cal_service.create_event(
        payload=CalendarPayload(
            title="Lezione Università",
            start_utc=conflict_start,
            end_utc=conflict_end,
        ),
        idempotency_key="idemp_uni_001",
    )

    # L'appuntamento proposto cade alle 18:30 (in pieno conflitto), ma è marcato flessibile
    meeting_payload = CalendarPayload(
        title="Call con Filippo Trellis",
        start_utc=datetime(2026, 10, 27, 18, 30, tzinfo=timezone.utc),
        end_utc=datetime(2026, 10, 27, 19, 0, tzinfo=timezone.utc),
        is_flexible=True,
        slot_reasoning="Flessibile la sera più tardi dopo le lezioni universitarie",
    )

    mock_session = SessionExtractionResult(
        session_id="ses_flex_cal_001",
        summary="Call flessibile serale",
        raw_transcript="call flessibile martedi sera con filippo dopo le lezioni",
        is_actionable=True,
        primary_intent=IntentCategory.BUSINESS_MEETING,
        entities=[],
        proposed_actions=[
            ProposedAction(
                id="act_cal_flex_001",
                session_id="ses_flex_cal_001",
                action_type=ActionType.CALENDAR_EVENT,
                calendar_data=meeting_payload,
            )
        ],
    )

    mock_llm = MagicMock()
    mock_llm.extract_from_text = AsyncMock(return_value=mock_session)

    vault_dir = tmp_path / "vault_cal_flex"
    vault_dir.mkdir(parents=True, exist_ok=True)
    obsidian = ObsidianAdapter(vault_path=str(vault_dir))

    orchestrator = ProcessSessionUseCase(
        llm_extractor=mock_llm,
        calendar_service=cal_service,
        email_service=LocalEmailService(),
        knowledge_service=obsidian,
        repository=test_repo,
    )

    res = await orchestrator.execute(text_prompt="call flessibile martedi sera con filippo")

    cal_act = res.proposed_actions[0]
    # L'azione deve essere stata automaticamente spostata allo slot libero (dopo le 19:30)
    assert cal_act.status == ActionStatus.PROPOSED
    assert cal_act.calendar_data.start_utc >= conflict_end
    assert "Orario individuato automaticamente" in (cal_act.calendar_data.slot_reasoning or "")


@pytest.mark.asyncio
async def test_spoken_email_and_zero_leakage_to_third_parties(test_repo, tmp_path):
    """
    Test 4: Verifica che la sintassi vocale italiana 'Giorgio.chiocciola@gmail.com'
    venga pulita in 'giorgio@gmail.com' e che l'email personale di Davide non venga
    MAI leccata come destinatario di Giorgio.
    """
    user_contact = Contact(
        id="cnt_davide_real",
        first_name="Davide",
        last_name="Berno",
        email="bernodavide8@gmail.com",
        tags=["utente", "personale"],
    )
    await test_repo.add_contact(user_contact)

    # 1. Test unitario funzione spoken email
    assert clean_spoken_email("Giorgio.chiocciola@gmail.com") == "giorgio@gmail.com"
    assert clean_spoken_email("mario punto rossi chiocciola hotmail punto com.") == "mario.rossi@hotmail.com"

    # 2. Test pipeline di protezione zero-leakage
    mock_session = SessionExtractionResult(
        session_id="ses_mail_leak_001",
        summary="Email di ringraziamento a Giorgio",
        raw_transcript="manda un'email a giorgio chiocciola gmail com per ringraziarlo",
        is_actionable=True,
        primary_intent=IntentCategory.FOLLOW_UP,
        entities=[ExtractedEntity(raw_name="Giorgio")],
        proposed_actions=[
            ProposedAction(
                id="act_mail_giorgio_001",
                session_id="ses_mail_leak_001",
                action_type=ActionType.EMAIL_DRAFT,
                email_data=EmailPayload(
                    recipient_name="Giorgio",
                    recipient_email="Giorgio.chiocciola@gmail.com",
                    subject="Grazie per il prestito",
                    body_markdown="Ciao Giorgio, ti ringrazio molto per i soldi che mi hai prestato.",
                ),
            )
        ],
    )

    mock_llm = MagicMock()
    mock_llm.extract_from_text = AsyncMock(return_value=mock_session)

    vault_dir = tmp_path / "vault_leak"
    vault_dir.mkdir(parents=True, exist_ok=True)
    obsidian = ObsidianAdapter(vault_path=str(vault_dir))

    orchestrator = ProcessSessionUseCase(
        llm_extractor=mock_llm,
        calendar_service=LocalCalendarService(),
        email_service=LocalEmailService(),
        knowledge_service=obsidian,
        repository=test_repo,
    )

    res = await orchestrator.execute(text_prompt="manda un'email a giorgio per ringraziarlo")

    mail_act = res.proposed_actions[0]
    assert mail_act.email_data.recipient_name == "Giorgio"
    assert mail_act.email_data.recipient_email == "giorgio@gmail.com"
    assert mail_act.email_data.recipient_email != "bernodavide8@gmail.com"
