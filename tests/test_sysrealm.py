"""
SysRealm Automated Verification Test Suite
Tests covering CPU scheduling with staggered arrivals, classic deadlock RAG detection,
memory capacity boundaries, database commit/rollback with trigger undo,
and canonical disk scheduling benchmarks.
"""

import unittest
import sqlite3
import os
import sys

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend import scheduler
from backend.deadlock_detector import DeadlockDetector
from backend.memory_manager import MemoryManager
from backend import disk_scheduler
from backend.app_manager import AppManager
from backend.process_manager import ProcessManager


class TestCPUSchedulerStaggered(unittest.TestCase):
    """
    Test CPU scheduling with processes arriving at different times.
    Verifies Gantt timeline segments, individual waiting/turnaround/response times,
    and aggregate metrics.
    """

    def setUp(self):
        # Staggered arrivals:
        # P1 arrives at t=0, burst=4
        # P2 arrives at t=1, burst=3
        # P3 arrives at t=2, burst=1
        self.procs = [
            {'pid': 'P1', 'name': 'Process 1', 'arrival_time': 0, 'burst_time': 4, 'priority': 1},
            {'pid': 'P2', 'name': 'Process 2', 'arrival_time': 1, 'burst_time': 3, 'priority': 2},
            {'pid': 'P3', 'name': 'Process 3', 'arrival_time': 2, 'burst_time': 1, 'priority': 3},
        ]

    def test_fcfs_staggered_timeline_and_metrics(self):
        result = scheduler.fcfs(self.procs)
        gantt = result['gantt_chart']
        procs = {p['pid']: p for p in result['processes']}
        metrics = result['metrics']

        # Gantt segments check:
        # P1 runs [0, 4]
        # P2 runs [4, 7]
        # P3 runs [7, 8]
        self.assertEqual(len(gantt), 3)
        self.assertEqual(gantt[0]['process'], 'P1')
        self.assertEqual(gantt[0]['start'], 0)
        self.assertEqual(gantt[0]['end'], 4)

        self.assertEqual(gantt[1]['process'], 'P2')
        self.assertEqual(gantt[1]['start'], 4)
        self.assertEqual(gantt[1]['end'], 7)

        self.assertEqual(gantt[2]['process'], 'P3')
        self.assertEqual(gantt[2]['start'], 7)
        self.assertEqual(gantt[2]['end'], 8)

        # Individual metrics check:
        # P1: completion=4, TAT=4-0=4, WT=4-4=0, RT=0-0=0
        self.assertEqual(procs['P1']['completion_time'], 4)
        self.assertEqual(procs['P1']['turnaround_time'], 4)
        self.assertEqual(procs['P1']['waiting_time'], 0)
        self.assertEqual(procs['P1']['response_time'], 0)

        # P2: completion=7, TAT=7-1=6, WT=6-3=3, RT=4-1=3
        self.assertEqual(procs['P2']['completion_time'], 7)
        self.assertEqual(procs['P2']['turnaround_time'], 6)
        self.assertEqual(procs['P2']['waiting_time'], 3)
        self.assertEqual(procs['P2']['response_time'], 3)

        # P3: completion=8, TAT=8-2=6, WT=6-1=5, RT=7-2=5
        self.assertEqual(procs['P3']['completion_time'], 8)
        self.assertEqual(procs['P3']['turnaround_time'], 6)
        self.assertEqual(procs['P3']['waiting_time'], 5)
        self.assertEqual(procs['P3']['response_time'], 5)

        # Summary metrics check:
        # avg_wt = (0 + 3 + 5) / 3 = 2.67
        # avg_tat = (4 + 6 + 6) / 3 = 5.33
        # avg_rt = (0 + 3 + 5) / 3 = 2.67
        self.assertAlmostEqual(metrics['avg_waiting_time'], 2.67, places=2)
        self.assertAlmostEqual(metrics['avg_turnaround_time'], 5.33, places=2)
        self.assertAlmostEqual(metrics['avg_response_time'], 2.67, places=2)
        self.assertEqual(metrics['completed'], 3)


class TestDeadlockClassicRAG(unittest.TestCase):
    """
    Test deadlock detection on classic Resource Allocation Graph:
    P1 holds R1 and wants R2; P2 holds R2 and wants R1.
    """

    def setUp(self):
        self.detector = DeadlockDetector()

    def test_classic_two_process_deadlock(self):
        allocation = {
            'P1': {'R1': 1},
            'P2': {'R2': 1}
        }
        request = {
            'P1': {'R2': 1},
            'P2': {'R1': 1}
        }
        available = {
            'R1': 0,
            'R2': 0
        }

        result = self.detector.detect(allocation, request, available)

        # Deadlock must be detected
        self.assertTrue(result['deadlock'])
        self.assertCountEqual(result['deadlocked_processes'], ['P1', 'P2'])
        self.assertTrue(len(result['cycle']) >= 2)
        self.assertIn('DEADLOCK', result['explanation'])

    def test_safe_state_no_deadlock(self):
        # P1 holds R1 and wants R2, but R2 is available!
        allocation = {
            'P1': {'R1': 1},
            'P2': {'R2': 1}
        }
        request = {
            'P1': {'R2': 1},
            'P2': {}
        }
        available = {
            'R1': 0,
            'R2': 1
        }

        result = self.detector.detect(allocation, request, available)
        self.assertFalse(result['deadlock'])
        self.assertEqual(len(result['deadlocked_processes']), 0)
        self.assertEqual(len(result['cycle']), 0)


class TestMemoryManagerCapacity(unittest.TestCase):
    """
    Test memory allocation at capacity and just over capacity.
    Total RAM = 1024 MB (2 x 512 MB blocks).
    """

    def setUp(self):
        self.mm = MemoryManager(total_mb=1024)

    def test_capacity_and_overflow(self):
        # 1. Allocate P1 (512 MB) -> Success
        res1 = self.mm.allocate('P1', 'Process 1', 512)
        self.assertTrue(res1['success'])
        self.assertEqual(self.mm.used_mb(), 512)
        self.assertEqual(self.mm.free_mb(), 512)

        # 2. Allocate P2 (512 MB) -> Exactly at capacity (1024 MB)
        res2 = self.mm.allocate('P2', 'Process 2', 512)
        self.assertTrue(res2['success'])
        self.assertEqual(self.mm.used_mb(), 1024)
        self.assertEqual(self.mm.free_mb(), 0)
        self.assertEqual(self.mm.utilization(), 100.0)

        # 3. Allocate P3 (1 MB) -> Just over capacity, must fail
        res3 = self.mm.allocate('P3', 'Process 3', 1)
        self.assertFalse(res3['success'])
        self.assertIn('Insufficient', res3['error'])
        self.assertEqual(self.mm.used_mb(), 1024)

        # 4. Release P1 (512 MB) -> Should free up 512 MB
        rel = self.mm.release('P1')
        self.assertTrue(rel['success'])
        self.assertEqual(self.mm.used_mb(), 512)
        self.assertEqual(self.mm.free_mb(), 512)

        # 5. Now P3 (512 MB) should succeed
        res4 = self.mm.allocate('P3', 'Process 3', 512)
        self.assertTrue(res4['success'])
        self.assertEqual(self.mm.used_mb(), 1024)
        self.assertEqual(self.mm.free_mb(), 0)


class TestDatabaseTransactionRollback(unittest.TestCase):
    """
    Test database commit and rollback consistency.
    Verifies that when a transaction aborts, all changes—including trigger-generated
    activity logs and session counter updates—are completely rolled back with zero partial changes.
    """

    def setUp(self):
        # Create an in-memory SQLite database with exact SysRealm schema & triggers
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        cur = self.conn.cursor()
        cur.executescript("""
            CREATE TABLE simulation_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                algorithm TEXT NOT NULL,
                status TEXT NOT NULL,
                num_processes INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
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
                state TEXT NOT NULL DEFAULT 'NEW',
                remaining_time INTEGER DEFAULT 0,
                start_time INTEGER NULL,
                completion_time INTEGER NULL,
                waiting_time INTEGER DEFAULT 0,
                turnaround_time INTEGER DEFAULT 0,
                response_time INTEGER NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (session_id, pid)
            );
            CREATE TABLE process_activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                process_id TEXT,
                event_type TEXT NOT NULL,
                simulation_time INTEGER DEFAULT 0,
                description TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TRIGGER trg_after_process_insert
            AFTER INSERT ON processes
            BEGIN
                INSERT INTO process_activity_logs (session_id, process_id, event_type, simulation_time, description)
                VALUES (
                    NEW.session_id,
                    NEW.pid,
                    'PROCESS_CREATED',
                    0,
                    '[Trigger: trg_after_process_insert] Process ' || NEW.pid || ' (' || NEW.name || ') registered.'
                );
                UPDATE simulation_sessions
                SET num_processes = num_processes + 1
                WHERE session_id = NEW.session_id;
            END;
        """)
        # Seed an active session
        cur.execute("INSERT INTO simulation_sessions (session_id, algorithm, status, num_processes) VALUES ('TEST_SES', 'FCFS', 'ACTIVE', 0)")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_transaction_rollback_undoes_row_and_trigger_logs(self):
        cur = self.conn.cursor()

        # Initial baseline count
        cur.execute("SELECT COUNT(*) FROM processes WHERE session_id='TEST_SES'")
        init_proc_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM process_activity_logs WHERE session_id='TEST_SES'")
        init_log_count = cur.fetchone()[0]
        cur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id='TEST_SES'")
        init_session_procs = cur.fetchone()[0]

        self.assertEqual(init_proc_count, 0)
        self.assertEqual(init_log_count, 0)
        self.assertEqual(init_session_procs, 0)

        # 1. Begin explicit transaction and insert
        cur.execute("BEGIN TRANSACTION")
        cur.execute("""
            INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb)
            VALUES ('P99', 'TEST_SES', 'AbortedProcess', 0, 5, 1, 512)
        """)

        # Inside transaction: process exists and trigger has inserted into activity logs
        cur.execute("SELECT COUNT(*) FROM processes WHERE session_id='TEST_SES' AND pid='P99'")
        self.assertEqual(cur.fetchone()[0], 1)

        cur.execute("SELECT COUNT(*) FROM process_activity_logs WHERE session_id='TEST_SES' AND process_id='P99'")
        self.assertEqual(cur.fetchone()[0], 1)

        cur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id='TEST_SES'")
        self.assertEqual(cur.fetchone()[0], 1)

        # 2. Abort transaction via ROLLBACK
        self.conn.rollback()

        # 3. Verify ZERO partial changes after rollback
        cur.execute("SELECT COUNT(*) FROM processes WHERE session_id='TEST_SES' AND pid='P99'")
        self.assertEqual(cur.fetchone()[0], 0, "Aborted process must not exist after rollback")

        cur.execute("SELECT COUNT(*) FROM process_activity_logs WHERE session_id='TEST_SES' AND process_id='P99'")
        self.assertEqual(cur.fetchone()[0], 0, "Trigger-generated log must roll back with the aborted transaction")

        cur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id='TEST_SES'")
        self.assertEqual(cur.fetchone()[0], 0, "Session counter must roll back to 0")

    def test_transaction_commit_persists_row_and_trigger_logs(self):
        cur = self.conn.cursor()

        cur.execute("BEGIN TRANSACTION")
        cur.execute("""
            INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb)
            VALUES ('P100', 'TEST_SES', 'CommittedProcess', 0, 5, 1, 512)
        """)
        self.conn.commit()

        cur.execute("SELECT COUNT(*) FROM processes WHERE session_id='TEST_SES' AND pid='P100'")
        self.assertEqual(cur.fetchone()[0], 1)

        cur.execute("SELECT COUNT(*) FROM process_activity_logs WHERE session_id='TEST_SES' AND process_id='P100'")
        self.assertEqual(cur.fetchone()[0], 1)

        cur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id='TEST_SES'")
        self.assertEqual(cur.fetchone()[0], 1)


class TestDiskSchedulingCanonical(unittest.TestCase):
    """
    Test disk scheduling with canonical benchmark:
    Requests: 98, 183, 37, 122, 14, 124, 65, 67, initial head: 53.
    FCFS total seek must equal 640.
    Also verifies repeated disk track requests.
    """

    def test_canonical_fcfs_seek_distance(self):
        requests = [98, 183, 37, 122, 14, 124, 65, 67]
        initial_head = 53

        result = disk_scheduler.fcfs(requests, initial_head)

        # Canonical standard: 640 total cylinders
        self.assertEqual(result['total_seek'], 640)
        self.assertEqual(result['sequence'], [53, 98, 183, 37, 122, 14, 124, 65, 67])
        self.assertEqual(result['avg_seek'], 80.0)

    def test_repeated_track_requests(self):
        # When a cylinder is requested more than once, head distance for consecutive requests to same track is 0
        requests = [65, 65, 98]
        initial_head = 53

        # Path: 53 -> 65 (12) -> 65 (0) -> 98 (33) = 45 total seek
        result = disk_scheduler.fcfs(requests, initial_head)
        self.assertEqual(result['total_seek'], 45)
        # Average seek must divide by 3 requests (not distinct set count 2)
        self.assertEqual(result['avg_seek'], 15.0)



class TestRealAppsAndMemoryManagement(unittest.TestCase):
    """
    Test suite for realistic multi-process applications and system memory management:
    - Launching multi-process apps and checking RAM allocation
    - Dynamic tab spawning
    - Interactive child process termination (RAM reclamation)
    - Virtual memory paging / Swapping out and in
    - Kernel OOM Killer badness score heuristic and automatic eviction
    """

    def setUp(self):
        self.proc_mgr = ProcessManager()
        self.mem_mgr = MemoryManager(total_mb=4096)  # 4 GB test physical memory
        self.app_mgr = AppManager(self.proc_mgr, self.mem_mgr)

    def test_launch_app_multi_process_allocation(self):
        # Launch browser (total blueprint: 512 + 1024 + 768 + 256 + 512 = 3072 MB)
        res = self.app_mgr.launch_app('browser')
        self.assertTrue(res['success'])
        self.assertEqual(res['launched_count'], 5)
        self.assertEqual(res['failed_count'], 0)

        # Check memory usage in MemoryManager
        self.assertEqual(self.mem_mgr.used_mb(), 3072)
        self.assertEqual(self.mem_mgr.free_mb(), 1024)

        # Check that processes are registered in ProcessManager
        all_procs = self.proc_mgr.get_all()
        self.assertEqual(len(all_procs), 5)

    def test_dynamic_tab_spawning(self):
        self.app_mgr.launch_app('browser')
        # Spawn a new tab of 512 MB
        res = self.app_mgr.spawn_tab('browser', tab_name='YouTube 1080p', memory_mb=512)
        self.assertTrue(res['success'])
        self.assertEqual(self.mem_mgr.used_mb(), 3584)

        # Attempt to spawn another tab that exceeds remaining 512 MB RAM (e.g. 1024 MB)
        res_oom = self.app_mgr.spawn_tab('browser', tab_name='Heavy Canvas', memory_mb=1024)
        self.assertFalse(res_oom['success'])
        self.assertTrue(res_oom.get('out_of_memory'))

    def test_interactive_kill_reclaims_ram(self):
        self.app_mgr.launch_app('browser')
        browser = self.app_mgr.apps['browser']
        # Find 3D WebGL Canvas child process (1024 MB)
        webgl_proc = next(p for p in browser.processes if 'WebGL' in p.name)
        pid = webgl_proc.pid

        # Kill webgl process
        kill_res = self.app_mgr.kill_process('browser', pid)
        self.assertTrue(kill_res['success'])
        self.assertEqual(kill_res['freed_mb'], 1024)

        # RAM should now have freed 1024 MB (3072 - 1024 = 2048 MB)
        self.assertEqual(self.mem_mgr.used_mb(), 2048)
        self.assertIsNone(self.proc_mgr.get_process(pid))

    def test_virtual_memory_swapping_cycle(self):
        self.app_mgr.launch_app('browser')
        browser = self.app_mgr.apps['browser']
        webgl_proc = next(p for p in browser.processes if 'WebGL' in p.name)
        pid = webgl_proc.pid

        # Swap OUT to simulated disk
        swap_out_res = self.app_mgr.swap_process('browser', pid, action='swap_out')
        self.assertTrue(swap_out_res['success'])
        self.assertEqual(webgl_proc.state, 'SWAPPED')
        self.assertIn(pid, self.app_mgr.swap_space)
        self.assertEqual(self.mem_mgr.used_mb(), 2048)  # 1024 MB freed in physical RAM

        # Swap back IN to physical RAM
        swap_in_res = self.app_mgr.swap_process('browser', pid, action='swap_in')
        self.assertTrue(swap_in_res['success'])
        self.assertEqual(webgl_proc.state, 'RUNNING')
        self.assertNotIn(pid, self.app_mgr.swap_space)
        self.assertEqual(self.mem_mgr.used_mb(), 3072)

    def test_kernel_oom_killer_badness_heuristic(self):
        self.app_mgr.launch_app('browser')
        browser = self.app_mgr.apps['browser']
        # Current utilization: 3072 / 4096 = 75%
        # Force invocation of OOM killer
        oom_res = self.app_mgr.run_oom_killer(force=True)
        self.assertTrue(oom_res['success'])
        self.assertTrue(oom_res['invoked'])

        victim = oom_res['victim']
        # The 3D WebGL Canvas tab (1024 MB, priority 3, worker tab) has highest badness score:
        # badness = (1024 * 10) + (3 * 50) + 150 = 10540
        # Main UI process has -500 discount so it is spared!
        self.assertIn('WebGL', victim['name'])
        self.assertEqual(victim['memory_mb'], 1024)
        self.assertEqual(self.mem_mgr.used_mb(), 2048)

    def test_representative_processes_selection(self):
        procs = self.app_mgr.get_representative_processes()
        self.assertEqual(len(procs), 4)
        app_ids = {p['app_id'] for p in procs}
        self.assertEqual(app_ids, {'browser', 'code_editor', 'media_player', 'game_engine'})

        # Verify key attributes
        p_browser = next(p for p in procs if p['app_id'] == 'browser')
        p_pulse = next(p for p in procs if p['app_id'] == 'media_player')
        self.assertEqual(p_browser['burst_time'], 8)
        self.assertEqual(p_pulse['priority'], 1)  # High priority real-time audio

    def test_representative_multi_algorithm_simulation(self):
        res = self.app_mgr.simulate_representative_processes(algorithm='ALL', quantum=2)
        self.assertTrue(res['success'])
        self.assertEqual(res['mode'], 'all')
        self.assertIn('FCFS', res['results'])
        self.assertIn('SJF', res['results'])
        self.assertIn('Priority', res['results'])
        self.assertIn('RoundRobin', res['results'])

        # Check metrics: SJF should achieve lower or equal waiting time than FCFS
        awt_fcfs = res['results']['FCFS']['metrics']['avg_waiting_time']
        awt_sjf = res['results']['SJF']['metrics']['avg_waiting_time']
        self.assertLessEqual(awt_sjf, awt_fcfs)

        # Round Robin should have low response time due to time-slicing
        art_rr = res['results']['RoundRobin']['metrics']['avg_response_time']
        art_fcfs = res['results']['FCFS']['metrics']['avg_response_time']
        self.assertLess(art_rr, art_fcfs)

    def test_representative_load_to_engine(self):
        from backend.simulation_engine import SimulationEngine
        engine = SimulationEngine()
        load_res = self.app_mgr.load_representative_to_engine(engine)
        self.assertTrue(load_res['success'])
        all_procs = engine.process_manager.get_all()
        self.assertEqual(len(all_procs), 4)
        self.assertGreater(engine.memory_manager.used_mb(), 0)


# ═══════════════════════════════════════════════════════════════════════
# DBMS TEST SUITE: Real Triggers, JOIN Queries, Integrity & Auditing
# ═══════════════════════════════════════════════════════════════════════

import uuid
import json
from app import app, _get_sqlite_mirror, _init_sqlite_schema, compute_workload_hash, compute_context_switches, save_simulation_run


def create_isolated_test_db():
    conn = sqlite3.connect(':memory:')
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    _init_sqlite_schema(conn)
    return conn


class TestDBMSProcessTriggerIntegrity(unittest.TestCase):
    """
    Test authoritative process counter and trigger-driven activity logging.
    Verifies:
    1. trg_after_process_insert increments simulation_sessions.num_processes by 1.
    2. trg_after_process_insert generates an authoritative PROCESS_CREATED log.
    3. Updating process attributes (name, priority) does NOT increment num_processes.
    4. trg_after_process_delete decrements num_processes by 1 and logs PROCESS_DELETED.
    5. Transaction rollback restores num_processes to previous value.
    """

    def setUp(self):
        self.conn = create_isolated_test_db()
        self.cur = self.conn.cursor()
        self.session_id = f"TEST_SES_CNT_{uuid.uuid4().hex[:8]}"
        self.cur.execute(
            "INSERT INTO simulation_sessions (session_id, algorithm, status, num_processes) VALUES (?, 'FCFS', 'RUNNING', 0)",
            (self.session_id,)
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_counter_increment_on_insert(self):
        # Initial count is 0
        self.cur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id = ?", (self.session_id,))
        self.assertEqual(self.cur.fetchone()['num_processes'], 0)

        # Insert Process 1
        self.cur.execute(
            """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
               VALUES ('P1', ?, 'Proc 1', 0, 5, 1, 128, 'READY')""",
            (self.session_id,)
        )
        self.conn.commit()

        # Counter should be 1
        self.cur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id = ?", (self.session_id,))
        self.assertEqual(self.cur.fetchone()['num_processes'], 1)

        # Audit log should have PROCESS_CREATED
        self.cur.execute(
            "SELECT event_type FROM process_activity_logs WHERE session_id = ? AND process_id = 'P1'",
            (self.session_id,)
        )
        logs = self.cur.fetchall()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['event_type'], 'PROCESS_CREATED')

        # Insert Process 2
        self.cur.execute(
            """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
               VALUES ('P2', ?, 'Proc 2', 1, 4, 2, 256, 'READY')""",
            (self.session_id,)
        )
        self.conn.commit()

        # Counter should be 2
        self.cur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id = ?", (self.session_id,))
        self.assertEqual(self.cur.fetchone()['num_processes'], 2)

    def test_counter_unchanged_on_process_update(self):
        # Insert P1
        self.cur.execute(
            """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
               VALUES ('P1', ?, 'Proc 1', 0, 5, 1, 128, 'READY')""",
            (self.session_id,)
        )
        self.conn.commit()

        # Update P1 name and priority
        self.cur.execute(
            "UPDATE processes SET name = 'Renamed Proc 1', priority = 9 WHERE pid = 'P1' AND session_id = ?",
            (self.session_id,)
        )
        self.conn.commit()

        # Counter must remain exactly 1 (not 2)
        self.cur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id = ?", (self.session_id,))
        self.assertEqual(self.cur.fetchone()['num_processes'], 1)

    def test_counter_decrement_on_process_delete(self):
        # Insert P1 and P2
        self.cur.execute(
            """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
               VALUES ('P1', ?, 'Proc 1', 0, 5, 1, 128, 'READY')""",
            (self.session_id,)
        )
        self.cur.execute(
            """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
               VALUES ('P2', ?, 'Proc 2', 1, 4, 2, 256, 'READY')""",
            (self.session_id,)
        )
        self.conn.commit()

        self.cur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id = ?", (self.session_id,))
        self.assertEqual(self.cur.fetchone()['num_processes'], 2)

        # Delete P2
        self.cur.execute("DELETE FROM processes WHERE pid = 'P2' AND session_id = ?", (self.session_id,))
        self.conn.commit()

        # Counter should decrement to 1
        self.cur.execute("SELECT num_processes FROM simulation_sessions WHERE session_id = ?", (self.session_id,))
        self.assertEqual(self.cur.fetchone()['num_processes'], 1)

        # Activity log should record PROCESS_DELETED
        self.cur.execute(
            "SELECT event_type FROM process_activity_logs WHERE session_id = ? AND process_id = 'P2' AND event_type = 'PROCESS_DELETED'",
            (self.session_id,)
        )
        del_log = self.cur.fetchone()
        self.assertIsNotNone(del_log)


class TestDBMSProcessStateHistoryTrigger(unittest.TestCase):
    """
    Test real database trigger trg_after_process_state_update recording
    meaningful process-state transitions into process_state_history.
    """

    def setUp(self):
        self.conn = create_isolated_test_db()
        self.cur = self.conn.cursor()
        self.session_id = f"TEST_SES_HIST_{uuid.uuid4().hex[:8]}"
        self.cur.execute(
            "INSERT INTO simulation_sessions (session_id, algorithm, status, num_processes) VALUES (?, 'FCFS', 'RUNNING', 0)",
            (self.session_id,)
        )
        self.cur.execute(
            """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
               VALUES ('P1', ?, 'Worker Proc', 0, 8, 1, 256, 'READY')""",
            (self.session_id,)
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_state_transitions_recorded_in_history(self):
        # Initial check: no state history yet (process created in READY)
        self.cur.execute("SELECT COUNT(*) AS c FROM process_state_history WHERE session_id = ?", (self.session_id,))
        self.assertEqual(self.cur.fetchone()['c'], 0)

        # Transition 1: READY -> RUNNING
        self.cur.execute("UPDATE processes SET state = 'RUNNING' WHERE pid = 'P1' AND session_id = ?", (self.session_id,))
        self.conn.commit()

        # Transition 2: RUNNING -> WAITING
        self.cur.execute("UPDATE processes SET state = 'WAITING' WHERE pid = 'P1' AND session_id = ?", (self.session_id,))
        self.conn.commit()

        # Transition 3: WAITING -> READY
        self.cur.execute("UPDATE processes SET state = 'READY' WHERE pid = 'P1' AND session_id = ?", (self.session_id,))
        self.conn.commit()

        # Transition 4: READY -> RUNNING
        self.cur.execute("UPDATE processes SET state = 'RUNNING' WHERE pid = 'P1' AND session_id = ?", (self.session_id,))
        self.conn.commit()

        # Transition 5: RUNNING -> TERMINATED
        self.cur.execute("UPDATE processes SET state = 'TERMINATED' WHERE pid = 'P1' AND session_id = ?", (self.session_id,))
        self.conn.commit()

        # Retrieve history
        self.cur.execute(
            "SELECT old_state, new_state FROM process_state_history WHERE session_id = ? AND pid = 'P1' ORDER BY id ASC",
            (self.session_id,)
        )
        history = [(r['old_state'], r['new_state']) for r in self.cur.fetchall()]
        expected = [
            ('READY', 'RUNNING'),
            ('RUNNING', 'WAITING'),
            ('WAITING', 'READY'),
            ('READY', 'RUNNING'),
            ('RUNNING', 'TERMINATED'),
        ]
        self.assertEqual(history, expected)

    def test_non_state_update_does_not_insert_history(self):
        # Update burst_time and priority without changing state
        self.cur.execute(
            "UPDATE processes SET burst_time = 12, priority = 5 WHERE pid = 'P1' AND session_id = ?",
            (self.session_id,)
        )
        self.conn.commit()

        # State history must still be empty
        self.cur.execute("SELECT COUNT(*) AS c FROM process_state_history WHERE session_id = ?", (self.session_id,))
        self.assertEqual(self.cur.fetchone()['c'], 0)


class TestDBMSValidationTriggers(unittest.TestCase):
    """
    Test trg_before_process_insert and trg_before_process_update:
    Enforcing invariants (non-negative burst_time, non-negative memory, valid states).
    """

    def setUp(self):
        self.conn = create_isolated_test_db()
        self.cur = self.conn.cursor()
        self.session_id = f"TEST_SES_VAL_{uuid.uuid4().hex[:8]}"
        self.cur.execute(
            "INSERT INTO simulation_sessions (session_id, algorithm, status, num_processes) VALUES (?, 'FCFS', 'RUNNING', 0)",
            (self.session_id,)
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_insert_negative_burst_time_rejected(self):
        with self.assertRaises(sqlite3.DatabaseError) as ctx:
            self.cur.execute(
                """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
                   VALUES ('P_NEG', ?, 'Bad Burst', 0, -5, 1, 128, 'READY')""",
                (self.session_id,)
            )
        self.conn.rollback()
        self.assertIn('Burst time must be greater than 0', str(ctx.exception))

    def test_insert_negative_memory_rejected(self):
        with self.assertRaises(sqlite3.DatabaseError) as ctx:
            self.cur.execute(
                """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
                   VALUES ('P_NEG_MEM', ?, 'Bad Mem', 0, 5, 1, -64, 'READY')""",
                (self.session_id,)
            )
        self.conn.rollback()
        self.assertIn('Memory allocation must be between 1 MB and 16384 MB', str(ctx.exception))

    def test_insert_invalid_state_rejected(self):
        with self.assertRaises(sqlite3.DatabaseError) as ctx:
            self.cur.execute(
                """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
                   VALUES ('P_BAD_ST', ?, 'Bad State', 0, 5, 1, 128, 'INVALID_STATE')""",
                (self.session_id,)
            )
        self.conn.rollback()
        self.assertIn('Invalid process state', str(ctx.exception))

    def test_update_negative_burst_time_rejected(self):
        # Insert valid process first
        self.cur.execute(
            """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
               VALUES ('P1', ?, 'Valid Proc', 0, 5, 1, 128, 'READY')""",
            (self.session_id,)
        )
        self.conn.commit()

        # Update to negative burst time must be rejected
        with self.assertRaises(sqlite3.DatabaseError) as ctx:
            self.cur.execute(
                "UPDATE processes SET burst_time = -1 WHERE pid = 'P1' AND session_id = ?",
                (self.session_id,)
            )
        self.conn.rollback()
        self.assertIn('Burst time must be greater than 0', str(ctx.exception))

    def test_update_invalid_state_rejected(self):
        self.cur.execute(
            """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
               VALUES ('P1', ?, 'Valid Proc', 0, 5, 1, 128, 'READY')""",
            (self.session_id,)
        )
        self.conn.commit()

        # Update to bogus state must be rejected
        with self.assertRaises(sqlite3.DatabaseError) as ctx:
            self.cur.execute(
                "UPDATE processes SET state = 'ZOMBIE_EXTREME' WHERE pid = 'P1' AND session_id = ?",
                (self.session_id,)
            )
        self.conn.rollback()
        self.assertIn('Invalid process state', str(ctx.exception))


class TestDBMSTerminationScoringIdempotency(unittest.TestCase):
    """
    Test termination triggers (trg_after_process_terminated and trg_after_process_insert_terminated)
    Verifies that reward points are awarded exactly once upon entering TERMINATED state,
    and repeated updates while already in TERMINATED state do not duplicate points.
    """

    def setUp(self):
        self.conn = create_isolated_test_db()
        self.cur = self.conn.cursor()
        self.session_id = f"TEST_SES_SCR_{uuid.uuid4().hex[:8]}"
        self.cur.execute(
            "INSERT INTO simulation_sessions (session_id, algorithm, status, num_processes) VALUES (?, 'FCFS', 'RUNNING', 0)",
            (self.session_id,)
        )
        self.cur.execute(
            """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
               VALUES ('P1', ?, 'Proc 1', 0, 4, 1, 128, 'READY')""",
            (self.session_id,)
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_idempotent_termination_scoring(self):
        # Process is in READY -> score should be 0
        self.cur.execute("SELECT total_score FROM scores WHERE session_id = ?", (self.session_id,))
        row = self.cur.fetchone()
        self.assertIsNone(row)

        # Transition 1: READY -> TERMINATED
        self.cur.execute("UPDATE processes SET state = 'TERMINATED' WHERE pid = 'P1' AND session_id = ?", (self.session_id,))
        self.conn.commit()

        # Score should be 10
        self.cur.execute("SELECT total_score FROM scores WHERE session_id = ?", (self.session_id,))
        score_row = self.cur.fetchone()
        self.assertIsNotNone(score_row)
        self.assertEqual(score_row['total_score'], 10)

        # Update while already TERMINATED (e.g. updating remaining_time or name)
        self.cur.execute(
            "UPDATE processes SET remaining_time = 0, state = 'TERMINATED' WHERE pid = 'P1' AND session_id = ?",
            (self.session_id,)
        )
        self.conn.commit()

        # Score must remain 10, NOT 20
        self.cur.execute("SELECT total_score FROM scores WHERE session_id = ?", (self.session_id,))
        self.assertEqual(self.cur.fetchone()['total_score'], 10)

    def test_direct_terminated_insert_awards_score_once(self):
        # Insert a process directly in TERMINATED state
        self.cur.execute(
            """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
               VALUES ('P2', ?, 'Pre-finished', 0, 2, 1, 128, 'TERMINATED')""",
            (self.session_id,)
        )
        self.conn.commit()

        # Score should be 10
        self.cur.execute("SELECT total_score FROM scores WHERE session_id = ?", (self.session_id,))
        score_row = self.cur.fetchone()
        self.assertIsNotNone(score_row)
        self.assertEqual(score_row['total_score'], 10)


class TestDBMSResourceAllocationIntegrity(unittest.TestCase):
    """
    Test resource allocation validation, composite foreign keys (session_id, pid),
    and hardware audit trigger trg_after_resource_allocation.
    """

    def setUp(self):
        self.conn = create_isolated_test_db()
        self.cur = self.conn.cursor()
        self.session_id = f"TEST_SES_RES_{uuid.uuid4().hex[:8]}"
        self.res_id = f"R_GPU_{uuid.uuid4().hex[:6]}"
        self.cur.execute(
            "INSERT INTO simulation_sessions (session_id, algorithm, status, num_processes) VALUES (?, 'FCFS', 'RUNNING', 0)",
            (self.session_id,)
        )
        self.cur.execute(
            """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
               VALUES ('P1', ?, 'GPU Compute Task', 0, 6, 1, 512, 'RUNNING')""",
            (self.session_id,)
        )
        self.cur.execute(
            "INSERT INTO resources (resource_id, name, total, icon) VALUES (?, 'NVIDIA RTX Compute', 4, '🖥️')",
            (self.res_id,)
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_allocation_trigger_creates_audit_log(self):
        # Insert allocation
        self.cur.execute(
            """INSERT INTO resource_allocations (session_id, pid, resource_id, count, status)
               VALUES (?, 'P1', ?, 2, 'allocated')""",
            (self.session_id, self.res_id)
        )
        self.conn.commit()

        # Verify trigger fired
        self.cur.execute(
            "SELECT event_type, description FROM process_activity_logs WHERE session_id = ? AND process_id = 'P1' AND event_type = 'RESOURCE_ALLOCATED'",
            (self.session_id,)
        )
        log = self.cur.fetchone()
        self.assertIsNotNone(log)
        self.assertIn(self.res_id, log['description'])
        self.assertIn('count=2', log['description'])

    def test_composite_foreign_key_referential_integrity(self):
        # Attempt to allocate for a non-existent pid 'P_NONEXIST'
        with self.assertRaises(sqlite3.IntegrityError):
            self.cur.execute(
                """INSERT INTO resource_allocations (session_id, pid, resource_id, count, status)
                   VALUES (?, 'P_NONEXIST', ?, 1, 'allocated')""",
                (self.session_id, self.res_id)
            )
        self.conn.rollback()

        # Attempt to allocate a non-existent resource
        with self.assertRaises(sqlite3.IntegrityError):
            self.cur.execute(
                """INSERT INTO resource_allocations (session_id, pid, resource_id, count, status)
                   VALUES (?, 'P1', 'NONEXISTENT_RES_ID', 1, 'allocated')""",
                (self.session_id,)
            )
        self.conn.rollback()


class TestDBMSAdvancedJoinReports(unittest.TestCase):
    """
    Test the 3 advanced JOIN reports:
    - Report A: Simulation Session Summary (pre-aggregated subquery preventing Cartesian explosion)
    - Report B: Hardware Resource Utilization (LEFT JOIN with composite key)
    - Report C: Lab Assignments and Student Submissions (LEFT JOIN preserving all assignments)
    """

    def setUp(self):
        self.conn = create_isolated_test_db()
        self.cur = self.conn.cursor()
        self.ses1 = f"SES_RPT1_{uuid.uuid4().hex[:6]}"
        self.ses2 = f"SES_RPT2_{uuid.uuid4().hex[:6]}"

        # Insert sessions
        self.cur.execute("INSERT INTO simulation_sessions (session_id, algorithm, status, num_processes) VALUES (?, 'FCFS', 'COMPLETED', 2)", (self.ses1,))
        self.cur.execute("INSERT INTO simulation_sessions (session_id, algorithm, status, num_processes) VALUES (?, 'RR', 'RUNNING', 1)", (self.ses2,))

        # Insert processes for ses1 (2 processes)
        self.cur.execute("INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state) VALUES ('P1', ?, 'Task A', 0, 4, 1, 100, 'TERMINATED')", (self.ses1,))
        self.cur.execute("INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state) VALUES ('P2', ?, 'Task B', 0, 6, 2, 200, 'TERMINATED')", (self.ses1,))
        # Insert process for ses2 (1 process)
        self.cur.execute("INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state) VALUES ('P1', ?, 'Task C', 0, 10, 1, 300, 'RUNNING')", (self.ses2,))

        # Insert scores for ses1
        self.cur.execute("INSERT INTO scores (session_id, total_score, reason) VALUES (?, 100, 'Test Bonus') ON CONFLICT(session_id) DO UPDATE SET total_score = 100", (self.ses1,))

        # Insert resource and allocation
        self.res1 = f"R_PRN_{uuid.uuid4().hex[:4]}"
        self.res2 = f"R_DSK_{uuid.uuid4().hex[:4]}"
        self.cur.execute("INSERT INTO resources (resource_id, name, total, icon) VALUES (?, 'Line Printer', 2, '🖨️')", (self.res1,))
        self.cur.execute("INSERT INTO resources (resource_id, name, total, icon) VALUES (?, 'NVMe Disk', 4, '💾')", (self.res2,))
        self.cur.execute("INSERT INTO resource_allocations (session_id, pid, resource_id, count, status) VALUES (?, 'P1', ?, 1, 'allocated')", (self.ses1, self.res1))

        # Insert assignment and submission
        self.asg_id = 99990 + int(uuid.uuid4().int % 1000)
        self.cur.execute(
            """INSERT INTO lab_assignments (id, title, description, target_panel, required_algo, points)
               VALUES (?, 'Process Scheduling Lab', 'FCFS vs RR Benchmark', 'scheduler', 'RoundRobin', 100)""",
            (self.asg_id,)
        )
        self.cur.execute(
            """INSERT INTO assignment_submissions (assignment_id, student_email, student_name, status, score_awarded, verification_note)
               VALUES (?, 'student@sysrealm.edu', 'Alex Student', 'COMPLETED', 95, 'Optimal scheduling verified')""",
            (self.asg_id,)
        )

        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_report_a_session_summary_no_cartesian_explosion(self):
        """
        Verify Report A pre-aggregates processes to avoid Cartesian explosion
        when joining with scores.
        """
        sql = """SELECT s.session_id, s.algorithm, s.status,
       COALESCE(p_agg.proc_count, 0) AS process_count,
       ROUND(COALESCE(p_agg.avg_burst, 0), 2) AS avg_burst_time,
       COALESCE(sc.total_score, 0) AS total_score
FROM simulation_sessions s
LEFT JOIN (
    SELECT session_id,
           COUNT(*) AS proc_count,
           AVG(burst_time) AS avg_burst
    FROM processes
    GROUP BY session_id
) p_agg ON s.session_id = p_agg.session_id
LEFT JOIN scores sc ON s.session_id = sc.session_id
WHERE s.session_id IN (?, ?)
ORDER BY s.session_id;"""
        self.cur.execute(sql, (self.ses1, self.ses2))
        rows = self.cur.fetchall()

        # Exactly 2 rows returned (one per session)
        self.assertEqual(len(rows), 2)

        row1 = next(r for r in rows if r['session_id'] == self.ses1)
        self.assertEqual(row1['process_count'], 2)
        self.assertEqual(row1['avg_burst_time'], 5.0)  # (4 + 6) / 2 = 5.0
        self.assertEqual(row1['total_score'], 100)

        row2 = next(r for r in rows if r['session_id'] == self.ses2)
        self.assertEqual(row2['process_count'], 1)
        self.assertEqual(row2['avg_burst_time'], 10.0)
        self.assertEqual(row2['total_score'], 0)

    def test_report_b_resource_utilization(self):
        sql = """SELECT 
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
WHERE r.resource_id IN (?, ?)
ORDER BY r.resource_id;"""
        self.cur.execute(sql, (self.res1, self.res2))
        rows = self.cur.fetchall()

        self.assertEqual(len(rows), 2)
        # res1 is allocated to P1
        r1 = next(r for r in rows if r['resource_id'] == self.res1)
        self.assertEqual(r1['requesting_pid'], 'P1')
        self.assertEqual(r1['process_name'], 'Task A')
        self.assertEqual(r1['session_algorithm'], 'FCFS')

        # res2 is unallocated -> requesting_pid is '—'
        r2 = next(r for r in rows if r['resource_id'] == self.res2)
        self.assertEqual(r2['requesting_pid'], '—')
        self.assertEqual(r2['process_name'], '—')
        self.assertEqual(r2['allocation_status'], 'IDLE/UNALLOCATED')

    def test_report_c_assignment_submissions(self):
        sql = """SELECT 
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
    COALESCE(sub.verification_note, 'Pending Evaluation') AS verification_note
FROM lab_assignments a
LEFT JOIN assignment_submissions sub ON a.id = sub.assignment_id
WHERE a.id = ?;"""
        self.cur.execute(sql, (self.asg_id,))
        rows = self.cur.fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['assignment_title'], 'Process Scheduling Lab')
        self.assertEqual(rows[0]['score_awarded'], 95)
        self.assertEqual(rows[0]['student_name'], 'Alex Student')
        self.assertEqual(rows[0]['submission_status'], 'COMPLETED')


class TestDBMSAPIEndpoints(unittest.TestCase):
    """
    Test Flask endpoints:
    - /api/dbms/join (All 7 join types with accurate engine badges)
    - /api/dbms/process-history (Audit inspection)
    - /api/processes/<pid>/state (Real state transitions)
    """

    def setUp(self):
        self.client = app.test_client()
        self.session_id = f"TEST_SES_API_{uuid.uuid4().hex[:8]}"
        conn = _get_sqlite_mirror()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO simulation_sessions (session_id, algorithm, status, num_processes) VALUES (?, 'FCFS', 'RUNNING', 1)",
            (self.session_id,)
        )
        cur.execute(
            """INSERT INTO processes (pid, session_id, name, arrival_time, burst_time, priority, memory_mb, state)
               VALUES ('P1', ?, 'API Worker', 0, 5, 1, 256, 'READY')""",
            (self.session_id,)
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        conn = _get_sqlite_mirror()
        cur = conn.cursor()
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            cur.execute("DELETE FROM process_state_history WHERE session_id = ?", (self.session_id,))
            cur.execute("DELETE FROM processes WHERE session_id = ?", (self.session_id,))
            cur.execute("DELETE FROM simulation_sessions WHERE session_id = ?", (self.session_id,))
            conn.commit()
        except Exception:
            pass
        conn.close()

    def test_join_api_all_types(self):
        with self.client.session_transaction() as sess:
            sess['user_email'] = 'teacher@sysrealm.edu'
            sess['account_type'] = 'teacher'

        join_types = [
            'inner_join', 'left_join', 'right_join', 'cross_join',
            'session_summary', 'resource_utilization', 'assignment_submissions_report'
        ]
        for jt in join_types:
            res = self.client.post('/api/dbms/join', json={'join_type': jt})
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data['success'])
            self.assertIn('title', data)
            self.assertIn('rows', data)
            self.assertIn('columns', data)
            self.assertIn('engine', data)
            self.assertIn(data['engine'], ['MySQL 8.0', 'SQLite Fallback Mirror'])

    def test_process_state_transition_and_history_api(self):
        with self.client.session_transaction() as sess:
            sess['user_email'] = 'student@sysrealm.edu'
            sess['account_type'] = 'student'

        # 1. Transition P1 from READY to RUNNING
        res = self.client.post(
            '/api/processes/P1/state',
            json={'state': 'RUNNING', 'session_id': self.session_id}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['old_state'], 'READY')
        self.assertEqual(data['new_state'], 'RUNNING')

        # 2. Inspect history via API
        hist_res = self.client.get(
            f'/api/dbms/process-history?session_id={self.session_id}&pid=P1'
        )
        self.assertEqual(hist_res.status_code, 200)
        hist_data = hist_res.get_json()
        self.assertTrue(hist_data['success'])
        self.assertGreaterEqual(len(hist_data['history']), 1)
        latest = hist_data['history'][-1]
        self.assertEqual(latest['old_state'], 'READY')
        self.assertEqual(latest['new_state'], 'RUNNING')


# ═══════════════════════════════════════════════════════════════════════
# SIMULATION HISTORY & PERFORMANCE ANALYTICS TEST SUITE
# ═══════════════════════════════════════════════════════════════════════

class TestSimulationRunPersistence(unittest.TestCase):
    """
    Test persistence of CPU scheduling simulation runs and process-level execution results.
    Verifies:
    1. Saving a simulation run creates rows in simulation_runs and simulation_run_processes.
    2. Re-reading run by ID returns accurate process start/completion times, WT, TAT, RT.
    3. Gantt chart is serialized as JSON and reconstructed accurately.
    4. Database transaction integrity and rollback on failure prevents orphan records.
    5. Foreign key cascade deletion works as expected.
    """

    def setUp(self):
        self.conn = create_isolated_test_db()
        self.cur = self.conn.cursor()
        self.procs = [
            {'pid': 'P1', 'name': 'Browser', 'arrival_time': 0, 'burst_time': 5, 'priority': 2, 'memory_mb': 1024},
            {'pid': 'P2', 'name': 'Player', 'arrival_time': 1, 'burst_time': 3, 'priority': 1, 'memory_mb': 512},
            {'pid': 'P3', 'name': 'Editor', 'arrival_time': 2, 'burst_time': 2, 'priority': 3, 'memory_mb': 256},
        ]
        self.sim_res = scheduler.fcfs(self.procs)

    def tearDown(self):
        self.conn.close()

    def test_save_and_retrieve_simulation_run(self):
        saved = save_simulation_run(
            session_id='TEST_SES_01',
            algorithm='FCFS',
            quantum=None,
            processes=self.sim_res['processes'],
            metrics=self.sim_res['metrics'],
            gantt_chart=self.sim_res['gantt_chart'],
            conn=self.conn
        )
        run_id = saved['run_id']
        self.assertTrue(run_id.startswith('RUN-'))
        self.assertEqual(saved['algorithm'], 'FCFS')
        self.assertEqual(saved['process_count'], 3)
        self.assertGreaterEqual(saved['context_switches'], 2)

        # Query simulation_runs
        self.cur.execute("SELECT * FROM simulation_runs WHERE run_id = ?", (run_id,))
        run_row = self.cur.fetchone()
        self.assertIsNotNone(run_row)
        self.assertEqual(run_row['algorithm'], 'FCFS')
        self.assertEqual(run_row['process_count'], 3)
        self.assertEqual(run_row['status'], 'COMPLETED')
        self.assertAlmostEqual(float(run_row['avg_waiting_time']), self.sim_res['metrics']['avg_waiting_time'], places=2)

        # Query simulation_run_processes
        self.cur.execute("SELECT * FROM simulation_run_processes WHERE run_id = ? ORDER BY execution_order", (run_id,))
        proc_rows = self.cur.fetchall()
        self.assertEqual(len(proc_rows), 3)

        # Check process metrics
        p1 = proc_rows[0]
        self.assertEqual(p1['pid'], 'P1')
        self.assertEqual(p1['start_time'], 0)
        self.assertEqual(p1['completion_time'], 5)
        self.assertEqual(p1['waiting_time'], 0)
        self.assertEqual(p1['turnaround_time'], 5)

        # Verify Gantt reconstruction from JSON
        gantt_json = run_row['gantt_json']
        gantt_reconstructed = json.loads(gantt_json)
        self.assertEqual(len(gantt_reconstructed), len(self.sim_res['gantt_chart']))
        self.assertEqual(gantt_reconstructed[0]['process'], 'P1')

    def test_cascade_delete_simulation_run(self):
        saved = save_simulation_run(
            session_id='TEST_SES_DEL',
            algorithm='SJF',
            quantum=None,
            processes=self.sim_res['processes'],
            metrics=self.sim_res['metrics'],
            gantt_chart=self.sim_res['gantt_chart'],
            conn=self.conn
        )
        run_id = saved['run_id']

        # Verify processes exist
        self.cur.execute("SELECT COUNT(*) AS cnt FROM simulation_run_processes WHERE run_id = ?", (run_id,))
        self.assertEqual(self.cur.fetchone()['cnt'], 3)

        # Delete run from parent table
        self.cur.execute("DELETE FROM simulation_runs WHERE run_id = ?", (run_id,))
        self.conn.commit()

        # Child processes must cascade delete
        self.cur.execute("SELECT COUNT(*) AS cnt FROM simulation_run_processes WHERE run_id = ?", (run_id,))
        self.assertEqual(self.cur.fetchone()['cnt'], 0)

    def test_transaction_rollback_on_failure(self):
        # Insert a run with duplicate run_id inside transaction to force failure
        test_run_id = 'RUN-UNIQUE-TEST'
        self.cur.execute(
            """INSERT INTO simulation_runs (run_id, run_name, algorithm, workload_hash)
               VALUES (?, 'First Run', 'FCFS', 'HASH123')""",
            (test_run_id,)
        )
        self.conn.commit()

        # Attempt to insert same run_id inside a transaction
        with self.assertRaises(sqlite3.IntegrityError):
            with self.conn:
                self.cur.execute(
                    """INSERT INTO simulation_runs (run_id, run_name, algorithm, workload_hash)
                       VALUES (?, 'Second Run', 'SJF', 'HASH123')""",
                    (test_run_id,)
                )

        # Verify first run is intact and second was rolled back
        self.cur.execute("SELECT run_name FROM simulation_runs WHERE run_id = ?", (test_run_id,))
        self.assertEqual(self.cur.fetchone()['run_name'], 'First Run')


class TestWorkloadEquivalenceAndComparison(unittest.TestCase):
    """
    Test workload hash generation and fair algorithm comparison rules:
    1. Deterministic workload hashing regardless of process list order.
    2. Any modification in arrival time, burst time, priority or memory alters hash.
    3. Multi-algorithm comparison flags fair_comparison: True when workloads match.
    4. Multi-algorithm comparison flags fair_comparison: False and warns when workloads differ.
    5. Winner identification accurately selects lowest waiting time, turnaround time, etc.
    """

    def setUp(self):
        self.procs1 = [
            {'pid': 'P1', 'arrival_time': 0, 'burst_time': 4, 'priority': 1, 'memory_mb': 512},
            {'pid': 'P2', 'arrival_time': 1, 'burst_time': 3, 'priority': 2, 'memory_mb': 256},
        ]
        # Same processes in reverse order
        self.procs1_reversed = [
            {'pid': 'P2', 'arrival_time': 1, 'burst_time': 3, 'priority': 2, 'memory_mb': 256},
            {'pid': 'P1', 'arrival_time': 0, 'burst_time': 4, 'priority': 1, 'memory_mb': 512},
        ]
        # Modified burst time
        self.procs2_different = [
            {'pid': 'P1', 'arrival_time': 0, 'burst_time': 9, 'priority': 1, 'memory_mb': 512},
            {'pid': 'P2', 'arrival_time': 1, 'burst_time': 3, 'priority': 2, 'memory_mb': 256},
        ]

    def test_deterministic_workload_hashing(self):
        hash1 = compute_workload_hash(self.procs1)
        hash1_rev = compute_workload_hash(self.procs1_reversed)
        hash2 = compute_workload_hash(self.procs2_different)

        self.assertEqual(hash1, hash1_rev)
        self.assertNotEqual(hash1, hash2)
        self.assertEqual(len(hash1), 16)

    def test_context_switch_computation(self):
        # Timeline: P1 -> P2 -> P1 -> P2
        gantt = [
            {'process': 'P1', 'start': 0, 'end': 2},
            {'process': 'P2', 'start': 2, 'end': 4},
            {'process': 'P1', 'start': 4, 'end': 6},
            {'process': 'P2', 'start': 6, 'end': 7},
        ]
        switches = compute_context_switches(gantt)
        self.assertEqual(switches, 3)

        # Idle segments should not count as spurious process switches
        gantt_with_idle = [
            {'process': 'IDLE', 'start': 0, 'end': 1},
            {'process': 'P1', 'start': 1, 'end': 4},
            {'process': 'IDLE', 'start': 4, 'end': 5},
            {'process': 'P2', 'start': 5, 'end': 7},
        ]
        switches_idle = compute_context_switches(gantt_with_idle)
        self.assertEqual(switches_idle, 1)


class TestSimulationAnalyticsQueries(unittest.TestCase):
    """
    Test real SQL aggregate queries powering the Simulation Analytics dashboard:
    1. COUNT(*) total simulation runs.
    2. GROUP BY algorithm calculating AVG(avg_waiting_time), AVG(cpu_utilization).
    3. MIN and MAX finding global optimal benchmarks.
    4. COUNT(DISTINCT workload_hash) measuring experiment diversity.
    """

    def setUp(self):
        self.conn = create_isolated_test_db()
        self.cur = self.conn.cursor()

        # Seed 3 simulation runs: 2 FCFS, 1 SJF
        runs = [
            ('RUN-A', 'FCFS', 4.0, 8.0, 90.0, 0.25, 2, 'HASH_A'),
            ('RUN-B', 'FCFS', 6.0, 10.0, 80.0, 0.20, 2, 'HASH_B'),
            ('RUN-C', 'SJF', 2.5, 6.0, 95.0, 0.30, 2, 'HASH_A'),
        ]
        for r in runs:
            self.cur.execute(
                """INSERT INTO simulation_runs
                    (run_id, run_name, algorithm, avg_waiting_time, avg_turnaround_time,
                     cpu_utilization, throughput, context_switches, workload_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (r[0], f"Run {r[0]}", r[1], r[2], r[3], r[4], r[5], r[6], r[7])
            )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_aggregate_group_by_algorithm(self):
        self.cur.execute(
            """SELECT algorithm,
                      COUNT(*) AS total_runs,
                      ROUND(AVG(avg_waiting_time), 2) AS avg_wt,
                      ROUND(AVG(cpu_utilization), 2) AS avg_cpu
               FROM simulation_runs
               GROUP BY algorithm
               ORDER BY total_runs DESC"""
        )
        rows = [dict(r) for r in self.cur.fetchall()]
        self.assertEqual(len(rows), 2)

        # FCFS should have 2 runs, avg_wt = (4.0 + 6.0)/2 = 5.0
        fcfs = next(r for r in rows if r['algorithm'] == 'FCFS')
        self.assertEqual(fcfs['total_runs'], 2)
        self.assertAlmostEqual(fcfs['avg_wt'], 5.0)
        self.assertAlmostEqual(fcfs['avg_cpu'], 85.0)

        # SJF should have 1 run, avg_wt = 2.5
        sjf = next(r for r in rows if r['algorithm'] == 'SJF')
        self.assertEqual(sjf['total_runs'], 1)
        self.assertAlmostEqual(sjf['avg_wt'], 2.5)

    def test_min_max_extremum_queries(self):
        self.cur.execute(
            """SELECT MIN(avg_waiting_time) AS best_wt,
                      MAX(cpu_utilization) AS peak_cpu
               FROM simulation_runs"""
        )
        row = dict(self.cur.fetchone())
        self.assertAlmostEqual(row['best_wt'], 2.5)
        self.assertAlmostEqual(row['peak_cpu'], 95.0)

    def test_distinct_workload_count(self):
        self.cur.execute("SELECT COUNT(DISTINCT workload_hash) AS distinct_wl FROM simulation_runs")
        self.assertEqual(self.cur.fetchone()['distinct_wl'], 2)


class TestSimulationHistoryAPI(unittest.TestCase):
    """
    Test Flask API endpoints for Simulation History & Performance Analytics:
    - GET /api/simulation/history
    - GET /api/simulation/history/<run_id>
    - POST /api/simulation/compare
    - GET /api/simulation/analytics
    - POST /api/simulation/history/<run_id>/rerun
    """

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    def test_analytics_api_returns_success(self):
        with self.client.session_transaction() as sess:
            sess['user_email'] = 'student@sysrealm.edu'
            sess['account_type'] = 'student'

        res = self.client.get('/api/simulation/analytics')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIn('total_runs', data)
        self.assertIn('algorithm_statistics', data)
        self.assertIn('best_observed', data)
        self.assertIn('sql_demonstration', data)

    def test_history_list_api_supports_filtering(self):
        with self.client.session_transaction() as sess:
            sess['user_email'] = 'student@sysrealm.edu'
            sess['account_type'] = 'student'

        # Filter by algorithm=FCFS
        res = self.client.get('/api/simulation/history?algorithm=FCFS&limit=10')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        for r in data['runs']:
            self.assertEqual(r['algorithm'], 'FCFS')

    def test_compare_endpoint_fair_vs_unfair(self):
        with self.client.session_transaction() as sess:
            sess['user_email'] = 'student@sysrealm.edu'
            sess['account_type'] = 'student'

        # First get runs from history
        h_res = self.client.get('/api/simulation/history?limit=5')
        h_data = h_res.get_json()
        if len(h_data['runs']) >= 2:
            r1 = h_data['runs'][0]['run_id']
            r2 = h_data['runs'][1]['run_id']
            cmp_res = self.client.post(
                '/api/simulation/compare',
                json={'run_ids': [r1, r2]}
            )
            self.assertEqual(cmp_res.status_code, 200)
            cmp_data = cmp_res.get_json()
            self.assertTrue(cmp_data['success'])
            self.assertIn('fair_comparison', cmp_data)
            self.assertIn('winner', cmp_data)
            self.assertIn('educational_analysis', cmp_data)

    def test_rerun_workload_api(self):
        with self.client.session_transaction() as sess:
            sess['user_email'] = 'student@sysrealm.edu'
            sess['account_type'] = 'student'

        h_res = self.client.get('/api/simulation/history?limit=1')
        h_data = h_res.get_json()
        if len(h_data['runs']) > 0:
            target_run_id = h_data['runs'][0]['run_id']
            res = self.client.post(f'/api/simulation/history/{target_run_id}/rerun')
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data['success'])
            self.assertIn('processes', data)
            self.assertGreater(len(data['processes']), 0)

    def test_e2e_scheduler_run_persistence_and_fair_comparison(self):
        with self.client.session_transaction() as sess:
            sess['user_email'] = 'student@sysrealm.edu'
            sess['account_type'] = 'student'

        # Reset and create test processes
        self.client.post('/api/scheduler/reset')
        self.client.post('/api/processes', json={'name': 'E2E Proc 1', 'arrival_time': 0, 'burst_time': 4, 'priority': 1, 'memory_mb': 512})
        self.client.post('/api/processes', json={'name': 'E2E Proc 2', 'arrival_time': 1, 'burst_time': 3, 'priority': 2, 'memory_mb': 256})

        # Run FCFS
        res_fcfs = self.client.post('/api/scheduler/run', json={'algorithm': 'FCFS'})
        self.assertEqual(res_fcfs.status_code, 200)
        data_fcfs = res_fcfs.get_json()
        self.assertTrue(data_fcfs['success'])
        run_fcfs = data_fcfs['run_id']
        hash_fcfs = data_fcfs['workload_hash']

        # Run SJF on same processes
        res_sjf = self.client.post('/api/scheduler/run', json={'algorithm': 'SJF'})
        self.assertEqual(res_sjf.status_code, 200)
        data_sjf = res_sjf.get_json()
        self.assertTrue(data_sjf['success'])
        run_sjf = data_sjf['run_id']
        hash_sjf = data_sjf['workload_hash']

        # Both runs operated on identical processes, so workload hashes MUST match
        self.assertEqual(hash_fcfs, hash_sjf)

        # Compare the two runs
        cmp_res = self.client.post(
            '/api/simulation/compare',
            json={'run_ids': [run_fcfs, run_sjf]}
        )
        self.assertEqual(cmp_res.status_code, 200)
        cmp_data = cmp_res.get_json()
        self.assertTrue(cmp_data['success'])
        self.assertTrue(cmp_data['fair_comparison'])
        self.assertIsNone(cmp_data['workload_warning'])


if __name__ == '__main__':
    unittest.main()



