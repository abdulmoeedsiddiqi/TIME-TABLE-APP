from django.conf import settings
from django.core.management import call_command
from django.http import HttpResponse
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import UploadSession, CourseOffering, Room, TimeSlot, TimetableEntry, Department, Program, Course, Teacher, ProspectusEntry
from .serializers import RoomSerializer, CourseSerializer, TeacherSerializer, DepartmentSerializer, ProgramSerializer, ProspectusEntrySerializer
from .utils.excel_parser import parse_courses_excel
from .utils.timetable_bridge import prepare_input, save_output
from algorithm.timetable_generator import generate


class MetadataView(APIView):
    def get(self, request):
        return Response({
            'departments': list(Department.objects.values('code', 'full_name')),
            'programs': list(Program.objects.select_related('department').values('code', 'full_name', 'department__code')),
            'rooms': Room.objects.count(),
            'time_slots': TimeSlot.objects.count(),
            'uploads': list(UploadSession.objects.order_by('-uploaded_at').values('id', 'uploaded_at', 'status')[:10]),
        })


class UploadExcelView(APIView):
    def post(self, request):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)
        if not file_obj.name.lower().endswith('.xlsx'):
            return Response({'error': 'Only .xlsx files are accepted'}, status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
        session = UploadSession.objects.create(uploaded_file=file_obj, status='pending')
        result = parse_courses_excel(file_obj, session)
        if result['status'] == 'error' and not result.get('courses_created'):
            session.status = 'failed'
            session.error_message = str(result.get('errors', []))
            session.save(update_fields=['status', 'error_message'])
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
        session.status = 'parsed'
        session.save(update_fields=['status'])
        result['upload_session_id'] = session.id
        return Response(result, status=status.HTTP_200_OK if not result.get('warnings') else status.HTTP_207_MULTI_STATUS)


class UploadPreviewView(APIView):
    def get(self, request, pk):
        offerings = CourseOffering.objects.filter(upload_session_id=pk).select_related('course', 'section__program', 'teacher')[:300]
        return Response({'preview': [{
            'course_code': o.course.code,
            'course_title': o.course.title,
            'section': str(o.section),
            'teacher': o.teacher.name,
            'sessions': o.sessions_per_week,
        } for o in offerings]})


class GenerateTimetableView(APIView):
    def post(self, request):
        session_id = request.data.get('upload_session_id')
        session = UploadSession.objects.filter(id=session_id).first() if session_id else UploadSession.objects.filter(status__in=['parsed', 'generated']).order_by('-uploaded_at').first()
        if not session:
            return Response({'error': 'No uploaded course-offering file found'}, status=status.HTTP_404_NOT_FOUND)

        faculty = request.data.get('faculty') or request.data.get('department')
        program = request.data.get('program')
        year = request.data.get('year')
        offerings_qs = CourseOffering.objects.filter(upload_session=session).select_related('course', 'section__program__department', 'teacher')
        if faculty and faculty != 'all':
            offerings_qs = offerings_qs.filter(section__program__department__code=faculty)
        if program and program != 'all':
            offerings_qs = offerings_qs.filter(section__program__code=program)
        if year and str(year).lower() != 'all':
            digits = ''.join(ch for ch in str(year) if ch.isdigit())
            if digits:
                offerings_qs = offerings_qs.filter(section__year=int(digits))
        if not offerings_qs.exists():
            return Response({'error': 'No courses found for selected filters'}, status=status.HTTP_400_BAD_REQUEST)

        TimetableEntry.objects.all().delete()
        rooms_qs = Room.objects.filter(is_active=True)
        time_slots_qs = TimeSlot.objects.filter(day__in=settings.TIMETABLE_CONFIG['WORKING_DAYS'], period_number__lte=settings.TIMETABLE_CONFIG['PERIODS_PER_DAY'])
        if not rooms_qs.exists() or not time_slots_qs.exists():
            return Response({'error': 'Static data missing. Click Load Static Data first.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        offerings, rooms, time_slots, config = prepare_input(offerings_qs, rooms_qs, time_slots_qs, settings.TIMETABLE_CONFIG)
        result = generate(offerings, rooms, time_slots, config)
        if result.get('status') == 'infeasible':
            return Response({'error': 'No feasible timetable found', **result}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        try:
            hc4_warnings = save_output(result['assignments'], session.id)
        except ValueError as exc:
            return Response({'error': 'Constraint violation while saving', 'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        session.status = 'generated'
        session.save(update_fields=['status'])
        hc = result.get('hard_constraints', {})
        resp = {
            'status': 'success' if hc.get('satisfied') else 'partial',
            'entries_generated': TimetableEntry.objects.count(),
            'soft_constraint_score': round(float(result.get('soft_score', 0)), 2),
            'generation_time_ms': result.get('generation_time_ms', 0),
            'upload_session_id': session.id,
            'hard_constraints': hc,
            'total_tasks': result.get('total_tasks', 0),
            'placed_tasks': result.get('placed_tasks', 0),
        }
        if hc4_warnings:
            resp['hc4_warnings'] = hc4_warnings
        return Response(resp)


class TimetableListView(APIView):
    DAY_MAP = {'MON': 'Monday', 'TUE': 'Tuesday', 'WED': 'Wednesday', 'THU': 'Thursday', 'FRI': 'Friday'}
    def get(self, request):
        qs = TimetableEntry.objects.select_related('time_slot', 'room', 'offering__section__program__department').all()
        faculty = request.query_params.get('faculty')
        program = request.query_params.get('program')
        year = request.query_params.get('year')
        section = request.query_params.get('section')
        teacher = request.query_params.get('teacher')
        room = request.query_params.get('room')
        day = request.query_params.get('day')
        if faculty and faculty != 'all': qs = qs.filter(offering__section__program__department__code=faculty)
        if program and program != 'all': qs = qs.filter(program_code=program)
        if year and year != 'all':
            digits = ''.join(ch for ch in str(year) if ch.isdigit())
            if digits: qs = qs.filter(year=int(digits))
        if section and section != 'all': qs = qs.filter(section_label=section)
        if teacher and teacher != 'all': qs = qs.filter(teacher_name__icontains=teacher)
        if room and room != 'all': qs = qs.filter(room__code=room)
        if day and day != 'all': qs = qs.filter(time_slot__day=day)
        entries = []
        for e in qs.order_by('time_slot__day', 'time_slot__period_number', 'room__code'):
            dept = e.offering.section.program.department.code
            entries.append({
                'day': self.DAY_MAP.get(e.time_slot.day, e.time_slot.day),
                'dayCode': e.time_slot.day,
                'period': e.time_slot.period_number,
                'startTime': e.time_slot.start_time.strftime('%H:%M'),
                'endTime': e.time_slot.end_time.strftime('%H:%M'),
                'courseCode': e.course_code,
                'courseTitle': e.course_title,
                'section': e.section_label,
                'instructor': e.teacher_name,
                'room': e.room.code,
                'program': e.program_code,
                'year': str(e.year),
                'faculty': dept,
            })
        return Response({'entries': entries})


class TimetableExportView(APIView):
    def get(self, request):
        import csv
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="giki_timetable.csv"'
        writer = csv.writer(response)
        writer.writerow(['Day','Period','Start','End','Course Code','Course Title','Teacher','Room','Section','Program','Year'])
        for e in TimetableEntry.objects.select_related('time_slot', 'room').order_by('time_slot__day', 'time_slot__period_number'):
            writer.writerow([e.time_slot.day, e.time_slot.period_number, e.time_slot.start_time.strftime('%H:%M'), e.time_slot.end_time.strftime('%H:%M'), e.course_code, e.course_title, e.teacher_name, e.room.code, e.section_label, e.program_code, e.year])
        return response


class TimetableClearView(APIView):
    def delete(self, request):
        count, _ = TimetableEntry.objects.all().delete()
        return Response({'message': f'Cleared {count} timetable entries'})


class LoadStaticDataView(APIView):
    def post(self, request):
        try:
            call_command('load_static_data')
            return Response({'status': 'success', 'message': 'Static data loaded successfully'})
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RoomListView(generics.ListAPIView):
    queryset = Room.objects.all()
    serializer_class = RoomSerializer

class CourseListView(generics.ListAPIView):
    queryset = Course.objects.all()
    serializer_class = CourseSerializer

class TeacherListView(generics.ListAPIView):
    queryset = Teacher.objects.all()
    serializer_class = TeacherSerializer

class DepartmentListView(generics.ListAPIView):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer

class ProgramListView(generics.ListAPIView):
    queryset = Program.objects.select_related('department').all()
    serializer_class = ProgramSerializer

class ProspectusListView(generics.ListAPIView):
    queryset = ProspectusEntry.objects.all()
    serializer_class = ProspectusEntrySerializer
