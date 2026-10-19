"""
landing.py — Schermata di Registrazione e Acquisizione di Aria.
Interfaccia Apple-grade, zero mock, acquisizione esclusivamente tramite registrazione microfonica dal vivo.
"""
import time
from datetime import datetime, timezone
from pathlib import Path
import sys

import streamlit as st

_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
from src.agent.presentation.state import run_async, get_orchestrator, COMMON_TIMEZONES


def render():
    """Renderizza la schermata principale centrata con la card di registrazione microfonica."""

    # ── HERO SECTION ─────────────────────────────────────────────────────────
    st.markdown(
        """
        <div style="text-align: center; padding: 28px 0 24px 0;">
            <div class="eyebrow-badge" style="margin-bottom: 12px;">
                <span>Aria • Assistente Esecutivo Vocale</span>
            </div>
            <h1 style="
                font-size: 38px;
                font-weight: 700;
                letter-spacing: -0.025em;
                color: #1A1A1E;
                margin: 0 0 10px 0;
                line-height: 1.15;
            ">Analisi Riunioni & Gestione Impegni</h1>
            <p style="
                font-size: 15.5px;
                color: #55555A;
                max-width: 580px;
                margin: 0 auto;
                line-height: 1.5;
                font-weight: 400;
            ">Registra una conversazione o una nota vocale dal vivo. Il sistema trascrive la discussione, verifica le disponibilità in agenda e prepara le bozze operative in tempo reale.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── MONOLITHIC AUDIO CARD ────────────────────────────────────────────────
    _, col_center, _ = st.columns([1, 2.2, 1])

    with col_center:
        st.markdown('<div class="landing-monolith">', unsafe_allow_html=True)
        with st.container(border=True):

            tab_voice, tab_text = st.tabs(["🎙️  Nota Vocale (Microfono)", "✍️  Prompt / Testo Diretto"])

            # ── FUSO ORARIO OPERATIVO (CONDIVISO) ─────────────────────────
            user_tz = st.session_state.get("user_timezone", "Europe/Rome")

            with tab_voice:
                st.markdown(
                    """
                    <div style="text-align: center; margin: 8px 0 14px 0;">
                        <h2 style="font-size: 17px; font-weight: 700; color: #1A1A1E; margin: 0 0 4px 0;">
                            Registrazione Vocale dal Vivo
                        </h2>
                        <p style="font-size: 12.5px; color: #6E6E73; margin: 0;">
                            Clicca il microfono per parlare. Al termine clicca il tasto rosso di stop ⏹️
                        </p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                mic = st.audio_input(
                    "Registra nota vocale",
                    label_visibility="collapsed",
                    key="aria_mic_recorder",
                )
                if mic is not None:
                    raw_bytes = mic.getvalue() if hasattr(mic, "getvalue") else mic.read()
                    if raw_bytes:
                        st.session_state.audio_bytes = raw_bytes
                        st.session_state.audio_filename = "registrazione_vocale.wav"

                has_audio = bool(st.session_state.get("audio_bytes"))

                if has_audio:
                    fname = st.session_state.get("audio_filename", "registrazione_vocale.wav")
                    audio_size_mb = len(st.session_state.audio_bytes) / (1024 * 1024)

                    if audio_size_mb > 25.0:
                        st.markdown(
                            f"""
                            <div style="background:#FFFBEB; border:1px solid #FCD34D; border-radius:12px; padding:12px 16px; margin:14px 0 10px 0;">
                                <div style="display:flex; align-items:center; gap:8px;">
                                    <span style="font-size:16px;">⚠️</span>
                                    <strong style="color:#B45309; font-size:13px;">Registrazione voluminosa ({audio_size_mb:.1f} MB)</strong>
                                </div>
                                <p style="color:#92400E; font-size:12px; margin:4px 0 0 0; line-height:1.45;">
                                    La registrazione supera 25MB. L'elaborazione potrebbe richiedere maggiore tempo.
                                </p>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                    preview_html = (
                        f'<div style="background:#F0FBF4; border:1px solid rgba(52,199,89,0.35); border-radius:12px; padding:12px 16px; margin:14px 0 10px 0;">'
                        f'<div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:6px;">'
                        f'<div style="display:flex; align-items:center; gap:8px;">'
                        f'<span style="font-size:16px;">🎵</span>'
                        f'<strong style="font-size:13px; color:#1A1A1E;">{fname} ({audio_size_mb:.1f} MB)</strong>'
                        f'</div>'
                        f'<span class="aria-pill aria-pill-green" style="font-size:10px;">Audio Pronto ✓</span>'
                        f'</div>'
                        f'<p style="font-size:12px; color:#15692E; margin:0; font-weight:500;">'
                        f'Registrazione pronta. Clicca il pulsante in basso per avviare l\'analisi.'
                        f'</p>'
                        f'</div>'
                    )
                    st.markdown(preview_html, unsafe_allow_html=True)
                    st.audio(st.session_state.audio_bytes)

                    col_btn, col_del = st.columns([3.2, 1])
                    with col_btn:
                        if st.button("⚡  Avvia Analisi della Riunione", type="primary", use_container_width=True, key="btn_run_analysis"):
                            t0 = time.perf_counter()
                            orchestrator = get_orchestrator()

                            with st.spinner("Trascrizione ed estrazione operativa in corso con Gemini..."):
                                result = run_async(
                                    orchestrator.execute(
                                        audio_bytes=st.session_state.audio_bytes,
                                        filename=st.session_state.audio_filename,
                                        anchor_utc=datetime.now(timezone.utc),
                                        user_tz=user_tz,
                                    )
                                )

                            st.session_state.elapsed_seconds = round(time.perf_counter() - t0, 2)
                            st.session_state.current_session = result
                            st.rerun()

                    with col_del:
                        if st.button("Rimuovi", type="secondary", use_container_width=True, key="btn_clear_audio"):
                            st.session_state.audio_bytes = None
                            st.session_state.audio_filename = None
                            st.rerun()
                else:
                    st.button("⚡  Avvia Analisi (In attesa di registrazione...)", type="primary", use_container_width=True, disabled=True, key="btn_disabled_hint")
                    st.markdown(
                        "<p style='font-size:12px; color:#6E6E73; text-align:center; margin:8px 0 0 0;'>"
                        "ℹ️ Clicca il microfono per registrare. Premi il pulsante di stop quando hai finito."
                        "</p>",
                        unsafe_allow_html=True,
                    )

            with tab_text:
                st.markdown(
                    """
                    <div style="text-align: center; margin: 8px 0 14px 0;">
                        <h2 style="font-size: 17px; font-weight: 700; color: #1A1A1E; margin: 0 0 4px 0;">
                            Prompt o Resoconto della Giornata
                        </h2>
                        <p style="font-size: 12.5px; color: #6E6E73; margin: 0;">
                            Incolla una trascrizione, un messaggio WhatsApp o descrivi i tuoi impegni ed email da inviare.
                        </p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                with st.form("landing_text_form", clear_on_submit=False):
                    txt_prompt = st.text_area(
                        "Prompt testuale:",
                        height=140,
                        placeholder="Es. Allora devo mandare un'email a me stesso con gli appunti, una mail a mia mamma in inglese dove le dico che le voglio bene, e ricordarmi di fare la spesa e dare da bere alle piante...",
                        key="landing_text_prompt",
                        label_visibility="collapsed",
                    )
                    submit_btn = st.form_submit_button(
                        "⚡  Avvia Analisi del Testo",
                        type="primary",
                        use_container_width=True,
                    )
                    if submit_btn:
                        if txt_prompt and txt_prompt.strip():
                            t0 = time.perf_counter()
                            orchestrator = get_orchestrator()

                            with st.spinner("Estrazione ed elaborazione semantica con Gemini..."):
                                result = run_async(
                                    orchestrator.execute(
                                        text_prompt=txt_prompt.strip(),
                                        anchor_utc=datetime.now(timezone.utc),
                                        user_tz=user_tz,
                                    )
                                )

                            st.session_state.elapsed_seconds = round(time.perf_counter() - t0, 2)
                            st.session_state.current_session = result
                            st.rerun()
                        else:
                            st.warning("ℹ️ Inserisci un testo prima di avviare l'analisi.")


            # ── FUSO ORARIO OPERATIVO (FOOTER CARD) ────────────────────────
            st.markdown("<div style='height: 12px; border-top: 1px solid #E5E7EB; margin-top: 14px;'></div>", unsafe_allow_html=True)
            col_tz_label, col_tz_pick = st.columns([1.4, 1.6])
            with col_tz_label:
                st.markdown(
                    "<p style='font-size:12px; color:#55555A; font-weight:600; margin:8px 0 0 0;'>🌐 Fuso Orario Agenda:</p>",
                    unsafe_allow_html=True,
                )
            with col_tz_pick:
                tz_idx = COMMON_TIMEZONES.index(user_tz) if user_tz in COMMON_TIMEZONES else 0
                chosen_tz = st.selectbox(
                    "Fuso Orario",
                    options=COMMON_TIMEZONES,
                    index=tz_idx,
                    key="landing_tz_picker",
                    label_visibility="collapsed",
                )
                if chosen_tz != user_tz:
                    st.session_state.user_timezone = chosen_tz

        st.markdown("</div>", unsafe_allow_html=True)
