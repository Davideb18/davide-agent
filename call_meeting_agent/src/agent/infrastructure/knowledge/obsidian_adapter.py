import os
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional

from ...domain.models import (
    KnowledgePayload,
    TaskPayload,
    PersonHistorySummary,
    PersonInteractionRecord,
)


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

    def _safe_person_filename(self, person_name: str) -> str:
        """Sanitizza il nome del contatto per garantire un nome file valido e sicuro sul filesystem."""
        clean = person_name.strip()
        safe = re.sub(r'[\\/*?:"<>|]', "", clean).strip()
        safe = re.sub(r"\s+", "_", safe)
        return f"{safe or 'Contatto'}.md"

    def _find_person_file(self, person_name: str) -> Optional[Path]:
        """Individua in modo flessibile il file markdown del contatto."""
        safe_name = self._safe_person_filename(person_name)
        p = self.contacts_dir / safe_name
        if p.exists():
            return p
        clean = person_name.strip().replace(" ", "_").lower()
        if self.contacts_dir.exists():
            for f in self.contacts_dir.glob("*.md"):
                if f.stem.lower() == clean or f.stem.lower() == person_name.strip().lower():
                    return f
        return None

    async def get_person_history(self, person_name: str) -> Optional[PersonHistorySummary]:
        """
        Recupera la memoria storica del contatto dal Second Brain (People Intelligence).
        Estrae cronologia interazioni, ultimo contatto e preferenze registrate nel tempo.
        """
        file_path = self._find_person_file(person_name)
        if not file_path or not file_path.exists():
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return None

        # Estrazione blocchi di interazione: ### 🗓️ Interazione del YYYY-MM-DD
        pattern = r"###\s*🗓️?\s*Interazione del\s*([0-9]{4}-[0-9]{2}-[0-9]{2})(?:\s*\(Rif:\s*\[\[(.*?)\]\]\))?\s*\n(.*?)(?=\n###|\Z)"
        matches = list(re.finditer(pattern, content, re.DOTALL))

        interactions: List[PersonInteractionRecord] = []
        last_date = None

        for match in matches:
            date_str = match.group(1).strip()
            meeting_ref = match.group(2).strip() if match.group(2) else ""
            body_text = match.group(3).strip()
            
            # Estrae i bullet points
            b_lines = [l.strip() for l in body_text.splitlines() if l.strip()]
            bullets = [line.lstrip("-* ").strip() for line in b_lines if line.startswith(("-", "*"))]
            summary_text = bullets[0] if bullets else (b_lines[0] if b_lines else "Incontro di allineamento.")
            
            interactions.append(
                PersonInteractionRecord(
                    meeting_date=date_str,
                    title=meeting_ref or f"Meeting del {date_str}",
                    summary=summary_text,
                    link=meeting_ref,
                )
            )
            last_date = date_str

        # Estrazione preferenze note: cerca sezione Profilo o bullet con keyword
        preferences: List[str] = []
        pref_section_match = re.search(r"##\s*📌?\s*Profilo\s*&\s*Preferenze Note(.*?)(?=##|\Z)", content, re.DOTALL)
        if pref_section_match:
            sec_lines = pref_section_match.group(1).splitlines()
            for line in sec_lines:
                clean_l = line.lstrip("-* ").strip()
                if clean_l and not clean_l.startswith("Scheda generata") and len(clean_l) > 5:
                    preferences.append(clean_l)

        # Scansione aggiuntiva nelle interazioni per insight su orari/preferenze
        for rec in interactions:
            for word in ["preferisce", "orari", "pomeriggio", "mattina", "call", "abitudine", "disponibile"]:
                if word in rec.summary.lower() and rec.summary not in preferences:
                    preferences.append(rec.summary)

        return PersonHistorySummary(
            contact_name=person_name,
            last_meeting_date=last_date,
            key_preferences=preferences[:4],
            recent_interactions=list(reversed(interactions))[:5],
        )

    async def link_meeting_to_person(
        self,
        person_name: str,
        meeting_title: str,
        meeting_rel_path: str,
        summary: str,
        insights: Optional[List[str]] = None,
    ) -> bool:
        """
        Aggiorna atomicamente la scheda del contatto creando un backlink bidirezionale formale verso la nota meeting.
        Preserva rigorosamente il frontmatter YAML e il contenuto manuale preesistente.
        """
        filename = self._safe_person_filename(person_name)
        file_path = self.contacts_dir / filename
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # 1. Se il dossier non esiste, lo crea con la struttura base
        if not file_path.exists():
            clean_name = person_name.strip()
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
Scheda arricchita automaticamente dall'Executive AI Agent.

---

## 📜 Storico Interazioni & Riunioni
"""
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(initial_content)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                existing_text = f.read()

            bullets = []
            if summary and summary.strip():
                bullets.append(f"- {summary.strip()}")
            if insights:
                for ins in insights:
                    if ins and ins.strip() and ins.strip() != (summary or "").strip():
                        bullets.append(f"- {ins.strip()}")
            if not bullets:
                bullets.append("- Incontro di allineamento e sincronizzazione operativa.")

            entry_body = "\n".join(bullets)
            entry = f"\n### 🗓️ Interazione del {now_str} (Rif: [[{meeting_rel_path}|{meeting_title}]])\n{entry_body}\n"

            # Inserimento atomico: cerca header storico con regex flessibile (con o senza emoji)
            header_pattern = r"(##\s*(?:📜\s*)?(?:Storico\s*Interazioni(?:\s*&\s*Riunioni)?|Incontri\s*Recenti))"
            header_match = re.search(header_pattern, existing_text, re.IGNORECASE)
            if header_match:
                idx = header_match.end()
                new_text = existing_text[:idx] + "\n" + entry + existing_text[idx:]
            else:
                new_text = existing_text + f"\n\n## 📜 Storico Interazioni & Riunioni\n" + entry

            # Scrittura atomica tramite file temporaneo per prevenire corruzioni
            tmp_path = file_path.with_suffix(".md.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(new_text)
            tmp_path.replace(file_path)
            return True
        except Exception:
            return False

    def _normalize_language_name(self, lang_str: str) -> str:
        """Normalizza la lingua in italiano, inglese, o codice ISO."""
        l = lang_str.lower().strip()
        if l in ("it", "ita", "italiano", "italian"):
            return "Italiano"
        if l in ("en", "eng", "inglese", "english"):
            return "English"
        if l in ("es", "spa", "spagnolo", "spanish"):
            return "Español"
        if l in ("de", "deu", "tedesco", "german"):
            return "Deutsch"
        if l in ("fr", "fra", "francese", "french"):
            return "Français"
        return lang_str.capitalize()

    async def get_user_profile_language(self) -> Optional[str]:
        """
        Recupera la preferenza linguistica specificata nel profilo utente all'interno del Second Brain.
        Cerca in file come IDENTITY/Profile.md, Profile.md, User_Profile.md.
        """
        candidate_files = [
            self.vault_path / "IDENTITY" / "Profile.md",
            self.vault_path / "IDENTITY" / "profile.md",
            self.vault_path / "IDENTITY" / "User_Profile.md",
            self.vault_path / "Profile.md",
            self.vault_path / "profile.md",
        ]

        identity_dir = self.vault_path / "IDENTITY"
        if identity_dir.exists():
            for f in identity_dir.glob("*.md"):
                if f not in candidate_files:
                    candidate_files.append(f)

        for filepath in candidate_files:
            if not filepath.exists():
                continue
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()

                # 1. Cerca nel frontmatter YAML (es. language: it / lingua: italiano / preferred_language: en)
                yaml_matches = re.findall(
                    r"(?i)^(?:language|lingua|preferred_language|lingua_preferita)\s*:\s*[\"']?([a-zA-Z\s]+)[\"']?",
                    content,
                    re.MULTILINE,
                )
                if yaml_matches:
                    val = yaml_matches[0].strip().lower()
                    return self._normalize_language_name(val)

                # 2. Cerca nel corpo markdown (es. - **Lingua**: Italiano / **Language**: English)
                body_matches = re.findall(
                    r"(?i)(?:-|\*)\s*\*\*(?:lingua|language|lingua preferita|preferred language)\*\*:\s*([a-zA-Z]+)",
                    content,
                )
                if body_matches:
                    val = body_matches[0].strip().lower()
                    return self._normalize_language_name(val)
            except Exception:
                continue

        return None


