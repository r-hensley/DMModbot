import os

import discord
from discord.ext import commands

from .modbot import Modbot
from .utils import helper_functions as hf

RYRY_ID = 202995638860906496
TEST_SERVER_ID = 275146036178059265


async def reinitialize_buttons(unbans):
    # example DB:
    # {
    # 'start_appeal_button':
    #   {986061548877410354: 1233599842983477258,
    #   1024106910225535076: 1233600145963094056,
    #   1024106387472666715: 1233600190284304414,
    #   985968511455232000: 1233600227957805158,
    #   985968434263257138: 1233600254239309895},
    # 'report_button': {554572239836545074: 1233599933563666462, 774660366620950538: 1233601399024124026},
    # 'main_start_button': {985967093411368981: 1233600929740230667}
    # }
    for button_name, button_dict in unbans.bot.db['buttons'].items():
        if button_name == 'start_appeal_button':
            for channel_id, msg_id in button_dict.items():
                await unbans.setup_appeal_button_view(channel_id, msg_id)
        
        elif button_name == 'main_start_button':
            for channel_id, msg_id in button_dict.items():
                await unbans.setup_appeal_button_view(channel_id, msg_id)


class Unbans(commands.Cog):
    """
    This cog is to manage the unbans server.

    When users are banned, if they join this server they can initiate an unban request through modbot.
    """
    def __init__(self, bot):
        self.bot: commands.Bot = bot
        self.ban_appeal_server_id = int(os.getenv("BAN_APPEALS_GUILD_ID") or 0)
        
    async def cog_load(self):
        await reinitialize_buttons(self)

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if not msg.guild:
            return

        ban_appeal_server = self.bot.get_guild(self.ban_appeal_server_id)
        if msg.guild == ban_appeal_server and msg.author != msg.guild.me:
            if msg.channel.category.name == 'servers' or msg.channel.name == 'start_here':
                await self.reattach_report_button(msg)  # if a mod edits one of the report info channels

    async def setup_appeal_button_view(self,
                                       msg_channel_id: int, msg_id: int, source_msg: discord.Message = None,
                                       to_edit_msg: discord.Message = None) -> discord.Message:
        """Sets up the view for the ban appeal button"""
        if not source_msg:
            msg = await self.bot.get_channel(msg_channel_id).fetch_message(msg_id)
        else:
            msg = source_msg
            
        view = hf.RaiView(timeout=0)
        button = discord.ui.Button(style=discord.ButtonStyle.primary, label="Start ban appeal")
        view.add_item(button)
        if msg.channel.name == 'start_here':
            button.callback = self.main_start_button_callback
        elif msg.channel.category.name == 'servers':
            button.callback = self.start_appeal_button_callback
            
        if to_edit_msg:
            sent_msg = await to_edit_msg.edit(view=view)
        else:
            invisible_character = "⁣"
            sent_msg = await msg.channel.send(invisible_character, view=view)
            
            # main appeal start button
            if msg.channel.name == 'start_here':
                self.bot.db['buttons'].setdefault('main_start_button', {})
                self.bot.db['buttons']['main_start_button'][sent_msg.channel.id] = sent_msg.id
            
            # the appeal start buttons in each server's appeal channel
            elif msg.channel.category.name == 'servers':
                self.bot.db['buttons'].setdefault('start_appeal_button', {})
                self.bot.db['buttons']["start_appeal_button"][sent_msg.channel.id] = sent_msg.id
                
        return sent_msg
    
    async def reattach_report_button(self, msg: discord.Message):
        """Called if a mod sends a message in the report info channel.

        This function will clear all the UI views in the channel and reattach them to the last message in channel"""
        async for m in msg.channel.history(limit=None):
            if m.author == msg.guild.me:
                await m.delete()

        await self.setup_appeal_button_view(msg.channel.id, msg.id, source_msg=msg)

    async def main_start_button_callback(self, button_interaction: discord.Interaction):
        """Perform the following steps
        1) Checks if the user is banned in some server
        2) For each server with a ban entry for the user, it will give them the role
        with a name equal to that server's ID"""
        roles = []
        for guild in self.bot.guilds:
            # Check if there's a channel in the appeals server corresponding to guild
            channel = discord.utils.find(lambda c: c.topic.split('\n')[0] == str(guild.id), 
                                         button_interaction.guild.text_channels)
            if not channel:
                continue

            # Check if user is banned in guild
            try:
                if button_interaction.user.id == RYRY_ID and guild.id == TEST_SERVER_ID:
                    pass
                else:
                    await guild.fetch_ban(button_interaction.user)
            except discord.NotFound:
                pass
            except discord.Forbidden:
                await button_interaction.response.send_message(f"I lack the permission to check bans on {guild.name}. "
                                                               f"In order to check this, I need `Ban Members`.")
                continue

            # If banned, create/add the role corresponding to guild
            else:
                try:
                    role = discord.utils.find(lambda r: r.name.startswith(str(guild.id)), button_interaction.guild.roles)
                    if not role:
                        role = await button_interaction.guild.create_role(name=str(guild.id))
                        try:
                            await channel.set_permissions(role, read_messages=True)
                        except discord.Forbidden:
                            await button_interaction.response.send_message("I lack the ability to edit permissions "
                                                                           "on channels. Please give me the "
                                                                           "`Manage Channels` permission.")
                            return
                    await button_interaction.user.add_roles(role)
                    roles.append(role)
                except discord.Forbidden:
                    await button_interaction.response.send_message("I lack the permission to manage roles in this "
                                                                   "server. Please give me that permission.")
                    return

        found_channels = []
        if roles:
            guild_ids = [r.name.split('_')[0] for r in roles]
            for guild_id in guild_ids:
                if found_channel := discord.utils.find(lambda c: c.topic.split('\n')[0] == str(guild_id),
                                           button_interaction.guild.text_channels):
                    found_channels.append(found_channel)

        if button_interaction.user.id == RYRY_ID:
            found_channels.append(self.bot.get_channel(986061548877410354))

        if found_channels:
            list_of_channel_mentions = '\n- '.join([c.mention for c in found_channels])
            await button_interaction.response.send_message(f"I've found ban entries in at least one server. Please "
                                                           f"check the following channels to start a ban appeal.\n"
                                                           f"- {list_of_channel_mentions}", ephemeral=True)
        else:
            m = "You are not banned in any of the servers I currently serve on this ban appeals server. " \
                "Please check again with the mods of that server. \n\nNote if you're sure you can't join that sever, " \
                "you may be IP banned. If you've ever used any other Discord accounts before, please try to join " \
                "this server with one of those accounts and try starting the process again."
            await button_interaction.response.send_message(m, ephemeral=True)

    async def start_appeal_button_callback(self, button_interaction: discord.Interaction):
        """When this button is pressed, it will confirm in the language of the user client if they really wish
        to open a ban appeal"""
        locale = button_interaction.locale
        try:
            guild_id = int(button_interaction.channel.topic.split('\n')[0])
            guild = self.bot.get_guild(guild_id)
        except TypeError:
            await button_interaction.response.send_message(f"<@{self.bot.owner_id}>: Please set the topic of this "
                                                           "channel to just a guild ID and nothing else.")
            return

        if not guild:
            await button_interaction.response.send_message("There's been some error and I can't find this guild "
                                                           "anymore. Maybe they've kicked me or the guild has been "
                                                           "deleted. Please contact Ryan")
            return

        # Check if the user already is in a report / appeal somewhere
        if button_interaction.user.id in self.bot.db['reports']:
            dm_channel = button_interaction.user.dm_channel
            dm_channel_link = ''
            if dm_channel:
                dm_channel_link = f":\n{dm_channel.jump_url}"
            await button_interaction.response.send_message("You are already in a report or ban appeal somewhere, "
                                                           f"please check your DMs with me{dm_channel_link}",
                                                           ephemeral=True)
            return

        # Check if a user has been blocked by the guild
        blocked_users_dict = self.bot.db.get('blocked_users', {})
        if button_interaction.user.id in blocked_users_dict.get(guild.id, []):
            await button_interaction.response.send_message("This guild's appeals room has been temporarily closed "
                                                           "down. Please try again later.", ephemeral=True)
            return

        if guild_id not in self.bot.db['guilds']:
            await button_interaction.response.send_message("The server has not properly setup their modbot room. The "
                                                           "moderators should type `_setup` in some channel on their "
                                                           "main server.")
            return

        dm_channel = button_interaction.user.dm_channel
        if not dm_channel:
            try:
                await button_interaction.user.create_dm()
            except (discord.Forbidden, discord.HTTPException):
                pass
        dm_channel_link = ''
        if dm_channel:
            dm_channel_link = f":\n{dm_channel.jump_url}"

        self.bot.db['user_localizations'][button_interaction.user.id] = str(locale)
        if str(locale).startswith('es'):
            response_text = f"Esto iniciará una apelación de baneo con {guild.name}. " \
                            f"¿Está seguro de que desea continuar?"
            confirmation_text = "Iniciar un apelación de expulsión"
            cancelation_text = "Cancelar"
            cancelation_confirmation = "Cancelado"
            final_text = f"Por favor, lea el mensaje privado de {self.bot.user.mention}{dm_channel_link}."
        elif str(locale).startswith("ja"):
            response_text = f"これにより{guild.name}でバンの解除申請が開始されます。よろしいですか。"
            confirmation_text = "バンの解除申請を開始します"
            cancelation_text = "キャンセル"
            cancelation_confirmation = "中止しました。"
            final_text = f"{self.bot.user.mention}からのメッセージをご確認ください{dm_channel_link}。"
        else:
            response_text = f"This will start a ban appeal with {guild.name}. Are you sure you wish to continue?"
            confirmation_text = "Start a ban appeal"
            cancelation_text = "Cancel"
            cancelation_confirmation = "Canceled"
            final_text = f"Please read the private message from {self.bot.user.mention}{dm_channel_link}"

        confirmation_button = discord.ui.Button(label=confirmation_text)
        cancellation_button = discord.ui.Button(label=cancelation_text)
        view = hf.RaiView()
        view.add_item(confirmation_button)
        view.add_item(cancellation_button)

        async def on_timeout():
            await button_interaction.edit_original_response(view=None)

        view.on_timeout = on_timeout

        async def confirmation_callback(confirmation_interaction: discord.Interaction):
            await confirmation_interaction.response.send_message(final_text, ephemeral=True)
            await button_interaction.edit_original_response(view=None)
            await self.start_ban_appeal(confirmation_interaction.user, guild)

        async def cancellation_callback(cancellation_confirmation: discord.Interaction):
            await button_interaction.edit_original_response(view=None)
            await cancellation_confirmation.response.send_message(cancelation_confirmation, ephemeral=True)

        confirmation_button.callback = confirmation_callback
        cancellation_button.callback = cancellation_callback
        await button_interaction.response.send_message(response_text, view=view, ephemeral=True)

    async def start_ban_appeal(self, user: discord.User, guild: discord.Guild):
        cog: Modbot = self.bot.get_cog("Modbot")
        await cog.start_report_room(user, guild, msg=None, main_or_secondary="main", ban_appeal=True)


async def setup(bot):
    await bot.add_cog(Unbans(bot))
