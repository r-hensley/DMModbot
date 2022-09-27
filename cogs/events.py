import os
import discord
from discord.ext import commands

class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot
        
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """This is to record the languages of users."""
        self.bot.db['user_localizations'][interaction.user.id] = str(interaction.locale)[:2]
        
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