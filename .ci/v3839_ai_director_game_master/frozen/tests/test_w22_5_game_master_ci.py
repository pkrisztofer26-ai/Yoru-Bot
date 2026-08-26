from __future__ import annotations
import asyncio
from pathlib import Path
import pytest
from app.ai_director_game_master import (
    AIDirectorGameMasterPacket, AIDirectorGameMasterValidationError,
    GAME_MASTER_CONTRACT_VERSION, GAME_MASTER_FAMILIES, GAME_MASTER_RUNTIME_ENABLED_DEFAULT,
    big_job_packet, npc_story_packet, consequence_recall_packet, chapter_packet,
    world_story_packet, legendary_event_packet, fallback_game_master_surface,
    validate_game_master_packet, validate_game_master_surface,
)
from app.providers.ai_director_game_master_groq import GroqAIDirectorGameMasterProvider
from app.services.ai_director_game_master import AIDirectorGameMaster

def big():
    return big_job_packet(target_name='Belvárosi trezor', phase_label='menekülés', approach_label='csendes', route_label='hátsó útvonal', host_resolution='részsiker', consequence_note='a csapat szétszóródva jutott ki')

def packets():
    return [
        big(),
        npc_story_packet(npc_name='Zoli', npc_role='kapcsolattartó', relationship_band='óvatos', recalled_event='korábban betartottad a megállapodást', current_story_state='újra szóba áll veled'),
        consequence_recall_packet(subject_label='a régi üzlettárs', memory_category='agreement', remembered_event='a megállapodást végül teljesítetted', current_relevance='ismét felmerült a közös múlt'),
        chapter_packet(chapter_title='Repedések a városban', stage_title='Lezárás', world_story_title='Feszült egyensúly', community_note='a közösségi döntések nyomot hagytak', host_ending='Törékeny egyensúly'),
        world_story_packet(national_title='Országos bizonytalanság', story_title='Feszült egyensúly', beat_title='Új törésvonal', city_label='Budapest', world_note='a helyi szereplők kivárnak'),
        legendary_event_packet(event_name='Fekete Korona', access_context='ritka meghívás után indult', phase_label='végjáték', host_resolution='részsiker', legacy_note='az ügy neve megmaradt a városi történetekben'),
    ]

def test_identity():
    assert GAME_MASTER_CONTRACT_VERSION == 'tier3-game-master-surface-v3'
    assert GAME_MASTER_RUNTIME_ENABLED_DEFAULT is False
    assert GAME_MASTER_FAMILIES == {'big_job','npc_story','consequence_recall','chapter','world_story','legendary_event'}

@pytest.mark.parametrize('packet', packets())
def test_family_packets_validate(packet):
    assert validate_game_master_packet(packet) is packet

@pytest.mark.parametrize('key', ['reward','payout','amount','wallet','xp','inventory','chance','probability','success','outcome','choice','branch','user_id','run_id'])
def test_authority_fact_keys_rejected(key):
    p = big()
    bad = AIDirectorGameMasterPacket(p.story_key,p.family,p.semantic_slot,p.fallback_title,p.fallback_description,{key:'x'})
    with pytest.raises(AIDirectorGameMasterValidationError): validate_game_master_packet(bad)

@pytest.mark.parametrize('description', [
    'A Belvárosi trezor részsiker lezárást kapott.',
    'A Repedések a városban fejezet a Törékeny egyensúly lezárás felé közeledik.',
    'A Fekete Korona neve örökre megmaradt a legendákban.',
    'A hátsó útvonal útvonal maradt.',
    'A ipari útvonal került elő.',
    'A Belvárosi trezor híre a környéknek gyorsan eljutott.',
    'A Feszült egyensúly történetszál Új törésvonal pontja került előtérbe.',
])
def test_human_quality_regressions_rejected(description):
    with pytest.raises(AIDirectorGameMasterValidationError):
        validate_game_master_surface(big(), {'title':'A Belvárosi trezor','description':description})

def test_npc_causality_rejected():
    p = npc_story_packet(npc_name='Mira',npc_role='informátor',relationship_band='bizalmatlan',recalled_event='egy régi ügyben cserben hagytad',current_story_state='távolságot tart')
    with pytest.raises(AIDirectorGameMasterValidationError):
        validate_game_master_surface(p, {'title':'Mira emlékszik','description':'Mira mivel emlékszik arra, hogy egy régi ügyben cserben hagytad, bizalmatlan maradt.'})

def test_world_story_beat_phrase_rejected():
    p = world_story_packet(national_title='Lassú rendeződés',story_title='Új kapcsolatok',beat_title='Csendes közeledés',city_label='Szeged',world_note='a helyi hangulat óvatosan enyhül')
    with pytest.raises(AIDirectorGameMasterValidationError):
        validate_game_master_surface(p, {'title':'Új kapcsolatok','description':'A Csendes közeledés pontja kerül előtérbe Szeged körül; a helyi hangulat óvatosan enyhül.'})

def test_fallbacks_validate_and_are_natural():
    for p in packets():
        f = fallback_game_master_surface(p)
        validate_game_master_surface(p, {'title':f.title,'description':f.description})
        assert 'lezárást kapott' not in f.description.casefold()
        assert 'útvonal útvonal' not in f.description.casefold()

def test_prompt_denies_authority_and_expansion():
    p = GroqAIDirectorGameMasterProvider.system_prompt().casefold()
    for term in ('nem dönthetsz','branch','jutalom','hiszen','környék','legend'):
        assert term in p

def test_schema_strict():
    s = GroqAIDirectorGameMasterProvider.output_schema()
    assert s['additionalProperties'] is False and set(s['properties']) == {'title','description'}

def test_review_harness_effective_gate():
    t = Path('scripts/ai_director_tier3_game_master_review.py').read_text(encoding='utf-8')
    assert 'EFFECTIVE_VALIDATED' in t
    assert 'effective_validated == len(rows)' in t
    assert 'player_facing_ai' in t and 'gameplay_authority' in t
