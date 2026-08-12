# Yoru Casino – Existing Games Rework Roadmap

## Projektcél

> **Implementációs státusz**
> - ✅ v3.18.0 — Phase 1 / Casino Core
> - ✅ v3.19.0 — Main Rework: Blackjack + Slots + Roulette + Casino lobby polish
> - ✅ v3.19.2 — Visual Framework: game-first UI, large Slots display, individual animated Roulette, Casino audit log
> - ✅ v3.20.1 — Quick-game visual polish: collision-safe header, player badge, richer Coinflip/Dice/RPS/High-Low/Chicken animations
> - ✅ v3.20.0 — Quick Games + Monthly Jackpot/Lottery + Chicken Fight; a meglévő house-game catalog rework kész

A jelenlegi Yoru gambling rendszer teljes UX/gameplay reworkje úgy, hogy a meglévő játékok ne egyszerű `command → RNG → eredmény` economy commandok legyenek, hanem látványosabb, animáltabb, interaktívabb és egységes casino játékok.

Az első fejlesztési hullámban **nem új játékok hozzáadása a fő cél**, hanem a már meglévő játékok rendes újraépítése.

A későbbi új játékok — Mines, Candy Rush, Crash, Plinko, Poker stb. — csak ezután jönnek.

> **Végleges Casino UX standard:** game-first nagy display, mobilbarát layout, kompakt HUD, player branding, owner-locked interaction, egy aktív játék/player/guild, renderelés az event loopon kívül limitált concurrencyvel, smooth kliensoldali animáció, majd statikus final state. A belső Game ID csak DB/admin auditban jelenik meg.

---

# 1. Közös Casino Engine / alapelvek

Minden játék ugyanazokat a közös rendszereket használja.

## Egységes backend

Prefix és slash command ne külön játéklogikát használjon.

Példa:

`!bj 100k`

és

`/casino blackjack 100k`

ugyanazt a Blackjack game/service backendet indítsa.

## Bet reservation

A tétet a játék indulásakor reserve-olni kell.

Ezzel megakadályozzuk, hogy egy játékos ugyanazzal a wallet balance-szal több párhuzamos all-in játékot indítson.

## Game ID

Minden gambling kör kapjon egyedi ID-t.

Példa:

`BJ-827193`

Tároljuk:

- user
- guild
- game
- bet
- payout
- profit/loss
- multiplier
- timestamp
- result

Debughoz és statisztikához is használható.

## Egységes stat tracking

Minden játéknál legalább:

- games played
- wins
- losses
- pushes
- total wagered
- total payout
- net P/L
- biggest bet
- biggest win
- highest multiplier

## Central payout config

Minden RTP/payout/balance érték központi configból menjen.

Ne legyenek payout számok szétszórva több service/cog fájlban.

## Animációs szabály

Discord rate limit miatt ne legyen túl sok message edit.

Általában:

**3–6 frame / esemény**

elég ahhoz, hogy animációnak érződjön.

## User-lock

Más játékos ne tudja nyomkodni más aktív game UI-ját.

Más user kattintása:

> Ez nem a te játékod.

ephemeral válasszal.

## Finished state

Játék végén minden gomb automatikusan disabled.

---

# 2. Blackjack

A jelenlegi Blackjack backend jó alap, de ki kell bővíteni.

## Új funkciók

- Hit
- Stand
- Double Down
- Split
- Insurance
- Natural Blackjack kezelés
- több hand támogatás split esetén
- dealer animation

## Dealer animation

Ne jelenjen meg instant a teljes dealer hand.

Példa:

`10♠️ ▰`

↓

`10♠️ 5♦️`

↓

`10♠️ 5♦️ 8♣️`

↓

`23 – BUST`

## Double Down

A játékos megduplázza a tétet.

Ezután:

- pontosan 1 lapot kap
- automatikusan Stand

## Split

Azonos értékű kezdő lapok esetén két külön hand.

Mindkét hand külön kijátszva.

Példa:

Hand 1
`8♠️ 3♣️`

Hand 2
`8♥️ K♦️`

## Insurance

Dealer Ace upcard esetén legyen opcionális insurance.

## Blackjack payout

Döntés szükséges:

- marad jelenlegi rendszer
- vagy klasszikus **3:2 blackjack profit**

Preferált irány: teljes Blackjack szabályrendszer és egységes Casino payout-kezelés.

## Bust UX fix

Ha a játékos bustol, ne játsszuk végig feleslegesen az osztó handjét úgy, hogy félrevezetően úgy nézzen ki, mintha a két bust handet összehasonlítanánk.

---

# 3. Slots

A jelenlegi 3-symbol slot teljes reworkje.

## Layout

Új alap:

**5×3 grid**

Példa:

`🍒 🍋 💎 🔔 🍇`
`7️⃣ 🍒 ⭐ 🍒 7️⃣`
`🍋 💎 🍇 🔔 🍒`

## Reel animation

A reel-ek balról jobbra álljanak meg.

Példa:

`🔄 🔄 🔄 🔄 🔄`

↓

első reel megáll

↓

második

↓

...

## Symbol rendszer

Normál symbolok:

- 🍒
- 🍋
- 🍇
- 🔔
- 💎
- 7️⃣

Special:

- ⭐ Wild
- 💰 Scatter

## Wild

Normál szimbólumokat helyettesít.

## Scatter

Scatter nem igényel payline-t.

Példa:

3 scatter → 5 free spins
4 scatter → 8 free spins
5 scatter → 12 free spins

## Free Spins

Automatikusan ugyanabban az embedben fusson.

Mutassa:

- current free spin
- total free spins
- current total win
- multiplier

## Payline / ways rendszer

A jelenlegi triple-only logikát le kell cserélni.

Lehet:

- fix paylines
- vagy ways-to-win

Végleges balance előtt RTP-szimuláció szükséges.

---

# 4. Roulette

A Roulette legyen valódi betting table.

## Több fogadás egy spinre

Egy játékos egyszerre több betet is rakhasson.

Példa:

- 250k Red
- 25k 0
- 20k 17

## Bet típusok

Első release:

- Red / Black
- Odd / Even
- 1–18 / 19–36
- 1st dozen
- 2nd dozen
- 3rd dozen
- 1st column
- 2nd column
- 3rd column
- single number 0–36

Később opcionálisan:

- split
- street
- corner

## Egyéni multi-bet asztal

Végleges irány:

- minden játékos a saját roulette sessionjét nyitja;
- egy spin előtt több külön fogadást rakhat fel;
- a fogadások ugyanarra az egy eredményre számolódnak;
- a teljes reserved tét egy sessionhöz tartozik;
- cancel/timeout esetén safe refund jár.

## Spin animation

Pár frame-es lassuló kijelzés.

Példa:

`17 → 5 → 32 → 14 → 9`

majd:

`🔴 9`

---

# 5. Coinflip

Maradjon gyors quick game.

## Single player

Rövid coin animation:

`🪙 → 🌑 → 🪙 → 🌑`

majd eredmény.

## Coinflip Duel

PvP mód.

Példa:

Krisz vs Pityu

Bet:

`1M / player`

Pot:

`2M`

Másik játékosnak:

- Accept
- Decline

Elfogadás után közös flip.

A winner viszi a potot.

Opcionális kis house rake később.

---

# 6. Dice

A jelenlegi exact 1–6 mód maradjon, de bővüljön.

## Játékmódok

- Exact number
- High / Low
- Odd / Even
- Over / Under 7
- Exactly 7

Over/Under módhoz két dice.

## Animation

A dice néhány frame-en keresztül változzon, majd álljon meg.

## Dice Duel

PvP mód.

Mindkét játékos dob.

Magasabb érték nyer.

Tie → reroll.

---

# 7. RPS

## Player vs Yoru

Marad quick game, de jobb reveal UI-val.

## PvP RPS

Mindkét játékos külön ephemeral módon választ:

- Rock
- Paper
- Scissors

A másik fél választását nem látják.

Mindkét választás után egyszerre reveal.

Lehetséges módok:

- Best of 1
- Best of 3
- Best of 5

---

# 8. High / Low

A jelenlegi egykörös High/Low helyett streak/cashout rendszer.

## Gameplay

Kezdő lap megjelenik.

Példa:

`7♥️`

Játékos választ:

- Higher
- Lower

Siker esetén új lap lesz az aktuális lap.

A cashout multiplier minden sikerrel nő.

Példa:

Streak 0 → x1.00

Streak 1 → x1.45

Streak 2 → x2.10

Streak 3 → x3.20

stb.

## Cashout

Minden sikeres kör után:

`CASH OUT`

gomb.

Hibás tipp:

a teljes aktív bet elveszik.

## Tie

Preferált szabály:

tie = push

A kör ugyanonnan folytatható.

---

# 9. Chicken Fight

A jelenlegi instant 46% RNG fight prezentációja túl egyszerű.

## Fight animation

Mindkét chicken kap HP bart.

Példa:

Krisz Chicken
`❤️ 82/100`

Opponent
`❤️ 61/100`

Roundonként:

- attack
- dodge
- critical
- counter

A tényleges final outcome továbbra is megfelelően balance-olt RNG lehet.

A fight azonban több frame-ben jelenjen meg.

## Hosszabb távú döntés

Később eldönthető, hogy:

- marad Chicken Fight
- vagy részben / teljesen leváltja Chicken Road

---

# 10. Monthly Global Jackpot – ÚJ KONCEPCIÓ

A jelenlegi klasszikus contribution jackpotot lecseréljük.

Nem a játékosok manuálisan fizetnek be a jackpotba.

## Jackpot funding

Minden olyan gambling veszteségből, ahol a pénz a house-hoz kerül:

annak egy kis százaléka bekerül a havi jackpot poolba.

Példa:

Játékos veszít:

`1,000,000 YC`

Jackpot contribution rate:

`2%`

Global Jackpot:

`+20,000 YC`

A maradék house sinkként eltűnik az economyból.

## Ajánlott kezdő rate

Config:

`JACKPOT_CONTRIBUTION_RATE = 0.02`

Ajánlott teszt range:

**1–3%**

10% elsőre túl magas lehet high-roller economy mellett.

## Mely veszteségek számítsanak?

Csak valódi **house lossok**:

- Blackjack loss
- Slots loss
- Roulette loss
- Dice loss
- Coinflip loss
- High/Low loss
- Chicken Fight loss
- későbbi casino house games

Ne számítson bele:

- PvP poker
- Coinflip Duel
- player-vs-player játék
- market veszteség
- rob
- economy command

Ezeknél nem a house kapja a teljes tétet.

## Jackpot UI

Casino menüben mindig látható:

> 💰 MONTHLY JACKPOT
> **$482,731,920**
>
> Következő húzás:
> **Augusztus 31.**
>
> Ebben a hónapban hozzáadtál:
> **$4,281,000**

Ez pszichológiailag is jó, mert a játékos látja, hogy a veszteségek egy része visszakerül a közösséghez.

## Monthly roll

Minden hónap végén automatikus jackpot draw.

A pool teljesen vagy nagyrészt kifizetésre kerül.

Utána:

új hónap → jackpot reset.

## Jogosultság

Nem lenne jó, ha egy hónapban nulla aktivitású alt nyerne.

A jackpot drawba csak olyan játékos kerüljön, aki az adott hónapban teljesített minimum aktivitást.

Például:

- legalább 25 casino game
- vagy legalább 250k total wager

A pontos requirement később balance-olandó.

## Nyerési esély

Első verzióban preferált:

**minden jogosult játékos azonos eséllyel induljon.**

Ne a wager határozza meg lineárisan az esélyt, mert akkor a leggazdagabb játékosok gyakorlatilag megvennék a jackpotot.

Később lehet ticket jellegű participation rendszer, de capelve.

## Jackpot animation

Hónap végén külön látványos draw.

Résztvevő nevek pörögnek:

`Krisz → Pityu → Józsi → Krisz...`

lassul...

majd:

> 👑 **MONTHLY JACKPOT WINNER**
>
> @Krisz
>
> 💰 **$482,731,920**

A winner ping opcionálisan kikapcsolható.

## Jackpot history

Tároljuk:

- month
- total jackpot
- winner
- eligible players
- total casino losses
- jackpot contribution total

Később:

`/casino jackpot history`

---

# 11. Lottery

A külön Lottery megmaradhat a Monthly Jackpot mellett.

A Lottery:

- ticket-alapú
- kisebb
- gyakrabban húzott

A Monthly Jackpot:

- automatikusan house lossból épül
- havi egyszer
- nagyon nagy prize

Így nem ütik egymást.

Lottery UI:

- current pot
- ticket count
- own tickets
- next draw
- last winner

---

# 12. Egységes Casino UI

Hosszabb távon az új slash struktúra legyen group/subcommand alapú a Discord slash limit miatt.

Preferált:

`/casino blackjack`

`/casino slots`

`/casino roulette`

`/casino coinflip`

`/casino dice`

`/casino highlow`

`/casino jackpot`

stb.

Vagy egy fő `/casino` interaktív selector menu.

A prefix rövidítések maradnak:

`!bj`

`!cf`

stb.

---

# Fejlesztési sorrend

## Phase 1 – Casino Core

- közös game session rendszer
- bet reservation
- game ID
- central stat tracking
- central payout config
- jackpot contribution hook
- concurrency tesztek
- prefix/slash shared backend

## Phase 2 – Blackjack

- új UI
- dealer animation
- Double
- Split
- Insurance
- payout újraszámolás
- bust UX fix

## Phase 3 – Slots

- 5×3 engine
- reel animation
- Wild
- Scatter
- Free Spins
- payline/ways rendszer
- RTP simulation

## Phase 4 – Roulette

- betting table
- multi-bet
- új bet type-ok
- individual multi-bet round
- animation

## Phase 5 – Quick Games

- Coinflip game-first animation
- Dice house-game modes
- RPS house-game reveal
- High/Low streak + dynamic cashout
- common Casino visual standard

A PvP Duel rendszer külön Social Economy surface marad; későbbi polishnál ugyanazt a vizuális standardot kapja.

## Phase 6 – Community Systems

- Monthly Global Jackpot
- monthly automatic draw
- eligibility
- jackpot history
- Lottery UI rework

## Phase 7 – Chicken Fight

- animated fight rework
- későbbi Chicken Road kompatibilitás

---

# Kötelező release előtti tesztek

Minden nagy Casino release-nél:

- Discord slash command count ellenőrzés
- prefix/slash parity
- párhuzamos user game teszt
- ugyanazon user double-spend teszt
- `all` bet 1B+ összegekkel
- minimum bet
- insufficient wallet
- reconnect / timeout
- interaction spam
- game button ownership
- payout correctness
- RTP simulation
- jackpot contribution correctness
- jackpot ne kapjon PvP veszteségből pénzt
- stat tracking
- game history
- old game regression tests

---

# Casino után

Csak a meglévő játékok reworkje után kezdjük az új játékokat.

Jelenlegi shortlist későbbre:

- Mines
- Candy Rush
- Crash / MÁV Crash
- Plinko
- Texas Hold'em Poker
- Chicken Road
- Tower
- NAV Escape
- Kincsem horse betting
- Baccarat
- Limbo
- Sic Bo
- Video Poker
- Liar's Dice

Ezek külön következő roadmapben lesznek kidolgozva.
---

# Elfogadott architektúra-kiegészítések

A rework indulásakor a roadmaphez az alábbi plusz szabályok kerültek elfogadásra:

- minden Casino pénzmozgás külön **Casino Ledger** rekordot kap (`BET_RESERVED`, extra bet, payout, refund, jackpot contribution);
- minden session settlement **idempotens**: ugyanaz a Game ID legfeljebb egyszer fizethet;
- az aktív session a játék induláskori payout/config snapshotot használja, ezért egy menet közbeni admin config-változtatás nem módosíthatja a futó játékot;
- restart után a memóriából elveszett nyitott sessionök nem hagyhatnak beragadt reserved pénzt: recover vagy safe refund kötelező;
- a Casino Core minden játék pénzmozgásának közös alapja; a vizuális renderelés külön threaden, limitált concurrencyvel fut;
- High/Low multiplier az aktuális lap valós probabilityje + house edge alapján dinamikus lesz, nem fix streak-táblából;
- Chicken Fight animáció a ténylegesen eldöntött fight state-ből készül, az animáció nem külön RNG-t futtat;
- `/casino` egy közös Casino lobby/stats/history/jackpot felületet kap, miközben a rövid prefixek megmaradnak shortcutnak.

## Módosított fejlesztési sorrend

1. **Casino Core** — session, reservation, ledger, Game ID, statok, payout config, jackpot hook, concurrency/restart safety.
2. **Blackjack**.
3. **Quick Games** — Coinflip, Dice, RPS, High/Low.
4. **Roulette** — individual European wheel + multi-bet.
5. **Slots** — 5×3, Wild/Scatter/Free Spins + nagy RTP-szimuláció.
6. **Community Systems** — Monthly Global Jackpot draw/eligibility/history + Lottery.
7. **Chicken Fight**.
8. Csak ezután új Casino játékok.

## v3.21.0 — PvP + Balance Pass

Coinflip/Dice/RPS duels migrated to the Casino visual framework. Default RTP/EV audit is stored in `CASINO_BALANCE_AUDIT.md`.
