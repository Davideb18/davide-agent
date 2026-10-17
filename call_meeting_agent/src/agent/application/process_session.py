import asyncio
import uuid
import hashlib
from datetime import datetime, timezone
from typing import List, Optional

from ..domain.models import (
    SessionExtractionResult,
    Contact,
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
        self, entity: ExtractedEntity, contacts: List[Contact]
    ) -> ExtractedEntity:
        """
        Algoritmo a 3 livelli (The Trellis Way):
        Cerca tra i contatti per nome, soprannomi e indizi di contesto (tag/ruolo).
        Se trova omonimi irrisolti, attiva la modalità 'is_ambiguous' per la scelta umana.
        """
        raw_lower = entity.raw_name.lower().strip()
        candidates: List[Contact] = []

        # 1. Ricerca candidati per nome, cognome o alias
        for c in contacts:
            full_name = f"{c.first_name} {c.last_name}".lower()
            aliases_lower = [a.lower() for a in c.aliases]
            if (
                raw_lower == c.first_name.lower()
                or raw_lower == full_name
                or raw_lower in aliases_lower
            ):
                candidates.append(c)

        if len(candidates) == 1:
            # Match perfetto univoco!
            entity.matched_contact_id = candidates[0].id
            entity.is_ambiguous = False
            entity.candidate_ids = []
            return entity

        if len(candidates) > 1:
            # 2. C'è più di un contatto con lo stesso nome! Usiamo gli indizi di contesto
            scored_candidates: List[Contact] = []
            clues = [clue.lower() for clue in entity.context_clues]

            for cand in candidates:
                cand_keywords = [cand.company.lower(), cand.role.lower()] + [t.lower() for t in cand.tags]
                if any(any(clue in kw for kw in cand_keywords) for clue in clues):
                    scored_candidates.append(cand)

            if len(scored_candidates) == 1:
                # Disambiguato con successo grazie al contesto!
                entity.matched_contact_id = scored_candidates[0].id
                entity.is_ambiguous = False
                entity.candidate_ids = []
                return entity

            # 3. Ambiguità irrisolta: Chiediamo all'umano sulla console
            entity.matched_contact_id = None
            entity.is_ambiguous = True
            entity.candidate_ids = [c.id for c in candidates]
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

        # Recupero preferenza linguistica dal profilo utente nel Second Brain (se definita)
        user_profile_lang = None
        try:
            if hasattr(self.knowledge, "get_user_profile_language"):
                user_profile_lang = await self.knowledge.get_user_profile_language()
        except Exception:
            user_profile_lang = None

        # 1. Estrazione multimodale con Gemini (Prompt Testuale o Registrazione Audio)
        if text_prompt and text_prompt.strip():
            session_result = await self.llm.extract_from_text(
                text_prompt=text_prompt.strip(),
                anchor_utc=anchor_utc,
                user_tz=user_tz,
                user_profile_language=user_profile_lang,
            )
        elif audio_bytes:
            session_result = await self.llm.extract_from_audio(
                audio_bytes=audio_bytes,
                filename=filename or "registrazione.wav",
                anchor_utc=anchor_utc,
                user_tz=user_tz,
                user_profile_language=user_profile_lang,
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
            disambiguated_entities.append(self._disambiguate_entity(ent, saved_contacts))
        session_result.entities = disambiguated_entities

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
                    chore_text = act.calendar_data.title.strip()
                    if todo_action:
                        if chore_text not in todo_action.task_data.task_items:
                            todo_action.task_data.task_items.append(chore_text)
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
                is_self = recip_name in ("me", "me stesso", "myself", "davide") or "bernardavide" in recip_email
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
                ActionType.KNOWLEDGE_NOTE,
                ActionType.TASK_TODO,
                ActionType.TASK_EXPORT_REMINDERS,
            ):
                if action.status not in (ActionStatus.EXECUTED, ActionStatus.REJECTED):
                    action.status = ActionStatus.PROPOSED

        # 5. Salvataggio nel database SQLite
        await self.repo.save_session(session_result)

        return session_result

