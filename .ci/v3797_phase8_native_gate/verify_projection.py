from pathlib import Path
import hashlib,json
G=Path(__file__).resolve().parent; S=G/'phase8_source'; M=json.loads((G/'PROJECTION_MANIFEST.json').read_text())
a=hashlib.sha256(); n=0
for x in M['files']:
 p=S/x['path']; b=p.read_bytes(); assert len(b)==x['bytes'] and hashlib.sha256(b).hexdigest()==x['sha256'],x['path']; a.update(x['path'].encode()+b'\0'+b); n+=1
assert a.hexdigest()==M['source_projection_sha256']
fp=json.loads((S/'SOURCE_FINGERPRINTS.json').read_text()); assert fp['source_release']=='3.79.7'
s=(S/'PHASE8_SCHEMA.sql').read_text(); assert all(x in s for x in ('crew_relations','crew_governance_proposals','crew_governance_votes','crew_governance_executions','crew_internal_projects','crew_hq_state','crew_hq_asset_links','ENGINE=InnoDB'))
t=(S/'tests/test_phase8_native_gate.py').read_text(); assert all(f'test_{i:02d}_' in t for i in range(1,11))
print(f'PHASE8_SOURCE_VERIFY=PASS files={n} source_projection_sha256={M["source_projection_sha256"]}')
print('W18.8N_PHASE8_NATIVE_STATIC=PASS')
