"""Test the upload-parse-generate pipeline end to end."""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'giki_timetable.settings')
django.setup()

from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from api.models import UploadSession, CourseOffering, Room, TimeSlot, TimetableEntry
from api.utils.excel_parser import parse_courses_excel
from api.utils.timetable_bridge import prepare_input, save_output
from algorithm.timetable_generator import generate

# Step 1: Upload & parse
filepath = os.path.join(settings.BASE_DIR, 'data', 'Fall_2025_Courses_by_Faculty.xlsx')
with open(filepath, 'rb') as f:
    file_data = f.read()
file_obj = SimpleUploadedFile('Fall_2025_Courses_by_Faculty.xlsx', file_data,
                              content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
session = UploadSession.objects.create(uploaded_file=file_obj, status='pending')
print(f"Upload session created: id={session.id}")

result = parse_courses_excel(file_obj, session)
print(f"\nParse result:")
print(f"  Status: {result['status']}")
print(f"  Total rows: {result['total_rows']}")
print(f"  Courses created: {result['courses_created']}")
print(f"  Teachers created: {result['teachers_created']}")
print(f"  Sections created: {result['sections_created']}")
print(f"  Preview count: {len(result['preview'])}")

if not result['preview']:
    print("ERROR: No offerings created! Cannot generate.")
    sys.exit(1)

# Step 2: Generate
offerings_qs = CourseOffering.objects.filter(upload_session=session).select_related(
    'course', 'section__program__department', 'teacher')
rooms_qs = Room.objects.filter(is_active=True)
time_slots_qs = TimeSlot.objects.filter(
    day__in=settings.TIMETABLE_CONFIG['WORKING_DAYS'],
    period_number__lte=settings.TIMETABLE_CONFIG['PERIODS_PER_DAY']
)
print(f"\nOffers: {offerings_qs.count()}, Rooms: {rooms_qs.count()}, Slots: {time_slots_qs.count()}")

TimetableEntry.objects.all().delete()
offerings, rooms, time_slots, config = prepare_input(offerings_qs, rooms_qs, time_slots_qs, settings.TIMETABLE_CONFIG)
gen_result = generate(offerings, rooms, time_slots, config)
print(f"\nGeneration: status={gen_result.get('status')}, assignments={len(gen_result.get('assignments', []))}, "
      f"time={gen_result.get('generation_time_ms')}ms, score={gen_result.get('soft_score')}")

if gen_result.get('status') in ('success', 'partial'):
    try:
        save_output(gen_result['assignments'], session.id)
        count = TimetableEntry.objects.count()
        print(f"\nSaved {count} timetable entries to database!")
        session.status = 'generated'
        session.save(update_fields=['status'])
    except ValueError as exc:
        print(f"\nERROR saving output: {exc}")
else:
    print(f"\nFailed: {gen_result.get('conflicts', [])[:5]}")

if gen_result.get('warnings'):
    print(f"\nWarnings ({len(gen_result['warnings'])}):")
    for w in gen_result['warnings'][:5]:
        print(f"  - {w}")
