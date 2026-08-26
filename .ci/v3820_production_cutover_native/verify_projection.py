from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SRC=ROOT/'source'
M=json.loads((ROOT/'PROJECTION_MANIFEST.json').read_text(encoding='utf-8'))

def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

for rel,spec in M['production_source_files'].items():
    p=SRC/rel
    assert p.exists(), f'missing frozen production source: {rel}'
    assert p.stat().st_size==spec['bytes'], (rel,p.stat().st_size,spec['bytes'])
    assert sha(p)==spec['sha256'], (rel,sha(p),spec['sha256'])

adapter=M['proof_adapter']
adapter_path=SRC/adapter['path']
assert adapter['scope']=='CI_ONLY_NOT_PRODUCTION_SOURCE'
assert adapter_path.exists()
assert adapter_path.stat().st_size==adapter['bytes']
assert sha(adapter_path)==adapter['sha256']

schema=SRC/'CHAPTER_SCHEMA.sql'
assert schema.exists()
assert sha(schema)==M['chapter_mysql_ddl_sha256']

chapter=(SRC/'app/services/chapters.py').read_text(encoding='utf-8').lower()
for bad in ('random.choice','rng.random','chapter_xp','chapter_score','chapter_payout'):
    assert bad not in chapter

assert M['phase10_db_backend_native_closure']=='HISTORICAL_PASS'
assert M['expected_native_tests']==8

print('V3820_CUTOVER_SOURCE_VERIFY=PASS')
print('W21_1_CHAPTER_DDL_FROZEN=PASS')
print('PRODUCTION_RC1_IDENTITY=PASS')
print('PROOF_ADAPTER=CI_ONLY')
