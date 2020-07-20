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

dir_path = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
RYRY = 202995638860906496

# {
#     "prefix": {},
#     "inpms": [],
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

    @commands.Cog.listener()
    async def on_command(self, ctx):
        print(f"Running {ctx.command.name}")

    @commands.Cog.listener()
    async def on_typing(self, channel, user, when):
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
        # for channel in guild.text_channels:
        #     try:
        #         invite = await channel.create_invite(max_uses=1, reason="For bot owner Ryry013#9234")
        #         msg += f"\n{invite.url}"
        #         break
        #     except discord.HTTPException:
        #         pass
        await self.bot.get_user(202995638860906496).send(msg)
        await self.bot.get_user(202995638860906496).send("Channels: \n" +
                                                         '\n'.join([channel.name for channel in guild.channels]))

        return
        msg_text = "Thanks for inviting me!  See a first-time setup guide here: " \
                   "https://github.com/ryry013/Rai/wiki/First-time-setup"
        if guild.system_channel:
            if guild.system_channel.permissions_for(guild.me).send_messages:
                await guild.system_channel.send(msg_text)
                return
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                await channel.send(msg_text)
                return

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
            # starting a report
            if not msg.guild and msg.author.id not in self.bot.db['inpms']:  # user is not in any rooms
                try:
                    self.bot.db['inpms'].append(msg.author.id)
                    config = await self.modbot_entry(msg)  # the main code for entering the user
                    return  # if it worked
                except Exception:
                    self.bot.db['inpms'].remove(msg.author.id)
                    await msg.author.send("WARNING: There's been an error. Setup will not continue.")
                    raise

            # a user wants to be removed from waiting list
            if not msg.guild and msg.content.casefold() == 'cancel':
                for guild in self.bot.db['guilds']:
                    if msg.author.id in self.bot.db['guilds'][guild]['waitinglist']:
                        self.bot.db['guilds'][guild]['waitinglist'].remove(msg.author.id)
                        await msg.author.send("I've removed you from the waiting list.")
                return

            # sending a message during a report
            # this next function returns either five values or five "None" values
            # it tries to find if a user messaged somewhere, which report room connection they're part of
            config, current_user, report_room, source, dest = self.find_current_guild(msg)
            if config:  # basically, if it's not None
                if not dest:  # me trying to fix the weird bug from this morning, config wasn't None but dest was None
                    await self.bot.get_channel(554572239836545074).send(f"{config}, {current_user}, {report_room},"
                                                                        f"{source}, {dest}")
                try:
                    await self.send_message(msg, config, current_user, report_room, source, dest)
                except Exception:
                    await source.send("WARNING: There's been an error.")
                    await dest.send("WARNING: There's been an error.")
                    await self.close_room(config, source, dest)
                    raise
        await pm_modbot()

    """Send message"""
    async def send_message(self, msg, config, current_user, report_room, source, dest):
        if msg.content:
            if msg.content[0] in "_;.,":  # messages starting with _ or other bot prefixes
                await msg.add_reaction('🔇')
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
                await self.close_room(config, source, dest)
                return
            if dest == msg.author.dm_channel:
                cont = f">>> "
                if len(config['mods']) >= 2:
                    cont += f"**Moderator {config['mods'].index(msg.author.id) + 1}:** "
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
            if cont and len(msg.embeds) == 1:
                await dest.send(cont, embed=msg.embeds[0])
            elif cont and not msg.embeds:
                await dest.send(cont)

            if len(msg.embeds) > 1:
                for embed in msg.embeds:
                    await dest.send(embed=embed)

            if msg.attachments:
                for attachment in msg.attachments:
                    await dest.send(f">>> {attachment.url}")

            if cont2:
                await dest.send(cont2)

        except discord.Forbidden:
            if dest == current_user.dm_channel:
                await dest.send("I couldn't send a message to the user (maybe they blocked me). "
                                "I have closed the chat.")

            elif dest == report_room:
                await msg.channel.send("I couldn't send your message to the mods. Maybe they've locked me out "
                                       "of the report channel. I have closed this chat.")
            await self.close_room(config, source, dest)

    # for finding out which report session a certain message belongs to, None if not part of anything
    def find_current_guild(self, msg):
        for guild in self.bot.db['guilds']:
            config = self.bot.db['guilds'][guild]
            if not config['currentuser']:
                continue
            report_room = self.bot.get_channel(config['channel'])
            current_user = self.bot.get_user(config['currentuser'])
            if msg.channel == current_user.dm_channel:  # DM --> Report room
                print(1)
                source = msg.author.dm_channel
                dest = report_room
                return config, current_user, report_room, source, dest
            elif msg.channel == report_room:  # Report room --> DM
                print(2)
                source = report_room
                dest = msg.author.dm_channel
                return config, current_user, report_room, source, dest
            else:
                continue
        return None, None, None, None, None

    # for first entering a user into the report room
    async def modbot_entry(self, msg):
        shared_guilds = sorted([g for g in self.bot.guilds if msg.author in g.members], key=lambda x: x.name)

        guild = None
        for g in self.bot.db['guilds']:
            if msg.author.id in self.bot.db['guilds'][g]['waitinglist']:
                guild = self.bot.get_guild(int(g))
                self.bot.db['guilds'][g]['waitinglist'].remove(msg.author.id)
                break

        if not guild:
            if len(shared_guilds) == 0:
                await msg.channel.send("I couldn't find any common guilds between us. Frankly, I don't know how you're "
                                       "messaging me. Have a nice day.")
                return
            elif len(shared_guilds) == 1:
                guild = shared_guilds[0]
                if str(guild.id) not in self.bot.db['guilds']:
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
                await msg.channel.send(msg_text, embed=discord.Embed(description=msg_embed, color=0x00FF00))
                try:
                    resp = await self.bot.wait_for('message',
                                                   check=lambda m: m.author == msg.author and m.channel == msg.channel,
                                                   timeout=60.0)
                except asyncio.TimeoutError:
                    await msg.channel.send("You've waited too long. Module closing.")
                    return
                guild_selection = re.findall("^\d{1,2}$", resp.content)
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

        config = self.bot.db['guilds'][str(guild.id)]
        report_channel = self.bot.get_channel(config['channel'])

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

            return

        # ##### START THE ROOM #######
        config['currentuser'] = msg.author.id

        async def open_room():
            await report_channel.trigger_typing()
            await msg.author.dm_channel.trigger_typing()
            await asyncio.sleep(3)
            try:
                text = f"@here The user {msg.author.mention} has entered the report room. I'll relay any of their " \
                       f"messages to this channel. Any messages you type will be sent to them.\n\nTo end this chat, " \
                       f"type `end` or `done`.\n\nTo *not* send a certain message, start the message with `_`. " \
                       f"For example, `Hello` would be sent and `_What should we do`/bot commands would not be sent." \
                       f"\n__{' '*70}__\n"
                await report_channel.send(text)
                text = f">>> {msg.author.mention}: {msg.content}"
                if len(text) > 2000:
                    await report_channel.send(text[:2000])
                    await report_channel.send(text[2000:])
                else:
                    await report_channel.send(text)
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

            # def check(m):
            #     cond1 = m.author == msg.author and m.channel == msg.channel  # message from OP in DMs
            #     cond2 = m.channel == report_channel  # message from *someone* in report room
            #     return cond1 or cond2
            #
            # finished_inner = False  # will become True if I have sent a notification saying the chat has been closed
            # mods = []
            #
            # while True:
            #     try:
            #         resp = await self.bot.wait_for('message', check=check, timeout=21600.0)
            #     except asyncio.TimeoutError:
            #         cutoff_msg = "This chat has been inactive for a long time, so it has been closed. In the future, " \
            #                      "type `end` or `done` to close it when you are done."
            #         await report_channel.send(cutoff_msg)
            #         await msg.channel.send(cutoff_msg)
            #         finished_inner = True
            #         break
            #     if resp.content:
            #         if resp.content[0] in "_;.,":  # messages starting with _
            #             await resp.add_reaction('🔇')
            #             continue
            #     if resp.author.bot:
            #         if resp.author == resp.guild.me:
            #             if resp.content.startswith('>>> '):
            #                 continue
            #         await resp.add_reaction('🔇')
            #         continue
            #     if resp.author.id not in mods:
            #         mods.append(resp.author.id)
            #     if resp.channel == msg.channel:
            #         dest = report_channel
            #     else:
            #         dest = msg.channel
            #
            #     if resp.content:
            #         if resp.content.casefold() in ['end', 'done']:
            #             await report_channel.send("Thank you, the room has been closed.")
            #             await msg.channel.send("Thank you, the room has been closed.")
            #             finished_inner = True
            #             break
            #         if dest == msg.channel:
            #             cont = f">>> "
            #             if len(mods) >= 2:
            #                 cont += f"**Moderator {mods.index(resp.author.id) + 1}:** "
            #         else:
            #             cont = f">>> {msg.author.mention}: "
            #         splice = 2000 - len(cont)
            #         cont += resp.content[:splice]
            #         if len(resp.content) > splice:
            #             cont2 = f">>> ... {resp.content[splice:]}"
            #         else:
            #             cont2 = None
            #     else:
            #         cont = cont2 = None
            #
            #     try:
            #         if cont and len(resp.embeds) == 1:
            #             await dest.send(cont, embed=resp.embeds[0])
            #         elif cont and not resp.embeds:
            #             await dest.send(cont)
            #
            #         if len(resp.embeds) > 1:
            #             for embed in resp.embeds:
            #                 await dest.send(embed=embed)
            #
            #         if resp.attachments:
            #             for attachment in resp.attachments:
            #                 await dest.send(f">>> {attachment.url}")
            #
            #         if cont2:
            #             await dest.send(cont2)
            #
            #     except discord.Forbidden:
            #         try:
            #             await report_channel.send("I couldn't send a message to the user (maybe they blocked me). "
            #                                       "I have closed the chat.")
            #         except discord.Forbidden:
            #             pass
            #
            #         try:
            #             await msg.channel.send("I couldn't send your message to the mods. Maybe they've locked me out "
            #                                    "of the report channel. I have closed this chat.")
            #         except discord.Forbidden:
            #             pass
            #         finished_inner = True
            #         break
            # return finished_inner

        finish_text = "Something went wrong and I closed the channel. It should be open for the next person to enter."
        try:
            await open_room()  # maybe this should always be True
        except Exception:
            await report_channel.send(finish_text)
            await msg.channel.send(finish_text)
            await self.close_room(config, msg.channel, report_channel)
            raise

    # for when the room is to be closed and the database reset
    async def close_room(self, config, source, dest):
        await source.send("Thank you, I have closed the room.")
        await dest.send("Thank you, I have closed the room.")
        if config['currentuser'] in self.bot.db['inpms']:
            self.bot.db['inpms'].remove(config['currentuser'])
        config['mods'] = []
        config['currentuser'] = None

        for u in config['waitinglist']:
            try:
                user = self.bot.get_user(int(u))
                if not user:
                    config['waitinglist'].remove(u)
                    continue
                await user.send("The report room has opened up. Please try messaging again, or type `cancel` to "
                                "remove yourself from the list.")
            except discord.Forbidden:
                config['waitinglist'].remove(u)
                report_room = self.bot.get_channel(config["channel"])
                await report_room.send(f"I tried to message {user.name} to tell them the report room opened, but "
                                       f"I couldn't send them a message. I've removed them from the waiting list.")

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
        await channel.send(f"Message from the mods of {ctx.guild.name}: {msg}")
        await ctx.message.add_reaction("✅")

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
            if user in self.bot.db['inpms']:
                self.bot.db['inpms'].remove(user)
        self.bot.db['guilds'][str(ctx.guild.id)]['waitinglist'] = []
        await ctx.send("I've cleared the waiting list.")
        await self.dump_json(ctx)

    @commands.command()
    @commands.check(is_admin)
    async def setup(self, ctx):
        """Sets the current channel as the report room, or resets the report module"""
        if str(ctx.guild.id) in self.bot.db['guilds']:
            for user in self.bot.db['guilds'][str(ctx.guild.id)]['waitinglist']:
                if user in self.bot.db['inpms']:
                    self.bot.db['inpms'].remove(user)
            if self.bot.db['guilds'][str(ctx.guild.id)]['currentuser']:
                if self.bot.db['guilds'][str(ctx.guild.id)]['currentuser'] in self.bot.db['inpms']:
                    self.bot.db['inpms'].remove(self.bot.db['guilds'][str(ctx.guild.id)]['currentuser'])
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

    def cleanup_code(self, content):
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
            except:
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

    async def dump_json(self, ctx):
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

def setup(bot):
    bot.add_cog(Modbot(bot))
