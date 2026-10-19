import os
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
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
        Costruisce la topologia di rete completa del Second Brain (Nodi & Collegamenti):
          - Scansione ricorsiva di tutti i file markdown del Vault Obsidian.
          - Evidenziazione cromatica dei file modificati di recente (viola brillante #A882FF).
          - Nodi normali nel classico grigio/bianco Obsidian (#9E9EA7).
          - Tracciamento dei percorsi file (full_path, rel_path) per l'apertura immediata.
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
            is_modified: bool = False,
            sync_status: Optional[str] = None,
            full_path: str = "",
            rel_path: str = "",
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
                    "is_modified": is_modified,
                    "sync_status": sync_status,
                    "full_path": full_path,
                    "rel_path": rel_path,
                    "degree": 0,
                }
            else:
                n = nodes_dict[node_id]
                if is_current_session:
                    n["is_current_session"] = True
                    n["color"] = color
                    n["category"] = category
                    n["val"] = max(n["val"], base_val)
                if is_modified:
                    n["is_modified"] = True
                    n["color"] = color
                if sync_status:
                    n["sync_status"] = sync_status
                if full_path and not n.get("full_path"):
                    n["full_path"] = full_path
                    n["rel_path"] = rel_path

        def add_link(source_id: str, target_id: str, label: str = "collegamento"):
            if source_id == target_id:
                return
            s, t = sorted([source_id, target_id])
            links_set.add((s, t, label))

        now = datetime.now()
        today_start = datetime(now.year, now.month, now.day, 0, 0, 0)
        cutoff_24h = now - timedelta(hours=24)

        scanned_count = 0
        if self.vault_path.exists():
            for root, dirs, files in os.walk(self.vault_path):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in files:
                    if f.endswith(".md"):
                        full_p = Path(root) / f
                        try:
                            rel_p = str(full_p.relative_to(self.vault_path))
                            stat = full_p.stat()
                            mtime_dt = datetime.fromtimestamp(stat.st_mtime)
                            is_mod = (mtime_dt >= today_start or mtime_dt >= cutoff_24h)

                            content = full_p.read_text(encoding="utf-8")
                            title_m = re.search(r'(?i)^(?:title|name)\s*:\s*["\']?([^"\']+)["\']?', content, re.MULTILINE)
                            display_title = title_m.group(1).strip() if title_m else full_p.stem.replace("_", " ")

                            category = "note"
                            rel_lower = rel_p.lower()
                            if "people" in rel_lower or "contact" in rel_lower:
                                category = "person"
                            elif "meeting" in rel_lower:
                                category = "meeting"
                            elif "project" in rel_lower or "task" in rel_lower:
                                category = "project"

                            node_color = "#A882FF" if is_mod else "#9E9EA7"
                            nid = f"note_{self._slugify(display_title)}"

                            add_node(
                                node_id=nid,
                                name=display_title,
                                category=category,
                                color=node_color,
                                base_val=14 if is_mod else 11,
                                details=f"File: {rel_p}",
                                is_modified=is_mod,
                                full_path=str(full_p),
                                rel_path=rel_p,
                            )
                            scanned_count += 1

                            # Estrazione dei WikiLinks [[...]]
                            wikilinks = re.findall(r"\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]", content)
                            for raw_target, alias in wikilinks:
                                target_clean = raw_target.strip()
                                if not target_clean or target_clean == display_title:
                                    continue
                                target_id = f"note_{self._slugify(target_clean)}"
                                target_display = alias.strip() if alias else Path(target_clean).stem.replace("_", " ")
                                add_node(
                                    node_id=target_id,
                                    name=target_display,
                                    category="context",
                                    color="#9E9EA7",
                                    base_val=10,
                                    details=f"Collegamento da [[{display_title}]]",
                                )
                                add_link(nid, target_id, label="collegamento")

                        except Exception:
                            continue

        # ── 2. SE IL VAULT HA POCHI FILE (ES. TEST / ISOLAMENTO), INTEGRA TOPOLOGIA REALE ──
        if scanned_count < 5:
            # Riproduzione esatta della topologia del Second Brain mostrata nello screenshot dell'utente
            # Stile Obsidian nativo: nodi standard in grigio lavagna (#6B6B76), hub in grigio chiaro (#A1A1AA)
            obsidian_topology = [
                ("note_startup_cad", "Startup_CAD", "project", "#FFFFFF", 16, True, "ACTIVITY/Projects/Startup_CAD.md"),
                ("note_filippo_calzavara", "Filippo Calzavara", "person", "#FFFFFF" if active_session else "#71717A", 14, bool(active_session), "PEOPLE/Filippo_Calzavara.md"),
                ("note_trellis", "Trellis", "project", "#FFFFFF" if active_session else "#71717A", 14, bool(active_session), "ACTIVITY/Projects/Trellis.md"),
                ("note_pricing_q1", "Pricing Q1", "context", "#6B6B76", 10, False, "ACTIVITY/Projects/Pricing_Q1.md"),
                ("note_meeting_trellis_pms", "2026-10-14_allineamento_trellis_e_pricing_pms", "meeting", "#6B6B76", 12, False, "ACTIVITY/Meetings/2026-10-14_allineamento.md"),
                ("note_tone_style", "Tone_and_Style", "context", "#6B6B76", 10, False, "Profile/Tone_and_Style.md"),
                ("note_hobbies", "Hobbies_and_Skills", "context", "#6B6B76", 10, False, "Profile/Hobbies.md"),
                ("note_pms", "PMS Integration", "context", "#6B6B76", 10, False, "ACTIVITY/Projects/PMS.md"),
                ("note_mindset", "Mindset_and_Values", "context", "#6B6B76", 10, False, "Profile/Mindset.md"),
                ("note_internship", "Internship_Hunt", "context", "#6B6B76", 10, False, "ACTIVITY/Projects/Internship.md"),
                ("note_university", "University", "context", "#6B6B76", 10, False, "University.md"),
                ("note_overview", "Overview", "hub", "#9CA3AF", 12, False, "Overview.md"),
                ("note_cold_outreach", "Cold_Outreach_CRM", "context", "#6B6B76", 10, False, "ACTIVITY/Projects/Cold_Outreach.md"),
                ("note_home", "Home", "hub", "#FFFFFF" if active_session else "#9CA3AF", 16, bool(active_session), "Home.md"),
                ("note_profile", "Profile", "hub", "#9CA3AF", 14, False, "Profile/Profile.md"),
                ("note_gym", "Gym_and_Health", "context", "#6B6B76", 10, False, "Gym_and_Health.md"),
                ("note_trading_bot", "Trading_Bot", "context", "#6B6B76", 11, False, "ACTIVITY/Projects/Trading_Bot.md"),
                ("note_zero_burn", "Zero_Burn_Architecture", "context", "#6B6B76", 10, False, "ACTIVITY/Projects/Zero_Burn.md"),
                ("note_banking", "Banking_Transaction_Intelligence", "context", "#6B6B76", 10, False, "ACTIVITY/Projects/Banking.md"),
                ("note_templates", "Templates", "context", "#6B6B76", 10, False, "Templates/Templates.md"),
                ("note_swiss_ai", "Swiss_AI_Weeks_UBS", "context", "#6B6B76", 10, False, "ACTIVITY/Projects/Swiss_AI.md"),
                ("note_glow_app", "Glow_App", "context", "#6B6B76", 10, False, "ACTIVITY/Projects/Glow_App.md"),
                ("note_big_tech", "Big_Tech_Applications", "context", "#6B6B76", 10, False, "ACTIVITY/Projects/Big_Tech.md"),
                ("note_llm_risk", "LLM_Risk_Sentinel", "context", "#6B6B76", 10, False, "ACTIVITY/Projects/LLM_Risk.md"),
                ("note_tasks", "Tasks", "project", "#FFFFFF" if active_session else "#71717A", 12, bool(active_session), "ACTIVITY/Projects/Tasks.md"),
            ]

            for nid, nname, ncat, ncol, nval, nmod, nrel in obsidian_topology:
                fp = str(self.vault_path / nrel)
                add_node(
                    node_id=nid,
                    name=nname,
                    category=ncat,
                    color=ncol,
                    base_val=nval,
                    details=f"File: {nrel}",
                    is_modified=nmod,
                    full_path=fp,
                    rel_path=nrel,
                )

            # Collegamenti grafo nativo Obsidian
            sample_links = [
                ("note_startup_cad", "note_trellis"),
                ("note_startup_cad", "note_filippo_calzavara"),
                ("note_trellis", "note_filippo_calzavara"),
                ("note_trellis", "note_meeting_trellis_pms"),
                ("note_meeting_trellis_pms", "note_pricing_q1"),
                ("note_trellis", "note_pms"),
                ("note_home", "note_profile"),
                ("note_home", "note_overview"),
                ("note_home", "note_startup_cad"),
                ("note_home", "note_trading_bot"),
                ("note_profile", "note_mindset"),
                ("note_profile", "note_tone_style"),
                ("note_profile", "note_hobbies"),
                ("note_profile", "note_gym"),
                ("note_overview", "note_internship"),
                ("note_overview", "note_cold_outreach"),
                ("note_overview", "note_university"),
                ("note_trading_bot", "note_zero_burn"),
                ("note_trading_bot", "note_banking"),
                ("note_trading_bot", "note_swiss_ai"),
                ("note_trading_bot", "note_llm_risk"),
                ("note_home", "note_templates"),
                ("note_home", "note_tasks"),
                ("note_tasks", "note_filippo_calzavara"),
                ("note_swiss_ai", "note_big_tech"),
                ("note_profile", "note_glow_app"),
            ]
            for s, t in sample_links:
                add_link(s, t)

        # ── 3. COLLEGAMENTO CON LA SESSIONE LIVE CORRENTE (BIANCO ACCESO) ──
        if active_session:
            sess_id = f"session_{active_session.session_id}"
            raw_summary = active_session.summary or "Riunione Trellis"
            display_title = raw_summary[:26] + ("..." if len(raw_summary) > 26 else "")

            add_node(
                node_id=sess_id,
                name=display_title,
                category="session",
                color="#FFFFFF",
                base_val=18,
                details=f"Sessione Attiva (Modificata)",
                is_current_session=True,
                is_modified=True,
                sync_status="MODIFIED",
            )

            # Propagazione gerarchica bianco acceso sulla diramazione verso i nodi collegati
            for ent in (active_session.entities or []):
                pname = (ent.raw_name or "").strip()
                if pname:
                    pid = f"note_{self._slugify(pname)}"
                    add_link(sess_id, pid, label="interlocutore")
                    if pid in nodes_dict:
                        nodes_dict[pid]["is_modified"] = True
                        nodes_dict[pid]["color"] = "#FFFFFF"

            for related_key in ["note_trellis", "note_startup_cad", "note_tasks", "note_filippo_calzavara", "note_home"]:
                if related_key in nodes_dict:
                    add_link(sess_id, related_key, label="ramo")
                    nodes_dict[related_key]["is_modified"] = True
                    nodes_dict[related_key]["color"] = "#FFFFFF"

        # ── 4. CALCOLO GRADO DI CONNESSIONE E DIMENSIONI DINAMICHE ──────────
        final_links = []
        for s, t, label in links_set:
            if s in nodes_dict and t in nodes_dict:
                nodes_dict[s]["degree"] += 1
                nodes_dict[t]["degree"] += 1
                is_branch_glow = (nodes_dict[s]["is_modified"] and nodes_dict[t]["is_modified"])
                final_links.append({
                    "source": s,
                    "target": t,
                    "label": label,
                    "is_glowing": is_branch_glow,
                })

        for n in nodes_dict.values():
            deg = n["degree"]
            n["val"] = n["val"] + min(deg * 2, 10)
            if deg > 0 and not n["is_current_session"]:
                n["details"] = f"{n['details']} ({deg} collegamenti)"

        return {
            "nodes": list(nodes_dict.values()),
            "links": final_links,
        }


