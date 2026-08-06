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
