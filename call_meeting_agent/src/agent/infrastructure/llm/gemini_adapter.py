from dotenv import load_dotenv
load_dotenv()
import os
import io
import uuid
import hashlib
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Optional, List, Any

from google import genai
from google.genai import types

from ...domain.models import (
    SessionExtractionResult,
    ProposedAction,
    EmailPayload,
    PersonHistorySummary,
)
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

        # Cascata di declassazione modelli (fallback ordinato con modelli ufficiali verificati)
        self.model_cascade: List[str] = [
            self.model_name,
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-flash-8b",
            "gemini-2.0-flash-lite",
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

    def _build_system_instruction(
        self, anchor_iso: str, user_tz: str, user_profile_language: Optional[str] = None
    ) -> str:
        """Costruisce le istruzioni di sistema per Gemini con vincoli temporali e linguistici rigorosi."""
        if user_profile_language:
            lang_section = f"""
REGOLA LINGUISTICA DA PROFILO UTENTE (SECOND BRAIN):
Nel profilo utente del Second Brain è specificata la seguente lingua: '{user_profile_language}'.
- Se l'audio o il testo fornito è in una lingua specifica (es. inglese, spagnolo, italiano), la lingua dell'audio/testo HA SEMPRE LA PRIORITÀ.
- Se l'audio/testo è coerente o compatibile, adotta '{user_profile_language}'.
- Popola il campo `detected_language` con il codice lingua appropriato (es. 'it', 'en', 'es', 'de', 'fr').
"""
        else:
            lang_section = """
REGOLA LINGUISTICA FONDAMENTALE (DIPENDE DALL'AUDIO O DAL PROMPT):
La lingua di TUTTI i contenuti estratti (summary, raw_transcript, titoli eventi, descrizioni, task_items, bozza email, appunti) DEVE DIPENDERE RIGOROSAMENTE DALLA LINGUA DELL'AUDIO O DEL PROMPT.
- Se l'utente parla o scrive in ITALIANO -> genera TUTTI i contenuti in ITALIANO (inclusi giorni, mesi e titoli).
- Se l'utente parla o scrive in INGLESE -> genera TUTTI i contenuti in INGLESE (es. 'Meeting with...', 'Fri 16 Oct').
- Se l'utente parla o scrive in un'altra lingua (spagnolo, francese, tedesco) -> genera tutto in quella lingua.
NON forzare mai l'italiano se l'utente parla in inglese, e non forzare l'inglese se l'utente parla in italiano!
Popola il campo `detected_language` con il codice lingua rilevato (es. 'it', 'en', 'es', 'de', 'fr').
"""

        return f"""
Sei un assistente esecutivo e personale avanzato per l'analisi di riunioni, note vocali, prompt testuali, promemoria, commissioni ed email.
Il tuo compito è analizzare la registrazione o il testo fornito ed estrarre in modo rigoroso, fedele ed esaustivo tutte le informazioni e le azioni operative.

INFORMAZIONI TEMPORALI FONDAMENTALI:
- Timestamp di riferimento attuale (UTC): {anchor_iso}
- Fuso orario di riferimento locale dell'utente: {user_tz}
Tutte le date e gli orari citati (es. "domani alle 9", "domani sera dopo cena", "venerdì alle 18:30", "tra due ore")
devono essere tassativamente calcolati rispetto a questo timestamp e convertiti in formato UTC ISO-8601 considerando il fuso orario {user_tz}.

{lang_section}

REGOLA SPECIALE: OVERRIDE LINGUA PER SINGOLA AZIONE:
Se l'utente specifica espressamente che una determinata email deve essere scritta in una lingua particolare (es. "L'email per mia mamma deve essere scritta in inglese" oppure "Write the follow-up in English"):
L'oggetto (`subject`) e il corpo (`body_markdown`) di QUELLA SPECIFICA EMAIL DEVONO ESSERE SCRITTI RIGOROSAMENTE NELLA LINGUA RICHIESTA (es. in inglese, tipo: Subject: "Thinking of you", Body: "Dear Mom, I just wanted to tell you how much I love you..."), indipendentemente dalla lingua parlata nella registrazione o prompt!

REGOLA ANTI-ALLUCINAZIONE NOMI E FONETICA:
- NON confondere MAI parole comuni del parlato come "mezzogiorno", "mangiare", "treno", "arrivo", "riposare" per nomi propri di persone (NON inventare MAI "giorgo", "mario", ecc.)!
- Estrai come entità o destinatari ESCLUSIVAMENTE persone reali richieste dall'utente:
  * "email a me stesso" -> destinatario "Davide" / "Me stesso", con la propria email (es. bernardavide88@gmail.com).
  * "email a mia mamma" -> destinatario "Mamma", email "" (stringa vuota se non fornita espressamente).
- NON associare MAI l'email personale dell'utente (es. bernardavide88@gmail.com) ad altri contatti (es. NON metterla su Mamma o altri contatti!).

CLASSIFICAZIONE DELLE AZIONI OPERATIVE (proposed_actions):
Devi distinguere con estremo buon senso e precisione la natura di ciascuna richiesta:

1. CALENDAR_EVENT (Solo per veri appuntamenti, riunioni o eventi con orario fissato):
   - Genera CALENDAR_EVENT ESCLUSIVAMENTE per:
     * Riunioni di lavoro, call o incontri con persone (es. "riunione con Mario alle 15").
     * Appuntamenti formali o personali concordati (es. "appuntamento di domani", "appuntamento lunedì dopo le lezioni", "visita medica"). Se l'utente menziona un appuntamento dicendo che è ad esempio "dopo le lezioni" o "dopo essere tornato a casa in treno e aver mangiato/riposato", proponi comunque l'azione CALENDAR_EVENT stimando l'orario plausibile (es. 16:30 o pomeriggio) affinché l'utente possa visualizzarlo e confermarlo o regolarlo con un clic.
   - REGOLA FERREA CONTRO FALSISIMI APPUNTAMENTI:
     Faccende personali, compiti ordinari, commissioni, spesa e promemoria (es. "dare da bere alle piante", "fare la spesa", "comprare le sigarette", "lavare l'auto", "prendere il treno") NON SONO ASSOLUTAMENTE APPUNTAMENTI DI CALENDARIO anche se menzionano un giorno come "domani" o un orario! Non inventare MAI orari per tali compiti: queste attività DEVONO TASSATIVAMENTE ANDARE IN `TASK_TODO`!

2. TASK_TODO (Tutte le cose da fare, commissioni personali e faccende):
   - Genera un'azione TASK_TODO con la lista `task_items` per tutte le cose da fare, to-do, faccende domestiche e commissioni:
     * "dare da bere alle piante" -> TASK_TODO
     * "fare la spesa" -> TASK_TODO
     * "prendere il treno" o "viaggio" -> contesto o TASK_TODO
   - Non mettere MAI le faccende in CALENDAR_EVENT!

3. EMAIL_DRAFT (Bozza di messaggio email richiesta):
   - Genera SEMPRE un'azione EMAIL_DRAFT per ciascuna email esplicitamente richiesta dall'utente:
     * `recipient_email`: l'email citata per quel destinatario. Se non fornita o se l'utente dice di lasciarla vuota, lascia stringa vuota "" (NON inventare domini e NON usare l'email personale dell'utente per altri destinatari!).
     * `recipient_name`: il nome della persona (es. 'Mamma', 'Davide').
     * `subject`: oggetto pertinente e caloroso (nella lingua richiesta per quell'email).
     * `body_markdown`: testo caloroso, naturale e fedele alle istruzioni dell'utente (nella lingua richiesta per quell'email).
     * IMPORTANTE: NON inserire MAI nel corpo email note di disponibilità slot, scuse per riunioni o date se l'email è un messaggio personale, affettivo o di appunti!

4. KNOWLEDGE_NOTE (Second Brain):
   - Note e approfondimenti rilevanti da conservare nel tempo.

5. ENTITÀ E RUOLI (entities):
   - Estrai i contatti reali (es. 'Mamma', 'Davide' o 'Me stesso').
   - Se per una persona viene citata un'email (es. "email a me stesso, quindi a bernardavide88@gmail.com"), compila TASSATIVAMENTE il campo `email` dell'entità con quell'indirizzo!
   - Per familiari o contatti personali, imposta `company="N/D"` e `role="Famiglia"` o `role="Personale"`. NON inventare ruoli aziendali ridicoli come "madre dell'utente" o "riceverà un'email".
"""

    async def extract_from_audio(
        self,
        audio_bytes: bytes,
        filename: str,
        anchor_utc: datetime,
        user_tz: str = "Europe/Rome",
        user_profile_language: Optional[str] = None,
    ) -> SessionExtractionResult:
        """
        Analizza l'audio con Gemini e cascata automatica di declassazione in caso di sovraccarico (503).
        La lingua dipende dalla lingua parlata nell'audio o dal profilo utente nel Second Brain.
        """
        mime_type = self._detect_mime_type(filename)
        anchor_iso = anchor_utc.isoformat()
        system_instruction = self._build_system_instruction(anchor_iso, user_tz, user_profile_language)

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=SessionExtractionResult,
            temperature=0.1,
        )

        last_error = None
        response_text = None
        client = genai.Client(api_key=self.api_key)

        if user_profile_language:
            lang_cue = f"Lingua preferita profilo Second Brain: '{user_profile_language}' (ma segui fedelmente la lingua dell'audio se diversa)."
        else:
            lang_cue = "La lingua di TUTTI i campi generati DEVE DIPENDERE RIGOROSAMENTE dalla lingua dell'audio (es. inglese se parla inglese, italiano se parla italiano)."

        prompt_directive = (
            f"Ascolta con la massima attenzione la registrazione audio ed estrai tutte le informazioni operative. "
            f"{lang_cue} "
            f"Genera CALENDAR_EVENT solo per veri incontri/riunioni con orario concordato. "
            f"Faccende personali e commissioni (es. 'dare da bere alle piante', 'fare la spesa') devono andare in TASK_TODO anche se citano 'domani'. "
            f"Genera EMAIL_DRAFT lasciando vuota l'email se non esplicitata, senza note inventate di calendario per messaggi personali."
        )

        # Preparazione contenuti audio
        raw_items: List[Any] = []
        if len(audio_bytes) < 15 * 1024 * 1024:
            audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
            raw_items = [
                audio_part,
                prompt_directive,
            ]
        else:
            temp_path = f"/tmp/{uuid.uuid4().hex}_{filename}"
            with open(temp_path, "wb") as f:
                f.write(audio_bytes)
            try:
                uploaded_file = await asyncio.to_thread(client.files.upload, file=temp_path)
                raw_items = [
                    uploaded_file,
                    prompt_directive,
                ]
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        contents_payload: Any = raw_items

        # Cascata di declassazione dei modelli (eseguita su thread isolato per evitare conflitti di loop)
        for model in self.model_cascade:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=contents_payload,
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

    async def extract_from_text(
        self,
        text_prompt: str,
        anchor_utc: datetime,
        user_tz: str = "Europe/Rome",
        user_profile_language: Optional[str] = None,
    ) -> SessionExtractionResult:
        """
        Analizza un testo o prompt descrittivo della giornata con Gemini e cascata automatica.
        La lingua dipende dalla lingua usata nel testo o dal profilo utente nel Second Brain.
        """
        anchor_iso = anchor_utc.isoformat()
        system_instruction = self._build_system_instruction(anchor_iso, user_tz, user_profile_language)

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=SessionExtractionResult,
            temperature=0.1,
        )

        if user_profile_language:
            lang_cue = f"Lingua preferita profilo Second Brain: '{user_profile_language}' (ma segui fedelmente la lingua del testo se diversa)."
        else:
            lang_cue = "La lingua di TUTTI i campi generati DEVE DIPENDERE RIGOROSAMENTE dalla lingua del testo (es. inglese se scrive in inglese, italiano se scrive in italiano)."

        prompt_directive = (
            f"Analizza con la massima attenzione il seguente prompt o resoconto ed estrai tutte le informazioni operative. "
            f"{lang_cue} "
            f"Genera CALENDAR_EVENT solo per veri incontri/riunioni con orario concordato. "
            f"Faccende personali e commissioni (es. 'dare da bere alle piante', 'fare la spesa') devono andare in TASK_TODO anche se citano 'domani'. "
            f"Genera EMAIL_DRAFT lasciando vuota l'email se non esplicitata, senza note inventate di calendario per messaggi personali."
        )

        contents: Any = [
            f"TESTO / PROMPT DELLA GIORNATA:\n{text_prompt}",
            prompt_directive,
        ]

        last_error = None
        response_text = None
        client = genai.Client(api_key=self.api_key)

        for model in self.model_cascade:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
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

    async def regenerate_email_draft(
        self,
        original_payload: EmailPayload,
        new_slot_str: str,
        history: Optional[PersonHistorySummary] = None,
        user_tz: str = "Europe/Rome",
    ) -> EmailPayload:
        """
        Riadatta in tempo reale la bozza email quando cambia l'orario a calendario.
        Modifica la formula di cortesia, la motivazione del cambio orario e applica lo stile/preferenze della persona.
        """
        pref_context = ""
        if history and history.key_preferences:
            pref_context = "Preferenze e abitudini note del destinatario:\n" + "\n".join([f"- {p}" for p in history.key_preferences])

        system_instruction = f"""
Sei un assistente esecutivo esperto nella stesura di email di lavoro e follow-up.
Il tuo compito è riaggiornare la bozza email per allinearla a un nuovo orario concordato o proposto.
Fuso orario dell'utente: {user_tz}.

REGOLE DI SCRITTURA:
1. Adatta la formula di cortesia e le motivazioni/scuse in modo fluido e professionale (es. "Purtroppo a quell'orario ho una sovrapposizione in agenda, ti andrebbe bene invece...").
2. Inserisci chiaramente la nuova proposta oraria: {new_slot_str}.
3. Preserva tutti gli appunti, le note e le richieste importanti già presenti nella bozza originale.
4. Tieni conto delle preferenze del contatto se fornite.
5. Mantieni destinatario ed email inalterati.
"""

        prompt = f"""
BOZZA ORIGINALE:
Destinatario: {original_payload.recipient_name} ({original_payload.recipient_email})
Oggetto: {original_payload.subject}
Corpo:
{original_payload.body_markdown}

NUOVO ORARIO CONCORDATO/PROPOSTO:
{new_slot_str}

{pref_context}

Genera il nuovo EmailPayload aggiornato con oggetto pertinente e corpo modificato.
"""

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=EmailPayload,
            temperature=0.2,
        )

        client = genai.Client(api_key=self.api_key)

        for model in self.model_cascade:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=[prompt],
                    config=config,
                )
                if response and response.text:
                    updated = EmailPayload.model_validate_json(response.text)
                    updated.linked_calendar_action_id = original_payload.linked_calendar_action_id
                    updated.cc = original_payload.cc
                    return updated
            except Exception as e:
                logger.warning(f"Modello {model} fallito in regenerate_email_draft: {e}")
                continue

        # Fallback non distruttivo
        fallback = original_payload.model_copy()
        fallback.body_markdown += f"\n\n> 🗓️ **Nuova Proposta Oraria**: {new_slot_str}"
        return fallback

    async def adapt_email_recipient(
        self,
        original_payload: EmailPayload,
        new_recipient_name: str,
        history: Optional[PersonHistorySummary] = None,
        user_tz: str = "Europe/Rome",
    ) -> EmailPayload:
        """
        Riadatta in tempo reale il corpo e l'oggetto della bozza email al nuovo destinatario.
        Aggiorna il saluto (es. 'Ciao Roberto', 'Cara Mamma', 'Cara Giulia'), concorda il genere
        (maschile/femminile) di articoli e aggettivi, mantenendo identico l'indirizzo email e i contenuti.
        """
        clean_name = new_recipient_name.strip()
        if not clean_name:
            return original_payload

        system_instruction = f"""
Sei un assistente esecutivo impeccabile nella redazione di email professionali e personali.
Il tuo compito è riadattare la bozza email al nuovo destinatario specificato: "{clean_name}".

REGOLE TASSATIVE DI RIADATTAMENTO:
1. Saluto iniziale e vocativi: aggiornali fedelmente al nuovo destinatario.
   - Es. Se era "Ciao Davide" e ora è "Roberto" -> "Ciao Roberto" o "Caro Roberto".
   - Se il destinatario è femminile (es. "Giulia", "Mamma", "Chiara", "Elena") -> usa forme femminili ("Cara Giulia", "Cara Mamma", "Ciao Giulia").
   - Se il destinatario è un familiare ("Mamma", "Papà"), usa un saluto affettuoso e cordiale.
2. Concordanza di genere e articoli nel testo:
   - Se il destinatario cambia genere (maschile <-> femminile), adatta tutti gli articoli, pronomi e participi passati (es. "benvenuto" <-> "benvenuta", "pronto" <-> "pronta", "caro" <-> "cara").
3. Contenuti e dettagli:
   - Mantieni INVARIATI tutti i contenuti operativi, i task, le decisioni, gli allegati o i riferimenti citati nel testo originale.
4. Campi tecnici:
   - `recipient_email`: MANTIENI TASSATIVAMENTE l'email originale "{original_payload.recipient_email}". NON modificarla e non inventare indirizzi.
   - `recipient_name`: imposta esattamente "{clean_name}".
"""

        prompt = f"""
BOZZA ORIGINALE:
Destinatario originale: {original_payload.recipient_name}
Email (da mantenere invariata): {original_payload.recipient_email}
Oggetto attuale: {original_payload.subject}
Testo attuale:
{original_payload.body_markdown}

NUOVO DESTINATARIO:
Nome: {clean_name}

Genera il nuovo EmailPayload aggiornato con concordanza perfetta di genere, formule di saluto e testo riadattato.
"""

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=EmailPayload,
            temperature=0.2,
        )

        client = genai.Client(api_key=self.api_key)

        contents_payload: Any = [prompt]
        for model in self.model_cascade:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=contents_payload,
                    config=config,
                )
                if response and response.text:
                    updated = EmailPayload.model_validate_json(response.text)
                    updated.recipient_email = original_payload.recipient_email
                    updated.recipient_name = clean_name
                    updated.linked_calendar_action_id = original_payload.linked_calendar_action_id
                    updated.cc = original_payload.cc
                    return updated
            except Exception as e:
                logger.warning(f"Modello {model} fallito in adapt_email_recipient: {e}")
                continue

        # Fallback euristico rapido (sostituzione vocativo)
        fallback = original_payload.model_copy()
        fallback.recipient_name = clean_name
        old_n = (original_payload.recipient_name or "").strip()
        body = fallback.body_markdown
        if old_n and old_n.lower() in body.lower():
            body = re.sub(re.escape(old_n), clean_name, body, flags=re.IGNORECASE)
        fallback.body_markdown = body
        return fallback



