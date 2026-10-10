"""Shared fixtures for report regression tests without a live Discord connection."""
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import discord

# Keep the tests independent of the bot's optional NLP dependencies and submodule.
test_package = types.ModuleType('_report_recovery_test_cogs')
test_package.__path__ = [str(Path(__file__).resolve().parents[1] / 'cogs')]
utils_package = types.ModuleType('_report_recovery_test_cogs.utils')
utils_package.__path__ = [str(Path(test_package.__path__[0]) / 'utils')]
hf = types.ModuleType('_report_recovery_test_cogs.utils.helper_functions')
hf.EndEarly = type('EndEarly', (Exception,), {})
with patch.dict(sys.modules, {
    test_package.__name__: test_package,
    utils_package.__name__: utils_package,
    hf.__name__: hf,
}):
    modbot_module = importlib.import_module('_report_recovery_test_cogs.modbot')
    status_module = importlib.import_module('_report_recovery_test_cogs.report_status')
    resolve_module = importlib.import_module('_report_recovery_test_cogs.resolve_after')


class ReportTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.thread_id = 123456789012345678
        self.user_id = 234567890123456789
        self.thread = self.make_thread(self.thread_id)
        self.user = Mock(spec=discord.User)
        self.user.id = self.user_id
        self.user.bot = False
        self.user.dm_channel = Mock(spec=discord.DMChannel)
        self.user.dm_channel.send = AsyncMock()
        self.user.send = AsyncMock()
        self.report = {'user_id': self.user_id, 'thread_id': self.thread_id}
        self.entry = {'resolve_at': 0, 'guild_id': self.thread.guild.id}
        self.bot = types.SimpleNamespace(
            db={'reports': {self.user_id: self.report},
                'scheduled_resolutions': {self.thread_id: self.entry}},
            user=types.SimpleNamespace(id=456789012345678901),
            get_channel=Mock(return_value=self.thread),
            fetch_channel=AsyncMock(return_value=self.thread),
            get_user=Mock(return_value=self.user),
            fetch_user=AsyncMock(return_value=self.user),
        )
        self.modbot = modbot_module.Modbot(self.bot)
        self.bot.get_cog = Mock(return_value=self.modbot)
        self.status = status_module.ReportStatus.__new__(status_module.ReportStatus)
        self.status.bot = self.bot
        self.resolver = resolve_module.ResolveAfter.__new__(resolve_module.ResolveAfter)
        self.resolver.bot = self.bot
        hf.dump_json = AsyncMock()
        hf.log_record_of_report = AsyncMock()
        async def archive(thread, finish=False):
            thread.archived = finish
        hf.close_thread = AsyncMock(side_effect=archive)


    def make_thread(self, thread_id, archived=False):
        thread = Mock(spec=discord.Thread)
        thread.id = thread_id
        thread.guild.id = 345678901234567890
        thread.archived = archived
        thread.send = AsyncMock()
        return thread


    def http_error(self, error_type=discord.Forbidden):
        status = 404 if error_type is discord.NotFound else 403
        return error_type(Mock(status=status, reason='Test response'), 'Test failure')


    async def tick(self):
        await resolve_module.ResolveAfter.resolve_after_loop.coro(self.resolver)


    def assert_disconnected(self):
        self.assertNotIn(self.user_id, self.bot.db['reports'])
        self.assertIn(self.user_id, self.bot.recently_in_report_room)
        hf.log_record_of_report.assert_awaited_once_with(self.thread, self.user)
