import re
from collections import defaultdict
from api.models import Course, Section, Teacher, Program, CourseOffering, ProspectusEntry


def _norm_header(value: str) -> str:
    return ''.join(ch.lower() for ch in str(value or '') if ch.isalnum())


def _find_header_row(matrix):
    for idx in range(min(8, len(matrix))):
        row = matrix[idx] or []
        normalized = [_norm_header(c) for c in row]
        has_code = 'code' in normalized or 'coursecode' in normalized
        has_sec = 'sec' in normalized or 'section' in normalized or 'sections' in normalized
        has_title = 'coursetitle' in normalized or 'title' in normalized
        has_instr = 'courseinstructor' in normalized or 'instructor' in normalized
        if has_code and has_sec and has_title and has_instr:
            return idx, normalized
    return -1, []


def _parse_year(text: str):
    text = str(text or '')
    match = re.search(r'(\d)(st|nd|rd|th)\s*year', text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r'\byear\s*([1-4])\b', text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r'\b([1-4])\b', text)
    return int(match.group(1)) if match else None


def _normalize_program_token(token: str) -> str:
    return ''.join(ch for ch in str(token or '').upper() if ch.isalnum())


def _program_codes_for_faculty(sheet_name: str, programs_by_code):
    faculty_map = {
        'FCSE': ['BCS', 'BAI', 'BSE', 'BDS', 'BCYS', 'BCE'],
        'FEE': ['BEE', 'BCE'],
        'FES': ['BES'],
        'FME': ['BME'],
        'FMCE': ['BMCE', 'BCH'],
        'DCVE': ['BCVE'],
        'SMGS': ['BMS'],
    }
    key = _normalize_program_token(sheet_name)
    return [code for code in faculty_map.get(key, []) if code in programs_by_code]


def _clean_program_text(text: str) -> str:
    text = str(text or '')
    text = re.sub(r'\bgrp\s*[ivx]+\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\bgroup\s*[ivx]+\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\bgrp\s*\d+\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\bgroup\s*\d+\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b[ivx]+\b$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b([1-4])(st|nd|rd|th)\s*year\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\byear\s*([1-4])\b', '', text, flags=re.IGNORECASE)
    return text.replace('-', ' ').strip()


def _resolve_program_codes(for_col: str, sheet_name: str, programs_by_code, name_map):
    raw = str(for_col or '').strip()
    year = _parse_year(raw)

    alias = {
        'AI': 'BAI', 'BAI': 'BAI',
        'CS': 'BCS', 'BCS': 'BCS', 'COMPSCI': 'BCS', 'COMPUTERSCIENCE': 'BCS',
        'SE': 'BSE', 'SWE': 'BSE', 'BSE': 'BSE', 'SOFTWAREENGINEERING': 'BSE',
        'DS': 'BDS', 'BDS': 'BDS', 'DATASCIENCE': 'BDS',
        'CYS': 'BCYS', 'BCYS': 'BCYS', 'CYBERS': 'BCYS', 'CYSEC': 'BCYS', 'CYBERSECURITY': 'BCYS', 'CYBERSEC': 'BCYS',
        'CE': 'BCE', 'BCE': 'BCE', 'COMPENG': 'BCE', 'COMPUTERENGINEERING': 'BCE',
        'EE': 'BEE', 'BEE': 'BEE', 'EEE': 'BEE', 'EEP': 'BEE', 'FEE': 'BEE',
        'ME': 'BME', 'BME': 'BME', 'FME': 'BME', 'MECHANICAL': 'BME',
        'ES': 'BES', 'BES': 'BES', 'FES': 'BES',
        'SMGS': 'BMS', 'MGS': 'BMS', 'MS': 'BMS', 'BMS': 'BMS', 'MANAGEMENT': 'BMS',
        'CVE': 'BCVE', 'CV': 'BCVE', 'BCVE': 'BCVE', 'CIVIL': 'BCVE', 'DCVE': 'BCVE',
        'MATERIAL': 'BMCE', 'MATERIALS': 'BMCE', 'MATERIALENGINEERING': 'BMCE', 'BMCE': 'BMCE', 'MTE': 'BMCE', 'MTM': 'BMCE', 'FMCE': 'BMCE',
        'CHEMICAL': 'BCH', 'CHEMICALENGINEERING': 'BCH', 'BCH': 'BCH', 'CME': 'BCH', 'CH': 'BCH',
    }

    if not raw or raw.lower() in {'nan', 'none'}:
        return [], year

    tokens = re.split(r'[,+/]|\band\b|&', raw, flags=re.IGNORECASE)
    resolved = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        count_match = re.search(r'(.+?)\s*=\s*(\d+)$', token)
        token_text = count_match.group(1).strip() if count_match else token
        count = int(count_match.group(2)) if count_match else None

        token_text = _clean_program_text(token_text)
        key = _normalize_program_token(token_text)
        token_year = None
        if key and key[-1].isdigit() and key[-1] in '1234':
            token_year = int(key[-1])
            key = key[:-1]
        if key.startswith('BS') and len(key) > 2:
            key = key[2:]

        code = None
        if key in programs_by_code:
            code = key
        elif key in alias:
            code = alias[key]
        elif key in name_map:
            code = name_map[key]

        if code and code in programs_by_code:
            resolved.append((code, token_year or year, count))

    return resolved, year


def _lookup_prospectus(course_code: str, program_codes=None):
    qs = ProspectusEntry.objects.filter(course_code__iexact=str(course_code).strip())
    if program_codes:
        qs = qs.filter(program__code__in=program_codes)
    return qs.select_related('program').order_by('program__code', 'semester')


def _parse_credit_hours(chs_raw, course_code, candidate_program_codes=None):
    if chs_raw is not None and str(chs_raw).strip() not in {'', 'nan', 'None'}:
        try:
            if isinstance(chs_raw, str) and '-' in chs_raw:
                parts = chs_raw.split('-')
                chs = sum(int(float(p.strip())) for p in parts if p.strip())
            else:
                chs = int(float(str(chs_raw).strip()))
            if chs > 0:
                return chs
        except Exception:
            pass

    entry = _lookup_prospectus(course_code, candidate_program_codes).first()
    if entry and entry.credit_hours:
        return int(entry.credit_hours)
    return 3


def _infer_type_and_sessions(course_code: str, title: str, chs: int, candidate_program_codes=None):
    code_upper = str(course_code or '').upper()
    title_upper = str(title or '').upper()
    entry = _lookup_prospectus(course_code, candidate_program_codes).first()
    if entry:
        course_type = entry.course_type
        # In the project data, each lab course is one weekly lab block; each theory
        # course has sessions equal to lecture/credit hours.
        sessions = 1 if course_type == 'lab' else max(1, int(entry.credit_hours or chs or 3))
        return course_type, sessions
    course_type = 'lab' if code_upper.endswith('L') or 'LAB' in title_upper else 'theory'
    sessions = 1 if course_type == 'lab' else max(1, int(chs or 3))
    return course_type, sessions


def _infer_programs_from_prospectus(course_code: str, sheet_name: str, programs_by_code):
    faculty_codes = _program_codes_for_faculty(sheet_name, programs_by_code)
    qs = _lookup_prospectus(course_code, faculty_codes or None)
    resolved = []
    for entry in qs:
        code = entry.program.code.upper()
        if code in programs_by_code:
            year = (int(entry.semester) + 1) // 2
            resolved.append((code, year, None))
    # Avoid generating duplicate sections when multiple specializations of same
    # degree appear in the prospectus (common for FEE streams).
    seen = set()
    deduped = []
    for item in resolved:
        key = (item[0], item[1])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def parse_courses_excel(file_obj, upload_session) -> dict:
    import pandas as pd
    result = {
        "status": "success",
        "total_rows": 0,
        "courses_created": 0,
        "teachers_created": 0,
        "sections_created": 0,
        "warnings": [],
        "errors": [],
        "preview": [],
    }

    file_obj.seek(0)
    try:
        excel = pd.ExcelFile(file_obj)
    except Exception as e:
        result["status"] = "error"
        result["errors"].append(f"Failed to read Excel file: {str(e)}")
        return result

    programs = Program.objects.all()
    programs_by_code = {p.code.upper(): p for p in programs}
    name_map = {_normalize_program_token(p.full_name): p.code.upper() for p in programs}
    total_rows = 0

    for sheet_name in excel.sheet_names:
        df_raw = excel.parse(sheet_name, header=None)
        matrix = df_raw.values.tolist()
        header_idx, header_row = _find_header_row(matrix)
        if header_idx < 0:
            result["warnings"].append(f"Sheet '{sheet_name}': headers not found. Skipping sheet.")
            continue

        def idx(keys):
            for k in keys:
                norm = _norm_header(k)
                if norm in header_row:
                    return header_row.index(norm)
            return -1

        col_code = idx(['Code', 'Course Code'])
        col_sec = idx(['Sec', 'Section', 'Sections'])
        col_title = idx(['Course Title', 'Title'])
        col_chs = idx(['CHs', 'Credit Hours', 'CH'])
        col_instr = idx(['Course Instructor', 'Instructor'])
        col_for = idx(['For', 'Expected to Register', 'Program'])
        col_extra = idx(['Extra Info', 'Students', 'Strength'])

        if col_code < 0 or col_sec < 0 or col_title < 0 or col_instr < 0:
            result["warnings"].append(f"Sheet '{sheet_name}': required columns missing. Skipping sheet.")
            continue

        # FIRST PASS: Collect all explicitly mentioned programs for each course code in this sheet
        explicit_course_programs = defaultdict(set)
        for row_index in range(header_idx + 1, len(matrix)):
            row = matrix[row_index]
            code = str(row[col_code]).strip() if col_code < len(row) else ''
            for_col = str(row[col_for]).strip() if col_for >= 0 and col_for < len(row) else ''
            
            if code and for_col and for_col.lower() not in {'nan', 'none'}:
                # Resolve the programs for this row
                resolved_prog, _ = _resolve_program_codes(for_col, sheet_name, programs_by_code, name_map)
                for prog_code, _, _ in resolved_prog:
                    explicit_course_programs[code].add(prog_code)

        # SECOND PASS: Process rows and create objects
        generic_course_distribution_idx = defaultdict(int)
        
        for row_index in range(header_idx + 1, len(matrix)):
            row = matrix[row_index]
            code = str(row[col_code]).strip() if col_code < len(row) else ''
            sec_label = str(row[col_sec]).strip() if col_sec < len(row) else ''
            title = str(row[col_title]).strip() if col_title < len(row) else ''
            chs_raw = row[col_chs] if col_chs >= 0 and col_chs < len(row) else None
            instructor_name = str(row[col_instr]).strip() if col_instr < len(row) else ''
            for_col = str(row[col_for]).strip() if col_for >= 0 and col_for < len(row) else ''
            extra_raw = row[col_extra] if col_extra >= 0 and col_extra < len(row) else None

            if not code or code.lower() == 'code' or not title:
                continue
            total_rows += 1

            resolved, parsed_year = _resolve_program_codes(for_col, sheet_name, programs_by_code, name_map)
            
            is_pure_generic = not resolved and (not sec_label or sec_label.lower() in {'nan', 'none'})

            if not resolved:
                # Infer from prospectus, but FILTER OUT any programs that were explicitly mapped elsewhere
                inferred = _infer_programs_from_prospectus(code, sheet_name, programs_by_code)
                explicitly_mapped = explicit_course_programs.get(code, set())
                valid_inferred = [item for item in inferred if item[0] not in explicitly_mapped]
                if valid_inferred and is_pure_generic:
                    # Distribute generic rows among the remaining inferred programs
                    idx = generic_course_distribution_idx[code]
                    
                    if 'senior design' in title.lower() or code.upper() in ['CS481', 'CS482']:
                        if idx == 0:
                            resolved = valid_inferred
                        else:
                            resolved = []
                        instructor_name = '-'
                        generic_course_distribution_idx[code] += 1
                    else:
                        chosen = valid_inferred[idx % len(valid_inferred)]
                        cycle = idx // len(valid_inferred)
                        sec_label = chr(ord('A') + cycle)
                        resolved = [chosen]
                        generic_course_distribution_idx[code] += 1
                else:
                    resolved = valid_inferred
                
            if not resolved:
                # Still empty? Then it was either fully covered by explicit mappings (so this is a redundant row)
                # or couldn't be mapped at all. Skip safely.
                continue

            candidate_program_codes = [item[0] for item in resolved]
            chs = _parse_credit_hours(chs_raw, code, candidate_program_codes)
            course_type, sessions_per_week = _infer_type_and_sessions(code, title, chs, candidate_program_codes)

            if not sec_label or sec_label.lower() in {'nan', 'none'}:
                sec_label = 'A'
                
            if 'senior design' in title.lower() or code.upper() in ['CS481', 'CS482']:
                instructor_name = '-'
            elif not instructor_name or instructor_name.lower() in {'nan', 'none'}:
                instructor_name = 'TBA'

            teacher, teacher_created = Teacher.objects.get_or_create(name=instructor_name)
            if teacher_created:
                result["teachers_created"] += 1

            course, course_created = Course.objects.get_or_create(
                upload_session=upload_session,
                code=code,
                defaults={
                    'title': title,
                    'credit_hours': chs,
                    'course_type': course_type,
                    'is_elective': 'elective' in title.lower() or 'xx' in code.lower(),
                },
            )
            if course_created:
                result["courses_created"] += 1

            for prog_code, override_year, student_count in resolved:
                program = programs_by_code.get(prog_code)
                if not program:
                    continue
                year_value = override_year or parsed_year
                if not year_value:
                    entry = _lookup_prospectus(code, [prog_code]).first()
                    if entry:
                        year_value = (int(entry.semester) + 1) // 2
                if not year_value:
                    year_value = 1
                semester = (year_value - 1) * 2 + 1

                if not student_count:
                    try:
                        student_count = int(float(extra_raw)) if extra_raw not in [None, ''] else 30
                    except Exception:
                        student_count = 30

                section, section_created = Section.objects.get_or_create(
                    program=program,
                    year=year_value,
                    label=sec_label,
                    defaults={'semester': semester, 'student_count': student_count or 30},
                )
                if section_created:
                    result["sections_created"] += 1

                CourseOffering.objects.create(
                    upload_session=upload_session,
                    course=course,
                    section=section,
                    teacher=teacher,
                    sessions_per_week=sessions_per_week,
                )

                result["preview"].append({
                    "course_code": code,
                    "section": f"{prog_code}-Y{year_value}{sec_label}",
                    "teacher": teacher.name,
                    "sessions": sessions_per_week,
                    "sheet": sheet_name,
                })

    result["total_rows"] = total_rows
    if not result["preview"]:
        result["status"] = "error"
        result["errors"].append("No valid course rows found in file.")
    return result
