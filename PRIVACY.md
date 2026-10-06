# DM Modbot Privacy Policy

**Last updated:** October 6, 2026

DM Modbot is operated by **ryry013** on Discord. This policy explains how the
bot handles information when connecting users with server staff for reports,
questions, and ban appeals.

**A direct message to the bot is a way to contact server staff. During an
active report or appeal, your messages and attachments are relayed to the
server you contact, and your Discord identity is visible to its staff.**

## Information the bot handles

Depending on the features you use, DM Modbot accesses or stores:

- **Discord identifiers and account information:** user, server, channel,
  thread, message, and role IDs; usernames, display names, and available
  profile information used to identify participants and route conversations.
- **Report and appeal content:** submitted text, moderator replies, images,
  files, links, stickers, embeds, and relevant moderation records supplied
  by a server's moderation bot, such as Rai.
- **Membership and moderation information:** membership in servers shared
  with the bot, roles, permissions, and ban status needed to select a server,
  check access, or provide access to an appeal channel.
- **Settings and conversation state:** configured report channels and staff
  roles, command prefixes, report type, active conversation connections,
  participating moderator IDs, moderator identity-display preferences,
  blocked-user IDs, and button or status-message references.
- **Language preferences and activity information:** the language reported by
  Discord interactions, report timestamps, recent report references and
  short text excerpts, message counts, response status, and typing events
  used to display a typing indicator during a conversation.
- **Diagnostic information:** errors and associated command or interaction
  context, which may include identifiers, message links, and message excerpts.
  When the bot joins a server, it also notifies the operator with server and
  channel information.

The bot can receive messages in channels where Discord permissions allow it.
It uses those messages to handle report conversations, commands, and appeal
setup. It does not maintain a general message archive of unrelated server
conversations. Diagnostic records may nevertheless contain excerpts from
messages involved in an error.

## Why the information is used

Information is used to deliver reports and appeals to the correct server,
relay replies and attachments, check permissions and appeal eligibility,
prevent abuse of the reporting system, display report status, remember
settings and recent reports, restore active conversations after restarts,
and diagnose operational problems.

DM Modbot does not sell user data, use it for advertising, or use message
content to train AI or machine learning models.

## Storage and access

The bot stores settings, conversation state, and recent report information
in JSON files on the host where it runs. It also creates database backups.
Full report conversations and relayed attachments are posted to Discord
messages and threads; short excerpts may also be included in the bot's
recent report records or diagnostic messages.

The bot operator and authorized maintainers handle bot-hosted files for
operation and support. Reports, appeals, and status messages are accessible
to anyone with permission to view the configured Discord channels and
threads. Server administrators control those permissions, including access
for moderators or other server helpers. People with access to the operator's
diagnostic channels may see error context.

Reports identify the person contacting staff. Moderator replies can use
labels such as "Moderator 1", but the bot retains the moderator IDs needed
to relay those replies. These labels do not make a conversation anonymous
to the bot operator or server staff.

Discord processes messages and attachments under its own
[Privacy Policy](https://discord.com/privacy). Hosting providers may process
bot-hosted information as needed to provide hosting services. Information may
also be disclosed when required by applicable law.

## Retention

The active conversation connection is removed when a report is closed. The
bot's current recent report list keeps up to five closed report references
per user per server, sometimes with short text excerpts. Older copies may
remain in Discord messages or database backups.

Closing or archiving a report does not delete its messages or attachments.
Settings, language preferences, blocked-user records, and backups do not
currently have an automatic time-based expiry. Removing the bot from a
server does not automatically erase those records. Removal of retained
bot-held information, including records no longer needed for the bot's
functions, is handled manually by the operator through the contact below.

## Access, correction, and deletion requests

Contact **ryry013** on Discord to ask about information associated with your
account or to request access, correction, or deletion. Include your Discord
user ID and the relevant server or report, if known. The operator may ask
you to verify that you control the account or are authorized to make a
server-wide request. Do not send passwords or account tokens.

Requests are handled manually. The operator will promptly correct or delete
the relevant information under their control, including retained backup
copies and diagnostic records containing it, unless applicable law requires
retention. If a request cannot be fully completed, the operator will explain
the limitation.

For report messages or records controlled independently by a server's staff,
contact that server's administrators as well. The operator cannot guarantee
removal of copies independently retained by other people or Discord.
Deleting bot-held information does not itself change a server's ban or other
moderation decision.

## Changes and contact

Updates to this policy will be published here with a revised date. For
privacy questions or concerns, contact **ryry013** on Discord.
