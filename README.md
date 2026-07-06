# GIKI Automated Timetable System

Complete Django + HTML/CSS/JavaScript project for CS378 Automated Timetable Scheduling.

## What this system does
- Loads GIKI rooms and lecture halls from Excel.
- Loads prospectus courses from Excel.
- Uploads Fall/Spring course-offering Excel files.
- Generates a Monday–Friday timetable for all faculties/departments.
- Enforces hard constraints:
  - A teacher cannot be assigned to more than one class at the same time.
  - A classroom cannot host multiple classes simultaneously.
  - A student group/section cannot have overlapping classes.
  - Each course is scheduled according to the required number of sessions.
- Optimizes soft constraints:
  - Fewer student gaps.
  - Avoids long consecutive lectures.
  - Uses room capacity efficiently.
  - Balances teacher workload across days.
  - Places elective classes later where possible.

## Setup

```bash
cd GIKIASS_COMPLETE_PROJECT
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate    # Linux/Mac
pip install -r requirements.txt
python manage.py migrate
python manage.py load_static_data
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/
```

## Recommended workflow
1. Run `python manage.py load_static_data`.
2. Open the web app.
3. Upload `Fall_2025_Courses_by_Faculty.xlsx` or `Spring_2026_Courses_by_Faculty.xlsx`.
4. Click Generate Timetable.
5. Use filters or export CSV.

## Project structure

```text
GIKIASS_COMPLETE_PROJECT/
├── manage.py
├── requirements.txt
├── data/
│   ├── Room_and_Lecture_Halls.xlsx
│   ├── GIKI_Prospectus_courses_extracted.xlsx
│   ├── Fall_2025_Courses_by_Faculty.xlsx
│   └── Spring_2026_Courses_by_Faculty.xlsx
├── giki_timetable/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── api/
│   ├── models.py
│   ├── serializers.py
│   ├── urls.py
│   ├── views.py
│   ├── utils/
│   └── management/commands/
├── algorithm/
│   └── timetable_generator.py
└── frontend/
    ├── index.html
    ├── styles.css
    └── app.js
```
