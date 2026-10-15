"""
state.py — Inizializzazione singleton dei servizi e session state.
Nessun mock per LLM: Gemini reale con cascata di declassazione automatica.
"""
import os
import asyncio
import concurrent.futures
from pathlib import Path
import sys

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Path resolution
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.agent.infrastructure.database.sqlite_repo import SqliteRepository
import importlib
import src.agent.infrastructure.google.mock_google as _mock_google_mod
_mock_google_mod = importlib.reload(_mock_google_mod)
from src.agent.infrastructure.google.mock_google import MockCalendarService, MockEmailService
from src.agent.infrastructure.knowledge.obsidian_adapter import ObsidianAdapter
from src.agent.infrastructure.llm.gemini_adapter import GeminiExtractorAdapter
from src.agent.application.process_session import ProcessSessionUseCase
from src.agent.application.commit_action import CommitActionUseCase


def run_async(coro):
    """Esegue coroutine async in modo sicuro nel thread sincrono Streamlit."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except Exception:
        return asyncio.run(coro)


def init():
    """Inizializza tutti i servizi reali una sola volta per sessione (con aggiornamento dinamico)."""
    if os.path.exists("data/token.json"):
        try:
            from src.agent.infrastructure.google.live_google import LiveCalendarService, LiveEmailService
            if not isinstance(st.session_state.get("calendar"), LiveCalendarService):
                st.session_state.calendar = LiveCalendarService()
            if not isinstance(st.session_state.get("email"), LiveEmailService):
                st.session_state.email = LiveEmailService()
        except Exception:
            pass

    import importlib
    import src.agent.infrastructure.google.mock_google as mock_mod
    mock_mod = importlib.reload(mock_mod)

    _required_cal_methods = ("get_events", "check_is_busy", "find_alternative_slots", "create_event")
    if "calendar" not in st.session_state or not all(hasattr(st.session_state.calendar, m) for m in _required_cal_methods):
        st.session_state.calendar = mock_mod.MockCalendarService()

    if "email" not in st.session_state or not hasattr(st.session_state.email, "create_draft"):
        from src.agent.infrastructure.google.live_google import LiveEmailService
        if os.path.exists("data/token.json"):
            st.session_state.email = LiveEmailService()
        else:
            from src.agent.infrastructure.google.live_google import MacMailService
            st.session_state.email = MacMailService()

    if "aria_initialized" not in st.session_state:
        # 1. Database SQLite Locale
        repo = SqliteRepository("data/call_agent.db")
        run_async(repo.init_db())
        run_async(repo.seed_default_contacts())
        st.session_state.repo = repo

        # 3. Obsidian Knowledge Vault
        vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "/Users/davide/Desktop/Personal_project/Second_Brain")
        st.session_state.knowledge = ObsidianAdapter(vault_path=vault_path)

        # 4. LLM: Gemini Reale con Cascata di Declassazione Automatica (No Mock)
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not gemini_key:
            raise ValueError("GEMINI_API_KEY non trovata nel file .env!")
        st.session_state.extractor = GeminiExtractorAdapter(
            api_key=gemini_key,
            model_name="gemini-flash-lite-latest",
        )

        # UI state
        st.session_state.current_session = None
        st.session_state.elapsed_seconds = None
        st.session_state.audio_bytes = None
        st.session_state.audio_filename = None
        st.session_state.aria_initialized = True


def get_orchestrator() -> ProcessSessionUseCase:
    return ProcessSessionUseCase(
        llm_extractor=st.session_state.extractor,
        calendar_service=st.session_state.calendar,
        email_service=st.session_state.email,
        knowledge_service=st.session_state.knowledge,
        repository=st.session_state.repo,
    )


def get_committer() -> CommitActionUseCase:
    return CommitActionUseCase(
        calendar_service=st.session_state.calendar,
        email_service=st.session_state.email,
        knowledge_service=st.session_state.knowledge,
        repository=st.session_state.repo,
    )


def connect_live_google() -> bool:
    """Attiva la connessione live a Google Calendar e Gmail se non ancora effettuata."""
    try:
        from src.agent.infrastructure.google.live_google import (
            get_google_credentials,
            LiveCalendarService,
            LiveEmailService,
        )
        creds = get_google_credentials()
        if creds:
            st.session_state.calendar = LiveCalendarService(credentials=creds)
            st.session_state.email = LiveEmailService(credentials=creds)
            return True
    except Exception:
        pass
    return False

