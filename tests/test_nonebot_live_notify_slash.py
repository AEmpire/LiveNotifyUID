from types import SimpleNamespace

from integrations.nonebot_live_notify_slash import (
    build_command_text,
    build_live_add_payload,
    build_live_list_payload,
    extract_slash_command,
)


def add_result(
    *,
    subscription=None,
    status=None,
    avatar_url=None,
    duplicate=False,
    initial_check_error=None,
    error_message=None,
):
    return SimpleNamespace(
        subscription=subscription,
        status=status,
        avatar_url=avatar_url,
        duplicate=duplicate,
        initial_check_error=initial_check_error,
        error_message=error_message,
    )


def sub(
    sub_id,
    platform,
    external_id,
    *,
    display_name=None,
    enabled=True,
    last_state="unknown",
    last_live_title=None,
    room_url=None,
    failure_count=0,
    last_error=None,
):
    return SimpleNamespace(
        id=sub_id,
        platform=platform,
        external_id=external_id,
        display_name=display_name,
        enabled=enabled,
        last_state=last_state,
        last_live_title=last_live_title,
        room_url=room_url,
        failure_count=failure_count,
        last_error=last_error,
    )


def option(name, value=None, options=None):
    data = {"name": name}
    if value is not None:
        data["value"] = value
    if options is not None:
        data["options"] = options
    return SimpleNamespace(**data)


def test_build_command_text_for_add_with_optional_name():
    assert (
        build_command_text(
            "add",
            {
                "platform": "youtube",
                "target": "https://www.youtube.com/@UTANOch/posts",
                "name": "Utano",
            },
        )
        == "add youtube https://www.youtube.com/@UTANOch/posts Utano"
    )


def test_build_command_text_for_id_commands():
    assert build_command_text("remove", {"id": 4}) == "remove 4"
    assert build_command_text("check", {"id": 5}) == "check 5"


def test_extract_slash_command_from_nested_discord_options():
    action, values = extract_slash_command(
        [
            option(
                "add",
                options=[
                    option("platform", "bili"),
                    option("target", "3494372800727907"),
                ],
            )
        ]
    )

    assert action == "add"
    assert values == {"platform": "bili", "target": "3494372800727907"}


def test_build_live_list_payload_empty_returns_no_groups():
    assert build_live_list_payload([]) == []


def test_build_live_list_payload_groups_by_platform_in_fixed_order():
    payloads = build_live_list_payload(
        [
            sub(1, "youtube", "UC_yt", display_name="YT One"),
            sub(2, "bili", "100", display_name="Bili One"),
        ]
    )
    assert [p["platform_key"] for p in payloads] == ["bili", "youtube"]


def test_build_live_list_payload_omits_platform_with_no_rows():
    payloads = build_live_list_payload([sub(1, "bili", "100")])
    assert len(payloads) == 1
    assert payloads[0]["platform_key"] == "bili"


def test_build_live_list_payload_sorts_live_first_then_disabled_last():
    rows = [
        sub(3, "bili", "3", last_state="offline", enabled=True),
        sub(1, "bili", "1", last_state="offline", enabled=False),
        sub(2, "bili", "2", last_state="live", enabled=True),
    ]
    payloads = build_live_list_payload(rows)
    fields = payloads[0]["fields"]
    assert [f["name"].split(" · ")[0] for f in fields] == ["#2", "#3", "#1"]


def test_build_live_list_payload_renders_state_badge_and_links():
    rows = [
        sub(
            42,
            "bili",
            "999",
            display_name="蕪山ふあな",
            last_state="live",
            last_live_title="今日歌枠",
            room_url="https://live.bilibili.com/12345",
        )
    ]
    payload = build_live_list_payload(rows)[0]
    field = payload["fields"][0]
    assert field["name"] == "#42 · 蕪山ふあな"
    assert "🔴 **LIVE**" in field["value"]
    assert "https://space.bilibili.com/999" in field["value"]
    assert "https://live.bilibili.com/12345" in field["value"]
    assert "今日歌枠" in field["value"]


def test_build_live_list_payload_disabled_subscription_shows_pause_mark():
    rows = [sub(1, "bili", "1", enabled=False, last_state="offline")]
    payload = build_live_list_payload(rows)[0]
    assert "⏸ 已停用" in payload["fields"][0]["value"]


def test_build_live_list_payload_shows_failure_count_and_error():
    rows = [
        sub(
            5,
            "youtube",
            "UC_x",
            failure_count=3,
            last_error="quota exceeded",
            last_state="unknown",
        )
    ]
    payload = build_live_list_payload(rows)[0]
    assert "⚠️ 失败 3 次" in payload["fields"][0]["value"]
    assert "quota exceeded" in payload["fields"][0]["value"]


def test_build_live_list_payload_truncates_long_live_title():
    long_title = "A" * 200
    rows = [
        sub(
            1,
            "bili",
            "1",
            last_state="live",
            last_live_title=long_title,
        )
    ]
    payload = build_live_list_payload(rows)[0]
    value = payload["fields"][0]["value"]
    assert long_title not in value
    assert "…" in value


def test_build_live_list_payload_header_counts_live_and_total():
    rows = [
        sub(1, "bili", "1", last_state="live"),
        sub(2, "bili", "2", last_state="offline"),
        sub(3, "bili", "3", last_state="live"),
    ]
    payload = build_live_list_payload(rows)[0]
    assert "总数 **3**" in payload["description"]
    assert "直播中 **2**" in payload["description"]
    assert payload["title"] == "📺 Bilibili 订阅 (3)"


def test_build_live_list_payload_falls_back_to_external_id_when_no_display_name():
    rows = [sub(7, "youtube", "UC_no_name")]
    payload = build_live_list_payload(rows)[0]
    assert payload["fields"][0]["name"] == "#7 · UC_no_name"


def test_build_live_list_payload_truncates_when_more_than_25_subscriptions():
    rows = [sub(i, "bili", str(i)) for i in range(1, 31)]  # 30 subs
    payload = build_live_list_payload(rows)[0]
    assert len(payload["fields"]) == 25  # 24 real + 1 marker
    assert payload["fields"][-1]["name"].startswith("... 还有")
    assert "6" in payload["fields"][-1]["name"]  # 30 - 24 = 6 remaining
    assert payload["title"] == "📺 Bilibili 订阅 (30)"


def test_build_live_list_payload_no_truncation_marker_at_exactly_25():
    rows = [sub(i, "bili", str(i)) for i in range(1, 26)]  # exactly 25
    payload = build_live_list_payload(rows)[0]
    assert len(payload["fields"]) == 25
    assert not payload["fields"][-1]["name"].startswith("... 还有")


def test_build_live_add_payload_renders_bilibili_success_with_avatar():
    subscription = sub(
        8, "bili", "480248442", display_name="北柚香Yuka", last_state="offline"
    )
    status = SimpleNamespace(
        state=SimpleNamespace(value="offline"),
        title=None,
        room_url=None,
    )
    result = add_result(
        subscription=subscription,
        status=status,
        avatar_url="https://i0.hdslb.com/bfs/face/abc.jpg",
    )

    payload = build_live_add_payload(result)

    assert "✅ 已添加" in payload["title"]
    assert "Bilibili" in payload["title"]
    assert "#8" in payload["title"]
    assert payload["color"] == 0xFB7299
    assert payload["thumbnail_url"] == "https://i0.hdslb.com/bfs/face/abc.jpg"
    field_names = [f["name"] for f in payload["fields"]]
    assert "频道" in field_names
    assert "ID" in field_names
    assert "初始状态" in field_names
    field_values = {f["name"]: f["value"] for f in payload["fields"]}
    assert "北柚香Yuka" in field_values["频道"]
    assert "480248442" in field_values["ID"]
    assert "离线" in field_values["初始状态"]

    # Homepage link must use a SHORT label so Discord won't soft-wrap the
    # rendered text mid-link and break the markdown parser. Specifically,
    # we must NOT emit `[full_url](full_url)` because Discord field values
    # have a finite render width and will wrap the long URL onto two visual
    # lines, leaving `[...]` and `(...)` on separate lines that no longer
    # parse as a markdown link.
    home_value = field_values["🔗 主页"]
    assert home_value.startswith("[")
    assert "](https://space.bilibili.com/480248442)" in home_value
    # Link text portion must NOT be the full URL.
    link_text = home_value.split("](", 1)[0][1:]
    assert "https://" not in link_text, (
        f"homepage link text must be a short label, got {link_text!r}"
    )


def test_build_live_add_payload_uses_avatar_as_logo_when_provided():
    subscription = sub(
        9, "youtube", "UCresolved", display_name="Utano", last_state="unknown"
    )
    result = add_result(
        subscription=subscription,
        avatar_url="https://yt3.example/avatar.jpg",
    )

    payload = build_live_add_payload(result)

    assert payload["logo_url"] == "https://yt3.example/avatar.jpg"
    assert payload["thumbnail_url"] == "https://yt3.example/avatar.jpg"


def test_build_live_add_payload_falls_back_to_platform_logo_without_avatar():
    subscription = sub(
        10, "bili", "999", display_name="Bili One", last_state="offline"
    )
    result = add_result(subscription=subscription, avatar_url=None)

    payload = build_live_add_payload(result)

    assert "bilibili.com" in (payload["logo_url"] or "")
    assert payload.get("thumbnail_url") is None


def test_build_live_add_payload_includes_live_title_when_currently_live():
    subscription = sub(
        11, "bili", "999", display_name="主播B", last_state="live"
    )
    status = SimpleNamespace(
        state=SimpleNamespace(value="live"),
        title="今日歌枠回",
        room_url="https://live.bilibili.com/12345",
    )
    result = add_result(
        subscription=subscription,
        status=status,
        avatar_url="https://i0.hdslb.com/bfs/face/abc.jpg",
    )

    payload = build_live_add_payload(result)
    field_values = {f["name"]: f["value"] for f in payload["fields"]}

    assert "🎬 正在播" in field_values
    assert "今日歌枠回" in field_values["🎬 正在播"]
    assert "https://live.bilibili.com/12345" in field_values["🎬 正在播"]
    assert "LIVE" in field_values["初始状态"]


def test_build_live_add_payload_surfaces_initial_check_failure():
    subscription = sub(
        12, "bili", "999", display_name="主播C", last_state="unknown"
    )
    result = add_result(
        subscription=subscription,
        avatar_url=None,
        initial_check_error="Bilibili UID not found: 999",
    )

    payload = build_live_add_payload(result)
    field_names = [f["name"] for f in payload["fields"]]
    assert "⚠️ 初始检查失败" in field_names
    err_field = next(f for f in payload["fields"] if f["name"] == "⚠️ 初始检查失败")
    assert "Bilibili UID not found" in err_field["value"]


def test_build_live_add_payload_renders_error_when_no_subscription():
    result = add_result(error_message="不支持的平台，请使用 bili 或 youtube。")

    payload = build_live_add_payload(result)

    assert payload["title"].startswith("❌")
    assert payload["color"] == 0xED4245
    assert "不支持的平台" in payload["description"]
    assert payload.get("thumbnail_url") is None


def test_build_live_add_payload_renders_duplicate_as_error_card():
    result = add_result(duplicate=True, error_message="该直播监听已存在")

    payload = build_live_add_payload(result)

    assert payload["title"].startswith("❌")
    assert "该直播监听已存在" in payload["description"]
