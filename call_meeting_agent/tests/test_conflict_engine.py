"""
test_conflict_engine.py — Test per l'algoritmo deterministico di risoluzione conflitti (The Trellis Way).
Verifica:
  - Rilevamento immediato slot libero (zero false-positive)
  - Collisione e scanning a finestra scorrevole (Sliding Window a passi di 30 min)
  - Rispetto rigoroso dei working hours (09:00 - 18:00) ed esclusione automatica weekend
  - Proiezione multi-fuso orario corretta (es. Europe/Rome vs America/New_York)
"""
import pytest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.agent.domain.models import CalendarPayload
from src.agent.infrastructure.google.live_google import LocalCalendarService
from src.agent.application.resolve_conflict import evaluate_calendar_slot


@pytest.mark.asyncio
async def test_free_slot_returns_no_conflict(local_calendar: LocalCalendarService):
    """Verifica che un orario libero in agenda non generi falsi positivi né alternative."""
    start_utc = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)  # Venerdì 10:00 UTC
    is_busy, alts = await evaluate_calendar_slot(
        calendar_service=local_calendar,
        requested_start_utc=start_utc,
        duration_minutes=30,
        user_tz="Europe/Rome",
    )
    assert is_busy is False
    assert alts == []


@pytest.mark.asyncio
async def test_busy_slot_triggers_sliding_window(local_calendar: LocalCalendarService):
    """Verifica che una collisione oraria attivi la sliding window generando i top 3 slot liberi."""
    start_utc = datetime(2026, 10, 16, 13, 0, tzinfo=timezone.utc)  # Venerdì 15:00 a Roma (13:00 UTC)

    # 1. Occupiamo lo slot nel calendario in memoria
    await local_calendar.create_event(
        CalendarPayload(
            title="Riunione Concorrente",
            start_utc=start_utc,
            end_utc=start_utc + timedelta(minutes=30),
        ),
        idempotency_key="idemp_conflict_1",
    )

    # 2. Valutazione conflitto
    is_busy, alts = await evaluate_calendar_slot(
        calendar_service=local_calendar,
        requested_start_utc=start_utc,
        duration_minutes=30,
        max_alternatives=3,
        user_tz="Europe/Rome",
    )
    assert is_busy is True
    assert len(alts) == 3
    # Lo slot originario occupato NON deve essere tra le alternative
    assert start_utc not in alts
    # Tutti gli slot alternativi devono essere successivi
    for slot in alts:
        assert slot > start_utc


@pytest.mark.asyncio
async def test_working_hours_and_weekend_filtering(local_calendar: LocalCalendarService):
    """Verifica che gli slot alternativi proposti rispettino i limiti orari lavorativi e saltino il weekend."""
    # Venerdì pomeriggio tardi: 15:30 UTC = 17:30 a Roma. Fine orario lavorativo alle 18:00 locale.
    start_utc = datetime(2026, 10, 16, 15, 30, tzinfo=timezone.utc)

    # Occupiamo questo slot
    await local_calendar.create_event(
        CalendarPayload(
            title="Meeting Fine Giornata",
            start_utc=start_utc,
            end_utc=start_utc + timedelta(minutes=30),
        ),
        idempotency_key="idemp_late_friday",
    )

    is_busy, alts = await evaluate_calendar_slot(
        calendar_service=local_calendar,
        requested_start_utc=start_utc,
        duration_minutes=30,
        working_hour_start=9,
        working_hour_end=18,
        max_alternatives=3,
        user_tz="Europe/Rome",
    )
    assert is_busy is True
    assert len(alts) > 0

    tz_rome = ZoneInfo("Europe/Rome")
    for alt in alts:
        alt_rome = alt.astimezone(tz_rome)
        # Deve essere un giorno feriale (Lunedì-Venerdì: 0-4)
        assert alt_rome.weekday() < 5, f"Slot alternativo {alt_rome} cade nel weekend!"
        # Deve essere all'interno delle working hours (09:00 - 18:00)
        assert 9 <= alt_rome.hour < 18, f"Slot alternativo {alt_rome} fuori orario lavorativo!"


@pytest.mark.asyncio
async def test_multi_timezone_projection(local_calendar: LocalCalendarService):
    """Verifica che la sliding window proietti correttamente le working hours sul fuso di New York."""
    # 14:00 UTC = 10:00 AM New York (EDT, UTC-4), in pieno orario lavorativo
    start_utc = datetime(2026, 10, 16, 14, 0, tzinfo=timezone.utc)

    # Occupiamo lo slot
    await local_calendar.create_event(
        CalendarPayload(
            title="Meeting NY Occupato",
            start_utc=start_utc,
            end_utc=start_utc + timedelta(minutes=30),
        ),
        idempotency_key="idemp_ny_busy",
    )

    is_busy, alts = await evaluate_calendar_slot(
        calendar_service=local_calendar,
        requested_start_utc=start_utc,
        duration_minutes=30,
        working_hour_start=9,
        working_hour_end=17,
        max_alternatives=2,
        user_tz="America/New_York",
    )
    assert is_busy is True
    assert len(alts) == 2

    tz_ny = ZoneInfo("America/New_York")
    for alt in alts:
        alt_ny = alt.astimezone(tz_ny)
        assert 9 <= alt_ny.hour < 17
        assert alt_ny.weekday() < 5
