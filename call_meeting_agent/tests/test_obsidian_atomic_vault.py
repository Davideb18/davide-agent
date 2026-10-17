"""
test_obsidian_atomic_vault.py — Test per l'archiviazione atomica e il grafo Second Brain Obsidian.
Verifica:
  - Scrittura atomica della nota meeting (preservazione frontmatter YAML e rimozione .tmp)
  - Collegamento bidirezionale automatico verso il dossier persona (link_meeting_to_person)
  - Estrazione People Intelligence e preferenze (get_person_history)
  - Lettura profilo utente per lingua preferita (get_user_profile_language)
  - Append sicuro delle checklist operative in Tasks.md
"""
import pytest
from pathlib import Path
from src.agent.domain.models import KnowledgePayload, TaskPayload
from src.agent.infrastructure.knowledge.obsidian_adapter import ObsidianAdapter


@pytest.mark.asyncio
async def test_atomic_tmp_replace_meeting_note(test_obsidian: ObsidianAdapter, test_vault_path: Path):
    """Verifica la creazione atomica della nota meeting e l'assenza di file temporanei residui."""
    payload = KnowledgePayload(
        title="Allineamento Trellis PMS",
        target_person_name="Filippo Calzavara",
        summary="Accordo su pricing e sincronizzazione calendari",
        backlinks=["Trellis", "PMS", "Engineering"],
        bullet_insights=["Margine 15%", "Webhook real-time", "Beta test a novembre"],
        markdown_content="Abbiamo concordato l'architettura tecnica e i contratti API.",
    )

    note_path_str = await test_obsidian.save_meeting_note(payload)
    note_path = Path(note_path_str)

    assert note_path.exists(), "Il file della nota meeting non è stato creato!"
    content = note_path.read_text(encoding="utf-8")

    # Verifica frontmatter YAML e backlink
    assert "---" in content
    assert 'title: "Allineamento Trellis PMS"' in content
    assert 'participant: "[[Filippo Calzavara]]"' in content
    assert "[[Trellis]]" in content
    assert "Margine 15%" in content
    assert "Abbiamo concordato l'architettura tecnica" in content

    # Verifica atomicità: nessun file temporaneo .tmp deve rimanere nel filesystem
    tmp_files = list(test_vault_path.rglob("*.tmp"))
    assert len(tmp_files) == 0, f"Rilevati file temporanei .tmp non ripuliti: {tmp_files}"


@pytest.mark.asyncio
async def test_bidirectional_person_dossier_linking(test_obsidian: ObsidianAdapter, test_vault_path: Path):
    """Verifica che link_meeting_to_person crei e aggiorni la scheda contatto con backlink formale."""
    person_name = "Filippo Calzavara"
    meeting_title = "Allineamento Trellis PMS"
    meeting_rel = "meetings/2026-10-17_allineamento_trellis_pms.md"
    summary = "Accordo su quota 15% e integrazione calendari."
    insights = ["Preferisce call nel primo pomeriggio", "Usa stack Python e FastAPI"]

    # 1. Primo collegamento: creazione automatica del dossier persona
    success = await test_obsidian.link_meeting_to_person(
        person_name=person_name,
        meeting_title=meeting_title,
        meeting_rel_path=meeting_rel,
        summary=summary,
        insights=insights,
    )
    assert success is True

    dossier_path = test_obsidian.contacts_dir / "Filippo_Calzavara.md"
    assert dossier_path.exists()
    content = dossier_path.read_text(encoding="utf-8")

    assert 'name: "Filippo Calzavara"' in content
    assert f"[[{meeting_rel}|{meeting_title}]]" in content
    assert "Preferisce call nel primo pomeriggio" in content

    # 2. Secondo collegamento successivo: inserimento atomico senza sovrascrittura
    success_2 = await test_obsidian.link_meeting_to_person(
        person_name=person_name,
        meeting_title="Follow-up Contrattuale",
        meeting_rel_path="meetings/2026-10-18_followup.md",
        summary="Revisione NDA firmata.",
        insights=["Confermata firma digitale"],
    )
    assert success_2 is True
    content_updated = dossier_path.read_text(encoding="utf-8")
    assert "Follow-up Contrattuale" in content_updated
    assert 'name: "Filippo Calzavara"' in content_updated

    # Nessun file .tmp residuo
    assert len(list(test_vault_path.rglob("*.tmp"))) == 0


@pytest.mark.asyncio
async def test_person_history_extraction(test_obsidian: ObsidianAdapter):
    """Verifica che get_person_history estragga le preferenze storiche e gli incontri dal dossier."""
    # Collega un incontro per creare lo storico
    await test_obsidian.link_meeting_to_person(
        person_name="Marco Rossi",
        meeting_title="Consulenza Contratti",
        meeting_rel_path="meetings/2026-10-17_consulenza.md",
        summary="Marco preferisce call la mattina prima delle 11:00.",
        insights=["Preferisce call la mattina"],
    )

    history = await test_obsidian.get_person_history("Marco Rossi")
    assert history is not None
    assert history.contact_name == "Marco Rossi"
    assert len(history.recent_interactions) >= 1
    assert "Consulenza Contratti" in history.recent_interactions[0].title


@pytest.mark.asyncio
async def test_user_profile_language_detection(test_obsidian: ObsidianAdapter, test_vault_path: Path):
    """Verifica il recupero della preferenza linguistica dal file IDENTITY/Profile.md."""
    # Caso 1: file assente -> fallback None
    lang_none = await test_obsidian.get_user_profile_language()
    assert lang_none is None

    # Caso 2: file presente con preferenza inglese
    identity_dir = test_vault_path / "IDENTITY"
    identity_dir.mkdir(parents=True, exist_ok=True)
    profile_file = identity_dir / "Profile.md"
    profile_file.write_text(
        """---
name: "Davide"
preferred_language: en
role: "Engineering Lead"
---

# Profilo Utente
- **Lingua Preferita**: English
""",
        encoding="utf-8",
    )

    detected_lang = await test_obsidian.get_user_profile_language()
    assert detected_lang == "English"


@pytest.mark.asyncio
async def test_tasks_markdown_append(test_obsidian: ObsidianAdapter, test_vault_path: Path):
    """Verifica l'inserimento formattato delle checklist in Tasks.md."""
    payload = TaskPayload(
        task_items=["Verificare quote commissioni Trellis", "Schedulare collaudo infrastruttura"],
        target_project="Integrazione PMS",
        assignee="Davide",
    )

    tasks_path_str = await test_obsidian.append_tasks(payload=payload, meeting_ref="Trellis Sync")
    tasks_path = Path(tasks_path_str)

    assert tasks_path.exists()
    content = tasks_path.read_text(encoding="utf-8")
    assert "- [ ] Verificare quote commissioni Trellis" in content
    assert "- [ ] Schedulare collaudo infrastruttura" in content
    assert "Trellis Sync" in content
