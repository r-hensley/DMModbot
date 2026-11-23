import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

import discord
from discord.ext import commands


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        source = Path(__file__).resolve().parents[1] / "Modbot.py"
        bot_file = self.directory / source.name
        shutil.copyfile(source, bot_file)
        (self.directory / ".env").touch()
        spec = importlib.util.spec_from_file_location("shutdown_test_modbot", bot_file)
        self.module = importlib.util.module_from_spec(spec)
        with (patch.dict(os.environ, BOT_TOKEN="test", DEFAULT_PREFIX="_", OWNER_ID="0"),
              patch.object(discord.utils, "setup_logging")):
            spec.loader.exec_module(self.module)
            self.bot = self.module.Modbot()

        self.hf = self.module.hf
        self.enterContext(patch.object(self.hf, "__file__", str(self.directory / "cogs/utils/helper_functions.py")))
        for name in ("bot", "loop", "dump_json_lock"):
            self.enterContext(patch.object(self.hf, name, None))
        self.database = self.directory / "modbot.json"

    async def test_close_waits_for_cancelled_writer_and_saves_latest_state_once(self):
        started = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        final_save_started = asyncio.Event()
        writes = []
        write = self.hf._dump_json_sync
        dump = self.hf.dump_json

        def delayed_write(snapshot):
            writes.append(snapshot)
            if len(writes) == 1:
                started.set()
                if not release.wait(5):
                    raise TimeoutError("Test did not release the autosave writer")
            write(snapshot)

        async def final_dump():
            final_save_started.set()
            await dump()

        await self.bot.__aenter__()
        self.hf.setup(self.bot, asyncio.get_running_loop())

        class Autosave(commands.Cog):
            def cog_unload(self):
                autosave.cancel()

        with patch.object(self.hf, "_dump_json_sync", delayed_write):
            autosave = asyncio.create_task(dump())
            try:
                await self.bot.add_cog(Autosave())
                self.assertTrue(await asyncio.to_thread(started.wait, 5))
                guild_id = 123456789012345678
                user_id = 234567890123456789
                self.bot.db["guilds"][guild_id] = {"channel": 345678901234567890}
                self.bot.db["reports"][user_id] = {"guild_id": guild_id, "anonymous_reporter": True}

                with patch.object(self.hf, "dump_json", final_dump):
                    close = asyncio.create_task(self.bot.close())
                    await asyncio.wait_for(final_save_started.wait(), 5)
                    self.assertTrue(autosave.cancelled())
                    self.assertTrue(self.hf.dump_json_lock.locked())
                    close.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await close

                    context_exit = asyncio.create_task(self.bot.__aexit__(None, None, None))
                    await asyncio.sleep(0)
                    self.assertFalse(context_exit.done())
                    release.set()
                    await asyncio.wait_for(context_exit, 5)
            finally:
                release.set()
                await self.bot.close()

        self.assertEqual(len(writes), 2)
        self.assertEqual(writes[0]["reports"], {})
        reloaded = self.module.str_keys_to_int_keys(json.loads(self.database.read_text()))
        self.assertEqual(reloaded, self.bot.db)
        self.assertEqual(json.loads((self.directory / "modbot_2.json").read_text())["reports"], {})

    async def test_close_before_helper_setup_leaves_database_alone(self):
        original = '{"reports": {}}\n'
        self.database.write_text(original)

        async with self.bot:
            pass

        self.assertTrue(self.bot.is_closed())
        self.assertEqual(self.database.read_text(), original)
        self.assertFalse((self.directory / "modbot_2.json").exists())

    async def test_save_failure_preserves_database_and_completes_cleanup(self):
        original = '{"reports": {}}\n'
        self.database.write_text(original)
        socket = self.directory / "control" / "control.sock"
        self.bot.control = self.module.BotControl(self.bot, socket, extensions={})

        async with self.bot:
            self.hf.setup(self.bot, asyncio.get_running_loop())
            await self.bot.control.start()
            self.assertTrue(socket.exists())
            with (patch.object(self.hf.os, "replace", side_effect=OSError("test disk failure")),
                  self.assertLogs(self.module.logger, level="ERROR") as log):
                await self.bot.close()

        self.assertTrue(self.bot.is_closed())
        self.assertFalse(socket.exists())
        self.assertEqual(self.database.read_text(), original)
        self.assertIn("Could not save modbot.json during shutdown", log.output[0])
        self.assertIn("test disk failure", log.output[0])
