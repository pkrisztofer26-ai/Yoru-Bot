from __future__ import annotations
from pathlib import Path
import hashlib,json,shutil,sys

ROOT=Path(__file__).resolve().parents[2]
GATE=ROOT/'.ci/v3784_phase7_native_gate'
MANIFEST=json.loads((GATE/'PROJECTION_MANIFEST.json').read_text(encoding='utf-8'))
OUT=GATE/'assembled'
if OUT.exists(): shutil.rmtree(OUT)
OUT.mkdir(parents=True)
count=0
for item in MANIFEST['files']:
    dest=OUT/item['path']; dest.parent.mkdir(parents=True,exist_ok=True)
    data=b''
    for part in item['parts']:
        p=ROOT/part['path']; raw=p.read_bytes()
        if len(raw)!=int(part['bytes']) or hashlib.sha256(raw).hexdigest()!=part['sha256']:
            raise SystemExit(f'PART_VERIFY=FAIL {part["path"]}')
        data+=raw
    if len(data)!=int(item['bytes']) or hashlib.sha256(data).hexdigest()!=item['sha256']:
        raise SystemExit(f'FILE_VERIFY=FAIL {item["path"]}')
    dest.write_bytes(data); count+=1
# Contract-level provenance checks.
fp=json.loads((OUT/'SOURCE_FINGERPRINTS.json').read_text(encoding='utf-8'))
if fp['VERSION']['sha256']!='02743d17dab081c1e42815418e31cc586741cbb6e464240ec435d6df42bd4ff8':
    raise SystemExit('VERSION_FINGERPRINT=FAIL')
if MANIFEST['source_build_sha256']!='c73214a6797e1db3dbef586e9d867ad956020d7fc6898c3bf7755bd1e7bc2d8e':
    raise SystemExit('SOURCE_BUILD_FINGERPRINT=FAIL')
schema=(OUT/'PHASE7_WORLD_SCHEMA.sql').read_text(encoding='utf-8')
methods=(OUT/'PHASE7_PERSISTENCE_METHODS.py.txt').read_text(encoding='utf-8')
for token in ('rp_world_causality_signals','rp_world_causality_decisions','rp_world_community_projects','rp_world_community_project_contributions','rp_world_community_project_outcomes','ENGINE=InnoDB'):
    if token not in schema: raise SystemExit(f'SCHEMA_TOKEN=FAIL {token}')
for token in ('record_causality_signal','_save_causality_decision','ensure_community_project','record_community_project_contribution','_ensure_community_project_outcome_db','recover_community_project_outcomes'):
    if token not in methods: raise SystemExit(f'METHOD_TOKEN=FAIL {token}')
print(f'PHASE7_SOURCE_VERIFY=PASS files={count} parts={sum(len(x["parts"]) for x in MANIFEST["files"])} source_build_sha256={MANIFEST["source_build_sha256"]}')
print('W17.6N_PHASE7_NATIVE_STATIC=PASS')
