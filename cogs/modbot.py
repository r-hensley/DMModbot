import asyncio
import os
import re
from dataclasses import dataclass
from datetime import datetime
from textwrap import dedent
from typing import Optional, Union

import discord
from discord import Guild
from discord.ext import commands

from .utils.db_utils import get_thread_id_to_thread_info
from .utils import helper_functions as hf
# from cogs.utils.BotUtils import bot_utils as utils

dir_path = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# database structure
# {
#     "prefix": {},
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
#     "user_localizations": {
#         "123446036178059265": "en-US"
#     },
# }

SP_SERV_ID = 243838819743432704
JP_SERV_ID = 189571157446492161


async def _send_typing_notif(self, channel, user):
    if type(channel) != discord.DMChannel:
        return
    reports = self.bot.db['reports']
    if user.id in reports:
        thread_info = reports[user.id]
        report_thread = self.bot.get_channel(thread_info['thread_id'])
        if report_thread is None:
            await self.bot.error_channel.send(f"Thread ID {thread_info['thread_id']} does not exist")
            del reports[user.id]  # clear reports since the thread id is invalid
            return
        await report_thread.typing()
        return


@dataclass
class OpenReport:
    thread_info: dict
    user: discord.User
    thread: discord.Thread
    source: Union[discord.Thread, discord.DMChannel]
    dest: Union[discord.Thread, discord.DMChannel]


class Modbot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot
        # dict w/ key ID and value of last left report room time
        if not hasattr(self, "recently_in_report_room"):
            self.recently_in_report_room = {}

    # main code is here
    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.author.bot:
            return  # ignore messages from bots

        if isinstance(msg.channel, discord.VoiceChannel):
            return  # messages in new voice channel text channels were causing bugs

        """PM Bot"""
        # This function will handle new users who are not in a report room and trying to start a new report
        if isinstance(msg.channel, discord.DMChannel):  # in a PM
            if result := await self.receive_new_users(msg):
                if result == "BLOCKED_USER":
                    await msg.reply("There has been some kind of error in joining that server's report room. Please "
                                    "contact the mods directly.")
                return  # True if a new user came into the report room

        # sending a message during a report
        # it tries to connect a message to a report and deliver it to the right place (either report room or DM channel)
        open_report = await self.find_current_guild(msg)
        # can be None if the above message was not sent to one of the open report threads in a server: i.e., it's
        # a random unrelated message in a server in a random channel
        if open_report:
            try:
                await self.send_message(msg, open_report)
            except Exception:
                await self.end_report(open_report, error=True)
                raise

    async def receive_new_users(self, msg: discord.Message):
        """This function is called whenever a user messages Modbot.

        It returns True if the user was not in any report rooms before and successfully admitted into one"""
        # check if they're currently in a report already
        if msg.author.id in list(self.bot.db['reports']):
            return False

        # check if they're currently in the middle of setting up a report already
        if msg.author.id in self.bot.db['settingup']:
            # if not a number (numbers are probably the user trying to specify which guild they want to connect to)
            if not msg.content.isdigit():
                await hf.try_add_reaction(msg, "❌")
            return False

        # then check if user just recently left a report room
        if time_remaining := self.check_if_recently_finished_report(msg):
            await msg.author.send(
                f"You've recently left a report room. Please wait {time_remaining} more seconds before "
                f"joining again.\nIf your message was something like 'goodbye', 'thanks', or similar, "
                f"we appreciate it, but it is not necessary to open another room.")
            return True

        # try to put user into report room
        else:
            guild: discord.Guild
            main_or_secondary: str  # "main" means main report room, "secondary" means report room for staff
            try:  # the user selects to which server they want to connect
                self.bot.db['settingup'].append(msg.author.id)
                guild, main_or_secondary = await self.server_select(msg)
            except Exception:
                self.bot.db['settingup'].remove(msg.author.id)
                await msg.author.send("WARNING: There's been an error. Setup will not continue.")
                raise

            # they've selected a server to make a report to, put them in that server's report room
            try:
                if guild:
                    # check if they have been blocked by the /block command
                    if main_or_secondary == "BLOCKED_USER":
                        return "BLOCKED_USER"

                    # assuming they haven't been blocked, continue here
                    await self.start_report_room(msg.author, guild, msg,
                                                 main_or_secondary, ban_appeal=False)  # bring user to report room
                return True  # if it worked
            except Exception:
                await msg.author.send("WARNING: There's been an error. Setup will not continue.")
                raise
            finally:
                self.bot.db['settingup'].remove(msg.author.id)

    # for finding out which report session a certain message belongs to, None if not part of anything
    # we should only be here if a user is for sure in the report room
    async def find_current_guild(self, msg: discord.Message) -> Optional[OpenReport]:
        if msg.guild:  # guild --> DM
            if msg.guild.id not in self.bot.db['guilds']:
                return None  # a message in a guild not registered for a report room
            thread_id_to_thread_info = get_thread_id_to_thread_info(self.bot.db)

            if msg.channel.id not in thread_id_to_thread_info:
                # check if msg.channel.parent is a guild report room
                if msg.content.casefold() == "finish" and hf.is_thread_in_a_report_channel(msg.channel):
                    # close thread, and add a "✅" reaction to the "finish" message
                    await hf.try_add_reaction(msg, "✅")
                    await hf.close_thread(msg.channel, finish=True)

                return None  # Message not sent in one of the active threads

            thread_info = thread_id_to_thread_info[msg.channel.id]

            # now for sure you're messaging in the report room of a guild with an active report happening
            current_user: discord.User = self.bot.get_user(thread_info["user_id"])
            if not current_user:
                # delete the entry out of bot.db['reports']
                del self.bot.db['reports'][msg.author.id]
                return None  # can't find the user

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

            # just delete the entry out of bot.db['reports']
            if not report_thread:
                del self.bot.db['reports'][msg.author.id]
                return None

            # if I want code that tries to unarchive the thread, I can use this
            #     # first, try to find the thread in the main report room
            #     report_room_id = self.bot.db['guilds'][thread_info['guild_id']]['channel']
            #     report_room = self.bot.get_channel(report_room_id)
            #     async for t in report_room.archived_threads():
            #         if t.id == thread_info['thread_id']:
            #             report_thread = t
            #             break
            #
            #     # if not found in main report room, try to find it in the secondary report room
            #     if not report_thread:
            #         if self.bot.db['guilds'][msg.guild.id]['secondary_channel']:
            #             report_room_id = self.bot.db['guilds'][thread_info['guild_id']]['secondary_channel']
            #             report_room = self.bot.get_channel(report_room_id)
            #             async for t in report_room.archived_threads():
            #                 if t.id == thread_info['thread_id']:
            #                     report_thread = t
            #                     break
            #
            #     # if still not found, return None
            #     if not report_thread:
            #         return None  # can't find the thread
            #
            # # if the thread is found, unarchive it if it's archived
            # if report_thread.archived:
            #     try:
            #         await report_thread.edit(archived=False)
            #     except (discord.Forbidden, discord.HTTPException):
            #         return None  # can't unarchive the thread

            current_user = msg.author
            return OpenReport(thread_info, current_user, report_thread, source, report_thread)

    # for first entering a user into the report room
    async def server_select(self, msg: discord.Message) -> Union[tuple[None, None], tuple[discord.Guild, str]]:
        """From the entry message into the DMs by a user, ask them which server they want to connect to, and return
        a guild object."""
        shared_guilds = sorted(
            [g for g in self.bot.guilds if msg.author in g.members], key=lambda x: x.name)

        appeals_server = self.bot.get_guild(int(os.getenv("BAN_APPEALS_GUILD_ID") or 0))
        if appeals_server:
            try:
                shared_guilds.remove(appeals_server)
            except ValueError:
                pass

        guild: Optional[discord.Guild] = None
        if not guild:
            if len(shared_guilds) == 0:
                await msg.channel.send("I couldn't find any common guilds between us. Frankly, I don't know how you're "
                                       "messaging me. Have a nice day.")
                return None, None
            elif len(shared_guilds) == 1:
                if shared_guilds[0].id in self.bot.db['guilds']:
                    main_or_secondary: str
                    guild, main_or_secondary = await self.ask_report_type(msg.author, shared_guilds[0])
                    return guild, main_or_secondary

                else:
                    await msg.channel.send("We only share one guild, but that guild has not setup their report room"
                                           " yet. Please tell the mods to type `_setup` in some channel.")
                    return None, None
            else:
                msg_text = {"en": "Hello, thank you for messaging me. Please select which "
                                  "server want to connect to. To do this, reply with the `number` before your "
                                  "server (for example, you can reply with the single number `3`.)",
                            "es": "Hola, gracias por enviarme un mensaje. Por favor, selecciona a qué servidor "
                                  "quieres conectarte. Para hacer esto, responda con el `número` antes de su "
                                  "servidor (por ejemplo, puede responder sólo con el número `3`)",
                            "ja": "こんにちは、メッセージありがとうございます。どのサーバーに接続したいかを選択してください。"
                                  "これを行うには、以下のサーバーの一つの名前の前にある数字を書いて返信してください "
                                  "(例えば、`3` という単一の数字で返信したら接続できます)。"}
                locale = hf.get_user_locale(msg.author.id)
                msg_text = msg_text.get(locale, msg_text['en'])
                index = 1
                msg_embed = ''
                for i_guild in shared_guilds:
                    msg_embed += f"`{index})` "
                    index += 1
                    msg_embed += f"{i_guild.name}"
                    msg_embed += "\n"
                try:
                    conf = await msg.channel.send(msg_text, embed=discord.Embed(description=msg_embed, color=0x00FF00))
                except AttributeError:
                    return None, None
                try:
                    resp = await self.bot.wait_for('message',
                                                   check=lambda m: m.author == msg.author and m.channel == msg.channel,
                                                   timeout=60.0)
                except asyncio.TimeoutError:
                    try:
                        await conf.delete()
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                    await msg.channel.send("You've waited too long. Module closing.")
                    return None, None
                try:
                    await conf.delete()
                except (discord.Forbidden, discord.HTTPException):
                    pass

                if resp.content.casefold() == 'cancel':
                    return None, None
                guild_selection = re.findall(r"^\d{1,2}$", resp.content)
                if guild_selection:
                    guild_selection = guild_selection[0]
                    try:
                        guild = shared_guilds[int(guild_selection) - 1]
                    except IndexError:
                        await msg.channel.send("I didn't understand which guild you responded with. "
                                               "Please respond with only a single number.")
                        return None, None
                else:
                    await msg.channel.send("I didn't understand which guild you responded with. "
                                           "Please respond with only a single number.")
                    return None, None

        if guild.id not in self.bot.db['guilds']:
            return None, None

        # the output point of this function will check if main_or_secondary equals "BLOCKED_USER"
        # if so, it'll propagate that error upwards so a report doesn't get started
        # it is checking if a server has blocked this user
        if guild:
            blocked_users_dict = self.bot.db.get('blocked_users', {})
            if msg.author.id in blocked_users_dict.get(guild.id, []):
                return guild, "BLOCKED_USER"

        guild, main_or_secondary = await self.ask_report_type(msg.author, guild)
        return guild, main_or_secondary

    async def ask_report_type(self, author: Union[discord.User, discord.Member],
                              guild: discord.Guild) -> Union[tuple[None, None], tuple[Guild, str]]:
        """After a user selects a server, this function will ask them which kind of report they want to make"""

        # below function defines and sets up four buttons for the user to select what kind of report they want to make
        report_button, account_q_button, server_q_button, cancel_button = \
            await hf.setup_confirm_guild_buttons(guild, author)

        # wait for the user to press a button
        def check_for_button_press(i):
            return i.type == discord.InteractionType.component and \
                   i.data.get("custom_id", "") in [report_button.custom_id, account_q_button.custom_id,
                                                   server_q_button.custom_id, cancel_button.custom_id]

        try:
            interaction = await self.bot.wait_for("interaction", timeout=180.0, check=check_for_button_press)
        except asyncio.TimeoutError:
            return None, None  # no button pressed
        else:
            if interaction.data.get("custom_id", "") in [report_button.custom_id, account_q_button.custom_id]:
                return guild, 'main'
            elif interaction.data.get("custom_id", "") == server_q_button.custom_id:
                return guild, 'secondary'
            else:
                return None, None

    async def start_report_room(self, author: discord.User, guild: discord.Guild, msg: Optional[discord.Message],
                                main_or_secondary: str, ban_appeal=False):
        """Performs initial code for bringing a user's first message into the report room and setting up the
        connection between the user and the mods.

        If this report is a ban appeal from the ban appeals server, then msg will be None and ban_appeal will be True"""
        try:
            report_channel, meta_channel = await hf.get_report_variables(guild, main_or_secondary, author)
        except hf.EndEarly:
            return

        # Check if the bot has the permissions to send messages in the report channel and create threads.
        await hf.check_bot_perms(report_channel, meta_channel, guild, author)

        # Deny users who come to the bot without language roles (they're probably asking how to get roles)
        await hf.new_user_role_request_denial(guild, ban_appeal, author, msg, meta_channel)

        # ##### START THE ROOM #######
        async def open_room():
            if not author.dm_channel:
                await author.create_dm()
            if isinstance(report_channel, discord.TextChannel):
                await report_channel.typing()

            await author.dm_channel.typing()
            await asyncio.sleep(1)

            try:
                report_thread = await hf.create_report_thread(author, msg, report_channel, ban_appeal)

                # try to capture the modlog that rai will post, delete it, and repost it ourselves to the thread
                await hf.repost_rai_modlog(report_thread)

                # Send divider to report room splitting information from bot above and actual report messages below
                invisible_character = "⠀"  # replacement of space to avoid whitespace trimming
                vertical_space = f"**Report starts here\n__{' ' * 70}__**\n\n\n{invisible_character}"
                await report_thread.send(vertical_space)

                # add info about user to self.bot.db['reports']
                await hf.add_report_to_db(author, report_thread)

                # send first message, notify user in DMs that the message successfully sent
                await hf.deliver_first_report_msg(report_thread, ban_appeal, author, msg)

            except discord.Forbidden:
                await author.send("Sorry, actually I can't send messages to the channel the mods had setup for me "
                                  "anymore. Please tell them to check the permissions on the channel or to run the"
                                  " setup command again.")
                return True

            # Send user a message explaining that the connection to the room has been made and explaining roughly
            # how to use the room. The message can be in English, Spanish, or Japanese depending on the user's locale.
            await hf.notify_user_of_report_connection(author, ban_appeal)

        try:
            await open_room()  # maybe this should always be True
        except Exception:
            if author.id in self.bot.db['reports']:
                del self.bot.db['reports'][author.id]
            await self.notify_end_thread(meta_channel, author.dm_channel, True)
            raise

    """Send message"""

    async def send_message(self, msg: discord.Message, open_report: OpenReport):
        # ignore messages starting with _ or other bot prefixes, also ignore all bot messages
        if not await hf.check_if_valid_msg(msg):
            return

        thread_info = open_report.thread_info

        # message is from report channel >> DMChannel
        # this creates a list of moderator IDs
        # whenever a moderator sends a message, it'll check their position in the list and give them a name like
        # "Moderator 1" if they're the first ID in the list
        if isinstance(open_report.dest, discord.DMChannel):
            if msg.author.id not in thread_info['mods']:
                # to be used later to specify Moderator 1, Moderator 2, etc
                thread_info['mods'].append(msg.author.id)

        try:
            cont, cont2 = await self.process_msg_content(msg, open_report)
        except hf.EndEarly:
            return

        try:
            if msg.embeds:
                await open_report.dest.send(embeds=msg.embeds)

            if msg.attachments:
                for attachment in msg.attachments:
                    await open_report.dest.send(f">>> {attachment.url}")

            if cont:
                await open_report.dest.send(cont)

            if cont2:
                await open_report.dest.send(cont2)

        except discord.Forbidden:
            if open_report.dest == open_report.user.dm_channel:
                await msg.channel.send("I couldn't send a message to the user (maybe they blocked me or left "
                                       "the server). I will close the chat.")

            elif open_report.dest == open_report.thread:
                await msg.channel.send("I couldn't send your message to the mods. Maybe they've locked me out "
                                       "of the report channel. I will close this chat.")

            await self.end_report(open_report, False)

        else:
            await hf.try_add_reaction(msg, "📨")

    async def process_msg_content(self, msg, open_report):
        thread_info = open_report.thread_info

        if msg.content:
            if msg.content.casefold() == 'done':
                await hf.try_add_reaction(msg, '🔇')
                await msg.reply("This used to be a command to close the room, but it has been changed to `close` "
                                "instead of `done` to avoid accidental closure of rooms by people trying to actually "
                                "send the word `done` to the reporter. For now, I've disabled the use of the word.")
                raise hf.EndEarly

            # if anyone types "end" or "close" in the report room, close the room
            if msg.content.casefold() in ['end', 'close']:
                await self.end_report(open_report, error=False, finish=False)
                raise hf.EndEarly

            # if the mods type "finish" (not the user in the DMs), close the room and mark it as resolved
            if msg.content.casefold() in ["finish"]:
                finish = isinstance(open_report.source, discord.Thread)  # True if in report room, from mods
                await self.end_report(open_report, error=False, finish=finish)
                raise hf.EndEarly

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

        return cont, cont2

    @staticmethod
    async def notify_end_thread(source, dest, error):
        """Notify the user and the mods that the room has been closed."""
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
                invisible_character = "⠀"  # To avoid whitespace trimming
                s1 = f"**{invisible_character}\n\n__{' ' * 70}__**\n**" \
                     f"Thank you, I have closed the room." \
                     f"{' Messages in this thread will no longer be sent to the user' if is_source_thread else ''}**"
                await source.send(s1)

                s2 = f"**{invisible_character}\n\n\n__{' ' * 70}__**\n**" \
                     f"Thank you, I have closed the room." \
                     f"{' Messages in this thread will no longer be sent to the user' if is_dest_thread else ''}**"
                await dest.send(s2)
            except discord.Forbidden:
                pass

    # for when the room is to be closed and the database reset
    # the error argument tells whether the room is being closed normally or after an error
    # source is the DM channel, dest is the report room
    async def end_report(self, open_report: OpenReport, error, finish=False):
        await self.notify_end_thread(open_report.source, open_report.dest, error)

        # get thread from open_report object
        thread: discord.Thread = self.bot.get_channel(open_report.thread_info['thread_id'])

        # delete report info from database
        if open_report.user.id in self.bot.db['reports']:
            del self.bot.db['reports'][open_report.user.id]

        # close the thread
        await hf.close_thread(thread, finish)

        # Add time the report ended to prevent users from quickly opening up the room immediately after it closes
        self.bot.recently_in_report_room[open_report.user.id] = discord.utils.utcnow().timestamp()

        await hf.log_record_of_report(thread, open_report.user)

    @commands.Cog.listener()
    async def on_typing(self, channel, user, _):
        """When a user in a DM channel starts typing, display that in the modbot report channel"""
        await _send_typing_notif(self, channel, user)

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        # check if bot has view_audit_logs permission
        if not before.guild.me.guild_permissions.view_audit_log:
            return

        if not before.archived and after.archived:
            # check audit log to see who archived the thread
            async for entry in after.guild.audit_logs(limit=5, action=discord.AuditLogAction.thread_update):
                if entry.target.id == after.id:
                    if entry.user.id == self.bot.user.id:
                        # I archived it, so do nothing
                        return

            # thread has been archived by someone else
            thread_id = after.id
            thread_id_to_thread_info = get_thread_id_to_thread_info(self.bot.db)

            # if the thread is a report thread, close it
            if thread_id in thread_id_to_thread_info:
                thread_info = thread_id_to_thread_info[thread_id]
                user = self.bot.get_user(thread_info['user_id'])
                if user is None:
                    await after.send("Failed to get the user who created this report.")
                    del self.bot.db['reports'][thread_info["user_id"]]
                    return
                await self.end_report(OpenReport(thread_info, user, after, user.dm_channel, after), True)

            # else, if the thread at least is in the report room, but not an active thread, still close it
            elif hf.is_thread_in_a_report_channel(after):
                await hf.close_thread(after, finish=True)

    #
    # ############ OTHER GENERAL COMMANDS #################
    #

    @commands.command()
    async def invite(self, ctx):
        """Get a link to invite this bot to your server"""
        link = f"https://discordapp.com/oauth2/authorize?client_id={self.bot.user.id}&scope=bot&permissions=18496"
        await ctx.send(f"Invite me using this link: {link}")

    def check_if_recently_finished_report(self, msg):
        report_timeout = 30  # number of seconds to make a user wait after finishing a report to open another room

        currently_in_settingup = msg.author.id in self.bot.db['settingup']
        currently_in_report_room = msg.author.id in self.bot.db['reports']
        if not currently_in_settingup and not currently_in_report_room:
            timestamp_of_last_report_end = getattr(self.bot, "recently_in_report_room", {}).get(msg.author.id, 0)
            time_since_report = discord.utils.utcnow().timestamp() - timestamp_of_last_report_end
            if msg.author in self.bot.recently_in_report_room and time_since_report < report_timeout:
                time_remaining = int(report_timeout - time_since_report)
                return time_remaining

        return 0


async def setup(bot):
    await bot.add_cog(Modbot(bot))
