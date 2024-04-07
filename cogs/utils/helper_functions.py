from datetime import datetime
from typing import Optional, Union

import discord
import traceback
from discord.ext import commands
import os
import sys

here = sys.modules[__name__]
here.bot: Optional[commands.Bot] = None


def setup(bot, loop):
    """This command is run in the setup_hook function in Modbot.py"""
    if here.bot is None:
        here.bot = bot
    else:
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
    async def on_error(self,
                       interaction: discord.Interaction,
                       error: Exception,
                       item: Union[discord.ui.Button, discord.ui.Select, discord.ui.TextInput]):
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


async def edit_thread_tags(thread: discord.Thread, add: list[str] = None, remove: list[str] = None):
    if not add and not remove:
        return
    if not add:
        add = []
    if not remove:
        remove = []

    if not isinstance(thread, discord.Thread):
        raise TypeError("Thread must be a discord.Thread object")

    thread_tags = thread.applied_tags
    available_tags = thread.parent.available_tags

    for to_add_tag in add:
        for tag in available_tags:
            if str(tag.emoji) == to_add_tag:
                thread_tags.append(tag)
                break

    for to_remove_tag in remove:
        for tag in thread_tags:
            if str(tag.emoji) == to_remove_tag:
                thread_tags.remove(tag)
                break

    await thread.edit(archived=False, applied_tags=thread_tags)

