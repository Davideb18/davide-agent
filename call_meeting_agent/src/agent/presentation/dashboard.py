"""
dashboard.py — Controller principale della vista CRM Aria.
Design executive sobrio, contrasto elevato:
  1. Banner riepilogo con partecipanti e trascrizione integrale.
  2. Card Calendario & Timeline Conflitti (Apple Calendar).
  3. Card Email Follow-up (macOS Mail / Gmail con auto-adattamento reattivo).
  4. Card Task Operativi & Promemoria macOS (con esportazione a latenza zero).
Tutti gli aggiornamenti del Second Brain avvengono automaticamente in background.
"""
import html
import streamlit as st
from src.agent.domain.enums import ActionType
from src.agent.domain.models import SessionExtractionResult
from src.agent.presentation.state import get_committer, run_async
from src.agent.presentation.components.sidebar_view import render_sidebar
from src.agent.presentation.components.calendar_card import render_calendar_card
from src.agent.presentation.components.email_card import render_email_card
from src.agent.presentation.components.tasks_card import render_tasks_card


def _render_summary_banner(session: SessionExtractionResult):
    """Card di intestazione dell'area operativa principale con sintesi, partecipanti e trascrizione."""
    with st.container(border=True):
        col_title, col_actions = st.columns([3.4, 1.4])
        with col_title:
            st.markdown(
                f"<h2 style='font-size:21px; font-weight:700; color:#1A1A1E; margin:0 0 6px 0; letter-spacing:-0.02em;'>"
                f"{html.escape(session.summary)}</h2>",
                unsafe_allow_html=True,
            )
        with col_actions:
            elapsed = st.session_state.get("elapsed_seconds")
            elapsed_html = f"<span class='aria-pill aria-pill-grey'>⏱ {elapsed}s</span>" if elapsed else ""
            st.markdown(f"<div style='text-align:right; margin-bottom:6px;'>{elapsed_html}</div>", unsafe_allow_html=True)
            if st.button("🎙️ Nuova Sessione", key="btn_new_audio_banner", type="primary", use_container_width=True):
                for k in ["current_session", "audio_bytes", "audio_filename", "elapsed_seconds", "text_prompt"]:
                    st.session_state[k] = None
                st.rerun()

        # Badge partecipanti
        pills_html = "<div style='display:flex; flex-wrap:wrap; gap:6px; margin: 10px 0;'>"
        for ent in session.entities:
            if ent.matched_contact_id:
                contact = None
                if hasattr(st.session_state, "repo") and st.session_state.repo:
                    contact = run_async(st.session_state.repo.get_contact_by_id(ent.matched_contact_id))
                name = f"{contact.first_name} {contact.last_name}" if contact else ent.raw_name
                pills_html += f"<span class='aria-pill aria-pill-blue'>👤 {html.escape(name)}</span>"
            elif ent.is_ambiguous:
                pills_html += f"<span class='aria-pill aria-pill-amber'>⚠ {html.escape(ent.raw_name)}</span>"
            else:
                pills_html += f"<span class='aria-pill aria-pill-grey'>👤 {html.escape(ent.raw_name)}</span>"
        pills_html += "</div>"
        st.markdown(pills_html, unsafe_allow_html=True)

        with st.expander("📝 Trascrizione integrale"):
            st.markdown(
                f"<div style='font-size:13.5px; color:#1A1A1E; line-height:1.6; white-space:pre-wrap; background:#FFFFFF; padding:16px; border-radius:12px; border:1px solid #E1E3EB;'>{html.escape(session.raw_transcript)}</div>",
                unsafe_allow_html=True,
            )


def render(session: SessionExtractionResult):
    """Renderizza la dashboard CRM completa."""
    # Sidebar sinistra informativa
    try:
        render_sidebar(session)
    except Exception as e:
        st.sidebar.error(f"Errore sidebar: {e}")

    # Committer per eseguire le azioni
    committer = get_committer()

    # Identificazione delle azioni proposte
    cal_actions = [a for a in session.proposed_actions if a.action_type == ActionType.CALENDAR_EVENT]
    mail_actions = [a for a in session.proposed_actions if a.action_type == ActionType.EMAIL_DRAFT]
    task_act = next((a for a in session.proposed_actions if a.action_type == ActionType.TASK_TODO), None)
    know_act = next((a for a in session.proposed_actions if a.action_type == ActionType.KNOWLEDGE_NOTE), None)

    # 1. Banner riepilogo in alto
    try:
        _render_summary_banner(session)
    except Exception as e:
        st.error(f"Errore banner riepilogo: {e}")

    # 2. Card Calendario & Timeline Conflitti (Apple Calendar)
    for cal_act in cal_actions:
        try:
            render_calendar_card(cal_act, committer)
            st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Errore visualizzazione calendario: {e}")

    # 3. Card Email Follow-up (macOS Mail Window)
    for mail_act in mail_actions:
        try:
            render_email_card(mail_act, know_act, committer)
            st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Errore visualizzazione bozza email: {e}")

    # 4. Card Task Operativi & Promemoria macOS
    if task_act:
        try:
            render_tasks_card(task_act, committer)
            st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Errore visualizzazione task / Promemoria: {e}")
