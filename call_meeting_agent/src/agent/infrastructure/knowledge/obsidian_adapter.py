import os
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Set, Tuple

from ...domain.models import (
    KnowledgePayload,
    TaskPayload,
    PersonHistorySummary,
    PersonInteractionRecord,
    SessionExtractionResult,
)
from ...domain.enums import ActionType, ActionStatus


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
                    r"(?i)^(?:language|lingua|preferred_language|lingua_preferita)\s*:\s*[\"']?([a-zA-Z_-]+)[\"']?",
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

    async def get_vault_graph_data(
        self, active_session: Optional[SessionExtractionResult] = None
    ) -> Dict[str, Any]:
        """
        Costruisce la topologia di rete del Second Brain (Nodi & Collegamenti) per la visualizzazione D3.js:
          - Nodi Persone (da PEOPLE/ o contacts/) con colore #007AFF
          - Nodi Riunioni (da ACTIVITY/Meetings/ o meetings/) con colore #5856D6
          - Nodi Contesto/Aziende/Tag (da WikiLinks estratti) con colore #34C759
          - Nodo Sessione Attiva (focal point della sessione aperta) con colore #FF9500
          - Calibrazione dinamica delle dimensioni (val) basata sul grado di connessione
          - Tracciamento dello stato di sincronizzazione (PROPOSED vs EXECUTED)
        """
        nodes_dict: Dict[str, Dict[str, Any]] = {}
        links_set: Set[Tuple[str, str, str]] = set()

        def add_node(
            node_id: str,
            name: str,
            category: str,
            color: str,
            base_val: int = 12,
            details: str = "",
            is_current_session: bool = False,
            sync_status: Optional[str] = None,
        ):
            if node_id not in nodes_dict:
                nodes_dict[node_id] = {
                    "id": node_id,
                    "name": name,
                    "category": category,
                    "color": color,
                    "val": base_val,
                    "details": details,
                    "is_current_session": is_current_session,
                    "sync_status": sync_status,
                    "degree": 0,
                }
            else:
                if is_current_session:
                    nodes_dict[node_id]["is_current_session"] = True
                    nodes_dict[node_id]["color"] = color
                    nodes_dict[node_id]["category"] = category
                    nodes_dict[node_id]["val"] = max(nodes_dict[node_id]["val"], base_val)
                if sync_status:
                    nodes_dict[node_id]["sync_status"] = sync_status

        def add_link(source_id: str, target_id: str, label: str = "collegamento"):
            if source_id == target_id:
                return
            s, t = sorted([source_id, target_id])
            links_set.add((s, t, label))

        # ── 1. SCANSIONE VAULT SU DISCO (PEOPLE / CONTACTS) ─────────────────
        if self.contacts_dir.exists():
            for f in self.contacts_dir.glob("*.md"):
                if f.name.startswith("."):
                    continue
                try:
                    content = f.read_text(encoding="utf-8")
                except Exception:
                    continue

                name_match = re.search(r'(?i)^name\s*:\s*["\']?([^"\']+)["\']?', content, re.MULTILINE)
                person_name = name_match.group(1).strip() if name_match else f.stem.replace("_", " ")
                person_id = f"person_{self._slugify(person_name)}"

                add_node(
                    node_id=person_id,
                    name=person_name,
                    category="person",
                    color="#007AFF",
                    base_val=14,
                    details="Dossier Contatto",
                )

                wikilinks = re.findall(r"\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]", content)
                for raw_target, alias in wikilinks:
                    target_clean = raw_target.strip()
                    if not target_clean or target_clean == person_name:
                        continue
                    if "meeting" in target_clean.lower() or "/" in target_clean:
                        display_title = alias.strip() if alias else Path(target_clean).stem.replace("_", " ")
                        mid = f"meeting_{self._slugify(display_title)}"
                        add_node(
                            node_id=mid,
                            name=display_title,
                            category="meeting",
                            color="#5856D6",
                            base_val=12,
                            details="Meeting Archiviato",
                            sync_status="SYNCED",
                        )
                        add_link(person_id, mid, label="partecipante")
                    else:
                        ctx_id = f"ctx_{self._slugify(target_clean)}"
                        add_node(
                            node_id=ctx_id,
                            name=target_clean,
                            category="context",
                            color="#34C759",
                            base_val=10,
                            details="Contesto / Relazione",
                        )
                        add_link(person_id, ctx_id, label="relazione")

        # ── 2. SCANSIONE VAULT SU DISCO (MEETINGS) ───────────────────────────
        if self.meetings_dir.exists():
            for f in self.meetings_dir.glob("*.md"):
                if f.name.startswith("."):
                    continue
                try:
                    content = f.read_text(encoding="utf-8")
                except Exception:
                    continue

                title_match = re.search(r'(?i)^title\s*:\s*["\']?([^"\']+)["\']?', content, re.MULTILINE)
                meeting_title = title_match.group(1).strip() if title_match else f.stem.replace("_", " ")
                meeting_id = f"meeting_{self._slugify(meeting_title)}"

                add_node(
                    node_id=meeting_id,
                    name=meeting_title,
                    category="meeting",
                    color="#5856D6",
                    base_val=12,
                    details="Nota Meeting Archiviata",
                    sync_status="SYNCED",
                )

                part_match = re.search(r'(?i)^participant\s*:\s*["\']?\[\[([^\]]+)\]\]["\']?', content, re.MULTILINE)
                if part_match:
                    pname = part_match.group(1).strip()
                    pid = f"person_{self._slugify(pname)}"
                    add_node(
                        node_id=pid,
                        name=pname,
                        category="person",
                        color="#007AFF",
                        base_val=14,
                        details="Dossier Contatto",
                    )
                    add_link(meeting_id, pid, label="partecipante")

                wikilinks = re.findall(r"\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]", content)
                for raw_target, alias in wikilinks:
                    target_clean = raw_target.strip()
                    if not target_clean or (part_match and target_clean == part_match.group(1).strip()):
                        continue
                    ctx_id = f"ctx_{self._slugify(target_clean)}"
                    add_node(
                        node_id=ctx_id,
                        name=target_clean,
                        category="context",
                        color="#34C759",
                        base_val=10,
                        details="Topic / Progetto",
                    )
                    add_link(meeting_id, ctx_id, label="topic")

        # ── 3. FUSIONE CON LA SESSIONE ATTIVA LIVE ───────────────────────────
        if active_session:
            sess_id = f"session_{active_session.session_id}"
            raw_summary = active_session.summary or "Allineamento Operativo"
            display_title = raw_summary[:28] + ("..." if len(raw_summary) > 28 else "")

            know_act = next(
                (a for a in active_session.proposed_actions if a.action_type == ActionType.KNOWLEDGE_NOTE),
                None,
            )
            is_synced = know_act is not None and getattr(know_act, "status", None) == ActionStatus.EXECUTED
            sync_status = "EXECUTED" if is_synced else "PROPOSED"
            status_desc = "Sincronizzato nel Vault" if is_synced else "In attesa di sync"

            add_node(
                node_id=sess_id,
                name=display_title,
                category="session",
                color="#FF9500",
                base_val=18,
                details=f"Sessione Attiva ({status_desc})",
                is_current_session=True,
                sync_status=sync_status,
            )

            for ent in (active_session.entities or []):
                pname = (ent.raw_name or "").strip()
                if not pname:
                    continue
                pid = f"person_{self._slugify(pname)}"
                add_node(
                    node_id=pid,
                    name=pname,
                    category="person",
                    color="#007AFF",
                    base_val=14,
                    details="Interlocutore Rilevato",
                )
                add_link(sess_id, pid, label="interlocutore")

            if know_act and know_act.knowledge_data:
                kd = know_act.knowledge_data
                for b in (kd.backlinks or []):
                    b_clean = b.strip()
                    if not b_clean:
                        continue
                    cid = f"ctx_{self._slugify(b_clean)}"
                    add_node(
                        node_id=cid,
                        name=b_clean,
                        category="context",
                        color="#34C759",
                        base_val=11,
                        details="Argomento Chiave",
                    )
                    add_link(sess_id, cid, label="argomento")

                if kd.target_person_name:
                    t_name = kd.target_person_name.strip()
                    t_id = f"person_{self._slugify(t_name)}"
                    add_node(
                        node_id=t_id,
                        name=t_name,
                        category="person",
                        color="#007AFF",
                        base_val=14,
                        details="Target Dossier",
                    )
                    add_link(sess_id, t_id, label="dossier")

        # ── 4. FALLBACK ZERO-CRASH SE IL GRAFO È TOTALMENTE VUOTO ────────────
        if not nodes_dict:
            add_node("hub_aria", "Aria Knowledge Hub", "session", "#FF9500", 18, "Nodo Centrale", is_current_session=True)
            add_node("ctx_network", "Network & Relazioni", "person", "#007AFF", 14, "Rubrica Persone")
            add_node("ctx_meetings", "Storico Riunioni", "meeting", "#5856D6", 13, "Meeting Notes")
            add_node("ctx_projects", "Progetti & Tasks", "context", "#34C759", 12, "Task Operativi")
            add_link("hub_aria", "ctx_network", "connette")
            add_link("hub_aria", "ctx_meetings", "organizza")
            add_link("hub_aria", "ctx_projects", "traccia")

        # ── 5. CALCOLO GRADO DI CONNESSIONE E DIMENSIONAMENTO DINAMICO ──────
        final_links = []
        for s, t, label in links_set:
            if s in nodes_dict and t in nodes_dict:
                nodes_dict[s]["degree"] += 1
                nodes_dict[t]["degree"] += 1
                final_links.append({"source": s, "target": t, "label": label})

        for n in nodes_dict.values():
            deg = n["degree"]
            n["val"] = n["val"] + min(deg * 2, 10)
            if deg > 0 and not n["is_current_session"]:
                n["details"] = f"{n['details']} ({deg} connessioni)"

        return {
            "nodes": list(nodes_dict.values()),
            "links": final_links,
        }


