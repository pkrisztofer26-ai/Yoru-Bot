from __future__ import annotations
import asyncio
import pytest
from app.ai_director_game_master import *
from app.services.ai_director_game_master import AIDirectorGameMaster
from app.providers.ai_director_game_master_groq import GroqAIDirectorGameMasterProvider


def run(c): return asyncio.run(c)
def p(): return big_job_packet(target_name='Belvárosi trezor',phase_label='menekülés',approach_label='csendes',route_label='hátsó útvonal',host_resolution='részsiker',consequence_note='a csapat szétszóródva jutott ki')
class Fake:
    def __init__(self, raw=None, error=None): self.raw=raw or {'title':'A Belvárosi trezor visszhangja','description':'A Belvárosi trezor akció részsikerrel zárult, és a csapat szétszóródva jutott ki.'}; self.error=error; self.calls=0
    async def generate_game_master(self, packet):
        self.calls += 1
        if self.error: raise self.error
        return self.raw

def test_identity(): assert GAME_MASTER_CONTRACT_VERSION=='tier3-game-master-surface-v1' and GAME_MASTER_RUNTIME_ENABLED_DEFAULT is False
def test_families(): assert GAME_MASTER_FAMILIES=={'big_job','npc_story','consequence_recall','chapter','world_story','legendary_event'}
@pytest.mark.parametrize('packet',[
 p(),
 npc_story_packet(npc_name='Zoli',npc_role='kapcsolattartó',relationship_band='óvatos',recalled_event='betartottad a megállapodást',current_story_state='újra szóba áll veled'),
 consequence_recall_packet(subject_label='a riválisod',memory_category='rival',remembered_event='a konfliktus lezáratlan maradt',current_relevance='ugyanabban a körben mozogtok'),
 chapter_packet(chapter_title='Repedések a városban',stage_title='Lezárás',world_story_title='Feszült egyensúly',community_note='a közösségi döntések nyomot hagytak',host_ending='Törékeny egyensúly'),
 world_story_packet(national_title='Országos bizonytalanság',story_title='Feszült egyensúly',beat_title='Új törésvonal',city_label='Budapest',world_note='a helyi szereplők kivárnak'),
 legendary_event_packet(event_name='Fekete Korona',access_context='ritka meghívás után indult',phase_label='végjáték',host_resolution='részsiker',legacy_note='az ügy neve megmaradt a városi történetekben'),
])
def test_builders(packet): assert validate_game_master_packet(packet) is packet
@pytest.mark.parametrize('key',['reward','payout','score','weights','trust_score','chance','success','outcome','choice','branch','user_id','run_id'])
def test_authority_facts_rejected(key):
    q=p(); bad=AIDirectorGameMasterPacket(q.story_key,q.family,q.semantic_slot,q.fallback_title,q.fallback_description,{key:'x'})
    with pytest.raises(AIDirectorGameMasterValidationError): validate_game_master_packet(bad)
def test_valid_surface(): assert validate_game_master_surface(p(),{'title':'A Belvárosi trezor','description':'A Belvárosi trezor akció részsikerrel zárult.'})[0]
def test_extra_field_rejected():
    with pytest.raises(AIDirectorGameMasterValidationError): validate_game_master_surface(p(),{'title':'A Belvárosi trezor','description':'A Belvárosi trezor akció részsikerrel zárult.','branch':'x'})
def test_mechanical_output_rejected():
    with pytest.raises(AIDirectorGameMasterValidationError): validate_game_master_surface(p(),{'title':'A Belvárosi trezor','description':'A Belvárosi trezor után biztosan nyersz jutalmat.'})
def test_jargon_output_rejected():
    with pytest.raises(AIDirectorGameMasterValidationError): validate_game_master_surface(p(),{'title':'A Belvárosi trezor','description':'A Belvárosi trezor canonical fallback szerint részsiker.'})
def test_fallback(): assert fallback_game_master_surface(p()).source=='deterministic_scenario_v2_fallback'
def test_default_off_wrong_guild():
    f=Fake(); gm=AIDirectorGameMaster(provider=f,enabled=False,test_guild_id=10); assert run(gm.surface(10,p())) is None
    gm=AIDirectorGameMaster(provider=f,enabled=True,test_guild_id=10); assert run(gm.surface(11,p())) is None and f.calls==0
def test_provider_error_fallback(): assert run(AIDirectorGameMaster(provider=Fake(error=RuntimeError('x')),enabled=True,test_guild_id=10).surface(10,p())).source=='deterministic_scenario_v2_fallback'
def test_provider_valid(): assert run(AIDirectorGameMaster(provider=Fake(),enabled=True,test_guild_id=10).surface(10,p())).source=='ai_game_master'
def test_prompt_and_schema():
    assert 'nem dönthetsz' in GroqAIDirectorGameMasterProvider.system_prompt().casefold()
    assert 'host_facts' in GroqAIDirectorGameMasterProvider.user_prompt(p()).casefold()
    s=GroqAIDirectorGameMasterProvider.output_schema(); assert s['additionalProperties'] is False and set(s['properties'])=={'title','description'}
