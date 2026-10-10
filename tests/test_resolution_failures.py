"""One failed closure must not disable other ticket timers."""
import unittest
from unittest.mock import AsyncMock

from report_test_support import ReportTestCase, hf, resolve_module


class ResolutionFailureTests(ReportTestCase):
    async def test_one_failed_closure_does_not_stop_other_due_tickets(self):
        other = self.make_thread(self.thread_id + 1)
        other_entry = {'resolve_at': 0, 'guild_id': other.guild.id}
        self.bot.db['scheduled_resolutions'][other.id] = other_entry
        self.bot.get_channel.side_effect = lambda thread_id: self.thread if thread_id == self.thread_id else other
        async def archive(thread, finish=False):
            if thread is self.thread:
                raise self.http_error()
            thread.archived = finish
        hf.close_thread.side_effect = archive
        with self.assertLogs(resolve_module.logger, level='WARNING'):
            await self.tick()
        self.assertIs(self.bot.db['scheduled_resolutions'][self.thread_id], self.entry)
        self.assertIs(self.bot.db['reports'][self.user_id], self.report)
        self.assertNotIn(other.id, self.bot.db['scheduled_resolutions'])
        self.assertTrue(other.archived)


    async def test_failed_closure_is_retried_on_the_next_tick(self):
        hf.close_thread.side_effect = self.http_error()
        with self.assertLogs(resolve_module.logger, level='WARNING'):
            await self.tick()
        self.assertIs(self.bot.db['scheduled_resolutions'][self.thread_id], self.entry)
        async def archive(thread, finish=False):
            thread.archived = finish
        hf.close_thread.side_effect = archive
        await self.tick()
        self.assertNotIn(self.thread_id, self.bot.db['scheduled_resolutions'])
        self.assertTrue(self.thread.archived)

    async def test_new_schedule_created_during_closure_is_preserved(self):
        replacement = {'resolve_at': 9999999999}
        async def reschedule(thread_id, entry):
            self.bot.db['scheduled_resolutions'][thread_id] = replacement
            return True
        self.resolver._resolve_ticket = AsyncMock(side_effect=reschedule)
        await self.tick()
        self.assertIs(self.bot.db['scheduled_resolutions'][self.thread_id], replacement)


if __name__ == '__main__':
    unittest.main()
