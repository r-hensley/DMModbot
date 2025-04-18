import asyncio
import re
from datetime import datetime
from textwrap import dedent
from typing import Optional, Union

import aiohttp
import discord
import traceback
from discord.ext import commands
import os
import sys

from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers import lsa

from cogs.utils.BotUtils import bot_utils as utils

here = sys.modules[__name__]
here.bot = None
here.loop = None

SP_SERV_ID = 243838819743432704
JP_SERV_ID = 189571157446492161

def setup(bot: commands.Bot, loop):
    """This command is run in the setup_hook function in Modbot.py"""
    if here.bot is None:
        here.bot = bot
    else:
        pass

    if here.loop is None:
        here.loop = loop
    else:
        pass


class EndEarly(Exception):
    """This exception is raised for example when the user types 'end' or 'close' in a report thread."""
    pass


def make_tags_list_for_forum_post(forum: discord.ForumChannel, add: list[str] = None, remove: list[str] = None):
    """This will make a list of tags to add and remove based on the add and remove lists."""
    if not add and not remove:
        return
    if not add:
        add = []
    if not remove:
        remove = []

    available_tags = forum.available_tags
    to_add = []
    to_remove = []

    for to_add_tag in add:
        for tag in available_tags:
            if str(tag.emoji) == to_add_tag:
                to_add.append(tag)
                break

    for to_remove_tag in remove:
        for tag in available_tags:
            if str(tag.emoji) == to_remove_tag:
                to_remove.append(tag)
                break

    return to_add, to_remove


async def edit_thread_tags(thread: discord.Thread, add: list[str] = None, remove: list[str] = None):
    """This will edit the tags of a thread based on the add and remove lists."""
    applied_tags = thread.applied_tags
    to_add, to_remove = make_tags_list_for_forum_post(thread.parent, add, remove)

    for tag in to_add:
        if tag in applied_tags:
            continue
        applied_tags.append(tag)

    for tag in to_remove:
        if tag not in applied_tags:
            continue
        applied_tags.remove(tag)

    await thread.edit(archived=False, applied_tags=applied_tags)


async def _pre_repost_rai_modlog(report_thread: discord.Thread):
    """This will repost the modlog that Rai posts in the report thread."""
    modlog_placeholder = await report_thread.send(".")
    rai = report_thread.guild.get_member(270366726737231884)
    if rai in report_thread.guild.members:
        # try to capture the modlog that will be posted by Rai, and repost it yourself
        try:
            rai_msg = await here.bot.wait_for("message",
                                              timeout=10.0,
                                              check=lambda m:
                                              m.channel == report_thread and m.author.id == rai.id and m.embeds)
        except asyncio.TimeoutError:
            await modlog_placeholder.delete()
        else:
            # delete the captured modlog
            try:
                await rai_msg.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass

            # repost it
            else:
                await modlog_placeholder.edit(content=rai_msg.content, embed=rai_msg.embeds[0])


async def repost_rai_modlog(report_thread: discord.Thread):
    """This will create a task to call the _pre_repost_rai_modlog function."""
    # error in PyCharm IDE, it wants me to put "await", but that would block the code
    # noinspection PyAsyncCall
    asyncio.create_task(_pre_repost_rai_modlog(report_thread))


def partition_text(text: str, length: int):
    return list(text[0+i:length+i] for i in range(0, len(text), length))


async def try_add_reaction(msg, emoji):
    """This will try to add a reaction to a message, and if it fails, it will ignore the error."""
    try:
        await msg.add_reaction(emoji)
    except (discord.HTTPException, discord.Forbidden, discord.NotFound):
        pass


async def deliver_ban_appeal_msg_to_thread(report_thread: discord.Thread, 
                                           author: discord.User,
                                           appeal_text: str):
    section_prefix = f">>> {author.mention}: "
    partitioned_text = partition_text(appeal_text, 2000 - len(section_prefix))
    for section in partitioned_text:
        await report_thread.send(f"{section_prefix}{section}")


async def forward_ban_appeal_msg_to_dm(dm_channel: discord.DMChannel, appeal_text: str):
    await dm_channel.send("### Your Appeal:")
    section_prefix = f">>> "
    partitioned_text = partition_text(appeal_text, 2000 - len(section_prefix))
    for section in partitioned_text:
        await dm_channel.send(f"{section_prefix}{section}")


async def deliver_first_report_msg_to_thread(
        report_thread: discord.Thread,
        author: discord.User,
        msg: Optional[discord.Message] = None):
    """This will deliver the first message of a report to the report thread from the user,
    and then in the DM channel, add a reaction to the message to indicate that it has been delivered."""
    if not msg:
        await report_thread.send("NOTE: The user has not sent a message yet.")
        return
    section_prefix = f">>> {author.mention}: "
    partitioned_text = partition_text(msg.content, 2000 - len(section_prefix))
    for section in partitioned_text:
        await report_thread.send(f"{section_prefix}{section}")
    await try_add_reaction(msg, "📨")
    await try_add_reaction(msg, "✅")
    if msg.attachments:
        for attachment in msg.attachments:
            await report_thread.send(f">>> {attachment.url}")
    if msg.embeds:
        await report_thread.send(embed=msg.embeds[0])


async def notify_user_of_ban_appeal_connection(author: discord.User):
    locale: str = here.bot.db['user_localizations'].get(author.id, "")
    if locale == 'ja':
        appeal = "サーバーの管理者に接続しました。またこれによりバンの解除申請が管理者に通知されました。" \
                    "ここで送信されたメッセージや画像は管理者に送られ、管理者からのメッセージもここに届きます。" \
                    "お返事に時間がかかる場合がございますので、ご了承ください。\n\n" \
                    "申請が終了したら、`end`または`close`とタイプしてください。"
    elif locale.startswith("es"):
        appeal = "Ahora estás conectado con los moderadores del servidor, y les he notificado que estás " \
                    "intentando apelar una expulsión. Los moderadores verán los mensajes o imágenes que " \
                    "envíes, y también recibirás mensajes y imágenes de los moderadores. " \
                    "Los moderadores pueden tardar " \
                    "un poco en ver tu apelación, así que ten paciencia. " \
                    "\n\nCuando hayas terminado de hablar " \
                    "con los moderadores, escribe `end` o `close` y el chat se cerrará."
    else:
        appeal = "You are now connected to the moderators of the server, and I've notified them that " \
                    "you're trying to appeal a ban. The moderators will see any messages " \
                    "or images you send, and you'll receive messages and images from the mods too. " \
                    "It may take a while for the moderators to see your appeal, so please be patient. \n\n" \
                    "When you are done talking to the mods, please type `end` or `close`, and then " \
                    "the chat will close."

    await author.send(embed=discord.Embed(description=appeal, color=0x00FF00))


async def notify_user_of_report_connection(author: discord.User):
    locale: str = here.bot.db['user_localizations'].get(author.id, "")
    if locale == 'ja':
        desc = "サーバーの管理者に接続しました。またあなたが最初に送信したメッセージも管理者に送られています。" \
                "ここで送信されたメッセージや画像は管理者に送られ、管理者からのメッセージもここに届きます。" \
                "お返事に時間がかかる場合がございますので、ご了承ください。\n\n" \
                "管理者への通報が終了したら、`end`または`close`とタイプしてください。"
    elif locale.startswith("es"):
        desc = "Ahora estás conectado con los moderadores del servidor, y les he enviado tu primer " \
                "mensaje. Los moderadores verán los mensajes o imágenes que " \
                "envíes, y también recibirás mensajes y imágenes de los moderadores. " \
                "Los moderadores pueden tardar un poco en ver tu reporte, " \
                "así que ten paciencia. \n\nCuando hayas terminado de hablar " \
                "con los moderadores, escribe `end` o `close` y el chat se cerrará."
    else:
        desc = "You are now connected to the moderators of the server, and I've sent your first message. " \
                "The moderators will see any messages " \
                "or images you send, and you'll receive messages and images from the mods too. " \
                "It may take a while for the moderators to see your appeal, so please be patient. \n\n" \
                "When you are done talking to the mods, please type `end` or `close`, and then " \
                "the chat will close."

    await author.send(embed=discord.Embed(description=desc, color=0x00FF00))


async def add_report_to_db(author: discord.User, report_thread: discord.Thread):
    here.bot.db['reports'][author.id] = {
        "user_id": author.id,
        "thread_id": report_thread.id,
        "guild_id": report_thread.guild.id,
        "mods": [],
        "not_anonymous": False,
    }


EXEMPTED_BOT_PREFIXES = ['_', ';', '.', ',', '>', '&', 't!', 't@', '$', '!', '?']


async def wait_for_further_info_from_op(report_entry_message: discord.Message,
                                        desired_chars: int = 150,
                                        ban_appeal: bool = False):
    """This will keep doing async wait_for and adding to the message until the message reaches the desired length."""
    debug = False  # enable debug prints
    text = report_entry_message.content.split(f"\nThe user ")
    if len(text) == 1:
        original_user_text, default_text = "", text[0]
    elif len(text) == 2:
        original_user_text, default_text = text
    else:
        raise ValueError("Unknown format of report_entry_message content")

    if not default_text:
        return
    default_text = "\nThe user " + default_text
    if ban_appeal:
        preface_text = original_user_text.split("\n", 1)[0] + "\n"
        original_user_text = "**"  # there will be no other text if it's a ban appeal
        
        # The user will not have sent a message yet, but "BAN APPEAL" will be in the "user_text" variable
        skip_next_message = False
    else:
        preface_text = ""
        
        # The "user_text" variable will already contain the first message sent by the user
        # Therefore, when it arrives in the report window, don't add it again
        skip_next_message = bool(original_user_text)

    original_user_text = original_user_text.replace("**", "")
    new_user_text = original_user_text
    
    await send_to_test_channel(f"```{preface_text}```", "\n", f"```{original_user_text}```", "\n",
                               skip_next_message, debug=debug)

    while len(new_user_text) < desired_chars:
        try:
            await send_to_test_channel("Waiting for info from OP", debug=debug)
            response = await here.bot.wait_for("message",
                                               check=lambda m: m.channel == report_entry_message.channel
                                               and m.author == report_entry_message.author,
                                               timeout=1000)
        except asyncio.TimeoutError:
            await send_to_test_channel("Timeout", debug=debug)
            break
        else:
            await send_to_test_channel(response.content, debug=debug)
            if not response.content.startswith(">>>"):
                await send_to_test_channel(f"Not a reply", debug=debug)
                continue

            # skip the first message if it's already set above as new_user_text
            if skip_next_message:
                skip_next_message = False
                await send_to_test_channel("Skipping next message", debug=debug)
                continue

            # delete URLs from the message
            candidate_text = utils.rem_emoji_url(response)
            
            # check if the text after removing spaces and punctuation no longer has any length
            # use regex
            if not re.search(r'\w', candidate_text):
                await send_to_test_channel("No word characters in candidate_text", debug=debug)
                continue

            # Delete ">>> <@\d{17,22}>" from beginning of candidate_text
            candidate_text = candidate_text.replace(r'>>> : ', '')

            # check if new_user_text ends with some kind of punctuation
            if not new_user_text:
                new_user_text = candidate_text
            elif new_user_text[-1] in ",.!?":
                new_user_text = new_user_text + f" {candidate_text}"
            else:
                new_user_text = new_user_text + f". {candidate_text}"

            # try fetching thread again to get its current status
            # if archived, stop trying to edit the message
            current_thread = report_entry_message.channel.parent.get_thread(report_entry_message.id)
            if current_thread:
                if current_thread.archived:
                    await send_to_test_channel("Thread is archived", debug=debug)
                    return
            else:
                await send_to_test_channel("Thread is None", debug=debug)
                return

            if new_user_text != original_user_text:
                if len(new_user_text) > desired_chars:
                    new_content = f"{preface_text}**{new_user_text[:desired_chars]}** [・・・]\n{default_text}"
                    await report_entry_message.edit(content=new_content)
                    await send_to_test_channel(f"MAX_LENGTH_BREAK: {len(new_user_text)}: {new_user_text}", debug=debug)
                    break
                else:
                    new_content = f"{preface_text}**{new_user_text}**\n{default_text}"
                    await report_entry_message.edit(content=new_content)


async def log_record_of_report(thread: discord.Thread, author: discord.User):
    """This will log a record of a report in the database under
    bot.db['recent_reports'][thread.guild.id][author.id]"""
    guild_id = thread.guild.id
    author_id = author.id
    if guild_id not in here.bot.db['recent_reports']:
        here.bot.db['recent_reports'][guild_id] = {}
    if author_id not in here.bot.db['recent_reports'][guild_id]:
        here.bot.db['recent_reports'][guild_id][author_id] = []
    
    # thread_info: {'thread_id': int, 'timestamp': int, 'summary': str}
    thread_info = {'thread_id': thread.id, 'timestamp': int(datetime.utcnow().timestamp())}
    
    thread_text = ""
    async for m in thread.history(limit=10, oldest_first=True):
        if m.content.startswith(">>>"):
            # delete ">>> <@\d{17,22}>: " from the beginning of the message
            thread_text += m.content[m.content.find(":") + 2:] + '. '
    thread_text = thread_text[:500]
    
    if not thread_text:
        pass
    elif len(thread_text) < 250:
        thread_info['summary'] = thread_text.replace('\n', '. ')
    else:
        if hasattr(here.bot, "eden"):
            if not here.bot.eden:
                pass
            else:
                summary = await eden_summarize(thread_text, language="en", sentences_count=1)
                summary = summary.replace('\n', '. ')
                thread_info['summary'] = summary
    
    here.bot.db['recent_reports'][guild_id][author_id].append(thread_info)
    if len(here.bot.db['recent_reports'][guild_id][author_id]) > 5:
        here.bot.db['recent_reports'][guild_id][author_id].pop(0)
        
        
def add_recent_report_info(thread_text: str, author_id: int, guild_id: int) -> str:
    """This will add a list of recent reports from the user to the thread text.
    Params:
    - thread_text: str: The text of the thread to add the recent reports to.
    - author_id: int: The ID of the user to get the recent reports from.
    - guild_id: int: The ID of the guild to get the recent reports from.
    Returns: str: The thread text with the recent reports added."""
    try:
        past_reports: list[dict] = here.bot.db['recent_reports'][guild_id][author_id]
    except KeyError:
        return thread_text
    
    if not past_reports:
        return thread_text
    else:
        thread_text += "\n\n**__Recent reports:__**\n"
    for thread_info in past_reports:
        # thread_info: {'thread_id': int, 'timestamp': int, 'summary': str}
        # add a single-line bullet point containing very shortly just the thread date and summary
        message_link = f"<https://discord.com/channels/{guild_id}/{thread_info['thread_id']}>"
        date_timestamp: int = thread_info['timestamp']
        # format using discord time string, <t:TIMESTAMP:f>
        thread_text += f"• [<t:{date_timestamp}:f> (link)]({message_link})"
        if thread_info.get('summary', ''):
            thread_text += f" - {thread_info['summary']}"
        thread_text += "\n"
    
    return thread_text

def escape_username(username: str):
    return username.replace("_", "\_")

def build_report_short_description(author: discord.User, title: str, is_staff_testing = False, is_ban_appeal = False):
    entry_text = f"{title}\n"
    entry_text += f"The user {author.mention} has entered the report room. Reply in the thread to continue. (@here)"

    if is_staff_testing:
        entry_text = entry_text.replace("@here", "@ here ~ exempted for staff testing")

    if is_ban_appeal:
        entry_text = f"*(Ban Appeal)*\n" + entry_text
        entry_text = entry_text.replace(author.mention,
                                        f"{author.mention} ({escape_username(str(author))}, {author.id})")
    
    return entry_text

def build_report_thread_header(author: discord.User, guild_id: int):
    thread_text = rf"""
            I'll relay any of their messages to this 
            channel. 
                \- Any messages you type will be sent
                    to the user. 
                \- To end this chat, type `end` or `close`.
                \- Typing `finish` will close the chat and 
                    also add a ✅ emoji to the thread, marking 
                    it as "Resolved".
                \- To *not* send a certain message, start the 
                    message with `_`. 
                \- For example, `Hello` would be sent, but 
                    `_What should we do` or bot
                    commands would not be sent.
                    Currently exempted bot prefixes:
                    `{'`   `'.join(EXEMPTED_BOT_PREFIXES)}`
            """
    thread_text = dedent(thread_text)
    thread_text = add_recent_report_info(thread_text, author.id, guild_id)
    return thread_text

async def create_report_thread(author: discord.User, report_text: str,
                               report_channel: Union[discord.TextChannel, discord.ForumChannel],
                               ban_appeal: bool):

    if len(report_text) > 150:
        report_title = f"**{report_text[:150]}** [・・・]\n"
    else:
        report_title = f"**{report_text}**\n"

    member = report_channel.guild.get_member(author.id)
    is_staff_testing = member and report_channel.permissions_for(member).read_messages  # someone from staff is testing modbot
    entry_text = build_report_short_description(author, report_title, is_staff_testing, ban_appeal)
    thread_text = build_report_thread_header(author, report_channel.guild.id)
    thread_name = f'{author.name} ({datetime.now().strftime("%Y-%m-%d")})'

    if isinstance(report_channel, discord.ForumChannel):
        if ban_appeal:
            tags_to_add, _ = make_tags_list_for_forum_post(report_channel, ["🚷", "❗"])
        else:
            tags_to_add, _ = make_tags_list_for_forum_post(report_channel, ["❗"])

        report_thread = (await report_channel.create_thread(name=thread_name,
                                                            content=f"{entry_text}\n{thread_text}",
                                                            applied_tags=tags_to_add)).thread

        if not report_thread.starter_message:
            try:
                starter_message = await report_thread.fetch_message(report_thread.id)
            except (discord.NotFound, discord.HTTPException):
                starter_message = None
        else:
            starter_message = report_thread.starter_message

        if starter_message:
            # error in PyCharm IDE, it wants me to put "await", but that would block the code
            # noinspection PyAsyncCall
            utils.asyncio_task(wait_for_further_info_from_op, report_thread.starter_message, 150, ban_appeal)
    else:
        entry_message: Optional[discord.Message] = await report_channel.send(entry_text)
        await try_add_reaction(entry_message, "❗")
        report_thread = await entry_message.create_thread(name=thread_name)  # Auto archive in 24 hours
        await report_thread.send(thread_text)

    return report_thread


async def close_thread(thread: discord.Thread, finish=False):
    """This will close a thread, and if finish is True, it will also mark it as resolved."""
    # if parent is a text channel, remove ❗ reaction from thread parent message if there
    if isinstance(thread.parent, discord.TextChannel):
        try:
            thread_opening_message = await thread.parent.fetch_message(thread.id)
        except (discord.NotFound, discord.HTTPException):
            pass
        else:
            try:
                await thread_opening_message.remove_reaction("❗", thread.guild.me)
                if finish:
                    await try_add_reaction(thread_opening_message, "✅")
            except (discord.NotFound, discord.HTTPException):
                pass

    # otherwise, if parent is a forum channel, look for tag that has "open" in name, replace it with "closed" tag
    elif isinstance(thread.parent, discord.ForumChannel):
        if finish:
            await edit_thread_tags(thread, add=["✅"], remove=["❗", "⏹️"])
        else:
            await edit_thread_tags(thread, add=["⏹️"], remove=["❗"])

    # archive thread
    if finish and thread:
        await thread.edit(archived=True)


async def deny_new_user_role_request(guild: discord.Guild, author: discord.User, msg: discord.Message,
                                       meta_channel: discord.Thread):
    # #### SPECIAL STUFF FOR JP SERVER ####
    # Turn away new users asking for a role
    if guild.id == JP_SERV_ID:
        # report_room = guild.get_channel(697862475579785216)
        jho = guild.get_channel(189571157446492161)
        member = guild.get_member(author.id)
        if guild.get_role(249695630606336000) in member.roles:  # new user role
            await member.send(f"In order to use the voice channels or this report bot, you need a language "
                              f"tag first. Please state your native language in {jho.mention}.\n"
                              f"ボイスチャットかこのボットを使うにはいずれかの言語ロールが必要です。 "
                              f"{jho.mention} にて母語を教えて下さい。")
            text = f"{str(author.mention)} came to me with the following message:" \
                   f"```{msg.content}```" \
                   f"I assumed they were asking for language tag, so I told them to state their " \
                   f"native language in JHO and blocked their request to open the report room."
            await meta_channel.send(embed=discord.Embed(description=text, color=0xFF0000))
            raise EndEarly

    # #### SPECIAL STUFF FOR SP SERVER ####
    # Turn away new users asking for a role
    if guild.id == SP_SERV_ID:
        # report_room = guild.get_channel(713314015014551573)
        getting_started = guild.get_channel(243838819743432704)
        member = guild.get_member(author.id)
        found_role = False  # will be True if the user has one of the roles in native_language_roles
        for role_id in [243853718758359040, 243854128424550401, 247020385730691073]:
            role = guild.get_role(role_id)
            if role in member.roles:
                found_role = True
                break

        if not found_role:  # new user role
            await member.send(f"To access the server, please read {getting_started.mention}.\n"
                              f"Para acceder al servidor, por favor, lee {getting_started.mention}.")
            text = f"{str(author.mention)} came to me with the following message:" \
                   f"```{msg.content}```" \
                   f"I assumed they were asking how to access the server, so I told them to get a native " \
                   f"language in the newcomers channels and blocked their request to open the report room."
            await meta_channel.send(author.mention, embed=discord.Embed(description=text, color=0xFF0000))
            raise EndEarly


async def get_report_variables(guild, main_or_secondary, author):
    guild_config = here.bot.db['guilds'][guild.id]
    if main_or_secondary == 'main':
        target_id = guild_config['channel']

    else:  # main_or_secondary == 'secondary'
        target_id = guild_config.get('secondary_channel', guild_config.get('channel'))

    report_channel: Union[discord.Thread, discord.TextChannel] = here.bot.get_channel(target_id)
    if isinstance(report_channel, discord.ForumChannel):
        # a pinned post in forum where I can send info messages
        meta_channel_id = here.bot.db['guilds'][guild.id].get('meta_channel')
        if 'secondary_channel' in guild_config:
            if main_or_secondary == 'secondary':
                meta_channel_id = guild_config.get('secondary_meta_channel')
            if not meta_channel_id:
                await author.send("The report room for this server is not properly setup. Please directly message "
                                  "the mods. (I can't find the ID for the channel to send info messages in)")
                raise EndEarly
        
        meta_channel = report_channel.get_thread(meta_channel_id)
        if not meta_channel:
            await author.send("The report room for this server is not properly setup. Please directly message "
                              "the mods. (I can't find the channel to send info messages in their forum channel)")
            raise EndEarly

    else:
        meta_channel = report_channel

    return report_channel, meta_channel


async def check_bot_perms(report_channel, meta_channel, guild, author):
    """Check if the bot has the permissions to send messages in the report channel and create threads."""
    perms = report_channel.permissions_for(guild.me)
    if not perms.send_messages or not perms.create_public_threads:
        try:
            await meta_channel.send(f"WARNING: {author.mention} tried to join the report room, but in order "
                                    f"to open a report here, I need the `Create Public Threads` permission "
                                    f"in this channel. Please give me that permission and tell the user "
                                    f"to try again.")
        except discord.Forbidden:
            pass
        await author.send("The report room for this server is not properly setup. Please directly message "
                          "the mods. (I don't have permission to send messages in the report room.)")
        return


async def check_if_valid_msg(msg):
    """Returns 'True' is the message should be sent, or 'False' if it should be ignored"""
    # ignore messages in guilds that start with a bot prefix
    if msg.content and msg.guild:
        for prefix in EXEMPTED_BOT_PREFIXES:
            if msg.content.startswith(prefix):
                await try_add_reaction(msg, '🔇')
                return False

    # ignore messages from bots
    if msg.author.bot:
        # don't attach 🔇 to the messages delivered by Modbot to the report room from the user
        if msg.author == msg.guild.me:
            if msg.content.startswith('>>> '):
                return False

        # for all other bot messages, attach 🔇
        await try_add_reaction(msg, '🔇')
        return False

    # ignore messages that are not of type "default" or "reply"
    if msg.type not in (discord.MessageType.default, discord.MessageType.reply):
        await try_add_reaction(msg, '🔇')
        return False

    return True


async def setup_confirm_guild_buttons(guild: discord.Guild, author: discord.User):
    txt = (f"Hello, you are trying to start a support ticket/report with "
           f"the mods of {guild.name}.\n\n"
           "**Please push one of the below buttons.**")
    view = utils.RaiView(timeout=180)
    report_str = {'en': "I want to report a user",
                  'es': "Quiero reportar a un usuario",
                  'ja': "他のユーザーを通報したい"}
    account_q_str = {'en': "I have a question about my account",
                     'es': "Tengo una pregunta sobre mi cuenta",
                     'ja': "自分のアカウントについて質問がある"}
    server_q_str = {'en': "I have a question about the server",
                    'es': "Tengo una pregunta sobre el servidor",
                    'ja': "サーバーについて質問がある"}
    cancel_str = {"en": "Nevermind, cancel this menu.",
                  "es": "Olvídalo, cancela este menú",
                  'ja': "なんでもない、このメニューを閉じてください"}
    user_locale = get_user_locale(author.id)
    report_button = discord.ui.Button(label=report_str.get(user_locale) or report_str['en'],
                                      style=discord.ButtonStyle.primary, row=1)
    account_q_button = discord.ui.Button(label=account_q_str.get(user_locale) or account_q_str['en'],
                                         style=discord.ButtonStyle.primary, row=2)
    server_q_button = discord.ui.Button(label=server_q_str.get(user_locale) or server_q_str['en'],
                                        style=discord.ButtonStyle.secondary, row=3)
    cancel_button = discord.ui.Button(label=cancel_str.get(user_locale) or cancel_str['en'],
                                      style=discord.ButtonStyle.red, row=4)

    if not author.dm_channel:
        try:
            await author.create_dm()
        except discord.Forbidden:
            return None, None
    q_msg = await author.dm_channel.send(txt)

    # delete original message if user pushes a button
    async def button_callback1(button_interaction: discord.Interaction):
        locale = button_interaction.locale
        here.bot.db['user_localizations'][author.id] = str(locale)
        await q_msg.delete()
        first_msg_conf = {"en": "I will try to send your first message. "
                                "Make sure all the messages you send receive a '📨' reaction.",
                          "es": "Intentaré enviar tu primer mensaje. "
                                "Asegúrate de que todos los mensajes que envíes reciban una reacción '📨'.",
                          "ja": "あなたの最初のメッセージを送信してみます。"
                                "送信するすべてのメッセージが '📨' のリアクションが付くことを確認してください。"}
        conf_txt = first_msg_conf.get(str(locale)[:2], first_msg_conf['en'])
        await button_interaction.response.send_message(conf_txt, ephemeral=True)

    async def button_callback2(button_interaction: discord.Interaction):
        here.bot.db['user_localizations'][author.id] = str(button_interaction.locale)
        await q_msg.delete()
        await button_interaction.response.send_message("Canceling report",
                                                       ephemeral=True)

    report_button.callback = account_q_button.callback = server_q_button.callback = button_callback1
    cancel_button.callback = button_callback2
    view.add_item(report_button)
    view.add_item(account_q_button)
    view.add_item(server_q_button)
    view.add_item(cancel_button)

    async def on_timeout():
        try:
            await q_msg.edit(content="I did not receive a response from you. Please try to send your "
                                     "message again", view=None)
        except discord.NotFound:
            pass

    view.on_timeout = on_timeout

    await q_msg.edit(view=view)  # add view to message

    return report_button, account_q_button, server_q_button, cancel_button


def get_user_locale(user_id: int) -> str:
    """Returns the user's locale from the database, defaulting to 'en'."""
    return here.bot.db.get('user_localizations', {}).get(user_id, 'en')[:2]


def is_thread_in_a_report_channel(thread: discord.Thread) -> bool:
    """Returns True if the thread is in the main or secondary report channel of the guild."""
    if not isinstance(thread, discord.Thread):
        return False
    report_channel = here.bot.db['guilds'][thread.guild.id].get('channel')
    secondary_report_channel = here.bot.db['guilds'][thread.guild.id].get('secondary_channel')
    return thread.parent.id in [report_channel, secondary_report_channel]


def summarize(text, language="english", sentences_count=1):
    parser = PlaintextParser.from_string(text, Tokenizer(language))
    # luhn, edmundson, lsa, lex_rank, sum_basic, kl, reduction
    # summarizers = [luhn.LuhnSummarizer(),
    #                lsa.LsaSummarizer(), lex_rank.LexRankSummarizer(),
    #                sum_basic.SumBasicSummarizer(), kl.KLSummarizer(),
    #                reduction.ReductionSummarizer()]
    summarizer = lsa.LsaSummarizer()
    summary = summarizer(parser.document, sentences_count)

    return summary


async def eden_summarize(text, language="en", sentences_count=1) -> str:
    url = "https://api.edenai.run/v2/text/summarize"
    payload = {
        "response_as_dict": True,
        "attributes_as_list": False,
        "show_original_response": False,
        "output_sentences": sentences_count,
        "providers": "cohere",
        "text": text,
        "language": language,
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": "Bearer " + os.getenv("EDEN_KEY"),
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as response:
            response = await response.json()
            
    if 'cohere' in response:
        response = response['cohere']
        if response['status'] == 'success':
            return response['result']
    
    # if the response is not successful, raise an error
    raise Exception(f"EdenAI API returned an error: {response}")
    

async def send_to_test_channel(*content, debug=True):
    if not debug:
        return
    content = ' '.join([str(i) for i in content])
    channel = here.bot.get_channel(275879535977955330)
    if channel:
        try:
            await channel.send(content)
        except discord.Forbidden:
            print("Failed to send content to test_channel in send_to_test_channel()")


# # create a command to run asyncio.create_task(),
# # and then add "add_done_callback" to it that calls exceptions from send_error_embed()
# def asyncio_task(func):
#     task = asyncio.create_task(func)
#     task.add_done_callback(asyncio_task_done_callback)
#
#
# def asyncio_task_done_callback(task):
#     print(f"Task {task.get_coro().__qualname__} done.")
#     if task.exception():
#         print("Error")
#         # Create a new task for the asynchronous function
#         asyncio.create_task(send_error_embed(here.bot, task.get_coro().__qualname__, task.exception()))
#     else:
#         print(f"Task {task.get_coro().__qualname__} completed successfully.")
# create a command to run asyncio.create_task(),
# and then add "add_done_callback" to it that calls exceptions from send_error_embed()