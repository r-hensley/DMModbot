import os
import discord
from discord.ext import commands
from .unbans import Unbans
from .admin import Admin

class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot
        
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """This is to record the languages of users."""
        self.bot.db['user_localizations'][interaction.user.id] = str(interaction.locale)[:2]
        
        #         def check_for_button_press(i):
        #             return i.type == discord.InteractionType.component and \
        #                    i.data.get("custom_id", "") in [report_button.custom_id, account_q_button.custom_id,
        #                                                    server_q_button.custom_id, cancel_button.custom_id]
        #
        #         try:
        #             interaction = await self.bot.wait_for("interaction", timeout=180.0, check=check_for_button_press)
        #         except asyncio.TimeoutError:
        #             return None, None  # no button pressed
        #         else:
        #             if interaction.data.get("custom_id", "") in [report_button.custom_id, account_q_button.custom_id]:
        #                 return guild, 'main'
        #             elif interaction.data.get("custom_id", "") == server_q_button.custom_id:
        #                 return guild, 'secondary'
        #             else:
        #                 return None, None
        
        async def check_for_ban_appeal_buttons():
            # spanish_server_appeal_channel = self.bot.get_channel(985968434263257138)
            # japanese_server_appeal_channel = self.bot.get_channel(985968511455232000)
            # celx_appeal_channel = self.bot.get_channel(1024106387472666715)
            # r_chineselanguage_appeal_channel = self.bot.get_channel(1024106910225535076)
            # ryan_test_server_appeal_channel = self.bot.get_channel(986061548877410354)
            #
            # start_channel = self.bot.get_channel(985967093411368981)
            #
            # create_ticket_channel = self.bot.get_channel(774660366620950538)
            
            # channels = [spanish_server_appeal_channel, japanese_server_appeal_channel, celx_appeal_channel,
            #             r_chineselanguage_appeal_channel, ryan_test_server_appeal_channel,
            #             start_channel, create_ticket_channel]
            
            # unbans cog
            # noinspection PyTypeChecker
            unbans: Unbans = self.bot.get_cog("Unbans")
            # noinspection PyTypeChecker
            admin: Admin = self.bot.get_cog("Admin")
            
            # interaction custom_id
            custom_id = interaction.data.get("custom_id", "")
            
            # loop through the custom_ids in self.bot.db['buttons']
            # if the custom_id matches the interaction's custom_id, call the function
            if custom_id == self.bot.db['buttons'].get("main_start_button", "not_found"):
                await unbans.main_start_button_callback(interaction)
                return
            
            for _, button_id in self.bot.db['buttons'].get('start_appeal_button', {}).items():
                if custom_id == button_id:
                    await unbans.start_appeal_button_callback(interaction)
                    return
            
            await admin.report_button_callback(interaction)
            
            # for channel in channels:
            #     last_message = [message async for message in channel.history(limit=1)][0]
            #     if last_message.author.id != self.bot.user.id:
            #         continue
            #
            #     # check if buttons are in the message
            #     if not last_message.components:
            #         continue
            #
            #     # check if the button push in "interaction" is the button in "last_message"
            #     interaction_id = interaction.data.get("custom_id", "")
            #     # message.components returns a list of "ActionRow" objects
            #     if interaction_id == last_message.components[0].children[0].custom_id:
            #         # call that button's function
            #         if channel == start_channel:
            #             await unbans.main_start_button_callback(interaction)
            #         elif channel == create_ticket_channel:
            #             await admin.report_button_callback(interaction)
            #         else:
            #             await unbans.start_appeal_button_callback(interaction)
        
        # await check_for_ban_appeal_buttons()
                
    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        msg = f"""__New guild__
        **Name:** {guild.name}
        **Owner:** {guild.owner.mention} ({guild.owner.name}#{guild.owner.discriminator}))
        **Members:** {guild.member_count}
        **Channels:** {len(guild.text_channels)} text / {len(guild.voice_channels)} voice"""

        await self.bot.get_user(self.bot.owner_id).send(msg)
        await self.bot.get_user(self.bot.owner_id).send("Channels: \n" +
                                                        '\n'.join([channel.name for channel in guild.channels]))
        
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        ban_appeals_guild_id = int(os.getenv("BAN_APPEALS_GUILD_ID") or 0)
        ban_appeals_guild = self.bot.get_guild(ban_appeals_guild_id)
        servers_category = discord.utils.find(lambda c: c.name.casefold() == 'servers', ban_appeals_guild.categories)
        guild_id_to_role_dict: dict[int, discord.Role] = {}
        
        server_moderator_role = ban_appeals_guild.get_role(1024206163715297341)
        
        for role in ban_appeals_guild.roles:
            # most role names will be named after a guild ID
            try:
                guild_id = int(role.name.split('_')[0])
            except ValueError:
                continue
            
            # try to get guild matching the name of the role
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            
            member_in_guild = guild.get_member(member.id)
            if not member_in_guild:
                continue
            
            # if they have admin or manage_guild, assign them the role corresponding to their guild they moderate
            perms = member_in_guild.guild_permissions
            if perms.administrator or perms.manage_guild:
                try:
                    await member.add_roles(role, server_moderator_role)
                    await member.send("I've given you special access to the appeals channel for your server. Normally "
                                      "users will only be able to see this if they are banned on your server. If you "
                                      "wish, you can send a message to this channel and it will overwrite the "
                                      "previous appeals instructions message in the server (ask Ryan if you want to " 
                                      "recover an old message).")
                except (discord.Forbidden, discord.HTTPException):
                    continue            
            

async def setup(bot):
    await bot.add_cog(Events(bot))
    