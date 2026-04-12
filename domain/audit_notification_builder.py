from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence

from domain.shared.person_html import person_display_html


@dataclass(frozen=True)
class PersonDisplay:
    english_name: str
    tg_username: Optional[str]


@dataclass(frozen=True)
class LeaveLineDisplay:
    person: PersonDisplay
    approver: str  # 已按“对外人员展示规则”格式化（可含 <a>）
    approved_at_local: str  # 已是班次时区展示时间文本


def _person_display(p: PersonDisplay) -> str:
    return person_display_html(english_name=p.english_name, tg_username=p.tg_username)


def _list_people(title: str, people: Sequence[PersonDisplay]) -> str:
    if not people:
        return f"{title}：0\n"
    lines = "\n".join([f"- {_person_display(p)}" for p in people])
    return f"{title}：{len(people)}\n{lines}\n"


def build_shift_start_group_notice_html(
    *,
    work_date: date,
    department_name: str,
    shift_label: str,
    timezone_name: str,
    leader_display_html: str,
    should_count: int,
    checked_in: Sequence[PersonDisplay],
    on_leave: Sequence[PersonDisplay],
    late: Sequence[PersonDisplay],
    absent: Sequence[PersonDisplay],
) -> str:
    """
    3003 开班考勤群公告（文案组装，不访问 DB）。
    """
    dept = department_name or "未配置"
    leader_html = (leader_display_html or "").strip() or html.escape("未配置")
    parts: list[str] = []
    parts.append("开班考勤汇总：\n")
    parts.append(f"日期：{html.escape(str(work_date))}\n")
    parts.append(f"部门：{html.escape(dept)}\n")
    parts.append(f"班次：{html.escape(shift_label)}\n")
    parts.append(f"时区：{html.escape(timezone_name)}\n")
    parts.append(f"部门负责人：{leader_html}\n\n")
    parts.append(f"今日应到岗人数：{should_count}\n")
    parts.append(f"已到岗人数：{len(checked_in)}\n\n")
    parts.append(_list_people("报备休假名单", on_leave))
    parts.append(_list_people("迟到名单", late))
    parts.append(_list_people("未打卡名单", absent))
    parts.append("\n质检即将启动，请留意通知。")
    return "".join(parts)


def build_shift_start_leader_dm_html(
    *,
    timezone_name: str,
    shift_label: str,
    should_count: int,
    checked_in_count: int,
    on_leave_lines: Sequence[LeaveLineDisplay],
    not_clocked: Sequence[PersonDisplay],
) -> str:
    """
    3004 开班组长私信（文案组装，不访问 DB）。
    """
    # 严格按指定模板输出（顺序不可变）
    # shift_label 形如 "HH:MM - HH:MM"
    checkin_time = ""
    checkout_time = ""
    if " - " in (shift_label or ""):
        checkin_time, checkout_time = (shift_label.split(" - ", 1) + [""])[:2]
    tz = html.escape(timezone_name or "")
    cin = html.escape(checkin_time or "")
    cout = html.escape(checkout_time or "")

    parts: list[str] = []
    parts.append(
        f"您负责的{tz} {cin} —— {cout} 的班次目前已经开始，应到岗{should_count}人，已到岗{checked_in_count}人。\n"
    )

    # 其中{leave_count}人报备休息...
    if on_leave_lines:
        parts.append("\n")
        parts.append(f"其中{len(on_leave_lines)}人报备休息，名单为：\n")
        for ln in on_leave_lines:
            person_html = person_display_html(
                english_name=ln.person.english_name,
                tg_username=ln.person.tg_username,
            )
            approver_html = (ln.approver or "").strip() or html.escape("（审批人未配置）")
            approved_at = html.escape((ln.approved_at_local or "").strip() or "（审批时间缺失）")
            parts.append(f"{person_html}（审批人：{approver_html}，审批时间：{approved_at}）\n")

    # 以下成员应到岗但仍未打卡...
    if not_clocked:
        parts.append("\n")
        parts.append("以下成员应到岗但仍未打卡，请确认员工状态：\n")
        for p in not_clocked:
            parts.append(f"{person_display_html(english_name=p.english_name, tg_username=p.tg_username)}\n")

    return "".join(parts).strip()


def build_shift_end_group_reminder_plain_text(
    *,
    work_date: date,
    department_name: str,
    shift_label: str,
    timezone_name: str,
) -> str:
    """
    3006 下班考勤群提醒（文案组装，不访问 DB）。
    """
    # 说明：notification_queue 统一按 HTML parse_mode 发送。
    # 该模板本身不使用任何 HTML 标签，但为避免出现字面量 <、& 导致解析失败，
    # 这里对动态字段做 escape（不影响普通文本显示）。
    dept = html.escape(department_name or "未配置")
    shift = html.escape(shift_label or "")
    tz = html.escape(timezone_name or "")
    d = html.escape(str(work_date))
    return (
        "下班提醒：\n\n"
        f"日期：{d}\n"
        f"部门：{dept}\n"
        f"班次：{shift}\n"
        f"时区：{tz}\n\n"
        "本日工作时间已经结束，请各位同事不要忘记打卡，祝您生活愉快。"
    )


@dataclass(frozen=True)
class DepartmentGroupSummaryLine:
    group_name_html: str
    expected_count: int
    present_count: int
    leave_count: int
    not_clocked_count: int


def build_shift_start_department_head_dm_html(
    *,
    department_head_name_html: str,
    department_name: str,
    shift_label: str,
    timezone_name: str,
    groups: Sequence[DepartmentGroupSummaryLine],
) -> str:
    """
    3005 开班部门负责人汇总私信（严格按 docs00 模板）。
    """
    # shift_label 形如 "HH:MM - HH:MM"
    checkin_time = ""
    checkout_time = ""
    if " - " in (shift_label or ""):
        checkin_time, checkout_time = (shift_label.split(" - ", 1) + [""])[:2]

    head = (department_head_name_html or "").strip() or "（未注册）"
    dept = html.escape(department_name or "未配置")
    cin = html.escape(checkin_time or "")
    cout = html.escape(checkout_time or "")
    tz = html.escape(timezone_name or "")

    parts: list[str] = []
    parts.append(f"{head}领导您好，\n\n")
    parts.append(f"部门：{dept}\n")
    parts.append(f"班次：{cin} — {cout}\n")
    parts.append(f"时区：{tz}\n\n")

    for g in groups:
        gname = (g.group_name_html or "").strip() or "（未配置）组"
        parts.append(
            f"{gname}：应到岗{int(g.expected_count)}人，实际到岗{int(g.present_count)}人，"
            f"{int(g.leave_count)}人报备休假，{int(g.not_clocked_count)}人未打卡\n"
        )
    return "".join(parts).strip()

