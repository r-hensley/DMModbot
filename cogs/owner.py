import asyncio
import importlib
import io
import traceback
import textwrap
import sys
from contextlib import redirect_stdout
from subprocess import PIPE, run, TimeoutExpired
from typing import Optional

import discord
from discord.ext import commands

from .utils import helper_functions as hf
from cogs.utils.BotUtils import bot_utils as utils

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
        self.bot: commands.Bot = bot
        
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
        t = f"__prefix__: ``{self.bot.db['prefix']}``\n" \
            f"__settingup__: ``{self.bot.db['settingup']}``\n" + \
            f"__reports__: ```{self.bot.db['reports']}```\n".replace("}, ", "},\n") + \
            f"__guilds__:\n"
        guild_text = ""
        for guild in self.bot.db['guilds']:
            guild_text += f"{guild}: {self.bot.db['guilds'][guild]}\n"
        t += f"```{guild_text}```"
        if len(t) > 4000:
            t_part_1 = t[:1997] + '```'
            t_part_2 = '```' + t[1997:3991] + '```'
            await ctx.send(t_part_1)
            await ctx.send(t_part_2)
        else:
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
    async def load(self, ctx, *, cog: str):
        """Command which loads a module."""
        
        try:
            await self.bot.load_extension(f'cogs.{cog}')
        except Exception as e:
            await ctx.send('**`ERROR:`** {} - {}'.format(type(e).__name__, e))
        else:
            await ctx.send('**`SUCCESS`**')
    
    @commands.command(hidden=True)
    async def unload(self, ctx, *, cog: str):
        try:
            await self.bot.unload_extension(f'cogs.{cog}')
        except Exception as e:
            await ctx.send('**`ERROR:`** {} - {}'.format(type(e).__name__, e))
        else:
            await ctx.send('**`SUCCESS`**')

    @commands.command(hidden=True)
    async def reload(self, ctx, *, cogs: str):
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
        for cog in cogs.split():
            if cog == 'database':
                importlib.reload(sys.modules['cogs.database'])
            if cog in ['hf', 'helper_function']:
                try:
                    importlib.reload(sys.modules['cogs.utils.helper_functions'])
                    hf.setup(bot=self.bot, loop=asyncio.get_event_loop())  # this is to define here.bot in the hf file
                except Exception as e:
                    await utils.safe_send(ctx, f'**`ERROR:`** {type(e).__name__} - {e}')
                else:
                    await utils.safe_send(ctx, f'**`{cog}: SUCCESS`**', delete_after=5.0)

            elif cog == 'utils':
                # reload file in cogs/utils/BotUtils/bot_utils.py
                try:
                    importlib.reload(sys.modules['cogs.utils.BotUtils.bot_utils'])
                    utils.setup(bot=self.bot, loop=asyncio.get_event_loop())
                except Exception as e:
                    await utils.safe_send(ctx, f'**`ERROR:`** {type(e).__name__} - {e}')
                else:
                    await utils.safe_send(ctx, f'**`{cog}: SUCCESS`**', delete_after=5.0)

            else:
                try:
                    await self.bot.reload_extension(f'cogs.{cog}')
                    if cog == 'interactions':
                        sync = self.bot.get_command('sync')
                        await ctx.invoke(sync)
                except Exception as e:
                    await utils.safe_send(ctx, f'**`ERROR:`** {type(e).__name__} - {e}')
                else:
                    await utils.safe_send(ctx, f' **`{cog}: SUCCESS`**', delete_after=5.0)

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
        
        #  these are the default quotation marks on iOS, but they cause SyntaxError: invalid character in identifier
        body = (body.replace("“", '"').replace("”", '"')
                .replace("‘", "'").replace("’", "'"))
        
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
        await hf.dump_json()
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

    @commands.command()
    async def pull(self, ctx, mode: str = ""):
        """Safely fast-forward the bot repo."""
        force = mode.casefold().strip() == "force"
        try:
            result = await utils.safe_git_pull(force=force)
        except RuntimeError as exc:
            await ctx.send(f"**`ABORTED:`** {exc}")
            return

        if len(result) > 1900:
            result = result[:1900] + "\n...truncated"
        await ctx.send(f"```{result}```")

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

    @commands.command()
    async def sync(self, ctx: Optional[commands.Context]):
        """Syncs app commands"""
        # Sync interactions here in this file
        bot_guilds = [g.id for g in self.bot.guilds]
        for guild_id in [SP_SERV_ID, RY_TEST_SERV_ID]:
            if guild_id in bot_guilds:
                guild_object = discord.Object(id=guild_id)
                await self.bot.tree.sync(guild=guild_object)

        # global commands
        await self.bot.tree.sync()

        try:
            await ctx.message.add_reaction("♻")
        except (discord.HTTPException, discord.Forbidden, discord.NotFound):
            await ctx.send(f"**`interactions: commands synced`**", delete_after=5.0)

    @commands.command()
    async def change_to_forum(self, ctx: commands.Context, channel_before_id: int, channel_after_id: int):
        channel_before = self.bot.get_channel(channel_before_id)
        channel_after = self.bot.get_channel(channel_after_id)
        perms_before = channel_before.permissions_for(ctx.guild.me)
        perms_after = channel_after.permissions_for(ctx.guild.me)
        await ctx.send(f"Will change {channel_before.mention} to {channel_after.mention}")
        # "before" channel is a TextChannel with threads. Bot should have the ability to close threads
        # "after" channel is a ForumChannel. Bot should have the ability to create threads
        if not perms_before.manage_threads:
            await ctx.send(f"Bot doesn't have the permission to manage threads in {channel_before.mention}")
            return
        if not perms_after.create_public_threads:
            await ctx.send(f"Bot doesn't have the permission to create threads in {channel_after.mention}")
            return

        if ctx.guild.id != channel_before.guild.id != channel_after.guild.id:
            return

        for user_id in self.bot.db['reports']:
            report = self.bot.db['reports'][user_id]
            # skip if report['guild_id'] != ctx.guild.id, and then check if report['thread_id'] is in channel_before
            if report['guild_id'] != ctx.guild.id:
                continue
            if report['thread_id'] not in [t.id for t in channel_before.threads]:
                continue
            await ctx.send(f"Moving thread {report['thread_id']} to {channel_after.mention}")
            # open a post in the new forum channel with the same title and content as the thread
            thread = channel_before.get_thread(report['thread_id'])
            starter_message = await channel_before.fetch_message(report['thread_id'])
            post = (await channel_after.create_thread(name=thread.name, content=starter_message.content)).thread
            # update the report with the new thread id
            report['thread_id'] = post.id
            # post a message in the new post informing the mods that the thread has been moved with link to old thread
            await post.send(f"Thread moved from {thread.mention} to {post.mention}.")
            await thread.send(f"Thread moved to {post.mention}. This thread is no longer active.")
            await ctx.send(f"Thread {report['thread_id']} moved to {channel_after.mention}")
            # close the old thread
            await thread.edit(archived=True)
        # update self.bot.db['guilds']['channel'] with the new channel id
        self.bot.db['guilds'][ctx.guild.id]['channel'] = channel_after_id
        await ctx.send(f"Updated channel for {ctx.guild.name} to {channel_after.mention}")

    @commands.command()
    async def setup_forum(self,
                          ctx: commands.Context,
                          forum_channel_id: int,
                          report_room_type: str = "main"):
        """This command will:
        1) Create post called 'Meta Discussion' in the forum channel, pin it, and add the ID to
        bot.db['guilds']['meta_channel']
        2) Create tags: Complete (✅), Open (❗), Closed (Not Resolved) (⏹️),
        and Ban Appeal (🚷)"""
        self.bot.db['guilds'].setdefault(ctx.guild.id, {})
        forum_channel = self.bot.get_channel(forum_channel_id)
        perms = forum_channel.permissions_for(ctx.guild.me)
        if not perms.create_public_threads:
            await ctx.send(f"Bot doesn't have the permission to create threads in {forum_channel.mention}")
            return
        if not perms.manage_channels:
            await ctx.send(f"Bot doesn't have the permission to manage channels in {forum_channel.mention} "
                           f"(it's necessary just for creating the default tags for posts, you can remove it "
                           f"afterwards!)")
            return
        if not perms.manage_threads:
            await ctx.send(f"Bot doesn't have the permission to manage threads in {forum_channel.mention} "
                           f"(it's necessary for being able to archive threads!)")
            return

        try:
            meta_thread = await hf.ensure_forum_meta_thread(forum_channel)
        except ValueError as exc:
            await ctx.send(str(exc))
            return

        if not meta_thread:
            return

        await hf.ensure_forum_tags(forum_channel)

        try:
            hf.save_forum_report_config(self.bot.db['guilds'][ctx.guild.id], report_room_type,
                                        forum_channel_id, meta_thread.id)
        except ValueError as exc:
            await ctx.send(str(exc))
            return

        await ctx.send(f"Setup {report_room_type} forum channel {forum_channel.mention} "
                       f"for {ctx.guild.name}")
        return

    @commands.command()
    async def os(self, ctx, *, command):
        """
        Calls an os command using subprocess.run()
        This version will directly return the results of the command as text
        Command: The command you wish to input into your system
        """
        try:
            result = run(command,
                         stdout=PIPE,
                         stderr=PIPE,
                         universal_newlines=True,
                         shell=True,
                         timeout=15,
                         check=False)
        except TimeoutExpired:
            await utils.safe_send(ctx, "Command timed out")
            return
        result = f"{result.stdout}\n{result.stderr}"
        long = len(result) > 1994
        short_result = result[:1994]
        short_result = f"```{short_result}```"

        await utils.safe_send(ctx, short_result)

        if long:
            buffer = io.BytesIO(bytes(result, "utf-8"))
            f = discord.File(buffer, filename="text.txt")
            await ctx.send("Result was over 2000 characters", file=f)

async def setup(bot):
    await bot.add_cog(Owner(bot))