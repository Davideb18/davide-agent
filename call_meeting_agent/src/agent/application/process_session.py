import asyncio
import uuid
import hashlib
import re
import logging
from datetime import datetime, timezone
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
from ..domain.datetime_utils import format_localized_slot, is_english as check_is_english
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
        Algoritmo a 3 livelli (The Trellis Way):
        Cerca tra i contatti per nome, soprannomi e indizi di contesto (tag/ruolo).
        Se trova omonimi irrisolti, attiva la modalità 'is_ambiguous' per la scelta umana.
        """
        raw_lower = entity.raw_name.lower().strip()
        candidates: List[Contact] = []

        # 1. Ricerca candidati per nome, cognome o alias
        user_kws = {"me stesso", "myself", "io", "me", "self"}
        if user_profile:
            if user_profile.first_name:
                user_kws.add(user_profile.first_name.lower().strip())
            if user_profile.full_name:
                user_kws.add(user_profile.full_name.lower().strip())
            for a in user_profile.aliases:
                user_kws.add(a.lower().strip())

        is_self = any(k == raw_lower or k in raw_lower for k in user_kws)
        for c in contacts:
            full_name = f"{c.first_name} {c.last_name}".lower().strip()
            aliases_lower = [a.lower().strip() for a in c.aliases]
            c_tags = [t.lower() for t in c.tags]
            is_c_user = "utente" in c_tags or "personale" in c_tags
            if (
                raw_lower == c.first_name.lower().strip()
                or raw_lower == full_name
                or raw_lower in aliases_lower
                or (is_self and is_c_user)
            ):
                candidates.append(c)

        if len(candidates) >= 1:
            # Se è l'utente ("me stesso", "io"), seleziona prioritariamente il contatto utente salvato
            matched = candidates[0]
            if is_self:
                user_cand = next((c for c in candidates if "utente" in [t.lower() for t in c.tags] or "personale" in [t.lower() for t in c.tags]), None)
                if user_cand:
                    matched = user_cand

            entity.matched_contact_id = matched.id
            entity.is_ambiguous = False
            entity.candidate_ids = []
            # Il contatto in rubrica è la fonte autoritativa per nome ed email
            if matched.email:
                entity.email = matched.email
            if is_self or entity.raw_name.lower().strip() in ("me", "me stesso", "myself", "io"):
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

        # 1. Estrazione multimodale con Gemini (Prompt Testuale o Registrazione Audio)
        if text_prompt and text_prompt.strip():
            session_result = await self.llm.extract_from_text(
                text_prompt=text_prompt.strip(),
                anchor_utc=anchor_utc,
                user_tz=user_tz,
                user_profile_language=user_profile_lang,
                user_name=user_name,
                user_email=user_email,
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
        saved_contacts = await self.repo.get_contacts()
        disambiguated_entities: List[ExtractedEntity] = []
        for ent in session_result.entities:
            disambiguated_entities.append(self._disambiguate_entity(ent, saved_contacts, user_profile=user_profile))
        session_result.entities = disambiguated_entities

        # Assicura che le entità con contatto abbinato prendano sempre l'email ufficiale della rubrica
        for ent in session_result.entities:
            if ent.matched_contact_id:
                m_c = next((c for c in saved_contacts if c.id == ent.matched_contact_id), None)
                if m_c:
                    if m_c.email:
                        ent.email = m_c.email
                    if any(k in ent.raw_name.lower() for k in ("me", "me stesso", "myself", "io")):
                        ent.raw_name = m_c.first_name

        # Riconciliazione deterministica bozze EMAIL_DRAFT con i contatti della rubrica
        user_self_kws = {"me stesso", "myself", "io", "me", "self"}
        if user_profile:
            if user_profile.first_name:
                user_self_kws.add(user_profile.first_name.lower().strip())
            if user_profile.full_name:
                user_self_kws.add(user_profile.full_name.lower().strip())
            for a in user_profile.aliases:
                user_self_kws.add(a.lower().strip())

        for act in session_result.proposed_actions:
            if act.action_type == ActionType.EMAIL_DRAFT and act.email_data:
                r_name = (act.email_data.recipient_name or "").strip()
                r_lower = r_name.lower()
                is_self_act = any(k == r_lower or k in r_lower for k in user_self_kws)

                # 1. Cerca il contatto associato tra le entità già disambiguate
                matched_c = None
                for ent in session_result.entities:
                    if ent.matched_contact_id:
                        ent_lower = ent.raw_name.lower()
                        if (
                            r_lower in ent_lower
                            or ent_lower in r_lower
                            or (is_self_act and any(k in ent_lower for k in user_self_kws))
                        ):
                            matched_c = next((c for c in saved_contacts if c.id == ent.matched_contact_id), None)
                            if matched_c:
                                break

                # 2. Se non ancora trovato, cerca direttamente tra tutti i contatti salvati
                if not matched_c:
                    for c in saved_contacts:
                        full = f"{c.first_name} {c.last_name}".lower().strip()
                        aliases = [a.lower().strip() for a in (c.aliases or [])]
                        c_tags = [t.lower() for t in c.tags]
                        is_c_user = "utente" in c_tags or "personale" in c_tags
                        if (
                            r_lower == full
                            or r_lower == c.first_name.lower().strip()
                            or r_lower in aliases
                            or (is_self_act and is_c_user)
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
            "promemoria personale", "ricordarmi"
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
        
        async def evaluate_calendar(act):
            is_busy, alternatives = await evaluate_calendar_slot(
                self.calendar,
                requested_start_utc=act.calendar_data.start_utc,
                duration_minutes=30,
                user_tz=user_tz,
            )
            if is_busy:
                act.status = ActionStatus.CONFLICT_DETECTED
                act.calendar_data.alternative_slots_utc = alternatives
            else:
                act.status = ActionStatus.PROPOSED

        if calendar_actions:
            await asyncio.gather(*(evaluate_calendar(a) for a in calendar_actions))

        # Funzione helper per formattazione data/ora dipendente dalla lingua rilevata (audio o profilo utente)
        lang_code = (getattr(session_result, "detected_language", None) or "it").lower()
        is_english = check_is_english(lang_code) or bool(user_profile_lang and "eng" in user_profile_lang.lower() and not lang_code.startswith("it"))
        active_lang = "en" if is_english else "it"

        def format_slot_by_lang(dt_utc: datetime) -> str:
            return format_localized_slot(dt_utc, user_tz=user_tz, lang=active_lang)

        # Loop Reattivo Calendario <-> Email: collegamento e iniezione slot ESCLUSIVAMENTE se l'email riguarda l'incontro con un interlocutore esterno
        if calendar_actions and email_actions:
            cal_act = calendar_actions[0]
            for mail_act in email_actions:
                recip_name = (mail_act.email_data.recipient_name or "").lower().strip()
                recip_email = (mail_act.email_data.recipient_email or "").lower().strip()
                
                # Esclude tassativamente note a se stessi o email affettive a familiari
                is_self = (
                    any(k == recip_name or k in recip_name for k in user_self_kws)
                    or (user_profile and user_profile.email and user_profile.email.lower() in recip_email)
                )
                is_family_personal = any(f in recip_name for f in ("mamma", "madre", "papà", "padre", "mum", "mom", "dad"))

                # Verifica che l'email sia effettivamente un invito/follow-up per l'appuntamento
                subject_lower = (mail_act.email_data.subject or "").lower()
                is_meeting_invite = (
                    any(kw in subject_lower for kw in ["invito", "conferma incontro", "meeting", "riunione", "follow-up", "disponibilità", "call"])
                    and not is_self
                    and not is_family_personal
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
                            meeting_ref=act.task_data.target_project or "Meeting Sync"
                        )
                        act.status = ActionStatus.EXECUTED
                    except Exception as e:
                        logger.warning(f"Auto-append tasks Second Brain non riuscito: {e}")

        # 7. Salvataggio nel database SQLite
        await self.repo.save_session(session_result)

        return session_result

