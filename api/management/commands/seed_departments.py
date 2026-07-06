from django.core.management.base import BaseCommand
from api.models import Department, Program


class Command(BaseCommand):
    help = 'Seed GIKI departments and undergraduate programs'

    def handle(self, *args, **kwargs):
        departments = {
            'FCSE': ('Faculty of Computer Science and Engineering', [('BCS','BS Computer Science'), ('BAI','BS Artificial Intelligence'), ('BSE','BS Software Engineering'), ('BDS','BS Data Science'), ('BCYS','BS Cyber Security'), ('BCE','BS Computer Engineering')]),
            'FEE': ('Faculty of Electrical Engineering', [('BEE','BS Electrical Engineering')]),
            'FES': ('Faculty of Engineering Sciences', [('BES','BS Engineering Sciences')]),
            'FME': ('Faculty of Mechanical Engineering', [('BME','BS Mechanical Engineering')]),
            'FMCE': ('Faculty of Materials and Chemical Engineering', [('BMCE','BS Materials Engineering'), ('BCH','BS Chemical Engineering')]),
            'DCvE': ('Department of Civil Engineering', [('BCVE','BS Civil Engineering')]),
            'SMgS': ('School of Management Sciences', [('BMS','BS Management Sciences')]),
        }
        for dept_code, (dept_name, programs) in departments.items():
            dept, _ = Department.objects.update_or_create(code=dept_code, defaults={'full_name': dept_name})
            for code, name in programs:
                Program.objects.update_or_create(code=code, defaults={'department': dept, 'full_name': name})
        self.stdout.write(self.style.SUCCESS('Departments and programs seeded.'))
