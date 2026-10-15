"""
calendar_card.py — Interfaccia Apple Calendar Completa con Vista Multi-Giorno e Risoluzione Conflitti.
Design System: Apple macOS Calendar (Alte prestazioni, alto contrasto, zero cliché AI).
"""
from datetime import datetime, timedelta, timezone, time as dt_time
from typing import List, Optional
import streamlit as st

from src.agent.domain.enums import ActionStatus
from src.agent.domain.models import ProposedAction, CalendarEventItem

from src.agent.presentation.state import run_async, connect_live_google

WEEKDAYS_IT = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]
MONTHS_IT = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]


def _format_day_label(dt: datetime, suffix: str = "") -> str:
    w = WEEKDAYS_IT[dt.weekday()]
    m = MONTHS_IT[dt.month - 1]
    lbl = f"{w} {dt.day} {m}"
    if suffix:
        lbl += f" • {suffix}"
    return lbl


def _render_event_card(event: CalendarEventItem, is_conflict_target: bool = False):
    """Renderizza un singolo evento in stile Apple Calendar Card con accento cromatico."""
    time_str = f"{event.start_utc.strftime('%H:%M')} – {event.end_utc.strftime('%H:%M')} UTC"
    card_cls = "apple-event-card"
    if is_conflict_target:
        card_cls += " apple-event-conflict"
    elif event.color_tag == "purple":
        card_cls += " apple-event-purple"
    elif event.color_tag == "orange":
        card_cls += " apple-event-orange"
    elif event.color_tag == "green":
        card_cls += " apple-event-green"
    elif event.color_tag == "red":
        card_cls += " apple-event-red"
    else:
        card_cls += " apple-event-blue"

    loc_str = event.location or "Google Meet"
    att_str = ", ".join(event.attendees) if event.attendees else "Partecipanti standard"

    conflict_badge = ""
    if is_conflict_target:
        conflict_badge = '<span class="aria-pill aria-pill-amber" style="font-size:10px; margin-left:8px;">⚠️ Sovrapposizione Orario</span>'

    html = f"""
    <div class="{card_cls}">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <span class="apple-event-time">{time_str}</span>
            {conflict_badge}
        </div>
        <div class="apple-event-title">{event.title}</div>
        <div class="apple-event-meta">
            <span>📍 {loc_str}</span>
            <span>👥 {att_str}</span>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

    # Dettagli attività ispezionabili
    with st.expander(f"Dettagli: {event.title} ({time_str})"):
        st.markdown(f"**Descrizione:** {event.description or 'Nessuna nota aggiuntiva specificata.'}")
        if event.attendees:
            st.markdown(f"**Partecipanti convocati:** `{'`, `'.join(event.attendees)}`")
        if event.location:
            st.markdown(f"**Luogo / Collegamento:** {event.location}")


def _fetch_calendar_events(cal_service, range_start: datetime, range_end: datetime) -> List[CalendarEventItem]:
    """Recupera la lista eventi in modo resiliente e sicuro senza mai bloccare la UI."""
    if cal_service and hasattr(cal_service, "get_events"):
        try:
            return run_async(cal_service.get_events(range_start, range_end)) or []
        except Exception:
            pass

    # Se cal_service non ha get_events (es. istanza stale di una sessione Streamlit precedente)
    try:
        import importlib
        import src.agent.infrastructure.google.mock_google as mock_mod
        mock_mod = importlib.reload(mock_mod)
        fresh_cal = mock_mod.MockCalendarService()
        st.session_state.calendar = fresh_cal
        return run_async(fresh_cal.get_events(range_start, range_end)) or []
    except Exception:
        pass

    return []


def render_calendar_card(action: ProposedAction, committer):
    """Renderizza l'interfaccia Apple Calendar con visualizzazione agenda e gestione conflitti."""
    data = action.calendar_data
    if not data:
        return

    cal_service = st.session_state.get("calendar", None)
    _required_methods = ("get_events", "check_is_busy", "find_alternative_slots", "create_event")
    if cal_service is None or not all(hasattr(cal_service, m) for m in _required_methods):
        try:
            import importlib
            import src.agent.infrastructure.google.mock_google as mock_mod
            mock_mod = importlib.reload(mock_mod)
            cal_service = mock_mod.MockCalendarService()
            st.session_state.calendar = cal_service
        except Exception:
            pass

    with st.container(border=True):
        # ── HEADER CARD ──────────────────────────────────────────────────────
        col_title, col_status = st.columns([3.6, 1.4])
        with col_title:
            st.markdown(
                f"<h3 style='font-size:19px; font-weight:700; color:#1A1A1E; margin:0 0 4px 0; letter-spacing:-0.025em;'>"
                f"📅 Agenda Apple Calendar — {data.title}</h3>",
                unsafe_allow_html=True,
            )
            st.caption(
                f"Visualizzazione agenda sincronizzata • Fuso orario: Europe/Rome (UTC)"
            )
        with col_status:
            if action.status == ActionStatus.EXECUTED:
                st.markdown('<span class="aria-pill aria-pill-green" style="float:right;">Confermato ✓</span>', unsafe_allow_html=True)
            elif action.status == ActionStatus.CONFLICT_DETECTED:
                st.markdown('<span class="aria-pill aria-pill-amber" style="float:right;">Conflitto ⚠</span>', unsafe_allow_html=True)
            else:
                st.markdown('<span class="aria-pill aria-pill-blue" style="float:right;">Proposta</span>', unsafe_allow_html=True)

        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

        # ── FINESTRA TEMPORALE A 3 GIORNI (IERI, OGGI/MEETING, DOMANI) ────────
        meeting_day = data.start_utc.date()
        yesterday = meeting_day - timedelta(days=1)
        tomorrow = meeting_day + timedelta(days=1)

        range_start = datetime(yesterday.year, yesterday.month, yesterday.day, 0, 0, tzinfo=timezone.utc)
        range_end = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 23, 59, 59, tzinfo=timezone.utc)

        # Recupero impegni dal Calendar Service (Google Calendar Live o Mock Realistico con Fallback Sicuro)
        events: List[CalendarEventItem] = _fetch_calendar_events(cal_service, range_start, range_end)

        # Raggruppamento per giorno
        events_yesterday = [e for e in events if e.start_utc.date() == yesterday]
        events_meeting_day = [e for e in events if e.start_utc.date() == meeting_day]
        events_tomorrow = [e for e in events if e.start_utc.date() == tomorrow]

        # ── TABS MULTI-GIORNO STILE APPLE CALENDAR ────────────────────────────
        tab_yest_title = f"{_format_day_label(datetime(yesterday.year, yesterday.month, yesterday.day))} ({len(events_yesterday)})"
        tab_meet_title = f"⭐ {_format_day_label(datetime(meeting_day.year, meeting_day.month, meeting_day.day))} (Incontro)"
        tab_tomo_title = f"{_format_day_label(datetime(tomorrow.year, tomorrow.month, tomorrow.day))} ({len(events_tomorrow)})"

        tab_yest, tab_today, tab_tomo = st.tabs([tab_yest_title, tab_meet_title, tab_tomo_title])

        # ── TAB 1: IERI ───────────────────────────────────────────────────────
        with tab_yest:
            st.markdown(
                f"<p style='font-size:12.5px; font-weight:600; color:#6E6E73; margin-bottom:12px; text-transform:uppercase; letter-spacing:0.04em;'>"
                f"Agenda di {yesterday.strftime('%d/%m/%Y')}</p>",
                unsafe_allow_html=True,
            )
            if events_yesterday:
                for ev in sorted(events_yesterday, key=lambda x: x.start_utc):
                    _render_event_card(ev)
            else:
                st.info("Nessun impegno registrato per questa giornata.")

        # ── TAB 2: GIORNO DELL'INCONTRO (OGGI / TARGET) ──────────────────────
        with tab_today:
            st.markdown(
                f"<p style='font-size:12.5px; font-weight:600; color:#1A1A1E; margin-bottom:12px; text-transform:uppercase; letter-spacing:0.04em;'>"
                f"Agenda di {meeting_day.strftime('%d/%m/%Y')} — Visualizzazione Incontro & Conflitti</p>",
                unsafe_allow_html=True,
            )

            # Rilevamento visivo dell'evento che collide
            conflict_event = None
            if action.status == ActionStatus.CONFLICT_DETECTED:
                for ev in events_meeting_day:
                    if data.start_utc < ev.end_utc and data.end_utc > ev.start_utc:
                        conflict_event = ev
                        break

            # Se c'è conflitto, mostriamo il box di avviso sobrio
            if action.status == ActionStatus.CONFLICT_DETECTED and action.status != ActionStatus.EXECUTED:
                colliding_name = conflict_event.title if conflict_event else "un evento già programmato in agenda"
                st.markdown(
                    f"""
                    <div style="background: #FFFBF0; border: 1px solid #FDE68A; border-radius: 12px; padding: 12px 16px; margin-bottom: 14px;">
                        <div style="display:flex; align-items:center; gap:8px;">
                            <span style="font-size: 16px;">⚠️</span>
                            <div>
                                <strong style="font-size: 13.5px; color: #92400E;">Orario Occupato: {data.start_utc.strftime('%H:%M')} UTC</strong>
                                <p style="font-size: 12px; color: #78350F; margin: 2px 0 0 0;">
                                    L'orario richiesto si sovrappone a <b>{colliding_name}</b>. Scegli uno degli slot liberi consigliati o imposta un orario a tua scelta:
                                </p>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # Selettore Slot Alternativi
                alt_options = []
                slots_list = data.alternative_slots_utc or []
                for i, slot in enumerate(slots_list):
                    tag = "Consigliato" if i == 0 else "Disponibile"
                    alt_options.append(f"🟢 {slot.strftime('%H:%M')} UTC ({tag})")
                alt_options.append("🕒 Personalizza Orario...")

                chosen_slot_str = st.radio(
                    "Seleziona la collocazione in agenda per questo incontro:",
                    options=alt_options,
                    key=f"radio_slot_choice_{action.id}",
                )

                new_start: Optional[datetime] = None
                duration = data.end_utc - data.start_utc

                if chosen_slot_str == "🕒 Personalizza Orario...":
                    col_h, _ = st.columns([1, 1])
                    with col_h:
                        custom_time = st.time_input(
                            "Orario desiderato (UTC):",
                            value=dt_time(hour=data.start_utc.hour, minute=data.start_utc.minute),
                            key=f"custom_time_cal_{action.id}",
                        )
                    new_start = datetime(
                        meeting_day.year, meeting_day.month, meeting_day.day,
                        custom_time.hour, custom_time.minute, tzinfo=timezone.utc
                    )
                else:
                    slot_index = alt_options.index(chosen_slot_str)
                    if slot_index < len(slots_list):
                        new_start = slots_list[slot_index]

                if new_start:
                    data.start_utc = new_start
                    data.end_utc = new_start + duration

            # Render della Timeline del Giorno con eventi esistenti + Nuovo Appuntamento Posizionato
            events_to_show = sorted(events_meeting_day, key=lambda x: x.start_utc)

            for ev in events_to_show:
                is_colliding = (conflict_event and ev.id == conflict_event.id)
                _render_event_card(ev, is_conflict_target=is_colliding)

            # Card dell'Appuntamento Proposto o Spostato
            if action.status != ActionStatus.EXECUTED:
                slot_info = f"{data.start_utc.strftime('%H:%M')} – {data.end_utc.strftime('%H:%M')} UTC"
                st.markdown(
                    f"""
                    <div class="apple-event-card apple-event-proposed">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <span style="font-size:12px; font-weight:700; color:#15803D;">
                                📍 POSIZIONE INCONTRO SELEZIONATA: {slot_info}
                            </span>
                            <span class="aria-pill aria-pill-green" style="font-size:10px;">Pronto per Conferma</span>
                        </div>
                        <div class="apple-event-title" style="color:#14532D; margin-top:4px;">
                            {data.title}
                        </div>
                        <div class="apple-event-meta" style="color:#166534;">
                            <span>📍 {data.location or 'Google Meet'}</span>
                            <span>👥 {', '.join(data.attendees) if data.attendees else 'Partecipanti concordati'}</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"""
                    <div class="apple-event-card apple-event-green">
                        <div class="apple-event-time">
                            ✓ CONFERMATO IN AGENDA: {data.start_utc.strftime('%H:%M')} – {data.end_utc.strftime('%H:%M')} UTC
                        </div>
                        <div class="apple-event-title">{data.title}</div>
                        <div class="apple-event-meta">
                            <span>📍 {data.location or 'Google Meet'}</span>
                            <span>👥 {', '.join(data.attendees)}</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        # ── TAB 3: DOMANI ─────────────────────────────────────────────────────
        with tab_tomo:
            st.markdown(
                f"<p style='font-size:12.5px; font-weight:600; color:#6E6E73; margin-bottom:12px; text-transform:uppercase; letter-spacing:0.04em;'>"
                f"Agenda di {tomorrow.strftime('%d/%m/%Y')}</p>",
                unsafe_allow_html=True,
            )
            if events_tomorrow:
                for ev in sorted(events_tomorrow, key=lambda x: x.start_utc):
                    _render_event_card(ev)
            else:
                st.info("Nessun impegno registrato per questa giornata.")

        # ── AZIONI DI COMMIT / DECISIONE UTENTE ──────────────────────────────
        if action.status != ActionStatus.EXECUTED:
            st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
            col_b1, col_b2, col_b3 = st.columns([2.5, 1, 2])
            with col_b1:
                target_label = f"📅  Inserisci in Google Calendar ({data.start_utc.strftime('%H:%M')} UTC)"
                if st.button(target_label, key=f"btn_cal_{action.id}", type="primary", use_container_width=True):
                    ok, msg = run_async(committer.execute_action(action, user_modified_payload=data.model_dump(mode="json")))
                    if ok:
                        st.toast(msg, icon="📅")
                        st.rerun()
            with col_b2:
                if st.button("Rifiuta", key=f"btn_cal_reject_{action.id}", use_container_width=True):
                    run_async(committer.reject_action(action))
                    st.rerun()
            with col_b3:
                # Opzione di collegamento rapido Google Calendar se stiamo usando Mock
                if not getattr(st.session_state, "google_live_connected", False):
                    if st.button("🔗 Connetti Google Live", key=f"btn_auth_gcal_{action.id}", use_container_width=True):
                        connected = connect_live_google()
                        if connected:
                            st.session_state.google_live_connected = True
                            st.toast("Connesso con successo al tuo Google Calendar!", icon="🔗")
                            st.rerun()
