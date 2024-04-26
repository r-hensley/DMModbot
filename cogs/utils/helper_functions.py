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
from sumy.summarizers import luhn, lsa, lex_rank, sum_basic, kl, reduction

here = sys.modules[__name__]
here.bot = None
here.loop = None

SP_SERV_ID = 243838819743432704
JP_SERV_ID = 189571157446492161

_url = re.compile(
    r"""
            # protocol identifier
            (?:https?|ftp)://
            # user:pass authentication
            (?:\S+(?::\S*)?@)?
            (?:
              # IP address exclusion
              # private & local networks
              (?!(?:10|127)(?:\.\d{1,3}){3})
              (?!(?:169\.254|192\.168)(?:\.\d{1,3}){2})
              (?!172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2})
              # IP address dotted notation octets
              # excludes loopback network 0.0.0.0
              # excludes reserved space >= 224.0.0.0
              # excludes network & broacast addresses
              # (first & last IP address of each class)
              (?:[1-9]\d?|1\d\d|2[01]\d|22[0-3])
              (?:\.(?:1?\d{1,2}|2[0-4]\d|25[0-5])){2}
              \.(?:[1-9]\d?|1\d\d|2[0-4]\d|25[0-4])
            |
              # host name
              (?:[a-z\u00a1-\uffff0-9]-*)*[a-z\u00a1-\uffff0-9]+
              # domain name
              (?:\.(?:[a-z\u00a1-\uffff0-9]-*)*[a-z\u00a1-\uffff0-9]+)*
              # TLD identifier
              \.[a-z\u00a1-\uffff]{2,}
              # TLD may end with dot
              \.?
            )
            # port number
            (?::\d{2,5})?
            # resource path
            (?:[/?#]\S*)?
        """, re.VERBOSE | re.I)

_emoji = re.compile(r'<a?(:[A-Za-z0-9_]+:|#|@|@&)!?[0-9]{17,20}>')


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


async def send_error_embed(bot: discord.Client,
                           ctx: Union[commands.Context, discord.Interaction],
                           error: Exception,
                           embed: discord.Embed):
    error = getattr(error, 'original', error)
    try:
        qualified_name = getattr(ctx.command, 'qualified_name', ctx.command.name)
    except AttributeError:  # ctx.command.name is also None
        qualified_name = "Non-command"
    traceback.print_tb(error.__traceback__)
    print(discord.utils.utcnow())
    print(f'Error in {qualified_name}:', file=sys.stderr)
    print(f'{error.__class__.__name__}: {error}', file=sys.stderr)

    exc = ''.join(traceback.format_exception(type(error), error, error.__traceback__, chain=False))
    if ctx.message:
        traceback_text = f'{ctx.message.jump_url}\n```py\n{exc}```'
    elif ctx.channel:
        traceback_text = f'{ctx.channel.mention}\n```py\n{exc}```'
    else:
        traceback_text = f'```py\n{exc}```'

    embed.timestamp = discord.utils.utcnow()
    traceback_logging_channel = int(os.getenv("ERROR_CHANNEL_ID"))
    view = None
    if ctx.message:
        view = RaiView.from_message(ctx.message)
    await bot.get_channel(traceback_logging_channel).send(traceback_text[-2000:], embed=embed, view=view)
    print('')


class RaiView(discord.ui.View):
    """A view that will be used to display errors in the traceback logging channel."""

    async def on_error(self,
                       interaction: discord.Interaction,
                       error: Exception,
                       item: Union[discord.ui.Button, discord.ui.Select, discord.ui.TextInput]):
        """This is called when an error occurs in a view component."""
        e = discord.Embed(title=f'View Component Error ({str(item.type)})', colour=0xcc3366)
        e.add_field(name='Interaction User', value=f"{interaction.user} ({interaction.user.mention})")

        fmt = f'Channel: {interaction.channel} (ID: {interaction.channel.id})'
        if interaction.guild:
            fmt = f'{fmt}\nGuild: {interaction.guild} (ID: {interaction.guild.id})'

        e.add_field(name='Location', value=fmt, inline=False)

        if hasattr(item, "label"):
            e.add_field(name="Item label", value=item.label)

        if interaction.data:
            e.add_field(name="Data", value=f"```{interaction.data}```", inline=False)

        if interaction.extras:
            e.add_field(name="Extras", value=f"```{interaction.extras}```")

        await send_error_embed(interaction.client, interaction, error, e)


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


async def try_add_reaction(msg, emoji):
    """This will try to add a reaction to a message, and if it fails, it will ignore the error."""
    try:
        await msg.add_reaction(emoji)
    except [discord.HTTPException, discord.Forbidden, discord.NotFound]:
        pass


async def deliver_first_report_msg(report_thread: discord.Thread,
                                   ban_appeal,
                                   author: discord.User,
                                   msg: Optional[discord.Message] = None):
    """This will deliver the first message of a report to the report thread from the user,
    and then in the DM channel, add a reaction to the message to indicate that it has been delivered."""
    if not ban_appeal and msg:
        user_text = f">>> {author.mention}: {msg.content}"
        if len(user_text) > 2000:
            await report_thread.send(user_text[:2000])
            await report_thread.send(user_text[2000:])
        else:
            await report_thread.send(user_text)
        await try_add_reaction(msg, "📨")
        await try_add_reaction(msg, "✅")
        if msg.attachments:
            for attachment in msg.attachments:
                await report_thread.send(f">>> {attachment.url}")
        if msg.embeds:
            await report_thread.send(embed=msg.embeds[0])
    if not msg:
        await report_thread.send("NOTE: The user has not sent a message yet.")


async def notify_user_of_report_connection(author: discord.User, ban_appeal):
    if not ban_appeal:
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
    else:
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


async def add_report_to_db(author: discord.User, report_thread: discord.Thread):
    here.bot.db['reports'][author.id] = {
        "user_id": author.id,
        "thread_id": report_thread.id,
        "guild_id": report_thread.guild.id,
        "mods": [],
        "not_anonymous": False,
    }


EXEMPTED_BOT_PREFIXES = ['_', ';', '.', ',', '>', '&', 't!', 't@', '$', '!', '?']


def is_emoji(char):
    EMOJI_MAPPING = (
        # (0x0080, 0x02AF),
        # (0x0300, 0x03FF),
        # (0x0600, 0x06FF),
        # (0x0C00, 0x0C7F),
        # (0x1DC0, 0x1DFF),
        # (0x1E00, 0x1EFF),
        # (0x2000, 0x209F),
        # (0x20D0, 0x214F),
        # (0x2190, 0x23FF),
        # (0x2460, 0x25FF),
        # (0x2600, 0x27EF),
        # (0x2900, 0x2935),
        # (0x2B00, 0x2BFF),
        # (0x2C60, 0x2C7F),
        # (0x2E00, 0x2E7F),
        # (0x3000, 0x303F),
        (0xA490, 0xA4CF),
        (0xE000, 0xF8FF),
        (0xFE00, 0xFE0F),
        (0xFE30, 0xFE4F),
        (0x1F000, 0x1F02F),
        (0x1F0A0, 0x1F0FF),
        (0x1F100, 0x1F64F),
        (0x1F680, 0x1F6FF),
        (0x1F910, 0x1F96B),
        (0x1F980, 0x1F9E0),
    )
    return any(start <= ord(char) <= end for start, end in EMOJI_MAPPING)


def rem_emoji_url(msg):
    if isinstance(msg, discord.Message):
        msg = msg.content
    new_msg = _emoji.sub('', _url.sub('', msg))
    for char in msg:
        if is_emoji(char):
            new_msg = new_msg.replace(char, '').replace('  ', '')
    return new_msg


async def wait_for_further_info_from_op(report_entry_message: discord.Message, desired_chars: int = 150):
    """This will keep doing async wait_for and adding to the message until the message reaches the desired length."""
    user_text, default_text = report_entry_message.content.split(f"\nThe user ")
    default_text = "\nThe user " + default_text
    if not user_text and default_text:
        return

    new_user_text = user_text
    first = True

    while len(new_user_text) < desired_chars:
        try:
            response = await here.bot.wait_for("message",
                                               check=lambda m: m.channel == report_entry_message.channel
                                               and m.author == report_entry_message.author,
                                               timeout=1000)
        except asyncio.TimeoutError:
            break
        else:
            if not response.content.startswith(">>>"):
                continue

            # skip the first message as it's already set above as new_user_text
            if first:
                first = False
                continue

            # delete URLs from the message
            candidate_text = rem_emoji_url(response)
            # check if the text after removing spaces and punctuation no longer has any length
            # use regex
            if not re.search(r'\w', candidate_text):
                continue

            # Delete ">>> <@\d{17,22}>" from beginning of candidate_text
            candidate_text = candidate_text.replace(r'>>> : ', '')

            # check if new_user_text ends with some kind of punctuation
            if new_user_text.endswith(",") or new_user_text.endswith("!") or new_user_text.endswith("?"):
                new_user_text += f" {candidate_text}"
            else:
                new_user_text += f". {candidate_text}"

            # try fetching thread again to get its current status
            # if archived, stop trying to edit the message
            current_thread = report_entry_message.channel.parent.get_thread(report_entry_message.id)
            if current_thread:
                if current_thread.archived:
                    return
            else:
                return

            if new_user_text != user_text:
                if len(new_user_text) > desired_chars:
                    new_content = f"{new_user_text[:desired_chars]} [・・・]\n{default_text}"
                    await report_entry_message.edit(content=new_content)
                    break
                else:
                    new_content = f"{new_user_text}\n{default_text}"
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
        summary = summarize(thread_text, language="english", sentences_count=1)
        if summary:
            summary = str(summary[0]).replace('\n', '. ')
            thread_info['summary'] = summary
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


async def create_report_thread(author: discord.User, msg: discord.Message,
                               report_channel: Union[discord.TextChannel, discord.ForumChannel],
                               ban_appeal: bool):
    entry_text = ""
    if msg:
        if len(msg.content) > 150:
            entry_text = f"{msg.content[:150]} [・・・]\n"
        else:
            entry_text = f"{msg.content}\n"
    entry_text += f"The user {author.mention} has entered the report room. Reply in the thread to continue. (@here)"

    member = report_channel.guild.get_member(author.id)
    if member:
        if report_channel.permissions_for(member).read_messages:  # someone from staff is testing modbot
            entry_text = entry_text.replace("@here", "@ here ~ exempted for staff testing")

    if ban_appeal:
        entry_text = f"**__BAN APPEAL__**\n" + entry_text
        entry_text = entry_text.replace(author.mention,
                                        f"{author.mention} ({str(author)}, {author.id})")

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
    thread_text = add_recent_report_info(thread_text, author.id, report_channel.guild.id)

    thread_name = f'{author.name} ({datetime.now().strftime("%Y-%m-%d")})'
    if isinstance(report_channel, discord.ForumChannel):
        if ban_appeal:
            tags_to_add, _ = make_tags_list_for_forum_post(report_channel, ["🚷", "❗"])
        else:
            tags_to_add, _ = make_tags_list_for_forum_post(report_channel, ["❗"])

        report_thread = (await report_channel.create_thread(name=thread_name,
                                                            content=f"{entry_text}\n{thread_text}",
                                                            applied_tags=tags_to_add)).thread
        
        # error in PyCharm IDE, it wants me to put "await", but that would block the code
        # noinspection PyAsyncCall
        asyncio.create_task(wait_for_further_info_from_op(report_thread.starter_message, 150))
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


async def new_user_role_request_denial(guild: discord.Guild, ban_appeal, author: discord.User, msg: discord.Message,
                                       meta_channel: discord.Thread):
    if ban_appeal:
        return

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
            return

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
            return


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
        if main_or_secondary == 'secondary':
            meta_channel_id = here.bot.db['guilds'][guild.id].get('secondary_meta_channel')
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
    view = RaiView(timeout=180)
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
    account_q_button = discord.ui.Button(label=account_q_str.get(user_locale) or report_str['en'],
                                         style=discord.ButtonStyle.primary, row=2)
    server_q_button = discord.ui.Button(label=server_q_str.get(user_locale) or report_str['en'],
                                        style=discord.ButtonStyle.secondary, row=3)
    cancel_button = discord.ui.Button(label=cancel_str.get(user_locale) or report_str['en'],
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
        first_msg_conf = {"en": "I will send your first message. "
                                "Make sure all the messages you send receive a '📨' reaction.",
                          "es": "Enviaré tu primer mensaje. "
                                "Asegúrate de que todos los mensajes que envíes reciban una reacción '📨'.",
                          "ja": "あなたの最初のメッセージを送信しました。"
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
        await q_msg.edit(content="I did not receive a response from you. Please try to send your "
                                 "message again", view=None)

    view.on_timeout = on_timeout

    await q_msg.edit(view=view)  # add view to message

    return report_button, account_q_button, server_q_button, cancel_button


def get_user_locale(user_id: int) -> str:
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
    




async def send_to_test_channel(*content):
    content = ' '.join([str(i) for i in content])
    channel = here.bot.get_channel(275879535977955330)
    if channel:
        try:
            await channel.send(content)
        except discord.Forbidden:
            print("Failed to send content to test_channel in send_to_test_channel()")
