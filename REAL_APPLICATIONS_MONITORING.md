# SysRealm: Real Applications Monitoring & CPU Activity Timeline

**Project Title:** SysRealm: Kernel Panic — An Interactive Operating System Simulator  
**Academic Level:** Third-Year B.Tech Computer Science & Engineering  
**Subject Area:** Operating Systems (CS301 / CS302) & Systems Programming  
**Module:** Virtual Apps Lab — Real Applications Mode & Process Isolation  

---

## 1. Executive Summary & Problem Statement

Operating systems courses in undergraduate computer science curriculums often teach CPU scheduling (FCFS, SJF, Priority, Round Robin) using idealized theoretical abstractions: fixed burst times, deterministic arrival ticks, and static ready queues visualized via discrete Gantt charts. 

However, real-world operating systems—such as macOS (Darwin XNU), Linux (CFS / EEVDF), and Windows (Windows NT Kernel Scheduler)—operate in a continuous, dynamic environment with preemptive multi-core scheduling, asynchronous I/O bursts, hardware interrupts, and thousands of concurrent threads.

The **SysRealm Real Applications Monitoring Module** bridges this pedagogical gap by providing two complementary yet strictly isolated modes in the **Virtual Apps Lab**:

1. **Mode A: Virtual Applications Simulator (The Algorithmic Model)**
   - Simulates discrete application workloads (Lab Browser, Tone Player, Signal Sprint, Download Desk, Custom Apps).
   - Generates simulated processes with known arrival times, burst times, and priorities.
   - Dispatches workloads using classical scheduling algorithms.
   - Renders discrete algorithmic Gantt charts with exact slice boundaries and theoretical metrics (Average Waiting Time, Turnaround Time).
   - **Fixed Process Isolation:** Supports scheduling a selected virtual app's processes in isolation without polluting or disturbing the wider process queue.

2. **Mode B: Real Applications Monitor (Empirical System Telemetry)**
   - Observes live, physical operating system processes running on the student's personal machine (Google Chrome, Visual Studio Code, Spotify, Terminal, Shells, Python runtimes).
   - Collects non-invasive, read-only system telemetry via an external Python agent (`local_monitor/agent.py`) using `psutil`.
   - Visualizes continuous resource consumption on an **Observed Real Process Activity Timeline** sampled at discrete intervals.
   - **Architectural Boundary:** SysRealm *monitors* real OS processes; it **never** schedules, preempts, or modifies them.

---

## 2. System Architecture & Component Mapping

```
+---------------------------------------------------------------------------------------+
|                                    SYSREALM DASHBOARD                                 |
|                                                                                       |
|  +-------------------------------------+   +---------------------------------------+  |
|  |     MODE A: VIRTUAL SIMULATOR       |   |       MODE B: REAL MONITOR            |  |
|  |                                     |   |                                       |  |
|  |  * Built-in Virtual Apps            |   |  * Architecture Separation Banner     |  |
|  |  * Custom App Workload Builder      |   |  * Pairing Tray & Security Badge      |  |
|  |  * Isolated Scope Selector          |   |  * System Telemetry KPI Gauges        |  |
|  |  * Algorithmic Dispatcher (FCFS/RR) |   |  * Observed Activity Timeline         |  |
|  |  * Discrete Gantt Chart Canvas      |   |  * Detected Desktop Apps Grid         |  |
|  |  * Theoretical Waiting/Turnaround   |   |  * Real Process Inspector Table       |  |
|  +------------------^------------------+   +-------------------^-------------------+  |
+---------------------|------------------------------------------|----------------------+
                      | (Internal Flask API)                     | (REST / Polling)
                      |                                          |
                      v                                          v
+----------------------------------------+   +------------------------------------------+
|          FLASK BACKEND ENGINE          |   |       REAL MONITOR SESSION MANAGER       |
|            (backend/engine)            |   |       (backend/real_process_monitor.py)  |
|                                        |   |                                          |
|  * ProcessManager (Virtual PIDs only)  |   |  * Ephemeral 6-char Pairing Codes        |
|  * Scheduler (fcfs, sjf, priority, rr) |   |  * Bearer Token Authentication           |
|  * Filtered Process Isolation Run      |   |  * Bounded Rolling Buffer (180 snaps)    |
|  * SQLite Mirror / Transaction Log     |   |  * Rate Limiter (max 5 snaps/sec)        |
+----------------------------------------+   +-------------------^----------------------+
                                                                 |
                                                                 | HTTPS / HTTP Telemetry
                                                                 | (Authorization: Bearer)
                                                                 |
                                             +-------------------|----------------------+
                                             |        LOCAL MONITOR AGENT               |
                                             |           (local_monitor/)               |
                                             |                                          |
                                             |  * agent.py: CLI runner & SIGINT handler |
                                             |  * monitor.py: psutil reader (read-only) |
                                             |  * transport.py: token exchange & push   |
                                             |  * Multi-process App Grouping Heuristics |
                                             |  * Compound PID (PID + create_time)      |
                                             +------------------------------------------+
```

---

## 3. Strict Architectural Boundary: Mode A vs. Mode B

To prevent student misconceptions regarding how operating systems work, the implementation enforces a strict division between simulation and empirical telemetry:

| Dimension | Mode A: Virtual Simulator | Mode B: Real Applications Monitor |
| :--- | :--- | :--- |
| **Target Workload** | Synthetically modeled tasks (e.g. Tab Renderer, Audio DSP) | Actual OS processes (Chrome, Spotify, Code, Terminal) |
| **Scheduler Entity** | SysRealm's Python Scheduler (`backend/scheduler.py`) | Host Operating System Kernel (Darwin XNU, CFS, Windows) |
| **Process Queue Storage** | `backend.process_manager.ProcessManager` & SQLite | In-memory `MonitoringSession.snapshots` circular buffer |
| **Database Pollution** | Persisted in `simulation_sessions` and `processes` | **Zero database pollution.** Real processes are never stored |
| **Execution Visualization** | Algorithmic **Gantt Chart** (discrete contiguous slices) | **Observed Real Process Activity Timeline** (sampled ticks) |
| **Control Capabilities** | Play, Pause, Step, Change Quantum, Full Reset | **Read-Only Telemetry.** No kill, no pause, no sudo |
| **Time Model** | Modeled discrete simulation ticks ($t=0, 1, 2\dots$) | Wall-clock UTC/Local time intervals (sampled every 2.0s) |

---

## 4. Mode A Virtual Apps Isolation Bug Fix

### Prior Defect
In the original Virtual Applications Lab, clicking "Schedule Application" on any virtual app card invoked `/api/scheduler/run` without passing process filters. Consequently, the scheduler grabbed all processes in the global queue (including processes from other apps or manually added rows), scheduled them together, and overwrote the UI process queue.

### Resolution & Implementation
1. **Engine Level (`backend/simulation_engine.py`):**
   `run_scheduler(algorithm, quantum, process_ids=None)` now accepts an optional `process_ids` whitelist. When provided:
   ```python
   if process_ids is not None:
       pid_set = {str(x) for x in process_ids}
       processes = [p for p in processes if str(p.get('pid')) in pid_set]
   ```
2. **API Endpoint (`app.py`):**
   `/api/scheduler/run` extracts `process_ids` from JSON payloads and passes it to the engine.
3. **Frontend Controller (`static/js/virtual_apps.js`):**
   - Added `this.selectedApp` tracking and a Scope selector (`#va-sim-scope`).
   - Three selectable scheduling scopes:
     - `selected`: Filters strictly to `${VIRTUAL_PREFIX}${selectedApp.name}`.
     - `all-virtual`: Filters to all processes with prefix `Virtual App · `.
     - `entire-queue`: Passes all processes in the queue.
   - When "Schedule" is clicked on a specific app card, that app becomes `selectedApp`, scope switches to `selected`, and only its processes are scheduled.
   - The full process queue remains intact in the table while the Gantt chart and metrics display only the isolated execution.

---

## 5. Security & Safety Model for Real Telemetry

The local monitoring agent (`local_monitor/`) runs outside the browser sandbox and adheres to strict security standards:

1. **Least Privilege (No `sudo` / No Root):**
   - The agent requires only standard user permissions.
   - It invokes read-only `psutil` calls: `psutil.cpu_percent()`, `psutil.virtual_memory()`, and `psutil.process_iter()`.
   - It contains **zero** code for `kill()`, `terminate()`, `nice()`, or sending POSIX signals.
2. **Ephemeral Outbound Pairing Workflow:**
   - The student generates a 6-character single-use code in SysRealm (`SR-XXXX`).
   - The code is valid for 300 seconds (5 minutes) and tied to the user's session.
   - The agent initiates an *outbound* HTTP/HTTPS request (`POST /api/real-monitor/connect`) to swap the pairing code for an ephemeral bearer token (`sr_mon_<hex>`).
   - No inbound listening ports are opened on the student's laptop.
3. **Immediate Revocation:**
   - Clicking **Stop Monitoring** in the web UI immediately calls `POST /api/real-monitor/stop`, destroying the session and revoking the bearer token on the server.
   - Any further snapshot attempts with that token receive `401 Unauthorized`.
4. **PID Reuse Protection:**
   - Operating systems recycle process IDs once a process terminates.
   - The agent creates a compound unique identifier: `f"{pid}_{int(create_time)}"`.
5. **Bounded Memory Footprint (Circular Buffer):**
   - Telemetry snapshots on the server are stored in a `collections.deque(maxlen=180)`.
   - At a 2.0s sampling interval, this preserves a rolling 6-minute window and prevents memory leakage.
6. **Privacy Protections:**
   - Process command lines are sanitized and truncated to 120 characters to prevent inadvertent leakage of sensitive CLI tokens or file paths.

---

## 6. Real Applications Multi-Process Grouping Heuristics

Modern desktop applications rarely run as a single process. For example, modern web browsers (Chrome, Edge, Brave) and Electron applications (VS Code, Slack, Discord) utilize multi-process architectures to isolate renderer tabs, GPU pipelines, and utility workers.

The agent groups these processes into intuitive application families:

| Application | Process Signatures Detected | Categorization | Icon |
| :--- | :--- | :--- | :--- |
| **Google Chrome** | `google chrome`, `google chrome helper`, `chrome` | Web Browser | 🌐 |
| **Visual Studio Code** | `code`, `code helper`, `electron` | Development | 💻 |
| **Cursor IDE** | `cursor`, `cursor helper` | Development | ⚡ |
| **Antigravity IDE** | `antigravity`, `antigravity helper` | Development | 🚀 |
| **Spotify** | `spotify`, `spotify helper` | Media Player | 🎵 |
| **Terminal / Shells** | `terminal`, `iterm2`, `kitty`, `alacritty`, `zsh`, `bash` | System Utility | ⬛ |
| **Python Runtime** | `python`, `python3`, `agent.py` | Programming | 🐍 |
| **Docker** | `docker`, `dockerd`, `com.docker.backend` | Containerization | 🐳 |

---

## 7. Viva Voce Examination: Questions & Answers

The following questions and answers are designed to assist undergraduate students during their academic project evaluation and defense before university examiners.

---

### Q1. What is the fundamental theoretical difference between Mode A's Gantt chart and Mode B's Observed Activity Timeline?
**Answer:**  
Mode A's Gantt chart represents an **algorithmic model** of scheduling. It assumes deterministic burst times and visualizes how a specific scheduling algorithm (like FCFS or Round Robin) assigns discrete, non-overlapping slices of simulated CPU time to a known queue of processes.

Mode B's Observed Activity Timeline represents **empirical telemetry**. It does not decide which process runs; rather, it periodically samples the host operating system's CPU and memory state at discrete intervals ($t_0, t_1 \dots$). It displays observed CPU percentage utilization across multi-process application groups running on multi-core hardware, reflecting real kernel dispatcher decisions, cache misses, hardware interrupts, and background threads.

---

### Q2. Why is it architecturally critical that real OS processes never enter SysRealm's `ProcessManager`?
**Answer:**  
In operating system design, there is a strict separation between simulated domain models and host hardware state. If real OS processes entered SysRealm's `ProcessManager`:
1. The student could incorrectly assume that selecting "Round Robin" in SysRealm was time-slicing their real Spotify or Chrome instances.
2. The simulation database (`simulation_sessions` and `processes`) would be polluted with hundreds of transient OS processes, destroying the academic reproducibility of simulated experiments.
3. It would violate the principle of least privilege, creating safety risks if simulation controls (like kill or swap) were accidentally directed at host OS tasks.

---

### Q3. How does the local monitor agent handle the problem of OS PID reuse?
**Answer:**  
Most operating systems maintain a maximum PID limit (e.g. 32768 or 99999). When processes terminate and new ones launch, the operating system kernel recycles previously used PIDs. If an agent tracks processes solely by PID, a newly created process could inherit the history, memory metrics, and name of an unrelated dead process.

To prevent this collision, the agent generates a **compound process identifier**:
$$\text{UID} = \text{PID} + \text{"\_"} + \text{int}(\text{create\_time})$$
Because creation timestamps are monotonic and millisecond-accurate, the combination of PID and `create_time` is mathematically unique across the entire uptime of the machine.

---

### Q4. Why is `psutil.cpu_percent(interval=None)` used instead of a blocking interval in the agent?
**Answer:**  
Calling `psutil.cpu_percent(interval=1.0)` blocks the calling thread for a full second while taking two consecutive samples of the CPU counters (`/proc/stat` on Linux or `host_processor_info()` on macOS). In a real-time monitoring loop scanning dozens of individual processes, blocking calls would serialize execution, resulting in high latency, stale metrics, and missed polling deadlines.

Instead, the agent primes `cpu_percent(interval=None)` during initialization. Subsequent non-blocking calls compute CPU percentage by comparing current CPU time counters against the cached counters from the previous tick, allowing the agent to sample hundreds of processes in less than 50 milliseconds.

---

### Q5. Explain how process isolation was achieved for the Virtual Applications Simulator in Mode A.
**Answer:**  
Previously, the CPU scheduler always fetched all processes in the session (`self.process_manager.get_all()`). To achieve process isolation:
1. `backend/simulation_engine.py` was extended so `run_scheduler()` accepts an optional `process_ids` array.
2. The engine filters the candidate list to include only processes whose `pid` is present in the requested array.
3. The frontend `static/js/virtual_apps.js` identifies processes belonging to the selected app via the naming convention `Virtual App · <AppName> · <TaskName>`.
4. When "Schedule App" is triggered, only that app's PIDs are transmitted to the backend. The rest of the queue remains safely stored in `ProcessManager` without participating in that simulation run.

---

### Q6. How is the pairing workflow between the local agent and the Flask server secured without exposing local ports?
**Answer:**  
The agent utilizes an **outbound-only polling architecture**:
1. When the student clicks "Pair Local Agent", Flask generates an ephemeral, cryptographically random 6-character pairing code with a 5-minute TTL.
2. The student runs `python3 local_monitor/agent.py --pair <CODE>`.
3. The agent initiates an outbound HTTP POST request to `/api/real-monitor/connect`, providing the code and machine metadata.
4. The server validates the code, marks it consumed (single-use), and responds with a bearer token (`sr_mon_<hex>`).
5. Subsequent telemetry packets include `Authorization: Bearer <TOKEN>`.
6. Because the agent initiates all network connections outbound to the server, no incoming ports need to be opened on the student's firewall or router.

---

### Q7. How does the server prevent memory exhaustion from continuous telemetry snapshots?
**Answer:**  
Telemetry streams can run indefinitely. If every incoming snapshot were appended to an unbounded list, server memory would grow linearly, eventually triggering an Out-Of-Memory (OOM) crash.

To prevent this, the server stores snapshots in a `collections.deque(maxlen=180)`. A deque with a fixed `maxlen` acts as a **circular ring buffer**: when the 181st snapshot arrives, Python automatically discards the oldest entry from the head of the deque in $O(1)$ time. At a 2-second sampling rate, exactly 360 seconds (6 minutes) of high-resolution rolling history are retained with bounded, predictable memory consumption.

---

### Q8. What happens when an operating system process terminates while the agent is reading its metrics?
**Answer:**  
Between the moment `psutil.process_iter()` enumerates a running process and the moment the agent queries its CPU or memory usage, the process may terminate or transition into a zombie state.

The agent handles this by wrapping process attribute lookups in a multi-exception guard:
```python
try:
    info = p.info
    # read metrics...
except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
    continue
```
If the process has died, `NoSuchProcess` is caught, and the agent quietly continues to the next process without throwing an unhandled exception or terminating the agent.

---

### Q9. Why do modern operating systems categorize memory into RSS (Resident Set Size) and Virtual Memory Size (VMS)?
**Answer:**  
- **VMS (Virtual Memory Size):** The total address space mapped by a process, including shared libraries, memory-mapped files, and allocated address spaces that have not yet been backed by physical RAM frames.
- **RSS (Resident Set Size):** The portion of the process's memory that currently resides in physical hardware RAM frames.
The SysRealm Real Applications Monitor displays RSS because RSS represents the actual physical RAM consumption impacting system memory pressure.

---

### Q10. What scheduling policies do modern operating systems use in contrast to SysRealm's academic algorithms?
**Answer:**  
SysRealm simulates classical academic algorithms:
- **FCFS:** Non-preemptive, earliest arrival.
- **SJF:** Shortest burst first (requires theoretical prior knowledge of burst times).
- **Priority:** Fixed priority dispatching.
- **Round Robin:** Equal fixed time quantum.

Real operating systems do not know future CPU bursts in advance and cannot use pure SJF. Instead, they use **multi-level feedback queues and dynamic weighted fairness**:
- **macOS (Darwin XNU):** Mach-based multi-core scheduler with QoS (Quality of Service) classes (User Interactive, User Initiated, Default, Utility, Background) and priority decay.
- **Linux:** Completely Fair Scheduler (CFS) and Earliest Eligible Virtual Deadline First (EEVDF), which use red-black trees to track virtual runtime (`vruntime`) and ensure proportion-based CPU time allocation.
- **Windows:** Multilevel feedback queue with 32 priority levels, dynamic priority boosting for foreground focus and I/O completion, and thread quantum stretching.

---

## 8. Verification & Test Suite Summary

The Real Applications Monitoring module and process isolation fixes were validated using automated unit and integration tests:

| Test Suite | File | Tests | Coverage |
| :--- | :--- | :---: | :--- |
| **Real Monitor Unit Tests** | `tests/test_real_process_monitor.py` | 6 | Pairing code generation, single-use token exchange, token revocation, rate limiting, circular buffer boundedness (180 entries), app classification, timeline activity bands |
| **Monitor API Integration Tests** | `tests/test_monitor_api.py` | 2 | REST endpoints (`/api/real-monitor/*`), login validation, bearer token authentication, telemetry streaming, status reporting, process filtering, stop revocation |
| **Process Isolation Tests** | `tests/test_process_isolation.py` | 2 | Mode A selected app scheduling isolation, queue preservation, Mode B non-interference with `ProcessManager` |
| **DBMS & Query Optimizer Tests** | `tests/test_query_optimizer.py` | 32 | SQL rewriting, relational algebra, EXPLAIN plan analysis, semantic preservation |
| **Core OS & Scheduling Tests** | `tests/test_sysrealm.py` | 41 | CPU scheduling algorithms, Gantt generation, memory paging, deadlocks, disk scheduling |
| **Total Automated Tests** | **All suites** | **83** | **100% Passing (0.28s)** |

---

## 9. Conclusion

The addition of the **Real Applications Monitoring Module** and the **Observed Real Process Activity Timeline** transforms SysRealm from a purely theoretical textbook simulation into a comprehensive operating systems laboratory workbench. Students can directly observe how theoretical CPU scheduling concepts contrast with empirical operating system telemetry, reinforcing fundamental computer science principles while maintaining strict software architecture standards.
