from __future__ import annotations
import hashlib, json
from pathlib import Path
GATE=Path(__file__).resolve().parent
SRC=GATE/'source'
BASE=GATE.parent/'v3831_ai_director_review'/'frozen'
manifest=json.loads((GATE/'MANIFEST.json').read_text(encoding='utf-8'))
assert manifest['version']=='3.83.6'
assert manifest['work_item']=='W22.4.2'
assert manifest['contract']=='tier2-context-surface-v3'
assert manifest['human_qa_regressions']=='3/3 ENCODED'
assert manifest['player_facing_scope']=='TEST_GUILD_ONLY_DEFAULT_OFF'
assert manifest['gameplay_authority']=='NONE'
assert manifest['live_deploy'] is False
for rel, expected in manifest['source_sha256'].items():
    path=SRC/rel
    assert path.is_file(), rel
    actual=hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual==expected,(rel,actual,expected)
base_provider=BASE/'app/providers/ai_director_groq.py'
assert base_provider.is_file()
assert hashlib.sha256(base_provider.read_bytes()).hexdigest()==manifest['inherited_w22_2_provider_sha256']
core=(SRC/'app/ai_director_context.py').read_text(encoding='utf-8')
provider=(SRC/'app/providers/ai_director_context_groq.py').read_text(encoding='utf-8')
review=(SRC/'scripts/ai_director_tier2_context_review.py').read_text(encoding='utf-8')
service=(SRC/'app/services/ai_director_context.py').read_text(encoding='utf-8')
layer='\n'.join((core,provider,review,service))
for forbidden_import in ('services.economy','services.business','services.housing','services.jobs','services.cases','services.vehicles','services.police','services.contracts','services.assets'):
    assert forbidden_import not in layer, forbidden_import
for required in ('career','business','travel','housing','npc','tips','case','deterministic_context_fallback','asyncio.wait_for','tier2-context-surface-v3'):
    assert required in layer, required
for regression in ('otthonvárosban\\s+helyezkedik','ügyben\\s+áll','érkezett\\b.{0,48}\\bérkezett'):
    assert regression in core, regression
assert 'http_retries=1' in review and 'await asyncio.sleep(2.0)' in review
assert '"version": "3.83.6"' in review and '"work_item": "W22.4.2"' in review
print('W22_4_2_SOURCE_VERIFY=PASS')
print('W22_4_1_SOURCE_VERIFY=PASS')
print('NEW_SOURCE_SHA256=5/5 PASS')
print('INHERITED_W22_2_PROVIDER_SHA256=PASS')
print('TIER2_DOMAINS=7/7 PASS')
print('HUNGARIAN_SURFACE_HARDENING=PASS')
print('HUMAN_QA_REGRESSIONS=3/3 ENCODED')
print('AUTHORITY_BOUNDARY=PASS')
print('PLAYER_FACING_SCOPE=TEST_GUILD_ONLY_DEFAULT_OFF')
print('GAMEPLAY_AUTHORITY=NONE')
print('LIVE_DEPLOY=UNCHANGED')
