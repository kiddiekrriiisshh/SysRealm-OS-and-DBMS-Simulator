"""
SysRealm Isolated Workload Scheduler & Objective Evaluator
Executes CPU scheduling algorithms on teacher-published virtual app workloads
without mutating the global ProcessManager or simulation session state.
"""

import copy
from typing import List, Dict, Any, Tuple, Optional
from backend import scheduler


VALID_ALGORITHMS = {'FCFS', 'SJF', 'Priority', 'RoundRobin'}

VALID_OBJECTIVES = {
    'min_avg_waiting_time': 'avg_waiting_time',
    'min_avg_turnaround_time': 'avg_turnaround_time',
    'min_avg_response_time': 'avg_response_time'
}

OBJECTIVE_LABELS = {
    'min_avg_waiting_time': 'Minimize Average Waiting Time',
    'min_avg_turnaround_time': 'Minimize Average Turnaround Time',
    'min_avg_response_time': 'Minimize Average Response Time'
}


def canonicalize_algo_name(name: str) -> str:
    """Normalize algorithm names to canonical form."""
    if not name:
        return 'RoundRobin'
    clean = str(name).strip().replace('_', '').replace(' ', '').replace('-', '').lower()
    mapping = {
        'fcfs': 'FCFS',
        'firstcomefirstserved': 'FCFS',
        'sjf': 'SJF',
        'shortestjobfirst': 'SJF',
        'priority': 'Priority',
        'priorityscheduling': 'Priority',
        'roundrobin': 'RoundRobin',
        'rr': 'RoundRobin'
    }
    return mapping.get(clean, name)


def validate_workload(workload: Any) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Validate that workload is a valid list of 1-20 process dictionaries
    with non-negative arrival, positive burst, priority between 1 and 10,
    and unique PIDs.
    """
    if not isinstance(workload, list):
        return False, "Workload must be a JSON array of process specifications.", []
    
    if len(workload) == 0:
        return False, "Workload must contain at least 1 process.", []
    
    if len(workload) > 20:
        return False, "Workload cannot exceed 20 processes.", []

    seen_pids = set()
    cleaned = []

    for idx, item in enumerate(workload):
        if not isinstance(item, dict):
            return False, f"Process item at index {idx} must be a JSON object.", []

        pid_raw = item.get('pid')
        if pid_raw is None or str(pid_raw).strip() == '':
            pid = f"P{idx + 1}"
        else:
            pid = str(pid_raw).strip()

        if pid in seen_pids:
            return False, f"Duplicate Process ID '{pid}' detected. Every process must have a unique PID.", []
        seen_pids.add(pid)

        # Arrival Time >= 0
        try:
            arrival_time = int(item.get('arrival_time', 0))
            if arrival_time < 0:
                return False, f"Process '{pid}' has negative arrival time ({arrival_time}). Must be >= 0.", []
        except (ValueError, TypeError):
            return False, f"Process '{pid}' has invalid arrival time. Must be an integer >= 0.", []

        # Burst Time > 0
        try:
            burst_time = int(item.get('burst_time', 1))
            if burst_time <= 0:
                return False, f"Process '{pid}' has invalid burst time ({burst_time}). Must be > 0.", []
        except (ValueError, TypeError):
            return False, f"Process '{pid}' has invalid burst time. Must be a positive integer.", []

        # Priority 1..10
        try:
            priority = int(item.get('priority', 1))
            if priority < 1 or priority > 10:
                return False, f"Process '{pid}' priority ({priority}) must be between 1 and 10.", []
        except (ValueError, TypeError):
            return False, f"Process '{pid}' priority must be an integer between 1 and 10.", []

        # Memory MB > 0
        try:
            memory_mb = int(item.get('memory_mb', 512))
            if memory_mb <= 0:
                memory_mb = 512
        except (ValueError, TypeError):
            memory_mb = 512

        name = str(item.get('name') or f"Process {pid}").strip()
        app_name = str(item.get('app_name') or 'Virtual App').strip()

        cleaned.append({
            'pid': pid,
            'name': name,
            'app_name': app_name,
            'arrival_time': arrival_time,
            'burst_time': burst_time,
            'priority': priority,
            'memory_mb': memory_mb
        })

    return True, None, cleaned


def run_isolated_simulation(workload: List[Dict[str, Any]], algorithm: str, quantum: int = 2) -> Dict[str, Any]:
    """
    Run an isolated CPU scheduling simulation on an immutable copy of the workload.
    Does NOT touch the global ProcessManager, active session, or global score.
    """
    canon_algo = canonicalize_algo_name(algorithm)
    if canon_algo not in VALID_ALGORITHMS:
        raise ValueError(f"Unsupported algorithm '{algorithm}'. Must be one of {sorted(VALID_ALGORITHMS)}")

    if quantum is None or int(quantum) <= 0:
        quantum = 2
    else:
        quantum = int(quantum)

    # Deep copy input workload to ensure immutability
    isolated_processes = copy.deepcopy(workload)

    # Dispatch to pure scheduler implementation
    if canon_algo == 'FCFS':
        res = scheduler.fcfs(isolated_processes)
    elif canon_algo == 'SJF':
        res = scheduler.sjf(isolated_processes)
    elif canon_algo == 'Priority':
        res = scheduler.priority_scheduling(isolated_processes, preemptive=False)
    elif canon_algo == 'RoundRobin':
        res = scheduler.round_robin(isolated_processes, quantum=quantum)
    else:
        raise ValueError(f"Unknown algorithm: {canon_algo}")

    metrics = res.get('metrics', {})
    return {
        'success': True,
        'algorithm': canon_algo,
        'quantum': quantum if canon_algo == 'RoundRobin' else None,
        'metrics': metrics,
        'gantt_chart': res.get('gantt_chart', []),
        'processes': res.get('processes', []),
        'events': res.get('events', [])
    }


def evaluate_workload_objective(workload: List[Dict[str, Any]],
                                allowed_algorithms: List[str],
                                objective: str,
                                quantum: int = 2) -> Dict[str, Any]:
    """
    Simulate all allowed algorithms against the immutable workload,
    extract the target objective metric, find the minimum value,
    and identify best algorithms (including ties within a 0.05 numerical tolerance).
    """
    if objective not in VALID_OBJECTIVES:
        raise ValueError(f"Unknown objective '{objective}'. Must be one of {list(VALID_OBJECTIVES.keys())}")

    metric_key = VALID_OBJECTIVES[objective]
    clean_allowed = [canonicalize_algo_name(a) for a in allowed_algorithms if canonicalize_algo_name(a) in VALID_ALGORITHMS]
    if not clean_allowed:
        clean_allowed = ['FCFS', 'SJF', 'Priority', 'RoundRobin']

    results = {}
    metric_values = {}

    for algo in clean_allowed:
        sim_res = run_isolated_simulation(workload, algo, quantum=quantum)
        m = sim_res.get('metrics', {})
        val = float(m.get(metric_key, 999999.0))
        results[algo] = {
            'metrics': m,
            'objective_value': round(val, 2),
            'gantt_chart': sim_res.get('gantt_chart', []),
            'processes': sim_res.get('processes', [])
        }
        metric_values[algo] = val

    # Find the minimum metric value
    min_val = min(metric_values.values())

    # Identify winning algorithms within tolerance of 0.05 to handle mathematical ties
    tolerance = 0.05
    best_algorithms = [
        algo for algo, val in metric_values.items()
        if abs(val - min_val) <= tolerance
    ]

    for algo in results:
        results[algo]['is_best'] = (algo in best_algorithms)

    return {
        'objective': objective,
        'objective_label': OBJECTIVE_LABELS.get(objective, objective),
        'metric_key': metric_key,
        'min_value': round(min_val, 2),
        'best_algorithms': best_algorithms,
        'results': results
    }


def get_example_workload() -> List[Dict[str, Any]]:
    """Standard preset workload of 5 realistic virtual application processes."""
    return [
        {
            'pid': 'P1',
            'app_name': 'Browser',
            'name': 'Web Browser Tabs',
            'arrival_time': 0,
            'burst_time': 8,
            'priority': 3,
            'memory_mb': 1024
        },
        {
            'pid': 'P2',
            'app_name': 'Code Editor',
            'name': 'IDE Workspace & Linter',
            'arrival_time': 1,
            'burst_time': 4,
            'priority': 2,
            'memory_mb': 512
        },
        {
            'pid': 'P3',
            'app_name': 'Compiler',
            'name': 'GCC Build Pipeline',
            'arrival_time': 2,
            'burst_time': 9,
            'priority': 1,
            'memory_mb': 1536
        },
        {
            'pid': 'P4',
            'app_name': 'Database Server',
            'name': 'SQL Query Cache',
            'arrival_time': 3,
            'burst_time': 5,
            'priority': 4,
            'memory_mb': 2048
        },
        {
            'pid': 'P5',
            'app_name': 'Video Player',
            'name': 'H.264 Stream Decoder',
            'arrival_time': 4,
            'burst_time': 2,
            'priority': 5,
            'memory_mb': 768
        }
    ]
