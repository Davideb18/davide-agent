"""
calendar_card.py — Scheda Calendario Esecutiva in Stile Nativo Apple Calendar macOS.
Filosofia: Zero frizioni, massima automazione, colori fedeli ad Apple Calendar ed eccellente leggibilità.
"""
import html
from datetime import datetime, timedelta, timezone, time as dt_time, date as dt_date
from typing import List, Optional, Dict
from zoneinfo import ZoneInfo
import streamlit as st

from src.agent.domain.enums import ActionStatus, ActionType
from src.agent.domain.models import ProposedAction, CalendarEventItem
from src.agent.presentation.state import run_async, is_calendar_live

from src.agent.domain.datetime_utils import (
    WEEKDAYS_LOWER_IT as WEEKDAYS_IT,
    WEEKDAYS_SHORT_IT,
    WEEKDAYS_FULL_IT,
    MONTHS_SHORT_IT,
    MONTHS_FULL_IT as MONTHS_IT,
    WEEKDAYS_SHORT_EN,
    WEEKDAYS_FULL_EN,
    MONTHS_SHORT_EN,
    MONTHS_FULL_EN as MONTHS_EN,
    format_localized_slot,
    format_full_localized_slot,
    resolve_timezone,
    is_english as check_is_english,
    is_self_mention,
)


def _is_english_session() -> bool:
    """Verifica se la sessione corrente o il profilo utente è in lingua inglese."""
    session = st.session_state.get("current_session")
    if not session:
        return False
    lang = getattr(session, "detected_language", "it") or "it"
    return check_is_english(str(lang))


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Assicura che il datetime sia timezone-aware in UTC, rendendo matematicamente impossibile un TypeError."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_slot_label(dt: datetime) -> str:
    """Formatta un datetime nella lingua della sessione (italiano o inglese)."""
    user_tz = st.session_state.get("user_timezone", "Europe/Rome")
    lang = "en" if _is_english_session() else "it"
    return format_localized_slot(dt, user_tz=user_tz, lang=lang)


def _sync_calendar_change_to_email(action_id: str, new_slot_str: str) -> None:
    """Rigenera reattivamente la bozza email solo se esplicitamente collegata a questo incontro."""
    session = st.session_state.get("current_session")
    if not session or not hasattr(st.session_state, "extractor") or not st.session_state.extractor:
        return

    cal_act = next((a for a in session.proposed_actions if a.id == action_id), None)
    cal_title = (cal_act.calendar_data.title or "").lower() if cal_act and cal_act.calendar_data else ""
    cal_attendees = [att.lower() for att in (cal_act.calendar_data.attendees or [])] if cal_act and cal_act.calendar_data else []

    email_act = None
    for a in session.proposed_actions:
        if a.action_type == ActionType.EMAIL_DRAFT and a.email_data:
            # 1. Corrispondenza per linked_calendar_action_id
            if a.email_data.linked_calendar_action_id == action_id:
                email_act = a
                break
            # 2. Corrispondenza per nome interlocutore
            r_name = (a.email_data.recipient_name or "").lower().strip()
            if r_name and (r_name in cal_title or any(r_name in att for att in cal_attendees)):
                a.email_data.linked_calendar_action_id = action_id
                email_act = a
                break
            # 3. Corrispondenza per email esterna correlata alla call
            user_profile = st.session_state.get("user_profile")
            user_kws = {"me", "me stesso", "myself", "io", "stesso"}
            if user_profile and user_profile.first_name:
                user_kws.add(user_profile.first_name.lower())
            if not is_self_mention(r_name, user_kws):
                subj_low = (a.email_data.subject or "").lower()
                body_low = (a.email_data.body_markdown or "").lower()
                if any(w in subj_low or w in body_low for w in ["call", "appuntamento", "meeting", "riunione", "orario"]):
                    a.email_data.linked_calendar_action_id = action_id
                    email_act = a
                    break

    if email_act and email_act.email_data:
        try:
            ver = st.session_state.get(f"email_ver_{email_act.id}", 0)
            manual_body = st.session_state.get(f"body_{email_act.id}_{ver}")
            if manual_body and manual_body.strip():
                email_act.email_data.body_markdown = manual_body.strip()

            history = getattr(session, "person_history", None)
            with st.spinner("Riallineamento bozza email con l'orario concordato..."):
                new_payload = run_async(
                    st.session_state.extractor.regenerate_email_draft(
                        original_payload=email_act.email_data,
                        new_slot_str=new_slot_str,
                        history=history,
                        user_tz=st.session_state.get("user_timezone", "Europe/Rome"),
                    )
                )
            if new_payload:
                email_act.email_data = new_payload
                new_ver = ver + 1
                st.session_state[f"email_ver_{email_act.id}"] = new_ver
                st.session_state[f"body_{email_act.id}_{new_ver}"] = new_payload.body_markdown
                st.session_state[f"subj_{email_act.id}_{new_ver}"] = new_payload.subject

                # Sincronizza anche con il database se presente
                if hasattr(st.session_state, "repo") and st.session_state.repo:
                    run_async(st.session_state.repo.save_session(session))

                st.toast("Bozza email riallineata al nuovo orario!", icon="✉️")
        except Exception:
            pass


def _get_local_tz() -> ZoneInfo:
    """Recupera in modo dinamico il fuso orario impostato nella sessione utente."""
    return resolve_timezone(st.session_state.get("user_timezone", "Europe/Rome"))


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


def _generate_mini_week_html(
    display_monday: dt_date,
    week_events: List[CalendarEventItem],
    target_date: dt_date,
    start_local: datetime,
    end_local: datetime,
    title: str,
    today_date: dt_date,
    local_tz: ZoneInfo,
) -> str:
    """Genera la mini griglia settimanale in perfetto stile nativo Apple Calendar macOS (Sonoma/Sequoia)."""
    # Determina l'intervallo orario ottimale (min_h e max_h) in modo dinamico
    # per includere eventi del mattino presto, orario d'ufficio e impegni serali/notturni
    all_hours = [start_local.hour, (end_local.hour if end_local.minute == 0 else end_local.hour + 1)]
    for ev in week_events:
        s_loc = _to_local(ev.start_utc, local_tz)
        e_loc = _to_local(ev.end_utc, local_tz)
        all_hours.append(s_loc.hour)
        all_hours.append(e_loc.hour if e_loc.minute == 0 else e_loc.hour + 1)

    min_h = max(0, min(7, min(all_hours)))
    max_h = min(24, max(22, max(all_hours)))
    hour_height = 24  # 24px per ora per garantire totale leggibilità di titolo e orario
    total_h = (max_h - min_h) * hour_height
    days = [display_monday + timedelta(days=i) for i in range(7)]

    events_by_day: Dict[int, List[CalendarEventItem]] = {i: [] for i in range(7)}
    for ev in week_events:
        s_loc = _to_local(ev.start_utc, local_tz)
        diff = (s_loc.date() - display_monday).days
        if 0 <= diff < 7:
            events_by_day[diff].append(ev)

    lines: List[str] = [
        '<div style="background:#FFFFFF; border:1px solid #E5E5EA; border-radius:14px; padding:14px 16px; margin-top:10px; font-family:-apple-system,BlinkMacSystemFont,\'SF Pro Text\',sans-serif; box-shadow:0 4px 16px rgba(0,0,0,0.05); overflow:hidden;">',
        '  <div style="display:flex; border-bottom:1px solid #E5E5EA; padding-bottom:8px; margin-bottom:6px;">',
        '    <div style="width:46px; font-size:10px; color:#8E8E93; font-weight:700; text-align:right; padding-right:10px;">Ora</div>',
    ]

    days_short = WEEKDAYS_SHORT_EN if _is_english_session() else WEEKDAYS_SHORT_IT
    for i, d in enumerate(days):
        is_today = (d == today_date)
        is_target = (d == target_date)
        d_name = days_short[i].upper()

        if is_today:
            # Badge iconico Apple Calendar: cerchio rosso pieno
            d_html = (
                f'<span style="color:#FF3B30; font-weight:800; font-size:11px;">{d_name}</span> '
                f'<span style="background:#FF3B30; color:#FFFFFF; border-radius:50%; width:22px; height:22px; display:inline-flex; align-items:center; justify-content:center; font-weight:700; font-size:11.5px; margin-left:2px;">{d.day}</span>'
            )
        elif is_target:
            # Giorno selezionato per il meeting: evidenziato in Apple Blue
            d_html = (
                f'<span style="color:#007AFF; font-weight:800; font-size:11px;">{d_name}</span> '
                f'<span style="background:rgba(0,122,255,0.12); color:#007AFF; border-radius:50%; width:22px; height:22px; display:inline-flex; align-items:center; justify-content:center; font-weight:700; font-size:11.5px; margin-left:2px;">{d.day}</span>'
            )
        else:
            d_html = (
                f'<span style="color:#8E8E93; font-weight:600; font-size:11px;">{d_name}</span> '
                f'<span style="color:#1D1D1F; font-weight:700; font-size:11.5px; margin-left:2px;">{d.day}</span>'
            )

        lines.append(f'    <div style="flex:1; text-align:center;">{d_html}</div>')
    lines.append('  </div>')

    # Corpo griglia oraria in stile Apple Calendar (con overflow:hidden per evitare fuoriuscite visive)
    lines.append(f'  <div style="display:flex; height:{total_h}px; position:relative; overflow:hidden;">')

    # Asse orari a sinistra
    lines.append('    <div style="width:46px; position:relative; border-right:1px solid #E5E5EA;">')
    for h in range(min_h, max_h + 1):
        y = (h - min_h) * hour_height
        lines.append(f'      <div style="position:absolute; top:{y-7}px; right:10px; font-size:9.5px; color:#8E8E93; font-family:-apple-system,monospace; font-weight:500;">{h:02d}:00</div>')
    lines.append('    </div>')

    # Colonne dei 7 giorni
    lines.append('    <div style="flex:1; display:flex; position:relative;">')

    # Linee orizzontali di riferimento
    for h in range(min_h, max_h + 1):
        y = (h - min_h) * hour_height
        lines.append(f'      <div style="position:absolute; left:0; right:0; top:{y}px; height:1px; background:#F2F2F7; pointer-events:none;"></div>')

    for day_idx, d in enumerate(days):
        col_bg = "background:rgba(0,122,255,0.04);" if d == target_date else ""
        lines.append(f'      <div style="flex:1; position:relative; border-right:1px solid #E5E5EA; overflow:hidden; {col_bg}">')

        day_start = datetime(d.year, d.month, d.day, min_h, 0, 0, tzinfo=local_tz)
        day_end = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=local_tz) if max_h >= 24 else datetime(d.year, d.month, d.day, max_h, 0, 0, tzinfo=local_tz)

        # Impegni reali Google Calendar con clamping rigoroso all'intervallo visibile
        for ev in events_by_day.get(day_idx, []):
            ev_s = _to_local(ev.start_utc, local_tz)
            ev_e = _to_local(ev.end_utc, local_tz)
            vis_s = max(ev_s, day_start)
            vis_e = min(ev_e, day_end)
            if vis_e <= vis_s:
                continue

            s_frac = (vis_s.hour - min_h) + vis_s.minute / 60.0
            dur = (vis_e - vis_s).total_seconds() / 3600.0
            top_px = max(0, min(int(s_frac * hour_height), total_h - 18))
            h_px = max(18, min(int(dur * hour_height) - 2, total_h - top_px))
            safe_title = html.escape(ev.title)
            lines.append(
                f'        <div style="position:absolute; left:2px; right:2px; top:{top_px}px; height:{h_px}px; background:#EFF6FF; border-left:3.5px solid #2563EB; border-radius:5px; padding:2px 5px; overflow:hidden; z-index:1; box-shadow:0 1px 3px rgba(0,0,0,0.06);" title="{safe_title} ({ev_s.strftime("%H:%M")} – {ev_e.strftime("%H:%M")})">'
                f'          <div style="font-weight:700; font-size:10px; color:#1E40AF; line-height:1.2; overflow:hidden; white-space:nowrap; text-overflow:ellipsis;">{safe_title}</div>'
                f'          <div style="font-size:8.5px; color:#3B82F6; font-weight:600; line-height:1.1;">🕒 {ev_s.strftime("%H:%M")} – {ev_e.strftime("%H:%M")}</div>'
                f'        </div>'
            )

        # Box Nuovo Appuntamento Proposto (clamped alle ore della griglia)
        if d == target_date:
            p_vis_s = max(start_local, day_start)
            p_vis_e = min(end_local, day_end)
            if p_vis_e > p_vis_s:
                p_s_frac = (p_vis_s.hour - min_h) + p_vis_s.minute / 60.0
                p_dur = (p_vis_e - p_vis_s).total_seconds() / 3600.0
                p_top_px = max(0, min(int(p_s_frac * hour_height), total_h - 22))
                p_h_px = max(22, min(int(p_dur * hour_height) - 2, total_h - p_top_px))
                safe_t = html.escape(title or "Nuovo Appuntamento")
                lines.append(
                    f'        <div style="position:absolute; left:2px; right:2px; top:{p_top_px}px; height:{p_h_px}px; background:#007AFF; border-left:3.5px solid #0051B3; border-radius:6px; padding:2px 6px; overflow:hidden; z-index:3; box-shadow:0 3px 10px rgba(0,122,255,0.35);" title="Nuovo: {safe_t} ({start_local.strftime("%H:%M")})">'
                    f'          <div style="font-weight:800; font-size:10.5px; color:#FFFFFF; line-height:1.2; overflow:hidden; white-space:nowrap; text-overflow:ellipsis;">📍 {safe_t}</div>'
                    f'          <div style="font-size:9px; color:#E0F2FE; font-weight:700; line-height:1.1;">🕒 {start_local.strftime("%H:%M")} – {end_local.strftime("%H:%M")}</div>'
                    f'        </div>'
                )
        lines.append('      </div>')

    lines.append('    </div>')
    lines.append('  </div>')
    lines.append('</div>')
    return "".join(line.strip() for line in lines)


def render_calendar_card(action: ProposedAction, committer):
    """Renderizza la card appuntamento con banner conflitto extra spesso ed estetica Apple Calendar."""
    data = action.calendar_data
    if not data:
        return

    # Se l'azione è stata scartata, mostra un banner compatto e minimalista
    if action.status == ActionStatus.REJECTED:
        with st.container(border=True):
            col_t, col_undo = st.columns([4, 1])
            with col_t:
                st.markdown(
                    f"<div style='display:flex; align-items:center; gap:8px; color:#8E8E93; font-size:13px; font-weight:600; padding:4px 0;'>"
                    f"<span>🗑️</span>"
                    f"<span style='text-decoration:line-through;'>Appuntamento: {html.escape(data.title)}</span>"
                    f"<span class='aria-pill aria-pill-grey' style='font-size:10px;'>Scartato</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            with col_undo:
                if st.button("Ripristina", key=f"btn_undo_cal_{action.id}", use_container_width=True):
                    action.status = ActionStatus.PROPOSED
                    st.rerun()
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
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

    local_tz = _get_local_tz()
    tz_name = st.session_state.get("user_timezone", "Europe/Rome")
    now_local = datetime.now(local_tz)
    today_local_date = now_local.date()

    # Orari locali dell'evento
    start_local = _to_local(data.start_utc, local_tz)
    end_local = _to_local(data.end_utc, local_tz)
    duration_min = max(15, int((data.end_utc - data.start_utc).total_seconds() / 60))

    is_en = _is_english_session()
    target_date = start_local.date()
    weekday_str = WEEKDAYS_FULL_EN[target_date.weekday()] if is_en else WEEKDAYS_FULL_IT[target_date.weekday()]
    month_str = MONTHS_EN[target_date.month - 1] if is_en else MONTHS_IT[target_date.month - 1]

    # Gestione navigazione settimane per la mini anteprima
    week_offset_key = f"mini_cal_offset_{action.id}"
    if week_offset_key not in st.session_state:
        st.session_state[week_offset_key] = 0

    week_offset = st.session_state[week_offset_key]
    meeting_monday = target_date - timedelta(days=target_date.weekday())
    display_monday = meeting_monday + timedelta(weeks=week_offset)
    display_sunday = display_monday + timedelta(days=6)

    # Recupero eventi reali per la settimana visualizzata nella mini anteprima
    w_start_utc = datetime(display_monday.year, display_monday.month, display_monday.day, 0, 0, 0, tzinfo=local_tz).astimezone(timezone.utc)
    w_end_utc = datetime(display_sunday.year, display_sunday.month, display_sunday.day, 23, 59, 59, tzinfo=local_tz).astimezone(timezone.utc)
    week_events: List[CalendarEventItem] = _fetch_calendar_events(cal_service, w_start_utc, w_end_utc)

    # Verifica collisione effettiva sull'evento proposto (escludendo se già sincronizzato o evento stesso)
    is_conflict = (action.status == ActionStatus.CONFLICT_DETECTED)
    conflict_title = ""
    if action.status != ActionStatus.EXECUTED:
        d_start = _ensure_utc(data.start_utc)
        d_end = _ensure_utc(data.end_utc)
        for ev in week_events:
            ev_start = _ensure_utc(ev.start_utc)
            ev_end = _ensure_utc(ev.end_utc)
            if d_start and d_end and ev_start and ev_end and d_start < ev_end and d_end > ev_start:
                # Non considerare in conflitto l'evento appena inserito con lo stesso titolo
                if ev.title.strip().lower() == data.title.strip().lower():
                    continue
                is_conflict = True
                conflict_title = ev.title
                break
    else:
        is_conflict = False

    if is_conflict and not conflict_title:
        conflict_title = "Impegno già presente in calendario" if not is_en else "Existing calendar commitment"

    # Se c'è conflitto ma non abbiamo ancora calcolato le alternative, calcolale all'istante
    if is_conflict and not data.alternative_slots_utc and action.status != ActionStatus.EXECUTED:
        try:
            if cal_service and hasattr(cal_service, "find_alternative_slots"):
                user_tz_curr = st.session_state.get("user_timezone", "Europe/Rome")
                found_alts = run_async(
                    cal_service.find_alternative_slots(data.start_utc, duration_min, count=3, user_tz=user_tz_curr)
                )
                if found_alts:
                    data.alternative_slots_utc = found_alts
        except Exception:
            pass


    live_connected = is_calendar_live()
    sync_badge = (
        f"<span class='aria-pill aria-pill-green' style='font-size:11px; font-weight:700;'>🟢 {'Google Live Connected' if is_en else 'Google Live Connesso'}</span>"
        if live_connected else
        f"<span class='aria-pill aria-pill-amber' style='font-size:11px; font-weight:700;'>🟡 {'Local Calendar' if is_en else 'Calendario Locale'}</span>"
    )

    with st.container(border=True):
        # 1. Testata della scheda
        header_title = "📅 Calendar Appointment" if is_en else "📅 Appuntamento in Agenda"
        st.markdown(
            f"""
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
                <h3 style="font-size:19px; font-weight:800; color:#1D1D1F; margin:0; letter-spacing:-0.02em;">
                    {header_title}
                </h3>
                {sync_badge}
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 2. BANNER DI STATO DISPONIBILITÀ: Extra spesso, grosso e con altissimo contrasto visivo
        if is_conflict:
            warn_title = "Attention: Overlapping Event Detected!" if is_en else "Attenzione: Sovrapposizione Orario Rilevata!"
            warn_msg = (
                f"At <b>{start_local.strftime('%H:%M')}</b> you already have: <b style='text-decoration:underline;'>{html.escape(conflict_title)}</b>."
                if is_en else
                f"Alle ore <b>{start_local.strftime('%H:%M')}</b> hai già in calendario: <b style='text-decoration:underline;'>{html.escape(conflict_title)}</b>."
            )
            has_alts = bool(data.alternative_slots_utc and action.status != ActionStatus.EXECUTED)
            if has_alts:
                warn_sub = "👇 Click a recommended free slot to apply it immediately:" if is_en else "👇 Clicca su uno slot libero consigliato per applicarlo all'istante:"
            else:
                warn_sub = "👉 Seleziona un orario alternativo dal pannello 'Regola Rapidamente' a destra:" if not is_en else "👉 Select an alternative slot from the 'Quick Adjust' panel on the right:"

            status_html = (
                f"<div style='background:#FEF2F2; border:3.5px solid #EF4444; border-radius:14px; padding:16px 20px; margin-bottom:16px; box-shadow:0 4px 14px rgba(239,68,68,0.15);'>"
                f"  <div style='display:flex; align-items:center; gap:10px; margin-bottom:6px;'>"
                f"    <span style='font-size:24px; line-height:1;'>⚠️</span>"
                f"    <span style='font-size:17px; font-weight:800; color:#991B1B; text-transform:uppercase; letter-spacing:0.02em;'>"
                f"      {warn_title}"
                f"    </span>"
                f"  </div>"
                f"  <p style='color:#B91C1C; font-size:14.5px; font-weight:600; margin:0 0 10px 0; line-height:1.45;'>"
                f"    {warn_msg}"
                f"  </p>"
                f"  <div style='font-size:12.5px; font-weight:700; color:#7F1D1D;'>"
                f"    {warn_sub}"
                f"  </div>"
                f"</div>"
            )
            st.markdown(status_html, unsafe_allow_html=True)

            if has_alts:
                alt_cols = st.columns(min(len(data.alternative_slots_utc), 3))
                for idx, alt_utc in enumerate(data.alternative_slots_utc[:3]):
                    alt_loc = _to_local(alt_utc, local_tz)
                    btn_lbl = _format_slot_label(alt_loc)
                    with alt_cols[idx]:
                        if st.button(f"👉 {btn_lbl}", key=f"btn_alt_slot_{action.id}_{idx}", use_container_width=True):
                            data.start_utc = alt_utc
                            data.end_utc = alt_utc + timedelta(minutes=duration_min)
                            action.status = ActionStatus.PROPOSED
                            data.alternative_slots_utc = []
                            st.session_state[week_offset_key] = 0
                            st.session_state[f"cal_date_{action.id}"] = alt_loc.date()
                            st.session_state[f"cal_time_{action.id}"] = dt_time(alt_loc.hour, alt_loc.minute)
                            new_slot_text = (
                                f"{WEEKDAYS_FULL_EN[alt_loc.weekday()]} {alt_loc.day} {MONTHS_EN[alt_loc.month-1]} at {alt_loc.strftime('%H:%M')}"
                                if is_en else
                                f"{WEEKDAYS_FULL_IT[alt_loc.weekday()]} {alt_loc.day} {MONTHS_IT[alt_loc.month-1]} ore {alt_loc.strftime('%H:%M')}"
                            )
                            data.slot_reasoning = (
                                f"Slot alternativo consigliato ({btn_lbl}) applicato per evitare sovrapposizioni in agenda."
                                if not is_en else
                                f"Recommended alternative slot ({btn_lbl}) applied to resolve calendar conflicts."
                            )
                            _sync_calendar_change_to_email(action.id, new_slot_text)
                            st.toast(f"Orario aggiornato con successo: {btn_lbl}", icon="🗓️")
                            st.rerun()
                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        else:
            ok_title = "Time Slot Available in Calendar" if is_en else "Orario Disponibile in Agenda"
            ok_msg = (
                f"No conflicts detected. The slot <b>{weekday_str} {target_date.day} {month_str} at {start_local.strftime('%H:%M')} – {end_local.strftime('%H:%M')}</b> is free on Google Calendar!"
                if is_en else
                f"Nessun conflitto rilevato. Lo slot <b>{weekday_str} {target_date.day} {month_str} ore {start_local.strftime('%H:%M')} – {end_local.strftime('%H:%M')}</b> è libero su Google Calendar!"
            )
            status_html = (
                f"<div style='background:#F0FDF4; border:3.5px solid #22C55E; border-radius:14px; padding:15px 20px; margin-bottom:16px; box-shadow:0 4px 14px rgba(34,197,94,0.12);'>"
                f"  <div style='display:flex; align-items:center; gap:10px;'>"
                f"    <span style='font-size:24px; color:#16A34A; line-height:1;'>✓</span>"
                f"    <div>"
                f"      <div style='font-size:17px; font-weight:800; color:#166534; text-transform:uppercase; letter-spacing:0.02em;'>"
                f"        {ok_title}"
                f"      </div>"
                f"      <p style='color:#15803D; font-size:14px; font-weight:600; margin:2px 0 0 0;'>"
                f"        {ok_msg}"
                f"      </p>"
                f"    </div>"
                f"  </div>"
                f"</div>"
            )
            st.markdown(status_html, unsafe_allow_html=True)

        # 3. Dettagli Appuntamento e Modifica Rapida (Nessun doppio box ridondante)
        col_summary, col_edit = st.columns([1.5, 1.5], gap="large")

        with col_summary:
            summary_lbl = "Event Summary" if is_en else "Riepilogo Evento"
            time_lbl = f"🕒 {start_local.strftime('%H:%M')} – {end_local.strftime('%H:%M')}"
            st.markdown(
                f"""
                <div style="padding: 4px 2px;">
                    <div style="font-size:11px; font-weight:700; color:#8E8E93; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:4px;">
                        {summary_lbl}
                    </div>
                    <div style="font-size:20px; font-weight:800; color:#1D1D1F; margin-bottom:8px; line-height:1.25;">
                        {html.escape(data.title)}
                    </div>
                    <div style="display:flex; align-items:center; gap:8px; font-size:14.5px; font-weight:700; color:#007AFF; margin-bottom:10px;">
                        <span>🗓️ {weekday_str} {target_date.day} {month_str} {target_date.year}</span>
                        <span>•</span>
                        <span>{time_lbl}</span>
                    </div>
                    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                        <span class="aria-pill aria-pill-blue" style="font-size:11.5px; font-weight:600;">⏱️ {duration_min} min</span>
                        <span class="aria-pill aria-pill-purple" style="font-size:11.5px; font-weight:600;">🌍 {tz_name}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if getattr(data, "slot_reasoning", None):
                st.markdown(
                    f"""
                    <div style="background:#F0F9FF; border:1px solid #BAE6FD; border-left:4px solid #007AFF; border-radius:10px; padding:10px 14px; margin-top:10px;">
                        <div style="font-size:10.5px; font-weight:800; color:#0369A1; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:3px; display:flex; align-items:center; gap:6px;">
                            <span>💡</span> <span>{"Slot Reasoning" if is_en else "Motivazione orario individuato"}</span>
                        </div>
                        <div style="font-size:12.5px; color:#0C4A6E; line-height:1.45; font-weight:500;">
                            {html.escape(data.slot_reasoning)}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        with col_edit:
            is_exec = (action.status == ActionStatus.EXECUTED)
            adjust_lbl = "Quick Adjust" if is_en else "Regola Rapidamente"
            st.markdown(
                f"<div style='font-size:11px; font-weight:700; color:#8E8E93; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:6px;'>"
                f"{adjust_lbl}</div>",
                unsafe_allow_html=True,
            )

            # Titolo modificabile inline
            title_input_lbl = "Meeting title:" if is_en else "Titolo incontro:"
            data.title = st.text_input(
                title_input_lbl,
                value=data.title,
                key=f"cal_title_{action.id}",
                disabled=is_exec,
            )

            # Data e Ora affiancati (Massima fluidità: nessuna chiamata LLM bloccante)
            c_d, c_t = st.columns([1.2, 1])
            with c_d:
                date_input_lbl = "Date:" if is_en else "Data:"
                new_date = st.date_input(
                    date_input_lbl,
                    value=target_date,
                    key=f"cal_date_{action.id}",
                    disabled=is_exec,
                )
            with c_t:
                time_input_lbl = f"Time ({tz_name}):" if is_en else f"Ora ({tz_name}):"
                new_time = st.time_input(
                    time_input_lbl,
                    value=dt_time(start_local.hour, start_local.minute),
                    key=f"cal_time_{action.id}",
                    disabled=is_exec,
                )

            # Sincronizzazione immediata e fluida su cambio data/ora
            new_start_local = datetime.combine(new_date, new_time, tzinfo=local_tz)
            new_start_utc = new_start_local.astimezone(timezone.utc)
            if new_start_utc != data.start_utc:
                data.start_utc = new_start_utc
                data.end_utc = data.start_utc + timedelta(minutes=duration_min)
                action.status = ActionStatus.PROPOSED
                data.alternative_slots_utc = []
                new_monday = new_date - timedelta(days=new_date.weekday())
                st.session_state[week_offset_key] = (new_monday - meeting_monday).days // 7
                new_slot_text = (
                    f"{WEEKDAYS_FULL_EN[new_start_local.weekday()]} {new_start_local.day} {MONTHS_EN[new_start_local.month-1]} at {new_start_local.strftime('%H:%M')}"
                    if is_en else
                    f"{WEEKDAYS_FULL_IT[new_start_local.weekday()]} {new_start_local.day} {MONTHS_IT[new_start_local.month-1]} ore {new_start_local.strftime('%H:%M')}"
                )
                _sync_calendar_change_to_email(action.id, new_slot_text)
                st.rerun()

            st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

            # Pulsanti di Azione
            if not is_exec:
                c_btn, c_rej = st.columns([2.5, 1])
                with c_btn:
                    btn_text = "📅 Add to Google Calendar" if is_en else "📅 Inserisci in Google Calendar"
                    if st.button(btn_text, key=f"btn_cal_commit_{action.id}", type="primary", use_container_width=True):
                        curr_title = st.session_state.get(f"cal_title_{action.id}", data.title)
                        if curr_title:
                            data.title = curr_title
                        ok, msg = run_async(committer.execute_action(action, user_modified_payload=data.model_dump(mode="json")))
                        if ok:
                            st.toast(msg, icon="📅")
                            st.rerun()
                with c_rej:
                    rej_text = "Discard" if is_en else "Scarta"
                    if st.button(rej_text, key=f"btn_cal_rej_{action.id}", use_container_width=True):
                        run_async(committer.reject_action(action))
                        st.rerun()
            else:
                success_pill = "✓ Added Successfully" if is_en else "✓ Inserito con Successo"
                success_desc = (
                    f"Synchronized with Google Calendar for {weekday_str} {new_date.day} {month_str} at {new_time.strftime('%H:%M')}."
                    if is_en else
                    f"Sincronizzato in Google Calendar per {weekday_str} {new_date.day} {month_str} ore {new_time.strftime('%H:%M')}."
                )
                st.markdown(
                    f"""
                    <div style="background:#F0FDF4; border:1px solid #BBF7D0; border-radius:12px; padding:12px 16px;">
                        <span class="aria-pill aria-pill-green" style="font-size:11px; font-weight:700;">{success_pill}</span>
                        <p style="font-size:12.5px; color:#15803D; margin:4px 0 0 0; font-weight:600;">
                            {success_desc}
                        </p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        # 4. MINI PREVIEW SETTIMANALE DEL CALENDARIO (Stile macOS Apple Calendar)
        st.markdown("<hr style='border:none; border-top:1px solid #E5E5EA; margin:16px 0 10px 0;'/>", unsafe_allow_html=True)
        col_prev_head, col_prev_nav = st.columns([3, 1.3])
        with col_prev_head:
            months_short_list = MONTHS_SHORT_EN if is_en else MONTHS_SHORT_IT
            week_view_lbl = "🗓️ Week View:" if is_en else "🗓️ Vista Settimana:"
            st.markdown(
                f"<div style='font-size:13px; font-weight:700; color:#1D1D1F; padding-top:4px;'>"
                f"  {week_view_lbl} <b>{display_monday.day} {months_short_list[display_monday.month-1]} – {display_sunday.day} {months_short_list[display_sunday.month-1]} {display_monday.year}</b>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with col_prev_nav:
            c_p, c_t_btn, c_n = st.columns([1, 1.4, 1])
            with c_p:
                if st.button("‹", key=f"btn_mini_prev_{action.id}", help="Settimana precedente", use_container_width=True):
                    st.session_state[week_offset_key] = week_offset - 1
                    st.rerun()
            with c_t_btn:
                today_btn_lbl = "Today" if is_en else "Oggi"
                if st.button(today_btn_lbl, key=f"btn_mini_today_{action.id}", help="Settimana corrente", use_container_width=True):
                    today_monday = today_local_date - timedelta(days=today_local_date.weekday())
                    st.session_state[week_offset_key] = (today_monday - meeting_monday).days // 7
                    st.rerun()
            with c_n:
                if st.button("›", key=f"btn_mini_next_{action.id}", help="Settimana successiva", use_container_width=True):
                    st.session_state[week_offset_key] = week_offset + 1
                    st.rerun()

        # Render della mini griglia Apple Calendar
        mini_html = _generate_mini_week_html(
            display_monday=display_monday,
            week_events=week_events,
            target_date=target_date,
            start_local=start_local,
            end_local=end_local,
            title=data.title,
            today_date=today_local_date,
            local_tz=local_tz,
        )
        st.markdown(mini_html, unsafe_allow_html=True)

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
