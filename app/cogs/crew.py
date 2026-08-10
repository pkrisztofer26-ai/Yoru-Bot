from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.amounts import parse_amount
from app.crew_ui import CrewView, build_crew_embed, build_crew_top_embed
from app.services.crew import CrewService
from app.ui import BRAND, GOLD, SUCCESS, error_embed, money


class CrewCog(commands.Cog):
    def __init__(self, bot: commands.Bot, service: CrewService) -> None:
        self.bot = bot
        self.service = service

    async def _send_crew_panel(self, responder, guild_id: int, target: discord.abc.User, requester: discord.abc.User, *, slash: bool) -> None:
        embed = await build_crew_embed(self.bot, guild_id, target)
        if target.id == requester.id and await self.service.get_membership(guild_id, target.id) is None:
            invite = await self.service.pending_invite(guild_id, target.id)
            if invite:
                crew, expires = invite
                embed.add_field(
                    name="📨 Aktív meghívó",
                    value=f"**{crew.name}** • lejár <t:{int(expires.timestamp())}:R>\nElfogadás: `!crewaccept` vagy `/crewaccept`",
                    inline=False,
                )
        view = CrewView(self.bot, guild_id, target, requester.id)
        if slash:
            await responder.response.send_message(embed=embed, view=view)
        else:
            await responder.send(embed=embed, view=view)

    @app_commands.command(name="crew", description="Megnyitja a Crew profilodat vagy egy másik játékos Crew-ját.")
    @app_commands.describe(member="A játékos, akinek a Crew-ját meg akarod nézni")
    async def crew_slash(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        if interaction.guild_id is None:
            return
        target = member or interaction.user
        await self._send_crew_panel(interaction, interaction.guild_id, target, interaction.user, slash=True)

    @commands.command(name="crew", aliases=["clan", "team"])
    @commands.guild_only()
    async def crew_prefix(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await self._send_crew_panel(ctx, ctx.guild.id, member or ctx.author, ctx.author, slash=False)

    @app_commands.command(name="crewcreate", description="Új Crew alapítása.")
    @app_commands.describe(name="Crew név (3-24 karakter)")
    async def create_slash(self, interaction: discord.Interaction, name: str) -> None:
        if interaction.guild_id is None:
            return
        try:
            membership = await self.service.create(interaction.guild_id, interaction.user.id, name)
        except (ValueError, RuntimeError) as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = discord.Embed(
            title="👥 Crew megalapítva",
            description=f"**{membership.crew.name}** létrejött. Te vagy a Crew Leader.",
            color=SUCCESS,
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="🏦 Crew Bank", value=money(0), inline=True)
        embed.add_field(name="👥 Férőhely", value=f"1/{membership.crew.member_cap}", inline=True)
        embed.set_footer(text="Yoru • Következő: /crewinvite")
        await interaction.response.send_message(embed=embed)

    @commands.command(name="crewcreate", aliases=["createcrew", "clancreate"])
    @commands.guild_only()
    async def create_prefix(self, ctx: commands.Context, *, name: str) -> None:
        try:
            membership = await self.service.create(ctx.guild.id, ctx.author.id, name)
        except (ValueError, RuntimeError) as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        embed = discord.Embed(
            title="👥 Crew megalapítva",
            description=f"**{membership.crew.name}** létrejött. Te vagy a Crew Leader.",
            color=SUCCESS,
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        embed.add_field(name="🏦 Crew Bank", value=money(0), inline=True)
        embed.add_field(name="👥 Férőhely", value=f"1/{membership.crew.member_cap}", inline=True)
        embed.set_footer(text="Yoru • Következő: !crewinvite @tag")
        await ctx.send(embed=embed)

    @app_commands.command(name="crewinvite", description="Meghív egy játékost a Crew-dba.")
    async def invite_slash(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if interaction.guild_id is None:
            return
        if member.bot:
            return await interaction.response.send_message(embed=error_embed(interaction.user, "Botot nem hívhatsz meg Crew-ba."), ephemeral=True)
        try:
            expires = await self.service.invite(interaction.guild_id, interaction.user.id, member.id)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await interaction.response.send_message(
            f"📨 **{member.display_name}** meghívva a Crew-ba • lejár <t:{int(expires.timestamp())}:R>."
        )

    @commands.command(name="crewinvite", aliases=["cinvite", "claninvite"])
    @commands.guild_only()
    async def invite_prefix(self, ctx: commands.Context, member: discord.Member) -> None:
        if member.bot:
            return await ctx.send(embed=error_embed(ctx.author, "Botot nem hívhatsz meg Crew-ba."))
        try:
            expires = await self.service.invite(ctx.guild.id, ctx.author.id, member.id)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await ctx.send(f"📨 **{member.display_name}** meghívva a Crew-ba • lejár <t:{int(expires.timestamp())}:R>.")

    @app_commands.command(name="crewaccept", description="Elfogadja az aktív Crew meghívódat.")
    async def accept_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        try:
            membership = await self.service.accept(interaction.guild_id, interaction.user.id)
        except (ValueError, RuntimeError) as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = discord.Embed(title="🤝 Crew csatlakozás", description=f"Csatlakoztál: **{membership.crew.name}**", color=SUCCESS)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @commands.command(name="crewaccept", aliases=["caccept", "clanaccept"])
    @commands.guild_only()
    async def accept_prefix(self, ctx: commands.Context) -> None:
        try:
            membership = await self.service.accept(ctx.guild.id, ctx.author.id)
        except (ValueError, RuntimeError) as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        embed = discord.Embed(title="🤝 Crew csatlakozás", description=f"Csatlakoztál: **{membership.crew.name}**", color=SUCCESS)
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @app_commands.command(name="crewleave", description="Kilépsz a jelenlegi Crew-dból.")
    async def leave_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        try:
            name = await self.service.leave(interaction.guild_id, interaction.user.id)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await interaction.response.send_message(f"👋 Kiléptél a **{name}** Crew-ból.")

    @commands.command(name="crewleave", aliases=["cleave", "clanleave"])
    @commands.guild_only()
    async def leave_prefix(self, ctx: commands.Context) -> None:
        try:
            name = await self.service.leave(ctx.guild.id, ctx.author.id)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await ctx.send(f"👋 Kiléptél a **{name}** Crew-ból.")

    @app_commands.command(name="crewkick", description="Eltávolít egy alacsonyabb rangú tagot a Crew-ból.")
    async def kick_slash(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if interaction.guild_id is None:
            return
        try:
            crew = await self.service.kick(interaction.guild_id, interaction.user.id, member.id)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await interaction.response.send_message(f"👢 **{member.display_name}** eltávolítva a **{crew.name}** Crew-ból.")

    @commands.command(name="crewkick", aliases=["ckick", "clankick"])
    @commands.guild_only()
    async def kick_prefix(self, ctx: commands.Context, member: discord.Member) -> None:
        try:
            crew = await self.service.kick(ctx.guild.id, ctx.author.id, member.id)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await ctx.send(f"👢 **{member.display_name}** eltávolítva a **{crew.name}** Crew-ból.")

    async def _role_change(self, guild_id: int, actor_id: int, member: discord.Member, role: str):
        return await self.service.set_role(guild_id, actor_id, member.id, role)

    @app_commands.command(name="crewpromote", description="Officer rangot ad egy Crew tagnak.")
    async def promote_slash(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if interaction.guild_id is None:
            return
        try:
            await self._role_change(interaction.guild_id, interaction.user.id, member, "officer")
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await interaction.response.send_message(f"⭐ **{member.display_name}** mostantól Crew Officer.")

    @commands.command(name="crewpromote", aliases=["cpromote"])
    @commands.guild_only()
    async def promote_prefix(self, ctx: commands.Context, member: discord.Member) -> None:
        try:
            await self._role_change(ctx.guild.id, ctx.author.id, member, "officer")
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await ctx.send(f"⭐ **{member.display_name}** mostantól Crew Officer.")

    @app_commands.command(name="crewdemote", description="Officer rang visszavétele.")
    async def demote_slash(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if interaction.guild_id is None:
            return
        try:
            await self._role_change(interaction.guild_id, interaction.user.id, member, "member")
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await interaction.response.send_message(f"👤 **{member.display_name}** mostantól Crew Member.")

    @commands.command(name="crewdemote", aliases=["cdemote"])
    @commands.guild_only()
    async def demote_prefix(self, ctx: commands.Context, member: discord.Member) -> None:
        try:
            await self._role_change(ctx.guild.id, ctx.author.id, member, "member")
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await ctx.send(f"👤 **{member.display_name}** mostantól Crew Member.")

    @app_commands.command(name="crewtransfer", description="Átadja a Crew Leader rangot egy tagnak.")
    async def transfer_slash(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if interaction.guild_id is None:
            return
        try:
            membership = await self.service.transfer(interaction.guild_id, interaction.user.id, member.id)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await interaction.response.send_message(f"👑 **{member.display_name}** lett a **{membership.crew.name}** új Leader-e.")

    @commands.command(name="crewtransfer", aliases=["ctransfer"])
    @commands.guild_only()
    async def transfer_prefix(self, ctx: commands.Context, member: discord.Member) -> None:
        try:
            membership = await self.service.transfer(ctx.guild.id, ctx.author.id, member.id)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await ctx.send(f"👑 **{member.display_name}** lett a **{membership.crew.name}** új Leader-e.")

    @app_commands.command(name="crewdeposit", description="Pénzt tesz a Crew Bankba.")
    @app_commands.describe(amount="Például: 25k, 2m, all")
    async def deposit_slash(self, interaction: discord.Interaction, amount: str) -> None:
        if interaction.guild_id is None:
            return
        try:
            wallet, _ = await self.bot.database.get_balance(interaction.guild_id, interaction.user.id)
            parsed = parse_amount(amount, wallet)
            new_wallet, crew_bank, crew = await self.service.deposit(interaction.guild_id, interaction.user.id, parsed)
        except (ValueError, RuntimeError) as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = discord.Embed(title="🏦 Crew befizetés", color=SUCCESS)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.description = f"**{money(parsed)}** befizetve a **{crew.name}** Crew Bankba."
        embed.add_field(name="Crew Bank", value=money(crew_bank), inline=True)
        embed.add_field(name="Tárcád", value=money(new_wallet), inline=True)
        await interaction.response.send_message(embed=embed)

    @commands.command(name="crewdeposit", aliases=["cdep", "clandeposit"])
    @commands.guild_only()
    async def deposit_prefix(self, ctx: commands.Context, amount: str) -> None:
        try:
            wallet, _ = await self.bot.database.get_balance(ctx.guild.id, ctx.author.id)
            parsed = parse_amount(amount, wallet)
            new_wallet, crew_bank, crew = await self.service.deposit(ctx.guild.id, ctx.author.id, parsed)
        except (ValueError, RuntimeError) as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        embed = discord.Embed(title="🏦 Crew befizetés", color=SUCCESS)
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        embed.description = f"**{money(parsed)}** befizetve a **{crew.name}** Crew Bankba."
        embed.add_field(name="Crew Bank", value=money(crew_bank), inline=True)
        embed.add_field(name="Tárcád", value=money(new_wallet), inline=True)
        await ctx.send(embed=embed)

    @app_commands.command(name="crewwithdraw", description="Leaderként pénzt veszel ki a Crew Bankból.")
    @app_commands.describe(amount="Például: 25k, 2m, all")
    async def withdraw_slash(self, interaction: discord.Interaction, amount: str) -> None:
        if interaction.guild_id is None:
            return
        try:
            membership = await self.service.get_membership(interaction.guild_id, interaction.user.id)
            maximum = membership.crew.bank if membership else 0
            parsed = parse_amount(amount, maximum)
            wallet, crew_bank, crew = await self.service.withdraw(interaction.guild_id, interaction.user.id, parsed)
        except (ValueError, RuntimeError) as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = discord.Embed(title="💸 Crew kivét", color=GOLD)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.description = f"**{money(parsed)}** kivéve a **{crew.name}** Crew Bankból."
        embed.add_field(name="Crew Bank", value=money(crew_bank), inline=True)
        embed.add_field(name="Tárcád", value=money(wallet), inline=True)
        await interaction.response.send_message(embed=embed)

    @commands.command(name="crewwithdraw", aliases=["cwith", "clanwithdraw"])
    @commands.guild_only()
    async def withdraw_prefix(self, ctx: commands.Context, amount: str) -> None:
        try:
            membership = await self.service.get_membership(ctx.guild.id, ctx.author.id)
            maximum = membership.crew.bank if membership else 0
            parsed = parse_amount(amount, maximum)
            wallet, crew_bank, crew = await self.service.withdraw(ctx.guild.id, ctx.author.id, parsed)
        except (ValueError, RuntimeError) as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        embed = discord.Embed(title="💸 Crew kivét", color=GOLD)
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        embed.description = f"**{money(parsed)}** kivéve a **{crew.name}** Crew Bankból."
        embed.add_field(name="Crew Bank", value=money(crew_bank), inline=True)
        embed.add_field(name="Tárcád", value=money(wallet), inline=True)
        await ctx.send(embed=embed)

    @app_commands.command(name="crewupgrade", description="A Crew Bankból fejleszti a Crew szintjét.")
    async def upgrade_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        try:
            crew, cost = await self.service.upgrade(interaction.guild_id, interaction.user.id)
        except (ValueError, RuntimeError) as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = discord.Embed(title="⬆️ Crew fejlesztve", description=f"**{crew.name}** elérte a **Level {crew.level}** szintet.", color=SUCCESS)
        embed.add_field(name="Költség", value=money(cost), inline=True)
        embed.add_field(name="Új férőhely", value=str(crew.member_cap), inline=True)
        embed.add_field(name="Income bónusz", value=f"+{crew.income_bonus * 100:g}%", inline=True)
        await interaction.response.send_message(embed=embed)

    @commands.command(name="crewupgrade", aliases=["cupgrade", "clanupgrade"])
    @commands.guild_only()
    async def upgrade_prefix(self, ctx: commands.Context) -> None:
        try:
            crew, cost = await self.service.upgrade(ctx.guild.id, ctx.author.id)
        except (ValueError, RuntimeError) as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        embed = discord.Embed(title="⬆️ Crew fejlesztve", description=f"**{crew.name}** elérte a **Level {crew.level}** szintet.", color=SUCCESS)
        embed.add_field(name="Költség", value=money(cost), inline=True)
        embed.add_field(name="Új férőhely", value=str(crew.member_cap), inline=True)
        embed.add_field(name="Income bónusz", value=f"+{crew.income_bonus * 100:g}%", inline=True)
        await ctx.send(embed=embed)

    @app_commands.command(name="crewdescription", description="Beállítja a Crew rövid leírását.")
    async def description_slash(self, interaction: discord.Interaction, text: str) -> None:
        if interaction.guild_id is None:
            return
        try:
            crew = await self.service.set_description(interaction.guild_id, interaction.user.id, text)
        except (ValueError, RuntimeError) as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await interaction.response.send_message(f"📝 **{crew.name}** leírása frissítve.")

    @commands.command(name="crewdescription", aliases=["crewdesc", "cdesc"])
    @commands.guild_only()
    async def description_prefix(self, ctx: commands.Context, *, text: str) -> None:
        try:
            crew = await self.service.set_description(ctx.guild.id, ctx.author.id, text)
        except (ValueError, RuntimeError) as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await ctx.send(f"📝 **{crew.name}** leírása frissítve.")

    @app_commands.command(name="crewdisband", description="Végleg feloszlatja a Crew-t. Leader-only.")
    @app_commands.describe(confirm="Megerősítés: DISBAND")
    async def disband_slash(self, interaction: discord.Interaction, confirm: str) -> None:
        if interaction.guild_id is None:
            return
        if confirm != "DISBAND":
            return await interaction.response.send_message(embed=error_embed(interaction.user, "A megerősítéshez írd be pontosan: `DISBAND`."), ephemeral=True)
        try:
            name, refund = await self.service.disband(interaction.guild_id, interaction.user.id)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await interaction.response.send_message(f"🗑️ **{name}** feloszlatva. Crew Bank visszautalva: **{money(refund)}**.")

    @commands.command(name="crewdisband", aliases=["cdisband", "clandisband"])
    @commands.guild_only()
    async def disband_prefix(self, ctx: commands.Context, confirm: str = "") -> None:
        if confirm != "DISBAND":
            return await ctx.send(embed=error_embed(ctx.author, "Használat: `!crewdisband DISBAND`."))
        try:
            name, refund = await self.service.disband(ctx.guild.id, ctx.author.id)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await ctx.send(f"🗑️ **{name}** feloszlatva. Crew Bank visszautalva: **{money(refund)}**.")

    @app_commands.command(name="crewtop", description="A szerver Crew ranglistája.")
    async def top_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        await interaction.response.send_message(embed=await build_crew_top_embed(self.bot, interaction.guild_id, interaction.user))

    @commands.command(name="crewtop", aliases=["ctop", "clantop"])
    @commands.guild_only()
    async def top_prefix(self, ctx: commands.Context) -> None:
        await ctx.send(embed=await build_crew_top_embed(self.bot, ctx.guild.id, ctx.author))
