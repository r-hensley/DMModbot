# DMModBot

DM Modbot connects Discord users with server staff for reports, questions,
and ban appeals through direct messages.

### Terms and privacy

- [Terms of Service](TERMS.md)
- [Privacy Policy](PRIVACY.md)

For support or privacy requests, contact **ryry013** on Discord.

### Cloning the Repo

This repo uses git submodules, so when cloning be sure to use:

```bash
git clone --recurse-submodules
```

### Running the bot

1. Create venv if you don't have it already
   ```bash
   python3 -m venv .venv
   ```
2. Activate
   ```bash
   source ./.venv/bin/activate
   ```
3. Install dependencies

   ```bash
   python3 -m pip install -r requirements.txt
   ```

   (When using the master branch of discord.py, you also need `python -m pip install -U git+https://github.com/Rapptz/discord.py`)

4. Copy the config sample file and fill it in
   ```bash
   cp config.example.py config.py
   ```
5. Run
   ```bash
   python3 Modbot.py
   ```

### Local bot controls

On the bot host, set `DMMODBOT_CONTROL_SOCKET` in the bot's `.env` or service
environment to an absolute Unix socket path in a directory owned by the bot's OS
user with mode `0700`, then restart the bot once. For example, use
`/home/bot/.dmmodbot-control/control.sock` if the bot runs as `bot`. An unset
variable leaves the listener disabled.

From a shell on the bot host running as that same OS user:

```bash
python3 -m cogs.utils.BotUtils.bot_control --socket /home/bot/.dmmodbot-control/control.sock status
python3 -m cogs.utils.BotUtils.bot_control --socket /home/bot/.dmmodbot-control/control.sock reload hf report_intake modbot report_status
python3 -m cogs.utils.BotUtils.bot_control --socket /home/bot/.dmmodbot-control/control.sock unload report_status
python3 -m cogs.utils.BotUtils.bot_control --socket /home/bot/.dmmodbot-control/control.sock load report_status
```

The shared [BotUtils control module](cogs/utils/BotUtils/bot_control.py)
only accepts the bot's shipped extensions and the two named reload
helpers. Pull or copy the code onto the host before reloading. Reload
`report_intake` before `modbot` when both files changed. If a crash leaves the
socket behind, remove it after verifying that the bot process has stopped.
