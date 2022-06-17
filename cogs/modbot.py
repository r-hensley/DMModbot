import re
import os

import asyncio
from typing import Optional, Union
from textwrap import dedent
from datetime import datetime
from dataclasses import dataclass

import discord
from discord.ext import commands

from .utils.db_utils import get_thread_id_to_thread_info

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
    def __init__(self, bot):
        self.bot: commands.Bot = bot
        # dict w/ key ID and value of last left report room time
        self.recently_in_report_room = {}

    # main code is here
    @commands.Cog.listener()
    async def on_message(self, msg):
        if msg.author.bot:
            return  # ignore messages from bots

        if isinstance(msg.channel, discord.VoiceChannel):
            return  # messages in new voice channel text channels were causing bugs

        """PM Bot"""
        # This function will handle new users who are not in a report room and trying to start a new report
        if isinstance(msg.channel, discord.DMChannel):  # in a PM
            if await self.receive_new_users(msg):
                return  # True if a new user came into the report room

        # sending a message during a report
        # it tries to connect a message to a report and deliver it to the right place (either report room or DM channel)
        open_report = await self.find_current_guild(msg)
        if open_report:  # basically, if it's not None
            try:
                await self.send_message(msg, open_report)
            except Exception:
                await self.close_room(open_report, error=True)
                raise

    async def receive_new_users(self, msg):
        """This function is called whenever a user messages Modbot.

        It returns True if the user was not in any report rooms before and successfully admitted into one"""
        # check if they're currently in a report/setting up for a report (here)
        if msg.author.id in self.bot.db['settingup'] + list(self.bot.db['reports']):
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
            try:  # the user selects to which server they want to connect
                self.bot.db['settingup'].append(msg.author.id)
                guild: discord.Guild = await self.server_select(msg)
                self.bot.db['settingup'].remove(msg.author.id)
            except Exception:
                self.bot.db['settingup'].remove(msg.author.id)
                await msg.author.send("WARNING: There's been an error. Setup will not continue.")
                raise

            # they've selected a server to make a report to, put them in that server's report room
            try:
                if guild:
                    await self.start_report_room(msg.author, guild, msg, ban_appeal=False)  # bring user to report room
                return True  # if it worked
            except Exception:
                await msg.author.send("WARNING: There's been an error. Setup will not continue.")
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

    async def start_report_room(self, author: discord.User, guild: discord.Guild, msg: Optional[discord.Message], 
                                ban_appeal=False):
        """Performs initial code for bringing a user's first message into the report room and setting up the
        connection between the user and the mods.

        If this report is a ban appeal from the ban appeals server, then msg will be None and ban_appeal will be True"""
        guild_config = self.bot.db['guilds'][guild.id]
        report_channel: discord.Thread = self.bot.get_channel(guild_config['channel'])

        perms = report_channel.permissions_for(guild.me)
        if not perms.send_messages or not perms.create_public_threads:
            try:
                await report_channel.send(f"WARNING: {author.mention} tried to join the report room, but in order "
                                          f"to open a report here, I need the `Create Public Threads` permission "
                                          f"in this channel. Please give me that permission and tell the user "
                                          f"to try again.")
            except discord.Forbidden:
                pass
            await author.send("The report room for this server is not properly setup. Please directly message "
                              "the mods.")
            return

        # #### SPECIAL STUFF FOR JP SERVER ####
        # Turn away new users asking for a role
        if guild.id == 189571157446492161 and not ban_appeal:
            report_room = guild.get_channel(697862475579785216)
            jho = guild.get_channel(189571157446492161)
            member = guild.get_member(author.id)
            if guild.get_role(249695630606336000) in member.roles:  # new user role
                for word in ['voice', 'role', 'locked', 'tag', 'lang', 'ボイス', 'チャンネル']:
                    if word in msg.content:
                        await member.send(f"In order to use the voice channels, you need a language tag first. "
                                          f"Please state your native language in {jho.mention}.\n"
                                          f"ボイスチャットを使うにはいずれかの言語ロールが必要です。 "
                                          f"{jho.mention} にて母語を教えて下さい。")
                        text = f"{str(author.mention)} came to me with the following message:" \
                               f"```{msg.content}```" \
                               f"I assumed they were asking for language tag, so I told them to state their " \
                               f"native language in JHO and blocked their request to open the report room."
                        await report_room.send(embed=discord.Embed(description=text, color=0xFF0000))
                        return

        # ##### START THE ROOM #######
        async def open_room():
            if not author.dm_channel:
                await author.create_dm()
            await report_channel.typing()

            await author.dm_channel.typing()
            await asyncio.sleep(1)

            try:
                invisible_character = "⠀"  # replacement of space to avoid whitespace trimming
                entry_text = f"The user {author.mention} has entered the report room. " \
                             f"Reply in the thread to continue. (@here)"

                member = report_channel.guild.get_member(author.id)
                if member:
                    if report_channel.permissions_for(member).read_messages:  # someone from staff is testing modbot
                        entry_text = entry_text.replace("@here", "@ here ~ exempted for staff testing")

                if ban_appeal:
                    entry_text = f"**__BAN APPEAL__**\n" + entry_text
                    entry_text = entry_text.replace(author.mention,
                                                    f"{author.mention} ({str(author)}, {author.id})")

                thread_text = f"""\
                I'll relay any of their messages to this 
                channel. 
                   - Any messages you type will be sent
                      to the user. 
                   - To end this chat, type `end` or `done`.
                   - To *not* send a certain message, start the 
                      message with `_`. 
                   - For example, `Hello` would be sent, but 
                      `_What should we do` or bot
                      commands would not be sent.
                
                **Report starts here
                __{' '*70}__**
                \n\n
                """  # invisible character at end of this line to avoid whitespace trimming

                thread_text = dedent(thread_text) + invisible_character  # invis. character breaks dedent
                entry_message: discord.Message = await report_channel.send(entry_text)
                report_thread = await entry_message.create_thread(
                    name=f'{author.name} report {datetime.now().strftime("%Y-%m-%d")}',
                    auto_archive_duration=1440)  # Auto archive in 24 hours
                await report_thread.send(thread_text)

                # Add reaction signifying open room, will remove in close_room() function
                try:
                    await entry_message.add_reaction("❗")
                except discord.Forbidden:
                    pass

                self.bot.db['reports'][author.id] = {
                    "user_id": author.id,
                    "thread_id": report_thread.id,
                    "guild_id": report_thread.guild.id,
                    "mods": [],
                    "not_anonymous": False
                }

                if not ban_appeal:
                    user_text = f">>> {author.mention}: {msg.content}"
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
                await author.send("Sorry, actually I can't send messages to the channel the mods had setup for me "
                                       "anymore. Please tell them to check the permissions on the channel or to run the"
                                       " setup command again.")
                return True

            if not ban_appeal:
                locale: str = self.bot.db['user_localizations'].get(author.id, "")
                if locale == 'ja':
                    desc = "サーバーの管理者に接続しました。また先ほどあなたが送信したメッセージも管理者に送られています。" \
                           "ここで送信されたメッセージや画像は管理者に送られ、管理者からのメッセージもここに届きます。" \
                           "お返事に時間がかかる場合がございますので、ご了承ください。\n\n" \
                           "通報内容の入力が終了したら、`end`または`done`とタイプしてください。"
                elif locale.startswith("es"):
                    desc = "Ahora estás conectado con los moderadores del servidor, y les he enviado tu mensaje " \
                           "anterior. Los moderadores verán los mensajes o imágenes que " \
                           "envíes, y también recibirás mensajes y imágenes de los moderadores. " \
                           "Los moderadores pueden tardar un poco en ver tu reporte, " \
                           "así que ten paciencia. \n\nCuando hayas terminado de hablar " \
                           "con los moderadores, escribe `end` o `done` y el chat se cerrará."
                else:
                    desc = "You are now connected to the moderators of the server, and I've sent your above message. " \
                           "The moderators will see any messages " \
                             "or images you send, and you'll receive messages and images from the mods too." \
                             "It may take a while for the moderators to see your appeal, so please be patient. \n\n" \
                             "When you are done talking to the mods, please type `end` or `done`, and then " \
                             "the chat will close."

                await author.send(embed=discord.Embed(description=desc, color=0x00FF00))
            else:
                locale: str = self.bot.db['user_localizations'].get(author.id, "")
                if locale == 'ja':
                    appeal = "サーバーの管理者に接続しました。またこれによりバンの解除申請が管理者に通知されました。" \
                             "ここで送信されたメッセージや画像は管理者に送られ、管理者からのメッセージもここに届きます。" \
                             "お返事に時間がかかる場合がございますので、ご了承ください。\n\n" \
                             "申請内容の入力が終了したら、`end`または`done`とタイプしてください。"
                elif locale.startswith("es"):
                    appeal = "Ahora estás conectado con los moderadores del servidor, y les he notificado que estás " \
                             "intentando apelar una expulsión. Los moderadores verán los mensajes o imágenes que " \
                             "envíes, y también recibirás mensajes y imágenes de los moderadores. " \
                             "Los moderadores pueden tardar " \
                             "un poco en ver tu apelación, así que ten paciencia. " \
                             "\n\nCuando hayas terminado de hablar " \
                             "con los moderadores, escribe `end` o `done` y el chat se cerrará."
                else:
                    appeal = "You are now connected to the moderators of the server, and I've notified them that " \
                             "you're trying to appeal a ban. The moderators will see any messages " \
                             "or images you send, and you'll receive messages and images from the mods too." \
                             "It may take a while for the moderators to see your appeal, so please be patient. \n\n" \
                             "When you are done talking to the mods, please type `end` or `done`, and then " \
                             "the chat will close."

                await author.send(embed=discord.Embed(description=appeal, color=0x00FF00))
                return entry_message
            return entry_message

        try:
            await open_room()  # maybe this should always be True
        except Exception:
            if author.id in self.bot.db['reports']:
                del self.bot.db['reports'][author.id]
            await self.notify_close_room(report_channel, author.dm_channel, True)
            raise

    """Send message"""
    async def send_message(self,
                           msg: discord.Message,
                           open_report: OpenReport):
        if msg.content:
            for prefix in ['_', ';', '.', ',', '>>', '&', 't!', 't@', '$']:
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
        # this creates a list of moderator IDs
        # whenever a moderator sends a message, it'll check their position in the list and give them a name like
        # "Moderator 1" if they're the first ID in the list
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

    @staticmethod
    async def notify_close_room(source, dest, error):
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
                s1 = f"**{invisible_character}\n\n__{' '*70}__**\n**" \
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
    async def close_room(self, open_report: OpenReport, error):
        await self.notify_close_room(open_report.source, open_report.dest, error)

        # get thread from open_report object
        thread: discord.Thread = self.bot.get_channel(open_report.thread_info['thread_id'])

        # delete report info from database
        if open_report.user.id in self.bot.db['reports']:
            del self.bot.db['reports'][open_report.user.id]

        # archive thread
        if thread:
            await thread.edit(archived=True)

        # remove ❗ reaction from thread parent message if there
        try:
            thread_opening_message = await thread.parent.fetch_message(thread.id)
        except (discord.NotFound, discord.HTTPException):
            pass
        else:
            try:
                await thread_opening_message.remove_reaction("❗", thread.guild.me)
            except (discord.NotFound, discord.HTTPException):
                pass

        # Add time the report ended to prevent users from quickly opening up the room immediately after it closes
        self.bot.recently_in_report_room[open_report.user.id] = discord.utils.utcnow().timestamp()

    @commands.Cog.listener()
    async def on_typing(self, channel, user, _):
        """When a user in a DM channel starts typing, display that in the modbot report channel"""
        await _send_typing_notif(self, channel, user)

    @commands.Cog.listener()
    async def on_thread_update(self, before, after):
        if not before.archived and after.archived:
            if after.archiver_id == self.bot.user.id:
                # I archived it, so do nothing
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
                await self.close_room(OpenReport(thread_info, user, after, user.dm_channel, after), False)

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
            timestamp_of_last_report_end = self.bot.recently_in_report_room.get(msg.author.id, 0)
            time_since_report = discord.utils.utcnow().timestamp() - timestamp_of_last_report_end
            if msg.author in self.bot.recently_in_report_room and time_since_report < report_timeout:
                time_remaining = int(report_timeout - time_since_report)
                return time_remaining

        return 0


async def setup(bot):
    await bot.add_cog(Modbot(bot))
