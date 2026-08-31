from datetime import date
from repositories import shifts_repo
from services import group_attendance_summary_service as g

CHAT_ID = -1003883297177
TARGET = date(2026, 8, 31)

print('=== SHIFTS ===')
for s in shifts_repo.list_all_shifts():
    print(s)

rows = g.build_rows_for_group(chat_id=CHAT_ID, target_date=TARGET)
print('\n=== DAILY SUMMARY ===')
print(g.summarize_text(rows=rows, target_date=TARGET, chat_id=CHAT_ID))

buckets = g.compute_shift_start_notice_buckets(chat_id=CHAT_ID, target_date=TARGET, shift_id=1)
print('\n=== SHIFT START BUCKETS ===')
print(f'should={buckets.should_count} arrived={len(buckets.arrived)} rest={len(buckets.on_rest)} late={len(buckets.late)} absent={len(buckets.absent)}')
