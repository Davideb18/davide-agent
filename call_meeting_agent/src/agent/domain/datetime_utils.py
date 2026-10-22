"""
datetime_utils.py — Funzioni pure e immutabili per la gestione di date, orari e fusi orari.
Disaccoppiato da locale di sistema (zero 'locale.setlocale()') per totale thread-safety in ambienti concorrenti.
"""
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Iterable
from zoneinfo import ZoneInfo

# ── DIZIONARI COSTANTI IMMUTABILI (ITALIANO) ──────────────────────────────────
WEEKDAYS_SHORT_IT: List[str] = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
WEEKDAYS_FULL_IT: List[str] = [
    "Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"
]
WEEKDAYS_LOWER_IT: List[str] = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]

MONTHS_SHORT_IT: List[str] = [
    "Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
    "Lug", "Ago", "Set", "Ott", "Nov", "Dic"
]
MONTHS_FULL_IT: List[str] = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"
]

# ── DIZIONARI COSTANTI IMMUTABILI (INGLESE) ───────────────────────────────────
WEEKDAYS_SHORT_EN: List[str] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAYS_FULL_EN: List[str] = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]
WEEKDAYS_LOWER_EN: List[str] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

MONTHS_SHORT_EN: List[str] = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
]
MONTHS_FULL_EN: List[str] = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


def resolve_timezone(tz_identifier: Optional[str] = None) -> ZoneInfo:
    """Restituisce l'oggetto ZoneInfo in modo sicuro con fallback deterministico su Europe/Rome."""
    if not tz_identifier or not tz_identifier.strip():
        return ZoneInfo("Europe/Rome")
    try:
        return ZoneInfo(tz_identifier.strip())
    except Exception:
        return ZoneInfo("Europe/Rome")


def to_user_timezone(dt: datetime, user_tz: str = "Europe/Rome") -> datetime:
    """Converte un datetime (UTC o naive) nel fuso orario locale dell'utente."""
    tz = resolve_timezone(user_tz)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def is_english(lang_code: Optional[str] = None) -> bool:
    """Verifica se il codice lingua indica l'inglese."""
    if not lang_code:
        return False
    clean = lang_code.lower().strip()
    return clean.startswith("en") or "eng" in clean


def format_localized_slot(
    dt_utc: datetime,
    user_tz: str = "Europe/Rome",
    lang: str = "it",
) -> str:
    """
    Formatta uno slot orario (es. per bozza email o preview appuntamento)
    nella lingua richiesta rispettando il fuso orario locale.
    Esempio IT: 'Lun 16 Ott ore 15:00'
    Esempio EN: 'Mon 16 Oct at 15:00'
    """
    loc = to_user_timezone(dt_utc, user_tz)
    w_idx = loc.weekday()
    m_idx = loc.month - 1

    if is_english(lang):
        w_name = WEEKDAYS_SHORT_EN[w_idx]
        m_name = MONTHS_SHORT_EN[m_idx]
        return f"{w_name} {loc.day} {m_name} at {loc.strftime('%H:%M')}"
    else:
        w_name = WEEKDAYS_SHORT_IT[w_idx]
        m_name = MONTHS_SHORT_IT[m_idx]
        return f"{w_name} {loc.day} {m_name} ore {loc.strftime('%H:%M')}"


def format_full_localized_slot(
    dt_utc: datetime,
    user_tz: str = "Europe/Rome",
    lang: str = "it",
) -> str:
    """
    Formatta uno slot orario in forma estesa (es. per banner o conferme formali).
    Esempio IT: 'Lunedì 16 Ottobre ore 15:00'
    Esempio EN: 'Monday 16 October at 15:00'
    """
    loc = to_user_timezone(dt_utc, user_tz)
    w_idx = loc.weekday()
    m_idx = loc.month - 1

    if is_english(lang):
        w_name = WEEKDAYS_FULL_EN[w_idx]
        m_name = MONTHS_FULL_EN[m_idx]
        return f"{w_name} {loc.day} {m_name} at {loc.strftime('%H:%M')}"
    else:
        w_name = WEEKDAYS_FULL_IT[w_idx]
        m_name = MONTHS_FULL_IT[m_idx]
        return f"{w_name} {loc.day} {m_name} ore {loc.strftime('%H:%M')}"


def get_weekday_label(weekday_idx: int, full: bool = False, lang: str = "it") -> str:
    """Restituisce il nome del giorno della settimana (0 = Lunedì / Monday)."""
    idx = weekday_idx % 7
    if is_english(lang):
        return WEEKDAYS_FULL_EN[idx] if full else WEEKDAYS_SHORT_EN[idx]
    return WEEKDAYS_FULL_IT[idx] if full else WEEKDAYS_SHORT_IT[idx]


def get_month_label(month_num: int, full: bool = False, lang: str = "it") -> str:
    """Restituisce il nome del mese (1-indexed: 1 = Gennaio / January)."""
    idx = max(0, min(11, month_num - 1))
    if is_english(lang):
        return MONTHS_FULL_EN[idx] if full else MONTHS_SHORT_EN[idx]
    return MONTHS_FULL_IT[idx] if full else MONTHS_SHORT_IT[idx]


def clean_spoken_email(raw_email: Optional[str]) -> str:
    """
    Pulisce e normalizza indirizzi email pronunciati o trascritti da speech-to-text.
    Gestisce espressioni fonetiche del parlato ('chiocciola', 'punto', spazi):
      - 'Giorgio.chiocciola@gmail.com' -> 'giorgio@gmail.com'
      - 'giorgio chiocciola gmail punto com' -> 'giorgio@gmail.com'
      - 'mario.rossi chiocciola yahoo punto it' -> 'mario.rossi@yahoo.it'
    Se l'indirizzo risultante non è sintatticamente valido, restituisce '' (stringa vuota).
    """
    if not raw_email or not isinstance(raw_email, str):
        return ""
    text = raw_email.strip().lower()
    text = re.sub(r'[\._-]?chiocciola@?', '@', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+chiocciola\s+', '@', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+at\s+', '@', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+punto\s+', '.', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+dot\s+', '.', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', '', text)

    match = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', text)
    if match:
        cleaned = match.group(0).strip('.')
        if '.' in cleaned.split('@')[-1] and len(cleaned.split('@')[-1].split('.')[-1]) >= 2:
            return cleaned
    return ""


def is_self_mention(text: Optional[str], self_kws: Any) -> bool:
    """
    Verifica se una stringa (nome interlocutore, entità o destinatario) si riferisce all'utente.
    Previene categoricamente falsi positivi di sottostringa su nomi italiani come 'Giorgio', 'Antonio',
    'Mario', 'Claudio', 'Fabio' causati da keyword brevi come 'io' o 'me'.
    """
    if not text or not isinstance(text, str):
        return False
    lower = text.lower().strip()
    tokens = set(re.split(r'[\s_,\.\-\/]+', lower))
    for k in self_kws:
        k_clean = str(k).strip().lower()
        if not k_clean:
            continue
        if lower == k_clean:
            return True
        if " " in k_clean:
            if k_clean in lower:
                return True
        elif k_clean in tokens:
            return True
    return False

