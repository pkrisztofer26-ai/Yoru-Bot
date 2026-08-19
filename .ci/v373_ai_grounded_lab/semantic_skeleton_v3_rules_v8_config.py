from __future__ import annotations

import copy

VERSION = "w12.3-semantic-skeleton-v8"


def _append_forbidden(config: dict, packet_key: str, name: str, pattern: str) -> None:
    rows = config["packets"][packet_key].setdefault("forbidden", [])
    if not any(existing == name for existing, _ in rows):
        rows.append([name, pattern])


def build_config(base: dict) -> dict:
    config = copy.deepcopy(base)
    config["version"] = VERSION

    config["packets"]["bank_heist_plan_mismatch"]["choices"] = [
        {"label": "Visszavonulást javasolsz", "consequence": "A csapat nem folytatja automatikusan a megváltozott helyzetet."},
        {"label": "Kivárást kérsz", "consequence": "A csapat röviden megáll, mielőtt döntene."},
        {"label": "Újraértékelitek a helyzetet", "consequence": "A csapat előbb közös álláspontra jut arról, hogyan tovább."},
        {"label": "Folytatást javasolsz", "consequence": "A csapat a folytatás mellett dönt."},
    ]
    config["packets"]["store_heist_alarm_change"]["choices"] = [
        {"label": "Visszavonulást javasolsz", "consequence": "A csapat nem folytatja automatikusan a tervet."},
        {"label": "Kivárást kérsz", "consequence": "A csapat röviden megáll, mielőtt döntene."},
        {"label": "Megszakítod a tervet", "consequence": "A terv ezen a ponton véget ér."},
        {"label": "Folytatást javasolsz", "consequence": "A csapat a folytatás mellett dönt."},
    ]
    config["packets"]["crime_hold_unknown_bag"]["choices"] = [
        {"label": "Visszautasítod a kérést", "consequence": "Nem tartod magadnál az ismeretlen tartalmú táskát."},
        {"label": "További tisztázást kérsz", "consequence": "A döntés előtt egyenesebb választ kérsz."},
        {"label": "Elvállalod rövid időre", "consequence": "Jelzed, hogy rövid időre elvállalod a táska megőrzését."},
    ]
    config["packets"]["crime_unknown_envelope"]["choices"] = [
        {"label": "További tisztázást kérsz", "consequence": "Addig nem vállalsz semmit, amíg nem kapsz egyenesebb választ."},
        {"label": "Visszautasítod a kérést", "consequence": "Nem vállalod a lezárt boríték eljuttatását."},
        {"label": "Elvállalod a kérést", "consequence": "Jelzed, hogy vállalod a lezárt boríték eljuttatását."},
    ]
    if ["pénz helyett"] not in config["packets"]["crime_unknown_envelope"]["anchors"]:
        config["packets"]["crime_unknown_envelope"]["anchors"].append(["pénz helyett"])

    for packet_key in (
        "bank_heist_plan_mismatch", "bank_heist_unexpected_crowd",
        "store_heist_alarm_change", "store_heist_teammate_panic",
    ):
        _append_forbidden(config, packet_key, "heist_player_facing_internal_language", r"(?i)\b(?:magas\s+szint(?:ű|en)?|fiktív)\b")

    for packet_key, name, pattern in (
        ("store_heist_alarm_change", "store_alarm_stage_or_authority_drift", r"(?i)(?:\bvezető(?:i)?\b|\bművelet\s+közepén\b|boltrablás\s+közben)"),
        ("crime_illegal_race_invite", "race_final_bad_hungarian", r"(?i)(?:sürgősen\s+igényl|részvételtől|rögtön\s+most|meghívó\s+adója)"),
        ("npc_misi_car_dealer", "misi_final_time_or_scope_drift", r"(?i)(?:\búj\s+autó\b|\bközelmúltban\b|autóvásárlási\s+szándék)"),
        ("npc_jani_mechanic", "jani_final_overformal_surface", r"(?i)(?:közösen\s+beszélhessenek|rendelkezésre\s+áll-e|felajánlja,\s+hogy)"),
        ("crime_hold_unknown_bag", "bag_final_awkward_request_wording", r"(?i)lezárt\s+táska\s+iránti\s+kérés"),
        ("work_mezokovesd_archive", "archive_final_singular_label_wording", r"(?i)\ba\s+mappa\s+címkéi\b"),
        ("world_miskolc_roadworks", "roadworks_final_plural_scope_drift", r"(?i)\bútfelújítások\s+miatt\b"),
        ("memory_jani_tools", "jani_memory_final_awkward_help_wording", r"(?i)segítséget\s+adott.{0,45}elpakolásához"),
        ("career_mechanic_part_delay", "mechanic_final_awkward_title", r"(?i)\bkésés\s+az\s+autó\s+körül\b"),
    ):
        _append_forbidden(config, packet_key, name, pattern)
    return config
