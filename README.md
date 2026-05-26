# LiveNotifyUID

GsCore plugin for Bilibili and YouTube live notifications.

## Install

Clone this repository into `gsuid_core/plugins/LiveNotifyUID`, install the runtime dependencies in the GsCore environment, then restart GsCore. The repository root is importable as the `LiveNotifyUID` plugin package for this layout.

## VPS Deployment

1. Clone this repository as `gsuid_core/plugins/LiveNotifyUID`.
2. Install dependencies in the same Python environment used by GsCore:
   `pip install httpx sqlmodel`
3. Restart GsCore.
4. Set `youtube_api_key` and `discord_channel_id` in the LiveNotifyUID config.
5. Add subscriptions with `/live add bili <uid>` or `/live add youtube <channel_id_or_url>`.

## Configure

Open the GsCore WebConsole or configuration terminal, find the `LiveNotifyUID`
plugin config, and set:

- `youtube_api_key`
- `discord_channel_id`
- polling options
- notification options

The same values are stored in `gsuid_core/data/LiveNotifyUID/config.json`.

## Commands

Both `live ...` and `/live ...` are accepted by the plugin prefix.

- `/live add bili <uid> [display_name]`
- `/live add youtube <channel_id_or_url> [display_name]`
- `/live remove <id>`
- `/live list`
- `/live enable <id>`
- `/live disable <id>`
- `/live check <id>`
- `/live status`

## Optional Discord Slash Bridge

`integrations/nonebot_live_notify_slash.py` can be copied into a
NoneBot Discord project and loaded as a plugin. It registers a Discord
`/live` slash command and writes to the same
`gsuid_core/data/LiveNotifyUID/live_notify.db` database used by the GsCore
plugin.

Required NoneBot environment:

- `nonebot-adapter-discord`
- `sqlmodel`
- `application_commands` configured for the target Discord guild

## Notification Behavior

The plugin only sends a notification on `offline -> live`. On first startup, already-live channels are recorded without notification unless `notify_on_startup_live` is enabled.

## First-Version Limits

- YouTube input accepts Channel ID, `@handle`, `/@handle/...` URLs, and `/channel/UC...` URLs.
- Bilibili input is UID.
- One Discord target channel is configured globally.
- Offline notifications and repeated reminders are not sent.
