"""
SysRealm CPU Scheduling Algorithms
Implements FCFS, Priority, Round Robin, and SJF
Returns structured event lists for frontend animation
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import copy


@dataclass
class Process:
    pid: str
    name: str
    arrival_time: int
    burst_time: int
    priority: int = 1
    memory_mb: int = 512
    remaining_time: int = 0
    start_time: Optional[int] = None
    completion_time: Optional[int] = None
    waiting_time: int = 0
    turnaround_time: int = 0
    response_time: Optional[int] = None

    def __post_init__(self):
        if self.remaining_time == 0:
            self.remaining_time = self.burst_time

    def to_dict(self):
        return asdict(self)


@dataclass
class GanttSegment:
    process: str
    start: int
    end: int
    color: str = '#4CAF50'

    def to_dict(self):
        return asdict(self)


@dataclass
class SchedulingEvent:
    time: int
    event: str  # PROCESS_STARTED, PROCESS_COMPLETED, PROCESS_PREEMPTED, QUANTUM_EXPIRED, IDLE
    process_id: Optional[str]
    process_name: Optional[str]
    queue: List[str]  # PIDs in ready queue
    gantt: Optional[Dict] = None
    remaining: Optional[int] = None
    explanation: str = ''
    metrics: Optional[Dict] = None

    def to_dict(self):
        d = asdict(self)
        return d


PROCESS_COLORS = [
    '#e74c3c', '#3498db', '#2ecc71', '#f39c12',
    '#9b59b6', '#1abc9c', '#e67e22', '#e91e63',
    '#00bcd4', '#8bc34a'
]


def _assign_colors(processes: List[Process]) -> Dict[str, str]:
    return {p.pid: PROCESS_COLORS[i % len(PROCESS_COLORS)] for i, p in enumerate(processes)}


def _calc_metrics(processes: List[Process]) -> Dict[str, Any]:
    completed = [p for p in processes if p.completion_time is not None]
    if not completed:
        return {}
    n = len(completed)
    avg_wt = sum(p.waiting_time for p in completed) / n
    avg_tat = sum(p.turnaround_time for p in completed) / n
    avg_rt = sum(p.response_time for p in completed if p.response_time is not None) / n
    total_burst = sum(p.burst_time for p in completed)
    total_time = max(p.completion_time for p in completed) if completed else 1
    cpu_util = round((total_burst / total_time) * 100, 2) if total_time > 0 else 0
    throughput = round(n / total_time, 4) if total_time > 0 else 0
    return {
        'avg_waiting_time': round(avg_wt, 2),
        'avg_turnaround_time': round(avg_tat, 2),
        'avg_response_time': round(avg_rt, 2),
        'cpu_utilization': cpu_util,
        'throughput': throughput,
        'completed': n
    }


def fcfs(processes: List[Dict]) -> Dict[str, Any]:
    """First Come First Served scheduling"""
    procs = [Process(**{k: v for k, v in p.items() if k in Process.__dataclass_fields__}) for p in processes]
    procs = sorted(procs, key=lambda p: (p.arrival_time, p.pid))
    colors = _assign_colors(procs)

    events = []
    gantt_chart = []
    current_time = 0
    queue = []
    remaining = list(procs)
    idx = 0

    # Initial arrivals at time 0
    while idx < len(remaining) and remaining[idx].arrival_time <= current_time:
        queue.append(remaining[idx])
        events.append(SchedulingEvent(
            time=current_time,
            event='PROCESS_ARRIVED',
            process_id=remaining[idx].pid,
            process_name=remaining[idx].name,
            queue=[p.pid for p in queue],
            explanation=f"{remaining[idx].name} (PID: {remaining[idx].pid}) arrives at time {current_time} and enters the Ready Queue."
        ))
        idx += 1

    while queue or idx < len(remaining):
        if not queue:
            # CPU idle
            next_arrival = remaining[idx].arrival_time if idx < len(remaining) else current_time + 1
            events.append(SchedulingEvent(
                time=current_time,
                event='CPU_IDLE',
                process_id=None,
                process_name=None,
                queue=[],
                explanation=f"CPU is idle at time {current_time}. Waiting for next process arrival at time {next_arrival}."
            ))
            current_time = next_arrival
            while idx < len(remaining) and remaining[idx].arrival_time <= current_time:
                queue.append(remaining[idx])
                events.append(SchedulingEvent(
                    time=current_time,
                    event='PROCESS_ARRIVED',
                    process_id=remaining[idx].pid,
                    process_name=remaining[idx].name,
                    queue=[p.pid for p in queue],
                    explanation=f"{remaining[idx].name} arrives at time {current_time} and enters the Ready Queue."
                ))
                idx += 1
            continue

        proc = queue.pop(0)
        proc.start_time = current_time
        if proc.response_time is None:
            proc.response_time = current_time - proc.arrival_time

        events.append(SchedulingEvent(
            time=current_time,
            event='PROCESS_STARTED',
            process_id=proc.pid,
            process_name=proc.name,
            queue=[p.pid for p in queue],
            gantt={'process': proc.pid, 'name': proc.name, 'start': current_time, 'end': current_time + proc.burst_time, 'color': colors[proc.pid]},
            remaining=proc.burst_time,
            explanation=f"FCFS selects {proc.name} (PID: {proc.pid}) because it arrived first in the queue. It will run for {proc.burst_time} time units."
        ))

        end_time = current_time + proc.burst_time
        gantt_chart.append(GanttSegment(process=proc.pid, start=current_time, end=end_time, color=colors[proc.pid]))

        # Check for arrivals during execution
        while current_time < end_time:
            current_time += 1
            while idx < len(remaining) and remaining[idx].arrival_time <= current_time:
                queue.append(remaining[idx])
                events.append(SchedulingEvent(
                    time=remaining[idx].arrival_time,
                    event='PROCESS_ARRIVED',
                    process_id=remaining[idx].pid,
                    process_name=remaining[idx].name,
                    queue=[p.pid for p in queue] + [proc.pid],
                    explanation=f"{remaining[idx].name} arrives at time {remaining[idx].arrival_time} and waits in the Ready Queue while {proc.name} runs."
                ))
                idx += 1

        current_time = end_time
        proc.completion_time = current_time
        proc.turnaround_time = proc.completion_time - proc.arrival_time
        proc.waiting_time = proc.turnaround_time - proc.burst_time

        events.append(SchedulingEvent(
            time=current_time,
            event='PROCESS_COMPLETED',
            process_id=proc.pid,
            process_name=proc.name,
            queue=[p.pid for p in queue],
            explanation=f"{proc.name} (PID: {proc.pid}) completes execution at time {current_time}. Turnaround time: {proc.turnaround_time}, Waiting time: {proc.waiting_time}.",
            metrics=_calc_metrics(procs)
        ))

    metrics = _calc_metrics(procs)
    return {
        'algorithm': 'FCFS',
        'events': [e.to_dict() for e in events],
        'gantt_chart': [g.to_dict() for g in gantt_chart],
        'metrics': metrics,
        'processes': [p.to_dict() for p in procs]
    }


def priority_scheduling(processes: List[Dict], preemptive: bool = False) -> Dict[str, Any]:
    """Priority Scheduling (non-preemptive by default)"""
    procs = [Process(**{k: v for k, v in p.items() if k in Process.__dataclass_fields__}) for p in processes]
    procs_map = {p.pid: p for p in procs}
    sorted_by_arrival = sorted(procs, key=lambda p: p.arrival_time)
    colors = _assign_colors(procs)

    events = []
    gantt_chart = []
    current_time = 0
    queue = []
    remaining = list(sorted_by_arrival)
    idx = 0
    completed = []

    def add_arrivals(t):
        nonlocal idx
        while idx < len(remaining) and remaining[idx].arrival_time <= t:
            queue.append(remaining[idx])
            events.append(SchedulingEvent(
                time=remaining[idx].arrival_time,
                event='PROCESS_ARRIVED',
                process_id=remaining[idx].pid,
                process_name=remaining[idx].name,
                queue=[p.pid for p in queue],
                explanation=f"{remaining[idx].name} arrives at time {remaining[idx].arrival_time} with priority {remaining[idx].priority}."
            ))
            idx += 1

    add_arrivals(0)

    while len(completed) < len(procs):
        if not queue:
            current_time += 1
            add_arrivals(current_time)
            continue

        # Select highest priority (lowest number = highest priority)
        queue.sort(key=lambda p: (p.priority, p.arrival_time))
        proc = queue.pop(0)

        higher_prio_names = ', '.join(f"{p.name}(P:{p.priority})" for p in queue[:3]) if queue else 'none'
        events.append(SchedulingEvent(
            time=current_time,
            event='PROCESS_STARTED',
            process_id=proc.pid,
            process_name=proc.name,
            queue=[p.pid for p in queue],
            gantt={'process': proc.pid, 'name': proc.name, 'start': current_time, 'end': current_time + proc.remaining_time, 'color': colors[proc.pid]},
            remaining=proc.remaining_time,
            explanation=f"Priority Scheduling selects {proc.name} (Priority={proc.priority}) — it has the highest priority among ready processes. Other waiting: [{higher_prio_names}]."
        ))

        if proc.start_time is None:
            proc.start_time = current_time
        if proc.response_time is None:
            proc.response_time = current_time - proc.arrival_time

        end_time = current_time + proc.remaining_time
        gantt_chart.append(GanttSegment(process=proc.pid, start=current_time, end=end_time, color=colors[proc.pid]))

        while current_time < end_time:
            current_time += 1
            add_arrivals(current_time)

        proc.remaining_time = 0
        proc.completion_time = current_time
        proc.turnaround_time = proc.completion_time - proc.arrival_time
        proc.waiting_time = proc.turnaround_time - proc.burst_time
        completed.append(proc)

        events.append(SchedulingEvent(
            time=current_time,
            event='PROCESS_COMPLETED',
            process_id=proc.pid,
            process_name=proc.name,
            queue=[p.pid for p in queue],
            explanation=f"{proc.name} completes at time {current_time}. TAT={proc.turnaround_time}, WT={proc.waiting_time}.",
            metrics=_calc_metrics(procs)
        ))

    metrics = _calc_metrics(procs)
    return {
        'algorithm': 'Priority',
        'events': [e.to_dict() for e in events],
        'gantt_chart': [g.to_dict() for g in gantt_chart],
        'metrics': metrics,
        'processes': [p.to_dict() for p in procs]
    }


def round_robin(processes: List[Dict], quantum: int = 2) -> Dict[str, Any]:
    """Round Robin scheduling with configurable time quantum"""
    procs = [Process(**{k: v for k, v in p.items() if k in Process.__dataclass_fields__}) for p in processes]
    sorted_by_arrival = sorted(procs, key=lambda p: (p.arrival_time, p.pid))
    colors = _assign_colors(procs)
    proc_map = {p.pid: p for p in procs}

    events = []
    gantt_chart = []
    current_time = 0
    queue = []
    remaining_procs = list(sorted_by_arrival)
    idx = 0
    completed_count = 0
    n = len(procs)

    def add_arrivals(t, exclude_pid=None):
        nonlocal idx
        added = []
        while idx < len(remaining_procs) and remaining_procs[idx].arrival_time <= t:
            if remaining_procs[idx].pid != exclude_pid:
                queue.append(remaining_procs[idx])
                events.append(SchedulingEvent(
                    time=remaining_procs[idx].arrival_time,
                    event='PROCESS_ARRIVED',
                    process_id=remaining_procs[idx].pid,
                    process_name=remaining_procs[idx].name,
                    queue=[p.pid for p in queue],
                    explanation=f"{remaining_procs[idx].name} arrives at time {remaining_procs[idx].arrival_time} and joins the Round Robin queue."
                ))
            added.append(remaining_procs[idx])
            idx += 1
        return added

    add_arrivals(0)

    while completed_count < n:
        if not queue:
            if idx < len(remaining_procs):
                current_time = remaining_procs[idx].arrival_time
                add_arrivals(current_time)
            else:
                break
            continue

        proc = queue.pop(0)
        if proc.start_time is None:
            proc.start_time = current_time
        if proc.response_time is None:
            proc.response_time = current_time - proc.arrival_time

        exec_time = min(quantum, proc.remaining_time)
        end_time = current_time + exec_time

        events.append(SchedulingEvent(
            time=current_time,
            event='PROCESS_STARTED',
            process_id=proc.pid,
            process_name=proc.name,
            queue=[p.pid for p in queue],
            gantt={'process': proc.pid, 'name': proc.name, 'start': current_time, 'end': end_time, 'color': colors[proc.pid]},
            remaining=proc.remaining_time,
            explanation=f"Round Robin selects {proc.name} (PID: {proc.pid}). Remaining burst: {proc.remaining_time}. Time quantum: {quantum}. Will run until time {end_time}."
        ))

        gantt_chart.append(GanttSegment(process=proc.pid, start=current_time, end=end_time, color=colors[proc.pid]))

        # Simulate tick by tick
        for t in range(current_time + 1, end_time + 1):
            add_arrivals(t, exclude_pid=proc.pid)

        current_time = end_time
        proc.remaining_time -= exec_time

        if proc.remaining_time == 0:
            proc.completion_time = current_time
            proc.turnaround_time = proc.completion_time - proc.arrival_time
            proc.waiting_time = proc.turnaround_time - proc.burst_time
            completed_count += 1
            events.append(SchedulingEvent(
                time=current_time,
                event='PROCESS_COMPLETED',
                process_id=proc.pid,
                process_name=proc.name,
                queue=[p.pid for p in queue],
                explanation=f"{proc.name} completes at time {current_time}. TAT={proc.turnaround_time}, WT={proc.waiting_time}.",
                metrics=_calc_metrics(procs)
            ))
        else:
            events.append(SchedulingEvent(
                time=current_time,
                event='QUANTUM_EXPIRED',
                process_id=proc.pid,
                process_name=proc.name,
                queue=[p.pid for p in queue] + [proc.pid],
                remaining=proc.remaining_time,
                explanation=f"Time quantum of {quantum} units expired for {proc.name}. It has {proc.remaining_time} units remaining. {proc.name} returns to the back of the Ready Queue."
            ))
            queue.append(proc)  # Re-add to back of queue

    metrics = _calc_metrics(procs)
    return {
        'algorithm': 'Round Robin',
        'quantum': quantum,
        'events': [e.to_dict() for e in events],
        'gantt_chart': [g.to_dict() for g in gantt_chart],
        'metrics': metrics,
        'processes': [p.to_dict() for p in procs]
    }


def sjf(processes: List[Dict]) -> Dict[str, Any]:
    """Shortest Job First (non-preemptive)"""
    procs = [Process(**{k: v for k, v in p.items() if k in Process.__dataclass_fields__}) for p in processes]
    sorted_by_arrival = sorted(procs, key=lambda p: p.arrival_time)
    colors = _assign_colors(procs)

    events = []
    gantt_chart = []
    current_time = 0
    queue = []
    remaining = list(sorted_by_arrival)
    idx = 0
    completed = []

    def add_arrivals(t):
        nonlocal idx
        while idx < len(remaining) and remaining[idx].arrival_time <= t:
            queue.append(remaining[idx])
            events.append(SchedulingEvent(
                time=remaining[idx].arrival_time,
                event='PROCESS_ARRIVED',
                process_id=remaining[idx].pid,
                process_name=remaining[idx].name,
                queue=[p.pid for p in queue],
                explanation=f"{remaining[idx].name} arrives at time {remaining[idx].arrival_time} with burst time {remaining[idx].burst_time}."
            ))
            idx += 1

    add_arrivals(0)

    while len(completed) < len(procs):
        if not queue:
            current_time += 1
            add_arrivals(current_time)
            continue

        queue.sort(key=lambda p: (p.burst_time, p.arrival_time))
        proc = queue.pop(0)

        if proc.start_time is None:
            proc.start_time = current_time
        if proc.response_time is None:
            proc.response_time = current_time - proc.arrival_time

        events.append(SchedulingEvent(
            time=current_time,
            event='PROCESS_STARTED',
            process_id=proc.pid,
            process_name=proc.name,
            queue=[p.pid for p in queue],
            gantt={'process': proc.pid, 'name': proc.name, 'start': current_time, 'end': current_time + proc.burst_time, 'color': colors[proc.pid]},
            remaining=proc.burst_time,
            explanation=f"SJF selects {proc.name} (Burst={proc.burst_time}) — it has the shortest burst time among ready processes."
        ))

        end_time = current_time + proc.burst_time
        gantt_chart.append(GanttSegment(process=proc.pid, start=current_time, end=end_time, color=colors[proc.pid]))

        while current_time < end_time:
            current_time += 1
            add_arrivals(current_time)

        proc.completion_time = current_time
        proc.turnaround_time = proc.completion_time - proc.arrival_time
        proc.waiting_time = proc.turnaround_time - proc.burst_time
        completed.append(proc)

        events.append(SchedulingEvent(
            time=current_time,
            event='PROCESS_COMPLETED',
            process_id=proc.pid,
            process_name=proc.name,
            queue=[p.pid for p in queue],
            explanation=f"{proc.name} completes at time {current_time}. TAT={proc.turnaround_time}, WT={proc.waiting_time}.",
            metrics=_calc_metrics(procs)
        ))

    metrics = _calc_metrics(procs)
    return {
        'algorithm': 'SJF',
        'events': [e.to_dict() for e in events],
        'gantt_chart': [g.to_dict() for g in gantt_chart],
        'metrics': metrics,
        'processes': [p.to_dict() for p in procs]
    }
