# Yoru Bot v3.20.1

Saját Discord economy + gambling bot Python / discord.py / SQLite alapon.

## Indítás

1. A `.env` fájlod maradjon meg.
2. Függőségek: `pip install -r requirements.txt`
3. Indítás: `python bot.py`

A meglévő `data/vaultbot.db` adatbázist **nem kell törölni**. Induláskor a bot automatikusan hozzáadja az aktuális release új oszlopait/tábláit; a Casino migráció is in-place történik.

## Fő prefix parancsok

### Economy
`!bal`, `!daily`, `!wk`, `!mo`, `!w`, `!cr`, `!rob @tag`, `!beg`, `!search`, `!cd`, `!dep all`, `!with all`, `!pay @tag 25k`, `!int`

A `/settings → Economy` oldalon szerverenként kapcsolható az economy, gambling, bank, interest és role income, valamint külön a Daily/Weekly/Monthly/Work/Crime/Search/Beg/Rob/Slut funkciók. Beállítható több engedélyezett economy csatorna **és teljes kategória**, cooldownok és reward range-ek, a rob arány, a gambling nyerő profit-szorzó, továbbá a pénznem neve és jele. Ha nincs engedélyezett hely megadva, az economy bárhol használható. **Frissítés után minden régi szerver a v3.10.1 alapértékekkel működik tovább**, amíg egy admin nem ír felül valamit a Settingsben.


### Music Fast Resolver (v3.17.2)
A Spotify backend **Python-only**, külön Java/Lavalink hosting nem szükséges. Spotify track/album/playlist hozzáadáskor Yoru csak egy gyors metadata-passzt végez és cache-el; egy playlist összes audioforrását **nem** próbálja előre feloldani. Az aktuális track forrása just-in-time kerül feloldásra, ISRC-first módszerrel, rövid hard timeoutokkal és title/artist fallbackkel. Egy hibás vagy lassú track ezért nem tarthatja percekig/órákig fogva az egész queue-t.




### Casino • Quick Visual Polish (v3.20.1)
- A quick-game renderer teljes header/layout polish-t kapott: a játéknév és a player branding külön sorban van, így hosszú cím vagy név sem csúszik egymásra.
- Coinflip valódi flip/squash animációt, Dice bounce/roll animációt, RPS 3-2-1 reveal-t, High/Low slide/reveal-t, Chicken Fight pedig támadás/hit mozgásokat kapott.
- A final result továbbra is statikus PNG; a GIF kizárólag a játék közben fut.
- A player badge minden quick-game GIF-en és final képen megmarad megosztható formában.

### Casino • Quick & Community Rework (v3.20.0)

- **Coinflip:** nagy, player-branded érmedobás animáció → statikus final kép.
- **Dice:** Exact, High/Low, Odd/Even, Over/Under 7 és Exactly 7 módok; egy- és kétkockás nagy display, ugyanazzal a smooth GIF → PNG flow-val.
- **RPS:** game-first választás/reveal animáció, utána statikus eredmény.
- **High / Low:** teljes streak + dynamic cashout játékmenet. A következő lap valós esélye és house factor alapján változik a szorzó; tie folytatja a kört.
- **Chicken Fight:** HP-s, többkörös attack/dodge/crit/counter animáció; az animáció a már eldöntött tényleges outcome-ból épül fel.
- A quick game-ek is a Casino UX standardot használják: **1 aktív game/player**, nagy mobilbarát display, player branding, render thread/concurrency limit, animáció után statikus final state.
- **Monthly Casino Jackpot:** automatikus hónapzáró draw, 25 game **VAGY** 250k havi wager eligibility, az eligible játékosok azonos nyerési eséllyel indulnak; ha nincs jogosult, a pool továbbgördül. History persistálódik.
- A régi manuális player-funded `!jp <összeg>` flow ki lett vezetve: `!jp` és `/community jackpot` most a Monthly Casino Jackpot státuszát mutatja.
- **Lottery panel:** `/casino lottery` mutatja a poolt, saját/összes jegyet, következő húzást és előző nyertest; +1/+5/+10/+50 gombos vásárlás. A hagyományos `!lot <jegyek>` shortcut megmarad.

### Casino • Finish Polish (v3.19.4)

- Egy játékos egy szerveren egyszerre csak **egy aktív Casino játékot** tarthat fenn; process-szintű guard + DB tranzakciós ellenőrzés védi a spam/double-start helyzeteket.
- A Slots/Roulette GIF-ek kb. **30%-kal lassabbak**; a Roulette 16 frame-en több teljes körből fokozatosan lassul bele a nyertes rekeszbe.
- Win/loss után a GIF **statikus PNG final frame-re cserélődik**, így az eredmény kijelzése nem indítja újra az animációt.
- A Slots és Roulette vizuálon megjelenik a játékos neve `XY'S GAME` formában, hogy a kimentett GIF önmagában is megosztható legyen.
- A Slots/Roulette session lock csak a statikus végeredmény megjelenése után oldódik fel.

### Casino • Performance & Multi-bet hotfix (v3.19.3)

- Slots/Roulette animációk egyetlen kliensoldali GIF uploadból futnak; a Pillow render külön threadben és korlátozott concurrencyvel készül, így nem blokkolja a Discord event loopot.
- Slots: **20 payline**, a HUD nem árulja el a win/multiplier eredményt az animáció előtt.
- Roulette: egyéni **multi-bet** kör; ugyanarra a spinre több külön tét rakható, majd egy Pörgetés gomb indítja.
- A végső Casino stat/ledger elszámolás továbbra is atomikus és Game ID alapján auditált.

### Casino • Visual Framework (v3.19.2)

- A Casino UI mostantól **game-first**: maga a játék a nagy vizuális felület, a tét/P-L/egyenleg kisebb HUD.
- **Blackjack:** a dealer látható upcard pontja az első körben is megjelenik; a belső Game ID eltűnt a player UI-ból.
- **Slots:** nagy, generált 5×3 játékgép-kép, reel stop animáció és final winning-cell highlight.
- **Roulette:** egyéni európai kerék, generált kör alakú display, animált golyó; Piros/Fekete/Zöld-0/Páros/Páratlan/Konkrét szám.
- **Casino audit:** `/settings → Casino` alatt külön log csatorna választható; ide kerülnek a belső Game ID-k és settlement adatok. A DB ledger akkor is megmarad, ha nincs Discord log csatorna.
- A player-facing Casino history nem mutat belső Game ID-ket.

### Casino • Main Rework (v3.19.0–3.19.1)

- Blackjack: Double, Split, Insurance, dealer animation, 3:2 natural.
- Slots: 5×3 engine, Wild, Scatter, Free Spins; v3.19.3-tól 20 paylines és RTP-szimuláció.
- Roulette alap betting/payout engine megmaradt, a player UX v3.19.2-ben egyéni kerékre váltott.
- v3.19.1 javította a Slots runtime RNG crash-t és nagyobb Blackjack kártyadisplayt adott.

### Casino • Phase 1 — Casino Core (v3.18.0)

- Új közös **Casino session engine**: a prefix/slash/UI ugyanazt a money/session backendet használja.
- A tét a játék indulásakor atomikusan **reserve-olódik**, így ugyanaz a wallet balance nem költhető el párhuzamosan többször.
- Minden új house-game kör egyedi **Game ID-t** kap.
- Új **Casino Ledger** auditálja a base/extra betet, payoutot, refundot és Monthly Jackpot hozzájárulást.
- Settlement **idempotens**: ugyanaz a Game ID nem fizethet kétszer interaction race/retry esetén sem.
- Restartkor az előző processből nyitva maradt reserved sessionök automatikus safe refundot kapnak.
- A payout source-of-truth az `app/casino_config.py`; a futó játék a startkori szerver payout multiplier snapshotját használja.
- Coinflip, Dice, Slots, Roulette, Blackjack, High/Low, RPS és Chicken Fight a közös Casino Core pénzelszámolását használja.
- `/casino` egy közös interaktív lobby: játékok, statok, history, Monthly Jackpot és Lottery.
- A house-game nettó veszteség **2%**-a gyűlik a Monthly Casino Jackpotba; a havi automatikus draw/eligibility/history v3.20.0-tól aktív.
- A részletes rework terv: `CASINO_ROADMAP.md`.

### Activity Roles 2.0 + Frakció role sync (v3.17.5)

- Az Activity milestone ranglétra **teljesen dinamikus és DB-ben persistált**: `/settings → Activity → Milestone rangok` alatt új milestone adható hozzá, meglévő szerkeszthető/törölhető, és bármely kezelhető Discord role hozzáköthető.
- A milestone selector lapozott, ezért **25-nél több rang** is kezelhető; a beépített magyar ranglétra csak első telepítéses template.
- A hozzákötött Discord role **neve, színe, hoist és mentionable állapota Discord → DB irányban automatikusan szinkronizálódik**. Yoru nem nevezi vissza a kézzel szerkesztett role-t.
- Ha egy hozzákötött Activity role-t közvetlenül Discordon törölnek, Yoru a legutóbbi biztonságos DB snapshotból újraköti/létrehozza; szándékos milestone törléshez a Settings panel használható.
- Frakció alapításkor továbbra is automatikus, hoistolt Discord role készül a Frakció nevével; join/leave/kick/disband és startup reconcile támogatott.

### Tutorial 2.0 (v3.17.3)
Az admin-only `!tutorial` létrehoz/szinkronizál egy read-only **játékos tutorial Forumot**. A posztok `01 → 02 → 03...` sorrendben, az első lépésektől a late-game rendszerekig haladnak, és csak azt tartalmazzák, amit egy átlag játékosnak tudnia kell. A korábbi moderáció/admin részek automatikusan kikerülnek a player Forumból.

A `!tutorial admin` külön, @everyone elől rejtett **Admin Tutorial Forumot** hoz létre moderációval, AutoModdal, Settingsszel, ticket/welcome setup-pal és minden szerverüzemeltetési résszel. `/settings → Tutorial` alatt külön Player sync és Admin sync gomb van.

### Polish / Diagnosztika (v3.17)
A `/settings → Diagnosztika` egy interaktív admin health panel: bot permissionök, role hierarchy, gateway latency, slash budget, persistent view-k, SQLite quick_check/WAL/DB méret és a Music runtime egy helyen. A Music runtime a Python Fast Resolver, spotDL, yt-dlp, FFmpeg és resolver cache állapotát mutatja.

### Nagy Meló
`!heist` / `/heist panel` megnyitja a teljes interaktív kooperatív heist UI-t. Party, meghívók, saját szerepkör/loadout, részesedés-elfogadás, három absztrakt fázis, gear shop, előzmények és toplista. Admin: `/settings → Nagy Meló`.

### Progression
`!profile`, `!ach`, `!titles`, `!title <cím>`, `!boost`, `!bl`, `!invest low|medium|high <összeg>`, `!prestige`, `!prestigetop`


### Frakció 2.0
A `!crew` / `/crew` most egy teljes interaktív **Frakció** panel: Frakció XP és Level, shared daily/weekly célok, perk tree, contribution, belső rangok granular jogokkal és objective-alapú Frakció Wars. A `/settings → Frakció` alatt az adminok Discordon belül kapcsolhatják a rendszert, a célokat és a Warst, illetve állíthatják az XP szorzót. A régi `crew_*` adatbázis és parancsnevek kompatibilitási okból megmaradnak.

### Biznisz Empire (v3.15)
A `!biznisz` / `/business panel` egy teljes interaktív late-game üzleti panelt nyit. Activity + Prestige gate után permanent **Business License** vásárolható, majd fikciós propertyk szerezhetők valódi magyar város/negyed/utca game-world címkékkel.

A panelből kezelhető az **Ingatlanpiac**, property fejlesztés és Reputation, offline bevétel, fenntartás/adó, napi worker rotáció, dolgozói szerződések, player-to-player escrow ajánlatok és a ranglista. Property adás-vételnél a Level, Reputation és aktív worker szerződések a propertyvel együtt mennek át.

A `/settings → Biznisz` alatt más adminok Discordon belül állíthatják az unlock követelményeket, Business License árat, adót, offline capet, income multipliert, worker szerződés időt és anti-monopoly property/város limiteket. A Business License Prestige reset után is megmarad.

### Activity Level
A **v3.12 Activity System** külön progression a meglévő economy/progression Leveltől. Valódi Discord chat + voice aktivitást követ, anti-farm védelemmel.

- Chat: alapból **12–20 Activity XP**, 60 mp XP cooldown, rövid időn belüli message gate és 5 perces duplicate védelem. Prefix parancsok nem számítanak Activitynek.
- Voice: alapból **3 Activity XP / qualifying perc**. Legalább 2 qualifying, nem-bot tag kell ugyanabban a voice-ban; AFK, Stage audience és server-deaf nem farmolhat. Self-deaf kizárás a Settingsben kapcsolható. XP csak teljes, megszakítás nélküli qualifying tick után jár, így a join/leave időzítés nem ad ingyen percet.
- Persistálódik: total Activity XP, Chat XP, Voice XP, qualifying message count, qualifying voice idő és Activity Level.
- XP görbe: Activity Lv. 40 ≈ **85 800 XP**, Lv. 100 ≈ **514 500 XP**.
- `/settings → Activity`: ON/OFF, Chat/Voice XP, level-up csatorna, XP tuning, self-deaf szabály és teljesen dinamikus milestone-rang manager.
- A milestone szintek/nameszám **nem fix**: admin új szintet/rangot adhat hozzá, átnevezheti/átszintezheti/törölheti, meglévő Discord role-t köthet hozzá, és Role Income-ot állíthat. A selector lapozott, így 25+ milestone is kezelhető.
- Role hierarchy safety: előbb megkapod a magasabb milestone rangot; a régebbit csak sikeres kiosztás után távolítja el.
- Profilban külön **Activity** oldal van.

### Social Economy (v3.13)
**Player Marketplace:** `!market [oldal] [keresés]`, `!market list <item> <db> <egységár>`, `!market buy <listing_id> [db]`, `!market cancel <id>`, `!market history`. Slash: `/social market`, `marketlist`, `marketbuy`, `marketcancel`, `markethistory`. A listing item escrow-ba kerül, 72 óra után automatikusan visszajár; a sikeres eladáson **5% market tax** ég el.

**Server Shop:** `!servershop`, `!servershop buy <id>` / `/social shop`, `/social shopbuy`. Adminok `/social shopadd` alatt Discord role-t, temporary role-t, Yoru inventory itemet vagy manuális/custom rewardot hozhatnak létre stockkal, per-user limittel, Activity/Yoru Level követelménnyel és árral. Custom reward vásárlás claimet készít, amit staff `/social shopclaims` + `/social shopfulfill` alatt kezel.

**PvP gambling:** `!duel @tag 100k coinflip|dice|rps` / `/social duel`. A két fél téte elfogadáskor escrow-ba kerül; Coinflip és Dice azonnal lezárul, RPS-nél mindkét választás rejtett a másik előtt. Timeout/restart esetén a bennragadt elfogadott tét automatikusan refundolódik. `!duelstats` / `/social duelstats`.

**Economy Analytics:** admin `/social analytics` vagy `!ecoanalytics 24h|7d|30d`: total supply, wallet/bank eloszlás, nettó létrehozott/elégetett pénz, source/sink kategóriák, Player Market/PvP volume és wealth-koncentráció.

### Crew / Social
`!crew`, `!crewcreate <név>`, `!crewinvite @tag`, `!crewaccept`, `!crewleave`, `!crewdeposit 250k`, `!crewwithdraw all`, `!crewupgrade`, `!crewpromote @tag`, `!crewdemote @tag`, `!crewkick @tag`, `!crewtransfer @tag`, `!crewdesc <szöveg>`, `!crewdisband DISBAND`, `!crewtop`

### Shop
`!shop [game|lootbox|booster|utility]`, `!buy <item> [db]`, `!sell <item> [db]`, `!use <item>`, `!inv`

Új ládák: `common_crate`, `rare_crate`, `epic_crate`, `legendary_crate`, `mythic_crate`.

Új boosterek: `work_booster`, `crime_booster`, `luck_booster`, `interest_booster`, `rob_booster`.

### Casino / közösségi játékok
`!casino`, `!cf`, `!dice`, `!sl`, `!r`, `!bj`, `!hl`, `!rps`, `!cock`, `!jp`, `!lot <jegyek>`

Casino slash felület: `/casino lobby`, `/casino blackjack`, `/casino slots`, `/casino roulette`, `/casino coinflip`, `/casino dice`, `/casino highlow`, `/casino rps`, `/casino chicken`, `/casino stats`, `/casino history`, `/casino jackpot`, `/casino lottery`. A Casino history és ledger a Casino Core köröket követi; a Game ID csak backend/admin auditban látható.

`!jp`, `/community jackpot` és `/casino jackpot` a **Monthly Casino Jackpot** státuszát mutatja. House-game veszteségekből automatikusan épül, hónapzáráskor Yoru sorsol az eligible játékosok között.

Lottery: $25 000 / jegy, automatikus sorsolás óránként, a pot 90%-a kerül kiosztásra. `/casino lottery` interaktív panel és history/last-winner kijelzés is van.

### Music
`!play <keresés / YouTube / Spotify>`, `!musicpanel`, `!queue`, `!np`, `!pause`, `!resume`, `!skip`, `!stop`, `!vol 75`, `!loop`, `!shuffle`, `!leave`

Slash: `/music play`, `/music panel`, `/music queue`, `/music now`, `/music pause`, `/music resume`, `/music skip`, `/music stop`, `/music volume`, `/music loop`, `/music shuffle`, `/music leave`.

Támogatott bemenetek: sima keresés, YouTube videó, **YouTube playlist**, Spotify **track / album / playlist**. Spotify esetén Yoru a Python-only Fast Resolverrel először csak metadata-passzt/cache-t készít; az audioforrás az aktuális trackhez just-in-time, ISRC-first módszerrel és rövid timeoutokkal oldódik fel. A Spotify audio nem közvetlenül a Spotify-ról streamelődik.

A `/music panel` egy persistent, tagoknak is használható interaktív Music Player embedet hoz létre/frissít. Gombok: Zene hozzáadása, Pause/Resume, Skip, Queue, Refresh, Shuffle, Loop, Hangerő, Stop, Leave. Ugyanez a `/settings → Music → Player panel` gombbal is publikálható.

A `/settings → Music` alatt kapcsolható a modul, kijelölhető Music text channel és DJ rang, valamint beállítható az alap hangerő és queue limit. A voice lejátszáshoz a Python dependency-k mellett **FFmpeg** bináris is kell a hoston. A requirements a discord.py hivatalos `voice` extráját használja (PyNaCl + davey).

### Fun
`!ship @tag [@tag]` • `/fun ship`

A Fun modulban csak a **Ship** maradt. Ugyanarra a párosra stabil százalékot ad, és Pillow-val generált dark/purple képkártyán jeleníti meg a két nagy kör alakú avatart, neveket és a compatibility százalékot. Ha a kép generálása vagy az avatar CDN hibázik, minimalista embed fallback marad. A `/settings → Fun` oldalon továbbra is ki-/bekapcsolható és opcionálisan egyetlen text csatornára korlátozható.

### Eventek
`!lada <összeg> <mp>`, `!hh <összeg> <join mp> <kör mp>`, `!bm`, `!bm buy <item> [db]`, `!effects`

A `/settings → Events` oldalon szerverenként kapcsolható az automatikus eventrendszer, a **Kincses Láda**, a **Hirtelen Halál** és a manuális staff indítás. Beállítható az event csatorna, minimum/maximum random időköz, jelentkezési és HH köridő, aktivitási gate, Láda reward range, HH belépő range és a Láda/HH választási esély.

A régi `.env` event beállítások továbbra is **fallback alapértékek**, ezért meglévő szerveren frissítés után nem változik meg automatikusan a működés. A Feketepiac / Work Rush / Crime Rush / Lucky Hour külön, ritkább 1–4 órás közösségi event loop marad, de ugyanazt a szerverenkénti **Auto Events** kapcsolót és event csatornát használja. A Lottery ettől függetlenül óránként sorsol, az eredményt pedig a konfigurált Events csatornába küldi, ha van ilyen.

### Toplisták
`!top money`, `wallet`, `bank`, `rob`, `gambling`, `wins`, `work`, `crime`, `daily`, `earned`, `level`, `investment`, `jackpot`, `lottery`, `chicken`, `scratch`, `weekly`, `activity`, `activityxp`, `chat`, `chatxp`, `voice`

Slash `/top` alatt ugyanezek az Activity kategóriák elérhetők új top-level command nélkül.

### Admin
`!yc` – Yoru állapot / economy összesítő

`!starteffect work 2 60` – manuális szerver effekt

`!starteffect crime 1.5 60`

`!starteffect luck 1.25 60`

`!cleareffects`

`!openbm` – Feketepiac azonnali megnyitása

`!drawlot` – Lottery azonnali sorsolása

## Slash parancsok

A legtöbb fontos rendszer slash commandként is elérhető, például `/profile`, `/shop`, `/use`, `/achievements`, `/titles`, `/invest`, `/prestige`, `/crew`, `/crewcreate`, `/crewinvite`, `/crewdeposit`, `/crewupgrade`, `/crewtop`, `/community jackpot`, `/community lottery`, `/community blackmarket`, `/community servereffects`, `/hirtelenhalal`, `/kincseslada`.

## v2.0 fő újdonságok

- progression XP / level rendszer
- achievementek és választható title-ok
- profil bővítés
- 5 lootbox rarity
- booster rendszer
- bank szintek és skálázódó kamat
- befektetés három kockázati szinttel
- közösségi Jackpot
- automatikus Lottery
- Feketepiac limitált készlettel
- automatikus szerver-wide Work / Crime / Luck eventek
- kibővített toplisták
- kategorizált shop
- egységesebb Yoru UI
- régi adatbázis automatikus migrációja


## v2.1.3 bugfix
- /leaderboard slash javítva.
- /deposit és /withdraw támogatja az `all`, `25k`, `2m`, `1b`, `1t`, `1q` formátumokat.
- Gambling max tét plafon eltávolítva; `all` a teljes walletre működik.
- Minden normál gambling győzelem 2x teljes kifizetést jelent (nettó +1x tét).
- Történeti v2.1.3 szabály: a Blackjack natural még 2x volt. **v3.19.0-tól a Blackjack natural 3:2 profit / 2.5x total payout** érvényes.

## v2.1.5
- Egységes amount parser slash + prefix parancsokhoz.
- Slash gamblingnél is használható: `all`, `25k`, `2m`, `1b`, `1t`, `1q`, stb.
- Érintett: `/coinflip`, `/dice`, `/slots`, `/roulette`, `/blackjack`, `/chickenfight`, `/highlow`, `/rps`, `/jackpot`.
- Ugyanez bekerült `/invest` és `/pay` parancsokhoz is.
- Nincs felső összeglimit a parserben; a wallet aktuális egyenlege a tényleges maximum.

## v2.2 Moderáció
Új slash + prefix moderációs rendszer: ban/unban/kick, mute/unmute, warn/warnings/clearwarns, purge, lock/unlock, slowmode, adminpay, modlog, userinfo/serverinfo és konfigurálható moderációs logcsatorna. A log csatorna beállítása: `/mod setlogchannel` vagy `!setlog #csatorna`.

## v2.2.1 – Economy reset

Admin-only full server economy reset:

- Slash: `/reseteconomy confirm:RESET`
- Prefix: `!reseteconomy RESET`
- Aliases: `!reseteco RESET`, `!economyreset RESET`, `!ereset RESET`

The reset clears player economy profiles, wallet/bank data, cooldowns/stats, inventory, achievements, boosters, lottery entries, economy transactions, server-wide economy effects, and daily market state for the current guild. Shop configuration, role-income configuration, and moderation data/log settings are preserved.

After the reset, users are recreated as new economy users on their next command and receive the configured `STARTING_BALANCE`.

## Yoru v3.2 — Quest rendszer

Napi küldetések:
- `!quests` / `/quests`
- 3 napi quest, naponta frissül

Heti küldetések:
- `!quests weekly` / `/quests period:weekly`
- 3 heti quest, hétfőn UTC szerint frissül

Jutalom átvétel:
- a quest panel `Jutalmak átvétele` gombjával
- vagy `!qclaim daily 1`
- slash: `/questclaim`

A v3.2 achievement rendszer a névtér-alapú `user_statistics` statokra épül.


## Yoru v3.3 — Prestige / Endgame

Új endgame loop:
- `!prestige` / `/prestige` — prestige állapot, követelmények és biztonságos megerősítő gomb
- `!prestigetop` / `/prestigetop` — szerver prestige ranglista
- Prestige 1 alapkövetelmény: Level 50 + $35 000 000 teljes vagyon
- Minden további prestige nehezebb
- Minden prestige +4% tartós income bónuszt ad, maximum +40%-ig
- A bónusz a daily/weekly/monthly/work/crime/search/beg/slut/role income/interest jutalmakra érvényes

Prestige során nullázódik a wallet, bank, progression level/XP, normál inventory és aktív boosterek. A lifetime statok, achievementek, badge-ek, címek, cooldownok/quest állapot és a valódi prémium reward itemek megmaradnak.

A profil új Prestige oldalt kapott, valamint új prestige achievementek, badge-ek és címek kerültek a progression rendszerbe.


## Yoru v3.4 — Crew / Social Economy

- Szerverenkénti játékos Crew-k Leader / Officer / Member rangokkal.
- Crew Bank, lifetime befizetés, interaktív Crew panel és Crew leaderboard.
- 5 fejleszthető Crew szint.
- Férőhely: **5 → 8 → 12 → 18 → 25**.
- Income bónusz: **0% → 1% → 2% → 3.5% → 5%**.
- Upgrade költség a közös bankból: **$5M → $15M → $40M → $100M**.
- Crew tagság és Crew Bank Prestige alatt megmarad; full economy reset viszont törli.
- Új social achievementek, badge-ek, title-ok, profil Crew oldal és stat tracking.


## Activity-aware auto events

Az automatikus Kincses Láda / Hirtelen Halál csak akkor indul, ha az event csatorna aktív.
Default: 20 érvényes üzenet / 30 perc, legalább 4 különböző userrel; userenként 5 másodpercenként legfeljebb 1 üzenet számít.

```env
AUTO_EVENT_ACTIVITY_MESSAGES=20
AUTO_EVENT_ACTIVITY_WINDOW_MINUTES=30
AUTO_EVENT_ACTIVITY_MIN_USERS=4
AUTO_EVENT_ACTIVITY_USER_COOLDOWN_SECONDS=5
```
## v3.5.0 — Economy Rebase

A fő economy balance az `app/economy_config.py` fájlban él; a **Casino/gambling payoutok és Casino Core paraméterek** v3.18.0-tól külön az `app/casino_config.py` source-of-truthból mennek. Shop/crate, market, event reward, Frakció/Prestige, Nitro és progression XP továbbra is az economy/progression configokban vannak.

Fő skála: **$25k starter**, `!work` **$6k–$25k / 5 perc**, Daily **$60k–$100k**, Weekly **$300k–$450k**, Monthly **$1M–$1.5M**. A Weeklyhez 7, Monthlyhoz 30 napos Yoru account kell.

A pénz és a progression XP szét lett választva: gambling/event/crate cash payout nem levellez automatikusan. Gamblingnél továbbra sincs max bet / all-in tiltás.

Premium reward: Nitro Basic **$500M / 30 nap / Level 35**, Discord Nitro **$750M / 45 nap / Level 45**, havi és személyes stock/cooldown védelemmel. Searchből egyik Nitro sem eshet.

Meglévő economy átállításához adminnal **egyszer** futtasd: `!rebaseeconomy REBASE` (vagy `/rebaseeconomy`). A Yoru account kora, Crew tagság, lifetime activity countok és premium reward history/itemek megmaradnak.

## v3.6.0 — Moderation & AutoMod 2.0

- Guildenként konfigurálható AutoMod: invite, link, spam, duplicate spam, mention spam, CAPS, emoji, szófilter és Zalgo/Unicode védelem.
- Szabályonként delete / warn / timeout action, threshold, timeout és channel/category/role kivételek.
- Domain allowlist/blocklist, raid activity alert és új account figyelmeztetés.
- Kibővített modlog: törölt/szerkesztett üzenetek, cache-elt törölt attachmentek, kézi Discord timeout/ban/unban/kick, role/nickname és opcionális voice log.
- Moderációs case rendszer és `!modstatus` / `/modstatus` diagnosztika.

## v3.6.1 — Interactive Server Settings

A szerveradminoknak nem kell az AutoMod konfigurációs parancsokat fejből tudniuk:

- `!settings` / `/settings` — interaktív szerverbeállítások.
- AutoMod globális ON/OFF, Basic / Recommended / Strict presetek.
- Szabályonként interaktív action, threshold, időablak, timeout és kivétel kezelés.
- Lapozható channel/category/role selectek partner, ticket és staff kivételekhez; nagy szerveren sem vágja le a listát.
- Domain allow/block manager és tiltott szó/kifejezés szerkesztő.
- Moderációs log csatorna és minden logtípus külön ki-/bekapcsolható.
- `!setup` / `/setup` — gyors első szerver setup AutoMod presettel, modloggal és kivételekkel.
- A központi `ServerSettingsService` lesz a későbbi Welcome/Roles/Tickets/Music/Fun panel és web dashboard közös konfigurációs backendje.


## v3.6.2
A moderációs slash parancsok a Discord globális command limit miatt `/mod` group alá kerültek. A prefix parancsok változatlanok.

## v3.7.0 — Welcome & Roles

A `/settings` panelben most már aktív a **Welcome** és **Roles** modul is.

- Welcome/goodbye csatorna, embed/szöveg, szerkeszthető sablonok, random welcome variációk és opcionális DM.
- Template változók: `{user}`, `{username}`, `{display_name}`, `{server}`, `{membercount}`, `{account_age}`.
- Emberi és bot autorole-ok, biztonságos role restore.
- Persistent self-role gombpanelek multi vagy single-choice móddal.
- Persistent rules/verification panel kiosztandó és opcionálisan eltávolítandó ranggal.
- Minden a meglévő `/settings` UI-ból kezelhető, új top-level slash command nélkül.

## v3.7.1 — Large Server Selector Hotfix

A `/settings` és `/setup` csatorna-/kategóriaválasztói Yoru által lapozott listát használnak. Ez biztosítja, hogy nagy szerveren is minden csatorna elérhető legyen a Welcome, Goodbye, Verification, Self-role, Modlog, AutoMod exemption és Quick Setup felületeken. Egy oldal 23 valódi elemet használ; a maradék helyet az Előző/Következő navigáció kapja. Új slash command nem került be.


## v3.8.0 — Community Management

A `/settings` új **Community** oldala szerverenként, interaktívan kezeli a közösségi modulokat.

- **Suggestions:** kijelölt suggestion csatorna, opcionális névtelen beküldés, 👍/👎 szavazás, staff elfogadás/elutasítás, persistent gombok.
- **Polls:** modalos létrehozás, 2–5 opció, egy aktív szavazat/fő, visszavonható szavazat, konfigurálható alap idő, restart-safe automatikus lezárás.
- **Giveaways:** persistent Join/Leave gomb, 1–10 nyertes, m/h/d időtartam, automatikus lezárás, restart-safe timer és staff reroll.
- **Starboard:** konfigurálható csatorna és ⭐ küszöb, automatikus create/update/remove, képes attachment preview és forráslink.
- **AFK:** indokkal beállítható, mention értesítés, első normál üzenetnél automatikusan törlődik.
- **Sticky:** csatornánként sticky üzenet, konfigurálható újraküldési küszöb, régi bot-sticky biztonságos cseréje.
- A régi közösségi economy slash parancsok is a `/community` groupba kerültek, így csökkent a top-level slash terhelés. Prefix parancsok változatlanok.
- A Settings csatorna- **és rangválasztói** 23 elemes lapozást használnak; native ChannelSelect/RoleSelect nincs a konfigurációs UI-ban.
- Release regression védelem: slash-limit, selector-pagination, economy és Community persistence/source tesztek.

## v3.9.0 — Tickets

A `/settings` panelben most már aktív a **Tickets** modul is, új top-level slash command nélkül.

- Reaction-role jellegű, persistent gombos ticket panelek, panelenként legfeljebb 5 konfigurálható ticket típussal.
- Privát ticket csatornák a kiválasztott Ticket kategóriában; a megnyitó, a konfigurált staff rangok és Yoru fér hozzá.
- A Ticket kategória automatikusan Yoru AutoMod invite- és link-kivételt kap, így a ticketekben invite link, normál link, kép és fájl is küldhető.
- Interaktív kezelés: **Claim**, **Add User**, **Remove User**, **Rename**, **Close**, **Reopen**, **Delete**.
- Konfigurálható staff rangok, log csatorna, felhasználónkénti nyitott-ticket limit és opcionális DM transcript.
- Lezáráskor `.txt` transcript készül, opcionálisan a ticket log csatornába és a megnyitó DM-jébe kerül.
- A ticket panelek és kezelőgombok restart után is működnek persistent view-val.
- A ticket adatstruktúrák induláskor automatikusan létrejönnek a meglévő SQLite adatbázisban; a meglévő adatbázist nem kell törölni vagy lecserélni.
- A Settings kategória-, csatorna- és staff-rang választói továbbra is a 23 elemes Yoru lapozást használják nagy szervereken.


## v3.10.0 — Music + Fun

A `/settings` két következő modulja, a **Music** és **Fun** aktív lett.

- **Music:** keresés/URL alapú voice lejátszás, queue, pause/resume, skip/stop, now playing, hangerő, current-track loop, shuffle és automatikus 5 perces idle disconnect.
- **Music settings:** globális ON/OFF, opcionális dedikált Music csatorna, opcionális DJ rang, alap hangerő és queue limit. A dedikált Music csatorna automatikus generic-link AutoMod kivételt kap, hogy a `!play <URL>` működjön.
- **Music hosting:** `yt-dlp` + `PyNaCl` Python dependency került a requirementsbe; a host rendszerén FFmpeg bináris szükséges. Ha valamelyik runtime elem hiányzik, a bot többi része tovább indul, csak a Music ad érthető hibát.
- **Fun:** `/fun` group + prefix megfelelői: 8Ball, choose, dice roll, tét nélküli coin, deterministic rate/ship, Truth, Dare, Would You Rather, mock és joke.
- **Fun settings:** ON/OFF és opcionális dedikált Fun csatorna.
- A Help panel külön Music és Fun oldalt kapott.
- Slash-limit védelem: Music és Fun is egy-egy GroupCog, így összesen csak 2 új top-level application command került be.
- Prefix név/alias collision regression teszt bekerült.


## v3.11.0 — Economy + Events Settings

A `/settings` panelben most már az **Economy** és **Events** modul is teljesen interaktívan konfigurálható, új top-level slash command nélkül.

- **Economy:** globális ON/OFF, parancsonkénti kapcsolók, opcionális dedikált economy csatorna, szerverenkénti cooldownok és reward range-ek.
- **Advanced economy:** rob arány, gambling nyerő profit-szorzó, pénznem név/jel és egygombos visszaállítás.
- **Events:** Auto / Kincses Láda / Hirtelen Halál / manuális staff event külön kapcsolóval, lapozott event-csatorna választóval.
- **Event tuning:** min/max random idő, jelentkezési idő, HH köridő, aktivitási gate, reward/belépő range és Láda esély.
- A meglévő `.env` és `app/economy_config.py` értékek fallbackként megmaradnak; frissítés önmagában nem borítja fel a jelenlegi szerver balance-át.
- A Community market event loop az Events oldal Auto kapcsolóját és csatornáját követi, saját ritkább időzítését megtartva.
- Manuális Láda/HH indításhoz elég a **Szerver kezelése** jogosultság, ha a manuális eventek engedélyezve vannak.
- A konfiguráció a meglévő `guild_state` backendben marad, így későbbi web dashboard ugyanazokat az értékeket tudja használni.
- A Settings csatornaválasztók továbbra is a 23 elemes Yoru lapozást használják nagy szervereken.


## v3.11.1 — Stability + Multi Economy Channels + Ship 2.0

- **Multi Economy Channels:** több text csatorna és több teljes Discord kategória engedélyezhető egyszerre. Ha nincs megadva egy sem, az economy bárhol használható. A v3.11.0 egyetlen dedikált csatornája automatikusan legacy fallbackként megmarad.
- **Chicken Fight:** vereségnél 1 Chicken meghal és eltűnik az inventoryból; győzelemnél túléli a harcot. A shop leírása ezt jelzi.
- **Quest bugfix:** a napi/heti questek már az adott időszak első quest-releváns aktivitása **előtt** kiosztódnak, ezért a progress akkor is számít, ha a Quest menüt csak később nyitod meg.
- **Fun cleanup:** Eight Ball / Choose / Roll / Coin / Rate / Truth / Dare / WYR / Mock / Joke kikerült.
- **Ship 2.0:** mindkét profilkép, compatibility bar, eredményfüggő Yoru-ítélet és stabil páros-százalék.
- A hosszú távú fejlesztési terv a projektben lévő `ROADMAP.md` fájlban van rögzítve: Activity Level + automatikus milestone role-ok, Social Economy, **Frakció 2.0**, magyarországi late-game **Biznisz Empire**, **Heist / Nagy Meló**, majd finomhangolás és Web Dashboard.

## v3.12.0 — Activity System

- Külön Activity XP/Level backend, economy/progression XP-től függetlenül.
- Chat XP + qualifying message count anti-farm cooldownnal, duplicate védelemmel és prefix-command kizárással.
- Voice XP + qualifying voice time, minimum 2 real user szabállyal, AFK/deaf/stage audience védelemmel.
- `/settings → Activity` teljes interaktív konfiguráció, lapozott channel/role selectorokkal.
- Milestone role rendszer 5/10/20/35/50/75/100 szinteken, auto-create/rename, Role Income integráció és hierarchy-safe role upgrade.
- Activity level-up csatorna és automatikus milestone reconcile.
- Profil Activity oldal + részletes Activity statok.
- Meglévő `top` leaderboard bővítve Activity/Chat/Voice kategóriákkal; **0 új top-level slash command**.
- A meglévő SQLite DB automatikusan migrálódik; törölni/cserélni nem kell.

## v3.11.2 — Ship Image Card + Spotify Reliability

- **Ship redesign:** a verdict/ítélet, Yoru-szöveg és régi meter helyett generált dark/purple képkártya két nagy kör alakú Discord avatarral, nevekkel és stabil compatibility százalékkal. Pillow/CDN hiba esetére minimalista embed fallback marad.
- **Spotify reliability:** `spotdl save --preload` → metadata-only retry → `spotdl url` → trackenkénti `ytsearch1` fallback. A spotDL által talált source URL sikertelensége esetén a playback automatikusan visszaesik a keresésre.
- **Managed-host friendly:** nincs Lavalink/Java kötelezettség; a meglévő discord.py voice + yt-dlp + FFmpeg stack marad.
- **YouTube és Music Panel:** YouTube/playlist, queue, pause/resume, skip, stop, volume, loop, shuffle és persistent panel változatlanul megmarad.
- **Dependency:** `Pillow==12.3.0` a Ship kártyához.


## v3.12.2 — Channel Guard Hotfix

- Activity/chat/voice toplisták Generalban is használhatók.
- Rossz helyre írt prefix gambling parancs törlődik, a user pedig privát DM-ben kapja meg az engedélyezett helyeket.


## v3.12.3 — Public Leaderboards + Gambling Channel Cleanup

- `!top`, `!leaderboard` és `!lb` minden toplista-kategóriával használható Generalban is; a toplisták read-only közösségi statok, ezért nem követik az economy hely-korlátozást.
- A slash `/top` szintén minden kategóriával bárhol használható.
- Rossz helyen használt prefix gambling parancsnál Yoru megpróbálja törölni az eredeti parancsüzenetet, majd DM-ben megadja az engedélyezett csatornákat/kategóriákat; zárt DM esetén rövid, automatikusan eltűnő fallback üzenetet küld.


## v3.12.4 — Unified Economy Channel Cleanup

- Rossz helyen használt prefix economy parancsok (`!work`, `!crime`, `!beg`, `!daily`, bank/shop stb.) ugyanúgy törlődnek, mint a gambling parancsok.
- A felhasználó DM-ben kapja meg az engedélyezett economy csatornákat/kategóriákat; zárt DM esetén csak rövid, automatikusan törlődő fallback jelenik meg.
- `!top` / `!leaderboard` / `!lb` továbbra is publikus és Generalban is használható.
- Feature-disabled hiba továbbra sem keveredik össze a wrong-channel takarítással.


## v3.13.1 — Social Economy UI/UX

- `!market` és `/social market`: teljes interaktív Player Marketplace (keresés, lapozás, vétel, eladás, saját listingek, history).
- `!servershop` és `/social shop`: interaktív player shop reward selecttel és Buy gombbal.
- `/settings → Social`: Server Shop admin manager + pending claimek + Economy Analytics.
- A Server Shop összes fontos reward mezője Discordon belül szerkeszthető.

## Casino PvP + Balance Pass (v3.21.0)

Coinflip/Dice/RPS PvP duels now use the same large game-first Casino visual standard, with cross-system one-active-game protection and a documented Casino balance audit.
