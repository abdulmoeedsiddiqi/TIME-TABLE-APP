from api.models import Room, ProspectusEntry, Program


def _norm_header(value):
    return ''.join(ch.lower() for ch in str(value or '') if ch.isalnum())


def _find_col(columns, keys):
    normalized = {_norm_header(c): c for c in columns}
    for key in keys:
        if _norm_header(key) in normalized:
            return normalized[_norm_header(key)]
    return None


def _parse_int(value, default=0):
    try:
        if value is None or str(value).strip().lower() in ['', 'nan', 'none']:
            return default
        return int(float(str(value).strip()))
    except Exception:
        return default


def _normalize_program_code(raw):
    code = ''.join(ch for ch in str(raw or '') if ch.isalnum()).upper()
    aliases = {
        'CS': 'BCS', 'COMPSCI': 'BCS', 'COMPUTERSCIENCE': 'BCS',
        'SE': 'BSE', 'SOFTWAREENGINEERING': 'BSE', 'SOFTWAREENG': 'BSE',
        'AI': 'BAI', 'ARTIFICIALINTELLIGENCE': 'BAI',
        'DS': 'BDS', 'DATASCIENCE': 'BDS',
        'CYS': 'BCYS', 'CYBERSECURITY': 'BCYS', 'CYBERSEC': 'BCYS',
        'CE': 'BCE', 'COMPENG': 'BCE', 'COMPUTERENGINEERING': 'BCE',
        'EE': 'BEE', 'ELECTRICALENGINEERING': 'BEE',
        'ES': 'BES', 'ENGINEERINGSCIENCES': 'BES',
        'ME': 'BME', 'MECHANICAL': 'BME', 'MECHANICALENGINEERING': 'BME',
        'MTE': 'BMCE', 'MATERIALS': 'BMCE', 'MATERIALENGINEERING': 'BMCE', 'MATERIALSENGINEERING': 'BMCE',
        'CHE': 'BCH', 'CHEMICAL': 'BCH', 'CHEMICALENGINEERING': 'BCH',
        'CIVIL': 'BCVE', 'CVE': 'BCVE', 'CIVILENGINEERING': 'BCVE',
        'MS': 'BMS', 'MGS': 'BMS', 'MANAGEMENT': 'BMS', 'MANAGEMENTSCIENCES': 'BMS',
    }
    if code.startswith('BS') and len(code) > 2:
        code = code[2:]
    return aliases.get(code, code)


def _sheet_to_program_code(sheet_name):
    name = str(sheet_name or '').strip()
    if not name or name.lower() in ['readme', 'index']:
        return ''
    if '_' in name:
        name = name.split('_', 1)[1]
    return _normalize_program_code(name)


def load_rooms(filepath):
    import pandas as pd
    result = {'loaded': 0, 'skipped': 0, 'errors': [], 'warnings': []}
    try:
        excel = pd.ExcelFile(filepath)
        for sheet in excel.sheet_names:
            df = excel.parse(sheet)
            col_code = _find_col(df.columns, ['Room Code', 'Room', 'Room No', 'Code', 'Room Name', 'Rooms'])
            col_capacity = _find_col(df.columns, ['Capacity', 'Cap', 'Seats', 'Seating Capacity'])
            col_type = _find_col(df.columns, ['Type', 'Room Type', 'Category'])
            col_building = _find_col(df.columns, ['Building', 'Block', 'Location', 'Faculty'])
            if col_code:
                for _, row in df.iterrows():
                    code = str(row.get(col_code, '')).strip()
                    if not code or code.lower() == 'nan':
                        result['skipped'] += 1
                        continue
                    raw_type = str(row.get(col_type, '')).lower() if col_type else code.lower()
                    room_type = 'lab' if 'lab' in raw_type else 'lecture'
                    capacity = _parse_int(row.get(col_capacity), 30 if room_type == 'lab' else 60) if col_capacity else (30 if room_type == 'lab' else 60)
                    building = str(row.get(col_building, '')).strip() if col_building else sheet
                    Room.objects.update_or_create(code=code, defaults={'capacity': capacity, 'room_type': room_type, 'building': building, 'is_active': True})
                    result['loaded'] += 1
                continue
            raw = excel.parse(sheet, header=None).values.tolist()
            for row in raw:
                if not row:
                    continue
                code = str(row[0]).strip()
                if not code or code.lower() in ['nan', 'room name', 'room']:
                    continue
                raw_type = str(row[1]).lower() if len(row) > 1 else code.lower()
                room_type = 'lab' if 'lab' in raw_type else 'lecture'
                Room.objects.update_or_create(code=code, defaults={'capacity': 30 if room_type == 'lab' else 60, 'room_type': room_type, 'building': sheet, 'is_active': True})
                result['loaded'] += 1
    except Exception as exc:
        result['errors'].append(str(exc))
    return result


def load_prospectus(filepath):
    import pandas as pd
    result = {'loaded': 0, 'skipped': 0, 'errors': [], 'warnings': []}
    try:
        excel = pd.ExcelFile(filepath)
        programs = {p.code.upper(): p for p in Program.objects.all()}
        for sheet in excel.sheet_names:
            program_code = _sheet_to_program_code(sheet)
            program = programs.get(program_code.upper())
            if not program:
                continue
            df = excel.parse(sheet)
            col_sem = _find_col(df.columns, ['Semester', 'Sem'])
            col_code = _find_col(df.columns, ['Course Code', 'Code', 'Course'])
            col_title = _find_col(df.columns, ['Course Title', 'Title', 'Course Name'])
            col_ch = _find_col(df.columns, ['Credit Hrs', 'Credit Hours', 'CHs', 'CH', 'Credits'])
            col_type = _find_col(df.columns, ['Course Type', 'Type', 'Lab Hrs', 'Lab'])
            if not col_code:
                result['warnings'].append(f"{sheet}: course code column not found")
                continue
            for _, row in df.iterrows():
                code = str(row.get(col_code, '')).strip()
                if not code or code.lower() == 'nan':
                    result['skipped'] += 1
                    continue
                semester = _parse_int(row.get(col_sem), 1) if col_sem else 1
                title = str(row.get(col_title, '')).strip() if col_title else code
                ch = _parse_int(row.get(col_ch), 3) if col_ch else 3
                raw_type = str(row.get(col_type, '')).lower() if col_type else code.lower()
                course_type = 'lab' if code.upper().endswith('L') or 'lab' in raw_type or 'lab' in title.lower() else 'theory'
                ProspectusEntry.objects.update_or_create(
                    program=program, semester=semester, course_code=code,
                    defaults={'course_title': title, 'credit_hours': max(ch, 1), 'course_type': course_type, 'is_elective': 'elective' in title.lower()}
                )
                result['loaded'] += 1
    except Exception as exc:
        result['errors'].append(str(exc))
    return result
