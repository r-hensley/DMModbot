import os

import discord
from discord.ext import commands
import sys

from .utils import helper_functions as hf


class Main(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot
        self.bot.tree.on_error = on_tree_error
    
    @commands.Cog.listener()
    async def on_ready(self):
        print("Bot loaded")
        self.bot.log_channel = self.bot.get_channel(int(os.getenv("LOG_CHANNEL_ID")))
        self.bot.error_channel = self.bot.get_channel(int(os.getenv("ERROR_CHANNEL_ID")))

        await self.bot.log_channel.send('Bot loaded')
        await self.bot.change_presence(activity=discord.Game('DM me to talk to mods'))

        if not hasattr(self, "recently_in_report_room"):
            self.bot.recently_in_report_room = {}
            
        # for thread_info in self.db['reports'].values():
        #     report_channel = self.get_channel(thread_info['thread_id'])
        #     if report_channel:
        #         await report_channel.send("NOTIFICATION: Sorry, I had to restart, so I cleared this room. If the "
        #                                   "user continues messaging they should be able to come right back in.")
        #     user = self.get_user(thread_info["user_id"])
        #     if user and user.dm_channel:
        #         await user.dm_channel.send(
        #             "NOTIFICATION: Sorry, I had to restart, so I cleared this room. Please try again.")
        
        if 'reports' not in self.bot.db:
            self.bot.db['reports'] = {}
    
    @commands.Cog.listener()
    async def on_error(self, event: str, *args, **kwargs):
        # Get the exception info
        # exc_info() returns the tuple (type(e), e, e.__traceback__)
        error_info = sys.exc_info()
        if error_info[0] is None:
            print("No error occurred, can't send error embed.")
            return
        
        # Create an Exception object from the exception info
        # error = error_info[0](error_info[1]).with_traceback(error_info[2])
        
        # Use the send_error_embed function
        await hf.send_error_embed(self.bot, event, error_info[1], args, kwargs)
    
    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.BadArgument):
            # parsing or conversion failure is encountered on an argument to pass into a command.
            await ctx.send(f"Failed to find the object you tried to look up.  Please try again")
            return
        
        elif isinstance(error, commands.NoPrivateMessage):
            try:
                await ctx.author.send("You can only use this in a guild.")
                return
            except discord.Forbidden:
                pass
        
        elif isinstance(error, discord.Forbidden):
            try:
                await ctx.author.send("Rai lacked permissions to do something there")
            except discord.Forbidden:
                pass
        
        elif isinstance(error, commands.BotMissingPermissions):
            msg = f"To do that command, Rai is missing the following permissions: " \
                  f"`{'`, `'.join(error.missing_permissions)}`"
            try:
                await ctx.send(msg)
            except discord.Forbidden:
                try:
                    await ctx.author.send(msg)
                except discord.Forbidden:
                    pass
            return
        
        elif isinstance(error, commands.CommandInvokeError):
            try:
                await ctx.send(f"I couldn't execute the command.  I probably have a bug.  "
                               f"This has been reported to Ryan.")
            except discord.Forbidden:
                await ctx.author.send(f"I tried doing something but I lack permissions to send messages.  "
                                      f"I probably have a bug.  This has been reported to Ryan.")
            pass
        
        elif isinstance(error, commands.CommandNotFound):
            # no command under that name is found
            return
        
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"This command is on cooldown.  Try again in {round(error.retry_after)} seconds.")
            return
        
        elif isinstance(error, commands.CheckFailure):
            # the predicates in Command.checks have failed.
            try:
                if ctx.guild:
                    if ctx.guild.id in self.bot.db['guilds']:
                        await ctx.send("You lack permissions to do that.")
                    else:
                        await ctx.send(f"You lack the permissions to do that.  If you are a mod, try getting "
                                       f"the owner or someone with the administrator permission to type "
                                       f"`'setmodrole <role name>`")
                else:
                    await ctx.send("You lack permissions to do that.")
            
            except discord.Forbidden:
                await ctx.author.send(f"I tried doing something but I lack permissions to send messages.")
            return
        
        elif isinstance(error, commands.MissingRequiredArgument):
            # parsing a command and a parameter that is required is not encountered
            msg = f"You're missing a required argument ({error.param}).  " \
                  f"Try running `;help {ctx.command.qualified_name}`"
            if error.param.name in ['args', 'kwargs']:
                msg = msg.replace(f" ({error.param})", '')
            try:
                await ctx.send(msg)
            except discord.Forbidden:
                pass
            return
        
        elif isinstance(error, discord.Forbidden):
            await ctx.send(f"I tried to do something I'm not allowed to do, so I couldn't complete your command :(")
        
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send(f"To do that command, you are missing the following permissions: "
                           f"`{'`, `'.join(error.missing_permissions)}`")
            return
        
        elif isinstance(error, commands.NotOwner):
            await ctx.send(f"Only Ryan can do that.")
            return
        
        await hf.send_error_embed(self.bot, ctx, error)
        
        
async def setup(bot: commands.Bot):
    await bot.add_cog(Main(bot))
    

async def on_tree_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    qualified_name = getattr(interaction.command, 'qualified_name', interaction.command.name)
    e = discord.Embed(title=f'App Command Error ({interaction.type})', colour=0xcc3366)
    e.add_field(name='Name', value=qualified_name)
    e.add_field(name='Author', value=interaction.user)

    fmt = f'Channel: {interaction.channel} (ID: {interaction.channel.id})'
    if interaction.guild:
        fmt = f'{fmt}\nGuild: {interaction.guild} (ID: {interaction.guild.id})'

    e.add_field(name='Location', value=fmt, inline=False)

    if interaction.data:
        e.add_field(name="Data", value=f"```{interaction.data}```")

    if interaction.extras:
        e.add_field(name="Extras", value=f"```{interaction.extras}```")

    await hf.send_error_embed(interaction.client, interaction, error, e)