"""
SysRealm Memory Manager
Simulates RAM allocation with both Contiguous View and Non-Contiguous Hardware Paging:
- 32 Physical Frames x 512 MB = 16,384 MB (16 GB) RAM
- Per-Process Page Tables (Page Number -> Frame Number | Valid Bit | Internal Fragmentation)
- MMU Logical-to-Physical Address Translator:
    p = floor(Address / PageSize)
    d = Address mod PageSize
    Physical Address = (Frame * PageSize) + d
"""

import math
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict


@dataclass
class MemoryBlock:
    pid: str
    name: str
    size_mb: int
    start_addr: int
    end_addr: int
    color: str = '#3498db'

    def to_dict(self):
        return asdict(self)


PROCESS_COLORS = [
    '#e74c3c', '#3498db', '#2ecc71', '#f39c12',
    '#9b59b6', '#1abc9c', '#e67e22', '#e91e63'
]

# Non-contiguous frame order to realistically simulate scattered OS physical frames
SCATTER_FRAME_ORDER = [
    0, 3, 6, 1, 5, 9, 2, 7,
    11, 4, 8, 13, 10, 15, 12, 18,
    14, 20, 16, 22, 17, 25, 19, 27,
    21, 29, 23, 31, 24, 26, 28, 30
]


class MemoryManager:
    def __init__(self, total_mb: int = 16384, page_size_mb: int = 512):  # 16 GB, 32 Frames x 512 MB
        self.total_mb = total_mb
        self.page_size_mb = page_size_mb
        self.num_frames = total_mb // page_size_mb
        self.allocations: Dict[str, MemoryBlock] = {}
        self.frames: List[Optional[Dict[str, Any]]] = [None] * self.num_frames
        self.page_tables: Dict[str, Dict[str, Any]] = {}
        self.scatter_mode: bool = True
        self._color_idx = 0

    def _next_color(self):
        c = PROCESS_COLORS[self._color_idx % len(PROCESS_COLORS)]
        self._color_idx += 1
        return c

    def _pick_free_frames(self, count: int) -> List[int]:
        """Selects `count` free physical frames (non-contiguously when scatter_mode is active)."""
        free_indices = [i for i in range(self.num_frames) if self.frames[i] is None]
        if len(free_indices) < count:
            return []
        if self.scatter_mode:
            ordered = [idx for idx in SCATTER_FRAME_ORDER if idx < self.num_frames and self.frames[idx] is None]
            # Append any remaining free indices not in SCATTER_FRAME_ORDER
            for idx in free_indices:
                if idx not in ordered:
                    ordered.append(idx)
            return ordered[:count]
        return free_indices[:count]

    def allocate(self, pid: str, name: str, size_mb: int) -> Dict[str, Any]:
        if pid in self.allocations:
            return {'success': False, 'error': f'Process {pid} already has memory allocated'}
        if size_mb <= 0:
            return {'success': False, 'error': 'Memory size must be positive'}

        pages_needed = math.ceil(size_mb / self.page_size_mb)
        chosen_frames = self._pick_free_frames(pages_needed)
        if not chosen_frames:
            free_frames = sum(1 for f in self.frames if f is None)
            return {
                'success': False,
                'error': (
                    f'Insufficient physical frames. Requested: {size_mb} MB ({pages_needed} pages), '
                    f'Free Frames: {free_frames} ({free_frames * self.page_size_mb} MB)'
                )
            }

        color = self._next_color()
        start_addr = 0
        if self.allocations:
            start_addr = max(b.end_addr for b in self.allocations.values()) + 1

        block = MemoryBlock(
            pid=pid,
            name=name,
            size_mb=size_mb,
            start_addr=start_addr,
            end_addr=start_addr + size_mb - 1,
            color=color
        )
        self.allocations[pid] = block

        # Populate Physical Frames and Per-Process Page Table
        entries = []
        remaining_mb = size_mb
        for page_no, frame_no in enumerate(chosen_frames):
            used_in_page = min(self.page_size_mb, remaining_mb)
            wasted_in_page = self.page_size_mb - used_in_page
            remaining_mb = max(0, remaining_mb - used_in_page)

            phys_start = frame_no * self.page_size_mb
            phys_end = phys_start + self.page_size_mb - 1

            frame_data = {
                'frame_no': frame_no,
                'pid': pid,
                'name': name,
                'page_no': page_no,
                'total_pages': pages_needed,
                'used_mb': used_in_page,
                'internal_frag_mb': wasted_in_page,
                'phys_start_mb': phys_start,
                'phys_end_mb': phys_end,
                'color': color,
                'valid_bit': 1
            }
            self.frames[frame_no] = frame_data
            entries.append({
                'page_no': page_no,
                'frame_no': frame_no,
                'valid_bit': 1,
                'logical_start_mb': page_no * self.page_size_mb,
                'logical_end_mb': (page_no + 1) * self.page_size_mb - 1,
                'phys_start_mb': phys_start,
                'phys_end_mb': phys_end,
                'used_mb': used_in_page,
                'internal_frag_mb': wasted_in_page
            })

        allocated_frame_mb = pages_needed * self.page_size_mb
        internal_frag_mb = allocated_frame_mb - size_mb

        self.page_tables[pid] = {
            'pid': pid,
            'name': name,
            'color': color,
            'size_mb': size_mb,
            'page_size_mb': self.page_size_mb,
            'num_pages': pages_needed,
            'allocated_frame_mb': allocated_frame_mb,
            'internal_frag_mb': internal_frag_mb,
            'frames_list': chosen_frames,
            'entries': entries
        }

        return {
            'success': True,
            'block': block.to_dict(),
            'page_table': self.page_tables[pid],
            'used_mb': self.used_mb(),
            'free_mb': self.free_mb()
        }

    def release(self, pid: str) -> Dict[str, Any]:
        if pid not in self.allocations:
            return {'success': False, 'error': f'No memory allocated for {pid}'}
        block = self.allocations.pop(pid)
        self.page_tables.pop(pid, None)
        for i in range(self.num_frames):
            if self.frames[i] and self.frames[i].get('pid') == pid:
                self.frames[i] = None
        return {
            'success': True,
            'freed_mb': block.size_mb,
            'used_mb': self.used_mb(),
            'free_mb': self.free_mb()
        }

    def reshuffle_frames(self, scatter: bool = True) -> Dict[str, Any]:
        """Re-allocates all current processes in either scattered (non-contiguous) or contiguous frame order."""
        saved = [(b.pid, b.name, b.size_mb) for b in self.allocations.values()]
        self.reset()
        self.scatter_mode = scatter
        for pid, name, size_mb in saved:
            self.allocate(pid, name, size_mb)
        return self.get_state()

    def load_paging_demo(self) -> Dict[str, Any]:
        """
        Loads a 4-process Non-Contiguous Paging & Internal Fragmentation showcase:
        - P1 (Browser):          1200 MB -> 3 Pages (1536 MB allocated, 336 MB internal frag on Page 2)
        - P2 (Music Player):      650 MB -> 2 Pages (1024 MB allocated, 374 MB internal frag on Page 1)
        - P3 (Game Engine):      1850 MB -> 4 Pages (2048 MB allocated, 198 MB internal frag on Page 3)
        - P4 (Download Manager):  768 MB -> 2 Pages (1024 MB allocated, 256 MB internal frag on Page 1)
        """
        self.reset()
        self.scatter_mode = True
        demo_procs = [
            ('P1', 'Browser', 1200),
            ('P2', 'Music Player', 650),
            ('P3', 'Game Engine', 1850),
            ('P4', 'Download Manager', 768),
        ]
        for pid, name, size_mb in demo_procs:
            self.allocate(pid, name, size_mb)
        return self.get_state()

    def translate_address(self, pid: str, logical_address: int) -> Dict[str, Any]:
        """
        MMU Hardware Logical-to-Physical Address Translation:
        p = floor(logical_address / page_size_mb)
        d = logical_address mod page_size_mb
        phys = (frame_no * page_size_mb) + d
        """
        if pid not in self.page_tables:
            return {'success': False, 'error': f'Process {pid} has no Page Table in memory'}
        if logical_address < 0:
            return {'success': False, 'error': 'Logical address cannot be negative'}

        pt = self.page_tables[pid]
        page_size = self.page_size_mb
        page_no = logical_address // page_size
        offset = logical_address % page_size

        # Case 1: Page number outside process page table -> Page Fault / Protection Trap
        if page_no >= pt['num_pages']:
            return {
                'success': True,
                'status': 'PAGE_FAULT_OUT_OF_BOUNDS',
                'valid': False,
                'pid': pid,
                'process_name': pt['name'],
                'process_size_mb': pt['size_mb'],
                'logical_address': logical_address,
                'page_size_mb': page_size,
                'page_no': page_no,
                'offset': offset,
                'max_page_no': pt['num_pages'] - 1,
                'frame_no': None,
                'physical_address': None,
                'message': (
                    f"🔴 MMU PAGE TRAP (OUT OF BOUNDS): Logical Address {logical_address} MB maps to "
                    f"Page p = ⌊{logical_address} / {page_size}⌋ = {page_no}, which exceeds {pid}'s "
                    f"Page Table limit (Pages 0..{pt['num_pages'] - 1}, Valid Bit = 0)!"
                )
            }

        entry = pt['entries'][page_no]
        frame_no = entry['frame_no']
        physical_address = (frame_no * page_size) + offset

        # Case 2: Within allocated frame, but falls in Internal Fragmentation padding of the last page
        in_internal_frag = logical_address >= pt['size_mb']

        return {
            'success': True,
            'status': 'INTERNAL_FRAGMENTATION_WARNING' if in_internal_frag else 'TRANSLATION_SUCCESS',
            'valid': not in_internal_frag,
            'in_internal_fragmentation': in_internal_frag,
            'pid': pid,
            'process_name': pt['name'],
            'process_size_mb': pt['size_mb'],
            'color': pt['color'],
            'logical_address': logical_address,
            'page_size_mb': page_size,
            'page_no': page_no,
            'offset': offset,
            'frame_no': frame_no,
            'valid_bit': entry['valid_bit'],
            'physical_address': physical_address,
            'frame_start_mb': entry['phys_start_mb'],
            'frame_end_mb': entry['phys_end_mb'],
            'formulas': {
                'page_calc': f"p = ⌊{logical_address} / {page_size}⌋ = {page_no}",
                'offset_calc': f"d = {logical_address} mod {page_size} = {offset} MB",
                'frame_lookup': f"PageTable[{pid}][Page {page_no}] → Frame {frame_no} (Valid = 1)",
                'phys_calc': f"Physical Address = ({frame_no} × {page_size}) + {offset} = {physical_address} MB"
            },
            'message': (
                f"⚠️ INTERNAL FRAGMENTATION REGION: Page {page_no} maps to Frame {frame_no} "
                f"(Physical Address {physical_address} MB), but Logical Address {logical_address} MB "
                f"is beyond {pid}'s actual size ({pt['size_mb']} MB) — inside the {entry['internal_frag_mb']} MB wasted tail of Frame {frame_no}!"
                if in_internal_frag else
                f"✅ MMU TRANSLATION HIT: Logical {logical_address} MB → (Page {page_no}, Offset {offset} MB) "
                f"→ Frame {frame_no} → Physical Address {physical_address} MB!"
            )
        }

    def used_mb(self) -> int:
        return sum(b.size_mb for b in self.allocations.values())

    def allocated_frames_mb(self) -> int:
        used_frames = sum(1 for f in self.frames if f is not None)
        return used_frames * self.page_size_mb

    def total_internal_frag_mb(self) -> int:
        return sum(pt.get('internal_frag_mb', 0) for pt in self.page_tables.values())

    def free_mb(self) -> int:
        return self.total_mb - self.used_mb()

    def utilization(self) -> float:
        return round((self.used_mb() / self.total_mb) * 100, 2) if self.total_mb > 0 else 0

    def get_state(self) -> Dict[str, Any]:
        used_frames = sum(1 for f in self.frames if f is not None)
        free_frames = self.num_frames - used_frames
        frame_grid = []
        for idx in range(self.num_frames):
            f = self.frames[idx]
            if f is None:
                frame_grid.append({
                    'frame_no': idx,
                    'allocated': False,
                    'pid': None,
                    'name': None,
                    'page_no': None,
                    'used_mb': 0,
                    'internal_frag_mb': 0,
                    'phys_start_mb': idx * self.page_size_mb,
                    'phys_end_mb': (idx + 1) * self.page_size_mb - 1,
                    'color': None
                })
            else:
                frame_grid.append(dict(f, allocated=True))

        return {
            'total_mb': self.total_mb,
            'total_gb': round(self.total_mb / 1024, 1),
            'used_mb': self.used_mb(),
            'used_gb': round(self.used_mb() / 1024, 2),
            'free_mb': self.free_mb(),
            'free_gb': round(self.free_mb() / 1024, 2),
            'utilization': self.utilization(),
            'allocations': [b.to_dict() for b in self.allocations.values()],
            'paging': {
                'page_size_mb': self.page_size_mb,
                'total_frames': self.num_frames,
                'used_frames': used_frames,
                'free_frames': free_frames,
                'allocated_frames_mb': used_frames * self.page_size_mb,
                'total_internal_frag_mb': self.total_internal_frag_mb(),
                'scatter_mode': self.scatter_mode,
                'frames': frame_grid,
                'page_tables': self.page_tables
            }
        }

    def simulate_page_replacement(self, ref_string: List[int], num_frames: int = 3, algorithm: str = 'FIFO') -> Dict[str, Any]:
        """
        Simulates Demand Paging & Page Replacement (FIFO, LRU, OPTIMAL).
        Returns the full Frame-by-Step Matrix, Page Hits, Page Faults, Hit Ratio %, and step explanations.
        """
        algo = algorithm.upper()
        if algo not in ('FIFO', 'LRU', 'OPTIMAL'):
            algo = 'FIFO'
        num_frames = max(1, min(8, int(num_frames)))

        frames: List[Optional[int]] = [None] * num_frames
        fifo_order: List[int] = []         # stores frame indices in FIFO load order
        loaded_step: Dict[int, int] = {}   # page -> step when loaded
        last_used: Dict[int, int] = {}     # page -> step when last referenced

        steps = []
        hits = 0
        faults = 0

        for i, page in enumerate(ref_string):
            last_used[page] = i
            if page in frames:
                hits += 1
                hit_frame_idx = frames.index(page)
                steps.append({
                    'step': i + 1,
                    'page': page,
                    'status': 'HIT',
                    'frames': list(frames),
                    'target_frame': hit_frame_idx,
                    'victim': None,
                    'reason': f"Page {page} is already in Frame {hit_frame_idx} → PAGE HIT (🟢)"
                })
                continue

            # Page Fault
            faults += 1
            if None in frames:
                empty_idx = frames.index(None)
                frames[empty_idx] = page
                fifo_order.append(empty_idx)
                loaded_step[page] = i
                steps.append({
                    'step': i + 1,
                    'page': page,
                    'status': 'FAULT',
                    'frames': list(frames),
                    'target_frame': empty_idx,
                    'victim': None,
                    'reason': f"Cold miss: Loaded Page {page} into free Frame {empty_idx} → PAGE FAULT (🔴)"
                })
            else:
                # Choose victim frame index according to algorithm
                if algo == 'FIFO':
                    victim_frame_idx = fifo_order.pop(0)
                    victim_page = frames[victim_frame_idx]
                    reason = (
                        f"FIFO Eviction: Evicted Page {victim_page} from Frame {victim_frame_idx} "
                        f"(oldest loaded at step {loaded_step.get(victim_page, 0) + 1}) → Loaded Page {page}"
                    )
                    fifo_order.append(victim_frame_idx)

                elif algo == 'LRU':
                    # Find frame whose page has minimum last_used index
                    victim_frame_idx = min(
                        range(num_frames),
                        key=lambda f_idx: last_used.get(frames[f_idx], -1)
                    )
                    victim_page = frames[victim_frame_idx]
                    prev_step = last_used.get(victim_page, 0) + 1
                    reason = (
                        f"LRU Eviction: Evicted Page {victim_page} from Frame {victim_frame_idx} "
                        f"(least recently used at step {prev_step}) → Loaded Page {page}"
                    )

                else:  # OPTIMAL
                    future_refs = ref_string[i + 1:]
                    best_frame_idx = 0
                    furthest_dist = -1
                    best_loaded = 10**9
                    for f_idx in range(num_frames):
                        p_in_frame = frames[f_idx]
                        if p_in_frame in future_refs:
                            dist = future_refs.index(p_in_frame)
                        else:
                            dist = 10**9  # never referenced again
                        p_load_time = loaded_step.get(p_in_frame, 0)
                        if dist > furthest_dist or (dist == furthest_dist and p_load_time < best_loaded):
                            furthest_dist = dist
                            best_frame_idx = f_idx
                            best_loaded = p_load_time

                    victim_frame_idx = best_frame_idx
                    victim_page = frames[victim_frame_idx]
                    if furthest_dist >= 10**9:
                        future_note = "never referenced again in future"
                    else:
                        future_note = f"next referenced furthest away at step {i + 2 + furthest_dist}"
                    reason = (
                        f"Optimal Eviction: Evicted Page {victim_page} from Frame {victim_frame_idx} "
                        f"({future_note}) → Loaded Page {page}"
                    )

                frames[victim_frame_idx] = page
                loaded_step[page] = i
                steps.append({
                    'step': i + 1,
                    'page': page,
                    'status': 'FAULT',
                    'frames': list(frames),
                    'target_frame': victim_frame_idx,
                    'victim': victim_page,
                    'reason': reason
                })

        total = len(ref_string)
        hit_ratio = round((hits / total) * 100, 2) if total > 0 else 0.0
        fault_ratio = round((faults / total) * 100, 2) if total > 0 else 0.0

        return {
            'algorithm': algo,
            'num_frames': num_frames,
            'reference_string': ref_string,
            'total_references': total,
            'page_hits': hits,
            'page_faults': faults,
            'hit_ratio': hit_ratio,
            'fault_ratio': fault_ratio,
            'steps': steps
        }

    def simulate_all_replacements(self, ref_string: List[int], num_frames: int = 3, active_algo: str = 'FIFO') -> Dict[str, Any]:
        """Runs active algorithm + compares FIFO, LRU, and Optimal + checks Belady's Anomaly."""
        active_res = self.simulate_page_replacement(ref_string, num_frames, active_algo)
        comparison = {}
        for alg in ('FIFO', 'LRU', 'OPTIMAL'):
            r = self.simulate_page_replacement(ref_string, num_frames, alg)
            comparison[alg] = {
                'algorithm': alg,
                'page_faults': r['page_faults'],
                'page_hits': r['page_hits'],
                'hit_ratio': r['hit_ratio'],
                'fault_ratio': r['fault_ratio']
            }

        # Belady's Anomaly check (FIFO with 3 frames vs 4 frames on this reference string)
        fifo_3 = self.simulate_page_replacement(ref_string, 3, 'FIFO')
        fifo_4 = self.simulate_page_replacement(ref_string, 4, 'FIFO')
        belady_detected = fifo_4['page_faults'] > fifo_3['page_faults']

        return {
            'success': True,
            'active': active_res,
            'comparison': comparison,
            'belady_check': {
                'detected': belady_detected,
                'fifo_3_frames_faults': fifo_3['page_faults'],
                'fifo_4_frames_faults': fifo_4['page_faults'],
                'explanation': (
                    f"🚨 BELADY'S ANOMALY PROVEN! On this reference string, increasing physical RAM from "
                    f"3 Frames ({fifo_3['page_faults']} Page Faults) to 4 Frames ({fifo_4['page_faults']} Page Faults) "
                    f"under FIFO actually INCREASED page faults by +{fifo_4['page_faults'] - fifo_3['page_faults']}! "
                    f"(LRU and Optimal are stack algorithms and never suffer from Belady's Anomaly.)"
                    if belady_detected else
                    f"No Belady's Anomaly on current string: FIFO 3-Frames = {fifo_3['page_faults']} faults vs. "
                    f"FIFO 4-Frames = {fifo_4['page_faults']} faults. Click '⚡ Load Belady\\'s Anomaly String' to prove it!"
                )
            }
        }

    def reset(self):
        self.allocations = {}
        self.frames = [None] * self.num_frames
        self.page_tables = {}
        self._color_idx = 0

