from __future__ import annotations

from dataclasses import dataclass

HEIST_ENABLED_KEY = "heist_enabled"
HEIST_COOLDOWN_HOURS_KEY = "heist_cooldown_hours"
HEIST_JAIL_MINUTES_KEY = "heist_jail_minutes"
HEIST_FINE_PERCENT_KEY = "heist_fine_percent"
HEIST_GEAR_LOSS_PERCENT_KEY = "heist_gear_loss_percent"
HEIST_REWARD_MULTIPLIER_KEY = "heist_reward_multiplier_percent"
HEIST_LOBBY_EXPIRE_KEY = "heist_lobby_expire_minutes"
HEIST_MAX_PARTY_KEY = "heist_max_party_size"

DEFAULT_ENABLED = True
DEFAULT_COOLDOWN_HOURS = 8
DEFAULT_JAIL_MINUTES = 45
DEFAULT_FINE_PERCENT = 12
DEFAULT_GEAR_LOSS_PERCENT = 35
DEFAULT_REWARD_MULTIPLIER_PERCENT = 100

MIN_COOLDOWN_HOURS = 1
MAX_COOLDOWN_HOURS = 168
MIN_JAIL_MINUTES = 0
MAX_JAIL_MINUTES = 1440
MIN_FINE_PERCENT = 0
MAX_FINE_PERCENT = 50
MIN_GEAR_LOSS_PERCENT = 0
MAX_GEAR_LOSS_PERCENT = 100
MIN_REWARD_MULTIPLIER_PERCENT = 25
MAX_REWARD_MULTIPLIER_PERCENT = 500

LOBBY_EXPIRE_MINUTES = 30
MAX_PARTY_SIZE = 4
PHASE_LABELS = (
    ("prep", "🧠 Felkészülés"),
    ("execution", "⚙️ Végrehajtás"),
    ("escape", "🏁 Kijutás"),
)


@dataclass(frozen=True)
class HeistTarget:
    key: str
    name: str
    emoji: str
    city_key: str
    location: str
    flavor: str
    difficulty: int  # hidden tuning value, never player-facing
    min_party: int
    max_party: int
    reward_min: int  # hidden economy tuning
    reward_max: int


# Valós magyar városnevek csak játékvilág-hangulatként szerepelnek. A célpontok
# teljesen fikciósak; nincs valós bankfiók, biztonsági rendszer vagy műveleti leírás.
HEIST_TARGETS: tuple[HeistTarget, ...] = (
    HeistTarget("miskolc_hollo", "Fekete Holló Raktár", "🦅", "miskolc", "Miskolc • Belváros", "Egy éjszakai raktári ügy, amelyhez összehangolt csapat kell.", 38, 2, 4, 24_000_000, 38_000_000),
    HeistTarget("eger_smaragd", "Smaragd Galéria", "🖼️", "eger", "Eger • Belváros", "Egy kényes galériai megbízás, ahol a feltűnés könnyen visszaüthet.", 46, 2, 4, 34_000_000, 52_000_000),
    HeistTarget("debrecen_orbit", "Orbit Data Hub", "💾", "debrecen", "Debrecen • Belváros", "Egy technikai háttérrel rendelkező célpont, amely többféle felkészülést is elbír.", 54, 2, 4, 48_000_000, 72_000_000),
    HeistTarget("szeged_aranyhid", "Aranyhíd Logistics", "🚚", "szeged", "Szeged • Belváros", "Egy nagyobb logisztikai ügy, ahol a csapat és a kijutás megszervezése is számít.", 62, 3, 4, 68_000_000, 98_000_000),
    HeistTarget("budapest_neonvault", "Neon Vault Központ", "🌃", "budapest", "Budapest • XIII. kerület", "Komoly fővárosi ügy, sok mozgó résszel és kevés hibalehetőséggel.", 72, 3, 4, 105_000_000, 155_000_000),
    HeistTarget("budapest_dunacrown", "Duna Crown Holding", "👑", "budapest", "Budapest • V. kerület", "Ritka, nagy értékű ügy, amely teljes csapatot és jó előkészítést kíván.", 82, 4, 4, 165_000_000, 245_000_000),
)
TARGET_BY_KEY = {target.key: target for target in HEIST_TARGETS}


@dataclass(frozen=True)
class HeistRole:
    key: str
    name: str
    emoji: str
    prep_bonus: int
    execution_bonus: int
    escape_bonus: int


HEIST_ROLES: tuple[HeistRole, ...] = (
    HeistRole("planner", "Szervező", "🧠", 12, 2, 2),
    HeistRole("specialist", "Behatoló", "🛠️", 2, 12, 2),
    HeistRole("driver", "Sofőr", "🚗", 2, 2, 12),
    HeistRole("support", "Biztosító ember", "🤝", 5, 5, 5),
)
ROLE_BY_KEY = {role.key: role for role in HEIST_ROLES}


@dataclass(frozen=True)
class HeistGear:
    key: str
    name: str
    emoji: str
    description: str
    price: int
    prep_bonus: int
    execution_bonus: int
    escape_bonus: int


HEIST_GEAR: tuple[HeistGear, ...] = (
    HeistGear("intel_pack", "Megfigyelési csomag", "📡", "Az előkészítésnél adhat több mozgásteret.", 4_500_000, 9, 0, 0),
    HeistGear("toolkit", "Speciális szerszámkészlet", "🧰", "Váratlan technikai akadályoknál jöhet jól.", 6_500_000, 0, 11, 0),
    HeistGear("escape_kit", "Menekülőcsomag", "🎒", "A kijutás körüli helyzeteknél lehet hasznos.", 6_000_000, 0, 0, 11),
    HeistGear("disguise_set", "Álcaruha-készlet", "🎭", "Többféle helyzetben használható, ha nem akartok feltűnést kelteni.", 9_500_000, 4, 4, 4),
)
GEAR_BY_KEY = {gear.key: gear for gear in HEIST_GEAR}


@dataclass(frozen=True)
class HeistChoice:
    key: str
    label: str
    description: str
    role_affinity: tuple[str, ...]
    gear_affinity: tuple[str, ...]
    hidden_delta: int
    success_text: str
    failure_text: str


PHASE_CHOICES: dict[str, tuple[HeistChoice, ...]] = {
    "prep": (
        HeistChoice(
            "watch_pattern", "Kivárjátok a megfelelő pillanatot",
            "Még egy ideig figyelitek a környék ritmusát, és csak akkor mozdultok, amikor tisztábbnak tűnik a helyzet.",
            ("planner", "support"), ("intel_pack", "disguise_set"), 3,
            "A kivárás működött: a csapat úgy indult el, hogy kevesebb váratlan mozgással kellett számolnia.",
            "Túl sokáig maradtatok egy helyben, és közben megváltozott a környék ritmusa.",
        ),
        HeistChoice(
            "split_prep", "Két részre bontjátok az előkészítést",
            "A csapat egyik fele a bejutásra, a másik a kijutásra készül, majd közvetlenül indulás előtt egyeztettek.",
            ("specialist", "driver"), ("toolkit", "escape_kit"), 1,
            "A párhuzamos előkészítés összeállt, és egyik oldal sem maradt le a másiktól.",
            "Az utolsó egyeztetésnél több részlet sem passzolt, ezért kapkodva kellett korrigálni.",
        ),
        HeistChoice(
            "blend_in", "Beolvadtok a környék forgalmába",
            "Nem vártok teljes csendet; inkább a környék normál mozgását használjátok takarásnak.",
            ("support", "planner"), ("disguise_set", "intel_pack"), 2,
            "A környék természetes forgalma jól eltakarta a csapat mozgását.",
            "A forgalom kiszámíthatatlanabb lett a vártnál, és több improvizációra volt szükség.",
        ),
    ),
    "execution": (
        HeistChoice(
            "steady_route", "Tartjátok az előre megbeszélt menetet",
            "Nem gyorsítotok csak azért, mert egy rész könnyebbnek látszik; mindenki a saját feladatát viszi végig.",
            ("planner", "specialist"), ("toolkit", "intel_pack"), 2,
            "A fegyelmezett végrehajtás miatt a csapat végig egy ritmusban maradt.",
            "Egy váratlan akadályhoz túl mereven ragaszkodtatok a tervhez, és idő ment el a korrekcióra.",
        ),
        HeistChoice(
            "adapt_live", "Helyben igazítotok a terven",
            "A kialakult helyzethez igazítjátok a feladatokat, még akkor is, ha valakinek menet közben szerepet kell váltania.",
            ("support", "specialist"), ("disguise_set", "toolkit"), 1,
            "A gyors átszervezés működött, és a csapat kihasználta a megnyíló lehetőséget.",
            "Az improvizáció közben két feladat egymásra csúszott, ami feltartotta a csapatot.",
        ),
        HeistChoice(
            "quiet_pressure", "Visszavesztek a tempóból",
            "Nem a gyorsaságot erőltetitek; inkább kisebb lépésekben haladtok, hogy ne kelljen egyszerre túl sok problémát kezelni.",
            ("planner", "support"), ("disguise_set", "intel_pack"), 3,
            "A visszafogott tempó megóvta a csapatot egy nagyobb hibától.",
            "A lassabb haladás miatt egy korábban üresnek hitt időablak bezárult előttetek.",
        ),
    ),
    "escape": (
        HeistChoice(
            "side_route", "A kerülő útvonalon mentek ki",
            "A rövidebb út helyett több kisebb utcán és kevésbé kiszámítható útvonalon hagyjátok el a környéket.",
            ("driver", "planner"), ("escape_kit", "intel_pack"), 2,
            "A kerülő útvonal időigényesebb volt, de a csapat rendezve jutott ki a környékről.",
            "A kerülőn váratlan torlódás alakult ki, és túl sok idő ment el a kijutással.",
        ),
        HeistChoice(
            "stagger_exit", "Nem egyszerre hagyjátok el a helyszínt",
            "A csapat rövid időközökkel, külön mozog, majd egy előre egyeztetett ponton áll össze újra.",
            ("support", "driver"), ("disguise_set", "escape_kit"), 1,
            "A széthúzott kijutás csökkentette a feltűnést, és a csapat később újra összeállt.",
            "Az egyik mozgás megcsúszott, ezért a találkozási pontot az utolsó pillanatban kellett megváltoztatni.",
        ),
        HeistChoice(
            "direct_exit", "A rövidebb kijutást választjátok",
            "A csapat együtt marad, és a legegyenesebb használható útvonalon próbál eltűnni a környékről.",
            ("driver", "specialist"), ("escape_kit", "toolkit"), 0,
            "A közvetlen kijutás most működött, és nem kellett menet közben új útvonalat keresni.",
            "A rövidebb út túl zsúfoltnak bizonyult, és a csapatnak menet közben kellett irányt váltania.",
        ),
    ),
}

CHOICE_BY_KEY = {
    phase_key: {choice.key: choice for choice in choices}
    for phase_key, choices in PHASE_CHOICES.items()
}
