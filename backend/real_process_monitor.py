"""
SysRealm Real Applications Monitor: Session Manager & Telemetry Aggregator
===========================================================================
Academic Context:
  SysRealm: Kernel Panic — An Interactive Operating System Simulator
  Third-Year B.Tech Computer Science & Engineering (OS / Systems Programming)

Architecture & Separation of Concerns:
  - This module is strictly for REAL OPERATING SYSTEM process monitoring.
  - Real OS processes are MONITORED, NOT SCHEDULED by SysRealm's simulated scheduler.
  - Real processes NEVER enter the simulated ProcessManager or simulation_sessions table.
  - Telemetry is received via outbound HTTPS/HTTP from a local Python agent (local_monitor/)
    running on the student's laptop outside the browser sandbox.
  - Manages pairing codes, revocable bearer tokens, bounded rolling history buffers,
    and formats the Observed Real Process Activity Timeline.
"""

import time
import secrets
import string
import threading
from collections import deque
from typing import Dict, List, Optional, Any, Tuple


# Known desktop application signatures for consistent grouping and icons
APP_SIGNATURES = {
    'chrome': {'name': 'Google Chrome', 'icon': '🌐', 'category': 'Web Browser'},
    'google chrome': {'name': 'Google Chrome', 'icon': '🌐', 'category': 'Web Browser'},
    'google chrome helper': {'name': 'Google Chrome', 'icon': '🌐', 'category': 'Web Browser'},
    'chromium': {'name': 'Chromium', 'icon': '🌐', 'category': 'Web Browser'},
    'brave': {'name': 'Brave Browser', 'icon': '🦁', 'category': 'Web Browser'},
    'safari': {'name': 'Apple Safari', 'icon': '🧭', 'category': 'Web Browser'},
    'firefox': {'name': 'Mozilla Firefox', 'icon': '🦊', 'category': 'Web Browser'},
    'code': {'name': 'VS Code', 'icon': '💻', 'category': 'Development'},
    'code helper': {'name': 'VS Code', 'icon': '💻', 'category': 'Development'},
    'electron': {'name': 'VS Code / Electron', 'icon': '⚡', 'category': 'Development'},
    'cursor': {'name': 'Cursor IDE', 'icon': '⚡', 'category': 'Development'},
    'antigravity': {'name': 'Antigravity IDE', 'icon': '🚀', 'category': 'Development'},
    'pycharm': {'name': 'PyCharm', 'icon': '🐍', 'category': 'Development'},
    'spotify': {'name': 'Spotify', 'icon': '🎵', 'category': 'Media Player'},
    'spotify helper': {'name': 'Spotify', 'icon': '🎵', 'category': 'Media Player'},
    'vlc': {'name': 'VLC Media Player', 'icon': '🎬', 'category': 'Media Player'},
    'terminal': {'name': 'Terminal', 'icon': '⬛', 'category': 'System Utility'},
    'iterm2': {'name': 'iTerm2', 'icon': '⬛', 'category': 'System Utility'},
    'kitty': {'name': 'Kitty Terminal', 'icon': '🐱', 'category': 'System Utility'},
    'alacritty': {'name': 'Alacritty', 'icon': '⚡', 'category': 'System Utility'},
    'zsh': {'name': 'Zsh Shell', 'icon': '🐚', 'category': 'System Utility'},
    'bash': {'name': 'Bash Shell', 'icon': '🐚', 'category': 'System Utility'},
    'python': {'name': 'Python Runtime', 'icon': '🐍', 'category': 'Programming'},
    'python3': {'name': 'Python Runtime', 'icon': '🐍', 'category': 'Programming'},
    'node': {'name': 'Node.js Runtime', 'icon': '🟢', 'category': 'Programming'},
    'docker': {'name': 'Docker', 'icon': '🐳', 'category': 'Containerization'},
    'slack': {'name': 'Slack', 'icon': '💬', 'category': 'Communication'},
    'discord': {'name': 'Discord', 'icon': '🎮', 'category': 'Communication'},
    'finder': {'name': 'macOS Finder', 'icon': '📁', 'category': 'Operating System'},
    'windowserver': {'name': 'macOS WindowServer', 'icon': '🖥️', 'category': 'Operating System'},
    'system': {'name': 'System / Kernel', 'icon': '⚙️', 'category': 'Operating System'}
}


def classify_process_app(name: str, cmdline: str = '') -> Dict[str, str]:
    """Determines application group, human-friendly name, icon, and category."""
    lower_name = (name or '').lower().strip()
    lower_cmd = (cmdline or '').lower()

    # Direct match on process executable name
    if lower_name in APP_SIGNATURES:
        return APP_SIGNATURES[lower_name]

    # Substring search in name
    for sig, info in APP_SIGNATURES.items():
        if sig in lower_name:
            return info

    # Check command line arguments for hints (e.g. 'python3 -m unittest' or 'npm run dev')
    for sig, info in APP_SIGNATURES.items():
        if sig in lower_cmd:
            return info

    # Fallback for unrecognized processes
    clean_name = name.split('/')[-1] if '/' in name else name
    return {
        'name': clean_name or 'Background Process',
        'icon': '⚙️',
        'category': 'Other Process'
    }


class MonitoringSession:
    """Represents an active pairing session with a student's local monitor agent."""

    def __init__(self, session_id: str, user_email: str, token: str, agent_metadata: dict):
        self.session_id: str = session_id
        self.user_email: str = user_email
        self.token: str = token
        self.agent_metadata: dict = agent_metadata or {}
        self.connected_at: float = time.time()
        self.last_heartbeat: float = time.time()
        self.is_active: bool = True
        # Rolling buffer: stores up to 180 snapshots (at 2s interval = 360s = 6 minutes)
        self.snapshots: deque = deque(maxlen=180)
        self.last_snapshot_time: float = 0.0

    def record_snapshot(self, snapshot_data: dict) -> Tuple[bool, str]:
        """Appends a new validated telemetry snapshot to the circular buffer."""
        now = time.time()
        # Rate-limiting check: reject snapshots arriving faster than 0.2s
        if now - self.last_snapshot_time < 0.2:
            return False, "Rate limit exceeded (snapshots too frequent)"

        self.last_heartbeat = now
        self.last_snapshot_time = now

        # Ensure timestamp is recorded
        if 'timestamp' not in snapshot_data:
            snapshot_data['timestamp'] = now

        # Enrich snapshot with categorized application summaries if not already present
        if 'applications' not in snapshot_data or not snapshot_data['applications']:
            snapshot_data['applications'] = self._aggregate_applications(snapshot_data.get('processes', []))

        self.snapshots.append(snapshot_data)
        return True, "Snapshot recorded"

    def _aggregate_applications(self, processes: List[dict]) -> List[dict]:
        """Aggregates individual processes into application groups."""
        groups: Dict[str, dict] = {}
        for p in processes:
            pname = p.get('name', '')
            cmdline = p.get('cmdline', '')
            info = classify_process_app(pname, cmdline)
            app_name = info['name']

            if app_name not in groups:
                groups[app_name] = {
                    'name': app_name,
                    'icon': info['icon'],
                    'category': info['category'],
                    'process_count': 0,
                    'cpu_percent': 0.0,
                    'memory_rss_mb': 0.0,
                    'pids': []
                }
            groups[app_name]['process_count'] += 1
            groups[app_name]['cpu_percent'] += float(p.get('cpu_percent', 0.0))
            groups[app_name]['memory_rss_mb'] += float(p.get('memory_rss_mb', 0.0))
            groups[app_name]['pids'].append(p.get('pid'))

        # Round numerical metrics
        result = []
        for g in groups.values():
            g['cpu_percent'] = round(g['cpu_percent'], 1)
            g['memory_rss_mb'] = round(g['memory_rss_mb'], 1)
            result.append(g)

        result.sort(key=lambda x: (x['cpu_percent'], x['memory_rss_mb']), reverse=True)
        return result

    @property
    def is_connected(self) -> bool:
        """Agent is considered connected if heartbeat was seen within the last 10 seconds."""
        return self.is_active and (time.time() - self.last_heartbeat <= 10.0)

    def get_latest_snapshot(self) -> Optional[dict]:
        if not self.snapshots:
            return None
        return self.snapshots[-1]


class RealMonitorManager:
    """Thread-safe singleton managing real process monitor pairings and sessions."""

    def __init__(self):
        self._lock = threading.Lock()
        # Pairing codes: code -> {'user_email': str, 'created_at': float, 'expires_at': float}
        self._pair_codes: Dict[str, dict] = {}
        # Active sessions by token: token -> MonitoringSession
        self._sessions_by_token: Dict[str, MonitoringSession] = {}
        # Active sessions by user: user_email -> MonitoringSession
        self._sessions_by_user: Dict[str, MonitoringSession] = {}

    def generate_pairing_code(self, user_email: str, ttl_seconds: int = 300) -> Tuple[str, int]:
        """Generates a secure, human-readable 6-character pairing code with 5-minute TTL."""
        with self._lock:
            # Clean expired codes
            now = time.time()
            expired = [c for c, data in self._pair_codes.items() if data['expires_at'] < now]
            for c in expired:
                del self._pair_codes[c]

            # Clear any pending codes for this user
            existing_user_codes = [c for c, data in self._pair_codes.items() if data['user_email'] == user_email]
            for c in existing_user_codes:
                del self._pair_codes[c]

            # Generate new 6-char alphanumeric code (excluding easily confused chars: 0, O, 1, I)
            charset = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'
            code = 'SR-' + ''.join(secrets.choice(charset) for _ in range(4))

            self._pair_codes[code] = {
                'user_email': user_email,
                'created_at': now,
                'expires_at': now + ttl_seconds
            }
            return code, ttl_seconds

    def connect_agent(self, pair_code: str, agent_metadata: dict) -> Tuple[bool, str, Optional[dict]]:
        """Exchanges a valid pairing code for a persistent revocable bearer token."""
        code = (pair_code or '').strip().upper()
        with self._lock:
            now = time.time()
            if code not in self._pair_codes:
                return False, "Invalid or unrecognized pairing code.", None

            code_data = self._pair_codes[code]
            if code_data['expires_at'] < now:
                del self._pair_codes[code]
                return False, "Pairing code has expired. Please generate a new code in SysRealm.", None

            user_email = code_data['user_email']
            # Single-use: consume code immediately
            del self._pair_codes[code]

            # If user already had a running session, close it cleanly
            if user_email in self._sessions_by_user:
                old_session = self._sessions_by_user[user_email]
                old_session.is_active = False
                if old_session.token in self._sessions_by_token:
                    del self._sessions_by_token[old_session.token]

            # Create new token and session
            token = 'sr_mon_' + secrets.token_hex(20)
            session_id = 'sess_' + secrets.token_hex(8)

            session = MonitoringSession(
                session_id=session_id,
                user_email=user_email,
                token=token,
                agent_metadata=agent_metadata
            )
            self._sessions_by_token[token] = session
            self._sessions_by_user[user_email] = session

            return True, "Agent paired successfully.", {
                'token': token,
                'session_id': session_id,
                'interval': 2.0,
                'user_email': user_email
            }

    def get_session_by_token(self, token: str) -> Optional[MonitoringSession]:
        with self._lock:
            session = self._sessions_by_token.get(token)
            if session and session.is_active:
                return session
            return None

    def get_session_by_user(self, user_email: str) -> Optional[MonitoringSession]:
        with self._lock:
            return self._sessions_by_user.get(user_email)

    def stop_session(self, user_email: str) -> bool:
        """Revokes bearer token and stops monitoring for a given user."""
        with self._lock:
            session = self._sessions_by_user.get(user_email)
            if not session:
                return False
            session.is_active = False
            if session.token in self._sessions_by_token:
                del self._sessions_by_token[session.token]
            del self._sessions_by_user[user_email]
            return True

    def get_timeline(self, user_email: str, window_seconds: int = 120) -> List[dict]:
        """Formats the Observed Real Process Activity Timeline for the frontend.

        Returns discrete observations over time (e.g. every 2 seconds):
        [
          {
            "timestamp": "22:15:02",
            "t_offset": 0,
            "system_cpu": 14.5,
            "system_ram_mb": 8420.0,
            "top_apps": [
              {"name": "Google Chrome", "cpu_percent": 12.1, "activity": "ACTIVE"},
              {"name": "VS Code", "cpu_percent": 2.4, "activity": "LOW"}
            ]
          }, ...
        ]
        """
        session = self.get_session_by_user(user_email)
        if not session or not session.snapshots:
            return []

        now = time.time()
        cutoff = now - max(30, min(window_seconds, 600))

        timeline = []
        with self._lock:
            # Snapshots are in chronologic order
            recent = [s for s in session.snapshots if s.get('timestamp', 0) >= cutoff]
            if not recent and session.snapshots:
                recent = list(session.snapshots)[-30:]  # fallback to last 30 snapshots

            for s in recent:
                ts = s.get('timestamp', now)
                sys_sum = s.get('system_summary', {})
                apps = s.get('applications', [])

                top_apps_data = []
                for a in apps[:8]:
                    cpu = float(a.get('cpu_percent', 0.0))
                    if cpu >= 15.0:
                        activity = 'HIGH'
                    elif cpu >= 5.0:
                        activity = 'ACTIVE'
                    elif cpu > 0.5:
                        activity = 'LOW'
                    else:
                        activity = 'IDLE'

                    top_apps_data.append({
                        'name': a.get('name', 'Unknown'),
                        'icon': a.get('icon', '⚙️'),
                        'category': a.get('category', 'App'),
                        'cpu_percent': cpu,
                        'memory_rss_mb': a.get('memory_rss_mb', 0.0),
                        'activity': activity
                    })

                timeline.append({
                    'timestamp': time.strftime('%H:%M:%S', time.localtime(ts)),
                    'raw_time': ts,
                    'system_cpu': sys_sum.get('cpu_total_percent', 0.0),
                    'system_ram_percent': sys_sum.get('memory_percent', 0.0),
                    'system_ram_used_mb': sys_sum.get('memory_used_mb', 0.0),
                    'process_count': sys_sum.get('process_count', 0),
                    'top_apps': top_apps_data
                })

        return timeline


# Global singleton instance
monitor_manager = RealMonitorManager()
