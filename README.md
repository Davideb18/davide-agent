# Davide AI Agent Ecosystem

Questo repository contiene due progetti di intelligenza artificiale sviluppati da Davide in vista del colloquio con Trellis:

---

## 📁 1. `call_meeting_agent/` (In Sviluppo - Focus Principale)
**Executive Call & Meeting Operations Agent (Voice-to-Action)**
- **Obiettivo**: Automatizzare il flusso post-call/riunione da una semplice nota vocale o registrazione audio.
- **Architettura**: Hexagonal Architecture (Ports & Adapters) con State Machine deterministica in SQLite e Human-in-the-Loop.
- **Specifiche Tecniche**: Consulta il [MASTER_PLAN.md](file:///Users/davide/Desktop/davide-agent/call_meeting_agent/MASTER_PLAN.md).

---

## 📁 2. `hospitality_concierge/` (Progetto Precedente / Archivio di Ricerca)
**AuraConcierge - Assistente AI per Affitti Brevi**
- **Obiettivo**: Concierge virtuale per host e ospiti di case vacanza / Airbnb.
- **Funzionalità implementate**:
  - Architettura database a 5 tabelle (`db.py`) con SQLite asincrono (`aiosqlite`).
  - Validazione dati strutturati con modelli Pydantic v2 (`models.py`).
  - Parsing automatico del regolamento e dettagli casa da Markdown (`property.md`).
