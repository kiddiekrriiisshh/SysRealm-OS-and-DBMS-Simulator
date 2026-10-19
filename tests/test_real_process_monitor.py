"""
SysRealm Unit Tests: Real Applications Monitor Module
=====================================================
Tests session management, pairing, token generation, rate limiting,
circular buffer boundedness, application grouping, and activity timeline formatting.
"""

import time
import unittest
from backend.real_process_monitor import (
    RealMonitorManager,
    MonitoringSession,
    classify_process_app
)


class TestRealProcessMonitor(unittest.TestCase):

    def setUp(self):
        self.manager = RealMonitorManager()
        self.user_email = 'student@sysrealm.edu'
        self.peer_email = 'peer@sysrealm.edu'

    def test_pairing_code_generation_and_expiry(self):
        """Pairing codes must be 6-char prefixed (SR-XXXX) with configurable TTL."""
        code, ttl = self.manager.generate_pairing_code(self.user_email, ttl_seconds=300)
        self.assertTrue(code.startswith('SR-'))
        self.assertEqual(len(code), 7)
        self.assertEqual(ttl, 300)

        # Generating another code for same user invalidates previous one
        code2, _ = self.manager.generate_pairing_code(self.user_email, ttl_seconds=300)
        self.assertNotEqual(code, code2)

        # Old code cannot be used
        ok, msg, _ = self.manager.connect_agent(code, {'os': 'Darwin'})
        self.assertFalse(ok)
        self.assertIn('Invalid', msg)

    def test_connect_agent_success_and_single_use(self):
        """Pairing code must exchange for bearer token and be consumed immediately (single-use)."""
        code, _ = self.manager.generate_pairing_code(self.user_email, ttl_seconds=300)

        ok, msg, session_info = self.manager.connect_agent(code, {'hostname': 'MacBook-Pro'})
        self.assertTrue(ok)
        self.assertIsNotNone(session_info)
        token = session_info['token']
        self.assertTrue(token.startswith('sr_mon_'))
        self.assertEqual(session_info['user_email'], self.user_email)

        # Immediate reuse of the same code must fail
        ok2, msg2, _ = self.manager.connect_agent(code, {'hostname': 'MacBook-Pro'})
        self.assertFalse(ok2)
        self.assertIn('Invalid', msg2)

        # Lookup session by token
        sess = self.manager.get_session_by_token(token)
        self.assertIsNotNone(sess)
        self.assertEqual(sess.user_email, self.user_email)
        self.assertTrue(sess.is_connected)

    def test_stop_session_revokes_token(self):
        """Stopping monitoring session must revoke bearer token and deactivate session."""
        code, _ = self.manager.generate_pairing_code(self.user_email, ttl_seconds=300)
        ok, _, session_info = self.manager.connect_agent(code, {})
        token = session_info['token']

        # Session is valid
        self.assertIsNotNone(self.manager.get_session_by_token(token))

        # Stop session
        stopped = self.manager.stop_session(self.user_email)
        self.assertTrue(stopped)

        # Token is now revoked
        self.assertIsNone(self.manager.get_session_by_token(token))
        self.assertIsNone(self.manager.get_session_by_user(self.user_email))

    def test_snapshot_ingestion_and_rate_limiting(self):
        """Snapshots must be ingested safely; rapid bursts (< 0.2s) must be rate-limited."""
        sess = MonitoringSession('s1', self.user_email, 'tok1', {})
        snapshot = {
            'timestamp': time.time(),
            'system_summary': {'cpu_total_percent': 12.0, 'memory_percent': 45.0, 'process_count': 150},
            'applications': [],
            'processes': [
                {'pid': 101, 'name': 'Google Chrome', 'cpu_percent': 8.5, 'memory_rss_mb': 250.0}
            ]
        }

        ok, msg = sess.record_snapshot(snapshot)
        self.assertTrue(ok)
        self.assertEqual(len(sess.snapshots), 1)

        # Immediate follow-up snapshot without delay should be rate-limited
        ok2, msg2 = sess.record_snapshot(snapshot)
        self.assertFalse(ok2)
        self.assertIn('Rate limit', msg2)

    def test_circular_buffer_boundedness(self):
        """Snapshot buffer must not exceed maxlen (180) to prevent memory leak."""
        sess = MonitoringSession('s2', self.user_email, 'tok2', {})
        now = time.time()

        for i in range(220):
            snap = {
                'timestamp': now + (i * 0.5),
                'system_summary': {'cpu_total_percent': 10.0},
                'processes': []
            }
            # bypass interval check manually for testing buffer length
            sess.last_snapshot_time = 0.0
            sess.record_snapshot(snap)

        self.assertEqual(len(sess.snapshots), 180)
        # Verify oldest snapshots were evicted and latest are present
        latest_ts = sess.snapshots[-1]['timestamp']
        self.assertAlmostEqual(latest_ts, now + (219 * 0.5), places=1)

    def test_app_classification(self):
        """Tests that process names and cmdlines are correctly mapped to apps and icons."""
        c1 = classify_process_app('Google Chrome Helper (Renderer)', '')
        self.assertEqual(c1['name'], 'Google Chrome')
        self.assertEqual(c1['icon'], '🌐')

        c2 = classify_process_app('Code', '')
        self.assertEqual(c2['name'], 'VS Code')

        c3 = classify_process_app('spotify', '')
        self.assertEqual(c3['name'], 'Spotify')

        c4 = classify_process_app('python3', 'python3 local_monitor/agent.py')
        self.assertEqual(c4['name'], 'Python Runtime')

        c5 = classify_process_app('random_binary_123', '')
        self.assertEqual(c5['name'], 'random_binary_123')
        self.assertEqual(c5['icon'], '⚙️')

    def test_timeline_activity_bands(self):
        """Timeline must calculate correct activity bands: HIGH, ACTIVE, LOW, IDLE."""
        code, _ = self.manager.generate_pairing_code(self.user_email, ttl_seconds=300)
        _, _, sinfo = self.manager.connect_agent(code, {})
        sess = self.manager.get_session_by_token(sinfo['token'])

        now = time.time()
        snap = {
            'timestamp': now,
            'system_summary': {'cpu_total_percent': 35.0, 'memory_percent': 60.0, 'memory_used_mb': 8192.0, 'process_count': 120},
            'applications': [
                {'name': 'Google Chrome', 'cpu_percent': 22.0, 'memory_rss_mb': 1200.0},
                {'name': 'VS Code', 'cpu_percent': 8.0, 'memory_rss_mb': 600.0},
                {'name': 'Spotify', 'cpu_percent': 2.0, 'memory_rss_mb': 250.0},
                {'name': 'Terminal', 'cpu_percent': 0.1, 'memory_rss_mb': 50.0}
            ],
            'processes': []
        }
        sess.last_snapshot_time = 0.0
        sess.record_snapshot(snap)

        timeline = self.manager.get_timeline(self.user_email, window_seconds=60)
        self.assertEqual(len(timeline), 1)
        entry = timeline[0]
        self.assertEqual(entry['system_cpu'], 35.0)

        app_map = {a['name']: a['activity'] for a in entry['top_apps']}
        self.assertEqual(app_map['Google Chrome'], 'HIGH')      # >= 15%
        self.assertEqual(app_map['VS Code'], 'ACTIVE')          # >= 5%
        self.assertEqual(app_map['Spotify'], 'LOW')             # > 0.5%
        self.assertEqual(app_map['Terminal'], 'IDLE')           # <= 0.5%


if __name__ == '__main__':
    unittest.main()
