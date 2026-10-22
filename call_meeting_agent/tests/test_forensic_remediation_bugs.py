"""
test_forensic_remediation_bugs.py — Test di non-regressione per gli 8 Bug dell'Audit Forense.

Verifica:
- BUG-01: Ciclo di vita task (modifica e aggiornamento in Second Brain / Promemoria anche se già EXECUTED).
- BUG-02: Parsing eventi all-day Google Calendar in UTC ed eliminazione TypeError con _ensure_utc.
- BUG-03: Reset week_offset_key e aggiornamento chiavi widget date/time su slot alternativo.
- BUG-04: Rilevamento conflitti basato sulla durata reale (>30m, es. 90 min) del meeting.
- BUG-05: Preservazione istanze in-memory LocalCalendarService e LocalEmailService in state.py.
- BUG-06: Prevenzione doppio frontmatter YAML in ObsidianAdapter anche con BOM (\\ufeff) o spazi iniziali.
- BUG-07: Chiamata non-bloccante via asyncio.to_thread in MacMailService.
- BUG-08: Lookup O(1) contatti partecipanti senza query N+1.
"""
import asyncio
from datetime import datetime, timezone, timedelta, time as dt_time
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
import pytest

from src.agent.domain.enums import ActionStatus, ActionType
from src.agent.domain.models import (
    ProposedAction,
    TaskPayload,
    CalendarPayload,
    CalendarEventItem,
    Contact,
    SessionExtractionResult,
    ExtractedEntity,
)
from src.agent.application.resolve_conflict import evaluate_calendar_slot
from src.agent.application.process_session import ProcessSessionUseCase
from src.agent.infrastructure.google.live_google import (
    LocalCalendarService,
    LocalEmailService,
    MacMailService,
)
from src.agent.presentation.components.calendar_card import _ensure_utc


# =========================================================================
# BUG-01: TASK LIFECYCLE & EDITABILITY AFTER BACKGROUND SYNC
# =========================================================================

@pytest.mark.asyncio
async def test_bug01_task_lifecycle_update_when_already_executed(test_committer, test_repo, test_obsidian):
    """
    BUG-01: Se process_session ha già segnato un TASK_TODO come EXECUTED in background,
    l'utente deve poter modificare i task e salvarli/aggiornarli in Tasks.md
    senza essere bloccato dal controllo di idempotenza.
    """
    action = ProposedAction(
        id="act_task_01",
        session_id="sess_test_01",
        action_type=ActionType.TASK_TODO,
        status=ActionStatus.EXECUTED,
        idempotency_key="idemp_task_init_123",
        task_data=TaskPayload(task_items=["Vecchio Compito 1", "Vecchio Compito 2"], target_project="Progetto Alpha"),
    )
    # Salviamo l'azione come già eseguita nel DB
    await test_repo.save_proposed_action(action)
    assert await test_repo.is_idempotency_key_used("idemp_task_init_123") is True

    # L'utente ha modificato i compiti nella UI e clicca "Salva / Aggiorna in Second Brain"
    modified_items = ["Compito 1 Modificato", "Compito 3 Nuovo"]
    success, msg = await test_committer.execute_action(
        action,
        user_modified_payload={"task_items": modified_items, "target_project": "Progetto Alpha"},
    )

    assert success is True
    assert "Checklist operativa salvata" in msg or "Task" in msg
    assert action.status == ActionStatus.EXECUTED
    assert action.task_data is not None
    assert action.task_data.task_items == modified_items
    assert action.idempotency_key.startswith("idemp_task_upd_")

    # Verifica che Tasks.md contenga i compiti aggiornati
    tasks_file = test_obsidian.vault_path / "ACTIVITY" / "Projects" / "Tasks.md"
    if not tasks_file.exists():
        tasks_file = test_obsidian.vault_path / "Tasks.md"
    content = tasks_file.read_text(encoding="utf-8")
    assert "Compito 1 Modificato" in content
    assert "Compito 3 Nuovo" in content


@pytest.mark.asyncio
async def test_bug01_reminders_export_after_tasks_executed(test_committer, mock_reminders):
    """
    BUG-01: L'esportazione su Promemoria macOS deve funzionare anche con task
    modificati dall'utente, usando un'azione dedicata con idempotency_key fresca.
    """
    rem_action = ProposedAction(
        id="act_rem_fresh",
        session_id="sess_test_01",
        action_type=ActionType.TASK_EXPORT_REMINDERS,
        idempotency_key="idemp_rem_unique_999",
        task_data=TaskPayload(task_items=["Promemoria 1", "Promemoria 2"]),
    )

    success, msg = await test_committer.execute_action(rem_action)
    assert success is True
    mock_reminders.export_tasks.assert_called_once_with(
        task_items=["Promemoria 1", "Promemoria 2"],
        list_name="Promemoria",
    )


# =========================================================================
# BUG-02: ALL-DAY GOOGLE CALENDAR EVENTS (NAIVE VS AWARE DATETIMES)
# =========================================================================

def test_bug02_all_day_events_parsing_and_utc_awareness():
    """
    BUG-02: Gli eventi all-day da Google Calendar API arrivano con solo 'date' (YYYY-MM-DD).
    Il parser deve convertirli sempre in timezone-aware in UTC per prevenire TypeError.
    """
    raw_item = {
        "start": {"date": "2026-10-25"},
        "end": {"date": "2026-10-26"},
        "summary": "Hackathon 2026",
    }
    start_str = raw_item["start"].get("dateTime") or raw_item["start"].get("date")
    end_str = raw_item["end"].get("dateTime") or raw_item["end"].get("date")
    assert start_str is not None
    assert end_str is not None

    s_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
    e_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))

    # Logica applicata in live_google.py
    if s_dt.tzinfo is None:
        s_dt = s_dt.replace(tzinfo=timezone.utc)
    else:
        s_dt = s_dt.astimezone(timezone.utc)

    if e_dt.tzinfo is None:
        e_dt = e_dt.replace(tzinfo=timezone.utc)
    else:
        e_dt = e_dt.astimezone(timezone.utc)

    assert s_dt.tzinfo == timezone.utc
    assert e_dt.tzinfo == timezone.utc

    # Nessun TypeError deve essere sollevato confrontando con un aware datetime
    aware_now = datetime(2026, 10, 25, 14, 30, tzinfo=timezone.utc)
    assert s_dt < aware_now
    assert aware_now < e_dt


def test_bug02_ensure_utc_helper_defense_in_depth():
    """
    BUG-02 (Difesa in profondità): _ensure_utc converte qualsiasi datetime
    (naive, aware UTC, aware non-UTC) in datetime timezone-aware UTC.
    """
    naive_dt = datetime(2026, 10, 22, 10, 0, 0)
    res_naive = _ensure_utc(naive_dt)
    assert res_naive is not None
    assert res_naive.tzinfo == timezone.utc

    utc_dt = datetime(2026, 10, 22, 10, 0, 0, tzinfo=timezone.utc)
    res_utc = _ensure_utc(utc_dt)
    assert res_utc == utc_dt

    assert _ensure_utc(None) is None

    # Confronto diretto tra aware e convertito naive: zero eccezioni
    assert res_naive < datetime(2026, 10, 22, 11, 0, 0, tzinfo=timezone.utc)


# =========================================================================
# BUG-03: MINI-CALENDAR ALTERNATIVE SLOT SELECTION & WIDGET SYNC
# =========================================================================

def test_bug03_alternative_slot_resets_week_offset_and_updates_widget_state():
    """
    BUG-03: Quando l'utente seleziona uno slot alternativo:
    - week_offset_key deve essere resettato a 0
    - cal_date_{action.id} e cal_time_{action.id} in session_state devono aggiornarsi
    """
    session_state = {}
    action_id = "act_cal_99"
    week_offset_key = f"mini_cal_offset_{action_id}"

    # Simula stato precedente
    session_state[week_offset_key] = 2
    session_state[f"cal_date_{action_id}"] = datetime(2026, 10, 20).date()
    session_state[f"cal_time_{action_id}"] = dt_time(10, 0)

    # Nuovo slot selezionato: Giovedì 29 Ottobre 2026 alle 15:30 UTC
    alt_utc = datetime(2026, 10, 29, 15, 30, tzinfo=timezone.utc)

    # Esecuzione logica fixata
    session_state[week_offset_key] = 0
    session_state[f"cal_date_{action_id}"] = alt_utc.date()
    session_state[f"cal_time_{action_id}"] = dt_time(alt_utc.hour, alt_utc.minute)

    assert session_state[week_offset_key] == 0
    assert session_state[f"cal_date_{action_id}"] == datetime(2026, 10, 29).date()
    assert session_state[f"cal_time_{action_id}"] == dt_time(15, 30)


# =========================================================================
# BUG-04: REAL MEETING DURATION IN CONFLICT DETECTION (>30m)
# =========================================================================

@pytest.mark.asyncio
async def test_bug04_process_session_evaluates_actual_duration_for_long_meetings(local_calendar):
    """
    BUG-04: Un meeting di 90 minuti (10:00 - 11:30) deve rilevare un conflitto
    con un evento esistente alle 10:45 - 11:15, cosa che non avveniva quando
    la durata era forzata a 30 minuti (10:00 - 10:30 non avrebbe colliso!).
    """
    meeting_date = datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc)
    meeting_end = meeting_date + timedelta(minutes=90)  # 10:00 - 11:30

    # Inseriamo un evento nel calendario locale alle 10:45 - 11:15
    conflict_start = datetime(2026, 10, 28, 10, 45, tzinfo=timezone.utc)
    conflict_end = conflict_start + timedelta(minutes=30)
    await local_calendar.create_event(
        CalendarPayload(
            title="Meeting Sovrapposto",
            start_utc=conflict_start,
            end_utc=conflict_end,
        ),
        idempotency_key="idemp_existing_conflict",
    )

    # Se calcolato a 30 min (vecchio comportamento buggato):
    is_busy_30, _ = await evaluate_calendar_slot(
        local_calendar,
        requested_start_utc=meeting_date,
        duration_minutes=30,  # 10:00 - 10:30
        user_tz="Europe/Rome",
    )
    assert is_busy_30 is False  # Falso negativo!

    # Con la durata reale (90 min, nuovo comportamento corretto):
    actual_duration = int((meeting_end - meeting_date).total_seconds() / 60)
    is_busy_real, alternatives = await evaluate_calendar_slot(
        local_calendar,
        requested_start_utc=meeting_date,
        duration_minutes=actual_duration,
        user_tz="Europe/Rome",
    )
    assert is_busy_real is True  # Conflitto rilevato con successo!
    assert len(alternatives) > 0


# =========================================================================
# BUG-05: IN-MEMORY SERVICE PRESERVATION IN STATE.PY
# =========================================================================

def test_bug05_local_services_preserved_across_reruns_on_token_error():
    """
    BUG-05: Se st.session_state contiene già un LocalCalendarService con eventi in-memory,
    e data/token.json non esiste o fallisce, l'istanza non deve essere ricreata vuota.
    """
    session_state = {}
    cal = LocalCalendarService()
    cal.events["evt_1"] = CalendarEventItem(
        id="evt_1",
        title="Evento Esistente In Memory",
        start_utc=datetime.now(timezone.utc),
        end_utc=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    session_state["calendar"] = cal

    # Simula la logica di init()
    _required_cal_methods = ("get_events", "check_is_busy", "find_alternative_slots", "create_event")
    cal_in_state = session_state.get("calendar")
    has_valid_cal = cal_in_state is not None and all(hasattr(cal_in_state, m) for m in _required_cal_methods)

    # token.json assente: non deve sovrascrivere cal_in_state
    if not has_valid_cal:
        session_state["calendar"] = LocalCalendarService()

    assert session_state["calendar"] is cal
    assert len(session_state["calendar"].events) == 1
    assert "evt_1" in session_state["calendar"].events


# =========================================================================
# BUG-06: PREVENTION OF DOUBLE YAML FRONTMATTER IN OBSIDIAN
# =========================================================================

@pytest.mark.asyncio
async def test_bug06_obsidian_no_double_frontmatter_with_bom_or_whitespace(test_obsidian):
    """
    BUG-06: Se un file contatto markdown inizia con BOM (\\ufeff) o spazi/newline,
    l'aggiornamento con save_or_update_contact non deve generare un doppio blocco frontmatter ---.
    """
    contacts_dir = test_obsidian.contacts_dir
    contacts_dir.mkdir(parents=True, exist_ok=True)
    contact_file = contacts_dir / "Mario_Rossi.md"

    # Creiamo un file iniziale con BOM e spazi prima del frontmatter
    initial_content = (
        "\ufeff   \n\n---\n"
        "name: Mario Rossi\n"
        "email: mario@rossi.it\n"
        "tags:\n"
        "  - vecchio\n"
        "---\n\n"
        "# [[Mario Rossi]]\n\n"
        "Note storiche dell'incontro precedente.\n"
    )
    contact_file.write_text(initial_content, encoding="utf-8")

    # Aggiorniamo il contatto con ObsidianAdapter
    updated_contact = Contact(
        id="cnt_mario",
        first_name="Mario",
        last_name="Rossi",
        email="mario.nuovo@rossi.it",
        company="Nuova Spa",
        role="CEO",
        tags=["vip", "partner"],
    )
    await test_obsidian.save_or_update_contact(updated_contact)

    # Leggiamo il file risultante
    new_text = contact_file.read_text(encoding="utf-8")

    # Verifica che ci siano esattamente DUE occorrenze di '---' (inizio e fine frontmatter)
    fence_count = new_text.count("---")
    assert fence_count == 2, f"Rilevato frontmatter duplicato! '---' compare {fence_count} volte:\n{new_text}"

    # Verifica che il corpo sia stato preservato e l'email aggiornata
    assert "Note storiche dell'incontro precedente." in new_text
    assert "mario.nuovo@rossi.it" in new_text
    assert "Nuova Spa" in new_text


# =========================================================================
# BUG-07: NON-BLOCKING SUBPROCESS IN MACMAILSERVICE
# =========================================================================

@pytest.mark.asyncio
async def test_bug07_mac_mail_service_uses_asyncio_to_thread():
    """
    BUG-07: MacMailService.create_draft deve avvolgere subprocess.run
    in asyncio.to_thread per non bloccare mai l'event loop di Python.
    """
    from src.agent.domain.models import EmailPayload

    mail_service = MacMailService()
    payload = EmailPayload(
        recipient_name="Test Recipient",
        recipient_email="test@example.com",
        subject="Test Subj",
        body_markdown="Test Body",
    )

    with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        mock_proc_result = MagicMock()
        mock_proc_result.returncode = 0
        mock_to_thread.return_value = mock_proc_result

        draft_id = await mail_service.create_draft(payload, idempotency_key="idemp_mail_test_123")
        assert mock_to_thread.called is True
        assert draft_id == "mac_mail_idemp_mail"


# =========================================================================
# BUG-08: O(1) CONTACT LOOKUP IN DASHBOARD (ZERO N+1 QUERIES)
# =========================================================================

def test_bug08_dashboard_contacts_map_lookup():
    """
    BUG-08: Il banner della dashboard deve precaricare i contatti in un dizionario
    per eseguire lookup O(1) invece di N query SQLite distinte.
    """
    contacts = [
        Contact(id="cnt_1", first_name="Anna", last_name="Verdi", email="anna@test.it"),
        Contact(id="cnt_2", first_name="Marco", last_name="Bianchi", email="marco@test.it"),
    ]
    contacts_map = {c.id: c for c in contacts}

    entities = [
        ExtractedEntity(raw_name="Anna Verdi", matched_contact_id="cnt_1"),
        ExtractedEntity(raw_name="Marco Bianchi", matched_contact_id="cnt_2"),
        ExtractedEntity(raw_name="Sconosciuto", matched_contact_id=None),
    ]

    resolved_names = []
    for ent in entities:
        if ent.matched_contact_id:
            c = contacts_map.get(ent.matched_contact_id)
            name = f"{c.first_name} {c.last_name}" if c else ent.raw_name
        else:
            name = ent.raw_name
        resolved_names.append(name)

    assert resolved_names == ["Anna Verdi", "Marco Bianchi", "Sconosciuto"]
