"""
email_card.py — Card Bozza Email Follow-up in stile macOS Window / Gmail.
Design pulito, contrasto elevato, reattività sul cambio destinatario e copywriting sobrio.
"""
from typing import Optional, List
import streamlit as st
from src.agent.domain.enums import ActionStatus
from src.agent.domain.models import ProposedAction, Contact
from src.agent.presentation.state import run_async, is_email_live


def render_email_card(mail_action: ProposedAction, know_action: Optional[ProposedAction], committer):
    """Renderizza la finestra per la bozza email di follow-up con sincronizzazione reattiva del destinatario."""
    data = mail_action.email_data
    if not data:
        return

    # Recupero contatti salvati per auto-suggerimento email al cambio nome
    repo = st.session_state.get("repo")
    saved_contacts: List[Contact] = []
    if repo and hasattr(repo, "get_contacts"):
        try:
            saved_contacts = run_async(repo.get_contacts()) or []
        except Exception:
            saved_contacts = []

    # Chiavi univoche per gli input del destinatario
    name_key = f"recip_name_{mail_action.id}"
    email_key = f"recip_email_{mail_action.id}"
    prev_name_key = f"prev_recip_name_{mail_action.id}"

    # Inizializza session state se assente
    if name_key not in st.session_state:
        st.session_state[name_key] = data.recipient_name or ""
    if email_key not in st.session_state:
        st.session_state[email_key] = data.recipient_email or ""
    if prev_name_key not in st.session_state:
        st.session_state[prev_name_key] = st.session_state[name_key]

    # Rileva cambio di nome per aggiornare o resettare l'email correlata
    current_name = st.session_state[name_key].strip()
    last_known_name = st.session_state[prev_name_key].strip()

    if current_name != last_known_name:
        st.session_state[prev_name_key] = current_name
        data.recipient_name = current_name
        
        # Cerca corrispondenza nei contatti salvati
        clean_target = current_name.lower()
        matched_contact = None
        for c in saved_contacts:
            full = f"{c.first_name} {c.last_name}".lower().strip()
            aliases = [a.lower().strip() for a in (c.aliases or [])]
            if clean_target == full or clean_target == c.first_name.lower().strip() or clean_target in aliases:
                matched_contact = c
                break
        
        if matched_contact and matched_contact.email:
            data.recipient_email = matched_contact.email
            st.session_state[email_key] = matched_contact.email
            st.toast(f"Email di {current_name} recuperata dalla rubrica: {matched_contact.email}", icon="👤")
        elif not matched_contact and last_known_name and not current_name.lower().startswith(last_known_name.lower()):
            # Cambio di destinatario verso persona sconosciuta/senza email: svuota l'email per evitare attribuzioni errate
            data.recipient_email = ""
            st.session_state[email_key] = ""

    session = st.session_state.get("current_session")
    lang = getattr(session, "detected_language", "it") if session else "it"
    is_en = bool(lang and str(lang).lower().startswith("en"))

    email_live = is_email_live()
    live_lbl = "🟢 Gmail Live" if is_en else "🟢 Gmail Live"
    draft_lbl = "🟡 Local Draft" if is_en else "🟡 Bozza Locale"
    service_badge = (
        f'<span class="aria-pill aria-pill-green" style="font-size:10.5px; font-weight:700;">{live_lbl}</span>'
        if email_live else
        f'<span class="aria-pill aria-pill-amber" style="font-size:10.5px; font-weight:700;">{draft_lbl}</span>'
    )

    with st.container(border=True):
        is_followup = bool(data.linked_calendar_action_id)
        if is_followup:
            email_header = "✉️ Follow-up Email" if is_en else "✉️ Email di Follow-up"
            desc_text = "Draft reactively synced with Calendar schedule." if is_en else "Bozza allineata reattivamente con l'orario del Calendario."
        else:
            email_header = "✉️ Email Message" if is_en else "✉️ Messaggio Email"
            desc_text = "Draft generated automatically based on discussion and notes." if is_en else "Bozza generata automaticamente sulla base della conversazione."

        st.markdown(
            f"""
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
                <h3 style="font-size:19px; font-weight:800; color:#1D1D1F; margin:0; letter-spacing:-0.02em;">
                    {email_header}
                </h3>
                {service_badge}
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_left, col_right = st.columns([1, 1.4], gap="large")

        # Contesto a sinistra
        with col_left:
            recipient_section_lbl = "Recipient" if is_en else "Destinatario"
            st.markdown(
                f"<p style='font-size:11px; font-weight:700; color:#8E8E93; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:6px;'>{recipient_section_lbl}</p>",
                unsafe_allow_html=True,
            )
            default_disp_name = "Recipient" if is_en else "Destinatario"
            disp_name = st.session_state.get(name_key, data.recipient_name or default_disp_name)
            disp_email = st.session_state.get(email_key, data.recipient_email or "")

            if disp_email:
                email_line = f'<p style="font-size:12.5px; color:#0066CC; font-weight:600; margin:0 0 8px 0;">{disp_email}</p>'
            else:
                no_email_lbl = "(No email address provided)" if is_en else "(Nessun indirizzo email fornito)"
                email_line = f'<p style="font-size:12px; color:#8E8E93; font-style:italic; margin:0 0 8px 0;">{no_email_lbl}</p>'

            recipient_html = (
                f'<div style="background:#FFFFFF; border:1px solid #E5E5EA; border-radius:14px; padding:16px; box-shadow:0 2px 8px rgba(0,0,0,0.03);">'
                f'<p style="font-size:15px; font-weight:800; color:#1D1D1F; margin:0 0 4px 0;">{disp_name}</p>'
                f'{email_line}'
                f'<p style="font-size:12px; color:#48484A; margin:0; line-height:1.45;">{desc_text}</p>'
                f'</div>'
            )
            st.markdown(recipient_html, unsafe_allow_html=True)

            if know_action and know_action.knowledge_data and know_action.knowledge_data.bullet_insights:
                key_pts_lbl = "Key Takeaways:" if is_en else "Punti Principali:"
                st.markdown(
                    f"<p style='font-size:11px; font-weight:700; color:#8E8E93; text-transform:uppercase; letter-spacing:0.05em; margin:14px 0 6px 0;'>{key_pts_lbl}</p>",
                    unsafe_allow_html=True,
                )
                for point in know_action.knowledge_data.bullet_insights[:3]:
                    st.markdown(
                        f"<div style='font-size:12px; color:#1D1D1F; margin-bottom:6px; padding-left:10px; border-left:2.5px solid #007AFF; line-height:1.4;'>• {point}</div>",
                        unsafe_allow_html=True,
                    )

        # Finestra a destra
        with col_right:
            new_msg_lbl = "Gmail — New Message" if is_en else "Gmail — Nuovo Messaggio"
            titlebar_html = (
                '<div class="mac-titlebar" style="border-radius:14px 14px 0 0;">'
                '<span class="mac-dot mac-dot-red"></span>'
                '<span class="mac-dot mac-dot-yellow"></span>'
                '<span class="mac-dot mac-dot-green"></span>'
                f'<span style="font-size:12px; font-weight:600; color:#1D1D1F; margin-left:8px;">{new_msg_lbl}</span>'
                '</div>'
            )
            st.markdown(titlebar_html, unsafe_allow_html=True)

            if data.linked_calendar_action_id:
                link_lbl = "Draft reactively synced with Calendar schedule" if is_en else "Bozza allineata reattivamente con l'orario del Calendario"
                st.markdown(
                    f"<div style='background:#EFF6FF; border:1px solid #BFDBFE; border-radius:8px; padding:6px 10px; margin-bottom:8px; display:flex; align-items:center; gap:6px;'>"
                    f"<span style='font-size:12px;'>🔗</span>"
                    f"<span style='font-size:11px; color:#1D4ED8; font-weight:600;'>{link_lbl}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            is_exec = (mail_action.status == ActionStatus.EXECUTED)
            col_to_email, col_to_name = st.columns([1.4, 1.1])
            with col_to_email:
                email_input_lbl = "To (Recipient email):" if is_en else "A (Email destinatario):"
                email_placeholder = "e.g. name@email.com (optional)" if is_en else "es. nome@email.com (facoltativa)"
                new_email = st.text_input(
                    email_input_lbl,
                    value=st.session_state[email_key],
                    key=email_key,
                    placeholder=email_placeholder,
                    disabled=is_exec,
                )
                data.recipient_email = new_email

            with col_to_name:
                name_input_lbl = "Recipient name:" if is_en else "Nome destinatario:"
                name_placeholder = "e.g. Mom, Marco..." if is_en else "es. Mamma, Marco..."
                new_name = st.text_input(
                    name_input_lbl,
                    value=st.session_state[name_key],
                    key=name_key,
                    placeholder=name_placeholder,
                    disabled=is_exec,
                )
                data.recipient_name = new_name

            ver = st.session_state.get(f"email_ver_{mail_action.id}", 0)
            subj_lbl = "Subject:" if is_en else "Oggetto:"
            data.subject = st.text_input(
                subj_lbl,
                value=data.subject,
                key=f"subj_{mail_action.id}_{ver}",
                disabled=is_exec,
            )
            body_lbl = "Message body:" if is_en else "Testo del messaggio:"
            data.body_markdown = st.text_area(
                body_lbl,
                value=data.body_markdown,
                height=155,
                key=f"body_{mail_action.id}_{ver}",
                disabled=is_exec,
            )

            if not is_exec:
                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
                c1, c2 = st.columns([1.6, 1])
                with c1:
                    save_btn_lbl = "✉️  Save Draft in Gmail" if is_en else "✉️  Salva Bozza in Gmail"
                    if st.button(save_btn_lbl, key=f"btn_mail_{mail_action.id}", type="primary", use_container_width=True):
                        ok, msg = run_async(committer.execute_action(mail_action, user_modified_payload=data.model_dump(mode="json")))
                        if ok:
                            st.toast(msg, icon="✉️")
                            st.rerun()
                with c2:
                    rej_lbl = "Discard" if is_en else "Scarta"
                    if st.button(rej_lbl, key=f"btn_mail_reject_{mail_action.id}", use_container_width=True):
                        run_async(committer.reject_action(mail_action))
                        st.rerun()
                st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
                st.markdown(
                    f"""
                    <div style="
                        background: #F0FDF4;
                        border: 1px solid #BBF7D0;
                        border-radius: 14px;
                        padding: 16px 20px;
                        margin-top: 10px;
                        margin-bottom: 24px;
                        box-shadow: 0 1px 4px rgba(0,0,0,0.03);
                    ">
                        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
                            <span class="aria-pill aria-pill-green" style="font-size:11px; font-weight:700;">
                                ✓ Bozza Creata con Successo
                            </span>
                            <span style="font-size:11px; color:#15803D; font-family:monospace; font-weight:600;">
                                ID: #{mail_action.id}
                            </span>
                        </div>
                        <p style="font-size:12.5px; color:#166534; margin:0 0 4px 0; font-weight:600;">
                            Destinatario: {data.recipient_name} &lt;{data.recipient_email}&gt;
                        </p>
                        <p style="font-size:12px; color:#15803D; margin:0; line-height:1.45;">
                            Oggetto: <b>{data.subject}</b><br/>
                            Bozza archiviata in modo sicuro nel client di posta per revisione e invio finale. Nessuna email è stata trasmessa automaticamente.
                        </p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # Spazio generoso per distanziare la card email dalla card successiva
    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
