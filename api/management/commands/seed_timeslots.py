from django.core.management.base import BaseCommand
from django.conf import settings
from api.models import TimeSlot
import datetime


class Command(BaseCommand):
    help = 'Seed Monday-Friday time slots only'

    def handle(self, *args, **kwargs):
        TimeSlot.objects.exclude(day__in=settings.TIMETABLE_CONFIG['WORKING_DAYS']).delete()
        for day in settings.TIMETABLE_CONFIG['WORKING_DAYS']:
            for index, (start, end) in enumerate(settings.TIMETABLE_CONFIG['TIME_SLOTS'], start=1):
                start_time = datetime.datetime.strptime(start, '%H:%M').time()
                end_time = datetime.datetime.strptime(end, '%H:%M').time()
                TimeSlot.objects.update_or_create(day=day, period_number=index, defaults={'start_time': start_time, 'end_time': end_time})
        self.stdout.write(self.style.SUCCESS('Monday-Friday time slots seeded.'))
