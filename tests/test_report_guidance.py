"""Report-specific guidance must survive saving and restarting the bot."""
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
        self.user.dm_channel.typing = AsyncMock()
        self.thread = Mock(spec=discord.Thread)
        self.thread.id = self.thread_id
        self.thread.guild.id = 345678901234567890
        self.thread.send = AsyncMock()
        self.guild = self.thread.guild
        self.bot = types.SimpleNamespace(db={'reports': {}}, pending_report_kind={})
        self.cog = modbot_module.Modbot(self.bot)
        self.saved_json = None
        async def save():
            self.saved_json = json.dumps(self.bot.db)
        hf.dump_json = AsyncMock(side_effect=save)
        async def add_report(author, thread, room_type):
            self.bot.db['reports'][author.id] = {
                'user_id': author.id, 'thread_id': thread.id,
                'guild_id': thread.guild.id, 'report_room_type': room_type,
                'mods': [], 'not_anonymous': False,
            }
            await hf.dump_json()
        hf.add_report_to_db = AsyncMock(side_effect=add_report)
        hf.get_report_variables = AsyncMock(return_value=(Mock(spec=discord.ForumChannel), Mock()))
        hf.check_bot_perms = AsyncMock()
        hf.deny_new_user_role_request = AsyncMock()
        hf.create_report_thread = AsyncMock(return_value=self.thread)
        hf.repost_rai_modlog = AsyncMock()
        hf.deliver_first_report_msg_to_thread = AsyncMock()
        hf.notify_user_of_report_connection = AsyncMock()
        hf.try_add_reaction = AsyncMock()
        hf.check_if_valid_msg = AsyncMock(return_value=True)

    async def open_and_restart(self, report_kind):
        if report_kind is not None:
            self.bot.pending_report_kind[self.user_id] = report_kind
        with patch.object(modbot_module.asyncio, 'sleep', new=AsyncMock()):
            await self.cog.start_report_room(
                self.user, self.guild, Mock(content='My initial report message'), 'main',
            )
        reloaded_db = db_module.str_keys_to_int_keys(json.loads(self.saved_json))
        self.assertEqual(reloaded_db['reports'][self.user_id].get('report_kind'), report_kind)
        self.bot.db = reloaded_db
        self.cog = modbot_module.Modbot(self.bot)
        report = modbot_module.OpenReport(
            reloaded_db['reports'][self.user_id], self.user, self.thread,
            self.user.dm_channel, self.thread,
        )
        message = Mock(author=self.user, content='Here are more details',
                       embeds=[], attachments=[], stickers=[])
        await self.cog.send_message(message, report)
        self.user.dm_channel.send.assert_awaited_once()
        return self.user.dm_channel.send.call_args.kwargs['embed']

    async def test_user_report_retains_evidence_guidance_after_restart(self):
        embed = await self.open_and_restart('report_user')
        self.assertEqual(embed.title, 'Ticket Information')
        self.assertIn('username of the user', embed.description)
        self.assertIn('Text or image evidence', embed.description)

    async def test_account_question_retains_generic_guidance_after_restart(self):
        embed = await self.open_and_restart('account_question')
        self.assertIn('Please be patient', embed.description)
        self.assertNotIn('username of the user', embed.description)

    async def test_report_without_a_kind_retains_generic_guidance_after_restart(self):
        embed = await self.open_and_restart(None)
        self.assertIn('Please be patient', embed.description)
        self.assertNotIn('username of the user', embed.description)


if __name__ == '__main__':
    unittest.main()
