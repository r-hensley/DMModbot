import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Union

import discord
from discord.ext import commands

from .report_intake import CloseReportView, ReportIntake, card_copy, status_card, trace_flow, trace_flow_error
from .utils.db_utils import get_thread_id_to_thread_info
from .utils import helper_functions as hf
# from cogs.utils.BotUtils import bot_utils as utils

logger = logging.getLogger(__name__)
FOLLOWUP_DELAY = 60

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
        await _safe_typing(report_thread)
        return


async def _safe_typing(channel):
    """Send a typing indicator without allowing typing endpoint failures to interrupt flow."""
    if channel is None:
        return
    try:
        await channel.typing()
    except discord.HTTPException as err:
        if err.status == 429:
            logger.debug("Typing indicator request was rate limited for channel %s", getattr(channel, "id", None))
            return
        raise


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
        self.intakes = {}
        self.opening_reports = set()
        self.closing_reports = set()
        # dict w/ key ID and value of last left report room time
        if not hasattr(self.bot, "recently_in_report_room"):
            self.bot.recently_in_report_room = {}

    async def cog_load(self):
        self.close_view = CloseReportView(self)
        self.bot.add_view(self.close_view)
        trace_flow("cog_loaded")

    def cog_unload(self):
        self.close_view.stop()
        for intake in self.intakes.values():
            intake.view.stop()
        self.intakes.clear()

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
            trace_flow("dm_received")
            if await self.receive_users(msg):
                return

        # sending a message during a report
        # it tries to connect a message to a report and deliver it to the right place (either report room or DM channel)
        open_report = await self.find_current_guild(msg)
        # can be None if the above message was not sent to one of the open report threads in a server: i.e., it's
        # a random unrelated message in a server in a random channel
        if open_report and open_report.thread_info['thread_id'] not in self.closing_reports:
            new_flow = bool(open_report.thread_info.get('dm_card_id'))
            direction = "staff_to_reporter" if msg.guild else "reporter_to_staff"
            if new_flow:
                trace_flow("relay_started", direction=direction)
            try:
                await self.send_message(msg, open_report)
            except Exception as error:
                if new_flow:
                    trace_flow_error("relay_error", error, direction=direction)
                direction = "staff to reporter" if msg.guild else "reporter to staff"
                error.add_note(f"Closing report thread {open_report.thread.id} after relaying a message "
                               f"from {direction} failed.")
                try:
                    await self.end_report(open_report, error=True)
                except Exception as cleanup_error:
                    error.add_note(f"Closing the report also failed: {type(cleanup_error).__name__}: {cleanup_error}")
                    logger.exception("Could not close report thread %s after relay failure", open_report.thread.id)
                raise

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.guild_id is None and interaction.type in (
            discord.InteractionType.component, discord.InteractionType.modal_submit,
        ):
            trace_flow("dm_interaction_received", kind=interaction.type.name)

    async def receive_users(self, msg: discord.Message) -> bool:
        user_id = msg.author.id
        while intake := self.intakes.get(user_id):
            intake.trace("pending_dm_received")
            try:
                if await intake.add_message(msg):
                    return True
            except Exception as error:
                trace_flow_error("draft_message_error", error, intake.attempt)
                raise

        if user_id in self.bot.db['reports']:
            return False
        if user_id in self.opening_reports:
            trace_flow("dm_during_open")
            return True

        if time_remaining := self.check_if_recently_finished_report(msg):
            trace_flow("dm_during_cooldown")
            await msg.author.send(
                f"You've recently left a report room. Please wait {time_remaining} more seconds before "
                "joining again. A new report is only needed if you still need help."
            )
            return True

        intake = ReportIntake(self, msg)
        intake.trace("first_dm_received")
        self.intakes[user_id] = intake
        async with intake.lock:
            try:
                await intake.welcome()
            except Exception as error:
                trace_flow_error("welcome_error", error, intake.attempt)
                await intake.finish()
                raise
        return True

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
            current_user: Optional[discord.User] = self.bot.get_user(thread_info["user_id"])
            if not current_user:
                try:
                    current_user = await self.bot.fetch_user(thread_info["user_id"])
                except (discord.NotFound, discord.HTTPException, discord.Forbidden):
                    current_user = None

            if not current_user:
                await msg.channel.send("I couldn't find the user connected to this report anymore, so I am closing "
                                       "this report room.")
                # delete the entry out of bot.db['reports']
                del self.bot.db['reports'][thread_info["user_id"]]
                await hf.dump_json()
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
                await hf.dump_json()
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

    async def start_ban_appeal_room(self, author: discord.User, guild: discord.Guild,
                                    appeal_text: str, report_room_type: str):
        if author.id in self.opening_reports or author.id in self.bot.db['reports']:
            await author.send("You already have a report or appeal opening. Continue in that conversation.")
            return
        self.opening_reports.add(author.id)
        try:
            await self._start_ban_appeal_room(author, guild, appeal_text, report_room_type)
        finally:
            self.opening_reports.discard(author.id)

    async def _start_ban_appeal_room(self, author: discord.User, guild: discord.Guild,
                                    appeal_text: str, report_room_type: str):
        try:
            report_channel, meta_channel = await hf.get_report_variables(guild, report_room_type, author)
        except hf.EndEarly:
            return
        # Check if the bot has the permissions to send messages in the report channel and create threads.
        try:
            await hf.check_bot_perms(report_channel, meta_channel, guild, author)
        except hf.EndEarly:
            return
        async def open_room():
            if not author.dm_channel:
                await author.create_dm()
            if isinstance(report_channel, discord.TextChannel):
                await _safe_typing(report_channel)

            await _safe_typing(author.dm_channel)
            await asyncio.sleep(1)

            try:
                report_thread = await hf.create_report_thread(author, appeal_text,
                                                              report_channel, ban_appeal=True)

                # try to capture the modlog that rai will post, delete it, and repost it ourselves to the thread
                await hf.repost_rai_modlog(report_thread)

                # Send divider to report room splitting information from bot above and actual report messages below
                invisible_character = "⠀"  # replacement of space to avoid whitespace trimming
                vertical_space = f"**Report starts here\n__{' ' * 70}__**\n\n\n{invisible_character}"
                await report_thread.send(vertical_space)

                # add info about user to self.bot.db['reports']
                await hf.add_report_to_db(author, report_thread, report_room_type)

                # send first message, notify user in DMs that the message successfully sent
                await hf.deliver_ban_appeal_msg_to_thread(report_thread, author, appeal_text)

            except discord.Forbidden:
                await author.send("Sorry, actually I can't send messages to the channel the mods had setup for me "
                                    "anymore. Please tell them to check the permissions on the channel or to run the"
                                    " setup command again.")
                return

            # Send user a message explaining that the connection to the room has been made and explaining roughly
            # how to use the room. The message can be in English, Spanish, or Japanese depending on the user's locale.
            await hf.forward_ban_appeal_msg_to_dm(author.dm_channel, appeal_text)
            await hf.notify_user_of_ban_appeal_connection(author)

        try:
            await open_room()
        except Exception as error:
            error.add_note(f"Opening a ban appeal room in guild {guild.id} failed.")
            try:
                if author.id in self.bot.db['reports']:
                    del self.bot.db['reports'][author.id]
                    await hf.dump_json()
                await self.notify_end_thread(meta_channel, author.dm_channel, True)
            except Exception as cleanup_error:
                error.add_note(f"Ban appeal cleanup also failed: {type(cleanup_error).__name__}: {cleanup_error}")
                logger.exception("Could not clean up failed ban appeal in guild %s", guild.id)
            raise

    async def start_report_room(self, author, guild, messages, draft, report_room_type,
                                *, report_kind=None, anonymous=False, dm_card_id=None, flow_attempt=None) -> bool:
        stage = "resolve_destination"
        try:
            if report_kind == "voice_access":
                config = self.bot.db["guilds"][guild.id]
                if (guild.id != hf.SP_SERV_ID or report_room_type != "secondary"
                        or not config.get("secondary_channel") or config["secondary_channel"] == config["channel"]):
                    trace_flow("preflight_rejected", flow_attempt, stage=stage)
                    return False
            report_channel, meta_channel = await hf.get_report_variables(guild, report_room_type, author)
            stage = "permissions"
            await hf.check_bot_perms(report_channel, meta_channel, guild, author, anonymous=anonymous)
            stage = "server_roles"
            await hf.deny_new_user_role_request(guild, author, draft, meta_channel, anonymous=anonymous)
        except hf.EndEarly:
            trace_flow("preflight_rejected", flow_attempt, stage=stage)
            return False
        except Exception as error:
            trace_flow_error("preflight_error", error, flow_attempt, stage=stage)
            raise

        report_thread = None
        stage = "create_thread"
        try:
            report_thread = await hf.create_report_thread(
                author, draft, report_channel, voice_report=report_room_type == 'voice' or report_kind == "voice_access",
                anonymous=anonymous,
            )
            trace_flow("thread_created", flow_attempt)
            stage = "deliver_draft"
            if not anonymous:
                await hf.repost_rai_modlog(report_thread)
            await report_thread.send("**Report starts here**")
            await hf.deliver_report_draft(report_thread, author, messages, draft, anonymous=anonymous)
            trace_flow("draft_delivered", flow_attempt)
            stage = "save_report"
            await hf.add_report_to_db(author, report_thread, report_room_type,
                                      report_kind=report_kind, anonymous=anonymous, dm_card_id=dm_card_id,
                                      followup_due_at=discord.utils.utcnow().timestamp() + FOLLOWUP_DELAY)
        except Exception as error:
            trace_flow_error("open_report_error", error, flow_attempt, stage=stage)
            if report_thread is not None:
                self.bot.db['reports'].pop(author.id, None)
                try:
                    await hf.close_thread(report_thread)
                    await hf.dump_json()
                except Exception as cleanup_error:
                    trace_flow_error("open_cleanup_error", cleanup_error, flow_attempt)
                    logger.exception("Could not close incomplete report thread %s", report_thread.id)
            raise
        trace_flow("report_opened", flow_attempt)
        return True

    async def close_dm_report(self, user, channel, report):
        if self.bot.db['reports'].get(user.id) is not report:
            return
        thread = self.bot.get_channel(report['thread_id'])
        if thread is None:
            try:
                thread = await self.bot.fetch_channel(report['thread_id'])
            except discord.NotFound:
                if self.bot.db['reports'].get(user.id) is report:
                    self.bot.db['reports'].pop(user.id, None)
                    await self.update_dm_report_card(channel, user, report, error=True, notify=True)
                    await hf.dump_json()
                return
        await self.end_report(OpenReport(report, user, thread, channel, thread), error=False)

    async def send_message(self, msg: discord.Message, open_report: OpenReport):
        thread_info = open_report.thread_info
        new_flow = bool(thread_info.get('dm_card_id'))
        direction = "staff_to_reporter" if isinstance(open_report.dest, discord.DMChannel) else "reporter_to_staff"
        # ignore messages starting with _ or other bot prefixes, also ignore all bot messages
        if not await hf.check_if_valid_msg(msg):
            if new_flow:
                trace_flow("relay_ignored", direction=direction)
            return

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
            if new_flow:
                trace_flow("relay_consumed", direction=direction)
            return

        from_reporter = isinstance(open_report.source, discord.DMChannel)
        followup_changed = False
        followup_ready = False
        if from_reporter:
            if (not thread_info.get('sent_followup_notice')
                    and not thread_info.get('followup_answered', bool(thread_info['mods']))):
                now = discord.utils.utcnow().timestamp()
                previous_due = thread_info.get('followup_due_at')
                followup_ready = previous_due is not None and now >= previous_due
                thread_info['followup_due_at'] = now + FOLLOWUP_DELAY
                followup_changed = True
        elif not thread_info.get('followup_answered'):
            thread_info['followup_answered'] = True
            thread_info.pop('followup_due_at', None)
            followup_changed = True

        try:
            anonymous = open_report.dest == open_report.thread and thread_info.get('anonymous_reporter', False)
            await hf.forward_report_media(open_report.dest, msg, anonymous=anonymous)
            for part in (cont, cont2):
                if part:
                    if anonymous:
                        await open_report.dest.send(part, allowed_mentions=discord.AllowedMentions.none(),
                                                    suppress_embeds=True)
                    else:
                        await open_report.dest.send(part)

        except discord.Forbidden as error:
            if new_flow:
                trace_flow_error("relay_forbidden", error, direction=direction)
            if open_report.dest == open_report.user.dm_channel:
                await msg.channel.send("I couldn't send a message to the user (maybe they blocked me or left "
                                       "the server). I will close the chat.")

            elif open_report.dest == open_report.thread:
                await msg.channel.send("I couldn't send your message to the mods. Maybe they've locked me out "
                                       "of the report channel. I will close this chat.")

            await self.end_report(open_report, False)

        else:
            if new_flow:
                trace_flow("relay_delivered", direction=direction)
            await hf.try_add_reaction(msg, "📨")

            if followup_ready:
                await self.send_followup_notice(open_report)
            elif followup_changed:
                await hf.dump_json()

    async def send_followup_notice(self, open_report):
        user_id = open_report.user.id
        report = open_report.thread_info

        def still_waiting():
            return (self.bot.db['reports'].get(user_id) is report
                    and report['thread_id'] not in self.closing_reports
                    and not report.get('followup_answered', bool(report['mods'])))

        if not still_waiting() or report.get('sent_followup_notice'):
            return
        # Persist before sending so the same report cannot receive a second reminder.
        report['sent_followup_notice'] = True
        report.pop('followup_due_at', None)
        await hf.dump_json()
        if not still_waiting():
            return

        copy = card_copy(hf.get_user_locale(user_id))
        description = copy['followup_wait']
        if report.get('report_kind') == 'report_user':
            description += "\n\n" + copy['followup_evidence']
        try:
            await open_report.source.send(embed=discord.Embed(
                title=copy['followup_title'], description=description, color=discord.Color.blurple(),
            ))
        except discord.HTTPException as error:
            trace_flow_error("followup_error", error)
        else:
            trace_flow("followup_sent")

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
                guild_config = self.bot.db['guilds'].get(thread_info['guild_id'], {})
                permanent_non_anonymous_mods: list[int] = guild_config.get('permanent_non_anonymous_mods', [])
                is_permanently_non_anonymous = msg.author.id in permanent_non_anonymous_mods

                if is_permanently_non_anonymous:
                    notified_mods: list[int] = thread_info.setdefault('permanent_non_anonymous_notified_mods', [])
                    if msg.author.id not in notified_mods:
                        notified_mods.append(msg.author.id)
                        await msg.reply("Reminder: you have permanent non-anonymous mode enabled in this server, "
                                        "so your identity is shown in this and all other report threads.\n"
                                        "-# To toggle this setting, use `/permanent_non_anonymous`.")

                if thread_info.setdefault('not_anonymous', False) or is_permanently_non_anonymous:
                    cont = f" {msg.author.mention}: "
                else:
                    cont = f">>> **Moderator {thread_info['mods'].index(msg.author.id) + 1}**: "
            else:
                cont = f">>> {hf.reporter_label(msg.author, thread_info.get('anonymous_reporter', False))}: "

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
        targets = []
        if source is not None:
            targets.append((source, is_source_thread))
        if dest is not None and dest is not source:
            targets.append((dest, is_dest_thread))
        if error:
            for target, _ in targets:
                try:
                    await target.send("WARNING: There's been some kind of error. I will close the room. Please try again.")
                except (discord.Forbidden, discord.NotFound, discord.HTTPException, AttributeError):
                    pass
        else:
            invisible_character = "â €"  # To avoid whitespace trimming
            invisible_character = "\u2800"
            for index, (target, is_thread) in enumerate(targets):
                try:
                    spacing = "\n\n" if index == 0 else "\n\n\n"
                    content = f"**{invisible_character}{spacing}__{' ' * 70}__**\n**" \
                              f"Thank you, I have closed the room." \
                              f"{' Messages in this thread will no longer be sent to the user' if is_thread else ''}**"
                    await target.send(content)
                except (discord.Forbidden, discord.NotFound, discord.HTTPException, AttributeError):
                    pass
    async def update_dm_report_card(self, channel, user, report, *, error, notify=False):
        if not report.get('dm_card_id'):
            return
        if channel is None:
            trace_flow("closure_dm_unavailable")
            return
        copy = card_copy(hf.get_user_locale(user.id))
        view = status_card(copy['interrupted' if error else 'closed'])
        try:
            await channel.get_partial_message(report['dm_card_id']).edit(view=view)
        except discord.NotFound:
            trace_flow("closure_card_missing")
        except discord.HTTPException as card_error:
            trace_flow_error("closure_card_error", card_error)
            logger.warning("Could not update the closed report card %s", report['dm_card_id'])
        if notify:
            divider = f"**\u2800\n\n\n__{' ' * 70}__**\n"
            notice = f"{divider}**{copy['closed_notice']}**"
            if error:
                notice = f"{copy['interrupted']}\n{notice}"
            try:
                await channel.send(notice)
            except discord.HTTPException as notice_error:
                trace_flow_error("closure_notice_error", notice_error)
                logger.warning("Could not send closure notice for report card %s", report['dm_card_id'])
            else:
                trace_flow("closure_notice_sent")

    async def end_report(self, open_report: OpenReport, error, finish=False, notify=True):
        user_id = open_report.user.id
        report = open_report.thread_info
        thread_id = report['thread_id']
        if self.bot.db['reports'].get(user_id) is not report or thread_id in self.closing_reports:
            return

        self.closing_reports.add(thread_id)
        new_flow = bool(report.get('dm_card_id'))
        if new_flow:
            trace_flow("report_closing", interrupted=bool(error))
        try:
            thread = open_report.thread
            await hf.close_thread(thread, finish)
            if self.bot.db['reports'].get(user_id) is report:
                del self.bot.db['reports'][user_id]
            self.bot.db.get('scheduled_resolutions', {}).pop(thread_id, None)
            self.bot.recently_in_report_room[user_id] = discord.utils.utcnow().timestamp()
            try:
                if report.get('dm_card_id'):
                    await self.update_dm_report_card(open_report.user.dm_channel, open_report.user, report,
                                                     error=error, notify=notify)
                    if notify:
                        await self.notify_end_thread(thread, None, error)
                elif notify:
                    await self.notify_end_thread(open_report.source, open_report.dest, error)
                if not report.get('anonymous_reporter'):
                    await hf.log_record_of_report(thread, open_report.user)
            finally:
                await hf.dump_json()
            if new_flow:
                trace_flow("report_closed")
        except Exception as close_error:
            if new_flow:
                trace_flow_error("report_close_error", close_error)
            raise
        finally:
            self.closing_reports.discard(thread_id)

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
                    try:
                        user = await self.bot.fetch_user(thread_info['user_id'])
                    except (discord.NotFound, discord.HTTPException, discord.Forbidden):
                        user = None

                if user is None:
                    await after.send("Failed to get the user who created this report.")
                    del self.bot.db['reports'][thread_info["user_id"]]
                    await hf.dump_json()
                    return

                source = user.dm_channel
                if source is None:
                    try:
                        source = await user.create_dm()
                    except (discord.NotFound, discord.HTTPException, discord.Forbidden):
                        source = after

                if self.bot.db['reports'].get(user.id) is not thread_info or thread_id in self.closing_reports:
                    return
                reason = "Report thread archived while the report was active"
                detail = f"{reason}. Thread {thread_id}, guild {after.guild.id}."
                logger.warning("%s", detail)
                try:
                    await self.end_report(OpenReport(thread_info, user, after, source, after), True)
                finally:
                    try:
                        await self.bot.traceback_store.record_notice("on_thread_update", reason, detail)
                    except Exception:
                        logger.exception("Could not archive the closure notice for report thread %s", thread_id)

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

        currently_in_settingup = msg.author.id in self.intakes
        currently_in_report_room = msg.author.id in self.bot.db['reports']
        if not currently_in_settingup and not currently_in_report_room:
            timestamp_of_last_report_end = getattr(self.bot, "recently_in_report_room", {}).get(msg.author.id, 0)
            time_since_report = discord.utils.utcnow().timestamp() - timestamp_of_last_report_end
            if msg.author.id in self.bot.recently_in_report_room and time_since_report < report_timeout:
                time_remaining = int(report_timeout - time_since_report)
                return time_remaining

        return 0


async def setup(bot):
    await bot.add_cog(Modbot(bot))
