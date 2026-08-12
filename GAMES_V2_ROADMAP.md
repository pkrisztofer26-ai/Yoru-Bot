# YORU GAMES V2

## New Games + Interactive Early Game Roadmap

## 0. Projekt célja

A Yoru jelenlegi egyik fő problémája az early game gameplay loop:

`work → beg → search → cooldown → repeat`

Az új játékosnak kevés aktív tevékenysége van, ezért a játék első szakasza hamar monoton lesz.

A Games V2 célja két új pillér létrehozása:

### A) Interactive Jobs / Activities

A játékos akkor is tudjon aktívan játszani és pénzt keresni, amikor nincs gambling bankrollja vagy cooldownon vannak az egyszerű economy commandok.

### B) Új Casino / Multiplayer Games

A jelenlegi gambling játékok mellé kerüljenek:

- interaktív gambling játékok
- látványos/animált játékok
- cashout/risk játékok
- hosszabb multiplayer játékok
- server-wide betting játékok
- magyar/Yoru tematikájú játékok

A kiválasztott új játékok:

1. 🍬 Candy Rush
2. 💣 Mines
3. 🚂 MÁV Crash
4. 🔵 Plinko
5. 🐔 Chicken Road
6. ♠️ Texas Hold'em Poker
7. ⚽ Tippmix
8. 🐎 Lóverseny / Kincsem

---

# PART I – INTERACTIVE EARLY GAME

## 1. Alapelv

A jelenlegi:

- Work
- Beg
- Search
- Crime
- stb.

commandok NEM kerülnek eltávolításra.

Ezek maradnak gyors, cooldown-alapú pénzforrások.

Mellettük azonban megjelennek hosszabb, aktívan játszható munkák.

Az alapelv:

> Több játékidő + jobb teljesítmény = potenciálisan jobb reward.

Viszont:

- ne lehessen AFK farmolni;
- ne legyen korlátlanul exploitable;
- ne legyen kötelező;
- ne tegye értelmetlenné a sima Work commandot;
- 0 vagy nagyon kevés YC-vel is elérhető legyen.

---

# 2. 🚚 FUTÁR

## Koncepció

3–5 perces interaktív műszak.

A játékos több csomagot/fuvart teljesít egymás után.

Nem egyetlen RNG dobás határozza meg a fizetést.

## Gameplay

A játékos kap egy megbízást.

Példa:

**📦 Csomag #1**

A) Rövid út – alacsonyabb reward
B) Hosszabb út – jobb reward
C) Problémás cím – magasabb potenciális reward

Útközben események történhetnek:

- útlezárás
- dugó
- rossz cím
- késés
- sérült csomag
- extra fuvar
- borravaló
- sürgős kiszállítás

A játékos döntései módosítják:

- időt
- rewardot
- performance score-t

## Műszak vége

Rating:

`D / C / B / A / S`

A rating és a teljesített fuvarok alapján történik a payout.

---

# 3. 🔌 BORSODI LOPKODÁS

A korábbi Scrapyard/Lomizás koncepció Yoru/Magyarország tematikájú változata.

## Gameplay

Grid-based activity.

Például:

**5×5 grid**

A játékos limitált számú helyet vizsgálhat át.

Található:

- 🔩 fémhulladék
- 🔌 rézkábel
- 📺 elektronika
- 🚲 bicikli
- 💵 készpénz
- 📦 ritka loot
- 🗑️ értéktelen szemét

Lehetnek veszélyes/event mezők is.

A játékos célja a lehető legjobb loot megszerzése a rendelkezésre álló keresésekből.

## Fontos

Ez NEM fizetős Mines.

Nincs gambling bet.

A cél early-game income biztosítása aktív gameplayen keresztül.

A jelenlegi `/search` maradhat gyors verzióként.

A Borsodi Lopkodás annak nagyobb, interaktív megfelelője.

---

# 4. 🏦 HEIST LITE

GTA V / FiveM RP inspirációjú rövid küldetések.

Nem egyetlen `/crime` RNG roll.

A játékos ténylegesen végigjátssza a rablást.

## Első heistek

### 🏪 Boltrablás

Belépés

↓

kassza

↓

opcionális hátsó helyiség

↓

opcionális széf

↓

menekülés

### 🏦 Bankrablás

Nehezebb, hosszabb activity.

Több egymás utáni skill check/minigame.

Például:

1. bejutás
2. lockpick
3. security hack
4. vault
5. loot
6. menekülés

## Push-your-luck

A játékos bizonyos pontokon dönthessen:

**🏃 MENEKÜLÖK**

vagy

**💰 TOVÁBB A NAGYOBB LOOTÉRT**

Ha időben kilép:

megtartja a run lootját.

Ha később elbukik:

az adott heist lootjának egy részét vagy egészét elveszítheti.

A meglévő walletet early-game heistnél ne büntessük brutálisan.

## Extensible rendszer

Később ugyanarra az engine-re épülhet:

- benzinkút
- ATM
- ékszerbolt
- raktár
- páncélautó
- nagyobb bank

---

# 5. 📦 RAKTÁROS

Skill/memory alapú munka.

## Gameplay

Yoru megmutat rövid időre egy feladatsort.

Példa:

`A12 → C04 → B17 → A08`

Ezután eltűnik.

A játékosnak helyesen kell visszaadnia/kiválasztania a sorrendet vagy a megfelelő csomagokat.

## Progression egy műszakon belül

Minden hibátlan kör növelheti:

- combo
- performance
- reward multipliert

Hiba:

- combo reset
- időveszteség
- kisebb rating

A végén:

`D → C → B → A → S`

rating alapján payout.

---

# 6. 🚕 TAXI

GTA RP ihlette NPC fuvarrendszer.

## Gameplay

Egy műszak alatt több utas.

Példa:

> 👴 Pista bácsi
>
> Úticél: Vasútállomás
>
> Várható fizetés: 35–55k

Útközben döntési események:

- dugó
- útlezárás
- kerülőút
- problémás utas
- extra megálló
- gyorsabb, kockázatosabb út
- borravaló lehetőség

Egy teljes shift több egymást követő fuvarból áll.

A payout:

- fuvarok száma
- performance
- döntések
- random kisebb események

kombinációjából áll.

---

# 7. 🎮 SKILL JOB FRAMEWORK

Ezt nem külön játékként kell kezelni.

Ez egy újrahasznosítható framework, amelyre a Jobs és Heists épülnek.

## Újrahasznosítható minigame-ek

### Memory Grid

A játékos rövid ideig lát egy mintát.

Eltűnik.

Vissza kell állítania.

### Sequence

Például:

`7 → 3 → 9 → 2 → 5`

Eltűnik.

Helyes sorrendben vissza kell adni.

### Lockpick

Rövid interaction/timing/pattern minigame.

### Safe Crack

Kód/pattern alapú minigame limitált próbálkozással.

### Number / Logic Puzzle

Egyszerű, gyors puzzle.

## Technikai cél

Ne legyen minden activityben külön implementálva ugyanaz.

Lehetséges közös komponensek:

- `ActivitySession`
- `SkillCheck`
- `MemoryGame`
- `SequenceGame`
- `GridGame`
- `RiskCashout`
- `PerformanceRating`

A Futár, Taxi, Raktáros és Heist ugyanazokat a modulokat használhassa.

---

# PART II – ÚJ CASINO / GAMES

# 8. 🍬 CANDY RUSH

Az egyik flagship Yoru casino game.

## Alap

5×5 vagy 6×5 grid.

Nem klasszikus payline slot.

**Cluster/Cascade rendszer.**

Sok egymáshoz kapcsolódó azonos symbol → win.

## Cascade

Nyerő symbolok:

eltűnnek

↓

új symbolok beesnek

↓

új kombináció keresése

↓

ha ismét win → új cascade.

Egyetlen spin több egymást követő nyerést tartalmazhat.

## Multiplier

Cascade streakkel nőhet.

Például:

`x1 → x2 → x3 → x5 → x10`

A pontos görbét RTP simulation alapján kell balance-olni.

## Special

Scatter → Free Spins.

Free Spins alatt külön multiplier mechanic lehet.

## Animáció

Message edit:

grid

↓

winning cluster kiemelve / 💥

↓

eltűnt symbolok

↓

új grid

↓

következő cascade.

A játék vizuális élménye prioritás.

---

# 9. 💣 MINES

## Alap

5×5 button grid.

A játékos választ:

- bet
- mine count

Például:

3 / 5 / 10 / 15 / 20 mines.

## Gameplay

Minden mező:

💎 safe

vagy

💣 mine.

Safe után nő a cashout multiplier.

A játékos minden siker után dönt:

**TOVÁBB**

vagy

**CASHOUT**

Mine:

teljes aktív bet elveszik.

## Difficulty preset

Lehet:

🟢 Easy
🟡 Medium
🔴 Hard
💀 Borsod

A tényleges payout matematikailag a mine count + remaining tiles alapján számolandó, house edge figyelembevételével.

---

# 10. 🚂 MÁV CRASH

Yoru saját magyar Crash játéka.

## Shared multiplayer game

Nem külön instance minden játékosnak.

Egy közös MÁV Crash round fut a guild casino channelben.

## Betting phase

Például:

20 sec.

Minden játékos megadhatja a betjét.

## Round

Vonat elindul:

`1.00x`

↓

`1.14x`

↓

`1.39x`

↓

`1.82x`

↓

`2.41x`

↓

...

Minden játékosnak:

**💰 CASHOUT**

gomb.

Ha cashoutol x2.41-nél:

bet × 2.41 payout.

## Crash

Random, előre korrektül meghatározott crash point.

Példa:

> 🚨 A MÁV tájékoztatása szerint biztosítóberendezési hiba miatt a járat nem közlekedik.
>
> 💥 CRASH @ x4.82

Aki nem cashoutolt:

elveszíti a tétet.

## Magyar random crash message-ek

Többféle legyen, hogy ne ugyanaz jelenjen meg minden körben.

---

# 11. 🔵 PLINKO

## Setup

Játékos választ:

- bet
- risk level

Risk:

🟢 Low
🟡 Medium
🔴 High

## Gameplay

A golyó fentről indul.

Minden sorban:

balra vagy jobbra mozdul.

Discord embed/message edit animációval lefelé halad.

Végül valamelyik payout slotba érkezik.

## Risk

Low:

sűrűbb közepes payoutok.

High:

sok veszteséges/rossz multiplier, de ritka nagyon magas payout a széleken.

Példa:

`x0.2 | x0.5 | x1 | x3 | x20 | x100`

A pontos distribution RTP simulationből készüljön.

---

# 12. 🐔 CHICKEN ROAD

Push-your-luck cashout game.

## Gameplay

A csirke megpróbál átkelni az úton.

Minden sikeres lépés növeli a multipliert.

Példa:

`x1.12`

↓

`x1.31`

↓

`x1.65`

↓

`x2.20`

↓

`x3.10`

↓

...

Minden lépés után:

**➡️ TOVÁBB**

vagy

**💰 CASHOUT**

## Fail

Ha elüti egy autó:

`🚗💥🐔`

bet elveszik.

## Animáció

A csirke ténylegesen haladjon a Discord UI-ban.

Ne csak multiplier text változzon.

---

# 13. ♠️ TEXAS HOLD'EM POKER

Az egyik legfontosabb hosszabb multiplayer játék.

## Players

2–6 játékos.

## Lobby

Host létrehoz egy asztalt.

Beállítható:

- buy-in
- blinds
- max players

Más játékosok Join gombbal beléphetnek.

## Private cards

Minden játékos csak a saját hole cardjait láthatja.

## Teljes Texas Hold'em flow

- dealer/button
- small blind
- big blind
- hole cards
- pre-flop
- flop
- turn
- river
- showdown

## Actions

- Check
- Call
- Bet
- Raise
- All-in
- Fold

## Backend

Kötelező:

- hand evaluator
- betting rounds
- side pots
- split pots
- all-in kezelés
- disconnected/AFK player kezelés
- turn timeout

## Economy

A Poker alapvetően **nem generál új YC-t**.

A játékosok egymás pénzét nyerik.

Yoru opcionálisan kis rake-et vehet le a potról.

Ez fontos money sink lehet.

---

# 14. ⚽ TIPPMIX

Nem valódi pénzes vagy valódi sportfogadás.

Yoru saját, virtuális sportfogadási rendszere YC-vel.

## Első verzió

Yoru generál virtuális meccseket.

Példa:

> ⚽ Alsóbivaly FC
> vs
> Felcsút U99
>
> 1 — x2.20
> X — x3.40
> 2 — x2.85

A játékos YC-vel fogad.

## Meccs

Ne instant eredmény legyen.

A virtuális meccs rövid idő alatt „lejátszódik”.

Példa:

`23' ⚽ GÓL`

`51' 🟥 PIROS LAP`

`72' ⚽ 1–1`

`90+4' ⚽ 2–1`

Majd settlement.

## Későbbi bővítés

- accumulator / kötés
- over/under
- both teams to score
- exact score
- több virtuális sport
- napi/óránkénti fixture list

A rendszer ne használjon valódi sporteredményeket az első verzióban.

---

# 15. 🐎 LÓVERSENY / KINCSEM

Server-wide shared betting game.

## Betting phase

Minden futam előtt megjelenik 4–8 ló.

Mindegyik külön oddsot kap.

Példa:

🐎 Közpénz — x2.10
🐎 Hatósági Ár — x3.70
🐎 Provident — x8.20
🐎 MÁV Menetrend — x19.00

## Betting

20–30 sec betting phase.

Több játékos ugyanarra a futamra fogad.

## Race animation

A lovak ténylegesen haladnak.

Több frame:

Start

↓

első szakasz

↓

előzés

↓

utolsó szakasz

↓

finish.

Ne csak random winner embed legyen.

## Odds

Az oddsok és a lovak valódi underlying win probability-je egyezzen.

A house edge matematikailag kontrollált legyen.

## Theme

Magyar/Yoru shitpost lónevek nagy random poolból.

---

# PART III – KÖZÖS TECHNIKAI ARCHITEKTÚRA

Az új játékokat NEM különálló spaghetti code-ként kell implementálni.

## Shared Game Session

Közös session kezelés:

- player
- guild
- game type
- bet
- state
- started\_at
- finished\_at
- game ID

## Shared Betting Engine

Használja:

- MÁV Crash
- Tippmix
- Kincsem
- későbbi shared Roulette
- egyéb server-wide games

## Shared Lobby Engine

Használja:

- Poker
- későbbi multiplayer Blackjack
- későbbi PvP games

## Shared Grid Engine

Használható:

- Mines
- Candy Rush
- Borsodi Lopkodás
- Memory Grid
- későbbi grid games

## Shared Animation System

Discord message edit rate limitek figyelembevételével.

Animáció ne legyen blokkoló.

## Shared RNG

A gambling RNG legyen centralizált és tesztelhető.

A payout és displayed odds mindig egyezzen a tényleges backend probabilityvel.

---

# PART IV – MONTHLY JACKPOT INTEGRATION

A korábban elfogadott Monthly Global Jackpot rendszer az új house gamesre is vonatkozik.

A house ellen elveszített tétek konfigurálható kis része bekerül a havi jackpotba.

Ajánlott induló érték:

`1–3%`

például:

`2%`.

Jackpot contribution:

Candy Rush loss → igen
Mines loss → igen
MÁV Crash loss → igen
Plinko loss → igen
Chicken Road loss → igen
Tippmix house loss → igen
Kincsem house loss → igen

Poker:

**nem**, mert alapvetően player-vs-player.

---

# PART V – JAVASOLT FEJLESZTÉSI SORREND

## PHASE A – Existing Games Rework

A külön Existing Games Rework roadmap alapján:

- Casino Core
- Blackjack V2
- Slots V2
- Roulette V2
- Coinflip V2
- Dice V2
- RPS V2
- High/Low V2
- Chicken Fight V2
- Monthly Jackpot
- Lottery V2

---

## PHASE B – Interactive Activity Framework

Először az alap engine-ek:

- ActivitySession
- SkillCheck
- Memory
- Sequence
- Grid
- Performance Rating
- reward handling
- timeout handling

---

## PHASE C – Első Interactive Jobs

Első batch:

1. 📦 Raktáros
2. 🔌 Borsodi Lopkodás
3. 🚚 Futár

Ezekkel teszteljük a frameworköt.

---

## PHASE D – Complex Activities

4. 🚕 Taxi
5. 🏪 Boltrablás
6. 🏦 Bankrablás

A Heist Lite már több Skill Framework modult kombináljon.

---

## PHASE E – Új Casino Core Games

Első új gambling batch:

1. 💣 Mines
2. 🔵 Plinko
3. 🐔 Chicken Road
4. 🍬 Candy Rush

Ezek single-player játékok, ezért jók az új engine tesztelésére.

---

## PHASE F – Shared Casino

Közös server-wide betting engine elkészítése.

Utána:

5. 🚂 MÁV Crash
6. 🐎 Kincsem / Horse Racing
7. ⚽ Tippmix

---

## PHASE G – Poker

8. ♠️ Texas Hold'em

Külön nagyobb projektként.

Pokerhez:

- lobby engine
- private cards
- turn engine
- hand evaluator
- betting engine
- side pots
- reconnect/timeout
- AFK handling

szükséges.

Ne próbáljuk gyorsan összecsapni.

---

# PART VI – FONTOS DESIGN SZABÁLYOK

### 1. Ne legyen minden játék command → RNG → embed.

A játékosnak ahol értelmes:

- választania
- kattintania
- cashoutolnia
- stratégiát használnia
- más játékosokkal játszania

kelljen.

### 2. Látvány prioritás

Candy Rush cascade-je mozogjon.

Plinko golyó essen.

Chicken haladjon.

MÁV vonat menjen.

Kincsem lovai versenyezzenek.

Poker lapjai fokozatosan jelenjenek meg.

### 3. Discord rate limit

Az animációk legyenek látványosak, de ne használjanak értelmetlenül sok message editet.

### 4. Economy safety

Minden új gambling game előtt:

- probability calculation
- theoretical RTP
- simulation
- extreme payout simulation
- economy impact

kötelező.

### 5. 1B+ támogatás

Semelyik új rendszer ne feltételezze, hogy a balance vagy bet 1B alatt marad.

### 6. Slash command limit

Az új játékokat lehetőleg:

`/casino ...`

`/jobs ...`

jellegű group/subcommand struktúrába szervezzük.

Ne adjunk minden új feature-nek fölöslegesen külön top-level slash commandot.

### 7. Prefix támogatás

A meglévő Yoru filozófia szerint a fontos játékok prefixből is használhatók legyenek.

A prefix és slash ugyanazt a backend service-t használja.

### 8. Concurrency

Több játékos párhuzamos játéka nem keverheti össze:

- UI-t
- sessiont
- betet
- payoutot
- gombokat

### 9. Regression testing

Minden nagy release előtt ellenőrizni kell a Yoru korábbi ismert hibáit is, nem csak az új feature-öket.

---

# VÉGSŐ GAMES V2 STRUKTÚRA

## ⚡ Quick Economy

Work
Beg
Search
Crime
stb.

## 🧰 Interactive Jobs

🚚 Futár
🔌 Borsodi Lopkodás
📦 Raktáros
🚕 Taxi
🏪 Boltrablás
🏦 Bankrablás

## 🎮 Skill Framework

Memory
Sequence
Lockpick
Safe Crack
Grid
Logic/Puzzle
Performance system

## 🎰 Interactive Casino

🍬 Candy Rush
💣 Mines
🔵 Plinko
🐔 Chicken Road

## 🌐 Shared / Live Gambling

🚂 MÁV Crash
⚽ Tippmix
🐎 Kincsem

## ♠️ Multiplayer Strategy

Texas Hold'em Poker

## 🎰 Existing Casino

A külön Casino V2 Existing Games Rework roadmap szerint felújítva.

---

## Fő gameplay loop

A Games V2 után a cél:

**0 / kevés YC**

↓

Interactive Jobs / Work

↓

**bankroll építés**

↓

Casino / gambling

↓

Quick games / Interactive games / Shared games / Poker

↓

profit vagy loss

↓

ha elfogy a bankroll, továbbra is van aktív free content

↓

Interactive Jobs

Ez szünteti meg azt a jelenlegi problémát, hogy az early game lényegében csak:

`work → beg → search → cooldown`

és közben a meglévő economy rendszer továbbra is releváns marad.