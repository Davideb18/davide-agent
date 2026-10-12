from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


# =====================================================================
# ALLOGGIO: Modelli per la struttura della casa e dei partner
# =====================================================================

class GeoCoords(BaseModel):
    # Coordinate geografiche pure
    lat: float
    lng: float


class HouseRules(BaseModel):
    # Regole della casa: orari, limiti e istruzioni di emergenza
    quiet_hours_start: str
    quiet_hours_end: str
    max_guests: int
    parties_allowed: bool = False
    pets_allowed: bool = False
    smoking_allowed: bool = False
    
    # Posizioni fisiche per emergenze (lette dal file property.md)
    # Non sono obbligatorie averle nel file property.md
    emergency_water_valve_location: Optional[str] = None
    emergency_breaker_box_location: Optional[str] = None

    # Crea un dizionario nuovo per ogni alloggio invece di averne uno solo per tutti
    emergency_contacts: Dict[str, str] = Field(default_factory=dict)


class PartnerService(BaseModel):
    # Negozi o partner di quartiere (ristorante, farmacia, supermercato, ecc.)
    id: str
    name: str
    category: str  # 'restaurant', 'supermarket', 'pharmacy', 'florist', 'pastry', 'locker', 'parking'
    description: str
    price_level: str  # '€'
    lat: float
    lng: float
    address: str
    contact_phone: Optional[str] = None
    opening_hours: Dict[str, str] = Field(default_factory=dict)
    is_24_7: bool = False
    tags: List[str] = Field(default_factory=list)
    image_url: Optional[str] = None


class PropertyMetadata(BaseModel):
    # L'oggetto completo della casa: unisce coordinate, regole e istruzioni
    id: str
    name: str
    city: str
    neighborhood: str
    address: str
    coords: GeoCoords
    host_name: str
    host_phone: str
    wifi_ssid: str
    wifi_password: str
    smart_lock_brand: str
    smart_lock_instructions: str
    garbage_instructions: str
    air_conditioning_instructions: str
    ztl_info: str
    house_rules: HouseRules


# =====================================================================
# OSPITE: Preferenze e Grafo di Memoria Permanente
# =====================================================================

class GuestPreferences(BaseModel):
    # Preferenze soggettive dell'ospite
    language: str = "it"
    dietary: List[str] = Field(default_factory=list)  # es. ["celiaca", "vegetariano", "pesce"]
    vibe_preference: List[str] = Field(default_factory=list)  # es. ["romantico", "intimo", "storico"]
    budget_tier: str = "moderate"


class GuestMemoryGraph(BaseModel):
    # Grafo di memoria persistente: raccoglie i dettagli chiave man mano che l'ospite parla
    occasion: Optional[str] = None  # es. 'birthday', 'anniversary', 'work'
    occasion_details: Optional[str] = None
    has_infant: bool = False
    has_children: bool = False
    party_size: int = 2
    arrival_time: Optional[str] = None  # es. '21:30'
    travel_fatigue: bool = False
    work_needs: bool = False
    likes: List[str] = Field(default_factory=list)
    active_concierge_notes: List[str] = Field(default_factory=list)


class GuestProfile(BaseModel):
    # Profilo anagrafico dell'ospite associato all'alloggio
    id: str
    property_id: str
    full_name: str
    phone: str
    email: Optional[str] = None
    check_in_date: str
    check_out_date: str

    # Crea una scheda preferenze e un grafo di memoria nuovi e indipendenti per ogni ospite
    preferences: GuestPreferences = Field(default_factory=GuestPreferences)
    memory_graph: GuestMemoryGraph = Field(default_factory=GuestMemoryGraph)


# =====================================================================
# COMMERCE: Servizi a Pagamento (Upsell) e Ordini
# =====================================================================

class UpsellCategory(str, Enum):
    WELCOME_PACK = "welcome_pack"
    LATE_CHECKOUT = "late_checkout"
    LUGGAGE_STORAGE = "luggage_storage"
    FLOWERS_GIFTS = "flowers_gifts"
    MIDNIGHT_PANTRY = "midnight_pantry"


class UpsellPackage(BaseModel):
    # Un pacchetto acquistabile offerto dall'host
    id: str
    property_id: str
    title: str
    category: UpsellCategory
    description: str
    price: float
    currency: str = "EUR"
    image_url: Optional[str] = None
    items_included: List[str] = Field(default_factory=list)
    badge: Optional[str] = None  # es. "Consigliato per Coppie"
    is_active: bool = True


class OrderItem(BaseModel):
    package_id: str
    package_title: str
    price: float
    quantity: int = 1


class Order(BaseModel):
    # Un ordine confermato dall'ospite
    id: str
    property_id: str
    guest_id: str
    items: List[OrderItem]
    total_amount: float
    currency: str = "EUR"
    status: str = "confirmed"
    idempotency_key: str  # Chiave univoca anti-duplicati
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# =====================================================================
# GENERATIVE UI: Gli elementi grafici che l'agente manda a schermo
# =====================================================================

class PlaceCard(BaseModel):
    # Scheda visiva di un locale con foto, voto e distanza a piedi calcolata
    id: str
    name: str
    category: str
    rating: float
    review_count: int
    address: str
    distance_meters: int
    walk_time_minutes: int
    opening_hours_today: str
    is_open_now: bool
    price_level: str
    image_url: Optional[str] = None
    why_recommended: str
    google_maps_url: str
    phone: Optional[str] = None


class InteractiveMapMarker(BaseModel):
    # Un punto da mostrare sulla mappa interattiva
    id: str
    name: str
    lat: float
    lng: float
    marker_type: str  # 'apartment', 'restaurant', 'supermarket', 'pharmacy', 'emergency'
    label: str


class InteractiveMap(BaseModel):
    # Configurazione della mappa Leaflet
    center_lat: float
    center_lng: float
    zoom: int = 15
    markers: List[InteractiveMapMarker] = Field(default_factory=list)


class UpsellCard(BaseModel):
    # Box per acquistare un servizio con un click
    package_id: str
    title: str
    price: float
    currency: str = "EUR"
    badge: Optional[str] = None
    description: str
    image_url: Optional[str] = None
    button_label: str = "Aggiungi al Soggiorno"


class EmergencyAlert(BaseModel):
    # Banner rosso per emergenze (tubo rotto, serratura bloccata)
    severity: str  # 'CRITICAL_P0', 'HIGH', 'INFO'
    title: str
    instructions: str
    emergency_contacts: Dict[str, str] = Field(default_factory=dict)
    host_notified: bool = True


class ActionChip(BaseModel):
    # Bottoni con suggerimenti veloci per la prossima domanda
    label: str
    prompt: str


class GenerativeUIPayload(BaseModel):
    # Il pacchetto completo di componenti grafici da visualizzare
    place_cards: List[PlaceCard] = Field(default_factory=list)
    map_data: Optional[InteractiveMap] = None
    upsell_card: Optional[UpsellCard] = None
    emergency_alert: Optional[EmergencyAlert] = None
    action_chips: List[ActionChip] = Field(default_factory=list)


# =====================================================================
# OBSERVABILITY & CHAT: Pensieri dell'Agente e Messaggi
# =====================================================================

class AgentThoughtTrace(BaseModel):
    # Traccia dei pensieri dell'agente visibile nella Console dell'Host
    step_id: str
    agent_name: str
    thought: str
    tools_called: List[Dict[str, Any]] = Field(default_factory=list)
    decision: str
    latency_ms: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ChatMessage(BaseModel):
    # Messaggio singolo tra ospite e concierge
    id: str
    session_id: str
    role: str  # 'guest' o 'agent'
    content: str
    generative_ui: Optional[GenerativeUIPayload] = None
    traces: List[AgentThoughtTrace] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
