"""
SysRealm Local OS Process Monitor
=================================
Collects non-invasive, read-only system telemetry using `psutil`.

Safety Guarantees:
- Strictly READ-ONLY telemetry. Never executes kill, nice, signal, or sudo.
- Non-blocking CPU measurement (uses cached intervals to avoid thread starvation).
- Safe exception handling for short-lived processes (NoSuchProcess, AccessDenied, ZombieProcess).
- Compound process identity (PID + creation timestamp) protects against OS PID reuse.
- Aggregates multi-process applications (e.g. Chrome, VS Code, Spotify, Terminal).
"""

import os
import sys
import time
import platform
from typing import Dict, List, Optional, Any, Tuple

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False


# Desktop Application Classification Signatures
APP_RULES = [
    # (needle_in_name, needle_in_cmdline, app_name, icon, category)
    ('google chrome', None, 'Google Chrome', '🌐', 'Web Browser'),
    ('chrome', None, 'Google Chrome', '🌐', 'Web Browser'),
    ('chromium', None, 'Chromium', '🌐', 'Web Browser'),
    ('brave', None, 'Brave Browser', '🦁', 'Web Browser'),
    ('safari', None, 'Apple Safari', '🧭', 'Web Browser'),
    ('firefox', None, 'Mozilla Firefox', '🦊', 'Web Browser'),
    ('code', None, 'VS Code', '💻', 'Development'),
    ('cursor', None, 'Cursor IDE', '⚡', 'Development'),
    ('antigravity', None, 'Antigravity IDE', '🚀', 'Development'),
    ('pycharm', None, 'PyCharm', '🐍', 'Development'),
    ('sublime_text', None, 'Sublime Text', '📝', 'Development'),
    ('spotify', None, 'Spotify', '🎵', 'Media Player'),
    ('vlc', None, 'VLC Player', '🎬', 'Media Player'),
    ('music', None, 'Apple Music', '🎵', 'Media Player'),
    ('terminal', None, 'Terminal', '⬛', 'System Utility'),
    ('iterm2', None, 'iTerm2', '⬛', 'System Utility'),
    ('kitty', None, 'Kitty', '🐱', 'System Utility'),
    ('alacritty', None, 'Alacritty', '⚡', 'System Utility'),
    ('zsh', None, 'Zsh Shell', '🐚', 'System Utility'),
    ('bash', None, 'Bash Shell', '🐚', 'System Utility'),
    ('python', None, 'Python Process', '🐍', 'Programming'),
    ('node', None, 'Node.js', '🟢', 'Programming'),
    ('docker', None, 'Docker Engine', '🐳', 'Containerization'),
    ('slack', None, 'Slack', '💬', 'Communication'),
    ('discord', None, 'Discord', '🎮', 'Communication'),
    ('teams', None, 'Microsoft Teams', '👥', 'Communication'),
    ('zoom', None, 'Zoom', '📹', 'Communication'),
    ('finder', None, 'macOS Finder', '📁', 'Operating System'),
    ('windowserver', None, 'macOS WindowServer', '🖥️', 'Operating System'),
    ('explorer.exe', None, 'Windows Explorer', '📁', 'Operating System'),
]


def classify_app(name: str, cmdline_str: str = '') -> Tuple[str, str, str]:
    """Matches a process to an application group, icon, and category."""
    n = (name or '').lower().strip()
    c = (cmdline_str or '').lower()

    for needle_n, needle_c, app_name, icon, cat in APP_RULES:
        if needle_n and needle_n in n:
            return app_name, icon, cat
        if needle_c and needle_c in c:
            return app_name, icon, cat

    clean_name = name.split('/')[-1] if '/' in name else name
    return clean_name or 'System Process', '⚙️', 'Other'


class SystemMonitor:
    """Collects system-wide and per-process telemetry using psutil."""

    def __init__(self, max_processes: int = 60):
        self.max_processes = max_processes
        self.is_initialized = False
        self._prime_measurements()

    def _prime_measurements(self):
        """Initializes psutil CPU measurement timers to avoid 0.0% initial artifacts."""
        if not PSUTIL_AVAILABLE:
            return
        try:
            psutil.cpu_percent(interval=None)
            for p in psutil.process_iter(['pid']):
                try:
                    p.cpu_percent(interval=None)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            self.is_initialized = True
        except Exception as e:
            # Non-fatal during startup
            pass

    def collect_snapshot(self) -> Dict[str, Any]:
        """Collects a complete telemetry snapshot: system totals, app groups, and processes."""
        if not PSUTIL_AVAILABLE:
            return {
                'timestamp': time.time(),
                'error': 'psutil library not installed. Please run: pip install -r requirements.txt',
                'system_summary': {
                    'cpu_total_percent': 0.0,
                    'memory_total_mb': 0.0,
                    'memory_used_mb': 0.0,
                    'memory_percent': 0.0,
                    'process_count': 0,
                    'platform': f"{platform.system()} {platform.release()}"
                },
                'applications': [],
                'processes': []
            }

        now = time.time()
        # System-level metrics
        try:
            cpu_total = round(psutil.cpu_percent(interval=None), 1)
        except Exception:
            cpu_total = 0.0

        try:
            vm = psutil.virtual_memory()
            mem_total_mb = round(vm.total / (1024 * 1024), 1)
            mem_used_mb = round(vm.used / (1024 * 1024), 1)
            mem_percent = round(vm.percent, 1)
        except Exception:
            mem_total_mb = 0.0
            mem_used_mb = 0.0
            mem_percent = 0.0

        processes_data: List[Dict[str, Any]] = []
        app_aggregates: Dict[str, Dict[str, Any]] = {}
        total_procs = 0

        # Scan active processes safely
        for p in psutil.process_iter(['pid', 'ppid', 'name', 'cmdline', 'status', 'create_time', 'num_threads']):
            try:
                total_procs += 1
                info = p.info
                pid = info.get('pid')
                ppid = info.get('ppid') or 0
                name = info.get('name') or 'unknown'
                cmdline_list = info.get('cmdline') or []
                cmdline_str = ' '.join(cmdline_list[:10])  # limit length for privacy & payload size
                create_time = info.get('create_time') or now
                status = info.get('status') or 'unknown'
                num_threads = info.get('num_threads') or 1

                # Safe non-blocking CPU percent
                try:
                    cpu_perc = round(p.cpu_percent(interval=None), 1)
                except Exception:
                    cpu_perc = 0.0

                # Memory usage
                try:
                    mem_info = p.memory_info()
                    rss_mb = round(mem_info.rss / (1024 * 1024), 1)
                    vms_mb = round(mem_info.vms / (1024 * 1024), 1)
                except Exception:
                    rss_mb = 0.0
                    vms_mb = 0.0

                app_name, icon, category = classify_app(name, cmdline_str)
                uid_key = f"{pid}_{int(create_time)}"

                # Add to app aggregates
                if app_name not in app_aggregates:
                    app_aggregates[app_name] = {
                        'name': app_name,
                        'icon': icon,
                        'category': category,
                        'process_count': 0,
                        'cpu_percent': 0.0,
                        'memory_rss_mb': 0.0,
                        'main_pid': pid
                    }
                app_aggregates[app_name]['process_count'] += 1
                app_aggregates[app_name]['cpu_percent'] += cpu_perc
                app_aggregates[app_name]['memory_rss_mb'] += rss_mb

                proc_record = {
                    'pid': pid,
                    'ppid': ppid,
                    'uid': uid_key,
                    'name': name,
                    'cmdline': cmdline_str[:120],  # truncated sanitized summary
                    'app_name': app_name,
                    'app_icon': icon,
                    'app_category': category,
                    'cpu_percent': cpu_perc,
                    'memory_rss_mb': rss_mb,
                    'memory_vms_mb': vms_mb,
                    'status': status,
                    'threads': num_threads,
                    'create_time': create_time
                }
                processes_data.append(proc_record)

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue

        # Sort applications by CPU desc, then memory desc
        app_list = []
        for a in app_aggregates.values():
            a['cpu_percent'] = round(a['cpu_percent'], 1)
            a['memory_rss_mb'] = round(a['memory_rss_mb'], 1)
            app_list.append(a)
        app_list.sort(key=lambda x: (x['cpu_percent'], x['memory_rss_mb']), reverse=True)

        # Sort individual processes by CPU desc, then RSS desc, and slice to max_processes
        processes_data.sort(key=lambda x: (x['cpu_percent'], x['memory_rss_mb']), reverse=True)
        top_processes = processes_data[:self.max_processes]

        return {
            'timestamp': now,
            'system_summary': {
                'cpu_total_percent': cpu_total,
                'memory_total_mb': mem_total_mb,
                'memory_used_mb': mem_used_mb,
                'memory_percent': mem_percent,
                'process_count': total_procs,
                'platform': f"{platform.system()} {platform.release()}"
            },
            'applications': app_list,
            'processes': top_processes
        }
