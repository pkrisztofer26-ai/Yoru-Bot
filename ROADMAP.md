# Yoru Roadmap

_Last updated: 2026-08-12_

This is the agreed long-term development plan for Yoru. Existing stable features should be preserved unless a roadmap item explicitly changes them. Releases are delivered as a complete ready-to-upload project archive; the live `.env` and live database are never included.

## Current Casino UX standard (v3.19.4)

- One active Casino game per player/guild.
- Game-first, mobile-friendly visual hierarchy.
- Client-side animation where possible; CPU rendering stays off the asyncio event loop.
- Animated state is replaced by a static final result image after settlement.
- Shareable game visuals include the player's display name.
- This standard applies to every future Casino rework/new game.

## Core design decisions

- **Activity Level is separate** from the existing Yoru economy/progression level.
- Activity Level is earned from real Discord **chat + voice activity** with anti-farm rules.
- Yoru **automatically assigns milestone Discord roles** when members reach configured Activity Levels. The previous milestone role is removed when appropriate so Role Income does not unintentionally stack.
- Milestone roles can use the existing **Role Income** system. Since v3.17.5 the ladder is fully dynamic, DB-persisted and Discord-role appearance syncs back to the DB.
- The existing **Crew** feature is renamed user-facing to **Frakció**. Internal `crew_*` database names may remain for safe backwards compatibility.
- **Biznisz** is a true **late-game/endgame** system, not an early passive-income command.
- Proposed Biznisz unlock gate: meaningful Activity Level + Prestige progression + a permanent paid Business License. Exact numbers are finalized after the Activity XP curve is balanced.
- Biznisz and Heist gameplay take place in a **Hungary-based game world** using real Hungarian cities, districts/neighborhood names, streets and recognizable bank brands. Individual businesses, properties and bank branches are fictional game objects; exact real-world branch layouts/security details are not modeled.
- No Seasons system for now.
- Web Dashboard comes only after the bot-side systems are stable and polished.

---

## ✅ v3.11.1 — Stability + Economy Channel Rules + Fun cleanup

**Status:** implemented and QA-passed on 2026-08-11.

- Multi Economy Channels:
  - multiple allowed text channels;
  - multiple allowed categories;
  - zero configured channels/categories = economy usable anywhere;
  - preserve/migrate the existing single `economy_channel_id` setting.
- Chicken Fight:
  - Chicken becomes consumable;
  - on loss, one Chicken dies and is removed from inventory;
  - on win, Chicken survives;
  - shop/inventory text reflects this rule.
- Quest initialization bug:
  - daily/weekly quest assignments must initialize automatically on the first relevant tracked activity of the period;
  - progress must count even if the player has never opened the Quest menu that day/week.
- Fun cleanup:
  - remove Eight Ball, Choose, Roll, Coin, Rate, Truth, Dare, Would You Rather, Mock, Joke;
  - keep only Ship.
- Ship 2.0:
  - stable pair percentage;
  - both users represented with profile pictures;
  - improved compatibility bar, verdict text and cleaner embed.

## ✅ v3.11.2 — Ship Image Card + Music backend / Spotify reliability

**Status:** rebuilt from the v3.11.1 golden build; local QA passed on 2026-08-11, awaiting PebbleHost verification.

- Ship image-card redesign:
  - deterministic pair percentage preserved;
  - two large circular Discord avatars;
  - dark/purple Yoru card with names + large compatibility percentage;
  - old verdict / Yoru-opinion / meter clutter removed;
  - Pillow/avatar failure falls back to a minimal embed.
- Spotify track/album/playlist resolution:
  - `spotdl save --preload` first;
  - metadata-only `spotdl save` retry if preload fails;
  - `spotdl url` fills missing source URLs;
  - final per-track `artist + title` ytsearch fallback;
  - a failed preloaded source automatically retries the track search at playback time.
- YouTube video/playlist and the persistent member Music Panel stay supported.
- Queue/loop/shuffle/skip/volume controls stay unchanged.
- No mandatory Lavalink/Java dependency; managed-host/PebbleHost compatibility remains the priority.
- This does **not** claim direct Spotify audio streaming: Spotify metadata is resolved to playable external audio sources.

## ✅ v3.12 — Activity System

**Status:** implemented in v3.12.0.

A separate Discord-activity progression layer.

### Tracking
- Chat Activity XP with cooldown/anti-spam protection.
- Voice Activity XP/time:
  - no AFK-channel farming;
  - no solo voice farming;
  - bots do not count;
  - configurable self-deaf behavior.
- persistent chat message count and voice time.

### Leveling
- independent Activity Level + XP curve;
- configurable level-up announcement channel;
- Yoru automatically grants milestone roles when thresholds are reached;
- optional automatic creation of default milestone roles;
- role name/color/threshold/income configurable;
- use existing Role Income backend rather than duplicating income logic.

### Leaderboards
- Chat messages;
- Chat XP;
- Voice time;
- Activity Level.

### Settings
- `/settings -> Activity / Progression`;
- Chat/Voice XP toggles and multipliers;
- fully dynamic milestone role management (add/edit/delete/link + paginated 25+ ladder);
- level-up announcements;
- settings for existing quests, achievements and prestige where useful.


## ✅ v3.12.2 — Channel Guard Hotfix

- Activity/chat/voice leaderboards are usable outside economy allowlisted locations.
- Misplaced prefix gambling commands are removed from public chat and the user receives the configured allowed location by DM.

## ✅ v3.13 — Social Economy

**Status:** implemented and regression-tested in v3.13.0. Fixed-price marketplace is the v3.13 scope; auction/bid mode remains a later extension.

### Player Marketplace / Auction House
- player item listings;
- fixed-price buy-now listings first;
- listing expiry/cancel;
- item escrow;
- seller/buyer transaction history;
- market tax as a money sink;
- filtering/search/pagination;
- later auction/bid mode.

### Custom Server Shop
Admins can create server-specific rewards:
- Discord roles;
- temporary roles;
- custom items/rewards;
- stock and purchase limits;
- economy/activity/level requirements;
- configurable price and availability.

### Player-vs-player gambling
- Coinflip Duel;
- Dice Duel;
- RPS Duel;
- potential Blackjack Duel;
- both stakes escrowed before the match;
- accept/decline/timeout and anti-spam protection.

### Economy Analytics
- total supply;
- wallet vs bank distribution;
- money created/burned over 24h/7d;
- shop/gambling/market sinks and sources;
- marketplace volume;
- richest-share/concentration metrics;
- later Business/Heist metrics.

## ✅ v3.13.1 — Social Economy UI/UX

**Status:** implemented.

- Player Market and Server Shop are now interaction-first Discord UIs.
- `/settings -> Social` contains the full Server Shop admin manager and Economy Analytics dashboard.
- New Yoru systems should default to modern buttons/selects/modals/pagination and Discord-native admin configuration rather than command-only workflows.

## v3.14 — Frakció 2.0

**Status: implemented in v3.14.0.**

User-facing Crew name becomes **Frakció**. Legacy `crew_*` identifiers and command aliases remain for compatibility.

### Core
- Frakció XP + levels;
- shared quests/objectives;
- weekly objectives and leaderboard rewards;
- perk tree;
- contribution tracking;
- member-cap/income/gambling/business/heist perks;
- custom description/color/logo-style presentation.

### Roles and permissions
- Leader can create custom **internal Frakció ranks** (e.g. Alvezér, Toborzó, Veterán) with granular permissions such as invite/kick/bank/quest/war management;
- preferably one real Discord role per Frakció, customizable by the leader, instead of generating many Discord roles per internal rank;
- legacy `crew` commands may remain aliases while new UI/commands say `Frakció`.

### Frakció vs Frakció
Objective-based war rather than random coinflip PvP.

Proposed format:
- challenge + mutual leader acceptance;
- ~24-hour war window (configurable later);
- locked participant/member snapshot at start;
- multiple objective categories, e.g. Economy, Gambling, Quests, later Heist/Business Territory;
- per-player contribution caps to prevent one person from deciding the entire war through extreme grinding;
- reward: Frakció XP, Frakció-bank payout, leaderboard/war points, optional special tokens;
- optional Frakció-bank stake;
- losing a war never deletes or steals a player's permanent business/property.

## v3.15 — Biznisz Empire (Hungary, late-game only)

**Status: implemented in v3.15.0.**

A large endgame player-owned business/property economy.

### Unlock
Biznisz is permanently unlocked after meeting a late-game gate. Current design direction:
- sufficiently high **Activity Level**;
- meaningful **Prestige** requirement;
- purchase of a permanent **Vállalkozói Engedély** (large money sink).

Exact thresholds are decided after Activity XP pacing is known.

### Hungary-based world
Real place names form the game map. Examples:
- Miskolc, Eger, Debrecen, Szeged, Győr, Pécs, Nyíregyháza, Kecskemét, Székesfehérvár, Budapest;
- Budapest districts/neighborhoods such as Belváros, Terézváros, Józsefváros, Ferencváros, Újbuda, Óbuda, Rózsadomb, Csepel;
- real street names such as Váci utca, Andrássy út, Rákóczi út etc.

Properties are fictional game slots such as `Váci utca • Üzlethelyiség #04`; they are not claims about a real tenant or address.

### Expansion
- start in cheaper/earlier markets;
- unlock additional cities/areas progressively;
- Budapest premium districts are true endgame;
- expansion gates can require Business Level, reputation, number of properties and large expansion fees.

### Businesses
Examples:
- Gyrosos / Étterem / Kocsma / Kávézó / Kisbolt;
- Szupermarket;
- Autószerviz / Autókereskedés;
- Nightclub;
- Hotel;
- Gyár / Logisztikai központ;
- Irodaház / Befektetési társaság.

Business types have different ideal areas, worker capacity, costs and revenue profiles.

### Workers
Server-global rotating worker market:
- workers have star quality (normally 1–5⭐; rare special 6⭐ rewards possible);
- wage + base production;
- purchased worker disappears from global market;
- worker quality contributes to property valuation and output.

### Reputation / progression
- business reputation is star-based and multiplies output;
- business-specific daily/weekly-style objectives can raise reputation;
- upgrades, worker quality and expansion influence progression.

### Costs / economy sink
Income is net, not free money:
- worker wages;
- maintenance;
- property/operating costs;
- taxes/fees;
- poor finances reduce morale/reputation/output rather than instantly deleting the business.

### Player property market
Players can make offers to buy other players' businesses/properties:
- offer;
- accept;
- reject;
- counter-offer;
- escrow funds;
- ownership transfers with workers/upgrades/reputation/history;
- Yoru displays an estimated valuation but players choose the actual negotiated price.

Support portfolio/territory offers later (e.g. offer for multiple businesses/plots together).

### Anti-monopoly rules
Scarcity is desirable but hard-lock monopolies are not:
- per-player caps by area/territory;
- premium districts have limited slots;
- upgrades/perks may increase caps within reason.

### Frakció integration
- Frakció business perks;
- territory influence based partly on member businesses/activity;
- Frakció wars may award temporary area perks/influence;
- permanent player businesses are never confiscated merely because a Frakció loses a war.

## ✅ v3.16 — Heist / Nagy Meló (Hungary)

**Status: implemented in v3.16.0.**

Co-op heists based in the same Hungarian world. The shipped target names are fictional and the phase system stays abstract; no real branch security/layout information is modeled.

### Targets
Use recognizable Hungarian flavor and bank brands, but target entries are fictional game branches/locations. Examples may include:
- OTP;
- K&H;
- Erste;
- MBH;
- Raiffeisen;
- UniCredit;
- jewelry stores, warehouses, cash transports, casinos and other fictional targets.

Do not model exact real branch security/layouts or provide real-world operational details.

### Gameplay
- heist leader creates a crew of players;
- target shows base difficulty, payout range and success chance;
- players contribute simplified game gear categories rather than a huge realistic weapons simulation;
- example abstract gear groups: Weapon, Protection, Tool, Getaway;
- gear raises success chance within balanced caps;
- leader proposes payout percentages;
- every participant must explicitly accept their final cut before launch;
- failed heist can cause jail, fines, cooldowns and possible gear loss;
- successful heist gives money, XP, achievements and optional Frakció progression.

Potential name in Hungarian UI: **Nagy Meló** for the feature, with individual missions described as heists/rablások.

## ✅ v3.17 — Polish / Performance / Diagnostics

**Status: implemented in v3.17.0.**

- Settings Hub cleanup and current Frakció/Biznisz/Nagy Meló statuses;
- interactive `/settings → Diagnosztika`;
- permission + role hierarchy + music runtime health checks;
- SQLite quick_check/WAL visibility and hot-path indexes;
- large-server runtime cache pruning;
- Business marketplace pagination/select consistency;
- slash/component regression checks remain mandatory before release.

No economy rebalance was forced without live analytics data. Balance tuning stays analytics-driven rather than changing numbers blindly.

## ✅ v3.18–v3.20 — Casino Rework

The existing Casino catalog has been rebuilt around a shared session/ledger core and the game-first visual standard. The detailed implementation history lives in `CASINO_ROADMAP.md`.

### ✅ Casino Core (v3.18.0)
- shared prefix/slash/UI backend;
- atomic bet reservation + one active Casino game/player/guild;
- internal Game ID + Casino Ledger audit;
- idempotent settlement and restart recovery;
- central payout config and stat tracking;
- Monthly Casino Jackpot contribution hook.

### ✅ Main visual games (v3.19.x)
- Blackjack: Double, Split, Insurance, multi-hand, 3:2 natural, dealer animation;
- Slots: 5×3, Wild, Scatter, Free Spins, 20 paylines, simulated RTP, client-side animation;
- Roulette: **individual** European wheel, multi-bet per spin, red/black/0/even/odd/specific number, accelerated-start → gradual slowdown ball animation;
- game-first mobile-friendly visuals, player branding, GIF only during action and static final result;
- Game ID removed from player UI; `/settings → Casino` audit log keeps it for admins.

### ✅ Quick-game visual polish (v3.20.1)
- collision-safe shared header/player badge layout
- richer Coinflip/Dice/RPS/High-Low/Chicken animations
- shareable player branding + static final result

### ✅ Quick & Community games (v3.20.0)
- Coinflip: large branded animated flip → static final;
- Dice: Exact, High/Low, Odd/Even, Over/Under 7, Exactly 7 modes;
- RPS: animated reveal;
- High/Low: streak + dynamic probability-based cashout;
- Chicken Fight: HP-based multi-round visual fight generated from the real final outcome;
- Monthly Casino Jackpot: automatic month-end draw, eligibility, equal eligible-player odds, rollover and persistent history;
- Lottery: interactive Casino panel with quick ticket buttons and last-winner/history display;
- old manual player-funded `!jp <amount>` flow retired; `!jp` is now Monthly Casino Jackpot status.

### Casino UX standard going forward
Every current or future Casino game follows the same baseline: **game-first large display, mobile-first layout, compact secondary HUD, bounded off-loop rendering, smooth client animation, static final state, player branding, owner-locked controls, one active game/player, internal-only Game ID.**

### Next Casino content
Only after the existing catalog is stable: Mines, Crash / MÁV Crash, Plinko, Poker, Chicken Road, Tower and other new games.

## Later — Web Dashboard

The Web Dashboard remains planned, but only after the Casino bot-side rework is stable enough that the same systems do not have to be rebuilt twice.

## v3.21.0 — Casino PvP + Balance Pass

PvP visual standard + full default Casino RTP/EV audit completed. Next new Casino-game candidate: Mines.
