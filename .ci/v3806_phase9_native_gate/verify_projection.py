from pathlib import Path
import ast,hashlib,json

G=Path(__file__).resolve().parent
S=G/'phase9_source'
M=json.loads((G/'PROJECTION_MANIFEST.json').read_text())

errors=[]
for x in M['files']:
    p=S/x['path']
    if not p.is_file():
        errors.append(f"missing:{x['path']}")
        continue
    b=p.read_bytes()
    actual_len=len(b)
    actual_sha=hashlib.sha256(b).hexdigest()
    if actual_len != x['bytes'] or actual_sha != x['sha256']:
        errors.append(
            f"mismatch:{x['path']}:bytes={actual_len}/{x['bytes']}:sha256={actual_sha}/{x['sha256']}"
        )
if errors:
    raise AssertionError('; '.join(errors))

projection=hashlib.sha256()
for x in M['files']:
    projection.update(f"{x['path']}\0{x['bytes']}\0{x['sha256']}\n".encode())
assert projection.hexdigest()==M['source_projection_sha256'],(
    projection.hexdigest(),M['source_projection_sha256']
)

fp=json.loads((S/'SOURCE_FINGERPRINTS.json').read_text())
assert fp['source_release']=='3.80.6'
assert M['full_build_sha256']==fp['release_artifact']['sha256']=='d55469a3bf3adc2af250ea107be85a821c04f60d605645544d9f3e84b96eafb2'
assert fp['phase9_schema_sha256']==hashlib.sha256((S/'PHASE9_SCHEMA.sql').read_bytes()).hexdigest()

s=(S/'PHASE9_SCHEMA.sql').read_text()
assert all(x in s for x in (
    'asset_instances','asset_ownership_history','asset_auction_listings',
    'asset_auction_bids','asset_trophy_showcase','ENGINE=InnoDB'
))

count=0
for p in (S/'tests').glob('test_*.py'):
    t=ast.parse(p.read_text())
    count += sum(
        isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) and x.name.startswith('test_')
        for x in ast.walk(t)
    )
assert count==13,count

print(f'PHASE9_SOURCE_VERIFY=PASS files={len(M["files"])} tests={count} source_projection_sha256={M["source_projection_sha256"]}')
print('W19.8N_PHASE9_NATIVE_STATIC=PASS')
