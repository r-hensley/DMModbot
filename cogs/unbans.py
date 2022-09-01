import os

import discord
from discord.ext import commands

from .modbot import Modbot
from .utils import helper_functions as hf

RYRY_ID = 202995638860906496
TEST_SERVER_ID = 275146036178059265


async def on_tree_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    await hf.send_error_embed(interaction.client, interaction, error)


class Unbans(commands.Cog):
    """
    This cog is to manage the unbans server.

    When users are banned, if they join this server they can initiate an unban request through modbot.
    """
    def __init__(self, bot):
        self.bot = bot
        self.ban_appeal_server_id = int(os.getenv("BAN_APPEALS_GUILD_ID") or 0)
        self.bot.tree.on_error = on_tree_error

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if not msg.guild:
            return

        ban_appeal_server = self.bot.get_guild(self.ban_appeal_server_id)
        if msg.guild == ban_appeal_server and msg.author != msg.guild.me:
            if msg.channel.category.name == 'servers' or msg.channel.name == 'start_here':
                await self.reattach_report_button(msg)  # if a mod edits one of the report info channels

    async def reattach_report_button(self, msg: discord.Message):
        """Called if a mod sends a message in the report info channel.

        This function will clear all the UI views in the channel and reattach them to the last message in channel"""
        async for m in msg.channel.history(limit=None):
            if m.author == msg.guild.me:
                await m.delete()

        view = discord.ui.View(timeout=0)
        button = discord.ui.Button(style=discord.ButtonStyle.primary, label="Start ban appeal")
        view.add_item(button)

        if msg.channel.name == 'start_here':
            button.callback = self.main_start_button_callback
        elif msg.channel.category.name == 'servers':
            button.callback = self.start_appeal_button_callback

        invisible_character = "⁣"
        await msg.channel.send(invisible_character, view=view)

    async def main_start_button_callback(self, button_interaction: discord.Interaction):
        """Perform the following steps
        1) Checks if the user is banned in some server
        2) For each server with a ban entry for the user, it will give them the role
        with a name equal to that server's ID"""
        roles = []
        for guild in self.bot.guilds:
            # Check if there's a channel in the appeals server corresponding to guild
            channel = discord.utils.get(button_interaction.guild.text_channels, topic=str(guild.id))
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
                    role = discord.utils.get(button_interaction.guild.roles, name=str(guild.id))
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
            guild_ids = [r.name for r in roles]
            for guild_id in guild_ids:
                if c := discord.utils.get(button_interaction.guild.text_channels, topic=str(guild_id)):
                    found_channels.append(c)

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
            guild_id = int(button_interaction.channel.topic)
            guild = self.bot.get_guild(guild_id)
        except TypeError:
            await button_interaction.response.send_message(f"<@{self.bot.owner_id}>: Please set the topic of this "
                                                           "channel to just a guild ID and nothing else.")
            return

        if guild_id not in self.bot.db['guilds']:
            await button_interaction.response.send_message("The server has not properly setup their modbot room. The "
                                                           "moderators should type `_setup` in some channel on their "
                                                           "main server.")
            return

        self.bot.db['user_localizations'][button_interaction.user.id] = str(locale)
        if str(locale).startswith('es'):
            response_text = f"Esto iniciará una apelación de baneo con {guild.name}. " \
                            f"¿Está seguro de que desea continuar?"
            confirmation_text = "Iniciar un apelación de expulsión"
            cancelation_text = "Cancelar"
            cancelation_confirmation = "Cancelado"
            final_text = f"Por favor, lea el mensaje privado de {self.bot.user.mention}."
        elif str(locale).startswith("ja"):
            response_text = f"これにより{guild.name}でバンの解除申請が開始されます。よろしいですか。"
            confirmation_text = "バンの解除申請を開始します"
            cancelation_text = "キャンセル"
            cancelation_confirmation = "中止しました。"
            final_text = f"{self.bot.user.mention}からのメッセージをご確認ください。"
        else:
            response_text = f"This will start a ban appeal with {guild.name}. Are you sure you wish to continue?"
            confirmation_text = "Start a ban appeal"
            cancelation_text = "Cancel"
            cancelation_confirmation = "Canceled"
            final_text = f"Please read the private message from {self.bot.user.mention}"

        confirmation_button = discord.ui.Button(label=confirmation_text)
        cancellation_button = discord.ui.Button(label=cancelation_text)
        view = discord.ui.View()
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
