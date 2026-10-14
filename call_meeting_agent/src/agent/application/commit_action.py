from typing import Optional, Dict, Any, Tuple
from ..domain.models import ProposedAction, CalendarPayload, EmailPayload, KnowledgePayload, TaskPayload
from ..domain.enums import ActionStatus, ActionType
from ..domain.ports import (
    CalendarServicePort,
    EmailServicePort,
    KnowledgeServicePort,
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
    ) -> None:
        self.calendar = calendar_service
        self.email = email_service
        self.knowledge = knowledge_service
        self.repo = repository

    async def execute_action(
        self, action: ProposedAction, user_modified_payload: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str]:
        """
        Esegue l'azione verso l'esterno (Google Calendar, Gmail o Obsidian).
        Ritorna:
            (success: bool, message: str)
        """
        # 1. CONTROLLO DI IDEMPOTENZA (Anti-Doppio Click)
        already_used = await self.repo.is_idempotency_key_used(action.idempotency_key)
        if already_used:
            return False, f"⚠️ Azione già eseguita in precedenza! Bloccata duplicazione (Chiave: {action.idempotency_key})."

        # 2. Se l'utente ha modificato i dati nella dashboard, li applichiamo
        if user_modified_payload:
            if action.action_type == ActionType.CALENDAR_EVENT and action.calendar_data:
                action.calendar_data = CalendarPayload.model_validate(user_modified_payload)
            elif action.action_type == ActionType.EMAIL_DRAFT and action.email_data:
                action.email_data = EmailPayload.model_validate(user_modified_payload)
            elif action.action_type == ActionType.KNOWLEDGE_NOTE and action.knowledge_data:
                action.knowledge_data = KnowledgePayload.model_validate(user_modified_payload)
            elif action.action_type == ActionType.TASK_TODO and action.task_data:
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
                await self.knowledge.update_person_dossier(
                    person_name=action.knowledge_data.target_person_name,
                    new_insights=action.knowledge_data.bullet_insights,
                    meeting_ref=action.knowledge_data.title,
                )
                success_msg = f"Nota Second Brain creata e Dossier aggiornato! ({note_path})"

            elif action.action_type == ActionType.TASK_TODO:
                if not action.task_data:
                    return False, "Dati dei task mancanti!"
                tasks_path = await self.knowledge.append_tasks(
                    payload=action.task_data,
                    meeting_ref=action.task_data.target_project or "Meeting Sync"
                )
                success_msg = f"Checklist operativa salvata nei Task di Progetto! ({tasks_path})"

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


# SCRIPT DI COLLAUDO IMMEDIATO
if __name__ == "__main__":
    import asyncio
    from datetime import datetime, timezone
    from ..infrastructure.google.mock_google import MockCalendarService, MockEmailService
    from ..infrastructure.knowledge.obsidian_adapter import ObsidianAdapter
    from ..infrastructure.database.sqlite_repo import SqliteRepository
    from ..infrastructure.llm.mock_llm import MockLLMExtractor
    from .process_session import ProcessSessionUseCase

    async def test():
        repo = SqliteRepository("data/test_call_agent.db")
        await repo.init_db()
        await repo.seed_default_contacts()

        cal = MockCalendarService()
        mail = MockEmailService()
        know = ObsidianAdapter()

        # 1. Creiamo una sessione con l'orchestratore
        orchestrator = ProcessSessionUseCase(
            llm_extractor=MockLLMExtractor(),
            calendar_service=cal,
            email_service=mail,
            knowledge_service=know,
            repository=repo,
        )
        session = await orchestrator.execute(b"fake", "demo_call.mp3", datetime.now(timezone.utc))

        committer = CommitActionUseCase(
            calendar_service=cal,
            email_service=mail,
            knowledge_service=know,
            repository=repo,
        )

        print("=" * 65)
        print("COLLAUDO COMMIT ACTION (HUMAN-IN-THE-LOOP COMMIT)...")

        # Eseguiamo la prima azione (es. la bozza email)
        email_action = [a for a in session.proposed_actions if a.action_type == ActionType.EMAIL_DRAFT][0]
        ok, msg = await committer.execute_action(email_action)
        print(f"1. Primo tentativo commit: {msg}")

        # Proviamo a rieseguire la STESSA azione una seconda volta (Test Idempotenza!)
        ok_dup, msg_dup = await committer.execute_action(email_action)
        print(f"2. Secondo tentativo duplicato: {msg_dup}")

        print("=" * 65)

    asyncio.run(test())
