"""Exercise room errors through the existing Discord reporter and local archive."""
import asyncio
from contextlib import closing, redirect_stderr
from io import StringIO
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import traceback
from unittest.mock import AsyncMock, Mock, patch

import discord

from cogs.main import Main
from cogs.utils.traceback_store import TracebackStore
from report_test_support import ReportTestCase, hf


class ReportTracebackTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        self.path = Path(self.enterContext(TemporaryDirectory())) / "tracebacks.db"
        self.bot.traceback_store = TracebackStore(self.path)
        self.bot.traceback_store.initialize()
        self.bot.record_traceback = AsyncMock(side_effect=self.bot.traceback_store.record_exception)
        main = Main.__new__(Main)
        main.bot = self.bot
        self.bot.on_error = main.on_error
        self.traceback_channel = Mock(send=AsyncMock())
        self.bot.get_channel.side_effect = {42: self.traceback_channel, self.thread_id: self.thread}.get
        self.enterContext(patch.dict(os.environ, {"ERROR_CHANNEL_ID": "42"}))

    def query(self, sql):
        with closing(sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)) as db:
            return db.execute(sql).fetchall()

    async def relay_failure(self):
        error = RuntimeError("relay failed")

        async def relay(*args):
            raise error from OSError("connection dropped")

        self.modbot.send_message = relay
        self.user.dm_channel.id = 12  # The bot has no cache entry for this DM.
        message = Mock(spec=discord.Message, id=34, guild=None, author=self.user,
                       channel=self.user.dm_channel, content="Private report text")
        with self.assertLogs(level="ERROR"), redirect_stderr(StringIO()):
            await discord.Client._run_event(self.bot, self.modbot.on_message, "on_message", message)
        self.assertIs(self.bot.record_traceback.await_args.args[0], error)
        self.traceback_channel.send.assert_awaited_once()
        args, kwargs = self.traceback_channel.send.await_args
        self.assertIn("Traceback event: 1", args[0])
        self.assertNotIn("Private report text", str(kwargs["embed"].to_dict()))
        attachment = kwargs["file"]
        self.addCleanup(attachment.close)
        (sample,), = self.query("SELECT sample_traceback FROM caller_paths")
        self.assertEqual(attachment.fp.getvalue().decode(), sample)
        self.assertIn("OSError: connection dropped", sample)
        self.assertIn("RuntimeError: relay failed", sample)
        self.assertIn("reporter to staff", sample)
        self.assertNotIn("Private report text", sample)
        return sample

    async def test_relay_failure_closes_room_and_reaches_archive_and_discord(self):
        await self.relay_failure()
        self.assert_disconnected()
        self.assertIn("some kind of error", self.user.dm_channel.send.await_args.args[0])
        self.assertEqual(self.query("SELECT occurrences FROM group_summary"), [(1,)])

    async def test_cleanup_failure_preserves_original_relay_exception(self):
        hf.close_thread.side_effect = OSError("cleanup failed")
        sample = await self.relay_failure()
        self.assertIn("Closing the report also failed: OSError: cleanup failed", sample)
        self.assertEqual(self.query("SELECT exception_class FROM group_summary"), [("builtins.RuntimeError",)])

    async def test_ban_appeal_open_failure_warns_and_reraises(self):
        self.bot.db["reports"].clear()
        error = RuntimeError("appeal open failed")
        self.user.dm_channel.typing = AsyncMock(side_effect=error)
        destinations = AsyncMock(return_value=(self.thread, self.thread))
        with (
            patch.object(hf, "get_report_variables", destinations, create=True),
            patch.object(hf, "check_bot_perms", AsyncMock(), create=True),
            self.assertRaises(RuntimeError) as caught,
        ):
            await self.modbot.start_ban_appeal_room(self.user, self.thread.guild, "Private appeal", "main")
        self.assertIs(caught.exception, error)
        self.assertIn("Opening a ban appeal room", error.__notes__[0])
        self.assertIn("some kind of error", self.user.dm_channel.send.await_args.args[0])

    async def test_external_archive_records_reason_without_creating_traceback(self):
        async def audit_log(**kwargs):
            yield Mock(target=self.thread, user=Mock(id=123))

        self.thread.guild.audit_logs = audit_log
        before = self.make_thread(self.thread_id)
        self.thread.archived = True
        with self.assertLogs(level="WARNING"):
            await self.modbot.on_thread_update(before, self.thread)
        self.assert_disconnected()
        self.traceback_channel.send.assert_not_awaited()
        self.assertEqual(self.query("SELECT exception_class, failure_site FROM group_summary"),
                         [(None, "Report thread archived while the report was active")])
        (context,), = self.query("SELECT context FROM events")
        self.assertIn(str(self.thread_id), context)

    async def test_repeated_caller_path_keeps_every_occurrence(self):
        async def record(detail):
            try:
                raise ValueError("broken input")
            except ValueError as error:
                error.add_note(detail)
                return await self.bot.traceback_store.record_exception(
                    error, "test", "".join(traceback.format_exception(error)),
                )

        event_ids = await asyncio.gather(record("first room"), record("second room"))
        self.assertEqual(sorted(event_ids), [1, 2])
        self.assertEqual(self.query("SELECT occurrences, caller_paths FROM group_summary"), [(2, 1)])
        contexts = self.query("SELECT context FROM events ORDER BY context")
        self.assertEqual(contexts, [('["first room"]',), ('["second room"]',)])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
