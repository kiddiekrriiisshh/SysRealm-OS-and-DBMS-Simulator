#!/usr/bin/env python3
"""
SysRealm Local OS Process Monitor Agent
=======================================
Academic Project: SysRealm (Third-Year B.Tech CSE)
Author: Real Applications Monitoring Module

Usage:
    python3 local_monitor/agent.py --server http://localhost:5000 --pair SR-7X2K
    python3 local_monitor/agent.py --config config.json
"""

import os
import sys
import time
import json
import signal
import socket
import platform
import argparse

# Allow imports from local directory if run directly
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from monitor import SystemMonitor, PSUTIL_AVAILABLE
from transport import MonitorTransport, REQUESTS_AVAILABLE


class SysRealmAgent:
    """Coordinates OS process monitoring and telemetry streaming to SysRealm."""

    def __init__(self, server_url: str, pair_code: str = None, token: str = None,
                 interval: float = 2.0, max_procs: int = 50):
        self.server_url = server_url
        self.pair_code = pair_code
        self.token = token
        self.interval = max(1.0, min(interval, 10.0))
        self.max_procs = max_procs
        self.running = True

        self.monitor = SystemMonitor(max_processes=self.max_procs)
        self.transport = MonitorTransport(server_url=self.server_url, token=self.token)

    def _setup_signals(self):
        def handle_exit(sig, frame):
            print("\n\n[SysRealm Monitor] Shutting down agent cleanly...")
            self.running = False

        signal.signal(signal.SIGINT, handle_exit)
        signal.signal(signal.SIGTERM, handle_exit)

    def _get_agent_metadata(self) -> dict:
        return {
            'hostname': socket.gethostname(),
            'platform': platform.platform(),
            'python_version': platform.python_version(),
            'os_name': platform.system(),
            'cpu_count': os.cpu_count() or 1,
            'agent_version': '1.0.0'
        }

    def run(self):
        self._setup_signals()

        print("=" * 64)
        print("   SYSREALM: REAL APPLICATIONS MONITOR AGENT (v1.0.0)")
        print("   Mode B: Live OS Process Telemetry Streamer")
        print("=" * 64)

        if not PSUTIL_AVAILABLE:
            print("\n[ERROR] Missing dependency 'psutil'.")
            print("Please run: pip install -r local_monitor/requirements.txt")
            return 1

        if not REQUESTS_AVAILABLE:
            print("\n[ERROR] Missing dependency 'requests'.")
            print("Please run: pip install -r local_monitor/requirements.txt")
            return 1

        print(f"Target Server : {self.server_url}")
        print(f"Host System   : {platform.system()} ({platform.release()})")
        print(f"Sampling Rate : Every {self.interval}s")
        print("-" * 64)

        # Authenticate / Pair
        if not self.transport.token:
            if not self.pair_code:
                print("[ERROR] Neither a pair code nor a bearer token was provided.")
                print("Usage: python3 local_monitor/agent.py --server http://localhost:5000 --pair SR-XXXX")
                return 1

            print(f"[1/2] Connecting to SysRealm with pairing code '{self.pair_code}'...")
            meta = self._get_agent_metadata()
            ok, msg = self.transport.pair_with_code(self.pair_code, meta)
            if not ok:
                print(f"[FAILED] Could not pair: {msg}")
                return 1
            print(f"[2/2] Paired successfully! Session ID: {self.transport.session_id}")
            self.interval = self.transport.interval
        else:
            print(f"[1/1] Reusing existing bearer token. Session ready.")

        print("\n[✓] Telemetry active. Streaming live process metrics to SysRealm...")
        print("Press Ctrl+C at any time to stop monitoring.\n")
        print(f"{'TIME':<10} | {'SNAPSHOT':<9} | {'CPU %':<7} | {'RAM (MB)':<10} | {'APPS':<5} | {'TOP ACTIVE APP'}")
        print("-" * 64)

        snapshot_seq = 0
        consecutive_failures = 0

        while self.running:
            start_t = time.time()
            snapshot_seq += 1

            # Collect metrics safely
            data = self.monitor.collect_snapshot()
            data['seq'] = snapshot_seq

            # Transmit to SysRealm
            ok, msg = self.transport.send_snapshot(data)

            now_str = time.strftime('%H:%M:%S', time.localtime(data['timestamp']))
            sys_cpu = data['system_summary'].get('cpu_total_percent', 0.0)
            sys_ram = data['system_summary'].get('memory_used_mb', 0.0)
            num_apps = len(data.get('applications', []))
            top_app = data['applications'][0]['name'] if data.get('applications') else "None"
            top_app_cpu = data['applications'][0]['cpu_percent'] if data.get('applications') else 0.0

            if ok:
                consecutive_failures = 0
                print(f"{now_str:<10} | #{snapshot_seq:<8} | {sys_cpu:>5.1f}% | {sys_ram:>8.1f}MB | {num_apps:<5} | {top_app} ({top_app_cpu}%)")
            else:
                consecutive_failures += 1
                print(f"{now_str:<10} | #{snapshot_seq:<8} | [WARN] {msg}")
                if "Session terminated" in msg or "token revoked" in msg:
                    print("\n[!] The monitoring session was stopped by the user from the SysRealm dashboard.")
                    break
                if consecutive_failures >= 15:
                    print("\n[!] Lost connection to SysRealm server after 15 attempts. Stopping.")
                    break

            # Sleep remaining time in interval
            elapsed = time.time() - start_t
            sleep_time = max(0.1, self.interval - elapsed)
            time.sleep(sleep_time)

        print("\n[SysRealm Monitor] Agent stopped. Goodbye!")
        return 0


def main():
    parser = argparse.ArgumentParser(description="SysRealm Real Process Monitor Agent")
    parser.add_argument('--server', default="http://127.0.0.1:5000", help="SysRealm server base URL")
    parser.add_argument('--pair', default=None, help="6-character pairing code from SysRealm UI")
    parser.add_argument('--token', default=None, help="Bearer token (if previously paired)")
    parser.add_argument('--interval', type=float, default=2.0, help="Sampling interval in seconds (default: 2.0)")
    parser.add_argument('--max-procs', type=int, default=50, help="Max processes to send per snapshot")
    parser.add_argument('--config', default=None, help="Path to config JSON file")

    args = parser.parse_args()

    server = args.server
    pair_code = args.pair
    token = args.token
    interval = args.interval
    max_procs = args.max_procs

    if args.config and os.path.exists(args.config):
        try:
            with open(args.config, 'r') as f:
                cfg = json.load(f)
                server = cfg.get('server_url', server)
                pair_code = cfg.get('pair_code', pair_code)
                token = cfg.get('token', token)
                interval = cfg.get('interval_seconds', interval)
                max_procs = cfg.get('max_processes', max_procs)
        except Exception as e:
            print(f"[WARN] Could not parse config file: {e}")

    agent = SysRealmAgent(
        server_url=server,
        pair_code=pair_code,
        token=token,
        interval=interval,
        max_procs=max_procs
    )
    sys.exit(agent.run())


if __name__ == '__main__':
    main()
