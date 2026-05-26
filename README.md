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
5. Add subscriptions with `/live add bili <uid>` or `/live add youtube <channel_id>`.

## Configure

Set `youtube_api_key`, `discord_channel_id`, polling options, and notification options in the plugin config.

## Commands

- `/live add bili <uid> [display_name]`
- `/live add youtube <channel_id> [display_name]`
- `/live remove <id>`
- `/live list`
- `/live enable <id>`
- `/live disable <id>`
- `/live check <id>`
- `/live status`

## Notification Behavior

The plugin only sends a notification on `offline -> live`. On first startup, already-live channels are recorded without notification unless `notify_on_startup_live` is enabled.

## First-Version Limits

- YouTube input is Channel ID.
- Bilibili input is UID.
- One Discord target channel is configured globally.
- Offline notifications and repeated reminders are not sent.
