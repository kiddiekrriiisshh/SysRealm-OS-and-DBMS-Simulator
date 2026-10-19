"""
SysRealm Process Manager
Manages simulated process lifecycle and state transitions
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
import time
import uuid


class ProcessState:
    NEW = 'NEW'
    READY = 'READY'
    RUNNING = 'RUNNING'
    WAITING = 'WAITING'
    TERMINATED = 'TERMINATED'


@dataclass
class SimProcess:
    pid: str
    name: str
    arrival_time: int
    burst_time: int
    priority: int = 2
    memory_mb: int = 512
    state: str = ProcessState.NEW
    remaining_time: int = 0
    start_time: Optional[int] = None
    completion_time: Optional[int] = None
    waiting_time: int = 0
    turnaround_time: int = 0
    response_time: Optional[int] = None
    resource_waiting_for: Optional[str] = None
    session_id: Optional[str] = None
    db_id: Optional[int] = None

    def __post_init__(self):
        if self.remaining_time == 0:
            self.remaining_time = self.burst_time

    def to_dict(self):
        return {
            'pid': self.pid,
            'name': self.name,
            'arrival_time': self.arrival_time,
            'burst_time': self.burst_time,
            'priority': self.priority,
            'memory_mb': self.memory_mb,
            'state': self.state,
            'remaining_time': self.remaining_time,
            'start_time': self.start_time,
            'completion_time': self.completion_time,
            'waiting_time': self.waiting_time,
            'turnaround_time': self.turnaround_time,
            'response_time': self.response_time,
            'resource_waiting_for': self.resource_waiting_for,
            'session_id': self.session_id,
            'db_id': self.db_id
        }


class ProcessManager:
    def __init__(self):
        self.processes: Dict[str, SimProcess] = {}
        self._pid_counter = 1

    def create_process(self, name: str, arrival_time: int, burst_time: int,
                       priority: int = 2, memory_mb: int = 512,
                       pid: Optional[str] = None, session_id: Optional[str] = None) -> SimProcess:
        if burst_time <= 0:
            raise ValueError('Burst time must be positive')
        if priority < 1:
            raise ValueError('Priority must be >= 1')
        if memory_mb <= 0:
            raise ValueError('Memory requirement must be positive')

        if pid is None:
            pid = f'P{self._pid_counter}'
            self._pid_counter += 1

        if pid in self.processes:
            raise ValueError(f'Process {pid} already exists')

        proc = SimProcess(
            pid=pid,
            name=name,
            arrival_time=arrival_time,
            burst_time=burst_time,
            priority=priority,
            memory_mb=memory_mb,
            state=ProcessState.NEW,
            remaining_time=burst_time,
            session_id=session_id
        )
        self.processes[pid] = proc
        return proc

    def transition(self, pid: str, new_state: str) -> SimProcess:
        if pid not in self.processes:
            raise ValueError(f'Process {pid} not found')
        proc = self.processes[pid]
        valid_transitions = {
            ProcessState.NEW: [ProcessState.READY],
            ProcessState.READY: [ProcessState.RUNNING, ProcessState.WAITING],
            ProcessState.RUNNING: [ProcessState.READY, ProcessState.WAITING, ProcessState.TERMINATED],
            ProcessState.WAITING: [ProcessState.READY],
            ProcessState.TERMINATED: []
        }
        if new_state not in valid_transitions.get(proc.state, []):
            raise ValueError(f'Invalid transition {proc.state} -> {new_state} for {pid}')
        proc.state = new_state
        return proc

    def get_process(self, pid: str) -> Optional[SimProcess]:
        return self.processes.get(pid)

    def get_all(self) -> List[Dict]:
        return [p.to_dict() for p in self.processes.values()]

    def delete_process(self, pid: str) -> bool:
        if pid in self.processes:
            del self.processes[pid]
            return True
        return False

    def reset(self):
        self.processes = {}
        self._pid_counter = 1

    def clear(self):
        self.reset()

    def get_by_state(self, state: str) -> List[SimProcess]:
        return [p for p in self.processes.values() if p.state == state]

    def load_demo_processes(self, session_id: Optional[str] = None):
        self.reset()
        demo = [
            {'name': 'Browser', 'arrival_time': 0, 'burst_time': 5, 'priority': 2, 'memory_mb': 1024},
            {'name': 'Music Player', 'arrival_time': 1, 'burst_time': 3, 'priority': 1, 'memory_mb': 512},
            {'name': 'Game', 'arrival_time': 2, 'burst_time': 6, 'priority': 3, 'memory_mb': 2048},
            {'name': 'Download Manager', 'arrival_time': 3, 'burst_time': 4, 'priority': 2, 'memory_mb': 768},
        ]
        created = []
        for p in demo:
            proc = self.create_process(session_id=session_id, **p)
            created.append(proc)
        return created
