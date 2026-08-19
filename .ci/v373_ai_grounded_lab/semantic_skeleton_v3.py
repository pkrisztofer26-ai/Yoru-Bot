from __future__ import annotations

from semantic_skeleton_v3_rules import *
from semantic_skeleton_v3_install_v5 import install_semantic_layer
from semantic_skeleton_v3_surface_v5 import _surface_fields_only, _extract_failed_generation, repair_surface_with_golden
from semantic_skeleton_v3_validation_v5 import self_test, regression_report
from semantic_skeleton_v3_output_v5 import out_dir_from_argv, rewrite_gate_files, write_tpd_stop

SAFETY_MARKER = {"production_ai_authorized": False}


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
