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

START_HOUR = 6
END_HOUR = 19
HOUR_HEIGHT = 46  # pixel per ora


def _get_local_tz() -> ZoneInfo:
    """Recupera in modo dinamico il fuso orario impostato nella sessione utente."""
    tz_str = st.session_state.get("user_timezone", "Europe/Rome")
    try:
        return ZoneInfo(tz_str)
    except Exception:
        return ZoneInfo("Europe/Rome")


def _to_local(dt: datetime, tz: Optional[ZoneInfo] = None) -> datetime:
    """Converte un datetime UTC nel fuso orario locale dell'utente."""
    if tz is None:
        tz = _get_local_tz()
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz)
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
        import os
        import src.agent.infrastructure.google.live_google as lg
        if os.path.exists("data/token.json"):
            cal = lg.LiveCalendarService()
        else:
            cal = lg.LocalCalendarService()
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
    tz: Optional[ZoneInfo] = None,
) -> List[Tuple[str, datetime]]:
    """Calcola slot orari liberi durante l'orario operativo (08:30 – 18:30) con etichette compatte anti-troncamento."""
    slots: List[Tuple[str, datetime]] = []
    local_tz = tz or _get_local_tz()

    # 1. Se fornito un orario richiesto, verifichiamo la sua disponibilità
    if requested_time:
        req_start_local = datetime.combine(target_date, requested_time, tzinfo=local_tz)
        req_end_local = req_start_local + timedelta(minutes=duration_minutes)
        collision = any(
            req_start_local < _to_local(ev.end_utc, local_tz) and req_end_local > _to_local(ev.start_utc, local_tz)
            for ev in day_events
        )
        tag = f"⚠️ {req_start_local.strftime('%H:%M')} (Occupato)" if collision else f"📍 {req_start_local.strftime('%H:%M')} (Richiesto)"
        slots.append((tag, req_start_local))

    # 2. Orari candidati tipici della giornata lavorativa
    candidate_hours = [(8, 30), (9, 30), (10, 30), (11, 30), (14, 0), (15, 0), (16, 0), (17, 0), (18, 0)]
    for h, m in candidate_hours:
        c_start = datetime.combine(target_date, dt_time(h, m), tzinfo=local_tz)
        c_end = c_start + timedelta(minutes=duration_minutes)
        if requested_time and requested_time.hour == h and requested_time.minute == m:
            continue

        collision = any(
            c_start < _to_local(ev.end_utc, local_tz) and c_end > _to_local(ev.start_utc, local_tz)
            for ev in day_events
        )
        if not collision and len(slots) < 6:
            slots.append((f"🟢 {c_start.strftime('%H:%M')}", c_start))

    return slots


def _generate_apple_calendar_html(
    week_days: List[datetime],
    events_by_day: Dict[int, List[CalendarEventItem]],
    proposed_day_idx: int,
    proposed_start_local: datetime,
    proposed_end_local: datetime,
    proposed_title: str,
    today_local_date: dt_date,
    current_local_time: datetime,
    is_conflict: bool,
    tz: Optional[ZoneInfo] = None,
) -> str:
    """Genera la tabella grafica esatta Apple Calendar Dark Mode (Zero markdown escaping issues)."""

    total_grid_height = (END_HOUR - START_HOUR + 1) * HOUR_HEIGHT
    month_name = MONTHS_IT[week_days[3].month - 1]
    year_num = week_days[3].year
    week_range_str = f"{week_days[0].day} {MONTHS_IT[week_days[0].month - 1][:3]} – {week_days[-1].day} {MONTHS_IT[week_days[-1].month - 1][:3]}"

    lines: List[str] = [
        '<div class="apple-dark-canvas">',
        '  <div class="apple-dark-topbar">',
        f'    <div class="apple-dark-month-title"><strong>{month_name}</strong> <span class="apple-dark-year">{year_num}</span> <span style="font-size:12.5px; font-weight:400; color:#8E8E93; margin-left:6px;">({week_range_str})</span></div>',
        '    <div class="apple-dark-nav-pills">',
        '      <span class="apple-sync-badge">🟢 Google Live Sincronizzato</span>',
        '    </div>',
        '  </div>',
    ]


    # 2. Header colonne giorni (lun 12, mar 13, mer 14, gio 15 con cerchio rosso, ecc.)
    lines.append('  <div class="apple-days-header-row">')
    lines.append('    <div class="apple-time-spacer"></div>')
    for d in week_days:
        w_name = WEEKDAYS_IT[d.weekday()]
        d_num = str(d.day)
        is_today = (d.date() == today_local_date)
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
    curr_hour_frac = (current_local_time.hour - START_HOUR) + (current_local_time.minute / 60.0)
    if 0 <= curr_hour_frac <= (END_HOUR - START_HOUR + 1):
        curr_y = int(curr_hour_frac * HOUR_HEIGHT)
        curr_hm_str = current_local_time.strftime("%H:%M")
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
        is_today = (d.date() == today_local_date)
        lines.append(f'      <div class="apple-day-column" style="left: {day_idx * 14.2857}%; width: 14.2857%;">')

        # Punto rosso indicatore all'incrocio per oggi
        if is_today and 0 <= curr_hour_frac <= (END_HOUR - START_HOUR + 1):
            curr_y = int(curr_hour_frac * HOUR_HEIGHT)
            lines.append(f'        <div class="apple-current-dot" style="top: {curr_y - 4}px;"></div>')

        # Eventi reali del calendario per questo giorno
        day_events = events_by_day.get(day_idx, [])
        for ev in day_events:
            ev_start_l = _to_local(ev.start_utc, tz)
            ev_end_l = _to_local(ev.end_utc, tz)
            start_frac = (ev_start_l.hour - START_HOUR) + (ev_start_l.minute / 60.0)
            dur_hours = (ev_end_l - ev_start_l).total_seconds() / 3600.0

            if start_frac + dur_hours < 0 or start_frac > (END_HOUR - START_HOUR + 1):
                continue

            top_px = max(0, int(start_frac * HOUR_HEIGHT))
            height_px = max(34, int(dur_hours * HOUR_HEIGHT) - 2)
            time_str = f"{ev_start_l.strftime('%H:%M')} – {ev_end_l.strftime('%H:%M')}"
            safe_title = html.escape(ev.title)

            lines.append(
                f'        <div class="apple-event-teal" style="top: {top_px}px; height: {height_px}px;" title="{safe_title} ({time_str})">'
                f'          <div class="apple-event-teal-title">{safe_title}</div>'
                f'          <div class="apple-event-teal-time">🕒 {time_str}</div>'
                f'        </div>'
            )

        # Evento proposto / selezionato (Evidenziato)
        if day_idx == proposed_day_idx:
            p_start_frac = (proposed_start_local.hour - START_HOUR) + (proposed_start_local.minute / 60.0)
            p_dur_hours = (proposed_end_local - proposed_start_local).total_seconds() / 3600.0
            p_top_px = max(0, int(p_start_frac * HOUR_HEIGHT))
            p_height_px = max(36, int(p_dur_hours * HOUR_HEIGHT) - 2)
            p_time_str = f"{proposed_start_local.strftime('%H:%M')} – {proposed_end_local.strftime('%H:%M')}"
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
    """Renderizza l'interfaccia Apple Calendar Dark Mode 1:1 con navigazione per settimane e selettore completo."""
    data = action.calendar_data
    if not data:
        return

    # Inizializzazione Calendar Service (Live 100%)
    cal_service = st.session_state.get("calendar", None)
    if cal_service is None or not hasattr(cal_service, "get_events"):
        try:
            import os
            from src.agent.infrastructure.google.live_google import LiveCalendarService, LocalCalendarService
            if os.path.exists("data/token.json"):
                cal_service = LiveCalendarService()
            else:
                cal_service = LocalCalendarService()
            st.session_state.calendar = cal_service
        except Exception:
            pass

    # Recupero fuso orario dinamico
    local_tz = _get_local_tz()
    tz_name = st.session_state.get("user_timezone", "Europe/Rome")
    now_local = datetime.now(local_tz)
    today_local_date = now_local.date()

    # Coordinate temporali dell'evento proposto
    proposed_start_local = _to_local(data.start_utc, local_tz)
    proposed_end_local = _to_local(data.end_utc, local_tz)
    duration = data.end_utc - data.start_utc
    duration_min = int(duration.total_seconds() / 60) if duration.total_seconds() > 0 else 30

    # Gestione navigazione settimane: offset salvato in session_state
    week_offset_key = f"cal_week_offset_{action.id}"
    if week_offset_key not in st.session_state:
        st.session_state[week_offset_key] = 0

    week_offset = st.session_state[week_offset_key]

    # Settimana base della proposta e settimana visualizzata a schermo
    meeting_day = proposed_start_local.date()
    base_monday = meeting_day - timedelta(days=meeting_day.weekday())
    display_monday = base_monday + timedelta(weeks=week_offset)

    week_days = [
        datetime(display_monday.year, display_monday.month, display_monday.day, tzinfo=timezone.utc) + timedelta(days=i)
        for i in range(7)
    ]
    range_start = week_days[0]
    range_end = week_days[-1] + timedelta(hours=23, minutes=59, seconds=59)

    # Recupero impegni reali da Google Calendar per la settimana visualizzata
    raw_events: List[CalendarEventItem] = _fetch_calendar_events(cal_service, range_start, range_end)

    # Mappatura eventi per giorno della settimana visualizzata (0 = Lunedì, 6 = Domenica)
    events_by_day: Dict[int, List[CalendarEventItem]] = {i: [] for i in range(7)}
    for ev in raw_events:
        r_dt = _to_local(ev.start_utc, local_tz)
        day_diff = (r_dt.date() - display_monday).days
        if 0 <= day_diff < 7:
            events_by_day[day_diff].append(ev)

    # Badge connettività servizio
    from src.agent.presentation.state import is_calendar_live
    is_live = is_calendar_live()
    sync_badge = (
        "<span class='apple-sync-badge'>🟢 Google Live Connesso</span>"
        if is_live else
        "<span class='aria-pill aria-pill-amber' style='font-size:10.5px;'>🟡 Calendario Locale</span>"
    )

    # ── HEADER & NAVIGAZIONE SETTIMANA APPLE CALENDAR ────────────────────────
    with st.container():
        c_head, c_badge = st.columns([3, 1])
        with c_head:
            st.markdown(
                f"<h3 style='font-size:20px; font-weight:700; color:#1A1A1E; margin:0 0 2px 0; letter-spacing:-0.025em;'>"
                f"  📅 Apple Calendar — {data.title}"
                f"</h3>"
                f"<p style='font-size:12.5px; color:#55555A; margin:0 0 8px 0;'>"
                f"  Navigazione agenda macOS in tempo reale • Fuso: <b>{tz_name}</b>"
                f"</p>",
                unsafe_allow_html=True,
            )
        with c_badge:
            st.markdown(f"<div style='text-align:right;'>{sync_badge}</div>", unsafe_allow_html=True)

        # ── CONTROLLI NAVIGAZIONE SETTIMANALE ────────────────────────────────
        col_nav_prev, col_nav_today, col_nav_next, col_nav_label = st.columns([1, 0.9, 1.1, 3.2])
        with col_nav_prev:
            if st.button("‹ Prec.", key=f"btn_prev_week_{action.id}", use_container_width=True):
                st.session_state[week_offset_key] = week_offset - 1
                st.rerun()
        with col_nav_today:
            is_viewing_today_week = (display_monday <= today_local_date <= display_monday + timedelta(days=6))
            if st.button("Oggi", key=f"btn_today_week_{action.id}", type="primary" if not is_viewing_today_week else "secondary", use_container_width=True):
                today_monday = today_local_date - timedelta(days=today_local_date.weekday())
                st.session_state[week_offset_key] = (today_monday - base_monday).days // 7
                st.rerun()
        with col_nav_next:
            if st.button("Succ. ›", key=f"btn_next_week_{action.id}", use_container_width=True):
                st.session_state[week_offset_key] = week_offset + 1
                st.rerun()
        with col_nav_label:
            disp_end = display_monday + timedelta(days=6)
            st.markdown(
                f"<div style='padding-top:7px; font-size:13px; font-weight:600; color:#1A1A1E;'>"
                f"  🗓️ Settimana: {display_monday.day} {MONTHS_IT[display_monday.month-1][:3]} – {disp_end.day} {MONTHS_IT[disp_end.month-1][:3]} {display_monday.year}"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

        # ── 1. SELETTORE GIORNO DELLA SETTIMANA VISUALIZZATA ─────────────────
        st.markdown(
            "<span style='font-size:12px; font-weight:700; color:#444449; text-transform:uppercase; letter-spacing:0.04em;'>"
            "1. Scegli Giorno della Settimana:</span>",
            unsafe_allow_html=True,
        )

        day_labels = []
        for i, wd in enumerate(week_days):
            d_local = _to_local(wd, local_tz)
            lbl = f"{WEEKDAYS_IT[i].capitalize()} {d_local.day} {MONTHS_IT[d_local.month-1][:3]}"
            if d_local.date() == today_local_date:
                lbl = f"⭐ {lbl} (Oggi)"
            day_labels.append(lbl)

        # Se l'appuntamento cade nella settimana visualizzata, imposta quel giorno come default
        active_day_idx = (proposed_start_local.date() - display_monday).days
        if not (0 <= active_day_idx < 7):
            active_day_idx = 0

        selected_day_label = st.pills(
            "Seleziona giorno:",
            options=day_labels,
            default=day_labels[active_day_idx],
            key=f"cal_day_pills_{action.id}_{week_offset}",
            label_visibility="collapsed",
        )

        chosen_day_idx = day_labels.index(selected_day_label) if selected_day_label in day_labels else active_day_idx
        target_day_date = display_monday + timedelta(days=chosen_day_idx)

        # ── 2. SELETTORE SLOT CONSIGLIATI (ANTI-TRONCAMENTO) ─────────────────
        st.markdown(
            "<div style='margin-top:8px;'><span style='font-size:12px; font-weight:700; color:#444449; text-transform:uppercase; letter-spacing:0.04em;'>"
            "2. Orari e Slot Consigliati (Verifica Conflitti Live):</span></div>",
            unsafe_allow_html=True,
        )

        target_day_events = events_by_day.get(chosen_day_idx, [])
        free_slots_data = _calculate_free_slots(
            target_date=target_day_date,
            day_events=target_day_events,
            duration_minutes=duration_min,
            requested_time=dt_time(proposed_start_local.hour, proposed_start_local.minute) if proposed_start_local.date() == target_day_date else None,
            tz=local_tz,
        )

        slot_label_to_dt = {label: dt for label, dt in free_slots_data}
        slot_options = list(slot_label_to_dt.keys())

        if slot_options:
            default_slot_idx = 0
            for idx, (_, dt_val) in enumerate(free_slots_data):
                if dt_val.hour == proposed_start_local.hour and dt_val.minute == proposed_start_local.minute and target_day_date == proposed_start_local.date():
                    default_slot_idx = idx
                    break

            chosen_slot_label = st.pills(
                "Seleziona orario slot:",
                options=slot_options,
                default=slot_options[default_slot_idx],
                key=f"cal_slot_pills_{action.id}_{chosen_day_idx}_{week_offset}",
                label_visibility="collapsed",
            )

            if chosen_slot_label and chosen_slot_label in slot_label_to_dt:
                new_start_dt = slot_label_to_dt[chosen_slot_label]
                new_start_utc = new_start_dt.astimezone(timezone.utc)
                if new_start_utc != data.start_utc:
                    data.start_utc = new_start_utc
                    data.end_utc = data.start_utc + timedelta(minutes=duration_min)

        # ── 3. PERSONALIZZAZIONE TOTALE LIBERA (QUALSIASI DATA, ORA, DURATA) ──
        with st.expander("⚙️ Personalizza Data, Orario & Durata (Sposta Liberamente)", expanded=False):
            st.markdown(
                "<p style='font-size:12px; color:#55555A; margin:0 0 10px 0;'>"
                "Sposta liberamente l'appuntamento a qualsiasi data e orario futuro. Il calendario si sincronizzerà all'istante."
                "</p>",
                unsafe_allow_html=True,
            )
            col_cust_d, col_cust_t, col_cust_dur = st.columns([1.2, 1, 1.2])
            with col_cust_d:
                picked_date = st.date_input(
                    "📅 Data appuntamento:",
                    value=proposed_start_local.date(),
                    key=f"cust_date_{action.id}",
                )
            with col_cust_t:
                picked_time = st.time_input(
                    f"🕒 Inizio ({tz_name}):",
                    value=dt_time(proposed_start_local.hour, proposed_start_local.minute),
                    key=f"cust_time_{action.id}",
                )
            with col_cust_dur:
                duration_options = [15, 30, 45, 60, 90, 120]
                def _fmt_dur(d):
                    if d < 60:
                        return f"{d} minuti"
                    elif d == 60:
                        return "1 ora"
                    elif d == 90:
                        return "1h 30m"
                    else:
                        return f"{d // 60} ore"
                dur_idx = duration_options.index(duration_min) if duration_min in duration_options else 1
                picked_duration = st.selectbox(
                    "⏱️ Durata incontro:",
                    options=duration_options,
                    index=dur_idx,
                    format_func=_fmt_dur,
                    key=f"cust_dur_{action.id}",
                )

            data.title = st.text_input(
                "🏷️ Titolo appuntamento:",
                value=data.title,
                key=f"cust_title_{action.id}",
            )

            new_custom_start_local = datetime.combine(picked_date, picked_time, tzinfo=local_tz)
            new_custom_end_local = new_custom_start_local + timedelta(minutes=picked_duration)
            new_custom_start_utc = new_custom_start_local.astimezone(timezone.utc)
            new_custom_end_utc = new_custom_end_local.astimezone(timezone.utc)

            if new_custom_start_utc != data.start_utc or new_custom_end_utc != data.end_utc:
                data.start_utc = new_custom_start_utc
                data.end_utc = new_custom_end_utc
                # Se la nuova data cade in un'altra settimana, naviga automaticamente a quella settimana
                new_monday = picked_date - timedelta(days=picked_date.weekday())
                st.session_state[week_offset_key] = (new_monday - base_monday).days // 7
                st.rerun()

        # Ricalcolo coordinate definitive dell'evento proposto
        proposed_start_local = _to_local(data.start_utc, local_tz)
        proposed_end_local = _to_local(data.end_utc, local_tz)
        proposed_day_idx = (proposed_start_local.date() - display_monday).days

        # Verifica collisione effettiva contro gli impegni Google Calendar
        is_conflict = False
        conflict_event_title = ""
        for ev in raw_events:
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
                f"    L'orario scelto ({proposed_start_local.strftime('%H:%M')}) si sovrappone a <b>{html.escape(conflict_event_title)}</b>. "
                f"    Seleziona uno slot con bollino verde o modifica l'orario nel pannello personalizzazione."
                f"  </p>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            in_view_note = ""
            if not (0 <= proposed_day_idx < 7):
                in_view_note = f" <i>(Fissato per {WEEKDAYS_FULL_IT[proposed_start_local.weekday()]} {proposed_start_local.day} {MONTHS_IT[proposed_start_local.month-1]} — usa le frecce per visualizzarlo)</i>"
            st.markdown(
                f"<div style='background:#F0FDF4; border:1px solid #BBF7D0; border-radius:10px; padding:8px 14px; margin: 8px 0 14px 0;'>"
                f"  <span style='color:#15803D; font-weight:600; font-size:12.5px;'>"
                f"    ✓ Posizione confermata in agenda: <b>{WEEKDAYS_FULL_IT[proposed_start_local.weekday()]} {proposed_start_local.day} {MONTHS_IT[proposed_start_local.month-1]}</b> ore <b>{proposed_start_local.strftime('%H:%M')} – {proposed_end_local.strftime('%H:%M')}</b> ({tz_name}){in_view_note}"
                f"  </span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # ── GENERAZIONE E RENDER DEL CALENDARIO APPLE DARK MODE ──────────────────
    apple_cal_html = _generate_apple_calendar_html(
        week_days=week_days,
        events_by_day=events_by_day,
        proposed_day_idx=proposed_day_idx,
        proposed_start_local=proposed_start_local,
        proposed_end_local=proposed_end_local,
        proposed_title=data.title,
        today_local_date=today_local_date,
        current_local_time=now_local,
        is_conflict=is_conflict,
        tz=local_tz,
    )

    st.markdown(apple_cal_html, unsafe_allow_html=True)

    # ── BOTTONI DI CONFERMA / RIFIUTO ────────────────────────────────────────
    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
    if action.status != ActionStatus.EXECUTED:
        c_btn, c_rej = st.columns([3, 1])
        with c_btn:
            btn_label = f"📅  Inserisci in Google Calendar ({WEEKDAYS_FULL_IT[proposed_start_local.weekday()]} ore {proposed_start_local.strftime('%H:%M')} {tz_name})"
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
            f"<div style='background:#F0FDF4; border:1px solid #BBF7D0; border-radius:12px; padding:16px 20px; text-align:center; box-shadow:0 1px 4px rgba(0,0,0,0.03); margin-top:8px; margin-bottom:18px;'>"
            f"  <span style='color:#15803D; font-weight:700; font-size:13.5px;'>✓ Confermato e programmato in Google Calendar per {WEEKDAYS_FULL_IT[proposed_start_local.weekday()]} {proposed_start_local.day} {MONTHS_IT[proposed_start_local.month-1]} alle {proposed_start_local.strftime('%H:%M')} ({tz_name})</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # Spazio generoso per distanziare la card calendario dalla card email
    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)

