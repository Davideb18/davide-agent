from datetime import datetime, timedelta, timezone
from typing import List, Tuple
from ..domain.ports import CalendarServicePort
from ..domain.datetime_utils import resolve_timezone


async def evaluate_calendar_slot(
    calendar_service: CalendarServicePort,
    requested_start_utc: datetime,
    duration_minutes: int = 30,
    working_hour_start: int = 9,
    working_hour_end: int = 18,
    max_alternatives: int = 3,
    user_tz: str = "Europe/Rome",
) -> Tuple[bool, List[datetime]]:
    """
    Verifica se lo slot orario richiesto è disponibile su Google Calendar.
    Se è occupato (The Trellis Way: rischio overbooking), scansiona gli intervalli adiacenti
    a finestre di 30 minuti per individuare i 3 migliori slot alternativi disponibili.

    Ritorna:
        (is_busy: bool, alternative_slots: List[datetime])
    """
    requested_end_utc = requested_start_utc + timedelta(minutes=duration_minutes)

    # 1. Controllo immediato: lo slot desiderato è occupato?
    is_busy = await calendar_service.check_is_busy(requested_start_utc, requested_end_utc)
    if not is_busy:
        # Perfetto: nessun conflitto, orario libero!
        return False, []

    # Risoluzione fuso orario utente per calcolo orario lavorativo
    tz = resolve_timezone(user_tz)

    req_utc = requested_start_utc if requested_start_utc.tzinfo else requested_start_utc.replace(tzinfo=timezone.utc)
    req_local = req_utc.astimezone(tz)
    is_evening_request = (req_local.hour >= 19 or req_local.hour < 8)
    is_weekend_request = (req_local.weekday() >= 5)

    # 2. Conflitto rilevato! Avviamo la Sliding Window deterministica
    alternative_slots: List[datetime] = []
    current_candidate = requested_start_utc + timedelta(minutes=30)

    # Scansioniamo fino a un massimo di 4 giorni in avanti
    limit_scan = requested_start_utc + timedelta(days=4)

    while current_candidate < limit_scan and len(alternative_slots) < max_alternatives:
        candidate_end = current_candidate + timedelta(minutes=duration_minutes)

        # Proiezione dell'orario candidato nel fuso orario locale dell'utente
        if current_candidate.tzinfo is None:
            cand_utc = current_candidate.replace(tzinfo=timezone.utc)
        else:
            cand_utc = current_candidate
        cand_local = cand_utc.astimezone(tz)

        # Filtro orari contestuale: adatta a seconda della natura dell'orario richiesto
        if is_evening_request:
            is_valid_hour = (cand_local.hour >= 19 or cand_local.hour <= 2)
        elif is_weekend_request:
            is_valid_hour = (cand_local.weekday() >= 5 and 9 <= cand_local.hour <= 23)
        else:
            is_valid_hour = (
                working_hour_start <= cand_local.hour < working_hour_end
                and cand_local.weekday() < 5
            )

        if is_valid_hour:
            candidate_busy = await calendar_service.check_is_busy(current_candidate, candidate_end)
            if not candidate_busy:
                alternative_slots.append(current_candidate)

        # Fa avanzare la finestra di 30 minuti
        current_candidate += timedelta(minutes=30)

    return True, alternative_slots
