# Yoru Bot v3.8.0

Saját Discord economy + gambling bot Python / discord.py / SQLite alapon.

## Indítás

1. A `.env` fájlod maradjon meg.
2. Függőségek: `pip install -r requirements.txt`
3. Indítás: `python bot.py`

A meglévő `data/vaultbot.db` adatbázist **nem kell törölni**. Induláskor a bot automatikusan hozzáadja a v2.0 új oszlopait és tábláit.

## Fő prefix parancsok

### Economy
`!bal`, `!daily`, `!wk`, `!mo`, `!w`, `!cr`, `!rob @tag`, `!beg`, `!search`, `!cd`, `!dep all`, `!with all`, `!pay @tag 25k`, `!int`

### Progression
`!profile`, `!ach`, `!titles`, `!title <cím>`, `!boost`, `!bl`, `!invest low|medium|high <összeg>`, `!prestige`, `!prestigetop`

### Crew / Social
`!crew`, `!crewcreate <név>`, `!crewinvite @tag`, `!crewaccept`, `!crewleave`, `!crewdeposit 250k`, `!crewwithdraw all`, `!crewupgrade`, `!crewpromote @tag`, `!crewdemote @tag`, `!crewkick @tag`, `!crewtransfer @tag`, `!crewdesc <szöveg>`, `!crewdisband DISBAND`, `!crewtop`

### Shop
`!shop [game|lootbox|booster|utility]`, `!buy <item> [db]`, `!sell <item> [db]`, `!use <item>`, `!inv`

Új ládák: `common_crate`, `rare_crate`, `epic_crate`, `legendary_crate`, `mythic_crate`.

Új boosterek: `work_booster`, `crime_booster`, `luck_booster`, `interest_booster`, `rob_booster`.

### Gambling / közösségi játékok
`!cf`, `!dice`, `!sl`, `!r`, `!bj`, `!hl`, `!rps`, `!cock`, `!jp <összeg>`, `!lot <jegyek>`

Jackpot: az első beszállás után 60 másodperces kör indul. A nyerési esély a befizetett összeg arányában nő. A nyertes a pot 95%-át kapja.

Lottery: $25 000 / jegy, automatikus sorsolás óránként. A pot 90%-a kerül kiosztásra.

### Eventek
`!lada <összeg> <mp>`, `!hh <összeg> <join mp> <kör mp>`, `!bm`, `!bm buy <item> [db]`, `!effects`

Az automata Kincses Láda / Hirtelen Halál random időzítését az `.env` kezeli (a példa 15 perc–1,5 óra).
A pénzügyi alapértékek az `app/economy_config.py`-ban vannak: Kincses Láda **$100k–$500k teljes reward**, Hirtelen Halál belépő **$25k–$150k**, nevezés **30 mp**, köridő **15 mp**.
Az auto Kincses Láda / Hirtelen Halál csak aktivitási gate után indul: alapból 20 érvényes üzenet / 30 perc / legalább 4 user.
A Feketepiac / Work Rush / Crime Rush / Lucky Hour egy külön, ritkább 1–4 órás közösségi event loop.
Az `AUTO_EVENTS_ENABLED=false` mindkét automatikus event loopot leállítja; a Lottery ettől függetlenül óránként sorsol.

### Toplisták
`!top money`, `wallet`, `bank`, `rob`, `gambling`, `wins`, `work`, `crime`, `daily`, `earned`, `level`, `investment`, `jackpot`, `lottery`, `chicken`, `scratch`, `weekly`

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
- Blackjack natural is 2x kifizetés, nincs 2.5x eltérés.

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

A fő balance most az `app/economy_config.py` fájlban él: income, cooldown, gambling payout, shop/crate, market, event reward, Crew/Prestige, Nitro és progression XP.

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
