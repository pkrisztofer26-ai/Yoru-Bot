from __future__ import annotations
import ast, hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SRC=ROOT/'source'
M=json.loads((ROOT/'PROJECTION_MANIFEST.json').read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
for rel,spec in M['source_files'].items():
    p=SRC/rel
    assert p.exists(), f'missing frozen source: {rel}'
    assert p.stat().st_size==spec['bytes'], (rel,p.stat().st_size,spec['bytes'])
    assert sha(p)==spec['sha256'], (rel,sha(p),spec['sha256'])
mod=ast.parse((SRC/'app/database.py').read_text(encoding='utf-8'))
ddl=None
for node in ast.walk(mod):
    if isinstance(node,ast.AsyncFunctionDef) and node.name=='_ensure_chapter_foundation_schema':
        for sub in ast.walk(node):
            if isinstance(sub,ast.Call):
                fn=sub.func
                name=fn.attr if isinstance(fn,ast.Attribute) else (fn.id if isinstance(fn,ast.Name) else '')
                if name=='execute_backend_ddl':
                    for kw in sub.keywords:
                        if kw.arg=='mysql_sql' and isinstance(kw.value,ast.Constant) and isinstance(kw.value.value,str):
                            ddl=kw.value.value.strip()+'\n'
assert ddl is not None
assert hashlib.sha256(ddl.encode()).hexdigest()==M['chapter_mysql_ddl_sha256']
assert (SRC/'CHAPTER_SCHEMA.sql').read_text(encoding='utf-8')==ddl
chapter=(SRC/'app/services/chapters.py').read_text(encoding='utf-8').lower()
for bad in ('random.choice','rng.random','chapter_xp','chapter_score','chapter_payout'):
    assert bad not in chapter
print('V3820_CUTOVER_SOURCE_VERIFY=PASS')
print('W21_1_CHAPTER_DDL_FROZEN=PASS')
print('PRODUCTION_RC1_IDENTITY=PASS')
