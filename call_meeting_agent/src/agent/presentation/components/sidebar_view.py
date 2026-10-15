"""
sidebar_view.py — Colonna sinistra (Sidebar) del CRM Aria.
Design pulito, contrasto elevato, zero testi da chatbot AI.
"""
import uuid
import streamlit as st
from src.agent.domain.enums import ActionStatus, ActionType
from src.agent.domain.models import SessionExtractionResult, Contact
from src.agent.presentation.state import (
    run_async,
    is_calendar_live,
    is_email_live,
    COMMON_TIMEZONES,
)


def render_sidebar(session: SessionExtractionResult):
    """Renderizza la sidebar sinistra in stile Apple sobrio e professionale."""
    with st.sidebar:
        # Header Brand
        st.markdown(
            """
            <div style="padding: 14px 0 12px 0; border-bottom: 1px solid #E1E3EB; margin-bottom: 12px;">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span style="font-size: 20px;">🎙️</span>
                    <div>
                        <h2 style="font-size: 16.5px; font-weight: 700; color: #1A1A1E; margin: 0; letter-spacing: -0.02em;">
                            Aria
                        </h2>
                        <span style="font-size: 11px; color: #6E6E73; font-weight: 600;">
                            Riepilogo Sessione
                        </span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── INDICATORI STATO SERVIZI (LIVE VS LOCALE) ───────────────────
        cal_live = is_calendar_live()
        mail_live = is_email_live()
        cal_badge = (
            '<span class="aria-pill aria-pill-green" style="font-size:10.5px; padding:3px 8px;">🟢 Google Calendar: Connesso</span>'
            if cal_live else
            '<span class="aria-pill aria-pill-amber" style="font-size:10.5px; padding:3px 8px;">🟡 Calendar: Locale (No OAuth)</span>'
        )
        mail_badge = (
            '<span class="aria-pill aria-pill-green" style="font-size:10.5px; padding:3px 8px;">🟢 Gmail API: Connesso</span>'
            if mail_live else
            '<span class="aria-pill aria-pill-amber" style="font-size:10.5px; padding:3px 8px;">🟡 Email: Bozza Locale</span>'
        )
        st.markdown(
            f"""
            <div style="display:flex; flex-direction:column; gap:6px; margin-bottom:14px;">
                {cal_badge}
                {mail_badge}
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── SCHEDA CONTATTO INTERLOCUTORE ──────────────────────────────
        primary_entity = next((e for e in session.entities if e.matched_contact_id), None)
        contact = None
        if primary_entity and hasattr(st.session_state, "repo") and st.session_state.repo:
            contact = run_async(st.session_state.repo.get_contact_by_id(primary_entity.matched_contact_id))

        if contact:
            fn = (contact.first_name or "").strip()
            ln = (contact.last_name or "").strip()
            if fn and ln:
                initials = f"{fn[:1]}{ln[:1]}".upper()
            elif len(fn) >= 2:
                initials = fn[:2].upper()
            elif len(fn) == 1:
                initials = fn.upper()
            elif len(ln) >= 2:
                initials = ln[:2].upper()
            elif len(ln) == 1:
                initials = ln.upper()
            else:
                initials = "👤"

            full_display_name = f"{fn} {ln}".strip() or "Contatto"
            badges = []
            comp = (contact.company or "").strip()
            role = (contact.role or "").strip()
            junk_terms = ["dell'utente", "riceverà", "ricevere", "email", "mail", "none", "n/d", "referente"]
            if comp and not any(t in comp.lower() for t in junk_terms):
                badges.append(f'<span class="aria-pill aria-pill-blue" style="font-size:10.5px;">{comp}</span>')
            if role and not any(t in role.lower() for t in junk_terms):
                badges.append(f'<span class="aria-pill aria-pill-grey" style="font-size:10.5px;">{role}</span>')
            badges_html = f"<div style='display:flex; justify-content:center; flex-wrap:wrap; gap:5px; margin-bottom:8px;'>{''.join(badges)}</div>" if badges else ""
            email_html = f'<a href="mailto:{contact.email}" style="font-size: 11.5px; color: #0066CC; text-decoration: none; font-weight: 500;">{contact.email}</a>' if contact.email else '<span style="font-size: 11px; color:#8E8E93;">Nessuna email registrata</span>'

            st.markdown(
                f"""
                <div style="
                    background: #FFFFFF;
                    border: 1px solid #E1E3EB;
                    border-radius: 16px;
                    padding: 16px;
                    text-align: center;
                    margin-bottom: 14px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.03);
                ">
                    <div style="
                        width: 50px;
                        height: 50px;
                        border-radius: 50%;
                        background: #0066CC;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        font-size: 18px;
                        font-weight: 700;
                        color: #FFFFFF !important;
                        margin: 0 auto 10px auto;
                    ">{initials}</div>
                    <h3 style="font-size: 15.5px; font-weight: 700; color: #1A1A1E; margin: 0 0 4px 0; letter-spacing: -0.02em;">
                        {full_display_name}
                    </h3>
                    {badges_html}
                    {email_html}
                </div>
                """,
                unsafe_allow_html=True,
            )
        elif session.entities:
            ent = session.entities[0]
            st.markdown(
                f"""
                <div style="
                    background: #FFFFFF;
                    border: 1px solid #E1E3EB;
                    border-radius: 16px;
                    padding: 16px;
                    text-align: center;
                    margin-bottom: 10px;
                ">
                    <div style="font-size: 26px; margin-bottom: 4px;">👤</div>
                    <h3 style="font-size: 15px; font-weight: 700; color: #1A1A1E; margin: 0;">{ent.raw_name}</h3>
                    <p style="font-size: 11.5px; color: #6E6E73; margin: 2px 0 0 0;">Contatto non in rubrica</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Quick Action: Aggiungi a Contatti (Expander fluido che si apre verso il basso)
            with st.expander("➕  Salva Contatto in Rubrica", expanded=False):
                st.markdown("<p style='font-size:12.5px; font-weight:700; margin-bottom:6px;'>Salva Persona</p>", unsafe_allow_html=True)
                raw_parts = ent.raw_name.strip().split(maxsplit=1)
                default_fn = raw_parts[0] if raw_parts else ent.raw_name.strip()
                default_ln = raw_parts[1] if len(raw_parts) > 1 else ""

                default_desc = "Persona"
                raw_lower = ent.raw_name.lower()
                if any(k in raw_lower for k in ("mamma", "madre", "papà", "padre", "fratello", "sorella", "famiglia")):
                    default_desc = "Famiglia"
                elif ent.context_clues and len(ent.context_clues) > 0:
                    clue = ent.context_clues[0].strip()
                    junk_clues = ["dell'utente", "riceverà", "ricevere", "email", "mail", "none", "n/d", "referente"]
                    if not any(j in clue.lower() for j in junk_clues):
                        default_desc = clue

                # Email vuota di default se non esplicitata per evitare attribuzioni errate
                q_fn = st.text_input("Nome:", value=default_fn, key=f"q_fn_{ent.raw_name}")
                q_ln = st.text_input("Cognome (opzionale):", value=default_ln, key=f"q_ln_{ent.raw_name}")
                q_desc = st.text_input("Descrizione / Relazione (opzionale):", value=default_desc, key=f"q_desc_{ent.raw_name}", help="Es. Famiglia, Amico, Collega")
                q_mail = st.text_input("Email (opzionale):", value="", key=f"q_mail_{ent.raw_name}")

                if st.button("Salva Persona", type="primary", use_container_width=True, key=f"btn_save_cnt_{ent.raw_name}"):
                    new_contact = Contact(
                        id=f"cnt_{uuid.uuid4().hex[:8]}",
                        first_name=q_fn.strip() or ent.raw_name,
                        last_name=q_ln.strip(),
                        email=q_mail.strip(),
                        company="N/D",
                        role=q_desc.strip() or default_desc,
                        aliases=[ent.raw_name, q_fn.strip()],
                        tags=["famiglia" if default_desc == "Famiglia" else "network"],
                        timezone=st.session_state.get("user_timezone", "Europe/Rome"),
                    )
                    run_async(st.session_state.repo.add_contact(new_contact))
                    ent.matched_contact_id = new_contact.id
                    ent.is_ambiguous = False
                    st.toast(f"Contatto {new_contact.first_name} {new_contact.last_name}".strip() + " salvato con successo!", icon="👤")
                    st.rerun()

            st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

        # ── MEMORIA STORICA & PEOPLE INTELLIGENCE ────────────────────────
        if session.person_history:
            ph = session.person_history
            last_date_str = ph.last_meeting_date or "Nessun incontro recente"
            prefs_html = "".join(
                f'<span class="aria-pill aria-pill-blue" style="font-size:10px; margin:2px 2px 2px 0;">{p}</span>'
                for p in ph.key_preferences[:4]
            ) or '<span style="font-size:11px; color:#6E6E73;">Nessuna preferenza registrata</span>'

            interactions_count = len(ph.recent_interactions)
            interactions_label = (
                f"{interactions_count} note meeting collegate"
                if interactions_count > 0
                else "Primo incontro archiviato"
            )

            st.markdown(
                f"""
                <div style="
                    background: rgba(255, 255, 255, 0.90);
                    backdrop-filter: blur(16px);
                    -webkit-backdrop-filter: blur(16px);
                    border: 1px solid #D2D2D7;
                    border-radius: 14px;
                    padding: 12px 14px;
                    margin-bottom: 14px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
                ">
                    <div style="display:flex; align-items:center; gap:6px; margin-bottom:6px;">
                        <span style="font-size:13px;">🧠</span>
                        <div style="font-size:11px; font-weight:700; color:#1A1A1E; text-transform:uppercase; letter-spacing:0.04em;">
                            Memoria & Preferenze
                        </div>
                    </div>
                    <div style="font-size:11.5px; color:#1A1A1E; margin-bottom:6px;">
                        <b>Ultimo sync:</b> <span style="color:#0066CC;">{last_date_str}</span>
                    </div>
                    <div style="margin-bottom:6px; display:flex; flex-wrap:wrap; gap:3px;">
                        {prefs_html}
                    </div>
                    <div style="font-size:10.5px; color:#6E6E73;">
                        🔗 {interactions_label}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # ── GRIGLIA METRICHE DINAMICHE REALI ────────────────────────────
        elapsed = st.session_state.get("elapsed_seconds", "—")
        has_conflict = any(a.status == ActionStatus.CONFLICT_DETECTED for a in session.proposed_actions)
        status_agenda = "Conflitto ⚠" if has_conflict else "Disponibile ✓"
        status_color = "#8A4800" if has_conflict else "#15692E"

        # Conteggi dinamici reali da session.proposed_actions
        tasks_count = sum(len(a.task_data.task_items or []) for a in session.proposed_actions if a.task_data)
        appointments_count = sum(1 for a in session.proposed_actions if a.calendar_data)

        st.markdown(
            f"""
            <div class="metrics-grid">
                <div class="metric-box">
                    <div class="metric-box-label">Elaborazione</div>
                    <div class="metric-box-val">{elapsed}s</div>
                </div>
                <div class="metric-box">
                    <div class="metric-box-label">Agenda</div>
                    <div class="metric-box-val" style="color: {status_color}; font-size:12.5px;">{status_agenda}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-box-label">Compiti</div>
                    <div class="metric-box-val">{tasks_count} estratti</div>
                </div>
                <div class="metric-box">
                    <div class="metric-box-label">Appuntamenti</div>
                    <div class="metric-box-val">{appointments_count} rilevati</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── SINTESI DELLA SESSIONE ─────────────────────────────────────
        st.markdown(
            f"""
            <div style="
                background: #FFFFFF;
                border: 1px solid #E1E3EB;
                border-radius: 14px;
                padding: 14px 16px;
                margin-bottom: 14px;
            ">
                <div style="font-size: 11px; text-transform: uppercase; color: #6E6E73; font-weight: 600; letter-spacing: 0.05em; margin-bottom: 6px;">
                    Riepilogo Chiamata
                </div>
                <p style="font-size: 12.5px; color: #1A1A1E; line-height: 1.45; margin: 0; font-weight: 500;">
                    {session.summary}
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── STATO DELLE ATTIVITÀ PROPOSTE ──────────────────────────────
        st.markdown(
            "<div style='font-size: 11px; text-transform: uppercase; color: #6E6E73; font-weight: 600; letter-spacing: 0.05em; margin: 12px 0 8px 0;'>Attività Rilevate</div>",
            unsafe_allow_html=True,
        )
        action_map = {
            ActionType.CALENDAR_EVENT: ("📅", "Calendario"),
            ActionType.EMAIL_DRAFT: ("✉️", "Email"),
            ActionType.KNOWLEDGE_NOTE: ("🧠", "Note"),
            ActionType.TASK_TODO: ("✅", "Compiti"),
            ActionType.TASK_EXPORT_REMINDERS: ("🍎", "Promemoria macOS"),
        }
        for act in session.proposed_actions:
            icon, label = action_map.get(act.action_type, ("•", str(act.action_type.value)))
            if act.status == ActionStatus.EXECUTED:
                badge = '<span class="aria-pill aria-pill-green" style="font-size:10px; padding:2px 8px;">Confermato ✓</span>'
            elif act.status == ActionStatus.CONFLICT_DETECTED:
                badge = '<span class="aria-pill aria-pill-amber" style="font-size:10px; padding:2px 8px;">Conflitto ⚠</span>'
            elif act.status == ActionStatus.REJECTED:
                badge = '<span class="aria-pill aria-pill-red" style="font-size:10px; padding:2px 8px;">Scartato</span>'
            else:
                badge = '<span class="aria-pill aria-pill-blue" style="font-size:10px; padding:2px 8px;">In attesa</span>'

            st.markdown(
                f"""
                <div style="
                    display:flex;
                    align-items:center;
                    justify-content:space-between;
                    padding: 8px 12px;
                    background: #FFFFFF;
                    border: 1px solid #E1E3EB;
                    border-radius: 10px;
                    margin-bottom: 6px;
                ">
                    <span style="font-size: 12.5px; font-weight: 500; color: #1A1A1E;">
                        {icon} {label}
                    </span>
                    {badge}
                </div>
                """,
                unsafe_allow_html=True,
            )

        # ── IMPOSTAZIONE FUSO ORARIO ─────────────────────────────────────
        current_tz = st.session_state.get("user_timezone", "Europe/Rome")
        with st.expander(f"🌐 Fuso Orario: {current_tz}", expanded=False):
            tz_choice = st.selectbox(
                "Fuso orario visualizzazione:",
                options=COMMON_TIMEZONES,
                index=COMMON_TIMEZONES.index(current_tz) if current_tz in COMMON_TIMEZONES else 0,
                key="sb_tz_picker",
                label_visibility="collapsed",
            )
            if tz_choice != current_tz:
                st.session_state.user_timezone = tz_choice
                st.rerun()

        # ── TASTO NUOVA CHIAMATA ─────────────────────────────────────────
        st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
        if st.button("← Nuova Sessione", use_container_width=True, type="secondary", key="btn_new_call"):
            for k in ["current_session", "audio_bytes", "audio_filename", "elapsed_seconds"]:
                st.session_state[k] = None
            st.rerun()
