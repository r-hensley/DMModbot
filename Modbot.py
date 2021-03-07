# -*- coding: utf8 -*-
import discord
from discord.ext.commands import Bot
from discord.ext import commands
import sys, traceback
import json
from datetime import datetime

import os
dir_path = os.path.dirname(os.path.realpath(__file__))

import logging
logging.basicConfig(level=logging.WARNING)
# logger = logging.getLogger('discord')
# logger.setLevel(logging.INFO)
# handler = logging.FileHandler(
#     filename=f'{dir_path}/log/{datetime.utcnow().strftime("%y%m%d_%H%M")}.log',
#     encoding='utf-8',
#     mode='a')
# handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
# logger.addHandler(handler)

intents = discord.Intents.default()
intents.members = True

class Modbot(Bot):
    def __init__(self):
        super().__init__(description="Bot by Ryry013#9234", command_prefix='_', owner_id=202995638860906496,
                         intents=intents)
        print('starting loading of jsons')
        with open(f"{dir_path}/modbot.json", "r") as read_file1:
            read_file1.seek(0)
            self.db = json.load(read_file1)

        date = datetime.today().strftime("%d%m%Y%H%M")
        with open(f"{dir_path}/database_backups/database_{date}.json", "w") as write_file:
            json.dump(self.db, write_file)
        for extension in ['cogs.modbot']:
            try:
                self.load_extension(extension)
            except Exception as e:
                print(f'Failed to load {extension}', file=sys.stderr)
                traceback.print_exc()
                raise

    async def on_ready(self):
        print("Bot loaded")

        await self.get_channel(275879535977955330).send('Bot loaded')
        await self.change_presence(activity=discord.Game('DM me to talk to mods'))

        for guild in self.db['guilds'].copy():
            if self.db['guilds'][guild]['currentuser']:
                report_channel = self.get_channel(int(self.db['guilds'][guild]['channel']))
                self.db['guilds'][guild]['currentuser'] = None
                self.recently_in_report_room = []  # users will be on this list for 10s after leaving room
                await report_channel.send("NOTIFICATION: Sorry, I had to restart, so I cleared this room. If the "
                                          "user continues messaging they should be able to come right back in.")

    async def on_error(self, event, *args, **kwargs):
        e = discord.Embed(title='Event Error', colour=0xa32952)
        e.add_field(name='Event', value=event)
        e.description = f'```py\n{traceback.format_exc()}\n```'
        e.timestamp = datetime.utcnow()

        args_str = ['```py']
        jump_url = ''
        for index, arg in enumerate(args):
            print(type(arg))
            args_str.append(f'[{index}]: {arg!r}')
            if type(arg) == discord.Message:
                e.add_field(name="Author", value=f'{arg.author} (ID: {arg.author.id})')
                fmt = f'Channel: {arg.channel} (ID: {arg.channel.id})'
                if arg.guild:
                    fmt = f'{fmt}\nGuild: {arg.guild} (ID: {arg.guild.id})'
                e.add_field(name='Location', value=fmt, inline=False)
                jump_url = arg.jump_url
        args_str.append('```')
        e.add_field(name='Args', value='\n'.join(args_str), inline=False)
        await self.get_channel(554572239836545074).send(jump_url, embed=e)
        traceback.print_exc()

    async def on_command_error(self, ctx, error):
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
            msg = f"To do that command, Rai is missing the following permissions: `{'`, `'.join(error.missing_perms)}`"
            try:
                await ctx.send(msg)
            except discord.Forbidden:
                try:
                    await ctx.author.send(msg)
                except discord.Forbidden:
                    pass
            return

        elif isinstance(error, commands.CommandInvokeError):
            command = ctx.command.qualified_name
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
                if str(ctx.guild.id) in self.db['modrole']:
                    await ctx.send("You lack permissions to do that.")
                else:
                    await ctx.send(f"You lack the permissions to do that.  If you are a mod, try getting the owner or "
                                   f"someone with the administrator permission to type `'setmodrole <role name>`")
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
                           f"`{'`, `'.join(error.missing_perms)}`")
            return

        elif isinstance(error, commands.NotOwner):
            await ctx.send(f"Only Ryan can do that.")
            return

        print(datetime.now())
        error = getattr(error, 'original', error)
        qualified_name = getattr(ctx.command, 'qualified_name', ctx.command.name)
        print(f'Error in {qualified_name}:', file=sys.stderr)
        traceback.print_tb(error.__traceback__)
        print(f'{error.__class__.__name__}: {error}', file=sys.stderr)

        e = discord.Embed(title='Command Error', colour=0xcc3366)
        e.add_field(name='Name  ', value=qualified_name)
        e.add_field(name='Command', value=ctx.message.content[:1000])
        e.add_field(name='Author', value=f'{ctx.author} (ID: {ctx.author.id})')

        fmt = f'Channel: {ctx.channel} (ID: {ctx.channel.id})'
        if ctx.guild:
            fmt = f'{fmt}\nGuild: {ctx.guild} (ID: {ctx.guild.id})'

        e.add_field(name='Location', value=fmt, inline=False)

        exc = ''.join(traceback.format_exception(type(error), error, error.__traceback__, chain=False))
        traceback_text = f'{ctx.message.jump_url}\n```py\n{exc}```'
        e.timestamp = datetime.utcnow()
        await self.get_channel(554572239836545074).send(traceback_text, embed=e)
        print('')


bot = Modbot()
with open(f"{dir_path}/ModbotKey.txt") as f:
    bot.run(f.read() + 'o')
