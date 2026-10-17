"""
conftest.py — Fixture condivise e architettura di isolamento per la test suite di Aria.
Garantisce:
  - Isolamento totale su filesystem temporaneo (tmp_path) senza toccare data/
  - Zero chiamate di rete esterne (Google, Gemini)
  - Zero interazioni subprocess osascript / AppleScript
  - Connessioni SQLite persistenti tra chiamate asincrone tramite db file dedicato in tmp_path
"""
import pytest
from unittest.mock import AsyncMock
from pathlib import Path

from src.agent.infrastructure.database.sqlite_repo import SqliteRepository
from src.agent.infrastructure.knowledge.obsidian_adapter import ObsidianAdapter
from src.agent.infrastructure.google.live_google import LocalCalendarService, LocalEmailService
from src.agent.application.commit_action import CommitActionUseCase


@pytest.fixture
async def test_repo(tmp_path: Path):
    """Istanza di SqliteRepository isolata su file temporaneo tmp_path."""
    db_file = tmp_path / "test_aria.db"
    repo = SqliteRepository(db_path=str(db_file))
    await repo.init_db()
    return repo


@pytest.fixture
def test_vault_path(tmp_path: Path) -> Path:
    """Directory di sandbox isolata per il Second Brain Obsidian."""
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    return vault


@pytest.fixture
def test_obsidian(test_vault_path: Path) -> ObsidianAdapter:
    """Istanza di ObsidianAdapter vincolata al vault isolato in tmp_path."""
    return ObsidianAdapter(vault_path=str(test_vault_path))


@pytest.fixture
def local_calendar() -> LocalCalendarService:
    """Implementazione dinamica in memoria di CalendarServicePort (nessuna rete)."""
    return LocalCalendarService()


@pytest.fixture
def local_email() -> LocalEmailService:
    """Implementazione locale in memoria di EmailServicePort (nessuna rete)."""
    return LocalEmailService()


@pytest.fixture
def mock_reminders() -> AsyncMock:
    """Mock asincrono di RemindersServicePort per evitare chiamate osascript durante i test."""
    mock = AsyncMock()
    mock.export_tasks.return_value = (True, "Compiti sincronizzati con successo in Apple Reminders (Mock)")
    return mock


@pytest.fixture
def test_committer(
    local_calendar: LocalCalendarService,
    local_email: LocalEmailService,
    test_obsidian: ObsidianAdapter,
    test_repo: SqliteRepository,
    mock_reminders: AsyncMock,
) -> CommitActionUseCase:
    """CommitActionUseCase collegato a servizi in-memory e sandbox temporanea."""
    return CommitActionUseCase(
        calendar_service=local_calendar,
        email_service=local_email,
        knowledge_service=test_obsidian,
        repository=test_repo,
        reminders_service=mock_reminders,
    )
