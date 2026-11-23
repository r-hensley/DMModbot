import logging
import re
from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .utils import helper_functions as hf
from .modbot import OpenReport


logger = logging.getLogger(__name__)


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

    def _get_forum_context(
        self, interaction: discord.Interaction,
    ) -> Optional[tuple[discord.ForumChannel, set[str]]]:
        guild = interaction.guild
        channel = interaction.channel
        member = interaction.user
        if (
            guild is None
            or not isinstance(channel, discord.Thread)
            or not isinstance(member, discord.Member)
        ):
            return None

        forum = channel.parent
        if not isinstance(forum, discord.ForumChannel):
            return None

        guilds = self.bot.db.get("guilds", {})
        config = guilds.get(guild.id, guilds.get(str(guild.id)))
        if not isinstance(config, dict):
            return None

        room_keys = (
            ("channel", "meta_channel"),
            ("secondary_channel", "secondary_meta_channel"),
            ("voice_report_channel", "voice_report_meta_channel"),
        )
        if not any(str(config.get(forum_key)) == str(forum.id) for forum_key, _ in room_keys):
            return None

        # All posts in a forum inherit its visibility permissions.
        if not forum.permissions_for(member).view_channel:
            return None

        return forum, {str(config.get(meta_key)) for _, meta_key in room_keys}

    async def _post_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:

        context = self._get_forum_context(interaction)
        if context is None:
            return []
        forum, meta_ids = context

        current = current.lower().strip()

        posts = []

        for thread in forum.threads:
            if str(thread.id) in meta_ids or thread.archived:
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
        post="The ticket to close. Leave blank to use the current ticket.",
        time="How long to wait for a reply before resolving, e.g. 12h, 1d, 2d, 1w.",
    )
    @app_commands.autocomplete(post=_post_autocomplete)
    async def resolve_after(
        self,
        interaction: discord.Interaction,
        time: str,
        post: Optional[str] = None,
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

        context = self._get_forum_context(interaction)
        if context is None:
            await interaction.response.send_message(
                "Use this command from a ticket or Meta Discussion post in a report forum you can view.",
                ephemeral=True,
            )
            return
        forum, meta_ids = context

        post_channel = interaction.channel
        if post is not None:
            try:
                post_id = int(post)
            except ValueError:
                await interaction.response.send_message("Invalid forum post ID.", ephemeral=True)
                return
            if post_id != interaction.channel_id:
                post_channel = forum.get_thread(post_id)

        if not isinstance(post_channel, discord.Thread):
            await interaction.response.send_message(
                "I couldn't find that post in this report forum.",
                ephemeral=True,
            )
            return

        if str(post_channel.id) in meta_ids:
            await interaction.response.send_message(
                "Choose a ticket with the `post` option.",
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
        # Incoming reporter DMs include attachment, embed and sticker-only replies;
        # their relayed copies in the thread do not always have a text prefix.
        if message.author.bot or not isinstance(message.channel, discord.DMChannel):
            return
        if message.type not in (discord.MessageType.default, discord.MessageType.reply):
            return

        report = self.bot.db.get("reports", {}).get(message.author.id)
        if report is None:
            return
        thread_id = report.get("thread_id")
        scheduled = self.bot.db.get("scheduled_resolutions", {})
        if thread_id not in scheduled:
            return

        del scheduled[thread_id]
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
            entry = scheduled.get(thread_id)

            if entry is None:
                continue

            try:
                completed = await self._resolve_ticket(thread_id, entry)
            except discord.HTTPException:
                logger.warning("Could not resolve ticket %s; will retry", thread_id, exc_info=True)
                continue

            # A reply or a new schedule may have changed this entry while we waited.
            if completed and scheduled.get(thread_id) is entry:
                del scheduled[thread_id]

        await hf.dump_json()

    @resolve_after_loop.before_loop
    async def before_resolve_after_loop(self):
        await self.bot.wait_until_ready()

    async def _resolve_ticket(
        self,
        thread_id: int,
        entry: dict,
    ) -> bool:
        thread = self.bot.get_channel(thread_id)
        if not isinstance(thread, discord.Thread):
            try:
                thread = await self.bot.fetch_channel(thread_id)
            except discord.NotFound:
                return True  # The thread was deleted; there is nothing left to archive.

        if not isinstance(thread, discord.Thread):
            return True

        report = next(
            (report for report in self.bot.db.get("reports", {}).values()
             if report.get("thread_id") == thread_id),
            None,
        )
        if thread.archived and report is None:
            return True  # The existing archive handler already closed this report.

        user = None
        modbot = None
        if report is not None:
            modbot = self.bot.get_cog("Modbot")
            if modbot is None:
                return False
            user_id = report["user_id"]
            user = self.bot.get_user(user_id)
            if user is None:
                try:
                    user = await self.bot.fetch_user(user_id)
                except discord.NotFound:
                    pass

        # Fetching the thread or user gives reply/closure handlers time to run.
        if self.bot.db.get("scheduled_resolutions", {}).get(thread_id) is not entry:
            return False
        if report is not None and self.bot.db.get("reports", {}).get(report["user_id"]) is not report:
            return True

        embed = self._get_resolution_embed()
        if user is not None:
            try:
                await user.send(embed=embed)
            except discord.HTTPException:
                pass

        try:
            await thread.send(embed=embed)
        except discord.HTTPException:
            pass

        if report is not None and user is not None:
            # Use the report lifecycle to disconnect the DM, record the closure and
            # apply the usual cooldown, including for recovered archived threads.
            await modbot.end_report(
                OpenReport(report, user, thread, thread, user.dm_channel),
                error=False,
                finish=True,
                notify=False,  # The Ticket Closed embed above already notified both sides.
            )
        else:
            await hf.close_thread(thread, finish=True)
            if report is not None:
                reports = self.bot.db.get("reports", {})
                if reports.get(report["user_id"]) is report:
                    del reports[report["user_id"]]
                await hf.dump_json()

        return True


async def setup(bot: commands.Bot):
    await bot.add_cog(ResolveAfter(bot))
