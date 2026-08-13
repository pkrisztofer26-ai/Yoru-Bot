# YORU BOT — PROJECT HANDOFF / CHANGELOG

**Utolsó frissítés:** 2026-08-13  
**Aktuális release:** `v3.25.12`  
**Következő fő fázis:** v3.25.12 egyszerű Plinko lifecycle éles validation; ha stabil, a Plinko playback rész lezárva és jöhet a generic Casino visual migration következő hulláma (Slots + közös Fast/Auto/Bet framework).

Ez az egyetlen folyamatosan vezetett projekt-handoff fájl. Új beszélgetésben ezt a fájlt kell elsődleges projektállapotként kezelni.

---

## 1. Projekt / workflow

- Bot: **Yoru**
- Stack: Python, discord.py 2.7.x, SQLite/aiosqlite, PebbleHost.
- Prefix: `!`, mellette slash commandok.
- GitHub forrás: `pkrisztofer26-ai/Yoru-Bot`, de **release-t ne pusholj GitHubra**; a felhasználó chatben kér komplett ZIP-et.
- A felhasználó teljes replacement release ZIP-eket kér, kevés magyarázattal.
- Normál release ZIP tartalma: `app/`, `bot.py`, `requirements.txt`, `VERSION`, `PROJECT_HANDOFF.md`.
- Ne kerüljön release ZIP-be: tests, README, külön roadmap/changelog/audit fájlok, `.env`, DB, `__pycache__`.
- Runtime / money / exploit / settlement / gamebreaker hiba azonnali hotfix.
- Pusztán vizuális polish mehet a következő tervezett release-be.
- Minden release válasz végén kötelező felsorolni az új `!command`-okat, slash megfelelőiket, admin commandokat és settings útvonalakat.

### Kötelező safety gate minden pénzes/stateful funkciónál

Release előtt ellenőrizendő:
- wallet vs bank finanszírozás;
- `all` kezelés;
- insufficient funds;
- double click / spam click;
- stale interaction;
- timeout;
- restart / cog reload;
- reconnect, ahol releváns;
- atomic + idempotent settlement;
- duplicate payout;
- párhuzamos játékos/session izoláció;
- Discord API/edit failure ne változtassa meg a backend pénzügyi eredményt;
- payout/RTP/EV/exploit audit;
- Discord slash command top-level és group/subcommand limitek.

### Pénzforrás szabály

A gambling / betting / Poker / MÁV stake **wallet-only**.  
`all` ezeken a rendszereken **csak a wallet teljes elkölthető összegét** jelenti.  
A bank védett tároló, játék-téthez nem használható.

---

## 2. v3.22 — Jobs / Settings

### v3.22.0
- Interactive Jobs alap: Raktáros, Borsodi Lopkodás, Futár, Taxi.
- Job Mastery, History, service/DB integráció.

### v3.22.1
- hosszabb, interaktívabb Raktáros;
- scenario döntések;
- job timing/cooldown finomítás.

### v3.22.2
- egyetlen shared Jobs cooldown;
- 2 órás alap cooldown minden befejezett job után;
- 15 perc abandon anti-reroll;
- Jobs UI overflow/layout javítás.

### v3.22.3
- persistent Gamble Room panel;
- játékosok saját ideiglenes gamble roomot hozhatnak létre;
- Hirtelen Halál/Bomba entry source tracking;
- 5 perc post-withdraw Rob protection.

### v3.22.4 HOTFIX
Settings → Jobs crash: `TypeError: 'async_generator' object is not iterable`.  
Ok: `sum(... if await ...)`.  
Fix: explicit awaited loop + regression protection.

### v3.22.5 — Settings Authority
A DB-backed szerver settings lett az elsődleges source of truth többek között:
Prestige, quests, progression, Invest, starting balance, Rob, Role Income, Interest, account age, streak, Crime/Slut, Casino/Jackpot, Jobs timings, Market/PvP, Faction, Business, Heist, Lottery, economy events és activity anti-farm területen.

### v3.22.6 HOTFIX
Progression Settings: `NameError: money is not defined`.  
Fix: hiányzó formatter import + settings undefined-name pass.

---

## 3. v3.23 — Casino Expansion

### v3.23.0
Új játékok:
- Mines
- Chicken Road
- Plinko
- Candy Rush

Továbbá:
- Casino V2 settlement/renderer szétválasztás;
- Raktáros bemutatott sequence = tényleges GIF/final sequence;
- Slots Free Spin már mind az 5 külön spin eredményt animálja.

### v3.23.1
- Chicken Road gyorsabb léptetés (~0.8 sec/step).
- Candy Rush core display rebuild: beesés → win cluster → pop → gravity → refill → cascade.
- Plinko teljes interaktív rework későbbre maradt.

A felhasználó v3.23.1-et működés szempontjából rendben találta.

---

## 4. v3.24 — Live World & Betting

Végleges irány:
- Boltrablás = single-player.
- Bankrablás = single-player.
- MÁV Crash = single-player.
- Kincsem = szerver-wide futam 4 óránként, napi 6.
- Tippmix = virtuális napi football betting rendszer.
- Texas Hold'em = fő multiplayer rendszer.
- Heist/Nagymeló marad a külön co-op rablás.

### v3.24.0

#### Live World
- Boltrablás SP.
- Bankrablás SP.
- MÁV Crash.
- Texas Hold'em 2–6 player, private hole cards, fold/check-call/raise/all-in, side pots, showdown, AFK/restart refund.

#### Betting
- persistent Fogadási Központ;
- napi virtuális meccskínálat;
- széles magyar klubpool + nagy külföldi ligák/kupák;
- 1X2, dupla esély, O/U, BTTS, DNB, félidő, handicap, pontos eredmény;
- Single / Kötés / Rendszer;
- Kincsem;
- DM settlement + History.

#### Fő commandok
- `!betting`, `!fogadas`, `!fogadás`, `!tippmix` → `/betting open`
- admin panel: `!bettingpanel`, `!betpanel`, `!fogadaspanel`, `!fogadáspanel` → `/betting panel`
- `!boltrablas`, `!boltrablás`, `!shoprob` → `/live shoprob`
- `!bankrablas`, `!bankrablás`, `!bankrob` → `/live bankrob`
- `!mav <tét>`, `!máv`, `!crash` → `/live mav`
- `!poker <buyin>` → `/live poker`
- `!pokerhand`, `!lapjaim`, `!kezem` → `/live pokerhand`

### v3.24.1 — MÁV GAMEBREAKER HOTFIX
Éles hibák:
- `!mav all` bankból is fedezett;
- Cashout View 180 sec után lejárt;
- live update új View-kat generált, stale interaction keletkezett;
- `Yoru failed to interact`;
- UI edit latency gameplayt lassíthatott;
- egyik session cashoutja más sessiont megakaszthatott.

Fixek:
- wallet-only;
- `all` = wallet;
- stabil timeout nélküli Cashout View;
- backend clock független Discord message edit sebességtől;
- per-session task/lock;
- atomic crash/cashout;
- final edit retry.

### v3.24.2 — Betting output + funding hotfix

#### Napi eredmény Forum
A `#sportfogadás-panel` többé nem kap automatikus eredmény-spamet.  
A Betting settingsben külön Discord Forum választható. Yoru naponta egy posztot készít, pl.:
`📅 2026.08.13 • Sportfogadás eredmények`

Az adott nap Tippmix + Kincsem eredményei ugyanabba a napi fórumpostba mennek. Másnap új post. Forum API failure nem blokkolhat money settlementet, DM-et vagy History mentést.

#### Funding hotfix
Audit során kiderült:
- Tippmix/Kincsem bankból is tudott volna tétet fedezni;
- Poker buy-in bankból is tudott volna hiányt pótolni.

Mind wallet-only lett.

---

## 5. v3.24.3 — Stability + Balance + MÁV Gamebreaker Fix

### A felhasználó által reprodukált MÁV hibák

1. Aktív MÁV játékos rabolható volt.
2. MÁV kör néha eredmény nélkül megállt, a stake bent ragadt.
3. 135B stake @1.18x esetén a helyes **159.3B** payout helyett pontosan **100B** érkezett.
4. Cashout spam / lag esetén a vonat még ~0.4–0.7x-et haladt, mielőtt a gombnyomás feldolgozódott.

### MÁV konkrét root cause-ok és fixek

#### 100B payout truncation
Root cause: a shared Live `max_payout=100B` rá volt húzva a MÁV-ra:
`min(max_payout, stake * multiplier)`.

Fix:
- **MÁV payouton nincs utólagos max payout truncation.**
- 135B × 1.18 = **159.3B**.
- A Live max payout most csak a rablás reward capja.

#### Cashout latency
- Settlement a Discord interaction **létrehozási idejét** (`interaction.created_at`) használja.
- Nem azt a multipliert kapod, amikor a callback végre CPU/DB időt kapott, hanem azt, amikor ténylegesen kattintottál.
- A stale DB/UI `current` érték többé nem tud settlementet mozgatni; a `started_at` + elapsed backend clock az egyetlen source of truth.
- Live UI edit cashoutkor azonnal leáll best-effort módon, de settlement nem vár Discord editre.
- v3.24.3-ban még 8 sec backend interaction grace maradt. **Ez később hibás architekturális döntésnek bizonyult**, mert a crash settlementet 8 másodperccel késleltette. v3.24.4 ezt teljesen eltávolította.
- Discord I/O nincs a settlement lock critical sectionben.

#### Random session death / stake hostage
- unexpected MÁV runner exception → **exactly-once full stake refund**;
- runner cancellation → exactly-once refund, ha a session még aktív;
- cog unload/reload megvárja a cancellation refund handlereket;
- restart recovery továbbra is visszatéríti az aktív stake-et;
- refund visszagörgeti a `money_lost` statot is;
- refund tranzakció idempotens.

#### Rob protection
Aktív MÁV közben:
- a játékos **nem rabolhat**;
- a játékos **nem lehet Rob célpont**.

A védelem DB-backed `live_game_sessions` lookupból jön, nem in-memory állapotból.

#### Session isolation / duplicate payout
- minden MÁV külön task + lock;
- egyik player cashoutja nem cancel-elhet más sessiont;
- 20 párhuzamos ugyanarra a sessionre küldött settlementből csak 1 tud payoutot commitolni.

### Boltrablás / Bankrablás stability

- bekerültek a **`!job` / `!jobs`** interaktív választóba;
- továbbra is ugyanaz az interaktív Robbery UI;
- saját Live cooldownjuk marad (alap: Bolt 2h, Bank 4h);
- nem kapnak hamis Jobs Mastery/history bejegyzést, amíg ehhez nincs külön progression design;
- régi direkt commandok kompatibilitásból megmaradnak;
- új slash shortcut: `/jobs shoprob`, `/jobs bankrob`.

Stability:
- stage döntés DB `BEGIN IMMEDIATE` tranzakció;
- rendered stage száma one-shot tokenként működik;
- régi/stale gomb nem tud újabb stage-et végrehajtani;
- spam click nem tud több stage-et átugrani;
- session action/cashout per-session lockot kapott;
- Robbery UI timeout 10 perc; timeoutkor az aktív rablás `cancelled`, ezért nem blokkol örökké más Live játékot.

### Boltrablás / Bankrablás balance
300k Monte Carlo / stratégia, prestige nélkül:

Boltrablás (2h alap cooldown):
- Safe EV ~245k/run, ~61.8% teljes survival, ~123k/hour.
- Fast EV ~246k/run, ~44.3%, ~123k/hour.
- Greedy EV ~234k/run, ~27.3%, ~117k/hour.

Bankrablás (4h alap cooldown):
- Safe EV ~582k/run, ~33.1%, ~146k/hour.
- Fast EV ~624k/run, ~22.6%, ~156k/hour.
- Greedy EV ~553k/run, ~12.1%, ~138k/hour.

Cél: a kockázatos gombok többé ne legyenek nyilvánvaló EV-csapdák, de egyik stratégia se legyen kiugróan OP.

### Tippmix stability + balance audit

#### Félidős pozitív-EV exploit — FIX
Root cause:
- HT odds Poisson `xG * 0.46` modellből készültek;
- settlement viszont egy másik, `min(full_score, second random Poisson)` modellből generálta a félidőt.

Bizonyos félidős pickek ~118–122% RTP-t értek el.

Fix:
- első félidő + második félidő független Poisson komponensekből épül;
- összegük megtartja a full-time xG modellt;
- HT odds és settlement ugyanazt a distributiont használja.

#### Payout cap viselkedés
Korábban egy accepted ticketet settlementkor csonkolhatott volna a max payout.

Fix:
- új Tippmix ticketet **nem fogad el**, ha a maximum lehetséges payout már feladáskor a szerver cap fölött lenne;
- Kincsem ugyanez;
- stake levonás ELŐTT hibát ad;
- settlement oldali cap csak defensive/legacy protectionként maradt.

#### Odds/RTP újrakalibrálás
A korábbi extrém DNB/handicap/correct-score oddsok túl büntetők voltak, extreme handicap rounding pedig pici >100% RTP edge-et is adhatott.

Most elméleti audit több rating-különbségen:
- 1X2: ~93.3–93.7%
- Double Chance: ~94.4–97.2%
- Goals O/U: ~93.0–93.9%
- BTTS: ~93.2–93.7%
- DNB: ~95.2–97.1%
- Half-time: ~93.2–93.7%
- Handicap: ~93.1–99.1%, **nincs >100% edge**
- Correct Score: ~90.8–91.0%

Correct Score:
- a nagyon valószínűtlen score-ok nem jelennek meg hamis, alulfizetett 50x oddsszal;
- csak >=0.4% model probability score kerül piacra;
- odds cap 250x;
- max payout gate továbbra is védi az economy-t.

### Kincsem balance
Longshot odds capek korábban túl alacsonyak voltak. Új capek:
- Win max 35x
- Top2 max 15x
- Top3 max 10x

2500 random 6-lovas mezőny exact Plackett–Luce audit:
- Win ~91.5–92.0% RTP
- Top2 ~92.2–93.0%
- Top3 ~93.0–95.4%

### MÁV balance
1M crash-szimuláció, fix cashout stratégiák:
- 1.05x ~96.1% RTP
- 1.10x ~96.1%
- 1.18x ~96.2%
- 1.25x ~96.3%
- 1.5x ~96.4%
- 2x ~96.6%
- 3x ~96.6%
- 5x ~96.5%
- 10x ~96.6%
- 25x ~96.9%

Cél: kb. 3–4% house edge, payout truncation nélkül.

### Poker audit
12,000 legális, teljesen szimulált 2–6 fős hand:
- side-pot payout összege = pot;
- final stacks + payouts = induló összes chip;
- nincs Yoru által generált extra pénz a hand engine-ben.

### QA v3.24.3
- `compileall`: PASS.
- MÁV 135B @1.18 regression: PASS → 159.3B.
- delayed pre-crash click timestamp settlement: PASS.
- post-crash click loss: PASS.
- exactly-once runtime refund: PASS.
- parallel MÁV session isolation: PASS.
- 20x duplicate settlement: PASS, 1 payout.
- active-MÁV Rob target + robber protection: PASS.
- Robbery stale/spam stage: PASS.
- duplicate robbery cashout: PASS, 1 payout.
- timed-out robbery session cleanup: PASS.
- Betting wallet-only: PASS.
- Tippmix/Kincsem over-cap pre-acceptance rejection: PASS.
- Poker legal-action conservation: PASS, 12,000 hands.
- Slash static audit: estimated **85 top-level app commands**, GroupCog subcommand maximum jelenleg 21; Discord top-level 100-as limit alatt.

---

## 6. v3.24.4 — MÁV Backend-First Architecture Hotfix

Éles videós reprodukció alapján a v3.24.3 MÁV továbbra is képes volt 1.5x körül vizuálisan/belsőleg hosszú másodpercekre megállni, majd csak később crash-elni.

### Root cause

A v3.24.3 runner crashkor rossz sorrendet használt:

`crash deadline → final Discord message.edit → 8 sec grace sleep → DB crash settlement`

Ez azt jelentette, hogy egy lassú/rate-limited Discord edit és a mesterséges 8 másodperces grace közvetlenül késleltette a pénzügyi lezárást. A backend ugyan timestamp-alapú volt, de a tényleges crash state nem lett azonnal commitolva.

### v3.24.4 fix

Az új kötelező sorrend:

`crash deadline → atomic DB settlement AZONNAL → UI task cancel/throttle → best-effort final Discord edit`

- **Nincs több `MAV_CASHOUT_GRACE_SECONDS`.**
- A crash runner deadline-aware sleepet használ, tehát nem overshootol egy teljes UI tickkel.
- Live Discord refresh 1.0 sec-re throttled, és külön taskban fut.
- Lassú/rate-limited `message.edit()` többé semmilyen módon nem késleltetheti a crash settlementet.
- Final crash edit szintén külön best-effort task; a pénz már előtte lezárult.

### Késve beérkező Cashout fair kezelése

A 8 sec globális grace helyett a service már egy **már commitolt crash-et is képes pontosan egyszer korrigálni**, ha a Discord callback késve érkezik, de az immutable `interaction.created_at` bizonyítja, hogy a játékos a crash deadline **előtt** kattintott.

Flow:
1. backend deadline-kor azonnal `crash` commit;
2. később beérkező callback timestamp ellenőrzés;
3. ha click < crash deadline → zero-payout crash atomikusan cashoutra korrigálható;
4. payout exactly-once;
5. 20 párhuzamos azonos late callbackből csak egy `mav_late_cashout:<session>` pénztranzakció készül; minden további callback idempotensen ugyanazt az eredményt látja.

Crash UTÁN timestampelt click soha nem korrigálható.

### Interaction acknowledgement hardening

A cashout pénzügyi feldolgozása többé nem függ attól, hogy a Discord `interaction.response.defer()` sikerül-e.
Ha az acknowledgement `Unknown interaction` / HTTP hibával elkésik, Yoru ettől még feldolgozza a hiteles click timestampet és settle-öli a játékot.

### Rob race fix

A korábbi EconomyService-level Rob guard mellé bekerült a **DB tranzakciószintű MÁV exclusion** is a `rob_wallet` és `pay_rob_fine` pénzmozgásokba.
Ez lezárja azt a race-et, ahol a MÁV session az első Rob-check után, de a tényleges wallet transfer előtt indult el.

### QA v3.24.4

- `compileall`: PASS.
- v3.24.3 service stability regression: PASS.
- Poker conservation regression: PASS, 12,000 hand.
- MÁV 135B @1.18x: PASS → 159.3B.
- backend crash → utólag érkező pre-deadline click correction: PASS.
- post-deadline click: PASS → crash marad.
- 20x concurrent late cashout: PASS → 1 wallet credit / 1 transaction.
- Rob DB transaction-level MÁV guard: PASS mind robber, mind victim oldalon.
- static architecture gate: settlement hívás megelőzi a terminal Discord editet; nincs grace sleep.
- Balance regression változatlan: MÁV cél ~96–97% RTP; Tippmix/Kincsem/rablás audit továbbra is a v3.24.3 tartományban.

---

## 7. Aktuális commandok a v3.24.4 érintett részeihez

### Jobs
- `!job`, `!jobs`, `!munka`, `!munkak`, `!munkák`
- Boltrablás és Bankrablás a selectorban.
- `/jobs shoprob`
- `/jobs bankrob`
- Régi direkt kompatibilitás:
  - `!boltrablas`, `!boltrablás`, `!shoprob` → `/live shoprob`
  - `!bankrablas`, `!bankrablás`, `!bankrob` → `/live bankrob`

### MÁV
- `!mav <tét>`
- alias: `!máv`, `!crash`
- példák: `!mav 500k`, `!mav 135b`, `!mav all`
- `/live mav tet:<összeg|all>`
- `all` = wallet only.

### Betting
- `!betting`, `!fogadas`, `!fogadás`, `!tippmix`
- `/betting open`
- admin persistent panel:
  - `!bettingpanel`, `!betpanel`, `!fogadaspanel`, `!fogadáspanel`
  - `/betting panel`
- settings: `!settings` → Fogadás.
- külön napi result Forum beállítás itt található.

### Poker
- `!poker <buyin>` → `/live poker`
- `!pokerhand`, `!lapjaim`, `!kezem` → `/live pokerhand`
- wallet-only buy-in.

### Live settings
- `!settings` → Live
- `/live settings`
- Live max payout felirat/jelentés: **Rablás max payout**, MÁV-ra nem vonatkozik.

---

## 8. Következő teendő

Elsőként **v3.24.4 éles MÁV/multiplayer stress teszt** valódi Discordon, különösen:
- 3–5 párhuzamos MÁV;
- cashout spam nagyon nagy balance-szal;
- rob próbálkozás aktív MÁV ellen;
- bot/cog restart aktív MÁV alatt;
- több user Tippmix/Kincsem settlement ugyanabban a percben;
- Poker több valódi userrel, AFK/reconnect helyzetek.

Ha ez tiszta, következő fő release: **v3.25 Visual Overhaul**.

Prioritás:
1. Plinko teljes UI/gameplay presentation rework: bet controls, Drop Ball, több párhuzamos ball, staggered animation.
2. Casino visual consistency.
3. Jobs presentation.
4. Live World/MÁV presentation.
5. Betting/Poker UI polish.
6. régi economy embedek egységesítése.

A vizuális overhaul előtt ne változtassuk meg újra a settlement logikát indok nélkül.

---

## 9. MÁV-ból levont kötelező architekturális szabály

Helyes sorrend minden pénzes játékban:

`backend state / immutable input timestamp → atomic DB settlement → committed result → Discord render/edit`

**Soha fordítva.**

- Discord message edit nem lehet gameplay clock.
- Discord API failure nem tarthat stake-et hostage-ként.
- UI callback latency nem módosíthatja a játékos tényleges döntési időpontját.
- Minden settlement idempotens legyen.
- Minden session izolált legyen.
- Accepted odds/payout szabályt utólag ne csonkolja rejtett cap; cap esetén a fogadást előre kell elutasítani.

---

## 10. Roadmap update – Casino UX, Auto/Fast Spin, future casino expansion

### Kötelező fázis a v3.25 Visual Overhaul ELŐTT: UI Design Approval

A Visual Overhaul kódolása előtt először közösen véglegesíteni kell a Yoru vizuális rendszerét.

Flow:
1. több eltérő UI-template/mockup készül a fő játéktípusokra;
2. külön GIF/animáció prototípusok készülnek, hogy Discordon ténylegesen látható legyen a tempó és a mozgás;
3. összehasonlítjuk mobil + desktop nézetben;
4. kiválasztjuk a végleges Yoru design language-et;
5. csak jóváhagyott template után indul a teljes UI implementáció.

Véglegesítendő elemek:
- header / footer szerkezet;
- játékos név + avatar elhelyezés;
- bet / payout / profit / balance HUD;
- gombméretek és gombkiosztás;
- normál / hover-equivalent / disabled / running / finished állapotok;
- bet-control panel;
- tipográfia és spacing;
- képek/GIF-ek mérete és centering;
- mobil safe layout;
- animáció timing;
- success/loss/cashout/crash vizuális állapotok;
- egységes Yoru ikon- és assetnyelv.

### v3.25 – Casino Visual & Interaction Foundation

Első konkrét rework továbbra is a Plinko, de a cél már egy közös casino interaction framework létrehozása, amit a többi játék is újrahasznál.

Tervezett közös casino controls, ahol az adott játék mechanikája engedi:
- Bet `-` / `+`;
- `1/2`;
- `x2`;
- egyedi tét beállítás;
- `ALL` wallet-only;
- Spin / Play / Drop;
- Fast Spin / Turbo mód;
- Auto Spin;
- Auto Spin stop;
- session profit/loss;
- utolsó payout;
- aktuális balance;
- játék-specifikus risk/rows/lines/etc. controls.

Fontos: nem minden játék kap vakon ugyanazt a kontrollt. A shared framework közös, de a játék mechanikájához igazodik.

### Kötelező vizuális design-elv – közös framework, egyedi játékidentitás

A Yoru Casino vizuális rendszere NEM azt jelenti, hogy minden játék ugyanúgy nézzen ki.

Alapszabály:
**közös engine / UX framework + játékonként egyedi art direction.**

Generikus/common játékoknál elfogadható az erősebben egységes, hasonló vizuális megjelenés, például:
- Blackjack;
- Roulette;
- Coinflip;
- Dice;
- egyszerűbb table/utility gambling játékok.

Ezek használhatnak nagyon hasonló:
- header/footer rendszert;
- HUD-ot;
- bet-control panelt;
- tipográfiát;
- spacinget;
- gombelrendezést;
- alap háttér/keret logikát.

Ezzel szemben minden egyedi, saját karakterrel rendelkező casino játék – például Candy Rush és a későbbi online-casino-inspired címek – kapjon külön vizuális identitást. A Plinko a generic Yoru Casino framework referenciaimplementációja. Kötelezően lehessen eltérő:
- háttér és környezet;
- színpaletta;
- symbol/candy/card/object assetek;
- frame-ek és HUD styling;
- layout hangulat;
- ikonok;
- animációk;
- particle/VFX;
- win/loss/bonus/cascade prezentáció;
- játék-specifikus typography vagy dekoráció, ahol indokolt.

A közös framework ezek alatt maradjon egységes:
- settlement/state architecture;
- input és button lifecycle;
- bet-change logika;
- Fast Spin / Auto Spin infrastruktúra;
- wallet-only és money safety;
- session kezelés;
- Discord rate-limit safe render flow;
- accessibility/mobile readability alapelvek.

Tehát egy Candy Rush-szerű cascade játék, egy Plinko, egy tower game és egy későbbi új slot vizuálisan ne ugyanannak a template-nek az átszínezése legyen. Az egyediség a cél, miközben a felhasználói működés és a backend framework konzisztens marad.

UI Design Approval fázisban ezért nem csak egyetlen globális template-et kell jóváhagyni: legyen egy közös Yoru Casino UX foundation, majd az egyedi játékokhoz külön art-direction/template/GIF approval, mielőtt az adott játék végleges visual implementationje elkészül.

### Fast Spin

Fast Spin célja: a normál animáció rövidítése/kihagyása, NEM a settlement safety megkerülése.

Architektúra:
`input → atomic settlement → committed result → gyors/minimális render`

A backend settlement sebessége nem függhet a GIF/message edit sebességétől.

### Auto Spin

Később Slot és minden arra alkalmas ismétlődő játék kapjon Auto Spin módot.

Tervezett opciók:
- 10 / 25 / 50 / 100 spin;
- folyamatos mód manuális Stop gombbal, ha Discord UX-ben stabilan megoldható;
- Auto Spin közben a tét fix marad, amíg a user külön nem állítja le;
- insufficient wallet esetén automatikus stop;
- session lock: ugyanaz a user ne tudjon párhuzamosan két Auto Spin loopot indítani ugyanabban a játékban;
- stop/restart/disconnect esetén no duplicate settlement;
- minden spin külön idempotens transaction;
- Discord rate limit nem blokkolhat settlementet;
- UI update throttled lehet, miközben a backend korrekt marad.

Későbbi, opcionális Auto Spin auto-stop feltételek, amelyeket NEM kell az első Auto Spin verzióba erőltetni, de amikor eljutunk az Auto Spin fejlesztési fázisához, EZEKET KÖTELEZŐ újra megemlíteni Krisznek és közösen eldönteni, melyek kerüljenek be:
- Stop at profit / célprofit elérése, pl. +500M session profit;
- Stop at loss / max session veszteség, pl. -250M;
- Stop on Big Win / előre definiált nagy nyeremény után;
- Stop on Bonus / Free Spins trigger után;
- opcionálisan Stop on balance threshold / minimális wallet elérésekor;
- opcionálisan Stop after X consecutive losses/wins, csak ha balance és UX szempontból indokolt.

Fontos roadmap reminder: amikor az Auto Spin framework implementációja ténylegesen elkezdődik, az asszisztens külön hívja fel a figyelmet erre az auto-stop opciólistára a kódolás előtt, ne legyen csendben automatikusan implementálva vagy kihagyva.

Discord miatt Fast/Auto Spin esetén nem cél a webkaszinós 10+ render/sec. Inkább gyors backend + kontrollált UI refresh / szükség esetén összesített animation/result flow.

### Plinko rework – első referenciaimplementáció

- interaktív személyes panel;
- bet controls;
- **nincs Risk selector**;
- egy standard random-drop paytable;
- közép = gyakori/kis payout, szélek = ritka/nagy payout;
- Drop Ball;
- Fast;
- Auto Drop;
- több aktív labda;
- staggered drops;
- több labdát együtt mutató animáció;
- payout-bin HUD;
- session P/L;
- backend-first settlement;
- spam-click / multi-ball / restart / duplicate settlement safety.

A Plinko lesz a minta arra, hogyan nézzen ki a későbbi Yoru casino interaction framework.

---

## 11. Future Casino Expansion

A Visual Foundation után további, valódi online kaszinókból ismert játéktípusok implementálhatók Yoru-s, saját névvel és saját témával.

Irányelv:
- mechanika inspiráció rendben;
- saját név;
- saját grafika;
- saját ikonok;
- saját UI/layout;
- saját szövegek;
- saját hang/animáció, ha lesz;
- ne másoljuk 1:1-ben az eredeti brand assetjeit vagy vizuális identitását.

Candy Rush jelenlegi iránya is ezt kövesse: a cascade / falling-symbol / cluster-win mechanika maradhat, de Yoru saját theme-je és vizuális identitása legyen.

Tervezett jövőbeli casino expansion lehet például:
- több cluster/cascade slot;
- multiplier/cascade játékok;
- tower/ladder risk game;
- limbo jellegű multiplier game;
- wheel / prize wheel;
- keno/bingo-szerű gyors játék;
- baccarat;
- video poker;
- új table/card game-ek;
- további original Yoru casino játékok.

A konkrét listát külön design/balance körben véglegesítjük; új játék csak payout/RTP + settlement audit után kerülhet release-be.

---

## 12. Casino IP / licensing fejlesztési szabály

A projektben ne abból induljunk ki, hogy egy létező kaszinójáték egyszerű átnevezése automatikusan jogilag biztonságossá teszi a klónt.

Gyakorlati Yoru-szabály:
**mechanic-inspired, expression-original.**

Vagyis reprodukálhatunk általános játékmeneti ötleteket/mechanikákat, de ne vegyük át 1:1-ben:
- eredeti játék nevét / brandjét;
- logót;
- karaktereket;
- candy/symbol asseteket;
- háttérgrafikát;
- hangokat;
- animációkat;
- szövegeket;
- forráskódot;
- felismerhetően azonos teljes UI megjelenést.

Ha egy konkrét online kaszinójátékot akarunk Yoru-ba átültetni, először külön bontsuk szét:
1. mi a puszta mechanic;
2. mi az eredeti játék creative expression/branding része;
3. ezek helyére tervezzünk saját Yoru megoldást.

---

## 13. Frissített release agenda

1. v3.24.4 éles stability validáció – jelenleg működőnek jelentve.
2. UI Design Approval phase – templatek + GIF prototípusok, közös döntés a végleges UI-ról.
3. v3.25.0 – Plinko Rework + Casino Interaction/Visual Foundation.
4. v3.25.x – Slot + alkalmas casino játékok Fast Spin / bet controls alapjai.
5. Auto Spin framework és játék-specifikus integrációk – ekkor külön fel kell hozni és jóvá kell hagyatni az opcionális profit/loss/Big Win/Bonus auto-stop feltételeket.
6. Casino V2 + régi gambling játékok teljes visual migrationje.
7. Jobs UI overhaul.
8. Live World UI overhaul.
9. Betting + Poker UI overhaul.
10. Economy UI egységesítés.
11. Future Casino Expansion – további online-casino-inspired, saját Yoru játékok.

Minden további release-nél ezt a `PROJECT_HANDOFF.md` fájlt kell továbbvezetni; ne készüljön külön ROADMAP/CHANGELOG/AUDIT fájlhalom.

---

# v3.25 DESIGN LOCK + RELEASE STATE

## Végleges Yoru visual framework lock (2026-08-13)

A UI Design Approval phase lezárult.

Végleges generic casino vizuális irány:
- **Clean Minimal Dark** alap;
- sötét/fekete felület;
- Yoru lila/magenta accent;
- kevés dekoráció, erős game-first fókusz;
- mobilon is jól olvasható HUD;
- a nagy játékfelület/render legyen a fő fókusz;
- alatta natív Discord componentek;
- natív Discord gombszíneket használunk, nem próbálunk nem létező custom button-colort imitálni;
- renderelt image/GIF + natív Discord buttons/select/modal elválasztás;
- Discord UI/API failure soha nem módosíthat pénzügyi outcome-ot.

A felhasználó által jóváhagyott Plinko referencia layout a generic casino framework alapja.

### Generic vs. egyedi játék vizuális szabály – véglegesített

A generic/common casino játékok erősen egységes frameworket és vizuális nyelvet használhatnak.

Az egyedi játékok saját grafikát, hátteret, symbol/asset készletet és egyedi játékspecifikus prezentációt kapnak, DE nem szabad teljesen más univerzumnak érződniük. Az összes egyedi játék maradjon ugyanabban a Yoru vizuális családban:
- clean/dark alap;
- visszatérő spacing/typography/HUD logika;
- visszafogott Yoru accentek;
- hasonló quality level;
- közös interaction lifecycle;
- saját art direction, de ne radikálisan eltérő design system.

Tehát: **közös vibe + közös UX framework + játékonként saját grafika/identitás**.

## Plinko végleges design/gameplay lock

A korábbi Low / Medium / High Risk selector TÖRÖLVE.

A Plinko egyszerű standard random-drop játék:
- nincs Risk selector;
- nincs külön risk paytable;
- a játékos tétet állít és labdát dob;
- minden peg döntés fair 50/50 left/right;
- 10 soros binomial board;
- **középső slot = gyakori és kis payout**;
- **szélső slot = nagyon ritka és nagy payout**;
- több labda együtt/staggered animálható;
- Fast mód kihagyja/rövidíti a hosszú animációt;
- Auto Drop támogatott;
- backend-first settlement minden labdánál.

### v3.25.0 standard Plinko paytable

Balról jobbra:
`50x | 3.5x | 2.2x | 1.2x | 0.65x | 0.20x | 0.65x | 1.2x | 2.2x | 3.5x | 50x`

10 soros fair binomial path mellett exact base RTP:
**95.64453125%**.

Ez a paytable code-owned Casino RTP/paytable. A Plinko panel azt a multipliert mutatja, amit ténylegesen fizet; ne legyen rejtett post-result payout scaling/cap, ami eltér a boardon kijelzett értéktől.

## v3.25.0 – Plinko Rework + Generic Casino UI Framework

Állapot: IMPLEMENTÁLVA ebben a release-ben.

Új `app/casino_ui_framework.py`:
- locked clean-dark/Yoru purple visual tokenek;
- közös compact amount formatter;
- közös wallet-only bet-control logika;
- `ALL` wallet-only;
- `1/2`, `-`, `+`, `x2` controls;
- nincs money movement a bet-control kattintáskor, csak a tényleges Drop/Spin reservál stake-et.

Plinko panel:
- `ALL | 1/2 | - | + | x2`
- `DROP BALL | FAST | AUTO`
- nincs Risk selector;
- HUD: Active Balls / Total Bet / Profit-Loss;
- clean minimal dark render + lila/magenta payout accent;
- több friss labda egyetlen közös GIF-ben, staggered starttal;
- max 10 vizuálisan együtt kezelt labda;
- Fast módban statikus/gyors result refresh hosszú GIF nélkül;
- Auto Drop: 10 / 25 / 50 / 100 / inf;
- Auto gomb futás közben Stop Auto-vá változik;
- Auto futás alatt a bet controls + manual Drop le van tiltva, tehát az Auto stake fix marad a teljes run alatt; Fast továbbra is toggle-olható;
- insufficient wallet / backend error esetén Auto leáll;
- ugyanazon Plinko panelen a settlementek serializáltak;
- egy user/guild egyszerre egy aktív Plinko panelt kap; új panel lezárja a régit.

### Plinko safety architecture

Minden labda:
`button/auto input → atomic wallet reserve → RNG → atomic settlement → committed result → render queue`

A rendererben NINCS pénzmozgás.
A Discord message edit/GIF hiba nem refundolja és nem duplázza a már settled labdát.
Bot restartnál csak egy esetleg begin és settle között maradt ACTIVE Casino session recovery/refundolható a már meglévő Casino recovery által.

Auto UI Discord rate-limit protection:
- Auto alatt a settlementek gyorsabban történhetnek, mint a render;
- a render queue több eredményt összevon;
- Discordot nem próbáljuk 10+ edit/sec sebességgel frissíteni;
- a vizuál csak best-effort display, a DB ledger az authority.

### v3.25.0 QA

- compileall: PASS;
- Plinko exact RTP: 95.64453125%;
- 500,000 deterministic simulation: ~95.70% RTP;
- 500k distribution check: a center slot >150x gyakoribb volt, mint egy edge slot;
- paytable symmetry: PASS;
- center-low / edge-high invariant: PASS;
- PNG renderer: PASS;
- 10-ball combined GIF renderer: PASS;
- generated 10-ball GIF < 1 MB a QA mintában;
- component layout static audit: 5 bet buttons row 0 + 3 action buttons row 1;
- slash `/casino plinko` többé nem kér Risk argumentumot;
- régi `!plinko <tét> medium` prefix form kompatibilitásból nem törik el, a legacy risk argumentum figyelmen kívül marad;
- új slash command nem került be, tehát top-level slash count nem nőtt.

## v3.25.0 commandok

Prefix:
`!plinko <tét>`
alias: `!plink <tét>`

Példák:
`!plinko 10m`
`!plinko 5b`
`!plinko all`

Slash:
`/casino plinko osszeg:<tét|all>`

A parancs most NEM azonnal egyetlen labdát játszik le; megnyitja a személyes interaktív Plinko panelt. Pénz csak a `DROP BALL`/Auto Drop tényleges labdáinál mozog.

Panel controls:
- `ALL` = aktuális wallet teljes összege, bankot nem érinti;
- `1/2` = selected bet felezése;
- `-` / `+` = casino bet ladder lefelé/felfelé;
- `x2` = selected bet duplázása, legfeljebb az aktuális walletig;
- `DROP BALL` = 1 labda;
- `FAST` = gyors/static display toggle;
- `AUTO` = 10 / 25 / 50 / 100 / inf Auto Drop modal;
- futó Auto alatt ugyanaz a gomb `STOP AUTO`.

## v3.25.1 – Plinko Large Display / Components V2 hotfix

Éles desktop teszten a v3.25.0 Plinko funkcionálisan működött, de a játéktér **túl kicsinek bizonyult**. A legacy Discord embed `set_image()` megjelenítés a nagy rendelkezésre álló chat-terület ellenére egy keskeny embed-kártyába szorította a 900×790 renderelt boardot. Emiatt a peg-ek, payout slotok és HUD nehezen olvashatók voltak.

### v3.25.1 display lock

A Plinko többé **nem legacy embed image**.

A panel `discord.ui.LayoutView` + Discord Components V2 alapra került:
- full-width `MediaGallery` tartalmazza a Plinko PNG/GIF-et;
- a native bet gombok külön `ActionRow` sorban vannak;
- a Drop/Fast/Auto gombok második `ActionRow` sorban vannak;
- nincs embed width bottleneck;
- a PNG és GIF ugyanazon MediaGallery helyen váltódik;
- a pénzügyi backend továbbra is teljesen független ettől a display rétegtől.

A renderer olvashatósági tuningot is kapott:
- nagyobb peg-ek;
- vastagabb triangle rail;
- nagyobb payout-slot magasság és betűméret;
- nagyobb labdák;
- nagyobb HUD label/value tipográfia;
- nagyobb title/bet amount typography.

A gameplay/paytable **nem változott**:
`50x | 3.5x | 2.2x | 1.2x | 0.65x | 0.20x | 0.65x | 1.2x | 2.2x | 3.5x | 50x`
Exact RTP továbbra is **95.64453125%**.

### v3.25.1 QA

- compileall: PASS;
- Plinko exact RTP változatlan: 95.64453125%;
- 1,000,000 deterministic simulation: ~95.44% (50x edge-ek miatt magas variance mellett elfogadható mintafutás);
- static renderer: PASS;
- 10-ball GIF renderer: PASS, ~0.55 MB QA mintában;
- Components V2 structure static audit: `LayoutView` + `MediaGallery` + 5-button bet ActionRow + 3-button action ActionRow;
- Plinko legacy embed-image path eltávolítva;
- money/settlement kód nem változott.

## v3.25.1 commandok

Nincs új command.

Prefix:
`!plinko <tét>` / `!plink <tét>`

Slash:
`/casino plinko osszeg:<tét|all>`

A változás kizárólag a Plinko panel megjelenítési rétegét és olvashatóságát érinti.

## Következő agenda v3.25.1 után

1. v3.25.1 éles Plinko validation: desktop + mobil méret, MediaGallery PNG/GIF váltás, több user, Auto/Fast/spam.
2. Generic Casino visual migration első hullám: Slots + egyszerűbb casino játékok.
3. Slot Fast Spin + bet controls.
4. Auto Spin framework játék-specifikus kiterjesztése.
   - EKKOR KÖTELEZŐ újra felhozni Krisznek a korábban eltett opcionális auto-stop listát: profit target, max loss, Big Win, Bonus/Free Spins, balance threshold, consecutive win/loss.
5. Mines / Chicken Road visual framework migration.
6. Egyedi játékok (Candy Rush és későbbi inspired játékok) saját, de Yoru-vibe-kompatibilis art directionnel.
7. Casino után Jobs → Live World → Betting/Poker → Economy UI overhaul.


## v3.25.2 – Plinko immutable animation queue + wide display hotfix

Éles spamteszten a v3.25.1 Plinko animáció több vizuális race-et mutatott: gyors Drop Ball spam mellett GIF-ek újraindultak, labdák eltűntek/újra megjelentek, egyes animációk nem futottak végig, és desktopon a board továbbra is túl kicsinek érződött.

### Root cause

A hiba több rétegből állt:
- minden új render új attachmentre cserélte az éppen játszott GIF-et, amitől a Discord kliens újraindította az animációt;
- `_pending_results` minden settlement után `[-10:]`-re lett csonkolva, ezért nagyobb spam burstnél régebbi, már pénzügyileg settled labdák vizuálisan kieshettek a queue-ból;
- a v3.25.1 fix `1.8s` után static frame-re váltott, miközben több labdás GIF ennél hosszabb is lehetett, tehát a bot saját maga vágta le az animáció végét;
- a ball path soronként csak egy frame-et kapott, ezért a labda inkább teleportált peg-ek között, mint folyamatosan pattogott;
- a 900x790 közel négyzetes boardot Discord desktopon magasság-limit miatt továbbra is túl kicsire skálázta.

### v3.25.2 animation architecture lock

A Plinko display queue most FIFO + immutable batch alapú:
- minden Drop pénzügyileg továbbra is backend-first settle-öl;
- a pending result queue NEM csonkolható, minden settled labdának vizuálisan is sorra kell kerülnie;
- maximum 10 labda kerül egy vizuális batchbe; további spam a következő FIFO batchbe kerül;
- ha egy GIF már elindult, azt sem új Drop, sem új pending batch nem cserélheti le a teljes animációs idő előtt;
- új Dropok a futó GIF közben csak queue-ba kerülnek;
- a következő batch csak az előző GIF tényleges időtartama után indul;
- batch-ek között nincs kötelező static flash;
- static final frame csak akkor kerül ki, amikor nincs pending batch;
- nincs több fix 1.8 másodperces animation clear timer;
- Fast mód továbbra is static/gyors display, de ugyanazt a FIFO queue-t használja.

### Smooth animation

- 2 subframe / peg-row;
- fractional ball position + bounce arc;
- több labda staggerelt indítással fut ugyanabban a GIF-ben;
- 10-ball animáció kb. 3.3 sec, és ezt a backend render worker ténylegesen kivárja, mielőtt másik attachmentre vált.

### v3.25.2 wide display

A renderer 900x790-ről 1280x700 landscape arányra változott.
Cél: Discord desktop max-height mellett sokkal nagyobb tényleges képszélesség.

A board szinte teljesen kitölti a landscape képet:
- nagyobb horizontális peg spacing;
- nagyobb payout slotok és feliratok;
- nagyobb balls;
- HUD kompakt marad;
- Components V2 MediaGallery megmarad.

Gameplay/paytable változatlan:
`50x | 3.5x | 2.2x | 1.2x | 0.65x | 0.20x | 0.65x | 1.2x | 2.2x | 3.5x | 50x`
Exact RTP: `95.64453125%`.

### v3.25.2 safety notes

- Auto futás alatt manuális Drop callback backend oldalon is rejectel, nem csak disabled UI-ra támaszkodik;
- Auto futás alatt bet-change callback szintén backend oldalon rejectel;
- render/UI továbbra sem authority és nem mozgat pénzt;
- settled labda renderhiba miatt nem refundolódhat vagy duplázódhat.

### v3.25.2 QA

- compileall: PASS;
- static wide renderer: 1280x700 PASS;
- 10-ball staggered GIF: 1280x700, 39 frames, ~1.1 MB PASS;
- exact RTP változatlan: 95.64453125%;
- immutable FIFO source audit: pending queue truncation eltávolítva;
- fixed 1.8s clear timer eltávolítva;
- 10-ball animation duration helper: ~3.3s;
- multi-batch policy: max 10 / batch, FIFO remainder következő batch;
- command/slash surface nem változott.

## v3.25.2 commandok

Nincs új command.

Prefix:
`!plinko <tét>` / `!plink <tét>`

Slash:
`/casino plinko osszeg:<tét|all>`

## v3.25.3 – Plinko UX Rework

### Implemented
- Removed separate `DROP BALL` button from the Plinko panel.
- Added dedicated manual batch buttons: `1 BALL`, `2 BALL`, `3 BALL`, `5 BALL`, `10 BALL`.
- The ball-count button is now the action itself: one click = one full batch/GIF with exactly that many balls.
- Manual play is hard-locked to one batch at a time; button spam no longer queues overlapping visual rewrites.
- Added `INFO` button for quick ephemeral panel state summary.
- Reworked Auto modal: it now asks for **round count** (`10 / 25 / 50 / 100 / inf`) and **balls per round** (`1 / 2 / 3 / 5 / 10`).
- Auto now runs round-based batches and waits for each visual batch to finish before starting the next one.
- Plinko HUD now respects the current selected batch size as the active-ball limit display instead of always showing `/10`.

### Locked UX rules
- Bet row: `ALL | 1/2 | - | + | x2`
- Manual batch row: `1 BALL | 2 BALL | 3 BALL | 5 BALL | 10 BALL`
- Utility row: `FAST | AUTO | INFO`
- During a manual batch animation, bet controls and manual ball buttons are disabled.
- During Auto, manual buttons remain disabled and Auto owns the rounds until stopped/finished.

### Notes
- This is a stability/UX iteration; it does not change the backend RTP or paytable.
- Visual overhaul direction remains locked to the v3.25 Plinko/Casino framework, with generic games sharing the common framework and unique games receiving their own matching graphics language.

## v3.25.4 – Plinko Animation/INFO Hotfix

### User-reported issues
- `INFO` button crashed with `NameError: compact_amount is not defined`.
- Manual Plinko GIF could take too long to appear and looked low-FPS/laggy.
- When a ball/batch reached the bottom, the GIF visibly restarted for a fraction of a second.
- After playback, the panel unnecessarily showed the balls parked in their landing slots.

### Root causes
- `compact_amount` was used by `PlinkoPanelView._info_callback` without importing it.
- Plinko GIFs were saved with `loop=0` (infinite loop); the UI then tried to replace the GIF with a static attachment after a timer, producing a visible first-frame restart/flash.
- The renderer repeatedly loaded fonts and redrew the entire static 1280x700 board for every frame.
- The static refresh reused recent results, intentionally drawing landed balls after the animation even though the desired UX is a clean board.

### Fixes
- Added the missing `compact_amount` import; INFO is functional again.
- Plinko GIF is now **one-shot**: no GIF loop extension is written.
- The final GIF frame is an **empty Plinko board** with the updated HUD; no landed balls remain on screen.
- Normal batch completion no longer swaps the GIF attachment for another static image. Only native buttons are re-enabled, eliminating the finish flash/restart.
- FAST/static Plinko results also return to a clean board instead of leaving balls in landing slots.
- Cached font loading and cached the immutable Plinko board background to reduce render latency.
- Animation timing changed from ~14 FPS to ~20 FPS (`70ms -> 50ms` frame cadence) and ball stagger was tightened (`2 -> 1` frame).
- Manual batch and Auto round now pre-check `bet_per_ball × balls_in_round` against wallet before starting, reducing partial-batch insufficient-wallet cases.
- If an unexpected backend error happens after some balls already settled, those settled results are still scheduled for display instead of disappearing.

### Locked Plinko end-state rule
After a manual/auto Plinko GIF finishes, the visible board must be clean: **no replay, no landed-ball markers, no attachment flash**. The updated Total Bet / Profit-Loss stays visible in the final frame.

## v3.25.5 – Plinko Batch Engine + Animation Polish

### User-reported issue after v3.25.4
- `10 BALL` után több másodpercig üresen állhatott a board, mielőtt a GIF elindult.
- A backend eredmény már kész volt, ezért a Total Bet / Profit-Loss a GIF előtt vagy annak elején elárulhatta a batch végső eredményét.
- Több labdánál a mozgás még darabosnak / túl sűrűn indítottnak érződött.
- A kívánt UX: gyors indulás, eredmény csak landing közben bontakozzon ki, a végén tiszta üres board.

### Root cause
A v3.25.4 manual/Auto batch továbbra is labdánként futtatta a teljes `begin -> DB reserve -> RNG -> settle` ciklust. Egy 10 labdás kattintás ezért 10 külön SQLite money lifecycle-t + akár 10 settlement-log lookup/send útvonalat várt meg, és csak ezután kezdődött a GIF render. A renderer pedig már a batch végleges összesített HUD értékeit kapta.

### Backend fix – true atomic batch settlement
- Új `Database.settle_casino_batch_immediate(...)` tranzakciós primitive.
- Új `CasinoService.settle_immediate_batch(...)` service API.
- 1/2/3/5/10 Plinko labda most **egy `BEGIN IMMEDIATE` SQLite tranzakcióban** reserve + settle-öl.
- A teljes szükséges stake (`bet_per_ball × ball_count`) wallet-only módon, a tranzakción belül kerül ellenőrzésre.
- Ha a teljes batchre nincs wallet, **0 labda / 0 levonás** történik.
- Bármely transaction/DB hiba esetén az egész batch rollbackel; részleges charge/settlement nem maradhat bent.
- Minden labda továbbra is külön `casino_sessions` rekordot, reserve/payout ledger sort és külön gambling play/statot kap. A 10 BALL tehát statisztikailag továbbra is 10 Plinko play.
- Jackpot contribution is per-ball szabály szerint számolódik, de ugyanabban az atomikus tranzakcióban.
- Batch settlement audit/log delivery a commit UTÁN background best-effort fut, így egy 10-ball action nem vár 10 Discord log sendre.
- Process-local one-active-casino-game guard a teljes batchre fennmarad.

### Double-click / spam safety
- Manual batch indítás state lockkal atomikusan claimeli a panelt.
- Két közel azonos idejű BALL callback közül csak az első indíthat batch-et; a második busy választ kap.
- Bet-change és FAST callback is ugyanazzal a state lockkal koordinál, így nem tud a selected bet batch-start közben megváltozni.
- Manual batch alatt új manual batch nincs queue-zva.
- Auto továbbra is egy teljes batch/kör elkészülését + animáció végét várja meg a következő kör előtt.

### Progressive visual timeline
- Backend továbbra is **backend-first**: a batch pénze a GIF előtt már final.
- A GIF azonban külön vizuális timeline-t kap: a HUD nem a backend final state-et mutatja az első frame-től.
- `TOTAL BET` és `PROFIT / LOSS` csak akkor lép előre, amikor az adott labda vizuálisan ténylegesen eléri a slotját.
- Landolt labda csak egy rövid landing frame-en látszik, utána eltűnik; nem gyűlnek a slotokban a későbbi labdák alatt.
- Final frame: üres board + végleges HUD. Nincs replay, landed-ball state vagy utólagos attachment swap.

### Animation timing
- 3 movement substep / peg-row a simább mozgáshoz.
- 3-frame stagger @ 40 ms = kb. 120 ms indulási távolság labdánként.
- 10 BALL: 59 frame, ~25 FPS frame cadence, kb. 2.58 s one-shot playback.
- 1280x700 Components V2 landscape board változatlan.
- Cached fonts + cached static board továbbra is használatban.

### QA
- all Python files `py_compile`: PASS.
- Atomic 10-ball SQLite batch test: PASS; 10 settled sessions, 10 reserve ledger, 10 payout ledger, `gambling.plinko.plays += 10`.
- Insufficient-wallet atomic rollback: PASS; wallet/session count változatlan.
- Game-ID collision rollback: PASS; új session sem kerül részlegesen be.
- 10-ball GIF: 59 frames, no loop extension, 2580 ms playback, final clean frame.
- Renderer local generation: ~1.0 s test environmentben, ~1.5 MB GIF.
- Exact Plinko RTP/paytable változatlan: `95.64453125%`.
- Slash/command surface változatlan.

## v3.25.5 commandok / settings
Nincs új command és nincs új admin/settings menüpont.

Prefix:
`!plinko <tét>` / `!plink <tét>`

Slash:
`/casino plinko osszeg:<tét|all>`

Panel:
- Bet: `ALL | 1/2 | - | + | x2`
- Manual: `1 BALL | 2 BALL | 3 BALL | 5 BALL | 10 BALL`
- Utility: `FAST | AUTO | INFO`
- Auto: körök `10 / 25 / 50 / 100 / inf`, labda/kör `1 / 2 / 3 / 5 / 10`.

## v3.25.6 – Plinko Media Lifecycle Hotfix

### User-reported issue after v3.25.5
Új manual kör indításakor (különösen `10 BALL`) a Discord egy rövid időre **újra lejátszotta az előző kör GIF-jét** a régi HUD-dal (`TOTAL BET`, `PROFIT / LOSS`), majd hirtelen átváltott az új kör GIF-jére. Ez egyértelműen régi-media replay volt, nem RNG/batch settlement hiba.

### Root cause
A v3.25.5 one-shot GIF már nem tartalmazott loop extensiont, de a lejátszás után **maga a `.gif` attachment továbbra is az üzenethez volt kötve**. A panel csak `message.edit(view=...)` hívással engedte vissza a gombokat. Discord kliensoldalon egy már befejezett GIF attachment bármely későbbi message/component edit hatására újra renderelődhet / újrajátszódhat. A következő BALL click elején végzett button-disable `message.edit(view=...)` ezért röviden újraindította round N GIF-jét, mielőtt round N+1 új GIF-je elkészült és feltöltődött.

### Final fix – strict media lifecycle
Plinko media state explicit állapotgépet kapott:
- `STATIC`: idle/nyugalmi állapot, kizárólag PNG attachment;
- `ANIMATED`: csak az aktívan játszott batch GIF idejére.

Új kötelező lifecycle:
`STATIC round N-1 -> unique GIF round N -> full playback -> clean STATIC PNG round N -> controls unlock -> next action`

Részletek:
- A clean final PNG **már a GIF indítása előtt elkészül**. Normál animációnál nem külön újrarenderelt board: a bot a kész GIF **saját dekódolt utolsó frame-jét** menti PNG snapshotként.
- Emiatt a GIF utolsó frame-je és a final PNG nem csak logikailag, hanem pixel/palette szinten is megegyezik; a `GIF -> PNG` cleanup nem okozhat szín/fényerő villanást.
- A gombok csak akkor oldhatók fel, ha a static PNG replacement Discordon sikeresen megtörtént.
- Ha a static cleanup Discord API hiba miatt többszöri retry után sem sikerül, a panel **nem nyílik vissza stale GIF fölött**; Auto leáll, és új panel szükséges. Inkább locked UX, mint replay/race.
- Component-only `message.edit(view=...)` **tilos**, amíg `_media_state == "ANIMATED"`.
- `close_panel` sem editeli az animated message-et csak azért, hogy szürkítse a gombokat; a backend `interaction_check` továbbra is rejecteli a stale interactiont.
- Auto `visual idle` csak akkor teljes, ha render task kész, nincs pending batch, nincs aktív animáció **és media state STATIC**.

### Unique attachment generation
A korábbi fix filename-ek (`plinko.gif`, `plinko.png`) helyett minden media update egyedi generation filename-et kap, pl.:
- `plinko_<user>_<generation>_round.gif`
- `plinko_<user>_<generation>_idle.png`
- `plinko_<user>_<generation>_static.png`

Ez csökkenti a Discord/CDN/client cache reuse esélyét és explicit round-media identitást ad.

### Regression rule
A következő sequence minden jövőbeli animált Discord játéknál kötelező teszt:
1. round 1 GIF elindul;
2. round 1 teljesen lefut;
3. message attachment már PNG, nem GIF;
4. következő action button-disable/edit történik;
5. round 1 GIF nem jelenhet meg újra;
6. round 2 saját, új filename-ű GIF-je indul;
7. round 2 után ismét PNG idle state.

### Command/settings surface
Nincs új command, slash command, admin command vagy Settings menüpont.

Prefix:
`!plinko <tét>` / `!plink <tét>`

Slash:
`/casino plinko osszeg:<tét|all>`

---

## v3.25.7 – Plinko No-Edit Media Lifecycle Hotfix

### Tünet
A v3.25.6 után az előző kör már nem a *következő* button-disable editnél indult újra, de a videón továbbra is látszott egy rövid replay artifact közvetlenül a kör végén: a labdák leértek, majd a GIF egy pillanatra visszaugrott a korábbi animáció egyik frame-jére, utána jelent meg az üres final board.

### Valódi root cause
A v3.25.6 feltételezése részben hibás volt. Nem elég, hogy a one-shot GIF-et playback után PNG-re cseréljük. **Maga a GIF -> PNG cleanup `message.edit()` is újrarenderelheti / újraindíthatja a még csatolt GIF-et a Discord kliensben**, még akkor is, ha ugyanabban az editben a bot már statikus PNG-re akar váltani.

### Végleges media lifecycle
Normál Plinko körnél:
1. backend batch settlement final;
2. új GIF teljesen elkészül memóriában;
3. **egyetlen Discord media edit** cseréli le az előző STATIC/GIF_IDLE médiát az új GIF-re;
4. GIF egyszer lefut;
5. playback után **nincs semmilyen message edit**;
6. a GIF clean final frame-en marad, internal state = `GIF_IDLE`;
7. következő roundnál a következő új GIF már elkészül, és egyetlen direct replacement edit váltja le az előzőt.

Nincs több:
- pre-round button-disable edit;
- GIF -> PNG cleanup edit;
- post-round button-enable edit;
- Auto-finish component edit;
- bet/Fast main-panel edit completed GIF felett;
- timeout/close component edit completed GIF felett.

### Interaction safety
A gombok vizuálisan kattinthatók maradnak, mert a Discord komponensek disable/re-enable állapota message editet igényelne. **A valódi spam/concurrency védelem backend `_state_lock` + session state**, ezért extra kattintás pénzt nem mozgat és ephemeral rejectet kap. Ez a kötelező minta későbbi animált játékoknál is.

### Control UX kompromisszum
- `AUTO` label nem vált dinamikusan `STOP AUTO`-ra, mert a labelváltás message edit lenne. Futó Auto alatt ugyanaz az `AUTO` gomb stopként működik, és ephemeral visszajelzést ad.
- Bet/Fast változás completed GIF (`GIF_IDLE`) felett csak backend state-ben frissül + ephemeral visszajelzés. Az új érték a következő round új médiáján jelenik meg.
- Ha a panel még valódi STATIC PNG állapotban van (pl. friss panel vagy FAST eredmény), static component/media frissítés továbbra is engedett.

### Retry rule
Animált GIF media uploadnál `retries=1`. Egy bizonytalan állapotú animált edit vak retry-ja önmagában replayt okozhat. Static fallbacknél retry továbbra is engedett.

### Regression invariant
Normál round sequence:
`old STATIC/GIF_IDLE -> backend batch -> render new GIF -> ONE message.edit -> GIF_ACTIVE -> playback -> internal GIF_IDLE -> ZERO message.edit`

Következő round:
`GIF_IDLE -> backend batch -> render next GIF -> ONE direct replacement edit`

Kötelező teszt: két-három egymás utáni `10 BALL` körnél az előző GIF **se a kattintás pillanatában, se a kör végén, se a következő round renderelése közben nem jelenhet meg újra**.

### Money / RTP
Nincs payout, paytable vagy wallet semantics változás. Exact Plinko RTP marad `95.64453125%`; wallet-only és atomikus batch settlement változatlan.

### Release QA
- 98 Python fájl `py_compile`: PASS.
- 10-ball GIF: 59 frame, 1280×700, one-shot (`loop=None`), renderer timing 2.58s.
- Source invariant audit: accepted manual round előtt nincs main-message edit; playback után nincs media/view edit; `GIF_ACTIVE -> GIF_IDLE` csak internal state change; `_edit_view_only` csak valódi `STATIC` PNG állapotban engedett; animated media replacement retry = 1.
- Ez a lifecycle **éles Discord kliens-validációt továbbra is igényel**, mert a replay artifact kliensoldali Discord viselkedés volt.

### Command/settings surface
Nincs új command, slash command, admin command vagy Settings menüpont.

Prefix: `!plinko <tét>` / `!plink <tét>`
Slash: `/casino plinko osszeg:<tét|all>`

---

# PLINKO MASTER POSTMORTEM / JÖVŐBELI ANIMÁLT JÁTÉK CHECKLIST

Ez a rész **nem csak Plinko dokumentáció**, hanem kötelező tervezési szabálygyűjtemény minden későbbi Yoru animált/pénzes játékhoz (Slots, Chicken Road, Mines animációk, Candy Rush, új tower/cascade/ball games stb.). A Plinkónál végigzongorázott hibákat ezekkel a szabályokkal már első implementációban ki kell küszöbölni.

## A. Discord display sizing
### Hiba
A renderer technikailag nagy felbontású volt, de legacy embed image-ként Discord keskeny oszlopba skálázta, ezért desktopon olvashatatlanul kicsinek érződött.
### Fix
- Components V2 `LayoutView + MediaGallery` a nagy játékmedia számára.
- Landscape arány (`1280x700` jelleg), ne magas/négyszögletes canvas, ha Discord magasság-limit skálázza.
- Nagyobb peg/symbol/slot/font spacing; a tényleges Discord megjelenési méretet kell tesztelni, nem csak a raw pixel resolutiont.
### Általános szabály
**Raw resolution != perceived Discord size.** Desktop és mobil screenshot/video validation kötelező.

## B. Interaction spam / overlapping render
### Hiba
Minden Drop új rendert/GIF attachmentet indított és lecserélte a már futót. Labdák eltűntek, újra megjelentek, GIF-ek restartoltak.
### Korai részfix
FIFO queue + immutable batch.
### Végleges UX
Manual Plinko nem spamelhető Drop queue: `1 / 2 / 3 / 5 / 10 BALL` batch gombok. Egy manual batch fut egyszerre. **v3.25.8-tól a külön controls message vizuálisan is disable-ölhető**, mert nem tartalmaz GIF-et; a backend state lock ettől függetlenül továbbra is rejecteli a második/spam actiont.
### Általános szabály
Egy interakció elején **backend state lockkal** claimeld a session/actiont. Disabled button önmagában nem concurrency protection.

## C. Queue truncation
### Hiba
`pending[-10:]` miatt már settled labdák vizuálisan elveszhettek.
### Fix
Settled result queue soha nem csonkolható implicit módon. Batch max-size külön legyen a queue retentiontől.
### Általános szabály
**Financially committed result must never disappear because of display queue truncation.**

## D. Animation duration mismatch
### Hiba
Fix 1.8s timer statikusra váltott, miközben 10-ball GIF hosszabb volt; a bot saját maga vágta le az animációt.
### Fix
Renderer timing constantsból számolt exact playback duration helper.
### Általános szabály
Soha ne hardcode-olj UI clear timert az animáció valódi frame/duration modelljétől függetlenül.

## E. Low-FPS / teleport movement
### Hiba
Labda rowonként egy frame-et kapott; peg-ek között teleportáló hatás.
### Fix
Fractional interpolation + substeps + bounce arc; később 3 substep/row és ~25 FPS körüli cadence.
### Általános szabály
FPS emelés önmagában nem elég: **movement interpolation** fontosabb, miközben render size/CPU továbbra is kontrollált.

## F. GIF render latency / CPU
### Hiba
Minden GIF frame újratöltötte fontokat és újrarajzolta a teljes statikus boardot.
### Fix
Font cache + immutable/static board cache + csak változó layer kompozitálása, ahol lehetséges.
### Általános szabály
Animált rendernél első designban válaszd szét: `static background` vs `dynamic sprites/HUD`.

## G. Infinite loop GIF / finish restart
### Hiba
`loop=0` = végtelen GIF. Timerrel próbáltuk statikusra váltani, ezért a végén újraindult egy pillanatra.
### Fix
One-shot GIF: loop extension elhagyása.
### Általános szabály
Pillow/GIF API semantic audit kötelező: `loop=0` nem one-shot, hanem infinite.

## H. Landed balls maradtak a boardon
### Hiba
Animáció után recent results statikus renderben is szerepeltek.
### Fix
Final/idle board clean: `results=()`. A labda landing után röviden látszik, majd eltűnik.
### Általános szabály
Külön definiáld a játék **animation final frame** és **idle panel state** UX-ét; ne örököld véletlenül a result-history sprite-okat.

## I. INFO NameError
### Hiba
`compact_amount` callbackben használva import nélkül.
### Fix
Hiányzó import.
### Általános szabály
Release gate: `py_compile/compileall` + minden új UI callback smoke path. Undefined-name/import regresszió release előtt nem mehet ki.

## J. Sequential DB settlement caused startup delay
### Hiba
10 BALL = 10 külön `begin -> reserve -> RNG -> settle` SQLite lifecycle + settlement log útvonal; GIF csak ezután indult.
### Fix
`settle_casino_batch_immediate` / `settle_immediate_batch`: teljes 1/2/3/5/10-ball round egy `BEGIN IMMEDIATE` atomikus transactionban.
### Általános szabály
Ha UX szerint egy action egy batch, a backend settlement primitive is legyen **batch-native**, ne N darab public single-action API egymás után.

## K. Partial insufficient funds
### Kockázat
Labdánkénti settlementnél batch közben fogyhat el a wallet.
### Fix
Teljes batch stake tranzakción belüli wallet check; insufficient esetén 0 labda, 0 charge.
### Általános szabály
Batch stake = `unit stake × count`; reserve/check atomikusan az egész batchre.

## L. Final P/L spoiled before animation
### Hiba
Backend már settle-ölt, renderer pedig rögtön final Total Bet/P&L-t mutatott, mielőtt a labdák vizuálisan landoltak.
### Fix
Backend ledger state és visual timeline szétválasztása. GIF HUD landing eventenként halad base -> final irányba.
### Általános szabály
**Backend-first does not mean UI-result-first.** Backend eredmény lehet final, miközben a presentation timeline kontrolláltan fedi fel.

## M. Manual vs Auto mixing
### Kockázat
Manual Drop, bet change vagy Fast click versenyezhet Auto körrel.
### Fix
State lock + backend callback rejection az authority. **Animated display message-en visual controls tilosak; külön controls message-en a disable/enable biztonságos.** Auto round-based: balls/round + rounds, minden round visual-idle-t vár.
### Általános szabály
UI disabled csak presentation. Minden tiltás backend/state oldalon is enforce-olandó.

## N. Discord GIF replay lifecycle — v3.25.6 -> v3.25.8
### Hiba
A one-shot Plinko GIF több külön módon is újraindulhatott Discordon. Először a cleanup `message.edit()` okozott rövid replayt, később v3.25.7-ben éles videó bizonyította, hogy **még bot-side display edit nélkül is** újraindulhat az előző GIF, amikor a játékos ugyanazon Discord message egyik button komponensére kattint.

### Elégtelen részfixek
- **v3.25.6:** playback után GIF -> PNG cleanup + unique filename. A cleanup edit maga is replay artifactot okozott.
- **v3.25.7:** no-edit-after-start lifecycle. Ez megszüntette a bot saját pre/post editjeit, de nem tudta megakadályozni, hogy a **Discord component interaction/ACK ugyanazon a message-en újrarenderelje a csatolt GIF-et**.

### Valódi root cause
**Animated media + interactive controls ugyanabban a Discord message-ben nem tekinthető stabil architektúrának.** A Discord kliens a component interaction feldolgozásakor újrarenderelheti a message-et, és ezzel a már lefutott GIF korábbi frame-jeit újra lejátszhatja. Ez kliens/UI lifecycle jelenség, nem RNG, settlement vagy queue hiba.

### Végleges architekturális fix — v3.25.8
A Plinko két fizikailag külön Discord message-re lett szétválasztva:
1. **DISPLAY MESSAGE** — csak Components V2 `MediaGallery` + PNG/GIF; **0 interaktív component**.
2. **CONTROL MESSAGE** — csak `ALL/1/2/-/+/x2`, `1/2/3/5/10 BALL`, `FAST/AUTO/INFO`; **0 animált attachment**.

A button interaction kizárólag a control message-et érinti. A display message csak akkor változik, amikor egy teljesen elkészült új PNG/GIF közvetlenül lecseréli a korábbi médiát.

### Általános szabály
**Interaktív animált Discord casino UI-nál a display és a controls külön message legyen.**
- animated display message: no buttons/selects/modal trigger components;
- control message: no GIF/animated attachment;
- component ACK soha ne ugyanazt a message-et érje, amelyik a GIF-et tartalmazza;
- backend state lock továbbra is authority a double-click/spam ellen;
- display media replacement csak teljesen elkészült új assettel történjen.

Ez a szabály kötelező a későbbi Slots Fast/Auto, Candy Rush és minden új GIF-es/interaktív casino frameworknél.

## O. Discord API/edit/render failure ownership
### Kötelező szabály
- Money/RNG/session settlement mindig backend authority.
- GIF/PNG generation, upload, `message.edit`, MediaGallery state csak presentation.
- Render failure nem refundolhat már settled játékot és nem generálhat új payoutot.
- Static lifecycle cleanup failurenél inkább lockold/leállítsd a panelt, mint hogy stale animated state mellett engedd a következő pénzes actiont.

## P. Required regression suite for every future animated money game
Minden ilyen új játék/rework release előtt legalább:
- single action;
- max batch/action count;
- double click same millisecond/burst;
- manual spam;
- bet change race;
- Fast toggle race;
- Auto start/stop race;
- insufficient wallet before action;
- wallet changes between panel open/action;
- `ALL` wallet-only;
- bank untouched;
- atomic rollback injected DB failurenél;
- duplicate settlement/idempotence;
- render exception after settlement;
- Discord edit exception after settlement;
- old GIF/media must not replay next interactionnél; **különösen button click/ACK alatt**;
- animated display és controls külön Discord message-en legyenek; display message-ben 0 interactive component;
- final GIF frame clean/empty; display media csak a következő teljesen elkészült asset direct replacementjekor változzon;
- animation exact duration vs lifecycle timer;
- mobile + desktop perceived size;
- concurrent different users session isolation;
- restart/cog reload recovery;
- RTP/EV exact + simulation audit;
- command/slash-limit audit.

## Q. Current Plinko locked architecture after v3.25.12
- Wallet-only stake; `ALL` wallet-only.
- Standard 10-row / 11-slot pure 50/50 peg path; nincs Risk selector.
- Center = common low payout; edges = rare high payout.
- Paytable: `50x | 3.5x | 2.2x | 1.2x | 0.65x | 0.20x | 0.65x | 1.2x | 2.2x | 3.5x | 50x`.
- Exact RTP: `95.64453125%`.
- Bet row: `ALL | 1/2 | - | + | x2`.
- Manual row: `1 BALL | 2 BALL | 3 BALL | 5 BALL | 10 BALL`.
- Utility: `FAST | AUTO | INFO`.
- Auto: rounds `10/25/50/100/inf`; balls per round `1/2/3/5/10`.
- Display and controls remain physically separate Discord messages: display = attachment only, controls = Components V2 buttons only.
- Backend = one atomic wallet-only batch settlement per manual/Auto round; Discord render/edit never controls money.
- **Authoritative playback lifecycle is intentionally simple and copied from Slots/Candy Rush:** `PNG idle -> atomic settle -> render GIF+final PNG -> install GIF -> wait full GIF duration + 0.35s grace -> install final PNG -> wait 0.45s static-confirm delay -> unlock/next round`.
- No `_pending_batches`, no render queue, no background playback worker, no speculative parallel render, no GIF-idle state, no early PNG swap.
- Auto calls the same `_play_batch()` routine sequentially; it cannot begin the next round until the previous round has returned from final PNG + static-confirm delay.
- Final PNG is pre-generated from the GIF's exact decoded final frame, so the normal `GIF -> PNG` swap is pixel-identical.
- If final PNG cannot be confirmed after an installed GIF, the panel is locked/closed instead of allowing another round from an uncertain animated state.
- `(edited)` on the display attachment message remains an accepted Discord-native compromise for now.

## R. Current roadmap after Plinko stabilization
1. **Validate v3.25.12 on real Discord** with repeated manual `10 BALL`, mixed 1/2/3/5/10 BALL, FAST, and Auto. The key invariant is boring by design: after every normal round the visible display must be PNG for at least 0.45s before another manual round can unlock; Auto must use the exact same lifecycle sequentially.
2. If v3.25.12 is stable, freeze the Plinko playback implementation. Do not reintroduce queue/worker/speculative-lifecycle complexity unless a measured requirement proves it necessary.
3. Generic Casino visual migration first wave: Slots + common Casino interaction framework reuse.
4. Slots Fast Spin / bet controls: preserve the already-stable Slots playback primitive; controls should be added around it, not by replacing it with Plinko's discarded experiments.
5. Auto Spin framework expansion. **Before implementation, explicitly discuss with Krisz** optional stops: profit target, max loss, Big Win, Bonus/Free Spins, minimum wallet threshold, consecutive wins/losses, manual Stop.
6. Mines / Chicken Road visual migration with distinct-enough game graphics but shared Yoru casino vibe.
7. Unique titles (Candy Rush and future games) get their own art direction while sharing backend/control safety framework.
8. Jobs visual overhaul.
9. Live World visual overhaul.
10. Betting & Poker visual overhaul.
11. Economy/general UI overhaul.
12. Only after stability/UI foundation: additional casino-inspired games with original branding/art/expression.

## v3.25.8 – Plinko Split Display / Control Architecture

### Éles tünet a v3.25.7 után
A felhasználói videóban a `10 BALL` megnyomásakor az előző kör GIF-je újraindult, majd az új GIF elkészülésekor hirtelen átváltott az aktuális körre. A régi Total Bet / Profit-Loss frame-ek visszaugrása bizonyította, hogy valóban az előző GIF replayelt.

### Root cause
A v3.25.7-ben a bot már nem editelte a Plinko message-et a button click pillanatában, mégis replay történt. Következtetés és éles bizonyíték: a Discord kliens **maga a same-message component interaction/ACK során** újrarenderelheti a message-et, ami újraindítja a csatolt one-shot GIF-et.

### Fix
- `PlinkoDisplayView`: Components V2 MediaGallery-only view, 0 button/select.
- `PlinkoPanelView`: controls-only LayoutView, 0 media attachment.
- Slash flow: original response = display, followup = controls.
- Prefix flow: első bot message = display, második bot message = controls.
- `_replace_media()` kizárólag `display_message.edit(..., view=display_view)` hívást használ.
- `_edit_view_only()` kizárólag `control_message.edit(view=controls)` hívást használ.
- Manual batch alatt a külön control message vizuálisan disable-ölhető; backend `_state_lock` továbbra is védi a race-et.
- Auto alatt a control message dinamikusan `STOP AUTO` állapotot mutathat, replay veszély nélkül.
- Display GIF lifecycle és money/RNG/batch settlement nem változott.

### QA
- 98 Python fájl `py_compile`: PASS.
- Static source split-routing audit: PASS.
- Display view source-ban nincs `discord.ui.Button`.
- Media edit csak `display_message`-re megy; control edit csak `control_message`-re megy.
- Plinko exact RTP változatlan: `95.64453125%`.

## v3.25.9 – Components V2 Control Message Hotfix

### Symptom
- Opening the split Plinko panel failed after the display message was created.
- Discord returned `400 Bad Request / 50035` with: `The 'content' field cannot be used when using MessageFlags.IS_COMPONENTS_V2`.
- Prefix traceback pointed at the controls-only send: `ctx.send(content="\\u200b", view=view)`.

### Root cause
- `PlinkoPanelView` is a `discord.ui.LayoutView`, which uses Discord Components V2.
- The v3.25.8 split architecture correctly separated display and controls, but the controls-only message was still given a zero-width `content="\\u200b"` placeholder.
- Components V2 rejected the message because `content` was present at all; an invisible/empty-looking character is still message content.

### Final fix
- Prefix controls message: `ctx.send(view=view)`.
- Slash controls message: `interaction.followup.send(view=view, wait=True)`.
- Removed the zero-width content placeholder entirely.
- Source audit confirmed there are no remaining `content="\\u200b"` sends in the app.

### Permanent framework rule
- A controls-only `LayoutView` / Components V2 message must be sent as a component-only message. Do **not** add placeholder message content, including zero-width characters.
- When splitting animated casino UI into DISPLAY + CONTROL messages:
  - DISPLAY: media-only Components V2 message.
  - CONTROL: controls-only Components V2 message.
  - Do not add dummy `content` merely to make either message look non-empty; the components/media are already valid message payloads.
- Add this to the pre-release runtime/API compatibility audit for every future Components V2 migration; Python compile cannot catch Discord API payload validation errors.

### Regression check
- Both prefix and slash Plinko open paths were inspected.
- Plinko controls send contains no `content=` field.
- Full Python compile gate must remain mandatory, but this incident demonstrates that source/API-shape audits are also required for Discord payload constraints.
## v3.25.10 – Plinko Fundamental Media Lifecycle Reset

### Why another architecture change was necessary
After v3.25.8/v3.25.9, controls and display were physically separated, yet live video still showed the previous round replaying while the next round GIF was being prepared. This proved that the remaining problem was not only same-message button ACK behavior. The display itself was still left in an idle GIF state and still used Components V2 `MediaGallery`, unlike the already-stable Slots implementation.

The user correctly proposed the simpler Slots-like lifecycle: keep a real static PNG between rounds, generate the next GIF from that known state, play it once, update money/HUD visually during the animation, then return to PNG before another round can start.

### Root cause of the remaining replay
- Plinko display idle state was still a finished GIF attachment (`GIF_IDLE`).
- Starting the next display replacement could make Discord briefly rerender/replay that old attachment while the new GIF was being uploaded/applied.
- `MediaGallery` added another Discord Components V2 rendering layer that Slots does not use.
- Therefore split DISPLAY/CONTROL messages alone were insufficient while DISPLAY itself retained an idle GIF.

### Final v3.25.10 architecture
- Removed `PlinkoDisplayView` / display-side `MediaGallery`.
- Display message is now **plain attachment-only**, with no View, no components, no content dependency.
- Control message remains a physically separate `LayoutView`.
- Initial state: static `plinko.png`.
- Normal manual/Auto round:
  1. display is confirmed `STATIC` PNG;
  2. backend atomically settles the batch;
  3. GIF is rendered using previous visual totals as the HUD base;
  4. exact final-frame PNG is extracted/precomputed before playback;
  5. one attachment edit installs the new GIF;
  6. GIF plays once;
  7. one attachment-only edit replaces it with the precomputed final PNG;
  8. `_media_state` returns to `STATIC`;
  9. only then are controls unlocked / Auto allowed to advance.
- FAST skips GIF and directly installs the final PNG.
- Every round uses unique filenames.

### Why this intentionally mirrors Slots
Existing Slots already uses the proven pattern `slots.gif -> sleep(animation duration) -> slots.png` on a normal non-interactive media message. Plinko now uses the same primitive instead of a custom MediaGallery lifecycle. Future casino framework work must prefer already-proven Discord primitives over inventing a more complex media lifecycle without a concrete need.

### Plinko master postmortem additions / permanent rules
1. **Never leave an animated attachment as the idle state of a repeatedly interactive game.** Idle must be static media.
2. **Reuse proven architecture from an existing stable game when the requirements match.** Slots already demonstrated GIF->PNG; future work should inspect working project patterns before designing a new Discord lifecycle.
3. **Separate three states explicitly:** financial truth, animation timeline, Discord message attachment state. They may advance at different times and must not implicitly control each other.
4. **Precompute cleanup assets before playback.** Do not wait for the GIF to end and only then begin rendering the PNG.
5. **Controls unlock only after static-idle restoration succeeds.** This makes `PNG -> GIF -> PNG` an invariant rather than a best-effort cosmetic step.
6. **Display/control split still applies** for interactive animated games: buttons cannot live on the animated message.
7. **Plain attachment-only display is preferred over Components V2 MediaGallery** when the game only needs one full-size animated asset and direct attachment replacement.
8. **No result spoiler:** backend may already be settled, but the GIF HUD starts from the prior PNG totals and reveals bet/P&L only as balls land.
9. **No partial batch:** 1/2/3/5/10 BALL is one atomic backend batch.
10. **Regression test for every future animated casino game:** run at least 3 consecutive rounds and verify `STATIC -> ANIMATED -> STATIC` after every round, with no old-frame replay at next interaction.

### Superseded Plinko experiments
Historical v3.25.6-v3.25.9 notes remain in this file for changelog/postmortem value, but their media-lifecycle recommendations are **not authoritative** where they conflict with v3.25.10. In particular:
- `GIF_IDLE` is no longer permitted.
- display-side MediaGallery is no longer used.
- "zero edits after GIF starts until next round" is superseded by the proven explicit GIF->PNG finalization.

### v3.25.10 validation gate
- Python compile across runtime files.
- Exact Plinko RTP unchanged.
- GIF final frame == extracted idle PNG pixel-for-pixel.
- Source audit: Plinko display open path contains no display `LayoutView`/MediaGallery.
- Source audit: normal round contains GIF install followed by PNG install.
- Source audit: Auto visual-idle wait requires `_media_state == "STATIC"`.
- Live Discord validation still required because client playback behavior cannot be perfectly reproduced offline.

## v3.25.11 – Plinko Smooth Playback + Seamless Transition Pass

### Live feedback after v3.25.10
The fundamental `PNG -> GIF -> PNG` state machine was finally correct, but the real Discord video still showed two quality issues:
- some Plinko GIF runs visibly stuttered/lagged even though the animation logic itself was correct;
- the PNG/GIF transitions still felt slightly abrupt, and the display message's Discord-native `(edited)` marker remained visually annoying. The user approved leaving `(edited)` for now rather than introducing message rotation and another large architecture change.

### Root cause: GIF playback lag
The Plinko GIF used a static 1280×700 background but was encoded with GIF disposal mode 2. That caused effectively full-canvas frame storage/decoding for a 59/60-frame animation even though most pixels never changed. A representative 10-ball GIF was roughly 1.5 MB. This creates unnecessary upload, decode and Discord client playback pressure.

### Final playback optimization
- Plinko keeps the same large 1280×700 visual and same motion quality.
- Shared palette remains enabled.
- Plinko GIF now uses disposal mode 1, allowing unchanged background regions to remain and the encoded stream to behave as delta frames.
- `optimize=False` is intentionally retained because Pillow's full optimization made encoding much slower; disposal=1 alone gave the important size win.
- Regression comparison proved every decoded frame from disposal=1 is pixel-identical to the disposal=2 reference for the same deterministic round.
- Representative 10 BALL result: about 1.5 MB -> ~0.36–0.38 MB while retaining 60 frames and identical decoded playback.
- Warm local GIF render median is ~0.34 s on the test container.

### Start-latency fix: render and settlement in parallel
The old flow was effectively `atomic DB settlement -> GIF render -> upload`, so button-to-animation latency was the sum of backend and render time.

New flow:
1. RNG outcomes/payout math are prepared.
2. GIF/final-PNG rendering starts in a worker task.
3. The atomic wallet-only batch settlement runs concurrently.
4. **Nothing is uploaded before settlement succeeds.** Backend-first financial safety therefore remains intact.
5. After both complete, the already-prepared GIF is uploaded immediately.
6. If backend settlement fails, speculative media is discarded/cancelled and never shown.
7. If actual settlement math ever differs from the predicted render math, the speculative render is discarded and a correct fallback render is generated from authoritative settlement values.

This is the permanent rule for future deterministic animated money games: **speculative rendering may run concurrently with settlement, but speculative media may never be published before authoritative settlement succeeds.**

### Seamless PNG -> GIF -> PNG transition changes
- GIF frame 0 is now an exact idle-state timeline frame using the previous round's Total Bet / Profit-Loss. The motion starts only after that frame, matching the user's requested `previous PNG -> new GIF` model.
- The final GIF frame remains an empty board with the final HUD values.
- The final PNG is still extracted from that exact decoded final GIF frame, so GIF-final -> PNG pixels are identical.
- PNG replacement now begins shortly **after the GIF enters its final static hold frame**, rather than waiting for the entire final hold to expire. The upload/edit latency is therefore hidden while the player is already looking at the same final pixels.
- The `(edited)` badge is a Discord-native consequence of attachment edits and is intentionally accepted for now. Removing it would require delete/re-send message rotation, which risks message ordering/flicker and is deferred unless explicitly requested again.

### Button-to-start latency detail
The controls-only disable edit no longer blocks the gameplay path. It is dispatched concurrently; backend `_state_lock` remains the authoritative anti-spam/double-click protection. Therefore a slow control-message HTTP edit cannot delay GIF preparation.

### New permanent regression rules from v3.25.11
For every future animated casino game with a mostly static canvas:
1. Audit GIF/APNG/WebP frame encoding efficiency, not only FPS. A visually simple animation must not store a full high-resolution canvas per frame unnecessarily.
2. Compare optimized and reference animations by decoding **every frame**; optimization is accepted only when decoded frames match (or intentional visual differences are explicitly approved).
3. Record animation byte size, frame count, total duration and local render time in QA.
4. First animation frame should match the previous static state when the game is presented as `STATIC -> ANIMATED`.
5. Final animation frame should match the next static state when the game is presented as `ANIMATED -> STATIC`.
6. Hide final static-media upload latency inside an already-identical final animation hold where possible.
7. Backend settlement and rendering may overlap for latency, but publishing remains strictly settlement-gated.
8. Control-message network edits must never be a prerequisite for starting the financial/game/render path; server-side state lock is authoritative.
9. Do not reduce render resolution merely to hide inefficient encoding unless the user approves the visual-size tradeoff first.

### v3.25.11 QA snapshot
- Full Python compile: PASS.
- Plinko exact RTP: `95.64453125%`, unchanged.
- 500k deterministic simulation remained in expected vicinity (~95.46% in the v3.25.11 sample).
- 10 BALL: 60 frames, ~2.62 s encoded duration, no loop extension.
- Static PNG swap begins ~2.42 s into the 10-ball timeline, after the identical final frame has already started.
- Representative optimized GIF: ~366 KB.
- Warm render test: ~0.32–0.42 s, median ~0.34 s.
- GIF final decoded frame == extracted final PNG: pixel-exact PASS.
- Disposal=1 optimized playback vs disposal=2 reference: all decoded frames identical PASS.
- No commands, admin commands, settings paths, RTP or wallet/bank rules changed in this release.

## v3.25.12 – Plinko Simple Playback Reset (Slots/Candy Rush Pattern)

### Why this release exists
After v3.25.11, live Discord testing still showed that Plinko playback/transitions were unreliable despite multiple increasingly complex lifecycle hotfixes. The user correctly pointed out that existing Yoru games such as Slots and Candy Rush already play animations cleanly with a much simpler pattern. Source comparison confirmed that the remaining Plinko complexity itself had become the problem.

### Superseded v3.25.11 complexity
The following Plinko-specific mechanisms are intentionally removed from the authoritative controller:
- `_pending_batches`;
- `_render_task` / background render worker;
- `_media_state` state machine;
- `_animation_active`;
- speculative render running concurrently with settlement;
- early PNG swap during the GIF final hold;
- visual-idle polling loops.

These techniques are preserved in the changelog/postmortem as lessons, but they are **not** the current architecture and must not be copied into new animated games by default.

### New authoritative lifecycle
Every manual Plinko round is one coroutine with this exact order:
1. server-side state lock claims the round;
2. control buttons are visibly locked on the separate controls message;
3. RNG outcomes are generated;
4. the complete batch is atomically settled wallet-only in one DB transaction;
5. only after settlement succeeds, GIF + exact final PNG are rendered;
6. display attachment is replaced once with the GIF;
7. bot waits the **entire encoded GIF duration** plus `0.35 s` playback grace;
8. display attachment is replaced once with the exact final PNG;
9. bot waits `0.45 s` static-confirm safety delay;
10. only then are manual controls unlocked.

Normal round display edits are therefore exactly: `PNG -> GIF -> PNG`. Nothing touches the display during GIF playback.

### Auto rule
Auto has no independent animation engine. It simply awaits the same `_play_batch(balls_per_round)` function for every round. Because `_play_batch()` does not return until PNG + static-confirm delay is complete, Auto cannot overlap rounds or race the display lifecycle.

### Why this mirrors existing working games
- Candy Rush: settle -> render/send GIF -> sleep animation duration -> render/edit PNG -> done.
- Slots: result -> send GIF -> fixed animation sleep -> final PNG edit -> done.
- Plinko v3.25.12 now follows the same primitive while preserving its separate control panel and atomic multi-ball settlement.

### GIF performance adjustment
To reduce Discord client decode pressure without making the ball path visibly choppy:
- 10 BALL frame count reduced from 60 to **51**;
- frame interval changed from 40 ms (~25 FPS) to **50 ms (~20 FPS)**;
- ball stagger changed from 3 frames to 2 frames, preserving ~100 ms stagger;
- final static hold is 300 ms;
- representative deterministic 10 BALL GIF: ~340–345 KB, 51 frames, 2.8 s encoded duration;
- delta/shared-palette encoding remains.

### Permanent lesson from the Plinko hotfix chain
Before inventing a new playback/state architecture, **inspect existing proven project patterns first**. If Slots/Candy Rush already solve the same Discord media problem, copy the proven primitive and only add the minimum game-specific state required. Optimization should come after a stable simple lifecycle, not replace it.

### Failure ownership
- Settlement remains backend-first and atomic.
- If GIF rendering/upload fails after settlement, Yoru attempts to show the authoritative final PNG instead; money is never rolled back because of a display failure.
- If an installed GIF cannot be replaced by the final PNG, the panel is not allowed to start another round from an uncertain animated state.
- No Discord render/edit failure can create duplicate payout or partial batch settlement.

### v3.25.12 validation gate
- Full Python compile must pass.
- Source audit must find no Plinko pending queue/render worker/speculative render lifecycle.
- Normal `_play_batch()` order must be `settle -> render -> GIF edit -> full-duration wait -> PNG edit -> static-confirm wait`.
- Auto must call/await the same `_play_batch()` function.
- Exact RTP/paytable must remain unchanged.
- 10 BALL rendered GIF must be one-shot, final decoded frame == final PNG, and byte/frame/duration metrics recorded.
- Live Discord validation remains mandatory for repeated manual/Auto playback because client playback timing cannot be fully reproduced offline.

### Commands / settings
No command surface changed:
- prefix: `!plinko <tét>` / `!plink <tét>`;
- slash: `/casino plinko osszeg:<tét|all>`;
- no new admin command;
- no new Settings menu item.

