import os
import io
import traceback
import textwrap
import shutil
import json
import sys
from copy import deepcopy
from contextlib import redirect_stdout
from typing import Optional

import discord
from discord.ext import commands

from .utils.db_utils import int_keys_to_str_keys

dir_path = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

RYRY_ID = 202995638860906496
ABELIAN_ID = 414873201349361664  # Ryry alt
MARIO_RYAN_ID = 528770932613971988  # Ryry alt
UNITARITY_ID = 528770932613971988  # Ryry alt

MAIN_MODBOT_ID = 713245294657273856
MAIN_RYRY_TEST_BOT_ID = 536170400871219222

SP_SERV_ID = 243838819743432704
RY_TEST_SERV_ID = 275146036178059265


class Owner(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # For use in eval command
        self._last_result = None

    async def cog_check(self, ctx):
        if self.bot.user.id in [MAIN_MODBOT_ID, MAIN_RYRY_TEST_BOT_ID]:  # If it's Ryry's Rai bot
            return ctx.author.id in [RYRY_ID, ABELIAN_ID, MARIO_RYAN_ID, UNITARITY_ID]
        else:
            return ctx.author.id == self.bot.owner_id

    @commands.command()
    async def db(self, ctx):
        """Shows me my DB"""
        t = f"prefix: {self.bot.db['prefix']}\n" \
            f"settingup: {self.bot.db['settingup']}\nreports: {self.bot.db['reports']}\n"
        for guild in self.bot.db['guilds']:
            t += f"{guild}: {self.bot.db['guilds'][guild]}\n"
        await ctx.send(t)

    @commands.command()
    async def sendtoall(self, ctx, *, msg):
        config = self.bot.db['guilds']
        for guild in config:
            report_room = self.bot.get_channel(config[guild]['channel'])
            if report_room:
                try:
                    await report_room.send(msg)
                except (discord.Forbidden, discord.HTTPException):
                    pass
        try:
            await ctx.message.add_reaction('✅')
        except (discord.HTTPException, discord.Forbidden):
            pass

    @commands.command(hidden=True)
    async def reload(self, ctx, *, cog: str):
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
        try:
            await self.bot.reload_extension(f'cogs.{cog}')
        except Exception as e:
            await ctx.send(f'**`ERROR:`** {type(e).__name__} - {e}')
        else:
            await ctx.send('**`SUCCESS`**', delete_after=5.0)

    @staticmethod
    def cleanup_code(content):
        """Automatically removes code blocks from the code."""
        # remove triple quotes + py\n
        if content.startswith("```") and content.endswith("```"):
            return '\n'.join(content.split('\n')[1:-1])

        # remove `single quotes`
        return content.strip('` \n')

    @commands.command(hidden=True, name='eval')
    async def _eval(self, ctx, *, body: str):
        """Evaluates a code"""
        env = {
            'bot': self.bot,
            'ctx': ctx,
            'channel': ctx.channel,
            'author': ctx.author,
            'guild': ctx.guild,
            'message': ctx.message,
            '_': self._last_result
        }

        env.update(globals())

        body = self.cleanup_code(body)
        stdout = io.StringIO()

        to_compile = f'async def func():\n{textwrap.indent(body, "  ")}'

        try:
            exec(to_compile, env)
        except Exception as e:
            return await ctx.send(f'```py\n{e.__class__.__name__}: {e}\n```')

        func = env['func']
        try:
            with redirect_stdout(stdout):
                ret = await func()
        except Exception as e:
            value = stdout.getvalue()
            await ctx.send(f'```py\n{value}{traceback.format_exc()}\n```')
        else:
            value = stdout.getvalue()
            try:
                await ctx.message.add_reaction('\u2705')
            except discord.Forbidden:
                pass

            if ret is None:
                if value:
                    try:
                        await ctx.send(f'```py\n{value}\n```')
                    except discord.errors.HTTPException:
                        st = f'```py\n{value}\n```'
                        await ctx.send('Result over 2000 characters')
                        await ctx.send(st[0:1996] + '\n```')
            else:
                self._last_result = ret
                await ctx.send(f'```py\n{value}{ret}\n```')

    @commands.command()
    async def sdb(self, ctx):
        await dump_json(ctx)
        try:
            await ctx.message.add_reaction('\u2705')
        except discord.NotFound:
            pass

    @commands.command()
    async def flush(self, ctx):
        """Flushes stderr/stdout"""
        sys.stderr.flush()
        sys.stdout.flush()
        await ctx.message.add_reaction('🚽')

    @commands.command(aliases=['quit'])
    async def kill(self, ctx):
        """Modbot is a killer"""
        try:
            await ctx.message.add_reaction('💀')
            await ctx.invoke(self.flush)
            await ctx.invoke(self.sdb)
            await self.bot.close()
        except Exception as e:
            await ctx.send(f'**`ERROR:`** {type(e).__name__} - {e}')

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        msg = f"""__New guild__
        **Name:** {guild.name}
        **Owner:** {guild.owner.mention} ({guild.owner.name}#{guild.owner.discriminator}))
        **Members:** {guild.member_count}
        **Channels:** {len(guild.text_channels)} text / {len(guild.voice_channels)} voice"""

        await self.bot.get_user(self.bot.owner_id).send(msg)
        await self.bot.get_user(self.bot.owner_id).send("Channels: \n" +
                                                        '\n'.join([channel.name for channel in guild.channels]))

    @commands.command()
    async def sync(self, ctx: Optional[commands.Context]):
        """Syncs app commands"""
        # Sync interactions here in this file
        bot_guilds = [g.id for g in self.bot.guilds]
        for guild_id in [SP_SERV_ID, RY_TEST_SERV_ID]:
            if guild_id in bot_guilds:
                guild_object = discord.Object(id=guild_id)
                await self.bot.tree.sync(guild=guild_object)

        try:
            await ctx.message.add_reaction("♻")
        except (discord.HTTPException, discord.Forbidden, discord.NotFound):
            await ctx.send(f"**`interactions: commands synced`**", delete_after=5.0)


async def dump_json(ctx):
    db_copy = deepcopy(ctx.bot.db)
    if os.path.exists(f'{dir_path}/modbot_3.json'):
        shutil.copy(f'{dir_path}/modbot_3.json', f'{dir_path}/modbot_4.json')
    if os.path.exists(f'{dir_path}/modbot_2.json'):
        shutil.copy(f'{dir_path}/modbot_2.json', f'{dir_path}/modbot_3.json')
    if os.path.exists(f'{dir_path}/modbot.json'):
        shutil.copy(f'{dir_path}/modbot.json', f'{dir_path}/modbot_2.json')
    with open(f'{dir_path}/modbot_temp.json', 'w') as write_file:
        json.dump(int_keys_to_str_keys(db_copy), write_file, indent=4)
    shutil.copy(f'{dir_path}/modbot_temp.json', f'{dir_path}/modbot.json')


async def setup(bot):
    await bot.add_cog(Owner(bot))
