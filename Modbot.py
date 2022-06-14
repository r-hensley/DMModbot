# -*- coding: utf8 -*-
import logging

import discord
from discord.ext.commands import Bot
from discord.ext import commands
import sys
import traceback
import json
from datetime import datetime
from cogs.utils.db_utils import str_keys_to_int_keys, convert_old_db, int_keys_to_str_keys
from dotenv import load_dotenv

import os

dir_path = os.path.dirname(os.path.realpath(__file__))

FORMAT = "%(levelname)s [%(asctime)s %(filename)s->%(funcName)s():%(lineno)s]: %(message)s"
logging.basicConfig(format=FORMAT, level=logging.INFO)

# logger = logging.getLogger('discord')
# logger.setLevel(logging.INFO)
# handler = logging.FileHandler(
#     filename=f'{dir_path}/log/{datetime.utcnow().strftime("%y%m%d_%H%M")}.log',
#     encoding='utf-8',
#     mode='a')
# handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
# logger.addHandler(handler)

# noinspection lines to fix pycharm error saying Intents doesn't have members and Intents is read-only
intents = discord.Intents.default()
# noinspection PyUnresolvedReferences,PyDunderSlots
intents.members = True
# noinspection PyUnresolvedReferences,PyDunderSlots
intents.typing = True
# noinspection PyUnresolvedReferences,PyDunderSlots
intents.message_content = True

if not os.path.exists(f"{dir_path}/.env"):
    txt = ("# Fill this file with your data\nDEFAULT_PREFIX=_\nBOT_TOKEN=0000\nOWNER_ID=0000\n"
           "LOG_CHANNEL_ID=0000\nERROR_CHANNEL_ID=0000\nBAN_APPEALS_GUILD_ID=0000\n")
    with open(f'{dir_path}/.env', 'w') as f:
        f.write(txt)
    raise discord.LoginFailure("I've created a .env file for you, go in there and put your bot token in the file.\n")

# Credentials
load_dotenv(f'{dir_path}/.env')

if not os.getenv("BOT_TOKEN"):
    raise discord.LoginFailure("You need to add your bot token to the .env file in your bot folder.")


class Modbot(Bot):
    def __init__(self):
        super().__init__(description="Bot by Ryry013#9234", command_prefix=os.getenv("DEFAULT_PREFIX"),
                         intents=intents, owner_id=int(os.getenv("OWNER_ID")))
        print('starting loading of jsons')
        db_file_path = f"{dir_path}/modbot.json"
        if os.path.exists(db_file_path):
            with open(db_file_path, "r") as read_file1:
                read_file1.seek(0)
                self.db = str_keys_to_int_keys(convert_old_db(json.load(read_file1)))
        else:
            # Initial bot set up
            self.db = {
                "prefix": {},
                "settingup": [],
                "guilds": {},
                "reports": {},
                "user_localizations": {},
            }

        date = datetime.today().strftime("%d%m%Y%H%M")
        backup_dir = f"{dir_path}/database_backups"
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        with open(f"{backup_dir}/database_{date}.json", "w") as write_file:
            json.dump(int_keys_to_str_keys(self.db), write_file)

        self.log_channel = None
        self.error_channel = None

    async def setup_hook(self):
        for extension in ['cogs.modbot', 'cogs.admin', 'cogs.owner', 'cogs.unbans']:
            try:
                await self.load_extension(extension)
            except Exception as e:
                print(f'Failed to load {extension}', file=sys.stderr)
                traceback.print_exc()
                raise

    async def on_ready(self):
        print("Bot loaded")
        self.log_channel = self.get_channel(int(os.getenv("LOG_CHANNEL_ID")))
        self.error_channel = self.get_channel(int(os.getenv("ERROR_CHANNEL_ID")))

        await self.log_channel.send('Bot loaded')
        await self.change_presence(activity=discord.Game('DM me to talk to mods'))

        self.recently_in_report_room = {}
        for thread_info in self.db['reports'].values():
            report_channel = self.get_channel(thread_info['thread_id'])
            if report_channel:
                await report_channel.send("NOTIFICATION: Sorry, I had to restart, so I cleared this room. If the "
                                          "user continues messaging they should be able to come right back in.")
            user = self.get_user(thread_info["user_id"])
            if user and user.dm_channel:
                await user.dm_channel.send(
                    "NOTIFICATION: Sorry, I had to restart, so I cleared this room. Please try again.")
        self.db['reports'] = {}

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
                e.add_field(name="Author",
                            value=f'{arg.author} (ID: {arg.author.id})')
                fmt = f'Channel: {arg.channel} (ID: {arg.channel.id})'
                if arg.guild:
                    fmt = f'{fmt}\nGuild: {arg.guild} (ID: {arg.guild.id})'
                e.add_field(name='Location', value=fmt, inline=False)
                jump_url = arg.jump_url
        args_str.append('```')
        e.add_field(name='Args', value='\n'.join(args_str), inline=False)
        await self.error_channel.send(jump_url, embed=e)
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
                if ctx.guild.id in self.db['guilds']:
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
        qualified_name = getattr(
            ctx.command, 'qualified_name', ctx.command.name)
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

        exc = ''.join(traceback.format_exception(
            type(error), error, error.__traceback__, chain=False))
        traceback_text = f'{ctx.message.jump_url}\n```py\n{exc}```'
        e.timestamp = datetime.utcnow()
        await self.error_channel.send(traceback_text, embed=e)
        print('')


def run_bot():
    bot = Modbot()
    bot_token = os.getenv("BOT_TOKEN")

    if len(bot_token) == 58:
        # A bit of a deterrent from my bot token instantly being used if my .env file gets leaked somehow
        bot.run(bot_token + "o")

    else:
        bot.run(bot_token)

    print('Bot finished running')


def main():
    run_bot()


if __name__ == '__main__':
    main()
