from __future__ import annotations

from semantic_skeleton_v3_rules import *
import os

def install_semantic_layer(lab) -> None:
    base_validate = lab.validate_payload
    base_request = lab.request_groq
    lab.CONTRACT_VERSION = CONTRACT_VERSION
    lab.output_schema = surface_output_schema
    lab.system_prompt = system_prompt_v3
    lab.user_prompt = user_prompt_v3

    def request_v3(**kwargs):
        packet = kwargs["packet"]
        payload, usage, latency, http_attempts, rate = base_request(**kwargs)
        payload = canonicalize_surface_payload(lab, packet, payload)
        return payload, usage, latency, http_attempts, rate

    def validate_v3(packet, payload):
        base = list(base_validate(packet, payload))
        if packet.profile == "world":
            base = [e for e in base if "choices count must be 1..2" not in e]
        return base + semantic_errors(lab, packet, payload)

    lab.request_groq = request_v3
    lab.validate_payload = validate_v3


def regression_report(lab) -> dict[str, Any]:
    packed = base64.b64decode("".join(p.read_text(encoding="ascii") for p in REGRESSION_CHUNKS))
    corpus = json.loads(gzip.decompress(packed).decode("utf-8"))["items"]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in corpus:
        grouped.setdefault(str(row["packet"]), []).append(row)
    packet_by_key = {p.key: p for p in lab.PACKETS}
    rows = []
    legacy_pass = 0
    for key in sorted(grouped):
        packet = packet_by_key[key]
        old = sorted(grouped[key], key=lambda x: int(x["index"]))
        surface = {"items": [
            {"slot": SLOT_IDS[i], "title": r["item"]["title"], "description": r["item"]["description"]}
            for i, r in enumerate(old)
        ]}
        canonical = canonicalize_surface_payload(lab, packet, surface)
        errs = lab.validate_payload(packet, canonical)
        passed = not errs
        if passed:
            legacy_pass += 1
        statuses = [r["human_status"] for r in old]
        if "FAIL" in statuses:
            human_packet_class = "BLOCKER"
        elif "MAJOR" in statuses:
            human_packet_class = "REWRITE"
        elif "MINOR" in statuses:
            human_packet_class = "POLISH"
        else:
            human_packet_class = "PASS"
        rows.append({
            "packet": key,
            "human_packet_class": human_packet_class,
            "old_human_statuses": statuses,
            "w123_accepts_old_packet_after_host_repair": passed,
            "error_count": len(errs),
            "sample_errors": errs[:10],
        })
    blocker_rows = [r for r in rows if r["human_packet_class"] == "BLOCKER"]
    blocker_accepted = sum(bool(r["w123_accepts_old_packet_after_host_repair"]) for r in blocker_rows)
    legacy_rejected = len(grouped) - legacy_pass
    acceptance = "PASS" if blocker_accepted == 0 and legacy_rejected >= 20 else "FAIL"
    return {
        "gate": f"{GATE_NAME} — W12.2 regression corpus",
        "source_items": len(corpus),
        "source_packets": len(grouped),
        "source_blocker_packets": len(blocker_rows),
        "legacy_packets_rejected": legacy_rejected,
        "legacy_packets_accepted_after_host_repair": legacy_pass,
        "blocker_packets_rejected": len(blocker_rows) - blocker_accepted,
        "blocker_packets_accepted": blocker_accepted,
        "acceptance": acceptance,
        "production_ai_authorized": False,
        "rows": rows,
    }


def self_test(lab) -> dict[str, Any]:
    assert CONFIG.get("version") == CONTRACT_VERSION
    assert set(CONFIG["packets"]) == {p.key for p in lab.PACKETS}
    assert len(lab.PACKETS) == 24
    assert sum(p.count for p in lab.PACKETS) == 120

    # Surface schema has no authority/choice fields.
    sample = lab.PACKETS[0]
    props = surface_output_schema(sample)["properties"]["items"]["items"]["properties"]
    assert set(props) == {"slot", "title", "description"}

    # Host owns choices and world contexts own zero choices.
    def probe_surface(packet, title="Rövid próbacím", desc="próba"):
        cfg = packet_cfg(packet)
        anchor_text = " ".join(group[0] for group in cfg["anchors"])
        return {"items": [
            {"slot": slot, "title": f"{title} {chr(65+i)}", "description": f"{anchor_text} {desc} {chr(97+i)}."}
            for i, slot in enumerate(SLOT_IDS)
        ]}

    non_world = next(p for p in lab.PACKETS if p.key == "crime_unknown_envelope")
    can = canonicalize_surface_payload(lab, non_world, probe_surface(non_world))
    assert can["items"][0]["choices"] == choice_rows(non_world, 0)
    assert "slot" not in can["items"][0]

    world = next(p for p in lab.PACKETS if p.key == "world_miskolc_roadworks")
    can_world = canonicalize_surface_payload(lab, world, probe_surface(world))
    assert all(x["choices"] == [] for x in can_world["items"])

    # Known W12.2 factual drift must be blocked.
    canteen = next(p for p in lab.PACKETS if p.key == "work_miskolc_canteen")
    bad = probe_surface(canteen, desc="zöldséget talál ki")
    badc = canonicalize_surface_payload(lab, canteen, bad)
    assert any("ingredient_invention" in e for e in semantic_errors(lab, canteen, badc))

    # Meta/numbered title regression.
    bad_title = probe_surface(non_world)
    bad_title["items"][0]["title"] = "Változat egy"
    bad_title_c = canonicalize_surface_payload(lab, non_world, bad_title)
    assert any("numbered_template_title" in e for e in semantic_errors(lab, non_world, bad_title_c))

    regression = regression_report(lab)
    assert regression["source_items"] == 120
    assert regression["source_packets"] == 24
    assert regression["acceptance"] == "PASS", regression
    assert regression["blocker_packets_accepted"] == 0, regression
    assert regression["legacy_packets_rejected"] >= 20, regression
    print(
        "W12_3_SEMANTIC_SKELETON_SELFTEST_PASS "
        f"surface_only host_choices world_no_choice anchors forbidden_regressions "
        f"legacy_rejected={regression['legacy_packets_rejected']}/24 blocker_rejected={regression['blocker_packets_rejected']}/{regression['source_blocker_packets']}",
        flush=True,
    )
    return regression


def out_dir_from_argv() -> Path:
    args = sys.argv[1:]
    if "--out-dir" in args:
        i = args.index("--out-dir")
        if i + 1 < len(args):
            return Path(args[i + 1])
    return Path("artifacts/ai_semantic_skeleton_lab")


def rewrite_gate_files(out: Path, regression: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "W12_3_REGRESSION_RESULT.json").write_text(json.dumps(regression, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "W12_3_REGRESSION_RESULT.txt").write_text(
        "\n".join([
            regression["gate"],
            f"STATUS: {regression['acceptance']}",
            f"legacy_packets_rejected={regression['legacy_packets_rejected']}/24",
            f"blocker_packets_rejected={regression['blocker_packets_rejected']}/{regression['source_blocker_packets']}",
            f"source_items={regression['source_items']}/120",
            "production_ai_authorized=false",
            "",
        ]), encoding="utf-8"
    )

    dry = out / "YORU_AI_GROUNDED_LAB_DRY_RUN.json"
    if dry.is_file():
        try:
            data = json.loads(dry.read_text(encoding="utf-8"))
            data["gate"] = GATE_NAME
            data["contract_version"] = CONTRACT_VERSION
            data["run_scope"] = os.environ.get("W123_RUN_SCOPE", "full")
            data["semantic_skeleton"] = {
                "provider_fields": ["slot", "title", "description"],
                "host_owned": ["key", "semantic_key", "choices", "tags", "grounding_ids", "entities_mentioned", "new_fact_claims"],
                "world_player_choices": False,
                "w122_regression_packets_rejected": regression["legacy_packets_rejected"],
                "w122_blocker_packets_rejected": regression["blocker_packets_rejected"],
            }
            dry.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    result = out / "YORU_AI_GROUNDED_LAB_RESULT.json"
    if result.is_file():
        try:
            data = json.loads(result.read_text(encoding="utf-8"))
            summary = data.get("summary", {})
            if isinstance(summary, dict):
                summary["gate"] = GATE_NAME
                summary["contract_version"] = CONTRACT_VERSION
                summary["semantic_skeleton_enabled"] = True
                summary["run_scope"] = os.environ.get("W123_RUN_SCOPE", "full")
                summary["w122_regression_packets_rejected"] = regression["legacy_packets_rejected"]
                summary["w122_blocker_packets_rejected"] = regression["blocker_packets_rejected"]
            result.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    result_txt = out / "YORU_AI_GROUNDED_LAB_RESULT.txt"
    if result_txt.is_file():
        text = result_txt.read_text(encoding="utf-8")
        lines = text.splitlines()
        if lines:
            lines[0] = GATE_NAME
        result_txt.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

    old_progress = out / "W12_2_PROGRESS.txt"
    if old_progress.is_file():
        (out / "W12_3_PROGRESS.txt").write_text(old_progress.read_text(encoding="utf-8"), encoding="utf-8")


def write_tpd_stop(out: Path, exc) -> None:
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "gate": GATE_NAME,
        "contract_version": CONTRACT_VERSION,
        "status": "INCOMPLETE",
        "run_scope": os.environ.get("W123_RUN_SCOPE", "full"),
        "provider_blocked_reason": "daily_token_limit",
        "provider_retry_after_seconds": round(float(exc.retry_after_seconds), 3),
        "checkpoint_progress_preserved": True,
        "semantic_skeleton_enabled": True,
        "human_review_required": True,
        "production_ai_authorized": False,
    }
    (out / "YORU_AI_GROUNDED_LAB_RESULT.json").write_text(json.dumps({"summary": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "YORU_AI_GROUNDED_LAB_RESULT.txt").write_text(
        "\n".join([
            GATE_NAME,
            "STATUS: INCOMPLETE",
            "provider_blocked_reason=daily_token_limit",
            f"provider_retry_after_seconds={summary['provider_retry_after_seconds']}",
            "checkpoint_progress_preserved=true",
            "semantic_skeleton_enabled=true",
            "human_review_required=true",
            "production_ai_authorized=false",
            "",
        ]), encoding="utf-8"
    )
    print(
        f"TPD_BUDGET_STOP retry_after={float(exc.retry_after_seconds):.1f}s "
        "checkpoint_progress_preserved=true; W12.3 auto-resume eligible",
        flush=True,
    )


def main() -> int:
    lab = V2.load_lab()
    V2.install_provider_hotfix(lab)
    V2.self_test(lab)
    install_semantic_layer(lab)
    regression = self_test(lab)
    out = out_dir_from_argv()
    try:
        code = int(lab.main())
        rewrite_gate_files(out, regression)
        return code
    except V2.DailyTokenLimitStop as exc:
        write_tpd_stop(out, exc)
        rewrite_gate_files(out, regression)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
