"""
SysRealm Disk Scheduling Algorithms Module
Implements FCFS, SSTF, SCAN, C-SCAN, LOOK, and C-LOOK.
Provides step-by-step seek trace, cumulative head movement,
and comparison metrics for OS education.
"""

from typing import List, Dict, Any, Tuple


def _calc_steps(sequence: List[int], initial_head: int, request_set: set, total_req_count: int = None) -> Tuple[List[Dict[str, Any]], int, float]:
    """Calculates step-by-step seek distance and cumulative movement."""
    steps = []
    total_seek = 0
    curr = initial_head

    for idx, next_track in enumerate(sequence[1:], start=1):
        dist = abs(next_track - curr)
        total_seek += dist
        is_request = next_track in request_set
        steps.append({
            'step': idx,
            'from_track': curr,
            'to_track': next_track,
            'distance': dist,
            'cumulative': total_seek,
            'serviced': is_request
        })
        curr = next_track

    req_count = total_req_count if total_req_count is not None else len(request_set)
    avg_seek = round(total_seek / req_count, 2) if req_count > 0 else 0.0
    return steps, total_seek, avg_seek


def fcfs(requests: List[int], head: int) -> Dict[str, Any]:
    """First-Come, First-Served Disk Scheduling."""
    req_set = set(requests)
    sequence = [head] + list(requests)
    steps, total_seek, avg_seek = _calc_steps(sequence, head, req_set, len(requests))

    return {
        'algorithm': 'FCFS',
        'name': 'First-Come, First-Served',
        'sequence': sequence,
        'steps': steps,
        'total_seek': total_seek,
        'avg_seek': avg_seek,
        'explanation': (
            f"FCFS services all {len(requests)} I/O requests strictly in arrival order. "
            f"Head moves from {head} through {requests}. Total seek distance is {total_seek} cylinders."
        )
    }


def sstf(requests: List[int], head: int) -> Dict[str, Any]:
    """Shortest Seek Time First Disk Scheduling."""
    req_set = set(requests)
    pending = list(requests)
    sequence = [head]
    curr = head

    while pending:
        # Pick request with minimum absolute distance from current head
        closest = min(pending, key=lambda x: (abs(x - curr), x))
        pending.remove(closest)
        sequence.append(closest)
        curr = closest

    steps, total_seek, avg_seek = _calc_steps(sequence, head, req_set, len(requests))

    return {
        'algorithm': 'SSTF',
        'name': 'Shortest Seek Time First',
        'sequence': sequence,
        'steps': steps,
        'total_seek': total_seek,
        'avg_seek': avg_seek,
        'explanation': (
            f"SSTF greedily chooses the request closest to the current head at each step, "
            f"reducing total head movement to {total_seek} cylinders (Note: may cause starvation for distant requests)."
        )
    }


def scan(requests: List[int], head: int, total_tracks: int = 200, direction: str = 'right') -> Dict[str, Any]:
    """
    SCAN (Elevator) Disk Scheduling.
    Moves in current direction until the cylinder boundary (0 or total_tracks-1),
    then reverses direction.
    """
    req_set = set(requests)
    max_track = total_tracks - 1
    left_reqs = sorted([r for r in requests if r < head])
    right_reqs = sorted([r for r in requests if r >= head])

    sequence = [head]

    if direction.lower() in ('right', 'high', 'up'):
        # Move towards high end
        sequence.extend(right_reqs)
        # Touch the outer boundary only if there are requests on the other side
        if left_reqs:
            if not sequence or sequence[-1] != max_track:
                sequence.append(max_track)
            # Reverse and service left requests descending
            sequence.extend(reversed(left_reqs))
    else:
        # Move towards low end
        sequence.extend(reversed(left_reqs))
        if right_reqs:
            if not sequence or sequence[-1] != 0:
                sequence.append(0)
            sequence.extend(right_reqs)

    steps, total_seek, avg_seek = _calc_steps(sequence, head, req_set, len(requests))

    dir_label = "Increasing (High)" if direction.lower() in ('right', 'high', 'up') else "Decreasing (Low)"
    return {
        'algorithm': 'SCAN',
        'name': 'SCAN (Elevator Algorithm)',
        'sequence': sequence,
        'steps': steps,
        'total_seek': total_seek,
        'avg_seek': avg_seek,
        'direction': dir_label,
        'explanation': (
            f"SCAN sweeps the disk head in the {dir_label} direction servicing requests, "
            f"reaches boundary cylinder ({max_track if 'High' in dir_label else 0}), then reverses. "
            f"Total seek distance: {total_seek} cylinders."
        )
    }


def c_scan(requests: List[int], head: int, total_tracks: int = 200, direction: str = 'right') -> Dict[str, Any]:
    """
    C-SCAN (Circular SCAN) Disk Scheduling.
    Moves in one direction to the end boundary, then jumps immediately to the
    opposite boundary (without servicing) and continues in the same direction.
    """
    req_set = set(requests)
    max_track = total_tracks - 1
    left_reqs = sorted([r for r in requests if r < head])
    right_reqs = sorted([r for r in requests if r >= head])

    sequence = [head]

    if direction.lower() in ('right', 'high', 'up'):
        sequence.extend(right_reqs)
        if left_reqs:
            if not sequence or sequence[-1] != max_track:
                sequence.append(max_track)
            sequence.append(0)  # Jump to beginning
            sequence.extend(left_reqs)
    else:
        sequence.extend(reversed(left_reqs))
        if right_reqs:
            if not sequence or sequence[-1] != 0:
                sequence.append(0)
            sequence.append(max_track)  # Jump to opposite end
            sequence.extend(reversed(right_reqs))

    steps, total_seek, avg_seek = _calc_steps(sequence, head, req_set, len(requests))

    dir_label = "Increasing (High)" if direction.lower() in ('right', 'high', 'up') else "Decreasing (Low)"
    return {
        'algorithm': 'C-SCAN',
        'name': 'Circular SCAN (C-SCAN)',
        'sequence': sequence,
        'steps': steps,
        'total_seek': total_seek,
        'avg_seek': avg_seek,
        'direction': dir_label,
        'explanation': (
            f"C-SCAN provides more uniform wait time. Sweeps {dir_label}, hits boundary, "
            f"and jumps directly to the opposite end without servicing, then resumes. "
            f"Total seek distance: {total_seek} cylinders."
        )
    }


def look(requests: List[int], head: int, direction: str = 'right') -> Dict[str, Any]:
    """
    LOOK Disk Scheduling.
    Like SCAN, but looks ahead: only goes as far as the final request in each
    direction, avoiding unnecessary traversal to the boundary tracks.
    """
    req_set = set(requests)
    left_reqs = sorted([r for r in requests if r < head])
    right_reqs = sorted([r for r in requests if r >= head])

    sequence = [head]

    if direction.lower() in ('right', 'high', 'up'):
        sequence.extend(right_reqs)
        sequence.extend(reversed(left_reqs))
    else:
        sequence.extend(reversed(left_reqs))
        sequence.extend(right_reqs)

    steps, total_seek, avg_seek = _calc_steps(sequence, head, req_set, len(requests))

    dir_label = "Increasing (High)" if direction.lower() in ('right', 'high', 'up') else "Decreasing (Low)"
    return {
        'algorithm': 'LOOK',
        'name': 'LOOK Algorithm',
        'sequence': sequence,
        'steps': steps,
        'total_seek': total_seek,
        'avg_seek': avg_seek,
        'direction': dir_label,
        'explanation': (
            f"LOOK optimizes SCAN by reversing immediately at the outermost request without "
            f"traveling all the way to cylinder boundaries. Total seek distance: {total_seek} cylinders."
        )
    }


def c_look(requests: List[int], head: int, direction: str = 'right') -> Dict[str, Any]:
    """
    C-LOOK Disk Scheduling.
    Like C-SCAN, but only goes as far as the last request in the servicing direction,
    then jumps directly to the lowest requested cylinder.
    """
    req_set = set(requests)
    left_reqs = sorted([r for r in requests if r < head])
    right_reqs = sorted([r for r in requests if r >= head])

    sequence = [head]

    if direction.lower() in ('right', 'high', 'up'):
        sequence.extend(right_reqs)
        if left_reqs:
            sequence.extend(left_reqs)
    else:
        sequence.extend(reversed(left_reqs))
        if right_reqs:
            sequence.extend(reversed(right_reqs))

    steps, total_seek, avg_seek = _calc_steps(sequence, head, req_set, len(requests))

    dir_label = "Increasing (High)" if direction.lower() in ('right', 'high', 'up') else "Decreasing (Low)"
    return {
        'algorithm': 'C-LOOK',
        'name': 'Circular LOOK (C-LOOK)',
        'sequence': sequence,
        'steps': steps,
        'total_seek': total_seek,
        'avg_seek': avg_seek,
        'direction': dir_label,
        'explanation': (
            f"C-LOOK is one of the most efficient algorithms in modern OS kernels. "
            f"Services requests in {dir_label} direction, jumps to lowest pending request without touching boundaries. "
            f"Total seek distance: {total_seek} cylinders."
        )
    }


def simulate(algo: str, requests: List[int], head: int, total_tracks: int = 200, direction: str = 'right') -> Dict[str, Any]:
    """Simulates a single disk scheduling algorithm."""
    algo_clean = (algo or 'FCFS').upper().replace('-', '_').replace(' ', '_')
    if algo_clean == 'FCFS':
        return fcfs(requests, head)
    elif algo_clean == 'SSTF':
        return sstf(requests, head)
    elif algo_clean == 'SCAN':
        return scan(requests, head, total_tracks, direction)
    elif algo_clean == 'C_SCAN':
        return c_scan(requests, head, total_tracks, direction)
    elif algo_clean == 'LOOK':
        return look(requests, head, direction)
    elif algo_clean == 'C_LOOK':
        return c_look(requests, head, direction)
    else:
        raise ValueError(f"Unknown disk algorithm: {algo}")


def compare_all(requests: List[int], head: int, total_tracks: int = 200, direction: str = 'right') -> Dict[str, Any]:
    """Runs all 6 disk scheduling algorithms and returns comparative metrics."""
    algos = [
        ('FCFS', fcfs(requests, head)),
        ('SSTF', sstf(requests, head)),
        ('SCAN', scan(requests, head, total_tracks, direction)),
        ('C-SCAN', c_scan(requests, head, total_tracks, direction)),
        ('LOOK', look(requests, head, direction)),
        ('C-LOOK', c_look(requests, head, direction)),
    ]

    results = {}
    chart_data = []
    best_algo = None
    min_seek = float('inf')

    for code, res in algos:
        results[code] = res
        chart_data.append({
            'algorithm': code,
            'name': res['name'],
            'total_seek': res['total_seek'],
            'avg_seek': res['avg_seek'],
            'sequence_len': len(res['sequence'])
        })
        if res['total_seek'] < min_seek:
            min_seek = res['total_seek']
            best_algo = code

    return {
        'comparison': chart_data,
        'best_algorithm': best_algo,
        'min_seek_cylinders': min_seek,
        'details': results
    }
