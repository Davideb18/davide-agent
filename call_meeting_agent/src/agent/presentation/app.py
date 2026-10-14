import os
import sys
import uuid
import asyncio
import concurrent.futures
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List

import streamlit as st
from dotenv import load_dotenv

# Carica le variabili da .env
load_dotenv()

# Project root nel path
project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.agent.domain.enums import ActionStatus, ActionType, IntentCategory
from src.agent.domain.models import (
    ProposedAction,
    SessionExtractionResult,
    CalendarPayload,
    EmailPayload,
    KnowledgePayload,
    TaskPayload,
    Contact,
)
from src.agent.infrastructure.database.sqlite_repo import SqliteRepository
from src.agent.infrastructure.google.mock_google import MockCalendarService, MockEmailService
from src.agent.infrastructure.knowledge.obsidian_adapter import ObsidianAdapter
from src.agent.infrastructure.llm.mock_llm import MockLLMExtractor
from src.agent.infrastructure.llm.gemini_adapter import GeminiExtractorAdapter
from src.agent.application.process_session import ProcessSessionUseCase
from src.agent.application.commit_action import CommitActionUseCase


def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        else:
            return loop.run_until_complete(coro)
    except Exception:
        return asyncio.run(coro)


# CONFIGURAZIONE PAGINA
st.set_page_config(
    page_title="Executive Operations",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# STILE APPLE LIGHT & FROSTED GLASS
apple_css = """
<style>
/* Font e sfondo generale stile Apple macOS */
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", sans-serif;
    color: #1D1D1F;
}

.stApp {
    background: #F5F5F7;
}

/* Nasconde barra e footer Streamlit */
header {visibility: hidden;}
footer {visibility: hidden;}
#MainMenu {visibility: hidden;}

/* Card Apple Frosted Glass */
.apple-card {
    background: rgba(255, 255, 255, 0.85);
    backdrop-filter: blur(25px);
    -webkit-backdrop-filter: blur(25px);
    border: 1px solid rgba(0, 0, 0, 0.07);
    border-radius: 20px;
    padding: 24px;
    margin-bottom: 24px;
    box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.04);
}

.apple-header {
    text-align: center;
    padding: 30px 0 20px 0;
}

.apple-title {
    font-size: 32px;
    font-weight: 700;
    letter-spacing: -0.8px;
    color: #1D1D1F;
    margin-bottom: 6px;
}

.apple-subtitle {
    font-size: 15px;
    color: #86868B;
    font-weight: 400;
}

/* Badge di stato */
.badge-person {
    display: inline-block;
    background: #E8F2FF;
    color: #0071E3;
    padding: 6px 14px;
    border-radius: 30px;
    font-size: 13px;
    font-weight: 600;
    margin-right: 8px;
}

.badge-tag {
    display: inline-block;
    background: #F2F2F7;
    color: #48484A;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 12px;
    margin-right: 6px;
}

/* Gmail Composer Mockup */
.gmail-window {
    background: #FFFFFF;
    border: 1px solid #E0E0E0;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 8px 30px rgba(0,0,0,0.08);
}

.gmail-header {
    background: #F2F6FC;
    padding: 10px 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #E0E0E0;
    font-size: 14px;
    font-weight: 600;
    color: #1F1F1F;
}

.gmail-controls span {
    display: inline-block;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    margin-left: 6px;
}

.gmail-close { background: #FF5F56; }
.gmail-min { background: #FFBD2E; }
.gmail-max { background: #27C93F; }

.gmail-row {
    padding: 8px 16px;
    border-bottom: 1px solid #F1F3F4;
    font-size: 13px;
    color: #5F6368;
}

.gmail-row b {
    color: #202124;
}

/* Timeline Calendario */
.cal-timeline {
    display: flex;
    gap: 8px;
    overflow-x: auto;
    padding: 12px 0;
}

.cal-slot {
    flex: 1;
    min-width: 90px;
    padding: 12px 8px;
    text-align: center;
    border-radius: 12px;
    border: 1px solid rgba(0,0,0,0.08);
    font-size: 12px;
}

.cal-slot-busy {
    background: #FFF2F0;
    border-color: #FFCCC7;
    color: #CF1322;
}

.cal-slot-free {
    background: #F6FFED;
    border-color: #B7EB8F;
    color: #389E0D;
    font-weight: 600;
}

.cal-slot-normal {
    background: #FAFAFA;
    color: #8C8C8C;
}

/* Bottoni Apple Style */
.stButton>button {
    border-radius: 10px;
    font-weight: 500;
    font-size: 14px;
    padding: 8px 18px;
    transition: all 0.2s ease;
    border: none;
}

.stButton>button[kind="primary"] {
    background: #0071E3;
    color: #FFFFFF;
}

.stButton>button[kind="primary"]:hover {
    background: #0077ED;
    box-shadow: 0 4px 12px rgba(0, 113, 227, 0.3);
}

.stButton>button[kind="secondary"] {
    background: #E8E8ED;
    color: #1D1D1F;
}

.stButton>button[kind="secondary"]:hover {
    background: #DCDCE2;
}

/* Tabs Apple Style */
.stTabs [data-baseweb="tab-list"] {
    gap: 12px;
    justify-content: center;
    background: #E8E8ED;
    padding: 4px;
    border-radius: 12px;
}

.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    padding: 6px 18px;
    font-size: 14px;
    font-weight: 500;
    border: none;
    color: #1D1D1F;
}

.stTabs [aria-selected="true"] {
    background: #FFFFFF !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
</style>
"""
st.markdown(apple_css, unsafe_allow_html=True)

# INIZIALIZZAZIONE COMPONENTI (Singleton pulito)
if "repo" not in st.session_state:
    repo = SqliteRepository("data/call_agent.db")
    run_async(repo.init_db())
    run_async(repo.seed_default_contacts())
    st.session_state.repo = repo
    st.session_state.calendar = MockCalendarService()
    st.session_state.email = MockEmailService()
    
    vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "/Users/davide/Desktop/Personal_project/Second_Brain")
    st.session_state.knowledge = ObsidianAdapter(vault_path=vault_path)
    
    # Se la chiave Gemini è presente in .env, usa Gemini 3.8 Flash, altrimenti Mock
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            st.session_state.extractor = GeminiExtractorAdapter(api_key=gemini_key, model_name="gemini-3.8-flash")
        except Exception:
            st.session_state.extractor = MockLLMExtractor()
    else:
        st.session_state.extractor = MockLLMExtractor()

    st.session_state.current_session = None

repo = st.session_state.repo
cal_svc = st.session_state.calendar
mail_svc = st.session_state.email
know_svc = st.session_state.knowledge
llm_svc = st.session_state.extractor

# HEADER STILE APPLE
st.markdown(
    """
    <div class="apple-header">
        <div class="apple-title">Executive Operations</div>
        <div class="apple-subtitle">Voice-to-Action • Human-in-the-Loop • Apple Glassmorphic Design</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# STEP 1: INGESTION AUDIO IN APPLE CARD
st.markdown('<div class="apple-card">', unsafe_allow_html=True)

if "audio_bytes" not in st.session_state:
    st.session_state.audio_bytes = None
if "audio_filename" not in st.session_state:
    st.session_state.audio_filename = None

tab_mic, tab_file, tab_demo = st.tabs([
    "🎙️ Registra Microfono",
    "📁 Carica Audio",
    "🚀 Demo Veloce (Filippo Calzavara)",
])

with tab_mic:
    st.caption("Registra dal vivo una nota vocale o sintesi della call:")
    live_audio = st.audio_input("Premi Registra per iniziare:")
    if live_audio is not None:
        st.session_state.audio_bytes = live_audio.read()
        st.session_state.audio_filename = "registrazione_microfono.wav"

with tab_file:
    uploaded_file = st.file_uploader(
        "Trascina qui il file audio (MP3, WAV, M4A, OGG):",
        type=["mp3", "wav", "m4a", "ogg", "aac"],
        label_visibility="collapsed",
    )
    if uploaded_file is not None:
        st.session_state.audio_bytes = uploaded_file.read()
        st.session_state.audio_filename = uploaded_file.name

with tab_demo:
    st.caption("Simula il colloquio e allineamento con Filippo (CTO Trellis):")
    if st.button("Carica Registrazione Demo Trellis", use_container_width=True):
        st.session_state.audio_bytes = b"mock_audio_bytes"
        st.session_state.audio_filename = "meeting_filippo_trellis.mp3"

if st.session_state.audio_bytes is not None:
    st.markdown("---")
    col_aud, col_btn = st.columns([2, 1])
    with col_aud:
        st.caption(f"Audio pronto: **{st.session_state.audio_filename}**")
        if st.session_state.audio_bytes != b"mock_audio_bytes":
            st.audio(st.session_state.audio_bytes)
    with col_btn:
        st.write("")
        if st.button("⚡ Elabora con l'AI", type="primary", use_container_width=True):
            with st.spinner("Analisi audio e verifica disponibilità agenda in corso..."):
                orchestrator = ProcessSessionUseCase(
                    llm_extractor=llm_svc,
                    calendar_service=cal_svc,
                    email_service=mail_svc,
                    knowledge_service=know_svc,
                    repository=repo,
                )
                session_result = run_async(
                    orchestrator.execute(
                        audio_bytes=st.session_state.audio_bytes,
                        filename=st.session_state.audio_filename,
                        anchor_utc=datetime.now(timezone.utc),
                    )
                )
                st.session_state.current_session = session_result
                st.rerun()

st.markdown('</div>', unsafe_allow_html=True)


# STEP 2 & RISULTATI OPERATIVI
current_session: Optional[SessionExtractionResult] = st.session_state.current_session

if current_session:
    committer = CommitActionUseCase(
        calendar_service=cal_svc,
        email_service=mail_svc,
        knowledge_service=know_svc,
        repository=repo,
    )

    # 1. CARD: RIEPILOGO & CONTATTI IDENTIFICATI
    st.markdown('<div class="apple-card">', unsafe_allow_html=True)
    st.markdown(f"### 📌 {current_session.summary}")
    
    # Entità trovate formattate a badge
    ents_html = "<div>"
    for ent in current_session.entities:
        if ent.matched_contact_id:
            c = run_async(repo.get_contact_by_id(ent.matched_contact_id))
            if c:
                ents_html += f'<span class="badge-person">👤 {c.first_name} {c.last_name} ({c.company} • {c.role})</span>'
        elif ent.is_ambiguous:
            ents_html += f'<span class="badge-person" style="background:#FFF1F0;color:#F5222D;">⚠️ {ent.raw_name} (Ambiguità)</span>'
        else:
            ents_html += f'<span class="badge-person" style="background:#F4F4F5;color:#71717A;">👤 {ent.raw_name}</span>'
    ents_html += "</div>"
    st.markdown(ents_html, unsafe_allow_html=True)

    with st.expander("📝 Trascrizione Audio"):
        st.write(current_session.raw_transcript)
    st.markdown('</div>', unsafe_allow_html=True)

    # TROVA LE AZIONI
    cal_action = next((a for a in current_session.proposed_actions if a.action_type == ActionType.CALENDAR_EVENT), None)
    mail_action = next((a for a in current_session.proposed_actions if a.action_type == ActionType.EMAIL_DRAFT), None)
    know_action = next((a for a in current_session.proposed_actions if a.action_type == ActionType.KNOWLEDGE_NOTE), None)
    task_action = next((a for a in current_session.proposed_actions if a.action_type == ActionType.TASK_TODO), None)

    # 2. SEZIONE CALENDARIO VISIVO (TIMELINE E GESTIONE CONFLITTI)
    if cal_action and cal_action.calendar_data:
        st.markdown('<div class="apple-card">', unsafe_allow_html=True)
        col_c_title, col_c_status = st.columns([3, 1])
        with col_c_title:
            st.markdown(f"### 📅 Calendario: {cal_action.calendar_data.title}")
        with col_c_status:
            if cal_action.status == ActionStatus.EXECUTED:
                st.markdown('<span class="badge-person" style="background:#F6FFED;color:#389E0D;">✅ Schedulato</span>', unsafe_allow_html=True)
            elif cal_action.status == ActionStatus.CONFLICT_DETECTED:
                st.markdown('<span class="badge-person" style="background:#FFF2F0;color:#CF1322;">⚠️ Conflitto Rilevato</span>', unsafe_allow_html=True)
            else:
                st.markdown(f'<span class="badge-person">{cal_action.status.value}</span>', unsafe_allow_html=True)

        # Timeline visiva della giornata
        st.caption("Disponibilità oraria della giornata (UTC):")
        req_hour = cal_action.calendar_data.start_utc.hour
        timeline_html = '<div class="cal-timeline">'
        for h in range(9, 18):
            time_label = f"{h:02d}:00"
            if h == 14:
                timeline_html += f'<div class="cal-slot cal-slot-busy"><b>{time_label}</b><br>Occupato</div>'
            elif h in (15, 16):
                timeline_html += f'<div class="cal-slot cal-slot-free"><b>{time_label}</b><br>Libero ✨</div>'
            else:
                timeline_html += f'<div class="cal-slot cal-slot-normal"><b>{time_label}</b><br>Libero</div>'
        timeline_html += '</div>'
        st.markdown(timeline_html, unsafe_allow_html=True)

        if cal_action.status == ActionStatus.CONFLICT_DETECTED and cal_action.calendar_data.alternative_slots_utc:
            st.warning(
                f"🚨 **Rischio Overbooking:** Lo slot richiesto ({cal_action.calendar_data.start_utc.strftime('%H:%M')} UTC) "
                "si sovrappone a un altro evento in agenda."
            )
            alt_options = [
                slot.strftime("%Y-%m-%d ore %H:%M UTC")
                for slot in cal_action.calendar_data.alternative_slots_utc
            ]
            selected_alt = st.selectbox(
                "Sposta l'orario su uno slot libero suggerito:",
                options=alt_options,
                key=f"alt_{cal_action.id}",
            )
            if selected_alt:
                idx = alt_options.index(selected_alt)
                chosen_start = cal_action.calendar_data.alternative_slots_utc[idx]
                dur = cal_action.calendar_data.end_utc - cal_action.calendar_data.start_utc
                cal_action.calendar_data.start_utc = chosen_start
                cal_action.calendar_data.end_utc = chosen_start + dur

        col_c1, col_c2 = st.columns([1, 4])
        with col_c1:
            if cal_action.status != ActionStatus.EXECUTED:
                if st.button("Approva & Inserisci", key=f"btn_c_{cal_action.id}", type="primary"):
                    ok, msg = run_async(committer.execute_action(cal_action, user_modified_payload=cal_action.calendar_data.model_dump(mode="json")))
                    if ok:
                        st.toast(msg, icon="📅")
                        st.rerun()
        with col_c2:
            if cal_action.status != ActionStatus.EXECUTED:
                if st.button("Rifiuta", key=f"btn_rej_c_{cal_action.id}"):
                    run_async(committer.reject_action(cal_action))
                    st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)

    # 3. SEZIONE GMAIL (SPLIT VIEW: CONTESTO A SINISTRA, GMAIL MOCKUP A DESTRA)
    if mail_action and mail_action.email_data:
        st.markdown('<div class="apple-card">', unsafe_allow_html=True)
        col_m_left, col_m_right = st.columns([1, 1], gap="large")

        with col_m_left:
            st.markdown("### 🗣️ Contesto Estratto dalla Call")
            st.info(
                f"**Destinatario:** {mail_action.email_data.recipient_name}\n\n"
                f"**Email:** `{mail_action.email_data.recipient_email}`\n\n"
                f"**Riepilogo Accordi:** L'AI ha generato il testo del follow-up basandosi sugli accordi "
                f"commerciali (modello commissioni al 3%) e la disponibilità concordata."
            )
            if know_action and know_action.knowledge_data:
                st.markdown("**Insight emersi:**")
                for ins in know_action.knowledge_data.bullet_insights:
                    st.markdown(f"- {ins}")

        with col_m_right:
            # Finestra Gmail Composizione Stile Real
            st.markdown(
                """
                <div class="gmail-window">
                    <div class="gmail-header">
                        <span>✉️ Nuovo messaggio • Gmail</span>
                        <div class="gmail-controls">
                            <span class="gmail-min"></span>
                            <span class="gmail-max"></span>
                            <span class="gmail-close"></span>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption(f"A: **{mail_action.email_data.recipient_email}**")
            new_subject = st.text_input("Oggetto:", value=mail_action.email_data.subject, key=f"subj_{mail_action.id}")
            mail_action.email_data.subject = new_subject
            
            new_body = st.text_area(
                "Testo email:",
                value=mail_action.email_data.body_markdown,
                height=140,
                key=f"body_{mail_action.id}",
            )
            mail_action.email_data.body_markdown = new_body

            col_mb1, col_mb2 = st.columns([1, 2])
            with col_mb1:
                if mail_action.status != ActionStatus.EXECUTED:
                    if st.button("Salva Bozza su Gmail", key=f"btn_m_{mail_action.id}", type="primary"):
                        ok, msg = run_async(committer.execute_action(mail_action, user_modified_payload=mail_action.email_data.model_dump(mode="json")))
                        if ok:
                            st.toast(msg, icon="✉️")
                            st.rerun()
                else:
                    st.success("✅ Bozza salvata su Gmail")
            with col_mb2:
                if mail_action.status != ActionStatus.EXECUTED:
                    if st.button("Rifiuta Bozza", key=f"btn_rej_m_{mail_action.id}"):
                        run_async(committer.reject_action(mail_action))
                        st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)

    # 4. SEZIONE REPORT TO-DO & SECOND BRAIN (FROSTED GLASS CARD)
    st.markdown('<div class="apple-card">', unsafe_allow_html=True)
    st.markdown("### 📋 Report Azioni & To-Do List")
    st.caption("Checklist operativa dei compiti concordati e sincronizzazione con il Second Brain:")

    if task_action and task_action.task_data:
        tasks_text = "\n".join(task_action.task_data.task_items)
        edited_tasks = st.text_area(
            "Task Operativi da svolgere:",
            value=tasks_text,
            height=100,
            key=f"task_area_{task_action.id}",
        )
        task_action.task_data.task_items = [t.strip() for t in edited_tasks.split("\n") if t.strip()]

    col_sync1, col_sync2 = st.columns([1, 1])
    with col_sync1:
        if task_action and task_action.status != ActionStatus.EXECUTED:
            if st.button("✅ Salva Task in Projects/Tasks.md", key=f"btn_t_{task_action.id}", type="primary", use_container_width=True):
                ok, msg = run_async(committer.execute_action(task_action, user_modified_payload=task_action.task_data.model_dump(mode="json")))
                if ok:
                    st.toast("Task salvati nel Second Brain!", icon="📋")
                    st.rerun()
        elif task_action and task_action.status == ActionStatus.EXECUTED:
            st.success("✅ Task archiviati in Tasks.md")

    with col_sync2:
        if know_action and know_action.status != ActionStatus.EXECUTED:
            if st.button("🧠 Sincronizza Scheda & Dossier Obsidian", key=f"btn_k_{know_action.id}", type="secondary", use_container_width=True):
                ok, msg = run_async(committer.execute_action(know_action))
                if ok:
                    st.toast("Second Brain sincronizzato!", icon="🧠")
                    st.rerun()
        elif know_action and know_action.status == ActionStatus.EXECUTED:
            st.success("✅ Note e Dossier Persona sincronizzati nel Vault")

    st.markdown('</div>', unsafe_allow_html=True)
