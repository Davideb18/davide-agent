"""
tasks_card.py — Card To-Do List e Promemoria macOS.
Design System: Apple Executive.
"""
import html
from typing import Optional
import streamlit as st
from src.agent.domain.enums import ActionStatus, ActionType
from src.agent.domain.models import ProposedAction, TaskPayload
from src.agent.presentation.state import run_async


def render_tasks_card(task_action: Optional[ProposedAction], committer):
    """Renderizza la card per la checklist dei task operativi e l'esportazione su Promemoria macOS."""
    if not task_action or not task_action.task_data:
        return

    data = task_action.task_data

    # Se l'azione task è stata scartata, mostra banner ridotto
    if task_action.status == ActionStatus.REJECTED:
        with st.container(border=True):
            col_t, col_undo = st.columns([4, 1])
            with col_t:
                st.markdown(
                    f"<div style='display:flex; align-items:center; gap:8px; color:#8E8E93; font-size:13px; font-weight:600; padding:4px 0;'>"
                    f"<span>🗑️</span>"
                    f"<span style='text-decoration:line-through;'>Compiti To-Do concordati ({len(data.task_items)} elementi)</span>"
                    f"<span class='aria-pill aria-pill-grey' style='font-size:10px;'>Scartati</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            with col_undo:
                if st.button("Ripristina", key=f"btn_undo_task_{task_action.id}", use_container_width=True):
                    task_action.status = ActionStatus.PROPOSED
                    st.rerun()
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        return

    with st.container(border=True):
        proj_badge = (
            f"<span class='aria-pill aria-pill-blue' style='font-size:11px;'>Progetto: [[{html.escape(data.target_project)}]]</span>"
            if data.target_project else
            "<span class='aria-pill aria-pill-grey' style='font-size:11px;'>To-Do Operativi</span>"
        )
        st.markdown(
            f"""
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
                <h3 style="font-size:19px; font-weight:800; color:#1D1D1F; margin:0; letter-spacing:-0.02em;">
                    📋 Compiti Operativi (To-Do List)
                </h3>
                {proj_badge}
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_edit, col_actions = st.columns([2, 1.2], gap="large")

        with col_edit:
            txt_items = "\n".join(data.task_items or [])
            is_exec = (task_action.status == ActionStatus.EXECUTED)
            edited_tasks = st.text_area(
                "Compiti da eseguire (uno per riga):",
                value=txt_items,
                height=140,
                key=f"tasks_input_{task_action.id}",
                disabled=is_exec,
                help="Modifica o aggiungi compiti prima di salvarli nel tuo progetto o in Promemoria.",
            )
            data.task_items = [t.strip() for t in edited_tasks.split("\n") if t.strip()]

        with col_actions:
            st.markdown(
                "<div style='font-size:11px; font-weight:700; color:#8E8E93; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:8px;'>Sincronizzazione</div>",
                unsafe_allow_html=True,
            )

            # Esporta su Apple Reminders (Promemoria macOS) — Esecuzione non-bloccante a latenza zero
            rem_synced = st.session_state.get(f"reminders_synced_{task_action.id}", False)
            if not rem_synced:
                if st.button("🍎 Esporta su Promemoria macOS", key=f"btn_save_reminders_{task_action.id}", type="primary", use_container_width=True):
                    import uuid
                    import hashlib
                    import threading

                    latest_raw = st.session_state.get(f"tasks_input_{task_action.id}", edited_tasks)
                    data.task_items = [t.strip() for t in latest_raw.split("\n") if t.strip()]

                    raw_sig = f"{task_action.session_id}_reminders_{','.join(data.task_items)}"
                    rem_action = ProposedAction(
                        id=f"act_rem_{uuid.uuid4().hex[:8]}",
                        session_id=task_action.session_id,
                        action_type=ActionType.TASK_EXPORT_REMINDERS,
                        idempotency_key=f"idemp_rem_{hashlib.sha256(raw_sig.encode()).hexdigest()[:12]}",
                        task_data=TaskPayload(task_items=data.task_items),
                    )

                    def _run_bg_export():
                        try:
                            import asyncio
                            asyncio.run(committer.execute_action(rem_action))
                        except Exception as e:
                            import logging
                            logging.getLogger(__name__).error(f"Errore esportazione background Promemoria: {e}")

                    threading.Thread(target=_run_bg_export, daemon=True).start()
                    st.session_state[f"reminders_synced_{task_action.id}"] = True
                    st.toast("Compiti inviati a Promemoria macOS!", icon="🍎")
                    st.rerun()
            else:
                st.markdown(
                    '<div style="background:#F0FDF4; border:1px solid #BBF7D0; border-radius:10px; padding:10px;"><span class="aria-pill aria-pill-green">✅ Sincronizzato con Promemoria macOS</span></div>',
                    unsafe_allow_html=True,
                )

            # Bottone Scarta
            if not is_exec:
                st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
                if st.button("Scarta Compiti", key=f"btn_rej_task_{task_action.id}", use_container_width=True):
                    run_async(committer.reject_action(task_action))
                    st.rerun()

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
