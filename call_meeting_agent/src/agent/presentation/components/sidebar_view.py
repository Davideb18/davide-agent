"""
sidebar_view.py — Colonna sinistra (Sidebar) del CRM Aria.
Design pulito, contrasto elevato, zero testi da chatbot AI.
"""
import html
import re
import uuid
import streamlit as st
from src.agent.domain.enums import ActionStatus, ActionType
from src.agent.domain.models import SessionExtractionResult, Contact, ExtractedEntity
from src.agent.presentation.state import (
    run_async,
    is_calendar_live,
    is_email_live,
    COMMON_TIMEZONES,
)


def _resolve_entity_email(ent: ExtractedEntity, session: SessionExtractionResult) -> str:
    """Risolve l'email di un'entità controllando l'attributo email, le azioni email e il testo/prompt."""
    # 1. Se già presente direttamente sull'entità
    if getattr(ent, "email", None) and ent.email.strip():
        return ent.email.strip()

    ent_name = (ent.raw_name or "").lower().strip()
    user_profile = st.session_state.get("user_profile")
    self_names = {"me", "stesso", "io", "myself"}
    if user_profile:
        if user_profile.first_name: self_names.add(user_profile.first_name.lower())
        if user_profile.last_name: self_names.add(user_profile.last_name.lower())
        if user_profile.full_name: self_names.add(user_profile.full_name.lower())
        for a in user_profile.aliases: self_names.add(a.lower())

    is_self = any(k in ent_name for k in self_names)

    # 2. Controlla tra le proposed_actions di tipo EMAIL_DRAFT
    for act in session.proposed_actions:
        if act.action_type == ActionType.EMAIL_DRAFT and act.email_data and act.email_data.recipient_email:
            r_name = (act.email_data.recipient_name or "").lower().strip()
            r_email = act.email_data.recipient_email.strip()
            if ent_name in r_name or r_name in ent_name:
                ent.email = r_email
                return r_email
            if is_self and (any(k in r_name for k in self_names) or (user_profile and user_profile.email and user_profile.email.lower() in r_email.lower())):
                ent.email = r_email
                return r_email

    # 3. Controlla indirizzi email nel testo/transcript
    full_text = f"{session.raw_transcript or ''} {getattr(session, 'summary', '') or ''}"
    found_emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', full_text)
    if is_self and found_emails:
        ent.email = found_emails[0]
        return found_emails[0]

    return ""


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

        # ── SCHEDE CONTATTI / PERSONE RILEVATE ─────────────────────────
        st.markdown(
            "<div style='font-size:11px; font-weight:700; color:#8E8E93; text-transform:uppercase; letter-spacing:0.05em; margin:14px 0 8px 0;'>"
            "👥 Persone e Contatti Rilevati</div>",
            unsafe_allow_html=True,
        )

        matched_entities = [e for e in session.entities if e.matched_contact_id]
        other_entities = [e for e in session.entities if not e.matched_contact_id]

        # Se ci sono contatti riconosciuti nella rubrica interna
        if matched_entities:
            for ent in matched_entities[:5]:
                contact = None
                if hasattr(st.session_state, "repo") and st.session_state.repo:
                    contact = run_async(st.session_state.repo.get_contact_by_id(ent.matched_contact_id))

                if contact:
                    fn = (contact.first_name or "").strip()
                    ln = (contact.last_name or "").strip()
                    initials = f"{fn[:1]}{ln[:1]}".upper() if fn and ln else (fn[:2].upper() if len(fn) >= 2 else "👤")
                    full_display_name = f"{fn} {ln}".strip() or ent.raw_name
                    badges = []
                    comp = (contact.company or "").strip()
                    role = (contact.role or "").strip()
                    junk_terms = ["dell'utente", "riceverà", "ricevere", "email", "mail", "none", "n/d", "referente"]
                    if comp and not any(t in comp.lower() for t in junk_terms):
                        badges.append(f'<span class="aria-pill aria-pill-blue" style="font-size:10px;">{html.escape(comp)}</span>')
                    if role and not any(t in role.lower() for t in junk_terms):
                        badges.append(f'<span class="aria-pill aria-pill-grey" style="font-size:10px;">{html.escape(role)}</span>')
                    badges_html = f"<div style='display:flex; justify-content:center; flex-wrap:wrap; gap:4px; margin-bottom:6px;'>{''.join(badges)}</div>" if badges else ""
                    disp_email = contact.email or _resolve_entity_email(ent, session)
                    email_html = f'<div style="font-size:11px; color:#0066CC; font-weight:500;">📧 {html.escape(disp_email)}</div>' if disp_email else ''

                    st.markdown(
                        f"""
                        <div style="
                            background: #FFFFFF;
                            border: 1px solid #E1E3EB;
                            border-radius: 14px;
                            padding: 12px;
                            text-align: center;
                            margin-bottom: 10px;
                            box-shadow: 0 1px 3px rgba(0,0,0,0.03);
                        ">
                            <div style="
                                width: 40px;
                                height: 40px;
                                border-radius: 50%;
                                background: #0066CC;
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                font-size: 15px;
                                font-weight: 700;
                                color: #FFFFFF !important;
                                margin: 0 auto 6px auto;
                            ">{initials}</div>
                            <h4 style="font-size: 14px; font-weight: 700; color: #1A1A1E; margin: 0 0 2px 0;">
                                {full_display_name}
                            </h4>
                            <div style="font-size: 10.5px; color: #8E8E93; margin-bottom: 6px;">Profilo Rubrica / Interlocutore</div>
                            {badges_html}
                            {email_html}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        # Mostra anche altre persone/familiari citati nella conversazione (es. Mamma, Me stesso)
        if other_entities:
            cards_html = []
            for o_ent in other_entities[:4]:
                ent_mail = _resolve_entity_email(o_ent, session)
                if ent_mail:
                    badge_status = '<span class="aria-pill aria-pill-blue" style="font-size:9.5px; padding:1px 6px;">Email Rilevata</span>'
                    mail_line = f'<div style="font-size:11px; color:#0066CC; font-weight:600; margin-top:2px; word-break:break-all;">📧 {html.escape(ent_mail)}</div>'
                else:
                    badge_status = '<span class="aria-pill aria-pill-grey" style="font-size:9.5px; padding:1px 6px;">Nessuna email</span>'
                    mail_line = ''

                cards_html.append(
                    f'<div style="background:#FFFFFF; border:1px solid #E1E3EB; border-radius:10px; padding:8px 10px; margin-bottom:6px; box-shadow:0 1px 3px rgba(0,0,0,0.02);">'
                    f'<div style="display:flex; align-items:center; justify-content:space-between; gap:6px;">'
                    f'<span style="font-size:12px; font-weight:700; color:#1A1A1E;">👤 {html.escape(o_ent.raw_name)}</span>'
                    f'{badge_status}'
                    f'</div>'
                    f'{mail_line}'
                    f'</div>'
                )

            st.markdown(
                f"<div style='margin-bottom:10px;'>"
                f"<div style='font-size:10.5px; color:#8E8E93; margin-bottom:6px;'>Altre persone citate nella sessione:</div>"
                f"{''.join(cards_html)}"
                f"</div>",
                unsafe_allow_html=True,
            )

            # Quick Action: Salva ciascuna persona non ancora presente in rubrica
            for idx, target_ent in enumerate(other_entities[:4]):
                ent_email = _resolve_entity_email(target_ent, session)
                raw_lower = target_ent.raw_name.lower().strip()
                user_profile = st.session_state.get("user_profile")
                self_names = {"me", "stesso", "io", "myself"}
                if user_profile:
                    if user_profile.first_name: self_names.add(user_profile.first_name.lower())
                    if user_profile.last_name: self_names.add(user_profile.last_name.lower())
                    if user_profile.full_name: self_names.add(user_profile.full_name.lower())
                    for a in user_profile.aliases: self_names.add(a.lower())

                is_self = any(k in raw_lower for k in self_names)

                if is_self:
                    default_fn = user_profile.first_name if user_profile else "Me"
                    default_ln = user_profile.last_name if user_profile else ""
                    default_desc = user_profile.role if (user_profile and user_profile.role) else "Personale / Utente"
                else:
                    raw_parts = target_ent.raw_name.strip().split(maxsplit=1)
                    default_fn = raw_parts[0] if raw_parts else target_ent.raw_name.strip()
                    default_ln = raw_parts[1] if len(raw_parts) > 1 else ""
                    default_desc = "Persona"
                    if any(k in raw_lower for k in ("mamma", "madre", "papà", "padre", "fratello", "sorella", "famiglia")):
                        default_desc = "Famiglia"
                    elif target_ent.context_clues and len(target_ent.context_clues) > 0:
                        clue = target_ent.context_clues[0].strip()
                        junk_clues = ["dell'utente", "riceverà", "ricevere", "email", "mail", "none", "n/d", "referente"]
                        if not any(j in clue.lower() for j in junk_clues):
                            default_desc = clue

                exp_title = f"➕ Salva '{target_ent.raw_name}' in Rubrica"
                if ent_email:
                    exp_title += f" ({ent_email})"

                safe_id = f"{idx}_{target_ent.raw_name.replace(' ', '_')}"
                with st.expander(exp_title, expanded=False):
                    st.markdown(
                        f"<p style='font-size:12px; font-weight:700; margin-bottom:6px;'>Salva Persona in Rubrica ({html.escape(target_ent.raw_name)})</p>",
                        unsafe_allow_html=True,
                    )
                    q_fn = st.text_input("Nome:", value=default_fn, key=f"q_fn_{safe_id}")
                    q_ln = st.text_input("Cognome (opzionale):", value=default_ln, key=f"q_ln_{safe_id}")
                    q_desc = st.text_input(
                        "Descrizione / Relazione (opzionale):",
                        value=default_desc,
                        key=f"q_desc_{safe_id}",
                        help="Es. Famiglia, Amico, Collega, Personale / Utente",
                    )
                    q_mail = st.text_input("Email (opzionale):", value=ent_email, key=f"q_mail_{safe_id}")

                    if st.button("Salva Persona", type="primary", use_container_width=True, key=f"btn_save_cnt_{safe_id}"):
                        new_contact = Contact(
                            id=f"cnt_{uuid.uuid4().hex[:8]}",
                            first_name=q_fn.strip() or target_ent.raw_name,
                            last_name=q_ln.strip(),
                            email=q_mail.strip(),
                            company=(user_profile.company if (is_self and user_profile and user_profile.company) else "N/D"),
                            role=q_desc.strip() or default_desc,
                            aliases=[target_ent.raw_name, q_fn.strip(), f"{q_fn.strip()} {q_ln.strip()}".strip()],
                            tags=["utente"] if is_self else (["famiglia"] if default_desc == "Famiglia" else ["network"]),
                            timezone=st.session_state.get("user_timezone", "Europe/Rome"),
                        )
                        run_async(st.session_state.repo.add_contact(new_contact))
                        if "knowledge" in st.session_state and st.session_state.knowledge:
                            try:
                                run_async(st.session_state.knowledge.save_or_update_contact(new_contact))
                            except Exception:
                                pass
                        target_ent.matched_contact_id = new_contact.id
                        target_ent.is_ambiguous = False
                        target_ent.email = new_contact.email

                        # Sincronizza anche con le bozze email pendenti
                        for act in session.proposed_actions:
                            if act.action_type == ActionType.EMAIL_DRAFT and act.email_data:
                                r_name = (act.email_data.recipient_name or "").lower().strip()
                                if (
                                    target_ent.raw_name.lower() in r_name
                                    or r_name in target_ent.raw_name.lower()
                                    or (is_self and any(k in r_name for k in self_names))
                                ):
                                    if not act.email_data.recipient_email:
                                        act.email_data.recipient_email = new_contact.email
                                    # Resetta la chiave session_state per riflettere l'email inserita
                                    st.session_state.pop(f"recip_email_{act.id}", None)

                        run_async(st.session_state.repo.save_session(session))
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
            for k in ["current_session", "audio_bytes", "audio_filename", "elapsed_seconds", "text_prompt"]:
                st.session_state[k] = None
            st.rerun()
