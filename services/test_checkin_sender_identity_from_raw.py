"""方案 B：群名噪声丢弃 + 仅全文有本人时回填（无登记名硬填）。"""
from __future__ import annotations

from services import checkin_identity_match_service as svc


def test_plan_b_fills_sender_from_raw_when_group_name_wrong():
    raw = (
        '{"display_name":"Y-UX-KQBHQ","username_hint":"KQBHQ",'
        '"clock_time":"02:02:00","clock_date":"2026-07-11",'
        '"evidence":"group Y_UX_KAIRICE大米 y_ux_kairice"}'
    )
    resolved = svc.resolve_sender_identity_plan_b(
        display_name="Y-UX-KQBHQ",
        username_hint="KQBHQ",
        raw=raw,
        tg_username="y_ux_kairice",
        english_name="KAIRICE",
    )
    assert resolved is not None
    assert resolved.username_hint == "y_ux_kairice"
    assert "kairice" in resolved.display_name.lower()


def test_plan_b_no_registration_fallback_when_only_group_title():
    raw = (
        '{"display_name":"Y-UX-KQBHQ","username_hint":"KQBHQ",'
        '"clock_time":"02:02:00","clock_date":"2026-07-11",'
        '"evidence":"group title only"}'
    )
    resolved = svc.resolve_sender_identity_plan_b(
        display_name="Y-UX-KQBHQ",
        username_hint="KQBHQ",
        raw=raw,
        tg_username="Y_UX_Kairice",
        english_name="Kairice",
    )
    assert resolved is None


def test_plan_b_no_fallback_for_other_person():
    resolved = svc.resolve_sender_identity_plan_b(
        display_name="Y_TC_Xitanua",
        username_hint="y_tc_xitanua",
        raw='{"display_name":"Y_TC_Xitanua","username_hint":"y_tc_xitanua"}',
        tg_username="Y_UX_Kairice",
        english_name="Kairice",
    )
    assert resolved is None


def test_group_noise_detects_kairice_fail_variants():
    assert svc.is_attendance_group_identity_noise("Y-UX-KQBQQ", "KQBQQ")
    assert svc.is_attendance_group_identity_noise("Y-UX-KQBHQ", "KQBHQ")
    assert not svc.is_attendance_group_identity_noise("Y_UX_KAIRICE大米", "y_ux_kairice")


def test_strip_group_noise_keeps_matched_sender_name():
    """本人 + 误带群名：只清群名，保留本人。"""
    disp, hint = svc.strip_group_name_noise_fields(
        display_name="PADADGU",
        username_hint="Y_UX_KQBQQ",
    )
    assert disp == "PADADGU"
    assert hint is None
    assert svc.match_expected_sender(
        display_name=disp,
        username_hint=hint,
        tg_username="Y_UX_Padadgu",
        english_name="PADADGU",
    )


def test_strip_group_noise_still_clears_only_group_pair():
    disp, hint = svc.strip_group_name_noise_fields(
        display_name="Y-UX-KQBQQ",
        username_hint="KQBQQ",
    )
    assert disp is None
    assert hint is None


def test_visible_texts_picks_sender_over_macos_noise():
    disp, hint, action = svc.apply_visible_texts_identity(
        display_name="查看macOS15的新功能",
        username_hint="查看新功能",
        visible_texts=[
            "Y_UX_Rapunzelli 樂佩",
            "查看 macOS 15 的新功能",
            "TIME.IS",
            "现在的北京北京时间",
        ],
        tg_username="Y_UX_Rapunzelli1",
        english_name="Rapunzelli",
    )
    assert action == "picked"
    assert "Rapunzelli" in (disp or "")
    assert svc.match_expected_sender(
        display_name=disp,
        username_hint=hint,
        tg_username="Y_UX_Rapunzelli1",
        english_name="Rapunzelli",
    )


def test_visible_texts_clears_ui_noise_when_sender_absent():
    disp, hint, action = svc.apply_visible_texts_identity(
        display_name="查看macOS15的新功能",
        username_hint="查看新功能",
        visible_texts=["TIME.IS", "查看 macOS 15 的新功能", "现在的北京北京时间"],
        tg_username="Y_UX_Rapunzelli1",
        english_name="Rapunzelli",
    )
    assert action == "cleared_ungrounded"
    assert disp is None and hint is None


def test_visible_texts_rejects_ai_hallucinated_registered_name():
    """AI 把 prompt 登记身份填进 display_name，但 visible_texts 无此人 → 必须清空。"""
    disp, hint, action = svc.apply_visible_texts_identity(
        display_name="Y_UX_Nayxua, NAYXUA",
        username_hint="NAYXUA",
        visible_texts=[
            "15:37",
            "中国北京市的时间",
            "Time.is",
            "智谱AI开放平台",
            "Y_UX_Rapunzelli 樂佩",
        ],
        tg_username="Y_UX_Nayxua",
        english_name="NAYXUA",
    )
    assert action == "cleared_ungrounded"
    assert disp is None and hint is None


def test_ui_identity_noise_detects_macos():
    assert svc.is_ui_identity_noise("查看macOS15的新功能")
    assert svc.is_ui_identity_noise("更改表情符号状态")
    assert not svc.is_ui_identity_noise("Y_UX_Rapunzelli 樂佩")
