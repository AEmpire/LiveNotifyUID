# Live Notify GsCore Plugin Design

## Goal

Build a GsCore plugin that monitors specified Bilibili and YouTube channels and sends a notification to one configured Discord channel when a monitored channel starts a live stream.

The plugin runs inside GsCore on the user's VPS. It does not run as an independent service. It should support a medium monitoring scale of roughly 20-100 channels without spamming Discord, exhausting YouTube quota unnecessarily, or blocking GsCore's main runtime.

## Scope

Included in the first version:

- Bilibili live status checks by streamer UID.
- YouTube live status checks by YouTube Channel ID through the YouTube Data API.
- One configured Discord target channel ID.
- Config-file and command-based subscription management.
- Open-live notifications only, sent once per detected live session.
- Persistent state across GsCore restarts.
- Discord Embed-style notifications when supported, with text fallback.
- Admin-only management commands.

Excluded from the first version:

- Offline notifications.
- Repeated in-live reminder notifications.
- Multiple Discord target channels.
- YouTube WebSub/PubSub callback handling.
- Bilibili login cookie support.
- YouTube handle-to-channel-ID resolution.

## Architecture

The plugin is split into focused modules:

- `config`: Loads plugin settings from GsCore configuration and exposes them to the GsCore console where supported.
- `database`: Persists monitored channels, live status, notification state, failure counters, and timestamps.
- `providers`: Contains platform-specific live detectors. Bilibili and YouTube providers both return a normalized `LiveStatus`.
- `scheduler`: Runs periodic batch checks through GsCore's scheduler facilities.
- `notifier`: Sends Discord notifications to the configured channel, preferring Embed-style messages and falling back to plain text.
- `commands`: Adds, removes, lists, enables, disables, checks, and summarizes subscriptions.

Data flow:

```text
Commands/config -> subscription database -> scheduler batch selection
  -> platform provider check -> state transition decision
  -> notifier -> database state update
```

Providers only fetch and normalize live status. They do not decide whether to notify. The scheduler and state machine own notification decisions.

## Data Model

Each monitored channel is stored as a `live_subscriptions` record:

```text
id
platform: bili | youtube
external_id: Bilibili UID or YouTube Channel ID
display_name
room_url
enabled
last_state: unknown | offline | live
last_live_id
last_live_title
last_notified_live_id
last_checked_at
last_notified_at
failure_count
last_error
created_at
updated_at
```

`last_live_id` and `last_notified_live_id` are intentionally separate. A detected live session updates `last_live_id`; only a successful Discord notification updates `last_notified_live_id`. If notification delivery fails, the next eligible check may retry the same live session.

## Configuration

Recommended first-version configuration:

```yaml
youtube_api_key: ""
discord_channel_id: ""
poll_interval_seconds: 300
batch_size: 20
max_concurrency: 5
request_timeout_seconds: 10
failure_backoff_minutes: 15
embed_enabled: true
notify_on_startup_live: false
```

`notify_on_startup_live: false` means that the first check after startup or after adding a channel records an already-live state without notifying. Only a later `offline -> live` transition sends a notification. This prevents deployment or restart spam.

## Commands

The primary command is `/live`.

Supported subcommands:

```text
/live add bili <uid> [display_name]
/live add youtube <channel_id> [display_name]
/live remove <id>
/live list
/live enable <id>
/live disable <id>
/live check <id>
/live status
```

Command behavior:

- `add`: Saves a subscription and performs an initial check. If the channel is already live, the plugin records state but does not notify unless `notify_on_startup_live` is enabled.
- `remove`: Deletes the subscription in the first version.
- `list`: Shows paginated subscription records with ID, platform, name, enabled state, recent live state, last check time, and failure count.
- `enable` and `disable`: Toggle monitoring without deleting the record.
- `check`: Manually checks one channel and returns the current status to the command caller. It does not send an official Discord notification.
- `status`: Shows plugin health, subscription counts, recent scheduler activity, failed channel count, and YouTube configuration or quota warnings.

All management commands are restricted to GsCore administrators or owners in the first version.

## Polling And State Machine

The scheduler runs every `poll_interval_seconds`, selecting up to `batch_size` enabled subscriptions that are due for checking. Checks run asynchronously with a `max_concurrency` limit.

For medium scale, the default values are:

- `poll_interval_seconds`: `300`
- `batch_size`: `20`
- `max_concurrency`: `5`

Channel scheduling uses `last_checked_at` and `failure_count`. Channels with repeated failures are delayed by at least `failure_backoff_minutes` to avoid repeatedly hitting broken endpoints.

State transitions:

```text
unknown -> live     record only, unless notify_on_startup_live=true
unknown -> offline  record only
offline -> live     notify
live -> live        do not notify; update metadata
live -> offline     record only
```

After successful notification:

```text
last_notified_live_id = live_id
last_notified_at = now
```

If Discord notification fails, `last_notified_live_id` is not updated. The plugin records the error and may retry after a short notification failure backoff.

## Provider Behavior

The YouTube provider uses the YouTube Data API and requires `youtube_api_key`. It treats the configured `external_id` as a Channel ID. Missing or invalid keys pause YouTube checks and surface a clear warning through `/live status`.

The Bilibili provider uses a public or quasi-official endpoint keyed by streamer UID. It should not require a login cookie in the first version. If Bilibili fields are missing or an endpoint response changes, the provider records a parse error without affecting other subscriptions.

Both providers return a normalized live status containing:

```text
platform
external_id
state: offline | live
live_id
title
display_name
room_url
cover_url
started_at
raw_metadata
```

## Notification Format

When Embed-style messages are supported by the active GsCore Discord adapter, the notification should include:

- Title: `<display_name> started streaming`
- Description: live title
- URL: live room or stream URL
- Image or thumbnail: stream cover when available
- Fields: platform, streamer/channel, start time, channel or room ID
- Footer: `LiveNotifyUID`

If Embed-style messages are unavailable or sending fails because of unsupported rich-message fields, the plugin falls back to plain text:

```text
【B站直播开播】
主播：<display_name>
标题：<title>
链接：<room_url>
```

```text
【YouTube 直播开播】
频道：<display_name>
标题：<title>
链接：<room_url>
```

## Error Handling

- A single channel failure does not stop the batch.
- A Bilibili provider failure does not affect YouTube checks.
- A YouTube API configuration or quota error pauses YouTube checks for the current run and is reported by `/live status`.
- Provider parse errors are recorded in `last_error` and leave the prior live state intact unless the provider can confidently report a new state.
- Discord send failures are recorded and do not mark the live session as notified.
- GsCore restarts restore state from the database and do not duplicate notifications for already-notified live sessions.

## Testing

Provider tests:

- Bilibili offline response.
- Bilibili live response.
- YouTube offline response.
- YouTube live response.
- API failure.
- Missing optional fields.
- Response parse error.

State machine tests:

- `unknown -> live` records without notification by default.
- `offline -> live` sends exactly one notification.
- `live -> live` does not repeat notification.
- `live -> offline` records without notification.
- Notification failure does not update `last_notified_live_id`.
- Restarted plugin does not resend an already-notified live session.

Command and integration tests:

- `add`, `remove`, `list`, `enable`, `disable`, `check`, and `status` validate parameters and update persistent state correctly.
- Manual `check` reports status but does not send the official notification.
- Admin-only command restrictions are enforced.

## Open Decisions

The first version uses a single configured Discord channel ID rather than per-subscription routing. If multiple target channels become necessary, the data model can add a `target_channel_id` column without changing provider or state-machine responsibilities.

YouTube handle support is deferred. Users provide Channel IDs in the first version to keep API use deterministic.
