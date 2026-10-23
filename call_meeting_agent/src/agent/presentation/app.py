"""
app.py — Entry point di Executive Agent.
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
    page_title="Executive Agent — Assistente Vocale",
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


# Routing principale con error boundary di sicurezza
try:
    if st.session_state.get("current_session") is None:
        landing.render()
    else:
        dashboard.render(st.session_state.current_session)
except Exception as e:
    st.error(f"Si è verificato un errore durante la renderizzazione: {e}")
    if st.button("🔄 Torna alla Schermata Principale", type="primary", key="btn_global_reset"):
        for k in ["current_session", "audio_bytes", "audio_filename", "text_prompt", "elapsed_seconds"]:
            st.session_state[k] = None
        st.rerun()
