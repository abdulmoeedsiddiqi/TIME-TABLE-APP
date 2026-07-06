from django.db import models
from django.core.exceptions import ValidationError


class Department(models.Model):
    code = models.CharField(max_length=20, unique=True)
    full_name = models.CharField(max_length=200)

    def __str__(self):
        return self.code


class Program(models.Model):
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='programs')
    code = models.CharField(max_length=20, unique=True)
    full_name = models.CharField(max_length=200)

    def __str__(self):
        return self.code


class Room(models.Model):
    ROOM_TYPE_CHOICES = [('lecture', 'Lecture Hall'), ('lab', 'Laboratory')]
    code = models.CharField(max_length=50, unique=True)
    capacity = models.PositiveIntegerField(default=60)
    room_type = models.CharField(max_length=10, choices=ROOM_TYPE_CHOICES, default='lecture')
    building = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.code} ({self.room_type})'


class TimeSlot(models.Model):
    DAY_CHOICES = [('MON','Monday'),('TUE','Tuesday'),('WED','Wednesday'),('THU','Thursday'),('FRI','Friday')]
    day = models.CharField(max_length=3, choices=DAY_CHOICES)
    period_number = models.PositiveIntegerField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        unique_together = ('day', 'period_number')
        ordering = ['day', 'period_number']

    def __str__(self):
        return f'{self.day} P{self.period_number} ({self.start_time}-{self.end_time})'


class Teacher(models.Model):
    name = models.CharField(max_length=200)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name='teachers')
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=['name'])]

    def __str__(self):
        return self.name


class ProspectusEntry(models.Model):
    COURSE_TYPE_CHOICES = [('theory','Theory'),('lab','Laboratory')]
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='prospectus_entries')
    semester = models.PositiveIntegerField()
    course_code = models.CharField(max_length=50)
    course_title = models.CharField(max_length=250, blank=True)
    credit_hours = models.PositiveIntegerField(default=3)
    course_type = models.CharField(max_length=10, choices=COURSE_TYPE_CHOICES, default='theory')
    is_elective = models.BooleanField(default=False)

    class Meta:
        unique_together = ('program', 'semester', 'course_code')
        indexes = [models.Index(fields=['course_code'])]

    def __str__(self):
        return f'{self.program.code} Sem{self.semester} {self.course_code}'


class UploadSession(models.Model):
    STATUS_CHOICES = [('pending','Pending'),('parsed','Parsed'),('generated','Generated'),('failed','Failed')]
    uploaded_file = models.FileField(upload_to='uploads/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True)

    def __str__(self):
        return f'Upload #{self.pk} - {self.status}'


class Course(models.Model):
    COURSE_TYPE_CHOICES = [('theory','Theory'),('lab','Laboratory')]
    upload_session = models.ForeignKey(UploadSession, on_delete=models.CASCADE, related_name='courses')
    code = models.CharField(max_length=50)
    title = models.CharField(max_length=250)
    credit_hours = models.PositiveIntegerField(default=3)
    course_type = models.CharField(max_length=10, choices=COURSE_TYPE_CHOICES, default='theory')
    is_elective = models.BooleanField(default=False)

    class Meta:
        unique_together = ('upload_session', 'code')
        indexes = [models.Index(fields=['code'])]

    def __str__(self):
        return f'{self.code} - {self.title}'


class Section(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='sections')
    year = models.PositiveIntegerField(default=1)
    semester = models.PositiveIntegerField(default=1)
    label = models.CharField(max_length=20, default='A')
    student_count = models.PositiveIntegerField(default=30)

    class Meta:
        unique_together = ('program', 'year', 'label')

    def __str__(self):
        return f'{self.program.code}-Y{self.year}{self.label}'


class CourseOffering(models.Model):
    upload_session = models.ForeignKey(UploadSession, on_delete=models.CASCADE, related_name='offerings')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='offerings')
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='offerings')
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='offerings')
    sessions_per_week = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f'{self.course.code} | {self.section} | {self.teacher.name}'


class TimetableEntry(models.Model):
    offering = models.ForeignKey(CourseOffering, on_delete=models.CASCADE, related_name='timetable_entries')
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='timetable_entries')
    time_slot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE, related_name='timetable_entries')
    generated_at = models.DateTimeField(auto_now=True)
    course_code = models.CharField(max_length=50)
    course_title = models.CharField(max_length=250)
    teacher_name = models.CharField(max_length=200)
    section_label = models.CharField(max_length=60)
    program_code = models.CharField(max_length=20)
    year = models.PositiveIntegerField()

    class Meta:
        # HC2: A room cannot host multiple classes at the same time slot
        unique_together = [('room', 'time_slot')]
        indexes = [
            models.Index(fields=['program_code', 'year']),
            models.Index(fields=['teacher_name']),
            # Indexes to speed up HC1 and HC3 lookups
            models.Index(fields=['teacher_name', 'time_slot']),
            models.Index(fields=['section_label', 'time_slot']),
        ]

    def clean(self):
        """Validate all hard constraints at the model level."""
        # HC1: A teacher cannot be assigned to more than one class at the same time
        if self.offering.teacher and TimetableEntry.objects.filter(
            offering__teacher=self.offering.teacher, time_slot=self.time_slot
        ).exclude(pk=self.pk).exists():
            raise ValidationError(
                f'HC1: Teacher {self.offering.teacher.name} is already booked for {self.time_slot}.'
            )
        # HC2: A classroom cannot host multiple classes simultaneously (enforced by unique_together)
        if TimetableEntry.objects.filter(
            room=self.room, time_slot=self.time_slot
        ).exclude(pk=self.pk).exists():
            raise ValidationError(
                f'HC2: Room {self.room.code} is already booked for {self.time_slot}.'
            )
        # HC3: A student group cannot have overlapping classes
        if TimetableEntry.objects.filter(
            offering__section=self.offering.section, time_slot=self.time_slot
        ).exclude(pk=self.pk).exists():
            raise ValidationError(
                f'HC3: Section {self.offering.section} is already booked for {self.time_slot}.'
            )
