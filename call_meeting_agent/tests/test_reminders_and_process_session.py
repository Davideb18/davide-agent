"""
test_reminders_and_process_session.py — Test di regressione per:
  - Esportazione verso Apple Reminders e gestione TASK_EXPORT_REMINDERS
  - Conversione chore e faccende in TASK_TODO
  - Sincronizzazione automatica in background del Second Brain in ProcessSessionUseCase
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from src.agent.domain.models import (
    ProposedAction,
    CalendarPayload,
    EmailPayload,
    KnowledgePayload,
    TaskPayload,
    SessionExtractionResult,
    ExtractedEntity,
    Contact,
)
from src.agent.domain.enums import ActionType, ActionStatus, IntentCategory
from src.agent.application.commit_action import CommitActionUseCase
from src.agent.application.process_session import ProcessSessionUseCase
from src.agent.infrastructure.apple.reminders_adapter import AppleRemindersAdapter


@pytest.mark.asyncio
async def test_reminders_empty_items():
    """Verifica che AppleRemindersAdapter gestisca compiti vuoti restituendo False senza errori."""
    adapter = AppleRemindersAdapter()
    ok, msg = await adapter.export_tasks([])
    assert ok is False
    assert "nessun compito" in msg.lower()


@pytest.mark.asyncio
async def test_reminders_action_commit_lifecycle(test_repo, tmp_path):
    """Verifica il ciclo di vita completo di TASK_EXPORT_REMINDERS nel Committer."""
    mock_reminders = MagicMock()
    mock_reminders.export_tasks = AsyncMock(return_value=(True, "3 promemoria esportati"))

    from src.agent.infrastructure.knowledge.obsidian_adapter import ObsidianAdapter
    from src.agent.infrastructure.google.live_google import LocalCalendarService, LocalEmailService

    committer = CommitActionUseCase(
        calendar_service=LocalCalendarService(),
        email_service=LocalEmailService(),
        knowledge_service=ObsidianAdapter(vault_path=str(tmp_path / "vault")),
        repository=test_repo,
        reminders_service=mock_reminders,
    )

    action = ProposedAction(
        id="act_rem_test_001",
        session_id="ses_rem_001",
        action_type=ActionType.TASK_EXPORT_REMINDERS,
        status=ActionStatus.PROPOSED,
        task_data=TaskPayload(task_items=["Comprare il pane", "Chiamare commercialista"]),
        idempotency_key="idemp_rem_test_001",
    )

    ok, msg = await committer.execute_action(action)
    assert ok is True
    assert action.status == ActionStatus.EXECUTED
    assert "3 promemoria esportati" in msg

    # Replay protection: seconda esecuzione bloccata
    ok2, msg2 = await committer.execute_action(action)
    assert ok2 is False
    assert "già eseguita" in msg2.lower()


@pytest.mark.asyncio
async def test_chore_detection_and_conversion_in_process_session(test_repo, tmp_path):
    """Verifica che le faccende (piante, spesa, spazzatura) vengano convertite in TASK_TODO senza UnboundLocalError."""
    from src.agent.infrastructure.knowledge.obsidian_adapter import ObsidianAdapter
    from src.agent.infrastructure.google.live_google import LocalCalendarService, LocalEmailService

    vault_dir = tmp_path / "vault"
    obsidian = ObsidianAdapter(vault_path=str(vault_dir))

    now_utc = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)
    mock_session = SessionExtractionResult(
        session_id="ses_chore_001",
        is_actionable=True,
        intent_category=IntentCategory.PERSONAL_MEMO,
        summary="Test faccende",
        raw_transcript="Devo ricordarmi di dare da bere alle piante domani e fare la spesa",
        entities=[],
        proposed_actions=[
            ProposedAction(
                id="act_cal_chore",
                session_id="ses_chore_001",
                action_type=ActionType.CALENDAR_EVENT,
                calendar_data=CalendarPayload(
                    title="Dare da bere alle piante",
                    start_utc=now_utc + timedelta(days=1),
                    end_utc=now_utc + timedelta(days=1, minutes=30),
                    description="Faccenda domestica",
                ),
            )
        ],
    )

    mock_llm = MagicMock()
    mock_llm.extract_from_text = AsyncMock(return_value=mock_session)

    orchestrator = ProcessSessionUseCase(
        llm_extractor=mock_llm,
        calendar_service=LocalCalendarService(),
        email_service=LocalEmailService(),
        knowledge_service=obsidian,
        repository=test_repo,
    )

    result = await orchestrator.execute(text_prompt="Test chore prompt", anchor_utc=now_utc)
    # L'azione CALENDAR_EVENT con titolo 'Dare da bere alle piante' deve essere convertita in TASK_TODO
    assert len(result.proposed_actions) == 1
    act = result.proposed_actions[0]
    assert act.action_type == ActionType.TASK_TODO
    assert act.task_data is not None
    assert "Dare da bere alle piante" in act.task_data.task_items
    assert act.calendar_data is None


@pytest.mark.asyncio
async def test_background_second_brain_auto_sync(test_repo, tmp_path):
    """Verifica che il Second Brain venga sincronizzato silenziosamente e automaticamente in background."""
    from src.agent.infrastructure.knowledge.obsidian_adapter import ObsidianAdapter
    from src.agent.infrastructure.google.live_google import LocalCalendarService, LocalEmailService

    vault_dir = tmp_path / "vault"
    obsidian = ObsidianAdapter(vault_path=str(vault_dir))

    now_utc = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)
    mock_session = SessionExtractionResult(
        session_id="ses_bg_sync_001",
        is_actionable=True,
        intent_category=IntentCategory.BUSINESS_MEETING,
        summary="Riunione Trellis con Filippo",
        raw_transcript="Riunione tecnica con Filippo per architettura Trellis",
        entities=[
            ExtractedEntity(raw_name="Filippo", context_clues=["Trellis", "CTO"])
        ],
        proposed_actions=[
            ProposedAction(
                id="act_know_001",
                session_id="ses_bg_sync_001",
                action_type=ActionType.KNOWLEDGE_NOTE,
                knowledge_data=KnowledgePayload(
                    title="Allineamento Trellis",
                    target_person_name="Filippo",
                    summary="Accordi su API",
                    backlinks=["Trellis", "Filippo"],
                    bullet_insights=["API schema validato"],
                    markdown_content="Note complete del meeting",
                ),
            ),
            ProposedAction(
                id="act_task_001",
                session_id="ses_bg_sync_001",
                action_type=ActionType.TASK_TODO,
                task_data=TaskPayload(
                    task_items=["Aggiornare schema database", "Verifica endpoint"],
                    target_project="Trellis",
                ),
            ),
        ],
    )

    mock_llm = MagicMock()
    mock_llm.extract_from_text = AsyncMock(return_value=mock_session)

    orchestrator = ProcessSessionUseCase(
        llm_extractor=mock_llm,
        calendar_service=LocalCalendarService(),
        email_service=LocalEmailService(),
        knowledge_service=obsidian,
        repository=test_repo,
    )

    result = await orchestrator.execute(text_prompt="Riunione con Filippo", anchor_utc=now_utc)
    assert result.session_id == "ses_bg_sync_001"

    # Verifica che la nota sia stata fisicamente creata nella cartella meetings/
    created_notes = list(obsidian.meetings_dir.glob("*.md"))
    assert len(created_notes) >= 1

    # Verifica che il dossier della persona esista in contacts/ o PEOPLE/
    person_file = obsidian._find_person_file("Filippo")
    assert person_file is not None
    assert person_file.exists()

    # Verifica che i task siano stati aggiunti in Tasks.md
    tasks_file = vault_dir / "Tasks.md"
    assert tasks_file.exists()
    content = tasks_file.read_text(encoding="utf-8")
    assert "Aggiornare schema database" in content
