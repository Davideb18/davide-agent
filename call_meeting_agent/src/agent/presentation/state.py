"""
state.py — Inizializzazione singleton dei servizi e session state.
Esecuzione 100% reale: Gemini multimodale e integrazione Google Calendar/Gmail.
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

from zoneinfo import ZoneInfo
from src.agent.infrastructure.database.sqlite_repo import SqliteRepository
from src.agent.infrastructure.google.live_google import (
    LiveCalendarService,
    LiveEmailService,
    LocalCalendarService,
    LocalEmailService,
)
from src.agent.infrastructure.knowledge.obsidian_adapter import ObsidianAdapter
from src.agent.infrastructure.llm.gemini_adapter import GeminiExtractorAdapter
from src.agent.infrastructure.apple.reminders_adapter import AppleRemindersAdapter
from src.agent.application.process_session import ProcessSessionUseCase
from src.agent.application.commit_action import CommitActionUseCase

COMMON_TIMEZONES = [
    "Europe/Rome",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Zurich",
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "Asia/Tokyo",
    "Asia/Dubai",
    "UTC",
]


def detect_system_timezone() -> str:
    """Rileva in modo resiliente il fuso orario del sistema con fallback su Europe/Rome."""
    tz_env = os.environ.get("TZ")
    if tz_env:
        try:
            ZoneInfo(tz_env)
            return tz_env
        except Exception:
            pass

    if os.path.exists("/etc/localtime"):
        try:
            real_path = os.path.realpath("/etc/localtime")
            if "zoneinfo/" in real_path:
                iana_name = real_path.split("zoneinfo/")[-1]
                ZoneInfo(iana_name)
                return iana_name
        except Exception:
            pass

    return "Europe/Rome"


def is_calendar_live() -> bool:
    """Verifica se il servizio di calendario è connesso all'API Google live."""
    cal = st.session_state.get("calendar")
    return isinstance(cal, LiveCalendarService)


def is_email_live() -> bool:
    """Verifica se il servizio email è connesso all'API Gmail live."""
    mail = st.session_state.get("email")
    return isinstance(mail, LiveEmailService)


def run_async(coro):
    """Esegue coroutine async in modo sicuro ed isolato nel thread sincrono Streamlit."""
    try:
        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(lambda: asyncio.run(coro)).result()

        try:
            event_loop = asyncio.get_event_loop()
        except RuntimeError:
            event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(event_loop)

        if event_loop.is_closed():
            event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(event_loop)

        return event_loop.run_until_complete(coro)
    except RuntimeError as re_err:
        if "already running" in str(re_err).lower():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(lambda: asyncio.run(coro)).result()
        raise



def init():
    """Inizializza tutti i servizi reali una sola volta per sessione (con aggiornamento dinamico)."""
    # 1. Calendario: Google Calendar Live se autenticato, altrimenti Calendario Locale dinamico (preservando istanza in-memory)
    _required_cal_methods = ("get_events", "check_is_busy", "find_alternative_slots", "create_event")
    cal_in_state = st.session_state.get("calendar")
    has_valid_cal = cal_in_state is not None and all(hasattr(cal_in_state, m) for m in _required_cal_methods)

    if not has_valid_cal or not isinstance(cal_in_state, LiveCalendarService):
        if os.path.exists("data/token.json"):
            try:
                st.session_state.calendar = LiveCalendarService()
            except Exception:
                if not has_valid_cal:
                    st.session_state.calendar = LocalCalendarService()
        elif not has_valid_cal:
            st.session_state.calendar = LocalCalendarService()

    # 2. Email: Gmail Live se autenticato, altrimenti Servizio Email Locale dinamico (preservando bozze in-memory)
    mail_in_state = st.session_state.get("email")
    has_valid_mail = mail_in_state is not None and hasattr(mail_in_state, "create_draft")

    if not has_valid_mail or not isinstance(mail_in_state, LiveEmailService):
        if os.path.exists("data/token.json"):
            try:
                st.session_state.email = LiveEmailService()
            except Exception:
                if not has_valid_mail:
                    st.session_state.email = LocalEmailService()
        elif not has_valid_mail:
            st.session_state.email = LocalEmailService()

    if "aria_initialized" not in st.session_state:
        # 3. Database SQLite Locale
        repo = SqliteRepository("data/call_agent.db")
        run_async(repo.init_db())
        st.session_state.repo = repo

        # 4. Obsidian Knowledge Vault (Source of truth per contatti e identità)
        vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "data/vault")
        knowledge = ObsidianAdapter(vault_path=vault_path)
        st.session_state.knowledge = knowledge

        # 4b. Sincronizzazione contatti e identità dal Second Brain
        user_profile = None
        try:
            user_profile = run_async(knowledge.get_user_profile())
            st.session_state.user_profile = user_profile
        except Exception:
            st.session_state.user_profile = None

        try:
            vault_contacts = run_async(knowledge.get_all_contacts()) or []
            if user_profile and user_profile.full_name:
                has_user = any("utente" in [t.lower() for t in c.tags] for c in vault_contacts)
                if not has_user:
                    from src.agent.domain.models import Contact
                    vault_contacts.insert(
                        0,
                        Contact(
                            id=f"cnt_{knowledge._slugify(user_profile.full_name)}",
                            first_name=user_profile.first_name,
                            last_name=user_profile.last_name,
                            email=user_profile.email or os.getenv("USER_EMAIL", ""),
                            company=user_profile.company or "N/D",
                            role=user_profile.role or "Utente / Personale",
                            aliases=user_profile.aliases or ["Me stesso", "Io"],
                            tags=["utente", "personale"],
                            timezone=user_profile.timezone,
                        ),
                    )

            if vault_contacts:
                run_async(repo.sync_contacts_from_vault(vault_contacts))
            else:
                run_async(repo.seed_default_contacts())
        except Exception:
            run_async(repo.seed_default_contacts())

        # 5. LLM: Gemini Reale con Cascata di Declassazione Automatica
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not gemini_key:
            raise ValueError("GEMINI_API_KEY non trovata nel file .env!")
        st.session_state.extractor = GeminiExtractorAdapter(
            api_key=gemini_key,
            model_name="gemini-flash-lite-latest",
        )

        # 6. Apple Reminders nativo (macOS con fallback elegante)
        st.session_state.reminders = AppleRemindersAdapter()

        # UI state
        st.session_state.current_session = None
        st.session_state.elapsed_seconds = None
        st.session_state.audio_bytes = None
        st.session_state.audio_filename = None
        st.session_state.text_prompt = None
        st.session_state.user_timezone = detect_system_timezone()
        st.session_state.aria_initialized = True
    elif "user_timezone" not in st.session_state:
        st.session_state.user_timezone = detect_system_timezone()

    if "reminders" not in st.session_state:
        st.session_state.reminders = AppleRemindersAdapter()


def get_orchestrator() -> ProcessSessionUseCase:
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    extractor = GeminiExtractorAdapter(api_key=gemini_key)
    st.session_state.extractor = extractor

    vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "data/vault")
    knowledge = ObsidianAdapter(vault_path=vault_path)
    st.session_state.knowledge = knowledge

    return ProcessSessionUseCase(
        llm_extractor=extractor,
        calendar_service=st.session_state.calendar,
        email_service=st.session_state.email,
        knowledge_service=knowledge,
        repository=st.session_state.repo,
    )


def get_committer() -> CommitActionUseCase:
    vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "data/vault")
    knowledge = ObsidianAdapter(vault_path=vault_path)
    st.session_state.knowledge = knowledge

    return CommitActionUseCase(
        calendar_service=st.session_state.calendar,
        email_service=st.session_state.email,
        knowledge_service=knowledge,
        repository=st.session_state.repo,
        reminders_service=st.session_state.get("reminders"),
    )


def connect_live_google() -> bool:
    """Attiva la connessione live a Google Calendar e Gmail se credenziali presenti."""
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
