from datetime import datetime, timedelta, timezone
from typing import List, Tuple
from ..domain.ports import CalendarServicePort


async def evaluate_calendar_slot(
    calendar_service: CalendarServicePort,
    requested_start_utc: datetime,
    duration_minutes: int = 30,
    working_hour_start: int = 9,
    working_hour_end: int = 18,
    max_alternatives: int = 3,
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

    # 2. Conflitto rilevato! Avviamo la Sliding Window deterministica
    alternative_slots: List[datetime] = []
    current_candidate = requested_start_utc + timedelta(minutes=30)

    # Scansioniamo fino a un massimo di 4 giorni in avanti
    limit_scan = requested_start_utc + timedelta(days=4)

    while current_candidate < limit_scan and len(alternative_slots) < max_alternatives:
        candidate_end = current_candidate + timedelta(minutes=duration_minutes)

        # Filtro orari lavorativi: esclude la notte (es. prima delle 9:00 o dopo le 18:00)
        # e salta i weekend (sabato = 5, domenica = 6)
        is_working_hour = (
            working_hour_start <= current_candidate.hour < working_hour_end
            and current_candidate.weekday() < 5
        )

        if is_working_hour:
            candidate_busy = await calendar_service.check_is_busy(current_candidate, candidate_end)
            if not candidate_busy:
                alternative_slots.append(current_candidate)

        # Fa avanzare la finestra di 30 minuti
        current_candidate += timedelta(minutes=30)

    return True, alternative_slots
