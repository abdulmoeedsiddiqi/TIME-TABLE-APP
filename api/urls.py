from django.urls import path
from .views import (
    UploadExcelView, UploadPreviewView, GenerateTimetableView, TimetableListView,
    TimetableExportView, TimetableClearView, LoadStaticDataView, MetadataView,
    RoomListView, CourseListView, TeacherListView, DepartmentListView, ProgramListView,
    ProspectusListView
)

urlpatterns = [
    path('metadata/', MetadataView.as_view()),
    path('upload/', UploadExcelView.as_view()),
    path('upload/<int:pk>/preview/', UploadPreviewView.as_view()),
    path('generate/', GenerateTimetableView.as_view()),
    path('timetable/', TimetableListView.as_view()),
    path('timetable/export/', TimetableExportView.as_view()),
    path('timetable/clear/', TimetableClearView.as_view()),
    path('load-static-data/', LoadStaticDataView.as_view()),
    path('rooms/', RoomListView.as_view()),
    path('courses/', CourseListView.as_view()),
    path('teachers/', TeacherListView.as_view()),
    path('departments/', DepartmentListView.as_view()),
    path('programs/', ProgramListView.as_view()),
    path('prospectus/', ProspectusListView.as_view()),
]
