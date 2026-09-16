import re
from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .utils import helper_functions as hf


_DURATION_PATTERN = re.compile(r'(\d+)\s*([smhdw])', re.IGNORECASE)

_UNIT_SECONDS = {
    's': 1,
    'm': 60,
    'h': 3600,
    'd': 86400,
    'w': 604800,
}

RESOLUTION_MESSAGE = (
    "Hi! Since we haven't heard back from you, we're going "
    "to close this ticket for now. If you still need help, please feel free "
    "to reach out again at any time. We'll be happy to assist!"
)

def parse_duration(time_str: str) -> Optional[timedelta]:
    if not time_str:
        return None

    matches = _DURATION_PATTERN.findall(time_str.strip())

    if not matches:
        return None

    total_seconds = sum(
        int(value) * _UNIT_SECONDS[unit.lower()]
        for value, unit in matches
    )

    if total_seconds <= 0:
        return None

    return timedelta(seconds=total_seconds)


class ResolveAfter(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.resolve_after_loop.start()

    def cog_unload(self):
        self.resolve_after_loop.cancel()

    def _get_resolution_embed(self) -> discord.Embed:
        return discord.Embed(
            title="Ticket Closed",
            description=RESOLUTION_MESSAGE,
            color=discord.Color.blurple(),
        )

    def _get_meta_channel_id(self, guild_id: int) -> Optional[int]:
        guilds = self.bot.db.get("guilds", {})

        guild_data = guilds.get(str(guild_id))

        if guild_data is None:
            guild_data = guilds.get(guild_id)

        if not isinstance(guild_data, dict):
            return None

        meta_channel_id = guild_data.get("meta_channel")

        if not meta_channel_id:
            return None

        try:
            return int(meta_channel_id)
        except (TypeError, ValueError):
            return None

    def _get_meta_thread(
        self,
        guild: discord.Guild,
    ) -> Optional[discord.Thread]:

        meta_channel_id = self._get_meta_channel_id(guild.id)

        if not meta_channel_id:
            return None

        meta_thread = guild.get_thread(meta_channel_id)

        if isinstance(meta_thread, discord.Thread):
            return meta_thread

        channel = self.bot.get_channel(meta_channel_id)

        if isinstance(channel, discord.Thread):
            return channel

        return None

    def _get_meta_forum_id(
        self,
        guild: discord.Guild,
    ) -> Optional[int]:

        meta_thread = self._get_meta_thread(guild)

        if not meta_thread:
            return None

        return meta_thread.parent_id

    async def _post_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:

        if not interaction.guild:
            return []

        forum_id = self._get_meta_forum_id(interaction.guild)

        if not forum_id:
            return []

        meta_channel_id = self._get_meta_channel_id(
            interaction.guild.id
        )

        current = current.lower().strip()

        posts = []

        for thread in interaction.guild.threads:
            if thread.parent_id != forum_id:
                continue

            if thread.id == meta_channel_id:
                continue

            if thread.archived:
                continue

            if current and current not in thread.name.lower():
                continue

            posts.append(thread)

        posts.sort(
            key=lambda thread: thread.created_at or discord.utils.utcnow(),
            reverse=True,
        )

        return [
            app_commands.Choice(
                name=thread.name[:100],
                value=str(thread.id),
            )
            for thread in posts[:25]
        ]

    @app_commands.command(
        name="resolve_after",
        description="Automatically resolve a forum ticket if the user doesn't reply in time.",
    )
    @app_commands.default_permissions()
    @app_commands.describe(
        post="The forum post/ticket that should be automatically resolved.",
        time="How long to wait for a reply before resolving, e.g. 12h, 1d, 2d, 1w.",
    )
    @app_commands.autocomplete(post=_post_autocomplete)
    async def resolve_after(
        self,
        interaction: discord.Interaction,
        post: str,
        time: str,
    ):
        delta = parse_duration(time)

        if delta is None:
            await interaction.response.send_message(
                f"I couldn't understand `{time}` as a duration. "
                f"Try something like `12h`, `1d`, `2d`, or `1w`.",
                ephemeral=True,
            )
            return

        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        try:
            post_id = int(post)
        except (TypeError, ValueError):
            await interaction.response.send_message(
                "Invalid forum post.",
                ephemeral=True,
            )
            return

        post_channel = interaction.guild.get_thread(post_id)

        if not isinstance(post_channel, discord.Thread):
            channel = self.bot.get_channel(post_id)

            if isinstance(channel, discord.Thread):
                post_channel = channel

        if not isinstance(post_channel, discord.Thread):
            await interaction.response.send_message(
                "I couldn't find that forum post.",
                ephemeral=True,
            )
            return

        forum_id = self._get_meta_forum_id(interaction.guild)

        if not forum_id:
            await interaction.response.send_message(
                "I couldn't find the Meta Discussion post for this server.",
                ephemeral=True,
            )
            return

        if post_channel.parent_id != forum_id:
            await interaction.response.send_message(
                "That post doesn't belong to the configured forum.",
                ephemeral=True,
            )
            return

        meta_channel_id = self._get_meta_channel_id(
            interaction.guild.id
        )

        if post_channel.id == meta_channel_id:
            await interaction.response.send_message(
                "The Meta Discussion post cannot be resolved using this command.",
                ephemeral=True,
            )
            return

        if post_channel.archived:
            await interaction.response.send_message(
                f"{post_channel.mention} is already archived/resolved.",
                ephemeral=True,
            )
            return

        resolve_at = discord.utils.utcnow() + delta

        self.bot.db.setdefault(
            "scheduled_resolutions",
            {},
        )[post_channel.id] = {
            "guild_id": post_channel.guild.id,
            "resolve_at": int(resolve_at.timestamp()),
            "requested_by": interaction.user.id,
        }

        await hf.dump_json()

        await interaction.response.send_message(
            f"{post_channel.mention} will be closed "
            f"<t:{int(resolve_at.timestamp())}:R> "
            f"if we don't receive a reply from the user before then."
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return

        scheduled = self.bot.db.get(
            "scheduled_resolutions",
            {},
        )

        if message.channel.id not in scheduled:
            return

        if not self.bot.user:
            return

        if message.author.id != self.bot.user.id:
            return

        if not (message.content or "").startswith(">>>"):
            return

        del scheduled[message.channel.id]

        await hf.dump_json()

    @tasks.loop(minutes=1)
    async def resolve_after_loop(self):
        scheduled = self.bot.db.get(
            "scheduled_resolutions",
            {},
        )

        if not scheduled:
            return

        now_ts = int(
            discord.utils.utcnow().timestamp()
        )

        due_thread_ids = [
            thread_id
            for thread_id, entry in scheduled.items()
            if entry.get("resolve_at", 0) <= now_ts
        ]

        if not due_thread_ids:
            return

        for thread_id in due_thread_ids:
            entry = scheduled.pop(
                thread_id,
                None,
            )

            if entry is None:
                continue

            await self._resolve_ticket(
                thread_id,
                entry,
            )

        await hf.dump_json()

    @resolve_after_loop.before_loop
    async def before_resolve_after_loop(self):
        await self.bot.wait_until_ready()

    async def _resolve_ticket(
        self,
        thread_id: int,
        entry: dict,
    ):
        thread = self.bot.get_channel(thread_id)

        if not isinstance(thread, discord.Thread):
            return

        if thread.archived:
            return

        user = None

        for report in self.bot.db.get(
            "reports",
            {},
        ).values():

            if report.get("thread_id") != thread_id:
                continue

            user_id = report.get("user_id")

            user = self.bot.get_user(user_id)

            if not user:
                try:
                    user = await self.bot.fetch_user(user_id)
                except (
                    discord.NotFound,
                    discord.HTTPException,
                ):
                    user = None

            break

        embed = self._get_resolution_embed()

        if user:
            try:
                await user.send(embed=embed)
            except (
                discord.Forbidden,
                discord.HTTPException,
            ):
                pass

        try:
            await thread.send(embed=embed)
        except (
            discord.Forbidden,
            discord.HTTPException,
        ):
            pass

        await hf.close_thread(
            thread,
            finish=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ResolveAfter(bot))
