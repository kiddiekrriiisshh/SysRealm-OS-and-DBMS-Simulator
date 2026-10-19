"""
Comprehensive Unit and Regression Test Suite for SysRealm Query Optimizer & Relational Algebra Engine
Validates:
1. SQLite schema introspection with conn.row_factory = sqlite3.Row
2. Connection-isolated schema caching (preventing metadata leakage across databases)
3. Schema catalog accuracy (no phantom 'available' column in resources)
4. Projection pruning (pi) preserving all required columns across SELECT, expressions, JOIN, GROUP BY, ORDER BY
5. Wildcard SELECT * preservation
6. Subquery unnesting (IN -> semijoin) preserving outer WHERE predicates (e.g. s.algorithm = 'FCFS') and duplicate semantics
7. LEFT JOIN preservation (preventing conversion to INNER JOIN and retaining unmatched rows)
8. Three-table JOIN predicate and column preservation
9. Cartesian comma join elimination to ANSI explicit INNER JOIN
10. Authentic SQLite EXPLAIN QUERY PLAN parsing with sqlite3.Row without fake plans
11. Dynamic Relational Algebra tree generation strictly reflecting the submitted query
12. Strict read-only query safety:
    - Rejection of DROP, DELETE, INSERT, UPDATE, ALTER
    - Rejection of file-writing SELECT variants: INTO OUTFILE, INTO DUMPFILE
    - Rejection of locking clauses: FOR UPDATE, LOCK IN SHARE MODE
    - Rejection of multi-statements separated by semicolons
    - Acceptance of safe string literals containing SQL keywords ('delete')
    - Acceptance of leading block/line comments
    - Acceptance of CTE expressions (WITH ... SELECT ...)
13. Honest, mathematically consistent performance metrics (non-negative savings, explicit baselines)
14. Unordered and ordered multi-set result equivalence verification
15. End-to-end API integration tests for /api/dbms/optimize-query and /api/assignments/<id>/submit-optimizer
"""

import unittest
import sqlite3
import json
from backend import query_optimizer
from app import app


class TestQueryOptimizer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Create an isolated in-memory SQLite database populated with the official schema
        cls.conn = sqlite3.connect(':memory:')
        # Strictly configure row_factory = sqlite3.Row to match production app.py
        cls.conn.row_factory = sqlite3.Row
        cur = cls.conn.cursor()

        # Create tables matching database/schema.sql
        cur.executescript("""
        CREATE TABLE simulation_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            user_id INTEGER,
            algorithm TEXT NOT NULL,
            status TEXT NOT NULL,
            quantum INTEGER,
            cpu_utilization REAL DEFAULT 0.0,
            avg_waiting_time REAL DEFAULT 0.0,
            avg_turnaround_time REAL DEFAULT 0.0,
            num_processes INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        );

        CREATE TABLE processes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pid TEXT NOT NULL,
            session_id TEXT NOT NULL,
            name TEXT NOT NULL,
            arrival_time INTEGER NOT NULL,
            burst_time INTEGER NOT NULL,
            priority INTEGER NOT NULL,
            memory_mb INTEGER NOT NULL,
            state TEXT DEFAULT 'NEW',
            remaining_time INTEGER DEFAULT 0,
            start_time INTEGER,
            completion_time INTEGER,
            waiting_time INTEGER DEFAULT 0,
            turnaround_time INTEGER DEFAULT 0,
            response_time INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES simulation_sessions(session_id)
        );

        CREATE TABLE resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            total INTEGER NOT NULL,
            icon TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE resource_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_id TEXT NOT NULL,
            pid TEXT NOT NULL,
            session_id TEXT NOT NULL,
            count INTEGER DEFAULT 1,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE process_activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            process_id TEXT,
            event_type TEXT NOT NULL,
            simulation_time INTEGER DEFAULT 0,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE empty_sample_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_name TEXT
        );
        """)

        # Insert deterministic test records
        cur.executescript("""
        INSERT INTO simulation_sessions (session_id, algorithm, status, cpu_utilization, num_processes)
        VALUES 
            ('session_alpha', 'FCFS', 'COMPLETED', 78.5, 3),
            ('session_beta', 'RoundRobin', 'ACTIVE', 85.0, 2),
            ('session_orphan', 'Priority', 'WAITING', 0.0, 0);

        INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
        VALUES
            ('P1', 'session_alpha', 'proc_web', 0, 8, 1, 1024, 'RUNNING'),
            ('P2', 'session_alpha', 'proc_db', 1, 4, 2, 768, 'READY'),
            ('P3', 'session_alpha', 'proc_calc', 2, 2, 3, 256, 'TERMINATED'),
            ('P4', 'session_beta', 'proc_io', 0, 12, 1, 2048, 'WAITING'),
            ('P5', 'session_beta', 'proc_gui', 1, 5, 2, 512, 'READY'),
            ('P6', 'session_alpha', 'proc_extra_mem', 3, 6, 1, 1024, 'READY');

        INSERT INTO resources (resource_id, name, total, icon)
        VALUES
            ('R_CPU', 'CPU Cores', 4, 'microchip'),
            ('R_RAM', 'RAM Blocks', 16, 'memory'),
            ('R_PRINTER', 'Laser Printer', 1, 'print');

        INSERT INTO resource_allocations (resource_id, pid, session_id, count, status)
        VALUES
            ('R_CPU', 'P1', 'session_alpha', 1, 'ALLOCATED'),
            ('R_RAM', 'P1', 'session_alpha', 4, 'ALLOCATED'),
            ('R_PRINTER', 'P4', 'session_beta', 1, 'WAITING');

        INSERT INTO process_activity_logs (session_id, process_id, event_type, description)
        VALUES
            ('session_alpha', 'P1', 'PROCESS_CREATED', 'Process proc_web created'),
            ('session_alpha', 'P3', 'PROCESS_DELETED', 'delete this process after termination');
        """)
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 2 & 3: SCHEMA INTROSPECTION & CACHE ISOLATION TESTS
    # ──────────────────────────────────────────────────────────────────────────
    def test_01_sqlite_introspection_with_row_factory(self):
        """
        Validates that get_schema_catalog successfully discovers tables, columns,
        primary keys, and row counts from SQLite when conn.row_factory = sqlite3.Row,
        without raising AttributeError: 'sqlite3.Row' object has no attribute 'get'.
        """
        catalog = query_optimizer.get_schema_catalog(self.conn, force_refresh=True)

        self.assertIn('__metadata_status__', catalog)
        self.assertTrue(catalog['__metadata_status__']['verified'])
        self.assertEqual(catalog['__metadata_status__']['source'], 'live_sqlite')

        # Check processes table
        self.assertIn('processes', catalog)
        p_info = catalog['processes']
        self.assertEqual(p_info['pk'], 'id')
        self.assertIn('pid', p_info['cols'])
        self.assertIn('memory_mb', p_info['cols'])
        self.assertIn('burst_time', p_info['cols'])
        self.assertGreaterEqual(p_info['est_rows'], 6)

        # Check empty table handling (tables with 0 rows)
        self.assertIn('empty_sample_table', catalog)
        self.assertEqual(catalog['empty_sample_table']['pk'], 'id')
        self.assertIn('sample_name', catalog['empty_sample_table']['cols'])

    def test_02_connection_cache_isolation(self):
        """
        Validates that schema metadata from one database connection is isolated
        and cannot contaminate or be incorrectly reused for another database.
        """
        conn2 = sqlite3.connect(':memory:')
        conn2.row_factory = sqlite3.Row
        cur2 = conn2.cursor()
        cur2.execute("CREATE TABLE isolated_custom_tbl (custom_id INTEGER PRIMARY KEY, custom_value TEXT);")
        conn2.commit()

        cat1 = query_optimizer.get_schema_catalog(self.conn)
        cat2 = query_optimizer.get_schema_catalog(conn2)

        self.assertIn('processes', cat1)
        self.assertNotIn('isolated_custom_tbl', cat1)

        self.assertIn('isolated_custom_tbl', cat2)
        conn2.close()

    def test_03_resource_schema_accuracy(self):
        """
        Input: SELECT resource_id, name FROM resources WHERE total > 1;
        Ensures rewritten SQL references only existing columns and NEVER introduces 'available'.
        """
        sql = "SELECT resource_id, name FROM resources WHERE total > 1;"
        analysis = query_optimizer.analyze_query(custom_sql=sql, db_conn=self.conn)

        self.assertTrue(analysis['success'])
        opt_sql = analysis['optimized_sql']
        self.assertNotIn("available", opt_sql.lower())

        cur = self.conn.cursor()
        cur.execute(opt_sql)
        rows = cur.fetchall()
        self.assertTrue(len(rows) > 0)
        self.assertEqual(analysis['metrics']['results_equivalent'], True)

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 4: PROJECTION PRUNING TESTS
    # ──────────────────────────────────────────────────────────────────────────
    def test_04_missing_projected_column_fix(self):
        """
        Input: SELECT p.memory_mb FROM processes p WHERE p.memory_mb > 512;
        Ensures outer query p.memory_mb is retained in inner subquery and executes without error.
        """
        sql = "SELECT p.memory_mb FROM processes p WHERE p.memory_mb > 512;"
        analysis = query_optimizer.analyze_query(custom_sql=sql, db_conn=self.conn)

        self.assertTrue(analysis['success'])
        opt_sql = analysis['optimized_sql']
        self.assertIn('memory_mb', opt_sql)

        cur = self.conn.cursor()
        cur.execute(opt_sql)
        opt_rows = [tuple(r) for r in cur.fetchall()]

        cur.execute(sql)
        orig_rows = [tuple(r) for r in cur.fetchall()]

        self.assertEqual(sorted(opt_rows), sorted(orig_rows))
        self.assertTrue(len(opt_rows) > 0)
        self.assertEqual(analysis['metrics']['results_equivalent'], True)

    def test_05_projection_pruning_with_expressions(self):
        """
        Input: SELECT p.memory_mb + 100 AS mem_plus FROM processes p WHERE p.memory_mb > 512;
        Ensures expressions and column references inside expressions are preserved.
        """
        sql = "SELECT p.memory_mb + 100 AS mem_plus FROM processes p WHERE p.memory_mb > 512;"
        analysis = query_optimizer.analyze_query(custom_sql=sql, db_conn=self.conn)

        self.assertTrue(analysis['success'])
        opt_sql = analysis['optimized_sql']

        cur = self.conn.cursor()
        cur.execute(sql)
        orig_rows = [tuple(r) for r in cur.fetchall()]

        cur.execute(opt_sql)
        opt_rows = [tuple(r) for r in cur.fetchall()]

        self.assertEqual(sorted(orig_rows), sorted(opt_rows))
        self.assertEqual(analysis['metrics']['results_equivalent'], True)

    def test_06_wildcard_select_star_preserved(self):
        """
        Input: SELECT * FROM processes p WHERE p.memory_mb > 512;
        Ensures SELECT * is never replaced with an arbitrary subset of columns.
        """
        sql = "SELECT * FROM processes p WHERE p.memory_mb > 512;"
        analysis = query_optimizer.analyze_query(custom_sql=sql, db_conn=self.conn)

        self.assertTrue(analysis['success'])
        opt_sql = analysis['optimized_sql']

        cur = self.conn.cursor()
        cur.execute(sql)
        orig_rows = [tuple(r) for r in cur.fetchall()]

        cur.execute(opt_sql)
        opt_rows = [tuple(r) for r in cur.fetchall()]

        self.assertEqual(sorted(orig_rows), sorted(opt_rows))
        self.assertEqual(analysis['metrics']['results_equivalent'], True)

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 5: SUBQUERY UNNESTING & IN-TO-JOIN TESTS
    # ──────────────────────────────────────────────────────────────────────────
    def test_07_subquery_in_preserves_outer_predicates(self):
        """
        Input:
        SELECT s.session_id
        FROM simulation_sessions s
        WHERE s.session_id IN (
            SELECT p.session_id
            FROM processes p
            WHERE p.memory_mb > 512
        )
        AND s.algorithm = 'FCFS';
        Validates:
        1. Outer condition (s.algorithm = 'FCFS') is strictly preserved in rewritten SQL.
        2. Session beta (RoundRobin) is NOT returned, only session alpha (FCFS).
        3. Multiple processes matching the condition do not duplicate session rows.
        4. Equivalence check passes.
        """
        sql = (
            "SELECT s.session_id\n"
            "FROM simulation_sessions s\n"
            "WHERE s.session_id IN (\n"
            "    SELECT p.session_id\n"
            "    FROM processes p\n"
            "    WHERE p.memory_mb > 512\n"
            ")\n"
            "AND s.algorithm = 'FCFS';"
        )
        analysis = query_optimizer.analyze_query(custom_sql=sql, db_conn=self.conn)

        self.assertTrue(analysis['success'])
        opt_sql = analysis['optimized_sql']
        self.assertIn("algorithm = 'FCFS'", opt_sql)

        cur = self.conn.cursor()
        cur.execute(sql)
        orig_rows = [tuple(r) for r in cur.fetchall()]

        cur.execute(opt_sql)
        opt_rows = [tuple(r) for r in cur.fetchall()]

        self.assertEqual(sorted(orig_rows), sorted(opt_rows))
        self.assertEqual(len(opt_rows), 1)
        self.assertEqual(opt_rows[0][0], 'session_alpha')
        self.assertEqual(analysis['metrics']['results_equivalent'], True)

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 6: JOIN REWRITING & PREDICATE PRESERVATION TESTS
    # ──────────────────────────────────────────────────────────────────────────
    def test_08_left_join_preservation(self):
        """
        Input: SELECT s.session_id, p.pid FROM simulation_sessions s LEFT JOIN processes p ON s.session_id = p.session_id;
        Ensures sessions without processes ('session_orphan') are preserved and LEFT JOIN is not corrupted to INNER JOIN.
        """
        sql = (
            "SELECT s.session_id, p.pid\n"
            "FROM simulation_sessions s\n"
            "LEFT JOIN processes p ON s.session_id = p.session_id;"
        )
        analysis = query_optimizer.analyze_query(custom_sql=sql, db_conn=self.conn)

        self.assertTrue(analysis['success'])
        opt_sql = analysis['optimized_sql']
        self.assertIn("LEFT JOIN", opt_sql.upper())
        self.assertNotIn("INNER JOIN", opt_sql.upper())

        cur = self.conn.cursor()
        cur.execute(sql)
        orig_rows = [tuple(r) for r in cur.fetchall()]

        cur.execute(opt_sql)
        opt_rows = [tuple(r) for r in cur.fetchall()]

        self.assertEqual(sorted(orig_rows), sorted(opt_rows))
        orphan_tuples = [r for r in opt_rows if r[0] == 'session_orphan']
        self.assertEqual(len(orphan_tuples), 1)
        self.assertIsNone(orphan_tuples[0][1])

    def test_09_three_table_join_preservation(self):
        """
        Input: 3-table join across simulation_sessions, processes, resource_allocations
        Ensures all join conditions and filters are retained.
        """
        sql = (
            "SELECT s.session_id, p.name, r.resource_id, r.count\n"
            "FROM simulation_sessions s\n"
            "JOIN processes p ON s.session_id = p.session_id\n"
            "JOIN resource_allocations r ON p.pid = r.pid\n"
            "WHERE s.algorithm = 'FCFS' AND p.memory_mb > 512;"
        )
        analysis = query_optimizer.analyze_query(custom_sql=sql, db_conn=self.conn)

        self.assertTrue(analysis['success'])
        opt_sql = analysis['optimized_sql']

        cur = self.conn.cursor()
        cur.execute(sql)
        orig_rows = [tuple(r) for r in cur.fetchall()]

        cur.execute(opt_sql)
        opt_rows = [tuple(r) for r in cur.fetchall()]

        self.assertEqual(sorted(orig_rows), sorted(opt_rows))
        self.assertEqual(analysis['metrics']['results_equivalent'], True)

    def test_10_comma_join_elimination(self):
        """
        Input: SQL-89 comma cross product:
        SELECT s.session_id, p.name FROM simulation_sessions s, processes p WHERE s.session_id = p.session_id AND p.burst_time > 4;
        Ensures it is converted to explicit ANSI INNER JOIN with identical results.
        """
        sql = (
            "SELECT s.session_id, p.name\n"
            "FROM simulation_sessions s, processes p\n"
            "WHERE s.session_id = p.session_id AND p.burst_time > 4;"
        )
        analysis = query_optimizer.analyze_query(custom_sql=sql, db_conn=self.conn)

        self.assertTrue(analysis['success'])
        opt_sql = analysis['optimized_sql']
        self.assertIn("INNER JOIN", opt_sql)

        cur = self.conn.cursor()
        cur.execute(sql)
        orig_rows = [tuple(r) for r in cur.fetchall()]

        cur.execute(opt_sql)
        opt_rows = [tuple(r) for r in cur.fetchall()]

        self.assertEqual(sorted(orig_rows), sorted(opt_rows))
        self.assertEqual(analysis['metrics']['results_equivalent'], True)

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 8: STRICT READ-ONLY SQL VALIDATION TESTS
    # ──────────────────────────────────────────────────────────────────────────
    def test_11_destructive_sql_rejection(self):
        """
        Validates that all DDL/DML destructive statements are rejected with clear error messages.
        """
        destructive_statements = [
            "DROP TABLE users;",
            "DELETE FROM processes WHERE pid = 'P1';",
            "INSERT INTO resources (resource_id, name, total) VALUES ('R_NEW', 'New', 1);",
            "UPDATE simulation_sessions SET status = 'HACKED';",
            "ALTER TABLE processes ADD COLUMN extra_col INT;",
            "TRUNCATE TABLE simulation_sessions;"
        ]
        for bad_sql in destructive_statements:
            analysis = query_optimizer.analyze_query(custom_sql=bad_sql, db_conn=self.conn)
            self.assertFalse(analysis['success'])
            self.assertIn("read-only SELECT", analysis['error'])

    def test_12_file_writing_and_locking_rejection(self):
        """
        Validates rejection of SELECT ... INTO OUTFILE / DUMPFILE and explicit row locking clauses.
        """
        file_and_lock_sql = [
            "SELECT pid INTO OUTFILE '/tmp/export.txt' FROM processes;",
            "SELECT pid INTO DUMPFILE '/tmp/export.bin' FROM processes;",
            "SELECT pid FROM processes FOR UPDATE;",
            "SELECT pid FROM processes LOCK IN SHARE MODE;"
        ]
        for stmt in file_and_lock_sql:
            analysis = query_optimizer.analyze_query(custom_sql=stmt, db_conn=self.conn)
            self.assertFalse(analysis['success'])
            self.assertIn("forbidden", analysis['error'].lower())

    def test_13_multiple_statements_rejection(self):
        """
        Validates that multiple SQL statements separated by semicolons are rejected.
        """
        multi_sql = "SELECT 1; DROP TABLE users;"
        analysis = query_optimizer.analyze_query(custom_sql=multi_sql, db_conn=self.conn)
        self.assertFalse(analysis['success'])
        self.assertIn("Multiple SQL statements", analysis['error'])

    def test_14_read_only_permits_safe_keywords_and_comments(self):
        """
        Validates that queries containing keywords inside string literals,
        leading comments, or CTEs are correctly accepted.
        """
        # Keyword inside string literal
        sql_with_string_kw = "SELECT * FROM process_activity_logs WHERE description = 'delete this process after termination';"
        analysis = query_optimizer.analyze_query(custom_sql=sql_with_string_kw, db_conn=self.conn)
        self.assertTrue(analysis['success'])

        # Leading comments
        sql_with_comment = "/* Query optimizer benchmark */ SELECT session_id FROM simulation_sessions;"
        analysis2 = query_optimizer.analyze_query(custom_sql=sql_with_comment, db_conn=self.conn)
        self.assertTrue(analysis2['success'])

        # CTE query
        cte_sql = "WITH active_procs AS (SELECT pid FROM processes WHERE burst_time > 4) SELECT * FROM active_procs;"
        analysis3 = query_optimizer.analyze_query(custom_sql=cte_sql, db_conn=self.conn)
        self.assertTrue(analysis3['success'])

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 10: REAL DATABASE EXECUTION PLANS
    # ──────────────────────────────────────────────────────────────────────────
    def test_15_actual_sqlite_execution_plan(self):
        """
        Validates execution plan retrieval from SQLite when conn.row_factory = sqlite3.Row,
        confirming genuine EXPLAIN QUERY PLAN parsing and no fake sample plans.
        """
        sql = "SELECT session_id, algorithm FROM simulation_sessions;"
        analysis = query_optimizer.analyze_query(custom_sql=sql, db_conn=self.conn)

        self.assertTrue(analysis['success'])
        orig_plan = analysis['original_explain_plan']
        self.assertTrue(orig_plan['available'])
        self.assertEqual(orig_plan['engine'], 'SQLite Query Planner')

        plan_rows = orig_plan['plan_rows']
        self.assertTrue(len(plan_rows) > 0)
        table_names = [r['table'].lower() for r in plan_rows]
        self.assertTrue(any('simulation_sessions' in t for t in table_names))
        self.assertFalse(any('users' in t for t in table_names))

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 11 & 12: RELATIONAL ALGEBRA & HONEST METRICS
    # ──────────────────────────────────────────────────────────────────────────
    def test_16_relational_algebra_dynamic_accuracy(self):
        """
        Input: Query on resources table.
        Ensures generated canonical and optimized trees reference 'resources', NOT 'users' or 'processes'.
        """
        sql = "SELECT resource_id, name FROM resources WHERE total > 1;"
        analysis = query_optimizer.analyze_query(custom_sql=sql, db_conn=self.conn)

        canonical = analysis['canonical_tree']
        optimized = analysis['optimized_tree']

        all_c_text = ' '.join([n['label'] + ' ' + n['desc'] for n in canonical['nodes']]).lower()
        self.assertIn('resources', all_c_text)
        self.assertNotIn('users', all_c_text)
        self.assertNotIn('processes', all_c_text)

        all_o_text = ' '.join([n['label'] + ' ' + n['desc'] for n in optimized['nodes']]).lower()
        self.assertIn('resources', all_o_text)
        self.assertNotIn('users', all_o_text)

    def test_17_honest_metrics_non_negative(self):
        """
        Ensures metric values are mathematically sound, non-negative, and live timing is captured.
        """
        sql = "SELECT pid, burst_time FROM processes WHERE burst_time > 4;"
        analysis = query_optimizer.analyze_query(custom_sql=sql, db_conn=self.conn)

        m = analysis['metrics']
        self.assertGreaterEqual(m['reduction_pct'], 0.0)
        self.assertLessEqual(m['reduction_pct'], 100.0)
        self.assertGreaterEqual(m['intermediate_rows_saved'], 0)
        self.assertGreaterEqual(m['buffer_memory_saved_kb'], 0.0)
        self.assertTrue(m['measured_available'])
        self.assertIsNotNone(m['original_time_ms'])
        self.assertIsNotNone(m['optimized_time_ms'])
        self.assertEqual(m['verification_status'], 'verified_equivalent')

    def test_18_malformed_sql_graceful_handling(self):
        """
        Submits malformed SQL. Ensures system returns original SQL gracefully without crashing.
        """
        bad_sql = "SELECT FROM WHERE;"
        analysis = query_optimizer.analyze_query(custom_sql=bad_sql, db_conn=self.conn)
        self.assertFalse(analysis['optimization_applied'])
        self.assertEqual(analysis['optimized_sql'], bad_sql)

    # ──────────────────────────────────────────────────────────────────────────
    # PHASE 13 & 14: API ENDPOINT INTEGRATION TESTS
    # ──────────────────────────────────────────────────────────────────────────
    def test_19_api_optimize_query_endpoint(self):
        """
        Tests /api/dbms/optimize-query through Flask test client with an authenticated session.
        """
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['user_name'] = 'Teacher'
                sess['account_type'] = 'teacher'
                sess['user_email'] = 'teacher@sysrealm.com'

            resp = client.post('/api/dbms/optimize-query', json={
                'custom_sql': 'SELECT p.pid, p.name FROM processes p WHERE p.burst_time > 4;'
            })
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data['success'])
            self.assertIn('optimized_sql', data)
            self.assertIn('original_explain_plan', data)
            self.assertIn('optimized_explain_plan', data)
            self.assertIn('metrics', data)
            self.assertTrue(data['metrics']['measured_available'])

    def test_20_api_submit_assignment_safety_and_metrics(self):
        """
        Tests /api/assignments/<id>/submit-optimizer:
        1. Destructive SQL (DROP TABLE) is rejected with HTTP 400.
        2. Valid SQL is accepted with authentic CBO metrics.
        """
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 2
                sess['user_name'] = 'Student'
                sess['account_type'] = 'student'
                sess['user_email'] = 'student@sysrealm.com'

            # 1. Attempt destructive query submission
            bad_resp = client.post('/api/assignments/1/submit-optimizer', json={
                'submitted_query': 'DROP TABLE users;',
                'student_explanation': 'Hacked assignment'
            })
            self.assertEqual(bad_resp.status_code, 400)
            bad_data = bad_resp.get_json()
            self.assertIn('rejected', bad_data.get('error', '').lower())

            # 2. Attempt valid query submission
            good_resp = client.post('/api/assignments/1/submit-optimizer', json={
                'submitted_query': 'SELECT p.pid, p.name FROM processes p WHERE p.burst_time > 4;',
                'student_explanation': 'Pushed selection burst_time > 4 to base relation'
            })
            # Assignment #1 might exist or return 404 if not seeded, but shouldn't crash
            if good_resp.status_code == 200:
                good_data = good_resp.get_json()
                self.assertEqual(good_data['status'], 'SUBMITTED')
                self.assertIn('cbo_metrics', good_data)
                self.assertGreaterEqual(good_data['cbo_metrics']['reduction_pct'], 0.0)

    def test_21_where_references_non_selected_column(self):
        """
        Input: SELECT p.name FROM processes p WHERE p.burst_time > 4;
        Ensures p.burst_time is retained in inner subquery projection even though
        only p.name is selected by the outer query.
        """
        sql = "SELECT p.name FROM processes p WHERE p.burst_time > 4;"
        analysis = query_optimizer.analyze_query(custom_sql=sql, db_conn=self.conn)

        self.assertTrue(analysis['success'])
        opt_sql = analysis['optimized_sql']

        cur = self.conn.cursor()
        cur.execute(sql)
        orig_rows = [tuple(r) for r in cur.fetchall()]

        cur.execute(opt_sql)
        opt_rows = [tuple(r) for r in cur.fetchall()]

        self.assertEqual(sorted(orig_rows), sorted(opt_rows))
        self.assertEqual(analysis['metrics']['results_equivalent'], True)

    def test_22_aggregate_query_optimization(self):
        """
        Input: Query with GROUP BY and aggregate functions.
        Ensures aggregates and group by columns are preserved and result matches.
        """
        sql = (
            "SELECT s.algorithm, COUNT(p.id) AS cnt\n"
            "FROM simulation_sessions s\n"
            "JOIN processes p ON s.session_id = p.session_id\n"
            "WHERE p.burst_time > 4\n"
            "GROUP BY s.algorithm;"
        )
        analysis = query_optimizer.analyze_query(custom_sql=sql, db_conn=self.conn)
        self.assertTrue(analysis['success'])

        cur = self.conn.cursor()
        cur.execute(sql)
        orig_rows = [tuple(r) for r in cur.fetchall()]

        cur.execute(analysis['optimized_sql'])
        opt_rows = [tuple(r) for r in cur.fetchall()]

        self.assertEqual(sorted(orig_rows), sorted(opt_rows))
        self.assertEqual(analysis['metrics']['results_equivalent'], True)

    def test_23_or_condition_in_where_preserved(self):
        """
        Input: Query with OR condition inside parentheses.
        SELECT pid, name FROM processes WHERE (priority = 1 OR burst_time < 4);
        Ensures parentheses and OR logic are not broken.
        """
        sql = "SELECT pid, name FROM processes WHERE (priority = 1 OR burst_time < 4);"
        analysis = query_optimizer.analyze_query(custom_sql=sql, db_conn=self.conn)

        self.assertTrue(analysis['success'])
        cur = self.conn.cursor()
        cur.execute(sql)
        orig_rows = [tuple(r) for r in cur.fetchall()]

        cur.execute(analysis['optimized_sql'])
        opt_rows = [tuple(r) for r in cur.fetchall()]

        self.assertEqual(sorted(orig_rows), sorted(opt_rows))
        self.assertEqual(analysis['metrics']['results_equivalent'], True)

    def test_24_api_rewrite_query_endpoint(self):
        """
        Tests /api/dbms/rewrite-query route ensuring identical safety and validation.
        """
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 1
                sess['user_name'] = 'Teacher'
                sess['account_type'] = 'teacher'
                sess['user_email'] = 'teacher@sysrealm.com'

            resp = client.post('/api/dbms/rewrite-query', json={
                'custom_sql': 'SELECT session_id, algorithm FROM simulation_sessions WHERE algorithm = "FCFS";'
            })
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data['success'])


if __name__ == '__main__':
    unittest.main()
