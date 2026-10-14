import hashlib
from datetime import datetime, timedelta, timezone
from typing import List

from ...domain.models import (
    SessionExtractionResult,
    ProposedAction,
    ExtractedEntity,
    CalendarPayload,
    EmailPayload,
    KnowledgePayload,
    TaskPayload,
)
from ...domain.enums import ActionStatus, ActionType, IntentCategory


class MockLLMExtractor:
    """Simulatore del motore Gemini per test offline e live demo immediate."""

    async def extract_from_audio(
        self, audio_bytes: bytes, filename: str, anchor_utc: datetime
    ) -> SessionExtractionResult:
        """Simula l'analisi multimodale di Gemini restituendo entità, impegni e note collegate."""
        session_id = f"ses_{hashlib.sha256(filename.encode()).hexdigest()[:8]}"

        # 1. ESCAPE HATCH: Se il file indica convenevoli o rumore, scartiamo senza azioni
        if "chitchat" in filename.lower() or "vuoto" in filename.lower():
            return SessionExtractionResult(
                session_id=session_id,
                is_actionable=False,
                intent_category=IntentCategory.CHITCHAT_NOOP,
                summary="Audio informale senza impegni operativi o date rilevate.",
                raw_transcript="Ciao Davide, ci vediamo in giro uno di questi giorni, buona giornata!",
                entities=[],
                proposed_actions=[],
            )

        # 2. CASO OPERATIVO: Riunione con Filippo di Trellis
        entities = [
            ExtractedEntity(
                raw_name="Filippo",
                context_clues=["Trellis", "CTO", "pricing", "integrazione"],
                matched_contact_id="cnt_filippo",
                is_ambiguous=False,
                candidate_ids=[],
            )
        ]

        # Impostiamo il meeting alle 14:00 UTC (proprio l'orario che fa scattare il conflitto in agenda!)
        meeting_start = anchor_utc.replace(hour=14, minute=0, second=0, microsecond=0)
        meeting_end = meeting_start + timedelta(minutes=30)

        # Azione 1: Google Calendar
        calendar_action = ProposedAction(
            id=f"act_cal_{session_id}",
            session_id=session_id,
            action_type=ActionType.CALENDAR_EVENT,
            status=ActionStatus.PROPOSED,
            calendar_data=CalendarPayload(
                title="Sync Tecnico: Integrazione PMS Trellis",
                start_utc=meeting_start,
                end_utc=meeting_end,
                attendees=["filippo@trellis.so"],
                description="Allineamento tecnico sull'architettura di aggregazione PMS e review roadmap.",
                location="Google Meet",
            ),
            idempotency_key=f"idemp_cal_{session_id}",
        )

        # Azione 2: Bozza Gmail
        email_action = ProposedAction(
            id=f"act_mail_{session_id}",
            session_id=session_id,
            action_type=ActionType.EMAIL_DRAFT,
            status=ActionStatus.PROPOSED,
            email_data=EmailPayload(
                recipient_email="filippo@trellis.so",
                recipient_name="Filippo Calzavara",
                subject="Follow-up Call: Pricing e Roadmap Trellis",
                body_markdown=(
                    "Ciao Filippo,\n\n"
                    "Grazie per l'allineamento di oggi. Come concordato, ho bloccato lo slot per "
                    "approfondire l'integrazione e il modello commissioni.\n\n"
                    "A presto,\nDavide"
                ),
            ),
            idempotency_key=f"idemp_mail_{session_id}",
        )

        # Azione 3: Second Brain / Obsidian
        knowledge_action = ProposedAction(
            id=f"act_know_{session_id}",
            session_id=session_id,
            action_type=ActionType.KNOWLEDGE_NOTE,
            status=ActionStatus.PROPOSED,
            knowledge_data=KnowledgePayload(
                title="Allineamento Trellis e Pricing PMS",
                target_person_name="Filippo Calzavara",
                backlinks=["Filippo Calzavara", "Trellis", "PMS Integration", "Pricing Q1"],
                bullet_insights=[
                    "Accettato modello commissioni al 3% sui volumi aggregati",
                    "Filippo ha espresso dubbi sulla compatibilità temporale del rilascio Q1",
                    "Preferisce fissare le call sempre nella fascia mattutina (CET)",
                ],
                markdown_content="Abbiamo discusso l'architettura tecnica per l'aggregazione dei PMS...",
            ),
            idempotency_key=f"idemp_know_{session_id}",
        )


        # Azione 4: Task & Action Items Tracker
        task_action = ProposedAction(
            id=f"act_task_{session_id}",
            session_id=session_id,
            action_type=ActionType.TASK_TODO,
            status=ActionStatus.PROPOSED,
            task_data=TaskPayload(
                task_items=[
                    "Inviare schema rivisto commissioni al 3% sui volumi aggregati",
                    "Condividere documentazione tecnica API aggregazione PMS",
                    "Confermare slot definitivo per sync tecnico con Filippo",
                ],
                assignee="Davide",
                target_project="Trellis",
            ),
            idempotency_key=f"idemp_task_{session_id}",
        )

        return SessionExtractionResult(
            session_id=session_id,
            is_actionable=True,
            intent_category=IntentCategory.BUSINESS_MEETING,
            summary="Allineamento con Filippo (CTO Trellis) sul pricing del 3% e pianificazione sync tecnico.",
            raw_transcript=(
                "Ho sentito Filippo per il colloquio e per Trellis. Abbiamo confermato il pricing "
                "e ci vediamo per un sync tecnico per definire l'integrazione."
            ),
            entities=entities,
            proposed_actions=[calendar_action, email_action, knowledge_action, task_action],
        )


# SCRIPT DI COLLAUDO IMMEDIATO
if __name__ == "__main__":
    import asyncio

    async def test():
        extractor = MockLLMExtractor()
        fake_audio = b"fake_audio_bytes_123"
        now_utc = datetime.now(timezone.utc)

        print("=" * 65)
        print("1. Test Audio Normale (Riunione di Business)...")
        res_business = await extractor.extract_from_audio(fake_audio, "call_filippo.mp3", now_utc)
        print(f"Session ID: {res_business.session_id}")
        print(f"Summary: {res_business.summary}")
        print(f"Azioni generate: {len(res_business.proposed_actions)}")
        for act in res_business.proposed_actions:
            print(f" - [{act.action_type.value}] Stato: {act.status.value}")

        print("\n2. Test Audio Informale (Escape Hatch: Solo Saluti)...")
        res_chitchat = await extractor.extract_from_audio(fake_audio, "chitchat_amici.mp3", now_utc)
        print(f"È operativo? {res_chitchat.is_actionable}")
        print(f"Categoria: {res_chitchat.intent_category.value}")
        print(f"Azioni: {len(res_chitchat.proposed_actions)} (Correttamente zero!)")
        print("=" * 65)

    asyncio.run(test())
