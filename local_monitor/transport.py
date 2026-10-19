"""
SysRealm Local Monitor Transport Client
=======================================
Communicates with SysRealm backend API using standard HTTP/HTTPS.
Handles pairing code exchange, bearer token authentication, and telemetry posting.
"""

import sys
import time
from typing import Dict, Optional, Tuple, Any

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    requests = None
    REQUESTS_AVAILABLE = False


class MonitorTransport:
    """Handles network communication between local monitor agent and SysRealm server."""

    def __init__(self, server_url: str, token: Optional[str] = None, timeout: float = 5.0):
        self.server_url = server_url.rstrip('/')
        self.token = token
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self.interval: float = 2.0

    def pair_with_code(self, pair_code: str, agent_metadata: dict) -> Tuple[bool, str]:
        """Exchanges single-use pairing code for a bearer token."""
        if not REQUESTS_AVAILABLE:
            return False, "Python 'requests' library not found. Run: pip install requests"

        url = f"{self.server_url}/api/real-monitor/connect"
        payload = {
            'pair_code': pair_code.strip().upper(),
            'agent_metadata': agent_metadata
        }

        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            data = resp.json()
            if resp.status_code == 200 and data.get('success'):
                self.token = data.get('token')
                self.session_id = data.get('session_id')
                self.interval = float(data.get('interval', 2.0))
                return True, data.get('message', 'Successfully paired!')
            else:
                return False, data.get('error', f"HTTP {resp.status_code}: Failed to pair")
        except requests.exceptions.ConnectionError:
            return False, f"Could not connect to SysRealm at {self.server_url}. Is SysRealm running?"
        except Exception as e:
            return False, f"Connection error: {str(e)}"

    def send_snapshot(self, snapshot: Dict[str, Any]) -> Tuple[bool, str]:
        """Transmits an authenticated telemetry snapshot to SysRealm."""
        if not self.token:
            return False, "Not authenticated (missing bearer token)"
        if not REQUESTS_AVAILABLE:
            return False, "Python 'requests' library not found"

        url = f"{self.server_url}/api/real-monitor/snapshot"
        headers = {
            'Authorization': f"Bearer {self.token}",
            'Content-Type': 'application/json'
        }

        try:
            resp = requests.post(url, json=snapshot, headers=headers, timeout=self.timeout)
            if resp.status_code == 200:
                return True, "Snapshot accepted"
            elif resp.status_code == 401:
                return False, "Session terminated or token revoked by server"
            else:
                data = resp.json() if resp.content else {}
                return False, data.get('error', f"HTTP {resp.status_code}")
        except requests.exceptions.RequestException as e:
            return False, f"Network error: {str(e)}"
