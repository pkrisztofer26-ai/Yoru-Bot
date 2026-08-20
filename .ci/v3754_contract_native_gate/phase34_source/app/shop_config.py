from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ShopItemSpec:
    item_id: str
    name: str
    description: str
    emoji: str
    rarity: str
    category: str
    price: int
    aliases: tuple[str, ...] = ()
    shop_visible: bool = True
    sellable: bool = True
    usable: bool = False
    market_asset: bool = False


CATEGORY_LABELS = {
    "all": ("🛒", "Minden"),
    "game": ("🎮", "Játékkellékek"),
    "lootbox": ("📦", "Ládák"),
    "utility": ("🧰", "Hasznos tárgyak"),
    "personal": ("🧍", "Személyes tárgyak"),
}

# A rarity belső technikai adat marad. A játékos csak természetes magyar
# kategórianevet lát, nem Common/Rare/Epic/Mythic szinteket.
RARITY_LABELS = {
    "common": ("⚪", "Általános"),
    "rare": ("🔵", "Ritka"),
    "epic": ("🟣", "Kiemelt"),
    "legendary": ("🟡", "Exkluzív"),
    "mythic": ("🔴", "Különleges"),
}


ITEMS: dict[str, ShopItemSpec] = {
    "lottery_ticket": ShopItemSpec(
        "lottery_ticket", "Kaparós sorsjegy",
        "Egyszer használható kaparós. A nyeremény véletlenszerű, és nem garantált. Kaparás: /scratch vagy !sorsjegy.",
        "🎟️", "common", "game", 25_000,
        ("sorsjegy", "kaparos", "kaparós", "jegy", "scratch"), usable=False,
    ),
    "chicken": ShopItemSpec(
        "chicken", "Harci csirke",
        "A Harci csirke játék nevezési kelléke. Vereségnél a csirke elveszhet.",
        "🐔", "common", "game", 50_000,
        ("csirke", "harcicsirke", "chicken"),
    ),
    "rob_shield": ShopItemSpec(
        "rob_shield", "Rablásvédelem",
        "Egyszer automatikusan megvéd egy sikeres játékosrablástól, majd elhasználódik.",
        "🛡️", "rare", "utility", 1_000_000,
        ("rablásvédelem", "rablasvedelem", "pajzs", "shield"),
    ),
    "lucky_charm": ShopItemSpec(
        "lucky_charm", "Szerencsehozó",
        "A következő ládanyitásnál két kimenet közül a kedvezőbb marad meg.",
        "🍀", "epic", "utility", 250_000,
        ("szerencsehozo", "szerencsehozó", "charm", "lucky"),
    ),

    # Személyes / státusztárgyak. Ezek nem adnak rejtett income vagy sikerbónuszt:
    # a céljuk, hogy legyen mire költeni és mit gyűjteni a karakter körül.
    "used_phone": ShopItemSpec(
        "used_phone", "Használt okostelefon",
        "Egyszerű személyes telefon a karaktered mindennapjaihoz.",
        "📱", "common", "personal", 180_000,
        ("telefon", "hasznalttelefon", "használttelefon", "phone"),
    ),
    "premium_phone": ShopItemSpec(
        "premium_phone", "Prémium okostelefon",
        "Újabb, drágább telefon azoknak, akik már nem a túlélőszettet hordják.",
        "📱", "rare", "personal", 650_000,
        ("premiumtelefon", "prémiumtelefon", "mobil"),
    ),
    "premium_headphones": ShopItemSpec(
        "premium_headphones", "Prémium fejhallgató",
        "Minőségi fejhallgató személyes használatra.",
        "🎧", "rare", "personal", 420_000,
        ("fejhallgato", "fejhallgató", "headphones"),
    ),
    "ultrabook": ShopItemSpec(
        "ultrabook", "Prémium laptop",
        "Könnyű, erős laptop munkához és hétköznapi használatra.",
        "💻", "rare", "personal", 950_000,
        ("laptop", "notebook", "ultrabook"),
    ),
    "camera": ShopItemSpec(
        "camera", "Fényképezőgép",
        "Komolyabb fényképezőgép objektívvel és alap felszereléssel.",
        "📷", "rare", "personal", 1_400_000,
        ("kamera", "fenykepezogep", "fényképezőgép", "camera"),
    ),
    "gaming_pc": ShopItemSpec(
        "gaming_pc", "Erős asztali gép",
        "Nagy teljesítményű asztali gép teljes személyes szettel.",
        "🖥️", "epic", "personal", 2_400_000,
        ("gamerpc", "gamingpc", "pc"),
    ),
    "designer_outfit": ShopItemSpec(
        "designer_outfit", "Márkás szett",
        "Drága ruhaszett és kiegészítők azoknak, akik szeretnek látszani is.",
        "🧥", "epic", "personal", 3_800_000,
        ("designer", "szett", "ruha"),
    ),
    "gold_chain": ShopItemSpec(
        "gold_chain", "Aranylánc",
        "Feltűnő személyes ékszer, már egyértelmű státusztárgy.",
        "⛓️", "epic", "personal", 6_500_000,
        ("aranylanc", "aranylánc", "lanc", "lánc"),
    ),
    "luxury_watch": ShopItemSpec(
        "luxury_watch", "Luxusóra",
        "Komolyabb karóra, ami már inkább státusz, mint időmérés.",
        "⌚", "legendary", "personal", 18_000_000,
        ("luxusora", "luxusóra", "ora", "óra"),
    ),
    "collector_watch": ShopItemSpec(
        "collector_watch", "Limitált karóra",
        "Kis szériás gyűjtői darab a tehetősebb karaktereknek.",
        "🕰️", "legendary", "personal", 55_000_000,
        ("limitaltora", "limitáltóra", "gyujtoiora", "gyűjtőióra"),
    ),
    "art_piece": ShopItemSpec(
        "art_piece", "Gyűjtői műtárgy",
        "Ritkább dekor- és gyűjtői darab komolyabb vagyon mellett.",
        "🖼️", "mythic", "personal", 120_000_000,
        ("mutargy", "műtárgy", "art"),
    ),
    "custom_jewelry": ShopItemSpec(
        "custom_jewelry", "Egyedi ékszer",
        "Megrendelésre készült luxusékszer a legvagyonosabb gyűjtőknek.",
        "💍", "mythic", "personal", 250_000_000,
        ("ekszer", "ékszer", "egyediekszer", "egyediékszer"),
    ),

    "common_crate": ShopItemSpec(
        "common_crate", "Alap láda",
        "Kisebb tétű pénzláda visszafogottabb szórással.",
        "📦", "common", "lootbox", 100_000,
        ("alaplada", "alapláda", "commonlada", "common"), usable=True,
    ),
    "rare_crate": ShopItemSpec(
        "rare_crate", "Prémium láda",
        "Drágább pénzláda, nagyobb lehetséges kifizetéssel.",
        "🔷", "rare", "lootbox", 400_000,
        ("premiumlada", "prémiumláda", "ritkalada", "rare"), usable=True,
    ),
    "epic_crate": ShopItemSpec(
        "epic_crate", "Elit láda",
        "Magasabb tétű láda ritkább, nagyobb nyereményekkel.",
        "🟣", "epic", "lootbox", 1_500_000,
        ("elitlada", "elitláda", "epiclada", "epic"), usable=True,
    ),
    # Ezek tudatosan nem normál bolti polctermékek. Dropból, Feketepiacról és
    # különleges lehetőségekből kerülhetnek a játékoshoz.
    "mystery_box": ShopItemSpec(
        "mystery_box", "Rejtélyes csomag",
        "Nem szokványos forrásból szerezhető, nagy szórású pénzláda.",
        "🕳️", "rare", "lootbox", 200_000,
        ("rejtelyes", "rejtélyes", "mystery"), shop_visible=False, usable=True,
    ),
    "legendary_crate": ShopItemSpec(
        "legendary_crate", "Legendás láda",
        "Ritka forrásból szerezhető nagy értékű láda.",
        "🟡", "legendary", "lootbox", 5_000_000,
        ("legendaslada", "legendásláda", "legendary"), shop_visible=False, usable=True,
    ),
    "mythic_crate": ShopItemSpec(
        "mythic_crate", "Mitikus láda",
        "Különleges forrásból szerezhető, extrém nagy szórású láda.",
        "🔴", "mythic", "lootbox", 15_000_000,
        ("mitikuslada", "mitikusláda", "mythic"), shop_visible=False, usable=True,
    ),
    "silver": ShopItemSpec(
        "silver", "Ezüst", "Napi árfolyamos befektetés.", "🥈", "rare", "market",
        100_000, ("ezust", "ezüst", "silver"), shop_visible=False,
        market_asset=True,
    ),
    "gold": ShopItemSpec(
        "gold", "Arany", "Napi árfolyamos befektetés.", "🪙", "epic", "market",
        750_000, ("arany", "gold"), shop_visible=False, market_asset=True,
    ),
    "diamond": ShopItemSpec(
        "diamond", "Gyémánt", "Drágább, ritkább árupiaci eszköz nagyobb napi mozgással.", "💎", "legendary", "market",
        3_000_000, ("gyemant", "gyémánt", "diamond"), shop_visible=False,
        market_asset=True,
    ),
    "bond_fund": ShopItemSpec(
        "bond_fund", "Kötvényalap", "Nyugodtabb ármozgású befektetési alap, kisebb vételi és visszaváltási különbséggel.", "📜", "rare", "market",
        1_000_000, ("kotveny", "kötvény", "kotvenyalap", "kötvényalap", "bond"), shop_visible=False,
        market_asset=True,
    ),
    "duna_index": ShopItemSpec(
        "duna_index", "Duna részvénykosár", "Több vállalatot összefogó, kiegyensúlyozott részvénykosár.", "📊", "epic", "market",
        3_250_000, ("duna", "dunaindex", "reszveny", "részvény", "index"), shop_visible=False,
        market_asset=True,
    ),
    "real_estate_fund": ShopItemSpec(
        "real_estate_fund", "Ingatlanalap", "Nagyobb belépőjű, közepesen mozgó befektetési alap.", "🏢", "epic", "market",
        8_500_000, ("ingatlan", "ingatlanalap", "realestate"), shop_visible=False,
        market_asset=True,
    ),
    "tech_fund": ShopItemSpec(
        "tech_fund", "Technológiai alap", "Erősebben hullámzó, magasabb belépőjű technológiai befektetés.", "💻", "legendary", "market",
        18_000_000, ("tech", "technologia", "technológia", "techalap"), shop_visible=False,
        market_asset=True,
    ),
    "crypto_index": ShopItemSpec(
        "crypto_index", "Kriptoindex", "Nagyon erősen mozgó, magas tétű spekulatív befektetés.", "🪙", "mythic", "market",
        45_000_000, ("kripto", "crypto", "kriptoindex"), shop_visible=False,
        market_asset=True,
    ),
}


# Egyetlen bolti árlista az elsődleges forrás. Az economy_config ezt kompatibilitási
# nézetként importálja, ezért az item neve/ID-ja/ára nem él két külön configban.
SHOP_PRICES = {item_id: int(spec.price) for item_id, spec in ITEMS.items()}


def _normalize(value: str) -> str:
    return "".join(ch for ch in str(value).strip().lower().replace("-", "_").replace(" ", "_") if ch not in "'\"")


ALIASES: dict[str, str] = {}
for _item_id, _spec in ITEMS.items():
    ALIASES[_normalize(_item_id)] = _item_id
    ALIASES[_normalize(_spec.name)] = _item_id
    for _alias in _spec.aliases:
        ALIASES[_normalize(_alias)] = _item_id


def resolve_item_id(raw: str) -> str | None:
    return ALIASES.get(_normalize(raw))


def item_spec(item_id: str) -> ShopItemSpec | None:
    return ITEMS.get(str(item_id))


def catalog_rows() -> list[tuple[str, str, str, int, str, str, str]]:
    return [
        (spec.item_id, spec.name, spec.description, int(spec.price), spec.emoji, spec.rarity, spec.category)
        for spec in ITEMS.values()
    ]
