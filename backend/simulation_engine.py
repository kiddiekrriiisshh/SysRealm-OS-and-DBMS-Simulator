"""
SysRealm Simulation Engine
Orchestrates all managers and maintains simulation state
"""

from typing import Dict, List, Optional, Any
from .process_manager import ProcessManager, ProcessState
from .memory_manager import MemoryManager
from .resource_manager import ResourceManager
from .deadlock_detector import DeadlockDetector, DeadlockScenario
from .integrated_pipeline import IntegratedPipeline
from .app_manager import AppManager
from . import scheduler as sched
import time


class SimulationEngine:
    def __init__(self):
        self.process_manager = ProcessManager()
        self.memory_manager = MemoryManager(total_mb=16384)  # 16 GB
        self.resource_manager = ResourceManager()
        self.deadlock_detector = DeadlockDetector()
        self.integrated_pipeline = IntegratedPipeline()
        self.app_manager = AppManager(self.process_manager, self.memory_manager)
        self.current_session_id: Optional[str] = None
        self.current_algorithm: str = 'FCFS'
        self.time_quantum: int = 2
        self.simulation_events: List[Dict] = []
        self.gantt_chart: List[Dict] = []
        self.metrics: Dict = {}
        self.simulation_running: bool = False
        self.current_event_index: int = 0
        self.score: int = 0
        self.simulation_time: int = 0
        self.storage_total_gb: int = 100
        self.storage_used_gb: int = 0
        # Integrated Multi-Module Execution State
        self.integrated_result: Optional[Dict[str, Any]] = None
        self.integrated_events: List[Dict[str, Any]] = []
        self.integrated_event_index: int = 0
        self.integrated_running: bool = False

    def reset(self):
        self.process_manager.reset()
        self.memory_manager.reset()
        self.resource_manager.reset()
        self.app_manager.reset_all()
        self.simulation_events = []
        self.gantt_chart = []
        self.metrics = {}
        self.simulation_running = False
        self.current_event_index = 0
        self.simulation_time = 0
        self.storage_used_gb = 0

    def load_demo(self, session_id: Optional[str] = None):
        self.reset()
        self.current_session_id = session_id
        procs = self.process_manager.load_demo_processes(session_id)
        # Allocate memory for each process
        for p in procs:
            self.memory_manager.allocate(p.pid, p.name, p.memory_mb)
        return [p.to_dict() for p in procs]

    def run_scheduler(self, algorithm: str = 'FCFS', quantum: int = 2, process_ids: Optional[List[Any]] = None) -> Dict[str, Any]:
        self.current_algorithm = algorithm
        self.time_quantum = quantum
        processes = self.process_manager.get_all()
        if process_ids is not None:
            pid_set = {str(x) for x in process_ids}
            processes = [p for p in processes if str(p.get('pid')) in pid_set]
        if not processes:
            return {'success': False, 'error': 'No processes to schedule'}

        proc_dicts = [{
            'pid': p['pid'],
            'name': p['name'],
            'arrival_time': p['arrival_time'],
            'burst_time': p['burst_time'],
            'priority': p['priority'],
            'memory_mb': p['memory_mb']
        } for p in processes]

        if algorithm == 'FCFS':
            result = sched.fcfs(proc_dicts)
        elif algorithm == 'Priority':
            result = sched.priority_scheduling(proc_dicts)
        elif algorithm == 'RoundRobin':
            result = sched.round_robin(proc_dicts, quantum)
        elif algorithm == 'SJF':
            result = sched.sjf(proc_dicts)
        else:
            return {'success': False, 'error': f'Unknown algorithm: {algorithm}'}

        self.simulation_events = result['events']
        self.gantt_chart = result['gantt_chart']
        self.metrics = result.get('metrics', {})
        self.current_event_index = 0
        self.simulation_running = True
        result['success'] = True
        return result

    def get_next_event(self) -> Optional[Dict]:
        if self.current_event_index >= len(self.simulation_events):
            self.simulation_running = False
            return None
        event = self.simulation_events[self.current_event_index]
        self.current_event_index += 1
        self.simulation_time = event.get('time', self.simulation_time)
        return event

    def get_state(self) -> Dict[str, Any]:
        return {
            'session_id': self.current_session_id,
            'algorithm': self.current_algorithm,
            'time_quantum': self.time_quantum,
            'simulation_time': self.simulation_time,
            'simulation_running': self.simulation_running,
            'current_event_index': self.current_event_index,
            'total_events': len(self.simulation_events),
            'score': self.score,
            'processes': self.process_manager.get_all(),
            'memory': self.memory_manager.get_state(),
            'resources': self.resource_manager.get_state(),
            'metrics': self.metrics,
            'apps': self.app_manager.get_state(),
            'storage': {
                'total_gb': self.storage_total_gb,
                'used_gb': self.storage_used_gb,
                'free_gb': self.storage_total_gb - self.storage_used_gb
            }
        }

    def update_score(self, delta: int, reason: str) -> int:
        self.score += delta
        return self.score

    def detect_deadlock(self) -> Dict[str, Any]:
        matrix = self.resource_manager.get_allocation_matrix()
        return self.deadlock_detector.detect(
            matrix['allocation'], matrix['request'], matrix['available']
        )

    def load_deadlock_scenario(self, scenario_type: str = 'two_process') -> Dict[str, Any]:
        self.resource_manager.reset()
        if scenario_type == 'three_process':
            scenario = DeadlockScenario.three_process_deadlock()
        else:
            scenario = DeadlockScenario.circular_wait_two_processes()
        # Apply allocation/request to resource manager
        for pid, resources in scenario['allocation'].items():
            for rid, cnt in resources.items():
                self.resource_manager.force_allocate(pid, rid, cnt)
        for pid, resources in scenario['request'].items():
            for rid in resources:
                self.resource_manager.force_request(pid, rid)
        # Override available
        for rid, avail in scenario['available'].items():
            if rid in self.resource_manager.resources:
                self.resource_manager.resources[rid].available = avail
        result = self.deadlock_detector.detect(
            scenario['allocation'], scenario['request'], scenario['available']
        )
        result['scenario'] = scenario
        return result

    def run_integrated(self,
                       cpu_algo: str = 'RoundRobin',
                       disk_algo: str = 'SSTF',
                       page_algo: str = 'LRU',
                       quantum: int = 2,
                       num_frames: int = 4,
                       initial_head: int = 50,
                       demand_paging: bool = True,
                       custom_processes: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Runs the unified Process (CPU) + Memory (Page Faults) + Storage (Disk I/O) pipeline."""
        pipeline = IntegratedPipeline(
            cpu_algo=cpu_algo,
            disk_algo=disk_algo,
            page_algo=page_algo,
            quantum=quantum,
            num_frames=num_frames,
            initial_head=initial_head,
            demand_paging=demand_paging
        )
        self.integrated_pipeline = pipeline
        procs = custom_processes if custom_processes else IntegratedPipeline.get_default_demo_processes()
        result = pipeline.simulate(procs)

        self.integrated_result = result
        self.integrated_events = result['events']
        self.integrated_event_index = 0
        self.integrated_running = True
        return result

    def step_integrated(self) -> Dict[str, Any]:
        """Steps forward 1 event in the integrated simulation trace."""
        if not self.integrated_events or self.integrated_event_index >= len(self.integrated_events):
            self.integrated_running = False
            return {'done': True, 'event': None, 'state': self.get_integrated_state()}

        event = self.integrated_events[self.integrated_event_index]
        self.integrated_event_index += 1
        is_done = self.integrated_event_index >= len(self.integrated_events)
        if is_done:
            self.integrated_running = False

        return {
            'done': is_done,
            'event': event,
            'event_index': self.integrated_event_index,
            'total_events': len(self.integrated_events),
            'state': self.get_integrated_state()
        }

    def get_integrated_state(self) -> Dict[str, Any]:
        """Returns the current integrated simulation state."""
        return {
            'running': self.integrated_running,
            'event_index': self.integrated_event_index,
            'total_events': len(self.integrated_events),
            'config': self.integrated_result.get('config', {}) if self.integrated_result else {},
            'metrics': self.integrated_result.get('metrics', {}) if self.integrated_result else {},
            'final_memory': self.integrated_result.get('final_memory', {}) if self.integrated_result else {},
            'final_disk': self.integrated_result.get('final_disk', {}) if self.integrated_result else {}
        }

    def reset_integrated(self):
        """Resets the integrated simulation state."""
        self.integrated_result = None
        self.integrated_events = []
        self.integrated_event_index = 0
        self.integrated_running = False
