"""Report-specific guidance must survive saving and restarting the bot."""
from datetime import datetime, timedelta, timezone
import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import discord

# Import the production cog with isolated storage/network collaborators.
test_package = types.ModuleType('_report_guidance_test_cogs')
test_package.__path__ = [str(Path(__file__).resolve().parents[1] / 'cogs')]
utils_package = types.ModuleType('_report_guidance_test_cogs.utils')
utils_package.__path__ = [str(Path(test_package.__path__[0]) / 'utils')]
hf = types.ModuleType('_report_guidance_test_cogs.utils.helper_functions')
hf.EndEarly = type('EndEarly', (Exception,), {})
with patch.dict(sys.modules, {
    test_package.__name__: test_package,
    utils_package.__name__: utils_package,
    hf.__name__: hf,
}):
    modbot_module = importlib.import_module('_report_guidance_test_cogs.modbot')
    db_module = importlib.import_module('_report_guidance_test_cogs.utils.db_utils')


class ReportGuidanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user_id = 234567890123456789
        self.thread_id = 123456789012345678
        self.user = Mock(spec=discord.User)
        self.user.id = self.user_id
        self.user.bot = False
        self.user.dm_channel = Mock(spec=discord.DMChannel)
        self.user.dm_channel.send = AsyncMock()
        self.user.send = self.user.dm_channel.send
        self.user.dm_channel.typing = AsyncMock()
        self.thread = Mock(spec=discord.Thread)
        self.thread.id = self.thread_id
        self.thread.guild.id = 345678901234567890
        self.thread.send = AsyncMock()
        self.guild = self.thread.guild
        self.bot = types.SimpleNamespace(db={'reports': {}, 'guilds': {}})
        self.now = datetime(2026, 11, 22, tzinfo=timezone.utc)
        self.enterContext(patch.object(discord.utils, 'utcnow', side_effect=lambda: self.now))
        self.cog = modbot_module.Modbot(self.bot)
        self.saved_json = None
        async def save():
            self.saved_json = json.dumps(self.bot.db)
        hf.dump_json = AsyncMock(side_effect=save)
        async def add_report(author, thread, room_type, *, report_kind, followup_due_at, **kwargs):
            self.bot.db['reports'][author.id] = {
                'user_id': author.id, 'thread_id': thread.id,
                'guild_id': thread.guild.id, 'report_room_type': room_type,
                'mods': [], 'not_anonymous': False, 'report_kind': report_kind,
                'followup_due_at': followup_due_at, 'followup_answered': False,
            }
            await hf.dump_json()
        hf.add_report_to_db = AsyncMock(side_effect=add_report)
        hf.get_report_variables = AsyncMock(return_value=(Mock(spec=discord.ForumChannel), Mock()))
        hf.check_bot_perms = AsyncMock()
        hf.deny_new_user_role_request = AsyncMock()
        hf.create_report_thread = AsyncMock(return_value=self.thread)
        hf.repost_rai_modlog = AsyncMock()
        hf.deliver_report_draft = AsyncMock()
        hf.forward_report_media = AsyncMock()
        hf.reporter_label = lambda author, _anonymous: author.mention
        hf.try_add_reaction = AsyncMock()
        hf.check_if_valid_msg = AsyncMock(return_value=True)
        hf.get_user_locale = Mock(return_value='en')

    async def open_and_restart(self, report_kind):
        await self.cog.start_report_room(
            self.user, self.guild, [Mock(content='My initial report message')], 'My initial report message', 'main',
            report_kind=report_kind,
        )
        reloaded_db = db_module.str_keys_to_int_keys(json.loads(self.saved_json))
        self.assertEqual(reloaded_db['reports'][self.user_id].get('report_kind'), report_kind)
        self.bot.db = reloaded_db
        self.cog = modbot_module.Modbot(self.bot)
        return modbot_module.OpenReport(
            reloaded_db['reports'][self.user_id], self.user, self.thread,
            self.user.dm_channel, self.thread,
        )

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)

    async def relay(self, report, *, staff=False):
        sender = Mock(id=self.user_id + 1) if staff else self.user
        if staff:
            report = modbot_module.OpenReport(report.thread_info, self.user, self.thread,
                                              self.thread, self.user.dm_channel)
        message = Mock(author=sender, content='Here are more details', embeds=[], attachments=[], stickers=[])
        await self.cog.send_message(message, report)

    async def test_user_report_reminder_requires_a_later_message_and_is_sent_once(self):
        report = await self.open_and_restart('report_user')
        self.advance(30)
        await self.relay(report)
        self.advance(59)
        await self.relay(report)
        self.user.send.assert_not_awaited()

        self.advance(60)
        self.user.send.assert_not_awaited()
        await self.relay(report)
        self.user.send.assert_awaited_once()
        embed = self.user.send.call_args.kwargs['embed']
        self.assertEqual(embed.title, 'Ticket Information')
        self.assertIn('reported user’s username', embed.description)

        self.advance(60)
        await self.relay(report)
        self.user.send.assert_awaited_once()

    async def test_late_account_question_gets_generic_guidance_after_restart(self):
        report = await self.open_and_restart('account_question')
        self.advance(120)
        self.user.send.assert_not_awaited()
        await self.relay(report)
        embed = self.user.send.call_args.kwargs['embed']
        self.assertIn('Please be patient', embed.description)
        self.assertNotIn('reported user’s username', embed.description)

    async def test_unsupported_language_falls_back_to_english_on_late_message(self):
        hf.get_user_locale.return_value = 'unsupported'
        report = await self.open_and_restart(None)
        self.advance(60)
        await self.relay(report)
        embed = self.user.send.call_args.kwargs['embed']
        self.assertIn('Please be patient', embed.description)
        self.assertNotIn('reported user’s username', embed.description)

    async def test_late_reporter_followup_uses_saved_language(self):
        hf.get_user_locale.return_value = 'es'
        report = await self.open_and_restart('report_user')
        self.advance(60)
        await self.relay(report)
        embed = self.user.send.call_args.kwargs['embed']
        self.assertEqual(embed.title, 'Información del reporte')
        self.assertIn('Ten paciencia', embed.description)

    async def test_staff_reply_suppresses_reminder_for_the_rest_of_the_report(self):
        report = await self.open_and_restart('report_user')
        self.advance(30)
        await self.relay(report, staff=True)
        self.user.send.reset_mock()

        self.advance(60)
        await self.relay(report)
        self.advance(60)
        await self.relay(report)
        self.user.send.assert_not_awaited()

    async def test_closed_report_has_no_reminder(self):
        report = await self.open_and_restart('report_user')
        self.bot.db['reports'].clear()
        self.advance(60)
        await self.relay(report)
        self.user.send.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
