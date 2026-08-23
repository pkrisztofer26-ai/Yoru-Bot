from pathlib import Path
import ast,hashlib,json
G=Path(__file__).resolve().parent; S=G/'phase9_source'; M=json.loads((G/'PROJECTION_MANIFEST.json').read_text())
a=hashlib.sha256(); n=0
for x in M['files']:
 p=S/x['path']; b=p.read_bytes(); assert len(b)==x['bytes'] and hashlib.sha256(b).hexdigest()==x['sha256'],x['path']; a.update(x['path'].encode()+b'\0'+b); n+=1
assert a.hexdigest()==M['source_projection_sha256']
fp=json.loads((S/'SOURCE_FINGERPRINTS.json').read_text()); assert fp['source_release']=='3.80.6'
assert M['full_build_sha256']==fp['release_artifact']['sha256']=='d55469a3bf3adc2af250ea107be85a821c04f60d605645544d9f3e84b96eafb2'
s=(S/'PHASE9_SCHEMA.sql').read_text(); assert all(x in s for x in ('asset_instances','asset_ownership_history','asset_auction_listings','asset_auction_bids','asset_trophy_showcase','ENGINE=InnoDB'))
count=0
for p in (S/'tests').glob('test_*.py'):
 t=ast.parse(p.read_text()); count += sum(isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) and x.name.startswith('test_') for x in ast.walk(t))
assert count==13,count
print(f'PHASE9_SOURCE_VERIFY=PASS files={n} tests={count} source_projection_sha256={M["source_projection_sha256"]}')
print('W19.8N_PHASE9_NATIVE_STATIC=PASS')
