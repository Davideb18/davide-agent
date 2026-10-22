"""
email_card.py — Card Bozza Email Follow-up in stile macOS Window / Gmail.
Design pulito, contrasto elevato, reattività sul cambio destinatario e copywriting sobrio.
"""
import html
import re
from typing import Optional, List
import streamlit as st
from src.agent.domain.enums import ActionStatus
from src.agent.domain.models import ProposedAction, Contact
from src.agent.domain.datetime_utils import clean_spoken_email, is_self_mention
from src.agent.presentation.state import run_async, is_email_live


def _adapt_greeting_locally(text: str, new_name: str) -> str:
    """Adatta immediatamente il saluto e i vocativi (es. Ciao Davide -> Ciao David) in modo deterministico."""
    clean = (new_name or "").strip()
    if not clean or not text:
        return text
    raw_lower = clean.lower()
    is_fem = (
        any(raw_lower.endswith(e) for e in ("a", "mamma", "madre", "sorella", "nonna"))
        and not any(raw_lower == m for m in ("luca", "andrea", "mattia", "nicola", "elia"))
    )
    # 1. Saluto informale tipo "Ciao <Nome>," o "Buongiorno <Nome>,"
    text = re.sub(
        r'^(Ciao|Buongiorno|Salve|Hi|Hello|Dear)\s+[A-Za-zÀ-ÿ]+([,\n!])',
        rf'\1 {clean}\2',
        text,
        flags=re.MULTILINE,
    )
    # 2. Saluto formale o affettuoso "Caro <Nome>," / "Cara <Nome>,"
    if is_fem:
        text = re.sub(r'^(Car[oa]|Gentile)\s+[A-Za-zÀ-ÿ]+([,\n!])', rf'Cara {clean}\2', text, flags=re.MULTILINE)
    else:
        text = re.sub(r'^(Car[oa]|Gentile)\s+[A-Za-zÀ-ÿ]+([,\n!])', rf'Caro {clean}\2', text, flags=re.MULTILINE)
    return text


def render_email_card(mail_action: ProposedAction, know_action: Optional[ProposedAction], committer):
    """Renderizza la finestra per la bozza email di follow-up con sincronizzazione reattiva del destinatario."""
    data = mail_action.email_data
    if not data:
        return

    # Se l'azione email è stata scartata, mostra un banner compatto e discreto
    if mail_action.status == ActionStatus.REJECTED:
        with st.container(border=True):
            col_t, col_undo = st.columns([4, 1])
            with col_t:
                st.markdown(
                    f"<div style='display:flex; align-items:center; gap:8px; color:#8E8E93; font-size:13px; font-weight:600; padding:4px 0;'>"
                    f"<span>🗑️</span>"
                    f"<span style='text-decoration:line-through;'>Bozza email: {html.escape(data.subject or 'Nuovo messaggio')} (per {html.escape(data.recipient_name or 'destinatario')})</span>"
                    f"<span class='aria-pill aria-pill-grey' style='font-size:10px;'>Scartata</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            with col_undo:
                if st.button("Ripristina", key=f"btn_undo_mail_{mail_action.id}", use_container_width=True):
                    mail_action.status = ActionStatus.PROPOSED
                    st.rerun()
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        return

    # Recupero contatti salvati per auto-suggerimento email al cambio nome
    repo = st.session_state.get("repo")
    saved_contacts: List[Contact] = []
    if repo and hasattr(repo, "get_contacts"):
        try:
            saved_contacts = run_async(repo.get_contacts()) or []
        except Exception:
            saved_contacts = []

    # Chiavi univoche per gli input del destinatario
    name_key = f"recip_name_{mail_action.id}"
    email_key = f"recip_email_{mail_action.id}"
    last_adapted_key = f"last_adapted_name_{mail_action.id}"

    # Inizializza session state se assente
    # Inizializza session state se assente
    if name_key not in st.session_state:
        st.session_state[name_key] = data.recipient_name or ""
    if email_key not in st.session_state:
        st.session_state[email_key] = clean_spoken_email(data.recipient_email or "")
    if last_adapted_key not in st.session_state:
        st.session_state[last_adapted_key] = (data.recipient_name or "").strip()

    # Normalizzazione automatica: se il nome o il destinatario è riferito all'utente, risolvi con profilo/rubrica
    curr_n_raw = st.session_state[name_key].strip()
    user_profile = st.session_state.get("user_profile")
    user_c = next((c for c in saved_contacts if "utente" in [t.lower() for t in c.tags] or "personale" in [t.lower() for t in c.tags]), None)

    self_keywords = {"me", "me stesso", "myself", "io", "stesso", "me stessa"}
    if user_profile:
        if user_profile.first_name: self_keywords.add(user_profile.first_name.lower().strip())
        if user_profile.last_name: self_keywords.add(user_profile.last_name.lower().strip())
        if user_profile.full_name: self_keywords.add(user_profile.full_name.lower().strip())
        for a in user_profile.aliases: self_keywords.add(a.lower().strip())
    elif user_c:
        if user_c.first_name: self_keywords.add(user_c.first_name.lower().strip())
        if user_c.last_name: self_keywords.add(user_c.last_name.lower().strip())
        for a in user_c.aliases: self_keywords.add(a.lower().strip())

    user_emails = set()
    if user_profile and user_profile.email:
        user_emails.add(user_profile.email.lower().strip())
    if user_c and user_c.email:
        user_emails.add(user_c.email.lower().strip())

    is_self = is_self_mention(curr_n_raw, self_keywords)

    if is_self:
        resolved_name = user_c.first_name if user_c else (user_profile.first_name if user_profile else "")
        resolved_email = user_c.email if user_c and user_c.email else (user_profile.email if user_profile else "")
        if resolved_name and curr_n_raw.lower() in ("me", "me stesso", "myself", "io", "me stessa"):
            st.session_state[name_key] = resolved_name
            data.recipient_name = resolved_name
        if resolved_email and not (st.session_state.get(email_key) or "").strip():
            st.session_state[email_key] = resolved_email
            data.recipient_email = resolved_email
    else:
        # REGOLA ZERO-LEAKAGE: Se non è l'utente stesso, la sua email personale non deve mai essere usata
        curr_e = (st.session_state.get(email_key) or "").strip().lower()
        if curr_e in user_emails:
            st.session_state[email_key] = ""
            data.recipient_email = ""

    # Aggiorna il nome nel payload senza mai cancellare l'indirizzo email inserito
    current_name = st.session_state[name_key].strip()
    data.recipient_name = current_name

    # Suggerisci email solo se il campo email è attualmente vuoto
    if not st.session_state[email_key].strip() and current_name:
        clean_target = current_name.lower()
        # 1. Cerca nei contatti salvati
        for c in saved_contacts:
            full = f"{c.first_name} {c.last_name}".lower().strip()
            aliases = [a.lower().strip() for a in (c.aliases or [])]
            if clean_target == full or clean_target == c.first_name.lower().strip() or clean_target in aliases:
                if c.email:
                    data.recipient_email = c.email
                    st.session_state[email_key] = c.email
                    st.toast(f"Email di {current_name} recuperata dalla rubrica: {c.email}", icon="👤")
                break

        # 2. Se ancora vuoto, cerca tra le entità della sessione o nel prompt
        if not st.session_state[email_key].strip():
            session_obj = st.session_state.get("current_session")
            if session_obj and getattr(session_obj, "entities", None):
                for ent in session_obj.entities:
                    if getattr(ent, "email", None) and ent.email.strip():
                        ent_lower = ent.raw_name.lower().strip()
                        if (
                            ent_lower in clean_target
                            or clean_target in ent_lower
                            or (is_self and is_self_mention(ent_lower, self_keywords))
                        ):
                            # Non leccare email dell'utente a terzi
                            if not is_self and ent.email.strip().lower() in user_emails:
                                continue
                            cleaned = clean_spoken_email(ent.email.strip())
                            data.recipient_email = cleaned
                            st.session_state[email_key] = cleaned
                            break

            if not st.session_state[email_key].strip() and is_self and session_obj:
                full_txt = f"{getattr(session_obj, 'raw_transcript', '') or ''} {getattr(session_obj, 'summary', '') or ''}"
                found_mails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', full_txt)
                if found_mails:
                    data.recipient_email = found_mails[0]
                    st.session_state[email_key] = found_mails[0]


    session = st.session_state.get("current_session")
    lang = getattr(session, "detected_language", "it") if session else "it"
    is_en = bool(lang and str(lang).lower().startswith("en"))

    email_live = is_email_live()
    live_lbl = "🟢 Gmail Live" if is_en else "🟢 Gmail Live"
    draft_lbl = "🟡 Local Draft" if is_en else "🟡 Bozza Locale"
    service_badge = (
        f'<span class="aria-pill aria-pill-green" style="font-size:10.5px; font-weight:700;">{live_lbl}</span>'
        if email_live else
        f'<span class="aria-pill aria-pill-amber" style="font-size:10.5px; font-weight:700;">{draft_lbl}</span>'
    )

    with st.container(border=True):
        is_followup = bool(data.linked_calendar_action_id)
        if is_followup:
            email_header = "✉️ Follow-up Email" if is_en else "✉️ Email di Follow-up"
            desc_text = "Draft reactively synced with Calendar schedule." if is_en else "Bozza allineata reattivamente con l'orario del Calendario."
        else:
            email_header = "✉️ Email Message" if is_en else "✉️ Messaggio Email"
            desc_text = "Draft generated automatically based on discussion and notes." if is_en else "Bozza generata automaticamente sulla base della conversazione."

        st.markdown(
            f"""
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
                <h3 style="font-size:19px; font-weight:800; color:#1D1D1F; margin:0; letter-spacing:-0.02em;">
                    {email_header}
                </h3>
                {service_badge}
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_left, col_right = st.columns([1, 1.4], gap="large")

        # Contesto a sinistra
        with col_left:
            recipient_section_lbl = "Recipient" if is_en else "Destinatario"
            st.markdown(
                f"<p style='font-size:11px; font-weight:700; color:#8E8E93; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:6px;'>{recipient_section_lbl}</p>",
                unsafe_allow_html=True,
            )
            default_disp_name = "Recipient" if is_en else "Destinatario"
            disp_name = st.session_state.get(name_key, data.recipient_name or default_disp_name)
            disp_email = st.session_state.get(email_key, data.recipient_email or "")

            if disp_email:
                email_line = f'<p style="font-size:12.5px; color:#0066CC; font-weight:600; margin:0 0 8px 0;">{disp_email}</p>'
            else:
                no_email_lbl = "(No email address provided)" if is_en else "(Nessun indirizzo email fornito)"
                email_line = f'<p style="font-size:12px; color:#8E8E93; font-style:italic; margin:0 0 8px 0;">{no_email_lbl}</p>'

            recipient_html = (
                f'<div style="background:#FFFFFF; border:1px solid #E5E5EA; border-radius:14px; padding:16px; box-shadow:0 2px 8px rgba(0,0,0,0.03);">'
                f'<p style="font-size:15px; font-weight:800; color:#1D1D1F; margin:0 0 4px 0;">{disp_name}</p>'
                f'{email_line}'
                f'<p style="font-size:12px; color:#48484A; margin:0; line-height:1.45;">{desc_text}</p>'
                f'</div>'
            )
            st.markdown(recipient_html, unsafe_allow_html=True)

            if know_action and know_action.knowledge_data and know_action.knowledge_data.bullet_insights:
                key_pts_lbl = "Key Takeaways:" if is_en else "Punti Principali:"
                st.markdown(
                    f"<p style='font-size:11px; font-weight:700; color:#8E8E93; text-transform:uppercase; letter-spacing:0.05em; margin:14px 0 6px 0;'>{key_pts_lbl}</p>",
                    unsafe_allow_html=True,
                )
                for point in know_action.knowledge_data.bullet_insights[:3]:
                    st.markdown(
                        f"<div style='font-size:12px; color:#1D1D1F; margin-bottom:6px; padding-left:10px; border-left:2.5px solid #007AFF; line-height:1.4;'>• {point}</div>",
                        unsafe_allow_html=True,
                    )

        # Finestra a destra
        with col_right:
            new_msg_lbl = "Gmail — New Message" if is_en else "Gmail — Nuovo Messaggio"
            titlebar_html = (
                '<div class="mac-titlebar" style="border-radius:14px 14px 0 0;">'
                '<span class="mac-dot mac-dot-red"></span>'
                '<span class="mac-dot mac-dot-yellow"></span>'
                '<span class="mac-dot mac-dot-green"></span>'
                f'<span style="font-size:12px; font-weight:600; color:#1D1D1F; margin-left:8px;">{new_msg_lbl}</span>'
                '</div>'
            )
            st.markdown(titlebar_html, unsafe_allow_html=True)

            if data.linked_calendar_action_id:
                link_lbl = "Draft reactively synced with Calendar schedule" if is_en else "Bozza allineata reattivamente con l'orario del Calendario"
                st.markdown(
                    f"<div style='background:#EFF6FF; border:1px solid #BFDBFE; border-radius:8px; padding:6px 10px; margin-bottom:8px; display:flex; align-items:center; gap:6px;'>"
                    f"<span style='font-size:12px;'>🔗</span>"
                    f"<span style='font-size:11px; color:#1D4ED8; font-weight:600;'>{link_lbl}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            # Badge informativo se destinatario privo di email (bozza aperta legittima)
            curr_email_val = (st.session_state.get(email_key) or data.recipient_email or "").strip()
            if not curr_email_val:
                open_draft_msg = (
                    "Open draft (no email address attached — ready for manual review)"
                    if is_en else
                    "Bozza aperta (nessun indirizzo email associato — pronta per revisione manuale)"
                )
                st.markdown(
                    f"""
                    <div style="background:#FFFBEB; border:1px solid #FDE68A; border-radius:8px; padding:6px 10px; margin-bottom:10px; display:flex; align-items:center; gap:6px;">
                        <span style="font-size:12px;">📝</span>
                        <span style="font-size:11.5px; color:#B45309; font-weight:600;">{open_draft_msg}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            is_exec = (mail_action.status == ActionStatus.EXECUTED)

            # ── SELETTORE RAPIDO DALLA RUBRICA (AUTO-BINDING) ─────────────────
            contacts_with_email = [c for c in saved_contacts if (c.email or "").strip()]
            if contacts_with_email and not is_exec:
                placeholder_opt = "— Mantieni destinatario attuale —" if not is_en else "— Keep current recipient —"
                contact_labels = [placeholder_opt] + [
                    f"👤 {c.first_name} {c.last_name}".strip() + f" <{c.email}>" for c in contacts_with_email
                ]
                # Pre-selezione automatica se corrisponde al contatto associato
                match_idx = 0
                check_mail = (st.session_state.get(email_key) or data.recipient_email or "").strip().lower()
                check_name = (st.session_state.get(name_key) or data.recipient_name or "").strip().lower()
                for i_c, c in enumerate(contacts_with_email):
                    c_mail = (c.email or "").strip().lower()
                    c_fn = (c.first_name or "").strip().lower()
                    c_full = f"{c.first_name} {c.last_name}".strip().lower()
                    c_alias = [a.lower().strip() for a in (c.aliases or [])]
                    c_is_user = ("utente" in [t.lower() for t in c.tags] or "personale" in [t.lower() for t in c.tags])

                    # Se il destinatario attuale non è l'utente, non pre-selezionare l'utente dal dropdown
                    if not is_self and c_is_user:
                        continue

                    if (check_mail and c_mail == check_mail) or (check_name and (check_name in (c_fn, c_full) or check_name in c_alias)):
                        match_idx = i_c + 1
                        break

                selected_opt = st.selectbox(
                    "Scegli dalla rubrica contatti:",
                    options=contact_labels,
                    index=match_idx,
                    key=f"quick_contact_pick_{mail_action.id}",
                    help="Seleziona un contatto per compilare automaticamente nome e indirizzo email.",
                )
                if selected_opt and selected_opt != placeholder_opt:
                    clean_choice = selected_opt.replace("👤 ", "")
                    picked_email = clean_choice.split("<")[-1].rstrip(">").strip()
                    picked_name = clean_choice.split("<")[0].strip()
                    if st.session_state.get(email_key) != picked_email:
                        st.session_state[email_key] = picked_email
                        st.session_state[name_key] = picked_name
                        st.session_state[last_adapted_key] = picked_name
                        data.recipient_email = picked_email
                        data.recipient_name = picked_name
                        st.toast(f"Contatto rubrica associato: {picked_name} ({picked_email})", icon="👤")
                        st.rerun()

            col_to_email, col_to_name = st.columns([1.4, 1.1])
            with col_to_email:
                email_input_lbl = "To (Recipient email):" if is_en else "A (Email destinatario):"
                email_placeholder = "e.g. name@email.com (optional)" if is_en else "es. nome@email.com (facoltativa)"
                new_email = st.text_input(
                    email_input_lbl,
                    key=email_key,
                    placeholder=email_placeholder,
                    disabled=is_exec,
                )
                data.recipient_email = new_email

            with col_to_name:
                name_input_lbl = "Recipient name:" if is_en else "Nome destinatario:"
                name_placeholder = "e.g. Mom, Marco..." if is_en else "es. Mamma, Marco..."
                new_name = st.text_input(
                    name_input_lbl,
                    key=name_key,
                    placeholder=name_placeholder,
                    disabled=is_exec,
                )
                data.recipient_name = new_name

            # Rilevamento cambio nome per riadattamento AUTOMATICO del testo (concordanza, genere, saluti)
            current_typed_name = (new_name or "").strip()
            prev_adapted_name = st.session_state.get(last_adapted_key, "").strip()
            name_has_changed = bool(
                current_typed_name
                and prev_adapted_name
                and current_typed_name.lower() != prev_adapted_name.lower()
                and not is_exec
            )

            ver = st.session_state.get(f"email_ver_{mail_action.id}", 0)

            # Riadattamento automatico immediato: zero clic manuali richiesti
            if name_has_changed:
                curr_body = st.session_state.get(f"body_{mail_action.id}_{ver}", data.body_markdown)
                # Adattamento immediato locale deterministico (0ms di latenza)
                locally_adapted = _adapt_greeting_locally(curr_body, current_typed_name)
                data.body_markdown = locally_adapted
                data.recipient_name = current_typed_name
                st.session_state[last_adapted_key] = current_typed_name
                ver_key = f"email_ver_{mail_action.id}"
                new_ver = ver + 1
                st.session_state[ver_key] = new_ver
                st.session_state[f"body_{mail_action.id}_{new_ver}"] = locally_adapted
                st.session_state[f"subj_{mail_action.id}_{new_ver}"] = data.subject

                # Affinamento con LLM in background se disponibile
                extractor = st.session_state.get("extractor")
                if extractor and hasattr(extractor, "adapt_email_recipient"):
                    try:
                        updated_payload = run_async(
                            extractor.adapt_email_recipient(
                                original_payload=data,
                                new_recipient_name=current_typed_name,
                            )
                        )
                        if updated_payload and updated_payload.body_markdown:
                            data.body_markdown = updated_payload.body_markdown
                            data.subject = updated_payload.subject
                            st.session_state[f"body_{mail_action.id}_{new_ver}"] = updated_payload.body_markdown
                            st.session_state[f"subj_{mail_action.id}_{new_ver}"] = updated_payload.subject
                    except Exception:
                        pass

                st.toast(f"Testo email aggiornato automaticamente per {current_typed_name}!", icon="✨")
                st.rerun()

            subj_lbl = "Subject:" if is_en else "Oggetto:"
            subj_key = f"subj_{mail_action.id}_{ver}"
            if subj_key not in st.session_state:
                st.session_state[subj_key] = data.subject or ""
            new_subj = st.text_input(
                subj_lbl,
                key=subj_key,
                disabled=is_exec,
            )
            data.subject = new_subj

            body_lbl = "Message body:" if is_en else "Testo del messaggio:"
            body_key = f"body_{mail_action.id}_{ver}"
            if body_key not in st.session_state:
                st.session_state[body_key] = data.body_markdown or ""
            new_body = st.text_area(
                body_lbl,
                height=155,
                key=body_key,
                disabled=is_exec,
            )
            data.body_markdown = new_body

            if not is_exec:
                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
                col_save, col_rej = st.columns([1.8, 1])
                with col_save:
                    save_btn_lbl = "✉️  Save Draft" if is_en else ("✉️  Salva Bozza in Gmail" if email_live else "✉️  Salva Bozza")
                    if st.button(save_btn_lbl, key=f"btn_mail_{mail_action.id}", type="primary", use_container_width=True):
                        # Assicura la sincronizzazione dei campi editati dall'utente
                        curr_subj = st.session_state.get(f"subj_{mail_action.id}_{ver}", data.subject)
                        curr_body = st.session_state.get(f"body_{mail_action.id}_{ver}", data.body_markdown)
                        curr_email = st.session_state.get(email_key, data.recipient_email)
                        curr_name = st.session_state.get(name_key, data.recipient_name)
                        if curr_subj: data.subject = curr_subj
                        if curr_body: data.body_markdown = curr_body
                        if curr_email: data.recipient_email = curr_email
                        if curr_name: data.recipient_name = curr_name

                        # Auto-salvataggio dell'indirizzo email inserito nel contatto rubrica se precedentemente privo
                        if repo and curr_email and "@" in curr_email:
                            clean_target_name = (curr_name or "").lower().strip()
                            for sc in saved_contacts:
                                sc_full = f"{sc.first_name} {sc.last_name}".lower().strip()
                                sc_aliases = [a.lower().strip() for a in (sc.aliases or [])]
                                if (clean_target_name in (sc_full, sc.first_name.lower().strip()) or clean_target_name in sc_aliases) and not (sc.email or "").strip():
                                    sc.email = curr_email.strip()
                                    run_async(repo.add_contact(sc))
                                    if "knowledge" in st.session_state and st.session_state.knowledge:
                                        try:
                                            run_async(st.session_state.knowledge.save_or_update_contact(sc))
                                        except Exception:
                                            pass
                                    st.toast(f"Email di {sc.first_name} salvata automaticamente in rubrica e Second Brain!", icon="💾")
                                    break

                        ok, msg = run_async(committer.execute_action(mail_action, user_modified_payload=data.model_dump(mode="json")))
                        if ok:
                            st.toast(msg, icon="✅")
                            st.rerun()

                with col_rej:
                    rej_lbl = "Discard" if is_en else "Scarta"
                    if st.button(rej_lbl, key=f"btn_mail_reject_{mail_action.id}", use_container_width=True):
                        run_async(committer.reject_action(mail_action))
                        st.rerun()
                st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
                recip_display = (
                    f"{data.recipient_name} &lt;{data.recipient_email}&gt;"
                    if (data.recipient_email or "").strip() else
                    f"{data.recipient_name} (Bozza aperta — nessun indirizzo email)"
                )
                st.markdown(
                    f"""
                    <div style="
                        background: #F0FDF4;
                        border: 1px solid #BBF7D0;
                        border-radius: 14px;
                        padding: 16px 20px;
                        margin-top: 10px;
                        margin-bottom: 24px;
                        box-shadow: 0 1px 4px rgba(0,0,0,0.03);
                    ">
                        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
                            <span class="aria-pill aria-pill-green" style="font-size:11px; font-weight:700;">
                                ✓ Bozza Creata con Successo
                            </span>
                            <span style="font-size:11px; color:#15803D; font-family:monospace; font-weight:600;">
                                ID: #{mail_action.id}
                            </span>
                        </div>
                        <p style="font-size:12.5px; color:#166534; margin:0 0 4px 0; font-weight:600;">
                            Destinatario: {recip_display}
                        </p>
                        <p style="font-size:12px; color:#15803D; margin:0; line-height:1.45;">
                            Oggetto: <b>{data.subject}</b><br/>
                            Bozza archiviata in modo sicuro nel client di posta per revisione e invio finale. Nessuna email è stata trasmessa automaticamente.
                        </p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


    # Spazio generoso per distanziare la card email dalla card successiva
    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
