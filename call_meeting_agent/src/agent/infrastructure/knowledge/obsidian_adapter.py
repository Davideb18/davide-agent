import os
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional

from ...domain.models import KnowledgePayload, TaskPayload


class ObsidianAdapter:
    """
    Adattatore per Knowledge Base e Second Brain (Obsidian):
    Organizza in modo pulito e logico:
      - ACTIVITY/Meetings/ o meetings/ : Note dettagliate degli incontri con metadati e backlink.
      - PEOPLE/ o contacts/            : Dossier viventi e schede contatto arricchite nel tempo.
      - Projects/Tasks.md o Tasks.md   : Checklist operative delle cose da fare concordate.
    """

    def __init__(self, vault_path: Optional[str] = None) -> None:
        raw_path = vault_path or os.getenv("OBSIDIAN_VAULT_PATH", "data/vault")
        self.vault_path = Path(raw_path).expanduser().resolve()

        # Rilevamento della struttura del Vault
        if (self.vault_path / "ACTIVITY").exists():
            self.meetings_dir = self.vault_path / "ACTIVITY" / "Meetings"
            self.contacts_dir = self.vault_path / "PEOPLE"
        else:
            # Fallback standard per vault isolati o cartelle demo
            self.meetings_dir = self.vault_path / "meetings"
            self.contacts_dir = self.vault_path / "contacts"

        os.makedirs(self.meetings_dir, exist_ok=True)
        os.makedirs(self.contacts_dir, exist_ok=True)

        # Assicura il collegamento in Home.md se presente
        self._ensure_home_dashboard_links()

    def _slugify(self, text: str) -> str:
        """Pulisce un testo per usarlo in sicurezza come nome file."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        return re.sub(r"[-\s]+", "_", text)

    def _ensure_home_dashboard_links(self) -> None:
        """Aggiorna la Dashboard Home.md se presente nel Second Brain per includere la sezione People & Meetings."""
        home_path = self.vault_path / "Home.md"
        if not home_path.exists():
            return

        try:
            with open(home_path, "r", encoding="utf-8") as f:
                content = f.read()

            if "## 👥 Network & Relazioni" not in content:
                network_section = (
                    "\n## 👥 Network & Relazioni (Executive Agent)\n"
                    "Persone, meeting e decisioni tracciate in tempo reale dall'Executive AI Agent.\n"
                    "- **Dossier Contatti**: consulta le schede in `PEOPLE/`\n"
                    "- **Storico Riunioni**: note di allineamento e accordi in `ACTIVITY/Meetings/`\n"
                )
                with open(home_path, "a", encoding="utf-8") as f:
                    f.write(network_section)
        except Exception:
            pass

    async def save_meeting_note(self, payload: KnowledgePayload) -> str:
        """Crea una nota d'incontro formattata con frontmatter YAML e backlink bi-direzionali."""
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        slug = self._slugify(payload.title)
        filename = f"{date_str}_{slug}.md"
        file_path = self.meetings_dir / filename

        # Costruisce i bi-directional link in formato Obsidian: [[Nome]]
        backlinks_str = " ".join([f"[[{link}]]" for link in payload.backlinks if link != payload.target_person_name])
        insights_str = "\n".join([f"- {insight}" for insight in payload.bullet_insights])

        # Se menziona Trellis o CRM, colleghiamo anche Cold_Outreach_CRM
        extra_project_links = ""
        if "trellis" in payload.title.lower() or any("trellis" in b.lower() for b in payload.backlinks):
            if (self.vault_path / "ACTIVITY" / "Projects" / "Internship_Hunt" / "Cold_Outreach_CRM.md").exists():
                extra_project_links = " [[Cold_Outreach_CRM]] [[Internship_Hunt]]"

        tags_yaml = "\n".join([f"  - {self._slugify(b)}" for b in payload.backlinks[:4]])

        markdown_body = f"""---
title: "{payload.title}"
date: {date_str}
type: meeting
participant: "[[{payload.target_person_name}]]"
tags:
  - meeting
{tags_yaml}
---

# {payload.title}

- **Data:** {date_str}
- **Partecipante principale:** [[{payload.target_person_name}]]
- **Connessioni & Argomenti:** {backlinks_str}{extra_project_links}

---

## 💡 Decisioni Chiave & Insight
{insights_str if insights_str else '- Nessun punto chiave specifico registrato.'}

---

## 📝 Note Dettagliate dell'Incontro
{payload.markdown_content}
"""

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(markdown_body)

        return str(file_path)

    async def update_person_dossier(
        self, person_name: str, new_insights: List[str], meeting_ref: str
    ) -> str:
        """Aggiorna o crea il dossier vivente della persona nella cartella PEOPLE/."""
        clean_name = person_name.strip()
        filename = f"{clean_name.replace(' ', '_')}.md"
        file_path = self.contacts_dir / filename
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Se il file della persona non esiste ancora, crea la scheda iniziale con frontmatter
        if not file_path.exists():
            initial_content = f"""---
name: "{clean_name}"
type: person
tags:
  - contact
  - network
created: {now_str}
---

# [[{clean_name}]]

- **Tipo:** Dossier Persona / Relazione Professionale
- **Creato il:** {now_str}

## 📌 Profilo & Preferenze Note
Scheda generata e arricchita automaticamente dall'Executive AI Agent durante le call.

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

    async def append_tasks(self, payload: TaskPayload, meeting_ref: str) -> str:
        """Salva o aggiorna una checklist di task operativi nella cartella Projects/Tasks.md."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if (self.vault_path / "ACTIVITY" / "Projects").exists():
            tasks_file = self.vault_path / "ACTIVITY" / "Projects" / "Tasks.md"
        else:
            tasks_file = self.vault_path / "Tasks.md"

        if not tasks_file.exists():
            initial = (
                "# 📋 Registro Task & To-Do Operativi\n\n"
                "Lista delle azioni concordate durante le call, tracciate dall'Executive AI Agent.\n\n"
                "---\n\n"
            )
            with open(tasks_file, "w", encoding="utf-8") as f:
                f.write(initial)

        assignee_tag = f" (@{payload.assignee})" if payload.assignee else ""
        proj_str = f" [Progetto: [[{payload.target_project}]]]" if payload.target_project else ""
        header = f"\n### 🗓️ Task concordati il {now_str} (Rif: [[{meeting_ref}]]{proj_str})\n"

        items_str = ""
        for item in payload.task_items:
            items_str += f"- [ ] {item.strip()}{assignee_tag}\n"

        with open(tasks_file, "a", encoding="utf-8") as f:
            f.write(header + items_str)

        return str(tasks_file)
