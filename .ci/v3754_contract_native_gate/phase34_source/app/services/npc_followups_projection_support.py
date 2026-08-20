from __future__ import annotations
__all__ = ['ConsequenceMemoryService', 'FIRST_CONTACT_FOLLOWUP_HOURS', 'FOLLOWUPS', 'FavorRedemptionResult', 'GameplayNotificationContract', 'MemoryAdapterService', 'NPCFollowupDefinition', 'NPCRelationshipSummary', 'Opportunity', 'RESOLVED_RELATIONSHIP_AGE_HOURS', 'RelationshipState', 'TensionResolutionResult', '_fingerprint', '_parse_iso', 'dataclass', 'datetime', 'hashlib', 'log', 'logging', 'npc_config', 'npc_favor_config', 'timedelta', 'timezone']
'Relationship-driven NPC follow-ups for Phase 3.\n\nThis service may create social/private opportunity candidates and derived\nnotifications from already-settled relationship state. It never owns economy,\ninventory, career, vehicle or world settlement.\n'
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import logging
from app import npc_config
from app import npc_favor_config
from app.services.memory import ConsequenceMemoryService, RelationshipState
from app.services.memory_adapters import MemoryAdapterService
from app.services.notification_contracts import GameplayNotificationContract
from app.services.opportunities import Opportunity
log = logging.getLogger('vaultbot.npc_followups')
FIRST_CONTACT_FOLLOWUP_HOURS = 72
RESOLVED_RELATIONSHIP_AGE_HOURS = 72

def _parse_iso(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def _fingerprint(*parts: object, length: int=14) -> str:
    raw = '|'.join((str(part) for part in parts))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:length]

@dataclass(frozen=True, slots=True)
class NPCFollowupDefinition:
    npc_key: str
    destination_action: str
    destination_label: str
    followup_title: str
    followup_body: str
    favor_title: str
    favor_body: str
    destination_hint: str
FOLLOWUPS: dict[str, NPCFollowupDefinition] = {'kata_job_agent': NPCFollowupDefinition('kata_job_agent', 'career', 'Állások', 'Kata újra jelentkezett', 'Kata szólt, hogy érdemes ránézned az aktuális állásokra.', 'Kata visszaadná a segítséget', 'Korábban segítettél Katának. Most megkérheted, hogy nézzen körül neked az állások között.', 'Most rögtön megnézheted az aktuális állásokat.'), 'misi_car_dealer': NPCFollowupDefinition('misi_car_dealer', 'vehicles', 'Járműpiac', 'Misi újra keresett', 'Misi jelezte, hogy érdemes ránézned az aktuális autópiacra.', 'Misi visszaadná a segítséget', 'Korábban segítettél Misinek. Most megkérheted, hogy segítsen a következő kereskedéses autóvásárlásnál.', 'A következő kereskedéses autóvásárlásnál Misi közbenjárása automatikusan érvényesül.'), 'jani_mechanic': NPCFollowupDefinition('jani_mechanic', 'vehicles', 'Járműveim', 'Jani visszajelzett', 'Jani ismét jelentkezett; érdemes ránézned a járműveidre és az aktuális lehetőségekre.', 'Jani visszaadná a segítséget', 'Korábban segítettél Janinak. Most megkérheted, hogy a következő fizetős szerviznél segítsen.', 'A következő fizetős szerviznél Jani kedvezménye automatikusan érvényesül.'), 'lilla_dispatcher': NPCFollowupDefinition('lilla_dispatcher', 'career', 'Állások', 'Lilla újra keresett', 'Lilla jelezte, hogy érdemes ránézned az aktuális munkalehetőségekre.', 'Lilla visszaadná a segítséget', 'Korábban segítettél Lillának. Most megkérheted, hogy nézzen körül neked a munkalehetőségek között.', 'Most rögtön megnézheted az aktuális állásokat.'), 'bence_business_contact': NPCFollowupDefinition('bence_business_contact', 'business', 'Vállalkozások', 'Bence újra keresett', 'Bence szólt, hogy érdemes ránézned a vállalkozási lehetőségeidre.', 'Bence visszaadná a segítséget', 'Korábban segítettél Bencének. Most megkérheted, hogy segítsen a vállalkozói engedély ügyintézésében.', 'Ha még nincs engedélyed, a következő vásárlásnál Bence közbenjárása automatikusan érvényesül.'), 'zoli_black_market_broker': NPCFollowupDefinition('zoli_black_market_broker', 'blackmarket', 'Feketepiac', 'Zoli jelentkezett', 'Zoli jelezte, hogy érdemes figyelned a Feketepiac aktuális helyzetét.', 'Zoli tartozik egy szívességgel', 'Korábban segítettél Zolinak. Most felhívhatod, hogy jelezzen, ha érdemes ránézni a Feketepiacra.', 'Megnézheted, hogy a világhelyzet alapján jelenleg elérhető-e a Feketepiac.'), 'dora_legal_contact': NPCFollowupDefinition('dora_legal_contact', 'profile', 'Életpanel', 'Dóra visszajelzett', 'Dóra jelezte, hogy nem felejtette el a korábbi ügyeteket.', 'Dóra tartozik egy szívességgel', 'Korábban segítettél Dórának. Most kérhetsz tőle egy későbbi ügyhöz kapcsolódó utánajárást.', 'A szívesség megmarad, amíg egy megfelelő jogi vagy hatósági helyzetben fel nem használható.'), 'reka_property_agent': NPCFollowupDefinition('reka_property_agent', 'housing', 'Otthon', 'Réka újra keresett', 'Réka szólt, hogy érdemes ránézned az aktuális lakhatási lehetőségeidre.', 'Réka visszaadná a segítséget', 'Korábban segítettél Rékának. Most megkérheted, hogy nézze át veled a lakhatási lehetőségeket.', 'Most rögtön megnézheted az otthonodhoz kapcsolódó lehetőségeket.'), 'akos_training_mentor': NPCFollowupDefinition('akos_training_mentor', 'training', 'Képzések', 'Ákos újra jelentkezett', 'Ákos szólt, hogy érdemes ránézned az aktuális képzéseidre.', 'Ákos visszaadná a segítséget', 'Korábban segítettél Ákosnak. Most megkérheted, hogy nézze át veled a következő képzési lépést.', 'Most rögtön megnézheted az elérhető képzéseket.'), 'eszter_merchant': NPCFollowupDefinition('eszter_merchant', 'business', 'Vállalkozások', 'Eszter újra keresett', 'Eszter jelezte, hogy érdemes ránézned az üzleti lehetőségeidre.', 'Eszter visszaadná a segítséget', 'Korábban segítettél Eszternek. Most kérhetsz tőle piaci eligazítást.', 'Most rögtön megnézheted a vállalkozási lehetőségeidet.'), 'marci_city_contact': NPCFollowupDefinition('marci_city_contact', 'travel', 'Utazás', 'Marci jelentkezett', 'Marci szólt, hogy érdemes körülnézned, mi történik más városokban.', 'Marci visszaadná a segítséget', 'Korábban segítettél Marcinak. Most kérhetsz tőle egy kis helyi eligazítást.', 'Most rögtön megnézheted az utazási lehetőségeidet.'), 'tamas_organization_contact': NPCFollowupDefinition('tamas_organization_contact', 'organization', 'Szervezet', 'Tamás újra keresett', 'Tamás jelezte, hogy érdemes ránézned a szervezeti ügyeidre.', 'Tamás visszaadná a segítséget', 'Korábban segítettél Tamásnak. Most kérhetsz tőle egy szervezeti ügyhöz kapcsolódó utánajárást.', 'Most rögtön megnézheted a szervezeti lehetőségeidet.')}

@dataclass(frozen=True, slots=True)
class FavorRedemptionResult:
    npc_key: str
    npc_name: str
    destination_action: str
    destination_label: str
    remaining_favors: int
    memory_key: str
    newly_consumed: bool
    effect_key: str | None = None
    effect_label: str | None = None
    effect_description: str | None = None

@dataclass(frozen=True, slots=True)
class NPCRelationshipSummary:
    npc_key: str
    npc_name: str
    emoji: str
    role_label: str
    status_label: str
    note: str

@dataclass(frozen=True, slots=True)
class TensionResolutionResult:
    npc_key: str
    npc_name: str
    rival_state: str
    memory_key: str
