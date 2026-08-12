from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands

from app.cogs.economy import EconomyCog
from app.cogs.events import EventCog
from app.cogs.shop import ShopCog
from app.cogs.prefix import PrefixCog
from app.cogs.gambling import GamblingCog
from app.cogs.casino import CasinoCog
from app.cogs.extras import ExtrasCog
from app.cogs.extras_prefix import ExtrasPrefixCog
from app.config import load_settings
from app.database import Database
from app.services.economy import EconomyService
from app.services.statistics import StatisticsService
from app.services.shop import ShopService
from app.services.gambling import GamblingService
from app.services.casino import CasinoService
from app.services.extras import ExtrasService
from app.services.progression import ProgressionService
from app.services.prestige import PrestigeService
from app.services.crew import CrewService
from app.services.faction import FactionService
from app.services.quests import QuestService
from app.services.activity import ActivityService
from app.services.business import BusinessService
from app.services.heist import HeistService
from app.cogs.progression import ProgressionCog
from app.cogs.community import CommunityCog
from app.cogs.admin import AdminCog
from app.cogs.moderation import ModerationCog
from app.cogs.automod import AutomodCog
from app.cogs.quests import QuestCog
from app.cogs.prestige import PrestigeCog
from app.cogs.crew import CrewCog
from app.cogs.help import HelpCog
from app.cogs.settings import SettingsCog
from app.cogs.economy_events_settings import EconomyEventsSettingsCog
from app.cogs.welcome_roles import WelcomeRolesCog
from app.cogs.tickets import TicketCog
from app.cogs.music import MusicCog
from app.cogs.fun import FunCog
from app.cogs.activity import ActivityCog
from app.cogs.social_economy import SocialEconomyCog
from app.cogs.business import BusinessCog
from app.cogs.heist import HeistCog
from app.cogs.tutorial import TutorialCog
from app import economy_config as eco

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("vaultbot")


# Prefixes that are reserved for administrators.  Discord message commands cannot
# produce true ephemeral channel replies, so unauthorized attempts are deleted and
# the user receives a DM instead.
ADMIN_PREFIX_COMMANDS = {
    "setroleincome", "sri",
    "addmoney", "am",
    "removemoney", "rm",
    "setmoney", "sm",
    "drawlottery", "drawlot",
    "openblackmarket", "openbm",
    "yoruconfig", "yc", "config",
    "tutorial", "tutorialsync", "tutsync",
    "starteffect", "seffect",
    "cleareffects", "ceffects",
    "reseteconomy", "reseteco", "economyreset", "ereset",
}

# Staff prefix commands are hidden too, but unlike true admin commands they
# respect the relevant Discord moderation permission.
STAFF_PREFIX_PERMISSIONS = {
    "ban": "ban_members", "unban": "ban_members",
    "kick": "kick_members",
    "mute": "moderate_members", "timeout": "moderate_members", "to": "moderate_members",
    "unmute": "moderate_members", "untimeout": "moderate_members", "uto": "moderate_members",
    "warn": "moderate_members", "warnings": "moderate_members", "warns": "moderate_members",
    "modlog": "moderate_members", "cases": "moderate_members", "mlog": "moderate_members",
    "case": "moderate_members",
    "purge": "manage_messages", "clear": "manage_messages", "clean": "manage_messages",
    "lock": "manage_channels", "unlock": "manage_channels",
    "slowmode": "manage_channels", "slow": "manage_channels",
    "automod": "manage_guild", "amod": "manage_guild",
    "modstatus": "manage_guild", "logvoice": "manage_guild",
    "settings": "manage_guild", "configpanel": "manage_guild", "panel": "manage_guild",
    "setup": "manage_guild", "yorusetup": "manage_guild",
    "giveaway": "manage_messages", "gw": "manage_messages",
    "giveawayreroll": "manage_messages", "gwreroll": "manage_messages", "reroll": "manage_messages",
    "sticky": "manage_messages", "stickyoff": "manage_messages", "unsticky": "manage_messages",
    "kincseslada": "manage_guild", "lada": "manage_guild", "chest": "manage_guild",
    "hirtelenhalal": "manage_guild", "bomb": "manage_guild", "hh": "manage_guild", "sd": "manage_guild",
}


# Rövid, szerveroldali flood-védelem az állapotmódosító prefix parancsokra.
# Nem helyettesíti a rendes economy cooldownokat; csak azt akadályozza meg,
# hogy valaki 0.1 mp-enként Ctrl+C/Ctrl+V-vel több kérést indítson.
RATE_LIMITED_PREFIX_COMMANDS = {
    "daily", "dly", "weekly", "wk", "week", "monthly", "mo", "month",
    "beg", "koldul", "kereget", "search", "keres", "work", "w",
    "crime", "cr", "slut", "kurva", "hoe", "rob", "steal",
    "claimincome", "ci", "claim", "interest", "int", "kamat",
    "deposit", "dep", "withdraw", "with", "wd", "pay", "give", "send",
    "buy", "purchase", "sell", "s", "use", "u", "open",
    "scratch", "scr", "sorsjegy", "giveitem", "gi", "giftitem",
    "coinflip", "cf", "dice", "kocka", "roll", "slots", "slot", "sl",
    "roulette", "rulett", "r", "blackjack", "bj", "casino", "kaszino", "kaszinó",
    "chickenfight", "cock", "fight", "chicken", "highlow", "hl", "rps", "kpo",
    "jackpot", "jp", "pot", "lottery", "lotto", "lot", "lottó",
    "blackmarket", "bm", "feketepiac", "invest", "invst", "befektet",
    "questclaim", "qclaim", "qc",
    "crewcreate", "createcrew", "clancreate", "crewinvite", "cinvite", "claninvite",
    "crewaccept", "caccept", "clanaccept", "crewleave", "cleave", "clanleave",
    "crewkick", "ckick", "clankick", "crewpromote", "cpromote",
    "crewdemote", "cdemote", "crewtransfer", "ctransfer",
    "crewdeposit", "cdep", "clandeposit", "crewwithdraw", "cwith", "clanwithdraw",
    "crewupgrade", "cupgrade", "clanupgrade", "crewdescription", "crewdesc", "cdesc",
    "crewdisband", "cdisband", "clandisband",
    "suggest", "suggestion", "javaslat", "poll", "szavazas", "votecreate", "afk", "away",
    "play", "mplay", "musicplay",
    "market", "marketplace", "pmarket", "mp", "servershop", "sshop", "customshop",
    "duel", "pvp",
    "biznisz", "business", "empire", "biz",
    "heist", "nagymelo", "nagymeló", "melo", "meló", "heisttop", "melotop", "nagymelotop",
}

ADMIN_HIDDEN_PREFIX_COMMANDS = {
    "clearwarns", "cw",
    "setlogchannel", "setlog", "logchannel", "disablelogs", "logoff",
    "adminpay", "apay",
}


class VaultBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.settings = load_settings()
        self.database = Database(self.settings.database_path, self.settings.starting_balance)
        self.statistics = StatisticsService(self.database)
        self.prestige = PrestigeService(self.database, self.statistics)
        self.crew = CrewService(self.database, self.statistics)
        self.crew.bind_bot(self)
        self.factions = FactionService(self.database, self.statistics, self.crew)
        self.economy = EconomyService(self.database, self.statistics, self.prestige, self.crew)
        self.shop = ShopService(self.database, self.statistics)
        self.casino = CasinoService(self.database)
        self.gambling = GamblingService(self.database, self.casino)
        self.extras = ExtrasService(self.database, self.economy, self.casino)
        self.progression = ProgressionService(self.database, self.economy)
        self.quests = QuestService(self.database, self.statistics)
        self.activity_service = ActivityService(self.database)
        self.businesses = BusinessService(self.database, self.statistics, self.prestige, self.activity_service, self.crew, self.factions)
        self.heists = HeistService(self.database, self.statistics, self.prestige, self.activity_service, self.crew, self.factions)
        self._prefix_action_times: dict[tuple[int, int], float] = {}
        self._suppressed_delete_log_ids: set[int] = set()

    def _prune_prefix_runtime_cache(self, now: float) -> None:
        # Large servers can see thousands of one-off users over a long uptime.
        # Prefix anti-flood only needs the recent window, so stale keys must not
        # accumulate forever.
        if len(self._prefix_action_times) < 2000:
            return
        cutoff = now - max(60.0, float(eco.PREFIX_ACTION_MIN_INTERVAL_SECONDS) * 20.0)
        self._prefix_action_times = {key: stamp for key, stamp in self._prefix_action_times.items() if stamp >= cutoff}

    async def setup_hook(self) -> None:
        await self.database.initialize()
        recovered = await self.casino.recover_after_restart()
        if recovered:
            logger.warning("Casino restart recovery: %s nyitott session visszatérítve.", len(recovered))
        await self.add_cog(EconomyCog(self, self.economy))
        await self.add_cog(ShopCog(self, self.shop))
        await self.add_cog(EventCog(self, self.economy))
        await self.add_cog(GamblingCog(self, self.gambling))
        await self.add_cog(CasinoCog(self, self.casino, self.gambling))
        await self.add_cog(PrefixCog(self, self.economy, self.shop, self.gambling))
        await self.add_cog(ExtrasCog(self, self.extras))
        await self.add_cog(ExtrasPrefixCog(self, self.extras, self.economy))
        await self.add_cog(ProgressionCog(self, self.progression))
        await self.add_cog(QuestCog(self, self.quests))
        await self.add_cog(PrestigeCog(self, self.prestige))
        await self.add_cog(CrewCog(self, self.crew))
        await self.add_cog(HelpCog(self))
        await self.add_cog(CommunityCog(self, self.database, self.economy))
        await self.add_cog(AdminCog(self, self.database))
        await self.add_cog(ModerationCog(self, self.database))
        await self.add_cog(AutomodCog(self, self.database))
        await self.add_cog(SettingsCog(self, self.database))
        await self.add_cog(EconomyEventsSettingsCog(self, self.database))
        await self.add_cog(WelcomeRolesCog(self, self.database))
        await self.add_cog(TicketCog(self, self.database))
        await self.add_cog(MusicCog(self, self.database))
        await self.add_cog(FunCog(self, self.database))
        await self.add_cog(ActivityCog(self, self.database, self.activity_service))
        await self.add_cog(SocialEconomyCog(self, self.database, self.economy))
        await self.add_cog(BusinessCog(self, self.database, self.economy, self.businesses))
        await self.add_cog(HeistCog(self, self.database, self.economy, self.heists))
        await self.add_cog(TutorialCog(self, self.database))

        @self.tree.command(name="ping", description="Megmutatja, hogy működik-e a bot.")
        async def ping(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(f"🏓 Pong! **{round(self.latency * 1000)} ms**")

        if self.settings.test_guild_id:
            guild = discord.Object(id=self.settings.test_guild_id)

            # A globális parancsok korábbi példányait töröljük, különben ugyanaz a
            # parancs globálisan és tesztszerver-parancsként is megjelenhet.
            self.tree.copy_global_to(guild=guild)
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            synced = await self.tree.sync(guild=guild)
            logger.info("%s tesztparancs szinkronizálva. A régi globális másolatok törölve.", len(synced))
        else:
            synced = await self.tree.sync()
            logger.info("%s globális parancs szinkronizálva.", len(synced))

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        # AutoMod runs before command processing so a blocked/spam message can
        # never execute as a prefix command after being deleted.
        if message.guild is not None:
            automod = self.get_cog("AutomodCog")
            if automod is not None and hasattr(automod, "check_message"):
                try:
                    if await automod.check_message(message):
                        return
                except Exception:
                    logger.exception("AutoMod message check failed on guild %s", message.guild.id)

        # Activity tracking runs only after AutoMod accepted the message. Prefix
        # commands and anti-farm rules are filtered by ActivityService itself.
        if message.guild is not None:
            activity_cog = self.get_cog("ActivityCog")
            if activity_cog is not None and hasattr(activity_cog, "handle_message"):
                try:
                    await activity_cog.handle_message(message)
                except Exception:
                    logger.exception("Activity message tracking failed on guild %s", message.guild.id)

        content = message.content.strip()
        if message.guild is not None and content.startswith("!"):
            first_token = content[1:].split(maxsplit=1)[0].lower() if len(content) > 1 else ""
            is_admin_cmd = first_token in ADMIN_PREFIX_COMMANDS or first_token in ADMIN_HIDDEN_PREFIX_COMMANDS
            staff_permission = STAFF_PREFIX_PERMISSIONS.get(first_token)
            if is_admin_cmd or staff_permission:
                # Staff/admin command invocations never remain visible in chat.
                try:
                    self._suppressed_delete_log_ids.add(message.id)
                    await message.delete()
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    self._suppressed_delete_log_ids.discard(message.id)
                    logger.warning("Nem sikerült törölni egy staff prefix parancsot a(z) %s szerveren.", message.guild.id)

                member = message.author
                allowed = False
                if isinstance(member, discord.Member):
                    if member.guild_permissions.administrator:
                        allowed = True
                    elif staff_permission:
                        allowed = bool(getattr(member.guild_permissions, staff_permission, False))

                if not allowed:
                    warning = (
                        "⛔ **Nincs jogosultságod ehhez a Yoru staff parancshoz.**\n"
                        "A próbálkozásodat eltávolítottam a chatből."
                    )
                    try:
                        await member.send(warning)
                    except (discord.Forbidden, discord.HTTPException):
                        try:
                            await message.channel.send(f"{member.mention} {warning}", delete_after=5)
                        except discord.HTTPException:
                            pass
                    return

            if first_token in RATE_LIMITED_PREFIX_COMMANDS:
                key = (message.guild.id, message.author.id)
                now = time.monotonic()
                self._prune_prefix_runtime_cache(now)
                last = self._prefix_action_times.get(key)
                if last is not None and now - last < eco.PREFIX_ACTION_MIN_INTERVAL_SECONDS:
                    # Flood esetén nem küldünk újabb hibaüzenetet, mert azzal a bot
                    # maga is teleszemetelné a csatornát. A másolt parancsot, ha tudjuk, töröljük.
                    try:
                        self._suppressed_delete_log_ids.add(message.id)
                        await message.delete()
                    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                        self._suppressed_delete_log_ids.discard(message.id)
                    return
                self._prefix_action_times[key] = now

        await self.process_commands(message)

    async def on_ready(self) -> None:
        logger.info("Bejelentkezve: %s (%s)", self.user, self.user.id if self.user else "?")
        await self.change_presence(activity=discord.Game(name="!help • /help | Yoru"))


async def main() -> None:
    bot = VaultBot()
    async with bot:
        await bot.start(bot.settings.discord_token)


def run_bot() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
