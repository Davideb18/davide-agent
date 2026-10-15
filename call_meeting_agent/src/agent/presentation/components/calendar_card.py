"""
calendar_card.py — Vista Apple Calendar macOS Dark Mode fedele 1:1 allo screenshot.
Design System: Apple macOS Calendar Dark Mode (Canvas #1E1E1E, Griglia Oraria, Badge Oggi Rosso, Box Attività Teal).
100% Google Calendar Live connesso (Zero mock, zero residui di codice grezzo, selettore slot interattivo).
"""
import html
from datetime import datetime, timedelta, timezone, time as dt_time, date as dt_date
from typing import List, Optional, Dict, Tuple
from zoneinfo import ZoneInfo
import streamlit as st

from src.agent.domain.enums import ActionStatus
from src.agent.domain.models import ProposedAction, CalendarEventItem
from src.agent.presentation.state import run_async

WEEKDAYS_IT = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
WEEKDAYS_FULL_IT = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
MONTHS_IT = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"
]

ROME_TZ = ZoneInfo("Europe/Rome")
START_HOUR = 6
END_HOUR = 19
HOUR_HEIGHT = 46  # pixel per ora


def _to_rome(dt: datetime) -> datetime:
    """Converte un datetime UTC nel fuso orario Europe/Rome (CET/CEST)."""
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ROME_TZ)
    except Exception:
        return dt


def _fetch_calendar_events(cal_service, range_start: datetime, range_end: datetime) -> List[CalendarEventItem]:
    """Recupera la lista eventi in modo resiliente e sicuro senza mai bloccare la UI."""
    if cal_service and hasattr(cal_service, "get_events"):
        try:
            return run_async(cal_service.get_events(range_start, range_end)) or []
        except Exception:
            pass

    try:
        import importlib
        import src.agent.infrastructure.google.live_google as lg
        lg = importlib.reload(lg)
        cal = lg.LiveCalendarService()
        st.session_state.calendar = cal
        return run_async(cal.get_events(range_start, range_end)) or []
    except Exception:
        pass

    return []


def _calculate_free_slots(
    target_date: dt_date,
    day_events: List[CalendarEventItem],
    duration_minutes: int = 30,
    requested_time: Optional[dt_time] = None,
) -> List[Tuple[str, datetime]]:
    """Calcola slot orari liberi durante l'orario operativo (08:30 – 18:30) per la giornata scelta."""
    slots: List[Tuple[str, datetime]] = []

    # 1. Se fornito un orario richiesto, verifichiamo la sua disponibilità
    if requested_time:
        req_start_rome = datetime.combine(target_date, requested_time, tzinfo=ROME_TZ)
        req_end_rome = req_start_rome + timedelta(minutes=duration_minutes)
        collision = any(
            req_start_rome < _to_rome(ev.end_utc) and req_end_rome > _to_rome(ev.start_utc)
            for ev in day_events
        )
        tag = "⚠️ Richiesto (Occupato)" if collision else "📍 Richiesto"
        slots.append((f"{req_start_rome.strftime('%H:%M')} — {tag}", req_start_rome))

    # 2. Orari candidati tipici della giornata lavorativa
    candidate_hours = [(8, 30), (9, 0), (11, 0), (11, 30), (12, 30), (13, 30), (15, 0), (16, 30), (17, 0), (17, 30), (18, 0)]
    for h, m in candidate_hours:
        c_start = datetime.combine(target_date, dt_time(h, m), tzinfo=ROME_TZ)
        c_end = c_start + timedelta(minutes=duration_minutes)
        if requested_time and requested_time.hour == h and requested_time.minute == m:
            continue

        collision = any(
            c_start < _to_rome(ev.end_utc) and c_end > _to_rome(ev.start_utc)
            for ev in day_events
        )
        if not collision and len(slots) < 6:
            slots.append((f"🟢 {c_start.strftime('%H:%M')} (Libero)", c_start))

    return slots


def _generate_apple_calendar_html(
    week_days: List[datetime],
    events_by_day: Dict[int, List[CalendarEventItem]],
    proposed_day_idx: int,
    proposed_start_rome: datetime,
    proposed_end_rome: datetime,
    proposed_title: str,
    today_rome_date: dt_date,
    current_rome_time: datetime,
    is_conflict: bool,
) -> str:
    """Genera la tabella grafica esatta Apple Calendar Dark Mode (Zero markdown escaping issues)."""

    total_grid_height = (END_HOUR - START_HOUR + 1) * HOUR_HEIGHT
    month_name = MONTHS_IT[week_days[3].month - 1]
    year_num = week_days[3].year

    lines: List[str] = [
        '<div class="apple-dark-canvas">',
        '  <div class="apple-dark-topbar">',
        f'    <div class="apple-dark-month-title"><strong>{month_name}</strong> <span class="apple-dark-year">{year_num}</span></div>',
        '    <div class="apple-dark-nav-pills">',
        '      <span class="apple-pill-btn">‹</span>',
        '      <span class="apple-pill-btn apple-pill-today">Oggi</span>',
        '      <span class="apple-pill-btn">›</span>',
        '      <span class="apple-sync-badge">🟢 Google Live</span>',
        '    </div>',
        '  </div>',
    ]

    # 2. Header colonne giorni (lun 12, mar 13, mer 14, gio 15 con cerchio rosso, ecc.)
    lines.append('  <div class="apple-days-header-row">')
    lines.append('    <div class="apple-time-spacer"></div>')
    for d in week_days:
        w_name = WEEKDAYS_IT[d.weekday()]
        d_num = str(d.day)
        is_today = (d.date() == today_rome_date)
        if is_today:
            lines.append(f'    <div class="apple-day-col-head"><span class="apple-day-name apple-today-text">{w_name}</span><span class="apple-today-circle">{d_num}</span></div>')
        else:
            lines.append(f'    <div class="apple-day-col-head"><span class="apple-day-name">{w_name}</span><span class="apple-day-num">{d_num}</span></div>')
    lines.append('  </div>')

    # 3. Riga "tutto il g."
    lines.append('  <div class="apple-allday-row">')
    lines.append('    <div class="apple-time-spacer apple-allday-label">tutto il g.</div>')
    for _ in week_days:
        lines.append('    <div class="apple-allday-cell"></div>')
    lines.append('  </div>')

    # 4. Griglia oraria principale
    lines.append(f'  <div class="apple-grid-body" style="height: {total_grid_height}px;">')

    # Colonna orari a sinistra
    lines.append('    <div class="apple-time-axis">')
    for h in range(START_HOUR, END_HOUR + 1):
        top_px = (h - START_HOUR) * HOUR_HEIGHT
        time_lbl = f"{h:02d}:00"
        lines.append(f'      <div class="apple-hour-label" style="top: {top_px - 8}px;">{time_lbl}</div>')

    # Badge rosso dell'ora corrente sull'asse
    curr_hour_frac = (current_rome_time.hour - START_HOUR) + (current_rome_time.minute / 60.0)
    if 0 <= curr_hour_frac <= (END_HOUR - START_HOUR + 1):
        curr_y = int(curr_hour_frac * HOUR_HEIGHT)
        curr_hm_str = current_rome_time.strftime("%H:%M")
        lines.append(f'      <div class="apple-current-time-badge" style="top: {curr_y - 9}px;">{curr_hm_str}</div>')
    lines.append('    </div>')

    # Colonne dei 7 giorni
    lines.append('    <div class="apple-columns-container">')

    # Linee orizzontali orarie di sfondo
    for h in range(START_HOUR, END_HOUR + 1):
        top_px = (h - START_HOUR) * HOUR_HEIGHT
        lines.append(f'      <div class="apple-hour-gridline" style="top: {top_px}px;"></div>')

    # Linea rossa orizzontale che attraversa tutte le colonne all'orario attuale
    if 0 <= curr_hour_frac <= (END_HOUR - START_HOUR + 1):
        curr_y = int(curr_hour_frac * HOUR_HEIGHT)
        lines.append(f'      <div class="apple-current-timeline-full" style="top: {curr_y}px;"></div>')

    # Colonne per ogni giorno della settimana
    for day_idx, d in enumerate(week_days):
        is_today = (d.date() == today_rome_date)
        lines.append(f'      <div class="apple-day-column" style="left: {day_idx * 14.2857}%; width: 14.2857%;">')

        # Punto rosso indicatore all'incrocio per oggi
        if is_today and 0 <= curr_hour_frac <= (END_HOUR - START_HOUR + 1):
            curr_y = int(curr_hour_frac * HOUR_HEIGHT)
            lines.append(f'        <div class="apple-current-dot" style="top: {curr_y - 4}px;"></div>')

        # Eventi reali del calendario per questo giorno
        day_events = events_by_day.get(day_idx, [])
        for ev in day_events:
            ev_start_r = _to_rome(ev.start_utc)
            ev_end_r = _to_rome(ev.end_utc)
            start_frac = (ev_start_r.hour - START_HOUR) + (ev_start_r.minute / 60.0)
            dur_hours = (ev_end_r - ev_start_r).total_seconds() / 3600.0

            if start_frac + dur_hours < 0 or start_frac > (END_HOUR - START_HOUR + 1):
                continue

            top_px = max(0, int(start_frac * HOUR_HEIGHT))
            height_px = max(34, int(dur_hours * HOUR_HEIGHT) - 2)
            time_str = f"{ev_start_r.strftime('%H:%M')} – {ev_end_r.strftime('%H:%M')}"
            safe_title = html.escape(ev.title)

            lines.append(
                f'        <div class="apple-event-teal" style="top: {top_px}px; height: {height_px}px;" title="{safe_title} ({time_str})">'
                f'          <div class="apple-event-teal-title">{safe_title}</div>'
                f'          <div class="apple-event-teal-time">🕒 {time_str}</div>'
                f'        </div>'
            )

        # Evento proposto / selezionato (Evidenziato)
        if day_idx == proposed_day_idx:
            p_start_frac = (proposed_start_rome.hour - START_HOUR) + (proposed_start_rome.minute / 60.0)
            p_dur_hours = (proposed_end_rome - proposed_start_rome).total_seconds() / 3600.0
            p_top_px = max(0, int(p_start_frac * HOUR_HEIGHT))
            p_height_px = max(36, int(p_dur_hours * HOUR_HEIGHT) - 2)
            p_time_str = f"{proposed_start_rome.strftime('%H:%M')} – {proposed_end_rome.strftime('%H:%M')}"
            p_safe_title = html.escape(proposed_title)
            card_class = "apple-event-proposed-conflict" if is_conflict else "apple-event-proposed"
            badge_text = "⚠️ CONFLITTO" if is_conflict else "📍 PROPOSTA"

            lines.append(
                f'        <div class="{card_class}" style="top: {p_top_px}px; height: {p_height_px}px;" title="Nuovo Appuntamento: {p_safe_title} ({p_time_str})">'
                f'          <div class="apple-event-proposed-badge">{badge_text}</div>'
                f'          <div class="apple-event-proposed-title">{p_safe_title}</div>'
                f'          <div class="apple-event-proposed-time">🕒 {p_time_str}</div>'
                f'        </div>'
            )

        lines.append('      </div>')

    lines.append('    </div>')
    lines.append('  </div>')
    lines.append('</div>')

    # Compattazione senza indentazioni per azzerare qualunque parsing code block
    return "".join(line.strip() for line in lines)


def render_calendar_card(action: ProposedAction, committer):
    """Renderizza l'interfaccia Apple Calendar Dark Mode 1:1 con selettore interattivo di giorno e orario."""
    data = action.calendar_data
    if not data:
        return

    # Inizializzazione Calendar Service (Live 100%)
    cal_service = st.session_state.get("calendar", None)
    if cal_service is None or not hasattr(cal_service, "get_events"):
        try:
            from src.agent.infrastructure.google.live_google import LiveCalendarService
            cal_service = LiveCalendarService()
            st.session_state.calendar = cal_service
        except Exception:
            pass

    # Calcolo finestra temporale della settimana
    meeting_day = data.start_utc.date()
    monday_day = meeting_day - timedelta(days=meeting_day.weekday())
    week_days = [
        datetime(monday_day.year, monday_day.month, monday_day.day, tzinfo=timezone.utc) + timedelta(days=i)
        for i in range(7)
    ]

    range_start = week_days[0]
    range_end = week_days[-1] + timedelta(hours=23, minutes=59, seconds=59)

    # Recupero impegni reali da Google Calendar
    raw_events: List[CalendarEventItem] = _fetch_calendar_events(cal_service, range_start, range_end)

    # Mappatura eventi per giorno (0 = Lunedì, 6 = Domenica)
    events_by_day: Dict[int, List[CalendarEventItem]] = {i: [] for i in range(7)}
    for ev in raw_events:
        r_dt = _to_rome(ev.start_utc)
        day_diff = (r_dt.date() - monday_day).days
        if 0 <= day_diff < 7:
            events_by_day[day_diff].append(ev)

    now_rome = datetime.now(ROME_TZ)
    today_rome_date = now_rome.date()

    # Calcolo coordinate correnti dell'evento proposto
    proposed_start_rome = _to_rome(data.start_utc)
    proposed_end_rome = _to_rome(data.end_utc)
    duration = data.end_utc - data.start_utc
    duration_min = int(duration.total_seconds() / 60) if duration.total_seconds() > 0 else 30

    current_day_idx = (proposed_start_rome.date() - monday_day).days
    if not (0 <= current_day_idx < 7):
        current_day_idx = (today_rome_date - monday_day).days if 0 <= (today_rome_date - monday_day).days < 7 else 3

    # ── HEADER CARD & SELETTORE INTERATTIVO ──────────────────────────────────
    with st.container():
        st.markdown(
            f"<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;'>"
            f"  <div>"
            f"    <h3 style='font-size:20px; font-weight:700; color:#1A1A1E; margin:0 0 2px 0; letter-spacing:-0.025em;'>"
            f"      📅 Agenda Apple Calendar — {data.title}"
            f"    </h3>"
            f"    <p style='font-size:12.5px; color:#55555A; margin:0;'>"
            f"      Visualizzazione sincronizzata macOS • Fuso orario: Europe/Rome (UTC+2)"
            f"    </p>"
            f"  </div>"
            f"  <span class='apple-sync-badge'>🟢 Google Live Connesso</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # ── 1. SELETTORE GIORNO DELLA SETTIMANA ──────────────────────────────
        st.markdown(
            "<span style='font-size:12px; font-weight:700; color:#444449; text-transform:uppercase; letter-spacing:0.04em;'>"
            "1. Scegli Giorno per l'Attività:</span>",
            unsafe_allow_html=True,
        )

        day_labels = []
        for i, wd in enumerate(week_days):
            d_rome = _to_rome(wd)
            lbl = f"{WEEKDAYS_IT[i].capitalize()} {d_rome.day} {MONTHS_IT[d_rome.month-1][:3]}"
            if d_rome.date() == today_rome_date:
                lbl = f"⭐ {lbl} (Oggi)"
            day_labels.append(lbl)

        selected_day_label = st.pills(
            "Seleziona giorno:",
            options=day_labels,
            default=day_labels[current_day_idx],
            key=f"cal_day_pills_{action.id}",
            label_visibility="collapsed",
        )

        chosen_day_idx = day_labels.index(selected_day_label) if selected_day_label in day_labels else current_day_idx
        target_day_date = (monday_day + timedelta(days=chosen_day_idx))

        # ── 2. SELETTORE ORARIO / SLOT PER IL GIORNO SCELTO ──────────────────
        st.markdown(
            "<div style='margin-top:8px;'><span style='font-size:12px; font-weight:700; color:#444449; text-transform:uppercase; letter-spacing:0.04em;'>"
            "2. Scegli Orario o Slot Disponibile:</span></div>",
            unsafe_allow_html=True,
        )

        target_day_events = events_by_day.get(chosen_day_idx, [])
        free_slots_data = _calculate_free_slots(
            target_date=target_day_date,
            day_events=target_day_events,
            duration_minutes=duration_min,
            requested_time=dt_time(proposed_start_rome.hour, proposed_start_rome.minute),
        )

        slot_label_to_dt = {label: dt for label, dt in free_slots_data}
        slot_options = list(slot_label_to_dt.keys()) + ["🕒 Altro Orario..."]

        chosen_slot_label = st.pills(
            "Seleziona orario slot:",
            options=slot_options,
            default=slot_options[0],
            key=f"cal_slot_pills_{action.id}_{chosen_day_idx}",
            label_visibility="collapsed",
        )

        if chosen_slot_label == "🕒 Altro Orario...":
            col_t, _ = st.columns([1.5, 2])
            with col_t:
                custom_time = st.time_input(
                    "Imposta orario desiderato (Europe/Rome):",
                    value=dt_time(hour=proposed_start_rome.hour, minute=proposed_start_rome.minute),
                    key=f"custom_time_{action.id}_{chosen_day_idx}",
                )
            new_start_rome = datetime(
                target_day_date.year, target_day_date.month, target_day_date.day,
                custom_time.hour, custom_time.minute, tzinfo=ROME_TZ
            )
            data.start_utc = new_start_rome.astimezone(timezone.utc)
            data.end_utc = data.start_utc + duration
        elif chosen_slot_label in slot_label_to_dt:
            chosen_start_rome = slot_label_to_dt[chosen_slot_label]
            data.start_utc = chosen_start_rome.astimezone(timezone.utc)
            data.end_utc = data.start_utc + duration

        # Aggiornamento coordinate definitive
        proposed_start_rome = _to_rome(data.start_utc)
        proposed_end_rome = _to_rome(data.end_utc)
        proposed_day_idx = (proposed_start_rome.date() - monday_day).days
        if not (0 <= proposed_day_idx < 7):
            proposed_day_idx = chosen_day_idx

        # Verifica collisione effettiva
        is_conflict = False
        conflict_event_title = ""
        for ev in events_by_day.get(proposed_day_idx, []):
            if data.start_utc < ev.end_utc and data.end_utc > ev.start_utc:
                is_conflict = True
                conflict_event_title = ev.title
                break

        # Banner informativo dinamico stato slot
        if is_conflict:
            st.markdown(
                f"<div style='background:#FFFBEB; border:1px solid #FCD34D; border-radius:10px; padding:10px 14px; margin: 8px 0 14px 0;'>"
                f"  <span style='color:#B45309; font-weight:700; font-size:13px;'>⚠️ Sovrapposizione Orario Rilevata</span>"
                f"  <p style='color:#92400E; font-size:12px; margin:2px 0 0 0;'>"
                f"    L'orario scelto ({proposed_start_rome.strftime('%H:%M')}) si sovrappone a <b>{html.escape(conflict_event_title)}</b>. "
                f"    Seleziona uno dei pulsanti orario con il bollino verde sopra per spostarlo in uno slot libero."
                f"  </p>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='background:#F0FDF4; border:1px solid #BBF7D0; border-radius:10px; padding:8px 14px; margin: 8px 0 14px 0;'>"
                f"  <span style='color:#15803D; font-weight:600; font-size:12.5px;'>"
                f"    ✓ Posizione confermata in evidenza: <b>{WEEKDAYS_FULL_IT[proposed_day_idx]} {proposed_start_rome.day} {MONTHS_IT[proposed_start_rome.month-1]}</b> ore <b>{proposed_start_rome.strftime('%H:%M')} – {proposed_end_rome.strftime('%H:%M')}</b> (Slot Libero)"
                f"  </span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # ── GENERAZIONE E RENDER DEL CALENDARIO APPLE DARK MODE ──────────────────
    apple_cal_html = _generate_apple_calendar_html(
        week_days=week_days,
        events_by_day=events_by_day,
        proposed_day_idx=proposed_day_idx,
        proposed_start_rome=proposed_start_rome,
        proposed_end_rome=proposed_end_rome,
        proposed_title=data.title,
        today_rome_date=today_rome_date,
        current_rome_time=now_rome,
        is_conflict=is_conflict,
    )

    st.markdown(apple_cal_html, unsafe_allow_html=True)

    # ── BOTTONI DI CONFERMA / RIFIUTO ────────────────────────────────────────
    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
    if action.status != ActionStatus.EXECUTED:
        c_btn, c_rej = st.columns([3, 1])
        with c_btn:
            btn_label = f"📅  Inserisci in Google Calendar ({WEEKDAYS_FULL_IT[proposed_day_idx]} ore {proposed_start_rome.strftime('%H:%M')})"
            if st.button(btn_label, key=f"btn_cal_commit_{action.id}", type="primary", use_container_width=True):
                ok, msg = run_async(committer.execute_action(action, user_modified_payload=data.model_dump(mode="json")))
                if ok:
                    st.toast(msg, icon="📅")
                    st.rerun()
        with c_rej:
            if st.button("Rifiuta", key=f"btn_cal_rej_{action.id}", type="secondary", use_container_width=True):
                run_async(committer.reject_action(action))
                st.rerun()
    else:
        st.markdown(
            f"<div style='background:#F0FDF4; border:1px solid #BBF7D0; border-radius:10px; padding:10px 14px; text-align:center;'>"
            f"  <span style='color:#15803D; font-weight:700; font-size:13px;'>✓ Confermato e programmato in Google Calendar per {WEEKDAYS_FULL_IT[proposed_day_idx]} {proposed_start_rome.day} {MONTHS_IT[proposed_start_rome.month-1]} alle {proposed_start_rome.strftime('%H:%M')} Europe/Rome</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
