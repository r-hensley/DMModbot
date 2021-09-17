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

dir_path = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
RYRY = 202995638860906496
SPAM_CH = 275879535977955330
REPORT_TIMEOUT = 30

#              database structure
# {
#     "prefix": {},
#     "insetup": [USER1_ID, USER2_ID],
#     "inreportroom": {GUILD_ID: USER_ID, GUILD_ID: USER_ID, ...},
#     "guilds": {
#         "123446036178059265": {
#             "channel": 123459535977955330,
#             "currentuser": null,
#             "waitinglist": []
#         },
#         "123538819743432704": {
#             "channel": 12344015014551573,
#             "currentuser": null,
#             "waitinglist": []
#         }
#     },
#     "modrole": {}
# }


def is_admin(ctx):
    if not ctx.guild:
        return
    mod_role = ctx.guild.get_role(ctx.bot.db['modrole'].get(str(ctx.guild.id), None))
    return mod_role in ctx.author.roles or ctx.channel.permissions_for(ctx.author).administrator


class Modbot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_result = None
        self.recently_in_report_room = {}  # dict w/ key ID and value of last left report room time

    @commands.Cog.listener()
    async def on_command(self, ctx):
        print(f"Running {ctx.command.name}")

    @commands.Cog.listener()
    async def on_typing(self, channel, user, _):
        config = self.bot.db['guilds']
        for guild in config:
            if user.id == config[guild]['currentuser'] and type(channel) == discord.DMChannel:
                report_room = self.bot.get_channel(config[guild]['channel'])
                await report_room.trigger_typing()
                return

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        msg = f"""__New guild__
        **Name:** {guild.name}
        **Owner:** {guild.owner.mention} ({guild.owner.name}#{guild.owner.discriminator}))
        **Members:** {guild.member_count}
        **Channels:** {len(guild.text_channels)} text / {len(guild.voice_channels)} voice"""

        await self.bot.get_user(202995638860906496).send(msg)
        await self.bot.get_user(202995638860906496).send("Channels: \n" +
                                                         '\n'.join([channel.name for channel in guild.channels]))

    # main code is here
    @commands.Cog.listener()
    async def on_message(self, msg):
        if msg.author.bot:
            return

        if self.bot.db['pause']:
            if msg.author.id == RYRY and msg.content != "_pause":
                return

        """PM Bot"""
        async def pm_modbot():
            if not isinstance(msg.channel, discord.DMChannel) and not isinstance(msg.channel, discord.TextChannel):
                return  # because of new threads
            if isinstance(msg.channel, discord.DMChannel):  # in a PM
                # a user wants to be removed from waiting list
                if msg.content.casefold() == 'cancel':
                    for guild in self.bot.db['guilds']:
                        if msg.author.id in self.bot.db['guilds'][guild]['waitinglist']:
                            self.bot.db['guilds'][guild]['waitinglist'].remove(msg.author.id)
                            await msg.author.send("I've removed you from the waiting list.")
                            return
                    await msg.author.send("Canceled report")
                    return

                # starting a report, comes here if the user is not in server_select or in a report room already
                if msg.author.id not in self.bot.db['insetup'] + list(self.bot.db['inreportroom'].values()):
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
                        self.bot.db['insetup'].append(msg.author.id)
                        guild: discord.Guild = await self.server_select(msg)
                        self.bot.db['insetup'].remove(msg.author.id)
                    except Exception:
                        self.bot.db['insetup'].remove(msg.author.id)
                        await msg.author.send("WARNING: There's been an error. Setup will not continue.")
                        raise

                    try:
                        if guild:
                            await self.start_report_room(msg, guild)  # this should enter them into the report room
                        return  # if it worked
                    except Exception:
                        del(self.bot.db['inreportroom'][str(guild.id)])
                        await msg.author.send("WARNING: There's been an error. Setup will not continue.")
                        raise

            # sending a message during a report
            # this next function returns either five values or five "None" values
            # it tries to find if a user messaged somewhere, which report room connection they're part of
            config, current_user, report_room, source, dest = await self.find_current_guild(msg)
            if config:  # basically, if it's not None
                if not dest:  # config sometimes wasn't None but dest was None
                    await self.bot.get_channel(554572239836545074).send(f"{config}, {current_user}, {report_room},"
                                                                        f"{source}, {dest}")
                try:
                    await self.send_message(msg, config, current_user, report_room, source, dest)
                except Exception:
                    await self.close_room(config, source, dest, report_room.guild, True)
                    raise
        await pm_modbot()

    # for finding out which report session a certain message belongs to, None if not part of anything
    # we should only be here if a user is for sure in the report room
    async def find_current_guild(self, msg):
        guild_to_user_dict = self.bot.db['inreportroom']
        user_to_guild_dict = {j: i for i, j in guild_to_user_dict.items()}
        if msg.guild:  # guild --> DM
            if str(msg.guild.id) not in self.bot.db['guilds']:
                return None, None, None, None, None  # a message in a guild not registered for a report room
            config = self.bot.db['guilds'][str(msg.guild.id)]
            if msg.channel.id != config['channel']:
                return None, None, None, None, None  # a message in a guild, but outside report room
            if str(msg.guild.id) not in guild_to_user_dict:
                return None, None, None, None, None  # there's no active report in this guild

            # now for sure you're messaging in the report room of a guild with an active report happening

            current_user = self.bot.get_user(guild_to_user_dict[str(msg.guild.id)])

            source = report_room = self.bot.get_channel(config['channel'])
            dest = current_user.dm_channel
            if not dest:
                dest = await current_user.create_dm()
                if not dest:
                    return None, None, None, None, None  # can't create a DM with user
            return config, current_user, report_room, source, dest

        elif isinstance(msg.channel, discord.DMChannel):  # DM --> guild
            if msg.author.id not in user_to_guild_dict:
                return None, None, None, None, None  # it's in a PM, but that user isn't in any report rooms

            source = msg.author.dm_channel
            if not source:
                source = await msg.author.create_dm()
                if not source:
                    return None, None, None, None, None  # can't create a DM with user

            guild_id: str = user_to_guild_dict[msg.author.id]
            config = self.bot.db['guilds'][guild_id]
            dest = report_room = self.bot.get_channel(config['channel'])
            current_user = msg.author
            return config, current_user, report_room, source, dest

    #
    # for first entering a user into the report room
    async def server_select(self, msg):
        shared_guilds = sorted([g for g in self.bot.guilds if msg.author in g.members], key=lambda x: x.name)

        guild = None
        for g in self.bot.db['guilds']:
            if msg.author.id in self.bot.db['guilds'][g]['waitinglist']:
                guild = self.bot.get_guild(int(g))
                if not self.bot.db['guilds'][g]['currentuser']:
                    self.bot.db['guilds'][g]['waitinglist'].remove(msg.author.id)
                break

        if not guild:
            if len(shared_guilds) == 0:
                await msg.channel.send("I couldn't find any common guilds between us. Frankly, I don't know how you're "
                                       "messaging me. Have a nice day.")
                return
            elif len(shared_guilds) == 1:
                if str(shared_guilds[0].id) in self.bot.db['guilds']:
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
                                    if str(reaction) in "✅❌":
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

        if str(guild.id) not in self.bot.db['guilds']:
            return

        return guild

    async def start_report_room(self, msg, guild):
        config = self.bot.db['guilds'][str(guild.id)]
        report_channel = self.bot.get_channel(config['channel'])

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

        # ####### IF SOMEONE IN THE ROOM ###########
        if config['currentuser']:
            if msg.author.id in config['waitinglist']:
                await msg.channel.send(
                    "The report room is not open yet. You are still on the waiting list. If it is urgent, "
                    "please message a mod directly.")

            elif config['currentuser'] != msg.author.id:
                config['waitinglist'].append(msg.author.id)
                await msg.channel.send(
                    "There is currently someone else in the report room. You've been added to the waiting list. "
                    "You'll be messaged when the room opens up.")
                m = await report_channel.send(f"NOTIFICATION: User {msg.author.mention} has tried to join the report "
                                              f"room, but there is currently someone in it. Your options are:\n"
                                              f"1) Type `end` or `done` to finish the current report.\n"
                                              f"2) Type `_setup` to reset the room completely (if there's a bug).\n"
                                              f"3) Type `_waitinglist` to view the waiting list or `_clear` "
                                              f"to clear it.")
                await m.add_reaction('🔇')

            if msg.author.id in self.bot.db['insetup']:
                self.bot.db['insetup'].remove(msg.author.id)
            return

        # ##### START THE ROOM #######
        config['currentuser'] = msg.author.id
        self.bot.db['inreportroom'][str(guild.id)] = msg.author.id

        async def open_room():
            await report_channel.trigger_typing()
            await msg.author.dm_channel.trigger_typing()
            await asyncio.sleep(3)
            try:
                entry_text = f"@here The user {msg.author.mention} has entered the report room. I'll relay any of " \
                       f"their messages to this channel. Any messages you type will be sent to them.\n\nTo end this " \
                       f"chat, type `end` or `done`.\n\nTo *not* send a certain message, start the message with `_`. " \
                       f"For example, `Hello` would be sent and `_What should we do`/bot commands would not be sent." \
                       f"\n**Report starts here\n__{' '*70}__**\n\n\n"
                await report_channel.send(entry_text)
                user_text = f">>> {msg.author.mention}: {msg.content}"
                if len(user_text) > 2000:
                    await report_channel.send(user_text[:2000])
                    await report_channel.send(user_text[2000:])
                else:
                    await report_channel.send(user_text)
                await msg.add_reaction('📨')
                await msg.add_reaction('✅')
                if msg.attachments:
                    for attachment in msg.attachments:
                        await report_channel.send(f">>> {attachment.url}")
                if msg.embeds:
                    await report_channel.send(embed=msg.embeds[0])

            except discord.Forbidden:
                await msg.channel.send("Sorry, actually I can't send messages to the channel the mods had setup for me "
                                       "anymore. Please tell them to check the permissions on the channel or to run the"
                                       " setup command again.")
                return True

            await msg.channel.send("You are now connected to the report room. Any messages you send will be relayed "
                                   "there, and you'll receive messages from the mods. Also, I've sent your above"
                                   " message.\n\nWhen you are done talking to the mods, please type `end` or `done` "
                                   "to close the chat.")
            return True

        try:
            await open_room()  # maybe this should always be True
        except Exception:
            await self.close_room(config, msg.channel, report_channel, guild, True)
            raise

    """Send message"""
    async def send_message(self, msg, config, current_user, report_room, source, dest):
        if msg.content:
            for prefix in ['_', ';', '.', ',', '>>', '&']:
                if msg.content.startswith(prefix):  # messages starting with _ or other bot prefixes
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
        if msg.author.id not in config['mods']:
            config['mods'].append(msg.author.id)

        if msg.content:
            if msg.content.casefold() in ['end', 'done']:
                await self.close_room(config, source, dest, report_room.guild, False)
                return
            if isinstance(dest, discord.DMChannel):
                cont = f">>> **Moderator {config['mods'].index(msg.author.id) + 1}:** "
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
                    await dest.send(embed=embed)

            if msg.attachments:
                for attachment in msg.attachments:
                    await dest.send(f">>> {attachment.url}")

            if cont:
                try:
                    await dest.send(cont)
                except discord.Forbidden:
                    await self.close_room(config, source, dest, report_room.guild, True)

            if cont2:
                try:
                    await dest.send(cont2)
                except discord.Forbidden:
                    await self.close_room(config, source, dest, report_room.guild, True)

        except discord.Forbidden:
            if dest == current_user.dm_channel:
                await msg.channel.send("I couldn't send a message to the user (maybe they blocked me). "
                                       "I have closed the chat.")

            elif dest == report_room:
                await msg.channel.send("I couldn't send your message to the mods. Maybe they've locked me out "
                                       "of the report channel. I have closed this chat.")
            await self.close_room(config, source, dest, report_room.guild, False)

    # for when the room is to be closed and the database reset
    # the error argument tells whether the room is being closed normally or after an error
    # source is the DM channel, dest is the report room
    async def close_room(self, config, source, dest, guild, error):
        if not error:
            try:
                await source.send(f"**⠀\n⠀\n⠀\n__{' '*70}__**\n**Thank you, I have closed the room.**")
                await dest.send(f"**⠀\n⠀\n⠀\n__{' '*70}__**\n**Thank you, I have closed the room.**")
            except discord.Forbidden:
                pass
        else:
            try:
                await source.send("WARNING: There's been some kind of error. I will close the room. Please try again.")
                await dest.send("WARNING: There's been some kind of error. I will close the room. Please try again.")
            except discord.Forbidden:
                pass

        if str(guild.id) in self.bot.db['inreportroom']:
            del(self.bot.db['inreportroom'][str(guild.id)])
        config['mods'] = []
        config['currentuser'] = None

        for u in config['waitinglist']:
            user = self.bot.get_user(int(u))
            if not user:
                config['waitinglist'].remove(u)
                continue

            try:
                await user.send("The report room has opened up. Please try messaging again, or type `cancel` to "
                                "remove yourself from the list.")
            except discord.Forbidden:
                report_room = self.bot.get_channel(config["channel"])
                await report_room.send(f"I tried to message {user.name} to tell them the report room opened, but "
                                       f"I couldn't send them a message. I've removed them from the waiting list.")

        if hasattr(source, "recipient"):
            user = source.recipient
        else:
            user = dest.recipient
        self.bot.recently_in_report_room[user] = time.time()

    #
    # ############ OTHER GENERAL COMMANDS #################
    #

    @commands.command()
    async def invite(self, ctx):
        """Get an link to invite this bot to your server"""
        link = "https://discordapp.com/oauth2/authorize?client_id=713245294657273856&scope=bot&permissions=18496"
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
    async def waitinglist(self, ctx):
        """View the waiting list"""
        if str(ctx.guild.id) not in self.bot.db['guilds']:
            return
        config = self.bot.db['guilds'][str(ctx.guild.id)]
        users = []
        for u in config['waitinglist']:
            user = self.bot.get_user(u)
            if not user:
                config['waitinglist'].remove(u)
                continue
            users.append(user)
        await ctx.send(f"The current users on the waiting list are: {', '.join([u.mention for u in users])}")
        await self.dump_json(ctx)

    @commands.command()
    @commands.check(is_admin)
    async def clear(self, ctx):
        """Clears the waiting list"""
        if str(ctx.guild.id) not in self.bot.db['guilds']:
            return
        for user in self.bot.db['guilds'][str(ctx.guild.id)]['waitinglist']:
            if user in self.bot.db['insetup']:
                self.bot.db['insetup'].remove(str(user))
        self.bot.db['guilds'][str(ctx.guild.id)]['waitinglist'] = []
        await ctx.send("I've cleared the waiting list.")
        await self.dump_json(ctx)

    @commands.command()
    @commands.check(is_admin)
    async def setup(self, ctx):
        """Sets the current channel as the report room, or resets the report module"""
        if str(ctx.guild.id) in self.bot.db['guilds']:
            for user in self.bot.db['guilds'][str(ctx.guild.id)]['waitinglist']:
                if str(user) in self.bot.db['insetup']:
                    del(self.bot.db['insetup'][str(user)])
        if str(ctx.guild.id) in self.bot.db['inreportroom']:
            del(self.bot.db['inreportroom'][str(ctx.guild.id)])
        self.bot.db['guilds'][str(ctx.guild.id)] = {'channel': ctx.channel.id,
                                                    'currentuser': None,
                                                    'waitinglist': [],
                                                    'mods': []}
        await ctx.send(f"I've set the report channel as this channel. Now if someone messages me I'll deliver "
                       f"their messages here.")
        await self.dump_json(ctx)

    @commands.command()
    @commands.check(is_admin)
    async def setmodrole(self, ctx, *, role_name):
        """Set the mod role for your server.  Type the exact name of the role like `;setmodrole Mods`. \
                To remove the mod role, type `;setmodrole none`."""
        if role_name.casefold() == "none":
            del self.bot.db['modrole'][str(ctx.guild.id)]
            await ctx.send("Removed mod role setting for this server")
            return
        mod_role = discord.utils.find(lambda role: role.name == role_name, ctx.guild.roles)
        if not mod_role:
            await ctx.send("The role with that name was not found")
            return None
        self.bot.db['modrole'][str(ctx.guild.id)] = mod_role.id
        await ctx.send(f"Set the mod role to {mod_role.name} ({mod_role.id})")
        await self.dump_json(ctx)

    # ########### OWNER COMMANDS ####################

    @commands.command(hidden=True)
    @commands.is_owner()
    async def reload(self, ctx, *, cog: str):
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
        try:
            self.bot.reload_extension(f'cogs.{cog}')
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
        shutil.copy(f'{dir_path}/modbot_3.json', f'{dir_path}/modbot_4.json')
        shutil.copy(f'{dir_path}/modbot_2.json', f'{dir_path}/modbot_3.json')
        shutil.copy(f'{dir_path}/modbot.json', f'{dir_path}/modbot_2.json')
        with open(f'{dir_path}/modbot_temp.json', 'w') as write_file:
            json.dump(db_copy, write_file, indent=4)
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
        t = f"prefix: {self.bot.db['prefix']}\nmodrole: {self.bot.db['modrole']}\npause: {self.bot.db['pause']}\n" \
            f"insetup: {self.bot.db['insetup']}\ninreportroom: {self.bot.db['inreportroom']}\n"
        for guild in self.bot.db['guilds']:
            t += f"{guild}: {self.bot.db['guilds'][guild]}\n"
        await ctx.send(t)


def setup(bot):
    bot.add_cog(Modbot(bot))
