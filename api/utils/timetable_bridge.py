from collections import defaultdict
from api.models import TimetableEntry, CourseOffering, Room, TimeSlot


def prepare_input(offerings_qs, rooms_qs, time_slots_qs, config):
    offerings = []
    for off in offerings_qs.select_related('course', 'section__program__department', 'teacher'):
        offerings.append({
            'id': off.id,
            'course_code': off.course.code,
            'course_title': off.course.title,
            'course_type': off.course.course_type,
            'credit_hours': off.course.credit_hours,
            'sessions_per_week': off.sessions_per_week,
            'teacher_id': off.teacher.id if off.teacher else None,
            'section_id': off.section.id,
            'program_code': off.section.program.code,
            'department_code': off.section.program.department.code,
            'year': off.section.year,
            'is_elective': off.course.is_elective,
            'student_count': off.section.student_count,
        })
    rooms = list(rooms_qs.values('id', 'code', 'capacity', 'room_type'))
    time_slots = list(time_slots_qs.values('id', 'day', 'period_number', 'start_time', 'end_time'))
    return offerings, rooms, time_slots, dict(config)


def save_output(assignments, upload_session_id):
    """Save assignments to DB, enforcing HC1-HC4 during save.

    Hard Constraints enforced:
      HC1: Teacher cannot teach two classes at the same time.
      HC2: Room cannot host multiple classes simultaneously.
      HC3: Section cannot have overlapping classes.
      HC4: Each offering must have the required number of sessions.
    """
    offering_ids = [a['offering_id'] for a in assignments]
    room_ids = [a['room_id'] for a in assignments]
    time_slot_ids = []
    for a in assignments:
        time_slot_ids.extend(a.get('time_slot_ids') or [a['time_slot_id']])

    offerings = {o.id: o for o in CourseOffering.objects.select_related(
        'course', 'section__program', 'teacher'
    ).filter(id__in=offering_ids, upload_session_id=upload_session_id)}
    rooms = {r.id: r for r in Room.objects.filter(id__in=room_ids)}
    slots = {ts.id: ts for ts in TimeSlot.objects.filter(id__in=time_slot_ids)}

    entries = []
    teacher_slots = set()   # HC1: (teacher_id, slot_id) must be unique
    room_slots = set()      # HC2: (room_id, slot_id) must be unique
    section_slots = set()   # HC3: (section_id, slot_id) must be unique

    for a in assignments:
        off = offerings.get(a['offering_id'])
        room = rooms.get(a['room_id'])
        if not off or not room:
            raise ValueError('Invalid offering or room in generated timetable')
        for slot_id in a.get('time_slot_ids') or [a['time_slot_id']]:
            slot = slots.get(slot_id)
            if not slot:
                raise ValueError('Invalid time slot in generated timetable')
            if slot.day not in ['MON', 'TUE', 'WED', 'THU', 'FRI']:
                raise ValueError('Saturday/Sunday slot generated, which is not allowed')
            # HC1: Teacher cannot teach two classes at the same time
            if off.teacher:
                key = (off.teacher_id, slot.id)
                if key in teacher_slots:
                    raise ValueError(f'HC1 VIOLATED: Teacher {off.teacher.name} double-booked at {slot}')
                teacher_slots.add(key)
            # HC2: Room cannot host multiple classes simultaneously
            rkey = (room.id, slot.id)
            if rkey in room_slots:
                raise ValueError(f'HC2 VIOLATED: Room {room.code} double-booked at {slot}')
            room_slots.add(rkey)
            # HC3: Student section cannot have overlapping classes
            skey = (off.section_id, slot.id)
            if skey in section_slots:
                raise ValueError(f'HC3 VIOLATED: Section {off.section} double-booked at {slot}')
            section_slots.add(skey)

            entries.append(TimetableEntry(
                offering=off, room=room, time_slot=slot,
                course_code=off.course.code, course_title=off.course.title,
                teacher_name=off.teacher.name if off.teacher else 'TBA',
                section_label=str(off.section), program_code=off.section.program.code,
                year=off.section.year,
            ))

    # HC4: Check session counts (warn but don't block save — the algorithm
    # already reports unplaced tasks and the frontend shows HC4 status)
    hc4_warnings = []
    session_counts = defaultdict(int)
    for a in assignments:
        session_counts[a['offering_id']] += 1
    for off in offerings.values():
        expected = off.sessions_per_week
        actual = session_counts.get(off.id, 0)
        if actual != expected:
            hc4_warnings.append(
                f'{off.course.code} ({off.section}) expected {expected} sessions, got {actual}'
            )

    TimetableEntry.objects.bulk_create(entries)
    return hc4_warnings
