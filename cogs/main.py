import asyncio
import logging
import os
import sqlite3
import sys

import discord
from discord.ext import commands, tasks

from cogs.utils.BotUtils import bot_utils as utils
from .utils import helper_functions as hf
from .utils.traceback_store import TracebackStore


logger = logging.getLogger(__name__)


class Main(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot

    async def cog_load(self):
        store = TracebackStore()
        try:
            await asyncio.to_thread(store.initialize)
        except (OSError, sqlite3.Error):
            logger.exception("Could not initialize the local traceback archive")
        self.bot.traceback_store = store
        self.bot.record_traceback = store.record_exception
        if utils.here.bot is None:
            utils.setup(bot=self.bot, loop=asyncio.get_running_loop())
        self.bot.tree.on_error = on_tree_error
        self.bot.on_error = self.on_error
        self.autosave_db.start()

    def cog_unload(self):
        self.autosave_db.cancel()
    
    @commands.Cog.listener()
    async def on_ready(self):
        print("Bot loaded")
        self.bot.log_channel = self.bot.get_channel(int(os.getenv("LOG_CHANNEL_ID")))
        self.bot.error_channel = self.bot.get_channel(int(os.getenv("TRACEBACK_LOGGING_CHANNEL")))

        await self.bot.log_channel.send('Bot loaded')
        await self.bot.change_presence(activity=discord.Game('DM me to talk to mods'))

        if not hasattr(self.bot, "recently_in_report_room"):
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
        if 'buttons' not in self.bot.db:
            self.bot.db['buttons'] = {}
        if 'recent_reports' not in self.bot.db:
            self.bot.db['recent_reports'] = {}

    @tasks.loop(minutes=1)
    async def autosave_db(self):
        await hf.dump_json()

    @autosave_db.before_loop
    async def before_autosave_db(self):
        await self.bot.wait_until_ready()
    
    @commands.Cog.listener()
    async def on_error(self, event: str, *args, **kwargs):
        error = sys.exception()
        if error is None:
            print("No error occurred, can't send error embed.")
            return

        if event == "on_message" and args and isinstance(args[0], discord.Message):
            # Report DMs can be anonymous, and the source channel may be uncached.
            message = args[0]
            args = (f"Message ID {message.id}, channel ID {message.channel.id}",)
        await utils.send_error_embed(self.bot, event, error, *args, **kwargs)
    
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
        
        await utils.send_error_embed(self.bot, ctx, error)
        
        
async def setup(bot: commands.Bot):
    await bot.add_cog(Main(bot))
    

async def on_tree_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    await utils.send_error_embed(interaction.client, interaction, error)
