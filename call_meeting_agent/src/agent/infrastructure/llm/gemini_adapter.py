import os
import io
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ...domain.models import SessionExtractionResult, ProposedAction
from ...domain.enums import ActionStatus, ActionType, IntentCategory


class GeminiExtractorAdapter:
    """Implementazione reale del LLMExtractorPort tramite Google Gemini 3.5 Flash."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-3.8-flash",
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY non trovata! Inseriscila nel file .env o passala al costruttore."
            )

        self.model_name = model_name
        self.client = genai.Client(api_key=self.api_key)

    def _detect_mime_type(self, filename: str) -> str:
        """Determina il corretto MIME type audio in base all'estensione del file."""
        ext = Path(filename).suffix.lower()
        mapping = {
            ".mp3": "audio/mp3",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
            ".ogg": "audio/ogg",
            ".aac": "audio/aac",
            ".flac": "audio/flac",
        }
        return mapping.get(ext, "audio/mp3")

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def extract_from_audio(
        self, audio_bytes: bytes, filename: str, anchor_utc: datetime
    ) -> SessionExtractionResult:
        """
        Invia l'audio a Gemini 3.5 Flash con Anchor Timestamp e schema Pydantic forzato.
        Applica la Dual-Track Ingestion:
        - Sotto i 15MB: invio diretto in-memory ultraveloce.
        - Sopra i 15MB: upload asincrono tramite File API.
        """
        mime_type = self._detect_mime_type(filename)
        anchor_iso = anchor_utc.isoformat()

        # Prompt di Sistema con Anchor Temporale
        system_instruction = f"""
Sei l'Executive Operations Agent di Davide. Il tuo compito è analizzare note vocali o registrazioni di riunioni
ed estrarre con estrema precisione e rigore ingegneristico le informazioni operative.

INFORMAZIONI TEMPORALI CRITICHE:
- Timestamp di Riferimento Attuale (UTC): {anchor_iso}
- Fuso Orario Utente: Europe/Rome (CET/CEST)
Tutte le date relative dette a voce (es. "domani alle 15", "martedì prossimo", "tra due ore") DEVONO
essere calcolate rispetto a questo timestamp e convertite in formato UTC assoluto ISO-8601.

REGOLE DI ESTRAZIONE:
1. DETERMINISTIC ESCAPE HATCH: Se l'audio contiene solo convenevoli informali (chitchat), saluti o rumore senza
   alcun impegno o azione operativa, imposta is_actionable=False, intent_category='CHITCHAT_NOOP' e lascia proposed_actions vuoto.
2. ENTITÀ: Estrai i nomi delle persone menzionate e i dettagli di contesto (azienda, argomenti, ruolo).
3. CALENDARIO: Se viene concordato un incontro o follow-up call, genera un'azione CALENDAR_EVENT con start_utc ed end_utc.
4. EMAIL: Se occorre mandare un riepilogo o materiali, genera un'azione EMAIL_DRAFT con un testo professionale e conciso.
5. SECOND BRAIN (OBSIDIAN): Estrai le intuizioni chiave, preferenze personali emerse e decisioni in un'azione KNOWLEDGE_NOTE
   utilizzando i backlink in stile Obsidian [[NomePersona]] e [[Argomento]].
6. TASK OPERATIVI (ACTION ITEMS): Se emergono compiti da svolgere, scadenze, To-Do o deliverable concordati a voce,
   genera un'azione TASK_TODO popolando task_data con la lista di compiti (task_items), assignee ed eventuale target_project.
"""

        # Configurazione con Structured Outputs nativi (Pydantic Schema)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=SessionExtractionResult,
            temperature=0.1,  # massima precisione e determinismo
        )

        # Dual-track: se il file è leggero (<15MB) lo passiamo direttamente in memoria RAM
        if len(audio_bytes) < 15 * 1024 * 1024:
            audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
            contents = [
                audio_part,
                "Ascolta l'audio allegato ed estrai tutte le entità e le azioni operative rispettando lo schema.",
            ]
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )
        else:
            # File pesante: usiamo l'upload temporaneo su File API
            temp_path = f"/tmp/{uuid.uuid4().hex}_{filename}"
            with open(temp_path, "wb") as f:
                f.write(audio_bytes)
            try:
                uploaded_file = await self.client.aio.files.upload(file=temp_path)
                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=[
                        uploaded_file,
                        "Ascolta l'audio allegato ed estrai tutte le entità e le azioni operative rispettando lo schema.",
                    ],
                    config=config,
                )
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        # Convalida e istanziazione del modello Pydantic
        result = SessionExtractionResult.model_validate_json(response.text)

        # Garantisce ID univoci e chiavi di idempotenza su ogni azione
        for action in result.proposed_actions:
            if not action.id:
                action.id = f"act_{uuid.uuid4().hex[:10]}"
            if not action.session_id:
                action.session_id = result.session_id
            if not action.idempotency_key:
                raw_token = f"{result.session_id}_{action.action_type.value}_{action.id}"
                action.idempotency_key = f"idemp_{hashlib.sha256(raw_token.encode()).hexdigest()[:12]}"
            action.status = ActionStatus.PROPOSED

        return result
