from __future__ import annotations

"""W12.3 semantic skeleton v6 human-canary hardening.

v6 consumes the completed 35-scenario v5 canary as a human-QA regression.
The provider remains a seed-guided surface paraphraser, but subtle meaning
inversions and unsupplied scope broadening found by humans now trigger the
existing atomic curated-golden packet fallback.
"""

import copy as _copy
import re as _re

import semantic_skeleton_v3_rules_v5 as _v5
from semantic_skeleton_v3_rules_v5 import *

CONTRACT_VERSION = "w12.3-semantic-skeleton-v7"
CONFIG = _copy.deepcopy(_v5.CONFIG)
CONFIG["version"] = CONTRACT_VERSION

# Human mini-QA host-owned agency/copy fixes live in the current overlay so
# the historical v1 packet config remains immutable evidence.
CONFIG["packets"]["npc_lilla_dispatcher"]["choices"] = [
    {"label": "Vállalod a későbbi egyeztetést", "consequence": "Lillának jelzed, hogy ráérsz majd beszélni."},
    {"label": "Nem vállalod az egyeztetést", "consequence": "Lillának egyértelműen jelzed, hogy ezt az egyeztetést nem vállalod."},
]
CONFIG["packets"]["memory_nora_wallet"]["choices"] = [
    {"label": "Köszönsz Nórának", "consequence": "Röviden reagálsz arra, hogy felismer."},
    {"label": "Felidézed a pénztárcás találkozást", "consequence": "A beszélgetés a már megtörtént eseménynél marad."},
]

CONFIG["packets"]["crime_stolen_phone_offer"]["choices"] = [
    {"label": "Visszautasítod az ajánlatot", "consequence": "Nem fogadod el a kétes ajánlatot."},
    {"label": "Lezárod a beszélgetést", "consequence": "Lezárod a kétes ajánlatról szóló beszélgetést."},
    {"label": "További tisztázást kérsz", "consequence": "Újra rákérdezel a telefon eredetére."},
]


def _append_forbidden(packet_key: str, name: str, pattern: str) -> None:
    rows = CONFIG["packets"][packet_key].setdefault("forbidden", [])
    if not any(existing == name for existing, _ in rows):
        rows.append([name, pattern])


# Human mini-QA: the packet says the measurement SHOWS a deviation on the part.
# It does not say the measurement itself is inaccurate or defective.
_append_forbidden(
    "career_cnc_quality",
    "cnc_measurement_accuracy_inversion",
    r"(?i)(?:\bmérés\w*.{0,28}\b(?:pontatlan|hibás)\w*|\b(?:pontatlan|hibás)\w*.{0,28}\bmérés\w*)",
)
_append_forbidden(
    "career_cnc_quality",
    "cnc_unnatural_artifact_wording",
    r"(?i)\bCNC[-\s]?alkotás\w*\b",
)

# Human mini-QA: a growing queue does not establish a peak-hour fact.
_append_forbidden(
    "work_miskolc_canteen",
    "canteen_unsupplied_peak_period",
    r"(?i)\bcsúcsidő\w*\b",
)

# Human mini-QA: "munkaügyi" narrows the supplied generic work-related meeting
# into a different domain meaning.
_append_forbidden(
    "npc_lilla_dispatcher",
    "lilla_munkaugyi_scope_drift",
    r"(?i)\bmunkaügyi\b",
)

# Human mini-QA: recognition does not establish that Nóra greeted first, and
# ambiguous "ő" phrasing may flip who returned the wallet.
_append_forbidden(
    "memory_nora_wallet",
    "nora_ambiguous_actor_pronoun",
    r"(?i)(?:korábban\s+ő\s+találta|segítség\s+miatt\s*:\s*ő\s+találta)",
)

# Human mini-QA: fewer people staying outside is not an imposed restriction.
_append_forbidden(
    "world_eger_heat",
    "world_heat_imposed_restriction_drift",
    r"(?i)\b(?:korlátoz|tilt)\w*\b",
)

# Polish the two old curated panic phrasings through atomic fallback.
_append_forbidden(
    "store_heist_teammate_panic",
    "panic_awkward_communication_wording",
    r"(?i)(?:röviden\s+a\s+bizonytalan\s+kommunikáció\s+rendezésére\s+figyel|megtöri\s+a\s+csapat\s+addigi\s+kommunikációját)",
)


# Partial-FULL human QA: fluent-looking production failures from the first 70/120.
_append_forbidden(
    "work_miskolc_warehouse",
    "warehouse_partial_full_bad_hungarian",
    r"(?i)(?:\btorlasdott\b|kevert\s+címk\w*\s+sorrend|címk\w*\s+sorrendj|munkafolyamat\s+folytonos|sorrendet\s+kell\s+rendezni)",
)
_append_forbidden(
    "work_eger_event_cleanup",
    "cleanup_unsupplied_drying_location",
    r"(?i)(?:szabadban|kint)\s+szárad",
)
_append_forbidden(
    "work_eger_event_cleanup",
    "cleanup_wet_drying_role_inversion",
    r"(?i)nedves\s+(?:kábel\w*|felszerel\w*).{0,50}elkülönít\w*.{0,35}szárad",
)
_append_forbidden(
    "career_dispatch_road_closure",
    "dispatch_partial_full_broken_subject",
    r"(?i)(?:útlezárás\s+a\s+menet\s+közben|késő\s+fuvarra\s+bukkan|sofőrrel\s+találkozik\s+az\s+útlezárás)",
)
_append_forbidden(
    "career_retail_training",
    "retail_partial_full_bad_collocation",
    r"(?i)\bszorul\s+akadályba\b",
)
_append_forbidden(
    "work_mezokovesd_archive",
    "archive_partial_full_bad_plural",
    r"(?i)\ba\s+régi\s+mappa\s+közt\b",
)


# Partial-FULL curated wording overrides. Keep the canonical compressed golden
# corpus immutable; v7 overlays only the 19 rows corrected by early Human QA.
_GOLDEN_OVERRIDES = {
    ("work_miskolc_warehouse", "focus_a"): {"title": "Feltorlódott raklapok", "description": "A késő teherautó miatt több raklap torlódik fel, a két összekevert címke miatt pedig előbb a raklapok sorrendjét kell tisztázni."},
    ("work_miskolc_warehouse", "focus_b"): {"title": "Összekevert címkék", "description": "A miskolci raktárban több raklap torlódik, és két raklap címkéje összekeveredett, ezért nem szabad találgatni a sorrendet."},
    ("work_miskolc_warehouse", "focus_c"): {"title": "Sorrend tisztázása", "description": "A feltorlódott raklapoknál a két összekevert címke miatt előbb a raklapok helyes sorrendjét kell tisztázni."},
    ("work_miskolc_warehouse", "focus_d"): {"title": "Kapkodás helyett tisztázás", "description": "A késő teherautó miatt feltorlódott raklapoknál előbb a címkekeveredést és a sorrendet kell tisztázni, nem kapkodva rendezni."},
    ("work_miskolc_warehouse", "focus_e"): {"title": "Raktári torlódás", "description": "A raktári kisegítő több feltorlódott raklappal találkozik; két raklap címkéje összekeveredett, ezért előbb a sorrendet kell tisztázni."},
    ("work_eger_event_cleanup", "focus_a"): {"title": "Eső utáni bontás", "description": "Az esti eső után több kábel és könnyű felszerelés vizes, ezért szét kell válogatni, mi pakolható el és minek kell még száradnia."},
    ("work_eger_event_cleanup", "focus_b"): {"title": "Nedves felszerelés", "description": "A rendezvény bontásánál több kábel és könnyű felszerelés nedves, ezért külön kell választani a pakolható és a még száradó darabokat."},
    ("work_eger_event_cleanup", "focus_c"): {"title": "Biztonságos szétválogatás", "description": "A csapatnak a vizes kábeleket és könnyű felszerelést biztonságosan kell szétválogatnia aszerint, mi pakolható el és minek kell még száradnia."},
    ("work_eger_event_cleanup", "focus_d"): {"title": "Nedves kábelek", "description": "Az egri rendezvénybontásnál a nedves kábelek és könnyű felszerelések közül el kell különíteni, mi pakolható el és mi maradjon száradni."},
    ("work_eger_event_cleanup", "focus_e"): {"title": "Pakolás eső után", "description": "A vizes kábelek és könnyű felszerelések között előbb tisztázni kell, mi pakolható el biztonságosan és mi maradjon száradni."},
    ("work_mezokovesd_archive", "focus_c"): {"title": "Régi mappák rendezése", "description": "A régi mappák közt több hibás címke akad, ezért az iratokat nem szabad találgatással rossz helyre tenni."},
    ("career_dispatch_road_closure", "focus_a"): {"title": "Csúszó fuvar", "description": "A váratlan útlezárás miatt csúszik az egyik aznapi fuvar, ezért az úton lévő sofőrt értesíteni kell, és meg kell szervezni a helyzet kezelését."},
    ("career_dispatch_road_closure", "focus_b"): {"title": "Útlezárás útközben", "description": "Az egyik aznapi fuvar egy váratlan útlezárás miatt késik, miközben a sofőr már úton van, ezért időben jelezni kell neki a csúszást."},
    ("career_dispatch_road_closure", "focus_c"): {"title": "Fuvarszervezői helyzet", "description": "A kezdő fuvarszervező egy útlezárás miatt csúszó fuvarral szembesül, ezért a sofőr értesítése és a szervezés kerül előtérbe."},
    ("career_dispatch_road_closure", "focus_d"): {"title": "Sofőr már úton", "description": "A sofőr már úton van, amikor a váratlan útlezárás miatt csúszni kezd a fuvar, ezért kommunikációval és szervezéssel kell kezelni a helyzetet."},
    ("career_dispatch_road_closure", "focus_e"): {"title": "Váratlan késés", "description": "Az útlezárás az egyik aznapi fuvart késlelteti, ezért a játékos a sofőr tájékoztatására és a helyzet megszervezésére koncentrál."},
    ("career_retail_training", "focus_c"): {"title": "Műszakvezető csúcsidőben", "description": "A frissen kinevezett műszakvezetőnek az elakadt új kollégát kell segítenie úgy, hogy közben a csúcsidős sor felügyelete is megmaradjon."},
    ("career_retail_training", "focus_d"): {"title": "Segítség csúcsidőben", "description": "Egy új kolléga rutin feladatnál akad el, ezért úgy kell segíteni neki, hogy közben a sor felügyelete se maradjon el."},
    ("career_retail_training", "focus_e"): {"title": "Új kolléga támogatása", "description": "Az új kolléga csúcsidőben elakad, így a játékosnak úgy kell segítenie, hogy a sor ne maradjon teljesen felügyelet nélkül."},
}

_base_golden_rows = _v5.golden_rows

def _v7_golden_rows():
    rows = _copy.deepcopy(_base_golden_rows())
    for row in rows:
        key = (str(row.get("packet") or ""), str(row.get("slot") or ""))
        override = _GOLDEN_OVERRIDES.get(key)
        if override:
            row.update(override)
    return rows

_v5._GOLDEN_CACHE = _v7_golden_rows()

# Align imported layers with the merged current config/version.
_v5.CONFIG = CONFIG
_v5.CONTRACT_VERSION = CONTRACT_VERSION
try:
    _v5._v4.CONFIG = CONFIG
    _v5._v4.CONTRACT_VERSION = CONTRACT_VERSION
    _v5._v4._v3.CONFIG = CONFIG
    _v5._v4._v3.CONTRACT_VERSION = CONTRACT_VERSION
    _v5._v4._v3._v2.CONFIG = CONFIG
    _v5._v4._v3._v2.CONTRACT_VERSION = CONTRACT_VERSION
    _v5._v4._v3._v2._v1.CONFIG = CONFIG
    _v5._v4._v3._v2._v1.CONTRACT_VERSION = CONTRACT_VERSION
except Exception:
    pass



def semantic_errors(lab, packet, payload: dict) -> list[str]:
    return list(_v5.semantic_errors(lab, packet, payload))
