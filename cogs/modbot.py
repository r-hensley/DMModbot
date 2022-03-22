import logging
from concurrent.futures import thread
from typing import Optional, Union

import discord
from discord.ext import commands
import asyncio
import re
import os
import io
from contextlib import redirect_stdout
import traceback
import textwrap
from copy import deepcopy
import shutil
import json
import sys
import time
from datetime import datetime
from dataclasses import dataclass
from .utils.db_utils import int_keys_to_str_keys, get_thread_id_to_thread_info

dir_path = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

REPORT_TIMEOUT = 30

INSTRUCTIONS = """・`end` or `done` - Finish the current report.
・`_setup` - Reset the room completely (if there's a bug).
・`_clear` - Clear the waiting list
・`_send <id> <message text>` - Sends a message to a user or channel. It's helpful when you want a user to come 
　to the report room or send an official mod message to a channel.
・`_not_anonymous` - Type this during a report session to reveal moderator names for future messages. You can 
　enter it again to return to anonymity at any time during the session, and it'll be automatically reset to default   
　anonymity after the session ends."""

# database structure
# {
#     "prefix": {},
#     "pause": bool,
#     "settingup": [USER1_ID, USER2_ID],
#     "reports": { # user_id to thread_info
#         1234566789948 (user_id): {
#            "user_id": 123456789,
#            "guild_id": 1234566789,
#            "thread_id": 1234566789,
#            "mods": [USER_ID, USER2_ID ... ],
#            "not_anonymous": boolean,
#         }
#     },
#     "guilds": {
#         "123446036178059265": {
#             "channel": 123459535977955330,
#             "mod_role": 123459535977955330,
#         },
#     },
# }


def is_admin(ctx):
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


@dataclass
class OpenReport:
    thread_info: dict
    user: discord.User
    thread: discord.Thread
    source: Union[discord.Thread, discord.DMChannel]
    dest: Union[discord.Thread, discord.DMChannel]


class Modbot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_result = None
        # dict w/ key ID and value of last left report room time
        self.recently_in_report_room = {}

    @commands.Cog.listener()
    async def on_command(self, ctx):
        pass
    @commands.Cog.listener()
    async def on_typing(self, channel, user, _):
        if type(channel) != discord.DMChannel:
            return
        reports = self.bot.db['reports']
        if user.id in reports:
            thread_info = reports[user.id]
            report_thread = self.bot.get_channel(thread_info['thread_id'])
            if report_thread is None:
                await self.bot.error_channel.send(f"Thread ID {thread_info['thread_id']} does not exist")
                del reports[user.id] # clear reports since the thread id is invalid
                return
            await report_thread.trigger_typing()
            return

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

    @commands.Cog.listener()
    async def on_thread_update(self, before, after):
        if not before.archived and after.archived:
            if after.archiver_id == self.bot.user.id:
                # I archived it, so do noething
                return
            # thread has been archived by someone else
            thread_id = after.id
            thread_id_to_thread_info = get_thread_id_to_thread_info(self.bot.db)
            if thread_id in thread_id_to_thread_info:
                thread_info = thread_id_to_thread_info[thread_id]
                user = self.bot.get_user(thread_info['user_id'])
                if user is None:
                    await after.send("Failed to get the user who created this report.")
                    del self.bot.db['reports'][thread_info["user_id"]] 
                    return
                await self.close_room(OpenReport(thread_info, user, after, user.dm_channel, after ), False)

    # main code is here
    @commands.Cog.listener()
    async def on_message(self, msg):
        if msg.author.bot:
            return

        if self.bot.db['pause']:
            if msg.author.id == self.bot.owner_id and msg.content != "_pause":
                logging.info("Return statement reached", "_pause return statement")
                return

        """PM Bot"""
        if isinstance(msg.channel, discord.DMChannel):  # in a PM
            # starting a report, comes here if the user is not in server_select or in a report room already
            if msg.author.id not in self.bot.db['settingup'] and msg.author.id not in self.bot.db['reports']:
                if (msg.author in self.bot.recently_in_report_room.keys() and time.time() -
                        self.bot.recently_in_report_room[msg.author] < REPORT_TIMEOUT):
                    time_remaining = int(REPORT_TIMEOUT -
                                         (time.time() - self.bot.recently_in_report_room[msg.author]))
                    # re-running the same calculation is kind of a no-no but whatever
                    await msg.author.send(
                        f"You've recently left a report room. Please wait {time_remaining} more seconds before "
                        f"joining again.\nIf your message was something like 'goodbye', 'thanks', or similar, "
                        f"we appreciate it, but it is not necessary to open another room.")
                    return
                try:  # the user selects to which server they want to connect
                    self.bot.db['settingup'].append(msg.author.id)
                    guild: discord.Guild = await self.server_select(msg)
                    self.bot.db['settingup'].remove(msg.author.id)
                except Exception:
                    self.bot.db['settingup'].remove(msg.author.id)
                    await msg.author.send("WARNING: There's been an error. Setup will not continue.")
                    raise

                try:
                    if guild:
                        # this should enter them into the report room
                        await self.start_report_room(msg, guild)
                    return  # if it worked
                except Exception:
                    await msg.author.send("WARNING: There's been an error. Setup will not continue.")
                    raise

        # sending a message during a report
        # this next function returns either five values or None
        # it tries to find if a user messaged somewhere, which report room connection they're part of
        open_report = await self.find_current_guild(msg)
        if open_report:  # basically, if it's not None
            try:
                await self.send_message(msg, open_report)
            except Exception:
                await self.close_room(open_report, True)
                raise

    # for finding out which report session a certain message belongs to, None if not part of anything
    # we should only be here if a user is for sure in the report room
    async def find_current_guild(self, msg: discord.Message) -> Optional[OpenReport]:
        if msg.guild:  # guild --> DM
            if msg.guild.id not in self.bot.db['guilds']:
                return None  # a message in a guild not registered for a report room
            thread_id_to_thread_info = get_thread_id_to_thread_info(self.bot.db)
            if msg.channel.id not in thread_id_to_thread_info:
                return None  # Message not sent in one of the active threads
            
            thread_info = thread_id_to_thread_info[msg.channel.id]

            # now for sure you're messaging in the report room of a guild with an active report happening
            current_user: discord.User = self.bot.get_user(thread_info["user_id"])
            report_thread = msg.channel
            dest: discord.DMChannel = current_user.dm_channel
            if not dest:
                dest = await current_user.create_dm()
                if not dest:
                    return None  # can't create a DM with user

            return OpenReport(thread_info, current_user, report_thread, report_thread, dest)

        elif isinstance(msg.channel, discord.DMChannel):  # DM --> guild
            if msg.author.id not in self.bot.db['reports']:
                return None
            
            thread_info = self.bot.db['reports'][msg.author.id]

            source: discord.DMChannel = msg.author.dm_channel
            if not source:
                source = await msg.author.create_dm()
                if not source:
                    return None  # can't create a DM with user

            report_thread: discord.Thread = self.bot.get_channel(thread_info['thread_id'])
            current_user = msg.author
            return OpenReport(thread_info, current_user, report_thread, source, report_thread)

    #
    # for first entering a user into the report room
    async def server_select(self, msg):
        shared_guilds = sorted(
            [g for g in self.bot.guilds if msg.author in g.members], key=lambda x: x.name)

        guild = None
        if not guild:
            if len(shared_guilds) == 0:
                await msg.channel.send("I couldn't find any common guilds between us. Frankly, I don't know how you're "
                                       "messaging me. Have a nice day.")
                return
            elif len(shared_guilds) == 1:
                if shared_guilds[0].id in self.bot.db['guilds']:
                    try:
                        q_msg = await msg.channel.send(f"Do you need to enter the report room of the server "
                                                       f"`{shared_guilds[0].name}` and make a report to the mods of"
                                                       f" that server?")
                    except AttributeError:
                        return
                    await q_msg.add_reaction("✅")
                    await q_msg.add_reaction("❌")
                    try:
                        def check(reaction_check, user_check):
                            if user_check == msg.author:
                                if reaction_check.message.channel == msg.channel:
                                    if str(reaction_check) in "✅❌":
                                        return True

                        reaction, user = await self.bot.wait_for('reaction_add', check=check, timeout=60.0)
                    except asyncio.TimeoutError:
                        await msg.channel.send("You've waited too long. Module closing.")
                        return
                    if str(reaction) == "❌":
                        await msg.channel.send("Module closing.")
                        return
                    guild = shared_guilds[0]
                    await reaction.message.remove_reaction("✅", self.bot.user)
                    await reaction.message.remove_reaction("❌", self.bot.user)
                else:
                    await msg.channel.send("We only share one guild, but that guild has not setup their report room"
                                           " yet. Please tell the mods to type `_setup` in some channel.")
                    return
            else:
                msg_text = "Hello, thank you for messaging. We share multiple servers, so please select which " \
                           "server you're trying to make a report to by replying with the `number` before your " \
                           "server (for example, you could reply with the single number `3`.)"
                index = 1
                msg_embed = '`1)` '
                for i_guild in shared_guilds:
                    index += 1
                    msg_embed += f"{i_guild.name}"
                    if index < len(shared_guilds) + 1:
                        msg_embed += f"\n`{index})` "
                try:
                    await msg.channel.send(msg_text, embed=discord.Embed(description=msg_embed, color=0x00FF00))
                except AttributeError:
                    return
                try:
                    resp = await self.bot.wait_for('message',
                                                   check=lambda m: m.author == msg.author and m.channel == msg.channel,
                                                   timeout=60.0)
                except asyncio.TimeoutError:
                    await msg.channel.send("You've waited too long. Module closing.")
                    return
                if resp.content.casefold() == 'cancel':
                    return
                guild_selection = re.findall(r"^\d{1,2}$", resp.content)
                if guild_selection:
                    guild_selection = guild_selection[0]
                    try:
                        guild = shared_guilds[int(guild_selection) - 1]
                    except IndexError:
                        await msg.channel.send("I didn't understand which guild you responded with. "
                                               "Please respond with only a single number.")
                        return
                else:
                    await msg.channel.send("I didn't understand which guild you responded with. "
                                           "Please respond with only a single number.")
                    return

        if guild.id not in self.bot.db['guilds']:
            return

        return guild

    async def start_report_room(self, msg: discord.Message, guild: discord.Guild):
        guild_config = self.bot.db['guilds'][guild.id]
        report_channel = self.bot.get_channel(guild_config['channel'])

        # #### SPECIAL STUFF FOR JP SERVER ####
        # Turn away new users asking for a role
        if guild.id == 189571157446492161:
            report_room = guild.get_channel(697862475579785216)
            jho = guild.get_channel(189571157446492161)
            member = guild.get_member(msg.author.id)
            if guild.get_role(249695630606336000) in member.roles:  # new user role
                for word in ['voice', 'role', 'locked', 'tag', 'lang', 'ボイス', 'チャンネル']:
                    if word in msg.content:
                        await member.send(f"In order to use the voice channels, you need a language tag first. "
                                          f"Please state your native language in {jho.mention}.\n"
                                          f"ボイスチャットを使うにはいずれかの言語ロールが必要です。 "
                                          f"{jho.mention} にて母語を教えて下さい。")
                        text = f"{str(msg.author.mention)} came to me with the following message:" \
                               f"```{msg.content}```" \
                               f"I assumed they were asking for language tag, so I told them to state their " \
                               f"native language in JHO and blocked their request to open the report room."
                        await report_room.send(embed=discord.Embed(description=text, color=0xFF0000))
                        return

        # ##### START THE ROOM #######
        async def open_room():
            if not msg.author.dm_channel:
                await msg.author.create_dm()
            await report_channel.trigger_typing()

            await msg.author.dm_channel.trigger_typing()
            await asyncio.sleep(1)

            try:
                entry_text = f"The user {msg.author.mention} has entered the report room. Reply in the thread to continue."
                thread_text = f"""@here I'll relay any of their messages to this channel. Any messages you type will be sent to them.
To end this chat, type `end` or `done`.
To *not* send a certain message, start the message with `_`. " For example, `Hello` would be sent and `_What should we do`/bot commands would not be sent." **Report starts here\n__{' '*70}__**\n\n\n⠀
                """  # invisible character at end of this line
                entry_message = await report_channel.send(entry_text)
                report_thread = await entry_message.create_thread(name=f'{msg.author.name} report {datetime.now().strftime("%Y-%m-%d")}', auto_archive_duration=1440) # Auto archive in 24 hours
                await report_thread.send(thread_text)
                self.bot.db['reports'][msg.author.id] = {
                    "user_id": msg.author.id,
                    "thread_id": report_thread.id,
                    "guild_id": report_thread.guild.id,
                    "mods": [],
                    "not_anonymous": False
                }
                user_text = f">>> {msg.author.mention}: {msg.content}"
                if len(user_text) > 2000:
                    await report_thread.send(user_text[:2000])
                    await report_thread.send(user_text[2000:])
                else:
                    await report_thread.send(user_text)
                await msg.add_reaction('📨')
                await msg.add_reaction('✅')
                if msg.attachments:
                    for attachment in msg.attachments:
                        await report_thread.send(f">>> {attachment.url}")
                if msg.embeds:
                    await report_thread.send(embed=msg.embeds[0])

            except discord.Forbidden:
                await msg.channel.send("Sorry, actually I can't send messages to the channel the mods had setup for me "
                                       "anymore. Please tell them to check the permissions on the channel or to run the"
                                       " setup command again.")
                return True

            await msg.channel.send(embed=discord.Embed(
                description="You are now connected to the moderators of the server, and I've sent your above "
                            "message. The moderators will see any messages or images you send,"
                            " and you'll receive messages from the mods too. It may take a while for the moderators "
                            "to see your report, so please be patient. \n\n"
                            "When you are done talking to the mods, please type `end` or `done`, and then "
                            "the chat will close.",
                color=0x00FF00))
            return True

        try:
            await open_room()  # maybe this should always be True
        except Exception:
            if msg.author.id in self.bot.db['reports']:
                del self.bot.db['reports'][msg.author.id]
            await self.notify_close_room( report_channel, msg.author.dm_channel, True) 
            raise

    """Send message"""
    async def send_message(self,
                           msg: discord.Message,
                           open_report: OpenReport):
        if msg.content:
            for prefix in ['_', ';', '.', ',', '>>', '&']:
                # messages starting with _ or other bot prefixes
                if msg.content.startswith(prefix):
                    try:
                        await msg.add_reaction('🔇')
                    except discord.NotFound:
                        pass
                    return
        if msg.author.bot:
            if msg.author == msg.guild.me:
                if msg.content.startswith('>>> '):
                    return
            await msg.add_reaction('🔇')
            return

        thread_info = open_report.thread_info

        # message is from report channel >> DMChannel
        if isinstance(open_report.dest, discord.DMChannel):
            if msg.author.id not in thread_info['mods']:
                # to be used later to specify Moderator 1, Moderator 2, etc
                thread_info['mods'].append(msg.author.id)

        if msg.content:
            if msg.content.casefold() in ['end', 'done']:
                await self.close_room(open_report, False)
                return
            if isinstance(open_report.dest, discord.DMChannel):
                cont = f">>> **Moderator {thread_info['mods'].index(msg.author.id) + 1}"
                if thread_info.setdefault('not_anonymous', False):
                    cont += f" ({msg.author.mention}):** "
                else:
                    cont += ":** "
            else:
                cont = f">>> {msg.author.mention}: "
            splice = 2000 - len(cont)
            cont += msg.content[:splice]
            if len(msg.content) > splice:
                cont2 = f">>> ... {msg.content[splice:]}"
            else:
                cont2 = None
        else:
            cont = cont2 = None

        try:
            if len(msg.embeds) >= 1:
                for embed in msg.embeds:
                    await open_report.dest.send(embed=embed)

            if msg.attachments:
                for attachment in msg.attachments:
                    await open_report.dest.send(f">>> {attachment.url}")

            if cont:
                try:
                    await open_report.dest.send(cont)
                except discord.Forbidden:
                    await self.close_room(open_report, True)

            if cont2:
                try:
                    await open_report.dest.send(cont2)
                except discord.Forbidden:
                    await self.close_room(open_report, True)

        except discord.Forbidden:
            if open_report.dest == open_report.user.dm_channel:
                await msg.channel.send("I couldn't send a message to the user (maybe they blocked me). "
                                       "I have closed the chat.")

            elif open_report.dest == open_report.thread:
                await msg.channel.send("I couldn't send your message to the mods. Maybe they've locked me out "
                                       "of the report channel. I have closed this chat.")
            await self.close_room(open_report, False)

    async def notify_close_room(self, source, dest, error):
        is_source_thread = isinstance(source, discord.Thread)
        is_dest_thread = isinstance(dest, discord.Thread)
        if error:
            try:
                await source.send("WARNING: There's been some kind of error. I will close the room. Please try again.")
                await dest.send("WARNING: There's been some kind of error. I will close the room. Please try again.")
            except discord.Forbidden:
                pass
        else:
            try:
                await source.send(f"**⠀\n⠀\n⠀\n__{' '*70}__**\n**Thank you, I have closed the room.{' Messages in this thread will no longer be sent to the user' if is_source_thread else ''}**")
                await dest.send(f"**⠀\n⠀\n⠀\n__{' '*70}__**\n**Thank you, I have closed the room.{' Messages in this thread will no longer be sent to the user' if is_dest_thread else ''}**")
            except discord.Forbidden:
                pass

    # for when the room is to be closed and the database reset
    # the error argument tells whether the room is being closed normally or after an error
    # source is the DM channel, dest is the report room
    async def close_room(self, open_report: OpenReport, error):
        await self.notify_close_room(open_report.source, open_report.dest, error)
        thread = self.bot.get_channel(open_report.thread_info['thread_id'])
        if open_report.user.id in self.bot.db['reports']:
            del self.bot.db['reports'][open_report.user.id]
        if thread:
            await thread.edit(archived=True)
        self.bot.recently_in_report_room[open_report.user.id] = time.time()

    #
    # ############ OTHER GENERAL COMMANDS #################
    #

    @commands.command()
    async def invite(self, ctx):
        """Get an link to invite this bot to your server"""
        link = f"https://discordapp.com/oauth2/authorize?client_id={self.bot.user.id}&scope=bot&permissions=18496"
        await ctx.send(f"Invite me using this link: {link}")

    @commands.command()
    @commands.check(is_admin)
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
            except discord.Forbidden:
                pass

    # ############ ADMIN COMMANDS #################
    @commands.command()
    @commands.check(is_admin)
    async def clear(self, ctx):
        """Clears the server state """
        if ctx.guild.id not in self.bot.db['guilds']:
            return
        for user_id, thread_info in self.bot.db['reports'].items():
            if thread_info['guild_id'] == ctx.guild.id:
                del self.bot.db['reports'][user_id]
        await ctx.send("I've cleared the guild report state.")
        await self.dump_json(ctx)

    @commands.command()
    @commands.check(is_admin)
    async def setup(self, ctx):
        """Sets the current channel as the report room, or resets the report module"""
        guilds = self.bot.db['guilds']
        if ctx.guild.id not in guilds:
            guilds[ctx.guild.id] = { 'mod_role': None }
        guild_config = guilds[ctx.guild.id]
        guilds[ctx.guild.id] = {'channel': ctx.channel.id, 'mod_role': guild_config['mod_role'] }
        await ctx.send(f"I've set the report channel as this channel. Now if someone messages me I'll deliver "
                       f"their messages here.\n\nIf you'd like to pin the following message, it's some instructions "
                       f"on helpful commands for the bot")
        await ctx.send(INSTRUCTIONS)
        await self.dump_json(ctx)

    @commands.command()
    @commands.check(is_admin)
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
        mod_role = discord.utils.find(
            lambda role: role.name == role_name, ctx.guild.roles)
        if not mod_role:
            await ctx.send("The role with that name was not found")
            return None
        guild_config['mod_role'] = mod_role.id
        await ctx.send(f"Set the mod role to {mod_role.name} ({mod_role.id})")
        await self.dump_json(ctx)

    @commands.command(aliases=['not_anon', 'non_anonymous', 'non_anon', 'reveal'])
    @commands.check(is_admin)
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

    #
    # ########### OWNER COMMANDS ####################
    #

    @commands.command()
    @commands.is_owner()
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
    @commands.is_owner()
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
    @commands.is_owner()
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
    @commands.is_owner()
    async def sdb(self, ctx):
        await self.dump_json(ctx)
        try:
            await ctx.message.add_reaction('\u2705')
        except discord.NotFound:
            pass

    @staticmethod
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

    @commands.command()
    @commands.is_owner()
    async def flush(self, ctx):
        """Flushes stderr/stdout"""
        sys.stderr.flush()
        sys.stdout.flush()
        await ctx.message.add_reaction('🚽')

    @commands.command(aliases=['quit'])
    @commands.is_owner()
    async def kill(self, ctx):
        """Modbot is a killer"""
        try:
            await ctx.message.add_reaction('💀')
            await ctx.invoke(self.flush)
            await ctx.invoke(self.sdb)
            await self.bot.logout()
            await self.bot.close()
        except Exception as e:
            await ctx.send(f'**`ERROR:`** {type(e).__name__} - {e}')

    @commands.command()
    @commands.is_owner()
    async def pause(self, ctx):
        self.bot.db['pause'] = not self.bot.db['pause']
        await ctx.message.add_reaction('✅')

    @commands.command()
    @commands.is_owner()
    async def db(self, ctx):
        """Shows me my DB"""
        t = f"prefix: {self.bot.db['prefix']}\npause: {self.bot.db['pause']}\n" \
            f"settingup: {self.bot.db['settingup']}\nreports: {self.bot.db['reports']}\n"
        for guild in self.bot.db['guilds']:
            t += f"{guild}: {self.bot.db['guilds'][guild]}\n"
        await ctx.send(t)


async def setup(bot):
    await bot.add_cog(Modbot(bot))
