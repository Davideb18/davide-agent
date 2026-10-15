"""
test_agent_core.py — Test di regressione e integrazione dell'agente Aria.
Verifica assenza mock, validazione schema e gestione idempotente delle azioni.
"""
import os
import pytest
from datetime import datetime, timezone, timedelta

from src.agent.domain.models import (
    SessionExtractionResult,
    ProposedAction,
    CalendarPayload,
    EmailPayload,
    KnowledgePayload,
    TaskPayload,
    ExtractedEntity,
    CalendarEventItem,
)
from src.agent.domain.enums import ActionStatus, ActionType, IntentCategory
from src.agent.infrastructure.google.live_google import LocalCalendarService, LocalEmailService
from src.agent.infrastructure.knowledge.obsidian_adapter import ObsidianAdapter
from src.agent.infrastructure.database.sqlite_repo import SqliteRepository
from src.agent.application.resolve_conflict import evaluate_calendar_slot


def test_models_schema_and_defaults():
    task = TaskPayload(task_items=["Inviare report", "Chiamare fornitore"])
    assert task.assignee is None
    assert len(task.task_items) == 2

    session = SessionExtractionResult(
        session_id="ses_test_123",
        is_actionable=True,
        intent_category=IntentCategory.BUSINESS_MEETING,
        summary="Test riepilogo riunione",
        raw_transcript="Trascrizione di collaudo",
        entities=[],
        proposed_actions=[],
    )
    assert session.session_id == "ses_test_123"
    assert session.is_actionable is True


@pytest.mark.asyncio
async def test_local_calendar_service():
    cal = LocalCalendarService()
    now_utc = datetime.now(timezone.utc)
    
    # Inizialmente nessun impegno
    events = await cal.get_events(now_utc - timedelta(days=1), now_utc + timedelta(days=1))
    assert len(events) == 0
    assert await cal.check_is_busy(now_utc, now_utc + timedelta(hours=1)) is False

    # Creazione evento dinamico
    payload = CalendarPayload(
        title="Riunione Strategica",
        start_utc=now_utc,
        end_utc=now_utc + timedelta(hours=1),
        attendees=["client@domain.com"],
        description="Discussione roadmap",
    )
    ev_id = await cal.create_event(payload, idempotency_key="idemp_test_1")
    assert ev_id.startswith("evt_")

    # Ora lo slot risulta occupato
    assert await cal.check_is_busy(now_utc, now_utc + timedelta(hours=1)) is True
    events_after = await cal.get_events(now_utc - timedelta(days=1), now_utc + timedelta(days=1))
    assert len(events_after) == 1
    assert events_after[0].title == "Riunione Strategica"


@pytest.mark.asyncio
async def test_local_email_service():
    mail = LocalEmailService()
    payload = EmailPayload(
        recipient_email="partner@company.com",
        recipient_name="Mario Rossi",
        subject="Follow-up Incontro",
        body_markdown="Grazie per l'incontro di oggi.",
    )
    draft_id = await mail.create_draft(payload, idempotency_key="idemp_mail_1")
    assert draft_id.startswith("draft_")
    assert draft_id in mail.drafts


@pytest.mark.asyncio
async def test_conflict_evaluation_free_and_busy():
    cal = LocalCalendarService()
    start_utc = datetime(2026, 10, 16, 14, 0, tzinfo=timezone.utc)

    # 1. Slot libero
    is_busy, alts = await evaluate_calendar_slot(cal, start_utc, duration_minutes=30)
    assert is_busy is False
    assert alts == []

    # 2. Occupiamo lo slot
    await cal.create_event(
        CalendarPayload(
            title="Meeting Esistente",
            start_utc=start_utc,
            end_utc=start_utc + timedelta(minutes=30),
        ),
        idempotency_key="idemp_busy",
    )

    # 3. Verifica conflitto e alternative generate
    is_busy_now, alts_now = await evaluate_calendar_slot(cal, start_utc, duration_minutes=30, max_alternatives=2)
    assert is_busy_now is True
    assert len(alts_now) > 0
    assert start_utc not in alts_now


def test_obsidian_adapter_generic_vault(tmp_path):
    vault = ObsidianAdapter(vault_path=str(tmp_path))
    assert vault.vault_path == tmp_path.resolve()
    assert (tmp_path / "meetings").exists()
    assert (tmp_path / "contacts").exists()


def test_no_file_uploader_in_landing():
    with open("src/agent/presentation/landing.py", "r", encoding="utf-8") as f:
        code = f.read()
    assert "st.file_uploader" not in code
    assert "upload_file" not in code
    assert "osascript" not in code
    assert "Via Zocco" not in code
    assert "st.audio_input" in code


@pytest.mark.asyncio
async def test_commit_action_flow_and_idempotency(tmp_path):
    from src.agent.application.commit_action import CommitActionUseCase

    db_path = str(tmp_path / "test_commit.db")
    repo = SqliteRepository(db_path)
    await repo.init_db()

    cal = LocalCalendarService()
    mail = LocalEmailService()
    know = ObsidianAdapter(vault_path=str(tmp_path / "vault"))

    committer = CommitActionUseCase(
        calendar_service=cal,
        email_service=mail,
        knowledge_service=know,
        repository=repo,
    )

    now_utc = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)
    cal_action = ProposedAction(
        id="act_cal_1",
        session_id="ses_1",
        action_type=ActionType.CALENDAR_EVENT,
        status=ActionStatus.PROPOSED,
        calendar_data=CalendarPayload(
            title="Meeting Team",
            start_utc=now_utc,
            end_utc=now_utc + timedelta(minutes=45),
            attendees=["team@domain.com"],
            description="Allineamento settimanale",
        ),
        idempotency_key="idemp_cal_test_unique",
    )

    mail_action = ProposedAction(
        id="act_mail_1",
        session_id="ses_1",
        action_type=ActionType.EMAIL_DRAFT,
        status=ActionStatus.PROPOSED,
        email_data=EmailPayload(
            recipient_email="client@domain.com",
            recipient_name="Giuseppe Verdi",
            subject="Riepilogo Riunione",
            body_markdown="Ecco i punti concordati.",
        ),
        idempotency_key="idemp_mail_test_unique",
    )

    task_action = ProposedAction(
        id="act_task_1",
        session_id="ses_1",
        action_type=ActionType.TASK_TODO,
        status=ActionStatus.PROPOSED,
        task_data=TaskPayload(
            task_items=["Controllare metriche", "Aggiornare server"],
            target_project="Infrastruttura",
        ),
        idempotency_key="idemp_task_test_unique",
    )

    # Salvataggio sessione nel database prima dei commit utente
    session = SessionExtractionResult(
        session_id="ses_1",
        is_actionable=True,
        intent_category=IntentCategory.BUSINESS_MEETING,
        summary="Test Meeting",
        raw_transcript="Test Transcript",
        entities=[],
        proposed_actions=[cal_action, mail_action, task_action],
    )
    await repo.save_session(session)

    # 1. Primo commit: successo
    success, msg = await committer.execute_action(cal_action)
    assert success is True
    assert cal_action.status == ActionStatus.EXECUTED
    assert "creato con successo" in msg.lower()

    # 2. Secondo commit con la stessa chiave: blocco idempotenza
    success_dup, msg_dup = await committer.execute_action(cal_action)
    assert success_dup is False
    assert "bloccata duplicazione" in msg_dup.lower()

    # 3. Test Email Commit
    m_ok, m_msg = await committer.execute_action(mail_action)
    assert m_ok is True
    assert mail_action.status == ActionStatus.EXECUTED
    assert "bozza gmail generata con successo" in m_msg.lower()

    # 4. Test Task Commit
    t_ok, t_msg = await committer.execute_action(task_action)
    assert t_ok is True
    assert task_action.status == ActionStatus.EXECUTED


@pytest.mark.asyncio
async def test_dynamic_timezone_conflict_evaluation():
    from zoneinfo import ZoneInfo
    from src.agent.application.resolve_conflict import evaluate_calendar_slot

    cal = LocalCalendarService()
    # 14:00 UTC = 10:00 AM New York (EDT, UTC-4), in pieno orario lavorativo
    start_utc = datetime(2026, 10, 16, 14, 0, tzinfo=timezone.utc)

    # Occupiamo lo slot per forzare la ricerca di alternative
    await cal.create_event(
        CalendarPayload(
            title="Meeting Esistente NY",
            start_utc=start_utc,
            end_utc=start_utc + timedelta(minutes=30),
        ),
        idempotency_key="idemp_ny_1",
    )

    is_busy, alts = await evaluate_calendar_slot(
        cal,
        requested_start_utc=start_utc,
        duration_minutes=30,
        working_hour_start=9,
        working_hour_end=17,
        user_tz="America/New_York",
    )
    assert is_busy is True
    assert len(alts) > 0
    # Verifica che le alternative rispettino gli orari lavorativi di New York (9-17)
    ny_tz = ZoneInfo("America/New_York")
    for alt in alts:
        alt_ny = alt.astimezone(ny_tz)
        assert 9 <= alt_ny.hour < 17
        assert alt_ny.weekday() < 5


@pytest.mark.asyncio
async def test_quick_add_contact_repository(tmp_path):
    from src.agent.domain.models import Contact

    db_path = str(tmp_path / "test_contacts.db")
    repo = SqliteRepository(db_path)
    await repo.init_db()

    new_contact = Contact(
        id="cnt_sarah_connor",
        first_name="Sarah",
        last_name="Connor",
        email="sarah@skynet-defense.org",
        company="Cyberdyne Systems",
        role="Security Architect",
        aliases=["Sarah Connor", "Sarah"],
        tags=["defense", "security"],
        timezone="America/Los_Angeles",
    )

    # Salvataggio contatto rapido
    await repo.add_contact(new_contact)

    # Recupero e verifica
    saved = await repo.get_contact_by_id("cnt_sarah_connor")
    assert saved is not None
    assert saved.first_name == "Sarah"
    assert saved.company == "Cyberdyne Systems"
    assert saved.timezone == "America/Los_Angeles"

    # Verifica presenza nel Memory Graph
    all_contacts = await repo.get_contacts()
    assert any(c.id == "cnt_sarah_connor" for c in all_contacts)


def test_landing_hardening_and_audio_threshold():
    with open("src/agent/presentation/landing.py", "r", encoding="utf-8") as f:
        code = f.read()

    # Verifica gestione soglia audio > 25MB
    assert "25.0" in code
    assert "Registrazione voluminosa" in code
    # Verifica selettore fuso orario dinamico
    assert "COMMON_TIMEZONES" in code
    assert "landing_tz_picker" in code
    assert "user_tz=user_tz" in code



