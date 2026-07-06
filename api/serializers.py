from rest_framework import serializers
from .models import UploadSession, Room, Course, Teacher, Department, Program, ProspectusEntry, TimetableEntry


class UploadSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadSession
        fields = '__all__'


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = '__all__'


class CourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = '__all__'


class TeacherSerializer(serializers.ModelSerializer):
    class Meta:
        model = Teacher
        fields = '__all__'


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = '__all__'


class ProgramSerializer(serializers.ModelSerializer):
    department_code = serializers.CharField(source='department.code', read_only=True)
    class Meta:
        model = Program
        fields = ['id', 'code', 'full_name', 'department', 'department_code']


class ProspectusEntrySerializer(serializers.ModelSerializer):
    program_code = serializers.CharField(source='program.code', read_only=True)
    class Meta:
        model = ProspectusEntry
        fields = '__all__'


class TimetableEntrySerializer(serializers.ModelSerializer):
    day = serializers.CharField(source='time_slot.day')
    start_time = serializers.TimeField(source='time_slot.start_time')
    end_time = serializers.TimeField(source='time_slot.end_time')
    room_code = serializers.CharField(source='room.code')

    class Meta:
        model = TimetableEntry
        fields = ['id', 'day', 'start_time', 'end_time', 'course_code', 'course_title', 'teacher_name', 'section_label', 'program_code', 'year', 'room_code']
