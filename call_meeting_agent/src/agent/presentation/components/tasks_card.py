from datetime import datetime
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
            tasks_key = f"tasks_input_{task_action.id}"
            if tasks_key not in st.session_state:
                st.session_state[tasks_key] = "\n".join(data.task_items or [])
            edited_tasks = st.text_area(
                "Compiti da eseguire (uno per riga):",
                key=tasks_key,
                height=140,
                disabled=False,
                help="Modifica o aggiungi compiti prima di salvarli nel tuo progetto o in Promemoria.",
            )
            current_raw = st.session_state.get(tasks_key, edited_tasks)
            data.task_items = [t.strip() for t in current_raw.split("\n") if t.strip()]

        with col_actions:
            st.markdown(
                "<div style='font-size:11px; font-weight:700; color:#8E8E93; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:8px;'>Sincronizzazione</div>",
                unsafe_allow_html=True,
            )

            is_exec = (task_action.status == ActionStatus.EXECUTED)
            obs_synced = is_exec

            tasks_sync = st.session_state.get(f"tasks_last_sync_{task_action.id}")
            time_tag = f" • Ore {tasks_sync['time']} ({tasks_sync['count']} compiti)" if tasks_sync else ""

            if not obs_synced:
                if st.button("📓 Salva in Second Brain (Tasks.md)", key=f"btn_save_obs_tasks_{task_action.id}", type="primary", use_container_width=True):
                    latest_raw = st.session_state.get(tasks_key, edited_tasks)
                    data.task_items = [t.strip() for t in latest_raw.split("\n") if t.strip()]
                    if not data.task_items:
                        st.warning("Nessun compito inserito nella lista.")
                    else:
                        with st.spinner("Salvataggio in Tasks.md..."):
                            try:
                                ok, msg = run_async(committer.execute_action(task_action, user_modified_payload={"task_items": data.task_items, "target_project": data.target_project}))
                                if ok:
                                    st.session_state[f"tasks_last_sync_{task_action.id}"] = {
                                        "time": datetime.now().strftime("%H:%M:%S"),
                                        "count": len(data.task_items),
                                    }
                                    session = st.session_state.get("current_session")
                                    if session and hasattr(st.session_state, "repo") and st.session_state.repo:
                                        try:
                                            run_async(st.session_state.repo.save_session(session))
                                        except Exception:
                                            pass
                                    st.toast(f"✅ {len(data.task_items)} compiti salvati in Tasks.md!", icon="📋")
                                    st.rerun()
                                else:
                                    st.error(f"Errore Second Brain: {msg}")
                            except Exception as e:
                                st.error(f"Errore durante il salvataggio in Tasks.md: {e}")
            else:
                st.markdown(
                    f'<div style="background:#F0FDF4; border:1px solid #BBF7D0; border-radius:10px; padding:10px 12px; margin-bottom:8px;">'
                    f'  <div style="font-weight:700; color:#15803D; font-size:12px; display:flex; align-items:center; gap:6px;">'
                    f'    <span>✅</span> <span>Sincronizzato con Tasks.md</span>'
                    f'  </div>'
                    f'  <div style="font-size:11px; color:#166534; margin-top:2px; font-weight:500;">{time_tag or "Archiviato nel tuo Second Brain locale"}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if st.button("📓 Salva / Aggiorna in Second Brain (Tasks.md)", key=f"btn_update_obs_tasks_{task_action.id}", use_container_width=True):
                    latest_raw = st.session_state.get(tasks_key, edited_tasks)
                    data.task_items = [t.strip() for t in latest_raw.split("\n") if t.strip()]
                    if not data.task_items:
                        st.warning("Nessun compito inserito nella lista.")
                    else:
                        with st.spinner("Aggiornamento in Tasks.md..."):
                            try:
                                ok, msg = run_async(committer.execute_action(task_action, user_modified_payload={"task_items": data.task_items, "target_project": data.target_project}))
                                if ok:
                                    st.session_state[f"tasks_last_sync_{task_action.id}"] = {
                                        "time": datetime.now().strftime("%H:%M:%S"),
                                        "count": len(data.task_items),
                                    }
                                    session = st.session_state.get("current_session")
                                    if session and hasattr(st.session_state, "repo") and st.session_state.repo:
                                        try:
                                            run_async(st.session_state.repo.save_session(session))
                                        except Exception:
                                            pass
                                    st.toast(f"✅ Tasks.md aggiornato ({len(data.task_items)} compiti)!", icon="📋")
                                    st.rerun()
                                else:
                                    st.error(f"Errore Second Brain: {msg}")
                            except Exception as e:
                                st.error(f"Errore durante l'aggiornamento in Tasks.md: {e}")

            # Esporta su Apple Reminders (Promemoria macOS) — Esecuzione non-bloccante a latenza zero
            rem_synced = st.session_state.get(f"reminders_synced_{task_action.id}", False)
            rem_sync = st.session_state.get(f"reminders_last_sync_{task_action.id}")
            rem_time_tag = f" • Ore {rem_sync['time']} ({rem_sync['count']} compiti)" if rem_sync else ""

            if not rem_synced:
                if st.button("🍎 Esporta su Promemoria macOS", key=f"btn_save_reminders_{task_action.id}", use_container_width=True):
                    import uuid
                    import hashlib

                    latest_raw = st.session_state.get(tasks_key, edited_tasks)
                    data.task_items = [t.strip() for t in latest_raw.split("\n") if t.strip()]
                    if not data.task_items:
                        st.warning("Nessun compito inserito da esportare.")
                    else:
                        raw_sig = f"{task_action.session_id}_reminders_{','.join(data.task_items)}_{uuid.uuid4().hex[:6]}"
                        rem_action = ProposedAction(
                            id=f"act_rem_{uuid.uuid4().hex[:8]}",
                            session_id=task_action.session_id,
                            action_type=ActionType.TASK_EXPORT_REMINDERS,
                            idempotency_key=f"idemp_rem_{hashlib.sha256(raw_sig.encode()).hexdigest()[:12]}",
                            task_data=TaskPayload(task_items=data.task_items),
                        )

                        session = st.session_state.get("current_session")
                        if session and not any(a.id == rem_action.id for a in session.proposed_actions):
                            session.proposed_actions.append(rem_action)

                        with st.spinner("Sincronizzazione in corso con Promemoria macOS..."):
                            try:
                                ok, msg = run_async(committer.execute_action(rem_action))
                                if ok:
                                    st.session_state[f"reminders_synced_{task_action.id}"] = True
                                    st.session_state[f"reminders_last_sync_{task_action.id}"] = {
                                        "time": datetime.now().strftime("%H:%M:%S"),
                                        "count": len(data.task_items),
                                    }
                                    if session and hasattr(st.session_state, "repo") and st.session_state.repo:
                                        try:
                                            run_async(st.session_state.repo.save_session(session))
                                        except Exception:
                                            pass
                                    st.toast(f"🍎 {msg}", icon="🍎")
                                    st.rerun()
                                else:
                                    st.warning(f"⚠️ {msg}")
                            except Exception as e:
                                st.error(f"Errore durante l'esportazione su Promemoria: {e}")
            else:
                sub_label = rem_time_tag or "Presenti nell'app Promemoria"
                st.markdown(
                    f'<div style="background:#F0FDF4; border:1px solid #BBF7D0; border-radius:10px; padding:10px 12px; margin-bottom:8px;">'
                    f'  <div style="font-weight:700; color:#15803D; font-size:12px; display:flex; align-items:center; gap:6px;">'
                    f'    <span>🍎</span> <span>Sincronizzato con Promemoria macOS</span>'
                    f'  </div>'
                    f'  <div style="font-size:11px; color:#166534; margin-top:2px; font-weight:500;">{sub_label}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if st.button("🍎 Salva / Aggiorna su Promemoria macOS", key=f"btn_resave_reminders_{task_action.id}", use_container_width=True):
                    import uuid
                    import hashlib

                    latest_raw = st.session_state.get(tasks_key, edited_tasks)
                    data.task_items = [t.strip() for t in latest_raw.split("\n") if t.strip()]
                    if not data.task_items:
                        st.warning("Nessun compito inserito da aggiornare.")
                    else:
                        raw_sig = f"{task_action.session_id}_reminders_{','.join(data.task_items)}_{uuid.uuid4().hex[:6]}"
                        rem_action = ProposedAction(
                            id=f"act_rem_{uuid.uuid4().hex[:8]}",
                            session_id=task_action.session_id,
                            action_type=ActionType.TASK_EXPORT_REMINDERS,
                            idempotency_key=f"idemp_rem_{hashlib.sha256(raw_sig.encode()).hexdigest()[:12]}",
                            task_data=TaskPayload(task_items=data.task_items),
                        )

                        session = st.session_state.get("current_session")
                        if session and not any(a.id == rem_action.id for a in session.proposed_actions):
                            session.proposed_actions.append(rem_action)

                        with st.spinner("Aggiornamento su Promemoria macOS in corso..."):
                            try:
                                ok, msg = run_async(committer.execute_action(rem_action))
                                if ok:
                                    st.session_state[f"reminders_synced_{task_action.id}"] = True
                                    st.session_state[f"reminders_last_sync_{task_action.id}"] = {
                                        "time": datetime.now().strftime("%H:%M:%S"),
                                        "count": len(data.task_items),
                                    }
                                    if session and hasattr(st.session_state, "repo") and st.session_state.repo:
                                        try:
                                            run_async(st.session_state.repo.save_session(session))
                                        except Exception:
                                            pass
                                    st.toast(f"🍎 {msg}", icon="🍎")
                                    st.rerun()
                                else:
                                    st.warning(f"⚠️ {msg}")
                            except Exception as e:
                                st.error(f"Errore durante l'aggiornamento su Promemoria: {e}")

            # Bottone Scarta
            if not is_exec and not obs_synced:
                st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
                if st.button("Scarta Compiti", key=f"btn_rej_task_{task_action.id}", use_container_width=True):
                    run_async(committer.reject_action(task_action))
                    st.rerun()

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
