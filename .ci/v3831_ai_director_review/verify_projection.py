from __future__ import annotations
import hashlib, json
from pathlib import Path

GATE=Path(__file__).resolve().parent
SRC=GATE/'source'
manifest=json.loads((GATE/'MANIFEST.json').read_text(encoding='utf-8'))
assert manifest['version']=='3.83.1'
assert manifest['contract']=='tier1-cached-surface-v2'
assert manifest['player_facing_ai'] is False
assert manifest['production_runtime_enabled'] is False
assert manifest['live_deploy'] is False
for rel, expected in manifest['files'].items():
    path=SRC/rel
    assert path.is_file(), rel
    actual=hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual==expected, (rel, actual, expected)
provider=(SRC/'app/providers/ai_director_groq.py').read_text(encoding='utf-8')
review=(SRC/'app/ai_director_review.py').read_text(encoding='utf-8')
script=(SRC/'scripts/ai_director_tier1_review.py').read_text(encoding='utf-8')
director=(SRC/'app/ai_director.py').read_text(encoding='utf-8')
layer='\n'.join((provider,review,script,director))
for forbidden in ('services.economy','services.assets','services.contracts','services.heist'):
    assert forbidden not in layer, forbidden
assert 'json_schema' in provider and 'additionalProperties' in provider
assert 'GOLDEN SEED' in provider
assert 'AIDirectorDailyTokenLimit' in provider
assert 'PENDING_HUMAN' in review and 'AUTOMATED_HOLD' in review
assert 'PLAYER_FACING_AI=OFF' in script
assert 'PRODUCTION_RUNTIME_ENABLED=FALSE' in script
print('W22_2_SOURCE_VERIFY=PASS')
print('SOURCE_SHA256=10/10 PASS')
print('AUTHORITY_BOUNDARY=PASS')
print('PLAYER_FACING_AI=OFF')
print('PRODUCTION_RUNTIME_ENABLED=FALSE')
print('LIVE_DEPLOY=UNCHANGED')
