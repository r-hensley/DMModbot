from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands, tasks

from .utils import helper_functions as hf


ROOM_TYPES = {
    "main": {
        "channel_key": "channel",
        "meta_key": "meta_channel",
        "status_message_key": "meta_status_message_id",
        "label": "Main report room",
    },
    "secondary": {
        "channel_key": "secondary_channel",
        "meta_key": "secondary_meta_channel",
        "status_message_key": "secondary_meta_status_message_id",
        "label": "Secondary report room",
    },
    "voice": {
        "channel_key": "voice_report_channel",
        "meta_key": "voice_report_meta_channel",
        "status_message_key": "voice_report_meta_status_message_id",
        "label": "Voice report room",
    },
}


@dataclass
class ThreadStats:
    thread: Optional[discord.Thread]
    thread_info: dict
    user: Optional[discord.abc.User]
    message_count: int = 0
    first_message_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None
    last_activity_kind: str = "unknown"
    error: Optional[str] = None


class ReportStatus(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.report_status_loop.start()

    def cog_unload(self):
        self.report_status_loop.cancel()

    @tasks.loop(minutes=1)
    async def report_status_loop(self):
        db_changed = await self.prune_stale_reports()

        for guild_id, guild_config in self.bot.db.get("guilds", {}).items():
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue

            for room_type in ROOM_TYPES:
                changed = await self.update_room_status(guild, guild_config, room_type)
                db_changed = db_changed or changed

        if db_changed:
            await hf.dump_json()

    @report_status_loop.before_loop
    async def before_report_status_loop(self):
        await self.bot.wait_until_ready()

    async def prune_stale_reports(self) -> bool:
        stale_user_ids = []

        for user_id, report in list(self.bot.db.get("reports", {}).items()):
            thread = self.bot.get_channel(report.get("thread_id", 0))
            if not isinstance(thread, discord.Thread):
                stale_user_ids.append(user_id)
                continue

            if thread.archived:
                stale_user_ids.append(user_id)

        for user_id in stale_user_ids:
            self.bot.db["reports"].pop(user_id, None)

        return bool(stale_user_ids)

    async def update_room_status(self, guild: discord.Guild, guild_config: dict, room_type: str) -> bool:
        room_meta = ROOM_TYPES[room_type]
        report_channel_id = guild_config.get(room_meta["channel_key"])
        meta_thread_id = guild_config.get(room_meta["meta_key"])
        if not report_channel_id or not meta_thread_id:
            return False

        report_channel = self.bot.get_channel(report_channel_id)
        if not report_channel:
            return False

        meta_thread = report_channel.get_thread(meta_thread_id) if isinstance(report_channel, discord.ForumChannel) else None
        if not meta_thread:
            return False

        active_reports = [
            report for report in self.bot.db.get("reports", {}).values()
            if report.get("guild_id") == guild.id and report.get("thread_id")
        ]
        active_reports = [
            report for report in active_reports
            if self._report_matches_room(guild_config, report, room_type)
        ]

        embed = await self.build_status_embed(guild, report_channel, room_type, active_reports)
        return await self.ensure_status_message(meta_thread, guild_config, room_type, embed)

    def _report_matches_room(self, guild_config: dict, report: dict, room_type: str) -> bool:
        if report.get("report_room_type"):
            return report["report_room_type"] == room_type

        channel_id = guild_config.get(ROOM_TYPES[room_type]["channel_key"])
        thread = self.bot.get_channel(report["thread_id"])
        if thread and isinstance(thread, discord.Thread):
            return getattr(thread.parent, "id", None) == channel_id
        return room_type == "main" and channel_id == guild_config.get("channel")

    async def build_status_embed(
        self,
        guild: discord.Guild,
        report_channel: discord.abc.GuildChannel,
        room_type: str,
        active_reports: list[dict],
    ) -> discord.Embed:
        room_label = ROOM_TYPES[room_type]["label"]
        embed = discord.Embed(
            title=f"{room_label} status",
            color=0x23DD81,
            timestamp=discord.utils.utcnow(),
        )
        embed.description = (
            f"Active DB reports in {getattr(report_channel, 'mention', '#unknown')}: `{len(active_reports)}`"
        )

        if not active_reports:
            embed.add_field(name="Active reports", value="None", inline=False)
            return embed

        stats_entries: list[ThreadStats] = []
        for report in sorted(active_reports, key=lambda item: item.get("thread_id", 0)):
            entry = await self.collect_thread_stats(guild, report)
            if entry.thread is None or entry.user is None:
                continue
            stats_entries.append(entry)

        embed.description = (
            f"Active DB reports in {getattr(report_channel, 'mention', '#unknown')}: `{len(stats_entries)}`"
        )

        if not stats_entries:
            embed.add_field(name="Active reports", value="None", inline=False)
            return embed

        summary_lines = []
        for entry in stats_entries:
            summary_lines.append(self.format_thread_summary(entry))

        embed.add_field(
            name="Active reports",
            value=self.chunk_text("\n".join(summary_lines), 1024),
            inline=False,
        )

        flagged_lines = [self.format_flagged_state(entry) for entry in stats_entries if self.format_flagged_state(entry)]
        if flagged_lines:
            embed.add_field(
                name="Needs attention",
                value=self.chunk_text("\n".join(flagged_lines), 1024),
                inline=False,
            )
        embed.set_footer(
            text=f"✅ = responded • ⏳ = awaiting mod response"
        )
        return embed

    async def collect_thread_stats(self, guild: discord.Guild, report: dict) -> ThreadStats:
        thread = self.bot.get_channel(report["thread_id"])
        user = self.bot.get_user(report["user_id"])
        if not user:
            try:
                user = await self.bot.fetch_user(report["user_id"])
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                user = None

        stats = ThreadStats(thread=thread, thread_info=report, user=user)
        if not isinstance(thread, discord.Thread):
            stats.error = "Thread not found"
            return stats

        try:
            async for message in thread.history(limit=None, oldest_first=True):
                if message.type is not discord.MessageType.default and message.type is not discord.MessageType.reply:
                    continue

                stats.message_count += 1

                created_at = message.created_at.replace(tzinfo=timezone.utc) if message.created_at.tzinfo is None else message.created_at
                if stats.first_message_at is None:
                    stats.first_message_at = created_at
                stats.last_message_at = created_at

                if message.author.bot:
                    if message.author == guild.me and (message.content or "").startswith(">>> "):
                        stats.last_activity_kind = "user reply"
                    elif message.author == guild.me:
                        stats.last_activity_kind = "bot update"
                    continue

                stats.last_activity_kind = "mod reply"
        except (discord.Forbidden, discord.HTTPException) as exc:
            stats.error = type(exc).__name__

        return stats

    def format_thread_summary(self, entry: ThreadStats) -> str:
        if entry.thread is None:
            mention = f"`{entry.thread_info['thread_id']}`"
        else:
            mention = entry.thread.mention

        user_label = f"<@{entry.thread_info['user_id']}>"
        age_text = self.format_relative_time(entry.last_message_at)
        status_bits = []
        status_icon = "✅" if self.was_last_message_responded_to(entry) else "⏳"

        if entry.thread is not None:
            if entry.thread.archived:
                status_bits.append("archived")
            if entry.thread.locked:
                status_bits.append("locked")
            tag_names = [tag.name for tag in getattr(entry.thread, "applied_tags", [])]
            if tag_names:
                status_bits.append(", ".join(tag_names[:3]))

        if entry.error:
            status_bits.append(entry.error)

        return (
            f"{status_icon} {mention} {user_label}\n"
            f"msgs `{entry.message_count}` | last {age_text}"
        )

    @staticmethod
    def format_flagged_state(entry: ThreadStats) -> str:
        problems = []
        if entry.thread.archived:
            problems.append("archived")
        if entry.thread.locked:
            problems.append("locked")

        tag_names = {tag.name.casefold() for tag in getattr(entry.thread, "applied_tags", [])}
        if "closed (unresolved)" in tag_names:
            problems.append("closed unresolved")
        if "complete" in tag_names:
            problems.append("complete")

        if not problems:
            return ""

        return f"{entry.thread.mention}: `{', '.join(problems)}` while still present in the DB."

    @staticmethod
    def format_attention_hint(entry: ThreadStats) -> str:
        if entry.last_activity_kind == "user reply":
            return "needs mod review"
        if entry.last_activity_kind == "mod reply":
            return "waiting on user"
        if entry.last_activity_kind == "bot update":
            return "check thread"
        return "status unclear"

    @staticmethod
    def was_last_message_responded_to(entry: ThreadStats) -> bool:
        return entry.last_activity_kind in {"mod reply", "bot update"}

    @staticmethod
    async def ensure_status_message(
            meta_thread: discord.Thread,
        guild_config: dict,
        room_type: str,
        embed: discord.Embed,
    ) -> bool:
        message_key = ROOM_TYPES[room_type]["status_message_key"]
        stored_message_id = guild_config.get(message_key)
        stored_message = None

        if stored_message_id:
            try:
                stored_message = await meta_thread.fetch_message(stored_message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                stored_message = None

        newest_message = None
        async for message in meta_thread.history(limit=1):
            newest_message = message
            break

        if stored_message and newest_message and newest_message.id == stored_message.id:
            await stored_message.edit(embed=embed)
            return False

        if stored_message:
            try:
                await stored_message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        new_message = await meta_thread.send(embed=embed)
        guild_config[message_key] = new_message.id
        return True

    @staticmethod
    def format_relative_time(dt: Optional[datetime]) -> str:
        if not dt:
            return "unknown"
        timestamp = int(dt.timestamp())
        return f"<t:{timestamp}:R>"

    @staticmethod
    def chunk_text(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 16] + "\n`...truncated`"


async def setup(bot: commands.Bot):
    await bot.add_cog(ReportStatus(bot))
