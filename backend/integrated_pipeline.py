"""
SysRealm Integrated OS Pipeline: Process (CPU) + Memory (Paging / Page Faults) + Storage (Disk I/O)
Simulates full multiprogramming with CPU-I/O overlap:
1. CPU Scheduler executes process burst.
2. Process references virtual memory pages.
   - Hit: Page in RAM frame -> instant execution.
   - Fault: Page not in RAM -> MMU Page Fault trap.
3. On Page Fault, process is BLOCKED (RUNNING -> WAITING).
4. OS issues a Disk I/O Request for the backing store cylinder.
5. Disk Scheduler (SSTF/SCAN/FCFS/LOOK/C-SCAN) queues and seeks disk head to cylinder.
6. CPU switches to another READY process while disk I/O is in flight (CPU-I/O Overlap!).
7. Once disk read completes:
   - Page Replacement Algorithm (LRU / FIFO / Optimal) selects victim frame if RAM full.
   - Page is loaded into physical RAM frame.
   - I/O Complete interrupt: process transitions from WAITING -> READY queue.
8. CPU resumes process to finish remaining burst.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any, Tuple
import copy
import math

PROCESS_COLORS = [
    '#e74c3c', '#3498db', '#2ecc71', '#f39c12',
    '#9b59b6', '#1abc9c', '#e67e22', '#e91e63',
    '#00bcd4', '#8bc34a'
]


@dataclass
class PageReference:
    at_burst_time: int     # at which CPU burst time this memory page is accessed
    page_no: int           # virtual page number
    cylinder: int          # backing store disk cylinder (0..199)


@dataclass
class IntegratedProcess:
    pid: str
    name: str
    arrival_time: int
    burst_time: int
    priority: int = 1
    memory_mb: int = 512
    page_references: List[Dict[str, int]] = field(default_factory=list)
    # Execution state
    remaining_burst: int = 0
    executed_burst: int = 0
    state: str = 'NEW'      # NEW, READY, RUNNING, WAITING, TERMINATED
    start_time: Optional[int] = None
    completion_time: Optional[int] = None
    waiting_time: int = 0
    io_wait_time: int = 0
    turnaround_time: int = 0
    page_faults_count: int = 0
    page_hits_count: int = 0
    # Waiting on disk tracking
    blocked_on_page: Optional[int] = None
    blocked_on_cylinder: Optional[int] = None
    io_start_time: Optional[int] = None

    def __post_init__(self):
        if self.remaining_burst == 0:
            self.remaining_burst = self.burst_time

    def to_dict(self):
        return asdict(self)


class IntegratedPipeline:
    def __init__(self,
                 cpu_algo: str = 'RoundRobin',
                 disk_algo: str = 'SSTF',
                 page_algo: str = 'LRU',
                 quantum: int = 2,
                 num_frames: int = 4,
                 initial_head: int = 50,
                 total_cylinders: int = 200,
                 demand_paging: bool = True):
        self.cpu_algo = cpu_algo
        self.disk_algo = disk_algo
        self.page_algo = page_algo
        self.quantum = max(1, quantum)
        self.num_frames = max(2, num_frames)
        self.initial_head = initial_head
        self.total_cylinders = total_cylinders
        self.demand_paging = demand_paging

    @staticmethod
    def get_default_demo_processes() -> List[Dict[str, Any]]:
        """
        Textbook multiprogramming workload where processes have varying memory profiles
        and issue realistic page references/disk I/O requests.
        """
        return [
            {
                'pid': 'P1',
                'name': 'Browser (Render Engine)',
                'arrival_time': 0,
                'burst_time': 5,
                'priority': 2,
                'memory_mb': 1024,
                'page_references': [
                    {'at_burst_time': 0, 'page_no': 0, 'cylinder': 25},
                    {'at_burst_time': 2, 'page_no': 2, 'cylinder': 98},  # Page Fault -> Cylinder 98
                    {'at_burst_time': 4, 'page_no': 0, 'cylinder': 25},  # Page Hit
                ]
            },
            {
                'pid': 'P2',
                'name': 'Music Player (Audio Buffer)',
                'arrival_time': 1,
                'burst_time': 4,
                'priority': 1,
                'memory_mb': 512,
                'page_references': [
                    {'at_burst_time': 0, 'page_no': 0, 'cylinder': 37},
                    {'at_burst_time': 1, 'page_no': 1, 'cylinder': 14},  # Page Fault -> Cylinder 14
                    {'at_burst_time': 3, 'page_no': 1, 'cylinder': 14},  # Page Hit
                ]
            },
            {
                'pid': 'P3',
                'name': 'Game Engine (Shader Cache)',
                'arrival_time': 2,
                'burst_time': 6,
                'priority': 3,
                'memory_mb': 2048,
                'page_references': [
                    {'at_burst_time': 0, 'page_no': 0, 'cylinder': 65},
                    {'at_burst_time': 2, 'page_no': 3, 'cylinder': 183}, # Page Fault -> Cylinder 183
                    {'at_burst_time': 4, 'page_no': 4, 'cylinder': 122}, # Page Fault -> Cylinder 122
                ]
            },
            {
                'pid': 'P4',
                'name': 'DBMS Query Daemon',
                'arrival_time': 3,
                'burst_time': 5,
                'priority': 2,
                'memory_mb': 768,
                'page_references': [
                    {'at_burst_time': 0, 'page_no': 0, 'cylinder': 50},
                    {'at_burst_time': 2, 'page_no': 2, 'cylinder': 67},  # Page Fault -> Cylinder 67
                    {'at_burst_time': 4, 'page_no': 0, 'cylinder': 50},  # Page Hit
                ]
            }
        ]

    def simulate(self, processes_raw: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Executes the integrated simulation tick-by-tick.
        Returns full event trace, Gantt segments, memory snapshots, disk seek trace, and metrics.
        """
        processes: List[IntegratedProcess] = []
        for p in processes_raw:
            p_copy = copy.deepcopy(p)
            refs = p_copy.pop('page_references', [])
            proc = IntegratedProcess(**p_copy, page_references=refs)
            processes.append(proc)

        # Sort initial by arrival
        processes.sort(key=lambda p: (p.arrival_time, p.pid))
        color_map = {p.pid: PROCESS_COLORS[i % len(PROCESS_COLORS)] for i, p in enumerate(processes)}
        proc_map = {p.pid: p for p in processes}

        # Memory Frame Table: list of entries: { 'frame_no': i, 'pid': ..., 'page_no': ..., 'loaded_time': ..., 'last_used': ... }
        frames: List[Optional[Dict[str, Any]]] = [None] * self.num_frames
        page_hits_total = 0
        page_faults_total = 0

        # Optionally preload Code Page 0 for first 2 processes if not pure cold demand paging
        if not self.demand_paging:
            for i, p in enumerate(processes[:min(2, self.num_frames)]):
                frames[i] = {
                    'frame_no': i,
                    'pid': p.pid,
                    'page_no': 0,
                    'loaded_time': 0,
                    'last_used': 0
                }

        # Disk Subsystem State
        disk_head = self.initial_head
        disk_direction = 'right'  # for SCAN/C-SCAN
        # Pending disk requests: list of dicts { 'pid': ..., 'page_no': ..., 'cylinder': ..., 'request_time': ..., 'seek_remaining': ... }
        disk_queue: List[Dict[str, Any]] = []
        active_disk_op: Optional[Dict[str, Any]] = None
        disk_seek_history: List[Dict[str, Any]] = [{'time': 0, 'head': disk_head, 'event': 'INIT'}]
        total_seek_distance = 0

        # CPU Subsystem State
        current_time = 0
        ready_queue: List[IntegratedProcess] = []
        blocked_queue: List[IntegratedProcess] = []  # WAITING for I/O
        running_proc: Optional[IntegratedProcess] = None
        current_quantum_left = self.quantum

        events: List[Dict[str, Any]] = []
        gantt_segments: List[Dict[str, Any]] = []
        cpu_track_segments: List[Dict[str, Any]] = []
        disk_track_segments: List[Dict[str, Any]] = []

        def sort_ready_queue():
            nonlocal ready_queue
            if self.cpu_algo == 'Priority':
                ready_queue.sort(key=lambda p: (p.priority, p.arrival_time, p.pid))
            elif self.cpu_algo == 'SJF':
                ready_queue.sort(key=lambda p: (p.remaining_burst, p.arrival_time, p.pid))
            # FCFS & RoundRobin maintain arrival/FIFO order

        def pick_next_disk_target() -> Optional[Dict[str, Any]]:
            """Selects the next disk request based on the chosen disk scheduling algorithm."""
            nonlocal disk_direction
            if not disk_queue:
                return None
            if self.disk_algo == 'FCFS':
                return disk_queue[0]
            elif self.disk_algo == 'SSTF':
                return min(disk_queue, key=lambda req: (abs(req['cylinder'] - disk_head), req['request_time']))
            elif self.disk_algo in ('SCAN', 'LOOK'):
                if disk_direction == 'right':
                    ahead = [req for req in disk_queue if req['cylinder'] >= disk_head]
                    if ahead:
                        return min(ahead, key=lambda req: req['cylinder'])
                    else:
                        disk_direction = 'left'
                        behind = [req for req in disk_queue if req['cylinder'] < disk_head]
                        return max(behind, key=lambda req: req['cylinder']) if behind else disk_queue[0]
                else:
                    behind = [req for req in disk_queue if req['cylinder'] <= disk_head]
                    if behind:
                        return max(behind, key=lambda req: req['cylinder'])
                    else:
                        disk_direction = 'right'
                        ahead = [req for req in disk_queue if req['cylinder'] > disk_head]
                        return min(ahead, key=lambda req: req['cylinder']) if ahead else disk_queue[0]
            elif self.disk_algo in ('C_SCAN', 'C_LOOK'):
                ahead = [req for req in disk_queue if req['cylinder'] >= disk_head]
                if ahead:
                    return min(ahead, key=lambda req: req['cylinder'])
                else:
                    return min(disk_queue, key=lambda req: req['cylinder'])
            return disk_queue[0]

        def get_memory_snapshot():
            return {
                'num_frames': self.num_frames,
                'page_algo': self.page_algo,
                'page_hits': page_hits_total,
                'page_faults': page_faults_total,
                'hit_ratio': round((page_hits_total / (page_hits_total + page_faults_total) * 100), 1) if (page_hits_total + page_faults_total) > 0 else 0.0,
                'frames': [
                    {
                        'frame_no': i,
                        'pid': f['pid'] if f else None,
                        'name': proc_map[f['pid']].name if (f and f.get('pid') in proc_map) else (f['pid'] if f else None),
                        'page_no': f['page_no'] if f else None,
                        'color': color_map.get(f['pid'], None) if f else None,
                        'loaded_time': f['loaded_time'] if f else None,
                        'last_used': f['last_used'] if f else None,
                        'occupied': bool(f and f.get('pid'))
                    } for i, f in enumerate(frames)
                ]
            }

        def get_disk_snapshot():
            return {
                'head': disk_head,
                'head_position': disk_head,
                'direction': disk_direction,
                'algorithm': self.disk_algo,
                'total_seek_distance': total_seek_distance,
                'pending_cylinders': [r['cylinder'] for r in disk_queue],
                'pending_count': len(disk_queue),
                'queue': [{'cylinder': r['cylinder'], 'pid': r['pid'], 'page': r.get('page_no')} for r in disk_queue],
                'active_op': copy.deepcopy(active_disk_op) if active_disk_op else None
            }

        def get_blocked_queue_details():
            details = []
            for bp in blocked_queue:
                rem_seek = 2
                if active_disk_op and active_disk_op.get('pid') == bp.pid:
                    rem_seek = active_disk_op.get('seek_remaining', 1)
                else:
                    for req in disk_queue:
                        if req.get('pid') == bp.pid:
                            rem_seek = req.get('seek_remaining', 3)
                            break
                details.append({
                    'pid': bp.pid,
                    'name': bp.name,
                    'page': bp.blocked_on_page,
                    'cylinder': bp.blocked_on_cylinder,
                    'remaining_seek': rem_seek
                })
            return details

        def emit_event(ev: Dict[str, Any]):
            mem = get_memory_snapshot()
            dsk = get_disk_snapshot()
            bl_det = get_blocked_queue_details()
            ev.setdefault('memory_state', mem)
            ev.setdefault('mmu_state', mem)
            ev.setdefault('disk_state', dsk)
            ev.setdefault('queue', [p.pid for p in ready_queue])
            ev.setdefault('blocked_queue', [p.pid for p in blocked_queue])
            ev.setdefault('blocked_queue_details', bl_det)
            events.append(ev)

        uncompleted = list(processes)
        max_simulation_ticks = 120

        # Discrete simulation tick by tick
        while (uncompleted or ready_queue or blocked_queue or running_proc or disk_queue or active_disk_op) and current_time < max_simulation_ticks:
            
            # ── 1. Arrivals at current_time ──
            new_arrivals = [p for p in uncompleted if p.arrival_time == current_time and p.state == 'NEW']
            for np in new_arrivals:
                np.state = 'READY'
                ready_queue.append(np)
                emit_event({
                    'time': current_time,
                    'event': 'PROCESS_ARRIVED',
                    'process_id': np.pid,
                    'process_name': np.name,
                    'explanation': f"🚀 {np.name} ({np.pid}) arrives at t={current_time} and enters the Ready Queue."
                })
            if new_arrivals:
                sort_ready_queue()

            # ── 2. Progress Disk Subsystem ──
            if active_disk_op is None and disk_queue:
                target_req = pick_next_disk_target()
                if target_req:
                    disk_queue.remove(target_req)
                    active_disk_op = target_req
                    seek_dist = abs(active_disk_op['cylinder'] - disk_head)
                    # Discrete animation-friendly seek ticks: 2 to 4 ticks
                    active_disk_op['seek_duration'] = max(2, min(5, math.ceil(seek_dist / 35)))
                    active_disk_op['seek_remaining'] = active_disk_op['seek_duration']
                    active_disk_op['from_cylinder'] = disk_head
                    active_disk_op['start_time'] = current_time
                    emit_event({
                        'time': current_time,
                        'event': 'DISK_SEEK_DISPATCHED',
                        'process_id': active_disk_op['pid'],
                        'cylinder': active_disk_op['cylinder'],
                        'seek_dist': seek_dist,
                        'seek_duration': active_disk_op['seek_duration'],
                        'explanation': (
                            f"💽 Disk Scheduler ({self.disk_algo}) selected Cylinder {active_disk_op['cylinder']} "
                            f"for {active_disk_op['pid']}. Seek distance: {seek_dist} tracks (ETA: {active_disk_op['seek_duration']} ticks)."
                        )
                    })

            if active_disk_op:
                active_disk_op['seek_remaining'] -= 1

                if active_disk_op['seek_remaining'] <= 0:
                    completed_op = active_disk_op
                    active_disk_op = None

                    seek_amt = abs(completed_op['cylinder'] - disk_head)
                    total_seek_distance += seek_amt
                    disk_head = completed_op['cylinder']
                    disk_seek_history.append({'time': current_time + 1, 'head': disk_head, 'event': f"SERVICED_{completed_op['pid']}"})

                    # Page In: Frame allocation & replacement
                    c_pid = completed_op['pid']
                    c_page = completed_op['page_no']
                    c_proc = next((p for p in processes if p.pid == c_pid), None)

                    empty_frame_idx = next((i for i, f in enumerate(frames) if f is None), None)
                    evicted_page = None
                    evicted_pid = None

                    if empty_frame_idx is not None:
                        target_frame = empty_frame_idx
                    else:
                        if self.page_algo == 'FIFO':
                            target_frame = min(range(self.num_frames), key=lambda i: frames[i]['loaded_time'])
                        elif self.page_algo == 'OPTIMAL':
                            target_frame = min(range(self.num_frames), key=lambda i: frames[i]['loaded_time'])
                        else:  # LRU
                            target_frame = min(range(self.num_frames), key=lambda i: frames[i]['last_used'])

                        evicted_page = frames[target_frame]['page_no']
                        evicted_pid = frames[target_frame]['pid']

                    frames[target_frame] = {
                        'frame_no': target_frame,
                        'pid': c_pid,
                        'page_no': c_page,
                        'loaded_time': current_time + 1,
                        'last_used': current_time + 1
                    }

                    # Unblock Process from WAITING -> READY
                    if c_proc and c_proc in blocked_queue:
                        blocked_queue.remove(c_proc)
                        c_proc.state = 'READY'
                        c_proc.blocked_on_page = None
                        c_proc.blocked_on_cylinder = None
                        ready_queue.append(c_proc)
                        sort_ready_queue()

                        eviction_str = f" [Evicted {evicted_pid}'s Page {evicted_page} via {self.page_algo}]" if evicted_page is not None else ""
                        emit_event({
                            'time': current_time + 1,
                            'event': 'PAGE_IN_COMPLETED',
                            'process_id': c_pid,
                            'process_name': c_proc.name,
                            'cylinder': completed_op['cylinder'],
                            'frame_no': target_frame,
                            'page_no': c_page,
                            'explanation': (
                                f"✅ Disk I/O Complete at Cylinder {completed_op['cylinder']}! "
                                f"Page {c_page} loaded into Frame {target_frame}{eviction_str}. "
                                f"Process {c_proc.name} ({c_pid}) UNBLOCKED → moved back to Ready Queue!"
                            )
                        })

            # ── 3. Schedule / Dispatch CPU ──
            if running_proc is None:
                if ready_queue:
                    running_proc = ready_queue.pop(0)
                    running_proc.state = 'RUNNING'
                    if running_proc.start_time is None:
                        running_proc.start_time = current_time
                    current_quantum_left = self.quantum
                    emit_event({
                        'time': current_time,
                        'event': 'PROCESS_DISPATCHED',
                        'process_id': running_proc.pid,
                        'process_name': running_proc.name,
                        'remaining': running_proc.remaining_burst,
                        'explanation': f"⚡ CPU Scheduler ({self.cpu_algo}) dispatches {running_proc.name} ({running_proc.pid}) to run on CPU."
                    })

            # ── 4. Execute 1 CPU Tick ──
            if running_proc:
                cur_burst_point = running_proc.executed_burst
                matching_ref = next((r for r in running_proc.page_references if r['at_burst_time'] == cur_burst_point), None)

                page_fault_occurred = False
                if matching_ref:
                    req_page = matching_ref['page_no']
                    req_cyl = matching_ref['cylinder']

                    # Check MMU Frame Hit
                    frame_hit_idx = next((i for i, f in enumerate(frames) if f and f['pid'] == running_proc.pid and f['page_no'] == req_page), None)

                    if frame_hit_idx is not None:
                        page_hits_total += 1
                        running_proc.page_hits_count += 1
                        frames[frame_hit_idx]['last_used'] = current_time + 1
                        emit_event({
                            'time': current_time,
                            'event': 'PAGE_HIT',
                            'process_id': running_proc.pid,
                            'process_name': running_proc.name,
                            'page_no': req_page,
                            'frame_no': frame_hit_idx,
                            'explanation': (
                                f"🟢 MMU PAGE HIT: {running_proc.name} referenced Page {req_page}, "
                                f"already in RAM Frame {frame_hit_idx}. Zero-latency access!"
                            )
                        })
                    else:
                        # Page Fault Trap!
                        page_faults_total += 1
                        running_proc.page_faults_count += 1
                        page_fault_occurred = True

                        running_proc.state = 'WAITING'
                        running_proc.blocked_on_page = req_page
                        running_proc.blocked_on_cylinder = req_cyl
                        running_proc.io_start_time = current_time
                        blocked_queue.append(running_proc)

                        disk_req = {
                            'pid': running_proc.pid,
                            'page_no': req_page,
                            'cylinder': req_cyl,
                            'request_time': current_time
                        }
                        disk_queue.append(disk_req)

                        emit_event({
                            'time': current_time,
                            'event': 'PAGE_FAULT_TRAP',
                            'process_id': running_proc.pid,
                            'process_name': running_proc.name,
                            'page_no': req_page,
                            'cylinder': req_cyl,
                            'explanation': (
                                f"🔴 MMU PAGE FAULT TRAP: {running_proc.name} referenced Page {req_page} (not in RAM)! "
                                f"Process BLOCKED → WAITING. Disk request sent for Cylinder {req_cyl}. CPU yields!"
                            )
                        })
                        running_proc = None

                if not page_fault_occurred and running_proc:
                    running_proc.executed_burst += 1
                    running_proc.remaining_burst -= 1
                    current_quantum_left -= 1

                    cpu_seg = {
                        'type': 'cpu',
                        'track': 'cpu',
                        'process': running_proc.pid,
                        'name': running_proc.name,
                        'start': current_time,
                        'end': current_time + 1,
                        'color': color_map.get(running_proc.pid, '#3498db')
                    }
                    cpu_track_segments.append(cpu_seg)

                    if running_proc.remaining_burst <= 0:
                        running_proc.state = 'TERMINATED'
                        running_proc.completion_time = current_time + 1
                        running_proc.turnaround_time = running_proc.completion_time - running_proc.arrival_time
                        running_proc.waiting_time = max(0, running_proc.turnaround_time - running_proc.burst_time)
                        if running_proc in uncompleted:
                            uncompleted.remove(running_proc)

                        emit_event({
                            'time': current_time + 1,
                            'event': 'PROCESS_COMPLETED',
                            'process_id': running_proc.pid,
                            'process_name': running_proc.name,
                            'turnaround_time': running_proc.turnaround_time,
                            'waiting_time': running_proc.waiting_time,
                            'page_faults': running_proc.page_faults_count,
                            'page_hits': running_proc.page_hits_count,
                            'explanation': (
                                f"🏁 {running_proc.name} completed all execution! "
                                f"TAT={running_proc.turnaround_time}ms, WT={running_proc.waiting_time}ms, Faults={running_proc.page_faults_count}."
                            )
                        })
                        running_proc = None
                    elif self.cpu_algo == 'RoundRobin' and current_quantum_left <= 0:
                        running_proc.state = 'READY'
                        ready_queue.append(running_proc)
                        emit_event({
                            'time': current_time + 1,
                            'event': 'QUANTUM_EXPIRED',
                            'process_id': running_proc.pid,
                            'process_name': running_proc.name,
                            'remaining': running_proc.remaining_burst,
                            'explanation': f"⏱️ Time Quantum ({self.quantum}ms) expired for {running_proc.name}. Switched back to Ready Queue."
                        })
                        running_proc = None
            else:
                idle_seg = {
                    'type': 'idle',
                    'track': 'cpu',
                    'process': 'IDLE',
                    'name': 'CPU Idle',
                    'start': current_time,
                    'end': current_time + 1,
                    'color': '#334155'
                }
                cpu_track_segments.append(idle_seg)
                if blocked_queue:
                    emit_event({
                        'time': current_time,
                        'event': 'CPU_IDLE_WAITING_IO',
                        'process_id': None,
                        'explanation': f"💤 CPU is IDLE: all remaining processes {[p.pid for p in blocked_queue]} are currently waiting for Disk I/O."
                    })

            # Record disk I/O track segments for every blocked process during this tick
            for bp in blocked_queue:
                bp.io_wait_time += 1
                io_seg = {
                    'type': 'io_wait',
                    'track': 'io',
                    'process': bp.pid,
                    'name': bp.name,
                    'start': current_time,
                    'end': current_time + 1,
                    'color': '#f59e0b'
                }
                disk_track_segments.append(io_seg)

            for rp in ready_queue:
                rp.waiting_time += 1

            current_time += 1

        # Consolidate adjacent CPU track segments
        merged_cpu: List[Dict[str, Any]] = []
        for seg in cpu_track_segments:
            if merged_cpu and merged_cpu[-1]['process'] == seg['process'] and merged_cpu[-1]['type'] == seg['type'] and merged_cpu[-1]['end'] == seg['start']:
                merged_cpu[-1]['end'] = seg['end']
            else:
                merged_cpu.append(dict(seg))

        # Consolidate adjacent Disk I/O track segments
        merged_io: List[Dict[str, Any]] = []
        sorted_io = sorted(disk_track_segments, key=lambda s: (s['process'], s['start']))
        for seg in sorted_io:
            if merged_io and merged_io[-1]['process'] == seg['process'] and merged_io[-1]['end'] == seg['start']:
                merged_io[-1]['end'] = seg['end']
            else:
                merged_io.append(dict(seg))

        merged_gantt = sorted(merged_cpu + merged_io, key=lambda s: (s['start'], 0 if s.get('track') == 'cpu' else 1))

        total_time = max(1, current_time)
        completed_procs = [p for p in processes if p.state == 'TERMINATED']
        n_comp = len(completed_procs)

        avg_wt = sum(p.waiting_time for p in completed_procs) / n_comp if n_comp else 0.0
        avg_tat = sum(p.turnaround_time for p in completed_procs) / n_comp if n_comp else 0.0
        total_cpu_busy = sum(p.burst_time for p in completed_procs)
        cpu_util = round((total_cpu_busy / total_time) * 100, 2) if total_time else 0.0

        # Overlap analysis: ticks where both CPU was active AND disk was active
        cpu_ticks = {s['start'] for s in cpu_track_segments}
        disk_ticks = {s['start'] for s in disk_track_segments}
        overlap_ticks = cpu_ticks.intersection(disk_ticks)
        overlap_pct = round((len(overlap_ticks) / total_time) * 100, 2) if total_time else 0.0

        metrics = {
            'total_time': total_time,
            'completed_count': n_comp,
            'cpu_utilization': cpu_util,
            'avg_waiting_time': round(avg_wt, 2),
            'avg_turnaround_time': round(avg_tat, 2),
            'total_page_hits': page_hits_total,
            'total_page_faults': page_faults_total,
            'hit_ratio': round((page_hits_total / (page_hits_total + page_faults_total) * 100), 2) if (page_hits_total + page_faults_total) else 0.0,
            'total_seek_distance': total_seek_distance,
            'cpu_io_overlap_ticks': len(overlap_ticks),
            'cpu_io_overlap_percent': overlap_pct,
            'throughput': round(n_comp / total_time, 4) if total_time else 0.0
        }

        return {
            'success': True,
            'config': {
                'cpu_algo': self.cpu_algo,
                'disk_algo': self.disk_algo,
                'page_algo': self.page_algo,
                'quantum': self.quantum,
                'num_frames': self.num_frames,
                'initial_head': self.initial_head,
                'total_cylinders': self.total_cylinders
            },
            'events': events,
            'gantt_chart': merged_gantt,
            'cpu_track': cpu_track_segments,
            'disk_track': disk_track_segments,
            'processes': [p.to_dict() for p in processes],
            'metrics': metrics,
            'disk_seek_history': disk_seek_history,
            'final_memory': get_memory_snapshot(),
            'final_disk': get_disk_snapshot()
        }
