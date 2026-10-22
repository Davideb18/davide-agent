import os
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import aiosqlite

from ...domain.models import Contact, ProposedAction, SessionExtractionResult
from ...domain.enums import ActionStatus, ActionType, IntentCategory


class SqliteRepository:
    """Implementazione asincrona del RepositoryPort su database SQLite."""

    def __init__(self, db_path: str = "data/call_agent.db") -> None:
        self.db_path = db_path
        # Assicura che la cartella 'data/' esista sul computer
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    async def init_db(self) -> None:
        """Legge lo schema.sql e crea le tabelle nel file SQLite se non esistono già."""
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(schema_sql)
            try:
                await db.execute("ALTER TABLE proposed_actions ADD COLUMN knowledge_data_json TEXT")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE proposed_actions ADD COLUMN task_data_json TEXT")
            except Exception:
                pass
            await db.commit()

    async def seed_default_contacts(self) -> None:
        """Inserisce contatti di test per dimostrare l'agente e la risoluzione dei casi di omonimia."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM contacts") as cursor:
                row = await cursor.fetchone()
                if row and row[0] > 0:
                    return  # I contatti sono già presenti, non facciamo nulla

            demo_contacts = [
                (
                    "cnt_davide",
                    "Davide",
                    "Berno",
                    "bernodavide8@gmail.com",
                    "Trellis",
                    "Utente / Personale",
                    json.dumps(["Davide", "Davide Berno", "Me stesso", "Me", "Io", "Myself"]),
                    json.dumps(["utente", "personale", "trellis"]),
                    "Europe/Rome",
                    datetime.now(timezone.utc).isoformat(),
                ),
                (
                    "cnt_filippo",
                    "Filippo",
                    "Calzavara",
                    "filippo@trellis.so",
                    "Trellis",
                    "Lead Engineer & Acting CTO",
                    json.dumps(["Filippo", "Fil", "CTO Trellis"]),
                    json.dumps(["trellis", "pms", "engineering", "colloquio"]),
                    "Europe/Rome",
                    datetime.now(timezone.utc).isoformat(),
                ),
                (
                    "cnt_marco_rossi",
                    "Marco",
                    "Rossi",
                    "marco.rossi@legalstudio.it",
                    "Studio Legale Rossi",
                    "Avvocato Contrattualista",
                    json.dumps(["Marco Rossi", "Avvocato Marco"]),
                    json.dumps(["legal", "contratti", "nda"]),
                    "Europe/Rome",
                    datetime.now(timezone.utc).isoformat(),
                ),
                (
                    "cnt_marco_bianchi",
                    "Marco",
                    "Bianchi",
                    "marco.bianchi@designstudio.io",
                    "Design Studio",
                    "Senior UI/UX Designer",
                    json.dumps(["Marco Bianchi", "Marco Designer"]),
                    json.dumps(["design", "figma", "frontend", "grafica"]),
                    "Europe/Rome",
                    datetime.now(timezone.utc).isoformat(),
                ),
            ]

            await db.executemany(
                """
                INSERT INTO contacts (
                    id, first_name, last_name, email, company, role,
                    aliases_json, tags_json, timezone, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                demo_contacts,
            )
            await db.commit()

    async def add_contact(self, contact: Contact) -> None:
        """Aggiunge o aggiorna un contatto nella rubrica SQLite per il Memory Graph."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO contacts (
                    id, first_name, last_name, email, company, role,
                    aliases_json, tags_json, timezone, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contact.id,
                    contact.first_name,
                    contact.last_name,
                    contact.email,
                    contact.company,
                    contact.role,
                    json.dumps(contact.aliases),
                    json.dumps(contact.tags),
                    contact.timezone,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await db.commit()

    async def delete_contact(self, contact_id: str) -> None:
        """Rimuove un contatto dalla rubrica SQLite."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
            await db.commit()

    async def get_contacts(self) -> List[Contact]:
        """Recupera tutti i contatti salvati nel database per il Memory Graph."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM contacts ORDER BY first_name ASC") as cursor:
                rows = await cursor.fetchall()
                contacts: List[Contact] = []
                for row in rows:
                    contacts.append(
                        Contact(
                            id=row["id"],
                            first_name=row["first_name"],
                            last_name=row["last_name"],
                            email=row["email"],
                            company=row["company"],
                            role=row["role"],
                            aliases=json.loads(row["aliases_json"]),
                            tags=json.loads(row["tags_json"]),
                            timezone=row["timezone"],
                        )
                    )
                return contacts

    async def get_contact_by_id(self, contact_id: str) -> Optional[Contact]:
        """Recupera un singolo contatto tramite il suo ID univoco."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return Contact(
                    id=row["id"],
                    first_name=row["first_name"],
                    last_name=row["last_name"],
                    email=row["email"],
                    company=row["company"],
                    role=row["role"],
                    aliases=json.loads(row["aliases_json"]),
                    tags=json.loads(row["tags_json"]),
                    timezone=row["timezone"],
                )

    async def save_session(self, session: SessionExtractionResult) -> None:
        """Salva l'intera sessione audio estratta e inserisce le relative azioni proposte."""
        async with aiosqlite.connect(self.db_path) as db:
            # salva la sessione
            await db.execute(
                """
                INSERT OR REPLACE INTO sessions (
                    id, is_actionable, intent_category, summary, raw_transcript, entities_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    1 if session.is_actionable else 0,
                    session.intent_category.value,
                    session.summary,
                    session.raw_transcript,
                    json.dumps([e.model_dump() for e in session.entities]),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

            # salva le azioni proposte collegate
            for action in session.proposed_actions:
                cal_json = action.calendar_data.model_dump_json() if action.calendar_data else None
                mail_json = action.email_data.model_dump_json() if action.email_data else None
                know_json = action.knowledge_data.model_dump_json() if action.knowledge_data else None
                task_json = action.task_data.model_dump_json() if action.task_data else None

                await db.execute(
                    """
                    INSERT OR REPLACE INTO proposed_actions (
                        id, session_id, action_type, status, calendar_data_json, email_data_json,
                        knowledge_data_json, task_data_json, idempotency_key, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        action.id,
                        action.session_id,
                        action.action_type.value,
                        action.status.value,
                        cal_json,
                        mail_json,
                        know_json,
                        task_json,
                        action.idempotency_key,
                        action.created_at.isoformat(),
                        action.updated_at.isoformat(),
                    ),
                )

                # registra l'evento iniziale nell'Audit Log
                await db.execute(
                    """
                    INSERT INTO audit_log (action_id, old_status, new_status, diff_payload_json, executed_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        action.id,
                        "NONE",
                        action.status.value,
                        None,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

            await db.commit()

    async def save_proposed_action(self, action: ProposedAction) -> None:
        """Salva o aggiorna una singola azione proposta (supporta azioni generate on-demand dalla UI)."""
        async with aiosqlite.connect(self.db_path) as db:
            cal_json = action.calendar_data.model_dump_json() if action.calendar_data else None
            mail_json = action.email_data.model_dump_json() if action.email_data else None
            know_json = action.knowledge_data.model_dump_json() if action.knowledge_data else None
            task_json = action.task_data.model_dump_json() if action.task_data else None

            await db.execute(
                """
                INSERT OR REPLACE INTO proposed_actions (
                    id, session_id, action_type, status, calendar_data_json, email_data_json,
                    knowledge_data_json, task_data_json, idempotency_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action.id,
                    action.session_id,
                    action.action_type.value,
                    action.status.value,
                    cal_json,
                    mail_json,
                    know_json,
                    task_json,
                    action.idempotency_key,
                    action.created_at.isoformat(),
                    action.updated_at.isoformat(),
                ),
            )
            await db.commit()

    async def update_action_status(
        self, action_id: str, new_status: str, diff_payload: Optional[Dict[str, Any]] = None
    ) -> None:
        """Aggiorna lo stato di un'azione e traccia le modifiche dell'utente nell'Audit Log."""
        async with aiosqlite.connect(self.db_path) as db:
            # Recupera il vecchio stato
            async with db.execute("SELECT status FROM proposed_actions WHERE id = ?", (action_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return
                old_status = row[0]

            now_iso = datetime.now(timezone.utc).isoformat()

            # Aggiorna l'azione
            await db.execute(
                "UPDATE proposed_actions SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now_iso, action_id),
            )

            # Scrive l'evento nell'Audit Log (The Trellis Way: tracciabilità totale)
            diff_json = json.dumps(diff_payload) if diff_payload else None
            await db.execute(
                """
                INSERT INTO audit_log (action_id, old_status, new_status, diff_payload_json, executed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (action_id, old_status, new_status, diff_json, now_iso),
            )
            await db.commit()

    async def get_audit_logs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Recupera gli ultimi eventi registrati nell'Audit Log per tracciabilità in console."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT a.id, a.action_id, p.action_type, a.old_status, a.new_status, a.diff_payload_json, a.executed_at
                FROM audit_log a
                LEFT JOIN proposed_actions p ON a.action_id = p.id
                ORDER BY a.id DESC LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def is_idempotency_key_used(self, key: str) -> bool:
        """Verifica se un'azione con questa chiave è già stata eseguita o approvata."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM proposed_actions WHERE idempotency_key = ? AND status = 'EXECUTED'",
                (key,),
            ) as cursor:
                row = await cursor.fetchone()
                return row is not None

    async def sync_contacts_from_vault(self, contacts: "List[Contact]") -> int:
        """
        Sincronizza (upsert) i contatti letti dal Vault Obsidian nel database SQLite.
        Il vault è la source of truth: aggiorna i record esistenti senza cancellare
        i contatti aggiunti manualmente fuori dal vault.
        Ritorna il numero di contatti sincronizzati.
        """
        if not contacts:
            return 0

        count = 0
        async with aiosqlite.connect(self.db_path) as db:
            for contact in contacts:
                await db.execute(
                    """
                    INSERT INTO contacts (
                        id, first_name, last_name, email, company, role,
                        aliases_json, tags_json, timezone, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        first_name = excluded.first_name,
                        last_name = excluded.last_name,
                        email = CASE WHEN excluded.email != '' THEN excluded.email ELSE contacts.email END,
                        company = CASE WHEN excluded.company != 'N/D' THEN excluded.company ELSE contacts.company END,
                        role = CASE WHEN excluded.role != 'Contatto' THEN excluded.role ELSE contacts.role END,
                        aliases_json = excluded.aliases_json,
                        tags_json = excluded.tags_json,
                        timezone = excluded.timezone
                    """,
                    (
                        contact.id,
                        contact.first_name,
                        contact.last_name,
                        contact.email,
                        contact.company,
                        contact.role,
                        json.dumps(contact.aliases),
                        json.dumps(contact.tags),
                        contact.timezone,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                count += 1
            await db.commit()
        return count

