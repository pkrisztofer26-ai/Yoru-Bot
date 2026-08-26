from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from app.ai_director_game_master import (
    GAME_MASTER_CONTRACT_VERSION,
    GAME_MASTER_RUNTIME_ENABLED_DEFAULT,
    big_job_packet,
    chapter_packet,
    consequence_recall_packet,
    legendary_event_packet,
    npc_story_packet,
    world_story_packet,
)
from app.ai_director_game_master_integration import GAME_MASTER_FIELD_NAME, add_game_master_field
from app.services.ai_director_game_master import AIDirectorGameMaster

ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "proof"


def run(coro):
    return asyncio.run(coro)


class FakeProvider:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {"title": "A Belvárosi trezor", "description": "A Belvárosi trezor ügy lezárása: Siker."}
        self.error = error
        self.calls = 0

    async def generate_game_master(self, packet):
        self.calls += 1
        if self.error:
            raise self.error
        return dict(self.payload)


class FakeEmbed:
    def __init__(self): self.fields=[]
    def add_field(self, *, name, value, inline): self.fields.append((name,value,inline))


def big():
    return big_job_packet(
        target_name="Belvárosi trezor", phase_label="Lezárt ügy", approach_label="Csendes út",
        route_label="Eredeti útvonal", host_resolution="Siker",
        consequence_note="A csapat az eredeti útvonalon maradt.",
    )


def test_contract_and_runtime_defaults():
    assert GAME_MASTER_CONTRACT_VERSION == "tier3-game-master-surface-v6"
    assert GAME_MASTER_RUNTIME_ENABLED_DEFAULT is False


def test_wrong_guild_never_calls_provider():
    p=FakeProvider(); gm=AIDirectorGameMaster(provider=p,enabled=True,test_guild_id=10)
    assert run(gm.surface(11,big())) is None
    assert p.calls == 0


def test_no_provider_is_deterministic_fallback():
    gm=AIDirectorGameMaster(provider=None,enabled=True,test_guild_id=10)
    assert run(gm.surface(10,big())).source == "deterministic_scenario_v2_fallback"


def test_provider_error_fails_closed():
    gm=AIDirectorGameMaster(provider=FakeProvider(error=RuntimeError("offline")),enabled=True,test_guild_id=10)
    assert run(gm.surface(10,big())).source == "deterministic_scenario_v2_fallback"


def test_provider_success_is_cached():
    p=FakeProvider(); gm=AIDirectorGameMaster(provider=p,enabled=True,test_guild_id=10,cache_ttl_seconds=300)
    assert run(gm.surface(10,big())).source == "ai_game_master"
    assert run(gm.surface(10,big())).source == "ai_game_master_cache"
    assert p.calls == 1


def test_field_helper_adds_only_presentation_field():
    bot=SimpleNamespace(ai_director_game_master=AIDirectorGameMaster(provider=None,enabled=True,test_guild_id=10))
    e=FakeEmbed()
    assert run(add_game_master_field(bot,e,10,big)) is True
    assert e.fields[0][0] == GAME_MASTER_FIELD_NAME
    assert e.fields[0][2] is False


def test_packet_factory_error_never_breaks_host_panel():
    bot=SimpleNamespace(ai_director_game_master=AIDirectorGameMaster(provider=None,enabled=True,test_guild_id=10))
    e=FakeEmbed()
    def bad():
        return big_job_packet(target_name="Trezor 2",phase_label="Lezárt ügy",approach_label="Csendes út",route_label="Eredeti útvonal",host_resolution="Siker",consequence_note="Lezárt ügy.")
    assert run(add_game_master_field(bot,e,10,bad)) is False
    assert e.fields == []


def test_all_six_families_build():
    packets=[
        big(),
        npc_story_packet(npc_name="Mira",npc_role="informátor",relationship_band="Jó kapcsolat",recalled_event="Korábban információt adott.",current_story_state="Jó kapcsolat"),
        consequence_recall_packet(subject_label="Korábbi ügy",memory_category="Élettörténet",remembered_event="A korábbi ügy lezárult.",current_relevance="A feljegyzés megmaradt az élettörténetben."),
        chapter_packet(chapter_title="Törésvonalak",stage_title="Utórezgések",world_story_title="Csendes közeledés",community_note="A közösségi projekt lezárult."),
        world_story_packet(national_title="Feszült országos helyzet",story_title="Csendes közeledés",beat_title="Új kapcsolatok",city_label="Budapest",world_note="A történetszál új ponthoz ért."),
        legendary_event_packet(event_name="Éjféli Konvoj",access_context="Legendary meghívásból megnyílt ügy",phase_label="Lezárt művelet",host_resolution="Siker",legacy_note="A Legendary művelet lezárt ügyként szerepel."),
    ]
    assert {p.family for p in packets} == {"big_job","npc_story","consequence_recall","chapter","world_story","legendary_event"}


def test_manifest_declares_v38313_and_eight_files():
    data=json.loads((PROOF/'callsite_contract.json').read_text(encoding='utf-8'))
    assert data['version']=='3.83.13' and data['work_item']=='W22.6' and data['base_version']=='3.83.12'
    assert len(data['files']) == 8
    assert all(all(v for v in row.get('markers',{}).values()) for row in data['files'].values())


def test_patch_is_exact_and_contains_six_wiring_families():
    patch=(PROOF/'w226.patch').read_bytes()
    assert hashlib.sha256(patch).hexdigest() == 'c91b050eade554954633dd5013fde9b5bbb1833001871bf47c841b87226c8be4'
    text=patch.decode('utf-8')
    for marker in ('big_job_packet','legendary_event_packet','world_story_packet','chapter_packet','npc_story_packet','consequence_recall_packet'):
        assert marker in text


def test_patch_has_explicit_test_guild_flag_and_provider_gate():
    text=(PROOF/'w226.patch').read_text(encoding='utf-8')
    assert 'YORU_AI_DIRECTOR_GAME_MASTER_PILOT_ENABLED' in text
    assert 'if self.settings.ai_director_game_master_pilot_enabled:' in text
    assert 'GroqAIDirectorGameMasterProvider' in text


def test_patch_does_not_open_storyteller_pacing_or_generic_ai_runtime():
    text=(PROOF/'w226.patch').read_text(encoding='utf-8').casefold()
    assert 'storyteller_pacing' not in text
    assert 'runtime_enabled=true' not in text


def test_integration_module_has_no_authoritative_service_imports():
    text=Path('app/ai_director_game_master_integration.py').read_text(encoding='utf-8')
    for forbidden in ('services.economy','services.heist','services.world','services.chapters','services.memory','services.assets','services.contracts','services.police'):
        assert forbidden not in text
