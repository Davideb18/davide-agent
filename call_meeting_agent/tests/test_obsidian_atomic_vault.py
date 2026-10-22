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
from src.agent.domain.models import KnowledgePayload, TaskPayload, Contact, UserProfile
from src.agent.infrastructure.knowledge.obsidian_adapter import ObsidianAdapter
from src.agent.infrastructure.database.sqlite_repo import SqliteRepository


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


@pytest.mark.asyncio
async def test_vault_user_profile_and_contacts_extraction(test_obsidian: ObsidianAdapter, test_vault_path: Path):
    """Verifica lettura profilo da IDENTITY/Profile.md e scansione contatti da PEOPLE/*.md."""
    # 1. Crea IDENTITY/Profile.md
    id_dir = test_vault_path / "IDENTITY"
    id_dir.mkdir(parents=True, exist_ok=True)
    (id_dir / "Profile.md").write_text(
        """---
type: profile
name: Davide Berno
age: 21
preferred_language: it
role: "Engineering Lead"
company: "Trellis"
---
# Profilo
**Email**: bernodavide8@gmail.com
""",
        encoding="utf-8",
    )

    profile = await test_obsidian.get_user_profile()
    assert profile is not None
    assert profile.full_name == "Davide Berno"
    assert profile.first_name == "Davide"
    assert profile.last_name == "Berno"
    assert profile.email == "bernodavide8@gmail.com"
    assert profile.company == "Trellis"
    assert "Me stesso" in profile.aliases

    # 2. Crea contatto in PEOPLE/Filippo_Calzavara.md
    people_dir = test_vault_path / "PEOPLE"
    people_dir.mkdir(parents=True, exist_ok=True)
    (people_dir / "Filippo_Calzavara.md").write_text(
        """---
name: "Filippo Calzavara"
type: person
role: "Lead Engineer"
company: "Trellis"
email: "filippo@trellis.so"
aliases:
  - Fil
  - CTO Trellis
tags:
  - contact
  - trellis
---
# Filippo
""",
        encoding="utf-8",
    )

    contacts = await test_obsidian.get_all_contacts()
    assert len(contacts) >= 1
    fil = next((c for c in contacts if "Filippo" in c.first_name), None)
    assert fil is not None
    assert fil.first_name == "Filippo"
    assert fil.last_name == "Calzavara"
    assert fil.email == "filippo@trellis.so"
    assert "CTO Trellis" in fil.aliases


@pytest.mark.asyncio
async def test_vault_to_sqlite_contacts_sync(test_obsidian: ObsidianAdapter, test_vault_path: Path, tmp_path: Path):
    """Verifica sync_contacts_from_vault con logica UPSERT in SQLite."""
    db_file = tmp_path / "sync_test.db"
    repo = SqliteRepository(str(db_file))
    await repo.init_db()

    contacts = [
        Contact(
            id="cnt_fil_sync",
            first_name="Filippo",
            last_name="Calzavara",
            email="filippo@trellis.so",
            company="Trellis",
            role="CTO",
            aliases=["Fil"],
            tags=["trellis"],
        )
    ]

    synced = await repo.sync_contacts_from_vault(contacts)
    assert synced == 1

    saved = await repo.get_contacts()
    assert len(saved) == 1
    assert saved[0].id == "cnt_fil_sync"
    assert saved[0].email == "filippo@trellis.so"


@pytest.mark.asyncio
async def test_cross_directory_contact_search_and_update(test_vault_path: Path):
    """Verifica che _find_person_file e save_or_update_contact aggiornino i file in PEOPLE/ anche se contacts_dir è contacts/."""
    people_dir = test_vault_path / "PEOPLE"
    people_dir.mkdir(parents=True, exist_ok=True)
    filippo_md = people_dir / "Filippo_Calzavara.md"
    filippo_md.write_text(
        """---
name: "Filippo Calzavara"
type: person
email: ""
company: "Trellis"
---
# [[Filippo Calzavara]]
Corpo storico del contatto.
""",
        encoding="utf-8",
    )

    # Inizializziamo l'adapter con contacts_dir puntato a contacts/
    adapter = ObsidianAdapter(vault_path=str(test_vault_path))
    adapter.contacts_dir = test_vault_path / "contacts"
    adapter.contacts_dir.mkdir(parents=True, exist_ok=True)

    # 1. Verifica che _find_person_file trovi il contatto in PEOPLE/
    found = adapter._find_person_file("Filippo Calzavara")
    assert found is not None
    assert found.resolve() == filippo_md.resolve()

    # 2. Aggiornamento contatto: deve aggiornare in-place in PEOPLE/ senza duplicare in contacts/
    updated_contact = Contact(
        id="cnt_fil",
        first_name="Filippo",
        last_name="Calzavara",
        email="filippo@trellis.so",
        company="Trellis",
        role="CTO",
        aliases=["Fil"],
        tags=["contact"],
    )
    saved_path_str = await adapter.save_or_update_contact(updated_contact)
    assert Path(saved_path_str).resolve() == filippo_md.resolve()

    # Verifica contenuto aggiornato e preservazione corpo
    content = filippo_md.read_text(encoding="utf-8")
    assert 'email: "filippo@trellis.so"' in content
    assert "Corpo storico del contatto." in content

    # Verifica nessun duplicato in contacts/
    assert not (adapter.contacts_dir / "Filippo_Calzavara.md").exists()


