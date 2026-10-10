"""Recover uncached and archived threads before disconnecting open reports."""
import unittest

import discord

from report_test_support import ReportTestCase, hf, resolve_module, status_module


class ReportRecoveryTests(ReportTestCase):
    async def test_cleanup_fetches_uncached_active_thread_without_closing_it(self):
        self.bot.get_channel.return_value = None
        self.assertFalse(await self.status.prune_stale_reports())
        self.bot.fetch_channel.assert_awaited_once_with(self.thread_id)
        self.assertIs(self.bot.db['reports'][self.user_id], self.report)
        hf.close_thread.assert_not_awaited()
        self.user.dm_channel.send.assert_not_awaited()


    async def test_cleanup_recovers_archived_thread_and_notifies_reporter(self):
        self.bot.get_channel.return_value = None
        self.thread.archived = True
        self.assertTrue(await self.status.prune_stale_reports())
        self.bot.fetch_channel.assert_awaited_once_with(self.thread_id)
        self.assert_disconnected()
        self.user.dm_channel.send.assert_awaited_once()
        self.assertIn('closed the room', self.user.dm_channel.send.call_args.args[0])
        hf.close_thread.assert_awaited_once_with(self.thread, True)
        self.assertFalse(await self.status.prune_stale_reports())
        self.user.dm_channel.send.assert_awaited_once()


    async def test_cleanup_closes_cached_archived_report(self):
        self.thread.archived = True
        self.assertTrue(await self.status.prune_stale_reports())
        self.bot.fetch_channel.assert_not_awaited()
        self.assert_disconnected()
        self.user.dm_channel.send.assert_awaited_once()


    async def test_cleanup_preserves_report_after_lookup_permission_error(self):
        self.bot.get_channel.return_value = None
        self.bot.fetch_channel.side_effect = self.http_error()
        with self.assertLogs(status_module.logger, level='WARNING'):
            self.assertFalse(await self.status.prune_stale_reports())
        self.assertIs(self.bot.db['reports'][self.user_id], self.report)
        hf.close_thread.assert_not_awaited()


    async def test_cleanup_removes_confirmed_deleted_thread(self):
        self.bot.get_channel.return_value = None
        self.bot.fetch_channel.side_effect = self.http_error(discord.NotFound)
        self.assertTrue(await self.status.prune_stale_reports())
        self.assertNotIn(self.user_id, self.bot.db['reports'])
        hf.close_thread.assert_not_awaited()


    async def test_cleanup_retains_report_when_archiving_fails(self):
        self.thread.archived = True
        hf.close_thread.side_effect = self.http_error()
        with self.assertLogs(status_module.logger, level='WARNING'):
            self.assertFalse(await self.status.prune_stale_reports())
        self.assertIs(self.bot.db['reports'][self.user_id], self.report)
        hf.log_record_of_report.assert_not_awaited()


    async def test_timer_recovers_archived_open_report_and_completes_lifecycle(self):
        self.bot.get_channel.return_value = None
        self.thread.archived = True
        await self.tick()
        self.bot.fetch_channel.assert_awaited_once_with(self.thread_id)
        self.assert_disconnected()
        self.user.send.assert_awaited_once()
        self.assertEqual(self.user.send.call_args.kwargs['embed'].title, 'Ticket Closed')
        self.assertNotIn(self.thread_id, self.bot.db['scheduled_resolutions'])
        self.user.dm_channel.send.assert_not_awaited()  # Avoid a second closure notice.


    async def test_timer_fetches_uncached_active_report(self):
        self.bot.get_channel.return_value = None
        await self.tick()
        self.assert_disconnected()
        self.assertTrue(self.thread.archived)
        self.assertNotIn(self.thread_id, self.bot.db['scheduled_resolutions'])


    async def test_already_closed_archived_ticket_gets_no_second_notification(self):
        self.thread.archived = True
        await self.status.prune_stale_reports()
        self.user.dm_channel.send.assert_awaited_once()
        self.thread.send.reset_mock()
        hf.close_thread.reset_mock()
        await self.tick()
        self.user.send.assert_not_awaited()
        self.thread.send.assert_not_awaited()
        hf.close_thread.assert_not_awaited()
        self.assertNotIn(self.thread_id, self.bot.db['scheduled_resolutions'])


    async def test_timer_keeps_schedule_after_lookup_permission_error(self):
        self.bot.get_channel.return_value = None
        self.bot.fetch_channel.side_effect = self.http_error()
        with self.assertLogs(resolve_module.logger, level='WARNING'):
            await self.tick()
        self.assertIs(self.bot.db['scheduled_resolutions'][self.thread_id], self.entry)
        self.user.send.assert_not_awaited()
        hf.close_thread.assert_not_awaited()


    async def test_deleted_thread_schedule_is_removed(self):
        self.bot.get_channel.return_value = None
        self.bot.fetch_channel.side_effect = self.http_error(discord.NotFound)
        await self.tick()
        self.assertNotIn(self.thread_id, self.bot.db['scheduled_resolutions'])
        self.user.send.assert_not_awaited()


    async def test_cancelled_timer_during_lookup_does_not_close_ticket(self):
        self.bot.get_channel.return_value = None
        async def fetch(thread_id):
            del self.bot.db['scheduled_resolutions'][thread_id]
            return self.thread
        self.bot.fetch_channel.side_effect = fetch
        await self.tick()
        hf.close_thread.assert_not_awaited()
        self.user.send.assert_not_awaited()
        self.assertIs(self.bot.db['reports'][self.user_id], self.report)


    async def test_replaced_timer_during_lookup_is_preserved(self):
        self.bot.get_channel.return_value = None
        replacement = {'resolve_at': 9999999999, 'guild_id': self.thread.guild.id}
        async def fetch(thread_id):
            self.bot.db['scheduled_resolutions'][thread_id] = replacement
            return self.thread
        self.bot.fetch_channel.side_effect = fetch
        await self.tick()
        hf.close_thread.assert_not_awaited()
        self.user.send.assert_not_awaited()
        self.assertIs(self.bot.db['scheduled_resolutions'][self.thread_id], replacement)


    async def test_normal_report_closure_cancels_its_timer(self):
        from report_test_support import modbot_module
        await self.modbot.end_report(
            modbot_module.OpenReport(self.report, self.user, self.thread,
                                     self.user.dm_channel, self.thread),
            error=False,
        )
        self.assert_disconnected()
        self.assertNotIn(self.thread_id, self.bot.db['scheduled_resolutions'])
        self.user.dm_channel.send.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
