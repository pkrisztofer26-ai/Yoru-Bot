from __future__ import annotations

from dataclasses import dataclass, field


WORLD_CYCLE_HOURS = 8
WORLD_REFRESH_MINUTES = 15
WORLD_STORY_START_CHANCE = 0.55
WORLD_MAJOR_ACTIVITY_QUIET_MINUTES = 20

WORLD_NEWS_ENABLED_KEY = "world_news_enabled"
WORLD_NEWS_CHANNEL_KEY = "world_news_channel_id"
WORLD_NEWS_LAST_CYCLE_KEY = "world_news_last_cycle_id"
WORLD_NEWS_LAST_MESSAGE_KEY = "world_news_last_message_id"
WORLD_NEWS_LAST_MESSAGE_CHANNEL_KEY = "world_news_last_message_channel_id"
WORLD_NEWS_DEFAULT_ENABLED = False


@dataclass(frozen=True, slots=True)
class Situation:
    key: str
    emoji: str
    title: str
    summary: str
    job_multipliers_bp: dict[str, int] = field(default_factory=dict)
    business_multipliers_bp: dict[str, int] = field(default_factory=dict)
    illegal_attention_bonus: int = 0
    crime_reward_bp: int = 10000
    black_market_available: bool = False
    opportunity_jobs: tuple[str, ...] = ()
    major_activity: bool = False
    standalone_allowed: bool = True


@dataclass(frozen=True, slots=True)
class StoryBeat:
    key: str
    situation_key: str
    update: str
    next_beats: tuple[str, ...] = ()
    major_activity: bool = False


@dataclass(frozen=True, slots=True)
class WorldStory:
    key: str
    emoji: str
    title: str
    opening: str
    start_beat: str
    beats: tuple[StoryBeat, ...]

    def beat(self, beat_key: str) -> StoryBeat | None:
        return next((beat for beat in self.beats if beat.key == beat_key), None)


NATIONAL_SITUATIONS: tuple[Situation, ...] = (
    Situation(
        "regional_orders",
        "📋",
        "Megugrottak a rövid határidejű megrendelések",
        "Több ágazatban egyszerre jelentek meg rövid határidejű feladatok, ezért a raktári és futármunkák iránt is nőtt a kereslet.",
        job_multipliers_bp={"casual": 10400, "warehouse": 10400, "courier": 10500, "shelf_stocker": 10300},
        business_multipliers_bp={"Logisztika": 10800, "Kereskedelem": 10400, "Technológia": 10200},
        opportunity_jobs=("warehouse", "courier", "shelf_stocker"),
    ),
    Situation(
        "logistics_pressure",
        "📦",
        "Megtorpant az országos logisztika",
        "Több helyen torlódnak a szállítmányok, ezért sürgősebbé váltak a raktári és futármegbízások.",
        job_multipliers_bp={"casual": 10300, "warehouse": 10800, "courier": 11200, "shelf_stocker": 10400},
        business_multipliers_bp={"Logisztika": 11200, "Kereskedelem": 9600, "Vendéglátás": 9800},
        opportunity_jobs=("warehouse", "courier", "shelf_stocker"),
        major_activity=True,
    ),
    Situation(
        "travel_wave",
        "🚕",
        "Megugrott az utazási forgalom",
        "A nagyobb városok között és a helyi közlekedésben is több a fuvar, mint egy átlagos napon.",
        job_multipliers_bp={"taxi": 11200, "courier": 10500},
        business_multipliers_bp={"Turizmus": 11200, "Vendéglátás": 10800, "Szórakozás": 10600},
        opportunity_jobs=("taxi", "courier"),
        major_activity=True,
    ),
    Situation(
        "labour_shortage",
        "🦺",
        "Munkaerőhiány több ágazatban",
        "Több helyen hirtelen emberhiány alakult ki, ezért a rövid műszakokat gyorsabban töltik fel.",
        job_multipliers_bp={"casual": 10800, "warehouse": 11000, "courier": 10600, "taxi": 10600, "shelf_stocker": 10600, "cleaner": 10600, "kitchen_helper": 10700, "factory_operator": 10800, "forklift_operator": 10800, "security_guard": 10400, "hospitality": 10600},
        business_multipliers_bp={"Szolgáltatás": 10600, "Logisztika": 10500},
        opportunity_jobs=("warehouse", "courier", "taxi", "shelf_stocker", "cleaner", "kitchen_helper", "factory_operator"),
    ),
    Situation(
        "police_operation",
        "🚓",
        "Országos rendőrségi akció",
        "Több városban fokozottabb ellenőrzések zajlanak; a feltűnő illegális ügyek könnyebben hagynak nyomot, miközben több helyen plusz őrzést kérnek.",
        job_multipliers_bp={"security_guard": 10800},
        illegal_attention_bonus=4,
        crime_reward_bp=9200,
        opportunity_jobs=("security_guard",),
        major_activity=True,
    ),
    Situation(
        "scarce_special_goods",
        "🌑",
        "Eltűnt néhány ritkább áru a megszokott helyekről",
        "Bizonyos ritkább termékeket most nehezebb hivatalos úton beszerezni, ezért egyre több üzlet kötődik személyes kapcsolatokhoz és zárt körökhöz.",
        black_market_available=True,
    ),
    Situation(
        "underground_demand",
        "🌒",
        "Megmozdult a feketegazdaság",
        "Több kétes felvásárló jelent meg egyszerre, ezért az illegális ügyekből most többet lehet kihozni, de a kockázat ettől nem tűnt el.",
        crime_reward_bp=10800,
    ),
    Situation(
        "logistics_recovery",
        "🚛",
        "Lassan oldódik a szállítási torlódás",
        "A legsürgősebb rakományok elindultak, de a raktárak és futárok még mindig a felgyűlt lemaradást dolgozzák le.",
        job_multipliers_bp={"warehouse": 10400, "courier": 10500, "shelf_stocker": 10200},
        business_multipliers_bp={"Logisztika": 10300, "Kereskedelem": 10200},
        opportunity_jobs=("warehouse", "courier"),
        standalone_allowed=False,
    ),
    Situation(
        "underground_cooldown",
        "🌘",
        "Visszahúzódtak a kétes felvásárlók",
        "A korábbi rendőri mozgás után több zárt kör megszakította a nyílt üzletelést; az alvilági piac átmenetileg óvatosabb lett.",
        crime_reward_bp=9500,
        standalone_allowed=False,
    ),
    Situation(
        "service_pressure",
        "🧳",
        "Túlterheltek a szolgáltatók",
        "A megugrott utasforgalom után több városban egyszerre lett kevés a sofőr, a futár és a vendéglátós kisegítő.",
        job_multipliers_bp={"taxi": 11000, "courier": 10800, "kitchen_helper": 10700, "hospitality": 10800},
        business_multipliers_bp={"Turizmus": 10800, "Vendéglátás": 10900, "Szolgáltatás": 10700},
        opportunity_jobs=("taxi", "courier", "kitchen_helper", "hospitality"),
        major_activity=True,
    ),
    Situation(
        "travel_normalizing",
        "🚌",
        "Csillapodik az utazási hullám",
        "A kiugró forgalom kezd visszaállni a megszokott szintre, de néhány városban még maradtak sürgős fuvarok és elmaradt kiszállítások.",
        job_multipliers_bp={"taxi": 10300, "courier": 10300},
        business_multipliers_bp={"Turizmus": 10300, "Vendéglátás": 10200},
        opportunity_jobs=("taxi", "courier"),
        standalone_allowed=False,
    ),
)


WORLD_STORIES: tuple[WorldStory, ...] = (
    WorldStory(
        key="supply_chain_wave",
        emoji="🚚",
        title="Szállítási lánc nyomás alatt",
        opening="A rövid határidejű megrendelésekből országos szállítási hullám alakult ki.",
        start_beat="orders",
        beats=(
            StoryBeat(
                "orders", "regional_orders",
                "A kereskedők és beszállítók egyszerre kezdtek sürgős fuvarokat keresni.",
                ("bottleneck",), True,
            ),
            StoryBeat(
                "bottleneck", "logistics_pressure",
                "A korábbi rendelési hullám most már több útvonalon és raktárban torlódást okoz.",
                ("workforce", "recovery"), True,
            ),
            StoryBeat(
                "workforce", "labour_shortage",
                "A lemaradás ledolgozásához több helyen hirtelen plusz embereket keresnek.",
                ("recovery",), True,
            ),
            StoryBeat(
                "recovery", "logistics_recovery",
                "A legsürgősebb szállítmányok elindultak, és a torlódás fokozatosan oldódik.",
            ),
        ),
    ),
    WorldStory(
        key="underworld_sweep",
        emoji="🚓",
        title="Felforrósodott az alvilági piac",
        opening="Több városban egyszerre jelentek meg kétes felvásárlók és közvetítők.",
        start_beat="demand",
        beats=(
            StoryBeat(
                "demand", "underground_demand",
                "Az alvilági kereslet gyorsan nőtt, és egyre több feltűnő üzlet köttetett.",
                ("response",), False,
            ),
            StoryBeat(
                "response", "police_operation",
                "A feltűnő mozgásra országos rendőrségi akció indult több nagyvárosban.",
                ("scarcity", "cooldown"), True,
            ),
            StoryBeat(
                "scarcity", "scarce_special_goods",
                "A razziák után néhány ritkább áru eltűnt a megszokott csatornákról, és zárt körökbe szorult.",
                ("cooldown",), True,
            ),
            StoryBeat(
                "cooldown", "underground_cooldown",
                "A nagyobb szereplők visszahúzódtak, a nyílt üzletelés pedig érezhetően lelassult.",
            ),
        ),
    ),
    WorldStory(
        key="travel_peak",
        emoji="🧳",
        title="Országos utazási hullám",
        opening="Több rendezvény és szezonális mozgás egyszerre növelte meg az országon belüli forgalmat.",
        start_beat="rush",
        beats=(
            StoryBeat(
                "rush", "travel_wave",
                "A nagyobb városokban egyszerre ugrott meg a személy- és csomagforgalom.",
                ("pressure",), True,
            ),
            StoryBeat(
                "pressure", "service_pressure",
                "A forgalmi hullám most már a sofőröket, futárokat és vendéglátóhelyeket is túlterheli.",
                ("workforce", "normalizing"), True,
            ),
            StoryBeat(
                "workforce", "labour_shortage",
                "Több szolgáltató rövid műszakokra keres plusz embereket, hogy utolérje magát.",
                ("normalizing",), False,
            ),
            StoryBeat(
                "normalizing", "travel_normalizing",
                "A kiugró forgalom csillapodik, és a legtöbb útvonalon kezd helyreállni a megszokott ritmus.",
            ),
        ),
    ),
)


CITY_SITUATIONS: dict[str, tuple[Situation, ...]] = {
    "miskolc": (
        Situation(
            "miskolc_industry_rush", "🏭", "Ipari hajrá Miskolcon",
            "Több üzemi és raktári megrendelés fut egyszerre, ezért a környéken felértékelődött a gyors rakodás és kiszállítás.",
            job_multipliers_bp={"warehouse": 11200, "courier": 10600, "factory_operator": 11000, "forklift_operator": 10800},
            business_multipliers_bp={"Logisztika": 11500, "Szolgáltatás": 10400},
            opportunity_jobs=("warehouse", "courier", "factory_operator", "forklift_operator"),
        ),
        Situation(
            "miskolc_delivery_gap", "🚚", "Fuvarhiány az északi városrészekben",
            "Több cím és üzlet vár kiszállításra, miközben kevés a szabad futár.",
            job_multipliers_bp={"courier": 11200, "shelf_stocker": 10300}, business_multipliers_bp={"Logisztika": 10800, "Kereskedelem": 10300}, opportunity_jobs=("courier", "shelf_stocker"),
        ),
        Situation(
            "miskolc_checks", "🚔", "Sűrűbb esti ellenőrzések",
            "A rendőrök több forgalmas környéken megjelentek, ezért a feltűnő utcai ügyek könnyebben felkeltik a figyelmet.",
            illegal_attention_bonus=4, crime_reward_bp=9300,
        ),
    ),
    "budapest": (
        Situation(
            "budapest_evening_flow", "🌃", "Erős esti forgalom Budapesten",
            "Sok az utas és a sürgős kézbesítés, a város több pontján egyszerre nőtt meg a fuvarigény.",
            job_multipliers_bp={"taxi": 11200, "courier": 10800, "kitchen_helper": 10600, "hospitality": 10800}, business_multipliers_bp={"Vendéglátás": 10800, "Szórakozás": 10800, "Média": 10400}, opportunity_jobs=("taxi", "courier", "kitchen_helper", "hospitality"),
        ),
        Situation(
            "budapest_business_event", "🏢", "Nagy üzleti rendezvény a fővárosban",
            "A rendezvény környékén megugrott a személy- és csomagforgalom.",
            job_multipliers_bp={"taxi": 10800, "courier": 10800, "cleaner": 10400}, business_multipliers_bp={"Technológia": 11000, "Média": 11000, "Szolgáltatás": 10600}, opportunity_jobs=("taxi", "courier", "cleaner"),
        ),
        Situation(
            "budapest_raids", "🚨", "Célzott razziák több kerületben",
            "A rendőrség több környéken célzott ellenőrzéseket tart; az illegális ügyek most könnyebben hagynak nyomot.",
            illegal_attention_bonus=5, crime_reward_bp=9000,
        ),
    ),
    "debrecen": (
        Situation(
            "debrecen_industry", "🏗️", "Új ipari megrendelések Debrecenben",
            "A környék raktáraiban és beszállítóinál hirtelen több munka jelent meg.",
            job_multipliers_bp={"warehouse": 11200, "courier": 10600, "shelf_stocker": 10600, "factory_operator": 10800, "forklift_operator": 10600}, business_multipliers_bp={"Kereskedelem": 10800, "Logisztika": 11000}, opportunity_jobs=("warehouse", "courier", "shelf_stocker", "factory_operator", "forklift_operator"),
        ),
        Situation(
            "debrecen_transport", "🚕", "Megugrott a városi fuvarforgalom",
            "Több rendezvény és érkező utas egyszerre terheli a városi közlekedést.",
            job_multipliers_bp={"taxi": 11000, "courier": 10500}, opportunity_jobs=("taxi", "courier"),
        ),
        Situation(
            "debrecen_checks", "👮", "Fokozott közúti ellenőrzések",
            "Több útvonalon sűrűbb ellenőrzések vannak, a feltűnő illegális ügyek nagyobb nyomot hagyhatnak.",
            illegal_attention_bonus=3, crime_reward_bp=9500,
        ),
    ),
    "eger": (
        Situation(
            "eger_tourism", "🍷", "Turistahullám Egerben",
            "Megteltek a belvárosi utcák; sok az utas, a rendelés és az utolsó pillanatos kiszállítás.",
            job_multipliers_bp={"taxi": 11400, "courier": 10800, "kitchen_helper": 10800, "hospitality": 11200, "cleaner": 10400}, business_multipliers_bp={"Turizmus": 11500, "Vendéglátás": 11400, "Szolgáltatás": 10600}, opportunity_jobs=("taxi", "courier", "kitchen_helper", "hospitality", "cleaner"),
        ),
        Situation(
            "eger_event_prep", "🎪", "Rendezvény-előkészületek Egerben",
            "A környék raktáraiból és vendéglátóhelyeiről folyamatosan viszik az árut a helyszínekre.",
            job_multipliers_bp={"warehouse": 10800, "courier": 11000, "kitchen_helper": 10600, "hospitality": 10800}, business_multipliers_bp={"Rendezvény": 11200, "Vendéglátás": 10800, "Logisztika": 10600}, opportunity_jobs=("warehouse", "courier", "kitchen_helper", "hospitality"),
        ),
        Situation(
            "eger_supply_rush", "🏨", "Szállodai utánpótlási hajrá Egerben",
            "Több szálláshely és vendéglátóhely egyszerre rendel utánpótlást, ezért a fuvar- és raktári feladatok megszaporodtak.",
            job_multipliers_bp={"warehouse": 10600, "courier": 10900, "taxi": 10400, "kitchen_helper": 10600, "hospitality": 10800},
            business_multipliers_bp={"Turizmus": 11000, "Vendéglátás": 11000, "Kereskedelem": 10400},
            opportunity_jobs=("courier", "warehouse", "taxi", "kitchen_helper", "hospitality"),
        ),
    ),
    "szeged": (
        Situation(
            "szeged_event_week", "🎤", "Rendezvényhét Szegeden",
            "A város több pontján programok futnak, ezért megugrott a taxi- és kiszállítási igény.",
            job_multipliers_bp={"taxi": 11100, "courier": 11000, "kitchen_helper": 10600, "hospitality": 10800}, business_multipliers_bp={"Szórakozás": 11200, "Vendéglátás": 10900, "Rendezvény": 11100}, opportunity_jobs=("taxi", "courier", "kitchen_helper", "hospitality"),
        ),
        Situation(
            "szeged_warehouse", "📦", "Raktári átcsoportosítás Szegeden",
            "Több kereskedő egyszerre mozgat készletet, ezért extra raktári és fuvarfeladatok jelentek meg.",
            job_multipliers_bp={"warehouse": 11200, "courier": 10600, "factory_operator": 10800, "shelf_stocker": 10400}, business_multipliers_bp={"Kereskedelem": 10800, "Logisztika": 11000}, opportunity_jobs=("warehouse", "courier", "factory_operator", "shelf_stocker"),
        ),
        Situation(
            "szeged_checks", "🚓", "Sűrűbb belvárosi ellenőrzések",
            "A belvárosban több járőr mozog, így a feltűnő illegális ügyek könnyebben felkeltik a figyelmet.",
            illegal_attention_bonus=3, crime_reward_bp=9500,
        ),
    ),
}


NATIONAL_BY_KEY = {item.key: item for item in NATIONAL_SITUATIONS}
NATIONAL_STANDALONE_SITUATIONS = tuple(item for item in NATIONAL_SITUATIONS if item.standalone_allowed)
WORLD_STORY_BY_KEY = {story.key: story for story in WORLD_STORIES}
WORLD_STORY_BEAT_BY_KEY = {
    story.key: {beat.key: beat for beat in story.beats}
    for story in WORLD_STORIES
}
CITY_BY_KEY = {
    city_key: {item.key: item for item in items}
    for city_key, items in CITY_SITUATIONS.items()
}
