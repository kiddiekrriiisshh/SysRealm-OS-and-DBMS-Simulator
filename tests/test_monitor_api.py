"""
SysRealm API Integration Tests: Real Applications Monitoring Endpoints
======================================================================
Tests /api/real-monitor/* REST endpoints:
- Pairing code generation & validation
- Agent token exchange
- Authenticated snapshot streaming
- Status check & heartbeat detection
- Process and Application querying & filtering
- Rolling history / Timeline retrieval
- Stop & Token revocation
"""

import time
import json
import unittest
from app import app
from backend.real_process_monitor import monitor_manager


class TestRealMonitorAPI(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        self.user_email = 'test_student@sysrealm.edu'
        # Reset any lingering sessions for this user
        monitor_manager.stop_session(self.user_email)

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['user_email'] = self.user_email
            sess['account_type'] = 'student'
            sess['user_name'] = 'Test Student'

    def test_pair_requires_login(self):
        """Unauthenticated call to /api/real-monitor/pair must return 401."""
        res = self.client.post('/api/real-monitor/pair')
        self.assertEqual(res.status_code, 401)

    def test_complete_monitoring_lifecycle(self):
        """End-to-end integration test of pairing, telemetry streaming, status, query, and stop."""
        self._login()

        # Step 1: Generate Pairing Code
        pair_res = self.client.post('/api/real-monitor/pair')
        self.assertEqual(pair_res.status_code, 200)
        pair_data = json.loads(pair_res.data)
        self.assertTrue(pair_data['success'])
        pair_code = pair_data['pair_code']
        self.assertTrue(pair_code.startswith('SR-'))
        self.assertIn('command', pair_data)

        # Step 2: Agent connects with pair code (no login required, exchanges code for token)
        conn_res = self.client.post('/api/real-monitor/connect', json={
            'pair_code': pair_code,
            'agent_metadata': {'os': 'Darwin', 'hostname': 'Test-MacBook'}
        })
        self.assertEqual(conn_res.status_code, 200)
        conn_data = json.loads(conn_res.data)
        self.assertTrue(conn_data['success'])
        token = conn_data['token']
        self.assertTrue(token.startswith('sr_mon_'))

        # Step 3: Check status initially (connected, but no snapshots yet)
        status_res = self.client.get('/api/real-monitor/status')
        self.assertEqual(status_res.status_code, 200)
        status_data = json.loads(status_res.data)
        self.assertTrue(status_data['success'])
        self.assertTrue(status_data['has_session'])
        self.assertTrue(status_data['connected'])

        # Step 4: Agent posts a telemetry snapshot
        snapshot_payload = {
            'timestamp': time.time(),
            'system_summary': {
                'cpu_total_percent': 24.5,
                'memory_total_mb': 16384.0,
                'memory_used_mb': 8192.0,
                'memory_percent': 50.0,
                'process_count': 180,
                'platform': 'macOS 15.0'
            },
            'applications': [
                {'name': 'Google Chrome', 'icon': '🌐', 'category': 'Web Browser', 'process_count': 12, 'cpu_percent': 18.2, 'memory_rss_mb': 1450.0},
                {'name': 'VS Code', 'icon': '💻', 'category': 'Development', 'process_count': 5, 'cpu_percent': 4.3, 'memory_rss_mb': 520.0}
            ],
            'processes': [
                {'pid': 1234, 'ppid': 1, 'name': 'Google Chrome', 'app_name': 'Google Chrome', 'cpu_percent': 14.1, 'memory_rss_mb': 400.0, 'status': 'running'},
                {'pid': 1235, 'ppid': 1234, 'name': 'Google Chrome Helper', 'app_name': 'Google Chrome', 'cpu_percent': 4.1, 'memory_rss_mb': 250.0, 'status': 'running'},
                {'pid': 5678, 'ppid': 1, 'name': 'Code', 'app_name': 'VS Code', 'cpu_percent': 4.3, 'memory_rss_mb': 520.0, 'status': 'running'}
            ]
        }

        # Snapshot without bearer token must fail with 401
        unauth_snap = self.client.post('/api/real-monitor/snapshot', json=snapshot_payload)
        self.assertEqual(unauth_snap.status_code, 401)

        # Snapshot with valid bearer token
        snap_res = self.client.post(
            '/api/real-monitor/snapshot',
            json=snapshot_payload,
            headers={'Authorization': f'Bearer {token}'}
        )
        self.assertEqual(snap_res.status_code, 200)
        snap_data = json.loads(snap_res.data)
        self.assertTrue(snap_data['success'])

        # Step 5: Query /api/real-monitor/applications
        apps_res = self.client.get('/api/real-monitor/applications')
        self.assertEqual(apps_res.status_code, 200)
        apps_data = json.loads(apps_res.data)
        self.assertEqual(len(apps_data['applications']), 2)
        self.assertEqual(apps_data['applications'][0]['name'], 'Google Chrome')

        # Step 6: Query /api/real-monitor/processes (with filtering)
        procs_res = self.client.get('/api/real-monitor/processes?app=Chrome')
        self.assertEqual(procs_res.status_code, 200)
        procs_data = json.loads(procs_res.data)
        self.assertEqual(procs_data['total'], 2)

        # Step 7: Query /api/real-monitor/history (Timeline data)
        hist_res = self.client.get('/api/real-monitor/history?window=120')
        self.assertEqual(hist_res.status_code, 200)
        hist_data = json.loads(hist_res.data)
        self.assertTrue(hist_data['success'])
        self.assertGreaterEqual(hist_data['count'], 1)
        first_timeline_point = hist_data['timeline'][0]
        self.assertIn('top_apps', first_timeline_point)
        self.assertEqual(first_timeline_point['system_cpu'], 24.5)

        # Step 8: Stop monitoring
        stop_res = self.client.post('/api/real-monitor/stop')
        self.assertEqual(stop_res.status_code, 200)

        # After stop, sending snapshot with same token must fail with 401
        post_stop_snap = self.client.post(
            '/api/real-monitor/snapshot',
            json=snapshot_payload,
            headers={'Authorization': f'Bearer {token}'}
        )
        self.assertEqual(post_stop_snap.status_code, 401)


if __name__ == '__main__':
    unittest.main()
