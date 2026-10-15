"""
landing.py — Schermata di Ingestion e Landing di Aria.
Zero mock, audio reale (upload o microfono), design sobrio Apple-grade.
Pulsante di invio ed elaborazione SEMPRE visibile ed esplicito.
"""
import time
from datetime import datetime, timezone
from pathlib import Path
import sys

import streamlit as st

_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.agent.presentation.state import run_async, get_orchestrator


def render():
    """Renderizza la schermata principale centrata con la Monolithic Audio Card."""

    # ── HERO SECTION ─────────────────────────────────────────────────────────
    st.markdown(
        """
        <div style="text-align: center; padding: 24px 0 20px 0;">
            <div class="eyebrow-badge" style="margin-bottom: 12px;">
                <span>Aria • Assistente Riunioni</span>
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
            ">Registra una conversazione dal vivo o carica un file audio. Il sistema trascrive la discussione, verifica la disponibilità nella tua agenda Apple Calendar e prepara le bozze operative.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── MONOLITHIC AUDIO CARD ────────────────────────────────────────────────
    _, col_center, _ = st.columns([1, 2.3, 1])

    with col_center:
        st.markdown('<div class="landing-monolith">', unsafe_allow_html=True)
        with st.container(border=True):

            st.markdown(
                """
                <div style="text-align: center; margin-bottom: 14px;">
                    <h2 style="font-size: 17px; font-weight: 700; color: #1A1A1E; margin: 0 0 4px 0;">
                        Inserisci Registrazione Audio
                    </h2>
                    <p style="font-size: 13px; color: #6E6E73; margin: 0;">
                        Registra una nota con il microfono del tuo Mac oppure carica un file
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Segmented Control: Tab 1 Microfono, Tab 2 File
            tab_mic, tab_file = st.tabs([
                "🎙️  Registra con Microfono",
                "📁  Carica File Audio",
            ])

            # ── TAB 1: REGISTRAZIONE DAL VIVO ─────────────────────────
            with tab_mic:
                st.markdown(
                    "<p style='font-size:12.5px; color:#55555A; text-align:center; margin-bottom:10px; font-weight:500;'>"
                    "Premi il microfono per registrare una conversazione dal vivo:</p>",
                    unsafe_allow_html=True,
                )
                mic = st.audio_input(
                    "Registra nota vocale",
                    label_visibility="collapsed",
                    key="tab_record_mic",
                )
                if mic is not None:
                    raw_bytes = mic.getvalue() if hasattr(mic, "getvalue") else mic.read()
                    if raw_bytes:
                        st.session_state.audio_bytes = raw_bytes
                        st.session_state.audio_filename = "registrazione_microfono.wav"

            # ── TAB 2: FILE DROPZONE ──────────────────────────────────
            with tab_file:
                uploaded = st.file_uploader(
                    "Seleziona o trascina il tuo file audio:",
                    type=["mp3", "wav", "m4a", "ogg", "aac", "flac"],
                    label_visibility="collapsed",
                    key="tab_upload_file",
                )
                if uploaded is not None:
                    raw_bytes = uploaded.getvalue() if hasattr(uploaded, "getvalue") else uploaded.read()
                    if raw_bytes:
                        st.session_state.audio_bytes = raw_bytes
                        st.session_state.audio_filename = uploaded.name

            # ── ANTEPRIMA AUDIO CARICATO (SE PRESENTE) ────────────────
            has_audio = bool(st.session_state.get("audio_bytes"))

            if has_audio:
                fname = st.session_state.get("audio_filename", "audio_selezionato.wav")
                st.markdown(
                    f"""
                    <div style="
                        background: #F0FBF4;
                        border: 1px solid rgba(52, 199, 89, 0.35);
                        border-radius: 12px;
                        padding: 12px 16px;
                        margin: 14px 0 10px 0;
                    ">
                        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span style="font-size: 16px;">🎵</span>
                                <strong style="font-size: 13.5px; color: #1A1A1E;">
                                    {fname}
                                </strong>
                            </div>
                            <span class="aria-pill aria-pill-green" style="font-size:10px;">Audio Pronto ✓</span>
                        </div>
                        <p style="font-size: 12px; color: #15692E; margin: 0; font-weight:500;">
                            Registrazione acquisita. Premi il pulsante sottostante per avviare l'analisi.
                        </p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.session_state.audio_bytes:
                    st.audio(st.session_state.audio_bytes)

            st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

            # ── IL PULSANTE DI INVIO / ANALISI (SEMPRE VISIBILE!) ─────
            btn_label = "⚡  Avvia Analisi della Riunione" if has_audio else "⚡  Avvia Analisi (In attesa di audio...)"
            
            if has_audio:
                col_btn, col_del = st.columns([3, 1])
                with col_btn:
                    if st.button(btn_label, type="primary", use_container_width=True, key="btn_run_analysis"):
                        t0 = time.perf_counter()
                        orchestrator = get_orchestrator()

                        with st.spinner("Trascrizione ed estrazione operativa in corso con Gemini..."):
                            result = run_async(
                                orchestrator.execute(
                                    audio_bytes=st.session_state.audio_bytes,
                                    filename=st.session_state.audio_filename,
                                    anchor_utc=datetime.now(timezone.utc),
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
                st.button(btn_label, type="primary", use_container_width=True, disabled=True, key="btn_disabled_hint")
                st.markdown(
                    "<p style='font-size:12px; color:#6E6E73; text-align:center; margin:8px 0 0 0;'>"
                    "ℹ️ Registra una nota vocale con il microfono o trascina un file audio per abilitare l'invio."
                    "</p>",
                    unsafe_allow_html=True,
                )

        st.markdown('</div>', unsafe_allow_html=True)
