from django.contrib import admin
from .models import Department, Program, Room, TimeSlot, Teacher, ProspectusEntry, UploadSession, Course, Section, CourseOffering, TimetableEntry

for model in [Department, Program, Room, TimeSlot, Teacher, ProspectusEntry, UploadSession, Course, Section, CourseOffering, TimetableEntry]:
    admin.site.register(model)
