from __future__ import annotations

from pathlib import Path
import ast
import hashlib
import json
import re

G = Path(__file__).resolve().parent
S = G / "phase10_source"
M = json.loads((G / "PROJECTION_MANIFEST.json").read_text(encoding="utf-8"))

errors: list[str] = []
if M.get("schema") != 2:
    errors.append(f"manifest_schema:{M.get('schema')}")
if M.get("expected_files") != len(M.get("files", [])):
    errors.append(f"manifest_file_count:{len(M.get('files', []))}/{M.get('expected_files')}")
if len({x.get('path') for x in M.get('files', [])}) != len(M.get('files', [])):
    errors.append("duplicate_manifest_paths")

for x in M.get("files", []):
    p = S / x["path"]
    if not p.is_file():
        errors.append(f"missing:{x['path']}")
        continue
    b = p.read_bytes()
    actual_len = len(b)
    actual_sha = hashlib.sha256(b).hexdigest()
    if actual_len != x["bytes"] or actual_sha != x["sha256"]:
        errors.append(
            f"mismatch:{x['path']}:bytes={actual_len}/{x['bytes']}:sha256={actual_sha}/{x['sha256']}"
        )
if errors:
    raise AssertionError("; ".join(errors))

projection = hashlib.sha256()
for x in M["files"]:
    projection.update(f"{x['path']}\0{x['bytes']}\0{x['sha256']}\n".encode())
actual_projection = projection.hexdigest()
assert actual_projection == M["source_projection_sha256"], (
    actual_projection,
    M["source_projection_sha256"],
)

assert (S / "VERSION").read_text(encoding="utf-8").strip() == "3.81.7"
fp = json.loads((S / "SOURCE_FINGERPRINTS.json").read_text(encoding="utf-8"))
assert M["source_release"] == fp["source_release"] == "3.81.7"
assert M["full_build_sha256"] == fp["full_build_sha256"] == "d349eaa9217259668847ce8929cc4c07b973fdb1245cbcdd3ce50c5a52deb598"
assert M["current_tree_sha256"] == fp["current_tree_sha256"] == "44311b92d43e998b8dab2d31a95538a4f0d6d35c1d64c40fb78f9cdb77b765b7"
assert M["source_schema_sha256"] == hashlib.sha256((S / "PHASE10_SCHEMA.sql").read_bytes()).hexdigest()
assert M["feature_boundary_audit_sha256"] == hashlib.sha256((S / "FEATURE_BOUNDARY_AUDIT.json").read_bytes()).hexdigest()
assert len(fp["files"]) >= 22
assert len(fp["critical_methods"]) >= 30

required_source_files = {
    "app/services/holding.py",
    "app/services/acquisition.py",
    "app/services/mega_projects.py",
    "app/services/elite_opportunities.py",
    "app/services/legendary_heists.py",
    "app/services/veteran_identity.py",
    "app/services/asset_auctions.py",
    "app/services/shop.py",
    "app/services/hall_of_fame.py",
    "app/database.py",
    "app/db_backend.py",
}
assert required_source_files <= set(fp["files"])

required_methods = {
    "app/services/holding.py::snapshot",
    "app/services/acquisition.py::candidates",
    "app/services/acquisition.py::due_diligence",
    "app/services/mega_projects.py::start_project",
    "app/services/mega_projects.py::reconcile_project",
    "app/services/elite_opportunities.py::profile",
    "app/services/elite_opportunities.py::candidates",
    "app/services/legendary_heists.py::participant_eligible",
    "app/services/legendary_heists.py::access",
    "app/services/legendary_heists.py::create_from_invite",
    "app/services/asset_auctions.py::create_listing",
    "app/services/asset_auctions.py::visible_listings",
    "app/services/asset_auctions.py::place_bid",
    "app/services/asset_auctions.py::_settle_tx",
    "app/database.py::reserve_wallet_and_bank_tx",
    "app/database.py::refund_wallet_and_bank_tx",
    "app/database.py::credit_wallet_tx",
    "app/database.py::buy_market_item",
    "app/database.py::sell_market_item",
    "app/services/shop.py::_require_market_access",
    "app/services/veteran_identity.py::evaluate_history",
    "app/services/hall_of_fame.py::_guild_metrics",
    "app/services/hall_of_fame.py::_build_snapshot",
}
assert required_methods <= set(fp["critical_methods"])

audit = json.loads((S / "FEATURE_BOUNDARY_AUDIT.json").read_text(encoding="utf-8"))
assert audit["schema"] == 1
assert audit["source_release"] == "3.81.7"
assert audit["scope"] == "W20.1-W20.8"
assert audit["result"] == "PASS"
assert set(audit["features"]) == {f"W20.{i}" for i in range(1, 9)}
for item in audit["features"].values():
    assert item["parallel_persistence"] is False
    assert set(item["method_refs"]) <= set(fp["critical_methods"])
assert set(audit["canonical_transaction_methods"]) <= set(fp["critical_methods"])

schema = (S / "PHASE10_SCHEMA.sql").read_text(encoding="utf-8")
required_schema_tokens = (
    "ENGINE=InnoDB",
    "holding_mega_projects",
    "uq_holding_mega_project_once",
    "uq_holding_mega_project_active",
    "asset_auction_listings",
    "asset_auction_bids",
    "uq_asset_auction_active",
    "uq_asset_auction_bid_request",
    "market_daily",
    "inventory",
    "transactions",
    "asset_ownership_history",
)
assert all(token in schema for token in required_schema_tokens)
for forbidden_table in (
    "CREATE TABLE private_auction",
    "CREATE TABLE IF NOT EXISTS private_auction",
    "CREATE TABLE private_invest",
    "CREATE TABLE IF NOT EXISTS private_invest",
    "CREATE TABLE hall_of_fame",
    "CREATE TABLE IF NOT EXISTS hall_of_fame",
    "CREATE TABLE veteran_state",
    "CREATE TABLE IF NOT EXISTS veteran_state",
):
    assert forbidden_table.lower() not in schema.lower(), forbidden_table

# Feature-boundary audit: W20.1-W20.8 must keep access/projection layers on
# existing canonical ownership/economy/heist/market authorities.
assert audit["forbidden_parallel_tables"] == ["private_auction*", "private_invest*", "hall_of_fame*", "veteran_state*"]
assert {"guaranteed_yield", "passive_risk_free_profit", "permanent_blanket_multiplier", "prestige_reset"} <= set(audit["forbidden_mechanics"])

count = 0
for p in sorted((S / "tests").glob("test_*.py")):
    tree = ast.parse(p.read_text(encoding="utf-8"))
    count += sum(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        for node in ast.walk(tree)
    )
assert count == M["expected_tests"] == 13, count

print(f"PHASE10_SOURCE_VERIFY=PASS files={len(M['files'])} tests={count} source_projection_sha256={M['source_projection_sha256']}")
print("FEATURE_BOUNDARY_AUDIT=W20.1-W20.8 PASS")
print("W20.9N_PHASE10_NATIVE_STATIC=PASS")
