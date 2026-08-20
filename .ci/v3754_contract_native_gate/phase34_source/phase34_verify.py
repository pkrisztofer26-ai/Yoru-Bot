from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parent
m=json.loads((ROOT/"PHASE34_SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
ignore={"PHASE34_SOURCE_MANIFEST.json","phase34_verify.py"}
files=[]; total=0
for p in sorted(x for x in ROOT.rglob("*") if x.is_file() and "__pycache__" not in x.parts and ".pytest_cache" not in x.parts and not x.name.endswith(".pyc")):
    rel=p.relative_to(ROOT).as_posix()
    if rel in ignore: continue
    b=p.read_bytes(); files.append((rel,b)); total += len(b)
h=hashlib.sha256()
for rel,b in files:
    h.update(rel.encode()); h.update(b"\0"); h.update(hashlib.sha256(b).digest()); h.update(b"\n")
checks=(len(files)==int(m["file_count"]), total==int(m["total_bytes"]), h.hexdigest()==m["tree_sha256"])
if not all(checks):
    print(f"PHASE34_SOURCE_VERIFY=FAIL files={len(files)} bytes={total} tree={h.hexdigest()}")
    raise SystemExit(1)
print(f"PHASE34_SOURCE_VERIFY=PASS files={len(files)} bytes={total} tree={h.hexdigest()}")
