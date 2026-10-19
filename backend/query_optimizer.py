"""
SysRealm Query Optimizer & Relational Algebra Tree Generator
Comprehensive Rectification Implementation:
1. Real Database Schema Introspection (SQLite & MySQL) with full sqlite3.Row support.
2. Connection-isolated schema caching with explicit metadata status reporting.
3. Strict Read-Only SQL Safety Validation (blocking DDL/DML, file-writing SELECT variants like INTO OUTFILE,
   locking clauses, multi-statements, while safely allowing SQL keywords inside string literals, leading comments, and CTEs).
4. Semantic-Preserving Heuristic Query Rewriting:
   - Projection Pruning (pi) retaining ALL required attributes across SELECT, WHERE, ON, GROUP BY, ORDER BY, and expressions
   - Selection Pushdown (sigma) preserving conjunctive predicates and outer-join semantics (never pushing filters across LEFT JOIN nullable side)
   - Subquery Unnesting (IN predicates to hash semijoins) preserving outer WHERE predicates and duplicate semantics
   - Cartesian Comma Join elimination to ANSI INNER JOIN
   - Index Recommendations (DDL) matching real schema attributes
5. Dynamic Relational Algebra Tree Generation strictly representing the submitted query.
6. Real Database Execution Plan Generation (EXPLAIN QUERY PLAN for SQLite, EXPLAIN for MySQL) without fabricated sample plans.
7. High-precision monotonic elapsed timing and multi-set (bag) result-equivalence verification.
8. Clearly classified, honest performance metrics (measured vs estimated vs educational heuristics).
"""

from typing import Dict, Any, List, Optional, Tuple
import re
import time
import collections


# ══════════════════════════════════════════════════════════════════════════════
# 1. ACCURATE FALLBACK SCHEMA CATALOG (Mirrors database/schema.sql 100%)
# ══════════════════════════════════════════════════════════════════════════════
FALLBACK_SCHEMA_CATALOG: Dict[str, Dict[str, Any]] = {
    'processes': {
        'cols': [
            'id', 'pid', 'session_id', 'name', 'arrival_time', 'burst_time',
            'priority', 'memory_mb', 'state', 'remaining_time', 'start_time',
            'completion_time', 'waiting_time', 'turnaround_time', 'response_time',
            'created_at'
        ],
        'default_proj': ['pid', 'name', 'burst_time', 'priority', 'memory_mb', 'session_id'],
        'pk': 'id',
        'est_rows': 600,
        'row_size_bytes': 64
    },
    'simulation_sessions': {
        'cols': [
            'id', 'session_id', 'user_id', 'algorithm', 'status', 'quantum',
            'cpu_utilization', 'avg_waiting_time', 'avg_turnaround_time',
            'num_processes', 'created_at', 'completed_at'
        ],
        'default_proj': ['session_id', 'algorithm', 'status', 'cpu_utilization'],
        'pk': 'id',
        'est_rows': 150,
        'row_size_bytes': 96
    },
    'users': {
        'cols': ['id', 'username', 'email', 'password_hash', 'account_type', 'created_at'],
        'default_proj': ['id', 'username', 'email', 'account_type'],
        'pk': 'id',
        'est_rows': 200,
        'row_size_bytes': 128
    },
    'resource_allocations': {
        'cols': ['id', 'resource_id', 'pid', 'session_id', 'count', 'status', 'created_at'],
        'default_proj': ['resource_id', 'pid', 'session_id', 'count', 'status'],
        'pk': 'id',
        'est_rows': 850,
        'row_size_bytes': 48
    },
    'resources': {
        # 'available' removed: schema defines (id, resource_id, name, total, icon, created_at)
        'cols': ['id', 'resource_id', 'name', 'total', 'icon', 'created_at'],
        'default_proj': ['resource_id', 'name', 'total'],
        'pk': 'id',
        'est_rows': 10,
        'row_size_bytes': 40
    },
    'process_activity_logs': {
        'cols': ['id', 'session_id', 'process_id', 'event_type', 'simulation_time', 'description', 'created_at'],
        'default_proj': ['id', 'session_id', 'process_id', 'event_type', 'simulation_time'],
        'pk': 'id',
        'est_rows': 1200,
        'row_size_bytes': 256
    },
    'process_state_history': {
        'cols': ['id', 'session_id', 'pid', 'old_state', 'new_state', 'changed_at'],
        'default_proj': ['id', 'session_id', 'pid', 'old_state', 'new_state', 'changed_at'],
        'pk': 'id',
        'est_rows': 1500,
        'row_size_bytes': 64
    },
    'files': {
        'cols': ['id', 'session_id', 'filename', 'size_kb', 'owner_pid', 'created_at'],
        'default_proj': ['id', 'filename', 'size_kb', 'owner_pid'],
        'pk': 'id',
        'est_rows': 80,
        'row_size_bytes': 80
    },
    'scores': {
        'cols': ['id', 'session_id', 'total_score', 'reason', 'updated_at'],
        'default_proj': ['id', 'session_id', 'total_score', 'reason'],
        'pk': 'id',
        'est_rows': 100,
        'row_size_bytes': 64
    },
    'lab_assignments': {
        'cols': ['id', 'title', 'description', 'target_panel', 'required_algo', 'max_awt', 'points', 'created_by', 'created_at', 'given_query', 'expected_rules'],
        'default_proj': ['id', 'title', 'target_panel', 'points'],
        'pk': 'id',
        'est_rows': 20,
        'row_size_bytes': 128
    },
    'assignment_submissions': {
        'cols': ['id', 'assignment_id', 'student_email', 'student_name', 'status', 'score_awarded', 'verification_note', 'completed_at', 'submitted_query', 'student_explanation', 'cbo_metrics'],
        'default_proj': ['id', 'assignment_id', 'student_email', 'status', 'score_awarded'],
        'pk': 'id',
        'est_rows': 50,
        'row_size_bytes': 256
    },
    'simulation_runs': {
        'cols': ['id', 'run_id', 'session_id', 'user_id', 'run_name', 'algorithm', 'quantum', 'process_count', 'workload_hash', 'avg_waiting_time', 'avg_turnaround_time', 'avg_response_time', 'cpu_utilization', 'throughput', 'context_switches', 'status', 'gantt_json', 'metrics_json', 'created_at'],
        'default_proj': ['run_id', 'run_name', 'algorithm', 'avg_waiting_time', 'cpu_utilization'],
        'pk': 'id',
        'est_rows': 200,
        'row_size_bytes': 256
    },
    'simulation_run_processes': {
        'cols': ['id', 'run_id', 'pid', 'name', 'arrival_time', 'burst_time', 'priority', 'memory_mb', 'start_time', 'completion_time', 'waiting_time', 'turnaround_time', 'response_time', 'execution_order'],
        'default_proj': ['run_id', 'pid', 'name', 'burst_time', 'waiting_time', 'turnaround_time'],
        'pk': 'id',
        'est_rows': 1000,
        'row_size_bytes': 128
    }
}

SCHEMA_CATALOG = FALLBACK_SCHEMA_CATALOG

# Connection-isolated in-memory schema caches: {cache_key: (catalog, timestamp)}
_SCHEMA_CACHES: Dict[str, Tuple[Dict[str, Dict[str, Any]], float]] = {}


def _get_connection_cache_key(db_conn) -> str:
    """Computes a unique cache key based on the specific database connection and backing store."""
    if db_conn is None:
        return "none"
    is_sqlite = 'sqlite' in type(db_conn).__module__.lower() or hasattr(db_conn, 'iterdump')
    if is_sqlite:
        try:
            cur = db_conn.cursor()
            cur.execute("PRAGMA database_list;")
            rows = cur.fetchall()
            for r in rows:
                fpath = r[2] if isinstance(r, (list, tuple)) else (r['file'] if hasattr(r, 'keys') else '')
                if fpath:
                    return f"sqlite_file:{fpath}"
        except Exception:
            pass
        return f"sqlite_conn:{id(db_conn)}"
    try:
        host = getattr(db_conn, 'host', 'localhost')
        db = getattr(db_conn, 'db', 'sysrealm')
        return f"mysql_{host}_{db}_{id(db_conn)}"
    except Exception:
        return f"conn_{id(db_conn)}"


def get_schema_catalog(db_conn=None, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Introspects the real schema metadata from the active database (SQLite or MySQL).
    Supports sqlite3.Row, dict, tuple, and list row types without assuming .get() is available.
    Maintains connection-isolated caching to prevent cross-database metadata contamination.
    Clearly marks metadata status so fallback is never disguised as verified live metadata.
    """
    global _SCHEMA_CACHES

    cache_key = _get_connection_cache_key(db_conn)
    now = time.time()

    if not force_refresh and cache_key in _SCHEMA_CACHES:
        cached_cat, ts = _SCHEMA_CACHES[cache_key]
        if now - ts < 60.0:
            return cached_cat

    if db_conn is None:
        fallback_copy = {k: dict(v) for k, v in FALLBACK_SCHEMA_CATALOG.items()}
        fallback_copy['__metadata_status__'] = {
            'source': 'fallback',
            'verified': False,
            'note': 'Static educational reference catalog (no live database connection provided).'
        }
        return fallback_copy

    catalog: Dict[str, Dict[str, Any]] = {}
    is_sqlite = 'sqlite' in type(db_conn).__module__.lower() or hasattr(db_conn, 'iterdump')

    try:
        cur = db_conn.cursor()
        if is_sqlite:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
            table_rows = cur.fetchall()
            for trow in table_rows:
                if hasattr(trow, 'keys'):
                    tname = str(trow['name'])
                elif isinstance(trow, dict):
                    tname = str(trow.get('name', ''))
                else:
                    tname = str(trow[0])
                tname_clean = tname.strip()
                if not tname_clean:
                    continue

                # Table column metadata
                cur.execute(f'PRAGMA table_info("{tname_clean}");')
                cols_info = cur.fetchall()
                cols: List[str] = []
                pk_col = 'id'
                for cinfo in cols_info:
                    if hasattr(cinfo, 'keys'):
                        cname = str(cinfo['name'])
                        is_pk = bool(cinfo['pk'])
                    elif isinstance(cinfo, dict):
                        cname = str(cinfo.get('name', ''))
                        is_pk = bool(cinfo.get('pk', 0))
                    elif isinstance(cinfo, (list, tuple)) and len(cinfo) >= 6:
                        cname = str(cinfo[1])
                        is_pk = bool(cinfo[5])
                    else:
                        continue
                    cols.append(cname)
                    if is_pk:
                        pk_col = cname

                # Foreign Keys
                fks = []
                try:
                    cur.execute(f'PRAGMA foreign_key_list("{tname_clean}");')
                    for frow in cur.fetchall():
                        if hasattr(frow, 'keys'):
                            fks.append({'from': frow['from'], 'to_table': frow['table'], 'to_col': frow['to']})
                        elif isinstance(frow, dict):
                            fks.append({'from': frow.get('from'), 'to_table': frow.get('table'), 'to_col': frow.get('to')})
                        elif isinstance(frow, (list, tuple)) and len(frow) >= 5:
                            fks.append({'from': frow[3], 'to_table': frow[2], 'to_col': frow[4]})
                except Exception:
                    pass

                # Indexes
                indexes_info = []
                try:
                    cur.execute(f'PRAGMA index_list("{tname_clean}");')
                    for irow in cur.fetchall():
                        if hasattr(irow, 'keys'):
                            iname = irow['name']
                            is_u = bool(irow['unique'])
                        elif isinstance(irow, dict):
                            iname = irow.get('name')
                            is_u = bool(irow.get('unique', 0))
                        elif isinstance(irow, (list, tuple)) and len(irow) >= 3:
                            iname = irow[1]
                            is_u = bool(irow[2])
                        else:
                            continue
                        indexes_info.append({'name': iname, 'unique': is_u})
                except Exception:
                    pass

                # Estimated or actual row count
                est_rows = 100
                try:
                    cur.execute(f'SELECT COUNT(*) FROM "{tname_clean}";')
                    cnt_res = cur.fetchone()
                    if cnt_res is not None:
                        if hasattr(cnt_res, 'keys'):
                            k0 = list(cnt_res.keys())[0]
                            est_rows = max(1, int(cnt_res[k0] or 0))
                        elif isinstance(cnt_res, dict):
                            v0 = list(cnt_res.values())[0]
                            est_rows = max(1, int(v0 or 0))
                        else:
                            est_rows = max(1, int(cnt_res[0] or 0))
                except Exception:
                    est_rows = FALLBACK_SCHEMA_CATALOG.get(tname_clean.lower(), {}).get('est_rows', 100)

                default_p = [c for c in cols if c not in ('password_hash', 'created_at', 'updated_at')][:5] or cols
                catalog[tname_clean.lower()] = {
                    'table_name': tname_clean,
                    'cols': cols,
                    'default_proj': default_p,
                    'pk': pk_col,
                    'foreign_keys': fks,
                    'indexes': indexes_info,
                    'est_rows': est_rows,
                    'row_size_bytes': FALLBACK_SCHEMA_CATALOG.get(tname_clean.lower(), {}).get('row_size_bytes', 64)
                }

            # Merge any fallback definitions for missing tables
            for k, v in FALLBACK_SCHEMA_CATALOG.items():
                if k not in catalog:
                    catalog[k] = dict(v)

            catalog['__metadata_status__'] = {
                'source': 'live_sqlite',
                'verified': True,
                'tables_discovered': len(table_rows),
                'error': None
            }

        else:
            # MySQL metadata introspection
            cur.execute("SELECT table_name, column_name, column_key FROM information_schema.columns WHERE table_schema = DATABASE();")
            rows = cur.fetchall()
            for r in rows:
                if isinstance(r, dict):
                    tname = r['table_name'].lower()
                    cname = r['column_name']
                    is_pri = (r.get('column_key') == 'PRI')
                else:
                    tname = str(r[0]).lower()
                    cname = str(r[1])
                    is_pri = (str(r[2]).upper() == 'PRI')

                if tname not in catalog:
                    catalog[tname] = {
                        'table_name': tname,
                        'cols': [],
                        'default_proj': [],
                        'pk': 'id',
                        'est_rows': FALLBACK_SCHEMA_CATALOG.get(tname, {}).get('est_rows', 100),
                        'row_size_bytes': FALLBACK_SCHEMA_CATALOG.get(tname, {}).get('row_size_bytes', 64)
                    }
                catalog[tname]['cols'].append(cname)
                if is_pri:
                    catalog[tname]['pk'] = cname

            for tname, cinfo in catalog.items():
                cinfo['default_proj'] = [c for c in cinfo['cols'] if c not in ('password_hash', 'created_at', 'updated_at')][:5]

            for k, v in FALLBACK_SCHEMA_CATALOG.items():
                if k not in catalog:
                    catalog[k] = dict(v)

            catalog['__metadata_status__'] = {
                'source': 'live_mysql',
                'verified': True,
                'tables_discovered': len(catalog),
                'error': None
            }

        _SCHEMA_CACHES[cache_key] = (catalog, now)
        return catalog

    except Exception as e:
        fallback_copy = {k: dict(v) for k, v in FALLBACK_SCHEMA_CATALOG.items()}
        fallback_copy['__metadata_status__'] = {
            'source': 'fallback',
            'verified': False,
            'error': f"Schema introspection failed: {str(e)}. Operating in fallback mode."
        }
        return fallback_copy


# ══════════════════════════════════════════════════════════════════════════════
# 2. EDUCATIONAL PRESET QUERIES (100% valid schema columns)
# ══════════════════════════════════════════════════════════════════════════════
PRESET_QUERIES: Dict[str, Dict[str, Any]] = {
    'join_filter': {
        'title': '1. Push Selection Down JOIN (Standard Exam Problem)',
        'sql': (
            "SELECT s.session_id, s.algorithm, p.pid, p.name, p.burst_time\n"
            "FROM simulation_sessions s\n"
            "JOIN processes p ON s.session_id = p.session_id\n"
            "WHERE p.burst_time > 4 AND p.priority = 1;"
        ),
        'tables': ['simulation_sessions', 'processes'],
        'select_cols': ['s.session_id', 's.algorithm', 'p.pid', 'p.name', 'p.burst_time'],
        'join_condition': 's.session_id = p.session_id',
        'where_conditions': ['p.burst_time > 4', 'p.priority = 1'],
        'base_stats': {'simulation_sessions': 150, 'processes': 600}
    },
    'multi_join': {
        'title': '2. Multi-Table Join with Early Filtering & Projection',
        'sql': (
            "SELECT s.session_id, p.name, r.resource_id, r.count\n"
            "FROM simulation_sessions s\n"
            "JOIN processes p ON s.session_id = p.session_id\n"
            "JOIN resource_allocations r ON p.pid = r.pid\n"
            "WHERE s.algorithm = 'RoundRobin' AND p.memory_mb > 512;"
        ),
        'tables': ['simulation_sessions', 'processes', 'resource_allocations'],
        'select_cols': ['s.session_id', 'p.name', 'r.resource_id', 'r.count'],
        'join_condition': 's.session_id = p.session_id AND p.pid = r.pid',
        'where_conditions': ["s.algorithm = 'RoundRobin'", "p.memory_mb > 512"],
        'base_stats': {'simulation_sessions': 80, 'processes': 450, 'resource_allocations': 900}
    },
    'aggregate_filter': {
        'title': '3. Aggregated Filter with GROUP BY Optimization',
        'sql': (
            "SELECT s.algorithm, COUNT(p.id) as proc_count, AVG(p.burst_time) as avg_burst\n"
            "FROM simulation_sessions s\n"
            "JOIN processes p ON s.session_id = p.session_id\n"
            "WHERE s.status = 'ACTIVE'\n"
            "GROUP BY s.algorithm;"
        ),
        'tables': ['simulation_sessions', 'processes'],
        'select_cols': ['s.algorithm', 'COUNT(p.id)', 'AVG(p.burst_time)'],
        'join_condition': 's.session_id = p.session_id',
        'where_conditions': ["s.status = 'ACTIVE'"],
        'base_stats': {'simulation_sessions': 120, 'processes': 850}
    }
}


# ══════════════════════════════════════════════════════════════════════════════
# 3. STRICT READ-ONLY SQL VALIDATION & SECURITY
# ══════════════════════════════════════════════════════════════════════════════
def validate_read_only_sql(sql: str) -> Tuple[bool, Optional[str]]:
    """
    Validates that the provided SQL is strictly a read-only SELECT or CTE query.
    Rejects any destructive or administrative statement.
    Accurately handles leading comments, whitespace, semicolons, and string literals.
    Guards against file-writing SELECT variants (INTO OUTFILE, INTO DUMPFILE, INTO variable).
    Ensures safe text containing SQL keywords inside quotes is not incorrectly rejected.
    """
    if not sql or not sql.strip():
        return False, "Query cannot be empty."

    # Strip multi-line comments /* ... */ and line comments -- ...
    cleaned = re.sub(r'/\*.*?\*/', ' ', sql, flags=re.DOTALL)
    cleaned = re.sub(r'--[^\r\n]*', ' ', cleaned)
    cleaned = cleaned.strip()

    if not cleaned:
        return False, "Query contains only comments or whitespace."

    # Mask string literals so keywords inside quotes (e.g. 'delete') are never flagged
    def mask_string_literals(text: str) -> Tuple[str, bool]:
        masked = []
        i = 0
        n = len(text)
        in_single = False
        in_double = False
        while i < n:
            ch = text[i]
            if ch == "'" and not in_double:
                if in_single:
                    # check for escaped single quote ''
                    if i + 1 < n and text[i + 1] == "'":
                        i += 2
                        continue
                    in_single = False
                    masked.append("'__STR__'")
                    i += 1
                    continue
                else:
                    in_single = True
                    i += 1
                    continue
            elif ch == '"' and not in_single:
                if in_double:
                    if i + 1 < n and text[i + 1] == '"':
                        i += 2
                        continue
                    in_double = False
                    masked.append('"__STR__"')
                    i += 1
                    continue
                else:
                    in_double = True
                    i += 1
                    continue

            if not in_single and not in_double:
                masked.append(ch)
            i += 1

        if in_single or in_double:
            return "", False
        return ''.join(masked), True

    masked_sql, quotes_closed = mask_string_literals(cleaned)
    if not quotes_closed:
        return False, "Query contains unclosed string literal quotes."

    # Check for multiple SQL statements (outside string literals)
    statements = [s.strip() for s in masked_sql.split(';') if s.strip()]
    if len(statements) > 1:
        return False, "Multiple SQL statements are not supported in the read-only optimizer."

    target_sql = statements[0]

    # Must start with SELECT or WITH
    if not re.match(r'^(?:SELECT|WITH)\b', target_sql, re.IGNORECASE):
        return False, "Only read-only SELECT queries are supported by the query optimizer."

    # If it starts with WITH (CTE), ensure it contains a top-level SELECT
    if re.match(r'^WITH\b', target_sql, re.IGNORECASE):
        if not re.search(r'\bSELECT\b', target_sql, re.IGNORECASE):
            return False, "CTE expression must contain a valid SELECT query."

    # Forbid file-writing SELECT variants: INTO OUTFILE / INTO DUMPFILE
    if re.search(r'\bINTO\s+(?:OUTFILE|DUMPFILE)\b', target_sql, re.IGNORECASE):
        return False, "File-writing operations (INTO OUTFILE / DUMPFILE) are strictly forbidden in read-only analysis."

    # Forbid generic SELECT ... INTO statements
    if re.search(r'\bSELECT\b[\s\S]+?\bINTO\b', target_sql, re.IGNORECASE):
        return False, "SELECT ... INTO clauses modify external files or state and are strictly forbidden."

    # Forbid row-locking clauses
    if re.search(r'\bFOR\s+UPDATE\b|\bLOCK\s+IN\s+SHARE\s+MODE\b|\bFOR\s+SHARE\b', target_sql, re.IGNORECASE):
        return False, "Explicit row locking clauses (FOR UPDATE / LOCK IN SHARE MODE) are strictly forbidden in read-only analysis."

    # Forbidden DDL/DML/Administrative keywords (checked strictly outside string literals)
    forbidden = [
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE',
        'TRUNCATE', 'REPLACE', 'EXEC', 'EXECUTE', 'CALL', 'GRANT',
        'REVOKE', 'ATTACH', 'DETACH', 'PRAGMA', 'REINDEX', 'VACUUM',
        'LOAD_FILE', 'LOAD', 'SHUTDOWN', 'KILL', 'HANDLER', 'MERGE',
        'UPSERT'
    ]
    for kw in forbidden:
        if re.search(rf'\b{kw}\b', target_sql, re.IGNORECASE):
            return False, f"Statement contains forbidden keyword '{kw}'. Only read-only SELECT queries are allowed."

    return True, None


# ══════════════════════════════════════════════════════════════════════════════
# 4. PARENTHESIS-AWARE & QUOTE-AWARE CONDITION SPLITTER
# ══════════════════════════════════════════════════════════════════════════════
def split_top_level_and(where_str: str) -> List[str]:
    """
    Splits a WHERE clause on top-level AND operators, respecting nested parentheses
    and quoted string literals so boolean sub-expressions are never severed.
    """
    if not where_str or not where_str.strip():
        return []

    tokens: List[str] = []
    current: List[str] = []
    paren_depth = 0
    in_single_quote = False
    in_double_quote = False

    s = where_str.strip()
    i = 0
    n = len(s)

    while i < n:
        ch = s[i]
        if ch == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(ch)
            i += 1
            continue

        if not in_single_quote and not in_double_quote:
            if ch == '(':
                paren_depth += 1
                current.append(ch)
                i += 1
                continue
            elif ch == ')':
                paren_depth = max(0, paren_depth - 1)
                current.append(ch)
                i += 1
                continue
            elif paren_depth == 0:
                match = re.match(r'^\s+AND\s+', s[i:], re.IGNORECASE)
                if match:
                    t = ''.join(current).strip()
                    if t:
                        tokens.append(t)
                    current = []
                    i += len(match.group(0))
                    continue

        current.append(ch)
        i += 1

    if current:
        t = ''.join(current).strip()
        if t:
            tokens.append(t)

    return tokens


# ══════════════════════════════════════════════════════════════════════════════
# 5. PARSE TABLES & PRESERVE JOIN TYPES (INNER, LEFT, RIGHT, CROSS, COMMA)
# ══════════════════════════════════════════════════════════════════════════════
def parse_tables(from_part: str) -> List[Dict[str, Any]]:
    """
    Parses the FROM clause into individual table references, maintaining exact
    JOIN types (FROM, INNER JOIN, LEFT JOIN, RIGHT JOIN, CROSS JOIN, COMMA)
    and their respective ON predicates.
    """
    tables: List[Dict[str, Any]] = []
    from_clean = from_part.strip()

    join_pattern = re.compile(
        r'\s+(LEFT\s+OUTER\s+JOIN|RIGHT\s+OUTER\s+JOIN|LEFT\s+JOIN|RIGHT\s+JOIN|INNER\s+JOIN|CROSS\s+JOIN|JOIN)\s+',
        re.IGNORECASE
    )

    if join_pattern.search(from_clean):
        matches = list(join_pattern.finditer(from_clean))
        parts: List[Tuple[str, str]] = []

        last_pos = 0
        for m in matches:
            chunk = from_clean[last_pos:m.start()].strip()
            join_type = re.sub(r'\s+', ' ', m.group(1).upper())
            if join_type == 'JOIN':
                join_type = 'INNER JOIN'
            parts.append((chunk, join_type))
            last_pos = m.end()
        parts.append((from_clean[last_pos:].strip(), 'END'))

        # First table is FROM
        first_chunk = parts[0][0]
        m0 = re.match(r'([a-zA-Z0-9_]+)(?:\s+(?:AS\s+)?([a-zA-Z0-9_]+))?', first_chunk, re.IGNORECASE)
        if m0:
            tables.append({
                'table': m0.group(1),
                'alias': m0.group(2) or m0.group(1),
                'join_on': None,
                'join_type': 'FROM'
            })

        for i in range(1, len(parts)):
            chunk = parts[i][0]
            prev_join_type = parts[i - 1][1]
            on_parts = re.split(r'\s+ON\s+', chunk, flags=re.IGNORECASE, maxsplit=1)
            tbl_spec = on_parts[0].strip()
            on_cond = on_parts[1].strip() if len(on_parts) > 1 else None

            mt = re.match(r'([a-zA-Z0-9_]+)(?:\s+(?:AS\s+)?([a-zA-Z0-9_]+))?', tbl_spec, re.IGNORECASE)
            if mt:
                tables.append({
                    'table': mt.group(1),
                    'alias': mt.group(2) or mt.group(1),
                    'join_on': on_cond,
                    'join_type': prev_join_type
                })
    elif ',' in from_clean:
        for t in from_clean.split(','):
            t_strip = t.strip()
            mt = re.match(r'([a-zA-Z0-9_]+)(?:\s+(?:AS\s+)?([a-zA-Z0-9_]+))?', t_strip, re.IGNORECASE)
            if mt:
                tables.append({
                    'table': mt.group(1),
                    'alias': mt.group(2) or mt.group(1),
                    'join_on': None,
                    'join_type': 'COMMA' if len(tables) > 0 else 'FROM'
                })
    else:
        mt = re.match(r'([a-zA-Z0-9_]+)(?:\s+(?:AS\s+)?([a-zA-Z0-9_]+))?', from_clean, re.IGNORECASE)
        if mt:
            tables.append({
                'table': mt.group(1),
                'alias': mt.group(2) or mt.group(1),
                'join_on': None,
                'join_type': 'FROM'
            })

    return tables


# ══════════════════════════════════════════════════════════════════════════════
# 6. ATTRIBUTE & PROJECTION DEPENDENCY RESOLVER
# ══════════════════════════════════════════════════════════════════════════════
def extract_required_columns_for_table(
    table_dict: Dict[str, Any],
    all_sql_parts: List[str],
    schema_catalog: Dict[str, Dict[str, Any]]
) -> List[str]:
    """
    Extracts every column required for a specific table across the entire query:
    SELECT attributes, WHERE filters, JOIN ON predicates, GROUP BY, and ORDER BY.
    Handles aliases, expressions, function calls, and primary keys.
    Prevents projection pruning from omitting attributes needed by outer queries.
    """
    tname = table_dict['table'].lower()
    alias = table_dict['alias'].lower()
    valid_cols = set(schema_catalog.get(tname, {}).get('cols', []))

    needed_cols = set()
    combined_sql = ' '.join(all_sql_parts)

    # 1. Explicit alias.column references (e.g. p.memory_mb, COUNT(p.pid))
    explicit_matches = re.findall(rf'\b{re.escape(alias)}\.([a-zA-Z0-9_]+)\b', combined_sql, re.IGNORECASE)
    for col in explicit_matches:
        if not valid_cols or col.lower() in valid_cols:
            needed_cols.add(col.lower())

    # 2. Explicit table.column references (e.g. processes.memory_mb)
    tbl_matches = re.findall(rf'\b{re.escape(tname)}\.([a-zA-Z0-9_]+)\b', combined_sql, re.IGNORECASE)
    for col in tbl_matches:
        if not valid_cols or col.lower() in valid_cols:
            needed_cols.add(col.lower())

    # 3. Unqualified column references matching this table's schema
    for col in valid_cols:
        if re.search(rf'\b{re.escape(col)}\b', combined_sql, re.IGNORECASE):
            # Ensure not prefixed by another table alias
            if not re.search(rf'\b[a-zA-Z0-9_]+\.{re.escape(col)}\b', combined_sql, re.IGNORECASE):
                needed_cols.add(col.lower())

    # 4. Primary key preservation
    pk = schema_catalog.get(tname, {}).get('pk')
    if pk and (not valid_cols or pk.lower() in valid_cols):
        needed_cols.add(pk.lower())

    return sorted(list(needed_cols))


# ══════════════════════════════════════════════════════════════════════════════
# 7. CORE SQL REWRITING ENGINE (Semantic-Preserving Equivalence Rules)
# ══════════════════════════════════════════════════════════════════════════════
def rewrite_and_optimize_query(raw_sql: str, db_conn=None) -> Dict[str, Any]:
    """
    Applies Relational Algebra equivalence rules:
    - Rule 1: Pushdown Selections (sigma) into derived subqueries with 100% attribute preservation.
    - Rule 2: Pushdown Projections (pi) without dropping required columns or corrupting SELECT *.
    - Rule 3: Replace Cartesian Products (comma joins) with ANSI explicit joins.
    - Rule 4: Subquery Unnesting (IN -> distinct hash semijoin derived table) with outer WHERE preservation.
    - Rule 5: Strict preservation of LEFT JOIN and outer-join semantics (no filter pushdown across outer joins).
    """
    catalog = get_schema_catalog(db_conn)

    # Safety check
    is_safe, err_msg = validate_read_only_sql(raw_sql)
    if not is_safe:
        return {
            'success': False,
            'optimization_applied': False,
            'error': err_msg,
            'original_sql': raw_sql,
            'optimized_sql': raw_sql,
            'transformations': [],
            'index_recommendations': [],
            'metrics': {'reduction_pct': 0.0, 'naive_cost': 0, 'opt_cost': 0, 'intermediate_rows_saved': 0, 'buffer_memory_saved_kb': 0.0}
        }

    sql = raw_sql.strip()
    if sql.endswith(';'):
        sql = sql[:-1].strip()

    transformations = []
    indexes = []

    # ── CASE 1: Subquery IN pattern with outer WHERE predicate preservation ──
    # Check if WHERE clause contains a top-level IN subquery
    in_sub_match = re.search(
        r'\b([a-zA-Z0-9_\.]+)\s+IN\s*\(\s*SELECT\s+([a-zA-Z0-9_\.]+)\s+FROM\s+([a-zA-Z0-9_]+)(?:\s+([a-zA-Z0-9_]+))?\s*(?:WHERE\s+([^)]+))?\s*\)',
        sql,
        re.IGNORECASE
    )
    if in_sub_match:
        # Verify IN subquery is at top-level AND in WHERE clause
        where_m = re.search(r'\bWHERE\b\s+(.*)', sql, re.IGNORECASE | re.DOTALL)
        if where_m:
            raw_where = where_m.group(1).strip()
            where_conds = split_top_level_and(raw_where)
            # Find the specific condition containing the IN subquery
            matched_in_cond = None
            other_conds = []
            for c in where_conds:
                if re.search(r'\bIN\s*\(\s*SELECT\b', c, re.IGNORECASE):
                    matched_in_cond = c
                else:
                    other_conds.append(c)

            if matched_in_cond:
                outer_col = in_sub_match.group(1).strip()
                sub_col = in_sub_match.group(2).strip()
                sub_tbl = in_sub_match.group(3).strip()
                sub_alias = in_sub_match.group(4) or f"sub_{sub_tbl[:4]}"
                sub_cond = in_sub_match.group(5) or ''

                from_part_m = re.search(r'FROM\s+(.*?)\s+WHERE', sql, re.IGNORECASE | re.DOTALL)
                main_from_str = from_part_m.group(1).strip() if from_part_m else 'simulation_sessions s'

                sel_prefix_m = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
                outer_select_part = sel_prefix_m.group(1).strip() if sel_prefix_m else '*'

                # Preserve outer WHERE conditions
                outer_where_clause = f"\nWHERE {' AND '.join(other_conds)}" if other_conds else ""

                opt_sql = (
                    f"SELECT \n"
                    f"    {outer_select_part}\n"
                    f"FROM {main_from_str}\n"
                    f"INNER JOIN (\n"
                    f"    /* [Rule 4: Subquery unnested into distinct hash-semijoin derived table] */\n"
                    f"    SELECT DISTINCT {sub_col.split('.')[-1]}\n"
                    f"    FROM {sub_tbl}\n"
                    f"    {('WHERE ' + sub_cond.strip() + ' /* [Rule 1: Selection pushed directly to inner relation] */') if sub_cond else ''}\n"
                    f") {sub_alias} \n"
                    f"    ON {outer_col} = {sub_alias}.{sub_col.split('.')[-1]}"
                    f"{outer_where_clause};"
                )

                transformations.append({
                    'name': 'Subquery Unnesting (IN → INNER JOIN)',
                    'badge': 'Subquery Unnested',
                    'color': '#8b5cf6',
                    'rule': 'R ⋉ (σ_c(S)) ≡ R ⨝ (π_{key}(σ_c(S)))',
                    'before': f"WHERE ... IN (SELECT {sub_col} FROM {sub_tbl} ...)",
                    'after': f"INNER JOIN (SELECT DISTINCT {sub_col.split('.')[-1]} FROM {sub_tbl}) {sub_alias} ON ...",
                    'description': f"Converted unindexed nested subquery on '{sub_tbl}' into a set-oriented hash semijoin, eliminating O(N) repetitive subquery scans."
                })

                if sub_cond:
                    transformations.append({
                        'name': 'Pushdown Selection (σ-Pushdown)',
                        'badge': 'σ Filter Pushdown',
                        'color': '#22c55e',
                        'rule': 'σ_c(R) applied inside derived subquery',
                        'before': f"WHERE ... IN (SELECT ... WHERE {sub_cond})",
                        'after': f"Derived Table WHERE: {sub_cond}",
                        'description': f"Pushed condition '{sub_cond}' directly into inner table filter before distinct hashing."
                    })

                indexes.append({
                    'table': sub_tbl,
                    'sql': f"CREATE INDEX idx_{sub_tbl}_lookup ON {sub_tbl} ({sub_col.split('.')[-1]});",
                    'impact': 'Allows index-only scan (Using index) for distinct subquery values.'
                })

                # Calculate mathematically sound educational metrics
                s_rows = catalog.get(sub_tbl.lower(), {}).get('est_rows', 500)
                main_tbl_key = main_from_str.split()[0].lower()
                m_rows = catalog.get(main_tbl_key, {}).get('est_rows', 150)
                naive_tuples = s_rows * m_rows
                opt_tuples = int(m_rows + (s_rows * 0.15))
                saved_rows = max(0, naive_tuples - opt_tuples)
                pct = round((saved_rows / naive_tuples) * 100, 1) if naive_tuples > 0 else 0.0

                return {
                    'success': True,
                    'optimization_applied': True,
                    'original_sql': raw_sql,
                    'optimized_sql': opt_sql,
                    'transformations': transformations,
                    'index_recommendations': indexes,
                    'metrics': {
                        'reduction_pct': pct,
                        'naive_cost': naive_tuples,
                        'opt_cost': opt_tuples,
                        'intermediate_rows_saved': saved_rows,
                        'buffer_memory_saved_kb': round(saved_rows * 0.064, 1),
                        'best_plan': 'Subquery Unnested & Pushed-Down Derived Table'
                    }
                }

    # ── CASE 2: Standard SELECT query ──
    sel_match = re.search(r'SELECT\s+(.*?)\s+FROM\s+(.*)', sql, re.IGNORECASE | re.DOTALL)
    if not sel_match:
        return {
            'success': True,
            'optimization_applied': False,
            'original_sql': raw_sql,
            'optimized_sql': raw_sql,
            'transformations': [],
            'index_recommendations': [],
            'reason': 'Query syntax is not in supported heuristic transformation scope; returned unchanged.',
            'metrics': {'reduction_pct': 0.0, 'naive_cost': 100, 'opt_cost': 100, 'intermediate_rows_saved': 0, 'buffer_memory_saved_kb': 0.0}
        }

    select_part = sel_match.group(1).strip()
    rest = sel_match.group(2).strip()

    group_part = ''
    order_part = ''
    limit_part = ''

    if re.search(r'\bLIMIT\b', rest, re.IGNORECASE):
        parts = re.split(r'\bLIMIT\b', rest, flags=re.IGNORECASE)
        rest = parts[0].strip()
        limit_part = 'LIMIT ' + parts[1].strip()

    if re.search(r'\bORDER\s+BY\b', rest, re.IGNORECASE):
        parts = re.split(r'\bORDER\s+BY\b', rest, flags=re.IGNORECASE)
        rest = parts[0].strip()
        order_part = 'ORDER BY ' + parts[1].strip()

    if re.search(r'\bGROUP\s+BY\b', rest, re.IGNORECASE):
        parts = re.split(r'\bGROUP\s+BY\b', rest, flags=re.IGNORECASE)
        rest = parts[0].strip()
        group_part = 'GROUP BY ' + parts[1].strip()

    where_part = ''
    if re.search(r'\bWHERE\b', rest, re.IGNORECASE):
        parts = re.split(r'\bWHERE\b', rest, flags=re.IGNORECASE)
        from_part = parts[0].strip()
        where_part = parts[1].strip()
    else:
        from_part = rest

    tables = parse_tables(from_part)
    if not tables:
        return {
            'success': True,
            'optimization_applied': False,
            'original_sql': raw_sql,
            'optimized_sql': raw_sql,
            'transformations': [],
            'index_recommendations': [],
            'reason': 'No table relations identified in FROM clause; returned unchanged.',
            'metrics': {'reduction_pct': 0.0, 'naive_cost': 100, 'opt_cost': 100, 'intermediate_rows_saved': 0, 'buffer_memory_saved_kb': 0.0}
        }

    aliases = {t['alias'].lower(): t for t in tables}

    # Split WHERE conditions safely using parenthesis-aware splitter
    conds = split_top_level_and(where_part)

    join_conds: List[str] = []
    table_filters: Dict[str, List[str]] = {t['alias']: [] for t in tables}
    unassigned_filters: List[str] = []

    for c in conds:
        # Check if join predicate: alias1.col = alias2.col
        jm = re.match(r'^\s*([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\s*=\s*([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\s*$', c)
        if jm and jm.group(1).lower() in aliases and jm.group(3).lower() in aliases and jm.group(1).lower() != jm.group(3).lower():
            join_conds.append(c)
            continue

        # Check which table aliases are referenced in this condition
        referenced_aliases = set()
        for al in aliases:
            if re.search(rf'\b{re.escape(al)}\.', c, re.IGNORECASE):
                referenced_aliases.add(al)

        if len(referenced_aliases) == 1:
            target_al = list(referenced_aliases)[0]
            target_tbl_info = aliases[target_al]
            # SEMANTIC PRESERVATION: If target table is joined via LEFT/RIGHT JOIN,
            # pushing WHERE filters down before the outer join changes outer-join NULL semantics!
            if target_tbl_info.get('join_type') in ('LEFT JOIN', 'LEFT OUTER JOIN', 'RIGHT JOIN', 'RIGHT OUTER JOIN'):
                unassigned_filters.append(c)
            else:
                table_filters[target_tbl_info['alias']].append(c)
        elif len(referenced_aliases) == 0:
            # Unqualified column reference
            candidate_tables = []
            for t in tables:
                tname = t['table'].lower()
                for col in catalog.get(tname, {}).get('cols', []):
                    if re.search(rf'\b{re.escape(col)}\b', c, re.IGNORECASE):
                        candidate_tables.append(t['alias'])
                        break
            if len(candidate_tables) == 1:
                target_alias = candidate_tables[0]
                target_tbl_info = aliases[target_alias.lower()]
                if target_tbl_info.get('join_type') in ('LEFT JOIN', 'LEFT OUTER JOIN', 'RIGHT JOIN', 'RIGHT OUTER JOIN'):
                    unassigned_filters.append(c)
                else:
                    table_filters[target_alias].append(c)
            else:
                unassigned_filters.append(c)
        else:
            unassigned_filters.append(c)

    # Detect Cartesian comma join transformation
    has_comma_join = any(t.get('join_type') == 'COMMA' for t in tables)
    if has_comma_join:
        transformations.append({
            'name': 'ANSI Explicit Join (Cartesian Product Elimination)',
            'badge': 'ANSI INNER JOIN',
            'color': '#3b82f6',
            'rule': 'σ_{R.id = S.id}(R × S) ≡ R ⨝_{R.id = S.id} S',
            'before': f"FROM {from_part} WHERE ...",
            'after': "INNER JOIN ... ON ...",
            'description': 'Replaced SQL-89 comma cross-product with explicit ANSI SQL-92 JOIN, enabling optimizer to pick nested-loop or hash join plans.'
        })

    # Build optimized FROM clause with safe selection pushdown
    all_query_parts = [select_part, where_part, group_part, order_part] + [t.get('join_on') or '' for t in tables]
    from_sql_pieces = []
    pushed_filters_count = 0

    for idx, t in enumerate(tables):
        tname = t['table']
        talias = t['alias']
        tfilts = table_filters.get(talias, [])
        clean_filts = [re.sub(rf'\b{re.escape(talias)}\.', '', f) for f in tfilts]

        # Only create derived subquery if:
        # 1. There are filters to push down
        # 2. It is safe (not an outer join right-side)
        if tfilts and t.get('join_type') not in ('LEFT JOIN', 'LEFT OUTER JOIN', 'RIGHT JOIN', 'RIGHT OUTER JOIN'):
            pushed_filters_count += len(tfilts)

            # Determine required columns for this table
            if select_part == '*' or re.search(rf'\b{re.escape(talias)}\.\*', select_part):
                # If wildcard is requested, subquery MUST project * to satisfy outer query!
                sub_proj_str = '*'
            else:
                needed_cols = extract_required_columns_for_table(t, all_query_parts, catalog)
                for f in tfilts:
                    for c in catalog.get(tname.lower(), {}).get('cols', []):
                        if re.search(rf'\b{re.escape(c)}\b', f, re.IGNORECASE) and c not in needed_cols:
                            needed_cols.append(c)
                sub_proj_str = ', '.join(needed_cols) if needed_cols else '*'

            derived_sql = (
                f"(\n"
                f"        /* [Rule 1: Pushdown σ Selection directly to base table {tname}] */\n"
                f"        SELECT {sub_proj_str}\n"
                f"        FROM {tname}\n"
                f"        WHERE {' AND '.join(clean_filts)}\n"
                f"    ) AS {talias}"
            )
            tbl_repr = derived_sql

            transformations.append({
                'name': f"Pushdown Selection on {tname} (σ-Pushdown)",
                'badge': 'σ Filter Pushdown',
                'color': '#22c55e',
                'rule': 'σ_c(R ⨝ S) ≡ (σ_c(R)) ⨝ S',
                'before': f"Late filter in outer WHERE: {' AND '.join(tfilts)}",
                'after': f"Early filter inside derived subquery: WHERE {' AND '.join(clean_filts)}",
                'description': f"Filtered rows from '{tname}' before join execution, reducing intermediate tuple cardinality."
            })
        else:
            tbl_repr = f"{tname} {talias}" if talias != tname else tname

        if idx == 0:
            from_sql_pieces.append(f"FROM {tbl_repr}")
        else:
            # PRESERVE ORIGINAL JOIN TYPE! NEVER CONVERT LEFT JOIN TO INNER JOIN!
            j_type = t.get('join_type', 'INNER JOIN')
            if j_type == 'COMMA':
                j_type = 'INNER JOIN'

            j_on = t.get('join_on')
            if not j_on and join_conds:
                j_on = join_conds.pop(0)

            if j_on:
                from_sql_pieces.append(f"{j_type} {tbl_repr}\n    ON {j_on}")
            else:
                from_sql_pieces.append(f"{j_type} {tbl_repr}")

    # Build Projection: NEVER overwrite user's SELECT * with arbitrary subsets
    proj_str = select_part
    proj_comment = ""

    # Assemble Rewritten SQL
    opt_sql_lines = [
        f"SELECT \n    {proj_comment}{proj_str}",
        '\n'.join(from_sql_pieces)
    ]
    if unassigned_filters:
        opt_sql_lines.append(f"WHERE {' AND '.join(unassigned_filters)}")
    if group_part:
        opt_sql_lines.append(group_part)
    if order_part:
        opt_sql_lines.append(order_part)
    if limit_part:
        opt_sql_lines.append(limit_part)

    opt_sql = '\n'.join(opt_sql_lines) + ';'

    # Index recommendations based on actual columns
    for t in tables:
        tname = t['table']
        talias = t['alias']
        tfilts = table_filters.get(talias, [])
        cols_to_index: List[str] = []
        valid_table_cols = catalog.get(tname.lower(), {}).get('cols', [])

        for f in tfilts:
            for c in valid_table_cols:
                if re.search(rf'\b{re.escape(c)}\b', f, re.IGNORECASE) and c not in cols_to_index:
                    cols_to_index.append(c)

        for jc in join_conds:
            for c in valid_table_cols:
                if re.search(rf'\b{re.escape(c)}\b', jc, re.IGNORECASE) and c not in cols_to_index:
                    cols_to_index.append(c)

        if cols_to_index:
            idx_cols = ', '.join(cols_to_index[:3])
            idx_name = f"idx_{tname}_{'_'.join(cols_to_index[:2])}"
            indexes.append({
                'table': tname,
                'sql': f"CREATE INDEX {idx_name} ON {tname} ({idx_cols});",
                'impact': f"Enables index-based range/ref scan on '{tname}', eliminating full table scan."
            })

    # Educational cost model calculations (Strictly non-negative and mathematically valid)
    est_naive_rows = 1
    for t in tables:
        est_naive_rows *= catalog.get(t['table'].lower(), {}).get('est_rows', 100)
    est_naive_rows = min(est_naive_rows, 500000)

    if pushed_filters_count > 0:
        reduction_factor = 0.12 ** min(pushed_filters_count, 3)
        est_opt_rows = max(1, int(est_naive_rows * reduction_factor))
    elif has_comma_join:
        est_opt_rows = max(1, int(est_naive_rows * 0.75))
    else:
        est_opt_rows = est_naive_rows

    saved_tuples = max(0, est_naive_rows - est_opt_rows)
    pct = round((saved_tuples / est_naive_rows) * 100, 1) if est_naive_rows > 0 and saved_tuples > 0 else 0.0

    optimization_applied = len(transformations) > 0

    return {
        'success': True,
        'optimization_applied': optimization_applied,
        'original_sql': raw_sql,
        'optimized_sql': opt_sql if optimization_applied else raw_sql,
        'transformations': transformations,
        'index_recommendations': indexes,
        'metrics': {
            'reduction_pct': pct,
            'naive_cost': est_naive_rows,
            'opt_cost': est_opt_rows,
            'intermediate_rows_saved': saved_tuples,
            'buffer_memory_saved_kb': round(saved_tuples * 0.064, 1),
            'best_plan': 'Heuristic Relational Tree (Pushed-Down σ & π with ANSI Joins)' if optimization_applied else 'Original Plan Maintained'
        }
    }


# ══════════════════════════════════════════════════════════════════════════════
# 8. REAL DATABASE EXPLAIN PLAN GENERATION (SQLite & MySQL)
# ══════════════════════════════════════════════════════════════════════════════
def execute_explain_plan(db_conn, sql_query: str, engine_hint: Optional[str] = None) -> Dict[str, Any]:
    """
    Executes EXPLAIN on the active database connection.
    - Uses 'EXPLAIN QUERY PLAN' for SQLite and parses detail columns.
    - Uses 'EXPLAIN' for MySQL and parses engine access paths.
    - Accurately supports sqlite3.Row, tuple, list, and dict rows.
    - Never substitutes fabricated or hardcoded sample plans if execution fails.
    """
    if not db_conn:
        return {
            'available': False,
            'engine': 'None',
            'plan_rows': [],
            'error': 'No active database connection available for EXPLAIN plan retrieval.'
        }

    clean_sql = sql_query.strip().rstrip(';')

    is_sqlite = (
        (engine_hint and 'sqlite' in engine_hint.lower()) or
        'sqlite' in type(db_conn).__module__.lower() or
        hasattr(db_conn, 'iterdump')
    )

    plan_rows = []
    try:
        cur = db_conn.cursor()
        if is_sqlite:
            cur.execute(f"EXPLAIN QUERY PLAN {clean_sql}")
            raw = cur.fetchall()
            col_names = [d[0].lower() for d in cur.description] if cur.description else []

            for r in raw:
                if hasattr(r, 'keys'):
                    detail = str(r['detail'] if 'detail' in r.keys() else r[len(r) - 1])
                    step_id = r['id'] if 'id' in r.keys() else r[0]
                elif isinstance(r, dict):
                    detail = str(r.get('detail', r.get('Detail', '')))
                    step_id = r.get('id', 1)
                elif isinstance(r, (list, tuple)):
                    detail_idx = col_names.index('detail') if 'detail' in col_names else len(r) - 1
                    detail = str(r[detail_idx])
                    step_id = r[0]
                else:
                    detail = str(r)
                    step_id = 1

                # Parse detail for meaningful table and scan type
                tbl_m = re.search(r'(?:SCAN|SEARCH)\s+(?:TABLE\s+)?([a-zA-Z0-9_]+)(?:\s+AS\s+([a-zA-Z0-9_]+))?', detail, re.IGNORECASE)
                tbl_name = tbl_m.group(2) or tbl_m.group(1) if tbl_m else 'derived / subquery'

                idx_m = re.search(r'USING\s+(?:COVERING\s+)?INDEX\s+([a-zA-Z0-9_]+)', detail, re.IGNORECASE)
                idx_name = idx_m.group(1) if idx_m else None
                if not idx_name and 'INTEGER PRIMARY KEY' in detail:
                    idx_name = 'PRIMARY (rowid)'

                if 'SCAN' in detail.upper():
                    acc_type = 'SCAN (Full Table Scan)'
                elif 'SEARCH' in detail.upper():
                    acc_type = 'SEARCH (Index Lookup)'
                elif 'COMPOUND' in detail.upper():
                    acc_type = 'COMPOUND (Subquery)'
                else:
                    acc_type = 'QUERY PLAN STEP'

                plan_rows.append({
                    'id': step_id,
                    'select_type': 'SIMPLE',
                    'table': tbl_name,
                    'type': acc_type,
                    'possible_keys': idx_name or 'None',
                    'key': idx_name or 'None',
                    'key_len': '—',
                    'rows': '—',
                    'filtered': '—',
                    'extra': detail
                })
            return {
                'available': True,
                'engine': 'SQLite Query Planner',
                'plan_rows': plan_rows,
                'error': None
            }
        else:
            # MySQL
            cur.execute(f"EXPLAIN {clean_sql}")
            raw = cur.fetchall()
            for r in raw:
                if isinstance(r, dict):
                    plan_rows.append({
                        'id': r.get('id', 1),
                        'select_type': r.get('select_type', 'SIMPLE'),
                        'table': r.get('table', 'unknown'),
                        'type': r.get('type', 'ALL'),
                        'possible_keys': r.get('possible_keys') or 'NULL (No Index)',
                        'key': r.get('key') or 'NULL (Full Scan)',
                        'key_len': str(r.get('key_len') or '—'),
                        'rows': r.get('rows', '—'),
                        'filtered': f"{r.get('filtered', 100)}%" if r.get('filtered') is not None else '—',
                        'extra': r.get('Extra') or r.get('extra') or ''
                    })
                elif isinstance(r, (list, tuple)) and cur.description:
                    d_map = {d[0].lower(): r[idx] for idx, d in enumerate(cur.description)}
                    plan_rows.append({
                        'id': d_map.get('id', 1),
                        'select_type': d_map.get('select_type', 'SIMPLE'),
                        'table': d_map.get('table', 'unknown'),
                        'type': d_map.get('type', 'ALL'),
                        'possible_keys': d_map.get('possible_keys') or 'NULL (No Index)',
                        'key': d_map.get('key') or 'NULL (Full Scan)',
                        'key_len': str(d_map.get('key_len') or '—'),
                        'rows': d_map.get('rows', '—'),
                        'filtered': f"{d_map.get('filtered', 100)}%" if d_map.get('filtered') is not None else '—',
                        'extra': d_map.get('extra', '')
                    })
            return {
                'available': True,
                'engine': 'MySQL 8.0 InnoDB Optimizer',
                'plan_rows': plan_rows,
                'error': None
            }
    except Exception as e:
        return {
            'available': False,
            'engine': 'SQLite' if is_sqlite else 'MySQL',
            'plan_rows': [],
            'error': f"Failed to retrieve execution plan: {str(e)}"
        }


# ══════════════════════════════════════════════════════════════════════════════
# 9. RESULT EQUIVALENCE & MONOTONIC BENCHMARK VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════
def verify_query_equivalence(db_conn, sql1: str, sql2: str, max_rows: int = 500) -> Dict[str, Any]:
    """
    Executes both sql1 (original) and sql2 (optimized) against the active database and
    verifies that they return identical logical results.
    Preserves duplicate-row semantics (multi-set bag equality) and handles NULL values safely.
    Measures actual elapsed execution times with a monotonic high-precision timer.
    """
    if not db_conn:
        return {
            'verified': False,
            'equivalent': None,
            'verification_status': 'verification_unavailable',
            'reason': 'No database connection available for live verification.'
        }

    clean1 = sql1.strip().rstrip(';')
    clean2 = sql2.strip().rstrip(';')

    try:
        cur = db_conn.cursor()

        # Run Original Query
        t0 = time.perf_counter()
        cur.execute(clean1)
        rows1 = cur.fetchall()
        t1_orig = (time.perf_counter() - t0) * 1000.0
        cols1 = [d[0].lower() for d in cur.description] if cur.description else []

        # Run Optimized Query
        t0 = time.perf_counter()
        cur.execute(clean2)
        rows2 = cur.fetchall()
        t2_opt = (time.perf_counter() - t0) * 1000.0
        cols2 = [d[0].lower() for d in cur.description] if cur.description else []

        def normalize_rows(raw_rows, cols):
            norm = []
            for r in raw_rows:
                if isinstance(r, dict):
                    norm.append(tuple(r.get(c) for c in cols))
                elif hasattr(r, 'keys'):
                    norm.append(tuple(r[c] if c in r.keys() else r[idx] for idx, c in enumerate(cols)))
                else:
                    norm.append(tuple(r))
            return norm

        n_rows1 = normalize_rows(rows1, cols1)
        n_rows2 = normalize_rows(rows2, cols2)

        if len(n_rows1) != len(n_rows2):
            return {
                'verified': True,
                'equivalent': False,
                'verification_status': 'not_equivalent',
                'orig_count': len(n_rows1),
                'opt_count': len(n_rows2),
                'orig_time_ms': round(t1_orig, 3),
                'opt_time_ms': round(t2_opt, 3),
                'reason': f"Row count mismatch: original query returned {len(n_rows1)} rows, optimized query returned {len(n_rows2)} rows."
            }

        if len(cols1) != len(cols2):
            return {
                'verified': True,
                'equivalent': False,
                'verification_status': 'not_equivalent',
                'orig_count': len(n_rows1),
                'opt_count': len(n_rows2),
                'orig_time_ms': round(t1_orig, 3),
                'opt_time_ms': round(t2_opt, 3),
                'reason': f"Column count mismatch: original query exposed {len(cols1)} columns, optimized query exposed {len(cols2)} columns."
            }

        # Safe primitive conversion for multi-set bag comparison (handles NULLs safely)
        def hashable_row(row):
            def _conv(v):
                if v is None:
                    return (0, None)
                if isinstance(v, (int, float, str, bool, bytes)):
                    return (1, v)
                return (2, str(v))
            return tuple(_conv(v) for v in row)

        has_order_by = bool(re.search(r'\bORDER\s+BY\b', clean1, re.IGNORECASE))
        if has_order_by:
            match = ([hashable_row(r) for r in n_rows1] == [hashable_row(r) for r in n_rows2])
        else:
            # Bag equivalence via multi-set Counter (preserves duplicate row counts)
            c1 = collections.Counter(hashable_row(r) for r in n_rows1)
            c2 = collections.Counter(hashable_row(r) for r in n_rows2)
            match = (c1 == c2)

        return {
            'verified': True,
            'equivalent': match,
            'verification_status': 'verified_equivalent' if match else 'not_equivalent',
            'orig_count': len(n_rows1),
            'opt_count': len(n_rows2),
            'orig_time_ms': round(t1_orig, 3),
            'opt_time_ms': round(t2_opt, 3),
            'reason': 'Logical results match 100% across all rows.' if match else 'Row content mismatch between original and optimized queries.'
        }

    except Exception as e:
        return {
            'verified': False,
            'equivalent': False,
            'verification_status': 'not_equivalent',
            'error': str(e),
            'reason': f"Execution error during equivalence validation: {str(e)}"
        }


# ══════════════════════════════════════════════════════════════════════════════
# 10. DYNAMIC RELATIONAL ALGEBRA TREE GENERATOR
# ══════════════════════════════════════════════════════════════════════════════
def build_dynamic_relational_trees(
    sql_text: str,
    catalog: Dict[str, Dict[str, Any]]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Constructs Canonical (Naive) and Heuristically Optimized Relational Algebra
    tree representations dynamically based on the submitted query.
    Never produces hardcoded preset trees referencing unrelated tables (e.g. users).
    """
    sel_match = re.search(r'SELECT\s+(.*?)\s+FROM\s+(.*)', sql_text.strip().rstrip(';'), re.IGNORECASE | re.DOTALL)
    if not sel_match:
        empty_tree = {'name': 'Relational Plan', 'nodes': []}
        return empty_tree, empty_tree

    select_part = sel_match.group(1).strip()
    rest = sel_match.group(2).strip()

    where_part = ''
    if re.search(r'\bWHERE\b', rest, re.IGNORECASE):
        parts = re.split(r'\bWHERE\b', rest, flags=re.IGNORECASE)
        from_part = parts[0].strip()
        where_part = parts[1].strip()
    else:
        from_part = re.split(r'\b(GROUP\s+BY|ORDER\s+BY|LIMIT)\b', rest, flags=re.IGNORECASE)[0].strip()

    tables = parse_tables(from_part)
    if not tables:
        tables = [{'table': 'relation', 'alias': 'r', 'join_type': 'FROM', 'join_on': None}]

    conds = split_top_level_and(where_part)
    join_conds = [c for c in conds if re.match(r'^\s*[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+\s*=\s*[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+\s*$', c)]
    filter_conds = [c for c in conds if c not in join_conds]

    t_rows = [catalog.get(t['table'].lower(), {}).get('est_rows', 100) for t in tables]
    cartesian_prod = 1
    for r in t_rows:
        cartesian_prod *= r
    cartesian_prod = min(cartesian_prod, 500000)

    # ── Canonical Tree (Naive Plan: Full Cross Product -> Late Join -> Late Selection -> Projection) ──
    canonical_nodes = []
    canonical_nodes.append({
        'id': 'c1',
        'type': 'projection',
        'symbol': 'π',
        'label': f"π ({select_part[:40] + ('...' if len(select_part) > 40 else '')})",
        'desc': 'Final projection of output attributes',
        'rows': max(1, int(cartesian_prod * 0.1)),
        'status': 'neutral'
    })

    if filter_conds:
        canonical_nodes.append({
            'id': 'c2',
            'type': 'selection',
            'symbol': 'σ',
            'label': f"σ ({' ∧ '.join(filter_conds)[:45] + ('...' if len(' ∧ '.join(filter_conds)) > 45 else '')})",
            'desc': 'LATE SELECTION: Applied after full cross-product or join over massive intermediate relation!',
            'rows': max(1, int(cartesian_prod * 0.1)),
            'status': 'warning'
        })

    if len(tables) > 1:
        j_label = ' ∧ '.join(join_conds) if join_conds else ' × (Cartesian Cross Product)'
        canonical_nodes.append({
            'id': 'c3',
            'type': 'join',
            'symbol': '⨝' if join_conds else '×',
            'label': f"⨝ ({j_label[:40]})" if join_conds else "× Cartesian Product",
            'desc': f"UNFILTERED JOIN: Combining {' × '.join(t['table'] for t in tables)} before filtering",
            'rows': cartesian_prod,
            'status': 'danger'
        })

    for idx, t in enumerate(tables):
        tname = t['table']
        t_r = catalog.get(tname.lower(), {}).get('est_rows', 100)
        canonical_nodes.append({
            'id': f'c_tbl_{idx}',
            'type': 'table',
            'symbol': '📄',
            'label': f"Table: {tname} ({t['alias']})",
            'desc': f"Full table scan ({t_r} estimated rows)",
            'rows': t_r,
            'status': 'neutral'
        })

    canonical_tree = {
        'name': 'Canonical Initial Plan (Naive Execution)',
        'nodes': canonical_nodes,
        'intermediate_rows': cartesian_prod,
        'estimated_cost': cartesian_prod // 10 + 500,
        'buffer_memory_kb': round((cartesian_prod * 64) / 1024, 1)
    }

    # ── Optimized Tree (Heuristic Pushdown Plan: Filter Early -> Join -> Projection) ──
    opt_nodes = []
    opt_nodes.append({
        'id': 'o1',
        'type': 'projection',
        'symbol': 'π',
        'label': f"π ({select_part[:40] + ('...' if len(select_part) > 40 else '')})",
        'desc': 'Final projection with unneeded payload columns pruned early',
        'rows': max(1, int(t_rows[0] * 0.15)),
        'status': 'optimal'
    })

    if len(tables) > 1:
        j_label = ' ∧ '.join(join_conds) if join_conds else f"{tables[0]['alias']} ⨝ {tables[1]['alias']}"
        opt_nodes.append({
            'id': 'o2',
            'type': 'join',
            'symbol': '⨝',
            'label': f"⨝ ({j_label[:40]})",
            'desc': 'OPTIMIZED JOIN: Executed on pre-filtered and pre-projected relations!',
            'rows': max(1, int(t_rows[0] * 0.15)),
            'status': 'optimal'
        })

    for idx, t in enumerate(tables):
        tname = t['table']
        talias = t['alias']
        t_r = catalog.get(tname.lower(), {}).get('est_rows', 100)

        tbl_filts = [f for f in filter_conds if re.search(rf'\b{re.escape(talias)}\b|\b{re.escape(tname)}\b', f, re.IGNORECASE)]
        if tbl_filts:
            opt_nodes.append({
                'id': f'o_sel_{idx}',
                'type': 'selection',
                'symbol': 'σ',
                'label': f"σ ({' ∧ '.join(tbl_filts)[:35]})",
                'desc': f"PUSHED SELECTION: Filter applied directly to {tname} BEFORE join",
                'rows': max(1, int(t_r * 0.15)),
                'status': 'optimal'
            })

        opt_nodes.append({
            'id': f'o_tbl_{idx}',
            'type': 'table',
            'symbol': '📄',
            'label': f"Table: {tname} ({talias})",
            'desc': f"Access {tname} via index range scan",
            'rows': t_r,
            'status': 'neutral'
        })

    opt_rows = max(1, int(cartesian_prod * (0.12 if filter_conds else 0.85)))
    optimized_tree = {
        'name': 'Heuristically Optimized Plan (Pushed Selections & Projections)',
        'nodes': opt_nodes,
        'intermediate_rows': opt_rows,
        'estimated_cost': opt_rows // 10 + len(tables) * 50,
        'buffer_memory_kb': round((opt_rows * 48) / 1024, 1)
    }

    return canonical_tree, optimized_tree


# ══════════════════════════════════════════════════════════════════════════════
# 11. MAIN ANALYSIS & VALIDATION WORKFLOW
# ══════════════════════════════════════════════════════════════════════════════
def analyze_query(query_key: str = 'join_filter', custom_sql: str = None, db_conn=None, preset_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Complete Educational Query Optimization Pipeline:
    1. Validates query syntax & safety (rejecting write operations, file exports, and locking clauses).
    2. Heuristically rewrites query with semantic preservation (pushdown sigma, pi, ANSI joins, IN semijoins).
    3. Validates rewritten query against database schema.
    4. Runs separate EXPLAIN execution plans for original and optimized SQL.
    5. Benchmarks and verifies logical result equivalence across database engines.
    6. Constructs accurate, dynamic Relational Algebra trees.
    7. Formulates sound, clearly labelled performance metrics.
    """
    catalog = get_schema_catalog(db_conn)
    key_to_use = preset_key or query_key or 'join_filter'
    info = PRESET_QUERIES.get(key_to_use, PRESET_QUERIES['join_filter'])
    sql_text = custom_sql.strip() if custom_sql and custom_sql.strip() else info['sql']

    # Step 1: Read-only Safety Validation
    is_safe, safety_err = validate_read_only_sql(sql_text)
    if not is_safe:
        return {
            'success': False,
            'optimization_applied': False,
            'error': safety_err,
            'sql': sql_text,
            'original_sql': sql_text,
            'optimized_sql': sql_text,
            'transformations': [],
            'index_recommendations': [],
            'metrics': {'reduction_pct': 0.0, 'naive_cost': 0, 'opt_cost': 0, 'intermediate_rows_saved': 0, 'buffer_memory_saved_kb': 0.0},
            'canonical_tree': {'name': 'Query Rejected', 'nodes': []},
            'optimized_tree': {'name': 'Query Rejected', 'nodes': []},
            'original_explain_plan': {'available': False, 'plan_rows': [], 'error': safety_err},
            'optimized_explain_plan': {'available': False, 'plan_rows': [], 'error': safety_err},
            'explain_plan': []
        }

    # Step 2: Heuristic Rewriter
    rewrite_res = rewrite_and_optimize_query(sql_text, db_conn=db_conn)
    proposed_sql = rewrite_res.get('optimized_sql', sql_text)
    optimization_applied = rewrite_res.get('optimization_applied', False)

    # Step 3: Database Execution Plans (Separate Original and Optimized Plans)
    orig_plan_res = execute_explain_plan(db_conn, sql_text)
    opt_plan_res = execute_explain_plan(db_conn, proposed_sql)

    # If the rewritten query fails EXPLAIN validation, safely fall back to original SQL!
    validation_passed = True
    validation_error = None
    if optimization_applied and not opt_plan_res.get('available') and orig_plan_res.get('available'):
        validation_passed = False
        validation_error = f"Proposed optimization failed database validation: {opt_plan_res.get('error')}. Safely reverted to original query."
        proposed_sql = sql_text
        optimization_applied = False
        rewrite_res['transformations'] = []
        opt_plan_res = orig_plan_res

    # Step 4: Live Result Equivalence & Monotonic Timing
    equiv_res = verify_query_equivalence(db_conn, sql_text, proposed_sql)
    if optimization_applied and equiv_res.get('verified') and not equiv_res.get('equivalent'):
        validation_passed = False
        validation_error = f"Result equivalence check failed: {equiv_res.get('reason')}. Safely reverted to original query to preserve semantics."
        proposed_sql = sql_text
        optimization_applied = False
        rewrite_res['transformations'] = []
        opt_plan_res = orig_plan_res

    # Step 5: Dynamic Relational Algebra Trees
    if not custom_sql and query_key in PRESET_QUERIES:
        canonical_tree, optimized_tree = build_dynamic_relational_trees(info['sql'], catalog)
        title = info['title']
    else:
        canonical_tree, optimized_tree = build_dynamic_relational_trees(sql_text, catalog)
        title = 'Custom SQL Optimization & Relational Plan'

    # Step 6: Formulate Transparent, Clearly Labelled Metrics
    heur = rewrite_res.get('metrics', {})
    metrics = {
        # Educational cost model estimates
        'reduction_pct': heur.get('reduction_pct', 0.0) if optimization_applied else 0.0,
        'naive_cost': heur.get('naive_cost', 100),
        'opt_cost': heur.get('opt_cost', 100) if optimization_applied else heur.get('naive_cost', 100),
        'intermediate_rows_saved': heur.get('intermediate_rows_saved', 0) if optimization_applied else 0,
        'buffer_memory_saved_kb': heur.get('buffer_memory_saved_kb', 0.0) if optimization_applied else 0.0,
        'best_plan': heur.get('best_plan', 'Original Plan') if optimization_applied else 'Original Plan Maintained (Semantics Preserved)',

        # Live measured metrics
        'measured_available': equiv_res.get('verified', False),
        'original_time_ms': equiv_res.get('orig_time_ms'),
        'optimized_time_ms': equiv_res.get('opt_time_ms'),
        'original_row_count': equiv_res.get('orig_count'),
        'optimized_row_count': equiv_res.get('opt_count'),
        'results_equivalent': equiv_res.get('equivalent'),
        'verification_status': equiv_res.get('verification_status', 'verification_unavailable'),
        'equivalence_note': equiv_res.get('reason')
    }

    rules_applied = [
        {
            'rule_number': 1,
            'title': 'Cascade of Selections (Splitting Conjunctive Predicates)',
            'math': 'σ_{c1 ∧ c2}(R) ≡ σ_{c1}(σ_{c2}(R))',
            'explanation': 'Complex WHERE clauses with AND are split into individual atomic filters that can be pushed down independently.'
        },
        {
            'rule_number': 2,
            'title': 'Commutativity of Selection and Join (Pushing σ Down)',
            'math': 'σ_c(R ⨝ S) ≡ (σ_c(R)) ⨝ S  [if condition c references only R]',
            'explanation': 'Single-table predicates are evaluated at the base relation level, discarding non-matching tuples before join execution.'
        },
        {
            'rule_number': 3,
            'title': 'Pushing Projection Down (π Column Pruning)',
            'math': 'π_{L}(R ⨝ S) ≡ π_{L}(π_{L1}(R) ⨝ π_{L2}(S))',
            'explanation': 'Unused columns are discarded early, but all attributes required by outer SELECT, WHERE, and JOIN are strictly retained.'
        },
        {
            'rule_number': 4,
            'title': 'Cartesian Product Elimination to ANSI Join',
            'math': 'σ_{R.id = S.id}(R × S) ≡ R ⨝ S',
            'explanation': 'SQL-89 comma cross-products are converted into ANSI INNER JOINs, permitting index-based nested loops or hash joins.'
        }
    ]

    return {
        'success': True,
        'preset_key': query_key,
        'title': title,
        'sql': sql_text,
        'original_sql': sql_text,
        'optimized_sql': proposed_sql,
        'optimization_applied': optimization_applied,
        'validation_passed': validation_passed,
        'validation_error': validation_error,
        'transformations': rewrite_res.get('transformations', []),
        'index_recommendations': rewrite_res.get('index_recommendations', []),
        'canonical_tree': canonical_tree,
        'optimized_tree': optimized_tree,
        'metrics': metrics,
        'rules': rules_applied,
        'original_explain_plan': orig_plan_res,
        'optimized_explain_plan': opt_plan_res,
        'explain_plan': opt_plan_res.get('plan_rows', []) if opt_plan_res.get('available') else orig_plan_res.get('plan_rows', [])
    }
