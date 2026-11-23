"""The slash command may only disclose and schedule posts in its own report forum."""
from unittest.mock import AsyncMock, Mock

import discord

from report_test_support import ReportTestCase, hf


class ResolveAfterCommandTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        state = discord.Client(intents=discord.Intents.none())._connection
        guild_id = self.thread.guild.id
        self.member_id = self.user_id + 1
        self.hidden_member_id = self.user_id + 2
        view_channel = discord.Permissions(view_channel=True).value
        forums = [
            {'id': 100, 'name': 'mod-tickets', 'type': 15, 'position': 0},
            {'id': 200, 'name': 'staff-tickets', 'type': 15, 'position': 1,
             'permission_overwrites': [
                 {'id': self.hidden_member_id, 'type': 1, 'allow': '0', 'deny': str(view_channel)},
             ]},
            {'id': 300, 'name': 'other-forum', 'type': 15, 'position': 2},
            {'id': 400, 'name': 'voice-tickets', 'type': 15, 'position': 3},
        ]
        threads = [
            (101, 100, 'Meta Discussion', False),
            (102, 100, 'Mod ticket', False),
            (201, 200, 'Meta Discussion', False),
            (202, 200, 'Staff ticket', False),
            (203, 200, 'Archived staff ticket', True),
            (301, 300, 'Unrelated post', False),
            (401, 400, 'Meta Discussion', False),
            (402, 400, 'Voice ticket', False),
        ]
        self.guild = discord.Guild(state=state, data={
            'id': guild_id,
            'roles': [{'id': guild_id, 'name': '@everyone', 'permissions': str(view_channel)}],
            'channels': forums,
            'threads': [
                {'id': thread_id, 'parent_id': forum_id, 'name': name, 'type': 11,
                 'owner_id': self.bot.user.id, 'message_count': 0, 'member_count': 0,
                 'thread_metadata': {'archived': archived, 'auto_archive_duration': 1440,
                                     'archive_timestamp': '2026-11-22T00:00:00+00:00'}}
                for thread_id, forum_id, name, archived in threads
            ],
        })
        self.bot.db['guilds'] = {str(guild_id): {
            'channel': 100, 'meta_channel': 101,
            'secondary_channel': '200', 'secondary_meta_channel': '201',
            'voice_report_channel': 400, 'voice_report_meta_channel': 401,
        }}
        self.command = self.resolver.resolve_after

    def interaction(self, thread_id, *, member_id=None):
        member = discord.Member(state=self.guild._state, guild=self.guild, data={
            'user': {'id': member_id or self.member_id, 'username': 'Moderator',
                     'avatar': None, 'discriminator': '0'},
            'roles': [], 'flags': 0,
        })
        return Mock(
            guild=self.guild, channel=self.guild.get_thread(thread_id), channel_id=thread_id,
            user=member, response=Mock(send_message=AsyncMock()),
        )

    async def schedule(self, interaction, **kwargs):
        await self.command.callback(self.resolver, interaction, time='1d', **kwargs)

    async def assert_rejected(self, interaction, **kwargs):
        await self.schedule(interaction, **kwargs)
        self.assertTrue(interaction.response.send_message.await_args.kwargs['ephemeral'])
        self.assertEqual(self.bot.db['scheduled_resolutions'], {self.thread_id: self.entry})
        hf.dump_json.assert_not_awaited()

    def test_post_option_is_optional(self):
        self.assertEqual([(p.name, p.required) for p in self.command.parameters],
                         [('time', True), ('post', False)])

    async def test_omitted_post_schedules_current_ticket_in_each_report_forum(self):
        scheduled = self.bot.db['scheduled_resolutions']
        for thread_id in (102, 202, 402):
            with self.subTest(thread_id=thread_id):
                await self.schedule(self.interaction(thread_id))
                entry = scheduled[thread_id]
                self.assertEqual(entry['requested_by'], self.member_id)
                self.assertEqual(entry['guild_id'], self.guild.id)
                self.assertIs(scheduled[self.thread_id], self.entry)
        self.assertEqual(hf.dump_json.await_count, 3)

    async def test_meta_discussion_can_target_own_forum_and_reporter_reply_cancels(self):
        self.report['thread_id'] = 202
        await self.schedule(self.interaction(201), post='202')
        scheduled = self.bot.db['scheduled_resolutions']
        self.assertIn(202, scheduled)

        await self.resolver.on_message(Mock(
            author=self.user, channel=self.user.dm_channel, type=discord.MessageType.default,
        ))
        self.assertNotIn(202, scheduled)
        self.assertIs(scheduled[self.thread_id], self.entry)

    async def test_autocomplete_only_returns_active_tickets_from_invocation_forum(self):
        for meta_id, ticket_id in ((101, 102), (201, 202), (401, 402)):
            with self.subTest(meta_id=meta_id):
                choices = await self.resolver._post_autocomplete(self.interaction(meta_id), 'Ticket')
                self.assertEqual([choice.value for choice in choices], [str(ticket_id)])
                choices = await self.resolver._post_autocomplete(self.interaction(meta_id), '')
                self.assertEqual([choice.value for choice in choices], [str(ticket_id)])

    async def test_manually_entered_ids_cannot_cross_forums_or_target_ineligible_posts(self):
        for post in ('102', '201', '203', '302', 'not an ID'):
            with self.subTest(post=post):
                await self.assert_rejected(self.interaction(202), post=post)
        await self.assert_rejected(self.interaction(201))

    async def test_unconfigured_or_inaccessible_forum_returns_no_targets(self):
        for interaction in (self.interaction(301), self.interaction(201, member_id=self.hidden_member_id)):
            with self.subTest(channel_id=interaction.channel_id):
                self.assertEqual(await self.resolver._post_autocomplete(interaction, ''), [])
                await self.assert_rejected(interaction, post='202')
