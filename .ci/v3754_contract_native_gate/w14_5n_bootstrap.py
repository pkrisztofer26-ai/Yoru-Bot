from __future__ import annotations

import ast
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SOURCE = HERE / "source"
W10 = REPO / ".ci" / "v372_mysql_gate"
W10_PARTS = [W10 / f"w10_source_{i:02d}.b64" for i in range(4)]
W10_ARCHIVE_SHA256 = "ca2db6f82bedb9679b38ace75956e583c91f1d6b712309c0b0d3f4fc47d06839"
DB_BACKEND_SHA256 = "2820a18cb05b355be3cc756b6871832fe1b3e1525aae791622933776b80ad7ca"
METRICS_SHA256 = "fc7b9a463d8219186960098f0684972c95aaa673c1b2692f72637991440dd75c"
MANIFEST = SOURCE / "W14_5N_SOURCE_PROJECTION_MANIFEST.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reconstruct_w10_base() -> Path:
    encoded = "".join(p.read_text(encoding="ascii") for p in W10_PARTS)
    payload = base64.b64decode(encoded)
    actual = hashlib.sha256(payload).hexdigest()
    if actual != W10_ARCHIVE_SHA256:
        raise RuntimeError(f"W10 fixture archive hash mismatch: {actual}")
    work = Path(tempfile.mkdtemp(prefix="yoru-w145n-w10-"))
    archive = work / "source.zip"
    archive.write_bytes(payload)
    shutil.unpack_archive(str(archive), str(work / "src"))
    return work


def install_verified_backend() -> None:
    work = reconstruct_w10_base()
    try:
        src = work / "src"
        backend = src / "app" / "db_backend.py"
        metrics = src / "app" / "core" / "metrics.py"
        if sha256(backend) != DB_BACKEND_SHA256:
            raise RuntimeError("W10 db_backend hash mismatch")
        if sha256(metrics) != METRICS_SHA256:
            raise RuntimeError("W10 metrics hash mismatch")
        (SOURCE / "app" / "core").mkdir(parents=True, exist_ok=True)
        shutil.copy2(backend, SOURCE / "app" / "db_backend.py")
        shutil.copy2(metrics, SOURCE / "app" / "core" / "metrics.py")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def method_hash(node: ast.AST) -> str:
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def verify_projection() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = data["projected_method_ast_sha256"]
    found: dict[str, str] = {}
    for path in sorted((SOURCE / "app" / "services").glob("contracts_*_mixin.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        for node in cls.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[node.name] = method_hash(node)
    if found != expected:
        missing = sorted(set(expected) - set(found))
        extra = sorted(set(found) - set(expected))
        bad = sorted(k for k in expected.keys() & found.keys() if expected[k] != found[k])
        raise RuntimeError(f"Contract method projection mismatch missing={missing} extra={extra} bad={bad}")

    db_expected = data["projected_database_transaction_method_ast_sha256"]
    db_tree = ast.parse((SOURCE / "app" / "database.py").read_text(encoding="utf-8"))
    db_cls = next(n for n in db_tree.body if isinstance(n, ast.ClassDef) and n.name == "Database")
    db_found = {
        n.name: method_hash(n)
        for n in db_cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in db_expected
    }
    if db_found != db_expected:
        raise RuntimeError("Database method projection mismatch")

    schema_ns: dict[str, object] = {}
    exec((SOURCE / "app" / "contract_schema_mysql.py").read_text(encoding="utf-8"), schema_ns)
    ddl = tuple(schema_ns["MYSQL_CONTRACT_DDL"])
    ddl_hashes = [hashlib.sha256(str(item).encode()).hexdigest() for item in ddl]
    if ddl_hashes != data["canonical_contract_mysql_ddl_sha256"]:
        raise RuntimeError("MySQL contract DDL projection mismatch")

    if sha256(SOURCE / "app" / "contract_config.py") != data["canonical_contract_config_sha256"]:
        raise RuntimeError("contract_config hash mismatch")
    if sha256(SOURCE / "app" / "db_backend.py") != data["canonical_db_backend_sha256"]:
        raise RuntimeError("db_backend hash mismatch")
    if sha256(SOURCE / "app" / "core" / "metrics.py") != data["canonical_metrics_sha256"]:
        raise RuntimeError("metrics hash mismatch")


def main() -> int:
    install_verified_backend()
    verify_projection()
    print("W14_5N_SOURCE_PROJECTION_VERIFY=PASS")
    cmd = [sys.executable, "-m", "pytest", "-q", "tests/test_v3754_native_mariadb_contract_closure.py"]
    result = subprocess.run(cmd, cwd=SOURCE, env={**__import__('os').environ, "PYTHONPATH": "."})
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
