"""
test_commit_and_idempotency.py — Test per la State Machine, Idempotenza a 2 fasi e Audit Trail.
Verifica:
  - Transizione PROPOSED -> EXECUTED con scrittura su Audit Log
  - Scudo anti-doppio clic con chiave di idempotenza SHA-256 (Replay Protection)
  - Esecuzione sicura di bozze email senza destinatario (recipient_email="")
  - Esecuzione sicura di note Second Brain prive di summary esplicito (Zero AttributeError)
  - Transizione a REJECTED con persistenza del motivo nell'audit log
"""
import pytest
from datetime import datetime, timezone, timedelta

from src.agent.domain.models import (
    ProposedAction,
    CalendarPayload,
    EmailPayload,
    KnowledgePayload,
    TaskPayload,
    SessionExtractionResult,
)
from src.agent.domain.enums import ActionType, ActionStatus, IntentCategory
from src.agent.application.commit_action import CommitActionUseCase
from src.agent.infrastructure.database.sqlite_repo import SqliteRepository


@pytest.mark.asyncio
async def test_first_commit_succeeds_and_marks_executed(
    test_committer: CommitActionUseCase, test_repo: SqliteRepository
):
    """Verifica che il primo commit di un'azione calendar transiti ad EXECUTED e aggiorni l'Audit Log."""
    now_utc = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)
    cal_action = ProposedAction(
        id="act_cal_test_101",
        session_id="ses_test_101",
        action_type=ActionType.CALENDAR_EVENT,
        status=ActionStatus.PROPOSED,
        calendar_data=CalendarPayload(
            title="Meeting Architettura",
            start_utc=now_utc,
            end_utc=now_utc + timedelta(minutes=45),
            attendees=["filippo@trellis.so"],
            description="Discussione su Ports & Adapters",
        ),
        idempotency_key="idemp_cal_unique_101",
    )

    # Pre-salvataggio sessione e azione nel repository SQLite isolato
    session = SessionExtractionResult(
        session_id="ses_test_101",
        is_actionable=True,
        intent_category=IntentCategory.BUSINESS_MEETING,
        summary="Test Meeting",
        raw_transcript="Test Transcript",
        entities=[],
        proposed_actions=[cal_action],
    )
    await test_repo.save_session(session)

    # 1. Esecuzione azione
    success, msg = await test_committer.execute_action(cal_action)
    assert success is True
    assert cal_action.status == ActionStatus.EXECUTED
    assert "creato con successo" in msg.lower()

    # 2. Verifica Audit Log
    logs = await test_repo.get_audit_logs(limit=5)
    assert len(logs) >= 1
    recent_log = next((l for l in logs if l["action_id"] == "act_cal_test_101"), None)
    assert recent_log is not None
    assert recent_log["new_status"] == ActionStatus.EXECUTED.value


@pytest.mark.asyncio
async def test_second_commit_same_idempotency_key_rejected(
    test_committer: CommitActionUseCase, test_repo: SqliteRepository
):
    """Verifica che un secondo commit con la stessa chiave di idempotenza venga bloccato all'istante."""
    now_utc = datetime(2026, 10, 16, 11, 0, tzinfo=timezone.utc)
    cal_action = ProposedAction(
        id="act_cal_dup_102",
        session_id="ses_test_102",
        action_type=ActionType.CALENDAR_EVENT,
        status=ActionStatus.PROPOSED,
        calendar_data=CalendarPayload(
            title="Meeting Duplicato",
            start_utc=now_utc,
            end_utc=now_utc + timedelta(minutes=30),
            attendees=[],
        ),
        idempotency_key="idemp_dup_guard_102",
    )

    session = SessionExtractionResult(
        session_id="ses_test_102",
        is_actionable=True,
        intent_category=IntentCategory.BUSINESS_MEETING,
        summary="Test Dup",
        raw_transcript="Test",
        entities=[],
        proposed_actions=[cal_action],
    )
    await test_repo.save_session(session)

    # Primo commit: successo
    ok1, _ = await test_committer.execute_action(cal_action)
    assert ok1 is True

    # Secondo commit identico (simulazione double-click utente): blocco idempotenza
    ok2, msg2 = await test_committer.execute_action(cal_action)
    assert ok2 is False
    assert "già eseguita in precedenza" in msg2.lower()
    assert "bloccata duplicazione" in msg2.lower()


@pytest.mark.asyncio
async def test_unaddressed_email_draft_execution(
    test_committer: CommitActionUseCase, test_repo: SqliteRepository
):
    """Verifica che una bozza email per un contatto senza email (es. Mamma) venga eseguita senza crash."""
    mail_action = ProposedAction(
        id="act_mail_mom_103",
        session_id="ses_test_103",
        action_type=ActionType.EMAIL_DRAFT,
        status=ActionStatus.PROPOSED,
        email_data=EmailPayload(
            recipient_email="",  # Nessun indirizzo email noto
            recipient_name="Mamma",
            subject="Thinking of you",
            body_markdown="Dear Mom, just wanted to check in.",
        ),
        idempotency_key="idemp_mail_mom_103",
    )

    session = SessionExtractionResult(
        session_id="ses_test_103",
        is_actionable=True,
        intent_category=IntentCategory.PERSONAL_MEMO,
        summary="Memo Mamma",
        raw_transcript="Trascrizione",
        entities=[],
        proposed_actions=[mail_action],
    )
    await test_repo.save_session(session)

    # Esecuzione commit bozza orfana
    ok, msg = await test_committer.execute_action(mail_action)
    assert ok is True
    assert mail_action.status == ActionStatus.EXECUTED
    assert "generata con successo" in msg.lower()


@pytest.mark.asyncio
async def test_knowledge_note_commit_without_summary_succeeds(
    test_committer: CommitActionUseCase, test_repo: SqliteRepository
):
    """Verifica end-to-end che KnowledgePayload con summary=None esegua il fallback sui bullet points senza crash."""
    know_action = ProposedAction(
        id="act_know_safe_104",
        session_id="ses_test_104",
        action_type=ActionType.KNOWLEDGE_NOTE,
        status=ActionStatus.PROPOSED,
        knowledge_data=KnowledgePayload(
            title="Architettura Microservizi",
            target_person_name="Filippo Calzavara",
            summary=None,  # Nessun summary esplicito fornito
            backlinks=["Architettura", "Trellis"],
            bullet_insights=["Disaccoppiamento Ports and Adapters", "Database Isolation"],
            markdown_content="# Appunti Architettura",
        ),
        idempotency_key="idemp_know_safe_104",
    )

    session = SessionExtractionResult(
        session_id="ses_test_104",
        is_actionable=True,
        intent_category=IntentCategory.BUSINESS_MEETING,
        summary="Test Knowledge",
        raw_transcript="Trascrizione",
        entities=[],
        proposed_actions=[know_action],
    )
    await test_repo.save_session(session)

    # Esecuzione: non deve MAI sollevare AttributeError
    ok, msg = await test_committer.execute_action(know_action)
    assert ok is True
    assert know_action.status == ActionStatus.EXECUTED
    assert "second brain creata" in msg.lower()


@pytest.mark.asyncio
async def test_reject_action_audit_trail(
    test_committer: CommitActionUseCase, test_repo: SqliteRepository
):
    """Verifica che il rifiuto esplicito di un'azione transiti a REJECTED con tracciamento audit."""
    now_utc = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    task_action = ProposedAction(
        id="act_task_rej_105",
        session_id="ses_test_105",
        action_type=ActionType.TASK_TODO,
        status=ActionStatus.PROPOSED,
        task_data=TaskPayload(task_items=["Task non rilevante"]),
        idempotency_key="idemp_task_rej_105",
    )

    session = SessionExtractionResult(
        session_id="ses_test_105",
        is_actionable=True,
        intent_category=IntentCategory.BUSINESS_MEETING,
        summary="Test Reject",
        raw_transcript="Trascrizione",
        entities=[],
        proposed_actions=[task_action],
    )
    await test_repo.save_session(session)

    # Rifiuto dell'azione
    await test_committer.reject_action(task_action, reason="Rifiutata manualmente dall'utente")
    assert task_action.status == ActionStatus.REJECTED

    # Verifica Audit Log
    logs = await test_repo.get_audit_logs(limit=5)
    rej_log = next((l for l in logs if l["action_id"] == "act_task_rej_105"), None)
    assert rej_log is not None
    assert rej_log["new_status"] == ActionStatus.REJECTED.value


@pytest.mark.asyncio
async def test_concurrent_double_click_race_condition(
    test_committer: CommitActionUseCase, test_repo: SqliteRepository
):
    """
    Verifica che 2 chiamate simultanee tramite asyncio.gather con la stessa chiave di idempotenza
    vengano serializzate dal lock di concorrenza: esattamente UNA ha successo (True) e l'altra
    viene respinta all'istante (False) senza corrompere lo stato né eseguire doppi side effect.
    """
    import asyncio
    now_utc = datetime(2026, 10, 16, 14, 0, tzinfo=timezone.utc)
    cal_action = ProposedAction(
        id="act_cal_concurrent_201",
        session_id="ses_test_concurrent_201",
        action_type=ActionType.CALENDAR_EVENT,
        status=ActionStatus.PROPOSED,
        calendar_data=CalendarPayload(
            title="Concorrenza Meeting",
            start_utc=now_utc,
            end_utc=now_utc + timedelta(minutes=30),
            attendees=["team@trellis.so"],
        ),
        idempotency_key="idemp_concurrent_guard_201",
    )

    session = SessionExtractionResult(
        session_id="ses_test_concurrent_201",
        is_actionable=True,
        intent_category=IntentCategory.BUSINESS_MEETING,
        summary="Test Race Condition",
        raw_transcript="Trascrizione Concorrenza",
        entities=[],
        proposed_actions=[cal_action],
    )
    await test_repo.save_session(session)

    # Invocazione simultanea tramite asyncio.gather
    res1, res2 = await asyncio.gather(
        test_committer.execute_action(cal_action),
        test_committer.execute_action(cal_action),
    )

    results = [res1[0], res2[0]]
    assert results.count(True) == 1, f"Atteso esattamente 1 successo, ottenuto: {results}"
    assert results.count(False) == 1, f"Atteso esattamente 1 rifiuto, ottenuto: {results}"
    assert cal_action.status == ActionStatus.EXECUTED

    # Il messaggio dell'azione rifiutata deve contenere il warning di duplicazione
    rejected_msg = res1[1] if res1[0] is False else res2[1]
    assert "già eseguita" in rejected_msg.lower() or "duplicazione" in rejected_msg.lower()


@pytest.mark.asyncio
async def test_adapter_failure_preserves_state_and_logs_error(
    test_committer: CommitActionUseCase, test_repo: SqliteRepository
):
    """
    Simula un errore dell'adapter esterno (es. runtime timeout o I/O exception).
    Verifica:
      - Eccezione catturata in modo pulito con ritorno (False, msg)
      - Transizione dell'azione a EXECUTION_FAILED con tracciamento nell'Audit Log
      - La chiave di idempotenza NON blocca un successivo retry legittimo una volta risolto l'errore
    """
    from unittest.mock import AsyncMock

    now_utc = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)
    fail_action = ProposedAction(
        id="act_cal_fail_202",
        session_id="ses_test_fail_202",
        action_type=ActionType.CALENDAR_EVENT,
        status=ActionStatus.PROPOSED,
        calendar_data=CalendarPayload(
            title="Meeting Flaky Network",
            start_utc=now_utc,
            end_utc=now_utc + timedelta(minutes=30),
            attendees=[],
        ),
        idempotency_key="idemp_retryable_guard_202",
    )

    session = SessionExtractionResult(
        session_id="ses_test_fail_202",
        is_actionable=True,
        intent_category=IntentCategory.BUSINESS_MEETING,
        summary="Test Adapter Failure",
        raw_transcript="Trascrizione Errore",
        entities=[],
        proposed_actions=[fail_action],
    )
    await test_repo.save_session(session)

    # 1. Simulazione fallimento adapter (es. 503 Service Unavailable)
    original_create = test_committer.calendar.create_event
    test_committer.calendar.create_event = AsyncMock(side_effect=RuntimeError("Google Calendar API 503: Service Unavailable"))

    ok, err_msg = await test_committer.execute_action(fail_action)
    assert ok is False
    assert fail_action.status == ActionStatus.EXECUTION_FAILED
    assert "503" in err_msg or "errore" in err_msg.lower()

    # Verifica Audit Log
    logs = await test_repo.get_audit_logs(limit=5)
    fail_log = next((l for l in logs if l["action_id"] == "act_cal_fail_202"), None)
    assert fail_log is not None
    assert fail_log["new_status"] == ActionStatus.EXECUTION_FAILED.value

    # 2. Ripristino adapter: verifica che il retry con la STESSA chiave sia consentito
    test_committer.calendar.create_event = original_create
    ok_retry, retry_msg = await test_committer.execute_action(fail_action)
    assert ok_retry is True
    assert fail_action.status == ActionStatus.EXECUTED
    assert "creato con successo" in retry_msg.lower()

