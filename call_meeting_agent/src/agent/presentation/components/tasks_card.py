"""
tasks_card.py — Card To-Do List e Obsidian Second Brain.
Design System: Apple Executive / Gemini Glass.
"""
import re
from typing import Optional
import streamlit as st
from src.agent.domain.enums import ActionStatus
from src.agent.domain.models import ProposedAction
from src.agent.presentation.state import run_async


def render_tasks_card(task_action: Optional[ProposedAction], know_action: Optional[ProposedAction], committer):
    """Renderizza le sezioni operative per To-Do List e Second Brain Obsidian."""
    with st.container(border=True):
        st.markdown(
            "<h3 style='font-size:18px; font-weight:700; color:#1A1A1E; margin:0 0 14px 0; letter-spacing:-0.025em;'>"
            "📋 Action Items & Second Brain</h3>",
            unsafe_allow_html=True,
        )

        col_tasks, col_vault = st.columns([1.2, 1], gap="large")

        # Sezione Tasks a sinistra
        with col_tasks:
            st.markdown(
                "<div style='display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;'>"
                "<span style='font-size:11.5px; font-weight:700; color:#1A1A1E; text-transform:uppercase; letter-spacing:0.06em;'>Checklist Decisioni</span>"
                "<span class='aria-pill aria-pill-blue' style='font-size:10px;'>Priorità Alta</span>"
                "</div>",
                unsafe_allow_html=True,
            )
            if task_action and task_action.task_data:
                txt_items = "\n".join(task_action.task_data.task_items or [])
                edited_tasks = st.text_area(
                    "Compiti concordati:",
                    value=txt_items,
                    height=125,
                    key=f"tasks_input_{task_action.id}",
                    label_visibility="collapsed",
                )
                task_action.task_data.task_items = [t.strip() for t in edited_tasks.split("\n") if t.strip()]

                if task_action.status != ActionStatus.EXECUTED:
                    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
                    if st.button("✅  Salva Compiti in Tasks.md", key=f"btn_save_tasks_{task_action.id}", type="primary", use_container_width=True):
                        ok, _ = run_async(committer.execute_action(task_action, user_modified_payload=task_action.task_data.model_dump(mode="json")))
                        if ok:
                            st.toast("Compiti archiviati nel Second Brain!", icon="📋")
                            st.rerun()
                else:
                    st.markdown('<span class="aria-pill aria-pill-green">✓ Compiti Sincronizzati in Tasks.md</span>', unsafe_allow_html=True)

        # Sezione Obsidian Vault a destra
        with col_vault:
            st.markdown(
                "<p style='font-size:11.5px; font-weight:700; color:#1A1A1E; text-transform:uppercase; letter-spacing:0.06em; margin-bottom:8px;'>Obsidian Knowledge Vault</p>",
                unsafe_allow_html=True,
            )
            meeting_note = "ACTIVITY/Meetings/Nota_Riunione.md"
            contact_note = "PEOPLE/Contatto.md"
            if know_action and know_action.knowledge_data:
                def _slug(t: str) -> str:
                    return re.sub(r"[-\s]+", "_", re.sub(r"[^\w\s-]", "", (t or "").lower().strip()))
                t_slug = _slug(know_action.knowledge_data.title or "") or "meeting"
                p_slug = _slug(know_action.knowledge_data.target_person_name or "") or "contatto"
                meeting_note = f"ACTIVITY/Meetings/{t_slug}.md"
                contact_note = f"PEOPLE/{p_slug}.md"

            st.markdown(
                f"""
                <div style="background: #FFFFFF; border: 1px solid #D2D2D7; border-radius: 14px; padding: 14px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.03);">
                    <p style="font-size: 13.5px; font-weight: 700; color: #1A1A1E; margin: 0 0 4px 0;">🧠 Dossier Riunione & Backlink</p>
                    <p style="font-size: 11.5px; color: #55555A; margin: 0 0 10px 0; line-height: 1.45;">
                        Crea automaticamente le schede collegate nel tuo archivio Obsidian:
                    </p>
                    <div style="display:flex; flex-direction:column; gap:6px;">
                        <span style="font-size:11.5px; font-family:monospace; background:#EEF3FA; border:1px solid rgba(0,119,237,0.25); padding:4px 8px; border-radius:6px; color:#005FC4; font-weight:600;">
                            📁 {meeting_note}
                        </span>
                        <span style="font-size:11.5px; font-family:monospace; background:#EEF3FA; border:1px solid rgba(0,119,237,0.25); padding:4px 8px; border-radius:6px; color:#005FC4; font-weight:600;">
                            📁 {contact_note}
                        </span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if know_action and know_action.status != ActionStatus.EXECUTED:
                if st.button("🧠  Sincronizza nel Vault Obsidian", key=f"btn_sync_obsidian_{know_action.id}", use_container_width=True):
                    ok, _ = run_async(committer.execute_action(know_action))
                    if ok:
                        st.toast("Dossier sincronizzato nel vault Obsidian!", icon="🧠")
                        st.rerun()
            elif know_action and know_action.status == ActionStatus.EXECUTED:
                st.markdown('<span class="aria-pill aria-pill-green">✓ Dossier e Backlink Sincronizzati nel Vault</span>', unsafe_allow_html=True)
