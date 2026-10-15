"""
email_card.py — Card Bozza Email Follow-up in stile macOS Window / Gmail.
Design pulito, contrasto elevato, copywriting sobrio.
"""
from typing import Optional
import streamlit as st
from src.agent.domain.enums import ActionStatus
from src.agent.domain.models import ProposedAction
from src.agent.presentation.state import run_async, is_email_live


def render_email_card(mail_action: ProposedAction, know_action: Optional[ProposedAction], committer):
    """Renderizza la finestra per la bozza email di follow-up."""
    data = mail_action.email_data
    if not data:
        return

    email_live = is_email_live()
    service_badge = (
        '<span class="aria-pill aria-pill-green" style="font-size:10.5px;">🟢 Gmail Live</span>'
        if email_live else
        '<span class="aria-pill aria-pill-amber" style="font-size:10.5px;">🟡 Bozza Locale</span>'
    )

    with st.container(border=True):
        st.markdown(
            f"""
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
                <h3 style="font-size:18px; font-weight:700; color:#1A1A1E; margin:0; letter-spacing:-0.02em;">
                    ✉️ Email di Follow-up
                </h3>
                {service_badge}
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_left, col_right = st.columns([1, 1.4], gap="large")

        # Contesto a sinistra
        with col_left:
            st.markdown(
                "<p style='font-size:11.5px; font-weight:600; color:#6E6E73; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:8px;'>Destinatario</p>",
                unsafe_allow_html=True,
            )
            recipient_html = (
                f'<div style="background:#FFFFFF; border:1px solid #E1E3EB; border-radius:14px; padding:16px;">'
                f'<p style="font-size:14px; font-weight:700; color:#1A1A1E; margin:0 0 2px 0;">{data.recipient_name}</p>'
                f'<p style="font-size:12px; color:#0066CC; font-weight:500; margin:0 0 8px 0;">{data.recipient_email}</p>'
                f'<p style="font-size:12px; color:#3A3A40; margin:0; line-height:1.45;">Bozza generata automaticamente sulla base degli accordi presi durante la conversazione.</p>'
                f'</div>'
            )
            st.markdown(recipient_html, unsafe_allow_html=True)

            if know_action and know_action.knowledge_data and know_action.knowledge_data.bullet_insights:
                st.markdown(
                    "<p style='font-size:11.5px; font-weight:600; color:#6E6E73; text-transform:uppercase; letter-spacing:0.05em; margin:14px 0 6px 0;'>Punti Principali:</p>",
                    unsafe_allow_html=True,
                )
                for point in know_action.knowledge_data.bullet_insights[:3]:
                    st.markdown(
                        f"<div style='font-size:12px; color:#1A1A1E; margin-bottom:6px; padding-left:10px; border-left:2.5px solid #0066CC; line-height:1.4;'>• {point}</div>",
                        unsafe_allow_html=True,
                    )

        # Finestra a destra
        with col_right:
            titlebar_html = (
                '<div class="mac-titlebar" style="border-radius:14px 14px 0 0;">'
                '<span class="mac-dot mac-dot-red"></span>'
                '<span class="mac-dot mac-dot-yellow"></span>'
                '<span class="mac-dot mac-dot-green"></span>'
                '<span style="font-size:12px; font-weight:600; color:#1A1A1E; margin-left:8px;">Gmail — Nuovo Messaggio</span>'
                '</div>'
            )
            st.markdown(titlebar_html, unsafe_allow_html=True)

            is_exec = (mail_action.status == ActionStatus.EXECUTED)
            col_to_email, col_to_name = st.columns([1.5, 1])
            with col_to_email:
                data.recipient_email = st.text_input(
                    "A (Email destinatario):",
                    value=data.recipient_email,
                    key=f"recip_email_{mail_action.id}",
                    disabled=is_exec,
                )
            with col_to_name:
                data.recipient_name = st.text_input(
                    "Nome destinatario:",
                    value=data.recipient_name or "",
                    key=f"recip_name_{mail_action.id}",
                    disabled=is_exec,
                )

            data.subject = st.text_input("Oggetto:", value=data.subject, key=f"subj_{mail_action.id}", disabled=is_exec)
            data.body_markdown = st.text_area(
                "Testo del messaggio:", value=data.body_markdown, height=145, key=f"body_{mail_action.id}", disabled=is_exec
            )

            if not is_exec:
                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
                c1, c2 = st.columns([1.6, 1])
                with c1:
                    if st.button("✉️  Salva Bozza in Gmail", key=f"btn_mail_{mail_action.id}", type="primary", use_container_width=True):
                        ok, msg = run_async(committer.execute_action(mail_action, user_modified_payload=data.model_dump(mode="json")))
                        if ok:
                            st.toast(msg, icon="✉️")
                            st.rerun()
                with c2:
                    if st.button("Scarta", key=f"btn_mail_reject_{mail_action.id}", use_container_width=True):
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

