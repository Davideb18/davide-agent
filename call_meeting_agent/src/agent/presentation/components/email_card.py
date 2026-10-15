"""
email_card.py — Card Bozza Email Follow-up in stile macOS Window / Gmail.
Design pulito, contrasto elevato, copywriting sobrio.
"""
from typing import Optional
import streamlit as st
from src.agent.domain.enums import ActionStatus
from src.agent.domain.models import ProposedAction
from src.agent.presentation.state import run_async


def render_email_card(mail_action: ProposedAction, know_action: Optional[ProposedAction], committer):
    """Renderizza la finestra per la bozza email di follow-up."""
    data = mail_action.email_data
    if not data:
        return

    with st.container(border=True):
        st.markdown(
            "<h3 style='font-size:18px; font-weight:700; color:#1A1A1E; margin:0 0 14px 0; letter-spacing:-0.02em;'>"
            "✉️ Email di Follow-up</h3>",
            unsafe_allow_html=True,
        )

        col_left, col_right = st.columns([1, 1.4], gap="large")

        # Contesto a sinistra
        with col_left:
            st.markdown(
                "<p style='font-size:11.5px; font-weight:600; color:#6E6E73; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:8px;'>Destinatario</p>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"""
                <div style="background: #FFFFFF; border: 1px solid #E1E3EB; border-radius: 14px; padding: 16px;">
                    <p style="font-size: 14px; font-weight: 700; color: #1A1A1E; margin: 0 0 2px 0;">
                        {data.recipient_name}
                    </p>
                    <p style="font-size: 12px; color: #0066CC; font-weight: 500; margin: 0 0 8px 0;">
                        {data.recipient_email}
                    </p>
                    <p style="font-size: 12px; color: #3A3A40; margin: 0; line-height: 1.45;">
                        Bozza generata automaticamente sulla base degli accordi presi durante la conversazione.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if know_action and know_action.knowledge_data:
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
            st.markdown(
                """
                <div class="mac-titlebar" style="border-radius: 14px 14px 0 0;">
                    <span class="mac-dot mac-dot-red"></span>
                    <span class="mac-dot mac-dot-yellow"></span>
                    <span class="mac-dot mac-dot-green"></span>
                    <span style="font-size:12px; font-weight:600; color:#1A1A1E; margin-left:8px;">
                        Gmail — Nuovo Messaggio
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.caption(f"A: **{data.recipient_email}**")
            data.subject = st.text_input("Oggetto:", value=data.subject, key=f"subj_{mail_action.id}")
            data.body_markdown = st.text_area(
                "Testo del messaggio:", value=data.body_markdown, height=145, key=f"body_{mail_action.id}"
            )

            if mail_action.status != ActionStatus.EXECUTED:
                st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
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
            else:
                st.markdown('<span class="aria-pill aria-pill-green">✓ Bozza Salvata in Gmail</span>', unsafe_allow_html=True)
