# DMModbot admin guide

## Install and configure the bot

Clone the repository with its BotUtils submodule and run the bot from the checkout. Use Python 3.11 or later.

```bash
git clone --recurse-submodules git@github.com:r-hensley/DMModbot.git
cd DMModbot
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

If you already cloned the repo, run `git submodule update --init --recursive`.
Invite the bot to your server with the `bot` and `applications.commands` scopes. Enable the **Server Members Intent** and **Message Content Intent** in the Discord Developer Portal.

Create a private `.env` alongside `Modbot.py` with these settings.

| Setting | Value |
| --- | --- |
| `BOT_TOKEN` | Token from the Discord Developer Portal. Keep it private. |
| `DEFAULT_PREFIX` | Prefix for text commands. The examples use `_`. |
| `OWNER_ID` | Discord user ID for the owner of a self-hosted bot. |
| `LOG_CHANNEL_ID` | Channel ID for startup and bot logs. The bot must be able to post there. |
| `TRACEBACK_LOGGING_CHANNEL` | Private channel ID for error diagnostics. |
| `BAN_APPEALS_GUILD_ID` | Optional appeal server ID. Use `0` or omit it when appeals are disabled. |
| `$socket_env` | Optional absolute path for the local control socket. |

Start the bot with `.venv/bin/python Modbot.py`. The bot owner can run `_sync` in Discord to publish slash commands after setup or after a command signature changes. Use Discord’s app command permissions to grant moderation commands to the appropriate roles and channels.

## Set up report rooms

1. Restrict the report channel or forum to the bot and the staff who should handle its tickets. Give the bot access to view the channel, read history, post, and create and manage threads. Give it **Manage Channels** during forum setup so it can create tags.
2. For a text channel, run `_setup` there to initialize the server entry, then `_setmodrole Moderators` using the exact role name, then `_setup` again to save the room.
3. For a forum, the bot owner can run `_setup_forum <forum_id> main` from that server to create or reuse the pinned **$meta_post** post and set up tags. Set the mod role with `_setmodrole Moderators`. A server admin can also create a **$meta_post** post manually and run the same `_setup`, `_setmodrole`, `_setup` sequence inside it.
4. After configuring the main room, use `_setup secondary` or `_setup voice` in the corresponding text channel or inside its forum’s **$meta_post** post. The owner can use `_setup_forum <forum_id> secondary` or `_setup_forum <forum_id> voice` to provision those forums.

Send a test report from a member account. Check that it reaches the intended room and that a staff reply reaches the member’s DM.

### DM report routing

| Topic | Report room |
| --- | --- |
$routing_rows

Ordinary reports for an unconfigured secondary or voice room go to the main room. Voice access requests require a dedicated secondary room in the server where that feature is enabled.

## Manage tickets

- Reply from the ticket thread to reach the reporter by DM. Start a staff-only message with `>>> ` to keep it in the thread.
- Type `end` or `close` to end the conversation. Type `finish` from the staff thread to mark it resolved and archive it.
- Run `/resolve_after time:1d` inside a ticket to schedule closure. From **$meta_post**, specify `post` to select a ticket in that same forum. A reporter reply cancels the timer.
- Use `/block` with either a member or a user ID to toggle that user’s access to the report room.
- Use `_clear` only when recovering server report state. It removes the server’s active report mappings and disconnects their DM relay.

### Discord commands

The prefix `_` follows the example configuration. Brackets around slash options indicate optional arguments. `/create_report_button` is registered only in the guilds configured in the code.

| Command | Purpose |
| --- | --- |
$command_rows

## Control the bot on its host

Set `$socket_env` before starting the process. Use an absolute path whose parent is owned by the bot’s OS user with mode `0700`. For systemd, set the same variable in the service environment. The socket starts with the bot and stays disabled when the variable is unset.

Run the control CLI from the checkout as the bot’s OS user, using the bot’s virtual environment and the configured socket path.

```bash
.venv/bin/python -m cogs.utils.BotUtils.bot_control --socket /path/to/control.sock status
.venv/bin/python -m cogs.utils.BotUtils.bot_control --socket /path/to/control.sock reload resolve_after
.venv/bin/python -m cogs.utils.BotUtils.bot_control --socket /path/to/control.sock unload report_status
.venv/bin/python -m cogs.utils.BotUtils.bot_control --socket /path/to/control.sock load report_status
```

Update the checkout and its BotUtils pin before reloading. Verify the result with `status`. For a coordinated report update, keep affected targets in this order: `hf report_intake modbot report_status`. Reloading `modbot` clears in-progress drafts.

## State and troubleshooting

- `modbot.json` stores guild configuration, open tickets, and scheduled closures. Startup snapshots go to `database_backups/`. Keep these files private and save them before changing deployments.
- `tracebacks.db` stores diagnostic events. Match the ID from the Discord error message to `events.id`. Open the archive read-only and start with the `group_summary` view. Treat traceback contents as private.
- If reports fail to open, check that the bot can see and post in the destination, can manage its threads, and can find the configured **$meta_post** post. Then check the traceback channel and service logs.

## Update these guides

Edit the [templates](docs/) when the walkthroughs need to change. Run `python3 docs/generate_readmes.py` from the checkout to regenerate both guides. Include guide updates in the same commit as the related bot change when practical.
