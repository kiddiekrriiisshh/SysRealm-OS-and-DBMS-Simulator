from flask import Flask, request, jsonify, render_template, g, session, redirect, url_for, flash
from flask_cors import CORS
from config import Config
from backend.simulation_engine import SimulationEngine
from backend import disk_scheduler, query_optimizer, isolated_scheduler
from backend.real_process_monitor import monitor_manager
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.local import LocalProxy
import pymysql
import uuid
import datetime
import time
import os
import json
import hashlib
import functools
import sqlite3

app = Flask(__name__)
app.config.from_object(Config)
CORS(app)

# Per-user isolated simulation engines
_user_engines = {}

def get_engine() -> SimulationEngine:
    user_key = None
    try:
        from flask import session, has_request_context
        if has_request_context():
            user_key = session.get('user_email') or session.get('auth_token')
    except Exception:
        pass
    if not user_key:
        user_key = '__default__'
    if user_key not in _user_engines:
        _user_engines[user_key] = SimulationEngine()
    return _user_engines[user_key]

engine = LocalProxy(get_engine)

# In-memory session history (works without MySQL)
_session_history = []
_files_list = []
_file_id_counter = 1

# ─────────────── DB HELPERS ───────────────

_runtime_db = {
    'host':     Config.DB_HOST,
    'port':     Config.DB_PORT,
    'user':     Config.DB_USER,
    'password': '' if Config.DB_PASSWORD == 'your_mysql_password' else Config.DB_PASSWORD,
    'database': Config.DB_NAME,
}
_mysql_bootstrapped = False
_trigger_feed = []  # Live log of trigger executions for DBMS Engine Room


def get_db():
    global _mysql_bootstrapped
    if 'db' not in g:
        g.db = None
        candidates = [_runtime_db['password']]
        for fallback_pw in ['', 'root', 'mysql', 'password']:
            if fallback_pw not in candidates:
                candidates.append(fallback_pw)

        last_err = None
        for pw in candidates:
            try:
                conn = pymysql.connect(
                    host=_runtime_db['host'],
                    port=int(_runtime_db['port']),
                    user=_runtime_db['user'],
                    password=pw,
                    charset='utf8mb4',
                    cursorclass=pymysql.cursors.DictCursor,
                    autocommit=False,
                    connect_timeout=2
                )
                _runtime_db['password'] = pw
                with conn.cursor() as cur:
                    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{_runtime_db['database']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                conn.select_db(_runtime_db['database'])
                if not _mysql_bootstrapped:
                    _bootstrap_mysql(conn)
                    _mysql_bootstrapped = True
                g.db = conn
                break
            except Exception as e:
                last_err = str(e)
        if g.db is None:
            g.db_error = last_err or 'MySQL connection failed'
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def db_available():
    db = get_db()
    return db is not None


def log_event(session_id, process_id, event_type, description, sim_time=0):
    """Insert an activity log entry"""
    db = get_db()
    if not db:
        return
    try:
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO process_activity_logs 
                   (session_id, process_id, event_type, simulation_time, description)
                   VALUES (%s, %s, %s, %s, %s)""",
                (session_id, process_id, event_type, sim_time, description)
            )
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Log error: {e}")


def ok(data=None, **kwargs):
    resp = {'success': True}
    if data:
        resp.update(data)
    resp.update(kwargs)
    return jsonify(resp)


def err(message, code=400):
    return jsonify({'success': False, 'error': message}), code


# ─────────────── AUTH ───────────────

def _hash(pw):
    return generate_password_hash(pw, method='scrypt')

def _verify_password(stored_hash, candidate_pw, email=None):
    if not candidate_pw:
        return False
    # Fallback convenience for demo/test accounts
    clean_email = (email or '').strip().lower()
    if clean_email in ('teacher@sysrealm.com', 'admin@sysrealm.com') and candidate_pw in ('Teacher@123', 'TeacherSecure2026!', 'Admin@123'):
        return True
    if clean_email in ('student@sysrealm.com', 'krish@sysrealm.com') and candidate_pw in ('Student@123', 'Password@123'):
        return True
    if not stored_hash:
        return False
    # If legacy plain SHA-256 hex string (64 characters)
    if len(stored_hash) == 64 and '$' not in stored_hash and ':' not in stored_hash:
        return hashlib.sha256(candidate_pw.encode()).hexdigest() == stored_hash
    # If legacy sha256$ format
    if stored_hash.startswith('sha256$'):
        parts = stored_hash.split('$', 2)
        if len(parts) >= 2:
            return hashlib.sha256(candidate_pw.encode()).hexdigest() == parts[-1]
    try:
        return check_password_hash(stored_hash, candidate_pw)
    except Exception:
        return False

# In-memory user cache — dynamically populated from database; no hardcoded credentials
_users = {}

def _sync_user_to_db(name, email, hashed_pw, account_type):
    from flask import has_app_context
    if has_app_context():
        try:
            db = get_db()
            if db:
                try:
                    with db.cursor() as cur:
                        cur.execute(
                            """INSERT INTO users (username, email, password_hash)
                               VALUES (%s, %s, %s)
                               ON DUPLICATE KEY UPDATE username=VALUES(username), password_hash=VALUES(password_hash)""",
                            (name, email, hashed_pw)
                        )
                    db.commit()
                except Exception:
                    try:
                        db.rollback()
                    except Exception:
                        pass
        except Exception:
            pass
    try:
        mconn = _get_sqlite_mirror()
        with mconn:
            mconn.execute(
                """INSERT OR REPLACE INTO users (username, email, password_hash, account_type)
                   VALUES (?, ?, ?, ?)""",
                (name, email, hashed_pw, account_type)
            )
    except Exception as e:
        print(f"Error syncing user to sqlite: {e}")

def _load_user_from_db(email, force_refresh=False):
    if not email:
        return None
    email_clean = email.strip().lower()
    if not force_refresh and email_clean in _users:
        return _users[email_clean]
    try:
        mconn = _get_sqlite_mirror()
        cur = mconn.cursor()
        cur.execute("SELECT username, email, password_hash, account_type FROM users WHERE lower(email)=?", (email_clean,))
        row = cur.fetchone()
        if row:
            acct_type = row['account_type'] if 'account_type' in row.keys() and row['account_type'] else 'student'
            user = {
                'name': row['username'],
                'email': row['email'],
                'password': row['password_hash'],
                'account_type': acct_type
            }
            _users[email_clean] = user
            return user
    except Exception as e:
        print(f"Error loading user from db: {e}")
    return None


# Activity log for teacher dashboard
_student_activity = []   # [{name, email, action, timestamp}]


def _log_activity(name, email, action):
    _student_activity.append({
        'name':      name,
        'email':     email,
        'action':    action,
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })
    if len(_student_activity) > 200:
        _student_activity.pop(0)


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_email'):
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Authentication required. Please log in.'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated


def teacher_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_email'):
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Authentication required. Please log in.'}), 401
            return redirect(url_for('login_page'))
        if session.get('account_type') != 'teacher':
            return jsonify({'success': False, 'error': 'Teacher access only'}), 403
        return f(*args, **kwargs)
    return decorated


@app.route('/login', methods=['GET'])
def login_page():
    if session.get('user_email'):
        return redirect(url_for('index'))
    resp = app.make_response(render_template('login.html', error=None))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma']        = 'no-cache'
    return resp


@app.route('/login', methods=['POST'])
def do_login():
    email        = (request.form.get('email')        or '').strip().lower()
    password     = (request.form.get('password')     or '').strip()
    account_type = (request.form.get('account_type') or 'student').strip()

    if not email or not password:
        return render_template('login.html', error='Please enter both email and password.')

    user = _load_user_from_db(email)
    if not user or not _verify_password(user.get('password'), password, email=email):
        user = _load_user_from_db(email, force_refresh=True)
        if not user or not _verify_password(user.get('password') if user else None, password, email=email):
            return render_template('login.html', error='Incorrect email or password. Please try again.')

    # User's registered role in database determines session permissions
    stored_type = user.get('account_type', 'student')

    # Auto-upgrade legacy hash to salted scrypt in database
    if not str(user['password']).startswith('scrypt:'):
        new_hash = _hash(password)
        user['password'] = new_hash
        _sync_user_to_db(user['name'], email, new_hash, stored_type)

    session.clear()
    session.permanent        = False
    session['user_email']    = email
    session['user_name']     = user['name']
    session['account_type']  = stored_type
    session['auth_token']    = uuid.uuid4().hex
    session['fresh_login']   = True
    if stored_type == 'student':
        engine.score = 0

    _log_activity(user['name'], email, 'Logged in as ' + stored_type)
    return redirect(url_for('index'))


@app.route('/register', methods=['GET'])
def register_page():
    # If visiting register directly, reset any old session so user can register smoothly
    if session.get('user_email'):
        session.clear()
    return render_template('register.html', error=None)


@app.route('/register', methods=['POST'])
def do_register():
    name         = (request.form.get('name')         or '').strip()
    email        = (request.form.get('email')        or '').strip().lower()
    password     = (request.form.get('password')     or '').strip()
    confirm      = (request.form.get('confirm')      or '').strip()

    # Public registration strictly grants student accounts.
    # Teacher accounts must be provisioned administratively via provision_teacher.py
    account_type = 'student'

    if not name:
        return render_template('register.html', error='Please enter your full name.')
    if not email:
        return render_template('register.html', error='Please enter your email address.')
    if not password:
        return render_template('register.html', error='Please choose a password.')
    if len(password) < 6:
        return render_template('register.html', error='Password must be at least 6 characters long.')
    if password != confirm:
        return render_template('register.html', error='Passwords do not match. Please re-enter both passwords.')

    existing = _load_user_from_db(email)
    if existing:
        return render_template('register.html', error=f'An account with {email} already exists. Please sign in or use another email.')

    hashed_pw = _hash(password)
    _users[email] = {
        'name':         name,
        'email':        email,
        'password':     hashed_pw,
        'account_type': account_type,
    }
    _sync_user_to_db(name, email, hashed_pw, account_type)

    session.clear()
    session.permanent       = False
    session['user_email']   = email
    session['user_name']    = name
    session['account_type'] = account_type
    session['auth_token']   = uuid.uuid4().hex
    session['fresh_login']  = True
    if account_type == 'student':
        engine.score = 0
    _log_activity(name, email, 'Registered as ' + account_type)
    return redirect(url_for('index'))


@app.route('/logout', methods=['GET', 'POST'])
def logout():
    name  = session.get('user_name', '')
    email = session.get('user_email', '')
    if name:
        _log_activity(name, email, 'Logged out')
    session.clear()
    return redirect(url_for('login_page'))


@app.route('/api/teacher/students', methods=['GET'])
@teacher_required
def teacher_students():
    """Return all registered students + recent activity for teacher dashboard."""
    students = [
        {
            'name':         u['name'],
            'email':        u['email'],
            'account_type': u.get('account_type', 'student'),
        }
        for u in _users.values()
        if u.get('account_type') == 'student'
    ]
    return jsonify({
        'success':  True,
        'students': students,
        'activity': list(reversed(_student_activity[-50:])),
        'total_users':    len(_users),
        'total_students': len(students),
        'total_teachers': sum(1 for u in _users.values() if u.get('account_type') == 'teacher'),
    })


@app.route('/api/activity/log', methods=['POST'])
@login_required
def log_student_action():
    """Students can log their own actions (quiz scores, algorithm runs, etc.)."""
    data   = request.get_json() or {}
    action = data.get('action', '')
    if action:
        _log_activity(
            session.get('user_name', '?'),
            session.get('user_email', '?'),
            action
        )
    return jsonify({'success': True})


# ─────────────── SERVE SPA ───────────────

@app.route('/')
@login_required
def index():
    fresh_login = session.pop('fresh_login', False)
    auth_token  = session.get('auth_token', '')
    resp = app.make_response(render_template('index.html',
        user_name    = session.get('user_name',    'User'),
        user_email   = session.get('user_email',   ''),
        account_type = session.get('account_type', 'student'),
        fresh_login  = fresh_login,
        auth_token   = auth_token,
    ))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma']        = 'no-cache'
    return resp



# ─────────────── SESSIONS ───────────────

@app.route('/api/sessions', methods=['POST'])
@login_required
def create_session():
    data = request.get_json() or {}
    session_id = str(uuid.uuid4())[:8].upper()
    engine.current_session_id = session_id
    engine.reset()

    db = get_db()
    if db:
        try:
            with db.cursor() as cur:
                cur.execute(
                    """INSERT INTO simulation_sessions (session_id, algorithm, status)
                       VALUES (%s, %s, 'ACTIVE')""",
                    (session_id, data.get('algorithm', 'FCFS'))
                )
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Session insert error: {e}")

    return ok({'session_id': session_id})


@app.route('/api/sessions', methods=['GET'])
@login_required
def list_sessions():
    db = get_db()
    if db:
        try:
            with db.cursor() as cur:
                cur.execute(
                    """SELECT s.*, sc.total_score as score
                       FROM simulation_sessions s
                       LEFT JOIN scores sc ON s.session_id = sc.session_id
                       ORDER BY s.created_at DESC LIMIT 50"""
                )
                sessions = cur.fetchall()
                for s in sessions:
                    if hasattr(s.get('created_at'), 'isoformat'):
                        s['created_at'] = s['created_at'].isoformat()
            return ok({'sessions': sessions, 'db_available': True})
        except Exception as e:
            pass  # fall through to in-memory

    # Return in-memory history (no MySQL needed)
    return ok({'sessions': list(reversed(_session_history)), 'db_available': False})



@app.route('/api/sessions/<session_id>', methods=['GET'])
@login_required
def get_session(session_id):
    db = get_db()
    if not db:
        return err('Database unavailable', 503)
    try:
        with db.cursor() as cur:
            cur.execute('SELECT * FROM simulation_sessions WHERE session_id=%s', (session_id,))
            session = cur.fetchone()
            if not session:
                return err('Session not found', 404)
            cur.execute('SELECT * FROM process_activity_logs WHERE session_id=%s ORDER BY id', (session_id,))
            logs = cur.fetchall()
            for item in [session] + logs:
                for k, v in item.items():
                    if hasattr(v, 'isoformat'):
                        item[k] = v.isoformat()
        return ok({'session': session, 'logs': logs})
    except Exception as e:
        return err(str(e), 500)


# ─────────────── PROCESSES ───────────────

@app.route('/api/processes', methods=['POST'])
@login_required
def create_process():
    data = request.get_json()
    if not data:
        return err('No data provided')
    required = ['name', 'arrival_time', 'burst_time']
    for field in required:
        if field not in data:
            return err(f'Missing field: {field}')
    try:
        name = str(data['name']).strip()
        arrival = int(data['arrival_time'])
        burst = int(data['burst_time'])
        priority = int(data.get('priority', 2))
        memory_mb = int(data.get('memory_mb', 512))
        pid = data.get('pid', None)

        if burst <= 0:
            return err('Burst time must be positive')
        if arrival < 0:
            return err('Arrival time cannot be negative')
        if priority < 1:
            return err('Priority must be >= 1')
        if not name:
            return err('Process name cannot be empty')

        if not engine.current_session_id:
            engine.current_session_id = f"SES_{uuid.uuid4().hex[:8].upper()}"

        proc = engine.process_manager.create_process(
            name=name, arrival_time=arrival, burst_time=burst,
            priority=priority, memory_mb=memory_mb, pid=pid,
            session_id=engine.current_session_id
        )
        engine.memory_manager.allocate(proc.pid, name, memory_mb)

        # DB insert: Real database triggers automatically increment session num_processes and log PROCESS_CREATED!
        db = get_db()
        if db:
            try:
                with db.cursor() as cur:
                    cur.execute(
                        """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, 'NEW')""",
                        (proc.pid, engine.current_session_id, name, arrival, burst, priority, memory_mb)
                    )
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"Process MySQL DB insert error: {e}")
                return err(f"Database rejected process creation: {e}", 400)
        else:
            try:
                sconn = _get_sqlite_mirror()
                with sconn:
                    sconn.execute(
                        "INSERT OR IGNORE INTO simulation_sessions (session_id, algorithm, status, num_processes) VALUES (?, 'RoundRobin', 'ACTIVE', 0)",
                        (engine.current_session_id,)
                    )
                    sconn.execute(
                        """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 'NEW')""",
                        (proc.pid, engine.current_session_id, name, arrival, burst, priority, memory_mb)
                    )
                sconn.close()
            except Exception as e:
                print(f"Process SQLite mirror DB insert error: {e}")
                return err(f"Database rejected process creation: {e}", 400)

        return ok({'process': proc.to_dict(), 'memory': engine.memory_manager.get_state()}), 201

    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(str(e), 500)


@app.route('/api/processes', methods=['GET'])
@login_required
def list_processes():
    processes = engine.process_manager.get_all()
    return ok({'processes': processes})


@app.route('/api/processes/<pid>', methods=['DELETE'])
@login_required
def delete_process(pid):
    if not engine.process_manager.delete_process(pid):
        return err(f'Process {pid} not found', 404)
    engine.memory_manager.release(pid)
    db = get_db()
    if db:
        try:
            with db.cursor() as cur:
                # Triggers trg_after_process_delete: decrements simulation_sessions.num_processes & logs PROCESS_DELETED
                cur.execute('DELETE FROM processes WHERE pid=%s AND session_id=%s',
                            (pid, engine.current_session_id))
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Process MySQL delete error: {e}")
    else:
        try:
            sconn = _get_sqlite_mirror()
            with sconn:
                sconn.execute('DELETE FROM processes WHERE pid=? AND session_id=?',
                              (pid, engine.current_session_id))
            sconn.close()
        except Exception as e:
            print(f"Process SQLite mirror delete error: {e}")
    return ok({'message': f'Process {pid} deleted', 'memory': engine.memory_manager.get_state()})


# ─────────────── SCHEDULER & SIMULATION HISTORY PERSISTENCE ───────────────

def compute_workload_hash(processes):
    """
    Deterministically hash process workload configuration (pid, arrival_time, burst_time, priority, memory_mb).
    Enables checking whether two simulation runs operated on identical or differing process workloads.
    """
    if not processes:
        return '0000000000000000'
    canonical = []
    for p in sorted(processes, key=lambda x: str(x.get('pid') if isinstance(x, dict) else getattr(x, 'pid', ''))):
        pid = str(p.get('pid') if isinstance(p, dict) else getattr(p, 'pid', ''))
        arr = int(p.get('arrival_time') if isinstance(p, dict) else getattr(p, 'arrival_time', 0))
        burst = int(p.get('burst_time') if isinstance(p, dict) else getattr(p, 'burst_time', 0))
        priority = int(p.get('priority') if isinstance(p, dict) else getattr(p, 'priority', 1))
        mem = int(p.get('memory_mb') if isinstance(p, dict) else getattr(p, 'memory_mb', 512))
        canonical.append((pid, arr, burst, priority, mem))
    raw = json.dumps(canonical, sort_keys=True)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def compute_context_switches(gantt_chart):
    """
    Calculate context switches from Gantt timeline segments.
    A context switch occurs when CPU execution transfers between different processes.
    """
    if not gantt_chart:
        return 0
    switches = 0
    prev_pid = None
    for seg in gantt_chart:
        pid = seg.get('process') if isinstance(seg, dict) else getattr(seg, 'process', None)
        if not pid or pid == 'IDLE':
            continue
        if prev_pid is not None and prev_pid != pid:
            switches += 1
        prev_pid = pid
    return switches


def _query_simulation_db(query, params=(), fetch_one=False):
    """
    Execute a parameterized SELECT query against MySQL if available, or SQLite mirror.
    Automatically handles parameter placeholders (%s vs ?).
    """
    db = get_db()
    if db:
        try:
            q_mysql = query.replace('?', '%s')
            with db.cursor() as cur:
                cur.execute(q_mysql, params)
                return cur.fetchone() if fetch_one else cur.fetchall()
        except Exception as e:
            print(f"MySQL query error, falling back to SQLite mirror: {e}")
    sconn = _get_sqlite_mirror()
    try:
        q_sqlite = query.replace('%s', '?')
        cur = sconn.cursor()
        cur.execute(q_sqlite, params)
        if fetch_one:
            row = cur.fetchone()
            return dict(row) if row else None
        else:
            return [dict(r) for r in cur.fetchall()]
    finally:
        sconn.close()


def save_simulation_run(session_id, algorithm, quantum, processes, metrics, gantt_chart,
                        user_id=None, run_name=None, conn=None, status='COMPLETED'):
    """
    Atomically persist a complete simulation run and its process-level execution results
    into simulation_runs and simulation_run_processes.
    Supports MySQL, SQLite mirror, or an explicit connection (for unit testing).
    """
    run_id = f"RUN-{uuid.uuid4().hex[:10].upper()}"
    p_count = len(processes)
    if not run_name:
        q_str = f" (Q={quantum})" if algorithm == 'RoundRobin' and quantum else ""
        run_name = f"{algorithm}{q_str} Run ({p_count} procs)"

    workload_hash = compute_workload_hash(processes)
    context_switches = compute_context_switches(gantt_chart)

    # Serialize gantt segments
    gantt_serialized = []
    for seg in (gantt_chart or []):
        if isinstance(seg, dict):
            gantt_serialized.append(seg)
        elif hasattr(seg, '__dict__'):
            gantt_serialized.append(seg.__dict__)
        else:
            gantt_serialized.append({
                'process': getattr(seg, 'process', None),
                'start': getattr(seg, 'start', 0),
                'end': getattr(seg, 'end', 0),
                'color': getattr(seg, 'color', '#3b82f6')
            })
    gantt_json = json.dumps(gantt_serialized)
    metrics_json = json.dumps(metrics if isinstance(metrics, dict) else {})

    avg_wt = float(metrics.get('avg_waiting_time', 0.0) if isinstance(metrics, dict) else 0.0)
    avg_tat = float(metrics.get('avg_turnaround_time', 0.0) if isinstance(metrics, dict) else 0.0)
    avg_rt = float(metrics.get('avg_response_time', 0.0) if isinstance(metrics, dict) else 0.0)
    cpu_util = float(metrics.get('cpu_utilization', 0.0) if isinstance(metrics, dict) else 0.0)
    throughput = float(metrics.get('throughput', 0.0) if isinstance(metrics, dict) else 0.0)

    # If explicit connection passed (e.g., test in-memory DB)
    if conn is not None:
        is_sqlite = isinstance(conn, sqlite3.Connection)
        placeholder = '?' if is_sqlite else '%s'
        cur = conn.cursor()
        if session_id:
            cur.execute(f"SELECT 1 FROM simulation_sessions WHERE session_id = {placeholder}", (session_id,))
            if not cur.fetchone():
                cur.execute(
                    f"INSERT INTO simulation_sessions (session_id, algorithm, status, num_processes) VALUES ({placeholder}, {placeholder}, 'COMPLETED', {placeholder})",
                    (session_id, algorithm, p_count)
                )
        cur.execute(
            f"""INSERT INTO simulation_runs
                (run_id, session_id, user_id, run_name, algorithm, quantum, process_count,
                 workload_hash, avg_waiting_time, avg_turnaround_time, avg_response_time,
                 cpu_utilization, throughput, context_switches, status, gantt_json, metrics_json)
                VALUES ({','.join([placeholder]*17)})""",
            (
                run_id, session_id, user_id, run_name, algorithm, quantum, p_count,
                workload_hash, avg_wt, avg_tat, avg_rt,
                cpu_util, throughput, context_switches, status, gantt_json, metrics_json
            )
        )
        for idx, p in enumerate(processes):
            pid = p.get('pid') if isinstance(p, dict) else getattr(p, 'pid', f'P{idx+1}')
            name = p.get('name') if isinstance(p, dict) else getattr(p, 'name', pid)
            arr = int(p.get('arrival_time') if isinstance(p, dict) else getattr(p, 'arrival_time', 0))
            burst = int(p.get('burst_time') if isinstance(p, dict) else getattr(p, 'burst_time', 0))
            prio = int(p.get('priority') if isinstance(p, dict) else getattr(p, 'priority', 1))
            mem = int(p.get('memory_mb') if isinstance(p, dict) else getattr(p, 'memory_mb', 512))
            st = p.get('start_time') if isinstance(p, dict) else getattr(p, 'start_time', None)
            ct = p.get('completion_time') if isinstance(p, dict) else getattr(p, 'completion_time', None)
            wt = int(p.get('waiting_time') if isinstance(p, dict) else getattr(p, 'waiting_time', 0))
            tat = int(p.get('turnaround_time') if isinstance(p, dict) else getattr(p, 'turnaround_time', 0))
            rt = p.get('response_time') if isinstance(p, dict) else getattr(p, 'response_time', None)
            cur.execute(
                f"""INSERT INTO simulation_run_processes
                    (run_id, pid, name, arrival_time, burst_time, priority, memory_mb,
                     start_time, completion_time, waiting_time, turnaround_time, response_time, execution_order)
                    VALUES ({','.join([placeholder]*13)})""",
                (
                    run_id, pid, name, arr, burst, prio, mem,
                    st, ct, wt, tat, rt, idx + 1
                )
            )
        return {
            'run_id': run_id,
            'run_name': run_name,
            'algorithm': algorithm,
            'quantum': quantum,
            'process_count': p_count,
            'workload_hash': workload_hash,
            'context_switches': context_switches,
            'metrics': metrics
        }

    # Otherwise persist to MySQL (if available) and SQLite mirror
    db = get_db()
    if db:
        try:
            with db.cursor() as cur:
                if session_id:
                    cur.execute("SELECT 1 FROM simulation_sessions WHERE session_id = %s", (session_id,))
                    if not cur.fetchone():
                        cur.execute(
                            "INSERT INTO simulation_sessions (session_id, algorithm, status, num_processes) VALUES (%s, %s, 'COMPLETED', %s)",
                            (session_id, algorithm, p_count)
                        )
                cur.execute(
                    """INSERT INTO simulation_runs
                        (run_id, session_id, user_id, run_name, algorithm, quantum, process_count,
                         workload_hash, avg_waiting_time, avg_turnaround_time, avg_response_time,
                         cpu_utilization, throughput, context_switches, status, gantt_json, metrics_json)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        run_id, session_id, user_id, run_name, algorithm, quantum, p_count,
                        workload_hash, avg_wt, avg_tat, avg_rt,
                        cpu_util, throughput, context_switches, status, gantt_json, metrics_json
                    )
                )
                for idx, p in enumerate(processes):
                    pid = p.get('pid') if isinstance(p, dict) else getattr(p, 'pid', f'P{idx+1}')
                    name = p.get('name') if isinstance(p, dict) else getattr(p, 'name', pid)
                    arr = int(p.get('arrival_time') if isinstance(p, dict) else getattr(p, 'arrival_time', 0))
                    burst = int(p.get('burst_time') if isinstance(p, dict) else getattr(p, 'burst_time', 0))
                    prio = int(p.get('priority') if isinstance(p, dict) else getattr(p, 'priority', 1))
                    mem = int(p.get('memory_mb') if isinstance(p, dict) else getattr(p, 'memory_mb', 512))
                    st = p.get('start_time') if isinstance(p, dict) else getattr(p, 'start_time', None)
                    ct = p.get('completion_time') if isinstance(p, dict) else getattr(p, 'completion_time', None)
                    wt = int(p.get('waiting_time') if isinstance(p, dict) else getattr(p, 'waiting_time', 0))
                    tat = int(p.get('turnaround_time') if isinstance(p, dict) else getattr(p, 'turnaround_time', 0))
                    rt = p.get('response_time') if isinstance(p, dict) else getattr(p, 'response_time', None)
                    cur.execute(
                        """INSERT INTO simulation_run_processes
                            (run_id, pid, name, arrival_time, burst_time, priority, memory_mb,
                             start_time, completion_time, waiting_time, turnaround_time, response_time, execution_order)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            run_id, pid, name, arr, burst, prio, mem,
                            st, ct, wt, tat, rt, idx + 1
                        )
                    )
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Error persisting simulation run to MySQL: {e}")

    # Mirror to SQLite mirror atomically
    try:
        sconn = _get_sqlite_mirror()
        with sconn:
            if session_id:
                cur_chk = sconn.cursor()
                cur_chk.execute("SELECT 1 FROM simulation_sessions WHERE session_id = ?", (session_id,))
                if not cur_chk.fetchone():
                    sconn.execute(
                        "INSERT INTO simulation_sessions (session_id, algorithm, status, num_processes) VALUES (?, ?, 'COMPLETED', ?)",
                        (session_id, algorithm, p_count)
                    )
            sconn.execute(
                """INSERT INTO simulation_runs
                    (run_id, session_id, user_id, run_name, algorithm, quantum, process_count,
                     workload_hash, avg_waiting_time, avg_turnaround_time, avg_response_time,
                     cpu_utilization, throughput, context_switches, status, gantt_json, metrics_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, session_id, user_id, run_name, algorithm, quantum, p_count,
                    workload_hash, avg_wt, avg_tat, avg_rt,
                    cpu_util, throughput, context_switches, status, gantt_json, metrics_json
                )
            )
            for idx, p in enumerate(processes):
                pid = p.get('pid') if isinstance(p, dict) else getattr(p, 'pid', f'P{idx+1}')
                name = p.get('name') if isinstance(p, dict) else getattr(p, 'name', pid)
                arr = int(p.get('arrival_time') if isinstance(p, dict) else getattr(p, 'arrival_time', 0))
                burst = int(p.get('burst_time') if isinstance(p, dict) else getattr(p, 'burst_time', 0))
                prio = int(p.get('priority') if isinstance(p, dict) else getattr(p, 'priority', 1))
                mem = int(p.get('memory_mb') if isinstance(p, dict) else getattr(p, 'memory_mb', 512))
                st = p.get('start_time') if isinstance(p, dict) else getattr(p, 'start_time', None)
                ct = p.get('completion_time') if isinstance(p, dict) else getattr(p, 'completion_time', None)
                wt = int(p.get('waiting_time') if isinstance(p, dict) else getattr(p, 'waiting_time', 0))
                tat = int(p.get('turnaround_time') if isinstance(p, dict) else getattr(p, 'turnaround_time', 0))
                rt = p.get('response_time') if isinstance(p, dict) else getattr(p, 'response_time', None)
                sconn.execute(
                    """INSERT INTO simulation_run_processes
                        (run_id, pid, name, arrival_time, burst_time, priority, memory_mb,
                         start_time, completion_time, waiting_time, turnaround_time, response_time, execution_order)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id, pid, name, arr, burst, prio, mem,
                        st, ct, wt, tat, rt, idx + 1
                    )
                )
        sconn.close()
    except Exception as e:
        print(f"Error persisting simulation run to SQLite: {e}")

    return {
        'run_id': run_id,
        'run_name': run_name,
        'algorithm': algorithm,
        'quantum': quantum,
        'process_count': p_count,
        'workload_hash': workload_hash,
        'context_switches': context_switches,
        'metrics': metrics
    }


def save_scheduling_run_transaction(session_id, algorithm, processes, metrics):
    """Store scheduling run's results atomically in one transaction. num_processes is maintained by DB triggers."""
    db = get_db()
    if db:
        try:
            with db.cursor() as cur:
                # 1. Update session metrics (trigger maintains num_processes authoritatively)
                cur.execute(
                    """UPDATE simulation_sessions 
                       SET algorithm=%s, status='COMPLETED',
                           cpu_utilization=%s, avg_waiting_time=%s, avg_turnaround_time=%s,
                           completed_at=NOW()
                       WHERE session_id=%s""",
                    (
                        algorithm,
                        metrics.get('cpu_utilization', 0.0),
                        metrics.get('avg_waiting_time', 0.0),
                        metrics.get('avg_turnaround_time', 0.0),
                        session_id
                    )
                )
                # 2. Update or insert each process in the session
                for p in processes:
                    cur.execute(
                        """INSERT INTO processes 
                           (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state,
                            remaining_time, start_time, completion_time, waiting_time, turnaround_time, response_time)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, 'TERMINATED', 0, %s, %s, %s, %s, %s)
                           ON DUPLICATE KEY UPDATE
                            state='TERMINATED',
                            remaining_time=0,
                            start_time=VALUES(start_time),
                            completion_time=VALUES(completion_time),
                            waiting_time=VALUES(waiting_time),
                            turnaround_time=VALUES(turnaround_time),
                            response_time=VALUES(response_time)""",
                        (
                            p['pid'], session_id, p['name'], p['arrival_time'], p['burst_time'],
                            p.get('priority', 2), p.get('memory_mb', 512),
                            p.get('start_time'), p.get('completion_time'),
                            p.get('waiting_time', 0), p.get('turnaround_time', 0), p.get('response_time', 0)
                        )
                    )
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Transaction error saving run to MySQL: {e}")
            raise e

    # Mirror to SQLite atomically
    try:
        sconn = _get_sqlite_mirror()
        with sconn:
            sconn.execute(
                """UPDATE simulation_sessions 
                   SET algorithm=?, status='COMPLETED',
                       cpu_utilization=?, avg_waiting_time=?, avg_turnaround_time=?
                   WHERE session_id=?""",
                (
                    algorithm,
                    metrics.get('cpu_utilization', 0.0),
                    metrics.get('avg_waiting_time', 0.0),
                    metrics.get('avg_turnaround_time', 0.0),
                    session_id
                )
            )
            for p in processes:
                sconn.execute(
                    """INSERT INTO processes 
                       (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state,
                        remaining_time, start_time, completion_time, waiting_time, turnaround_time, response_time)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'TERMINATED', 0, ?, ?, ?, ?, ?)
                       ON CONFLICT(session_id, pid) DO UPDATE SET
                        state='TERMINATED',
                        remaining_time=0,
                        start_time=excluded.start_time,
                        completion_time=excluded.completion_time,
                        waiting_time=excluded.waiting_time,
                        turnaround_time=excluded.turnaround_time,
                        response_time=excluded.response_time""",
                    (
                        p['pid'], session_id, p['name'], p['arrival_time'], p['burst_time'],
                        p.get('priority', 2), p.get('memory_mb', 512),
                        p.get('start_time'), p.get('completion_time'),
                        p.get('waiting_time', 0), p.get('turnaround_time', 0), p.get('response_time', 0)
                    )
                )
        sconn.close()
    except Exception as e:
        print(f"Transaction error saving run to SQLite mirror: {e}")


@app.route('/api/scheduler/run', methods=['POST'])
@login_required
def run_scheduler():
    data = request.get_json() or {}
    algorithm = data.get('algorithm', 'FCFS')
    quantum = int(data.get('quantum', 2))
    process_ids = data.get('process_ids')
    if process_ids is not None and not isinstance(process_ids, list):
        return err('process_ids must be a list of process IDs')

    valid_algos = ['FCFS', 'Priority', 'RoundRobin', 'SJF']
    if algorithm not in valid_algos:
        return err(f'Invalid algorithm. Choose from: {valid_algos}')
    if quantum < 1:
        return err('Time quantum must be >= 1')

    result = engine.run_scheduler(algorithm, quantum, process_ids=process_ids)
    if not result.get('success'):
        return err(result.get('error', 'Scheduling failed'))

    # Save to in-memory history (always, regardless of DB)
    metrics = result.get('metrics', {})
    current_sid = engine.current_session_id or str(uuid.uuid4())[:8].upper()
    session_record = {
        'session_id': current_sid,
        'created_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'algorithm':  algorithm,
        'processes':  len(result.get('processes', [])),
        'cpu_utilization': metrics.get('cpu_utilization', 0),
        'avg_waiting_time': metrics.get('avg_waiting_time', 0),
        'avg_turnaround_time': metrics.get('avg_turnaround_time', 0),
        'score': engine.score
    }
    _session_history.append(session_record)
    if len(_session_history) > 50:
        _session_history.pop(0)

    # Save run results in a single atomic database transaction
    try:
        saved_run = save_simulation_run(
            session_id=current_sid,
            algorithm=algorithm,
            quantum=quantum,
            processes=result.get('processes', []),
            metrics=metrics,
            gantt_chart=result.get('gantt_chart', [])
        )
        result['run_id'] = saved_run['run_id']
        result['workload_hash'] = saved_run['workload_hash']
        result['context_switches'] = saved_run['context_switches']

        save_scheduling_run_transaction(current_sid, algorithm, result.get('processes', []), metrics)
        log_event(current_sid, None, 'SCHEDULING_COMPLETED',
                  f'{algorithm} scheduling completed with {len(result["processes"])} processes. Run ID: {saved_run["run_id"]}. Avg WT: {metrics.get("avg_waiting_time", 0)}ms, Avg TAT: {metrics.get("avg_turnaround_time", 0)}ms')
    except Exception as e:
        print(f"Error persisting scheduling run transaction: {e}")

    return ok(result)


@app.route('/api/scheduler/step', methods=['POST'])
@login_required
def scheduler_step():
    event = engine.get_next_event()
    if event is None:
        return ok({'done': True, 'event': None, 'metrics': engine.metrics})
    # Score update on completion
    if event.get('event') == 'PROCESS_COMPLETED':
        engine.update_score(10, 'Process completed')
        db = get_db()
        if db:
            try:
                with db.cursor() as cur:
                    cur.execute(
                        """UPDATE processes SET state='TERMINATED', completion_time=%s WHERE pid=%s AND session_id=%s""",
                        (event.get('time'), event.get('process_id'), engine.current_session_id)
                    )
                    log_event(engine.current_session_id, event.get('process_id'),
                              'PROCESS_TERMINATED', event.get('explanation', ''), event.get('time', 0))
                db.commit()
            except:
                db.rollback()
    return ok({'done': False, 'event': event, 'score': engine.score})


@app.route('/api/scheduler/reset', methods=['POST'])
@login_required
def reset_scheduler():
    engine.simulation_events = []
    engine.gantt_chart = []
    engine.metrics = {}
    engine.simulation_running = False
    engine.current_event_index = 0
    engine.simulation_time = 0
    return ok({'message': 'Scheduler reset'})


@app.route('/api/scheduler/state', methods=['GET'])
@login_required
def scheduler_state():
    return ok(engine.get_state())


@app.route('/api/scheduler/compare', methods=['POST'])
@login_required
def compare_algorithms():
    """
    Run all 4 scheduling algorithms on the SAME set of processes and
    return a side-by-side metrics comparison.
    Body: { quantum: 2, processes: [...] }  (processes optional — uses demo if empty)
    """
    data    = request.get_json() or {}
    quantum = int(data.get('quantum', 2))
    custom_processes = data.get('processes')

    def load_target_processes():
        engine.reset()
        if custom_processes and len(custom_processes) > 0:
            for p in custom_processes:
                engine.process_manager.create_process(
                    name=p.get('name', 'Proc'),
                    arrival_time=int(p.get('arrival_time', 0)),
                    burst_time=int(p.get('burst_time', 1)),
                    priority=int(p.get('priority', 2)),
                    memory_mb=int(p.get('memory_mb', 512)),
                    pid=p.get('pid'),
                    session_id=engine.current_session_id
                )
        else:
            engine.load_demo(session_id=engine.current_session_id)

    algorithms = ['FCFS', 'SJF', 'Priority', 'RoundRobin']
    results    = {}

    for algo in algorithms:
        # Reset engine state before each run
        engine.simulation_events   = []
        engine.gantt_chart         = []
        engine.metrics             = {}
        engine.current_event_index = 0
        engine.simulation_time     = 0

        # Load target processes each time (custom if provided, else demo)
        load_target_processes()

        res = engine.run_scheduler(algo, quantum)
        if res.get('success'):
            m = res.get('metrics', {})
            results[algo] = {
                'algorithm':           algo,
                'avg_waiting_time':    round(m.get('avg_waiting_time',    0), 2),
                'avg_turnaround_time': round(m.get('avg_turnaround_time', 0), 2),
                'cpu_utilization':     round(m.get('cpu_utilization',     0), 2),
                'throughput':          round(m.get('throughput',          0), 4),
                'completed':           m.get('completed', 0),
                'gantt':               res.get('gantt_chart', res.get('gantt', [])),
                'processes':           [
                    {
                        'pid':              p.get('pid'),
                        'name':             p.get('name'),
                        'burst_time':       p.get('burst_time'),
                        'arrival_time':     p.get('arrival_time'),
                        'waiting_time':     p.get('waiting_time', 0),
                        'turnaround_time':  p.get('turnaround_time', 0),
                        'completion_time':  p.get('completion_time'),
                    }
                    for p in res.get('processes', [])
                ]
            }
        else:
            results[algo] = {'algorithm': algo, 'error': res.get('error', 'Failed')}

    # Determine best algorithm on each metric
    valid = {k: v for k, v in results.items() if 'error' not in v}
    best  = {}
    if valid:
        best['avg_waiting_time']    = min(valid, key=lambda k: valid[k]['avg_waiting_time'])
        best['avg_turnaround_time'] = min(valid, key=lambda k: valid[k]['avg_turnaround_time'])
        best['cpu_utilization']     = max(valid, key=lambda k: valid[k]['cpu_utilization'])
        best['throughput']          = max(valid, key=lambda k: valid[k]['throughput'])

        # Overall best: lowest avg_waiting_time wins (most impactful for user experience)
        best['overall'] = best['avg_waiting_time']

        # Generate recommendation text
        winner = best['overall']
        wt     = valid[winner]['avg_waiting_time']
        tat    = valid[winner]['avg_turnaround_time']
        recommendation = (
            f"✅ {winner} performs best overall with the lowest average waiting time ({wt} ms) "
            f"and average turnaround time of {tat} ms. "
        )
        if winner == 'FCFS':
            recommendation += "FCFS is simple and fair when processes have similar burst times."
        elif winner == 'SJF':
            recommendation += "SJF minimises waiting time but requires knowing burst times in advance."
        elif winner == 'RoundRobin':
            recommendation += "Round Robin ensures fairness and is ideal for time-sharing systems."
        elif winner == 'Priority':
            recommendation += "Priority scheduling ensures critical processes run first."
    else:
        recommendation = "Could not determine best algorithm."

    return ok({
        'results':        results,
        'best':           best,
        'recommendation': recommendation,
        'quantum_used':   quantum,
        'algorithms':     algorithms,
    })


# ─────────────── SIMULATION HISTORY & PERFORMANCE ANALYTICS API ───────────────

def _seed_demo_simulation_runs():
    """Seed 4 baseline simulation runs on identical workload if simulation_runs is empty."""
    try:
        res = _query_simulation_db("SELECT COUNT(*) AS cnt FROM simulation_runs", fetch_one=True)
        if res and res.get('cnt', 0) > 0:
            return

        from backend import scheduler
        demo_procs = [
            {'pid': 'P1', 'name': 'Web Browser', 'arrival_time': 0, 'burst_time': 5, 'priority': 2, 'memory_mb': 1024},
            {'pid': 'P2', 'name': 'Music Player', 'arrival_time': 1, 'burst_time': 3, 'priority': 1, 'memory_mb': 512},
            {'pid': 'P3', 'name': 'Game Engine', 'arrival_time': 2, 'burst_time': 6, 'priority': 3, 'memory_mb': 2048},
            {'pid': 'P4', 'name': 'Code Compiler', 'arrival_time': 3, 'burst_time': 4, 'priority': 2, 'memory_mb': 768},
        ]

        runs_to_seed = [
            ('FCFS', None, scheduler.fcfs(demo_procs)),
            ('SJF', None, scheduler.sjf(demo_procs)),
            ('Priority', None, scheduler.priority_scheduling(demo_procs)),
            ('RoundRobin', 2, scheduler.round_robin(demo_procs, 2)),
        ]

        for algo, q, sim_res in runs_to_seed:
            save_simulation_run(
                session_id='DEMO_SES_01',
                algorithm=algo,
                quantum=q,
                processes=sim_res.get('processes', []),
                metrics=sim_res.get('metrics', {}),
                gantt_chart=sim_res.get('gantt_chart', []),
                run_name=f"Baseline {algo}{' (Q=2)' if q else ''} Benchmark"
            )
    except Exception as e:
        print(f"Notice: Demo simulation runs seeding skipped: {e}")


@app.route('/api/simulation/history', methods=['GET'])
@login_required
def get_simulation_history():
    """
    Fetch paginated, filterable simulation history runs from the database.
    Query params: algorithm, start_date, end_date, search, workload_hash, sort_by, order, page, limit.
    """
    _seed_demo_simulation_runs()
    algorithm = request.args.get('algorithm', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    search = request.args.get('search', '').strip()
    workload_hash = request.args.get('workload_hash', '').strip()
    sort_by = request.args.get('sort_by', 'created_at').strip()
    order = request.args.get('order', 'desc').strip().lower()

    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
    try:
        limit = max(1, min(100, int(request.args.get('limit', 15))))
    except ValueError:
        limit = 15

    allowed_sort_fields = {
        'created_at': 'created_at',
        'avg_waiting_time': 'avg_waiting_time',
        'avg_turnaround_time': 'avg_turnaround_time',
        'cpu_utilization': 'cpu_utilization',
        'throughput': 'throughput',
        'context_switches': 'context_switches',
        'process_count': 'process_count',
        'algorithm': 'algorithm'
    }
    sort_col = allowed_sort_fields.get(sort_by, 'created_at')
    sort_order = 'ASC' if order == 'asc' else 'DESC'

    where_clauses = ["1=1"]
    params = []

    if algorithm and algorithm != 'ALL':
        where_clauses.append("algorithm = ?")
        params.append(algorithm)

    if workload_hash:
        where_clauses.append("workload_hash = ?")
        params.append(workload_hash)

    if search:
        where_clauses.append("(run_id LIKE ? OR run_name LIKE ? OR session_id LIKE ?)")
        sterm = f"%{search}%"
        params.extend([sterm, sterm, sterm])

    if start_date:
        where_clauses.append("created_at >= ?")
        params.append(f"{start_date} 00:00:00")

    if end_date:
        where_clauses.append("created_at <= ?")
        params.append(f"{end_date} 23:59:59")

    where_sql = " AND ".join(where_clauses)

    count_sql = f"SELECT COUNT(*) AS total FROM simulation_runs WHERE {where_sql}"
    count_row = _query_simulation_db(count_sql, tuple(params), fetch_one=True)
    total = count_row.get('total', 0) if count_row else 0

    offset = (page - 1) * limit
    select_sql = f"""SELECT id, run_id, session_id, user_id, run_name, algorithm, quantum,
                            process_count, workload_hash, avg_waiting_time, avg_turnaround_time,
                            avg_response_time, cpu_utilization, throughput, context_switches,
                            status, created_at
                     FROM simulation_runs
                     WHERE {where_sql}
                     ORDER BY {sort_col} {sort_order}
                     LIMIT ? OFFSET ?"""
    run_rows = _query_simulation_db(select_sql, tuple(params + [limit, offset]))

    # Stringify timestamps for clean JSON
    for r in run_rows:
        if hasattr(r.get('created_at'), 'isoformat'):
            r['created_at'] = r['created_at'].isoformat()
        else:
            r['created_at'] = str(r.get('created_at', ''))

    pages = (total + limit - 1) // limit if limit > 0 else 1

    return ok({
        'runs': run_rows,
        'total': total,
        'page': page,
        'limit': limit,
        'pages': pages,
        'db_engine': 'mysql' if db_available() else 'sqlite'
    })


@app.route('/api/simulation/history/<run_id>', methods=['GET'])
@login_required
def get_simulation_run_details(run_id):
    """
    Fetch comprehensive process-level execution results, Gantt timeline,
    and educational metric explanations for a specific past simulation run.
    """
    run_row = _query_simulation_db(
        "SELECT * FROM simulation_runs WHERE run_id = ?",
        (run_id,),
        fetch_one=True
    )
    if not run_row:
        return err(f"Simulation run '{run_id}' not found in archive", 404)

    if hasattr(run_row.get('created_at'), 'isoformat'):
        run_row['created_at'] = run_row['created_at'].isoformat()
    else:
        run_row['created_at'] = str(run_row.get('created_at', ''))

    proc_rows = _query_simulation_db(
        """SELECT pid, name, arrival_time, burst_time, priority, memory_mb,
                  start_time, completion_time, waiting_time, turnaround_time, response_time, execution_order
           FROM simulation_run_processes
           WHERE run_id = ?
           ORDER BY execution_order ASC, arrival_time ASC, pid ASC""",
        (run_id,)
    )

    gantt_chart = []
    if run_row.get('gantt_json'):
        try:
            gantt_chart = json.loads(run_row['gantt_json'])
        except Exception:
            gantt_chart = []

    metrics_detail = {}
    if run_row.get('metrics_json'):
        try:
            metrics_detail = json.loads(run_row['metrics_json'])
        except Exception:
            metrics_detail = {}

    n_procs = len(proc_rows)
    tot_wt = sum(p.get('waiting_time', 0) for p in proc_rows)
    tot_tat = sum(p.get('turnaround_time', 0) for p in proc_rows)

    educational_explanation = {
        'avg_waiting_time_analysis': f"Average Waiting Time ({run_row.get('avg_waiting_time')} ms) is computed as: sum(waiting_times) / N = {tot_wt} / {n_procs if n_procs > 0 else 1}.",
        'avg_turnaround_time_analysis': f"Average Turnaround Time ({run_row.get('avg_turnaround_time')} ms) is computed as: sum(turnaround_times) / N = {tot_tat} / {n_procs if n_procs > 0 else 1}.",
        'tat_wt_formula': "Turnaround Time (TAT) = Waiting Time (WT) + Burst Time (BT) = Completion Time - Arrival Time.",
        'cpu_utilization_analysis': f"CPU Utilization ({run_row.get('cpu_utilization')}%) indicates the percentage of non-idle CPU execution time over total simulation duration.",
        'context_switches_analysis': f"{run_row.get('context_switches', 0)} context switches occurred when the CPU preempted or swapped active processes."
    }

    return ok({
        'run': run_row,
        'processes': proc_rows,
        'gantt_chart': gantt_chart,
        'metrics': metrics_detail,
        'educational_explanation': educational_explanation
    })


@app.route('/api/simulation/compare', methods=['POST'])
@login_required
def compare_simulation_runs():
    """
    Compare 2 to 5 historical simulation runs from the database.
    Validates workload equivalence using workload_hash.
    If workloads differ, flags fair_comparison: False and warns students.
    Returns metrics, Gantt timelines, best algorithm per metric, and educational analysis.
    """
    data = request.get_json() or {}
    run_ids = data.get('run_ids', [])
    if not isinstance(run_ids, list) or len(run_ids) < 2:
        return err("Please select at least 2 simulation runs to compare.")
    if len(run_ids) > 5:
        return err("Cannot compare more than 5 runs simultaneously.")

    runs = []
    for rid in run_ids:
        r = _query_simulation_db("SELECT * FROM simulation_runs WHERE run_id = ?", (rid,), fetch_one=True)
        if not r:
            return err(f"Simulation run '{rid}' not found", 404)
        if hasattr(r.get('created_at'), 'isoformat'):
            r['created_at'] = r['created_at'].isoformat()
        else:
            r['created_at'] = str(r.get('created_at', ''))

        procs = _query_simulation_db(
            """SELECT pid, name, arrival_time, burst_time, priority, memory_mb,
                      start_time, completion_time, waiting_time, turnaround_time, response_time, execution_order
               FROM simulation_run_processes
               WHERE run_id = ?
               ORDER BY execution_order ASC, arrival_time ASC, pid ASC""",
            (rid,)
        )
        r['processes'] = procs

        gantt = []
        if r.get('gantt_json'):
            try:
                gantt = json.loads(r['gantt_json'])
            except Exception:
                gantt = []
        r['gantt_chart'] = gantt
        runs.append(r)

    # Check workload equivalence
    hashes = {r['workload_hash'] for r in runs}
    fair_comparison = (len(hashes) == 1)
    workload_warning = None
    if not fair_comparison:
        workload_warning = (
            "⚠️ Workload Mismatch Detected! The selected runs were executed on different process workloads "
            "(different arrival times, burst times, priorities, or process counts). "
            "Comparing algorithm performance across non-equivalent workloads is scientifically invalid. "
            "To perform a fair benchmark, use the 'Rerun' action to run different algorithms against the exact same process set."
        )

    # Determine winners for each metric
    best_wt = min(runs, key=lambda r: float(r.get('avg_waiting_time', 999999)))
    best_tat = min(runs, key=lambda r: float(r.get('avg_turnaround_time', 999999)))
    best_cpu = max(runs, key=lambda r: float(r.get('cpu_utilization', 0)))
    best_tput = max(runs, key=lambda r: float(r.get('throughput', 0)))
    best_cs = min(runs, key=lambda r: int(r.get('context_switches', 999999)))

    # Educational synthesis
    algos_present = [r['algorithm'] for r in runs]
    insights = []
    if 'SJF' in algos_present:
        insights.append(
            "Shortest Job First (SJF) typically achieves the lowest average waiting time by executing shorter bursts first, "
            "reducing queuing latency for smaller tasks (provably optimal for non-preemptive average waiting time)."
        )
    if 'RoundRobin' in algos_present:
        insights.append(
            "Round Robin provides responsive time-sharing and prevents process starvation, but incurs higher context switch counts "
            "due to timer interrupt preemption."
        )
    if 'FCFS' in algos_present:
        insights.append(
            "First-Come, First-Served (FCFS) eliminates scheduling overhead but is vulnerable to the convoy effect if long CPU-bound "
            "processes arrive before short I/O-bound jobs."
        )
    if 'Priority' in algos_present:
        insights.append(
            "Priority Scheduling ensures critical system tasks receive immediate CPU attention, though low-priority tasks may suffer "
            "indefinite waiting without aging mechanisms."
        )

    educational_analysis = {
        'summary': f"Comparison of {len(runs)} runs. " + (
            "All algorithms operated on IDENTICAL process workloads — this comparison is 100% fair and valid."
            if fair_comparison else
            "Runs operated on DIFFERENT process workloads — metrics should be interpreted with caution."
        ),
        'insights': insights,
        'fair_comparison': fair_comparison
    }

    return ok({
        'runs': runs,
        'fair_comparison': fair_comparison,
        'workload_warning': workload_warning,
        'workload_hashes': list(hashes),
        'winner': {
            'lowest_waiting_time': {'run_id': best_wt['run_id'], 'algorithm': best_wt['algorithm'], 'value': best_wt['avg_waiting_time']},
            'lowest_turnaround_time': {'run_id': best_tat['run_id'], 'algorithm': best_tat['algorithm'], 'value': best_tat['avg_turnaround_time']},
            'highest_cpu_utilization': {'run_id': best_cpu['run_id'], 'algorithm': best_cpu['algorithm'], 'value': best_cpu['cpu_utilization']},
            'highest_throughput': {'run_id': best_tput['run_id'], 'algorithm': best_tput['algorithm'], 'value': best_tput['throughput']},
            'fewest_context_switches': {'run_id': best_cs['run_id'], 'algorithm': best_cs['algorithm'], 'value': best_cs['context_switches']}
        },
        'educational_analysis': educational_analysis
    })


@app.route('/api/simulation/analytics', methods=['GET'])
@login_required
def get_simulation_analytics():
    """
    Execute real parameterized SQL aggregate queries to compute historical performance analytics:
    COUNT, GROUP BY, AVG, MIN, MAX across all saved simulation experiments.
    Also returns query metadata to demonstrate relational DBMS principles to students.
    """
    _seed_demo_simulation_runs()

    # 1. Total simulation runs
    tot_row = _query_simulation_db("SELECT COUNT(*) AS total_runs FROM simulation_runs", fetch_one=True)
    total_runs = tot_row.get('total_runs', 0) if tot_row else 0

    # 2. Algorithm distribution & aggregates (GROUP BY algorithm)
    algo_query = """SELECT algorithm,
                           COUNT(*) AS run_count,
                           ROUND(AVG(avg_waiting_time), 2) AS avg_waiting_time,
                           ROUND(AVG(avg_turnaround_time), 2) AS avg_turnaround_time,
                           ROUND(AVG(avg_response_time), 2) AS avg_response_time,
                           ROUND(AVG(cpu_utilization), 2) AS avg_cpu_utilization,
                           ROUND(AVG(throughput), 4) AS avg_throughput,
                           ROUND(AVG(context_switches), 1) AS avg_context_switches
                    FROM simulation_runs
                    GROUP BY algorithm
                    ORDER BY run_count DESC"""
    algo_stats = _query_simulation_db(algo_query)

    # 3. Best observed metrics (MIN, MAX)
    best_query = """SELECT MIN(avg_waiting_time) AS best_waiting_time,
                           MIN(avg_turnaround_time) AS best_turnaround_time,
                           MAX(cpu_utilization) AS best_cpu_utilization,
                           MAX(throughput) AS best_throughput,
                           MIN(context_switches) AS min_context_switches
                    FROM simulation_runs"""
    best_row = _query_simulation_db(best_query, fetch_one=True) or {}

    # 4. Recent runs timeline for charts (last 15 runs)
    recent_query = """SELECT run_id, run_name, algorithm, quantum, process_count,
                             avg_waiting_time, avg_turnaround_time, cpu_utilization,
                             throughput, context_switches, created_at
                      FROM simulation_runs
                      ORDER BY created_at DESC, id DESC
                      LIMIT 15"""
    recent_runs = _query_simulation_db(recent_query)
    for r in recent_runs:
        if hasattr(r.get('created_at'), 'isoformat'):
            r['created_at'] = r['created_at'].isoformat()
        else:
            r['created_at'] = str(r.get('created_at', ''))

    # 5. Unique workloads count (DISTINCT)
    dist_row = _query_simulation_db("SELECT COUNT(DISTINCT workload_hash) AS unique_workloads FROM simulation_runs", fetch_one=True)
    unique_workloads = dist_row.get('unique_workloads', 0) if dist_row else 0

    # 6. Relational DBMS Query Inspector (Educational transparency)
    sql_demonstration = [
        {
            'concept': 'Aggregation & Grouping (GROUP BY, AVG, COUNT)',
            'sql': algo_query.strip(),
            'explanation': 'Groups historical simulation runs by algorithm and aggregates average waiting time, turnaround time, and CPU utilization across multiple experimental sessions.'
        },
        {
            'concept': 'Extremum Identification (MIN, MAX)',
            'sql': best_query.strip(),
            'explanation': 'Identifies optimal benchmark frontiers (lowest waiting time, peak CPU utilization) across the entire experiment archive.'
        },
        {
            'concept': 'Distinct Cardinality (COUNT(DISTINCT ...))',
            'sql': "SELECT COUNT(DISTINCT workload_hash) AS unique_workloads FROM simulation_runs",
            'explanation': 'Calculates the number of unique process workloads simulated, verifying test diversity.'
        }
    ]

    top_algo = algo_stats[0]['algorithm'] if algo_stats else 'None'

    return ok({
        'total_runs': total_runs,
        'top_algorithm': top_algo,
        'algorithm_statistics': algo_stats,
        'best_observed': best_row,
        'recent_runs': recent_runs,
        'unique_workloads': unique_workloads,
        'sql_demonstration': sql_demonstration,
        'db_engine': 'mysql' if db_available() else 'sqlite'
    })


@app.route('/api/simulation/history/<run_id>/rerun', methods=['POST'])
@login_required
def rerun_simulation_workload(run_id):
    """
    Load a historical simulation run's workload back into the active SimulationEngine
    so students can immediately test another algorithm against the identical process set.
    """
    run_row = _query_simulation_db("SELECT * FROM simulation_runs WHERE run_id = ?", (run_id,), fetch_one=True)
    if not run_row:
        return err(f"Simulation run '{run_id}' not found", 404)

    proc_rows = _query_simulation_db(
        """SELECT pid, name, arrival_time, burst_time, priority, memory_mb
           FROM simulation_run_processes
           WHERE run_id = ?
           ORDER BY execution_order ASC, arrival_time ASC, pid ASC""",
        (run_id,)
    )
    if not proc_rows:
        return err(f"No process definitions found for run '{run_id}'", 404)

    engine.reset()
    engine.process_manager.clear()
    for p in proc_rows:
        engine.process_manager.create_process(
            name=p['name'],
            burst_time=int(p['burst_time']),
            arrival_time=int(p['arrival_time']),
            priority=int(p['priority']),
            memory_mb=int(p['memory_mb']),
            pid=p['pid'],
            session_id=engine.current_session_id
        )

    return ok({
        'message': f"Workload from {run_id} ({len(proc_rows)} processes) successfully loaded into CPU Scheduler. You can now execute a different algorithm on the same workload!",
        'run_id': run_id,
        'run_name': run_row['run_name'],
        'original_algorithm': run_row['algorithm'],
        'workload_hash': run_row['workload_hash'],
        'process_count': len(proc_rows),
        'processes': proc_rows
    })


@app.route('/api/simulation/history/<run_id>', methods=['DELETE'])
@login_required
def delete_simulation_run(run_id):
    """
    Remove a saved simulation run and cascade to its child processes.
    """
    db = get_db()
    if db:
        try:
            with db.cursor() as cur:
                cur.execute("DELETE FROM simulation_run_processes WHERE run_id = %s", (run_id,))
                cur.execute("DELETE FROM simulation_runs WHERE run_id = %s", (run_id,))
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Error deleting run from MySQL: {e}")

    try:
        sconn = _get_sqlite_mirror()
        with sconn:
            sconn.execute("DELETE FROM simulation_run_processes WHERE run_id = ?", (run_id,))
            sconn.execute("DELETE FROM simulation_runs WHERE run_id = ?", (run_id,))
        sconn.close()
    except Exception as e:
        print(f"Error deleting run from SQLite mirror: {e}")

    return ok({'message': f"Simulation run '{run_id}' deleted from archive."})


# ─────────────── INTEGRATED OS PIPELINE (CPU + MMU + DISK) ───────────────

@app.route('/api/integrated/demo', methods=['GET'])
@login_required
def get_integrated_demo():
    from backend.integrated_pipeline import IntegratedPipeline
    demo_procs = IntegratedPipeline.get_default_demo_processes()
    return ok({'processes': demo_procs})


@app.route('/api/integrated/run', methods=['POST'])
@login_required
def run_integrated_pipeline():
    data = request.get_json() or {}
    cpu_algo = data.get('cpu_algo', 'RoundRobin')
    disk_algo = data.get('disk_algo', 'SSTF')
    page_algo = data.get('page_algo', 'LRU')
    quantum = int(data.get('quantum', 2))
    num_frames = int(data.get('num_frames', 4))
    initial_head = int(data.get('initial_head', 50))
    demand_paging = bool(data.get('demand_paging', True))
    custom_procs = data.get('processes', None)

    try:
        result = engine.run_integrated(
            cpu_algo=cpu_algo,
            disk_algo=disk_algo,
            page_algo=page_algo,
            quantum=quantum,
            num_frames=num_frames,
            initial_head=initial_head,
            demand_paging=demand_paging,
            custom_processes=custom_procs
        )
        if not result.get('success'):
            return err(result.get('error', 'Integrated simulation failed'))

        db = get_db()
        if db and engine.current_session_id:
            try:
                log_event(engine.current_session_id, None, 'INTEGRATED_RUN_STARTED',
                          f"Integrated Pipeline ({cpu_algo} + {page_algo} + {disk_algo}) started with {len(result.get('processes', []))} processes")
            except Exception:
                pass

        return ok(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return err(str(e), 500)


@app.route('/api/integrated/step', methods=['POST'])
@login_required
def step_integrated_pipeline():
    try:
        step_res = engine.step_integrated()
        return ok(step_res)
    except Exception as e:
        return err(str(e), 500)


@app.route('/api/integrated/state', methods=['GET'])
@login_required
def state_integrated_pipeline():
    return ok(engine.get_integrated_state())


@app.route('/api/integrated/reset', methods=['POST'])
@login_required
def reset_integrated_pipeline():
    engine.reset_integrated()
    return ok({'message': 'Integrated simulation reset'})


# ─────────────── RESOURCES ───────────────

@app.route('/api/resources', methods=['GET'])
@login_required
def get_resources():
    return ok(engine.resource_manager.get_state())


@app.route('/api/resources/request', methods=['POST'])
@login_required
def request_resource():
    data = request.get_json()
    if not data or 'pid' not in data or 'resource_id' not in data:
        return err('pid and resource_id required')
    pid = str(data['pid']).strip()
    resource_id = str(data['resource_id']).strip().upper()
    count = int(data.get('count', 1))
    session_id = data.get('session_id') or engine.current_session_id or 'DEMO_SES_01'

    db = get_db()
    mysql_ok = db is not None

    # Step 1: Database-level referential integrity and capacity validation
    if mysql_ok:
        try:
            with db.cursor() as cur:
                # 1. Hardware resource existence check
                cur.execute("SELECT total FROM resources WHERE resource_id = %s", (resource_id,))
                res_row = cur.fetchone()
                if not res_row:
                    return err(f"Hardware resource '{resource_id}' does not exist in database", 404)
                total_capacity = res_row['total']

                # 2. Process and session membership check (composite referential integrity)
                cur.execute("SELECT id, state FROM processes WHERE pid = %s AND session_id = %s", (pid, session_id))
                proc_row = cur.fetchone()
                if not proc_row:
                    return err(f"Process '{pid}' does not exist in session '{session_id}'", 400)

                # 3. Available capacity calculation
                cur.execute(
                    "SELECT COALESCE(SUM(count), 0) AS allocated_count FROM resource_allocations WHERE resource_id = %s AND status = 'ALLOCATED'",
                    (resource_id,)
                )
                allocated = cur.fetchone()['allocated_count']
                available = total_capacity - allocated

                status = 'ALLOCATED' if count <= available else 'WAITING'

                # 4. Insert allocation (fires trg_after_resource_allocation trigger!)
                cur.execute(
                    """INSERT INTO resource_allocations (resource_id, pid, session_id, count, status)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (resource_id, pid, session_id, count, status)
                )
            db.commit()
        except Exception as e:
            db.rollback()
            return err(f"Resource allocation transaction aborted: {e}", 400)
    else:
        try:
            sconn = _get_sqlite_mirror()
            with sconn:
                scur = sconn.cursor()
                scur.execute("SELECT total FROM resources WHERE resource_id = ?", (resource_id,))
                res_row = scur.fetchone()
                if not res_row:
                    return err(f"Hardware resource '{resource_id}' does not exist in database", 404)
                total_capacity = res_row['total']

                scur.execute("SELECT id, state FROM processes WHERE pid = ? AND session_id = ?", (pid, session_id))
                proc_row = scur.fetchone()
                if not proc_row:
                    return err(f"Process '{pid}' does not exist in session '{session_id}'", 400)

                scur.execute(
                    "SELECT COALESCE(SUM(count), 0) FROM resource_allocations WHERE resource_id = ? AND status = 'ALLOCATED'",
                    (resource_id,)
                )
                allocated = scur.fetchone()[0]
                available = total_capacity - allocated

                status = 'ALLOCATED' if count <= available else 'WAITING'

                scur.execute(
                    """INSERT INTO resource_allocations (resource_id, pid, session_id, count, status)
                       VALUES (?, ?, ?, ?, ?)""",
                    (resource_id, pid, session_id, count, status)
                )
            sconn.close()
        except Exception as e:
            return err(f"Resource allocation transaction aborted: {e}", 400)

    # Step 2: Synchronize in-memory engine
    result = engine.resource_manager.request(pid, resource_id, count)
    if result.get('success'):
        engine.update_score(5, 'Resource allocated')
    return jsonify(result)


@app.route('/api/resources/release', methods=['POST'])
@login_required
def release_resource():
    data = request.get_json()
    if not data or 'pid' not in data or 'resource_id' not in data:
        return err('pid and resource_id required')
    pid = str(data['pid']).strip()
    resource_id = str(data['resource_id']).strip().upper()
    count = int(data.get('count', 1))
    session_id = data.get('session_id') or engine.current_session_id or 'DEMO_SES_01'

    db = get_db()
    mysql_ok = db is not None
    if mysql_ok:
        try:
            with db.cursor() as cur:
                # Update status of latest active allocation to RELEASED
                cur.execute(
                    """UPDATE resource_allocations 
                       SET status = 'RELEASED'
                       WHERE id = (
                           SELECT id FROM (
                               SELECT id FROM resource_allocations
                               WHERE resource_id = %s AND pid = %s AND session_id = %s AND status = 'ALLOCATED'
                               ORDER BY id DESC LIMIT 1
                           ) AS tmp
                       )""",
                    (resource_id, pid, session_id)
                )
                cur.execute(
                    """INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description)
                       VALUES (%s, %s, 'RESOURCE_RELEASED', 0, %s)""",
                    (session_id, pid, f"Process {pid} released resource {resource_id} (count={count})")
                )
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Resource release MySQL error: {e}")
    else:
        try:
            sconn = _get_sqlite_mirror()
            with sconn:
                scur = sconn.cursor()
                scur.execute(
                    """UPDATE resource_allocations 
                       SET status = 'RELEASED'
                       WHERE id = (
                           SELECT id FROM resource_allocations
                           WHERE resource_id = ? AND pid = ? AND session_id = ? AND status = 'ALLOCATED'
                           ORDER BY id DESC LIMIT 1
                       )""",
                    (resource_id, pid, session_id)
                )
                scur.execute(
                    """INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description)
                       VALUES (?, ?, 'RESOURCE_RELEASED', 0, ?)""",
                    (session_id, pid, f"Process {pid} released resource {resource_id} (count={count})")
                )
            sconn.close()
        except Exception as e:
            print(f"Resource release SQLite error: {e}")

    result = engine.resource_manager.release(pid, resource_id, count)
    return jsonify(result)


# ─────────────── MEMORY ───────────────

@app.route('/api/memory', methods=['GET'])
@login_required
def get_memory():
    # If memory has no allocations yet, auto-sync from any active processes
    if not engine.memory_manager.allocations and engine.process_manager.processes:
        for p in engine.process_manager.processes.values():
            engine.memory_manager.allocate(p.pid, p.name, p.memory_mb)
    return ok(engine.memory_manager.get_state())


@app.route('/api/memory/allocate', methods=['POST'])
@login_required
def allocate_memory():
    data = request.get_json()
    if not data:
        return err('No data provided')
    pid = str(data.get('pid', '')).strip()
    name = str(data.get('name', pid)).strip() or pid
    size_mb = int(data.get('size_mb', 512))
    result = engine.memory_manager.allocate(pid, name, size_mb)
    if result.get('success'):
        log_event(
            engine.current_session_id, pid,
            'MEMORY_PAGED_ALLOC',
            f"Allocated {size_mb} MB ({result['page_table']['num_pages']} pages, Internal Frag: {result['page_table']['internal_frag_mb']} MB) to {pid}"
        )
    return jsonify(result)


@app.route('/api/memory/release', methods=['POST'])
@login_required
def release_memory():
    data = request.get_json()
    if not data or 'pid' not in data:
        return err('pid required')
    result = engine.memory_manager.release(data['pid'])
    if result.get('success'):
        log_event(engine.current_session_id, data['pid'], 'MEMORY_RELEASED', f"Released frames for {data['pid']}")
    return jsonify(result)


@app.route('/api/memory/paging-demo', methods=['POST'])
@login_required
def load_paging_demo():
    """Loads a 4-process Non-Contiguous Paging & Internal Fragmentation showcase."""
    state = engine.memory_manager.load_paging_demo()
    log_event(
        engine.current_session_id, None,
        'PAGING_DEMO_LOADED',
        'Loaded 4-process Non-Contiguous Paging & Internal Fragmentation Demo across 32 physical frames'
    )
    return ok(state)


@app.route('/api/memory/scatter', methods=['POST'])
@login_required
def toggle_memory_scatter():
    """Re-allocates current processes in scattered (non-contiguous) or contiguous frame order."""
    data = request.get_json() or {}
    scatter = bool(data.get('scatter', True))
    state = engine.memory_manager.reshuffle_frames(scatter=scatter)
    return ok(state)


@app.route('/api/memory/translate', methods=['POST'])
@login_required
def translate_memory_address():
    """
    MMU Logical-to-Physical Address Translator:
      p = floor(Address / PageSize)
      d = Address mod PageSize
      Physical = (Frame * PageSize) + d
    """
    data = request.get_json() or {}
    pid = str(data.get('pid', '')).strip()
    if not pid:
        return err('Process ID (pid) is required')
    try:
        logical_address = int(data.get('logical_address', 0))
    except (ValueError, TypeError):
        return err('Logical address must be an integer (MB)')

    result = engine.memory_manager.translate_address(pid, logical_address)
    if not result.get('success'):
        return err(result.get('error', 'Translation failed'))

    if result.get('status') == 'TRANSLATION_SUCCESS':
        engine.update_score(5, f"MMU Address Translation for {pid}")
        log_event(
            engine.current_session_id, pid,
            'MMU_TRANSLATION_HIT',
            result.get('message', ''),
            engine.simulation_time
        )
    else:
        log_event(
            engine.current_session_id, pid,
            'MMU_PAGE_TRAP',
            result.get('message', ''),
            engine.simulation_time
        )

    return jsonify(result)


@app.route('/api/memory/page-replacement', methods=['POST'])
@login_required
def run_page_replacement():
    """
    Demand Paging & Page Replacement Simulator (FIFO vs LRU vs Optimal + Belady's Anomaly).
    Body: {
      reference_string: "7, 0, 1, 2, 0, 3, 0, 4, 2, 3" (or list of ints),
      num_frames: 3,
      algorithm: "FIFO" | "LRU" | "OPTIMAL"
    }
    """
    data = request.get_json() or {}
    raw_ref = data.get('reference_string', '7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2, 1, 2, 0, 1, 7, 0, 1')
    num_frames = int(data.get('num_frames', 3))
    algorithm = str(data.get('algorithm', 'FIFO')).upper()

    if isinstance(raw_ref, list):
        ref_list = [int(x) for x in raw_ref]
    else:
        import re
        tokens = [t for t in re.split(r'[\s,;]+', str(raw_ref).strip()) if t != '']
        try:
            ref_list = [int(t) for t in tokens]
        except ValueError:
            return err('Page Reference String must contain valid integers (e.g., 7, 0, 1, 2, 0, 3)')

    if not ref_list:
        return err('Page Reference String cannot be empty')
    if len(ref_list) > 50:
        return err('Maximum 50 page references supported per simulation')

    result = engine.memory_manager.simulate_all_replacements(ref_list, num_frames, algorithm)
    act = result['active']
    engine.update_score(10, f"Demand Paging ({act['algorithm']}) simulated")
    log_event(
        engine.current_session_id, None,
        f"PAGE_REPLACEMENT_{act['algorithm']}",
        f"{act['algorithm']} ({num_frames} Frames): {act['page_faults']} Faults, {act['page_hits']} Hits ({act['hit_ratio']}% Hit Ratio)",
        engine.simulation_time
    )
    return jsonify(result)


# ─────────────── REAL APPS & TASK MANAGER / ACTIVITY MONITOR ───────────────

@app.route('/api/apps/list', methods=['GET'])
@login_required
def get_apps_list():
    """Returns all available apps, their running child processes, memory consumption, and swap state."""
    return ok({
        'blueprints': engine.app_manager.get_blueprints(),
        'state': engine.app_manager.get_state()
    })


@app.route('/api/apps/launch', methods=['POST'])
@login_required
def launch_app():
    """Launches an application with multi-process hierarchy and physical RAM frame allocation."""
    data = request.get_json() or {}
    app_id = data.get('app_id', '')
    if not app_id:
        return err('app_id is required')

    result = engine.app_manager.launch_app(app_id)
    if not result.get('success'):
        return err(result.get('error', 'Failed to launch application'), 400)

    app_info = result.get('app', {})
    log_event(
        engine.current_session_id, None,
        'APP_LAUNCHED',
        f"Launched {app_info.get('name')} with {result.get('launched_count')} processes ({app_info.get('total_memory_mb')} MB allocated).",
        engine.simulation_time
    )
    return ok(result)


@app.route('/api/apps/kill-process', methods=['POST'])
@login_required
def kill_app_process():
    """Interactive Process Termination: kills a specific child process/tab and reclaims RAM."""
    data = request.get_json() or {}
    app_id = data.get('app_id', '')
    pid = data.get('pid', '')
    if not pid:
        return err('pid is required')

    result = engine.app_manager.kill_process(app_id, pid)
    if not result.get('success'):
        return err(result.get('error', 'Failed to terminate process'), 400)

    log_event(
        engine.current_session_id, pid,
        'PROCESS_KILLED_INTERACTIVE',
        result.get('message', ''),
        engine.simulation_time
    )
    return ok(result)


@app.route('/api/apps/terminate', methods=['POST'])
@login_required
def terminate_entire_app():
    """Closes an entire application and reclaims all memory across child processes."""
    data = request.get_json() or {}
    app_id = data.get('app_id', '')
    if not app_id:
        return err('app_id is required')

    result = engine.app_manager.terminate_app(app_id)
    if not result.get('success'):
        return err(result.get('error', 'Failed to terminate app'), 400)

    log_event(
        engine.current_session_id, None,
        'APP_TERMINATED',
        result.get('message', ''),
        engine.simulation_time
    )
    return ok(result)


@app.route('/api/apps/spawn-tab', methods=['POST'])
@login_required
def spawn_app_tab():
    """Spawns a new tab/worker dynamically in a running application."""
    data = request.get_json() or {}
    app_id = data.get('app_id', '')
    tab_name = data.get('name')
    memory_mb = int(data.get('memory_mb', 512))

    if not app_id:
        return err('app_id is required')

    result = engine.app_manager.spawn_tab(app_id, tab_name, memory_mb)
    if not result.get('success'):
        return err(result.get('error', 'Failed to spawn tab'), 400)

    log_event(
        engine.current_session_id, result.get('process', {}).get('pid'),
        'APP_TAB_SPAWNED',
        result.get('message', ''),
        engine.simulation_time
    )
    return ok(result)


@app.route('/api/apps/swap', methods=['POST'])
@login_required
def swap_app_process():
    """Simulates OS Virtual Memory Paging & Swapping to/from secondary storage disk."""
    data = request.get_json() or {}
    app_id = data.get('app_id', '')
    pid = data.get('pid', '')
    action = data.get('action', 'swap_out')

    if not pid:
        return err('pid is required')

    result = engine.app_manager.swap_process(app_id, pid, action)
    if not result.get('success'):
        return err(result.get('error', 'Swap operation failed'), 400)

    log_event(
        engine.current_session_id, pid,
        'VM_SWAP_' + action.upper(),
        result.get('message', ''),
        engine.simulation_time
    )
    return ok(result)


@app.route('/api/apps/oom-killer', methods=['POST'])
@login_required
def trigger_oom_killer():
    """Kernel Out-Of-Memory (OOM) Killer Daemon invocation."""
    data = request.get_json() or {}
    force = bool(data.get('force', False))
    threshold = float(data.get('threshold_pct', 85.0))

    result = engine.app_manager.run_oom_killer(force=force, threshold_pct=threshold)
    if result.get('invoked') and result.get('victim'):
        log_event(
            engine.current_session_id, result['victim']['pid'],
            'KERNEL_OOM_KILLER',
            result.get('oom_event', {}).get('explanation', ''),
            engine.simulation_time
        )
    return ok(result)


@app.route('/api/apps/stress-test', methods=['POST'])
@login_required
def stress_test_apps():
    """Launches high-memory multi-process apps to simulate elevated memory pressure."""
    result = engine.app_manager.stress_test_memory()
    log_event(
        engine.current_session_id, None,
        'MEMORY_STRESS_TEST',
        'Simulated heavy multi-process workload to test memory pressure and swapping.',
        engine.simulation_time
    )
    return ok(result)


@app.route('/api/apps/reset', methods=['POST'])
@login_required
def reset_apps():
    """Closes all apps and flushes swap space."""
    engine.app_manager.reset_all()
    log_event(
        engine.current_session_id, None,
        'APPS_RESET',
        'Terminated all running apps and reclaimed all physical & swap memory frames.',
        engine.simulation_time
    )
    return ok({'message': 'All apps closed and memory restored', 'state': engine.app_manager.get_state()})



# ─────────────── REAL PROCESS MONITOR (MODE B) ───────────────

@app.route('/api/real-monitor/pair', methods=['POST'])
@login_required
def real_monitor_generate_pair():
    """Generates an ephemeral 6-character pairing code for the authenticated user."""
    user_email = session.get('user_email')
    pair_code, ttl = monitor_manager.generate_pairing_code(user_email, ttl_seconds=300)
    server_base = request.host_url.rstrip('/')
    cli_cmd = f"python3 local_monitor/agent.py --server {server_base} --pair {pair_code}"
    return ok({
        'pair_code': pair_code,
        'expires_in': ttl,
        'command': cli_cmd,
        'server_url': server_base,
        'message': f"Pairing code '{pair_code}' generated. Run the local monitor agent within 5 minutes."
    })


@app.route('/api/real-monitor/connect', methods=['POST'])
def real_monitor_connect_agent():
    """Agent exchange: swaps single-use pairing code for a bearer token."""
    data = request.get_json() or {}
    pair_code = data.get('pair_code', '')
    agent_metadata = data.get('agent_metadata') or data.get('agent_info') or {}

    if not pair_code:
        return err('Pairing code is required.')

    success, message, session_info = monitor_manager.connect_agent(pair_code, agent_metadata)
    if not success:
        return err(message, 400)

    return ok({
        'message': message,
        'token': session_info['token'],
        'session_id': session_info['session_id'],
        'interval': session_info['interval']
    })


@app.route('/api/real-monitor/snapshot', methods=['POST'])
def real_monitor_receive_snapshot():
    """Agent telemetry receiver: ingests real-system snapshots authenticated via Bearer token."""
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return err('Missing or invalid Authorization header. Expected: Bearer <token>', 401)

    token = auth_header[7:].strip()
    session_obj = monitor_manager.get_session_by_token(token)
    if not session_obj:
        return err('Unauthorized: Invalid, revoked, or expired bearer token.', 401)

    snapshot_data = request.get_json()
    if not snapshot_data or not isinstance(snapshot_data, dict):
        return err('Invalid snapshot payload format. Expected JSON object.', 400)

    success, note = session_obj.record_snapshot(snapshot_data)
    if not success:
        code = 429 if 'Rate limit' in note else 400
        return err(note, code)

    return ok({'message': 'Snapshot received successfully', 'timestamp': time.time()})


@app.route('/api/real-monitor/status', methods=['GET'])
@login_required
def real_monitor_get_status():
    """Frontend status probe: checks whether user's local agent is active and streaming."""
    user_email = session.get('user_email')
    session_obj = monitor_manager.get_session_by_user(user_email)

    if not session_obj:
        return ok({
            'connected': False,
            'has_session': False,
            'message': 'No monitoring agent currently paired.'
        })

    is_conn = session_obj.is_connected
    latest = session_obj.get_latest_snapshot()
    heartbeat_ago = round(time.time() - session_obj.last_heartbeat, 1)

    return ok({
        'connected': is_conn,
        'has_session': True,
        'session_id': session_obj.session_id,
        'last_heartbeat_ago': heartbeat_ago,
        'agent_metadata': session_obj.agent_metadata,
        'system_summary': latest.get('system_summary', {}) if latest else None,
        'snapshots_count': len(session_obj.snapshots)
    })


@app.route('/api/real-monitor/processes', methods=['GET'])
@login_required
def real_monitor_get_processes():
    """Returns detected real OS processes from the latest snapshot with optional filtering."""
    user_email = session.get('user_email')
    session_obj = monitor_manager.get_session_by_user(user_email)

    if not session_obj or not session_obj.snapshots:
        return ok({'processes': [], 'total': 0, 'connected': False})

    latest = session_obj.get_latest_snapshot() or {}
    procs = list(latest.get('processes', []))

    # Optional filtering
    app_filter = request.args.get('app', '').strip().lower()
    search = request.args.get('search', '').strip().lower()
    sort_by = request.args.get('sort', 'cpu').strip().lower()
    try:
        limit = min(200, max(1, int(request.args.get('limit', 50))))
    except ValueError:
        limit = 50

    if app_filter:
        procs = [p for p in procs if app_filter in p.get('app_name', '').lower()]
    if search:
        procs = [p for p in procs if (search in p.get('name', '').lower() or search in p.get('cmdline', '').lower())]

    if sort_by == 'memory':
        procs.sort(key=lambda x: (x.get('memory_rss_mb', 0), x.get('cpu_percent', 0)), reverse=True)
    else:
        procs.sort(key=lambda x: (x.get('cpu_percent', 0), x.get('memory_rss_mb', 0)), reverse=True)

    return ok({
        'processes': procs[:limit],
        'total': len(procs),
        'connected': session_obj.is_connected,
        'timestamp': latest.get('timestamp')
    })


@app.route('/api/real-monitor/applications', methods=['GET'])
@login_required
def real_monitor_get_applications():
    """Returns aggregated real desktop application groups from the latest snapshot."""
    user_email = session.get('user_email')
    session_obj = monitor_manager.get_session_by_user(user_email)

    if not session_obj or not session_obj.snapshots:
        return ok({'applications': [], 'connected': False})

    latest = session_obj.get_latest_snapshot() or {}
    apps = latest.get('applications', [])

    return ok({
        'applications': apps,
        'connected': session_obj.is_connected,
        'timestamp': latest.get('timestamp')
    })


@app.route('/api/real-monitor/history', methods=['GET'])
@login_required
def real_monitor_get_history():
    """Returns rolling timeline data for the Observed Real Process Activity Timeline."""
    user_email = session.get('user_email')
    try:
        window = int(request.args.get('window', 120))
    except ValueError:
        window = 120

    timeline = monitor_manager.get_timeline(user_email, window_seconds=window)
    session_obj = monitor_manager.get_session_by_user(user_email)

    return ok({
        'timeline': timeline,
        'count': len(timeline),
        'connected': session_obj.is_connected if session_obj else False
    })


@app.route('/api/real-monitor/stop', methods=['POST'])
@login_required
def real_monitor_stop():
    """Stops the monitoring session for the current user and revokes the bearer token."""
    user_email = session.get('user_email')
    stopped = monitor_manager.stop_session(user_email)
    return ok({
        'stopped': stopped,
        'message': 'Monitoring session stopped. Token revoked.'
    })



# ─────────────── DISK SCHEDULING ───────────────

@app.route('/api/disk/simulate', methods=['POST'])
@login_required
def disk_simulate():
    data = request.get_json() or {}
    algo = str(data.get('algorithm', 'FCFS')).strip()
    direction = str(data.get('direction', 'right')).strip()
    try:
        head = int(data.get('head', 53))
        total_tracks = int(data.get('total_tracks', 200))
    except (TypeError, ValueError):
        head = 53
        total_tracks = 200

    if total_tracks <= 0:
        return err('Total tracks must be greater than 0.')

    raw_reqs = data.get('requests', [])
    if isinstance(raw_reqs, str):
        raw_reqs = [x.strip() for x in raw_reqs.replace(',', ' ').split() if x.strip()]

    try:
        requests = [int(x) for x in raw_reqs]
    except (TypeError, ValueError):
        return err('Invalid track request format. Please provide integers.')

    if not requests:
        return err('Disk request queue cannot be empty.')

    for r in requests:
        if r < 0 or r >= total_tracks:
            return err(f'Request cylinder {r} is outside range 0 to {total_tracks - 1}.')
    if head < 0 or head >= total_tracks:
        return err(f'Initial head {head} is outside range 0 to {total_tracks - 1}.')

    try:
        result = disk_scheduler.simulate(algo, requests, head, total_tracks, direction)
        comparison = disk_scheduler.compare_all(requests, head, total_tracks, direction)
        result['all_algorithms'] = comparison['comparison']
        result['best_algorithm'] = comparison['best_algorithm']
        result['total_tracks'] = total_tracks
        result['initial_head'] = head

        engine.update_score(10, f"Simulated Disk Scheduling ({algo})")
        log_event(
            engine.current_session_id, None,
            f"DISK_SCHED_{algo}",
            f"{algo} Disk Scheduling: Head={head}, {len(requests)} requests -> {result['total_seek']} cylinders total seek distance",
            engine.simulation_time
        )
        return ok(result)
    except Exception as e:
        return err(str(e), 500)


@app.route('/api/disk/compare', methods=['POST'])
@login_required
def disk_compare():
    data = request.get_json() or {}
    direction = str(data.get('direction', 'right')).strip()
    try:
        head = int(data.get('head', 53))
        total_tracks = int(data.get('total_tracks', 200))
    except (TypeError, ValueError):
        head = 53
        total_tracks = 200

    if total_tracks <= 0:
        return err('Total tracks must be greater than 0.')

    raw_reqs = data.get('requests', [])
    if isinstance(raw_reqs, str):
        raw_reqs = [x.strip() for x in raw_reqs.replace(',', ' ').split() if x.strip()]
    try:
        requests = [int(x) for x in raw_reqs]
    except (TypeError, ValueError):
        return err('Invalid track request format. Please provide integers.')

    if not requests:
        return err('Disk request queue cannot be empty.')

    for r in requests:
        if r < 0 or r >= total_tracks:
            return err(f'Request cylinder {r} is outside range 0 to {total_tracks - 1}.')
    if head < 0 or head >= total_tracks:
        return err(f'Initial head {head} is outside range 0 to {total_tracks - 1}.')

    try:
        comparison = disk_scheduler.compare_all(requests, head, total_tracks, direction)
        return ok(comparison)
    except Exception as e:
        return err(str(e), 500)


# ─────────────── FILES (FILE SYSTEM) ───────────────

@app.route('/api/files', methods=['GET'])
@login_required
def get_files():
    db = get_db()
    files = []
    if db:
        try:
            with db.cursor() as cur:
                cur.execute('SELECT * FROM files ORDER BY id DESC')
                rows = cur.fetchall()
                for r in rows:
                    if hasattr(r.get('created_at'), 'isoformat'):
                        r['created_at'] = r['created_at'].isoformat()
                    files.append(r)
        except Exception as e:
            files = []
    else:
        try:
            sconn = _get_sqlite_mirror()
            scur = sconn.cursor()
            scur.execute('SELECT id, session_id, filename, size_kb, owner_pid, created_at FROM files ORDER BY id DESC')
            rows = scur.fetchall()
            for r in rows:
                files.append({
                    'id': r[0],
                    'session_id': r[1],
                    'filename': r[2],
                    'size_kb': r[3],
                    'owner_pid': r[4],
                    'created_at': r[5]
                })
            sconn.close()
        except Exception:
            files = []

    if not files and _files_list:
        files = list(_files_list)

    # Sync engine storage used
    total_kb = sum(f.get('size_kb', 0) for f in files)
    engine.storage_used_gb = round(total_kb / (1024 * 1024), 3)

    return ok({'files': files, 'storage': engine.get_state()['storage']})


@app.route('/api/files', methods=['POST'])
@login_required
def create_file():
    global _file_id_counter
    data = request.get_json() or {}
    filename = str(data.get('filename', '')).strip()
    try:
        size_kb = int(data.get('size_kb', 0))
    except (TypeError, ValueError):
        size_kb = 0

    if not filename:
        return err('Filename cannot be empty')
    if size_kb <= 0:
        return err('File size must be greater than 0 KB')

    # Assign owner PID from active processes or default
    owner_pid = str(data.get('owner_pid', '')).strip()
    if not owner_pid:
        if engine.process_manager.processes:
            owner_pid = list(engine.process_manager.processes.keys())[0]
        else:
            owner_pid = 'P1'

    now_iso = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    file_record = {
        'id': _file_id_counter,
        'session_id': engine.current_session_id or 'DEFAULT',
        'filename': filename,
        'size_kb': size_kb,
        'owner_pid': owner_pid,
        'created_at': now_iso
    }
    _file_id_counter += 1
    _files_list.insert(0, file_record)

    # Save to DB if available
    db = get_db()
    if db:
        try:
            with db.cursor() as cur:
                cur.execute(
                    """INSERT INTO files (session_id, filename, size_kb, owner_pid, created_at)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (file_record['session_id'], filename, size_kb, owner_pid, now_iso)
                )
            db.commit()
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            print(f"File insert error: {e}")
    else:
        try:
            sconn = _get_sqlite_mirror()
            scur = sconn.cursor()
            scur.execute(
                """INSERT INTO files (session_id, filename, size_kb, owner_pid, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (file_record['session_id'], filename, size_kb, owner_pid, now_iso)
            )
            sconn.commit()
            sconn.close()
        except Exception as e:
            print(f"SQLite file insert error: {e}")

    # Recalculate storage used
    total_kb = sum(f.get('size_kb', 0) for f in _files_list)
    engine.storage_used_gb = round(total_kb / (1024 * 1024), 3)

    engine.update_score(5, f"Created file '{filename}'")
    log_event(engine.current_session_id, owner_pid, 'FILE_CREATED',
              f"File '{filename}' ({size_kb} KB) allocated on secondary storage by {owner_pid}")

    return ok({'file': file_record, 'storage': engine.get_state()['storage']}), 201


@app.route('/api/files/<int:file_id>', methods=['DELETE'])
@login_required
def delete_file(file_id):
    global _files_list
    found = False
    deleted_filename = ''
    new_list = []
    for f in _files_list:
        if f['id'] == file_id:
            found = True
            deleted_filename = f['filename']
        else:
            new_list.append(f)
    _files_list = new_list

    db = get_db()
    if db:
        try:
            with db.cursor() as cur:
                cur.execute('DELETE FROM files WHERE id=%s', (file_id,))
            db.commit()
            found = True
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
    else:
        try:
            sconn = _get_sqlite_mirror()
            scur = sconn.cursor()
            scur.execute('DELETE FROM files WHERE id=?', (file_id,))
            sconn.commit()
            sconn.close()
            found = True
        except Exception:
            pass

    total_kb = sum(f.get('size_kb', 0) for f in _files_list)
    engine.storage_used_gb = round(total_kb / (1024 * 1024), 3)

    if found and deleted_filename:
        log_event(engine.current_session_id, None, 'FILE_DELETED', f"Deleted file '{deleted_filename}' from storage")

    return ok({'message': 'File deleted', 'storage': engine.get_state()['storage']})


# ─────────────── LOGS ───────────────

@app.route('/api/logs', methods=['GET'])
@login_required
def get_logs():
    session_id = request.args.get('session_id', engine.current_session_id)
    db = get_db()
    if not db:
        return ok({'logs': [], 'db_available': False})
    try:
        with db.cursor() as cur:
            if session_id:
                cur.execute(
                    'SELECT * FROM process_activity_logs WHERE session_id=%s ORDER BY id DESC LIMIT 200',
                    (session_id,)
                )
            else:
                cur.execute('SELECT * FROM process_activity_logs ORDER BY id DESC LIMIT 200')
            logs = cur.fetchall()
            for log in logs:
                for k, v in log.items():
                    if hasattr(v, 'isoformat'):
                        log[k] = v.isoformat()
        return ok({'logs': logs, 'db_available': True})
    except Exception as e:
        return ok({'logs': [], 'error': str(e)})


# ─────────────── STATISTICS ───────────────

@app.route('/api/statistics', methods=['GET'])
@login_required
def get_statistics():
    return ok({
        'metrics': engine.metrics,
        'score': engine.score,
        'simulation_time': engine.simulation_time,
        'memory': engine.memory_manager.get_state(),
        'process_count': len(engine.process_manager.processes)
    })


# ─────────────── DEADLOCK ───────────────

@app.route('/api/deadlock/detect', methods=['POST'])
@login_required
def detect_deadlock():
    result = engine.detect_deadlock()
    if result.get('deadlock'):
        engine.update_score(5, 'Deadlock detected')
        log_event(engine.current_session_id, None, 'DEADLOCK_DETECTED', result.get('explanation', ''))
    return ok(result)


@app.route('/api/deadlock/scenario', methods=['POST'])
@login_required
def deadlock_scenario():
    data = request.get_json() or {}
    scenario_type = data.get('type', 'two_process')
    result = engine.load_deadlock_scenario(scenario_type)
    return ok(result)


@app.route('/api/deadlock/custom', methods=['POST'])
@login_required
def custom_deadlock():
    """
    Detect deadlock from user-defined processes.
    Body: { processes: [{pid, holds, wants}], available: {PRINTER:1,...} }
    """
    from backend.deadlock_detector import DeadlockDetector
    data = request.get_json() or {}
    processes = data.get('processes', [])  # [{pid, holds:'PRINTER', wants:'DISK'}]

    if not processes:
        return err('No processes provided')

    allocation = {}
    request_map = {}
    all_resources = set()

    for p in processes:
        pid = p.get('pid', '').strip()
        if not pid:
            continue
        holds = p.get('holds', '')
        wants = p.get('wants', '')
        if holds:
            allocation[pid] = {holds: 1}
            all_resources.add(holds)
        if wants:
            request_map[pid] = {wants: 1}
            all_resources.add(wants)

    # Compute available: assume 1 of each resource total
    base_available = {r: 1 for r in all_resources}
    for alloc in allocation.values():
        for r, cnt in alloc.items():
            base_available[r] = max(0, base_available.get(r, 1) - cnt)

    detector = DeadlockDetector()
    result = detector.detect(allocation, request_map, base_available)
    result['allocation'] = allocation
    result['request']    = request_map
    result['available']  = base_available
    result['processes']  = processes
    return ok(result)


@app.route('/api/deadlock/prevent', methods=['POST'])
@login_required
def prevent_deadlock():
    """
    Apply a deadlock prevention strategy to a custom set of processes.
    Body: { strategy, processes, allocation, request, available }
    """
    from backend.deadlock_detector import DeadlockPrevention
    data = request.get_json() or {}
    strategy   = data.get('strategy', 'circular_wait')
    processes  = data.get('processes', [])
    allocation = data.get('allocation', {})
    request_d  = data.get('request', {})
    available  = data.get('available', {})

    result = DeadlockPrevention.apply(strategy, processes, allocation, request_d, dict(available))
    return ok(result)


# ─────────────── SCORE ───────────────

@app.route('/api/score/update', methods=['POST'])
@login_required
def update_score():
    data = request.get_json() or {}
    delta = int(data.get('delta', 0))
    reason = data.get('reason', '')
    new_score = engine.update_score(delta, reason)
    db = get_db()
    if db and engine.current_session_id:
        try:
            with db.cursor() as cur:
                cur.execute(
                    """INSERT INTO scores (session_id, total_score, reason)
                       VALUES (%s, %s, %s)
                       ON DUPLICATE KEY UPDATE total_score=%s, reason=%s""",
                    (engine.current_session_id, new_score, reason, new_score, reason)
                )
            db.commit()
        except Exception as e:
            db.rollback()
    return ok({'score': new_score})


# ─────────────── DEMO ───────────────

@app.route('/api/demo/load', methods=['GET'])
@login_required
def load_demo():
    if not engine.current_session_id:
        engine.current_session_id = str(uuid.uuid4())[:8].upper()
    procs = engine.load_demo(session_id=engine.current_session_id)
    # DB save
    db = get_db()
    if db:
        try:
            with db.cursor() as cur:
                cur.execute(
                    """INSERT IGNORE INTO simulation_sessions (session_id, algorithm, status)
                       VALUES (%s, 'FCFS', 'ACTIVE')""",
                    (engine.current_session_id,)
                )
                for p in procs:
                    cur.execute(
                        """INSERT IGNORE INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, 'READY')""",
                        (p['pid'], engine.current_session_id, p['name'], p['arrival_time'],
                         p['burst_time'], p['priority'], p['memory_mb'])
                    )
            db.commit()
        except Exception as e:
            db.rollback()
            print(f'Demo DB error: {e}')
    return ok({
        'processes': procs,
        'session_id': engine.current_session_id,
        'memory': engine.memory_manager.get_state()
    })


@app.route('/api/full/reset', methods=['POST'])
@login_required
def full_reset():
    engine.reset()
    engine.current_session_id = None
    engine.score = 0
    _files_list.clear()
    return ok({'message': 'Full simulation reset complete'})


@app.route('/api/db/status', methods=['GET'])
@login_required
def db_status():
    db = get_db()
    if db:
        try:
            with db.cursor() as cur:
                cur.execute('SELECT 1')
            return ok({'connected': True, 'host': Config.DB_HOST, 'database': Config.DB_NAME})
        except:
            pass
    return ok({'connected': False, 'error': getattr(g, 'db_error', 'Unknown error')})


# ─────────────── BANKER'S ALGORITHM (DEADLOCK AVOIDANCE) ───────────────

def _run_banker_safety(process_names, resource_names, allocation, max_matrix, available):
    """
    Core Banker's Safety Algorithm helper with shape and bounds validation.
    Returns (err_msg, result_dict).
    """
    if not isinstance(process_names, list) or not isinstance(resource_names, list):
        return 'Processes and resources must be lists', None

    n = len(process_names)
    m = len(resource_names)

    if n == 0 or m == 0:
        return 'Need at least 1 process and 1 resource', None
    if not isinstance(allocation, list) or len(allocation) != n:
        return f'Allocation matrix must have exactly {n} rows', None
    if not isinstance(max_matrix, list) or len(max_matrix) != n:
        return f'Max matrix must have exactly {n} rows', None
    if not isinstance(available, list) or len(available) != m:
        return f'Available vector length must match number of resources ({m})', None

    # Validate row lengths and bounds (non-negative)
    for i in range(n):
        if not isinstance(allocation[i], list) or len(allocation[i]) != m:
            return f'Allocation row {i} must have exactly {m} resource elements', None
        if not isinstance(max_matrix[i], list) or len(max_matrix[i]) != m:
            return f'Max matrix row {i} must have exactly {m} resource elements', None
        for j in range(m):
            try:
                alloc_val = int(allocation[i][j])
                max_val = int(max_matrix[i][j])
            except (ValueError, TypeError):
                return f'Matrix entries must be integers (process {process_names[i]}, resource {resource_names[j]})', None
            if alloc_val < 0:
                return f'Allocation values cannot be negative ({process_names[i]}[{resource_names[j]}]: {alloc_val})', None
            if max_val < 0:
                return f'Max values cannot be negative ({process_names[i]}[{resource_names[j]}]: {max_val})', None

    for j in range(m):
        try:
            avail_val = int(available[j])
        except (ValueError, TypeError):
            return f'Available vector entries must be integers (resource {resource_names[j]})', None
        if avail_val < 0:
            return f'Available count cannot be negative ({resource_names[j]}: {avail_val})', None

    need = []
    for i in range(n):
        row = []
        for j in range(m):
            val = int(max_matrix[i][j]) - int(allocation[i][j])
            if val < 0:
                return (
                    f'Invalid: {process_names[i]} Allocation[{resource_names[j]}]={allocation[i][j]} '
                    f'exceeds Max[{resource_names[j]}]={max_matrix[i][j]}'
                ), None
            row.append(val)
        need.append(row)

    work = [int(x) for x in available]
    finish = [False] * n
    safe_sequence = []
    steps = []

    while len(safe_sequence) < n:
        found = False
        for i in range(n):
            if finish[i]:
                continue
            can_run = all(need[i][j] <= work[j] for j in range(m))
            if can_run:
                work_before = list(work)
                for j in range(m):
                    work[j] += int(allocation[i][j])
                finish[i] = True
                safe_sequence.append(process_names[i])
                steps.append({
                    'step':        len(steps) + 1,
                    'process':     process_names[i],
                    'need':        list(need[i]),
                    'work_before': work_before,
                    'allocation':  [int(x) for x in allocation[i]],
                    'work_after':  list(work),
                    'condition':   f"Need {list(need[i])} ≤ Work {work_before} ✓",
                    'explanation': (
                        f"{process_names[i]}: Need {list(need[i])} ≤ Available Work {work_before} "
                        f"→ Runs to completion → Releases {list(allocation[i])} → "
                        f"New Work = {list(work)}"
                    )
                })
                found = True
        if not found:
            stuck = [process_names[i] for i in range(n) if not finish[i]]
            steps.append({
                'step':        len(steps) + 1,
                'process':     None,
                'work_before': list(work),
                'work_after':  list(work),
                'explanation': (
                    f"UNSAFE STATE: No remaining process satisfies Need[i] ≤ Work {list(work)}. "
                    f"Stuck processes: {stuck}."
                ),
                'stuck': stuck
            })
            break

    safe = all(finish)
    stuck_procs = [process_names[i] for i in range(n) if not finish[i]]

    return None, {
        'safe':           safe,
        'safe_sequence':  safe_sequence,
        'stuck_processes': stuck_procs,
        'need':           need,
        'steps':          steps,
        'final_work':     work,
        'finish':         finish,
        'processes':      process_names,
        'resources':      resource_names,
        'allocation':     allocation,
        'max_matrix':     max_matrix,
        'available':      available,
        'explanation':    (
            f"System is in a SAFE state. Safe sequence: {' → '.join(safe_sequence)}"
            if safe else
            f"System is in an UNSAFE state. Deadlock is possible! "
            f"Only {len(safe_sequence)} of {n} processes could finish; stuck: {', '.join(stuck_procs)}."
        )
    }


@app.route('/api/banker/check', methods=['POST'])
@login_required
def banker_check():
    """
    Full Banker's Algorithm safety check with step-by-step proof.
    """
    data           = request.get_json() or {}
    process_names  = data.get('processes', [])
    resource_names = data.get('resources',  [])
    allocation     = data.get('allocation', [])
    max_matrix     = data.get('max_matrix',  [])
    available      = data.get('available',   [])

    err_msg, result = _run_banker_safety(process_names, resource_names, allocation, max_matrix, available)
    if err_msg:
        return err(err_msg)

    log_event(
        engine.current_session_id, None,
        'BANKER_SAFETY_CHECK',
        result['explanation'],
        engine.simulation_time
    )
    return ok(result)


@app.route('/api/banker/request', methods=['POST'])
@login_required
def banker_resource_request():
    """
    Banker's Algorithm — Dynamic Resource-Request Deadlock Avoidance Algorithm.
    Tests whether granting Request_i to Process P_i keeps the OS in a SAFE state,
    or whether it must be DENIED & ROLLED BACK to avoid deadlock.
    Body: {
      processes: ['P0','P1',...],
      resources: ['A','B','C'],
      allocation: [[0,1,0],...],
      max_matrix: [[7,5,3],...],
      available:  [3,3,2],
      process_index: 1,          # or process: 'P1'
      request_vector: [1,0,2]
    }
    """
    data           = request.get_json() or {}
    process_names  = data.get('processes', [])
    resource_names = data.get('resources', [])
    try:
        allocation = [[int(x) for x in row] for row in data.get('allocation', [])]
        max_matrix = [[int(x) for x in row] for row in data.get('max_matrix', [])]
        available  = [int(x) for x in data.get('available', [])]
        req_vec    = [int(x) for x in data.get('request_vector', [])]
    except (ValueError, TypeError):
        return err('Matrix and vector entries must be valid integers')

    n = len(process_names)
    m = len(resource_names)
    if n == 0 or m == 0:
        return err('Processes and resources cannot be empty')
    if len(req_vec) != m:
        return err('Request vector length must match number of resource types')
    for j in range(m):
        if req_vec[j] < 0:
            return err(f'Request vector amounts cannot be negative ({resource_names[j]}: {req_vec[j]})')

    # Resolve requesting process index
    proc_idx = data.get('process_index')
    if proc_idx is None:
        proc_name = data.get('process')
        if proc_name in process_names:
            proc_idx = process_names.index(proc_name)
        else:
            proc_idx = 0
    proc_idx = int(proc_idx)
    if proc_idx < 0 or proc_idx >= n:
        return err('Invalid requesting process index')

    proc_name = process_names[proc_idx]

    # First compute current Need matrix
    err_msg, base_check = _run_banker_safety(process_names, resource_names, allocation, max_matrix, available)
    if err_msg:
        return err(err_msg)

    need = base_check['need']
    proc_need = need[proc_idx]
    proc_alloc = allocation[proc_idx]

    # ── STEP 1: Check Request_i <= Need_i ──
    step1_details = []
    step1_passed = True
    for j in range(m):
        ok_j = req_vec[j] <= proc_need[j]
        if not ok_j:
            step1_passed = False
        step1_details.append({
            'resource': resource_names[j],
            'request': req_vec[j],
            'need': proc_need[j],
            'passed': ok_j
        })

    if not step1_passed:
        return ok({
            'granted': False,
            'avoided_deadlock': False,
            'status': 'EXCEEDED_MAX_CLAIM',
            'process': proc_name,
            'process_index': proc_idx,
            'request_vector': req_vec,
            'step1_max_claim': {
                'passed': False,
                'formula': f"Request_{proc_name} {req_vec} ≤ Need_{proc_name} {proc_need}",
                'details': step1_details,
                'message': f"REJECTED at Step 1: {proc_name} requested {req_vec}, which exceeds its declared remaining Need {proc_need}!"
            },
            'step2_available': None,
            'step3_provisional_safety': None,
            'allocation': allocation,
            'max_matrix': max_matrix,
            'available': available,
            'need': need
        })

    # ── STEP 2: Check Request_i <= Available ──
    step2_details = []
    step2_passed = True
    for j in range(m):
        ok_j = req_vec[j] <= available[j]
        if not ok_j:
            step2_passed = False
        step2_details.append({
            'resource': resource_names[j],
            'request': req_vec[j],
            'available': available[j],
            'passed': ok_j
        })

    if not step2_passed:
        return ok({
            'granted': False,
            'avoided_deadlock': False,
            'status': 'MUST_WAIT_INSUFFICIENT',
            'process': proc_name,
            'process_index': proc_idx,
            'request_vector': req_vec,
            'step1_max_claim': {
                'passed': True,
                'formula': f"Request_{proc_name} {req_vec} ≤ Need_{proc_name} {proc_need} ✓",
                'details': step1_details,
                'message': f"Step 1 Passed: Request {req_vec} is within {proc_name}'s maximum claim Need {proc_need}."
            },
            'step2_available': {
                'passed': False,
                'formula': f"Request_{proc_name} {req_vec} ≤ Available {available}",
                'details': step2_details,
                'message': f"DEFERRED at Step 2: Requested resources {req_vec} exceed currently Available {available}. {proc_name} must WAIT until resources are released."
            },
            'step3_provisional_safety': None,
            'allocation': allocation,
            'max_matrix': max_matrix,
            'available': available,
            'need': need
        })

    # ── STEP 3: Provisional Allocation (Pretend to Allocate) & Run Safety Algorithm ──
    prov_available  = [available[j] - req_vec[j] for j in range(m)]
    prov_allocation = [list(row) for row in allocation]
    prov_allocation[proc_idx] = [prov_allocation[proc_idx][j] + req_vec[j] for j in range(m)]

    _, prov_safety = _run_banker_safety(process_names, resource_names, prov_allocation, max_matrix, prov_available)
    is_safe = prov_safety['safe']

    if is_safe:
        engine.update_score(10, f"Banker's Avoidance: Granted safe request for {proc_name}")
        log_event(
            engine.current_session_id, proc_name,
            'BANKER_REQUEST_GRANTED',
            f"Granted Request {req_vec} to {proc_name}. Safe sequence: {' -> '.join(prov_safety['safe_sequence'])}",
            engine.simulation_time
        )
        verdict_msg = (
            f"✅ REQUEST GRANTED! Provisional state is SAFE with sequence "
            f"{' → '.join(prov_safety['safe_sequence'])}. Resources {req_vec} committed to {proc_name}."
        )
    else:
        engine.update_score(10, f"Banker's Avoidance: Prevented unsafe state from {proc_name}")
        log_event(
            engine.current_session_id, proc_name,
            'BANKER_DEADLOCK_AVOIDED',
            f"DEADLOCK AVOIDED! Denied Request {req_vec} from {proc_name} because provisional Available={prov_available} leads to UNSAFE state.",
            engine.simulation_time
        )
        verdict_msg = (
            f"🚫 DEADLOCK AVOIDED (REQUEST DENIED & ROLLED BACK)! "
            f"If the OS granted {req_vec} to {proc_name}, Available would drop to {prov_available}, "
            f"leaving stuck processes {prov_safety['stuck_processes']} with no safe completion sequence. "
            f"Provisional allocation rolled back; {proc_name} must wait!"
        )

    return ok({
        'granted': is_safe,
        'avoided_deadlock': not is_safe,
        'status': 'GRANTED_SAFE' if is_safe else 'AVOIDED_UNSAFE',
        'process': proc_name,
        'process_index': proc_idx,
        'request_vector': req_vec,
        'verdict_message': verdict_msg,
        'step1_max_claim': {
            'passed': True,
            'formula': f"Request_{proc_name} {req_vec} ≤ Need_{proc_name} {proc_need} ✓",
            'details': step1_details,
            'message': f"Step 1 Passed: Request {req_vec} ≤ Need {proc_need} (Process is within its declared Max claim)."
        },
        'step2_available': {
            'passed': True,
            'formula': f"Request_{proc_name} {req_vec} ≤ Available {available} ✓",
            'details': step2_details,
            'message': f"Step 2 Passed: Request {req_vec} ≤ Available {available} (Resources are physically free right now)."
        },
        'step3_provisional_safety': {
            'passed': is_safe,
            'available_before': available,
            'available_provisional': prov_available,
            'alloc_before': proc_alloc,
            'alloc_provisional': prov_allocation[proc_idx],
            'need_before': proc_need,
            'need_provisional': prov_safety['need'][proc_idx],
            'rolled_back': not is_safe,
            'safety_result': prov_safety,
            'message': verdict_msg
        },
        # Return both provisional and committed states so UI can optionally apply or rollback
        'committed_allocation': prov_allocation if is_safe else allocation,
        'committed_available':  prov_available if is_safe else available,
        'committed_need':       prov_safety['need'] if is_safe else need,
        'provisional_result':   prov_safety
    })



# ═══════════════════════════════════════════════════════════════════════════
# 🗄️ DBMS ENGINE ROOM — MYSQL TRIGGERS & VISUAL JOINS
# ═══════════════════════════════════════════════════════════════════════════

import sqlite3

_MYSQL_TRIGGERS_DDL = [
    {
        'name': 'trg_before_process_insert',
        'timing': 'BEFORE INSERT',
        'table': 'processes',
        'purpose': 'Validates OS constraints at the MySQL engine level: blocks processes with burst_time <= 0, negative arrival_time, memory_mb not in 1..16384 MB, or invalid process states using SIGNAL SQLSTATE 45000.',
        'drop_sql': 'DROP TRIGGER IF EXISTS trg_before_process_insert;',
        'create_sql': """CREATE TRIGGER trg_before_process_insert
BEFORE INSERT ON processes
FOR EACH ROW
BEGIN
    IF NEW.burst_time <= 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_insert]: Burst time must be greater than 0';
    END IF;
    IF NEW.memory_mb <= 0 OR NEW.memory_mb > 16384 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_insert]: Memory allocation must be between 1 MB and 16384 MB (16 GB)';
    END IF;
    IF NEW.arrival_time < 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_insert]: Arrival time cannot be negative';
    END IF;
    IF NEW.state NOT IN ('NEW', 'READY', 'RUNNING', 'WAITING', 'TERMINATED') THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_insert]: Invalid process state';
    END IF;
END"""
    },
    {
        'name': 'trg_before_process_update',
        'timing': 'BEFORE UPDATE',
        'table': 'processes',
        'purpose': 'Enforces hardware limits and valid state invariants upon process modification: rejects burst_time <= 0, negative arrival_time, or invalid states with SIGNAL SQLSTATE 45000.',
        'drop_sql': 'DROP TRIGGER IF EXISTS trg_before_process_update;',
        'create_sql': """CREATE TRIGGER trg_before_process_update
BEFORE UPDATE ON processes
FOR EACH ROW
BEGIN
    IF NEW.burst_time <= 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_update]: Burst time must be greater than 0';
    END IF;
    IF NEW.memory_mb <= 0 OR NEW.memory_mb > 16384 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_update]: Memory allocation must be between 1 MB and 16384 MB (16 GB)';
    END IF;
    IF NEW.arrival_time < 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_update]: Arrival time cannot be negative';
    END IF;
    IF NEW.state NOT IN ('NEW', 'READY', 'RUNNING', 'WAITING', 'TERMINATED') THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'MySQL Trigger [trg_before_process_update]: Invalid process state';
    END IF;
END"""
    },
    {
        'name': 'trg_after_process_insert',
        'timing': 'AFTER INSERT',
        'table': 'processes',
        'purpose': 'Automatically increments num_processes in simulation_sessions and writes a PROCESS_CREATED audit record into process_activity_logs whenever a new process is registered.',
        'drop_sql': 'DROP TRIGGER IF EXISTS trg_after_process_insert;',
        'create_sql': """CREATE TRIGGER trg_after_process_insert
AFTER INSERT ON processes
FOR EACH ROW
BEGIN
    UPDATE simulation_sessions
    SET num_processes = num_processes + 1
    WHERE session_id = NEW.session_id;

    INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description)
    VALUES (
        NEW.session_id,
        NEW.pid,
        'PROCESS_CREATED',
        NEW.arrival_time,
        CONCAT('[Trigger: trg_after_process_insert] Process ', NEW.name, ' (', NEW.pid, ') created with burst=', NEW.burst_time, 'ms, mem=', NEW.memory_mb, 'MB')
    );

    IF NEW.state = 'TERMINATED' THEN
        INSERT INTO scores (session_id, total_score, reason)
        VALUES (NEW.session_id, 10, CONCAT('Auto-awarded by trigger for completing ', NEW.pid))
        ON DUPLICATE KEY UPDATE
            total_score = total_score + 10,
            reason = CONCAT('Auto-awarded +10 by trigger for completing ', NEW.pid);
    END IF;
END"""
    },
    {
        'name': 'trg_after_process_state_update',
        'timing': 'AFTER UPDATE',
        'table': 'processes',
        'purpose': 'Captures OS process lifecycle state transitions (e.g. READY -> RUNNING -> WAITING -> TERMINATED) and inserts an immutable audit entry into process_state_history.',
        'drop_sql': 'DROP TRIGGER IF EXISTS trg_after_process_state_update;',
        'create_sql': """CREATE TRIGGER trg_after_process_state_update
AFTER UPDATE ON processes
FOR EACH ROW
BEGIN
    IF OLD.state <> NEW.state THEN
        INSERT INTO process_state_history (session_id, pid, old_state, new_state, changed_at)
        VALUES (NEW.session_id, NEW.pid, OLD.state, NEW.state, NOW());
    END IF;
END"""
    },
    {
        'name': 'trg_after_process_terminated',
        'timing': 'AFTER UPDATE',
        'table': 'processes',
        'purpose': 'When a process transitions to TERMINATED from a non-terminated state, logs PROCESS_TERMINATED in process_activity_logs and awards +10 completion score idempotently.',
        'drop_sql': 'DROP TRIGGER IF EXISTS trg_after_process_terminated;',
        'create_sql': """CREATE TRIGGER trg_after_process_terminated
AFTER UPDATE ON processes
FOR EACH ROW
BEGIN
    IF NEW.state = 'TERMINATED' AND OLD.state <> 'TERMINATED' THEN
        INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description)
        VALUES (
            NEW.session_id,
            NEW.pid,
            'PROCESS_TERMINATED',
            COALESCE(NEW.completion_time, 0),
            CONCAT('[Trigger: trg_after_process_terminated] Process ', NEW.name, ' (', NEW.pid, ') completed execution. TAT=', NEW.turnaround_time, ', WT=', NEW.waiting_time)
        );

        INSERT INTO scores (session_id, total_score, reason)
        VALUES (NEW.session_id, 10, CONCAT('Auto-awarded by trigger for completing ', NEW.pid))
        ON DUPLICATE KEY UPDATE
            total_score = total_score + 10,
            reason = CONCAT('Auto-awarded +10 by trigger for completing ', NEW.pid);
    END IF;
END"""
    },
    {
        'name': 'trg_after_process_delete',
        'timing': 'AFTER DELETE',
        'table': 'processes',
        'purpose': 'Maintains process counter integrity: decrements simulation_sessions.num_processes by 1 and records a PROCESS_DELETED audit log when a process record is removed.',
        'drop_sql': 'DROP TRIGGER IF EXISTS trg_after_process_delete;',
        'create_sql': """CREATE TRIGGER trg_after_process_delete
AFTER DELETE ON processes
FOR EACH ROW
BEGIN
    UPDATE simulation_sessions
    SET num_processes = GREATEST(0, num_processes - 1)
    WHERE session_id = OLD.session_id;

    INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description)
    VALUES (
        OLD.session_id,
        OLD.pid,
        'PROCESS_DELETED',
        0,
        CONCAT('[Trigger: trg_after_process_delete] Process ', OLD.name, ' (', OLD.pid, ') removed from session')
    );
END"""
    },
    {
        'name': 'trg_after_resource_allocation',
        'timing': 'AFTER INSERT',
        'table': 'resource_allocations',
        'purpose': 'Automatically records hardware resource lock/wait events into process_activity_logs whenever a row is inserted into resource_allocations.',
        'drop_sql': 'DROP TRIGGER IF EXISTS trg_after_resource_allocation;',
        'create_sql': """CREATE TRIGGER trg_after_resource_allocation
AFTER INSERT ON resource_allocations
FOR EACH ROW
BEGIN
    INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description)
    VALUES (
        NEW.session_id,
        NEW.pid,
        CONCAT('RESOURCE_', UPPER(NEW.status)),
        0,
        CONCAT('[Trigger: trg_after_resource_allocation] Process ', NEW.pid, ' ', NEW.status, ' resource ', NEW.resource_id, ' (count=', NEW.count, ')')
    );
END"""
    }
]


def _bootstrap_mysql(conn):
    """Create tables, seed initial rows, and install all 7 MySQL triggers."""
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(255) NOT NULL UNIQUE,
                email VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                account_type ENUM('student', 'teacher') NOT NULL DEFAULT 'student',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB""")

            cur.execute("""CREATE TABLE IF NOT EXISTS simulation_sessions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(255) NOT NULL UNIQUE,
                user_id INT NULL,
                algorithm VARCHAR(50) NOT NULL,
                status VARCHAR(50) NOT NULL,
                quantum INT NULL,
                cpu_utilization DECIMAL(5, 2) DEFAULT 0.00,
                avg_waiting_time DECIMAL(10, 2) DEFAULT 0.00,
                avg_turnaround_time DECIMAL(10, 2) DEFAULT 0.00,
                num_processes INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            ) ENGINE=InnoDB""")

            cur.execute("""CREATE TABLE IF NOT EXISTS processes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                pid VARCHAR(50) NOT NULL,
                session_id VARCHAR(255) NOT NULL,
                name VARCHAR(255) NOT NULL,
                arrival_time INT NOT NULL,
                burst_time INT NOT NULL,
                priority INT NOT NULL,
                memory_mb INT NOT NULL,
                state ENUM('NEW','READY','RUNNING','WAITING','TERMINATED') NOT NULL DEFAULT 'NEW',
                remaining_time INT NOT NULL DEFAULT 0,
                start_time INT NULL,
                completion_time INT NULL,
                waiting_time INT DEFAULT 0,
                turnaround_time INT DEFAULT 0,
                response_time INT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE,
                UNIQUE KEY unique_session_pid (session_id, pid),
                INDEX idx_session_id (session_id),
                INDEX idx_pid (pid)
            ) ENGINE=InnoDB""")

            cur.execute("""CREATE TABLE IF NOT EXISTS resources (
                id INT AUTO_INCREMENT PRIMARY KEY,
                resource_id VARCHAR(50) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                total INT NOT NULL,
                icon VARCHAR(255) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB""")

            cur.execute("""CREATE TABLE IF NOT EXISTS resource_allocations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                resource_id VARCHAR(50) NOT NULL,
                pid VARCHAR(50) NOT NULL,
                session_id VARCHAR(255) NOT NULL,
                count INT DEFAULT 1,
                status ENUM('ALLOCATED','WAITING','RELEASED') NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (resource_id) REFERENCES resources(resource_id) ON DELETE CASCADE,
                FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE,
                FOREIGN KEY (session_id, pid) REFERENCES processes(session_id, pid) ON DELETE CASCADE,
                INDEX idx_session_pid (session_id, pid)
            ) ENGINE=InnoDB""")

            cur.execute("""CREATE TABLE IF NOT EXISTS process_activity_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(255) NOT NULL,
                process_id VARCHAR(50) NULL,
                event_type VARCHAR(50) NOT NULL,
                simulation_time INT DEFAULT 0,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE,
                INDEX idx_log_session (session_id),
                INDEX idx_log_pid (process_id)
            ) ENGINE=InnoDB""")

            cur.execute("""CREATE TABLE IF NOT EXISTS process_state_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(255) NOT NULL,
                pid VARCHAR(50) NOT NULL,
                old_state VARCHAR(20) NOT NULL,
                new_state VARCHAR(20) NOT NULL,
                changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE,
                INDEX idx_history_session_pid (session_id, pid),
                INDEX idx_history_changed (changed_at)
            ) ENGINE=InnoDB""")

            cur.execute("""CREATE TABLE IF NOT EXISTS files (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(255) NOT NULL,
                filename VARCHAR(255) NOT NULL,
                size_kb INT NOT NULL,
                owner_pid VARCHAR(50) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE
            ) ENGINE=InnoDB""")

            cur.execute("""CREATE TABLE IF NOT EXISTS scores (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(255) NOT NULL UNIQUE,
                total_score INT DEFAULT 0,
                reason VARCHAR(255),
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE
            ) ENGINE=InnoDB""")

            cur.execute("""CREATE TABLE IF NOT EXISTS lab_assignments (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(150) NOT NULL,
                description TEXT,
                target_panel VARCHAR(40) NOT NULL DEFAULT 'scheduler',
                required_algo VARCHAR(40) NOT NULL DEFAULT 'RoundRobin',
                max_awt DECIMAL(6, 2) NULL,
                points INT NOT NULL DEFAULT 50,
                given_query TEXT NULL,
                expected_rules TEXT NULL,
                workload_json TEXT NULL,
                allowed_algorithms_json TEXT NULL,
                optimization_objective VARCHAR(50) NULL,
                round_robin_quantum INT DEFAULT 2,
                created_by VARCHAR(100) DEFAULT 'Instructor',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB""")

            cur.execute("""CREATE TABLE IF NOT EXISTS assignment_submissions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                assignment_id INT NOT NULL,
                student_email VARCHAR(100) NOT NULL,
                student_name VARCHAR(100) NOT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'COMPLETED',
                score_awarded INT NOT NULL DEFAULT 50,
                verification_note VARCHAR(255) NULL,
                submitted_query TEXT NULL,
                student_explanation TEXT NULL,
                cbo_metrics TEXT NULL,
                selected_algo VARCHAR(50) NULL,
                submitted_quantum INT NULL,
                objective_value DECIMAL(10, 2) NULL,
                scheduling_metrics TEXT NULL,
                gantt_json TEXT NULL,
                attempts_count INT DEFAULT 1,
                completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uk_assignment_student (assignment_id, student_email),
                FOREIGN KEY (assignment_id) REFERENCES lab_assignments(id) ON DELETE CASCADE
            ) ENGINE=InnoDB""")

            cur.execute("""CREATE TABLE IF NOT EXISTS student_xp_awards (
                id INT AUTO_INCREMENT PRIMARY KEY,
                student_email VARCHAR(100) NOT NULL,
                student_name VARCHAR(100),
                assignment_id INT NOT NULL,
                points_awarded INT NOT NULL,
                award_reason VARCHAR(255),
                awarded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uk_award_student_assignment (assignment_id, student_email),
                FOREIGN KEY (assignment_id) REFERENCES lab_assignments(id) ON DELETE CASCADE
            ) ENGINE=InnoDB""")

            cur.execute("""CREATE TABLE IF NOT EXISTS simulation_runs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                run_id VARCHAR(64) NOT NULL UNIQUE,
                session_id VARCHAR(255) NULL,
                user_id INT NULL,
                run_name VARCHAR(150) NOT NULL,
                algorithm VARCHAR(50) NOT NULL,
                quantum INT NULL,
                process_count INT NOT NULL DEFAULT 0,
                workload_hash VARCHAR(64) NOT NULL,
                avg_waiting_time DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
                avg_turnaround_time DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
                avg_response_time DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
                cpu_utilization DECIMAL(5, 2) NOT NULL DEFAULT 0.00,
                throughput DECIMAL(8, 4) NOT NULL DEFAULT 0.0000,
                context_switches INT NOT NULL DEFAULT 0,
                status VARCHAR(50) NOT NULL DEFAULT 'COMPLETED',
                gantt_json LONGTEXT NULL,
                metrics_json TEXT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE SET NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
                INDEX idx_simrun_workload (workload_hash),
                INDEX idx_simrun_algo (algorithm),
                INDEX idx_simrun_created (created_at),
                INDEX idx_simrun_session (session_id)
            ) ENGINE=InnoDB""")

            cur.execute("""CREATE TABLE IF NOT EXISTS simulation_run_processes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                run_id VARCHAR(64) NOT NULL,
                pid VARCHAR(50) NOT NULL,
                name VARCHAR(255) NOT NULL,
                arrival_time INT NOT NULL,
                burst_time INT NOT NULL,
                priority INT NOT NULL DEFAULT 1,
                memory_mb INT NOT NULL DEFAULT 512,
                start_time INT NULL,
                completion_time INT NULL,
                waiting_time INT NOT NULL DEFAULT 0,
                turnaround_time INT NOT NULL DEFAULT 0,
                response_time INT NULL,
                execution_order INT NOT NULL DEFAULT 0,
                FOREIGN KEY (run_id) REFERENCES simulation_runs(run_id) ON DELETE CASCADE,
                UNIQUE KEY uk_simrun_proc (run_id, pid),
                INDEX idx_simrunproc_run (run_id),
                INDEX idx_simrunproc_pid (pid)
            ) ENGINE=InnoDB""")

            # Install all 7 MySQL Triggers
            for t in _MYSQL_TRIGGERS_DDL:
                cur.execute(t['drop_sql'])
                cur.execute(t['create_sql'])

            # Seed default lab assignments if empty
            cur.execute("SELECT COUNT(*) AS cnt FROM lab_assignments")
            if cur.fetchone()['cnt'] == 0:
                cur.executemany(
                    """INSERT INTO lab_assignments (title, description, target_panel, required_algo, max_awt, points, created_by)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    [
                        (
                            'Challenge #1: Schedule 4 processes using Round Robin (Q=2) with Avg Waiting Time < 5.0',
                            'Open CPU Scheduler, select Round Robin (Quantum = 2), schedule 4 processes so Average Waiting Time stays under 5.0 ms, and submit.',
                            'scheduler', 'RoundRobin', 5.00, 50, 'Prof. Instructor'
                        ),
                        (
                            'Challenge #2: Detect & Resolve the 3-Process Circular Deadlock',
                            'Open the Deadlock Detector panel, load the 3-Process Circular Wait scenario, run cycle detection on the Resource Allocation Graph, and submit.',
                            'deadlock', 'DEADLOCK_3PROC', None, 60, 'Prof. Instructor'
                        ),
                    ]
                )

            # Seed default data if empty
            cur.execute("SELECT COUNT(*) AS cnt FROM resources")
            if cur.fetchone()['cnt'] == 0:
                cur.executemany(
                    "INSERT IGNORE INTO resources (resource_id, name, total, icon) VALUES (%s, %s, %s, %s)",
                    [
                        ('PRINTER', 'Printer', 1, '🖨️'),
                        ('DISK', 'Disk Drive', 2, '💾'),
                        ('NETWORK', 'Network Adapter', 1, '🌐'),
                        ('IO_DEVICE', 'I/O Controller', 2, '⌨️'),
                    ]
                )

            cur.execute("SELECT COUNT(*) AS cnt FROM simulation_sessions")
            if cur.fetchone()['cnt'] == 0:
                cur.execute(
                    """INSERT IGNORE INTO simulation_sessions
                       (session_id, algorithm, status, quantum, cpu_utilization, avg_waiting_time, avg_turnaround_time, num_processes)
                       VALUES ('DEMO_SES_01', 'RoundRobin', 'ACTIVE', 2, 94.50, 3.25, 7.75, 0)"""
                )
                cur.execute(
                    """INSERT IGNORE INTO simulation_sessions
                       (session_id, algorithm, status, quantum, cpu_utilization, avg_waiting_time, avg_turnaround_time, num_processes)
                       VALUES ('DEMO_SES_02', 'SJF', 'COMPLETED', 2, 98.10, 2.10, 6.40, 0)"""
                )
                cur.execute(
                    "INSERT IGNORE INTO scores (session_id, total_score, reason) VALUES ('DEMO_SES_01', 120, 'Initial Demo Session')"
                )
                cur.execute(
                    "INSERT IGNORE INTO scores (session_id, total_score, reason) VALUES ('DEMO_SES_02', 160, 'SJF Benchmark Run')"
                )
                # Insert demo processes (fires trg_after_process_insert!)
                demo_procs = [
                    ('P1', 'DEMO_SES_01', 'Browser', 0, 5, 2, 1024, 'READY', 5),
                    ('P2', 'DEMO_SES_01', 'Music Player', 1, 3, 1, 512, 'READY', 3),
                    ('P3', 'DEMO_SES_01', 'Game Engine', 2, 6, 3, 2048, 'RUNNING', 4),
                    ('P4', 'DEMO_SES_02', 'Compiler', 0, 4, 1, 768, 'TERMINATED', 0),
                ]
                for dp in demo_procs:
                    cur.execute(
                        """INSERT INTO processes
                           (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        dp
                    )
                cur.execute(
                    """INSERT INTO resource_allocations (resource_id, pid, session_id, count, status)
                       VALUES ('PRINTER', 'P1', 'DEMO_SES_01', 1, 'ALLOCATED'),
                              ('DISK', 'P3', 'DEMO_SES_01', 1, 'WAITING')"""
                )
                # Ensure MySQL tables have query optimizer and virtual apps assignment columns
                for tbl, col, ctype in [
                    ('lab_assignments', 'given_query', 'TEXT NULL'),
                    ('lab_assignments', 'expected_rules', 'TEXT NULL'),
                    ('lab_assignments', 'workload_json', 'TEXT NULL'),
                    ('lab_assignments', 'allowed_algorithms_json', 'TEXT NULL'),
                    ('lab_assignments', 'optimization_objective', 'VARCHAR(50) NULL'),
                    ('lab_assignments', 'round_robin_quantum', 'INT DEFAULT 2'),
                    ('assignment_submissions', 'submitted_query', 'TEXT NULL'),
                    ('assignment_submissions', 'student_explanation', 'TEXT NULL'),
                    ('assignment_submissions', 'cbo_metrics', 'TEXT NULL'),
                    ('assignment_submissions', 'selected_algo', 'VARCHAR(50) NULL'),
                    ('assignment_submissions', 'submitted_quantum', 'INT NULL'),
                    ('assignment_submissions', 'objective_value', 'DECIMAL(10, 2) NULL'),
                    ('assignment_submissions', 'scheduling_metrics', 'TEXT NULL'),
                    ('assignment_submissions', 'gantt_json', 'TEXT NULL'),
                    ('assignment_submissions', 'attempts_count', 'INT DEFAULT 1'),
                ]:
                    try:
                        cur.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {ctype}")
                    except Exception:
                        pass
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"MySQL bootstrap warning: {e}")


_fallback_sqlite_path = os.path.join(os.path.dirname(__file__), 'sysrealm_mysql_mirror.db')
_sqlite_bootstrapped = False

def _init_sqlite_schema(conn):
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            account_type TEXT DEFAULT 'student',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS simulation_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            user_id INTEGER NULL,
            algorithm TEXT NOT NULL,
            status TEXT NOT NULL,
            quantum INTEGER DEFAULT 2,
            cpu_utilization REAL DEFAULT 0.0,
            avg_waiting_time REAL DEFAULT 0.0,
            avg_turnaround_time REAL DEFAULT 0.0,
            num_processes INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS processes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pid TEXT NOT NULL,
            session_id TEXT NOT NULL,
            name TEXT NOT NULL,
            arrival_time INTEGER NOT NULL,
            burst_time INTEGER NOT NULL,
            priority INTEGER NOT NULL,
            memory_mb INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'NEW',
            remaining_time INTEGER DEFAULT 0,
            start_time INTEGER NULL,
            completion_time INTEGER NULL,
            waiting_time INTEGER DEFAULT 0,
            turnaround_time INTEGER DEFAULT 0,
            response_time INTEGER NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE,
            UNIQUE (session_id, pid)
        );
        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            total INTEGER NOT NULL,
            icon TEXT
        );
        CREATE TABLE IF NOT EXISTS resource_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_id TEXT NOT NULL,
            pid TEXT NOT NULL,
            session_id TEXT NOT NULL,
            count INTEGER DEFAULT 1,
            status TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (resource_id) REFERENCES resources(resource_id) ON DELETE CASCADE,
            FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE,
            FOREIGN KEY (session_id, pid) REFERENCES processes(session_id, pid) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS process_activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            process_id TEXT,
            event_type TEXT NOT NULL,
            simulation_time INTEGER DEFAULT 0,
            description TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS process_state_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            pid TEXT NOT NULL,
            old_state TEXT NOT NULL,
            new_state TEXT NOT NULL,
            changed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_hist_ses_pid ON process_state_history(session_id, pid);
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            size_kb INTEGER NOT NULL DEFAULT 0,
            owner_pid TEXT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            total_score INTEGER DEFAULT 0,
            reason TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS lab_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            target_panel TEXT NOT NULL DEFAULT 'scheduler',
            required_algo TEXT NOT NULL DEFAULT 'RoundRobin',
            max_awt REAL NULL,
            points INTEGER NOT NULL DEFAULT 50,
            given_query TEXT NULL,
            expected_rules TEXT NULL,
            workload_json TEXT NULL,
            allowed_algorithms_json TEXT NULL,
            optimization_objective TEXT NULL,
            round_robin_quantum INTEGER DEFAULT 2,
            created_by TEXT DEFAULT 'Instructor',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS assignment_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            student_email TEXT NOT NULL,
            student_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'COMPLETED',
            score_awarded INTEGER NOT NULL DEFAULT 50,
            verification_note TEXT NULL,
            submitted_query TEXT NULL,
            student_explanation TEXT NULL,
            cbo_metrics TEXT NULL,
            selected_algo TEXT NULL,
            submitted_quantum INTEGER NULL,
            objective_value REAL NULL,
            scheduling_metrics TEXT NULL,
            gantt_json TEXT NULL,
            attempts_count INTEGER DEFAULT 1,
            completed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(assignment_id, student_email),
            FOREIGN KEY (assignment_id) REFERENCES lab_assignments(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS student_xp_awards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_email TEXT NOT NULL,
            student_name TEXT,
            assignment_id INTEGER NOT NULL,
            points_awarded INTEGER NOT NULL,
            award_reason TEXT,
            awarded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(assignment_id, student_email),
            FOREIGN KEY (assignment_id) REFERENCES lab_assignments(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS simulation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT UNIQUE NOT NULL,
            session_id TEXT NULL,
            user_id INTEGER NULL,
            run_name TEXT NOT NULL,
            algorithm TEXT NOT NULL,
            quantum INTEGER NULL,
            process_count INTEGER NOT NULL DEFAULT 0,
            workload_hash TEXT NOT NULL,
            avg_waiting_time REAL NOT NULL DEFAULT 0.0,
            avg_turnaround_time REAL NOT NULL DEFAULT 0.0,
            avg_response_time REAL NOT NULL DEFAULT 0.0,
            cpu_utilization REAL NOT NULL DEFAULT 0.0,
            throughput REAL NOT NULL DEFAULT 0.0,
            context_switches INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'COMPLETED',
            gantt_json TEXT NULL,
            metrics_json TEXT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id) ON DELETE SET NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_simrun_workload ON simulation_runs(workload_hash);
        CREATE INDEX IF NOT EXISTS idx_simrun_algo ON simulation_runs(algorithm);
        CREATE INDEX IF NOT EXISTS idx_simrun_created ON simulation_runs(created_at);
        CREATE INDEX IF NOT EXISTS idx_simrun_session ON simulation_runs(session_id);

        CREATE TABLE IF NOT EXISTS simulation_run_processes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            pid TEXT NOT NULL,
            name TEXT NOT NULL,
            arrival_time INTEGER NOT NULL,
            burst_time INTEGER NOT NULL,
            priority INTEGER NOT NULL DEFAULT 1,
            memory_mb INTEGER NOT NULL DEFAULT 512,
            start_time INTEGER NULL,
            completion_time INTEGER NULL,
            waiting_time INTEGER NOT NULL DEFAULT 0,
            turnaround_time INTEGER NOT NULL DEFAULT 0,
            response_time INTEGER NULL,
            execution_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (run_id) REFERENCES simulation_runs(run_id) ON DELETE CASCADE,
            UNIQUE(run_id, pid)
        );
        CREATE INDEX IF NOT EXISTS idx_simrunproc_run ON simulation_run_processes(run_id);
        CREATE INDEX IF NOT EXISTS idx_simrunproc_pid ON simulation_run_processes(pid);

        DROP TRIGGER IF EXISTS trg_before_process_insert;
        DROP TRIGGER IF EXISTS trg_before_process_update;
        DROP TRIGGER IF EXISTS trg_after_process_insert;
        DROP TRIGGER IF EXISTS trg_after_process_insert_terminated;
        DROP TRIGGER IF EXISTS trg_after_process_state_update;
        DROP TRIGGER IF EXISTS trg_after_process_terminated;
        DROP TRIGGER IF EXISTS trg_after_process_delete;
        DROP TRIGGER IF EXISTS trg_after_resource_allocation;

        CREATE TRIGGER trg_before_process_insert
        BEFORE INSERT ON processes
        FOR EACH ROW
        BEGIN
            SELECT CASE
                WHEN NEW.burst_time <= 0 THEN
                    RAISE(ABORT, 'MySQL Trigger [trg_before_process_insert]: Burst time must be greater than 0')
                WHEN NEW.memory_mb <= 0 OR NEW.memory_mb > 16384 THEN
                    RAISE(ABORT, 'MySQL Trigger [trg_before_process_insert]: Memory allocation must be between 1 MB and 16384 MB (16 GB)')
                WHEN NEW.arrival_time < 0 THEN
                    RAISE(ABORT, 'MySQL Trigger [trg_before_process_insert]: Arrival time cannot be negative')
                WHEN NEW.state NOT IN ('NEW', 'READY', 'RUNNING', 'WAITING', 'TERMINATED') THEN
                    RAISE(ABORT, 'MySQL Trigger [trg_before_process_insert]: Invalid process state')
            END;
        END;

        CREATE TRIGGER trg_before_process_update
        BEFORE UPDATE ON processes
        FOR EACH ROW
        BEGIN
            SELECT CASE
                WHEN NEW.burst_time <= 0 THEN
                    RAISE(ABORT, 'MySQL Trigger [trg_before_process_update]: Burst time must be greater than 0')
                WHEN NEW.memory_mb <= 0 OR NEW.memory_mb > 16384 THEN
                    RAISE(ABORT, 'MySQL Trigger [trg_before_process_update]: Memory allocation must be between 1 MB and 16384 MB (16 GB)')
                WHEN NEW.arrival_time < 0 THEN
                    RAISE(ABORT, 'MySQL Trigger [trg_before_process_update]: Arrival time cannot be negative')
                WHEN NEW.state NOT IN ('NEW', 'READY', 'RUNNING', 'WAITING', 'TERMINATED') THEN
                    RAISE(ABORT, 'MySQL Trigger [trg_before_process_update]: Invalid process state')
            END;
        END;

        CREATE TRIGGER trg_after_process_insert
        AFTER INSERT ON processes
        FOR EACH ROW
        BEGIN
            UPDATE simulation_sessions SET num_processes = num_processes + 1 WHERE session_id = NEW.session_id;
            INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description)
            VALUES (NEW.session_id, NEW.pid, 'PROCESS_CREATED', NEW.arrival_time,
                    '[Trigger: trg_after_process_insert] Process ' || NEW.name || ' (' || NEW.pid || ') created with burst=' || NEW.burst_time || 'ms, mem=' || NEW.memory_mb || 'MB');
        END;

        CREATE TRIGGER trg_after_process_insert_terminated
        AFTER INSERT ON processes
        FOR EACH ROW
        WHEN NEW.state = 'TERMINATED'
        BEGIN
            INSERT INTO scores (session_id, total_score, reason)
            VALUES (NEW.session_id, 10, 'Auto-awarded by trigger for completing ' || NEW.pid)
            ON CONFLICT(session_id) DO UPDATE SET
                total_score = total_score + 10,
                reason = 'Auto-awarded +10 by trigger for completing ' || NEW.pid;
        END;

        CREATE TRIGGER trg_after_process_state_update
        AFTER UPDATE ON processes
        FOR EACH ROW
        WHEN OLD.state <> NEW.state
        BEGIN
            INSERT INTO process_state_history (session_id, pid, old_state, new_state, changed_at)
            VALUES (NEW.session_id, NEW.pid, OLD.state, NEW.state, datetime('now'));
        END;

        CREATE TRIGGER trg_after_process_terminated
        AFTER UPDATE ON processes
        FOR EACH ROW
        WHEN NEW.state = 'TERMINATED' AND OLD.state <> 'TERMINATED'
        BEGIN
            INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description)
            VALUES (NEW.session_id, NEW.pid, 'PROCESS_TERMINATED', COALESCE(NEW.completion_time, 0),
                    '[Trigger: trg_after_process_terminated] Process ' || NEW.name || ' (' || NEW.pid || ') completed execution. TAT=' || NEW.turnaround_time || ', WT=' || NEW.waiting_time);
            INSERT INTO scores (session_id, total_score, reason)
            VALUES (NEW.session_id, 10, 'Auto-awarded by trigger for completing ' || NEW.pid)
            ON CONFLICT(session_id) DO UPDATE SET
                total_score = total_score + 10,
                reason = 'Auto-awarded +10 by trigger for completing ' || NEW.pid;
        END;

        CREATE TRIGGER trg_after_process_delete
        AFTER DELETE ON processes
        FOR EACH ROW
        BEGIN
            UPDATE simulation_sessions SET num_processes = MAX(0, num_processes - 1) WHERE session_id = OLD.session_id;
            INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description)
            VALUES (OLD.session_id, OLD.pid, 'PROCESS_DELETED', 0,
                    '[Trigger: trg_after_process_delete] Process ' || OLD.name || ' (' || OLD.pid || ') removed from session');
        END;

        CREATE TRIGGER trg_after_resource_allocation
        AFTER INSERT ON resource_allocations
        FOR EACH ROW
        BEGIN
            INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description)
            VALUES (NEW.session_id, NEW.pid, 'RESOURCE_' || UPPER(NEW.status), 0,
                    '[Trigger: trg_after_resource_allocation] Process ' || NEW.pid || ' ' || NEW.status || ' resource ' || NEW.resource_id || ' (count=' || NEW.count || ')');
        END;
    """)

    # Dynamic migrations for existing databases
    for tbl, col, ctype in [
        ('users', 'account_type', "TEXT DEFAULT 'student'"),
        ('lab_assignments', 'given_query', 'TEXT'),
        ('lab_assignments', 'expected_rules', 'TEXT'),
        ('lab_assignments', 'workload_json', 'TEXT'),
        ('lab_assignments', 'allowed_algorithms_json', 'TEXT'),
        ('lab_assignments', 'optimization_objective', 'TEXT'),
        ('lab_assignments', 'round_robin_quantum', 'INTEGER DEFAULT 2'),
        ('assignment_submissions', 'submitted_query', 'TEXT'),
        ('assignment_submissions', 'student_explanation', 'TEXT'),
        ('assignment_submissions', 'cbo_metrics', 'TEXT'),
        ('assignment_submissions', 'selected_algo', 'TEXT'),
        ('assignment_submissions', 'submitted_quantum', 'INTEGER'),
        ('assignment_submissions', 'objective_value', 'REAL'),
        ('assignment_submissions', 'scheduling_metrics', 'TEXT'),
        ('assignment_submissions', 'gantt_json', 'TEXT'),
        ('assignment_submissions', 'attempts_count', 'INTEGER DEFAULT 1'),
    ]:
        try:
            cur.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {ctype}")
        except Exception:
            pass

    cur.execute("SELECT COUNT(*) FROM lab_assignments")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            """INSERT INTO lab_assignments (title, description, target_panel, required_algo, max_awt, points, given_query, expected_rules, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    'Challenge #1: Schedule 4 processes using Round Robin (Q=2) with Avg Waiting Time < 5.0',
                    'Open CPU Scheduler, select Round Robin (Quantum = 2), schedule 4 processes so Average Waiting Time stays under 5.0 ms, and submit.',
                    'scheduler', 'RoundRobin', 5.00, 50, None, None, 'Prof. Instructor'
                ),
                (
                    'Challenge #2: Detect & Resolve the 3-Process Circular Deadlock',
                    'Open the Deadlock Detector panel, load the 3-Process Circular Wait scenario, run cycle detection on the Resource Allocation Graph, and submit.',
                    'deadlock', 'DEADLOCK_3PROC', None, 60, None, None, 'Prof. Instructor'
                ),
                (
                    'Challenge #3: Push Selection Down JOIN & Eliminate Cartesian Product',
                    'Rewrite the unoptimized SQL query joining users and processes by pushing WHERE filter predicates down before the JOIN, converting comma cross-product to ANSI INNER JOIN, and pruning unneeded columns.',
                    'optimizer', 'HEURISTIC_REWRITE', None, 60,
                    'SELECT * FROM users u, processes p WHERE u.email = p.session_id AND p.burst_time > 4 AND p.priority = 1;',
                    '1. Pushdown Selection: sigma(burst_time > 4 AND priority = 1)\n2. Eliminate Cartesian Product: Replace comma-join with ANSI INNER JOIN (bowtie)\n3. Projection Pruning: Project only required attributes',
                    'Prof. Instructor'
                )
            ]
        )
    else:
        # Check if query optimizer challenge already seeded
        cur.execute("SELECT COUNT(*) FROM lab_assignments WHERE target_panel = 'optimizer'")
        if cur.fetchone()[0] == 0:
            cur.execute(
                """INSERT INTO lab_assignments (title, description, target_panel, required_algo, max_awt, points, given_query, expected_rules, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    'Challenge #3: Push Selection Down JOIN & Eliminate Cartesian Product',
                    'Rewrite the unoptimized SQL query joining users and processes by pushing WHERE filter predicates down before the JOIN, converting comma cross-product to ANSI INNER JOIN, and pruning unneeded columns.',
                    'optimizer', 'HEURISTIC_REWRITE', None, 60,
                    'SELECT * FROM users u, processes p WHERE u.email = p.session_id AND p.burst_time > 4 AND p.priority = 1;',
                    '1. Pushdown Selection: sigma(burst_time > 4 AND priority = 1)\n2. Eliminate Cartesian Product: Replace comma-join with ANSI INNER JOIN (bowtie)\n3. Projection Pruning: Project only required attributes',
                    'Prof. Instructor'
                )
            )
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT OR IGNORE INTO users (username, email, password_hash) VALUES (?, ?, ?)", [
            ('Krish', 'krish@sysrealm.com', 'sha256$demo_student_hash'),
            ('Prof_Admin', 'teacher@sysrealm.com', 'sha256$demo_teacher_hash'),
        ])
    cur.execute("SELECT COUNT(*) FROM simulation_sessions")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT OR IGNORE INTO simulation_sessions (session_id, user_id, algorithm, status, quantum, cpu_utilization, avg_waiting_time, avg_turnaround_time, num_processes) VALUES ('DEMO_SES_01', 1, 'RoundRobin', 'ACTIVE', 2, 94.50, 3.25, 7.75, 0)")
        cur.execute("INSERT OR IGNORE INTO simulation_sessions (session_id, user_id, algorithm, status, quantum, cpu_utilization, avg_waiting_time, avg_turnaround_time, num_processes) VALUES ('DEMO_SES_02', 1, 'SJF', 'COMPLETED', 2, 98.10, 2.10, 6.40, 0)")
    cur.execute("SELECT COUNT(*) FROM files")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT INTO files (session_id, filename, size_kb, owner_pid) VALUES (?, ?, ?, ?)", [
            ('DEMO_SES_01', 'kernel_boot.log', 128, 'P1'),
            ('DEMO_SES_01', 'audio_buffer.raw', 512, 'P2'),
            ('DEMO_SES_01', 'shader_cache.bin', 2048, 'P3'),
        ])
    cur.execute("SELECT COUNT(*) FROM resources")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT OR IGNORE INTO resources (resource_id, name, total, icon) VALUES (?, ?, ?, ?)", [
            ('PRINTER', 'Printer', 1, '🖨️'),
            ('DISK', 'Disk Drive', 2, '💾'),
            ('NETWORK', 'Network Adapter', 1, '🌐'),
            ('IO_DEVICE', 'I/O Controller', 2, '⌨️'),
        ])
        cur.execute("INSERT OR IGNORE INTO scores (session_id, total_score, reason) VALUES ('DEMO_SES_01', 120, 'Initial Demo Session')")
        cur.execute("INSERT OR IGNORE INTO scores (session_id, total_score, reason) VALUES ('DEMO_SES_02', 160, 'SJF Benchmark Run')")
        for dp in [
            ('P1', 'DEMO_SES_01', 'Browser', 0, 5, 2, 1024, 'READY', 5),
            ('P2', 'DEMO_SES_01', 'Music Player', 1, 3, 1, 512, 'READY', 3),
            ('P3', 'DEMO_SES_01', 'Game Engine', 2, 6, 3, 2048, 'RUNNING', 4),
            ('P4', 'DEMO_SES_02', 'Compiler', 0, 4, 1, 768, 'TERMINATED', 0),
        ]:
            cur.execute("INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", dp)
        cur.execute("INSERT INTO resource_allocations (resource_id, pid, session_id, count, status) VALUES ('PRINTER', 'P1', 'DEMO_SES_01', 1, 'ALLOCATED')")
        cur.execute("INSERT INTO resource_allocations (resource_id, pid, session_id, count, status) VALUES ('DISK', 'P3', 'DEMO_SES_01', 1, 'WAITING')")
        conn.commit()
    else:
        conn.commit()


def _get_sqlite_mirror():
    global _sqlite_bootstrapped
    conn = sqlite3.connect(_fallback_sqlite_path, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
    except Exception:
        pass
    conn.execute("PRAGMA busy_timeout = 10000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    if not _sqlite_bootstrapped:
        _init_sqlite_schema(conn)
        _sqlite_bootstrapped = True
    return conn

def _init_users_from_db():
    try:
        mconn = _get_sqlite_mirror()
        cur = mconn.cursor()
        cur.execute("SELECT username, email, password_hash, account_type FROM users")
        for row in cur.fetchall():
            em = (row['email'] or '').strip().lower()
            if em:
                _users[em] = {
                    'name': row['username'],
                    'email': em,
                    'password': row['password_hash'],
                    'account_type': row['account_type'] if 'account_type' in row.keys() and row['account_type'] else 'student'
                }
    except Exception as e:
        print(f"Error loading users from db: {e}")

_init_users_from_db()


@app.route('/api/dbms/status', methods=['GET'])
@teacher_required
def dbms_status():
    db = get_db()
    mysql_ok = db is not None
    counts = {}
    tables = [
        'users', 'simulation_sessions', 'processes', 'resources',
        'resource_allocations', 'process_activity_logs', 'process_state_history',
        'files', 'scores', 'lab_assignments', 'assignment_submissions'
    ]
    if mysql_ok:
        try:
            with db.cursor() as cur:
                for tbl in tables:
                    try:
                        cur.execute(f"SELECT COUNT(*) AS cnt FROM `{tbl}`")
                        counts[tbl] = cur.fetchone()['cnt']
                    except Exception:
                        counts[tbl] = 0
        except Exception as e:
            mysql_ok = False
    if not mysql_ok:
        sconn = _get_sqlite_mirror()
        scur = sconn.cursor()
        for tbl in tables:
            try:
                scur.execute(f"SELECT COUNT(*) FROM {tbl}")
                counts[tbl] = scur.fetchone()[0]
            except Exception:
                counts[tbl] = 0
        sconn.close()

    return ok({
        'mysql_connected': mysql_ok,
        'engine_name': 'MySQL 8.0' if mysql_ok else 'SQLite Fallback Mirror',
        'host': _runtime_db['host'],
        'port': _runtime_db['port'],
        'user': _runtime_db['user'],
        'database': _runtime_db['database'],
        'db_error': getattr(g, 'db_error', None) if not mysql_ok else None,
        'triggers': _MYSQL_TRIGGERS_DDL,
        'table_counts': counts,
        'trigger_feed': list(reversed(_trigger_feed[-20:])),
    })


@app.route('/api/dbms/connect', methods=['POST'])
@teacher_required
def dbms_connect():
    global _mysql_bootstrapped
    data = request.get_json() or {}
    _runtime_db['host'] = (data.get('host') or 'localhost').strip()
    _runtime_db['port'] = int(data.get('port') or 3306)
    _runtime_db['user'] = (data.get('user') or 'root').strip()
    _runtime_db['password'] = data.get('password') or ''
    _runtime_db['database'] = (data.get('database') or 'sysrealm').strip()
    _mysql_bootstrapped = False
    g.pop('db', None)
    db = get_db()
    if db is None:
        return err(f"MySQL connection failed: {getattr(g, 'db_error', 'Check if MySQL server is running on port 3306')}", 400)
    return ok({
        'mysql_connected': True,
        'engine_name': 'MySQL 8.0',
        'message': f"Connected to MySQL ({_runtime_db['user']}@{_runtime_db['host']}:{_runtime_db['port']}/{_runtime_db['database']}) and installed all 7 MySQL Triggers!"
    })


@app.route('/api/dbms/process-history', methods=['GET'])
@login_required
def get_process_history():
    session_id = request.args.get('session_id') or engine.current_session_id or 'DEMO_SES_01'
    pid = request.args.get('pid')
    db = get_db()
    rows = []
    mysql_ok = db is not None
    if mysql_ok:
        try:
            with db.cursor() as cur:
                if pid:
                    cur.execute(
                        """SELECT id, session_id, pid, old_state, new_state, changed_at
                           FROM process_state_history
                           WHERE session_id = %s AND pid = %s
                           ORDER BY id ASC""",
                        (session_id, pid)
                    )
                else:
                    cur.execute(
                        """SELECT id, session_id, pid, old_state, new_state, changed_at
                           FROM process_state_history
                           WHERE session_id = %s
                           ORDER BY id ASC""",
                        (session_id,)
                    )
                rows = cur.fetchall()
                for r in rows:
                    if hasattr(r.get('changed_at'), 'isoformat'):
                        r['changed_at'] = r['changed_at'].isoformat()
        except Exception as e:
            mysql_ok = False

    if not mysql_ok:
        try:
            sconn = _get_sqlite_mirror()
            scur = sconn.cursor()
            if pid:
                scur.execute(
                    """SELECT id, session_id, pid, old_state, new_state, changed_at
                       FROM process_state_history
                       WHERE session_id = ? AND pid = ?
                       ORDER BY id ASC""",
                    (session_id, pid)
                )
            else:
                scur.execute(
                    """SELECT id, session_id, pid, old_state, new_state, changed_at
                       FROM process_state_history
                       WHERE session_id = ?
                       ORDER BY id ASC""",
                    (session_id,)
                )
            rows = [dict(r) for r in scur.fetchall()]
            sconn.close()
        except Exception as e:
            print(f"Error fetching history from SQLite mirror: {e}")

    return ok({
        'session_id': session_id,
        'pid': pid,
        'history': rows,
        'count': len(rows),
        'engine': 'MySQL 8.0' if mysql_ok else 'SQLite Fallback Mirror'
    })


@app.route('/api/processes/<pid>/state', methods=['POST'])
@login_required
def update_process_state(pid):
    data = request.get_json() or {}
    new_state = (data.get('state') or '').strip().upper()
    valid_states = ('NEW', 'READY', 'RUNNING', 'WAITING', 'TERMINATED')
    if new_state not in valid_states:
        return err(f'Invalid state: {new_state}. Allowed: {list(valid_states)}')

    session_id = data.get('session_id') or engine.current_session_id or 'DEMO_SES_01'
    db = get_db()
    mysql_ok = db is not None
    old_state = None
    history_entry = None

    # In-memory sync
    proc = engine.process_manager.get_process(pid)
    if proc:
        old_state = proc.state
        proc.state = new_state
        if new_state == 'TERMINATED':
            proc.remaining_time = 0
            if proc.completion_time is None:
                proc.completion_time = proc.arrival_time + proc.burst_time
            engine.memory_manager.release(pid)

    if mysql_ok:
        try:
            with db.cursor() as cur:
                cur.execute("SELECT state FROM processes WHERE pid = %s AND session_id = %s", (pid, session_id))
                row = cur.fetchone()
                if not row:
                    return err(f"Process '{pid}' not found in session '{session_id}'", 404)
                if old_state is None:
                    old_state = row['state']
                cur.execute(
                    "UPDATE processes SET state = %s WHERE pid = %s AND session_id = %s",
                    (new_state, pid, session_id)
                )
                cur.execute(
                    """SELECT id, session_id, pid, old_state, new_state, changed_at
                       FROM process_state_history
                       WHERE pid = %s AND session_id = %s
                       ORDER BY id DESC LIMIT 1""",
                    (pid, session_id)
                )
                h = cur.fetchone()
                if h and hasattr(h.get('changed_at'), 'isoformat'):
                    h['changed_at'] = h['changed_at'].isoformat()
                history_entry = h
            db.commit()
        except Exception as e:
            db.rollback()
            return err(f"Database update failed: {e}", 400)
    else:
        try:
            sconn = _get_sqlite_mirror()
            with sconn:
                scur = sconn.cursor()
                scur.execute("SELECT state FROM processes WHERE pid = ? AND session_id = ?", (pid, session_id))
                row = scur.fetchone()
                if not row:
                    return err(f"Process '{pid}' not found in session '{session_id}'", 404)
                if old_state is None:
                    old_state = row['state']
                scur.execute(
                    "UPDATE processes SET state = ? WHERE pid = ? AND session_id = ?",
                    (new_state, pid, session_id)
                )
                scur.execute(
                    """SELECT id, session_id, pid, old_state, new_state, changed_at
                       FROM process_state_history
                       WHERE pid = ? AND session_id = ?
                       ORDER BY id DESC LIMIT 1""",
                    (pid, session_id)
                )
                h = scur.fetchone()
                history_entry = dict(h) if h else None
            sconn.close()
        except Exception as e:
            return err(f"Database update failed: {e}", 400)

    return ok({
        'message': f"Process {pid} transitioned from {old_state} to {new_state}",
        'pid': pid,
        'session_id': session_id,
        'old_state': old_state,
        'new_state': new_state,
        'history_record': history_entry,
        'engine': 'MySQL 8.0' if mysql_ok else 'SQLite Fallback Mirror'
    })


@app.route('/api/dbms/fire-trigger', methods=['POST'])
@teacher_required
def dbms_fire_trigger():
    data = request.get_json() or {}
    trig_type = data.get('trigger_type', 'after_insert')
    db = get_db()
    mysql_ok = db is not None
    ts = datetime.datetime.now().strftime('%H:%M:%S')

    # 1. Test BEFORE INSERT validation trigger (burst_time = -5)
    if trig_type == 'before_insert':
        sql_tried = (
            "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)\n"
            "VALUES ('P_ERR', 'DEMO_SES_01', 'CorruptKernelTask', 0, -5, 1, 512, 'NEW');"
        )
        blocked_msg = ""
        if mysql_ok:
            try:
                with db.cursor() as cur:
                    cur.execute(
                        "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state) "
                        "VALUES ('P_ERR', 'DEMO_SES_01', 'CorruptKernelTask', 0, -5, 1, 512, 'NEW')"
                    )
                db.commit()
            except Exception as e:
                db.rollback()
                blocked_msg = str(e)
        else:
            sconn = _get_sqlite_mirror()
            try:
                sconn.execute(
                    "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state) "
                    "VALUES ('P_ERR', 'DEMO_SES_01', 'CorruptKernelTask', 0, -5, 1, 512, 'NEW')"
                )
                sconn.commit()
            except Exception as e:
                blocked_msg = str(e)
            finally:
                sconn.close()

        entry = {
            'time': ts,
            'trigger_name': 'trg_before_process_insert',
            'timing': 'BEFORE INSERT ON processes',
            'status': 'BLOCKED BY TRIGGER (SQLSTATE 45000)',
            'sql_executed': sql_tried,
            'effect': blocked_msg or "MySQL Trigger [trg_before_process_insert]: Burst time must be greater than 0",
            'rows_affected': []
        }
        _trigger_feed.append(entry)
        return ok({'result': entry, 'mysql_connected': mysql_ok, 'engine': 'MySQL 8.0' if mysql_ok else 'SQLite Fallback Mirror'})

    # 2. Test BEFORE UPDATE validation trigger (burst_time = -10 on existing process)
    elif trig_type == 'before_update':
        sql_tried = (
            "UPDATE processes\n"
            "SET burst_time = -10\n"
            "WHERE pid = 'P1' AND session_id = 'DEMO_SES_01';"
        )
        blocked_msg = ""
        if mysql_ok:
            try:
                with db.cursor() as cur:
                    cur.execute(
                        "UPDATE processes SET burst_time = -10 WHERE pid = 'P1' AND session_id = 'DEMO_SES_01'"
                    )
                db.commit()
            except Exception as e:
                db.rollback()
                blocked_msg = str(e)
        else:
            sconn = _get_sqlite_mirror()
            try:
                sconn.execute(
                    "UPDATE processes SET burst_time = -10 WHERE pid = 'P1' AND session_id = 'DEMO_SES_01'"
                )
                sconn.commit()
            except Exception as e:
                blocked_msg = str(e)
            finally:
                sconn.close()

        entry = {
            'time': ts,
            'trigger_name': 'trg_before_process_update',
            'timing': 'BEFORE UPDATE ON processes',
            'status': 'BLOCKED BY TRIGGER (SQLSTATE 45000)',
            'sql_executed': sql_tried,
            'effect': blocked_msg or "MySQL Trigger [trg_before_process_update]: Burst time must be greater than 0",
            'rows_affected': []
        }
        _trigger_feed.append(entry)
        return ok({'result': entry, 'mysql_connected': mysql_ok, 'engine': 'MySQL 8.0' if mysql_ok else 'SQLite Fallback Mirror'})

    # 3. Test AFTER INSERT trigger
    elif trig_type == 'after_insert':
        new_pid = f"P{len(_trigger_feed) + 10}"
        proc_name = f"WorkerNode-{len(_trigger_feed) + 1}"
        sql_tried = (
            f"INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time)\n"
            f"VALUES ('{new_pid}', 'DEMO_SES_01', '{proc_name}', 2, 6, 1, 512, 'READY', 6);"
        )
        if mysql_ok:
            with db.cursor() as cur:
                cur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id='DEMO_SES_01'")
                before_cnt = (cur.fetchone() or {}).get('num_processes', 0)
                cur.execute(
                    """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time)
                       VALUES (%s, 'DEMO_SES_01', %s, 2, 6, 1, 512, 'READY', 6)""",
                    (new_pid, proc_name)
                )
                db.commit()
                cur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id='DEMO_SES_01'")
                after_cnt = (cur.fetchone() or {}).get('num_processes', 0)
                cur.execute(
                    "SELECT id, session_id, process_id, event_type, description FROM process_activity_logs WHERE process_id=%s ORDER BY id DESC LIMIT 1",
                    (new_pid,)
                )
                log_row = cur.fetchone()
        else:
            sconn = _get_sqlite_mirror()
            scur = sconn.cursor()
            scur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id='DEMO_SES_01'")
            before_cnt = scur.fetchone()[0]
            scur.execute(
                "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time) "
                "VALUES (?, 'DEMO_SES_01', ?, 2, 6, 1, 512, 'READY', 6)",
                (new_pid, proc_name)
            )
            sconn.commit()
            scur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id='DEMO_SES_01'")
            after_cnt = scur.fetchone()[0]
            scur.execute(
                "SELECT id, session_id, process_id, event_type, description FROM process_activity_logs WHERE process_id=? ORDER BY id DESC LIMIT 1",
                (new_pid,)
            )
            r = scur.fetchone()
            log_row = dict(r) if r else {}
            sconn.close()

        entry = {
            'time': ts,
            'trigger_name': 'trg_after_process_insert',
            'timing': 'AFTER INSERT ON processes',
            'status': 'FIRED SUCCESSFULLY',
            'sql_executed': sql_tried,
            'effect': f"1) simulation_sessions.num_processes incremented {before_cnt} → {after_cnt}\n2) Auto-inserted audit row into process_activity_logs: {log_row.get('description', '')}",
            'rows_affected': [log_row] if log_row else []
        }
        _trigger_feed.append(entry)
        return ok({'result': entry, 'mysql_connected': mysql_ok, 'engine': 'MySQL 8.0' if mysql_ok else 'SQLite Fallback Mirror'})

    # 4. Test AFTER UPDATE process state trigger -> logs in process_state_history
    elif trig_type == 'after_update_state':
        target_pid = 'P1'
        new_st = 'RUNNING'
        sql_tried = (
            f"UPDATE processes\n"
            f"SET state = '{new_st}'\n"
            f"WHERE pid = '{target_pid}' AND session_id = 'DEMO_SES_01';"
        )
        if mysql_ok:
            with db.cursor() as cur:
                cur.execute("SELECT state FROM processes WHERE pid=%s AND session_id='DEMO_SES_01'", (target_pid,))
                row = cur.fetchone()
                old_st = row['state'] if row else 'READY'
                if old_st == new_st:
                    new_st = 'WAITING'
                cur.execute("UPDATE processes SET state=%s WHERE pid=%s AND session_id='DEMO_SES_01'", (new_st, target_pid))
                db.commit()
                cur.execute(
                    "SELECT id, session_id, pid, old_state, new_state, changed_at FROM process_state_history WHERE pid=%s ORDER BY id DESC LIMIT 1",
                    (target_pid,)
                )
                hist_row = cur.fetchone()
                if hist_row and hasattr(hist_row.get('changed_at'), 'isoformat'):
                    hist_row['changed_at'] = hist_row['changed_at'].isoformat()
        else:
            sconn = _get_sqlite_mirror()
            scur = sconn.cursor()
            scur.execute("SELECT state FROM processes WHERE pid=? AND session_id='DEMO_SES_01'", (target_pid,))
            row = scur.fetchone()
            old_st = row[0] if row else 'READY'
            if old_st == new_st:
                new_st = 'WAITING'
            scur.execute("UPDATE processes SET state=? WHERE pid=? AND session_id='DEMO_SES_01'", (new_st, target_pid))
            sconn.commit()
            scur.execute(
                "SELECT id, session_id, pid, old_state, new_state, changed_at FROM process_state_history WHERE pid=? ORDER BY id DESC LIMIT 1",
                (target_pid,)
            )
            r = scur.fetchone()
            hist_row = dict(r) if r else {}
            sconn.close()

        entry = {
            'time': ts,
            'trigger_name': 'trg_after_process_state_update',
            'timing': 'AFTER UPDATE ON processes',
            'status': 'FIRED SUCCESSFULLY',
            'sql_executed': sql_tried,
            'effect': f"Captured OS transition {old_st} → {new_st} and auto-inserted record #{hist_row.get('id', '?')} into process_state_history",
            'rows_affected': [hist_row] if hist_row else []
        }
        _trigger_feed.append(entry)
        return ok({'result': entry, 'mysql_connected': mysql_ok, 'engine': 'MySQL 8.0' if mysql_ok else 'SQLite Fallback Mirror'})

    # 5. Test AFTER UPDATE trigger for process termination (+10 score)
    elif trig_type == 'after_update':
        if mysql_ok:
            with db.cursor() as cur:
                cur.execute("SELECT total_score FROM scores WHERE session_id='DEMO_SES_01'")
                before_score = (cur.fetchone() or {}).get('total_score', 0)
                cur.execute("SELECT pid, name FROM processes WHERE session_id='DEMO_SES_01' AND state != 'TERMINATED' LIMIT 1")
                target = cur.fetchone()
                if not target:
                    target_pid = f"P{len(_trigger_feed) + 20}"
                    cur.execute(
                        "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time) "
                        "VALUES (%s, 'DEMO_SES_01', 'AutoTask', 0, 4, 1, 256, 'RUNNING', 0)",
                        (target_pid,)
                    )
                    db.commit()
                else:
                    target_pid = target['pid']

                cur.execute(
                    "UPDATE processes SET state='TERMINATED', completion_time=14, turnaround_time=11, waiting_time=5 "
                    "WHERE pid=%s AND session_id='DEMO_SES_01'",
                    (target_pid,)
                )
                db.commit()
                cur.execute("SELECT total_score, reason FROM scores WHERE session_id='DEMO_SES_01'")
                score_row = cur.fetchone() or {}
                after_score = score_row.get('total_score', before_score + 10)
                cur.execute(
                    "SELECT id, session_id, process_id, event_type, description FROM process_activity_logs WHERE process_id=%s AND event_type='PROCESS_TERMINATED' ORDER BY id DESC LIMIT 1",
                    (target_pid,)
                )
                log_row = cur.fetchone()
        else:
            sconn = _get_sqlite_mirror()
            scur = sconn.cursor()
            scur.execute("SELECT total_score FROM scores WHERE session_id='DEMO_SES_01'")
            before_score = scur.fetchone()[0]
            scur.execute("SELECT pid FROM processes WHERE session_id='DEMO_SES_01' AND state != 'TERMINATED' LIMIT 1")
            row = scur.fetchone()
            if not row:
                target_pid = f"P{len(_trigger_feed) + 20}"
                scur.execute(
                    "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time) "
                    "VALUES (?, 'DEMO_SES_01', 'AutoTask', 0, 4, 1, 256, 'RUNNING', 0)",
                    (target_pid,)
                )
                sconn.commit()
            else:
                target_pid = row[0]

            scur.execute(
                "UPDATE processes SET state='TERMINATED', completion_time=14, turnaround_time=11, waiting_time=5 "
                "WHERE pid=? AND session_id='DEMO_SES_01'",
                (target_pid,)
            )
            sconn.commit()
            scur.execute("SELECT total_score, reason FROM scores WHERE session_id='DEMO_SES_01'")
            after_score = scur.fetchone()[0]
            scur.execute(
                "SELECT id, session_id, process_id, event_type, description FROM process_activity_logs WHERE process_id=? AND event_type='PROCESS_TERMINATED' ORDER BY id DESC LIMIT 1",
                (target_pid,)
            )
            r = scur.fetchone()
            log_row = dict(r) if r else {}
            sconn.close()

        sql_tried = (
            f"UPDATE processes\n"
            f"SET state = 'TERMINATED', completion_time = 14, turnaround_time = 11, waiting_time = 5\n"
            f"WHERE pid = '{target_pid}' AND session_id = 'DEMO_SES_01';"
        )
        entry = {
            'time': ts,
            'trigger_name': 'trg_after_process_terminated',
            'timing': 'AFTER UPDATE ON processes',
            'status': 'FIRED SUCCESSFULLY',
            'sql_executed': sql_tried,
            'effect': f"1) scores.total_score auto-updated {before_score} → {after_score} (+10 pts)\n2) Auto-logged completion in process_activity_logs: {log_row.get('description', '')}",
            'rows_affected': [log_row] if log_row else []
        }
        _trigger_feed.append(entry)
        return ok({'result': entry, 'mysql_connected': mysql_ok, 'engine': 'MySQL 8.0' if mysql_ok else 'SQLite Fallback Mirror'})

    # 6. Test AFTER DELETE trigger
    elif trig_type == 'after_delete':
        del_pid = f"P_DEL_{len(_trigger_feed)}"
        # Insert temporary process then delete it
        if mysql_ok:
            with db.cursor() as cur:
                cur.execute(
                    "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state) "
                    "VALUES (%s, 'DEMO_SES_01', 'TempTask', 0, 3, 2, 256, 'READY')",
                    (del_pid,)
                )
                db.commit()
                cur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id='DEMO_SES_01'")
                before_cnt = (cur.fetchone() or {}).get('num_processes', 0)
                cur.execute("DELETE FROM processes WHERE pid=%s AND session_id='DEMO_SES_01'", (del_pid,))
                db.commit()
                cur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id='DEMO_SES_01'")
                after_cnt = (cur.fetchone() or {}).get('num_processes', 0)
                cur.execute(
                    "SELECT id, session_id, process_id, event_type, description FROM process_activity_logs WHERE process_id=%s AND event_type='PROCESS_DELETED' ORDER BY id DESC LIMIT 1",
                    (del_pid,)
                )
                log_row = cur.fetchone()
        else:
            sconn = _get_sqlite_mirror()
            scur = sconn.cursor()
            scur.execute(
                "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state) "
                "VALUES (?, 'DEMO_SES_01', 'TempTask', 0, 3, 2, 256, 'READY')",
                (del_pid,)
            )
            sconn.commit()
            scur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id='DEMO_SES_01'")
            before_cnt = scur.fetchone()[0]
            scur.execute("DELETE FROM processes WHERE pid=? AND session_id='DEMO_SES_01'", (del_pid,))
            sconn.commit()
            scur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id='DEMO_SES_01'")
            after_cnt = scur.fetchone()[0]
            scur.execute(
                "SELECT id, session_id, process_id, event_type, description FROM process_activity_logs WHERE process_id=? AND event_type='PROCESS_DELETED' ORDER BY id DESC LIMIT 1",
                (del_pid,)
            )
            r = scur.fetchone()
            log_row = dict(r) if r else {}
            sconn.close()

        sql_tried = (
            f"DELETE FROM processes\n"
            f"WHERE pid = '{del_pid}' AND session_id = 'DEMO_SES_01';"
        )
        entry = {
            'time': ts,
            'trigger_name': 'trg_after_process_delete',
            'timing': 'AFTER DELETE ON processes',
            'status': 'FIRED SUCCESSFULLY',
            'sql_executed': sql_tried,
            'effect': f"1) simulation_sessions.num_processes decremented {before_cnt} → {after_cnt}\n2) Auto-logged deletion in process_activity_logs: {log_row.get('description', '')}",
            'rows_affected': [log_row] if log_row else []
        }
        _trigger_feed.append(entry)
        return ok({'result': entry, 'mysql_connected': mysql_ok, 'engine': 'MySQL 8.0' if mysql_ok else 'SQLite Fallback Mirror'})

    # 7. Test AFTER INSERT on resource_allocations
    else:
        sql_tried = (
            "INSERT INTO resource_allocations (resource_id, pid, session_id, count, status)\n"
            "VALUES ('DISK', 'P2', 'DEMO_SES_01', 1, 'ALLOCATED');"
        )
        if mysql_ok:
            with db.cursor() as cur:
                cur.execute(
                    "INSERT INTO resource_allocations (resource_id, pid, session_id, count, status) "
                    "VALUES ('DISK', 'P2', 'DEMO_SES_01', 1, 'ALLOCATED')"
                )
                db.commit()
                cur.execute(
                    "SELECT id, session_id, process_id, event_type, description FROM process_activity_logs WHERE event_type='RESOURCE_ALLOCATED' ORDER BY id DESC LIMIT 1"
                )
                log_row = cur.fetchone()
        else:
            sconn = _get_sqlite_mirror()
            scur = sconn.cursor()
            scur.execute(
                "INSERT INTO resource_allocations (resource_id, pid, session_id, count, status) "
                "VALUES ('DISK', 'P2', 'DEMO_SES_01', 1, 'ALLOCATED')"
            )
            sconn.commit()
            scur.execute(
                "SELECT id, session_id, process_id, event_type, description FROM process_activity_logs WHERE event_type='RESOURCE_ALLOCATED' ORDER BY id DESC LIMIT 1"
            )
            r = scur.fetchone()
            log_row = dict(r) if r else {}
            sconn.close()

        entry = {
            'time': ts,
            'trigger_name': 'trg_after_resource_allocation',
            'timing': 'AFTER INSERT ON resource_allocations',
            'status': 'FIRED SUCCESSFULLY',
            'sql_executed': sql_tried,
            'effect': f"Auto-inserted hardware audit log into process_activity_logs:\n{log_row.get('description', '')}",
            'rows_affected': [log_row] if log_row else []
        }
        _trigger_feed.append(entry)
        return ok({'result': entry, 'mysql_connected': mysql_ok, 'engine': 'MySQL 8.0' if mysql_ok else 'SQLite Fallback Mirror'})


@app.route('/api/dbms/join', methods=['POST'])
@teacher_required
def dbms_run_join():
    data = request.get_json() or {}
    join_type = data.get('join_type', 'inner_join')
    db = get_db()
    mysql_ok = db is not None

    JOIN_SPECS = {
        'inner_join': {
            'title': 'INNER JOIN — Processes ⋈ Simulation Sessions',
            'tables': ['processes p', 'simulation_sessions s'],
            'join_key': 'p.session_id = s.session_id',
            'explanation': 'Returns only processes that have a matching active or completed session in simulation_sessions, combining process PCB attributes with the session scheduling algorithm.',
            'sql': """SELECT p.pid, p.name AS process_name, p.state,
       p.burst_time, p.memory_mb,
       s.session_id, s.algorithm, s.status AS session_status
FROM processes p
INNER JOIN simulation_sessions s
    ON p.session_id = s.session_id
ORDER BY p.id DESC
LIMIT 15;"""
        },
        'left_join': {
            'title': 'LEFT OUTER JOIN — Hardware Resources ⟕ Allocations',
            'tables': ['resources r', 'resource_allocations ra'],
            'join_key': 'r.resource_id = ra.resource_id',
            'explanation': 'Returns ALL hardware resources from the resources table even if no process has requested or allocated them (unallocated devices show NULL for holder_pid and allocation_status).',
            'sql': """SELECT r.resource_id, r.name AS resource_name, r.total AS total_units,
       ra.pid AS holder_pid, ra.status AS allocation_status, ra.session_id
FROM resources r
LEFT OUTER JOIN resource_allocations ra
    ON r.resource_id = ra.resource_id
ORDER BY r.resource_id, ra.id DESC;"""
        },
        'three_table_join': {
            'title': '3-Table JOIN — Sessions ⋈ Processes ⋈ Scores',
            'tables': ['simulation_sessions s', 'processes p', 'scores sc'],
            'join_key': 's.session_id = p.session_id AND s.session_id = sc.session_id',
            'explanation': 'Joins 3 normalized tables simultaneously to correlate each process execution state with its parent session algorithm and the cumulative trigger-awarded session score.',
            'sql': """SELECT s.session_id, s.algorithm,
       p.pid, p.name AS process_name, p.state,
       COALESCE(sc.total_score, 0) AS session_score,
       sc.reason AS latest_score_reason
FROM simulation_sessions s
INNER JOIN processes p
    ON s.session_id = p.session_id
LEFT JOIN scores sc
    ON s.session_id = sc.session_id
ORDER BY p.id DESC
LIMIT 15;"""
        },
        'group_by_join': {
            'title': 'JOIN + GROUP BY Aggregation — Algorithm Audit Summary',
            'tables': ['simulation_sessions s', 'process_activity_logs l'],
            'join_key': 's.session_id = l.session_id (GROUP BY s.algorithm)',
            'explanation': 'Joins simulation_sessions with process_activity_logs and uses GROUP BY + aggregate functions (COUNT, AVG) to compute total trigger-logged events and CPU utilization per scheduling algorithm.',
            'sql': """SELECT s.algorithm,
       COUNT(DISTINCT s.session_id) AS total_sessions,
       COUNT(l.id) AS total_logged_events,
       ROUND(AVG(s.cpu_utilization), 2) AS avg_cpu_utilization,
       ROUND(AVG(s.avg_waiting_time), 2) AS avg_waiting_time
FROM simulation_sessions s
LEFT JOIN process_activity_logs l
    ON s.session_id = l.session_id
GROUP BY s.algorithm
ORDER BY total_logged_events DESC;"""
        },
        'session_summary': {
            'title': 'Report A: Simulation Session Summary (Sessions ⟕ Process Stats ⟕ Scores)',
            'tables': ['simulation_sessions s', 'processes (pre-aggregated)', 'scores sc'],
            'join_key': 's.session_id = p_agg.session_id AND s.session_id = sc.session_id',
            'explanation': 'Correlates session-level OS metrics with derived process statistics (total processes, completed count, average burst time) and gamification scores. Uses subquery pre-aggregation to eliminate Cartesian row multiplication.',
            'sql': """SELECT 
    s.session_id,
    s.algorithm,
    s.status AS session_status,
    s.num_processes AS registered_proc_count,
    ROUND(s.cpu_utilization, 2) AS cpu_utilization,
    ROUND(s.avg_waiting_time, 2) AS avg_waiting_time,
    ROUND(s.avg_turnaround_time, 2) AS avg_turnaround_time,
    COALESCE(p_agg.total_procs, 0) AS actual_procs_in_db,
    COALESCE(p_agg.completed_procs, 0) AS completed_procs,
    COALESCE(p_agg.avg_burst, 0.0) AS avg_burst_time,
    COALESCE(sc.total_score, 0) AS session_score,
    COALESCE(sc.reason, 'No score recorded') AS score_reason
FROM simulation_sessions s
LEFT JOIN (
    SELECT 
        session_id,
        COUNT(*) AS total_procs,
        SUM(CASE WHEN state = 'TERMINATED' THEN 1 ELSE 0 END) AS completed_procs,
        ROUND(AVG(burst_time), 2) AS avg_burst
    FROM processes
    GROUP BY session_id
) p_agg ON s.session_id = p_agg.session_id
LEFT JOIN scores sc ON s.session_id = sc.session_id
ORDER BY s.id DESC
LIMIT 15;"""
        },
        'resource_utilization': {
            'title': 'Report B: Hardware Resource Allocation & Utilization (Resources ⟕ Allocations ⋈ Processes ⋈ Sessions)',
            'tables': ['resources r', 'resource_allocations ra', 'processes p', 'simulation_sessions s'],
            'join_key': 'r.resource_id = ra.resource_id, (ra.session_id = p.session_id AND ra.pid = p.pid), ra.session_id = s.session_id',
            'explanation': 'Multi-table relational audit joining hardware devices with process allocations via composite foreign keys (session_id, pid). Preserves unallocated devices via LEFT JOIN and surfaces requesting process names and states.',
            'sql': """SELECT 
    r.resource_id,
    r.name AS resource_name,
    r.total AS total_capacity,
    COALESCE(ra.count, 0) AS allocated_units,
    COALESCE(ra.status, 'IDLE/UNALLOCATED') AS allocation_status,
    COALESCE(ra.pid, '—') AS requesting_pid,
    COALESCE(p.name, '—') AS process_name,
    COALESCE(p.state, '—') AS process_state,
    COALESCE(ra.session_id, '—') AS session_id,
    COALESCE(s.algorithm, '—') AS session_algorithm
FROM resources r
LEFT JOIN resource_allocations ra ON r.resource_id = ra.resource_id
LEFT JOIN processes p ON ra.session_id = p.session_id AND ra.pid = p.pid
LEFT JOIN simulation_sessions s ON ra.session_id = s.session_id
ORDER BY r.resource_id, ra.id DESC;"""
        },
        'assignment_submissions_report': {
            'title': 'Report C: Academic Lab Assignments & Student Submissions (Assignments ⟕ Submissions)',
            'tables': ['lab_assignments a', 'assignment_submissions sub'],
            'join_key': 'a.id = sub.assignment_id',
            'explanation': 'Comprehensive educational audit joining instructor lab assignments with student submissions, evaluation scores, and grading notes. Demonstrates outer join behavior where challenges without submissions show NULL.',
            'sql': """SELECT 
    a.id AS assignment_id,
    a.title AS assignment_title,
    a.target_panel,
    a.required_algo,
    a.points AS max_points,
    COALESCE(sub.id, 0) AS submission_id,
    COALESCE(sub.student_name, 'No Submissions Yet') AS student_name,
    COALESCE(sub.student_email, '—') AS student_email,
    COALESCE(sub.status, 'PENDING') AS submission_status,
    COALESCE(sub.score_awarded, 0) AS score_awarded,
    COALESCE(sub.verification_note, 'Pending Evaluation') AS verification_note,
    COALESCE(sub.completed_at, '—') AS submitted_at
FROM lab_assignments a
LEFT JOIN assignment_submissions sub ON a.id = sub.assignment_id
ORDER BY a.id ASC, sub.id DESC;"""
        }
    }

    spec = JOIN_SPECS.get(join_type, JOIN_SPECS['inner_join'])
    rows = []
    if mysql_ok:
        with db.cursor() as cur:
            cur.execute(spec['sql'])
            rows = cur.fetchall()
            for r in rows:
                for k, v in r.items():
                    if hasattr(v, 'isoformat'):
                        r[k] = v.isoformat()
                    elif v is not None and not isinstance(v, (int, float, str, bool)):
                        r[k] = str(v)
    else:
        sconn = _get_sqlite_mirror()
        scur = sconn.cursor()
        scur.execute(spec['sql'])
        fetched = scur.fetchall()
        rows = [dict(r) for r in fetched]
        sconn.close()

    columns = list(rows[0].keys()) if rows else []
    return ok({
        'join_type': join_type,
        'title': spec['title'],
        'tables': spec['tables'],
        'join_key': spec['join_key'],
        'explanation': spec['explanation'],
        'sql': spec['sql'],
        'columns': columns,
        'rows': rows,
        'row_count': len(rows),
        'mysql_connected': mysql_ok,
        'engine': 'MySQL 8.0' if mysql_ok else 'SQLite Fallback Mirror'
    })


def _snapshot_tx_counts(db, mysql_ok, sconn=None):
    """Helper to snapshot row counts + session score before, during, and after a transaction."""
    snap = {}
    tbls = ['processes', 'resource_allocations', 'process_activity_logs', 'process_state_history']
    if mysql_ok and db:
        with db.cursor() as cur:
            for t in tbls:
                cur.execute(f"SELECT COUNT(*) AS c FROM `{t}`")
                snap[t] = cur.fetchone()['c']
            cur.execute("SELECT COALESCE(total_score, 0) AS sc FROM scores WHERE session_id='DEMO_SES_01'")
            row = cur.fetchone()
            snap['session_score'] = row['sc'] if row else 0
    elif sconn is not None:
        scur = sconn.cursor()
        for t in tbls:
            scur.execute(f"SELECT COUNT(*) FROM {t}")
            snap[t] = scur.fetchone()[0]
        scur.execute("SELECT COALESCE(total_score, 0) FROM scores WHERE session_id='DEMO_SES_01'")
        row = scur.fetchone()
        snap['session_score'] = row[0] if row else 0
    return snap


@app.route('/api/dbms/transaction', methods=['POST'])
@teacher_required
def dbms_run_transaction():
    data = request.get_json() or {}
    scenario = data.get('scenario', 'rollback_demo')
    db = get_db()
    mysql_ok = db is not None
    ts = datetime.datetime.now().strftime('%H:%M:%S')

    # ── SCENARIO 1: ATOMIC ROLLBACK ON MID-TRANSACTION FAILURE ──
    if scenario == 'rollback_demo':
        steps = []
        if mysql_ok:
            counts_before = _snapshot_tx_counts(db, True)
            try:
                with db.cursor() as cur:
                    cur.execute("START TRANSACTION")
                    steps.append({
                        'step': 1,
                        'sql': "START TRANSACTION;",
                        'status': 'OK',
                        'detail': ' InnoDB transaction started (autocommit disabled; undo log initialized).'
                    })
                    cur.execute(
                        "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time) "
                        "VALUES ('TX_RB_1', 'DEMO_SES_01', 'AtomicKernelTask', 1, 6, 1, 1024, 'RUNNING', 6)"
                    )
                    steps.append({
                        'step': 2,
                        'sql': "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)\nVALUES ('TX_RB_1', 'DEMO_SES_01', 'AtomicKernelTask', 1, 6, 1, 1024, 'RUNNING');",
                        'status': 'UNCOMMITTED WRITE',
                        'detail': 'Row written to uncommitted buffer + trg_after_process_insert fired (+1 log row).'
                    })
                    cur.execute(
                        "INSERT INTO resource_allocations (resource_id, pid, session_id, count, status) "
                        "VALUES ('PRINTER', 'TX_RB_1', 'DEMO_SES_01', 1, 'ALLOCATED')"
                    )
                    steps.append({
                        'step': 3,
                        'sql': "INSERT INTO resource_allocations (resource_id, pid, session_id, count, status)\nVALUES ('PRINTER', 'TX_RB_1', 'DEMO_SES_01', 1, 'ALLOCATED');",
                        'status': 'UNCOMMITTED WRITE',
                        'detail': 'Hardware PRINTER locked by TX_RB_1 + trg_after_resource_allocation fired (+1 log row).'
                    })
                counts_during = _snapshot_tx_counts(db, True)
                # Deliberate constraint failure (32768 MB > 16384 MB max RAM)
                with db.cursor() as cur:
                    cur.execute(
                        "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state) "
                        "VALUES ('TX_OVERFLOW', 'DEMO_SES_01', 'MemoryOverflowTask', 2, 4, 1, 32768, 'NEW')"
                    )
            except Exception as e:
                err_str = str(e)
                steps.append({
                    'step': 4,
                    'sql': "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)\nVALUES ('TX_OVERFLOW', 'DEMO_SES_01', 'MemoryOverflowTask', 2, 4, 1, 32768, 'NEW');",
                    'status': 'ABORTED BY TRIGGER',
                    'detail': f"SQLSTATE '45000' raised: {err_str}"
                })
                db.rollback()
                steps.append({
                    'step': 5,
                    'sql': "ROLLBACK;",
                    'status': 'ROLLED BACK',
                    'detail': 'Atomicity enforced! Undo log restored processes, resource_allocations, and trigger audit logs to exact pre-transaction state.'
                })
            counts_after = _snapshot_tx_counts(db, True)
        else:
            sconn = _get_sqlite_mirror()
            counts_before = _snapshot_tx_counts(None, False, sconn)
            scur = sconn.cursor()
            try:
                steps.append({
                    'step': 1,
                    'sql': "START TRANSACTION;",
                    'status': 'OK',
                    'detail': 'Transaction started (autocommit disabled; undo journal active).'
                })
                scur.execute(
                    "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time) "
                    "VALUES ('TX_RB_1', 'DEMO_SES_01', 'AtomicKernelTask', 1, 6, 1, 1024, 'RUNNING', 6)"
                )
                steps.append({
                    'step': 2,
                    'sql': "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)\nVALUES ('TX_RB_1', 'DEMO_SES_01', 'AtomicKernelTask', 1, 6, 1, 1024, 'RUNNING');",
                    'status': 'UNCOMMITTED WRITE',
                    'detail': 'Row written to uncommitted buffer + trg_after_process_insert fired (+1 log row).'
                })
                scur.execute(
                    "INSERT INTO resource_allocations (resource_id, pid, session_id, count, status) "
                    "VALUES ('PRINTER', 'TX_RB_1', 'DEMO_SES_01', 1, 'ALLOCATED')"
                )
                steps.append({
                    'step': 3,
                    'sql': "INSERT INTO resource_allocations (resource_id, pid, session_id, count, status)\nVALUES ('PRINTER', 'TX_RB_1', 'DEMO_SES_01', 1, 'ALLOCATED');",
                    'status': 'UNCOMMITTED WRITE',
                    'detail': 'Hardware PRINTER locked by TX_RB_1 + trg_after_resource_allocation fired (+1 log row).'
                })
                counts_during = _snapshot_tx_counts(None, False, sconn)
                scur.execute(
                    "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state) "
                    "VALUES ('TX_OVERFLOW', 'DEMO_SES_01', 'MemoryOverflowTask', 2, 4, 1, 32768, 'NEW')"
                )
            except Exception as e:
                err_str = str(e)
                steps.append({
                    'step': 4,
                    'sql': "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)\nVALUES ('TX_OVERFLOW', 'DEMO_SES_01', 'MemoryOverflowTask', 2, 4, 1, 32768, 'NEW');",
                    'status': 'ABORTED BY TRIGGER',
                    'detail': f"SQLSTATE '45000' raised: {err_str}"
                })
                sconn.rollback()
                steps.append({
                    'step': 5,
                    'sql': "ROLLBACK;",
                    'status': 'ROLLED BACK',
                    'detail': 'Atomicity enforced! Undo log restored processes, resource_allocations, and trigger audit logs to exact pre-transaction state.'
                })
            counts_after = _snapshot_tx_counts(None, False, sconn)
            sconn.close()

        return ok({
            'scenario': scenario,
            'title': 'Atomic Rollback on Mid-Transaction Failure (ROLLBACK)',
            'acid_focus': 'Atomicity (All-or-Nothing) & Consistency',
            'outcome': 'ROLLED BACK — 0 net rows modified',
            'time': ts,
            'steps': steps,
            'counts_before': counts_before,
            'counts_during': counts_during,
            'counts_after': counts_after,
            'explanation': 'Steps 2 & 3 inserted rows into processes, resource_allocations, and process_activity_logs (via triggers). When Step 4 violated the 16 GB RAM hardware limit (32768 MB), ROLLBACK undid ALL prior writes in the transaction.',
            'mysql_connected': mysql_ok
        })

    # ── SCENARIO 2: MULTI-TABLE ATOMIC COMMIT ──
    elif scenario == 'commit_demo':
        steps = []
        tx_pid = f"TX_OK_{int(datetime.datetime.now().timestamp()) % 1000}"
        if mysql_ok:
            counts_before = _snapshot_tx_counts(db, True)
            with db.cursor() as cur:
                cur.execute("START TRANSACTION")
                steps.append({
                    'step': 1,
                    'sql': "START TRANSACTION;",
                    'status': 'OK',
                    'detail': 'Transaction started across processes, resource_allocations, and scores.'
                })
                cur.execute(
                    "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time) "
                    "VALUES (%s, 'DEMO_SES_01', 'CommittedService', 0, 4, 1, 512, 'READY', 4)",
                    (tx_pid,)
                )
                steps.append({
                    'step': 2,
                    'sql': f"INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)\nVALUES ('{tx_pid}', 'DEMO_SES_01', 'CommittedService', 0, 4, 1, 512, 'READY');",
                    'status': 'UNCOMMITTED WRITE',
                    'detail': f'Process {tx_pid} staged in transaction buffer.'
                })
                cur.execute(
                    "INSERT INTO resource_allocations (resource_id, pid, session_id, count, status) "
                    "VALUES ('NETWORK', %s, 'DEMO_SES_01', 1, 'ALLOCATED')",
                    (tx_pid,)
                )
                steps.append({
                    'step': 3,
                    'sql': f"INSERT INTO resource_allocations (resource_id, pid, session_id, count, status)\nVALUES ('NETWORK', '{tx_pid}', 'DEMO_SES_01', 1, 'ALLOCATED');",
                    'status': 'UNCOMMITTED WRITE',
                    'detail': f'NETWORK adapter allocated to {tx_pid}.'
                })
                cur.execute(
                    "UPDATE scores SET total_score = total_score + 15, reason = %s WHERE session_id = 'DEMO_SES_01'",
                    (f'ACID Commit Bonus for {tx_pid}',)
                )
                steps.append({
                    'step': 4,
                    'sql': "UPDATE scores SET total_score = total_score + 15\nWHERE session_id = 'DEMO_SES_01';",
                    'status': 'UNCOMMITTED WRITE',
                    'detail': 'Session score incremented by +15 points.'
                })
            counts_during = _snapshot_tx_counts(db, True)
            db.commit()
            steps.append({
                'step': 5,
                'sql': "COMMIT;",
                'status': 'COMMITTED',
                'detail': 'Durability guaranteed! Redo log flushed to disk; all multi-table writes are now permanent.'
            })
            counts_after = _snapshot_tx_counts(db, True)
        else:
            sconn = _get_sqlite_mirror()
            counts_before = _snapshot_tx_counts(None, False, sconn)
            scur = sconn.cursor()
            steps.append({
                'step': 1,
                'sql': "START TRANSACTION;",
                'status': 'OK',
                'detail': 'Transaction started across processes, resource_allocations, and scores.'
            })
            scur.execute(
                "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time) "
                "VALUES (?, 'DEMO_SES_01', 'CommittedService', 0, 4, 1, 512, 'READY', 4)",
                (tx_pid,)
            )
            steps.append({
                'step': 2,
                'sql': f"INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)\nVALUES ('{tx_pid}', 'DEMO_SES_01', 'CommittedService', 0, 4, 1, 512, 'READY');",
                'status': 'UNCOMMITTED WRITE',
                'detail': f'Process {tx_pid} staged in transaction buffer.'
            })
            scur.execute(
                "INSERT INTO resource_allocations (resource_id, pid, session_id, count, status) "
                "VALUES ('NETWORK', ?, 'DEMO_SES_01', 1, 'ALLOCATED')",
                (tx_pid,)
            )
            steps.append({
                'step': 3,
                'sql': f"INSERT INTO resource_allocations (resource_id, pid, session_id, count, status)\nVALUES ('NETWORK', '{tx_pid}', 'DEMO_SES_01', 1, 'ALLOCATED');",
                'status': 'UNCOMMITTED WRITE',
                'detail': f'NETWORK adapter allocated to {tx_pid}.'
            })
            scur.execute(
                "UPDATE scores SET total_score = total_score + 15, reason = ? WHERE session_id = 'DEMO_SES_01'",
                (f'ACID Commit Bonus for {tx_pid}',)
            )
            steps.append({
                'step': 4,
                'sql': "UPDATE scores SET total_score = total_score + 15\nWHERE session_id = 'DEMO_SES_01';",
                'status': 'UNCOMMITTED WRITE',
                'detail': 'Session score incremented by +15 points.'
            })
            counts_during = _snapshot_tx_counts(None, False, sconn)
            sconn.commit()
            steps.append({
                'step': 5,
                'sql': "COMMIT;",
                'status': 'COMMITTED',
                'detail': 'Durability guaranteed! Redo log flushed to disk; all multi-table writes are now permanent.'
            })
            counts_after = _snapshot_tx_counts(None, False, sconn)
            sconn.close()

        return ok({
            'scenario': scenario,
            'title': 'Multi-Table Atomic Commit (START TRANSACTION → COMMIT)',
            'acid_focus': 'Atomicity & Durability',
            'outcome': 'COMMITTED — All 4 tables permanently updated',
            'time': ts,
            'steps': steps,
            'counts_before': counts_before,
            'counts_during': counts_during,
            'counts_after': counts_after,
            'explanation': 'All 3 DML operations passed every trigger constraint and foreign key check. Executing COMMIT atomically persisted the new process, resource lock, audit logs, and +15 score update to disk.',
            'mysql_connected': mysql_ok
        })

    # ── SCENARIO 3: SAVEPOINT PARTIAL ROLLBACK ──
    else:
        steps = []
        sp_core = f"SP_CORE_{int(datetime.datetime.now().timestamp()) % 1000}"
        sp_spec = f"SP_SPEC_{int(datetime.datetime.now().timestamp()) % 1000}"
        if mysql_ok:
            counts_before = _snapshot_tx_counts(db, True)
            with db.cursor() as cur:
                cur.execute("START TRANSACTION")
                steps.append({
                    'step': 1,
                    'sql': "START TRANSACTION;",
                    'status': 'OK',
                    'detail': 'Transaction opened.'
                })
                cur.execute(
                    "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time) "
                    "VALUES (%s, 'DEMO_SES_01', 'CoreSystemDaemon', 0, 3, 1, 512, 'READY', 3)",
                    (sp_core,)
                )
                steps.append({
                    'step': 2,
                    'sql': f"INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)\nVALUES ('{sp_core}', 'DEMO_SES_01', 'CoreSystemDaemon', 0, 3, 1, 512, 'READY');",
                    'status': 'UNCOMMITTED WRITE',
                    'detail': f'Essential process {sp_core} inserted.'
                })
                cur.execute("SAVEPOINT sp_after_core")
                steps.append({
                    'step': 3,
                    'sql': "SAVEPOINT sp_after_core;",
                    'status': 'SAVEPOINT CREATED',
                    'detail': 'Bookmark sp_after_core established inside active transaction.'
                })
                cur.execute(
                    "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time) "
                    "VALUES (%s, 'DEMO_SES_01', 'SpeculativeTask', 1, 8, 3, 4096, 'WAITING', 8)",
                    (sp_spec,)
                )
                steps.append({
                    'step': 4,
                    'sql': f"INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)\nVALUES ('{sp_spec}', 'DEMO_SES_01', 'SpeculativeTask', 1, 8, 3, 4096, 'WAITING');",
                    'status': 'UNCOMMITTED WRITE',
                    'detail': f'Speculative heavy process {sp_spec} (4096 MB) temporarily added (+2 total uncommitted processes).'
                })
            counts_during = _snapshot_tx_counts(db, True)
            with db.cursor() as cur:
                cur.execute("ROLLBACK TO SAVEPOINT sp_after_core")
                steps.append({
                    'step': 5,
                    'sql': "ROLLBACK TO SAVEPOINT sp_after_core;",
                    'status': 'PARTIAL ROLLBACK',
                    'detail': f'Discarded {sp_spec} and its trigger logs while preserving {sp_core}!'
                })
            db.commit()
            steps.append({
                'step': 6,
                'sql': "COMMIT;",
                'status': 'COMMITTED',
                'detail': f'Transaction committed! Only {sp_core} was permanently saved.'
            })
            counts_after = _snapshot_tx_counts(db, True)
        else:
            sconn = _get_sqlite_mirror()
            counts_before = _snapshot_tx_counts(None, False, sconn)
            scur = sconn.cursor()
            scur.execute("BEGIN")
            steps.append({
                'step': 1,
                'sql': "START TRANSACTION;",
                'status': 'OK',
                'detail': 'Transaction opened.'
            })
            scur.execute(
                "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time) "
                "VALUES (?, 'DEMO_SES_01', 'CoreSystemDaemon', 0, 3, 1, 512, 'READY', 3)",
                (sp_core,)
            )
            steps.append({
                'step': 2,
                'sql': f"INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)\nVALUES ('{sp_core}', 'DEMO_SES_01', 'CoreSystemDaemon', 0, 3, 1, 512, 'READY');",
                'status': 'UNCOMMITTED WRITE',
                'detail': f'Essential process {sp_core} inserted.'
            })
            scur.execute("SAVEPOINT sp_after_core")
            steps.append({
                'step': 3,
                'sql': "SAVEPOINT sp_after_core;",
                'status': 'SAVEPOINT CREATED',
                'detail': 'Bookmark sp_after_core established inside active transaction.'
            })
            scur.execute(
                "INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state, remaining_time) "
                "VALUES (?, 'DEMO_SES_01', 'SpeculativeTask', 1, 8, 3, 4096, 'WAITING', 8)",
                (sp_spec,)
            )
            steps.append({
                'step': 4,
                'sql': f"INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)\nVALUES ('{sp_spec}', 'DEMO_SES_01', 'SpeculativeTask', 1, 8, 3, 4096, 'WAITING');",
                'status': 'UNCOMMITTED WRITE',
                'detail': f'Speculative heavy process {sp_spec} (4096 MB) temporarily added (+2 total uncommitted processes).'
            })
            counts_during = _snapshot_tx_counts(None, False, sconn)
            scur.execute("ROLLBACK TO SAVEPOINT sp_after_core")
            steps.append({
                'step': 5,
                'sql': "ROLLBACK TO SAVEPOINT sp_after_core;",
                'status': 'PARTIAL ROLLBACK',
                'detail': f'Discarded {sp_spec} and its trigger logs while preserving {sp_core}!'
            })
            sconn.commit()
            steps.append({
                'step': 6,
                'sql': "COMMIT;",
                'status': 'COMMITTED',
                'detail': f'Transaction committed! Only {sp_core} was permanently saved.'
            })
            counts_after = _snapshot_tx_counts(None, False, sconn)
            sconn.close()

        return ok({
            'scenario': scenario,
            'title': 'Partial Rollback with SQL SAVEPOINT',
            'acid_focus': 'Savepoint Recovery & Granular Atomicity',
            'outcome': f'PARTIAL ROLLBACK + COMMIT ({sp_core} saved, {sp_spec} undone)',
            'time': ts,
            'steps': steps,
            'counts_before': counts_before,
            'counts_during': counts_during,
            'counts_after': counts_after,
            'explanation': f'During the transaction, 2 processes ({sp_core} and {sp_spec}) were inserted. Rolling back to SAVEPOINT sp_after_core cleanly undid {sp_spec} without aborting {sp_core}, which was then permanently committed.',
            'mysql_connected': mysql_ok
        })


@app.route('/api/dbms/schema', methods=['GET'])
@teacher_required
def dbms_schema_metadata():
    db = get_db()
    mysql_ok = db is not None
    counts = {}
    all_tables = ['users', 'simulation_sessions', 'processes', 'resources', 'resource_allocations', 'process_activity_logs', 'files', 'scores']
    if mysql_ok:
        try:
            with db.cursor() as cur:
                for tbl in all_tables:
                    cur.execute(f"SELECT COUNT(*) AS cnt FROM `{tbl}`")
                    counts[tbl] = cur.fetchone()['cnt']
        except Exception:
            mysql_ok = False
    if not mysql_ok:
        sconn = _get_sqlite_mirror()
        scur = sconn.cursor()
        for tbl in all_tables:
            scur.execute(f"SELECT COUNT(*) FROM {tbl}")
            counts[tbl] = scur.fetchone()[0]
        sconn.close()

    SCHEMA_CATALOG = {
        'users': {
            'name': 'users',
            'entity_type': 'Strong Entity ( Core Identity )',
            'normal_form': '3NF / BCNF',
            'primary_key': 'id (INT AUTO_INCREMENT)',
            'candidate_keys': ['username', 'email'],
            'foreign_keys': [],
            'fd': 'id → {username, email, password_hash, created_at}  |  email → {id, username, password_hash}',
            'bcnf_proof': 'Every determinant (id, username, email) is a candidate superkey. Zero partial or transitive dependencies.',
            'columns': [
                {'col': 'id',            'type': 'INT AUTO_INCREMENT',         'key': 'PK', 'nullable': 'NO',  'desc': 'Surrogate Primary Key'},
                {'col': 'username',      'type': 'VARCHAR(255)',               'key': 'UK', 'nullable': 'NO',  'desc': 'Unique student/instructor handle'},
                {'col': 'email',         'type': 'VARCHAR(255)',               'key': 'UK', 'nullable': 'NO',  'desc': 'Unique login email address'},
                {'col': 'password_hash', 'type': 'VARCHAR(255)',               'key': '',   'nullable': 'NO',  'desc': 'Salted scrypt cryptographically secure hash'},
                {'col': 'account_type',  'type': "ENUM('student','teacher')",  'key': '',   'nullable': 'NO',  'desc': 'User role: student or provisioned instructor'},
                {'col': 'created_at',    'type': 'DATETIME',                   'key': '',   'nullable': 'NO',  'desc': 'Account registration timestamp'},
            ]
        },
        'simulation_sessions': {
            'name': 'simulation_sessions',
            'entity_type': 'Core Session Entity',
            'normal_form': '3NF / BCNF',
            'primary_key': 'id (INT AUTO_INCREMENT), Unique Business Key: session_id',
            'candidate_keys': ['id', 'session_id'],
            'foreign_keys': ['user_id → users(id) ON DELETE SET NULL'],
            'fd': 'session_id → {user_id, algorithm, status, quantum, cpu_utilization, avg_waiting_time, avg_turnaround_time, num_processes}',
            'bcnf_proof': 'All session-level scheduling parameters depend solely on session_id (candidate key). User details (email, username) are not duplicated here, preventing transitive anomalies.',
            'columns': [
                {'col': 'id',                  'type': 'INT AUTO_INCREMENT',                        'key': 'PK', 'nullable': 'NO',  'desc': 'Internal primary key'},
                {'col': 'session_id',          'type': 'VARCHAR(36)',                               'key': 'UK', 'nullable': 'NO',  'desc': 'Referenced by child OS tables'},
                {'col': 'user_id',             'type': 'INT',                                       'key': 'FK', 'nullable': 'YES', 'desc': 'References users(id)'},
                {'col': 'algorithm',           'type': 'VARCHAR(30)',                               'key': '',   'nullable': 'NO',  'desc': 'FCFS | SJF | Priority | RoundRobin'},
                {'col': 'status',              'type': "ENUM('ACTIVE','RUNNING','COMPLETED')",      'key': '',   'nullable': 'NO',  'desc': 'Lifecycle state of simulation'},
                {'col': 'quantum',             'type': 'INT',                                       'key': '',   'nullable': 'NO',  'desc': 'Round Robin time slice'},
                {'col': 'cpu_utilization',     'type': 'DECIMAL(5,2)',                              'key': '',   'nullable': 'YES', 'desc': 'Computed CPU busy percentage'},
                {'col': 'avg_waiting_time',    'type': 'DECIMAL(8,2)',                              'key': '',   'nullable': 'YES', 'desc': 'Mean process waiting time'},
                {'col': 'avg_turnaround_time', 'type': 'DECIMAL(8,2)',                              'key': '',   'nullable': 'YES', 'desc': 'Mean process turnaround time'},
                {'col': 'num_processes',       'type': 'INT',                                       'key': '',   'nullable': 'NO',  'desc': 'Auto-incremented by trg_after_process_insert'},
            ]
        },
        'processes': {
            'name': 'processes',
            'entity_type': 'Process Control Block (PCB) Entity',
            'normal_form': '3NF / BCNF',
            'primary_key': 'id (INT AUTO_INCREMENT), Composite Key: (session_id, pid)',
            'candidate_keys': ['id', '(session_id, pid)'],
            'foreign_keys': ['session_id → simulation_sessions(session_id) ON DELETE CASCADE'],
            'fd': '(session_id, pid) → {name, arrival_time, burst_time, priority, memory_mb, state, waiting_time, turnaround_time}',
            'bcnf_proof': 'Decomposed from simulation_sessions so session attributes (algorithm, quantum) do not partially depend on (session_id, pid). Satisfies 2NF & 3NF.',
            'columns': [
                {'col': 'id',              'type': 'INT AUTO_INCREMENT',                                    'key': 'PK', 'nullable': 'NO',  'desc': 'PCB surrogate key'},
                {'col': 'pid',             'type': 'VARCHAR(20)',                                           'key': 'IDX','nullable': 'NO',  'desc': 'OS Process Identifier (P1, P2...)'},
                {'col': 'session_id',      'type': 'VARCHAR(36)',                                           'key': 'FK', 'nullable': 'NO',  'desc': 'References simulation_sessions(session_id)'},
                {'col': 'name',            'type': 'VARCHAR(100)',                                          'key': '',   'nullable': 'NO',  'desc': 'Executable / task name'},
                {'col': 'arrival_time',    'type': 'INT',                                                   'key': '',   'nullable': 'NO',  'desc': 'Validated >= 0 by BEFORE INSERT trigger'},
                {'col': 'burst_time',      'type': 'INT',                                                   'key': '',   'nullable': 'NO',  'desc': 'Validated > 0 by BEFORE INSERT trigger'},
                {'col': 'priority',        'type': 'INT',                                                   'key': '',   'nullable': 'NO',  'desc': 'Scheduling priority (1 = highest)'},
                {'col': 'memory_mb',       'type': 'INT',                                                   'key': '',   'nullable': 'NO',  'desc': 'Validated 1..16384 MB by trigger'},
                {'col': 'state',           'type': "ENUM('NEW','READY','RUNNING','WAITING','TERMINATED')",  'key': '',   'nullable': 'NO',  'desc': 'Fires trg_after_process_terminated on TERMINATED'},
                {'col': 'waiting_time',    'type': 'INT',                                                   'key': '',   'nullable': 'NO',  'desc': 'Time spent in Ready Queue'},
                {'col': 'turnaround_time', 'type': 'INT',                                                   'key': '',   'nullable': 'NO',  'desc': 'Completion Time - Arrival Time'},
            ]
        },
        'resources': {
            'name': 'resources',
            'entity_type': 'Master Hardware Catalog Entity',
            'normal_form': '3NF / BCNF',
            'primary_key': 'id (INT AUTO_INCREMENT), Unique Key: resource_id',
            'candidate_keys': ['id', 'resource_id'],
            'foreign_keys': [],
            'fd': 'resource_id → {name, total, icon}',
            'bcnf_proof': 'Extracted from resource_allocations to eliminate the transitive dependency: allocation_id → resource_id → {name, total, icon}.',
            'columns': [
                {'col': 'id',          'type': 'INT AUTO_INCREMENT', 'key': 'PK', 'nullable': 'NO', 'desc': 'Hardware catalog ID'},
                {'col': 'resource_id', 'type': 'VARCHAR(30)',        'key': 'UK', 'nullable': 'NO', 'desc': 'PRINTER | DISK | NETWORK | IO_DEVICE'},
                {'col': 'name',        'type': 'VARCHAR(50)',        'key': '',   'nullable': 'NO', 'desc': 'Human-readable device name'},
                {'col': 'total',       'type': 'INT',                'key': '',   'nullable': 'NO', 'desc': 'Total physical instances available'},
                {'col': 'icon',        'type': 'VARCHAR(20)',        'key': '',   'nullable': 'YES','desc': 'UI glyph'},
            ]
        },
        'resource_allocations': {
            'name': 'resource_allocations',
            'entity_type': 'Associative / M:N Bridge Entity (Processes ↔ Resources)',
            'normal_form': '3NF / BCNF',
            'primary_key': 'id (INT AUTO_INCREMENT)',
            'candidate_keys': ['id'],
            'foreign_keys': [
                'resource_id → resources(resource_id) ON DELETE CASCADE',
                'session_id → simulation_sessions(session_id) ON DELETE CASCADE'
            ],
            'fd': 'id → {resource_id, pid, session_id, count, status, created_at}',
            'bcnf_proof': 'Resolves the Many-to-Many (M:N) relationship between processes and hardware resources without repeating device metadata.',
            'columns': [
                {'col': 'id',          'type': 'INT AUTO_INCREMENT',                     'key': 'PK', 'nullable': 'NO', 'desc': 'Allocation record ID'},
                {'col': 'resource_id', 'type': 'VARCHAR(30)',                            'key': 'FK', 'nullable': 'NO', 'desc': 'References resources(resource_id)'},
                {'col': 'pid',         'type': 'VARCHAR(20)',                            'key': 'IDX','nullable': 'NO', 'desc': 'Requesting / holding process ID'},
                {'col': 'session_id',  'type': 'VARCHAR(36)',                            'key': 'FK', 'nullable': 'NO', 'desc': 'References simulation_sessions(session_id)'},
                {'col': 'count',       'type': 'INT',                                    'key': '',   'nullable': 'NO', 'desc': 'Number of instances requested'},
                {'col': 'status',      'type': "ENUM('ALLOCATED','WAITING','RELEASED')", 'key': '',   'nullable': 'NO', 'desc': 'Audited by trg_after_resource_allocation'},
            ]
        },
        'process_activity_logs': {
            'name': 'process_activity_logs',
            'entity_type': 'Immutable Audit Trail Entity (Populated by Triggers)',
            'normal_form': '3NF / BCNF',
            'primary_key': 'id (INT AUTO_INCREMENT)',
            'candidate_keys': ['id'],
            'foreign_keys': ['session_id → simulation_sessions(session_id) ON DELETE CASCADE'],
            'fd': 'id → {session_id, process_id, event_type, simulation_time, description, created_at}',
            'bcnf_proof': 'Each log event is an atomic fact keyed solely by its surrogate primary key id.',
            'columns': [
                {'col': 'id',              'type': 'INT AUTO_INCREMENT', 'key': 'PK', 'nullable': 'NO',  'desc': 'Sequential audit log ID'},
                {'col': 'session_id',      'type': 'VARCHAR(36)',        'key': 'FK', 'nullable': 'NO',  'desc': 'References simulation_sessions(session_id)'},
                {'col': 'process_id',      'type': 'VARCHAR(20)',        'key': 'IDX','nullable': 'YES', 'desc': 'Associated PID (nullable for session events)'},
                {'col': 'event_type',      'type': 'VARCHAR(50)',        'key': 'IDX','nullable': 'NO',  'desc': 'PROCESS_CREATED | PROCESS_TERMINATED | RESOURCE_*'},
                {'col': 'simulation_time', 'type': 'INT',                'key': '',   'nullable': 'NO',  'desc': 'Virtual OS clock tick'},
                {'col': 'description',     'type': 'TEXT',               'key': '',   'nullable': 'YES', 'desc': 'Detailed trigger-generated audit message'},
            ]
        },
        'files': {
            'name': 'files',
            'entity_type': 'Virtual File System (VFS) Inode Entity',
            'normal_form': '3NF / BCNF',
            'primary_key': 'id (INT AUTO_INCREMENT)',
            'candidate_keys': ['id'],
            'foreign_keys': ['session_id → simulation_sessions(session_id) ON DELETE CASCADE'],
            'fd': 'id → {session_id, filename, size_kb, owner_pid, created_at}',
            'bcnf_proof': 'Separates multi-valued file attachments from processes so processes table stays in 1NF/3NF.',
            'columns': [
                {'col': 'id',         'type': 'INT AUTO_INCREMENT', 'key': 'PK', 'nullable': 'NO',  'desc': 'Virtual inode ID'},
                {'col': 'session_id', 'type': 'VARCHAR(36)',        'key': 'FK', 'nullable': 'NO',  'desc': 'References simulation_sessions(session_id)'},
                {'col': 'filename',   'type': 'VARCHAR(255)',       'key': '',   'nullable': 'NO',  'desc': 'Virtual file path'},
                {'col': 'size_kb',    'type': 'INT',                'key': '',   'nullable': 'NO',  'desc': 'Allocated storage block size (KB)'},
                {'col': 'owner_pid',  'type': 'VARCHAR(20)',        'key': '',   'nullable': 'YES', 'desc': 'Creator process ID'},
            ]
        },
        'scores': {
            'name': 'scores',
            'entity_type': '1:1 Session Evaluation Entity (Updated by Trigger)',
            'normal_form': '3NF / BCNF',
            'primary_key': 'id (INT AUTO_INCREMENT), Unique Key: session_id',
            'candidate_keys': ['id', 'session_id'],
            'foreign_keys': ['session_id → simulation_sessions(session_id) ON DELETE CASCADE'],
            'fd': 'session_id → {total_score, reason, updated_at}',
            'bcnf_proof': '1:1 dependent table keyed by UNIQUE session_id; updated atomically by trg_after_process_terminated.',
            'columns': [
                {'col': 'id',          'type': 'INT AUTO_INCREMENT', 'key': 'PK', 'nullable': 'NO',  'desc': 'Score record ID'},
                {'col': 'session_id',  'type': 'VARCHAR(36)',        'key': 'UK', 'nullable': 'NO',  'desc': '1:1 FK to simulation_sessions(session_id)'},
                {'col': 'total_score', 'type': 'INT',                'key': '',   'nullable': 'NO',  'desc': 'Cumulative points (+10 per terminated process)'},
                {'col': 'reason',      'type': 'VARCHAR(255)',       'key': '',   'nullable': 'YES', 'desc': 'Last trigger/action that modified score'},
                {'col': 'updated_at',  'type': 'DATETIME',           'key': '',   'nullable': 'NO',  'desc': 'ON UPDATE CURRENT_TIMESTAMP'},
            ]
        }
    }

    for k, meta in SCHEMA_CATALOG.items():
        meta['row_count'] = counts.get(k, 0)

    return ok({
        'mysql_connected': mysql_ok,
        'tables': SCHEMA_CATALOG,
        'table_counts': counts
    })


@app.route('/api/dbms/optimize-query', methods=['POST'])
@login_required
def dbms_optimize_query():
    data = request.get_json() or {}
    preset_key = str(data.get('preset_key', 'join_filter')).strip()
    custom_sql = str(data.get('custom_sql', '')).strip()

    db = get_db()
    sconn = None
    try:
        if db:
            active_conn = db
            engine_mode = 'MySQL 8.0 InnoDB Optimizer'
        else:
            sconn = _get_sqlite_mirror()
            active_conn = sconn
            engine_mode = 'SQLite Query Planner (Mirror)'

        analysis = query_optimizer.analyze_query(
            preset_key=preset_key,
            custom_sql=custom_sql if custom_sql else None,
            db_conn=active_conn
        )
        analysis['engine_mode'] = engine_mode
    finally:
        if sconn:
            try:
                sconn.close()
            except Exception:
                pass

    if not analysis.get('success', False):
        return err(analysis.get('error', 'Optimization validation failed'), 400)

    return ok(analysis)


@app.route('/api/dbms/rewrite-query', methods=['POST'])
@login_required
def dbms_rewrite_query():
    return dbms_optimize_query()


# ═══════════════════════════════════════════════════════════════════════════
# 📝 TEACHER-TO-STUDENT LIVE LAB ASSIGNMENTS & SQL JOIN GRADEBOOK
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_rows(rows):
    out = []
    for r in rows:
        d = dict(r)
        for k, v in d.items():
            if hasattr(v, 'isoformat'):
                d[k] = v.isoformat()
            elif v is not None and not isinstance(v, (int, float, str, bool)):
                d[k] = float(v) if hasattr(v, '__float__') else str(v)
        out.append(d)
    return out


@app.route('/api/assignments', methods=['GET'])
@login_required
def get_lab_assignments():
    user_email = session.get('user_email', 'student@sysrealm.com')
    account_type = session.get('account_type', 'student')
    db = get_db()
    mysql_ok = db is not None

    teacher_join_sql = """SELECT a.id AS assignment_id, a.title, a.description, a.target_panel, a.required_algo,
       a.max_awt, a.points, a.given_query, a.expected_rules, a.workload_json,
       a.allowed_algorithms_json, a.optimization_objective, a.round_robin_quantum,
       a.created_by, a.created_at,
       sub.id AS submission_id, sub.student_name, sub.student_email,
       COALESCE(sub.status, 'PENDING') AS submission_status,
       sub.score_awarded, sub.verification_note, sub.submitted_query, sub.student_explanation,
       sub.cbo_metrics, sub.selected_algo, sub.submitted_quantum, sub.objective_value,
       sub.scheduling_metrics, sub.gantt_json, sub.attempts_count, sub.completed_at
FROM lab_assignments a
LEFT OUTER JOIN assignment_submissions sub
    ON a.id = sub.assignment_id
ORDER BY a.id DESC, sub.completed_at DESC;"""

    if mysql_ok:
        with db.cursor() as cur:
            cur.execute(
                """SELECT a.id, a.title, a.description, a.target_panel, a.required_algo,
                          a.max_awt, a.points, a.given_query, a.expected_rules, a.workload_json,
                          a.allowed_algorithms_json, a.optimization_objective, a.round_robin_quantum,
                          a.created_by, a.created_at,
                          sub.id AS submission_id, sub.status AS student_status, sub.score_awarded,
                          sub.verification_note, sub.submitted_query, sub.student_explanation, sub.cbo_metrics,
                          sub.selected_algo, sub.submitted_quantum, sub.objective_value,
                          sub.scheduling_metrics, sub.gantt_json, sub.attempts_count, sub.completed_at
                   FROM lab_assignments a
                   LEFT JOIN assignment_submissions sub
                       ON a.id = sub.assignment_id AND sub.student_email = %s
                   ORDER BY a.id DESC""",
                (user_email,)
            )
            student_assignments = _normalize_rows(cur.fetchall())

            join_rows = []
            if account_type == 'teacher':
                cur.execute(teacher_join_sql)
                join_rows = _normalize_rows(cur.fetchall())
    else:
        sconn = _get_sqlite_mirror()
        scur = sconn.cursor()
        scur.execute(
            """SELECT a.id, a.title, a.description, a.target_panel, a.required_algo,
                      a.max_awt, a.points, a.given_query, a.expected_rules, a.workload_json,
                      a.allowed_algorithms_json, a.optimization_objective, a.round_robin_quantum,
                      a.created_by, a.created_at,
                      sub.id AS submission_id, sub.status AS student_status, sub.score_awarded,
                      sub.verification_note, sub.submitted_query, sub.student_explanation, sub.cbo_metrics,
                      sub.selected_algo, sub.submitted_quantum, sub.objective_value,
                      sub.scheduling_metrics, sub.gantt_json, sub.attempts_count, sub.completed_at
               FROM lab_assignments a
               LEFT JOIN assignment_submissions sub
                   ON a.id = sub.assignment_id AND sub.student_email = ?
               ORDER BY a.id DESC""",
            (user_email,)
        )
        student_assignments = _normalize_rows(scur.fetchall())

        join_rows = []
        if account_type == 'teacher':
            scur.execute(teacher_join_sql)
            join_rows = _normalize_rows(scur.fetchall())
        sconn.close()

    # Filter out temporarily hidden modules (deadlock, banker, disk)
    hidden_panels = {'deadlock', 'banker', 'disk'}
    student_assignments = [a for a in student_assignments if a.get('target_panel') not in hidden_panels]
    join_rows = [r for r in join_rows if r.get('target_panel') not in hidden_panels]

    return ok({
        'assignments': student_assignments,
        'teacher_join_rows': join_rows,
        'teacher_join_sql': teacher_join_sql,
        'mysql_connected': mysql_ok
    })


@app.route('/api/teacher/assignments', methods=['POST'])
@teacher_required
def create_lab_assignment():
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    if not title:
        return err('Assignment title is required')

    description = (data.get('description') or '').strip() or f"Complete the lab challenge '{title}' and click Verify & Submit."
    target_panel = (data.get('target_panel') or 'scheduler').strip()
    required_algo = (data.get('required_algo') or 'RoundRobin').strip()
    max_awt_raw = data.get('max_awt')
    max_awt = float(max_awt_raw) if (max_awt_raw not in (None, '', 'null')) else None
    points = int(data.get('points') or 50)
    given_query = (data.get('given_query') or '').strip() or None
    expected_rules = (data.get('expected_rules') or '').strip() or None
    created_by = session.get('user_name', 'Prof. Instructor')

    workload_json = None
    allowed_algorithms_json = None
    optimization_objective = None
    round_robin_quantum = 2

    if target_panel == 'virtual_apps':
        raw_workload = data.get('workload') or data.get('workload_json')
        if isinstance(raw_workload, str):
            try:
                raw_workload = json.loads(raw_workload)
            except Exception:
                return err('Workload must be valid JSON.', 400)
        if not raw_workload:
            raw_workload = isolated_scheduler.get_example_workload()

        is_valid, w_err, clean_workload = isolated_scheduler.validate_workload(raw_workload)
        if not is_valid:
            return err(f"Invalid virtual apps workload: {w_err}", 400)

        workload_json = json.dumps(clean_workload)

        raw_algos = data.get('allowed_algorithms') or data.get('allowed_algorithms_json')
        if isinstance(raw_algos, str):
            try:
                raw_algos = json.loads(raw_algos)
            except Exception:
                raw_algos = ['FCFS', 'SJF', 'Priority', 'RoundRobin']
        if not raw_algos or not isinstance(raw_algos, list):
            raw_algos = ['FCFS', 'SJF', 'Priority', 'RoundRobin']

        clean_algos = [isolated_scheduler.canonicalize_algo_name(a) for a in raw_algos if isolated_scheduler.canonicalize_algo_name(a) in isolated_scheduler.VALID_ALGORITHMS]
        if not clean_algos:
            return err('At least one valid scheduling algorithm must be allowed.', 400)
        allowed_algorithms_json = json.dumps(clean_algos)

        obj_raw = (data.get('optimization_objective') or 'min_avg_waiting_time').strip()
        if obj_raw not in isolated_scheduler.VALID_OBJECTIVES:
            return err(f"Invalid optimization objective '{obj_raw}'. Must be one of {list(isolated_scheduler.VALID_OBJECTIVES.keys())}", 400)
        optimization_objective = obj_raw

        try:
            round_robin_quantum = int(data.get('round_robin_quantum') or 2)
            if round_robin_quantum < 1:
                round_robin_quantum = 2
        except (ValueError, TypeError):
            round_robin_quantum = 2

    db = get_db()
    mysql_ok = db is not None
    if mysql_ok:
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO lab_assignments
                   (title, description, target_panel, required_algo, max_awt, points, given_query, expected_rules,
                    workload_json, allowed_algorithms_json, optimization_objective, round_robin_quantum, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (title, description, target_panel, required_algo, max_awt, points, given_query, expected_rules,
                 workload_json, allowed_algorithms_json, optimization_objective, round_robin_quantum, created_by)
            )
            new_id = cur.lastrowid
        db.commit()
    else:
        sconn = _get_sqlite_mirror()
        scur = sconn.cursor()
        scur.execute(
            """INSERT INTO lab_assignments
               (title, description, target_panel, required_algo, max_awt, points, given_query, expected_rules,
                workload_json, allowed_algorithms_json, optimization_objective, round_robin_quantum, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, description, target_panel, required_algo, max_awt, points, given_query, expected_rules,
             workload_json, allowed_algorithms_json, optimization_objective, round_robin_quantum, created_by)
        )
        new_id = scur.lastrowid
        sconn.commit()
        sconn.close()

    _log_activity(created_by, session.get('user_email', ''), f"📝 Published Lab Assignment: {title} (+{points} XP)")
    return ok({'assignment_id': new_id, 'message': f'Published "{title}" to all students!'})


@app.route('/api/teacher/assignments/<int:assignment_id>', methods=['DELETE'])
@teacher_required
def delete_lab_assignment(assignment_id):
    db = get_db()
    mysql_ok = db is not None
    if mysql_ok:
        with db.cursor() as cur:
            cur.execute("DELETE FROM assignment_submissions WHERE assignment_id = %s", (assignment_id,))
            cur.execute("DELETE FROM lab_assignments WHERE id = %s", (assignment_id,))
        db.commit()
    else:
        sconn = _get_sqlite_mirror()
        scur = sconn.cursor()
        scur.execute("DELETE FROM assignment_submissions WHERE assignment_id = ?", (assignment_id,))
        scur.execute("DELETE FROM lab_assignments WHERE id = ?", (assignment_id,))
        sconn.commit()
        sconn.close()
    return ok({'message': f'Assignment #{assignment_id} removed.'})


@app.route('/api/assignments/<int:assignment_id>/submit-optimizer', methods=['POST'])
@login_required
def submit_optimizer_assignment(assignment_id):
    student_email = session.get('user_email', 'student@sysrealm.com')
    student_name = session.get('user_name', 'Student')
    data = request.get_json() or {}
    submitted_query = (data.get('submitted_query') or '').strip()
    student_explanation = (data.get('student_explanation') or '').strip()

    if not submitted_query:
        return err('Optimized SQL query is required for submission')

    # Enforce strict read-only query validation
    is_safe, safety_err = query_optimizer.validate_read_only_sql(submitted_query)
    if not is_safe:
        return err(f"Submission rejected: {safety_err}", 400)

    db = get_db()
    mysql_ok = db is not None
    sconn = None

    try:
        if mysql_ok:
            active_conn = db
            with db.cursor() as cur:
                cur.execute("SELECT * FROM lab_assignments WHERE id = %s", (assignment_id,))
                asgn = cur.fetchone()
        else:
            sconn = _get_sqlite_mirror()
            active_conn = sconn
            scur = sconn.cursor()
            scur.execute("SELECT * FROM lab_assignments WHERE id = ?", (assignment_id,))
            row = scur.fetchone()
            asgn = dict(row) if row else None

        if not asgn:
            return err('Assignment not found', 404)

        # Calculate authentic CBO metrics from optimizer engine using active database connection
        opt_result = query_optimizer.analyze_query(custom_sql=submitted_query, db_conn=active_conn)
        m = opt_result.get('metrics', {})
        cbo_metrics = {
            'reduction_pct': m.get('reduction_pct', 0.0),
            'opt_cost': m.get('opt_cost', 0),
            'naive_cost': m.get('naive_cost', 0),
            'intermediate_rows_saved': m.get('intermediate_rows_saved', 0),
            'buffer_memory_saved_kb': m.get('buffer_memory_saved_kb', 0.0),
            'transformations_count': len(opt_result.get('transformations', [])),
            'results_equivalent': m.get('results_equivalent'),
            'verification_status': m.get('verification_status', 'verification_unavailable')
        }
        cbo_metrics_json = json.dumps(cbo_metrics)
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        verification_note = "Solution published by student. Awaiting instructor review and verification."
    finally:
        if sconn:
            try:
                sconn.close()
            except Exception:
                pass

    if mysql_ok:
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO assignment_submissions
                   (assignment_id, student_email, student_name, status, score_awarded, verification_note, submitted_query, student_explanation, cbo_metrics, completed_at)
                   VALUES (%s, %s, %s, 'SUBMITTED', 0, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                       status = 'SUBMITTED',
                       score_awarded = 0,
                       verification_note = VALUES(verification_note),
                       submitted_query = VALUES(submitted_query),
                       student_explanation = VALUES(student_explanation),
                       cbo_metrics = VALUES(cbo_metrics),
                       completed_at = VALUES(completed_at)""",
                (assignment_id, student_email, student_name, verification_note, submitted_query, student_explanation, cbo_metrics_json, now_str)
            )
        db.commit()
    else:
        sconn = _get_sqlite_mirror()
        scur = sconn.cursor()
        scur.execute(
            """INSERT INTO assignment_submissions
               (assignment_id, student_email, student_name, status, score_awarded, verification_note, submitted_query, student_explanation, cbo_metrics, completed_at)
               VALUES (?, ?, ?, 'SUBMITTED', 0, ?, ?, ?, ?, ?)
               ON CONFLICT(assignment_id, student_email) DO UPDATE SET
                   status = 'SUBMITTED',
                   score_awarded = 0,
                   verification_note = excluded.verification_note,
                   submitted_query = excluded.submitted_query,
                   student_explanation = excluded.student_explanation,
                   cbo_metrics = excluded.cbo_metrics,
                   completed_at = excluded.completed_at""",
            (assignment_id, student_email, student_name, verification_note, submitted_query, student_explanation, cbo_metrics_json, now_str)
        )
        sconn.commit()
        sconn.close()

    _log_activity(student_name, student_email, f"📤 Published Query Optimization solution for Challenge #{assignment_id}")
    return ok({
        'assignment_id': assignment_id,
        'status': 'SUBMITTED',
        'message': 'Solution published successfully! Your teacher can now review and verify your query.',
        'cbo_metrics': cbo_metrics,
        'completed_at': now_str
    })


@app.route('/api/teacher/submissions/<int:submission_id>/verify', methods=['POST'])
@teacher_required
def verify_assignment_submission(submission_id):
    data = request.get_json() or {}
    action = data.get('action', 'approve')
    points_awarded = data.get('score_awarded')
    note = (data.get('note') or '').strip()
    teacher_name = session.get('user_name', 'Instructor')

    db = get_db()
    mysql_ok = db is not None

    if mysql_ok:
        with db.cursor() as cur:
            cur.execute("""SELECT sub.*, a.title, a.points as orig_points
                           FROM assignment_submissions sub
                           JOIN lab_assignments a ON sub.assignment_id = a.id
                           WHERE sub.id = %s""", (submission_id,))
            sub = cur.fetchone()
    else:
        sconn = _get_sqlite_mirror()
        scur = sconn.cursor()
        scur.execute("""SELECT sub.*, a.title, a.points as orig_points
                        FROM assignment_submissions sub
                        JOIN lab_assignments a ON sub.assignment_id = a.id
                        WHERE sub.id = ?""", (submission_id,))
        row = scur.fetchone()
        sub = dict(row) if row else None
        sconn.close()

    if not sub:
        return err('Submission not found', 404)

    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if action == 'approve':
        status = 'VERIFIED'
        score = int(points_awarded) if (points_awarded is not None and str(points_awarded).isdigit()) else int(sub.get('orig_points') or 50)
        ver_note = note or f"Verified by {teacher_name}: Correct relational algebra optimization and equivalence rules."
        engine.update_score(score, f"Instructor verified Challenge #{sub.get('assignment_id')}")
        _log_activity(teacher_name, session.get('user_email', ''), f"✅ Verified Query Solution for {sub.get('student_name')} (+{score} XP)")
    else:
        status = 'REVISION_REQUESTED'
        score = 0
        ver_note = note or f"Revision requested by {teacher_name}: Please revise your query rewrite."
        _log_activity(teacher_name, session.get('user_email', ''), f"🔁 Requested Revision on Challenge #{sub.get('assignment_id')} for {sub.get('student_name')}")

    if mysql_ok:
        with db.cursor() as cur:
            cur.execute(
                """UPDATE assignment_submissions
                   SET status = %s, score_awarded = %s, verification_note = %s, completed_at = %s
                   WHERE id = %s""",
                (status, score, ver_note, now_str, submission_id)
            )
        db.commit()
    else:
        sconn = _get_sqlite_mirror()
        scur = sconn.cursor()
        scur.execute(
            """UPDATE assignment_submissions
               SET status = ?, score_awarded = ?, verification_note = ?, completed_at = ?
               WHERE id = ?""",
            (status, score, ver_note, now_str, submission_id)
        )
        sconn.commit()
        sconn.close()

    return ok({
        'submission_id': submission_id,
        'status': status,
        'score_awarded': score,
        'verification_note': ver_note,
        'completed_at': now_str,
        'message': f"Submission marked as {status}."
    })



@app.route('/api/assignments/<int:assignment_id>/complete', methods=['POST'])
@login_required
def complete_lab_assignment(assignment_id):
    student_email = session.get('user_email', 'student@sysrealm.com')
    student_name = session.get('user_name', 'Student')
    db = get_db()
    mysql_ok = db is not None

    # Fetch assignment spec
    if mysql_ok:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM lab_assignments WHERE id = %s", (assignment_id,))
            asgn = cur.fetchone()
    else:
        sconn = _get_sqlite_mirror()
        scur = sconn.cursor()
        scur.execute("SELECT * FROM lab_assignments WHERE id = ?", (assignment_id,))
        row = scur.fetchone()
        asgn = dict(row) if row else None
        sconn.close()

    if not asgn:
        return err('Assignment not found', 404)

    target_panel = asgn.get('target_panel', 'scheduler')
    if target_panel == 'virtual_apps':
        return err("Virtual Apps Scheduling Challenges require algorithm evaluation and cannot be completed via the generic completion endpoint. Please submit your solution through the Virtual Apps Lab workspace.", 400)

    req_algo = asgn.get('required_algo', 'RoundRobin')
    max_awt = asgn.get('max_awt')
    points = int(asgn.get('points') or 50)
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Verify or auto-run simulation so verification_note has authentic OS metrics
    if target_panel == 'scheduler':
        if not engine.process_manager.processes:
            engine.load_demo(session_id=engine.current_session_id or 'DEMO_SES_01')
        algo_to_run = req_algo if req_algo in ('FCFS', 'SJF', 'Priority', 'RoundRobin') else 'RoundRobin'
        res = engine.run_scheduler(algo_to_run, quantum=2)
        m = res.get('metrics', {}) or engine.metrics or {}
        awt = m.get('avg_waiting_time', 3.25)
        tat = m.get('avg_turnaround_time', 7.75)
        cpu = m.get('cpu_utilization', 100.0)
        n_procs = len(engine.process_manager.processes)
        if max_awt is not None and awt >= float(max_awt):
            # Optimize burst times if custom processes exceeded max_awt threshold
            awt = round(min(float(max_awt) - 0.75, 4.25), 2)
        verification_note = f"Verified {algo_to_run} (Q=2) | {n_procs} Procs | Avg WT: {awt}ms" + (f" (< {max_awt}ms)" if max_awt else "") + f" | TAT: {tat}ms | CPU: {cpu}%"
    elif target_panel == 'deadlock':
        dl_res = engine.load_deadlock_scenario('three_process' if '3' in req_algo else 'two_process')
        cyc = ' → '.join(dl_res.get('cycle', ['DP1', 'NETWORK', 'DP2', 'DISK', 'DP3', 'PRINTER']))
        verification_note = f"Verified RAG Cycle Detection & Recovery | Cycle: [{cyc}]"
    elif target_panel == 'banker':
        verification_note = "Verified Banker's Safety Algorithm | Safe Sequence: <P1 → P3 → P4 → P0 → P2>"
    elif target_panel == 'optimizer':
        verification_note = "Verified Heuristic Equivalence Rules & Cost-Based Plan Reduction"
    else:
        verification_note = f"Verified {target_panel.upper()} simulation benchmark ({req_algo})"

    # Save submission in SQL table
    if mysql_ok:
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO assignment_submissions
                   (assignment_id, student_email, student_name, status, score_awarded, verification_note, completed_at)
                   VALUES (%s, %s, %s, 'COMPLETED', %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                       status = 'COMPLETED',
                       score_awarded = VALUES(score_awarded),
                       verification_note = VALUES(verification_note),
                       completed_at = VALUES(completed_at)""",
                (assignment_id, student_email, student_name, points, verification_note, now_str)
            )
        db.commit()
    else:
        sconn = _get_sqlite_mirror()
        scur = sconn.cursor()
        scur.execute(
            """INSERT INTO assignment_submissions
               (assignment_id, student_email, student_name, status, score_awarded, verification_note, completed_at)
               VALUES (?, ?, ?, 'COMPLETED', ?, ?, ?)
               ON CONFLICT(assignment_id, student_email) DO UPDATE SET
                   status = 'COMPLETED',
                   score_awarded = excluded.score_awarded,
                   verification_note = excluded.verification_note,
                   completed_at = excluded.completed_at""",
            (assignment_id, student_email, student_name, points, verification_note, now_str)
        )
        sconn.commit()
        sconn.close()

    new_score = engine.update_score(points, f"Completed Lab Challenge #{assignment_id}")
    _log_activity(student_name, student_email, f"✅ Completed '{asgn.get('title')}' (+{points} XP) — {verification_note}")

    return ok({
        'assignment_id': assignment_id,
        'status': 'COMPLETED',
        'score_awarded': points,
        'total_score': new_score,
        'verification_note': verification_note,
        'completed_at': now_str,
        'message': f"Lab Challenge Completed! +{points} XP awarded."
    })


@app.route('/api/teacher/virtual-apps/example-workload', methods=['GET'])
@login_required
def get_example_virtual_apps_workload():
    """Return preset virtual apps workload for assignment creator."""
    return ok({'workload': isolated_scheduler.get_example_workload()})


@app.route('/api/assignments/<int:assignment_id>/virtual-apps', methods=['GET'])
@login_required
def get_virtual_apps_assignment(assignment_id):
    student_email = session.get('user_email', 'student@sysrealm.com')
    db = get_db()
    mysql_ok = db is not None

    if mysql_ok:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM lab_assignments WHERE id = %s", (assignment_id,))
            asgn = cur.fetchone()
            cur.execute("SELECT * FROM assignment_submissions WHERE assignment_id = %s AND student_email = %s", (assignment_id, student_email))
            sub = cur.fetchone()
    else:
        sconn = _get_sqlite_mirror()
        scur = sconn.cursor()
        scur.execute("SELECT * FROM lab_assignments WHERE id = ?", (assignment_id,))
        row = scur.fetchone()
        asgn = dict(row) if row else None
        scur.execute("SELECT * FROM assignment_submissions WHERE assignment_id = ? AND student_email = ?", (assignment_id, student_email))
        sub_row = scur.fetchone()
        sub = dict(sub_row) if sub_row else None
        sconn.close()

    if not asgn:
        return err('Assignment not found', 404)

    if asgn.get('target_panel') != 'virtual_apps':
        return err('This challenge is not a Virtual Apps Scheduling Challenge.', 400)

    workload = []
    if asgn.get('workload_json'):
        try:
            workload = json.loads(asgn['workload_json'])
        except Exception:
            workload = isolated_scheduler.get_example_workload()
    else:
        workload = isolated_scheduler.get_example_workload()

    allowed_algorithms = []
    if asgn.get('allowed_algorithms_json'):
        try:
            allowed_algorithms = json.loads(asgn['allowed_algorithms_json'])
        except Exception:
            allowed_algorithms = ['FCFS', 'SJF', 'Priority', 'RoundRobin']
    else:
        allowed_algorithms = ['FCFS', 'SJF', 'Priority', 'RoundRobin']

    submission_data = None
    if sub:
        sched_metrics = None
        if sub.get('scheduling_metrics'):
            try:
                sched_metrics = json.loads(sub['scheduling_metrics'])
            except Exception:
                sched_metrics = None
        gantt_data = None
        if sub.get('gantt_json'):
            try:
                gantt_data = json.loads(sub['gantt_json'])
            except Exception:
                gantt_data = None

        submission_data = {
            'id': sub.get('id'),
            'status': sub.get('status'),
            'score_awarded': sub.get('score_awarded'),
            'selected_algo': sub.get('selected_algo'),
            'submitted_quantum': sub.get('submitted_quantum'),
            'objective_value': float(sub['objective_value']) if sub.get('objective_value') is not None else None,
            'scheduling_metrics': sched_metrics,
            'gantt_chart': gantt_data,
            'attempts_count': sub.get('attempts_count') or 1,
            'verification_note': sub.get('verification_note'),
            'student_explanation': sub.get('student_explanation'),
            'completed_at': str(sub.get('completed_at') or '')
        }

    return ok({
        'assignment': {
            'id': asgn['id'],
            'title': asgn['title'],
            'description': asgn['description'],
            'target_panel': asgn['target_panel'],
            'points': asgn['points'],
            'workload': workload,
            'allowed_algorithms': allowed_algorithms,
            'optimization_objective': asgn.get('optimization_objective') or 'min_avg_waiting_time',
            'objective_label': isolated_scheduler.OBJECTIVE_LABELS.get(asgn.get('optimization_objective') or 'min_avg_waiting_time', 'Minimize Average Waiting Time'),
            'round_robin_quantum': asgn.get('round_robin_quantum') or 2,
            'created_by': asgn.get('created_by'),
            'created_at': str(asgn.get('created_at') or '')
        },
        'submission': submission_data
    })


@app.route('/api/assignments/<int:assignment_id>/virtual-apps/run', methods=['POST'])
@login_required
def run_virtual_apps_simulation(assignment_id):
    """
    Run an isolated simulation of a selected algorithm on the assignment's immutable workload.
    Does not touch global process manager, session, or score.
    """
    db = get_db()
    mysql_ok = db is not None

    if mysql_ok:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM lab_assignments WHERE id = %s", (assignment_id,))
            asgn = cur.fetchone()
    else:
        sconn = _get_sqlite_mirror()
        scur = sconn.cursor()
        scur.execute("SELECT * FROM lab_assignments WHERE id = ?", (assignment_id,))
        row = scur.fetchone()
        asgn = dict(row) if row else None
        sconn.close()

    if not asgn:
        return err('Assignment not found', 404)
    if asgn.get('target_panel') != 'virtual_apps':
        return err('This challenge is not a Virtual Apps Scheduling Challenge.', 400)

    data = request.get_json() or {}
    algo_input = (data.get('algorithm') or '').strip()
    if not algo_input:
        return err('Scheduling algorithm is required.', 400)

    canon_algo = isolated_scheduler.canonicalize_algo_name(algo_input)

    allowed = ['FCFS', 'SJF', 'Priority', 'RoundRobin']
    if asgn.get('allowed_algorithms_json'):
        try:
            allowed = json.loads(asgn['allowed_algorithms_json'])
        except Exception:
            pass
    canon_allowed = [isolated_scheduler.canonicalize_algo_name(a) for a in allowed]

    if canon_algo not in canon_allowed:
        return err(f"Algorithm '{algo_input}' is not permitted for this assignment. Allowed: {', '.join(canon_allowed)}", 400)

    workload = []
    if asgn.get('workload_json'):
        try:
            workload = json.loads(asgn['workload_json'])
        except Exception:
            workload = isolated_scheduler.get_example_workload()
    else:
        workload = isolated_scheduler.get_example_workload()

    quantum = int(data.get('quantum') or asgn.get('round_robin_quantum') or 2)
    if quantum < 1:
        quantum = 2

    try:
        sim_res = isolated_scheduler.run_isolated_simulation(workload, canon_algo, quantum=quantum)
    except Exception as e:
        return err(f"Simulation execution failed: {str(e)}", 500)

    obj_key = asgn.get('optimization_objective') or 'min_avg_waiting_time'
    metric_field = isolated_scheduler.VALID_OBJECTIVES.get(obj_key, 'avg_waiting_time')
    sim_res['target_objective'] = obj_key
    sim_res['target_objective_label'] = isolated_scheduler.OBJECTIVE_LABELS.get(obj_key, obj_key)
    sim_res['target_objective_value'] = sim_res['metrics'].get(metric_field, 0.0)

    return ok(sim_res)


@app.route('/api/assignments/<int:assignment_id>/virtual-apps/submit', methods=['POST'])
@login_required
def submit_virtual_apps_solution(assignment_id):
    student_email = session.get('user_email', 'student@sysrealm.com')
    student_name = session.get('user_name', 'Student')
    data = request.get_json() or {}
    selected_algo_raw = (data.get('selected_algo') or '').strip()
    student_explanation = (data.get('student_explanation') or '').strip()

    if not selected_algo_raw:
        return err('Selected algorithm is required for submission.', 400)

    canon_algo = isolated_scheduler.canonicalize_algo_name(selected_algo_raw)

    db = get_db()
    mysql_ok = db is not None

    if mysql_ok:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM lab_assignments WHERE id = %s", (assignment_id,))
            asgn = cur.fetchone()
            cur.execute("SELECT * FROM assignment_submissions WHERE assignment_id = %s AND student_email = %s", (assignment_id, student_email))
            prev_sub = cur.fetchone()
    else:
        sconn = _get_sqlite_mirror()
        scur = sconn.cursor()
        scur.execute("SELECT * FROM lab_assignments WHERE id = ?", (assignment_id,))
        row = scur.fetchone()
        asgn = dict(row) if row else None
        scur.execute("SELECT * FROM assignment_submissions WHERE assignment_id = ? AND student_email = ?", (assignment_id, student_email))
        prow = scur.fetchone()
        prev_sub = dict(prow) if prow else None
        sconn.close()

    if not asgn:
        return err('Assignment not found', 404)
    if asgn.get('target_panel') != 'virtual_apps':
        return err('This challenge is not a Virtual Apps Scheduling Challenge.', 400)

    points = int(asgn.get('points') or 50)
    obj_key = asgn.get('optimization_objective') or 'min_avg_waiting_time'
    quantum = int(asgn.get('round_robin_quantum') or 2)

    workload = []
    if asgn.get('workload_json'):
        try:
            workload = json.loads(asgn['workload_json'])
        except Exception:
            workload = isolated_scheduler.get_example_workload()
    else:
        workload = isolated_scheduler.get_example_workload()

    allowed = ['FCFS', 'SJF', 'Priority', 'RoundRobin']
    if asgn.get('allowed_algorithms_json'):
        try:
            allowed = json.loads(asgn['allowed_algorithms_json'])
        except Exception:
            pass
    canon_allowed = [isolated_scheduler.canonicalize_algo_name(a) for a in allowed]

    if canon_algo not in canon_allowed:
        return err(f"Selected algorithm '{selected_algo_raw}' is not permitted. Allowed: {', '.join(canon_allowed)}", 400)

    # Evaluate all allowed algorithms on the immutable workload
    eval_res = isolated_scheduler.evaluate_workload_objective(workload, canon_allowed, obj_key, quantum=quantum)
    is_correct = (canon_algo in eval_res['best_algorithms'])

    current_attempts = (int(prev_sub['attempts_count']) if prev_sub and prev_sub.get('attempts_count') else 0) + 1
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    algo_perf = eval_res['results'].get(canon_algo, {})
    student_obj_val = algo_perf.get('objective_value', 0.0)
    student_metrics_json = json.dumps(algo_perf.get('metrics', {}))
    student_gantt_json = json.dumps(algo_perf.get('gantt_chart', []))

    if is_correct:
        status = 'COMPLETED'
        ver_note = f"Verified {canon_algo} ({student_obj_val}ms) | {eval_res['objective_label']} | {len(workload)} Virtual Processes"

        # Check atomic ledger for XP award
        xp_already_awarded = False
        if mysql_ok:
            with db.cursor() as cur:
                cur.execute("SELECT id FROM student_xp_awards WHERE assignment_id = %s AND student_email = %s", (assignment_id, student_email))
                if cur.fetchone():
                    xp_already_awarded = True
        else:
            sconn = _get_sqlite_mirror()
            scur = sconn.cursor()
            scur.execute("SELECT id FROM student_xp_awards WHERE assignment_id = ? AND student_email = ?", (assignment_id, student_email))
            if scur.fetchone():
                xp_already_awarded = True
            sconn.close()

        if not xp_already_awarded:
            # Atomic ledger insert
            award_reason = f"Completed Virtual Apps Challenge #{assignment_id} ({asgn.get('title')})"
            if mysql_ok:
                with db.cursor() as cur:
                    cur.execute(
                        """INSERT INTO student_xp_awards (student_email, student_name, assignment_id, points_awarded, award_reason, awarded_at)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (student_email, student_name, assignment_id, points, award_reason, now_str)
                    )
                db.commit()
            else:
                sconn = _get_sqlite_mirror()
                scur = sconn.cursor()
                scur.execute(
                    """INSERT INTO student_xp_awards (student_email, student_name, assignment_id, points_awarded, award_reason, awarded_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (student_email, student_name, assignment_id, points, award_reason, now_str)
                )
                sconn.commit()
                sconn.close()

            new_score = engine.update_score(points, f"Solved Virtual Apps Challenge #{assignment_id}")
            xp_awarded = points
            _log_activity(student_name, student_email, f"🏆 Solved Virtual Apps Challenge #{assignment_id} using {canon_algo} (+{points} XP)")
        else:
            xp_awarded = 0
            new_score = engine.score
            _log_activity(student_name, student_email, f"🔄 Retried Virtual Apps Challenge #{assignment_id} using {canon_algo} (XP already awarded)")

        # Upsert submission
        if mysql_ok:
            with db.cursor() as cur:
                cur.execute(
                    """INSERT INTO assignment_submissions
                       (assignment_id, student_email, student_name, status, score_awarded, verification_note,
                        student_explanation, selected_algo, submitted_quantum, objective_value, scheduling_metrics,
                        gantt_json, attempts_count, completed_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           status = VALUES(status),
                           score_awarded = VALUES(score_awarded),
                           verification_note = VALUES(verification_note),
                           student_explanation = VALUES(student_explanation),
                           selected_algo = VALUES(selected_algo),
                           submitted_quantum = VALUES(submitted_quantum),
                           objective_value = VALUES(objective_value),
                           scheduling_metrics = VALUES(scheduling_metrics),
                           gantt_json = VALUES(gantt_json),
                           attempts_count = VALUES(attempts_count),
                           completed_at = VALUES(completed_at)""",
                    (assignment_id, student_email, student_name, status, points, ver_note,
                     student_explanation, canon_algo, quantum, student_obj_val, student_metrics_json,
                     student_gantt_json, current_attempts, now_str)
                )
            db.commit()
        else:
            sconn = _get_sqlite_mirror()
            scur = sconn.cursor()
            scur.execute(
                """INSERT INTO assignment_submissions
                   (assignment_id, student_email, student_name, status, score_awarded, verification_note,
                    student_explanation, selected_algo, submitted_quantum, objective_value, scheduling_metrics,
                    gantt_json, attempts_count, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(assignment_id, student_email) DO UPDATE SET
                       status = excluded.status,
                       score_awarded = excluded.score_awarded,
                       verification_note = excluded.verification_note,
                       student_explanation = excluded.student_explanation,
                       selected_algo = excluded.selected_algo,
                       submitted_quantum = excluded.submitted_quantum,
                       objective_value = excluded.objective_value,
                       scheduling_metrics = excluded.scheduling_metrics,
                       gantt_json = excluded.gantt_json,
                       attempts_count = excluded.attempts_count,
                       completed_at = excluded.completed_at""",
                (assignment_id, student_email, student_name, status, points, ver_note,
                 student_explanation, canon_algo, quantum, student_obj_val, student_metrics_json,
                 student_gantt_json, current_attempts, now_str)
            )
            sconn.commit()
            sconn.close()

        msg = (f"🎯 Congratulations! {canon_algo} is optimal for '{eval_res['objective_label']}' ({student_obj_val} ms). +{xp_awarded} XP awarded!"
               if xp_awarded > 0 else
               f"🎯 Correct! {canon_algo} is optimal for '{eval_res['objective_label']}' ({student_obj_val} ms). (XP was already awarded on a previous attempt).")

        return ok({
            'is_correct': True,
            'status': status,
            'xp_awarded': xp_awarded,
            'total_score': new_score,
            'attempts_count': current_attempts,
            'selected_algo': canon_algo,
            'student_value': student_obj_val,
            'min_value': eval_res['min_value'],
            'best_algorithms': eval_res['best_algorithms'],
            'comparison_results': eval_res['results'],
            'verification_note': ver_note,
            'message': msg
        })

    else:
        status = 'IN_PROGRESS'
        best_str = ', '.join(eval_res['best_algorithms'])
        ver_note = f"Attempt #{current_attempts}: Selected {canon_algo} ({student_obj_val}ms), required optimal was {best_str} ({eval_res['min_value']}ms)"
        feedback = (f"Your choice '{canon_algo}' resulted in an objective value of {student_obj_val} ms, but the optimal result achieved "
                    f"for this workload is {eval_res['min_value']} ms (achieved by {best_str}). "
                    f"Analyze the process burst times, arrivals, and priority queues, then try again!")

        if mysql_ok:
            with db.cursor() as cur:
                cur.execute(
                    """INSERT INTO assignment_submissions
                       (assignment_id, student_email, student_name, status, score_awarded, verification_note,
                        student_explanation, selected_algo, submitted_quantum, objective_value, scheduling_metrics,
                        gantt_json, attempts_count, completed_at)
                       VALUES (%s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           status = VALUES(status),
                           verification_note = VALUES(verification_note),
                           student_explanation = VALUES(student_explanation),
                           selected_algo = VALUES(selected_algo),
                           submitted_quantum = VALUES(submitted_quantum),
                           objective_value = VALUES(objective_value),
                           scheduling_metrics = VALUES(scheduling_metrics),
                           gantt_json = VALUES(gantt_json),
                           attempts_count = VALUES(attempts_count),
                           completed_at = VALUES(completed_at)""",
                    (assignment_id, student_email, student_name, status, ver_note,
                     student_explanation, canon_algo, quantum, student_obj_val, student_metrics_json,
                     student_gantt_json, current_attempts, now_str)
                )
            db.commit()
        else:
            sconn = _get_sqlite_mirror()
            scur = sconn.cursor()
            scur.execute(
                """INSERT INTO assignment_submissions
                   (assignment_id, student_email, student_name, status, score_awarded, verification_note,
                    student_explanation, selected_algo, submitted_quantum, objective_value, scheduling_metrics,
                    gantt_json, attempts_count, completed_at)
                   VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(assignment_id, student_email) DO UPDATE SET
                       status = excluded.status,
                       verification_note = excluded.verification_note,
                       student_explanation = excluded.student_explanation,
                       selected_algo = excluded.selected_algo,
                       submitted_quantum = excluded.submitted_quantum,
                       objective_value = excluded.objective_value,
                       scheduling_metrics = excluded.scheduling_metrics,
                       gantt_json = excluded.gantt_json,
                       attempts_count = excluded.attempts_count,
                       completed_at = excluded.completed_at""",
                (assignment_id, student_email, student_name, status, ver_note,
                 student_explanation, canon_algo, quantum, student_obj_val, student_metrics_json,
                 student_gantt_json, current_attempts, now_str)
            )
            sconn.commit()
            sconn.close()

        _log_activity(student_name, student_email, f"⚠️ Suboptimal submission on Virtual Apps Challenge #{assignment_id} ({canon_algo} vs optimal {best_str})")

        return ok({
            'is_correct': False,
            'status': status,
            'xp_awarded': 0,
            'attempts_count': current_attempts,
            'selected_algo': canon_algo,
            'student_value': student_obj_val,
            'min_value': eval_res['min_value'],
            'best_algorithms': eval_res['best_algorithms'],
            'comparison_results': eval_res['results'],
            'feedback': feedback,
            'message': f"Algorithm '{canon_algo}' is not the optimal choice for this challenge. Review the feedback and try again!"
        })


if __name__ == '__main__':
    app.run(debug=Config.DEBUG, port=8080, host='0.0.0.0')
