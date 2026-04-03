import re

import discord
from discord.ext import commands
from .utils import helper_functions as hf


class Submod(commands.Cog):
    """Commands for submods"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if hf.is_submod(ctx):
            return True
        # allow role 591745589054668817 in Spanish server to use _send only
        if ctx.command.name == 'send' and ctx.guild and ctx.guild.id == hf.SP_SERV_ID:
            sp_send_role = ctx.guild.get_role(591745589054668817)
            if sp_send_role and sp_send_role in ctx.author.roles:
                return True
        return False

    @commands.command()
    async def set_submod_role(self, ctx, role: discord.Role):
        """Sets the submod role for this server. Submods have access to some mod commands, but not all."""
        self.bot.db.setdefault('submod_role', {}).setdefault(ctx.guild.id, {})['id'] = role.id
        await ctx.send(f"Submod role set to {role.mention}", allowed_mentions=discord.AllowedMentions.none())

    @commands.command()
    async def send(self, ctx: commands.Context, user_id: str, *, msg: str):
        """Sends a message to the channel ID specified"""
        user_id_match = re.match(r'^<?[@#]?(\d{17,22})>?$', str(user_id))
        _user_id = int(user_id_match.group(1)) if user_id_match else None
        target = self.bot.get_channel(_user_id)
        if not target:
            target = self.bot.get_user(_user_id)
            if not target:
                await ctx.send(f"Invalid ID: {user_id}")
                return

        # trying to send to any server channel
        if hasattr(target, "guild"):
            if target.guild != ctx.guild:
                await ctx.send("You can only send messages to channels in this server.")
                return

        # trying to send to a user
        elif isinstance(target, discord.User):
            appeal_server = self.bot.get_guild(985963522796183622)
            appeal_server_members = appeal_server.members if appeal_server else []
            if target not in ctx.guild.members and target not in appeal_server_members:
                await ctx.send("You can only send messages to users in this server.")
                return

        try:
            await target.send(f"Message from the mods of {ctx.guild.name}: {msg}")
        except discord.Forbidden as e:
            try:
                await ctx.send(f"I can't send messages to that user. {e}")
            except discord.Forbidden:
                pass
        else:
            try:
                await ctx.message.add_reaction("✅")
            except (discord.Forbidden, discord.NotFound):
                pass

async def setup(bot):
    await bot.add_cog(Submod(bot))
