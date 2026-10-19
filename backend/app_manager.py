"""
SysRealm Real Applications & Multi-Process Memory Manager
Simulates real desktop/web applications with multi-process architectures:
- Web Browser (UI process, multiple Tab processes, GPU engine)
- Code Editor (Editor core, Language Server, Terminal, Extensions)
- Media Player (UI, Audio DSP Engine, Network Buffer)
- 3D Game Engine (Game Loop, Vulkan Shaders, Physics Particle Worker)

Features:
- Hierarchical Task Manager process tree (Parent App -> Child Processes/Tabs)
- Interactive Kill / End Process (reclaims physical frames)
- Virtual Memory Paging & Swapping to Simulated Disk
- Kernel Out-Of-Memory (OOM) Killer daemon with Badness Score algorithm
- Memory Stress Tester for live pressure demonstrations
"""

import math
import copy
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from . import scheduler


@dataclass
class AppProcess:
    pid: str
    name: str
    role: str
    memory_mb: int
    burst_time: int
    priority: int = 2
    state: str = 'RUNNING'  # RUNNING, SWAPPED, TERMINATED
    arrival_time: int = 0
    is_main: bool = False
    swap_slot: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RealApp:
    def __init__(self, app_id: str, name: str, icon: str, category: str, description: str):
        self.app_id = app_id
        self.name = name
        self.icon = icon
        self.category = category
        self.description = description
        self.processes: List[AppProcess] = []
        self.status: str = 'STOPPED'  # STOPPED, RUNNING, PARTIALLY_SWAPPED, SWAPPED

    @property
    def total_memory_mb(self) -> int:
        return sum(p.memory_mb for p in self.processes if p.state != 'TERMINATED')

    @property
    def physical_ram_mb(self) -> int:
        return sum(p.memory_mb for p in self.processes if p.state == 'RUNNING')

    @property
    def swapped_ram_mb(self) -> int:
        return sum(p.memory_mb for p in self.processes if p.state == 'SWAPPED')

    def to_dict(self) -> Dict[str, Any]:
        active_procs = [p for p in self.processes if p.state != 'TERMINATED']
        has_running = any(p.state == 'RUNNING' for p in active_procs)
        has_swapped = any(p.state == 'SWAPPED' for p in active_procs)

        if not active_procs:
            status = 'STOPPED'
        elif has_running and has_swapped:
            status = 'PARTIALLY_SWAPPED'
        elif has_swapped:
            status = 'SWAPPED'
        else:
            status = 'RUNNING'
        self.status = status

        return {
            'app_id': self.app_id,
            'name': self.name,
            'icon': self.icon,
            'category': self.category,
            'description': self.description,
            'status': self.status,
            'total_memory_mb': self.total_memory_mb,
            'physical_ram_mb': self.physical_ram_mb,
            'swapped_ram_mb': self.swapped_ram_mb,
            'process_count': len(active_procs),
            'processes': [p.to_dict() for p in active_procs]
        }


# Default Application Blueprints (Realistic modern process hierarchies)
APP_BLUEPRINTS = {
    'browser': {
        'name': 'Quantum Web Browser',
        'icon': '🌐',
        'category': 'Internet & Web',
        'description': 'Multi-process browser architecture isolating UI, individual tabs, and GPU acceleration.',
        'processes': [
            {'name': 'Browser Main UI', 'role': 'Parent / Browser Core', 'memory_mb': 512, 'burst_time': 5, 'priority': 1, 'is_main': True},
            {'name': 'Tab: 3D WebGL Canvas', 'role': 'Web Content Tab', 'memory_mb': 1024, 'burst_time': 8, 'priority': 3, 'is_main': False},
            {'name': 'Tab: 4K Stream Video', 'role': 'Media Player Tab', 'memory_mb': 768, 'burst_time': 6, 'priority': 2, 'is_main': False},
            {'name': 'Tab: Wikipedia Docs', 'role': 'Lightweight Reader Tab', 'memory_mb': 256, 'burst_time': 3, 'priority': 3, 'is_main': False},
            {'name': 'GPU Rasterizer Engine', 'role': 'Hardware Acceleration', 'memory_mb': 512, 'burst_time': 4, 'priority': 1, 'is_main': False},
        ]
    },
    'code_editor': {
        'name': 'SysCode Studio IDE',
        'icon': '💻',
        'category': 'Development',
        'description': 'Modern code editor with separate extension host, language servers, and terminal workers.',
        'processes': [
            {'name': 'Editor Main Window', 'role': 'Parent / Editor UI', 'memory_mb': 512, 'burst_time': 4, 'priority': 1, 'is_main': True},
            {'name': 'PyRight / LSP Language Server', 'role': 'Syntax & Type Checker', 'memory_mb': 768, 'burst_time': 7, 'priority': 2, 'is_main': False},
            {'name': 'Integrated Terminal (zsh)', 'role': 'Shell Worker Process', 'memory_mb': 256, 'burst_time': 3, 'priority': 3, 'is_main': False},
            {'name': 'Debugger & Profiler Agent', 'role': 'Runtime Inspector', 'memory_mb': 512, 'burst_time': 5, 'priority': 2, 'is_main': False},
        ]
    },
    'media_player': {
        'name': 'PulseStream Hi-Fi',
        'icon': '🎵',
        'category': 'Multimedia',
        'description': 'Audio stream application with realtime DSP processing and ring-buffered network cache.',
        'processes': [
            {'name': 'Player Shell UI', 'role': 'Parent / Playback Controller', 'memory_mb': 256, 'burst_time': 3, 'priority': 2, 'is_main': True},
            {'name': 'DSP Equalizer Engine', 'role': 'Realtime Audio Synthesizer', 'memory_mb': 512, 'burst_time': 5, 'priority': 1, 'is_main': False},
            {'name': 'Network Stream Buffer', 'role': 'I/O Ring Cache', 'memory_mb': 384, 'burst_time': 4, 'priority': 2, 'is_main': False},
        ]
    },
    'game_engine': {
        'name': 'NeoRender 3D Simulation',
        'icon': '🎮',
        'category': 'Graphics & Gaming',
        'description': 'High-performance interactive 3D simulation with heavy physical memory footprint.',
        'processes': [
            {'name': 'Game Main Loop', 'role': 'Parent / Game Controller', 'memory_mb': 512, 'burst_time': 6, 'priority': 1, 'is_main': True},
            {'name': 'Vulkan Shader Pipeline', 'role': 'Texture & Geometry Shaders', 'memory_mb': 1536, 'burst_time': 9, 'priority': 3, 'is_main': False},
            {'name': 'Physics Particle Worker', 'role': 'Rigid-body Collision Engine', 'memory_mb': 768, 'burst_time': 7, 'priority': 2, 'is_main': False},
        ]
    }
}


class AppManager:
    """
    Manages realistic desktop/web applications in SysRealm.
    Coordinates process registration in ProcessManager, physical frame allocation
    in MemoryManager, swap space storage on simulated disk, and OOM killer protection.
    """

    def __init__(self, process_manager, memory_manager):
        self.process_manager = process_manager
        self.memory_manager = memory_manager
        self.apps: Dict[str, RealApp] = {}
        self.swap_space: Dict[str, Dict[str, Any]] = {}  # pid -> swap details
        self.max_swap_mb: int = 8192  # 8 GB simulated secondary storage swap file
        self.oom_logs: List[Dict[str, Any]] = []
        self._proc_counter = 100
        self._swap_slot_counter = 1
        self._init_apps()

    def _init_apps(self):
        for app_id, spec in APP_BLUEPRINTS.items():
            self.apps[app_id] = RealApp(
                app_id=app_id,
                name=spec['name'],
                icon=spec['icon'],
                category=spec['category'],
                description=spec['description']
            )

    def get_blueprints(self) -> List[Dict[str, Any]]:
        return [
            {
                'app_id': app_id,
                'name': spec['name'],
                'icon': spec['icon'],
                'category': spec['category'],
                'description': spec['description'],
                'default_process_count': len(spec['processes']),
                'default_memory_mb': sum(p['memory_mb'] for p in spec['processes'])
            }
            for app_id, spec in APP_BLUEPRINTS.items()
        ]

    def launch_app(self, app_id: str) -> Dict[str, Any]:
        """
        Launches an application: creates parent + child processes in ProcessManager
        and allocates their physical frames in MemoryManager.
        """
        if app_id not in APP_BLUEPRINTS:
            return {'success': False, 'error': f'Application "{app_id}" not found'}

        app = self.apps[app_id]
        if app.processes and any(p.state != 'TERMINATED' for p in app.processes):
            return {'success': False, 'error': f'{app.name} is already running!'}

        blueprint = APP_BLUEPRINTS[app_id]
        launched_procs = []
        failed_procs = []

        for p_spec in blueprint['processes']:
            pid = f"A_{app_id[:3].upper()}_{self._proc_counter}"
            self._proc_counter += 1

            app_proc = AppProcess(
                pid=pid,
                name=p_spec['name'],
                role=p_spec['role'],
                memory_mb=p_spec['memory_mb'],
                burst_time=p_spec['burst_time'],
                priority=p_spec.get('priority', 2),
                state='RUNNING',
                is_main=p_spec.get('is_main', False)
            )

            # 1. Register into ProcessManager so CPU Schedulers can see and execute it
            try:
                self.process_manager.create_process(
                    name=f"[{app.icon} {app_proc.name}]",
                    arrival_time=0,
                    burst_time=app_proc.burst_time,
                    priority=app_proc.priority,
                    memory_mb=app_proc.memory_mb,
                    pid=pid
                )
            except Exception:
                pass

            # 2. Allocate physical frames in MemoryManager
            alloc_res = self.memory_manager.allocate(
                pid=pid,
                name=f"[{app.name}] {app_proc.name}",
                size_mb=app_proc.memory_mb
            )

            if alloc_res.get('success'):
                app.processes.append(app_proc)
                launched_procs.append(app_proc.to_dict())
            else:
                # Insufficient physical RAM: Check if we can auto-swap or report memory pressure
                failed_procs.append({
                    'pid': pid,
                    'name': app_proc.name,
                    'memory_mb': app_proc.memory_mb,
                    'error': alloc_res.get('error', 'Insufficient physical RAM')
                })

        app.status = 'RUNNING' if launched_procs else 'STOPPED'

        return {
            'success': True if launched_procs else False,
            'app': app.to_dict(),
            'launched_count': len(launched_procs),
            'failed_count': len(failed_procs),
            'failed_procs': failed_procs,
            'memory_state': self.memory_manager.get_state()
        }

    def spawn_tab(self, app_id: str, tab_name: Optional[str] = None, memory_mb: int = 512) -> Dict[str, Any]:
        """
        Dynamically spawns a new tab/worker in a running application (e.g. user clicks + New Tab in Browser).
        """
        if app_id not in self.apps:
            return {'success': False, 'error': f'App "{app_id}" not found'}

        app = self.apps[app_id]
        if not app.processes or all(p.state == 'TERMINATED' for p in app.processes):
            # If app not running, launch it first
            launch_res = self.launch_app(app_id)
            if not launch_res['success']:
                return launch_res

        tab_idx = len([p for p in app.processes if p.state != 'TERMINATED']) + 1
        name = tab_name or f"Tab #{tab_idx}: Dynamic Worker"
        pid = f"A_{app_id[:3].upper()}_{self._proc_counter}"
        self._proc_counter += 1

        app_proc = AppProcess(
            pid=pid,
            name=name,
            role="Dynamically Spawned Tab Worker",
            memory_mb=max(128, int(memory_mb)),
            burst_time=4,
            priority=3,
            state='RUNNING',
            is_main=False
        )

        # 1. Register in ProcessManager
        try:
            self.process_manager.create_process(
                name=f"[{app.icon} {app_proc.name}]",
                arrival_time=0,
                burst_time=app_proc.burst_time,
                priority=app_proc.priority,
                memory_mb=app_proc.memory_mb,
                pid=pid
            )
        except Exception:
            pass

        # 2. Allocate in MemoryManager
        alloc_res = self.memory_manager.allocate(
            pid=pid,
            name=f"[{app.name}] {app_proc.name}",
            size_mb=app_proc.memory_mb
        )

        if not alloc_res.get('success'):
            return {
                'success': False,
                'error': f"Failed to allocate {memory_mb} MB for {name}: {alloc_res.get('error')}",
                'out_of_memory': True,
                'memory_state': self.memory_manager.get_state()
            }

        app.processes.append(app_proc)

        return {
            'success': True,
            'message': f"Spawned {name} ({memory_mb} MB) in {app.name}",
            'process': app_proc.to_dict(),
            'app': app.to_dict(),
            'memory_state': self.memory_manager.get_state()
        }

    def kill_process(self, app_id: str, pid: str) -> Dict[str, Any]:
        """
        Interactive Process Termination: Immediately terminates an individual child process or tab,
        reclaiming its physical frames in MemoryManager and releasing swap space.
        """
        target_app = self.apps.get(app_id)
        if not target_app:
            # Find app by pid
            for a in self.apps.values():
                if any(p.pid == pid for p in a.processes):
                    target_app = a
                    break

        if not target_app:
            return {'success': False, 'error': f'Process {pid} does not belong to any application'}

        target_proc = next((p for p in target_app.processes if p.pid == pid), None)
        if not target_proc:
            return {'success': False, 'error': f'Process {pid} not found in {target_app.name}'}

        was_swapped = target_proc.state == 'SWAPPED'
        freed_mb = target_proc.memory_mb

        # 1. Release physical memory if it was in RAM
        if not was_swapped:
            self.memory_manager.release(pid)
        else:
            self.swap_space.pop(pid, None)

        # 2. Remove from ProcessManager
        self.process_manager.delete_process(pid)

        # 3. Mark process terminated
        target_proc.state = 'TERMINATED'

        # Check if entire app terminated
        remaining = [p for p in target_app.processes if p.state != 'TERMINATED']
        if not remaining:
            target_app.status = 'STOPPED'

        return {
            'success': True,
            'message': f"Terminated {target_proc.name} (PID: {pid}). Reclaimed {freed_mb} MB " + ("from Swap" if was_swapped else "of Physical RAM!"),
            'freed_mb': freed_mb,
            'was_swapped': was_swapped,
            'app': target_app.to_dict(),
            'memory_state': self.memory_manager.get_state()
        }

    def terminate_app(self, app_id: str) -> Dict[str, Any]:
        """
        Closes entire application tree: terminates all child processes and reclaims all memory.
        """
        if app_id not in self.apps:
            return {'success': False, 'error': f'App "{app_id}" not found'}

        app = self.apps[app_id]
        total_freed_ram = 0
        total_freed_swap = 0

        for p in list(app.processes):
            if p.state == 'RUNNING':
                self.memory_manager.release(p.pid)
                total_freed_ram += p.memory_mb
            elif p.state == 'SWAPPED':
                self.swap_space.pop(p.pid, None)
                total_freed_swap += p.memory_mb
            self.process_manager.delete_process(p.pid)
            p.state = 'TERMINATED'

        app.processes.clear()
        app.status = 'STOPPED'

        return {
            'success': True,
            'message': f"Closed {app.name}. Reclaimed {total_freed_ram} MB RAM and {total_freed_swap} MB Swap.",
            'freed_ram_mb': total_freed_ram,
            'freed_swap_mb': total_freed_swap,
            'app': app.to_dict(),
            'memory_state': self.memory_manager.get_state()
        }

    def swap_process(self, app_id: str, pid: str, action: str = 'swap_out') -> Dict[str, Any]:
        """
        Simulates OS Demand Paging & Swapping to Disk:
        - `swap_out`: Frees physical frames in RAM and writes pages to simulated secondary storage swap space.
        - `swap_in`: Reads pages back from swap space and allocates physical frames in RAM.
        """
        target_app = self.apps.get(app_id)
        if not target_app:
            for a in self.apps.values():
                if any(p.pid == pid for p in a.processes):
                    target_app = a
                    break

        if not target_app:
            return {'success': False, 'error': f'Process {pid} not found'}

        target_proc = next((p for p in target_app.processes if p.pid == pid), None)
        if not target_proc:
            return {'success': False, 'error': f'Process {pid} not found'}

        if action == 'swap_out':
            if target_proc.state == 'SWAPPED':
                return {'success': False, 'error': f'Process {pid} is already swapped to disk!'}

            used_swap = sum(item['size_mb'] for item in self.swap_space.values())
            if used_swap + target_proc.memory_mb > self.max_swap_mb:
                return {'success': False, 'error': 'Swap Space Full! Cannot page out process to disk.'}

            # 1. Release physical RAM frames
            self.memory_manager.release(pid)

            # 2. Record in swap space
            slot = self._swap_slot_counter
            self._swap_slot_counter += 1
            self.swap_space[pid] = {
                'pid': pid,
                'name': target_proc.name,
                'app_id': target_app.app_id,
                'app_name': target_app.name,
                'size_mb': target_proc.memory_mb,
                'swap_slot': slot,
                'disk_track': 42 + (slot * 8) % 150  # Simulated cylinder on disk
            }

            target_proc.state = 'SWAPPED'
            target_proc.swap_slot = slot

            return {
                'success': True,
                'message': (
                    f"💾 Page-Out: Evicted {target_proc.name} (PID: {pid}) from Physical RAM. "
                    f"Saved {target_proc.memory_mb} MB to Swap Slot #{slot} on Secondary Storage."
                ),
                'action': 'swap_out',
                'freed_ram_mb': target_proc.memory_mb,
                'swap_item': self.swap_space[pid],
                'app': target_app.to_dict(),
                'memory_state': self.memory_manager.get_state()
            }

        elif action == 'swap_in':
            if target_proc.state != 'SWAPPED':
                return {'success': False, 'error': f'Process {pid} is already in physical RAM!'}

            # Check if there is enough physical RAM to swap back in
            free_ram = self.memory_manager.free_mb()
            if free_ram < target_proc.memory_mb:
                return {
                    'success': False,
                    'error': (
                        f"Cannot Page-In {target_proc.name}: Requires {target_proc.memory_mb} MB, "
                        f"but only {free_ram} MB of Physical RAM is free. Evict or swap another app first!"
                    ),
                    'out_of_memory': True
                }

            # Allocate frames back in MemoryManager
            alloc_res = self.memory_manager.allocate(
                pid=pid,
                name=f"[{target_app.name}] {target_proc.name}",
                size_mb=target_proc.memory_mb
            )

            if not alloc_res.get('success'):
                return alloc_res

            # Remove from swap space
            self.swap_space.pop(pid, None)
            target_proc.state = 'RUNNING'
            target_proc.swap_slot = None

            return {
                'success': True,
                'message': (
                    f"📥 Page-In: Loaded {target_proc.name} (PID: {pid}) from Swap Space back into "
                    f"Physical RAM ({target_proc.memory_mb} MB restored)!"
                ),
                'action': 'swap_in',
                'app': target_app.to_dict(),
                'memory_state': self.memory_manager.get_state()
            }

        return {'success': False, 'error': f'Unknown action "{action}"'}

    def run_oom_killer(self, force: bool = False, threshold_pct: float = 85.0) -> Dict[str, Any]:
        """
        Kernel Out-Of-Memory (OOM) Killer Daemon:
        Computes Badness Score for all running processes:
          badness = (memory_mb * 10) + (priority * 50) + (is_background ? 100 : 0) - (is_main ? 500 : 0)
        Automatically targets and terminates the highest-badness rogue/heavy process.
        """
        current_util = self.memory_manager.utilization()

        if not force and current_util < threshold_pct:
            return {
                'success': True,
                'invoked': False,
                'message': f"Memory pressure is safe ({current_util}% < {threshold_pct}%). OOM Killer standing by.",
                'current_utilization': current_util
            }

        # Gather all currently running processes across all apps
        candidates = []
        for app in self.apps.values():
            for p in app.processes:
                if p.state == 'RUNNING':
                    # Calculate badness
                    badness = (p.memory_mb * 10) + (p.priority * 50)
                    if p.is_main:
                        badness -= 500  # Avoid killing main application shell if tabs exist
                    else:
                        badness += 150  # Prefer killing worker tabs/child processes
                    candidates.append({
                        'app_id': app.app_id,
                        'app_name': app.name,
                        'pid': p.pid,
                        'name': p.name,
                        'memory_mb': p.memory_mb,
                        'priority': p.priority,
                        'is_main': p.is_main,
                        'badness_score': badness
                    })

        if not candidates:
            return {
                'success': False,
                'invoked': True,
                'message': 'OOM Killer found no killable processes in physical RAM.',
                'current_utilization': current_util
            }

        # Pick candidate with highest badness score
        candidates.sort(key=lambda c: c['badness_score'], reverse=True)
        victim = candidates[0]

        # Terminate victim process
        kill_res = self.kill_process(victim['app_id'], victim['pid'])

        oom_event = {
            'victim_pid': victim['pid'],
            'victim_name': victim['name'],
            'app_name': victim['app_name'],
            'memory_reclaimed_mb': victim['memory_mb'],
            'badness_score': victim['badness_score'],
            'pre_utilization_pct': current_util,
            'post_utilization_pct': self.memory_manager.utilization(),
            'explanation': (
                f"🚨 KERNEL OOM KILLER INVOKED: Memory pressure reached {current_util}%. "
                f"Targeted victim '{victim['name']}' (PID: {victim['pid']}, {victim['memory_mb']} MB, Badness: {victim['badness_score']}). "
                f"Physical RAM frames reclaimed. New utilization: {self.memory_manager.utilization()}%."
            )
        }
        self.oom_logs.insert(0, oom_event)

        return {
            'success': True,
            'invoked': True,
            'victim': victim,
            'oom_event': oom_event,
            'kill_result': kill_res,
            'memory_state': self.memory_manager.get_state()
        }

    def stress_test_memory(self) -> Dict[str, Any]:
        """
        Stress Test: Launches Browser, Code Editor, and Game Engine with heavy tabs
        to push RAM to ~85-95% capacity for testing OOM and Swapping.
        """
        # Launch browser and game engine to generate heavy realistic load
        self.launch_app('browser')
        self.launch_app('code_editor')
        self.launch_app('game_engine')
        self.spawn_tab('browser', tab_name='Tab: Unoptimized 8K Video Canvas', memory_mb=1024)

        return {
            'success': True,
            'message': '⚡ Memory Stress Test Applied: Launched multi-process apps to simulate high RAM pressure.',
            'state': self.get_state()
        }

    def get_state(self) -> Dict[str, Any]:
        mem_state = self.memory_manager.get_state()
        used_swap_mb = sum(item['size_mb'] for item in self.swap_space.values())
        util = mem_state['utilization']

        if util >= 85.0:
            pressure_level = 'CRITICAL'
            pressure_color = '#ef4444'
        elif util >= 65.0:
            pressure_level = 'ELEVATED'
            pressure_color = '#f59e0b'
        else:
            pressure_level = 'NORMAL'
            pressure_color = '#10b981'

        return {
            'apps': [app.to_dict() for app in self.apps.values()],
            'running_apps_count': sum(1 for a in self.apps.values() if a.status in ('RUNNING', 'PARTIALLY_SWAPPED')),
            'total_processes_count': sum(len([p for p in a.processes if p.state != 'TERMINATED']) for a in self.apps.values()),
            'ram': {
                'total_mb': mem_state['total_mb'],
                'used_mb': mem_state['used_mb'],
                'free_mb': mem_state['free_mb'],
                'utilization_pct': util,
                'pressure_level': pressure_level,
                'pressure_color': pressure_color,
                'frames': mem_state['paging']['frames']
            },
            'swap': {
                'total_mb': self.max_swap_mb,
                'used_mb': used_swap_mb,
                'free_mb': self.max_swap_mb - used_swap_mb,
                'utilization_pct': round((used_swap_mb / self.max_swap_mb) * 100, 1) if self.max_swap_mb else 0,
                'items': list(self.swap_space.values())
            },
            'oom_logs': self.oom_logs[:10]
        }

    def reset_all(self):
        """Terminates all apps and clears swap."""
        for app in self.apps.values():
            for p in list(app.processes):
                if p.state == 'RUNNING':
                    self.memory_manager.release(p.pid)
                self.process_manager.delete_process(p.pid)
            app.processes.clear()
            app.status = 'STOPPED'
        self.swap_space.clear()
        self.oom_logs.clear()

    def get_representative_processes(self) -> List[Dict[str, Any]]:
        """
        Returns one realistic process from each of the 4 real applications:
        - Browser: WebGL Canvas (burst 8, prio 3, 1024 MB)
        - SysCode: PyRight LSP Language Server (burst 7, prio 2, 768 MB)
        - PulseStream: Real-time Audio DSP Engine (burst 4, prio 1, 512 MB)
        - NeoRender: Vulkan Shader Pipeline (burst 9, prio 2, 1536 MB)
        """
        return copy.deepcopy(REPRESENTATIVE_APP_PROCESSES)

    def simulate_representative_processes(self, algorithm: str = 'ALL', quantum: int = 2) -> Dict[str, Any]:
        """
        Simulates the 4 representative app processes across CPU scheduling algorithms:
        Supports individual algorithm simulation (FCFS, SJF, Priority, RoundRobin)
        or 'ALL' for side-by-side comparative benchmarking.
        """
        procs = self.get_representative_processes()
        proc_dicts = [{
            'pid': p['pid'],
            'name': p['name'],
            'arrival_time': p['arrival_time'],
            'burst_time': p['burst_time'],
            'priority': p['priority'],
            'memory_mb': p['memory_mb']
        } for p in procs]

        color_map = {p['pid']: p['color'] for p in procs}

        def apply_colors(result):
            if 'gantt_chart' in result:
                for g in result['gantt_chart']:
                    if g.get('process') in color_map:
                        g['color'] = color_map[g['process']]
            if 'events' in result:
                for ev in result['events']:
                    if ev.get('gantt') and ev['gantt'].get('process') in color_map:
                        ev['gantt']['color'] = color_map[ev['gantt']['process']]
            return result

        algo_upper = str(algorithm).upper()
        if algo_upper in ('FCFS', 'SJF', 'PRIORITY', 'ROUNDROBIN'):
            if algo_upper == 'FCFS':
                res = scheduler.fcfs(proc_dicts)
            elif algo_upper == 'SJF':
                res = scheduler.sjf(proc_dicts)
            elif algo_upper == 'PRIORITY':
                res = scheduler.priority_scheduling(proc_dicts)
            elif algo_upper == 'ROUNDROBIN':
                res = scheduler.round_robin(proc_dicts, quantum=quantum)
            apply_colors(res)
            return {
                'success': True,
                'mode': 'single',
                'algorithm': algo_upper,
                'result': res,
                'processes': procs
            }

        # Run ALL 4 algorithms
        all_results = {}
        all_results['FCFS'] = apply_colors(scheduler.fcfs(proc_dicts))
        all_results['SJF'] = apply_colors(scheduler.sjf(proc_dicts))
        all_results['Priority'] = apply_colors(scheduler.priority_scheduling(proc_dicts))
        all_results['RoundRobin'] = apply_colors(scheduler.round_robin(proc_dicts, quantum=quantum))

        # Identify best metrics
        best_awt_algo = min(all_results.keys(), key=lambda k: all_results[k]['metrics']['avg_waiting_time'])
        best_tat_algo = min(all_results.keys(), key=lambda k: all_results[k]['metrics']['avg_turnaround_time'])
        best_art_algo = min(all_results.keys(), key=lambda k: all_results[k]['metrics'].get('avg_response_time', 999))

        analysis = {
            'summary': 'Simulated 1 representative process from each of the 4 applications across all 4 CPU scheduling algorithms.',
            'best_waiting_time': {
                'algorithm': best_awt_algo,
                'value': all_results[best_awt_algo]['metrics']['avg_waiting_time'],
                'explanation': 'SJF minimizes average waiting time by prioritizing the shorter PulseStream Audio DSP (4ms) before heavier IDE and 3D tasks.'
            },
            'best_response_time': {
                'algorithm': best_art_algo,
                'value': all_results[best_art_algo]['metrics'].get('avg_response_time', 0),
                'explanation': 'Round Robin gives the lowest initial response time (2.0ms) because time-slicing activates every app process almost immediately.'
            },
            'priority_observation': {
                'algorithm': 'Priority',
                'explanation': 'Priority scheduling ensures PulseStream Audio DSP (Priority 1) executes ahead of compiler & rendering tasks, preventing audio glitching and buffer underrun.'
            },
            'fcfs_convoy_effect': {
                'algorithm': 'FCFS',
                'explanation': 'FCFS suffers from the Convoy Effect: the 8ms WebGL canvas holds the CPU while the lightweight Audio DSP waits in line.'
            }
        }

        return {
            'success': True,
            'mode': 'all',
            'results': all_results,
            'processes': procs,
            'analysis': analysis
        }

    def load_representative_to_engine(self, engine) -> Dict[str, Any]:
        """Loads these 4 app processes into the engine's ProcessManager and MemoryManager."""
        engine.reset()
        procs = self.get_representative_processes()
        for p in procs:
            engine.process_manager.create_process(
                name=p['name'],
                arrival_time=p['arrival_time'],
                burst_time=p['burst_time'],
                priority=p['priority'],
                memory_mb=p['memory_mb'],
                pid=p['pid'],
                session_id=engine.current_session_id
            )
            engine.memory_manager.allocate(
                pid=p['pid'],
                name=p['name'],
                size_mb=p['memory_mb']
            )
        return {
            'success': True,
            'message': 'Loaded 4 representative app processes into CPU Scheduler and Memory Manager.',
            'processes': engine.process_manager.get_all(),
            'memory': engine.memory_manager.get_state()
        }


# Representative processes: Exactly one key process from each application
REPRESENTATIVE_APP_PROCESSES = [
    {
        'pid': 'APP_BROWSER',
        'app_id': 'browser',
        'app_name': 'Quantum Web Browser',
        'name': '🌐 [Browser] 3D WebGL Canvas',
        'short_name': 'Browser (WebGL)',
        'arrival_time': 0,
        'burst_time': 8,
        'priority': 3,
        'memory_mb': 1024,
        'icon': '🌐',
        'color': '#38bdf8',
        'role': 'Hardware-accelerated web content tab',
        'workload_type': 'Compute & GPU Bound'
    },
    {
        'pid': 'APP_SYSCODE',
        'app_id': 'code_editor',
        'app_name': 'SysCode Studio IDE',
        'name': '💻 [SysCode] PyRight LSP Server',
        'short_name': 'SysCode (LSP)',
        'arrival_time': 1,
        'burst_time': 7,
        'priority': 2,
        'memory_mb': 768,
        'icon': '💻',
        'color': '#a855f7',
        'role': 'Static syntax & type analysis worker',
        'workload_type': 'CPU Burst Worker'
    },
    {
        'pid': 'APP_PULSE',
        'app_id': 'media_player',
        'app_name': 'PulseStream Hi-Fi',
        'name': '🎵 [PulseStream] Audio DSP Engine',
        'short_name': 'PulseStream (Audio DSP)',
        'arrival_time': 2,
        'burst_time': 4,
        'priority': 1,  # 1 = Highest priority
        'memory_mb': 512,
        'icon': '🎵',
        'color': '#22c55e',
        'role': 'Low-latency real-time sound processor',
        'workload_type': 'Real-time Audio Filter (Latency-Sensitive)'
    },
    {
        'pid': 'APP_NEO3D',
        'app_id': 'game_engine',
        'app_name': 'NeoRender 3D Simulation',
        'name': '🎮 [NeoRender] Vulkan Shader Pipeline',
        'short_name': 'NeoRender (Vulkan)',
        'arrival_time': 3,
        'burst_time': 9,
        'priority': 2,
        'memory_mb': 1536,
        'icon': '🎮',
        'color': '#f59e0b',
        'role': 'Vulkan shader compiler & rasterizer',
        'workload_type': 'Heavy Graphics Compute'
    }
]

