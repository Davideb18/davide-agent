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
from ...domain.datetime_utils import clean_spoken_email

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
        self, anchor_iso: str, user_tz: str,
        user_profile_language: Optional[str] = None,
        user_name: Optional[str] = None,
        user_email: Optional[str] = None,
        known_contacts_summary: Optional[List[str]] = None,
    ) -> str:
        """Costruisce le istruzioni di sistema per Gemini con vincoli temporali, linguistici e identità utente."""
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

        # Sezione identità utente (dinamica dal vault)
        effective_name = user_name or "l'utente"
        identity_section = f"""
IDENTITÀ UTENTE (da Second Brain Vault):
- Nome utente: '{effective_name}'
- Email utente: '{user_email or "(non specificata)"}'
Regole:
  * Quando l'utente dice "email a me stesso", "io", "me stesso" → il destinatario è '{effective_name}'{f" con email '{user_email}'" if user_email else ", email da lasciare vuota se non specificata"}.
  * NON usare mai 'Me stesso' come nome del destinatario: usa sempre '{effective_name}'.
  * Se l'email è per l'utente stesso, il campo `recipient_name` deve essere '{effective_name}' (non 'Me', non 'Me stesso').
"""

        contacts_block = ""
        if known_contacts_summary:
            c_lines = "\n".join(f"  * {c}" for c in known_contacts_summary)
            contacts_block = f"""
RUBRICA CONTATTI NOTI (SECOND BRAIN):
{c_lines}
REGOLE RICONOSCIMENTO CONTATTI NOTI:
- Se l'utente cita una persona associandola alla sua azienda/progetto (es. 'Filippo Trellis', 'Filippo di Trellis', 'Filippo Trilli'), riconducila rigorosamente al contatto noto corrispondente (es. raw_name='Filippo Calzavara', company='Trellis', email='filippo@trellis.so')! NON creare duplicati fantasiosi!
- Se l'utente cita una nuova persona (es. 'Gennaro' della startup 'Caio Cato', o 'Giorgio' amico), estraila con il suo nome reale e azienda/ruolo corretti.
"""

        return f"""
Sei un assistente esecutivo e personale avanzato per l'analisi di riunioni, note vocali, prompt testuali, promemoria, commissioni ed email.
Il tuo compito è analizzare la registrazione o il testo fornito ed estrarre in modo rigoroso, fedele ed esaustivo tutte le informazioni e le azioni operative.

INFORMAZIONI TEMPORALI FONDAMENTALI:
- Timestamp di riferimento attuale (UTC): {anchor_iso}
- Fuso orario di riferimento locale dell'utente: {user_tz}
Tutte le date e gli orari citati (es. "domani alle 9", "domani sera dopo cena", "venerdì alle 18:30", "tra due ore")
devono essere tassativamente calcolati rispetto a questo timestamp e convertiti in formato UTC ISO-8601 considerando il fuso orario {user_tz}.

{identity_section}
{contacts_block}
{lang_section}

CONVENZIONI EMAIL NEL PARLATO E SEPARAZIONE BOZZE (CRITICO):
- Se l'utente detta un'email dicendo 'chiocciola' o la trascrizione scrive 'chiocciola' (es. 'Giorgio.chiocciola@gmail.com' o 'giorgio chiocciola gmail punto com'), convertila SEMPRE nel simbolo '@' -> 'giorgio@gmail.com'!
- Se l'utente menziona PIÙ EMAIL (es. 'un'email a me stesso' E 'un'email anche a Giorgio'), DEVI GENERARE AZIONI EMAIL_DRAFT SEPARATE E DISTINTE:
  * Una bozza EMAIL_DRAFT per Giorgio: recipient_name='Giorgio', recipient_email='giorgio@gmail.com' (o vuota se non chiara), con il testo per Giorgio (es. ringraziamento per il prestito).
  * Una bozza EMAIL_DRAFT o nota per l'utente stesso SE richiesta.
- REGOLA D'ORO: NON ASSEGNARE MAI E PER NESSUN MOTIVO L'EMAIL PERSONALE DELL'UTENTE ('{user_email}') AD ALTRE PERSONE (come Giorgio, Mamma, colleghi)! Se non sai l'email di un destinatario, lascia `recipient_email=""` (stringa vuota).

REGOLA ANTI-ALLUCINAZIONE NOMI E FONETICA:
- NON confondere MAI parole comuni del parlato come "mezzogiorno", "mangiare", "treno", "arrivo", "riposare" per nomi propri di persone!
- Estrai come entità o destinatari ESCLUSIVAMENTE persone reali richieste dall'utente:
  * "email a me stesso" → destinatario '{effective_name}' (l'utente stesso), NON usare "Me stesso"!
  * "email a mia mamma" → destinatario "Mamma", email "" (stringa vuota se non fornita espressamente).

CLASSIFICAZIONE DELLE AZIONI OPERATIVE (proposed_actions):
Devi distinguere con estremo buon senso e precisione la natura di ciascuna richiesta:

1. CALENDAR_EVENT (Solo per veri appuntamenti, riunioni o call con orario concordato o flessibile):
   - Genera CALENDAR_EVENT ESCLUSIVAMENTE per incontri, call o riunioni.
   - GESTIONE INTELLIGENTE DEI FUSI ORARI E PREFERENZE NOTI (es. Tokyo / Weekend / Mattina vs Sera):
     * OVERLAP CON TOKYO (Asia/Tokyo, UTC+9, 7-8 ore avanti rispetto all'Italia):
       - La fascia ottimale di sovrapposizione lavorativa è la MATTINA ITALIANA (09:30 - 12:30 Europe/Rome), che corrisponde al tardo pomeriggio a Tokyo (16:30 - 19:30 Tokyo).
       - Se l'interlocutore ha preferenza per la "fascia mattutina (CET)", oppure se l'incontro è nel "weekend" o flessibile senza lezioni universitarie diurne, COLLOCA SEMPRE LA CALL NELLA MATTINA ITALIANA (es. ore 10:00 o 10:30 Europe/Rome)!
       - Colloca la call la sera italiana (es. 20:30 o 21:00) SOLO E SOLTANTO SE l'utente dichiara esplicitamente di essere occupato di giorno (es. lezioni universitarie feriali) e specifica espressamente 'dopo cena' o 'sera'. Nel weekend o in assenza di vincoli serali espliciti, usa la mattina/primo pomeriggio compatibile con Tokyo.
     * FLESSIBILITÀ:
       - Imposta `is_flexible=True` nel CalendarPayload quando l'utente lascia margine ('weekend', 'orario decente', 'vedi quando farla').
       - Compila `slot_reasoning` spiegando la logica temporale adottata (es. 'Slot mattutino (ore 10:00) individuato per rispettare la preferenza del contatto e consentire un orario pomeridiano confortevole a Tokyo (ore 17:00)').
   - REGOLA FERREA CONTRO FALSISIMI APPUNTAMENTI:
     Faccende personali, compiti ordinari, commissioni e promemoria (es. "dare da bere alle piante", "portare fuori la spazzatura", "pulire la casa", "sistemare la stanza", "studiare", "recuperare appunti") NON SONO ASSOLUTAMENTE APPUNTAMENTI DI CALENDARIO! Vanno tassativamente in `TASK_TODO`!

2. TASK_TODO (Tutte le cose da fare, commissioni personali e faccende):
   - Genera un'azione TASK_TODO con la lista `task_items` per tutte le cose da fare, to-do, faccende domestiche e commissioni:
     * "dare da bere alle piante" → TASK_TODO
     * "portare fuori la spazzatura" → TASK_TODO
     * "pulire la casa" → TASK_TODO
     * "sistemare la stanza" → TASK_TODO
     * "recuperare gli appunti delle lezioni e finirli" → TASK_TODO
     * "studiare gli ultimi appunti" → TASK_TODO

3. EMAIL_DRAFT (Bozze di messaggio email):
   - Genera azioni EMAIL_DRAFT separate per ciascun destinatario distinto.
   - `recipient_email`: l'email corretta del destinatario (es. 'giorgio@gmail.com', 'arturo@gmail.com'). Se non fornita, lascia "" (MAI l'email personale dell'utente!).
   - `recipient_name`: nome della persona (es. 'Filippo', 'Arturo', '{effective_name}').
   - FORMATO ORARIO NELLE EMAIL (MAI SCRIVERE UTC NEL TESTO!):
     Nel corpo dell'email (`body_markdown`), gli orari DEVONO ESSERE SEMPRE ESPRESSI NEL FUSO ORARIO LOCALE DELL'UTENTE ({user_tz}) o dell'interlocutore (es. "sabato 24 ottobre alle ore 10:00" oppure "sabato 24 ottobre alle ore 10:00 italiane / 17:00 a Tokyo").
     È SEVERAMENTE VIETATO scrivere "UTC" o orari in UTC nel testo dell'email (es. MAI "ore 18:00 UTC")! Le persone reali non comunicano orari in UTC grezzo.
   - SPECIFICA ESPLICITA DELL'ORARIO:
     Se l'email ha lo scopo di concordare, confermare o comunicare l'orario di un appuntamento/call (es. per Filippo o colleghi):
     DEVI TASSATIVAMENTE INCLUDERE nel testo del messaggio (`body_markdown`) il giorno, la data e l'orario locale stabilito (es. "sabato 24 ottobre alle ore 10:00").
     NON usare mai frasi generiche senza orario come "ti confermo l'orario stabilito" senza specificare data e ora precise!
   - ZERO-HALLUCINATION SU TEMI, PROGETTI E PREFERENZE (CRITICO):
     Nelle email (`EMAIL_DRAFT`), scrivi SOLO E RIGOROSAMENTE ciò che l'utente ha esplicitamente richiesto di comunicare (es. comunicare l'orario della call e il link al repository GitHub, o inviare un messaggio al professore Arturo).
     È SEVERAMENTE VIETATO inventare argomenti aziendali non menzionati (es. 'rilascio Q1', 'roadmap', 'contratti'), discussioni passate o presunte preferenze orarie altrui NON pronunciate dall'utente!
     Tutto ciò che scrivi deve essere fondato al 100% sulla realtà espressa dall'utente.

4. KNOWLEDGE_NOTE (Second Brain):
   - Note e approfondimenti rilevanti da conservare nel tempo.

5. ENTITÀ E RUOLI (entities):
   - Estrai i contatti reali (es. 'Filippo Calzavara', 'Gennaro', 'Giorgio', '{effective_name}').
   - DEDUPLICAZIONE RIGOROSA: La stessa persona non deve MAI comparire più di una volta nell'elenco `entities`! L'utente ('{effective_name}') deve comparire al massimo una volta.
"""

    async def extract_from_audio(
        self,
        audio_bytes: bytes,
        filename: str,
        anchor_utc: datetime,
        user_tz: str = "Europe/Rome",
        user_profile_language: Optional[str] = None,
        user_name: Optional[str] = None,
        user_email: Optional[str] = None,
        known_contacts_summary: Optional[List[str]] = None,
    ) -> SessionExtractionResult:
        """
        Analizza l'audio con Gemini e cascata automatica di declassazione in caso di sovraccarico (503).
        La lingua dipende dalla lingua parlata nell'audio o dal profilo utente nel Second Brain.
        """
        mime_type = self._detect_mime_type(filename)
        anchor_iso = anchor_utc.isoformat()
        system_instruction = self._build_system_instruction(
            anchor_iso, user_tz, user_profile_language, user_name, user_email, known_contacts_summary
        )

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
            f"Genera EMAIL_DRAFT lasciando vuota l'email se non esplicitata; per email riguardanti incontri o call specifica sempre chiaramente giorno e orario stabiliti nel corpo del messaggio."
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

        # Pulizia email parlate e normalizzazione di sicurezza
        for action in result.proposed_actions:
            if action.action_type == ActionType.EMAIL_DRAFT and action.email_data:
                action.email_data.recipient_email = clean_spoken_email(action.email_data.recipient_email)
                recip_lower = (action.email_data.recipient_name or "").lower().strip()
                is_user_recip = any(k in recip_lower for k in ("davide", "me", "stesso", "myself", "io"))
                if not is_user_recip and user_email and action.email_data.recipient_email.lower() == user_email.lower():
                    action.email_data.recipient_email = ""

        for entity in result.entities:
            if getattr(entity, "email", None):
                entity.email = clean_spoken_email(entity.email)

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
        user_name: Optional[str] = None,
        user_email: Optional[str] = None,
        known_contacts_summary: Optional[List[str]] = None,
    ) -> SessionExtractionResult:
        """
        Analizza un testo o prompt descrittivo della giornata con Gemini e cascata automatica.
        La lingua dipende dalla lingua usata nel testo o dal profilo utente nel Second Brain.
        """
        anchor_iso = anchor_utc.isoformat()
        system_instruction = self._build_system_instruction(
            anchor_iso, user_tz, user_profile_language, user_name, user_email, known_contacts_summary
        )

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
            f"Genera EMAIL_DRAFT lasciando vuota l'email se non esplicitata; per email riguardanti incontri o call specifica sempre chiaramente giorno e orario stabiliti nel corpo del messaggio."
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

        # Pulizia email parlate e normalizzazione di sicurezza
        for action in result.proposed_actions:
            if action.action_type == ActionType.EMAIL_DRAFT and action.email_data:
                action.email_data.recipient_email = clean_spoken_email(action.email_data.recipient_email)
                recip_lower = (action.email_data.recipient_name or "").lower().strip()
                is_user_recip = any(k in recip_lower for k in ("davide", "me", "stesso", "myself", "io"))
                if not is_user_recip and user_email and action.email_data.recipient_email.lower() == user_email.lower():
                    action.email_data.recipient_email = ""

        for entity in result.entities:
            if getattr(entity, "email", None):
                entity.email = clean_spoken_email(entity.email)

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
            pref_context = "Preferenze verificate del contatto (attenersi ESCLUSIVAMENTE a queste, NON inventarne altre):\n" + "\n".join([f"- {p}" for p in history.key_preferences])
        else:
            pref_context = "Nessuna preferenza oraria registrata per questo contatto. NON citare alcuna preferenza (NON dire che preferisce la mattina o la sera)."

        system_instruction = f"""
Sei un assistente esecutivo per la stesura e l'aggiornamento di email.
Il tuo UNICO compito è aggiornare la proposta oraria all'interno della bozza email esistente, allineandola al nuovo orario: "{new_slot_str}".

VINCOLI TASSATIVI ZERO-HALLUCINATION (TOLLERANZA ZERO PER FABBRICAZIONI):
1. ZERO INVENZIONI DI PROGETTI O ARGOMENTI: È SEVERAMENTE VIETATO introdurre progetti, rilasci software (es. 'rilascio Q1', 'release', 'roadmap'), contratti, accordi o argomenti di discussione NON esplicitamente presenti nella bozza originale.
2. ZERO INVENZIONI DI PREFERENZE ORARIE: È SEVERAMENTE VIETATO inventare preferenze del destinatario (es. "so che preferisci la fascia mattutina", "so che preferisci la mattina"). Se non fornite espressamente nelle preferenze note, NON citare alcuna preferenza.
3. ZERO INVENZIONI DI SCUSE FITTIZIE: Non inventare false scuse, sovrapposizioni in agenda immaginarie o imprevisti non richiesti. Proponi o conferma il nuovo orario in modo diretto, cordiale e professionale (es. "Ti andrebbe bene invece {new_slot_str}?", o "Ti confermo il nuovo orario per la nostra call: {new_slot_str}").
4. INTEGRITÀ E SEMPLICITÀ DEL TESTO: Mantieni inalterati il saluto, il tono, il corpo principale e la firma della bozza originale. Sostituisci unicamente il riferimento al vecchio orario con il nuovo orario: "{new_slot_str}".
5. DESTINATARIO ED EMAIL: Mantieni inalterati `recipient_name` e `recipient_email`.
"""

        prompt = f"""
BOZZA ORIGINALE:
Destinatario: {original_payload.recipient_name} ({original_payload.recipient_email})
Oggetto: {original_payload.subject}
Corpo attuale:
{original_payload.body_markdown}

NUOVO ORARIO PROPOSTO/CONCORDATO:
{new_slot_str}

{pref_context}

Genera il nuovo EmailPayload aggiornato limitandoti a sostituire la data/ora con "{new_slot_str}", senza aggiungere argomenti, scuse o preferenze inventate.
"""

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=EmailPayload,
            temperature=0.0,
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
                    if updated.body_markdown:
                        updated.body_markdown = re.sub(
                            r'(?:alle\s+)?ore\s+\d{1,2}[:\.]\d{2}\s*(?:UTC|Z)\b',
                            new_slot_str,
                            updated.body_markdown,
                            flags=re.IGNORECASE,
                        )
                        updated.body_markdown = re.sub(
                            r'\b\d{1,2}[:\.]\d{2}\s*(?:UTC|Z)\b',
                            new_slot_str,
                            updated.body_markdown,
                            flags=re.IGNORECASE,
                        )
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
   - ZERO-HALLUCINATION: Non aggiungere argomenti aziendali, rilasci o preferenze inventate non presenti nel testo originale.
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
            temperature=0.0,
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



