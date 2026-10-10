"""Reporter replies cancel timers regardless of the forwarded message format."""
import unittest
from unittest.mock import Mock

import discord

from report_test_support import ReportTestCase, hf


class ReportReplyTests(ReportTestCase):
    def reply(self, content='', **kwargs):
        return Mock(author=self.user, channel=self.user.dm_channel, guild=None,
                    type=discord.MessageType.default, content=content, **kwargs)

    async def test_text_reply_cancels_timer(self):
        await self.resolver.on_message(self.reply(content='Here is more information'))
        self.assertNotIn(self.thread_id, self.bot.db['scheduled_resolutions'])
        hf.dump_json.assert_awaited_once()

    async def test_attachment_embed_and_sticker_only_replies_cancel_timer(self):
        for field in ('attachments', 'embeds', 'stickers'):
            with self.subTest(field=field):
                self.bot.db['scheduled_resolutions'][self.thread_id] = self.entry
                await self.resolver.on_message(self.reply(**{field: [Mock()]}))
                self.assertNotIn(self.thread_id, self.bot.db['scheduled_resolutions'])

    async def test_discord_reply_message_cancels_timer(self):
        message = self.reply()
        message.type = discord.MessageType.reply
        await self.resolver.on_message(message)
        self.assertNotIn(self.thread_id, self.bot.db['scheduled_resolutions'])

    async def test_bot_dm_does_not_cancel_timer(self):
        message = self.reply()
        message.author = Mock(id=self.user_id, bot=True)
        await self.resolver.on_message(message)
        self.assertIs(self.bot.db['scheduled_resolutions'][self.thread_id], self.entry)
        hf.dump_json.assert_not_awaited()

    async def test_staff_and_bot_thread_messages_do_not_cancel_timer(self):
        for author in (self.user, Mock(id=self.bot.user.id, bot=True)):
            with self.subTest(author=author.id):
                message = self.reply(content='>>> thread discussion')
                message.channel = self.thread
                message.guild = self.thread.guild
                message.author = author
                await self.resolver.on_message(message)
                self.assertIs(self.bot.db['scheduled_resolutions'][self.thread_id], self.entry)

    async def test_unrelated_users_do_not_cancel_timer(self):
        message = self.reply()
        message.author = Mock(id=self.user_id + 1, bot=False)
        await self.resolver.on_message(message)
        self.assertIs(self.bot.db['scheduled_resolutions'][self.thread_id], self.entry)

    async def test_system_message_does_not_cancel_timer(self):
        message = self.reply()
        message.type = discord.MessageType.pins_add
        await self.resolver.on_message(message)
        self.assertIs(self.bot.db['scheduled_resolutions'][self.thread_id], self.entry)

    async def test_repeated_reply_after_cancellation_is_harmless(self):
        await self.resolver.on_message(self.reply())
        await self.resolver.on_message(self.reply())
        hf.dump_json.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
