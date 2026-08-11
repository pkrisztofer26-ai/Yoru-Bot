from __future__ import annotations

import discord

from app.ui import BRAND


HELP_PAGES: dict[str, dict[str, object]] = {
    "home": {
        "title": "🌙 Yoru Help",
        "description": (
            "A **Yoru Cafe** economy és community rendszere.\n"
            "Válassz lent egy kategóriát — csak a lényeg, példákkal."
        ),
        "fields": [
            ("🚀 Gyors kezdés", "`!daily` • `!work` • `!profile` • `!shop` • `!quests`", False),
            ("💸 Összegek", "Használható: `25k`, `2m`, `1b`, `1t`, `1q`, `all`.", False),
            ("⌨️ Prefix / Slash", "A legtöbb rendszer működik `!parancs` és `/parancs` formában is.", False),
        ],
    },
    "economy": {
        "title": "💰 Economy",
        "description": "Pénzkeresés, bank, cooldownok és Role Income.",
        "fields": [
            ("💵 Alapok", "`!bal` egyenleg • `!bank` bank\n`!dep 100k` befizetés • `!with all` kivét • `!pay @tag 25k` utalás", False),
            ("🛠️ Pénzkeresés", "`!daily` • `!wk` • `!mo` • `!work` • `!beg` • `!search`\n`!crime` és `!slut` kockázatos: bukásnál tartozásba is kerülhetsz.", False),
            ("🥷 Kockázat / income", "`!rob @tag` rablás • `!int` bankkamat\n`!ri` Role Income lista • `!ci` Role Income felvétele • `!cd` cooldownok", False),
        ],
    },
    "gambling": {
        "title": "🎰 Gambling",
        "description": "Gyors játékok valódi kockázattal. Csak a tárcádban lévő pénzből fogadhatsz.",
        "fields": [
            ("🪙 Gyors játékok", "`!cf fej 10k` Coinflip\n`!dice 4 10k` Dice\n`!sl 10k` Slots\n`!r piros 10k` Roulette", False),
            ("🃏 Interaktív", "`!bj 10k` Blackjack\n`!hl high 10k` High/Low\n`!rps rock 10k` Kő-papír-olló\n`!cock 10k` Chicken Fight", False),
            ("💡 Tipp", "`all` is használható tétként, de a gambling hosszú távon nem garantált profit.", False),
        ],
    },
    "shop": {
        "title": "🛒 Shop & Inventory",
        "description": "Tárgyak, ládák, boosterek és a market.",
        "fields": [
            ("🛍️ Shop", "`!shop` megnyitás • `!shop market` market\n`!buy <id> [db]` vásárlás • `!sell <id> [db]` eladás", False),
            ("🎒 Inventory", "`!inv` inventory • `!use <id>` tárgy/láda/booster használata\n`!gi @tag <id> <db>` tárgy ajándékozása", False),
            ("🌑 Feketepiac", "`!bm` az aktuális Black Market • `!bm buy <id> <db>` vásárlás, amikor nyitva van.", False),
        ],
    },
    "progression": {
        "title": "🏆 Progression",
        "description": "Hosszú távú fejlődés, questek és Prestige.",
        "fields": [
            ("⭐ Profil", "`!profile` profil • `!stats` részletes statok\n`!ach` achievementek • `!badges` badge-ek • `!titles` címek • `!title <név>` cím kiválasztása", False),
            ("🎯 Questek", "`!quests` napi/heti feladatok • `!qclaim` kész quest jutalmának felvétele", False),
            ("🌌 Endgame", "`!prestige` Prestige • `!prestigetop` Prestige ranglista\n`!boost` aktív boosterek • `!bl` bank level • `!invest medium 50k` befektetés", False),
        ],
    },
    "community": {
        "title": "🌙 Community & Eventek",
        "description": "Közösségi eszközök, közös játékok és automatikusan induló szervereventek.",
        "fields": [
            ("💡 Közösségi eszközök", "`!suggest <szöveg>` / `/community suggest` • `!poll kérdés | A | B` / `/community poll` • `!afk [ok]` / `/community afk`", False),
            ("🎉 Giveaway / Sticky", "Staff: `!giveaway 1h 1 Nyeremény` / `/community giveaway` • `!sticky <szöveg>` / `/community sticky`", False),
            ("⭐ Starboard", "A `⭐` reakciók a `/settings → Community` alatt beállított küszöbnél automatikusan a Starboard csatornába kerülnek.", False),
            ("🎰 Közös economy", "`!jp 25k` / `/community jackpot` • `!lot 5` / `/community lottery` • `!bm` / `/community blackmarket`", False),
            ("🎁 Auto eventek", "**Kincses Láda** és **Hirtelen Halál** csak aktív chatnél indul automatikusan. Az event után új aktivitás kell a következőhöz.", False),
            ("⚡ Szerver eventek", "`!effects` / `/community servereffects` megmutatja az aktív Work / Crime / Luck szorzókat.", False),
        ],
    },
    "crew": {
        "title": "👥 Crew",
        "description": "Csapat, közös bank és fejlődési bónuszok.",
        "fields": [
            ("👥 Alapok", "`!crew` saját Crew • `!crewcreate <név>` létrehozás\n`!crewinvite @tag` meghívás • `!crewaccept` elfogadás • `!crewleave` kilépés", False),
            ("🏦 Crew Bank", "`!crewdeposit 250k` befizetés • `!crewwithdraw 100k` kivét (Leader) • `!crewupgrade` fejlesztés", False),
            ("👑 Vezetés", "`!crewpromote` • `!crewdemote` • `!crewkick` • `!crewtransfer`\n`!crewdesc <szöveg>` leírás • `!crewtop` ranglista", False),
        ],
    },
    "profile": {
        "title": "👤 Profil & Ranglisták",
        "description": "Minden, ami a saját fejlődésed és a szerver rangsora.",
        "fields": [
            ("👤 Saját adatok", "`!profile [@tag]` interaktív profil\n`!stats [@tag]` statisztikák\n`!hist [@tag]` utolsó tranzakciók", False),
            ("🏆 Toplisták", "`!top money` vagyon • `!top wallet` tárca • `!top bank` bank\nTovábbiak: `rob`, `gambling`, `wins`, `work`, `crime`, `daily`, `earned`, `level`, `investment`.", False),
            ("🚔 Állapot", "`!jail [@tag]` börtönstátusz • `!ping` bot válaszideje • `!version` futó verzió", False),
        ],
    },
    "music": {
        "title": "🎵 Music",
        "description": "Voice zenelejátszó kereséssel, queue-val és vezérléssel.",
        "fields": [
            ("▶️ Lejátszás", "`!play <keresés vagy URL>` • `/music play`\n`!queue` • `/music queue` • `!np` • `/music now`", False),
            ("🎛️ Vezérlés", "`!pause` • `!resume` • `!skip` • `!stop`\n`!vol 75` • `!loop` • `!shuffle` • `!leave`", False),
            ("⚙️ Beállítás", "`/settings → Music`: be/ki, Music csatorna, DJ rang, alap hangerő és queue limit.", False),
        ],
    },
    "fun": {
        "title": "💞 Fun • Ship 2.0",
        "description": "Letisztított Fun modul: a Ship maradt, szebb kétprofilos megjelenítéssel.",
        "fields": [
            ("💞 Ship", "`!ship @tag [@tag]` • `/fun ship`\nStabil százalék ugyanarra a párosra, két profilképpel, compatibility barral és Yoru-ítélettel.", False),
        ],
    },
    "staff": {
        "title": "🛡️ Moderáció & Staff",
        "description": "A parancsokhoz megfelelő Discord jogosultság szükséges.",
        "fields": [
            ("🔨 Moderáció", "Prefix: `!ban` • `!kick` • `!mute` • `!warn` • `!purge` stb.\nSlash: `/mod ban` • `/mod kick` • `/mod mute` • `/mod warn` • `/mod purge` stb.", False),
            ("📋 Esetek & log", "Prefix: `!userinfo` • `!serverinfo` • `!modlog` • `!case <id>` • `!modstatus`\nSlash ugyanez `/mod ...` alatt. Admin: `!setlog #csatorna` • `!disablelogs` • `!logvoice on/off` • `!adminpay`", False),
            ("🛡️ AutoMod", "**Ajánlott:** `!settings` / `/settings` interaktív panel\nGyors setup: `!setup` / `/setup`\nA régi `!automod ...` parancsok továbbra is működnek haladó fallbackként.", False),
            ("⚙️ Yoru admin", "`!yc` config • `!sri @rang összeg` Role Income • `!am` / `!rm` / `!sm` pénzkezelés\n`!lada` / `!hh` manuális event • `!drawlot` • `!openbm` • `!starteffect` • `!cleareffects`\n`!rebaseeconomy REBASE` v3.5 átállás • `!reseteconomy RESET` teljes reset", False),
        ],
    },
}


BUTTONS = (
    ("economy", "Economy", "💰", discord.ButtonStyle.success, 0),
    ("gambling", "Gambling", "🎰", discord.ButtonStyle.danger, 0),
    ("shop", "Shop", "🛒", discord.ButtonStyle.primary, 0),
    ("progression", "Progression", "🏆", discord.ButtonStyle.primary, 0),
    ("community", "Community", "🌙", discord.ButtonStyle.primary, 0),
    ("crew", "Crew", "👥", discord.ButtonStyle.secondary, 1),
    ("profile", "Profil", "👤", discord.ButtonStyle.secondary, 1),
    ("staff", "Staff", "🛡️", discord.ButtonStyle.secondary, 1),
    ("home", "Kezdőlap", "🌙", discord.ButtonStyle.secondary, 1),
    ("music", "Music", "🎵", discord.ButtonStyle.secondary, 2),
    ("fun", "Fun", "🎉", discord.ButtonStyle.secondary, 2),
)


def build_help_embed(user: discord.abc.User, page: str = "home") -> discord.Embed:
    data = HELP_PAGES.get(page, HELP_PAGES["home"])
    embed = discord.Embed(
        title=str(data["title"]),
        description=str(data["description"]),
        color=BRAND,
    )
    avatar = getattr(user.display_avatar, "url", None)
    embed.set_author(name=user.display_name, icon_url=avatar)
    for name, value, inline in data["fields"]:  # type: ignore[index]
        embed.add_field(name=name, value=value, inline=inline)
    embed.set_footer(text="Yoru • Help • A gombokat csak a parancs használója kezelheti")
    return embed


class HelpButton(discord.ui.Button):
    def __init__(self, page: str, label: str, emoji: str, style: discord.ButtonStyle, row: int) -> None:
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self.page = page

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, HelpView):
            return
        view.current_page = self.page
        await interaction.response.edit_message(embed=build_help_embed(interaction.user, self.page), view=view)


class HelpView(discord.ui.View):
    def __init__(self, owner: discord.abc.User) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner.id
        self.current_page = "home"
        self.message: discord.Message | None = None
        for page, label, emoji, style, row in BUTTONS:
            self.add_item(HelpButton(page, label, emoji, style, row))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ezt a help menüt nem te nyitottad meg.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass


def make_help_view(user: discord.abc.User) -> tuple[discord.Embed, HelpView]:
    view = HelpView(user)
    return build_help_embed(user, "home"), view
