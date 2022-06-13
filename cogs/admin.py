import os

import discord
from discord.ext import commands

from owner import dump_json
from .utils.db_utils import get_thread_id_to_thread_info

dir_path = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

INSTRUCTIONS = """・`end` or `done` - Finish the current report.
・`_setup` - Reset the room completely (if there's a bug).
・`_clear` - Clear the waiting list
・`_send <id> <message text>` - Sends a message to a user or channel. It's helpful when you want a user to come 
　to the report room or send an official mod message to a channel.
・`_not_anonymous` - Type this during a report session to reveal moderator names for future messages. You can 
　enter it again to return to anonymity at any time during the session, and it'll be automatically reset to default   
　anonymity after the session ends."""


def is_admin(ctx):
    """Checks if you are an admin in the guild you're running a command in"""
    if not ctx.guild:
        return False
    if ctx.channel.permissions_for(ctx.author).administrator:
        return True
    guilds = ctx.bot.db['guilds']
    if ctx.guild.id not in guilds:
        return False
    guild_config = guilds[ctx.guild.id]
    if 'mod_role' not in guild_config or guild_config['mod_role'] is None:
        return False
    mod_role = ctx.guild.get_role(guild_config['mod_role'])
    if mod_role is None:
        return False
    return mod_role in ctx.author.roles


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        return is_admin(ctx)

    @commands.command()
    async def clear(self, ctx):
        """Clears the server state """
        if ctx.guild.id not in self.bot.db['guilds']:
            return
        for user_id, thread_info in self.bot.db['reports'].items():
            if thread_info['guild_id'] == ctx.guild.id:
                del self.bot.db['reports'][user_id]
        await ctx.send("I've cleared the guild report state.")
        await dump_json(ctx)

    @commands.command()
    async def setup(self, ctx):
        """Sets the current channel as the report room, or resets the report module"""
        guilds = self.bot.db['guilds']
        if ctx.guild.id not in guilds:
            guilds[ctx.guild.id] = {'mod_role': None}
        guild_config = guilds[ctx.guild.id]
        if not guild_config.get("mod_role"):
            await ctx.send("Please configure the mod role first using `_setmodrole`.")
            return
        guilds[ctx.guild.id] = {'channel': ctx.channel.id, 'mod_role': guild_config['mod_role']}
        await ctx.send(f"I've set the report channel as this channel. Now if someone messages me I'll deliver "
                       f"their messages here.\n\nIf you'd like to pin the following message, it's some instructions "
                       f"on helpful commands for the bot")
        await ctx.send(INSTRUCTIONS)
        await dump_json(ctx)

    @commands.command()
    async def setmodrole(self, ctx, *, role_name):
        """Set the mod role for your server.  Type the exact name of the role like `;setmodrole Mods`. \
                To remove the mod role, type `;setmodrole none`."""
        if ctx.guild.id not in self.bot.db['guilds']:
            await ctx.send("Report channel must be set first. Use the `setup` command in the report room.")
            return
        guild_config = self.bot.db['guilds'][ctx.guild.id]
        if role_name.casefold() == "none":
            guild_config['mod_role'] = None
            await ctx.send("Removed mod role setting for this server")
            return
        mod_role: discord.Role = discord.utils.find(
            lambda role: role.name == role_name, ctx.guild.roles)
        if not mod_role:
            await ctx.send("The role with that name was not found")
            return None
        guild_config['mod_role'] = mod_role.id
        await ctx.send(f"Set the mod role to {mod_role.name} ({mod_role.id})")
        await dump_json(ctx)

    @commands.command(aliases=['not_anon', 'non_anonymous', 'non_anon', 'reveal'])
    async def not_anonymous(self, ctx, *, no_args_allowed=None):
        """This command will REVEAL moderator names to the user for the current report session."""
        if no_args_allowed:
            return  # to prevent someone unintentionally calling this command like "_reveal his face"
        thread_id_to_thread_info = get_thread_id_to_thread_info(self.bot.db)
        if ctx.channel.id not in thread_id_to_thread_info:
            return
        thread_info = thread_id_to_thread_info[ctx.channel.id]
        not_anon = thread_info.setdefault(
            'not_anonymous', False)

        if not not_anon:  # default option, moderators are still anonymous
            thread_info['not_anonymous'] = True
            await ctx.send("In future messages for this report session, your names will be revealed to the reporter. "
                           f"Type `{ctx.message.content}` to make your names anonymous again. "
                           "When this report ends, the setting will be reset and "
                           "in the next report you will be anonymous again.")
        else:
            thread_info['not_anonymous'] = False
            await ctx.send("You are now once again anonymous. If you sent any messages since the last time someone "
                           "inputted the command, the reporter will have been shown your username.")

    @commands.command()
    async def send(self, ctx, user_id: int, *, msg):
        """Sends a message to the channel ID specified"""
        channel = self.bot.get_channel(user_id)
        if not channel:
            channel = self.bot.get_user(user_id)
            if not channel:
                await ctx.send("Invalid ID")
                return
        try:
            await channel.send(f"Message from the mods of {ctx.guild.name}: {msg}")
        except discord.Forbidden:
            try:
                await ctx.send(f"I can't send messages to that user.")
            except discord.Forbidden:
                pass
        else:
            try:
                await ctx.message.add_reaction("✅")
            except (discord.Forbidden, discord.NotFound):
                pass


async def setup(bot):
    await bot.add_cog(Admin(bot))
