"""
landing.py — Schermata di Registrazione e Acquisizione di Aria.
Interfaccia Apple-grade, zero mock, acquisizione esclusivamente tramite registrazione microfono.
"""
import time
from datetime import datetime, timezone
from pathlib import Path
import sys

import streamlit as st

_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit.components.v1 as components
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

            st.markdown(
                """
                <div style="text-align: center; margin-bottom: 16px;">
                    <h2 style="font-size: 18px; font-weight: 700; color: #1A1A1E; margin: 0 0 4px 0;">
                        🎙️ Registrazione dal Vivo
                    </h2>
                    <p style="font-size: 13px; color: #6E6E73; margin: 0;">
                        Clicca il microfono per parlare. Premi <b>Invio ↵</b> o il tasto rosso di stop ⏹️ per completare.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Acquisizione esclusiva tramite Microfono
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

            # Hotkey universale: Invio ferma la registrazione o avvia l'analisi
            components.html(
                """
                <script>
                const doc = window.parent.document;
                if (!window.parent._ariaEnterListenerRegistered) {
                    window.parent._ariaEnterListenerRegistered = true;
                    doc.addEventListener('keydown', function(e) {
                        if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
                            // Non intercettare se l'utente sta scrivendo in un input testuale
                            if (e.target && ['INPUT', 'TEXTAREA'].includes(e.target.tagName)) {
                                if (!e.target.closest('[data-baseweb="select"]')) return;
                            }

                            // 1. Se sta registrando con stAudioInput, Invio clicca il pulsante di Stop
                            const stopBtn = doc.querySelector(
                                'button[data-testid="stAudioInputActionButton"][aria-label*="Stop"], ' +
                                'button[aria-label*="Stop recording"], ' +
                                'button[aria-label*="Ferma"], ' +
                                '[data-testid="stAudioInput"] button[aria-label*="Stop"]'
                            );
                            if (stopBtn) {
                                e.preventDefault();
                                e.stopPropagation();
                                stopBtn.click();
                                return;
                            }

                            // 2. Se l'audio è acquisito, Invio attiva il pulsante primario di analisi
                            const btn = doc.querySelector('button[kind="primary"]:not([disabled])');
                            if (btn) {
                                const txt = btn.innerText || "";
                                if (txt.includes("Avvia") || txt.includes("Analisi") || txt.includes("Invio")) {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    btn.click();
                                }
                            }
                        }
                    }, true);
                }
                </script>
                """,
                height=0,
                width=0,
            )

            # ── GESTIONE ECCEZIONI & ANTEPRIMA AUDIO ACQUISITO ────────────
            if has_audio:
                fname = st.session_state.get("audio_filename", "registrazione_vocale.wav")
                audio_size_mb = len(st.session_state.audio_bytes) / (1024 * 1024)

                # Hardening audio > 25MB
                if audio_size_mb > 25.0:
                    st.markdown(
                        f"""
                        <div style="background:#FFFBEB; border:1px solid #FCD34D; border-radius:12px; padding:12px 16px; margin:14px 0 10px 0;">
                            <div style="display:flex; align-items:center; gap:8px;">
                                <span style="font-size:16px;">⚠️</span>
                                <strong style="color:#B45309; font-size:13px;">Registrazione voluminosa ({audio_size_mb:.1f} MB)</strong>
                            </div>
                            <p style="color:#92400E; font-size:12px; margin:4px 0 0 0; line-height:1.45;">
                                La registrazione supera la soglia di 25MB. L'elaborazione con Gemini potrebbe richiedere maggiore tempo o impegno di memoria.
                            </p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                preview_html = (
                    f'<div style="background:#F0FBF4; border:1px solid rgba(52,199,89,0.35); border-radius:12px; padding:12px 16px; margin:16px 0 10px 0;">'
                    f'<div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:6px;">'
                    f'<div style="display:flex; align-items:center; gap:8px;">'
                    f'<span style="font-size:16px;">🎵</span>'
                    f'<strong style="font-size:13.5px; color:#1A1A1E;">{fname} ({audio_size_mb:.1f} MB)</strong>'
                    f'</div>'
                    f'<span class="aria-pill aria-pill-green" style="font-size:10px;">Audio Pronto ✓</span>'
                    f'</div>'
                    f'<p style="font-size:12px; color:#15692E; margin:0; font-weight:500;">'
                    f'Registrazione pronta. Premi <b>Invio ↵</b> sulla tastiera o clicca il pulsante in basso per avviare l\'analisi.'
                    f'</p>'
                    f'</div>'
                )
                st.markdown(preview_html, unsafe_allow_html=True)
                st.audio(st.session_state.audio_bytes)


            # ── FUSO ORARIO OPERATIVO ─────────────────────────────────────
            user_tz = st.session_state.get("user_timezone", "Europe/Rome")
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
                    user_tz = chosen_tz

            st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

            # ── PULSANTE DI INVIO ED ELABORAZIONE ──────────────────────────
            if has_audio:
                col_btn, col_del = st.columns([3.2, 1])
                with col_btn:
                    if st.button("⚡  Avvia Analisi della Riunione (Invio ↵)", type="primary", use_container_width=True, key="btn_run_analysis"):
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


        st.markdown("</div>", unsafe_allow_html=True)
