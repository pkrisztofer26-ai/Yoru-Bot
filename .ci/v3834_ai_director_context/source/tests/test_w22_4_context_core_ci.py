from __future__ import annotations

import asyncio
import pytest

from app.ai_director_context import (
    AIDirectorContextPacket, AIDirectorContextValidationError, CONTEXT_DOMAINS,
    business_context_packet, career_context_packet, case_context_packet, housing_context_packet,
    npc_context_packet, tips_context_packet, travel_context_packet, validate_context_packet,
    validate_context_surface,
)
from app.services.ai_director_context import AIDirectorContextPilot


class FakeProvider:
    def __init__(self, response=None, error=None):
        self.response=response or {"title":"Raktáros kontextus","description":"A Modine raktáros munkája Miskolc környezetében látszik."}
        self.error=error; self.calls=0
    async def generate_context(self, packet):
        self.calls += 1
        if self.error: raise self.error
        return dict(self.response)


def run(coro): return asyncio.run(coro)
def p(): return career_context_packet(career_name="Raktáros", employer="Modine", city="Miskolc", position="Tapasztalt munkatárs")


def test_domains(): assert CONTEXT_DOMAINS == {"career","business","travel","housing","npc","tips","case"}

@pytest.mark.parametrize("packet", [
    career_context_packet(career_name="Raktáros", employer="Modine", city="Miskolc", position="Tapasztalt munkatárs"),
    business_context_packet(business_name="Duna Logisztika", category="Logisztika", city="Budapest", operating_model="Kiegyensúlyozott működés"),
    travel_context_packet(current_city="Eger", destination_city="Miskolc", travel_mode="Vonat"),
    housing_context_packet(home_city="Debrecen", housing_tier="Saját lakás", location_state="otthonvárosban"),
    npc_context_packet(npc_name="Kata", npc_role="Munkaközvetítő", relationship_state="beváltásra váró szívesség"),
    tips_context_packet(topic="Alvilági nyom", source_label="korábbi alvilági ügy", certainty="bizonytalan jelzés"),
    case_context_packet(case_type="bűnügyi", case_status="nyitott", subject="Alvilági nyom"),
])
def test_builders(packet): assert validate_context_packet(packet) is packet

@pytest.mark.parametrize("key", ["reward","amount","chance","success","wallet","inventory","user_id","case_id"])
def test_sensitive_key_rejected(key):
    q=p()
    bad=AIDirectorContextPacket(q.context_key,q.domain,q.semantic_slot,q.fallback_title,q.fallback_description,{key:"x"})
    with pytest.raises(AIDirectorContextValidationError): validate_context_packet(bad)

@pytest.mark.parametrize("desc", [
    "A Modine raktáros munkája Miskolc mellett 5000 Ft jutalmat ad.",
    "A Modine raktáros munkája Miskolc mellett 90% eséllyel sikerül.",
])
def test_mechanical_surface_rejected(desc):
    with pytest.raises(AIDirectorContextValidationError): validate_context_surface(p(), {"title":"Raktáros", "description":desc})


@pytest.mark.parametrize("desc", [
    "A Modine raktáros munkája Miskolc mellett canonical helyzetként látszik.",
    "A Modine raktáros munkája Miskolc mellett mechanikai állapotként látszik.",
])
def test_internal_jargon_surface_rejected(desc):
    with pytest.raises(AIDirectorContextValidationError): validate_context_surface(p(), {"title":"Raktáros", "description":desc})


def test_fallbacks_are_free_of_internal_jargon():
    packets=[
        p(),
        business_context_packet(business_name="Duna Logisztika", category="Logisztika", city="Budapest", operating_model="Kiegyensúlyozott működés"),
        travel_context_packet(current_city="Eger", destination_city="Miskolc", travel_mode="Vonat"),
        housing_context_packet(home_city="Debrecen", housing_tier="Saját lakás", location_state="otthonvárosban"),
        npc_context_packet(npc_name="Kata", npc_role="Munkaközvetítő", relationship_state="beváltásra váró szívesség"),
        tips_context_packet(topic="Alvilági nyom", source_label="korábbi alvilági ügy", certainty="bizonytalan jelzés"),
        case_context_packet(case_type="bűnügyi", case_status="nyitott", subject="Alvilági nyom"),
    ]
    forbidden=("canonical","authority","mechanikai","validator","fallback","provider","contract")
    for packet in packets:
        text=f"{packet.fallback_title} {packet.fallback_description}".casefold()
        assert not any(word in text for word in forbidden)


def test_missing_anchor_rejected():
    with pytest.raises(AIDirectorContextValidationError): validate_context_surface(p(), {"title":"Munka", "description":"Egy csapatnál nyugodt a helyzet."})


def test_default_off_and_wrong_guild():
    provider=FakeProvider(); pilot=AIDirectorContextPilot(provider=provider, enabled=False, test_guild_id=10)
    assert run(pilot.surface(10,1,p())) is None
    pilot=AIDirectorContextPilot(provider=provider, enabled=True, test_guild_id=10)
    assert run(pilot.surface(11,1,p())) is None and provider.calls == 0


def test_valid_provider_and_cache():
    provider=FakeProvider(); pilot=AIDirectorContextPilot(provider=provider, enabled=True, test_guild_id=10)
    a=run(pilot.surface(10,1,p())); b=run(pilot.surface(10,2,p()))
    assert a and a.source == "ai_context" and b and b.source == "ai_context_cache" and provider.calls == 1


def test_provider_error_fallback():
    pilot=AIDirectorContextPilot(provider=FakeProvider(error=RuntimeError("down")), enabled=True, test_guild_id=10)
    result=run(pilot.surface(10,1,p()))
    assert result and result.source == "deterministic_context_fallback"


def test_invalid_provider_fallback():
    provider=FakeProvider({"title":"Raktáros", "description":"A Modine raktáros munkája Miskolc mellett 5000 Ft jutalmat ad."})
    pilot=AIDirectorContextPilot(provider=provider, enabled=True, test_guild_id=10)
    result=run(pilot.surface(10,1,p()))
    assert result and result.source == "deterministic_context_fallback"
