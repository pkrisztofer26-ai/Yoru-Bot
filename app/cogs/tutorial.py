from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import discord
from discord.ext import commands, tasks

from app import tutorial_config as cfg
from app.cogs.settings import OwnedView, PagedGuildChannelSelect
from app.services.server_settings import ServerSettingsService
from app.ui import BRAND, GOLD, SUCCESS, base_embed


@dataclass(frozen=True, slots=True)
class TutorialSection:
    slug: str
    emoji: str
    title: str
    intro: str
    fields: tuple[tuple[str, str], ...]


# Player tutorial only. Keep this ordered from first login → late game.
PLAYER_SECTIONS: tuple[TutorialSection, ...] = (
    TutorialSection(
        "start", "🌙", "Első lépések • Innen indulj",
        "Ha most találkozol először Yoruval, ezt a sorrendet kövesd. Nem kell mindent egyszerre megtanulnod: a bot fő rendszerei egymásra épülnek.",
        (
            ("1️⃣ Nézd meg magad", "`!profile` megnyitja a teljes játékosprofilodat. Itt látod a Yoru Levelt, Activityt, statokat, inventoryt, achievementeket és később a komolyabb rendszereket is."),
            ("2️⃣ Vedd fel az ingyen rewardokat", "`!daily` • `!weekly` / `!wk` • `!monthly` / `!mo`. Ezek időszakos jutalmak, ezért érdemes rendszeresen felvenni őket."),
            ("3️⃣ Keress pénzt", "Kezdésnek `!work`, `!beg` és `!search`, vagy `!jobs` alatt aktív, tét nélküli műszakok. Ha már érted a kockázatot, jöhet `!crime`, `!rob` és a többi economy activity."),
            ("4️⃣ Tedd biztonságba", "`!bal` mutatja az egyenleged. `!dep all` beteszi a wallet pénzedet a bankba, `!with <összeg>` visszavesz belőle."),
            ("5️⃣ Fejlődj", "Chatelj, voice-olj, teljesíts questeket, építs Job Masteryt, gyűjts XP-t, itemeket és pénzt. A későbbi rendszerek — Prestige, Frakció, Biznisz, Nagy Meló — ezekre épülnek."),
            ("🧭 Ha elakadsz", "`!help` az interaktív parancssúgó. Ez a tutorial viszont nem csak parancslista: azt magyarázza el, hogy mit miért és mikor érdemes használni."),
        ),
    ),
    TutorialSection(
        "money-basics", "💰", "Pénz, wallet, bank és összegek",
        "Yoruban a wallet és a bank két külön hely. A legtöbb költés/fogadás a walletből történik; a bank külön tároló és több bankos rendszer alapja.",
        (
            ("👛 Wallet", "A közvetlenül elkölthető pénzed. `!bal` / `!balance` mutatja a wallet + bank állapotot."),
            ("🏦 Bank", "`!dep 250k` befizetés • `!dep all` minden wallet pénz befizetése • `!with 100k` kivét • `!with all` teljes kivét."),
            ("💸 Játékosnak utalás", "`!pay @tag 25k` közvetlen pénzküldés. Mindig ellenőrizd a taget és az összeget."),
            ("🔢 Rövid összegek", "A bot érti például: `25k`, `2m`, `1b`, `1t`, `1q`, valamint ahol támogatott, az `all` értéket is."),
            ("♾️ Late-game economy", "Nincs mesterséges 1 milliárdos plafon. A nagyobb late-game összegek is normálisan kezelhetők."),
        ),
    ),
    TutorialSection(
        "earning", "💼", "Pénzkeresés • Cooldown és kockázat",
        "Az economy parancsok nem egyformák: van biztosabb, lassabb pénzkeresés és magasabb kockázatú opció is. Mindegyik saját cooldownnal működik.",
        (
            ("🛠️ Work", "`!work` a legstabilabb alap pénzkereső. Cooldown után újra használható és progression/quest progresshez is kapcsolódhat."),
            ("🙏 Beg / 🔎 Search", "`!beg` kisebb jutalomforrás. `!search` pénz mellett ritka itemeket/ládákat is dobhat."),
            ("🚨 Crime", "`!crime` nagyobb sikerjutalmat adhat, de bukáskor komoly veszteség is jöhet. Ne úgy használd, mintha garantált profit lenne."),
            ("🥷 Rob", "`!rob @tag` másik játékos walletjét célozza, a bankját nem. Siker/bukás és hosszabb cooldown tartozik hozzá."),
            ("💋 Slut", "Kockázatos economy action saját siker/bukás táblával; ugyanúgy cooldownos, mint a többi munka."),
            ("⏱️ Cooldownok", "`!cd` / cooldown panel megmutatja, miből mennyi idő van még hátra. Ha egy parancsot rossz economy helyen használsz, Yoru törli és DM-ben jelzi a helyes csatornát/kategóriát."),
            ("📈 Kamat és Role Income", "`!interest` bankkamat felvétele • `!ri` Role Income lista • `!ci` / claim income a jogosult rangok után."),
        ),
    ),
    TutorialSection(
        "interactive-jobs", "🧰", "Interactive Jobs • Aktív pénzkeresés",
        "Ha a sima Work/Beg/Search cooldownon van, a Jobs rendszerben ténylegesen játszható műszakokkal építhetsz bankrollt. Nincs tét és nincs AFK payout; egy választott, befejezett műszak után az egész Jobs pool közös 2 órás cooldownra kerül.",
        (
            ("🧰 Jobs lobby", "`!jobs` vagy `/jobs panel` nyitja a központi panelt. Innen indul a Raktáros, Borsodi Lopkodás, Futár és Taxi."),
            ("📦 Raktáros", "5 körös memória/sequence műszak. A mozgó GIF után külön memóriaidőt kapsz, majd bőven van időd kiválasztani a helyes kombinációt. Combo + performance alapján nő a jutalom."),
            ("🔌 Borsodi Lopkodás", "5×5 grid, 7 keresés. A mezőkben scrap/elektronika/pénz/ritkább loot lehet. Járőrnél nem automatikus a bukás: scenario nyílik több döntéssel, eltérő risk/reward következménnyel."),
            ("🚚 Futár / 🚕 Taxi", "Több fuvaros műszak. Az útvonal csak az első döntés: minden fuvar közben scenario jön (pl. ellenőrzés, sérült csomag, rosszul lévő utas), és kb. 30 másodperced van választani. A döntések alakítják a payoutot és a performance ratinget."),
            ("🏅 Job Mastery", "Minden munkának külön Mastery Levelje van. A fejlődés főleg progression/content; az income bónusz szándékosan kicsi és plafonozott, hogy ne törje szét az economy-t."),
            ("🔒 Session safety", "Egy szerveren egyszerre egy aktív Interactive Job műszakod lehet. Scenario timeoutnál a biztonságos alapdöntés fut le; restart után a session felszabadul. Befejezett műszak után közös 2 órás cooldown indul; félbehagyott normál műszaknál 15 perc anti-reroll lock jár."),
        ),
    ),
    TutorialSection(
        "activity", "📈", "Activity • Chat és Voice fejlődés",
        "Az Activity külön fejlődési rendszer a normál Yoru Level mellett. A valódi közösségi aktivitást jutalmazza, anti-farm szabályokkal.",
        (
            ("💬 Chat Activity", "Minősített üzenetek Activity XP-t adnak. Rövid cooldown, duplicate/spam és command-farm védelem miatt ugyanazt ismételgetve nem lehet farmolni."),
            ("🎙️ Voice Activity", "Solo voice nem ad farmolható XP-t. Legalább 2 valódi tag kell, és AFK/deaf állapotok kizárhatják a percet."),
            ("🏅 Milestone rangok", "A szerver Activity szintekhez Discord rangokat rendelhet. Yoru a legmagasabb elért milestone rangot tartja meg rajtad."),
            ("👤 Hol látod?", "`!profile` Activity oldala mutatja a szintedet, XP-det, Chat XP-t, Voice XP-t, üzenetszámot és voice időt."),
            ("🏆 Ranglisták", "`!top activity` • `!top chat` • `!top voice`. Ezek read-only toplisták, ezért Generalban is használhatók."),
        ),
    ),
    TutorialSection(
        "profile", "👤", "Profil • Yoru Level, statok és history",
        "A `!profile` Yoru egyik legfontosabb panelje. Ha nem tudod, hol tartasz a játékban, innen indulj.",
        (
            ("⭐ Yoru Level", "A normál progression XP economyból, játékokból és más támogatott tevékenységekből jön. Ez nem ugyanaz, mint az Activity Level."),
            ("📊 Stats", "`!stats [@tag]` részletesebb számlálókat mutat: earnings, work/crime, gambling, rob és más aktivitások."),
            ("🧾 History", "`!hist [@tag]` az utóbbi economy tranzakciókhoz hasznos, ha meg akarod nézni, honnan jött vagy hova ment pénz."),
            ("🎒 Inventory", "A profil/inventory oldalon követheted a ládákat, boostereket, utility itemeket és egyéb megszerzett tárgyakat."),
            ("🏆 Top", "`!top money`, `wallet`, `bank`, `level`, `earned`, `gambling`, `wins`, `work`, `crime`, `rob` és további kategóriák."),
        ),
    ),
    TutorialSection(
        "progression", "🏆", "Questek, achievementek, címek és Prestige",
        "A hosszú távú fejlődés nem csak pénzből áll. Questek, achievementek, title-ok, boosterek és Prestige adnak tartós célokat.",
        (
            ("🎯 Questek", "`!quests` alatt 3 napi + 3 heti feladatot kapsz. A progress automatikusan frissül, a kész jutalmat `!qclaim` / a panel Claim gombjával vedd fel."),
            ("🏅 Achievementek", "`!ach` / Achievement oldal: játék közben automatikusan nyílnak fel teljesítmények."),
            ("🏷️ Badge és Title", "`!badges` • `!titles` • `!title <név>`. A title a profilodon megjelenő választott cím."),
            ("🚀 Boosterek", "`!boost` mutatja az aktív boostereket. Bizonyos itemek ideiglenesen módosíthatnak jutalmakat/progressiont."),
            ("🏦 Bank Level / Investment", "`!bl` bank level • `!invest low|medium|high <összeg>` befektetési rendszer. Magasabb kockázat nem jelent garantált nagyobb profitot."),
            ("✨ Prestige", "Megfelelő Yoru Level + vagyon után `!prestige`. A progression egy része resetelődik, cserébe permanens income bónuszt kapsz. A Frakció megmarad, és több late-game rendszer Prestige-et kérhet."),
        ),
    ),
    TutorialSection(
        "inventory-shop", "🛍️", "Shop, Inventory, ládák és Feketepiac",
        "Az item economyban nem csak pénzt gyűjtesz. Vannak használható tárgyak, ládák, boosterek, market itemek és időszakos ajánlatok.",
        (
            ("🛒 Shop", "`!shop` interaktív shopot nyit. `!buy <id> [db]` és `!sell <id> [db]` shortcutként használható."),
            ("🎒 Inventory", "`!inv` / `!inventory` listázza a tárgyaidat. `!use <id>` használja a használható itemet. `!gi @tag <id> <db>` item-ajándékozás."),
            ("📦 Ládák", "Ládák Searchből, eventből, shopból vagy más jutalomból jöhetnek. Kinyitáskor rarity szerinti rewardot adnak."),
            ("💎 Fémek", "Ezüst, Arany és Gyémánt napi változó árral és limitált kínálattal működik; olcsóbban venni és később drágábban eladni lehetséges, de nem garantált."),
            ("🌑 Feketepiac", "`!bm` mutatja, ha nyitva van. Saját időszakos ajánlatokat tartalmaz, és event is megnyithatja."),
            ("🎁 Premium / utility", "A szerver shop konfigurációjától függően lehetnek crate-ek, boosterek, Discord rewardok és egyéb utility itemek."),
        ),
    ),
    TutorialSection(
        "gambling", "🎰", "Casino • Játékok, tét és statok",
        "A Yoru Casino a walletből fogad. A tét a kör indulásakor lefoglalásra kerül, majd a Casino Core biztonságosan elszámolja a payoutot vagy refundot.",
        (
            ("🎰 Casino lobby", "`!casino` vagy `/casino lobby` megnyitja a Casino panelt. Innen eléred a játékokat, a saját statjaidat, előzményeidet és a Monthly Jackpot poolt."),
            ("🃏 Blackjack", "`!bj <tét>` vagy `/casino blackjack`. Hit/Stand mellett Double, Split és dealer Ásznál Insurance is van. A natural Blackjack 3:2 profitot fizet; Splitből kapott 21 nem natural."),
            ("🎰 Slots", "`!sl <tét>` vagy `/casino slots`. Nagy 5×3 vizuális gép, 20 payline, ⭐ Wild, 💰 Scatter és Free Spins. A reel animáció kliensoldali GIF-ként fut, ezért több játékos mellett is simább; a végeredmény csak az animáció után jelenik meg a HUD-ban."),
            ("🎡 Roulette", "`!r` vagy `/casino roulette` megnyitja a saját európai roulette kerekedet. Egy körre több külön tétet is felrakhatsz pirosra, feketére, zöld/0-ra, párosra, páratlanra vagy konkrét 0–36 közötti számra, majd egyetlen Pörgetés gomb indítja a kereket."),
            ("💣 Mines", "`!mines <tét> [3|5|7|9]` vagy `/casino mines`. 5×4 mezőn fedhetsz fel lapokat; minden biztonságos találat növeli a cashout szorzót. Bomba esetén a kör bukik, timeoutnál pedig legalább egy safe reveal után automatikus cashout történik."),
            ("🐔 Chicken Road", "`!chickenroad <tét>` vagy `/casino chickenroad`. Sávonként döntesz: tovább mész vagy cashoutolsz. Minden sikeres átkelés növeli a szorzót; timeoutnál a már megszerzett szorzó automatikusan kifizetésre kerül."),
            ("🔵 Plinko", "`!plinko <tét>` vagy `/casino plinko`. Interaktív panel: tét/labda állítás, 1/2/3/5/10 Ball batch, Fast és Auto. Egy standard 10 soros táblán a közép gyakori/kisebb, a ritka szélek adják a nagy payoutot; nincs Risk selector."),
            ("🍬 Candy Rush", "`!candyrush <tét>` vagy `/casino candyrush`. 6×6 grid, valódi match-felismerés, eltűnő találatok, beeső új candy-k és egymásra épülő cascade szorzó."),
            ("🪙 Coinflip", "`!cf fej 10k` vagy `/casino coinflip`. Nagy, animált érmedobás fut; az eredmény után statikus final kép marad. Fej/írás választható."),
            ("🎲 Dice", "`!dice 4 10k` exact módhoz, vagy például `!dice odd 10k`, `!dice even 10k`, `!dice high 10k`, `!dice low 10k`, `!dice over7 10k`, `!dice under7 10k`, `!dice seven 10k`. A kétkockás módoknál az összeg dönt."),
            ("📈 High / Low", "`!hl <tét>` vagy `/casino highlow`. Kapsz egy kezdő lapot, majd Higher/Lower döntésekkel streaket építesz. Minden siker után nő a dinamikus cashout szorzó; bármikor kiszállhatsz. Tie nem töri meg a kört."),
            ("✂️ RPS", "`!rps rock|paper|scissors <tét>` vagy `/casino rps`. Yoru választása animáltan revealelődik; a végén statikus eredménykép marad."),
            ("🐔 Chicken Fight", "`!cock <tét>` vagy `/casino chicken`. A két Chicken HP-s, többkörös animált harcot vív; vereségnél a saját Chicken item elvész, győzelemnél túléli."),
            ("🔒 Egy aktív játék", "Egy szerveren egyszerre csak **egy aktív Casino játékod** lehet. Ez megakadályozza a spamet és a párhuzamos tét race-eket. A tét induláskor reserve-olódik; cancel/timeout/restart esetén a rendszer biztonságosan refundol, ahol szükséges."),
            ("📊 Casino statok", "`/casino stats` követi többek közt a games/win/loss/push, total wagered, total payout, nettó P/L, biggest bet, biggest win és highest multiplier adatokat."),
            ("💵 Payout", "Blackjack normál win 1:1 profit, natural 3:2 profit. Roulette klasszikus 2x / 3x / 36x total payout sávokat használ. Slots paytable-jét nagy mintás RTP-szimulációhoz hangoltuk."),
            ("♾️ All", "Ahol támogatott, `all` a teljes használható walletet teszi fel. Nincs fix max-bet plafon, ezért különösen figyelj az all-inre."),
        ),
    ),
    TutorialSection(
        "community-economy", "🎁", "Közös economy • Jackpot, Lottery és Eventek",
        "Néhány economy rendszer nem egyedül rólad szól, hanem az egész szerver közösen vesz részt benne.",
        (
            ("🏦 Monthly Casino Jackpot", "A house-game veszteségek kis része automatikusan a havi közös poolba kerül. `!jp`, `/community jackpot` vagy `/casino jackpot` mutatja az aktuális poolt, a saját havi hozzájárulásodat és az eligibility progresszt. A hónap lezárásakor Yoru automatikusan sorsol az eligible játékosok között, azonos eséllyel; ha nincs jogosult, a pool továbbgördül."),
            ("✅ Jackpot jogosultság", "Alapból legalább **25 Casino game VAGY 250k havi wager** kell. A részvételi esély nem nő lineárisan a téttel, így a leggazdagabb játékos nem tudja egyszerűen megvenni a sorsolást. A korábbi húzások historyban megmaradnak."),
            ("🎟️ Lottery", "`!lot <db>` vagy `/casino lottery` nyitja/kezeli a Lottery-t. A panel mutatja a poolt, összes és saját jegyet, következő húzást és az előző nyertest; +1/+5/+10/+50 gombbal is vehetsz jegyet."),
            ("💰 Kincses láda", "Automatikus event: reakcióval csatlakozol, a jutalom a résztvevők között oszlik el."),
            ("💣 Hirtelen Halál", "Belépős survival event: a résztvevők befizetése a pot, körönként kiesők vannak, az utolsó maradó viszi a potot."),
            ("⚡ Szerver effectek", "`!effects` mutatja az aktív Work / Crime / Luck módosítókat. Egyes eventek a Feketepiacot is megnyithatják."),
        ),
    ),
    TutorialSection(
        "market", "🛒", "Player Marketplace • Eladás és vásárlás",
        "A `!market` teljes interaktív piactér. Itt a játékosok egymás inventory itemjeivel kereskednek.",
        (
            ("🔎 Böngészés", "Keresés, listing választó és lapozás segítségével nézheted az aktív hirdetéseket."),
            ("➕ Eladás", "Az **Eladás** gomb inventory-választót nyit, majd modalban megadod a darabszámot és árat. A listázott item escrowba kerül, így nem tudod közben máshol elkölteni."),
            ("🛍️ Vásárlás", "Válassz listinget → **Vásárlás**. A tranzakció atomikusan kezelt, így ugyanazt az itemet nem lehet duplán megvenni."),
            ("📦 Saját hirdetések", "A saját listingjeidet külön oldalon látod és visszavonhatod. Cancel/lejárat esetén a bent lévő item visszakerül hozzád."),
            ("🧾 History / tax", "Az előzmények külön oldalon követhetők. A piactér szerveroldali adót is levonhat az eladási összegből."),
        ),
    ),
    TutorialSection(
        "server-shop-pvp", "🏪", "Server Shop, Custom Role és PvP Duel",
        "A Server Shop szerver-specifikus jutalmakat ad, a PvP Duel pedig két játékos közötti escrowzott fogadás.",
        (
            ("🎁 Server Shop", "`!servershop` lapozható, interaktív reward shop. A részleteknél látod az árat, stockot, limiteket és esetleges Activity/Yoru Level követelményt."),
            ("🎨 Custom Role", "Ha Custom Role rewardot veszel, vásárláskor te adod meg a rang nevét és HEX színét. Yoru ezután létrehozza neked a rangot."),
            ("⏳ Temporary Custom Role", "Ugyanez időlimittel: lejáratkor Yoru leveszi és törli a személyes rangot."),
            ("⚔️ Duel", "`!duel @tag 100k coinflip|dice|rps`. A másik fél Accept/Decline-t kap; mindkét tét escrowban van a lezárásig."),
            ("✊ RPS", "RPS duelban a választások rejtve maradnak, amíg mindkét fél nem választott."),
            ("📊 Duel stat", "`!duelstats` mutatja a PvP eredményeidet."),
        ),
    ),
    TutorialSection(
        "faction-start", "🌙", "Frakció • Belépés, bank és közös fejlődés",
        "A `!crew` / Frakció panel egy hosszú távú csapatrendszer. A régi commandnév kompatibilitásból `crew`, a játékosoldali rendszer neve Frakció.",
        (
            ("👥 Kezdés", "`!crew` megnyitja a panelt. Létrehozhatsz Frakciót, meghívást kaphatsz, csatlakozhatsz vagy kiléphetsz a szabályok szerint."),
            ("🏦 Frakció Bank", "A tagok pénzt tehetnek a közös bankba. A kivétel/fejlesztés belső rangjoghoz kötött lehet."),
            ("✨ Frakció XP", "A Frakciónak saját Levelje van. Tagok contribution XP-je, támogatott chat/voice és közös aktivitások építik."),
            ("📊 Contribution", "Nem csak a Frakció összpontja számít: a rendszer tagonként is követi, ki mennyit tett hozzá."),
            ("🎖️ Belső rangok", "A Frakció vezetése saját belső rangokat hozhat létre külön invite/kick/bank/perk/war/profile jogosultságokkal."),
        ),
    ),
    TutorialSection(
        "faction-advanced", "⚔️", "Frakció • Célok, Perk Tree és Wars",
        "A Frakció 2.0 endgame része a közös objective, perk és más Frakciók elleni War.",
        (
            ("🎯 Közös célok", "Naponta 3 és hetente 3 shared objective lehet aktív. A tagok egyéni progress-e ugyanabba a Frakció-célba számít bele."),
            ("🌲 Perk Tree", "Treasury • Objectives • Momentum • War ágak. Frakció Levelből kapott perk pontokkal nyithatók fejlesztések."),
            ("⚔️ War kihívás", "Egy Frakció objective-alapú Warra hívhat másikat. A kihívott Frakció leadere DM-et kap az új kihívásról."),
            ("✅ Elfogadás", "A Wars oldalon fogadható el vagy utasítható el. Elfogadás után mindkét oldal ugyanazért az objective-score-ért versenyez a megadott időablakban."),
            ("🏆 Eredmény", "A War score élőben követhető; lezáráskor W/L/D rekord és War Points frissül, a konfigurált jutalmakkal együtt."),
        ),
    ),
    TutorialSection(
        "business", "🏢", "Biznisz Empire • Late-game vállalkozások",
        "A Biznisz Empire a késői játék egyik fő pénz- és management rendszere. Activity, Prestige és Business License követelményhez köthető.",
        (
            ("📜 Business License", "A panel megmutatja a szükséges Activity/Prestige/pénz feltételeket. Ha megszerezted, a license permanens marad."),
            ("🏬 Ingatlanpiac", "Fikciós üzleteket/propertyket vásárolhatsz magyar game-world város/negyed/utca címkékkel. Anti-monopoly limitek korlátozhatják a darabszámot."),
            ("⬆️ Fejlesztés", "Property Level 1–5, reputation, adó és maintenance együtt hat a nettó termelésre."),
            ("💤 Offline termelés", "A biznisz offline is termelhet a beállított capig. Belépéskor/claimkor a rendszer levonja a kapcsolódó költségeket és jóváírja a nettó eredményt."),
            ("👷 Dolgozók", "Napi rotációs worker poolból bérelhetsz. Hire fee + órabér mellett income boostot adnak a szerződésük végéig."),
            ("🤝 Player property market", "Más játékos propertyjére ajánlatot tehetsz. A pénz escrowba kerül; acceptnél tulajdonosváltás, decline/cancel/expiry esetén refund történik."),
            ("🌙 Frakció kapcsolat", "Bizonyos business claim Frakció XP-t és matching Frakció-bank dividend-et is adhat."),
        ),
    ),
    TutorialSection(
        "heist", "🎯", "Nagy Meló • Party, gear és részesedés",
        "A Nagy Meló egy kooperatív, teljesen fikciós/absztrakt late-game rendszer. A sikerhez party coordination kell.",
        (
            ("🎯 Főpanel", "`!heist` / `/heist panel` alatt célpont, lobby, gear, meghívók, run és history egy helyen kezelhető."),
            ("👥 Party", "Max 4 játékos. A leader Discord User Pickerrel hív, a meghívott Accept/Decline-t választ. A lobby restart után is megmarad."),
            ("🎭 Szerepkör", "Tervező • Specialista • Sofőr • Támogató. Minden tag saját szerepkört és loadoutot választ."),
            ("🧰 Gear", "Az absztrakt gear shopból vásárolt felszerelés a heist kockázat/jutalom rendszeréhez kapcsolódik."),
            ("💸 Cut", "A leader javasolja a részesedéseket. Pontosan 100%-nak kell kijönnie, és minden résztvevő külön elfogadja indulás előtt."),
            ("🧩 3 fázis", "Felkészülés → Végrehajtás → Kijutás. 2/3 siker már teljesített run, 3/3 magasabb payoutot adhat."),
            ("🚔 Bukás", "Fine, jail, cooldown és konfigurálható gear-loss lehet a következmény. Siker esetén a rewardpool a jóváhagyott cut szerint oszlik."),
        ),
    ),
    TutorialSection(
        "music", "🎵", "Yoru Music • YouTube és Spotify",
        "Yoru voice zenelejátszója keresést, YouTube linket/playlistet és Spotify track/album/playlist linket is kezel.",
        (
            ("▶️ Play", "`!play <keresés vagy URL>` / `/music play`. Ha még nem vagy voice-ban, előbb lépj be egy voice csatornába."),
            ("🟢 Spotify", "A Python-only Fast Resolver csak a Spotify metadata-t tölti be gyorsan. Playlistnél nem resolve-olja előre az összes audioforrást; az aktuális track just-in-time, ISRC-first módon oldódik fel."),
            ("🎛️ Vezérlés", "`!pause` • `!resume` • `!skip` • `!stop` • `!queue` • `!np` • `!vol 75` • `!loop` • `!shuffle` • `!leave`."),
            ("⏱️ Nem ragad be", "Metadata/provider/yt-dlp lookup külön hard timeoutot kap. Ha egy szám forrása hibás vagy lassú, fallback/skip történik, nem áll meg órákra a queue."),
            ("🎚️ DJ korlátozás", "Egyes szervereken bizonyos vezérlők DJ ranghoz lehetnek kötve."),
        ),
    ),
    TutorialSection(
        "community", "🌙", "Közösségi funkciók • Amit játékosként használhatsz",
        "Yoru több olyan funkciót ad, ami nem közvetlen economy, de napi szerverhasználatnál hasznos.",
        (
            ("💡 Suggestion", "`!suggest <szöveg>` / `/community suggest` javaslat beküldése, ha a szerver engedélyezte."),
            ("📊 Poll", "A szerveren futó interaktív pollokban gombbal/selecttel szavazhatsz. Létrehozási jog szerverenként eltérhet."),
            ("🎉 Giveaway", "Aktív giveawayhez a megadott interactionnel csatlakozol; a lezárás és esetleges reroll automatikusan kezelt."),
            ("⭐ Starboard", "Ha a szerver használja, elég sok ⭐ reakció után egy üzenet automatikusan a Starboardra kerülhet."),
            ("💤 AFK", "`!afk [ok]` AFK státuszt állít. Ha valaki megemlít, Yoru jelezheti neki, hogy AFK vagy; visszatéréskor a státusz törlődik."),
            ("📌 Sticky", "Bizonyos csatornákon Yoru sticky üzenetet tarthat lent. Játékosként csak olvasnod kell; a bot automatikusan frissíti a helyét."),
        ),
    ),
    TutorialSection(
        "server-usage", "🎫", "Ticket, self-role, verification és szerverhasználat",
        "Ezeket a rendszereket a staff állítja be, de játékosként neked is tudnod kell, hogyan használd őket.",
        (
            ("🎫 Ticket", "A kijelölt Ticket panelen a gombbal nyitsz privát ticketet. A staff ott válaszol; a lezárt ticket transcriptelhető a szerver beállítása szerint."),
            ("🎭 Self Role", "A role panelen gombbal/selecttel vehetsz fel vagy adhatsz le választható rangokat."),
            ("✅ Verification / Rules", "Ha a szerver Yoru verification/rules flow-t használ, a megadott gombbal erősítsd meg a szabályokat vagy feloldást."),
            ("👋 Welcome / role restore", "Belépéskor Yoru adhat autorole-t és bizonyos szervereken visszaállíthatja a korábbi rangjaidat."),
            ("🔒 Jogosultság", "Ha egy panel gombja tiltott vagy nem reagál, lehet, hogy a funkció ranghoz, csatornához, cooldownhoz vagy más követelményhez kötött."),
        ),
    ),
    TutorialSection(
        "finish", "🏁", "Merre tovább? • Játékos checklist",
        "Ha idáig eljutottál, már ismered Yoru teljes játékosoldali rendszerét. Nem kell minden feature-t egyszerre grindolni; válassz célokat.",
        (
            ("🌱 Early game", "Daily/Weekly/Monthly → Work/Search → Bank → Questek → Activity → Shop/Inventory."),
            ("📈 Mid game", "Achievement/Title → Market → Server Shop → Frakció → komolyabb economy/gambling statok → Prestige előkészítés."),
            ("🌌 Late game", "Prestige → Frakció 2.0 Perk/Wars → Biznisz Empire → Nagy Meló."),
            ("👤 Mindig ellenőrizd", "`!profile` • `!quests` • `!cd` • `!bal` • `!top ...` — ezekből gyorsan látod, mi a következő értelmes lépés."),
            ("🆘 Súgó", "`!help` rövid command reference. Ha rendszerlogikát keresel, térj vissza ehhez a tutorialhoz."),
        ),
    ),
)


# Separate staff/admin handbook. Never mixed into the player forum.
ADMIN_SECTIONS: tuple[TutorialSection, ...] = (
    TutorialSection(
        "admin-start", "🛡️", "Admin kezdés • Yoru kezelési alapelvek",
        "Ez a külön admin tutorial a szerver üzemeltetéséhez készült. A játékos tutorialban szándékosan nincs moderáció vagy konfigurációs zaj.",
        (
            ("⚙️ Elsődleges felület", "A legtöbb beállítást `/settings` alatt kezeld. A régi prefix parancsok főleg gyors shortcut/fallback szerepet töltenek be."),
            ("🔐 Jogosultság", "Admin műveletekhez Discord Administrator/Manage Guild/moderációs permission és megfelelő Yoru role hierarchy kellhet."),
            ("🧭 Ajánlott sorrend", "Logok → Moderáció/AutoMod → Welcome/Roles → Tickets → Economy/Activity → Social → Frakció/Biznisz/Nagy Meló → Music/Community → Tutorial → Diagnosztika."),
        ),
    ),
    TutorialSection(
        "admin-settings", "⚙️", "/settings • Szerver konfiguráció",
        "Yoru admin UX-ének központja az interaktív Settings panel: gombok, lapozott selectek és modalok, fájlszerkesztés nélkül.",
        (
            ("📚 Fő modulok", "AutoMod • Moderáció • Logok • Welcome • Roles • Tickets • Music • Fun • Economy • Events • Community • Activity • Social • Frakció • Biznisz • Nagy Meló • Tutorial • Diagnosztika."),
            ("📄 Nagy szerverek", "A csatorna/kategória/rang selectek lapozottak, így nem ütköznek a Discord 25-option limitjébe."),
            ("🩺 Diagnosztika", "Gateway latency, permissionök, role hierarchy, SQLite quick_check/WAL, slash budget, persistent view-k és Music runtime ellenőrzése."),
        ),
    ),
    TutorialSection(
        "admin-moderation", "🔨", "Moderáció és logok",
        "A moderáció Discord permissionökre és Yoru modlog/case rendszerre épül.",
        (
            ("🔨 Alap parancsok", "Ban/unban/kick • timeout/mute/unmute • warn • purge • lock/unlock • slowmode • user/server info."),
            ("📋 Case / Modlog", "Esetek, moderációs history és kijelölt logcsatorna. Voice log külön kapcsolható, ha a szervernek szüksége van rá."),
            ("🤫 Admin economy", "Admin pénzkezelő parancsok lehetőleg silentek; jogosulatlan használatnál a bot privát/ephemeral visszajelzést ad."),
        ),
    ),
    TutorialSection(
        "admin-automod", "🛡️", "AutoMod • Szabályok és exemptionök",
        "Az AutoModot érdemes a szerver tényleges csatornaszerkezetéhez hangolni, nem mindent vakon maximumra kapcsolni.",
        (
            ("🚫 Védelem", "Invite/link • spam • duplicate • mention • CAPS • emoji • wordfilter • unicode/zalgo."),
            ("🧩 Exemption", "Staff, ticket és más szükséges kategóriák/csatornák felmenthetők a megfelelő filter alól."),
            ("📝 Log", "A blokkolt/törölt eseményeket külön AutoMod logcsatornába irányíthatod."),
        ),
    ),
    TutorialSection(
        "admin-welcome-tickets", "🎫", "Welcome, Roles és Tickets setup",
        "A beléptetés és support rendszerek persistent Discord UI-kra épülnek.",
        (
            ("👋 Welcome", "Welcome/Goodbye csatorna és üzenet, human autorole, bot autorole, role restore."),
            ("🎭 Role panelek", "Self-role gombpanelek, verification/rules flow és nagy szerveres lapozott selectors."),
            ("🎫 Tickets", "Ticket kategória, staff rangok, panel, claim, add/remove, rename, close/reopen/delete, transcript, opcionális DM transcript és log."),
            ("🔗 Ticket AutoMod", "Ticket kategóriát szükség esetén vedd ki invite/link filterből, hogy support során engedélyezett linkek működjenek."),
        ),
    ),
    TutorialSection(
        "admin-economy", "💰", "Economy, Gambling, Shop és Event konfiguráció",
        "A balance szerverenként finomhangolható, de módosítás előtt érdemes Analytics/valós használat alapján dönteni.",
        (
            ("📍 Engedélyezett helyek", "Több economy/gambling csatorna és teljes kategória adható meg. A read-only toplisták külön kivételek és Generalban is mehetnek."),
            ("⏱️ Cooldown / reward", "Daily/Weekly/Monthly, Work, Crime, Search, Beg, Rob, Slut, Interest és Role Income külön kapcsolható és hangolható."),
            ("🎰 Casino / Gambling", "A szerver Gambling profit-szorzója továbbra is `/settings → Economy` alatt kezelhető. A Casino minden session indulásakor snapshotolja ezt, ezért egy futó játék payoutját nem módosítja egy menet közbeni settings-változás. `/settings → Casino` alatt külön audit log csatorna állítható be; ott jelennek meg a belső Game ID-k és settlement adatok. Prefix tiltott helyen: command törlés + DM."),
            ("🎁 Eventek", "Kincses láda, Hirtelen Halál, activity gate, Work/Crime/Luck effectek és Black Market event konfiguráció."),
        ),
    ),
    TutorialSection(
        "admin-activity-social", "📈", "Activity, Social Economy és Server Shop",
        "A player progression és Social rendszerek admin oldala teljesen Discordból kezelhető.",
        (
            ("📈 Activity", "ON/OFF, level-up channel, chat/voice tuning, dinamikus milestone manager (hozzáadás/szerkesztés/törlés/meglévő role linkelés), Role Income és reconcile/sync. A Discordon kézzel módosított Activity role kinézete visszaszinkronizálódik a DB-be."),
            ("🏪 Server Shop", "Reward létrehozás/szerkesztés/törlés: ár, stock, user limit, Activity/Yoru Level requirement, existing/custom/temp role, inventory vagy manual reward."),
            ("🧰 Interactive Jobs", "`/settings → Jobs` alatt a teljes Jobs rendszer és az egyes munkák kapcsolhatók, reward multiplier állítható és külön audit log csatorna választható."),
            ("📊 Analytics", "24h / 7d / 30d supply, source/sink, market/PvP/Biznisz volumen és wealth concentration."),
            ("🧾 Manual claim", "Custom/manual Server Shop reward pending claimjeit admin felületről teljesítsd."),
        ),
    ),
    TutorialSection(
        "admin-lategame", "🌌", "Frakció, Biznisz és Nagy Meló admin beállítás",
        "A late-game rendszereknél különösen fontos, hogy az unlockok és multiplierek illeszkedjenek a szerver economy skálájához.",
        (
            ("🌙 Frakció", "Rendszer/célok/Wars ON/OFF, Frakció XP multiplier; a belső rangok kezelését maguk a Frakciók végzik permissionök alapján."),
            ("🏢 Biznisz", "Activity/Prestige unlock, license ár, adó, income multiplier, offline cap, worker contract, property/anti-monopoly limitek."),
            ("🎯 Nagy Meló", "Activity/Prestige requirement, cooldown, jail idő, bírság %, gear loss % és reward multiplier."),
        ),
    ),
    TutorialSection(
        "admin-music-community", "🎵", "Music és Community admin",
        "Music és közösségi automatizálások ugyanúgy a Settingsből hangolhatók.",
        (
            ("🎵 Music", "ON/OFF, Music csatorna, DJ rang, alap hangerő, queue limit, Fast Resolver cache/diagnosztika."),
            ("💡 Suggestions / Poll", "Csatornák, anonymous mód és alap poll paraméterek."),
            ("🎉 Giveaway / Starboard", "Giveaway kezelés/reroll, Starboard csatorna és reaction threshold."),
            ("📌 Sticky / AFK", "Sticky és AFK behavior szerver-specifikus beállításai."),
        ),
    ),
    TutorialSection(
        "admin-tutorial", "📚", "Tutorial kezelés és frissítés",
        "A játékos és admin kézikönyv külön Forum, így az új tagok csak a nekik fontos részeket látják.",
        (
            ("📚 `!tutorial`", "Létrehozza/szinkronizálja a **player** tutorial forumot. A posztok számozottak és a kezdéstől a late-game felé haladnak."),
            ("🛡️ `!tutorial admin`", "Létrehozza/szinkronizálja a külön, @everyone elől rejtett **admin** tutorial forumot."),
            ("🔄 Settings", "`/settings → Tutorial`: player sync, admin sync, közös kategória és ON/OFF."),
            ("♻️ Verziófrissítés", "A már létrehozott kezelt forumok verzióváltáskor automatikusan frissülnek; schema-váltáskor a Yoru által kezelt régi posztok tisztán újraépülnek."),
        ),
    ),
)

# Backwards-compatible name used by older tests/integrations; player content only.
SECTIONS = PLAYER_SECTIONS


class TutorialCog(commands.Cog):
    def __init__(self, bot: commands.Bot, db) -> None:
        self.bot = bot
        self.settings = ServerSettingsService(db)

    async def cog_load(self) -> None:
        self.maintain_tutorial_forums.start()

    async def cog_unload(self) -> None:
        self.maintain_tutorial_forums.cancel()

    @tasks.loop(hours=6)
    async def maintain_tutorial_forums(self) -> None:
        current_version = self._version()
        for guild in list(self.bot.guilds):
            try:
                if await self.is_enabled(guild.id):
                    forum = await self._forum(guild)
                    if forum is not None:
                        sync_version = await self.settings.get_text(guild.id, cfg.TUTORIAL_SYNC_VERSION_KEY, "-")
                        schema_version = (await self.settings.get_int(guild.id, cfg.TUTORIAL_SCHEMA_KEY)) or 0
                        if sync_version != current_version or schema_version != cfg.TUTORIAL_SCHEMA_VERSION:
                            await self.sync_tutorial(guild)
                        else:
                            await self._keep_threads_visible(guild, await self._load_post_map(guild.id, cfg.TUTORIAL_POSTS_KEY), forum.id)

                admin_forum = await self._admin_forum(guild)
                if admin_forum is not None:
                    admin_sync = await self.settings.get_text(guild.id, cfg.ADMIN_TUTORIAL_SYNC_VERSION_KEY, "-")
                    admin_schema = (await self.settings.get_int(guild.id, cfg.ADMIN_TUTORIAL_SCHEMA_KEY)) or 0
                    if admin_sync != current_version or admin_schema != cfg.ADMIN_TUTORIAL_SCHEMA_VERSION:
                        await self.sync_admin_tutorial(guild)
                    else:
                        await self._keep_threads_visible(guild, await self._load_post_map(guild.id, cfg.ADMIN_TUTORIAL_POSTS_KEY), admin_forum.id)
            except Exception:
                # Tutorial maintenance must never destabilize the bot.
                continue

    @maintain_tutorial_forums.before_loop
    async def before_tutorial_maintenance(self) -> None:
        await self.bot.wait_until_ready()

    @staticmethod
    def _version() -> str:
        try:
            return Path("VERSION").read_text(encoding="utf-8").strip() or "ismeretlen"
        except OSError:
            return "ismeretlen"

    async def is_enabled(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, cfg.TUTORIAL_ENABLED_KEY, cfg.TUTORIAL_DEFAULT_ENABLED)

    async def home_status(self, guild: discord.Guild) -> str:
        enabled = await self.is_enabled(guild.id)
        forum = await self._forum(guild)
        if not enabled:
            return "🔴 Kikapcsolva"
        if forum is not None:
            return f"🟢 {forum.mention}"
        return "🟡 Nincs létrehozva"

    async def _category(self, guild: discord.Guild) -> discord.CategoryChannel | None:
        category_id = await self.settings.get_int(guild.id, cfg.TUTORIAL_CATEGORY_KEY)
        category = guild.get_channel(category_id) if category_id else None
        return category if isinstance(category, discord.CategoryChannel) else None

    async def _forum_from_key(self, guild: discord.Guild, key: str) -> discord.ForumChannel | None:
        channel_id = await self.settings.get_int(guild.id, key)
        channel = guild.get_channel(channel_id) if channel_id else None
        return channel if isinstance(channel, discord.ForumChannel) else None

    async def _forum(self, guild: discord.Guild) -> discord.ForumChannel | None:
        return await self._forum_from_key(guild, cfg.TUTORIAL_FORUM_KEY)

    async def _admin_forum(self, guild: discord.Guild) -> discord.ForumChannel | None:
        return await self._forum_from_key(guild, cfg.ADMIN_TUTORIAL_FORUM_KEY)

    async def _ensure_forum(self, guild: discord.Guild, *, admin: bool = False) -> discord.ForumChannel:
        existing = await (self._admin_forum(guild) if admin else self._forum(guild))
        if existing is not None:
            return existing

        me = guild.me
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=not admin,
                send_messages=False,
                create_public_threads=False,
                send_messages_in_threads=False,
            )
        }
        if me is not None:
            overwrites[me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                create_public_threads=True,
                send_messages_in_threads=True,
                manage_threads=True,
                manage_channels=True,
            )

        forum = await guild.create_forum(
            cfg.ADMIN_TUTORIAL_FORUM_NAME if admin else cfg.TUTORIAL_FORUM_NAME,
            topic=cfg.ADMIN_TUTORIAL_FORUM_TOPIC if admin else cfg.TUTORIAL_FORUM_TOPIC,
            category=await self._category(guild),
            overwrites=overwrites,
            reason="Yoru admin tutorial forum létrehozás" if admin else "Yoru player tutorial forum létrehozás",
        )
        await self.settings.set_int(guild.id, cfg.ADMIN_TUTORIAL_FORUM_KEY if admin else cfg.TUTORIAL_FORUM_KEY, forum.id)
        return forum

    def _section_embed(self, section: TutorialSection, *, admin: bool = False, index: int | None = None, total: int | None = None) -> discord.Embed:
        number = f"{index:02d}. " if index is not None else ""
        embed = discord.Embed(
            title=f"{number}{section.emoji} {section.title}",
            description=section.intro,
            color=GOLD if section.slug in {"progression", "faction-start", "faction-advanced", "business", "heist"} else BRAND,
        )
        for name, value in section.fields:
            embed.add_field(name=name, value=value, inline=False)
        if admin:
            embed.set_footer(text=f"Yoru v{self._version()} • Admin Tutorial • {index}/{total}")
        else:
            embed.set_footer(text=f"Yoru v{self._version()} • Játékos Tutorial • {index}/{total} • !help")
        return embed

    async def _load_post_map(self, guild_id: int, key: str = cfg.TUTORIAL_POSTS_KEY) -> dict[str, int]:
        raw = await self.settings.get_text(guild_id, key, "{}")
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        result: dict[str, int] = {}
        for map_key, value in data.items():
            try:
                result[str(map_key)] = int(value)
            except (TypeError, ValueError):
                continue
        return result

    async def _fetch_thread(self, guild: discord.Guild, thread_id: int) -> discord.Thread | None:
        thread = guild.get_thread(int(thread_id))
        if isinstance(thread, discord.Thread):
            return thread
        try:
            fetched = await self.bot.fetch_channel(int(thread_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
        return fetched if isinstance(fetched, discord.Thread) else None

    async def _update_existing_post(self, thread: discord.Thread, section: TutorialSection, embed: discord.Embed, index: int) -> bool:
        try:
            if thread.archived:
                await thread.edit(archived=False, reason="Yoru tutorial sync")
            expected_name = f"{index:02d}・{section.emoji} {section.title}"[:100]
            if thread.name != expected_name:
                await thread.edit(name=expected_name, reason="Yoru tutorial sorrend frissítés")
            message = await thread.fetch_message(thread.id)
            await message.edit(embed=embed)
            return True
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False

    async def _delete_managed_threads(self, guild: discord.Guild, post_map: dict[str, int], forum_id: int) -> None:
        for thread_id in post_map.values():
            thread = await self._fetch_thread(guild, thread_id)
            if thread is None or thread.parent_id != forum_id:
                continue
            try:
                await thread.delete(reason="Yoru tutorial schema frissítés")
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    async def _keep_threads_visible(self, guild: discord.Guild, post_map: dict[str, int], forum_id: int) -> None:
        for thread_id in post_map.values():
            thread = await self._fetch_thread(guild, thread_id)
            if thread is not None and thread.parent_id == forum_id and thread.archived:
                try:
                    await thread.edit(archived=False, reason="Yoru tutorial visibility maintenance")
                except (discord.Forbidden, discord.HTTPException):
                    pass

    async def _sync_sections(
        self,
        guild: discord.Guild,
        *,
        sections: tuple[TutorialSection, ...],
        admin: bool,
        posts_key: str,
        sync_key: str,
        schema_key: str,
        schema_version: int,
    ) -> tuple[discord.ForumChannel, int, int]:
        forum = await self._ensure_forum(guild, admin=admin)
        post_map = await self._load_post_map(guild.id, posts_key)
        stored_schema = (await self.settings.get_int(guild.id, schema_key)) or 0

        # v3.17.3 player tutorial changes from mixed player/admin content to a
        # strict numbered learning path. Rebuild managed posts once so the
        # visual Forum order is also fixed, not just the embed text.
        if stored_schema != schema_version:
            await self._delete_managed_threads(guild, post_map, forum.id)
            post_map = {}

        updated = 0
        created = 0
        new_map: dict[str, int] = {}
        total = len(sections)

        # Discord Forum default activity order shows newest first. Creating in
        # reverse makes 01 the newest, then 02, 03... from top to bottom.
        for reverse_index, section in reversed(tuple(enumerate(sections, start=1))):
            index = reverse_index
            embed = self._section_embed(section, admin=admin, index=index, total=total)
            thread = await self._fetch_thread(guild, post_map[section.slug]) if section.slug in post_map else None
            if thread is not None and thread.parent_id == forum.id and await self._update_existing_post(thread, section, embed, index):
                new_map[section.slug] = thread.id
                updated += 1
                continue
            result = await forum.create_thread(
                name=f"{index:02d}・{section.emoji} {section.title}"[:100],
                embed=embed,
                auto_archive_duration=10080,
                reason="Yoru admin tutorial sync" if admin else "Yoru player tutorial sync",
            )
            thread = getattr(result, "thread", None)
            if thread is None and isinstance(result, tuple) and result:
                thread = result[0]
            if not isinstance(thread, discord.Thread):
                raise RuntimeError(f"Nem sikerült létrehozni a tutorial postot: {section.title}")
            new_map[section.slug] = thread.id
            created += 1

        # Preserve logical order in JSON too; only the creation loop is reversed.
        ordered_map = {section.slug: new_map[section.slug] for section in sections if section.slug in new_map}
        await self.settings.set_text(guild.id, posts_key, json.dumps(ordered_map, separators=(",", ":")), max_length=12000)
        await self.settings.set_text(guild.id, sync_key, self._version(), max_length=32)
        await self.settings.set_int(guild.id, schema_key, schema_version)
        return forum, created, updated

    async def sync_tutorial(self, guild: discord.Guild) -> tuple[discord.ForumChannel, int, int]:
        result = await self._sync_sections(
            guild,
            sections=PLAYER_SECTIONS,
            admin=False,
            posts_key=cfg.TUTORIAL_POSTS_KEY,
            sync_key=cfg.TUTORIAL_SYNC_VERSION_KEY,
            schema_key=cfg.TUTORIAL_SCHEMA_KEY,
            schema_version=cfg.TUTORIAL_SCHEMA_VERSION,
        )
        await self.settings.set_bool(guild.id, cfg.TUTORIAL_ENABLED_KEY, True)
        return result

    async def sync_admin_tutorial(self, guild: discord.Guild) -> tuple[discord.ForumChannel, int, int]:
        return await self._sync_sections(
            guild,
            sections=ADMIN_SECTIONS,
            admin=True,
            posts_key=cfg.ADMIN_TUTORIAL_POSTS_KEY,
            sync_key=cfg.ADMIN_TUTORIAL_SYNC_VERSION_KEY,
            schema_key=cfg.ADMIN_TUTORIAL_SCHEMA_KEY,
            schema_version=cfg.ADMIN_TUTORIAL_SCHEMA_VERSION,
        )

    async def settings_embed(self, guild: discord.Guild) -> discord.Embed:
        enabled = await self.is_enabled(guild.id)
        forum = await self._forum(guild)
        admin_forum = await self._admin_forum(guild)
        category = await self._category(guild)
        sync_version = await self.settings.get_text(guild.id, cfg.TUTORIAL_SYNC_VERSION_KEY, "-")
        admin_sync = await self.settings.get_text(guild.id, cfg.ADMIN_TUTORIAL_SYNC_VERSION_KEY, "-")
        post_map = await self._load_post_map(guild.id, cfg.TUTORIAL_POSTS_KEY)
        admin_map = await self._load_post_map(guild.id, cfg.ADMIN_TUTORIAL_POSTS_KEY)
        embed = base_embed(
            "📚 Yoru • Tutorial",
            "Két külön kézikönyv: egy részletes, sorrendbe rakott **játékos tutorial**, és egy külön, rejtett **admin tutorial**.",
            SUCCESS if enabled else BRAND,
        )
        embed.add_field(name="Állapot", value="🟢 Bekapcsolva" if enabled else "🔴 Kikapcsolva", inline=True)
        embed.add_field(name="📁 Kategória", value=category.mention if category else "Nincs • szerver gyökerében", inline=True)
        embed.add_field(name="📚 Player Forum", value=forum.mention if forum else "Még nincs létrehozva", inline=True)
        embed.add_field(name="🛡️ Admin Forum", value=admin_forum.mention if admin_forum else "Még nincs létrehozva", inline=True)
        embed.add_field(name="👥 Player posztok", value=f"**{len(post_map)}/{len(PLAYER_SECTIONS)}**", inline=True)
        embed.add_field(name="🔐 Admin posztok", value=f"**{len(admin_map)}/{len(ADMIN_SECTIONS)}**", inline=True)
        embed.add_field(name="🔄 Player sync", value=f"v{sync_version}" if sync_version != "-" else "Még nem futott", inline=True)
        embed.add_field(name="🔄 Admin sync", value=f"v{admin_sync}" if admin_sync != "-" else "Még nem futott", inline=True)
        embed.add_field(name="⌨️ Shortcut", value="`!tutorial` • player\n`!tutorial admin` • admin", inline=True)
        embed.set_footer(text="Yoru • Settings • Tutorial")
        return embed

    async def show_settings(self, interaction: discord.Interaction, owner_id: int, existing: "TutorialSettingsView | None" = None) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        view = TutorialSettingsView(self, owner_id, interaction.guild, category_page=existing.category_page if existing else 0)
        await interaction.edit_original_response(embed=await self.settings_embed(interaction.guild), view=view)

    async def back_to_settings(self, interaction: discord.Interaction, owner_id: int) -> None:
        settings_cog = self.bot.get_cog("SettingsCog")
        if settings_cog is None or not hasattr(settings_cog, "show_home"):
            return await interaction.response.send_message("❌ A Settings modul nem elérhető.", ephemeral=True)
        await settings_cog.show_home(interaction, owner_id)

    async def _notify_command_result(self, ctx: commands.Context, text: str) -> None:
        try:
            await ctx.author.send(text)
            return
        except (discord.Forbidden, discord.HTTPException):
            pass
        try:
            await ctx.send(text, delete_after=10)
        except discord.HTTPException:
            pass

    @commands.command(name="tutorial", aliases=["tutorialsync", "tutsync"])
    @commands.guild_only()
    @commands.has_guild_permissions(administrator=True)
    async def tutorial_prefix(self, ctx: commands.Context, mode: str | None = None) -> None:
        normalized = (mode or "player").strip().lower()
        if normalized in {"admin", "staff", "mod", "moderator"}:
            try:
                forum, created, updated = await self.sync_admin_tutorial(ctx.guild)
            except (discord.Forbidden, discord.HTTPException, RuntimeError) as exc:
                return await self._notify_command_result(ctx, f"❌ Admin tutorial sync hiba: {exc}")
            return await self._notify_command_result(
                ctx,
                f"🛡️ Admin tutorial kész/frissítve: {forum.mention} • **{created} új**, **{updated} frissített** poszt.",
            )
        if normalized not in {"player", "players", "jatekos", "játékos"}:
            return await self._notify_command_result(ctx, "❌ Használat: `!tutorial` vagy `!tutorial admin`")
        try:
            forum, created, updated = await self.sync_tutorial(ctx.guild)
        except (discord.Forbidden, discord.HTTPException, RuntimeError) as exc:
            return await self._notify_command_result(ctx, f"❌ Tutorial sync hiba: {exc}")
        await self._notify_command_result(
            ctx,
            f"📚 Játékos tutorial kész/frissítve: {forum.mention} • **{created} új**, **{updated} frissített** poszt.",
        )


class TutorialSettingsView(OwnedView):
    def __init__(self, cog: TutorialCog, owner_id: int, guild: discord.Guild, *, category_page: int = 0) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.category_page = category_page
        self.add_item(PagedGuildChannelSelect(
            self,
            guild,
            page_attr="category_page",
            selection_key="tutorial_category",
            placeholder="Tutorial kategória kiválasztása…",
            channel_types=(discord.ChannelType.category,),
            row=0,
        ))

    async def handle_channel_selection(self, interaction: discord.Interaction, selection_key: str, channels: Iterable[discord.abc.GuildChannel]) -> None:
        if selection_key != "tutorial_category":
            return
        channel = next(iter(channels), None)
        if not isinstance(channel, discord.CategoryChannel):
            return await interaction.response.send_message("❌ Kategóriát válassz.", ephemeral=True)
        await self.cog.settings.set_int(interaction.guild_id, cfg.TUTORIAL_CATEGORY_KEY, channel.id)
        for forum in (await self.cog._forum(interaction.guild), await self.cog._admin_forum(interaction.guild)):
            if forum is not None and forum.category_id != channel.id:
                try:
                    await forum.edit(category=channel, reason="Yoru tutorial settings")
                except (discord.Forbidden, discord.HTTPException):
                    pass
        await self.refresh(interaction)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_settings(interaction, self.owner_id, self)

    @discord.ui.button(label="ON/OFF", emoji="🔌", style=discord.ButtonStyle.secondary, row=1)
    async def toggle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        current = await self.cog.is_enabled(interaction.guild_id)
        await self.cog.settings.set_bool(interaction.guild_id, cfg.TUTORIAL_ENABLED_KEY, not current)
        await self.refresh(interaction)

    @discord.ui.button(label="Player sync", emoji="📚", style=discord.ButtonStyle.success, row=1)
    async def sync(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            forum, created, updated = await self.cog.sync_tutorial(interaction.guild)
        except (discord.Forbidden, discord.HTTPException, RuntimeError) as exc:
            return await interaction.followup.send(f"❌ Tutorial sync hiba: {exc}", ephemeral=True)
        await interaction.followup.send(
            f"📚 Player tutorial kész: {forum.mention} • **{created} új**, **{updated} frissített** poszt.",
            ephemeral=True,
        )

    @discord.ui.button(label="Admin sync", emoji="🛡️", style=discord.ButtonStyle.primary, row=1)
    async def admin_sync(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            forum, created, updated = await self.cog.sync_admin_tutorial(interaction.guild)
        except (discord.Forbidden, discord.HTTPException, RuntimeError) as exc:
            return await interaction.followup.send(f"❌ Admin tutorial sync hiba: {exc}", ephemeral=True)
        await interaction.followup.send(
            f"🛡️ Admin tutorial kész: {forum.mention} • **{created} új**, **{updated} frissített** poszt.",
            ephemeral=True,
        )

    @discord.ui.button(label="Kategória törlése", emoji="🧹", style=discord.ButtonStyle.secondary, row=1)
    async def clear_category(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_int(interaction.guild_id, cfg.TUTORIAL_CATEGORY_KEY, None)
        for forum in (await self.cog._forum(interaction.guild), await self.cog._admin_forum(interaction.guild)):
            if forum is not None:
                try:
                    await forum.edit(category=None, reason="Yoru tutorial settings")
                except (discord.Forbidden, discord.HTTPException):
                    pass
        await self.refresh(interaction)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.back_to_settings(interaction, self.owner_id)
