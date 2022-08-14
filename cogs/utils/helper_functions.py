from datetime import datetime
import discord
import traceback
from discord.ext import commands
import os
import sys

async def send_error_embed(bot, ctx, error):
    print(discord.utils.utcnow())
    error = getattr(error, 'original', error)
    qualified_name = getattr(ctx.command, 'qualified_name', ctx.command.name)
    print(f'Error in {qualified_name}:', file=sys.stderr)
    traceback.print_tb(error.__traceback__)
    print(f'{error.__class__.__name__}: {error}', file=sys.stderr)

    if isinstance(ctx, commands.Context):
        e = discord.Embed(title='Command Error', colour=0xcc3366)
        e.add_field(name='Name', value=qualified_name)
        e.add_field(name='Command', value=ctx.message.content[:1000])
        e.add_field(name='Author', value=f'{ctx.author} (ID: {ctx.author.id})')
    elif isinstance(ctx, discord.Interaction):
        e = discord.Embed(title='App Command Error', colour=0xcc3366)
        e.add_field(name='Name', value=qualified_name)
        e.add_field(name='Author', value=ctx.user)
    else:
        e = discord.Embed(title="Error of unknown type", colour=0xcc3366)

    fmt = f'Channel: {ctx.channel} (ID: {ctx.channel.id})'
    if ctx.guild:
        fmt = f'{fmt}\nGuild: {ctx.guild} (ID: {ctx.guild.id})'

    e.add_field(name='Location', value=fmt, inline=False)

    exc = ''.join(traceback.format_exception(type(error), error, error.__traceback__, chain=False))
    if isinstance(ctx, commands.Context):
        traceback_text = f'{ctx.message.jump_url}\n```py\n{exc}```'
    elif isinstance(ctx, discord.Interaction):
        traceback_text = f'{ctx.channel.mention}\n```py\n{exc}```'
    else:
        traceback_text = f'```py\n{exc}```'

    e.timestamp = discord.utils.utcnow()
    TRACEBACK_LOGGING_CHANNEL = int(os.getenv("ERROR_CHANNEL_ID"))
    await bot.get_channel(TRACEBACK_LOGGING_CHANNEL).send(traceback_text[-2000:], embed=e)
    print('')
