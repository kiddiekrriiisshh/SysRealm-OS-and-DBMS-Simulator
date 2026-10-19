"""
SysRealm Deadlock Detector
Detects deadlocks using Resource Allocation Graph cycle detection
"""

from typing import Dict, List, Optional, Any, Set, Tuple


class DeadlockDetector:
    def __init__(self):
        pass

    def detect(self, allocation: Dict[str, Dict], request: Dict[str, Dict],
               available: Dict[str, int]) -> Dict[str, Any]:
        """
        Banker's Algorithm / RAG cycle detection.
        allocation: {pid: {resource_id: count}}
        request: {pid: {resource_id: count}}
        available: {resource_id: count}
        """
        all_pids = set(list(allocation.keys()) + list(request.keys()))
        if not all_pids:
            return {
                'deadlock': False,
                'cycle': [],
                'deadlocked_processes': [],
                'explanation': 'No processes to analyze.',
                'graph': {'nodes': [], 'edges': []}
            }

        # Build RAG
        nodes = []
        edges = []
        resource_ids = set()
        for pid in all_pids:
            nodes.append({'id': pid, 'type': 'process', 'label': pid})
        for pid, resources in allocation.items():
            for rid, cnt in resources.items():
                resource_ids.add(rid)
                edges.append({'from': rid, 'to': pid, 'type': 'allocation', 'count': cnt})
        for pid, resources in request.items():
            for rid, cnt in resources.items():
                resource_ids.add(rid)
                edges.append({'from': pid, 'to': rid, 'type': 'request', 'count': cnt})
        for rid in resource_ids:
            nodes.append({'id': rid, 'type': 'resource', 'label': rid, 'available': available.get(rid, 0)})

        # Deadlock detection using Banker's safety reduction and RAG cycle analysis
        deadlocked = self._find_deadlocked_processes(all_pids, allocation, request, available)
        cycle = self._find_cycle_in_rag(allocation, request)

        rag_theorem = (
            "OS Graph Theory Theorem: If each resource type has exactly 1 instance, a cycle in the RAG "
            "is necessary and sufficient to prove deadlock. If resource types have multiple instances, "
            "a cycle is necessary but NOT always proof of deadlock (an unblocked process with an allocated "
            "instance can complete and release it, resolving the cycle). SysRealm pairs DFS cycle detection "
            "with Banker's safety reduction for conclusive verification."
        )

        if deadlocked:
            if cycle:
                explanation = (
                    f"DEADLOCK CONFIRMED! Processes {list(deadlocked)} are locked in circular wait "
                    f"({' → '.join(cycle)}). Banker's safety reduction confirms no process can proceed."
                )
            else:
                explanation = (
                    f"DEADLOCK DETECTED! Processes {list(deadlocked)} cannot complete under Banker's reduction."
                )
        elif cycle:
            explanation = (
                f"CYCLE DETECTED WITHOUT DEADLOCK: A cycle was found ({' → '.join(cycle)}), but resource types "
                f"have multiple instances. Banker's reduction confirms other processes can safely complete "
                f"and release instances, preventing a system freeze."
            )
        else:
            explanation = "No deadlock detected. No circular wait in RAG and all processes can safely complete."

        return {
            'deadlock': bool(deadlocked),
            'cycle': cycle,
            'deadlocked_processes': list(deadlocked),
            'explanation': explanation,
            'rag_theorem': rag_theorem,
            'graph': {'nodes': nodes, 'edges': edges}
        }

    def _find_deadlocked_processes(self, all_pids: Set, allocation: Dict,
                                   request: Dict, available: Dict) -> Set[str]:
        """Mark processes that cannot complete (Banker's safety algorithm)"""
        work = dict(available)
        finish = {pid: False for pid in all_pids}
        # Processes with no requests can finish
        for pid in all_pids:
            if not request.get(pid):
                finish[pid] = True
                # Release their resources
                for rid, cnt in allocation.get(pid, {}).items():
                    work[rid] = work.get(rid, 0) + cnt

        changed = True
        while changed:
            changed = False
            for pid in all_pids:
                if finish[pid]:
                    continue
                needs = request.get(pid, {})
                if all(needs.get(rid, 0) <= work.get(rid, 0) for rid in needs):
                    finish[pid] = True
                    for rid, cnt in allocation.get(pid, {}).items():
                        work[rid] = work.get(rid, 0) + cnt
                    changed = True

        return {pid for pid, done in finish.items() if not done}

    def _find_cycle_in_rag(self, allocation: Dict, request: Dict) -> List[str]:
        """DFS-based cycle detection"""
        # Build adjacency: process -> resource (request), resource -> process (allocation)
        adj = {}
        for pid, resources in request.items():
            adj.setdefault(pid, set())
            for rid in resources:
                adj[pid].add(rid)
        for pid, resources in allocation.items():
            for rid in resources:
                adj.setdefault(rid, set())
                adj[rid].add(pid)

        visited = set()
        rec_stack = set()
        cycle_path = []

        def dfs(node, path):
            visited.add(node)
            rec_stack.add(node)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    result = dfs(neighbor, path + [neighbor])
                    if result:
                        return result
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor) if neighbor in path else 0
                    return path[cycle_start:] + [neighbor]
            rec_stack.discard(node)
            return None

        for node in list(adj.keys()):
            if node not in visited:
                result = dfs(node, [node])
                if result:
                    return result
        return []


class DeadlockScenario:
    @staticmethod
    def circular_wait_two_processes():
        """Classic P1 holds R1, wants R2. P2 holds R2, wants R1."""
        return {
            'description': 'P1 holds Printer and waits for Disk. P2 holds Disk and waits for Printer. Circular wait!',
            'processes': [
                {'pid': 'DP1', 'name': 'Process-1', 'arrival_time': 0, 'burst_time': 5, 'priority': 1, 'memory_mb': 256},
                {'pid': 'DP2', 'name': 'Process-2', 'arrival_time': 0, 'burst_time': 5, 'priority': 1, 'memory_mb': 256},
            ],
            'allocation': {
                'DP1': {'PRINTER': 1},
                'DP2': {'DISK': 1},
            },
            'request': {
                'DP1': {'DISK': 1},
                'DP2': {'PRINTER': 1},
            },
            'available': {'PRINTER': 0, 'DISK': 0, 'NETWORK': 1, 'IO_DEVICE': 2}
        }

    @staticmethod
    def three_process_deadlock():
        """Three-way circular wait"""
        return {
            'description': 'P1→R2, P2→R3, P3→R1 (three-way deadlock)',
            'processes': [
                {'pid': 'DP1', 'name': 'Process-1', 'arrival_time': 0, 'burst_time': 5, 'priority': 1, 'memory_mb': 256},
                {'pid': 'DP2', 'name': 'Process-2', 'arrival_time': 0, 'burst_time': 5, 'priority': 1, 'memory_mb': 256},
                {'pid': 'DP3', 'name': 'Process-3', 'arrival_time': 0, 'burst_time': 5, 'priority': 1, 'memory_mb': 256},
            ],
            'allocation': {
                'DP1': {'PRINTER': 1},
                'DP2': {'NETWORK': 1},
                'DP3': {'DISK': 1},
            },
            'request': {
                'DP1': {'NETWORK': 1},
                'DP2': {'DISK': 1},
                'DP3': {'PRINTER': 1},
            },
            'available': {'PRINTER': 0, 'DISK': 0, 'NETWORK': 0, 'IO_DEVICE': 2}
        }


class DeadlockPrevention:
    """
    Implements all 4 Coffman conditions for deadlock prevention.
    Each strategy explains HOW the OS handles/prevents the deadlock
    given a specific set of custom processes.
    """

    RESOURCE_ORDER = {'PRINTER': 1, 'DISK': 2, 'NETWORK': 3, 'IO_DEVICE': 4}

    @classmethod
    def apply(cls, strategy: str, processes: list, allocation: dict, request: dict, available: dict) -> dict:
        """
        Apply a prevention strategy and return explanation + modified state.
        strategy: 'mutual_exclusion' | 'hold_wait' | 'no_preemption' | 'circular_wait'
        """
        if strategy == 'mutual_exclusion':
            return cls.mutual_exclusion(processes, allocation, request)
        elif strategy == 'hold_wait':
            return cls.hold_and_wait(processes, allocation, request, available)
        elif strategy == 'no_preemption':
            return cls.no_preemption(processes, allocation, request, available)
        elif strategy == 'circular_wait':
            return cls.circular_wait(processes, allocation, request)
        else:
            return {'success': False, 'error': f'Unknown strategy: {strategy}'}

    @classmethod
    def mutual_exclusion(cls, processes, allocation, request):
        """
        Condition 1: Mutual Exclusion
        Resources must be non-shareable (e.g., a printer can't be used by 2 at once).
        This condition CANNOT be eliminated for truly non-shareable resources.
        OS Response: Convert resources to shareable where possible (e.g., spooling for printers).
        """
        non_shareable = []
        shareable_candidates = []
        all_resources = set()
        for alloc in allocation.values():
            all_resources.update(alloc.keys())
        for req in request.values():
            all_resources.update(req.keys())

        for r in all_resources:
            if r == 'PRINTER':
                shareable_candidates.append(r)
            else:
                non_shareable.append(r)

        steps = [
            "🔴 Mutual Exclusion cannot be fully eliminated for hardware resources.",
            f"Non-shareable resources: {', '.join(non_shareable) if non_shareable else 'None'}",
            f"Shareable via spooling: {', '.join(shareable_candidates) if shareable_candidates else 'None'}",
            "OS Solution: Use SPOOLING — jobs are queued for PRINTER (only 1 process uses it at a time internally, but others can submit jobs).",
            "Result: Deadlock is reduced but NOT fully eliminated — other resources remain non-shareable.",
            "Verdict: ⚠️ Partial prevention only. Use other strategies for full prevention."
        ]
        return {
            'success': True,
            'strategy': 'mutual_exclusion',
            'title': 'Condition 1: Mutual Exclusion',
            'resolved': False,
            'steps': steps,
            'graph_changes': [],
            'explanation': ' '.join(steps)
        }

    @classmethod
    def hold_and_wait(cls, processes, allocation, request, available):
        """
        Condition 2: Hold and Wait
        A process must request ALL needed resources at once BEFORE starting.
        If any resource is unavailable, the process waits without holding anything.
        """
        steps = ["🟡 Hold & Wait Prevention: Processes must request ALL resources at once."]
        graph_changes = []
        new_allocation = {}
        new_request = {}
        resolved = True

        for proc in processes:
            pid = proc['pid']
            holds = allocation.get(pid, {})
            wants = request.get(pid, {})
            all_needed = {}
            all_needed.update(holds)
            all_needed.update(wants)

            # Check if ALL resources available simultaneously
            can_get_all = all(available.get(r, 0) >= cnt for r, cnt in all_needed.items())

            if can_get_all:
                steps.append(f"✅ {pid}: Can acquire ALL resources {list(all_needed.keys())} at once → proceeds immediately.")
                new_allocation[pid] = all_needed
                for r, cnt in all_needed.items():
                    available[r] = available.get(r, 0) - cnt
                graph_changes.append({'pid': pid, 'action': 'granted_all', 'resources': list(all_needed.keys())})
            else:
                unavailable = [r for r, cnt in all_needed.items() if available.get(r, 0) < cnt]
                steps.append(f"⏳ {pid}: Cannot get {unavailable} right now → releases held resources and WAITS (no holding).")
                # Process releases everything it holds
                for r, cnt in holds.items():
                    available[r] = available.get(r, 0) + cnt
                new_request[pid] = all_needed
                graph_changes.append({'pid': pid, 'action': 'released_and_waiting', 'resources': list(holds.keys())})
                resolved = False

        steps.append("✅ No circular wait possible — no process holds a resource while waiting." if resolved
                      else "⚠️ Some processes are waiting (but NOT holding). No deadlock — they'll get resources when available.")

        return {
            'success': True,
            'strategy': 'hold_wait',
            'title': 'Condition 2: Hold & Wait Eliminated',
            'resolved': True,  # deadlock is prevented even if some processes wait
            'steps': steps,
            'graph_changes': graph_changes,
            'explanation': ' | '.join(steps)
        }

    @classmethod
    def no_preemption(cls, processes, allocation, request, available):
        """
        Condition 3: No Preemption
        If a process can't get what it needs, OS preempts (takes back) all its resources.
        """
        steps = ["🟠 No Preemption Strategy: OS forcibly reclaims resources from blocked processes."]
        graph_changes = []
        preempted = []

        for proc in processes:
            pid = proc['pid']
            holds = allocation.get(pid, {})
            wants = request.get(pid, {})

            if not wants:
                steps.append(f"✅ {pid}: Has no pending requests — continues normally.")
                continue

            # Can it get what it wants?
            can_proceed = all(available.get(r, 0) >= cnt for r, cnt in wants.items())

            if not can_proceed:
                # OS preempts — takes back all held resources
                preempted.append(pid)
                freed = list(holds.keys())
                for r, cnt in holds.items():
                    available[r] = available.get(r, 0) + cnt
                steps.append(f"🔴 {pid} is BLOCKED. OS PREEMPTS — reclaims {freed} from {pid}. {pid} is rolled back to NEW state.")
                graph_changes.append({'pid': pid, 'action': 'preempted', 'freed_resources': freed})
            else:
                steps.append(f"✅ {pid}: Can proceed — gets {list(wants.keys())} from available pool.")
                graph_changes.append({'pid': pid, 'action': 'proceeds', 'resources': list(wants.keys())})

        if preempted:
            steps.append(f"Preempted processes: {preempted}. They will retry later when resources are available.")
            steps.append("✅ Deadlock BROKEN — circular wait eliminated by forced preemption.")
        else:
            steps.append("✅ No preemption needed — all processes can proceed.")

        return {
            'success': True,
            'strategy': 'no_preemption',
            'title': 'Condition 3: No Preemption Applied',
            'resolved': True,
            'steps': steps,
            'graph_changes': graph_changes,
            'explanation': ' | '.join(steps)
        }

    @classmethod
    def circular_wait(cls, processes, allocation, request):
        """
        Condition 4: Circular Wait
        OS imposes a strict global ordering on resources.
        Processes must request resources only in ascending order of their rank.
        """
        resource_order = cls.RESOURCE_ORDER
        steps = [
            "🟢 Circular Wait Prevention: OS assigns a global order to all resources.",
            f"Resource Order: {' < '.join(sorted(resource_order, key=resource_order.get))}",
            f"(PRINTER=1, DISK=2, NETWORK=3, IO_DEVICE=4)",
            "Rule: A process may only request resource Rj if rank(Rj) > rank of ALL currently held resources."
        ]
        graph_changes = []
        violations = []

        for proc in processes:
            pid = proc['pid']
            holds = allocation.get(pid, {})
            wants = request.get(pid, {})

            if not holds or not wants:
                steps.append(f"✅ {pid}: No conflict — not both holding and requesting.")
                continue

            max_held_rank = max((resource_order.get(r, 99) for r in holds), default=0)
            for r in wants:
                r_rank = resource_order.get(r, 99)
                if r_rank <= max_held_rank:
                    held_names = [h for h in holds if resource_order.get(h, 0) >= r_rank]
                    violations.append({'pid': pid, 'resource': r, 'held': held_names})
                    steps.append(
                        f"❌ VIOLATION: {pid} holds {list(holds.keys())} (max rank={max_held_rank}) "
                        f"but requests {r} (rank={r_rank}). OS DENIES this request."
                    )
                    steps.append(
                        f"   → OS tells {pid}: Release {list(holds.keys())} first, "
                        f"then re-request in order: {sorted(list(holds.keys()) + [r], key=lambda x: resource_order.get(x, 99))}."
                    )
                    graph_changes.append({'pid': pid, 'action': 'order_violation_denied', 'resource': r})
                else:
                    steps.append(f"✅ {pid}: Requests {r} (rank={r_rank}) > held max rank ({max_held_rank}). Allowed.")
                    graph_changes.append({'pid': pid, 'action': 'order_ok', 'resource': r})

        if violations:
            steps.append(f"✅ Deadlock PREVENTED — {len(violations)} out-of-order request(s) denied by OS. No circular wait possible.")
        else:
            steps.append("✅ All requests follow resource ordering — no circular wait possible even without intervention.")

        return {
            'success': True,
            'strategy': 'circular_wait',
            'title': 'Condition 4: Circular Wait Eliminated',
            'resolved': True,
            'steps': steps,
            'graph_changes': graph_changes,
            'violations': violations,
            'explanation': ' | '.join(steps)
        }

