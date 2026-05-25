# LiveNotifyUID

GsCore plugin for Bilibili and YouTube live notifications.

## Install

Clone this repository into `gsuid_core/plugins/LiveNotifyUID`, install the runtime dependencies in the GsCore environment, then restart GsCore.

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
