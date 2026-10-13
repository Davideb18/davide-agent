import asyncio
from datetime import datetime, timezone
from typing import List, Optional

from ..domain.models import (
    SessionExtractionResult,
    Contact,
    ExtractedEntity,
    ProposedAction,
)
from ..domain.enums import ActionStatus, ActionType, IntentCategory
from ..domain.ports import (
    LLMExtractorPort,
    CalendarServicePort,
    EmailServicePort,
    KnowledgeServicePort,
    RepositoryPort,
)
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
        self, audio_bytes: bytes, filename: str, anchor_utc: datetime
    ) -> SessionExtractionResult:
        """Esegue l'intera pipeline di elaborazione."""
        # 1. Estrazione multimodale con Gemini 3.8 Flash (o Mock)
        session_result = await self.llm.extract_from_audio(
            audio_bytes=audio_bytes,
            filename=filename,
            anchor_utc=anchor_utc,
        )

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

        # 4. Fan-Out Parallelo: Valutiamo le azioni (Controllo Conflitti su Calendario)
        for action in session_result.proposed_actions:
            if action.action_type == ActionType.CALENDAR_EVENT and action.calendar_data:
                is_busy, alternatives = await evaluate_calendar_slot(
                    self.calendar,
                    requested_start_utc=action.calendar_data.start_utc,
                    duration_minutes=30,
                )
                if is_busy:
                    action.status = ActionStatus.CONFLICT_DETECTED
                    action.calendar_data.alternative_slots_utc = alternatives
                else:
                    action.status = ActionStatus.PROPOSED

            elif action.action_type == ActionType.EMAIL_DRAFT:
                action.status = ActionStatus.PROPOSED

            elif action.action_type == ActionType.KNOWLEDGE_NOTE:
                action.status = ActionStatus.PROPOSED

        # 5. Salvataggio nel database SQLite
        await self.repo.save_session(session_result)

        return session_result


# SCRIPT DI COLLAUDO END-TO-END DELL'ORCHESTRATORE
if __name__ == "__main__":
    from ..infrastructure.llm.mock_llm import MockLLMExtractor
    from ..infrastructure.google.mock_google import MockCalendarService, MockEmailService
    from ..infrastructure.knowledge.obsidian_adapter import ObsidianAdapter
    from ..infrastructure.database.sqlite_repo import SqliteRepository

    async def test():
        repo = SqliteRepository("data/test_call_agent.db")
        await repo.init_db()
        await repo.seed_default_contacts()

        use_case = ProcessSessionUseCase(
            llm_extractor=MockLLMExtractor(),
            calendar_service=MockCalendarService(),
            email_service=MockEmailService(),
            knowledge_service=ObsidianAdapter(),
            repository=repo,
        )

        print("=" * 65)
        print("AVVIO ORCHESTRATORE END-TO-END...")
        result = await use_case.execute(
            audio_bytes=b"sample_bytes",
            filename="meeting_filippo.mp3",
            anchor_utc=datetime.now(timezone.utc),
        )

        print(f"Sessione ID: {result.session_id}")
        print(f"Riassunto: {result.summary}")
        print("\nEntità Riconosciute:")
        for e in result.entities:
            print(f" - {e.raw_name} -> Contatto Associato: {e.matched_contact_id} (Ambiguo: {e.is_ambiguous})")

        print("\nAzioni Proposte Coordinate:")
        for a in result.proposed_actions:
            print(f" - [{a.action_type.value}] Stato: {a.status.value}")
            if a.status == ActionStatus.CONFLICT_DETECTED:
                print(f"   ⚠️ Slot occupato! Alternative proposte: {len(a.calendar_data.alternative_slots_utc)}")

        print("\nPIPELINE COMPLETATA CON SUCCESSO! 🎉")
        print("=" * 65)

    asyncio.run(test())
