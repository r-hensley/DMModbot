import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord.ext import tasks

from cogs.modbot import Modbot, OpenReport
from cogs.report_intake import CloseReportView, DraftModal, TRACE_SECONDS, trace_flow
from cogs.report_status import ReportStatus, ThreadStats
from cogs.utils import helper_functions as hf


class ReportIntakeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.user = SimpleNamespace(id=4123, name="ReporterName", mention="<@4123>")
        self.card = SimpleNamespace(id=2, delete=AsyncMock(), edit=AsyncMock())
        self.user.dm_channel = SimpleNamespace(send=AsyncMock(return_value=self.card))
        self.user.dm_channel.get_partial_message = Mock(return_value=self.card)
        self.message = self.message_with("hi")
        self.guild = SimpleNamespace(id=8732, name="Shared Server", me=object())
        self.guild.get_member = Mock(return_value=self.user)
        self.thread = SimpleNamespace(id=4477, guild=self.guild, mention="<#4477>", send=AsyncMock(),
                                      archived=False, locked=False, edit=AsyncMock())
        marker = SimpleNamespace(create_thread=AsyncMock(return_value=self.thread), add_reaction=AsyncMock())
        self.staff = SimpleNamespace(id=8080, guild=self.guild, send=AsyncMock(return_value=marker),
                                     permissions_for=Mock(return_value=SimpleNamespace(
                                         read_messages=False, send_messages=True, create_public_threads=True,
                                     )))
        self.thread.parent = self.staff
        self.bot = SimpleNamespace(
            db={"guilds": {self.guild.id: {"channel": self.staff.id}}, "reports": {},
                "recent_reports": {self.guild.id: {self.user.id: [{"thread_id": 321, "timestamp": 0}]}}},
            guilds=[self.guild],
            get_channel={self.staff.id: self.staff, self.thread.id: self.thread}.get,
            get_guild={self.guild.id: self.guild}.get,
        )
        self.marker = marker
        self.cog = Modbot(self.bot)
        self.enterContext(patch.object(hf.here, "bot", self.bot))
        self.save = self.enterContext(patch.object(hf, "dump_json", new_callable=AsyncMock))

    def message_with(self, text):
        return SimpleNamespace(author=self.user, channel=self.user.dm_channel, content=text,
                               attachments=[], embeds=[], stickers=[], add_reaction=AsyncMock())

    def interaction(self, **data):
        return SimpleNamespace(user=self.user, message=self.card, data=data, channel=self.user.dm_channel,
                               locale=discord.Locale.spain_spanish,
                               response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(),
                                                        send_modal=AsyncMock()))

    async def test_language_is_saved_when_welcome_is_replaced(self):
        await self.cog.receive_users(self.message)
        intake = self.cog.intakes[self.user.id]
        self.assertEqual(intake.draft, "")
        welcome = intake.view.to_components()[0]["components"][0]["content"]
        self.assertEqual(len(welcome.splitlines()), 6)
        self.assertEqual(welcome.splitlines()[0], "__**Push this button to start.**__")
        self.assertIn("Appuie sur ce bouton", welcome)
        self.assertIn("اضغط على هذا الزر", welcome)
        self.assertIn("点击此按钮开始", welcome)
        self.assertFalse(await intake.view.interaction_check(SimpleNamespace(user=SimpleNamespace(id=9))))
        self.card.delete.side_effect = lambda: self.save.assert_awaited_once()

        await intake.begin(self.interaction())

        self.assertEqual(self.bot.db["user_localizations"][self.user.id], "es")
        self.card.delete.assert_awaited_once()
        self.assertEqual(self.user.dm_channel.send.await_count, 2)
        form = repr(intake.view.to_components())
        self.assertIn("Contactar con moderación", form)
        self.assertIn("Reportar de forma anónima · No", form)
        self.assertNotIn("Idioma", form)
        self.staff.send.assert_not_awaited()
        await intake.view.on_timeout()
        self.assertNotIn(self.user.id, self.cog.intakes)

    async def test_anonymous_report_keeps_the_reply_route_without_staff_identity_fields(self):
        await self.cog.receive_users(self.message)
        intake = self.cog.intakes[self.user.id]
        await intake.begin(self.interaction())
        await self.cog.receive_users(self.message_with("Issue details"))
        await intake.select_topic(self.interaction(values=["report"]))
        await intake.toggle_anonymous(self.interaction())
        self.assertEqual(DraftModal(intake).draft.default, "Issue details")

        await intake.submit(self.interaction())
        # A second click on the old button must not create another thread.
        await intake.submit(self.interaction())

        self.marker.create_thread.assert_awaited_once()
        self.assertIn("Anonymous report", self.marker.create_thread.call_args.kwargs["name"])
        for label in (self.user.name, self.user.mention, "Recent reports"):
            self.assertNotIn(label, repr(self.staff.send.call_args_list))
            self.assertNotIn(label, repr(self.thread.send.call_args_list))
        self.assertIn(">>> Anonymous reporter: Issue details", repr(self.thread.send.call_args_list))
        report = self.bot.db["reports"][self.user.id]
        self.assertTrue(report["anonymous_reporter"])
        with patch.object(tasks.Loop, "start"):
            summary = ReportStatus(self.bot).format_thread_summary(
                ThreadStats(thread=self.thread, thread_info=report, user=None)
            )
        self.assertIn("Anonymous reporter", summary)
        self.assertNotIn(self.user.mention, summary)

        followup = self.message_with("More details")
        open_report = OpenReport(report, self.user, self.thread, self.user.dm_channel, self.thread)
        content, _ = await self.cog.process_msg_content(followup, open_report)
        self.assertEqual(content, ">>> Anonymous reporter: More details")

        view = CloseReportView(self.cog)
        self.assertTrue(view.is_persistent())
        prompt = self.interaction()
        await view.ask(prompt)
        confirm = prompt.response.send_message.call_args.kwargs["view"].children[0]
        result = self.interaction()
        result.delete_original_response = AsyncMock()
        await confirm.callback(result)
        self.assertNotIn(self.user.id, self.bot.db["reports"])
        self.assertEqual(len(self.bot.db["recent_reports"][self.guild.id][self.user.id]), 1)
        self.assertIn("Conversación cerrada", repr(self.card.edit.call_args.kwargs["view"].to_components()))
        notice = self.user.dm_channel.send.call_args.args[0]
        self.assertTrue(notice.startswith(f"**\u2800\n\n\n__{' ' * 70}__**\n"))
        self.assertIn("**Esta conversación se ha cerrado.", notice)
        self.assertIn("envía un nuevo mensaje aquí para iniciar otro reporte.**", notice)

    async def test_block_is_rechecked_at_submission(self):
        await self.cog.receive_users(self.message_with("A report draft"))
        intake = self.cog.intakes[self.user.id]
        await intake.begin(self.interaction())
        await intake.select_topic(self.interaction(values=["voice"]))
        self.bot.db["blocked_users"] = {self.guild.id: [self.user.id]}

        await intake.submit(self.interaction())

        self.staff.send.assert_not_awaited()
        self.assertEqual(self.bot.db["reports"], {})
        self.assertNotIn(self.user.id, self.cog.intakes)

    async def test_temporary_trace_reports_failed_open_without_private_payload(self):
        with TemporaryDirectory() as directory:
            flag = Path(directory) / "report-flow-debug"
            flag.touch()
            with patch("cogs.report_intake.TRACE_FLAG", flag):
                with self.assertLogs("cogs.report_intake", level="INFO") as logs:
                    await self.cog.receive_users(self.message_with("PRIVATE DRAFT"))
                    intake = self.cog.intakes[self.user.id]
                    await intake.begin(self.interaction())
                    await intake.select_topic(self.interaction(values=["report"]))
                    with patch.object(hf, "create_report_thread", side_effect=RuntimeError("PRIVATE ERROR")):
                        with self.assertRaises(RuntimeError):
                            await intake.submit(self.interaction())

                output = "\n".join(logs.output)
                self.assertIn(f"event=welcome_sent attempt={intake.attempt}", output)
                self.assertIn(f"event=open_report_error attempt={intake.attempt}", output)
                self.assertIn("stage=create_thread", output)
                self.assertNotIn("PRIVATE", output)
                self.assertNotIn(self.user.name, output)
                self.assertNotIn(self.user.mention, output)
                self.assertNotIn("event=report_opened", output)

                stale = time() - TRACE_SECONDS - 1
                os.utime(flag, (stale, stale))
                with self.assertNoLogs("cogs.report_intake", level="INFO"):
                    trace_flow("report_opened")
