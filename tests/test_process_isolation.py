"""
SysRealm Unit & Isolation Tests: Mode A Isolation & Separation from Mode B
==========================================================================
Verifies:
1. Mode A Virtual Apps: Scheduling a selected application only runs the processes
   belonging to that application, rather than the entire shared queue.
2. Mode B Non-Interference: Telemetry snapshots from the real OS monitor NEVER
   insert records into the simulated ProcessManager or simulation_sessions table.
"""

import time
import json
import unittest
from app import app, engine
from backend.real_process_monitor import monitor_manager


class TestProcessIsolation(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        self.user_email = 'isolation_tester@sysrealm.edu'
        with self.client.session_transaction() as sess:
            sess['user_email'] = self.user_email
            sess['account_type'] = 'student'
            sess['user_name'] = 'Isolation Tester'
        from app import _user_engines
        from backend.simulation_engine import SimulationEngine
        self.user_engine = _user_engines.setdefault(self.user_email, SimulationEngine())
        self.user_engine.reset()
        monitor_manager.stop_session(self.user_email)

    def test_mode_a_selected_app_scheduling_isolation(self):
        """Scheduling with specific process_ids must isolate execution to only those processes."""
        # Create processes for two distinct virtual apps + one manual process
        p1 = self.user_engine.process_manager.create_process('Virtual App · Lab Browser · Core UI', 0, 4, 2, 256)
        p2 = self.user_engine.process_manager.create_process('Virtual App · Lab Browser · Tab Renderer', 1, 5, 3, 512)
        p3 = self.user_engine.process_manager.create_process('Virtual App · Tone Player · Audio DSP', 0, 3, 1, 256)
        p4 = self.user_engine.process_manager.create_process('Manual User Process', 0, 6, 2, 128)

        all_procs = self.user_engine.process_manager.get_all()
        self.assertEqual(len(all_procs), 4)

        # Schedule ONLY Lab Browser processes (p1 and p2)
        browser_pids = [p1.pid, p2.pid]
        res = self.client.post('/api/scheduler/run', json={
            'algorithm': 'FCFS',
            'quantum': 2,
            'process_ids': browser_pids
        })
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])

        scheduled_pids = [p['pid'] for p in data['processes']]
        self.assertEqual(set(scheduled_pids), set(browser_pids))
        self.assertNotIn(p3.pid, scheduled_pids)
        self.assertNotIn(p4.pid, scheduled_pids)

        # The other processes in ProcessManager must still exist unharmed
        remaining_procs = self.user_engine.process_manager.get_all()
        self.assertEqual(len(remaining_procs), 4)

    def test_mode_b_real_telemetry_never_enters_simulated_queue(self):
        """Mode B real process snapshots must NEVER pollute the simulated ProcessManager."""
        initial_sim_procs = len(self.user_engine.process_manager.get_all())

        # Pair and post real OS processes
        code, _ = monitor_manager.generate_pairing_code(self.user_email, 300)
        _, _, sinfo = monitor_manager.connect_agent(code, {'os': 'Darwin'})
        token = sinfo['token']

        real_snapshot = {
            'timestamp': time.time(),
            'system_summary': {'cpu_total_percent': 15.0, 'process_count': 250},
            'applications': [{'name': 'Google Chrome', 'cpu_percent': 10.0}],
            'processes': [
                {'pid': 99999, 'ppid': 1, 'name': 'Real OS Kernel Process', 'cpu_percent': 25.0, 'memory_rss_mb': 1024.0}
            ]
        }

        snap_res = self.client.post(
            '/api/real-monitor/snapshot',
            json=real_snapshot,
            headers={'Authorization': f'Bearer {token}'}
        )
        self.assertEqual(snap_res.status_code, 200)

        # Verify simulated process manager remains untouched
        post_snap_sim_procs = len(self.user_engine.process_manager.get_all())
        self.assertEqual(initial_sim_procs, post_snap_sim_procs)
        self.assertIsNone(self.user_engine.process_manager.get_process('99999'))
        self.assertIsNone(self.user_engine.process_manager.get_process(99999))

        # Query /api/processes - must NOT contain PID 99999
        api_procs_res = self.client.get('/api/processes')
        self.assertEqual(api_procs_res.status_code, 200)
        api_data = json.loads(api_procs_res.data)
        api_pids = [p.get('pid') for p in api_data.get('processes', [])]
        self.assertNotIn('99999', api_pids)
        self.assertNotIn(99999, api_pids)


if __name__ == '__main__':
    unittest.main()
