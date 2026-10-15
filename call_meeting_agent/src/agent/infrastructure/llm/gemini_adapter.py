from dotenv import load_dotenv
load_dotenv()
import os
import io
import uuid
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from google import genai
from google.genai import types

from ...domain.models import SessionExtractionResult, ProposedAction
from ...domain.enums import ActionStatus, ActionType, IntentCategory

logger = logging.getLogger(__name__)


class GeminiExtractorAdapter:
    """Implementazione reale tramite Google Gemini con cascata automatica dei modelli (no mock)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-flash-lite-latest",
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY non trovata! Inseriscila nel file .env o passala al costruttore."
            )

        self.model_name = model_name
        self.client = genai.Client(api_key=self.api_key)

        # Cascata di declassazione modelli (fallback ordinato)
        self.model_cascade: List[str] = [
            self.model_name,
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-flash-latest",
        ]
        # Rimuove duplicati preservando l'ordine
        seen = set()
        self.model_cascade = [m for m in self.model_cascade if not (m in seen or seen.add(m))]

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

    async def extract_from_audio(
        self, audio_bytes: bytes, filename: str, anchor_utc: datetime
    ) -> SessionExtractionResult:
        """
        Analizza l'audio con Gemini e cascata automatica di declassazione in caso di sovraccarico (503).
        Nessun mock hardcoded: esecuzione 100% reale.
        """
        mime_type = self._detect_mime_type(filename)
        anchor_iso = anchor_utc.isoformat()

        # Istruzioni di sistema con Anchor Temporale
        system_instruction = f"""
Sei un assistente per l'analisi di riunioni e note vocali.
Il tuo compito è analizzare la registrazione audio allegata ed estrarre le informazioni in modo fedele e accurato.

INFORMAZIONI TEMPORALI:
- Timestamp di riferimento attuale (UTC): {anchor_iso}
- Fuso orario di riferimento: Europe/Rome (CET/CEST)
Tutte le date e gli orari relativi citati nella conversazione (es. "domani alle 15", "martedì prossimo", "tra due ore")
devono essere calcolati rispetto a questo timestamp e convertiti in formato UTC ISO-8601.

REGOLE DI ESTRAZIONE:
1. TRASCRIZIONE: Fornisci una trascrizione fedele e completa della conversazione nel campo raw_transcript.
2. SINTESI: Riassumi chiaramente gli argomenti principali trattati nel campo summary.
3. ENTITÀ: Estrai i nomi delle persone coinvolte e il loro contesto (ruolo, azienda).
4. CALENDARIO: Se viene proposto o concordato un appuntamento, genera un'azione CALENDAR_EVENT con start_utc ed end_utc.
5. EMAIL: Se è emersa la necessità di inviare un recap o materiali, genera un'azione EMAIL_DRAFT con oggetto e corpo chiaro e professionale.
6. SECOND BRAIN (NOTE): Estrai i punti salienti, decisioni e preferenze in un'azione KNOWLEDGE_NOTE.
7. COMPITI (TASK_TODO): Se emergono compiti o azioni concordate, genera un'azione TASK_TODO con la lista dei compiti (task_items).
8. SE L'AUDIO È CHITCHAT O VUOTO: Imposta is_actionable=False e lascia proposed_actions vuoto.
"""

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=SessionExtractionResult,
            temperature=0.1,
        )

        last_error = None
        response_text = None

        # Preparazione contenuti audio
        if len(audio_bytes) < 15 * 1024 * 1024:
            audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
            contents = [
                audio_part,
                "Ascolta l'audio allegato ed estrai la trascrizione, la sintesi e le azioni operative rispettando lo schema.",
            ]
        else:
            temp_path = f"/tmp/{uuid.uuid4().hex}_{filename}"
            with open(temp_path, "wb") as f:
                f.write(audio_bytes)
            try:
                uploaded_file = await self.client.aio.files.upload(file=temp_path)
                contents = [
                    uploaded_file,
                    "Ascolta l'audio allegato ed estrai la trascrizione, la sintesi e le azioni operative rispettando lo schema.",
                ]
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        # Cascata di declassazione dei modelli (es. gemini-flash-lite -> gemini-3.5-flash-lite -> gemini-3.8-flash)
        for model in self.model_cascade:
            try:
                response = await self.client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                if response and response.text:
                    response_text = response.text
                    break
            except Exception as e:
                last_error = e
                logger.warning(f"Modello {model} non disponibile o in sovraccarico: {e}. Tento modello successivo nella cascata.")
                continue

        if not response_text:
            raise RuntimeError(
                f"Tutti i modelli nella cascata Gemini hanno fallito. Ultimo errore: {last_error}"
            )

        # Validazione Pydantic
        result = SessionExtractionResult.model_validate_json(response_text)

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
