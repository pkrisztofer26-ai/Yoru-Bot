# Yoru Bot v3.11.1

Saját Discord economy + gambling bot Python / discord.py / SQLite alapon.

## Indítás

1. A `.env` fájlod maradjon meg.
2. Függőségek: `pip install -r requirements.txt`
3. Indítás: `python bot.py`

A meglévő `data/vaultbot.db` adatbázist **nem kell törölni**. Induláskor a bot automatikusan hozzáadja a v2.0 új oszlopait és tábláit.

## Fő prefix parancsok

### Economy
`!bal`, `!daily`, `!wk`, `!mo`, `!w`, `!cr`, `!rob @tag`, `!beg`, `!search`, `!cd`, `!dep all`, `!with all`, `!pay @tag 25k`, `!int`

A `/settings → Economy` oldalon szerverenként kapcsolható az economy, gambling, bank, interest és role income, valamint külön a Daily/Weekly/Monthly/Work/Crime/Search/Beg/Rob/Slut funkciók. Beállítható több engedélyezett economy csatorna **és teljes kategória**, cooldownok és reward range-ek, a rob arány, a gambling nyerő profit-szorzó, továbbá a pénznem neve és jele. Ha nincs engedélyezett hely megadva, az economy bárhol használható. **Frissítés után minden régi szerver a v3.10.1 alapértékekkel működik tovább**, amíg egy admin nem ír felül valamit a Settingsben.

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

### Music
`!play <keresés / YouTube / Spotify>`, `!musicpanel`, `!queue`, `!np`, `!pause`, `!resume`, `!skip`, `!stop`, `!vol 75`, `!loop`, `!shuffle`, `!leave`

Slash: `/music play`, `/music panel`, `/music queue`, `/music now`, `/music pause`, `/music resume`, `/music skip`, `/music stop`, `/music volume`, `/music loop`, `/music shuffle`, `/music leave`.

Támogatott bemenetek: sima keresés, YouTube videó, **YouTube playlist**, Spotify **track / album / playlist**. Spotify esetén Yoru a Spotify metadata alapján azonosítja a zenéket, majd YouTube-ról keres hozzájuk lejátszható hangforrást.

A `/music panel` egy persistent, tagoknak is használható interaktív Music Player embedet hoz létre/frissít. Gombok: Zene hozzáadása, Pause/Resume, Skip, Queue, Refresh, Shuffle, Loop, Hangerő, Stop, Leave. Ugyanez a `/settings → Music → Player panel` gombbal is publikálható.

A `/settings → Music` alatt kapcsolható a modul, kijelölhető Music text channel és DJ rang, valamint beállítható az alap hangerő és queue limit. A voice lejátszáshoz a Python dependency-k mellett **FFmpeg** bináris is kell a hoston. A requirements a discord.py hivatalos `voice` extráját használja (PyNaCl + davey).

### Fun
`!ship @tag [@tag]` • `/fun ship`

A Fun modul v3.11.1-ben letisztult: csak a **Ship 2.0** maradt. Stabil páros-százalék, mindkét tag profilképe, compatibility bar és szebb eredmény embed. A `/settings → Fun` oldalon továbbra is ki-/bekapcsolható és opcionálisan egyetlen text csatornára korlátozható.

### Eventek
`!lada <összeg> <mp>`, `!hh <összeg> <join mp> <kör mp>`, `!bm`, `!bm buy <item> [db]`, `!effects`

A `/settings → Events` oldalon szerverenként kapcsolható az automatikus eventrendszer, a **Kincses Láda**, a **Hirtelen Halál** és a manuális staff indítás. Beállítható az event csatorna, minimum/maximum random időköz, jelentkezési és HH köridő, aktivitási gate, Láda reward range, HH belépő range és a Láda/HH választási esély.

A régi `.env` event beállítások továbbra is **fallback alapértékek**, ezért meglévő szerveren frissítés után nem változik meg automatikusan a működés. A Feketepiac / Work Rush / Crime Rush / Lucky Hour külön, ritkább 1–4 órás közösségi event loop marad, de ugyanazt a szerverenkénti **Auto Events** kapcsolót és event csatornát használja. A Lottery ettől függetlenül óránként sorsol, az eredményt pedig a konfigurált Events csatornába küldi, ha van ilyen.

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
