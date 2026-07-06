from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from api.utils.static_loader import load_rooms, load_prospectus
import os


class Command(BaseCommand):
    help = 'Load GIKI static data from data/ Excel files'

    def handle(self, *args, **kwargs):
        call_command('seed_departments')
        call_command('seed_timeslots')
        data_dir = settings.BASE_DIR / 'data'
        rooms_candidates = ['Room_and_Lecture_Halls.xlsx', 'Room_and_Lecture_Halls(1).xlsx', 'Rooms_and_Lecture_Halls.xlsx', 'rooms.xlsx']
        prospectus_candidates = ['GIKI_Prospectus_courses_extracted.xlsx', 'GIKI_Prospectus_courses_extracted(1).xlsx', 'prospectus_schedule.xlsx']
        def find_file(candidates):
            for name in candidates:
                path = data_dir / name
                if os.path.exists(path):
                    return str(path)
            return None
        rooms_file = find_file(rooms_candidates)
        if rooms_file:
            res = load_rooms(rooms_file)
            self.stdout.write(self.style.SUCCESS(f"Rooms loaded: {res['loaded']}, skipped: {res['skipped']}, errors: {res['errors']}"))
        else:
            self.stdout.write(self.style.WARNING('Rooms Excel file not found in data/'))
        prospectus_file = find_file(prospectus_candidates)
        if prospectus_file:
            res = load_prospectus(prospectus_file)
            self.stdout.write(self.style.SUCCESS(f"Prospectus loaded: {res['loaded']}, skipped: {res['skipped']}, errors: {res['errors']}"))
        else:
            self.stdout.write(self.style.WARNING('Prospectus Excel file not found in data/'))
