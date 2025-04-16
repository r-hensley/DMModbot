# -*- coding: utf8 -*-
import asyncio

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

try:
    if not os.listdir('cogs/utils/BotUtils'):
        raise FileNotFoundError
except FileNotFoundError:
    raise FileNotFoundError("The BotUtils submodule is not initialized. "
                            "Please run 'git submodule update --init --recursive' to initialize it.")
from cogs.utils import helper_functions as hf

dir_path = os.path.dirname(os.path.realpath(__file__))

discord.utils.setup_logging()

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
           "LOG_CHANNEL_ID=0000\nTRACEBACK_LOGGING_CHANNEL=0000\nBAN_APPEALS_GUILD_ID=0000\n")
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
                         intents=intents, owner_id=int(os.getenv("OWNER_ID") or 0) or None)
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
                "recent_reports": {},
                "buttons": {}
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
        for extension in ['cogs.modbot', 'cogs.main', 'cogs.admin', 'cogs.owner', 'cogs.unbans', 'cogs.events']:
            try:
                await self.load_extension(extension)
            except Exception as e:
                print(f'Failed to load {extension}', file=sys.stderr)
                traceback.print_exc()
                raise

        hf.setup(bot=self, loop=asyncio.get_event_loop())  # this is to define here.bot in the hf file
            

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