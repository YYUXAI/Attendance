from domain.clock_matter import parse_matter_from_text


def test_parse_matter_requires_exact_value_by_default() -> None:
    caption = (
        "@yyux_helper_bot #打卡\n"
        "英文名：Chapkups\n"
        "工号：58643\n"
        "事项：签到（未迟到 虚拟机无法登记 群里已报备）"
    )
    assert parse_matter_from_text(caption) is None
    assert parse_matter_from_text("事项：签到") == "签到"
    assert parse_matter_from_text("事项：签退") == "签退"


def test_parse_matter_embedded_for_qdyyz_caption() -> None:
    caption = (
        "@yyux_helper_bot #打卡\n"
        "英文名：Chapkups\n"
        "工号：58643\n"
        "事项：签到（未迟到 虚拟机无法登记 群里已报备）"
    )
    assert parse_matter_from_text(caption, allow_embedded=True) == "签到"
    assert parse_matter_from_text(
        "事项：今天签退（提前走）",
        allow_embedded=True,
    ) == "签退"


def test_parse_matter_embedded_uses_first_hit_in_caption() -> None:
    assert parse_matter_from_text(
        "#打卡 说明里有签到两个字",
        allow_embedded=True,
    ) == "签到"
    assert parse_matter_from_text("普通配文没有动作", allow_embedded=True) is None


def test_parse_matter_note_from_qdyyz_caption() -> None:
    from domain.clock_matter import parse_matter_note_from_text

    caption = (
        "@yyux_helper_bot #打卡\n"
        "英文名：Chapkups\n"
        "工号：58643\n"
        "事项：签到（未迟到 虚拟机无法登记 群里已报备）"
    )
    assert parse_matter_note_from_text(caption) == "未迟到 虚拟机无法登记 群里已报备"
    assert parse_matter_note_from_text("事项：签到 (未迟到 虚拟机无法登记 群里已报备)") == (
        "未迟到 虚拟机无法登记 群里已报备"
    )
    assert parse_matter_note_from_text("事项：签到") is None
    assert parse_matter_note_from_text("事项：签退（提前走）") == "提前走"


def test_format_export_status_with_note() -> None:
    from domain.clock_matter import format_export_status_with_note

    assert format_export_status_with_note("正常", "未迟到 虚拟机无法登记 群里已报备") == (
        "正常（未迟到 虚拟机无法登记 群里已报备）"
    )
    assert format_export_status_with_note("迟到", "（电梯故障）") == "迟到（电梯故障）"
    assert format_export_status_with_note("正常", None) == "正常"
    assert format_export_status_with_note("正常", "") == "正常"

