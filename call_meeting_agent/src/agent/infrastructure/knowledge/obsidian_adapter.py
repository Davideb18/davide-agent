import os
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import List

from ...domain.models import KnowledgePayload


class ObsidianAdapter:
    """Implementazione del KnowledgeServicePort: gestisce un Vault Markdown compatibile al 100% con Obsidian."""

    def __init__(self, vault_path: str = "data/vault") -> None:
        self.vault_path = Path(vault_path)
        self.meetings_dir = self.vault_path / "meetings"
        self.contacts_dir = self.vault_path / "contacts"

        # Crea le cartelle del Vault se non esistono già
        os.makedirs(self.meetings_dir, exist_ok=True)
        os.makedirs(self.contacts_dir, exist_ok=True)

    def _slugify(self, text: str) -> str:
        """Pulisce un testo per usarlo in sicurezza come nome del file (es: 'Meeting Filippo' -> 'meeting_filippo')."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        return re.sub(r"[-\s]+", "_", text)

    async def save_meeting_note(self, payload: KnowledgePayload) -> str:
        """Crea una nota d'incontro in formato Markdown con i backlink [[NomePersona]]."""
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        slug = self._slugify(payload.title)
        filename = f"{date_str}_{slug}.md"
        file_path = self.meetings_dir / filename

        # Costruisce i bi-directional link in formato Obsidian: [[Nome]]
        backlinks_str = " ".join([f"[[{link}]]" for link in payload.backlinks])
        insights_str = "\n".join([f"- {insight}" for insight in payload.bullet_insights])

        markdown_body = f"""# {payload.title}

- **Data:** {date_str}
- **Partecipante principale:** [[{payload.target_person_name}]]
- **Argomenti & Connessioni:** {backlinks_str}

---

## 💡 Insight Chiave & Decisioni
{insights_str if insights_str else '- Nessun punto chiave specifico registrato.'}

---

## 📝 Note Dettagliate
{payload.markdown_content}
"""

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(markdown_body)

        return str(file_path)

    async def update_person_dossier(
        self, person_name: str, new_insights: List[str], meeting_ref: str
    ) -> str:
        """Aggiorna il dossier vivente della persona, creando la scheda anagrafica se non esiste."""
        clean_name = person_name.strip()
        filename = f"{self._slugify(clean_name)}.md"
        file_path = self.contacts_dir / filename
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Se il file della persona non esiste ancora, crea la copertina
        if not file_path.exists():
            initial_content = f"""# [[{clean_name}]]

- **Tipo:** Dossier Persona / Relazione Professionale
- **Creato il:** {now_str}

## 📌 Profilo & Preferenze Note
Scheda generata e arricchita automaticamente dall'Executive AI Agent.

---

## 📜 Storico Interazioni & Riunioni
"""
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(initial_content)

        # Aggiunge i nuovi insight emersi oggi in coda al file
        append_content = f"\n### 🗓️ Interazione del {now_str} (Rif: [[{meeting_ref}]])\n"
        if new_insights:
            for item in new_insights:
                append_content += f"- {item}\n"
        else:
            append_content += "- Chiamata di allineamento generale.\n"

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(append_content)

        return str(file_path)


# SCRIPT DI COLLAUDO IMMEDIATO
if __name__ == "__main__":
    import asyncio

    async def test():
        adapter = ObsidianAdapter()
        payload = KnowledgePayload(
            title="Allineamento Trellis e Pricing PMS",
            target_person_name="Filippo Calzavara",
            backlinks=["Filippo Calzavara", "Trellis", "PMS Integration", "Pricing Q1"],
            bullet_insights=[
                "Accettato modello commissioni al 3% sui volumi aggregati",
                "Filippo ha espresso dubbi sulla compatibilità temporale del rilascio Q1",
                "Preferisce fissare le call sempre nella fascia mattutina (CET)",
            ],
            markdown_content="Abbiamo discusso l'architettura tecnica per l'aggregazione dei PMS...",
        )

        note_path = await adapter.save_meeting_note(payload)
        dossier_path = await adapter.update_person_dossier(
            person_name="Filippo Calzavara",
            new_insights=payload.bullet_insights,
            meeting_ref="Allineamento Trellis e Pricing PMS",
        )

        print("=" * 60)
        print("SECOND BRAIN COLLAUDATO CON SUCCESSO! 🧠")
        print(f"Nota meeting creata in: {note_path}")
        print(f"Dossier persona aggiornato in: {dossier_path}")
        print("=" * 60)

    asyncio.run(test())
