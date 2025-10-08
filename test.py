import os, sqlite3, uuid, json, time, io, csv
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, jsonify, send_file, abort
import hashlib

# Optional dependency for Excel handling
try:
    import pandas as pd
except Exception:
    pd = None

BASE_DIR = os.path.dirname(__file__)
DB = os.path.join(BASE_DIR, 'cbt.db')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'adminpass')

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS exams (
        id TEXT PRIMARY KEY,
        title TEXT,
        duration_minutes INTEGER,
        started INTEGER DEFAULT 0,
        teacher_id TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS questions (
        id TEXT PRIMARY KEY,
        exam_id TEXT,
        question TEXT,
        choices TEXT,
        answer_index INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        exam_id TEXT,
        start_time INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS results (
        id TEXT PRIMARY KEY,
        token TEXT,
        answers TEXT,
        score INTEGER,
        submitted_at INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS registered_students (
        id TEXT PRIMARY KEY,
        exam_id TEXT,
        student_name TEXT
    )''')
    # audit / teacher
    c.execute('''CREATE TABLE IF NOT EXISTS teachers (
        id TEXT PRIMARY KEY,
        name TEXT UNIQUE,
        password_hash TEXT,
        token TEXT UNIQUE
    )''')
    # audit logs
    c.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
        id TEXT PRIMARY KEY,
        ts INTEGER,
        action TEXT,
        teacher_id TEXT,
        exam_id TEXT,
        details TEXT
    )''')
    conn.commit()

    def ensure_column(table, column, definition):
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        cols = [row[1] for row in cur.fetchall()]
        if column not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            conn.commit()

    ensure_column('results', 'name', 'TEXT')
    ensure_column('results', 'total', 'INTEGER')
    ensure_column('results', 'student_id', 'TEXT')
    ensure_column('sessions', 'student_name', 'TEXT')
    ensure_column('sessions', 'end_time', 'INTEGER')
    ensure_column('exams', 'teacher_id', 'TEXT')
    # audit fields for questions
    ensure_column('questions', 'created_by', 'TEXT')
    ensure_column('questions', 'created_at', 'INTEGER')
    ensure_column('questions', 'updated_by', 'TEXT')
    ensure_column('questions', 'updated_at', 'INTEGER')

    conn.close()

app = Flask(__name__)
init_db()

def db_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def _hash_password(password: str) -> str:
    return hashlib.sha256((password or '').encode('utf-8')).hexdigest()

def get_teacher_by_token(token):
    if not token: return None
    conn = db_conn(); c = conn.cursor()
    c.execute('SELECT id,name,token FROM teachers WHERE token=?', (token,))
    t = c.fetchone()
    conn.close()
    return t

def get_teacher_from_request():
    token = request.headers.get('X-Teacher-Token') or (request.json and request.json.get('teacher_token'))
    if not token: return None
    return get_teacher_by_token(token)

@app.route('/')
def index():
    return redirect(url_for('admin'))

@app.route('/admin')
def admin():
    return render_template('admin.html', admin_password=ADMIN_PASSWORD)

@app.route('/teacher')
def teacher():
    return render_template('teacher.html')

@app.route('/student')
def student_landing():
    return render_template('student.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/api/create_exam', methods=['POST'])
def create_exam():
    data = request.json or {}
    title = data.get('title') or 'Exam'
    try:
        duration = int(data.get('duration') or 30)
    except Exception:
        duration = 30
    exam_id = str(uuid.uuid4())[:8]
    conn = db_conn(); c = conn.cursor()
    c.execute('INSERT INTO exams (id,title,duration_minutes) VALUES (?,?,?)', (exam_id, title, duration))
    conn.commit(); conn.close
    return jsonify({'exam_id': exam_id})

@app.route('/api/add_question', methods=['POST'])
def add_question():
    data = request.json or {}
    teacher = get_teacher_from_request()
    if not teacher:
        return jsonify({'error': 'teacher auth required'}), 401
    exam_id = data.get('exam_id')
    q = data.get('question')
    choices = data.get('choices') or []
    try:
        answer_index = int(data.get('answer_index') or 0)
    except Exception:
        answer_index = 0
    if not exam_id or not q:
        return jsonify({'error': 'missing fields'}), 400
    conn = db_conn(); c = conn.cursor()
    c.execute('SELECT teacher_id FROM exams WHERE id=?', (exam_id,))
    er = c.fetchone()
    if not er:
        conn.close(); return jsonify({'error': 'exam not found'}), 400
    if er['teacher_id'] and er['teacher_id'] != teacher['id']:
        conn.close(); return jsonify({'error': 'not allowed to add questions for this exam'}), 403
    qid = str(uuid.uuid4())[:8]
    now = int(time.time())
    c.execute('INSERT INTO questions (id,exam_id,question,choices,answer_index,created_by,created_at) VALUES (?,?,?,?,?,?,?)',
              (qid, exam_id, q, json.dumps(choices), answer_index, teacher['id'], now))
    conn.commit(); conn.close()
    log_audit('add_question', teacher['id'], exam_id, {'question_id': qid, 'answer_index': answer_index})
    return jsonify({'ok': True, 'question_id': qid})

@app.route('/api/list_exams')
def list_exams():
    conn = db_conn(); c = conn.cursor()
    c.execute('SELECT id,title,duration_minutes,started,teacher_id FROM exams ORDER BY rowid DESC')
    rows = c.fetchall(); conn.close()
    return jsonify([{'id': r['id'], 'title': r['title'], 'duration_minutes': r['duration_minutes'], 'started': bool(r['started']), 'teacher_id': r['teacher_id']} for r in rows])

@app.route('/api/questions/<exam_id>')
def get_questions(exam_id):
    conn = db_conn(); c = conn.cursor()
    c.execute('SELECT id,question,choices,answer_index FROM questions WHERE exam_id=?', (exam_id,))
    rows = c.fetchall(); conn.close()
    qs = []
    for r in rows:
        qs.append({'id': r['id'], 'question': r['question'], 'choices': json.loads(r['choices'] or '[]'), 'answer_index': r['answer_index']})
    return jsonify(qs)

@app.route('/api/start_exam', methods=['POST'])
def start_exam():
    data = request.json or {}
    exam_id = data.get('exam_id')
    student_name = (data.get('student_name') or '').strip()
    admin_pass = data.get('admin_password') or ''
    if not exam_id:
        return jsonify({'error': 'missing exam_id'}), 400
    conn = db_conn(); c = conn.cursor()
    c.execute('SELECT id, duration_minutes, started FROM exams WHERE id=?', (exam_id,))
    er = c.fetchone()
    if not er:
        conn.close(); return jsonify({'error': 'exam not found'}), 400
    # if exam not started, allow only when admin provides password
    if not er['started'] and admin_pass != ADMIN_PASSWORD:
        conn.close(); return jsonify({'error':'exam not open yet'},), 403

    # compute end_time and store it with session
    start_time = int(time.time())
    duration_minutes = int(er['duration_minutes'] or 0)
    end_time = start_time + max(1, duration_minutes) * 60

    c.execute('SELECT COUNT(1) as cnt FROM registered_students WHERE exam_id=?', (exam_id,))
    regcnt = c.fetchone()['cnt']
    if regcnt:
        if not student_name:
            conn.close(); return jsonify({'error': 'student name required for this exam'}), 400
        c.execute('SELECT id FROM registered_students WHERE exam_id=? AND LOWER(student_name)=LOWER(?)', (exam_id, student_name))
        if not c.fetchone():
            conn.close(); return jsonify({'error': 'student not registered for this exam'}), 403
    # prevent multiple active sessions for same student & exam (case-insensitive)
    if student_name:
        c.execute(
            "SELECT token, end_time FROM sessions WHERE exam_id=? AND LOWER(student_name)=LOWER(?)",
            (exam_id, student_name)
        )
        prev = c.fetchone()
        now = int(time.time())
        if prev and prev['end_time'] and prev['end_time'] > now:
            conn.close()
            return jsonify({'error': 'student already has an active session for this exam'}), 409
    token = str(uuid.uuid4())[:8]
    c.execute('INSERT INTO sessions (token,exam_id,start_time,end_time,student_name) VALUES (?,?,?,?,?)',
              (token, exam_id, start_time, end_time, student_name or None))
    conn.commit(); conn.close()
    url = request.host_url.rstrip('/') + url_for('exam_page', token=token)
    return jsonify({'token': token, 'url': url})

@app.route('/exam/<token>')
def exam_page(token):
    conn = db_conn(); c = conn.cursor()
    c.execute('SELECT exam_id,start_time,end_time FROM sessions WHERE token=?', (token,))
    row = c.fetchone()
    if not row:
        conn.close(); abort(404, description="Invalid token")
    exam_id = row['exam_id']
    end_time = row['end_time'] if 'end_time' in row.keys() else None
    c.execute('SELECT title,duration_minutes FROM exams WHERE id=?', (exam_id,))
    er = c.fetchone()
    if er is None:
        conn.close(); abort(404, description="Exam not found")
    title, duration = er['title'], er['duration_minutes']
    c.execute('SELECT id,question,choices FROM questions WHERE exam_id=?', (exam_id,))
    rows = c.fetchall()
    qs = [{'id': r['id'], 'question': r['question'], 'choices': json.loads(r['choices'] or '[]')} for r in rows]
    conn.close()
    # pass remaining seconds to template (fallback to duration*60)
    now = int(time.time())
    remaining = max(0, int(end_time - now)) if end_time else int(duration or 30) * 60
    return render_template('exam.html', token=token, title=title, duration=duration, questions=qs, remaining_seconds=remaining)

@app.route('/api/submit/<token>', methods=['POST'])
def submit(token):
    data = request.json or {}
    answers = data.get('answers') or {}
    name = (data.get('name') or '').strip()
    conn = db_conn(); c = conn.cursor()
    c.execute('SELECT exam_id, start_time, end_time, student_name FROM sessions WHERE token=?', (token,))
    row = c.fetchone()
    if not row:
        conn.close(); return jsonify({'error': 'invalid token'}), 400
    # enforce time limit
    now = int(time.time())
    if 'end_time' in row.keys() and row['end_time'] and now > row['end_time']:
        conn.close(); return jsonify({'error': 'exam time expired'}), 403
    exam_id = row['exam_id']
    if not name and 'student_name' in row.keys() and row['student_name']:
        name = row['student_name']
    c.execute('SELECT id,answer_index FROM questions WHERE exam_id=?', (exam_id,))
    qs = c.fetchall()
    score = 0
    for q in qs:
        qid = q['id']
        correct = str(q['answer_index'])
        if qid in answers and str(answers[qid]) == correct:
            score += 1
    submitted_at = int(time.time())
    rid = str(uuid.uuid4())[:8]
    c.execute('DELETE FROM results WHERE token=?', (token,))
    try:
        c.execute('INSERT INTO results (id,token,name,answers,score,submitted_at,total) VALUES (?,?,?,?,?,?,?)',
                  (rid, token, name, json.dumps(answers), score, submitted_at, len(qs)))
    except sqlite3.OperationalError:
        c.execute('INSERT INTO results (id,token,answers,score,submitted_at) VALUES (?,?,?,?,?)',
                  (rid, token, json.dumps(answers), score, submitted_at))
    conn.commit(); conn.close()
    try:
        save_result_to_excel(name, token, exam_id, score, len(qs), submitted_at)
    except Exception:
        pass
    return jsonify({'score': score, 'total': len(qs)})

def save_result_to_excel(name, token, exam_id, score, total, submitted_at):
    row = {
        'name': name,
        'token': token,
        'score': score,
        'total': total,
        'submitted_at': datetime.fromtimestamp(submitted_at).isoformat()
    }
    fname_xlsx = os.path.join(BASE_DIR, f'results_{exam_id}.xlsx')
    fname_csv = os.path.join(BASE_DIR, f'results_{exam_id}.csv')
    if pd:
        try:
            if os.path.exists(fname_xlsx):
                df = pd.read_excel(fname_xlsx)
                df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            else:
                df = pd.DataFrame([row])
            df.to_excel(fname_xlsx, index=False)
            return
        except Exception:
            pass
    write_header = not os.path.exists(fname_csv)
    with open(fname_csv, 'a', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=['name','token','score','total','submitted_at'])
        if write_header:
            writer.writeheader()
        writer.writerow(row)

@app.route('/api/results_csv/<exam_id>')
def results_csv(exam_id):
    conn = db_conn(); c = conn.cursor()
    c.execute('SELECT r.token, r.name, r.score, r.total, r.submitted_at FROM results r JOIN sessions s ON r.token=s.token WHERE s.exam_id=?', (exam_id,))
    rows = c.fetchall(); conn.close()
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(['token','name','score','total','submitted_at'])
    for r in rows:
        writer.writerow([r['token'], r['name'] or '', r['score'], r['total'] if 'total' in r.keys() else '', datetime.fromtimestamp(r['submitted_at']).isoformat() if r['submitted_at'] else ''])
    mem = io.BytesIO()
    mem.write(si.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, mimetype='text/csv', as_attachment=True, download_name=f'results_{exam_id}.csv')

@app.route('/api/upload_questions', methods=['POST'])
def upload_questions():
    """
    Accept file (CSV or Excel) and exam_id via form-data.
    Teachers may upload questions for their own exams by sending X-Teacher-Token.
    Admin (no teacher token) may also upload.
    """
    exam_id = request.form.get('exam_id')
    file = request.files.get('file')
    teacher = get_teacher_from_request()

    conn = db_conn(); c = conn.cursor()
    c.execute('SELECT id, teacher_id FROM exams WHERE id=?', (exam_id,))
    er = c.fetchone()
    if not er:
        conn.close(); return jsonify({'error': 'exam not found'}), 400

    # if exam is assigned to a teacher, require that the requester is that teacher
    if er['teacher_id']:
        if not teacher or teacher['id'] != er['teacher_id']:
            conn.close(); return jsonify({'error': 'not allowed to upload questions for this exam'}, 403)

    # read file into entries (same parsing logic as before)
    entries = []
    fname = file.filename.lower()
    try:
        if pd and (fname.endswith('.xlsx') or fname.endswith('.xls')):
            df = pd.read_excel(file)
            df.columns = [col.strip() for col in df.columns]
            for _, row in df.iterrows():
                question = row.get('question')
                if not question or (isinstance(question, float) and pd.isna(question)):
                    continue
                choices = []
                i = 1
                while f'choice{i}' in row.index:
                    val = row.get(f'choice{i}')
                    if not (isinstance(val, float) and pd.isna(val)):
                        choices.append(str(val))
                    i += 1
                if not choices:
                    for col in df.columns:
                        if str(col).lower().startswith('choice') and pd.notna(row.get(col)):
                            choices.append(str(row.get(col)))
                answer_index = int(row.get('answer_index') if 'answer_index' in row.index and not pd.isna(row.get('answer_index')) else 0)
                entries.append((question, choices, answer_index))
        else:
            stream = io.StringIO(file.stream.read().decode('utf-8'))
            reader = csv.DictReader(stream)
            for r in reader:
                question = r.get('question') or None
                if not question:
                    continue
                choices = []
                for k,v in r.items():
                    if k and k.lower().startswith('choice') and v:
                        choices.append(v)
                if not choices and r.get('choices'):
                    choices = [c.strip() for c in r.get('choices').split('|') if c.strip()] or [c.strip() for c in r.get('choices').split(',') if c.strip()]
                try:
                    answer_index = int(r.get('answer_index') or 0)
                except Exception:
                    answer_index = 0
                entries.append((question, choices, answer_index))
    except Exception as e:
        conn.close()
        app.logger.exception("upload parsing error: %s", e)
        return jsonify({'error': 'Failed parsing file'}), 400

    # insert entries
    c = conn.cursor()
    inserted = 0
    for question, choices, answer_index in entries:
        qid = str(uuid.uuid4())[:8]
        c.execute('INSERT INTO questions (id,exam_id,question,choices,answer_index) VALUES (?,?,?,?,?)',
                  (qid, exam_id, question, json.dumps(choices), answer_index))
        inserted += 1
    conn.commit(); conn.close()
    app.logger.info("Uploaded %d questions to exam %s by teacher=%s", inserted, exam_id, teacher['id'] if teacher else '-')
    return jsonify({'ok': True, 'count': inserted})

@app.route('/api/upload_students', methods=['POST'])
def upload_students():
    exam_id = request.form.get('exam_id')
    file = request.files.get('file')
    if not exam_id or not file:
        return jsonify({'error': 'Missing exam_id or file'}), 400
    conn = db_conn(); c = conn.cursor()
    c.execute('SELECT id FROM exams WHERE id=?', (exam_id,))
    if not c.fetchone():
        conn.close(); return jsonify({'error': 'exam not found'}), 400
    names = []
    fname = file.filename.lower()
    try:
        if pd and (fname.endswith('.xlsx') or fname.endswith('.xls')):
            df = pd.read_excel(file)
            for _, row in df.iterrows():
                n = row.get('name') or row.get('student') or None
                if n and not (isinstance(n, float) and pd.isna(n)):
                    names.append(str(n).strip())
        else:
            stream = io.StringIO(file.stream.read().decode('utf-8'))
            reader = csv.DictReader(stream)
            for r in reader:
                n = r.get('name') or next(iter(r.values()), None)
                if n:
                    names.append(n.strip())
    except Exception:
        conn.close(); return jsonify({'error': 'Failed parsing file'}), 400

    inserted = 0
    for name in names:
        if not name: continue
        c.execute('SELECT id FROM registered_students WHERE exam_id=? AND LOWER(student_name)=LOWER(?)', (exam_id, name))
        if c.fetchone(): continue
        sid = str(uuid.uuid4())[:8]
        c.execute('INSERT INTO registered_students (id,exam_id,student_name) VALUES (?,?,?)', (sid, exam_id, name))
        inserted += 1
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'count': inserted})

@app.route('/api/add_student', methods=['POST'])
def add_student():
    data = request.json or {}
    exam_id = (data.get('exam_id') or '').strip()
    name = (data.get('name') or '').strip()
    if not exam_id or not name:
        return jsonify({'error': 'exam_id and name required'}), 400
    conn = db_conn(); c = conn.cursor()
    c.execute('SELECT id FROM exams WHERE id=?', (exam_id,))
    if not c.fetchone():
        conn.close(); return jsonify({'error': 'exam not found'}), 400
    c.execute('SELECT id FROM registered_students WHERE exam_id=? AND LOWER(student_name)=LOWER(?)', (exam_id, name))
    if c.fetchone():
        conn.close(); return jsonify({'ok': True, 'note': 'already registered'})
    sid = str(uuid.uuid4())[:8]
    c.execute('INSERT INTO registered_students (id,exam_id,student_name) VALUES (?,?,?)', (sid, exam_id, name))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'student_id': sid})

@app.route('/api/list_students/<exam_id>')
def list_students(exam_id):
    conn = db_conn(); c = conn.cursor()
    c.execute('SELECT id,student_name FROM registered_students WHERE exam_id=? ORDER BY student_name', (exam_id,))
    rows = c.fetchall(); conn.close()
    return jsonify([{'id': r['id'], 'name': r['student_name']} for r in rows])

@app.route('/results/<token>')
def results_page(token):
    conn = db_conn(); c = conn.cursor()
    c.execute('SELECT r.score, r.submitted_at, r.name, s.exam_id FROM results r JOIN sessions s ON r.token=s.token WHERE r.token=?', (token,))
    row = c.fetchone(); conn.close()
    if not row:
        return "Result not found", 404
    score, submitted_at, name, exam_id = row['score'], row['submitted_at'], row['name'] or '', row['exam_id']
    return render_template('results.html', score=score, submitted_at=submitted_at, exam_id=exam_id, name=name, countdown=180)

@app.route('/api/register_teacher', methods=['POST'])
def register_teacher():
    data = request.json or {}
    name = (data.get('name') or '').strip()
    password = data.get('password') or ''
    if not name or not password:
        return jsonify({'error': 'name and password required'}), 400
    conn = db_conn(); c = conn.cursor()
    c.execute('SELECT id FROM teachers WHERE name=?', (name,))
    if c.fetchone():
        conn.close(); return jsonify({'error': 'teacher exists'}), 400
    tid = str(uuid.uuid4())[:8]
    token = str(uuid.uuid4())[:16]
    ph = _hash_password(password)
    c.execute('INSERT INTO teachers (id,name,password_hash,token) VALUES (?,?,?,?)', (tid, name, ph, token))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'teacher_token': token, 'name': name})

@app.route('/api/login_teacher', methods=['POST'])
def login_teacher():
    data = request.json or {}
    name = (data.get('name') or '').strip()
    password = data.get('password') or ''
    if not name or not password:
        return jsonify({'error': 'name and password required'}), 400
    ph = _hash_password(password)
    conn = db_conn(); c = conn.cursor()
    c.execute('SELECT id,token FROM teachers WHERE name=? AND password_hash=?', (name, ph))
    row = c.fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'invalid credentials'}), 401
    return jsonify({'ok': True, 'teacher_token': row['token'], 'name': name})

@app.route('/api/teacher_create_exam', methods=['POST'])
def teacher_create_exam():
    data = request.json or {}
    teacher = get_teacher_from_request()
    if not teacher:
        return jsonify({'error': 'teacher auth required'}), 401
    title = (data.get('title') or 'Exam').strip()
    try:
        duration = int(data.get('duration') or 30)
    except Exception:
        duration = 30
    exam_id = str(uuid.uuid4())[:8]
    conn = db_conn(); c = conn.cursor()
    c.execute('INSERT INTO exams (id,title,duration_minutes,teacher_id) VALUES (?,?,?,?)', (exam_id, title, duration, teacher['id']))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'exam_id': exam_id})

@app.route('/api/set_exam_state', methods=['POST'])
def set_exam_state():
    data = request.json or {}
    exam_id = data.get('exam_id')
    started = bool(data.get('started'))
    admin_pass = data.get('admin_password') or ''
    if admin_pass != ADMIN_PASSWORD:
        return jsonify({'error': 'admin auth required'}), 401
    if not exam_id:
        return jsonify({'error':'exam_id required'}), 400
    conn = db_conn(); c = conn.cursor()
    c.execute('UPDATE exams SET started=? WHERE id=?', (1 if started else 0, exam_id))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'exam_id': exam_id, 'started': started})

def log_audit(action, teacher_id, exam_id, details=None):
    try:
        conn = db_conn(); c = conn.cursor()
        aid = str(uuid.uuid4())[:8]
        c.execute('INSERT INTO audit_logs (id,ts,action,teacher_id,exam_id,details) VALUES (?,?,?,?,?,?)',
                  (aid, int(time.time()), action, teacher_id, exam_id, json
    except Exception:
        pass

if __name__ == '__main__':
    # Inform about optional dependency
    if pd is None:
        print("pandas not installed; Excel upload/save will fallback to CSV. Install pandas & openpyxl for full Excel support.")
    # Start server
    app.run(host='0.0.0.0', port=8000, debug=True)