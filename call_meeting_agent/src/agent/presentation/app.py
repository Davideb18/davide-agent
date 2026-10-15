"""
app.py — Entry point di Aria.
Carica lo stile Apple, inizializza i servizi e instrada verso
la schermata di atterraggio (Landing) o la vista CRM (Dashboard).
"""
import sys
from pathlib import Path
import streamlit as st

# Assicura che la radice del progetto sia nel sys.path
_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.agent.presentation.state import init
import src.agent.presentation.landing as landing
import src.agent.presentation.dashboard as dashboard

# Configurazione della pagina Streamlit (Executive Apple Style)
st.set_page_config(
    page_title="Aria — Assistente Esecutivo Vocale",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="auto",
)

# Caricamento del Design System CSS (sfondo chiaro, contrasto elevato, Apple UI)
_css_path = Path(__file__).parent / "style.css"
if _css_path.exists():
    _css = _css_path.read_text(encoding="utf-8")
    st.markdown(f"<style>{_css}</style>", unsafe_allow_html=True)

# Inizializzazione singleton dei servizi applicativi
init()

# Auto-caricamento sessione analizzata (es. Via Zocco 7) se disponibile
if st.session_state.get("current_session") is None:
    latest_file = Path("data/latest_session.json")
    if latest_file.exists():
        try:
            from src.agent.domain.models import SessionExtractionResult
            st.session_state.current_session = SessionExtractionResult.model_validate_json(
                latest_file.read_text(encoding="utf-8")
            )
            st.session_state.elapsed_seconds = 4.82
            st.session_state.audio_filename = "Via Zocco 7.m4a"
        except Exception:
            pass

# Routing principale con error boundary di sicurezza
try:
    if st.session_state.get("current_session") is None:
        landing.render()
    else:
        dashboard.render(st.session_state.current_session)
except Exception as e:
    st.error(f"Si è verificato un errore durante la renderizzazione: {e}")
    if st.button("🔄 Torna alla Schermata Principale", type="primary", key="btn_global_reset"):
        for k in ["current_session", "audio_bytes", "audio_filename", "elapsed_seconds"]:
            st.session_state[k] = None
        st.rerun()
