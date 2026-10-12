import os
import json
import re
import aiosqlite
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

from app.models import (
    PropertyMetadata, GeoCoords, HouseRules, PartnerService,
    GuestProfile, GuestPreferences, GuestMemoryGraph,
    UpsellPackage, UpsellCategory, Order, OrderItem,
    ChatMessage, GenerativeUIPayload, AgentThoughtTrace
)

# ---------------------------------------------------------------------
# Percorsi dei file e caricamento variabili d'ambiente (.env)
# ---------------------------------------------------------------------
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
ENV_PATH = os.path.join(BACKEND_DIR, ".env")
load_dotenv(ENV_PATH)

DB_PATH = os.path.join(BACKEND_DIR, "davide_agent.db")
SEED_DATA_PATH = os.path.join(os.path.dirname(__file__), "seed_data.json")
PROPERTY_MD_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "property.md")


# =====================================================================
# 1. CONNESSIONE E TABELLE SQLITE
# =====================================================================

@asynccontextmanager
async def get_db():
    """
    Apre e gestisce una connessione asincrona a SQLite con aiosqlite.
    L'annotazione @asynccontextmanager ci permette di usare 'async with get_db() as db:'.
    Quando il blocco finisce, la connessione si chiude da sola liberando memoria.
    row_factory = aiosqlite.Row permette di leggere le colonne per nome (row['name']).
    """
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    """
    Crea le 6 tabelle relazionali nel file davide_agent.db se non esistono ancora.
    1. properties: alloggi gestiti (Wi-Fi, serrature, regole casa)
    2. partners: negozi e servizi locali convenzionati (orari, GPS, foto)
    3. guests: anagrafica ospiti e memoria permanente dell'AI
    4. upsell_packages: servizi extra a pagamento (fiori, colazione, late checkout)
    5. orders: acquisti confermati con chiave anti-duplicato (idempotenza)
    6. chat_messages: storico conversazioni tra ospite e agente con Generative UI
    """
    async with get_db() as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS properties (
                id TEXT PRIMARY KEY, name TEXT, city TEXT, neighborhood TEXT, address TEXT,
                lat REAL, lng REAL, host_name TEXT, host_phone TEXT, wifi_ssid TEXT,
                wifi_password TEXT, smart_lock_brand TEXT, smart_lock_instructions TEXT,
                garbage_instructions TEXT, air_conditioning_instructions TEXT, ztl_info TEXT,
                house_rules_json TEXT
            );

            CREATE TABLE IF NOT EXISTS partners (
                id TEXT PRIMARY KEY, property_id TEXT, name TEXT, category TEXT,
                description TEXT, price_level TEXT, lat REAL, lng REAL, address TEXT,
                contact_phone TEXT, opening_hours_json TEXT, is_24_7 INTEGER,
                tags_json TEXT, image_url TEXT
            );

            CREATE TABLE IF NOT EXISTS guests (
                id TEXT PRIMARY KEY, property_id TEXT, full_name TEXT, phone TEXT, email TEXT,
                check_in_date TEXT, check_out_date TEXT, preferences_json TEXT,
                memory_graph_json TEXT
            );

            CREATE TABLE IF NOT EXISTS upsell_packages (
                id TEXT PRIMARY KEY, property_id TEXT, title TEXT, category TEXT,
                description TEXT, price REAL, currency TEXT DEFAULT 'EUR', image_url TEXT,
                badge TEXT, items_included_json TEXT, is_active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY, property_id TEXT, guest_id TEXT, items_json TEXT,
                total_amount REAL, currency TEXT DEFAULT 'EUR', status TEXT,
                idempotency_key TEXT UNIQUE, created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,
                generative_ui_json TEXT, traces_json TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.commit()


# =====================================================================
# 2. INGESTION DI PROPERTY.MD (DUAL-MODE: GEMINI AI + FALLBACK LOCALE)
# =====================================================================

def parse_property_markdown_fallback(content: str) -> PropertyMetadata:
    """
    Parser deterministico locale di sicurezza (senza AI).
    Viene usato se la chiave API di Gemini non è impostata o se la connessione è assente.
    Estrae SOLO i dati scritti dall'host senza inventare valori finti.
    """
    def extract_line(prefix: str) -> str:
        for line in content.splitlines():
            if prefix.lower() in line.lower():
                parts = line.split(":", 1)
                if len(parts) > 1:
                    return parts[1].strip().replace("**", "").replace("*", "")
        return ""

    # 1. Nome dell'alloggio
    name = ""
    for line in content.splitlines():
        if line.strip().startswith("# "):
            name = line.strip().replace("#", "").strip()
            break

    # 2. Coordinate geografiche
    lat_match = re.search(r"Latitudine:\s*([0-9.]+)", content, re.IGNORECASE)
    lng_match = re.search(r"Longitudine:\s*([0-9.]+)", content, re.IGNORECASE)
    lat = float(lat_match.group(1)) if lat_match else 0.0
    lng = float(lng_match.group(1)) if lng_match else 0.0

    # 3. Orari di silenzio
    quiet_match = re.search(r"dalle\s*([0-9:]+)\s*alle\s*([0-9:]+)", content, re.IGNORECASE)
    quiet_start = quiet_match.group(1).strip() if quiet_match else ""
    quiet_end = quiet_match.group(2).strip() if quiet_match else ""

    max_guests_str = extract_line("Capienza massima")
    max_guests = int(max_guests_str) if max_guests_str.isdigit() else 2

    # 4. Contatti d'emergenza
    emergency_contacts = {}
    host_phone = extract_line("Telefono Host")
    if host_phone:
        emergency_contacts["Host"] = host_phone
    emergency_host = extract_line("Telefono Emergenza Host")
    if emergency_host:
        emergency_contacts["Emergenza Host"] = emergency_host
    hospital = extract_line("Pronto Soccorso")
    if hospital:
        emergency_contacts["Pronto Soccorso"] = hospital

    rules = HouseRules(
        quiet_hours_start=quiet_start,
        quiet_hours_end=quiet_end,
        max_guests=max_guests,
        parties_allowed=False,
        pets_allowed=False,
        smoking_allowed=False,
        emergency_water_valve_location=extract_line("Valvola Generale Acqua") or None,
        emergency_breaker_box_location=extract_line("Quadro Elettrico") or None,
        emergency_contacts=emergency_contacts
    )

    return PropertyMetadata(
        id=extract_line("ID Alloggio") or "prop_vicenza_01",
        name=name or "Alloggio",
        city=extract_line("Città"),
        neighborhood=extract_line("Quartiere"),
        address=extract_line("Indirizzo"),
        coords=GeoCoords(lat=lat, lng=lng),
        host_name=extract_line("Host"),
        host_phone=host_phone,
        wifi_ssid=extract_line("Rete Wi-Fi"),
        wifi_password=extract_line("Password Wi-Fi"),
        smart_lock_brand=extract_line("Serratura Elettronica"),
        smart_lock_instructions=extract_line("Istruzioni Serratura"),
        garbage_instructions=extract_line("Raccolta Differenziata"),
        air_conditioning_instructions=extract_line("Aria Condizionata"),
        ztl_info=extract_line("ZTL & Parcheggio"),
        house_rules=rules
    )


# Alias di compatibilità
def parse_property_markdown(content: str) -> Dict[str, Any]:
    return {"metadata": parse_property_markdown_fallback(content)}


async def ingest_property_with_ai(content: str) -> PropertyMetadata:
    """
    Ingestion intelligente dell'alloggio con Gemini AI:
    1. Se la chiave GEMINI_API_KEY è configurata, chiama Gemini 2.5 Flash
       con Structured Outputs (response_schema=PropertyMetadata).
    2. Se la chiave manca o la chiamata fallisce, attiva il Circuit Breaker
       e usa il parser deterministico locale senza mai mandare in crash l'applicazione.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    if api_key:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            prompt = f"""Sei un Property Operations Ingestion Agent esperto.
Analizza il seguente documento dell'alloggio ed estrai tutte le informazioni necessarie per compilare esattamente la struttura richiesta:

{content}
"""
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PropertyMetadata,
                temperature=0.0
            )
            response = client.models.generate_content(
                model="gemini-3.1-flash",
                contents=prompt,
                config=config
            )
            if response.text:
                prop = PropertyMetadata.model_validate_json(response.text)
                print("✨ [AI Ingestion] Alloggio analizzato ed estratto con successo tramite Gemini 2.5 Flash!")
                return prop
        except Exception as e:
            print(f"⚠️ [AI Ingestion] Chiamata a Gemini non riuscita ({e}). Attivazione fallback locale.")

    print("ℹ️ [Ingestion] Utilizzo del parser deterministico locale (offline o API key non impostata).")
    return parse_property_markdown_fallback(content)


async def seed_from_markdown():
    """
    Inizializza il database SQLite al primo avvio:
    1. Legge l'alloggio da property.md tramite Gemini AI (o fallback locale) e lo salva nella tabella 'properties'.
    2. Legge i partner di quartiere, i pacchetti extra e l'ospite demo da seed_data.json.
    """
    await init_db()

    # 1. Caricamento alloggio da property.md
    if os.path.exists(PROPERTY_MD_PATH):
        with open(PROPERTY_MD_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
        
        if content:
            prop: PropertyMetadata = await ingest_property_with_ai(content)

            async with get_db() as db:
                await db.execute("""
                    INSERT OR REPLACE INTO properties (
                        id, name, city, neighborhood, address, lat, lng,
                        host_name, host_phone, wifi_ssid, wifi_password,
                        smart_lock_brand, smart_lock_instructions, garbage_instructions,
                        air_conditioning_instructions, ztl_info, house_rules_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    prop.id, prop.name, prop.city, prop.neighborhood, prop.address,
                    prop.coords.lat, prop.coords.lng, prop.host_name, prop.host_phone,
                    prop.wifi_ssid, prop.wifi_password, prop.smart_lock_brand,
                    prop.smart_lock_instructions, prop.garbage_instructions,
                    prop.air_conditioning_instructions, prop.ztl_info,
                    json.dumps(prop.house_rules.model_dump())
                ))
                await db.commit()

    # 2. Caricamento dei partner e pacchetti da seed_data.json
    if os.path.exists(SEED_DATA_PATH):
        with open(SEED_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        async with get_db() as db:
            # Salva partner locali (ristorante, farmacia, supermercato, ecc.)
            for p in data.get("partners", []):
                await db.execute("""
                    INSERT OR REPLACE INTO partners (
                        id, property_id, name, category, description, price_level,
                        lat, lng, address, contact_phone, opening_hours_json, is_24_7,
                        tags_json, image_url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    p["id"], "prop_vicenza_01", p["name"], p["category"], p["description"],
                    p["price_level"], p["lat"], p["lng"], p["address"], p["contact_phone"],
                    json.dumps(p.get("opening_hours", {})), p.get("is_24_7", 0),
                    json.dumps(p.get("tags", [])), p.get("image_url", "")
                ))

            # Salva pacchetti extra (fiori, spuntino notturno, late checkout)
            for pkg in data.get("upsell_packages", []):
                await db.execute("""
                    INSERT OR REPLACE INTO upsell_packages (
                        id, property_id, title, category, description, price, currency,
                        image_url, badge, items_included_json, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pkg["id"], "prop_vicenza_01", pkg["title"], pkg["category"], pkg["description"],
                    pkg["price"], pkg.get("currency", "EUR"), pkg.get("image_url", ""), pkg.get("badge", ""),
                    json.dumps(pkg.get("items_included", [])), 1
                ))

            # Salva ospite demo di test (Marco Rossi)
            guest = data.get("demo_guest")
            if guest:
                await db.execute("""
                    INSERT OR REPLACE INTO guests (
                        id, property_id, full_name, phone, email,
                        check_in_date, check_out_date,
                        preferences_json, memory_graph_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    guest["id"], guest.get("property_id", "prop_vicenza_01"),
                    guest["full_name"], guest["phone"], guest.get("email", ""),
                    guest["check_in_date"], guest["check_out_date"],
                    json.dumps(guest.get("preferences", {})),
                    json.dumps(guest.get("memory_graph", {}))
                ))

            await db.commit()


# =====================================================================
# 3. FUNZIONI DI LETTURA E SCRITTURA (QUERY ASINCRONE)
# =====================================================================

async def get_property(property_id: str = "prop_vicenza_01") -> Optional[PropertyMetadata]:
    """
    Cerca nel database SQLite l'alloggio con l'ID specificato.
    Ricostruisce e restituisce l'oggetto tipizzato PropertyMetadata di Pydantic.
    Se l'alloggio non esiste nel DB, restituisce None.
    """
    async with get_db() as db:
        async with db.execute("SELECT * FROM properties WHERE id = ?", (property_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            rules_dict = json.loads(d["house_rules_json"]) if d["house_rules_json"] else {}
            return PropertyMetadata(
                id=d["id"], name=d["name"], city=d["city"],
                neighborhood=d["neighborhood"], address=d["address"],
                coords=GeoCoords(lat=d["lat"], lng=d["lng"]),
                host_name=d["host_name"], host_phone=d["host_phone"],
                wifi_ssid=d["wifi_ssid"], wifi_password=d["wifi_password"],
                smart_lock_brand=d["smart_lock_brand"],
                smart_lock_instructions=d["smart_lock_instructions"],
                garbage_instructions=d["garbage_instructions"],
                air_conditioning_instructions=d["air_conditioning_instructions"],
                ztl_info=d["ztl_info"],
                house_rules=HouseRules(**rules_dict)
            )


async def get_partners(property_id: str = "prop_vicenza_01", category: Optional[str] = None) -> List[PartnerService]:
    """
    Interroga la tabella 'partners'. Permette di filtrare opzionalmente per categoria
    (es. 'restaurant', 'pharmacy', 'supermarket', 'florist').
    Restituisce una lista di oggetti PartnerService pronti per essere valutati dall'AI.
    """
    async with get_db() as db:
        query = "SELECT * FROM partners WHERE property_id = ?"
        params = [property_id]
        if category:
            query += " AND category = ?"
            params.append(category)

        partners = []
        async with db.execute(query, tuple(params)) as cursor:
            async for r in cursor:
                d = dict(r)
                partners.append(PartnerService(
                    id=d["id"], name=d["name"], category=d["category"],
                    description=d["description"], price_level=d["price_level"],
                    lat=d["lat"], lng=d["lng"],
                    address=d["address"], contact_phone=d["contact_phone"],
                    opening_hours=json.loads(d["opening_hours_json"]) if d["opening_hours_json"] else {},
                    is_24_7=bool(d["is_24_7"]),
                    tags=json.loads(d["tags_json"]) if d["tags_json"] else [],
                    image_url=d["image_url"]
                ))
        return partners


async def get_guest(guest_id: str) -> Optional[GuestProfile]:
    """
    Recupera il profilo di un ospite tramite il suo ID.
    Decodifica i campi JSON delle preferenze e del memory graph
    restituendo l'oggetto completo GuestProfile.
    """
    async with get_db() as db:
        async with db.execute("SELECT * FROM guests WHERE id = ?", (guest_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            pref_dict = json.loads(d["preferences_json"]) if d["preferences_json"] else {}
            mem_dict = json.loads(d["memory_graph_json"]) if d["memory_graph_json"] else {}
            return GuestProfile(
                id=d["id"], property_id=d["property_id"],
                full_name=d["full_name"], phone=d["phone"], email=d["email"],
                check_in_date=d["check_in_date"], check_out_date=d["check_out_date"],
                preferences=GuestPreferences(**pref_dict),
                memory_graph=GuestMemoryGraph(**mem_dict)
            )


async def update_guest_memory(guest_id: str, memory: GuestMemoryGraph):
    """
    Aggiorna il blocco appunti (Memory Graph) dell'ospite sul database.
    Viene chiamato dall'agente Profiler ogni volta che l'ospite rivela nuove informazioni
    (es. presenza di un neonato, anniversario di matrimonio, stanchezza dal volo).
    """
    async with get_db() as db:
        await db.execute("""
            UPDATE guests SET memory_graph_json = ? WHERE id = ?
        """, (json.dumps(memory.model_dump()), guest_id))
        await db.commit()


async def get_upsell_packages(property_id: str = "prop_vicenza_01") -> List[UpsellPackage]:
    """
    Recupera l'elenco dei servizi extra a pagamento disponibili per l'alloggio
    che sono contrassegnati come attivi (is_active = 1).
    """
    async with get_db() as db:
        packages = []
        async with db.execute("SELECT * FROM upsell_packages WHERE property_id = ? AND is_active = 1", (property_id,)) as cursor:
            async for r in cursor:
                d = dict(r)
                packages.append(UpsellPackage(
                    id=d["id"], property_id=d["property_id"],
                    title=d["title"], category=UpsellCategory(d["category"]),
                    description=d["description"], price=d["price"],
                    currency=d.get("currency", "EUR"), image_url=d.get("image_url"),
                    badge=d["badge"],
                    items_included=json.loads(d["items_included_json"]) if d["items_included_json"] else [],
                    is_active=bool(d["is_active"])
                ))
        return packages


# =====================================================================
# 4. GESTIONE ORDINI E CRONOLOGIA CHAT
# =====================================================================

async def save_order(order: Order) -> bool:
    """
    Salva un ordine d'acquisto nel database SQLite.
    Include la verifica di IDEMPOTENZA (idempotency_key):
    Se l'ospite clicca due volte velocemente sul pulsante 'Acquista',
    la seconda chiamata trova la chiave già esistente, non duplica l'addebito
    e restituisce False. Se l'ordine è nuovo, restituisce True.
    """
    async with get_db() as db:
        async with db.execute("SELECT id FROM orders WHERE idempotency_key = ?", (order.idempotency_key,)) as cursor:
            if await cursor.fetchone():
                return False  # Ordine già esistente: blocco duplicato

        items_json = json.dumps([i.model_dump() for i in order.items])
        await db.execute("""
            INSERT INTO orders (
                id, property_id, guest_id, items_json, total_amount,
                currency, status, idempotency_key, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order.id, order.property_id, order.guest_id, items_json,
            order.total_amount, order.currency, order.status,
            order.idempotency_key, order.created_at
        ))
        await db.commit()
        return True


async def save_chat_message(message: ChatMessage):
    """
    Salva nella tabella 'chat_messages' ogni singolo messaggio scambiato.
    Memorizza sia il testo, sia eventuali componenti grafici Generative UI
    (PlaceCard, Mappa, UpsellCard), sia la catena di pensieri dell'AI (traces).
    """
    async with get_db() as db:
        ui_json = json.dumps(message.generative_ui.model_dump()) if message.generative_ui else None
        traces_json = json.dumps([t.model_dump() for t in message.traces]) if message.traces else None
        await db.execute("""
            INSERT INTO chat_messages (
                id, session_id, role, content, generative_ui_json, traces_json
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            message.id, message.session_id, message.role,
            message.content, ui_json, traces_json
        ))
        await db.commit()


async def get_recent_chat_history(session_id: str, limit: int = 6) -> List[ChatMessage]:
    """
    Recupera gli ultimi N messaggi della sessione (default 6, ovvero 3 turni di botta e risposta).
    Perché solo 6? Perché gli LLM come Gemini consumano token ad ogni turno: inviare 50 messaggi
    rallenterebbe la risposta e costerebbe di più. 6 messaggi bastano per la fluidità, mentre i dettagli
    importanti (allergie, neonati, orari) sono già salvati nel compatto GuestMemoryGraph!
    """
    async with get_db() as db:
        messages = []
        async with db.execute("""
            SELECT * FROM chat_messages
            WHERE session_id = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (session_id, limit)) as cursor:
            rows = await cursor.fetchall()
            for r in reversed(rows):
                d = dict(r)
                ui = GenerativeUIPayload(**json.loads(d["generative_ui_json"])) if d["generative_ui_json"] else None
                traces = [AgentThoughtTrace(**t) for t in json.loads(d["traces_json"])] if d["traces_json"] else []
                messages.append(ChatMessage(
                    id=d["id"], session_id=d["session_id"], role=d["role"],
                    content=d["content"], generative_ui=ui, traces=traces,
                    timestamp=str(d["timestamp"])
                ))
        return messages
