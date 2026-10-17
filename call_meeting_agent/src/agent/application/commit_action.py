import asyncio
import threading
from typing import Optional, Dict, Any, Tuple
from ..domain.models import ProposedAction, CalendarPayload, EmailPayload, KnowledgePayload, TaskPayload
from ..domain.enums import ActionStatus, ActionType
from ..domain.ports import (
    CalendarServicePort,
    EmailServicePort,
    KnowledgeServicePort,
    RemindersServicePort,
    RepositoryPort,
)


class CommitActionUseCase:
    """Esegue in modo sicuro e idempotente le azioni approvate dall'utente sulla console."""

    def __init__(
        self,
        calendar_service: CalendarServicePort,
        email_service: EmailServicePort,
        knowledge_service: KnowledgeServicePort,
        repository: RepositoryPort,
        reminders_service: Optional[RemindersServicePort] = None,
    ) -> None:
        self.calendar = calendar_service
        self.email = email_service
        self.knowledge = knowledge_service
        self.repo = repository
        self.reminders = reminders_service
        self._key_locks: Dict[Tuple[int, str], asyncio.Lock] = {}
        self._locks_guard = threading.Lock()

    def _get_loop_key_lock(self, key: str) -> asyncio.Lock:
        """
        Restituisce un lock asincrono associato univocamente alla coppia (event_loop, idempotency_key).
        Garantisce immunità assoluta a 'RuntimeError: ... is bound to a different event loop'
        durante rerun successivi di Streamlit o invocazioni su loop multipli.
        """
        try:
            loop = asyncio.get_running_loop()
            loop_id = id(loop)
        except RuntimeError:
            loop_id = 0

        composite_key = (loop_id, key)
        with self._locks_guard:
            if composite_key not in self._key_locks:
                self._key_locks[composite_key] = asyncio.Lock()
            return self._key_locks[composite_key]

    async def execute_action(
        self, action: ProposedAction, user_modified_payload: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str]:
        """
        Esegue l'azione verso l'esterno (Google Calendar, Gmail, Obsidian o Apple Reminders).
        Ritorna:
            (success: bool, message: str)
        """
        # Concurrency Lock per chiave di idempotenza isolato per Event Loop
        key = action.idempotency_key or action.id
        key_lock = self._get_loop_key_lock(key)

        async with key_lock:
            # 1. CONTROLLO DI IDEMPOTENZA (Anti-Doppio Click con protezione da Race Condition)
            already_used = await self.repo.is_idempotency_key_used(action.idempotency_key)
            if already_used or action.status == ActionStatus.EXECUTED:
                return False, f"⚠️ Azione già eseguita in precedenza! Bloccata duplicazione (Chiave: {action.idempotency_key})."

            # Registrazione preventiva dell'azione nel database se creata on-demand
            await self.repo.save_proposed_action(action)

            # 2. Se l'utente ha modificato i dati nella dashboard, li applichiamo
            if user_modified_payload:
                if action.action_type == ActionType.CALENDAR_EVENT and action.calendar_data:
                    action.calendar_data = CalendarPayload.model_validate(user_modified_payload)
                elif action.action_type == ActionType.EMAIL_DRAFT and action.email_data:
                    action.email_data = EmailPayload.model_validate(user_modified_payload)
                elif action.action_type == ActionType.KNOWLEDGE_NOTE and action.knowledge_data:
                    action.knowledge_data = KnowledgePayload.model_validate(user_modified_payload)
                elif (
                    action.action_type in (ActionType.TASK_TODO, ActionType.TASK_EXPORT_REMINDERS)
                    and action.task_data
                ):
                    action.task_data = TaskPayload.model_validate(user_modified_payload)

            # 3. ESECUZIONE SPECIFICA PER TIPO DI AZIONE
            try:
                if action.action_type == ActionType.CALENDAR_EVENT:
                    if not action.calendar_data:
                        return False, "Dati del calendario mancanti!"
                    event_id = await self.calendar.create_event(
                        payload=action.calendar_data,
                        idempotency_key=action.idempotency_key,
                    )
                    success_msg = f"Evento Calendario creato con successo! (ID: {event_id})"

                elif action.action_type == ActionType.EMAIL_DRAFT:
                    if not action.email_data:
                        return False, "Dati email mancanti!"
                    draft_id = await self.email.create_draft(
                        payload=action.email_data,
                        idempotency_key=action.idempotency_key,
                    )
                    success_msg = f"Bozza Gmail generata con successo! (ID: {draft_id})"

                elif action.action_type == ActionType.KNOWLEDGE_NOTE:
                    if not action.knowledge_data:
                        return False, "Dati del Second Brain mancanti!"
                    note_path = await self.knowledge.save_meeting_note(action.knowledge_data)
                    # Graph Linking Bidirezionale: aggiornamento atomico del dossier persona con insight e backlink
                    if action.knowledge_data.target_person_name:
                        raw_summary = getattr(action.knowledge_data, "summary", None)
                        summary_text = (raw_summary.strip() if isinstance(raw_summary, str) and raw_summary.strip() else None) or (
                            action.knowledge_data.bullet_insights[0]
                            if action.knowledge_data.bullet_insights
                            else ""
                        )
                        await self.knowledge.link_meeting_to_person(
                            person_name=action.knowledge_data.target_person_name,
                            meeting_title=action.knowledge_data.title,
                            meeting_rel_path=note_path,
                            summary=summary_text,
                            insights=action.knowledge_data.bullet_insights,
                        )
                    success_msg = f"Nota Second Brain creata e Dossier collegato via Graph Link! ({note_path})"

                elif action.action_type == ActionType.TASK_TODO:
                    if not action.task_data:
                        return False, "Dati dei task mancanti!"
                    tasks_path = await self.knowledge.append_tasks(
                        payload=action.task_data,
                        meeting_ref=action.task_data.target_project or "Meeting Sync"
                    )
                    success_msg = f"Checklist operativa salvata nei Task di Progetto! ({tasks_path})"

                elif action.action_type == ActionType.TASK_EXPORT_REMINDERS:
                    if not action.task_data or not action.task_data.items:
                        return False, "Nessun task specificato per l'esportazione su Promemoria!"
                    if not self.reminders:
                        return False, "Servizio Apple Reminders non configurato o non disponibile."
                    success, msg = await self.reminders.export_tasks(
                        task_items=action.task_data.items,
                        list_name="Aria Tasks",
                    )
                    if not success:
                        return False, msg
                    success_msg = msg

                else:
                    return False, f"Tipo di azione non supportato: {action.action_type}"

                # 4. TRANSIZIONE DI STATO NEL DATABASE
                await self.repo.update_action_status(
                    action_id=action.id,
                    new_status=ActionStatus.EXECUTED.value,
                    diff_payload=user_modified_payload,
                )
                action.status = ActionStatus.EXECUTED
                return True, success_msg

            except Exception as e:
                # Se la chiamata esterna fallisce (es. token scaduto o timeout), registriamo il fallimento
                await self.repo.update_action_status(
                    action_id=action.id,
                    new_status=ActionStatus.EXECUTION_FAILED.value,
                    diff_payload={"error": str(e)},
                )
                action.status = ActionStatus.EXECUTION_FAILED
                return False, f"Errore durante l'esecuzione: {str(e)}"

    async def reject_action(self, action: ProposedAction, reason: Optional[str] = None) -> None:
        """Marca l'azione come RIFIUTATA dall'utente nell'Audit Log."""
        await self.repo.update_action_status(
            action_id=action.id,
            new_status=ActionStatus.REJECTED.value,
            diff_payload={"rejection_reason": reason or "Scartata manualmente dall'utente"},
        )
        action.status = ActionStatus.REJECTED

