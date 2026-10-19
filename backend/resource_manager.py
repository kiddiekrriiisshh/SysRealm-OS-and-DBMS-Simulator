"""
SysRealm Resource Manager
Simulates hardware resource allocation (Printer, Disk, Network, I/O)
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from collections import defaultdict


@dataclass
class Resource:
    resource_id: str
    name: str
    total: int
    available: int
    allocated: Dict[str, int] = field(default_factory=dict)  # pid -> count
    waiting_queue: List[str] = field(default_factory=list)   # list of pids
    icon: str = '🖨️'

    def to_dict(self):
        return {
            'resource_id': self.resource_id,
            'name': self.name,
            'total': self.total,
            'available': self.available,
            'allocated': self.allocated,
            'waiting_queue': self.waiting_queue,
            'icon': self.icon
        }


DEFAULT_RESOURCES = [
    {'resource_id': 'PRINTER', 'name': 'Printer', 'total': 1, 'available': 1, 'icon': '🖨️'},
    {'resource_id': 'DISK', 'name': 'Disk', 'total': 2, 'available': 2, 'icon': '💾'},
    {'resource_id': 'NETWORK', 'name': 'Network', 'total': 1, 'available': 1, 'icon': '🌐'},
    {'resource_id': 'IO_DEVICE', 'name': 'I/O Device', 'total': 2, 'available': 2, 'icon': '⌨️'},
]


class ResourceManager:
    def __init__(self):
        self.resources: Dict[str, Resource] = {}
        self._init_defaults()

    def _init_defaults(self):
        for r in DEFAULT_RESOURCES:
            self.resources[r['resource_id']] = Resource(**r)

    def request(self, pid: str, resource_id: str, count: int = 1) -> Dict[str, Any]:
        if resource_id not in self.resources:
            return {'success': False, 'error': f'Resource {resource_id} not found'}
        res = self.resources[resource_id]
        if res.available >= count:
            res.available -= count
            res.allocated[pid] = res.allocated.get(pid, 0) + count
            return {
                'success': True,
                'message': f'{res.name} allocated to {pid}.',
                'resource': res.to_dict()
            }
        else:
            if pid not in res.waiting_queue:
                res.waiting_queue.append(pid)
            return {
                'success': False,
                'waiting': True,
                'message': f'{res.name} unavailable. {pid} added to waiting queue.',
                'resource': res.to_dict()
            }

    def release(self, pid: str, resource_id: str, count: int = 1) -> Dict[str, Any]:
        if resource_id not in self.resources:
            return {'success': False, 'error': f'Resource {resource_id} not found'}
        res = self.resources[resource_id]
        if pid not in res.allocated:
            return {'success': False, 'error': f'{pid} has no allocation of {res.name}'}
        released = min(count, res.allocated.get(pid, 0))
        res.allocated[pid] -= released
        if res.allocated[pid] <= 0:
            del res.allocated[pid]
        res.available += released
        # Grant to next in waiting queue
        granted_to = None
        if res.waiting_queue and res.available > 0:
            next_pid = res.waiting_queue.pop(0)
            res.available -= 1
            res.allocated[next_pid] = res.allocated.get(next_pid, 0) + 1
            granted_to = next_pid
        return {
            'success': True,
            'message': f'{pid} released {res.name}.' + (f' Granted to {granted_to}.' if granted_to else ''),
            'granted_to': granted_to,
            'resource': res.to_dict()
        }

    def get_state(self) -> Dict[str, Any]:
        return {
            'resources': {rid: r.to_dict() for rid, r in self.resources.items()}
        }

    def get_allocation_matrix(self) -> Dict[str, Any]:
        """Returns allocation and request matrices for deadlock detection"""
        allocation = defaultdict(dict)
        request = defaultdict(dict)
        for rid, res in self.resources.items():
            for pid, cnt in res.allocated.items():
                allocation[pid][rid] = cnt
            for pid in res.waiting_queue:
                request[pid][rid] = request[pid].get(rid, 0) + 1
        return {
            'allocation': dict(allocation),
            'request': dict(request),
            'available': {rid: res.available for rid, res in self.resources.items()}
        }

    def reset(self):
        self.resources = {}
        self._init_defaults()

    def force_allocate(self, pid: str, resource_id: str, count: int = 1):
        """For deadlock scenario setup — bypass availability check"""
        if resource_id not in self.resources:
            return
        res = self.resources[resource_id]
        res.allocated[pid] = res.allocated.get(pid, 0) + count
        res.available = max(0, res.available - count)

    def force_request(self, pid: str, resource_id: str):
        """For deadlock scenario setup"""
        if resource_id not in self.resources:
            return
        res = self.resources[resource_id]
        if pid not in res.waiting_queue:
            res.waiting_queue.append(pid)
