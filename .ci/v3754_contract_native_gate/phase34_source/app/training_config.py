from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TrainingChoice:
    key: str
    label: str
    emoji: str
    outcome: str
    score_delta: int


@dataclass(frozen=True, slots=True)
class TrainingStage:
    title: str
    prompt: str
    choices: tuple[TrainingChoice, ...]
    exam: bool = False


@dataclass(frozen=True, slots=True)
class CourseDefinition:
    key: str
    name: str
    emoji: str
    category: str
    price: int
    retry_fee: int
    pass_score: int
    summary: str
    unlock_text: str
    qualification_name: str
    history_text: str
    stages: tuple[TrainingStage, ...]


def _choice(key: str, label: str, emoji: str, outcome: str, score_delta: int) -> TrainingChoice:
    return TrainingChoice(key, label, emoji, outcome, int(score_delta))


def _stage(title: str, prompt: str, *choices: TrainingChoice, exam: bool = False) -> TrainingStage:
    return TrainingStage(title, prompt, tuple(choices), exam=exam)


COURSES: dict[str, CourseDefinition] = {
    "driving_b": CourseDefinition(
        key="driving_b",
        name="B kategóriás jogosítvány",
        emoji="🚗",
        category="Jogosítványok",
        price=1_250_000,
        retry_fee=250_000,
        pass_score=7,
        summary="A hétköznapi autóvezetés alapja. Rövid, helyzetalapú felkészítés és forgalmi vizsga.",
        unlock_text="Szükséges a saját autó vezetéséhez, az autós városközi utazáshoz, a taxihoz és több sofőrfeladathoz.",
        qualification_name="B kategóriás jogosítvány",
        history_text="Sikeresen megszerezted a B kategóriás jogosítványt.",
        stages=(
            _stage(
                "Nedves út",
                "Esőben közelítesz egy zebrához. A járda szélén valaki a forgalmat figyeli, de még nem lépett le.",
                _choice("early_margin", "Elveszem a gázt, ellenőrzöm a tükröket és fékkészenlétbe kerülök", "🪞", "Több időd maradt reagálni, miközben a mögöttes forgalmat is figyelted.", 3),
                _choice("steady_ready", "Tartom a tempót, de közelebb viszem a lábam a fékhez", "🦶", "A helyzet kezelhető maradt, de kevés tartalékod lett volna egy hirtelen átkelésnél.", 0),
                _choice("visible_slow", "Korábban lassítok, hogy egyértelmű legyen: számítok az átkelésre", "🚦", "Jól olvashatóvá tetted a szándékodat, bár a lassítás a szükségesnél valamivel korábban kezdődött.", 2),
            ),
            _stage(
                "Szűk utca",
                "Parkoló autók között szemből érkezik egy jármű. Előtted van egy szélesebb rész, mögötted pedig már jönnek mások is.",
                _choice("claim_gap", "A szélesebb résznél félrehúzódom és ott engedem el", "↘️", "A találkozást kiszámíthatóan oldottad meg, anélkül hogy a szűk részen kellett volna centizni.", 3),
                _choice("creep_center", "Lassan továbbgurulok, és menet közben döntöm el, ki fér el", "↔️", "Mindketten lassítottatok, de a döntés későre maradt és kevés hely maradt korrigálni.", 0),
                _choice("hold_position", "Megállok még a szűkület előtt, és jelzem, hogy elengedem", "✋", "Biztonságosan oldottad meg, bár a mögötted érkezőknek is alkalmazkodniuk kellett.", 2),
            ),
            _stage(
                "Sárgára vált",
                "Közepes tempóval közelítesz egy lámpához, ami sárgára vált. Mögötted egy autó a megszokottnál közelebb jön.",
                _choice("mirror_brake", "Tükörből ellenőrzöm a mögöttem jövőt, majd határozottan, de nem vészfékezve megállok", "🛑", "A megállást úgy készítetted elő, hogy a mögötted haladónak is maradt reakcióideje.", 3),
                _choice("commit", "Mivel közel van mögöttem, inkább egyenletesen áthaladok", "➡️", "Nem okoztál hirtelen fékezést, de a döntésed túl sokat bízott a lámpaváltás pontos időzítésére.", 0),
                _choice("soft_then_decide", "Azonnal elveszem a gázt, és a rendelkezésre álló távolság alapján döntök a megállásról", "⚖️", "Jó tartalékot teremtettél, de a végső döntést később kellett meghoznod.", 2),
            ),
            _stage(
                "Forgalmi vizsga",
                "Későn veszed észre, hogy a navigáció szerint már az előző kereszteződésnél le kellett volna fordulnod. A következő sávváltás még fizikailag lehetséges, de szűk a hely.",
                _choice("reroute", "Továbbmegyek és hagyom újratervezni az útvonalat", "🧭", "Nem próbáltad egy késői manőverrel kijavítani a navigációs hibát.", 3),
                _choice("signal_merge", "Indexelek, és ha valaki helyet hagy, még besorolok", "🔀", "A manőver nem lett szabálytalan, de a vizsgáztató szerint felesleges nyomást tettél egy már elmulasztott kanyar miatt.", 0),
                _choice("pull_plan", "A következő szabályos helyen félreállok egy pillanatra és újratervezek", "🅿️", "Kontrolláltan rendezted a helyzetet, viszont a forgalomból való ki- és visszaállás plusz manővert igényelt.", 2),
                exam=True,
            ),
        ),
    ),
    "forklift": CourseDefinition(
        key="forklift",
        name="Targoncavezetői képzés",
        emoji="🏗️",
        category="Szakmai képzések",
        price=650_000,
        retry_fee=130_000,
        pass_score=7,
        summary="Raktári és logisztikai munkákhoz használható gyakorlati képesítés, rövid záróvizsgával.",
        unlock_text="Targoncás és magasabb felelősségű raktári/logisztikai munkákhoz nyit hozzáférést.",
        qualification_name="Targoncavezetői képesítés",
        history_text="Sikeresen megszerezted a targoncavezetői képesítést.",
        stages=(
            _stage(
                "Rakomány átvétele",
                "A raklap fóliája sérült, a felső sor enyhén megdőlt. A műszak pörög, mögötted már vár a következő raklap.",
                _choice("inspect_secure", "Félreteszem, ellenőrzöm a stabilitását, és csak utána veszem fel", "🔎", "Kiderült, hogy egy doboz valóban elmozdult; még emelés előtt sikerült rendezni.", 3),
                _choice("low_test", "Nagyon alacsonyan megemelem pár centire, hogy lássam, tart-e", "↕️", "A rakomány nem borult meg, de az oktató szerint az ellenőrzést már az emelés előtt le kellett volna zárni.", 0),
                _choice("repack", "Rögzítést kérek, közben átveszem a következő feladat adatait", "🧰", "Nem állt meg teljesen a munka, és a bizonytalan rakományt is stabilizálták.", 2),
            ),
            _stage(
                "Csarnokforgalom",
                "Egy gyalogos kilép a polcsorok közül a kijelölt útvonalad közelében. Mögötted egy másik targonca közeledik.",
                _choice("controlled_stop", "Megállok, jelzek, és csak akkor indulok, amikor a gyalogos elhagyta a zónát", "✋", "A gépet és a mögöttes forgalmat is kontroll alatt tartottad.", 3),
                _choice("horn_crawl", "Dudálok és lépésben továbbgurulok, hogy ne torlódjon fel a sor", "📣", "A gyalogos észrevett, de a mozgó gép mellett túl kevés tér maradt egy váratlan irányváltáshoz.", 0),
                _choice("yield_space", "Megállok kissé hátrébb, hogy a gyalogosnak egyértelmű útvonala legyen", "↩️", "Nagyobb helyet hagytál, viszont a mögötted érkezőnek is meg kellett állnia.", 2),
            ),
            _stage(
                "Vak kereszteződés",
                "Magas rakománnyal olyan csarnokkereszteződéshez érsz, ahol a rakomány miatt oldalra alig látsz.",
                _choice("spotter", "Megállok és segítséget kérek a belátáshoz", "🤝", "A kereszteződést teljes belátással tudtad megkezdeni.", 3),
                _choice("creep_horn", "Jelzek, majd nagyon lassan előregurulok, amíg ki nem látok", "👀", "Fokozatosan szereztél belátást; a helyzet kezelhető maradt, de a gép már részben belógott a kereszteződésbe.", 1),
                _choice("angle_load", "Kicsit elfordulok, hogy a rakomány mellett jobb legyen a rálátás", "↪️", "Jobban láttál, de a rakomány oldalkitérése miatt a manőver szűkebb lett a kelleténél.", 0),
            ),
            _stage(
                "Záró gyakorlat",
                "Egy sürgős, magas rakományt kell a másik csarnokba vinned. Indulás után enyhe oldalirányú mozgást érzel a raklapon.",
                _choice("lower_resecure", "Megállok, leengedem és újra ellenőrzöm a rögzítést", "🧱", "A felső sor egyik eleme meglazult; a hibát még menet közbeni elmozdulás előtt rendezted.", 3),
                _choice("slow_finish", "Visszaveszek a tempóból és alacsonyan tartva befejezem a rövid utat", "🐢", "A rakomány célba ért, de a vizsgáztató szerint a meglazulás okát indulás előtt kellett volna tisztázni.", 0),
                _choice("escort", "Megkérek valakit, hogy kísérjen és figyelje a rakományt, amíg lassan visszaviszem a rögzítőponthoz", "👷", "A hibás rakomány mozgását kontroll alatt tartva jutottál vissza az ellenőrzési ponthoz.", 2),
                exam=True,
            ),
        ),
    ),
    "security": CourseDefinition(
        key="security",
        name="Vagyonőri képzés",
        emoji="🛡️",
        category="Szakmai képzések",
        price=900_000,
        retry_fee=180_000,
        pass_score=7,
        summary="Beléptetés, konfliktuskezelés és objektumvédelem helyzetalapú képzése záróvizsgával.",
        unlock_text="Biztonsági őri, őrzési és rendezvénybiztosítási munkákhoz nyit hozzáférést.",
        qualification_name="Vagyonőri képesítés",
        history_text="Sikeresen megszerezted a vagyonőri képesítést.",
        stages=(
            _stage(
                "Beléptetés",
                "Egy ideges látogató azt mondja, bent várják, de nincs nála érvényes belépő. A recepción közben sor kezd kialakulni.",
                _choice("verify_hold", "Megkérem, hogy várjon mellettem, és közben ellenőrzöm az illetékesnél", "📞", "A belépési szabály megmaradt, miközben a helyzet sem fajult vitává.", 3),
                _choice("lobby_wait", "Beengedem a recepciós előtérbe, és ott kezdem el ellenőrizni", "🛋️", "Gyorsabban haladt a sor, de az ellenőrizetlen látogató már a belső előtérbe került.", 0),
                _choice("supervisor", "Félreállítom a sortól és a műszakvezetőt kérem az ellenőrzésre", "🎧", "Az ellenőrzés szabályosan megtörtént, bár egy másik kollégát is bevontál.", 2),
            ),
            _stage(
                "Talált belépőkártya",
                "Egy dolgozói belépőkártyát találsz a folyosón. A név alapján az illető ma szolgálatban van.",
                _choice("report_disable", "Jelzem a központnak és kérem a kártya ideiglenes tiltását", "🔒", "A kártya addig sem maradt használható, amíg a tulajdonosát keresték.", 3),
                _choice("secure_search", "Magamnál tartom, és rádión megpróbálom elérni a tulajdonost", "📻", "A kártya biztonságban volt, de a rendszerben továbbra is aktív maradt.", 1),
                _choice("desk_later", "Beteszem a szolgálati pultra, és a következő kör után leadom", "🗃️", "Nem veszett el, viszont egy ideig dokumentálatlanul és aktívan maradt.", 0),
            ),
            _stage(
                "Éjszakai riasztás",
                "Zárás után mozgásérzékelő jelez egy raktári részen. A kameraképen csak egy nyitott ajtó széle látszik.",
                _choice("secure_backup", "Biztosítom a kijáratot és társat kérek az ellenőrzéshez", "🚧", "A helyszínt úgy kezdtétek ellenőrizni, hogy közben a kijutási útvonal is felügyelet alatt maradt.", 3),
                _choice("camera_first", "Előbb végignézem a környező kamerákat, majd az információ alapján indulok", "📹", "Több információval indultál, de a helyszín fizikai biztosítása később kezdődött meg.", 2),
                _choice("door_check", "A folyosóról óvatosan benézek, mielőtt másokat riasztok", "🔦", "Gyorsan szereztél képet a helyzetről, de egyedül kerültél közel az ismeretlen forráshoz.", 0),
            ),
            _stage(
                "Záró helyzet",
                "Egy rendezvényen egy feldúlt vendég nem akarja elhagyni a lezárt részt. Hangos, de még nem támad senkire, a közelben több civil áll.",
                _choice("distance_support", "Távolságot tartok, felszólítom, és közben társat kérek a civilek eltereléséhez", "🗣️", "A konfliktus nem kapott új közönséget, és volt támogatásod, mire közelebb kellett lépni.", 3),
                _choice("escort_now", "Odamegyek és azonnal megpróbálom kivezetni, mielőtt jobban felhúzza magát", "🚶", "A gyors fellépés növelte a fizikai ellenállás esélyét, miközben civilek is közel maradtak.", -1),
                _choice("supervisor_talk", "A kijárat felé terelem a beszélgetést, és közben a műszakvezetőt kérem oda", "🎧", "A helyzet lassabban oldódott, de nem kellett egyedül döntened a következő lépésről.", 2),
                exam=True,
            ),
        ),
    ),
    "hospitality": CourseDefinition(
        key="hospitality",
        name="Vendéglátói alapképzés",
        emoji="🍽️",
        category="Szakmai képzések",
        price=750_000,
        retry_fee=150_000,
        pass_score=7,
        summary="Pörgős vendégtéri helyzetek, rendeléskezelés és vendégkommunikáció rövid záróvizsgával.",
        unlock_text="Vendéglátói, rendezvényes és magasabb felelősségű szolgáltatói munkákhoz nyit hozzáférést.",
        qualification_name="Vendéglátói alapképzés",
        history_text="Sikeresen elvégezted a vendéglátói alapképzést.",
        stages=(
            _stage(
                "Csúcsidő",
                "Egyszerre több asztal jelez, miközben egy rendelés már késik és a konyha is leterhelt.",
                _choice("coordinate_update", "Egyeztetek a konyhával, majd röviden jelzem az érintett asztaloknak a várakozást", "🤝", "A konyha és a vendégek is ugyanazt az információt kapták, így kevesebb új kérdés keletkezett.", 3),
                _choice("oldest_first", "A legrégebb óta váró rendelést viszem végig először, a többieknek menet közben szólok", "🧾", "A legnagyobb csúszás csökkent, de néhány asztal csak később kapott pontos tájékoztatást.", 2),
                _choice("keep_flow", "Folytatom a kész rendelések kivitelét, amíg a késő tétel meg nem érkezik", "🍽️", "A terem mozgásban maradt, viszont a késő rendelés vendége sokáig nem kapott visszajelzést.", 0),
            ),
            _stage(
                "Ételérzékenység",
                "A vendég azt kérdezi, biztosan nem tartalmaz-e számára problémás összetevőt egy fogás. A konyha éppen csúcsidőben dolgozik.",
                _choice("kitchen_verify", "Ellenőrzöm a receptúrát és a konyhával is megerősíttetem", "🔎", "Biztos információt kaptál az összetevőkről és az elkészítés körülményeiről is.", 3),
                _choice("menu_then_kitchen", "Átnézem a jelöléseket, majd csak a bizonytalan részletre kérdezek rá a konyhán", "📋", "Gyorsabban jutottál válaszhoz, és a kritikus részletet is ellenőrizted.", 2),
                _choice("simple_recommend", "A tapasztalatod alapján inkább egy egyszerűbb fogást ajánlasz, amit általában ilyen esetben kérnek", "🥗", "Az alternatíva ésszerűnek tűnt, de az összetevőkről továbbra sem volt ellenőrzött információd.", -1),
            ),
            _stage(
                "Hibás rendelés",
                "Egy vendég ingerülten jelzi, hogy nem azt kapta, amit rendelt. A blokk és a konyhai cetli sem teljesen egyértelmű.",
                _choice("confirm_replace", "Visszaellenőrzöm a rendelést, elismerem a problémát és elindítom a cserét", "🔄", "A vendég gyorsan kapott konkrét megoldást, miközben a hiba forrását is ellenőrizted.", 3),
                _choice("manager_check", "Szólok a műszakvezetőnek, hogy együtt tisztázzuk a rendelést", "👔", "Biztos döntés született, de a vendégnek tovább kellett várnia a megoldásra.", 2),
                _choice("receipt_first", "Előbb végigveszem vele a blokkot, hogy biztosan kiderüljön, hol csúszott el", "🧾", "A vita tárgya tisztább lett, de az ingerült vendég előbb magyarázatot kapott, mint megoldást.", 0),
            ),
            _stage(
                "Záró műszak",
                "Egy nagyobb asztal egyszerre kér számlát, közben egy másik vendég reklamál, és a konyha szól, hogy az egyik kifutó fogás elfogyott.",
                _choice("triage", "Röviden visszajelzek mindhárom helyzetre, a számlát elindítom, majd a reklamációt kezelem és alternatívát egyeztetek", "🗂️", "Minden érintett tudta, mi történik, miközben a feladatokat sürgősség szerint rendezted.", 3),
                _choice("complaint_first", "A reklamációt oldom meg teljesen, utána foglalkozom a többivel", "💬", "A konfliktus gyorsan lezárult, de a többi asztal visszajelzés nélkül várt tovább.", 0),
                _choice("delegate_bill", "A számlát átadom egy kollégának, én pedig a reklamációt és az elfogyott fogás pótlását intézem", "🤲", "Jól osztottad meg a terhelést, feltéve hogy a kolléga valóban át tudta venni a számlázást.", 2),
                exam=True,
            ),
        ),
    ),
}

COURSE_KEYS: tuple[str, ...] = tuple(COURSES)


def course(key: str) -> CourseDefinition:
    try:
        return COURSES[str(key)]
    except KeyError as exc:
        raise ValueError("Ez a képzés nem található.") from exc


def category_courses(category: str) -> tuple[CourseDefinition, ...]:
    return tuple(item for item in COURSES.values() if item.category == category)
