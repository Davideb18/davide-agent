import asyncio
import uuid
import hashlib
import re
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import List, Optional

logger = logging.getLogger(__name__)

from ..domain.models import (
    SessionExtractionResult,
    Contact,
    UserProfile,
    ExtractedEntity,
    ProposedAction,
    TaskPayload,
)
from ..domain.enums import ActionStatus, ActionType, IntentCategory
from ..domain.ports import (
    LLMExtractorPort,
    CalendarServicePort,
    EmailServicePort,
    KnowledgeServicePort,
    RepositoryPort,
)
from ..domain.datetime_utils import format_localized_slot, is_english as check_is_english, clean_spoken_email, is_self_mention, resolve_timezone
from .resolve_conflict import evaluate_calendar_slot


class ProcessSessionUseCase:
    """Il Direttore d'Orchestra: coordina estrazione audio, disambiguazione contatti e risoluzione conflitti."""

    def __init__(
        self,
        llm_extractor: LLMExtractorPort,
        calendar_service: CalendarServicePort,
        email_service: EmailServicePort,
        knowledge_service: KnowledgeServicePort,
        repository: RepositoryPort,
    ) -> None:
        self.llm = llm_extractor
        self.calendar = calendar_service
        self.email = email_service
        self.knowledge = knowledge_service
        self.repo = repository

    def _disambiguate_entity(
        self,
        entity: ExtractedEntity,
        contacts: List[Contact],
        user_profile: Optional[UserProfile] = None,
    ) -> ExtractedEntity:
        """
        Algoritmo a 3 livelli avanzato (The Trellis Way):
        1. Corrispondenza esatta (nome, cognome, alias, profilo utente).
        2. Corrispondenza composta (nome + azienda/affiliazione/ruolo/tag/indizi).
           Es. 'Filippo Trellis' -> Filippo Calzavara (Company: Trellis).
           Es. 'Gennaro Caio Cato' -> Gennaro (Startup Caio Cato).
        3. Corrispondenza univoca per nome di battesimo se nessun omonimo registrato.
        """
        raw_lower = entity.raw_name.lower().strip()
        candidates: List[Contact] = []

        # Keywords identificative per l'utente principale
        user_kws = {"me stesso", "myself", "io", "me", "self", "me stessa"}
        if user_profile:
            if user_profile.first_name:
                user_kws.add(user_profile.first_name.lower().strip())
            if user_profile.full_name:
                user_kws.add(user_profile.full_name.lower().strip())
            for a in user_profile.aliases:
                user_kws.add(a.lower().strip())

        is_self = is_self_mention(raw_lower, user_kws)

        # Token dell'entità per il matching analitico
        tokens = [t for t in re.split(r'[\s_,\.\-\/]+', raw_lower) if len(t) > 1]
        clues_lower = [c.lower().strip() for c in (entity.context_clues or [])]

        # 1. LIVELLO 1: Corrispondenza esatta, alias o contatto utente
        for c in contacts:
            fn = c.first_name.lower().strip()
            ln = c.last_name.lower().strip()
            full_name = f"{fn} {ln}".strip()
            aliases_lower = [a.lower().strip() for a in c.aliases]
            c_tags = [t.lower() for t in c.tags]
            is_c_user = "utente" in c_tags or "personale" in c_tags
            if (
                raw_lower == fn
                or raw_lower == full_name
                or raw_lower in aliases_lower
                or (is_self and is_c_user)
            ):
                candidates.append(c)

        # 2. LIVELLO 2: Corrispondenza Composta Nome + Azienda / Tag / Note / Indizi
        if not candidates and not is_self:
            for c in contacts:
                fn = c.first_name.lower().strip()
                ln = c.last_name.lower().strip()
                comp = (c.company or "").lower().strip()
                c_tags = [t.lower() for t in c.tags]
                aliases_lower = [a.lower().strip() for a in c.aliases]

                # Il nome deve essere presente nei token o nell'input
                name_matched = (fn in tokens) or (fn in raw_lower)
                if not name_matched and ln:
                    name_matched = (ln in tokens) or (ln in raw_lower)

                if name_matched:
                    # Verifica corrispondenza con azienda, tag o indizi di contesto
                    comp_matched = bool(
                        comp and comp != "n/d" and (
                            comp in raw_lower
                            or any(comp in clue for clue in clues_lower)
                            or any(t in comp for t in tokens if t != fn)
                        )
                    )
                    tag_matched = any(
                        t in raw_lower or any(t in clue for clue in clues_lower)
                        for t in c_tags if len(t) > 2
                    )
                    alias_token_matched = any(
                        a in raw_lower for a in aliases_lower if len(a) > 2
                    )
                    ln_matched = bool(ln and (ln in raw_lower or ln in tokens))

                    if comp_matched or tag_matched or alias_token_matched or ln_matched:
                        candidates.append(c)

        # 3. LIVELLO 3: Corrispondenza univoca per nome di battesimo se nessun omonimo
        if not candidates and not is_self and len(tokens) >= 1:
            first_token = tokens[0]
            first_name_matches = [
                c for c in contacts
                if c.first_name.lower().strip() == first_token
            ]
            if len(first_name_matches) == 1:
                candidates.append(first_name_matches[0])

        if len(candidates) >= 1:
            matched = candidates[0]
            if is_self:
                user_cand = next(
                    (c for c in candidates if "utente" in [t.lower() for t in c.tags] or "personale" in [t.lower() for t in c.tags]),
                    None
                )
                if user_cand:
                    matched = user_cand

            entity.matched_contact_id = matched.id
            entity.is_ambiguous = False
            entity.candidate_ids = []
            if matched.email:
                entity.email = matched.email
            if is_self or any(k in entity.raw_name.lower().strip() for k in ("me", "me stesso", "myself", "io", "me stessa")):
                entity.raw_name = matched.first_name or (user_profile.first_name if user_profile else "Io")
            return entity

        entity.matched_contact_id = None
        entity.is_ambiguous = False
        entity.candidate_ids = []
        return entity

    async def execute(
        self,
        audio_bytes: Optional[bytes] = None,
        filename: Optional[str] = None,
        text_prompt: Optional[str] = None,
        anchor_utc: Optional[datetime] = None,
        user_tz: str = "Europe/Rome",
    ) -> SessionExtractionResult:
        """Esegue l'intera pipeline di elaborazione su audio o prompt testuale."""
        if anchor_utc is None:
            anchor_utc = datetime.now(timezone.utc)

        # Recupero profilo utente e preferenza linguistica dal Second Brain (se definiti)
        user_profile: Optional[UserProfile] = None
        user_profile_lang = None
        try:
            if hasattr(self.knowledge, "get_user_profile"):
                user_profile = await self.knowledge.get_user_profile()
            if user_profile and user_profile.language:
                user_profile_lang = user_profile.language
            elif hasattr(self.knowledge, "get_user_profile_language"):
                user_profile_lang = await self.knowledge.get_user_profile_language()
        except Exception:
            user_profile = None
            user_profile_lang = None

        user_name = user_profile.full_name if user_profile else None
        user_email = user_profile.email if user_profile else None

        # Recupero contatti noti dal Memory Graph locale per il context-grounding di Gemini
        saved_contacts = await self.repo.get_contacts()
        known_contacts_summary = []
        for c in saved_contacts:
            pref_snippet = ""
            if self.knowledge and hasattr(self.knowledge, "get_person_history"):
                try:
                    c_hist = await self.knowledge.get_person_history(f"{c.first_name} {c.last_name}".strip())
                    if c_hist and c_hist.key_preferences:
                        pref_snippet = f", Preferenze note: {'; '.join(c_hist.key_preferences[:2])}"
                except Exception:
                    pass
            known_contacts_summary.append(
                f"{c.first_name} {c.last_name} (Azienda: {c.company}, Ruolo: {c.role}, Email: {c.email or 'N/D'}{pref_snippet})"
            )

        # 1. Estrazione multimodale con Gemini (Prompt Testuale o Registrazione Audio)
        if text_prompt and text_prompt.strip():
            session_result = await self.llm.extract_from_text(
                text_prompt=text_prompt.strip(),
                anchor_utc=anchor_utc,
                user_tz=user_tz,
                user_profile_language=user_profile_lang,
                user_name=user_name,
                user_email=user_email,
                known_contacts_summary=known_contacts_summary,
            )
            if not getattr(session_result, "raw_transcript", None):
                session_result.raw_transcript = text_prompt.strip()
        elif audio_bytes:
            session_result = await self.llm.extract_from_audio(
                audio_bytes=audio_bytes,
                filename=filename or "registrazione.wav",
                anchor_utc=anchor_utc,
                user_tz=user_tz,
                user_profile_language=user_profile_lang,
                user_name=user_name,
                user_email=user_email,
                known_contacts_summary=known_contacts_summary,
            )
        else:
            raise ValueError("Fornire 'audio_bytes' o 'text_prompt' per l'elaborazione.")

        # Garantisce ID univoci e chiavi di idempotenza su ogni azione
        for action in session_result.proposed_actions:
            if not action.id:
                action.id = f"act_{uuid.uuid4().hex[:10]}"
            if not action.session_id:
                action.session_id = session_result.session_id
            if not action.idempotency_key:
                raw_token = f"{session_result.session_id}_{action.action_type.value}_{action.id}"
                action.idempotency_key = f"idemp_{hashlib.sha256(raw_token.encode()).hexdigest()[:12]}"

        # 2. ESCAPE HATCH: se l'audio è solo rumore o convenevoli, salviamo e chiudiamo
        if not session_result.is_actionable:
            await self.repo.save_session(session_result)
            return session_result

        # 3. Disambiguazione Contatti tramite il Memory Graph locale
        disambiguated_entities: List[ExtractedEntity] = []
        for ent in session_result.entities:
            disambiguated_entities.append(self._disambiguate_entity(ent, saved_contacts, user_profile=user_profile))

        # Assicura che le entità con contatto abbinato prendano sempre l'email ufficiale della rubrica
        for ent in disambiguated_entities:
            if ent.matched_contact_id:
                m_c = next((c for c in saved_contacts if c.id == ent.matched_contact_id), None)
                if m_c:
                    if m_c.email:
                        ent.email = m_c.email
                    if any(k in ent.raw_name.lower() for k in ("me", "me stesso", "myself", "io", "me stessa")):
                        ent.raw_name = m_c.first_name

        # Deduplicazione rigorosa delle entità:
        # 1. Unifica tutte le entità che si riferiscono all'utente (massimo 1 entità profilo)
        # 2. Deduplica per matched_contact_id (un solo avatar/scheda per contatto rubrica)
        # 3. Deduplica per raw_name normalizzato per entità esterne non registrate
        deduped_entities: List[ExtractedEntity] = []
        seen_contact_ids = set()
        seen_raw_names = set()
        user_entity_added = False

        user_kws = {"me stesso", "myself", "io", "me", "self", "me stessa"}
        if user_profile:
            if user_profile.first_name:
                user_kws.add(user_profile.first_name.lower().strip())
            if user_profile.full_name:
                user_kws.add(user_profile.full_name.lower().strip())
            for a in user_profile.aliases:
                user_kws.add(a.lower().strip())

        for ent in disambiguated_entities:
            # Controllo se l'entità è l'utente
            is_ent_self = (
                is_self_mention(ent.raw_name, user_kws)
                or (
                    ent.matched_contact_id and any(
                        c.id == ent.matched_contact_id and (
                            "utente" in [t.lower() for t in c.tags] or "personale" in [t.lower() for t in c.tags]
                        )
                        for c in saved_contacts
                    )
                )
            )

            if is_ent_self:
                if not user_entity_added:
                    user_c = next((c for c in saved_contacts if "utente" in [t.lower() for t in c.tags] or "personale" in [t.lower() for t in c.tags]), None)
                    if user_c:
                        ent.matched_contact_id = user_c.id
                        ent.email = user_c.email or ent.email
                        ent.raw_name = user_c.first_name
                    elif user_profile:
                        ent.email = user_profile.email or ent.email
                        ent.raw_name = user_profile.first_name or user_profile.full_name or "Me stesso"
                    deduped_entities.append(ent)
                    user_entity_added = True
                continue

            if ent.matched_contact_id:
                if ent.matched_contact_id not in seen_contact_ids:
                    seen_contact_ids.add(ent.matched_contact_id)
                    deduped_entities.append(ent)
            else:
                norm_name = ent.raw_name.strip().lower()
                if norm_name and norm_name not in seen_raw_names and not is_self_mention(norm_name, user_kws):
                    seen_raw_names.add(norm_name)
                    deduped_entities.append(ent)

        session_result.entities = deduped_entities

        # Riconciliazione deterministica bozze EMAIL_DRAFT con i contatti della rubrica
        user_self_kws = {"me stesso", "myself", "io", "me", "self", "me stessa"}
        if user_profile:
            if user_profile.first_name:
                user_self_kws.add(user_profile.first_name.lower().strip())
            if user_profile.full_name:
                user_self_kws.add(user_profile.full_name.lower().strip())
            for a in user_profile.aliases:
                user_self_kws.add(a.lower().strip())

        for act in session_result.proposed_actions:
            if act.action_type == ActionType.EMAIL_DRAFT and act.email_data:
                # 1. Pulisce eventuale email dettata vocalmente (es. Giorgio.chiocciola@gmail.com -> giorgio@gmail.com)
                if act.email_data.recipient_email:
                    cleaned_em = clean_spoken_email(act.email_data.recipient_email)
                    act.email_data.recipient_email = cleaned_em

                r_name = (act.email_data.recipient_name or "").strip()
                r_lower = r_name.lower()
                is_self_act = is_self_mention(r_name, user_self_kws) if r_name else False

                matched_c = None
                if r_lower and len(r_lower) >= 2:
                    # 1. Cerca il contatto associato tra le entità già disambiguate
                    for ent in session_result.entities:
                        if ent.matched_contact_id:
                            ent_lower = ent.raw_name.lower()
                            if is_self_act:
                                matched_this = is_self_mention(ent_lower, user_self_kws)
                            else:
                                matched_this = (r_lower == ent_lower or r_lower in ent_lower or ent_lower in r_lower) and not is_self_mention(ent_lower, user_self_kws)
                            if matched_this:
                                cand_c = next((c for c in saved_contacts if c.id == ent.matched_contact_id), None)
                                if cand_c:
                                    cand_is_user = ("utente" in [t.lower() for t in cand_c.tags] or "personale" in [t.lower() for t in cand_c.tags])
                                    if is_self_act == cand_is_user:
                                        matched_c = cand_c
                                        break

                    # 2. Se non ancora trovato, cerca direttamente tra tutti i contatti salvati
                    if not matched_c:
                        for c in saved_contacts:
                            full = f"{c.first_name} {c.last_name}".lower().strip()
                            aliases = [a.lower().strip() for a in (c.aliases or [])]
                            c_tags = [t.lower() for t in c.tags]
                            is_c_user = "utente" in c_tags or "personale" in c_tags
                            if is_self_act:
                                if is_c_user:
                                    matched_c = c
                                    break
                            else:
                                if not is_c_user and (
                                    r_lower == full
                                    or r_lower == c.first_name.lower().strip()
                                    or r_lower in aliases
                                ):
                                    matched_c = c
                                    break

                # 3. Il contatto salvato in rubrica è l'autorità: applica nome ed email corretti
                if matched_c:
                    act.email_data.recipient_name = matched_c.first_name
                    if matched_c.email:
                        act.email_data.recipient_email = matched_c.email
                    elif is_self_act and user_profile and user_profile.email:
                        act.email_data.recipient_email = user_profile.email

                    if act.email_data.body_markdown:
                        act.email_data.body_markdown = re.sub(
                            r'^(Ciao|Buongiorno|Salve|Dear|Hi)\s+(?:Me stesso|me stesso)',
                            rf'\1 {matched_c.first_name}',
                            act.email_data.body_markdown,
                            flags=re.MULTILINE,
                        )

                # REGOLA CRITICA DI ZERO-LEAKAGE:
                # Se l'azione NON è indirizzata all'utente stesso (es. per Giorgio o un collaboratore),
                # l'email personale dell'utente NON DEVE MAI figurare come recipient_email!
                if not is_self_act:
                    user_emails = set()
                    if user_profile and user_profile.email:
                        user_emails.add(user_profile.email.lower().strip())
                    user_c = next((c for c in saved_contacts if "utente" in [t.lower() for t in c.tags] or "personale" in [t.lower() for t in c.tags]), None)
                    if user_c and user_c.email:
                        user_emails.add(user_c.email.lower().strip())

                    curr_em = (act.email_data.recipient_email or "").strip().lower()
                    if curr_em in user_emails:
                        # Email personale dell'utente erroneamente assegnata: azzera immediatamente
                        act.email_data.recipient_email = ""

        # Cross-linking di fallback: per entità ancora prive di email cerca nel testo/prompt
        full_context = f"{session_result.raw_transcript or ''} {text_prompt or ''}"
        found_emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', full_context)

        for ent in session_result.entities:
            if not getattr(ent, "email", None):
                ent_lower = ent.raw_name.lower().strip()
                for act in session_result.proposed_actions:
                    if act.action_type == ActionType.EMAIL_DRAFT and act.email_data and act.email_data.recipient_email:
                        r_name = (act.email_data.recipient_name or "").lower().strip()
                        if ent_lower in r_name or r_name in ent_lower:
                            ent.email = act.email_data.recipient_email
                            break

        # People Intelligence & Memoria Storica: recupero storico del contatto
        target_person_name: Optional[str] = None
        for ent in session_result.entities:
            if ent.matched_contact_id:
                matched = next((c for c in saved_contacts if c.id == ent.matched_contact_id), None)
                if matched:
                    target_person_name = f"{matched.first_name} {matched.last_name}".strip()
                    break
            elif ent.raw_name:
                target_person_name = ent.raw_name.strip()
                break

        if target_person_name:
            try:
                session_result.person_history = await self.knowledge.get_person_history(target_person_name)
            except Exception:
                session_result.person_history = None

        # 4. Controllo di sicurezza: Faccende e Promemoria convertiti in TASK_TODO
        CHORE_KEYWORDS = [
            "dare da bere", "bere alle piante", "innaffiare", "piante", "pianta",
            "fare la spesa", "spesa", "supermercato", "comprare",
            "pulire", "lavare", "bucato", "stirare", "buttare la spazzatura",
            "farmacia", "medicine", "bolletta", "bollette", "commissione", "commissioni",
            "tagliando", "meccanico", "posta", "pacco", "treno", "mangiare", "riposare",
            "promemoria personale", "ricordarmi", "dipingere", "muri", "stanza",
            "studiare", "appunti", "studio", "compiti", "ripassare", "tagliare l'erba", "lampadina"
        ]
        
        filtered_actions = []
        todo_action = next(
            (a for a in session_result.proposed_actions if a.action_type == ActionType.TASK_TODO and a.task_data),
            None
        )
        
        for act in session_result.proposed_actions:
            if act.action_type == ActionType.CALENDAR_EVENT and act.calendar_data:
                title_lower = (act.calendar_data.title or "").lower()
                desc_lower = (act.calendar_data.description or "").lower()
                is_chore = any(kw in title_lower or kw in desc_lower for kw in CHORE_KEYWORDS)
                if is_chore:
                    chore_text = (act.calendar_data.title or act.calendar_data.description or "Promemoria personale").strip()
                    task_data = todo_action.task_data if todo_action else None
                    if task_data is not None:
                        if chore_text not in task_data.task_items:
                            task_data.task_items.append(chore_text)
                    else:
                        act.action_type = ActionType.TASK_TODO
                        act.task_data = TaskPayload(task_items=[chore_text])
                        act.calendar_data = None
                        todo_action = act
                        filtered_actions.append(act)
                    continue
            filtered_actions.append(act)
            
        session_result.proposed_actions = filtered_actions

        # 5. Fan-Out Parallelo con asyncio.gather per massima reattività
        calendar_actions = [
            a for a in session_result.proposed_actions
            if a.action_type == ActionType.CALENDAR_EVENT and a.calendar_data
        ]
        email_actions = [
            a for a in session_result.proposed_actions
            if a.action_type == ActionType.EMAIL_DRAFT and a.email_data
        ]

        lang_code = (getattr(session_result, "detected_language", None) or "it").lower()
        is_english = check_is_english(lang_code) or bool(user_profile_lang and "eng" in user_profile_lang.lower() and not lang_code.startswith("it"))
        active_lang = "en" if is_english else "it"

        def format_slot_by_lang(dt_utc: datetime) -> str:
            return format_localized_slot(dt_utc, user_tz=user_tz, lang=active_lang)

        async def evaluate_calendar(act):
            if not act.calendar_data or not act.calendar_data.start_utc or not act.calendar_data.end_utc:
                return

            actual_duration_min = max(
                15,
                int((act.calendar_data.end_utc - act.calendar_data.start_utc).total_seconds() / 60),
            )
            is_busy, alternatives = await evaluate_calendar_slot(
                self.calendar,
                requested_start_utc=act.calendar_data.start_utc,
                duration_minutes=actual_duration_min,
                user_tz=user_tz,
            )

            is_flexible = getattr(act.calendar_data, "is_flexible", False)
            reasoning = (act.calendar_data.slot_reasoning or "").lower()
            flex_keywords = [
                "flessibile", "flexible", "compromesso", "sera più tardi",
                "sera tardi", "dopo le lezioni", "intorno a", "lezioni"
            ]
            is_flexible = is_flexible or any(kw in reasoning for kw in flex_keywords)

            if is_busy:
                if is_flexible and alternatives:
                    # L'utente è flessibile: individua subito lo slot libero consigliato (The Trellis Way)
                    chosen_alt = alternatives[0]
                    shift_delta = chosen_alt - act.calendar_data.start_utc
                    act.calendar_data.start_utc = chosen_alt
                    act.calendar_data.end_utc = act.calendar_data.end_utc + shift_delta
                    act.calendar_data.alternative_slots_utc = alternatives[1:]
                    act.status = ActionStatus.PROPOSED

                    local_chosen = format_slot_by_lang(chosen_alt)
                    note_auto = (
                        f"Orario individuato automaticamente ({local_chosen}) nel rispetto della flessibilità e degli impegni esistenti (es. lezioni universitarie o fuso orario Tokyo)."
                        if active_lang == "it" else
                        f"Slot automatically shifted to {local_chosen} to accommodate user flexibility and existing schedule (e.g. university lectures or Tokyo timezone)."
                    )
                    act.calendar_data.slot_reasoning = f"{act.calendar_data.slot_reasoning or ''}\n\n{note_auto}".strip()
                else:
                    act.status = ActionStatus.CONFLICT_DETECTED
                    act.calendar_data.alternative_slots_utc = alternatives
            else:
                act.status = ActionStatus.PROPOSED

        if calendar_actions:
            await asyncio.gather(*(evaluate_calendar(a) for a in calendar_actions))

        # Loop Reattivo Calendario <-> Email: collegamento e iniezione slot ESCLUSIVAMENTE se l'email riguarda l'incontro con un interlocutore esterno
        if calendar_actions and email_actions:
            cal_act = calendar_actions[0]
            cal_title_lower = (cal_act.calendar_data.title or "").lower()
            cal_attendees_lower = [att.lower() for att in (cal_act.calendar_data.attendees or [])]

            for mail_act in email_actions:
                recip_name = (mail_act.email_data.recipient_name or "").lower().strip()
                recip_email = (mail_act.email_data.recipient_email or "").lower().strip()
                
                # Esclude tassativamente note a se stessi o email affettive a familiari
                is_self = (
                    is_self_mention(recip_name, user_self_kws)
                    or (user_profile and user_profile.email and user_profile.email.lower() in recip_email)
                )
                is_family_personal = any(f in recip_name for f in ("mamma", "madre", "papà", "padre", "mum", "mom", "dad"))

                # Se ci sono più email e l'evento cita espressamente un'altra persona, questa email non è l'invito per questo evento
                recipient_mismatch = False
                if recip_name and len(email_actions) > 1:
                    other_recipients = [
                        (m.email_data.recipient_name or "").lower().strip()
                        for m in email_actions
                        if m != mail_act and (m.email_data.recipient_name or "").strip()
                    ]
                    if any(other in cal_title_lower for other in other_recipients) and recip_name not in cal_title_lower:
                        recipient_mismatch = True

                # Verifica che l'email sia effettivamente un invito/follow-up per l'appuntamento
                subject_lower = (mail_act.email_data.subject or "").lower()
                body_lower = (mail_act.email_data.body_markdown or "").lower()

                is_match_recipient = bool(
                    recip_name and (
                        recip_name in cal_title_lower
                        or any(recip_name in att for att in cal_attendees_lower)
                    )
                )
                has_meeting_keyword = any(
                    kw in subject_lower or kw in body_lower
                    for kw in [
                        "invito", "conferma", "appuntamento", "meeting", "riunione",
                        "follow-up", "disponibilità", "call", "orario", "sentirci", "vederci"
                    ]
                )
                is_single_pair = (len(calendar_actions) == 1 and len(email_actions) == 1)

                is_meeting_invite = (
                    (is_match_recipient or has_meeting_keyword or is_single_pair)
                    and not is_self
                    and not is_family_personal
                    and not recipient_mismatch
                )

                if is_meeting_invite:
                    mail_act.email_data.linked_calendar_action_id = cal_act.id
                    if cal_act.status == ActionStatus.CONFLICT_DETECTED:
                        alt_strs = [
                            format_slot_by_lang(slot)
                            for slot in (cal_act.calendar_data.alternative_slots_utc or [])
                        ]
                        mail_act.email_data.suggested_alternatives = alt_strs
                        if is_english:
                            mail_act.email_data.conflict_reason = "The requested time slot conflicts with an existing event on the calendar."
                            note_header = "[Availability Note]: The original slot is busy. Proposed alternatives:"
                        else:
                            mail_act.email_data.conflict_reason = "Lo slot orario richiesto risulta già occupato nel calendario."
                            note_header = "[Nota Disponibilità]: Lo slot originario è occupato. Alternative proposte:"

                        if alt_strs and not any(alt in mail_act.email_data.body_markdown for alt in alt_strs):
                            alternatives_text = "\n".join(f"- {alt}" for alt in alt_strs)
                            mail_act.email_data.body_markdown += f"\n\n{note_header}\n{alternatives_text}"
                    else:
                        # Assicura che l'email contenga data e ora esatte concordate
                        slot_text = format_slot_by_lang(cal_act.calendar_data.start_utc)
                        start_loc = cal_act.calendar_data.start_utc.astimezone(resolve_timezone(user_tz))
                        time_hm = start_loc.strftime("%H:%M")
                        body = mail_act.email_data.body_markdown or ""

                        # Rilevamento fuso orario di Tokyo per arricchimento di cortesia
                        is_tokyo = any(
                            "tokyo" in s.lower()
                            for s in [
                                session_result.raw_transcript or "",
                                getattr(session_result, "summary", "") or "",
                                cal_act.calendar_data.title or "",
                                cal_act.calendar_data.description or "",
                            ]
                        )
                        tokyo_note = ""
                        if is_tokyo:
                            try:
                                tokyo_loc = cal_act.calendar_data.start_utc.astimezone(ZoneInfo("Asia/Tokyo"))
                                tokyo_note = f" (ore {tokyo_loc.strftime('%H:%M')} a Tokyo)"
                            except Exception:
                                pass

                        display_time_str = f"ore {time_hm}{tokyo_note}"

                        # Sostituisce tassativamente qualsiasi menzione di "UTC" o "Z" con l'orario locale
                        body = re.sub(
                            r'(?:alle\s+)?ore\s+\d{1,2}[:\.]\d{2}\s*(?:UTC|Z)\b',
                            f"alle {display_time_str}",
                            body,
                            flags=re.IGNORECASE,
                        )
                        body = re.sub(
                            r'\b\d{1,2}[:\.]\d{2}\s*(?:UTC|Z)\b',
                            display_time_str,
                            body,
                            flags=re.IGNORECASE,
                        )

                        # Se Tokyo è nel contesto ma non ancora menzionato nel corpo dell'email, arricchisce l'orario
                        if is_tokyo and tokyo_note and "tokyo" not in body.lower():
                            body = re.sub(
                                rf'(ore\s+{re.escape(time_hm)})\b',
                                rf'\1{tokyo_note}',
                                body,
                                count=1,
                            )

                        if time_hm not in body and not re.search(r'\b\d{1,2}[:\.]\d{2}\b', body):
                            if re.search(r'l[\'’]orario (?:stabilito|concordato|fissato)', body, re.IGNORECASE):
                                body = re.sub(
                                    r'(l[\'’]orario (?:stabilito|concordato|fissato))',
                                    rf"\1 ({slot_text})",
                                    body,
                                    flags=re.IGNORECASE,
                                )
                            elif re.search(r'(nostra call di martedì|nostro incontro|nostra riunione|nostra call)', body, re.IGNORECASE):
                                body = re.sub(
                                    r'(nostra call di martedì|nostro incontro|nostra riunione|nostra call)',
                                    rf"\1 ({slot_text})",
                                    body,
                                    flags=re.IGNORECASE,
                                )
                            else:
                                tag = f"\n\n> 🗓️ **Orario Incontro**: {slot_text}"
                                if tag not in body:
                                    body += tag

                        mail_act.email_data.body_markdown = body
                else:
                    # Email personale/slegata (es. mamma, saluti, appunti personali): NESSUN collegamento al calendario
                    mail_act.email_data.linked_calendar_action_id = None
                    mail_act.email_data.suggested_alternatives = []
                    mail_act.email_data.conflict_reason = None

        for action in session_result.proposed_actions:
            if action.action_type in (
                ActionType.EMAIL_DRAFT,
                ActionType.TASK_TODO,
                ActionType.TASK_EXPORT_REMINDERS,
            ):
                if action.status not in (ActionStatus.EXECUTED, ActionStatus.REJECTED):
                    action.status = ActionStatus.PROPOSED

        # 6. SINCRONIZZAZIONE AUTOMATICA SILENZIOSA DEL SECOND BRAIN (OBSIDIAN) IN BACKGROUND
        # L'utente esige che ogni informazione, nota d'incontro, dossier e to-do sia effettivamente
        # applicato e sincronizzato all'interno del proprio Second Brain, ma senza alcun elemento grafico.
        if self.knowledge:
            for act in session_result.proposed_actions:
                if act.action_type == ActionType.KNOWLEDGE_NOTE and act.knowledge_data:
                    try:
                        note_path = await self.knowledge.save_meeting_note(act.knowledge_data)
                        if act.knowledge_data.target_person_name:
                            raw_summary = getattr(act.knowledge_data, "summary", None)
                            summary_text = (raw_summary.strip() if isinstance(raw_summary, str) and raw_summary.strip() else None) or (
                                act.knowledge_data.bullet_insights[0]
                                if act.knowledge_data.bullet_insights
                                else ""
                            )
                            await self.knowledge.link_meeting_to_person(
                                person_name=act.knowledge_data.target_person_name,
                                meeting_title=act.knowledge_data.title,
                                meeting_rel_path=note_path,
                                summary=summary_text,
                                insights=act.knowledge_data.bullet_insights,
                            )
                        act.status = ActionStatus.EXECUTED
                    except Exception as e:
                        logger.warning(f"Auto-sync Second Brain non riuscito: {e}")

                elif act.action_type == ActionType.TASK_TODO and act.task_data:
                    try:
                        await self.knowledge.append_tasks(
                            payload=act.task_data,
                            meeting_ref=act.task_data.target_project or "Task Session"
                        )
                        act.status = ActionStatus.EXECUTED
                    except Exception as e:
                        logger.warning(f"Auto-append tasks Second Brain non riuscito: {e}")

                elif act.action_type == ActionType.EMAIL_DRAFT and act.email_data:
                    if act.email_data.recipient_name and hasattr(self.knowledge, "record_email_interaction") and act.status == ActionStatus.EXECUTED:
                        try:
                            await self.knowledge.record_email_interaction(
                                person_name=act.email_data.recipient_name,
                                email_data=act.email_data,
                                status_label="Bozza registrata",
                            )
                        except Exception:
                            pass

        # 7. Salvataggio nel database SQLite
        await self.repo.save_session(session_result)

        return session_result

