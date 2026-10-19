# SysRealm: Virtual Apps Scheduling Assignment System

**Project Title:** SysRealm: Kernel Panic — An Interactive Operating System Simulator  
**Academic Level:** Third-Year B.Tech Computer Science & Engineering  
**Subject Area:** Operating Systems (CS301 / CS302) & Database Management Systems (CS304)  
**Module:** Virtual Apps Lab — Teacher-Published Scheduling Challenges & Automated Evaluation  

---

## 1. Executive Summary & Problem Statement

In undergraduate Computer Science Operating Systems curricula, CPU scheduling algorithms—such as First-Come First-Served (**FCFS**), Shortest Job First (**SJF**), Priority Scheduling, and Round Robin (**RR**)—are typically evaluated using static textbook problems. Students manually calculate waiting and turnaround times on paper for small sets of 3–5 processes.

While manual calculation reinforces basic arithmetic, it fails to provide students with intuition regarding:
1. How scheduling algorithms perform against heterogeneous, multi-process interactive workloads (e.g., browser tabs, audio DSP pipelines, background downloads).
2. How algorithm optimality dynamically shifts depending on the chosen system objective (e.g., minimizing Average Waiting Time vs. minimizing Average Turnaround Time vs. minimizing Response Time for interactive threads).
3. How real automated grading systems verify scheduling metrics objectively without human grading bottlenecks or cheating vectors.

The **SysRealm Virtual Apps Scheduling Assignment System** addresses these needs by integrating a teacher-guided challenge framework directly into the existing **Virtual Apps Lab (Mode A)**:
- **Teacher Workflow:** Instructors can publish custom or preset scheduling challenges directly from the Teacher Dashboard. A challenge defines an immutable workload of virtual application processes, a restricted subset of permissible algorithms, an optimization objective, and a designated XP reward.
- **Student Workflow:** Students discover the challenge in their **Quest Log**, open a dedicated **Assignment Workspace** inside the Virtual Apps Lab, run simulations in an isolated execution sandbox, benchmark performance metrics against the stated objective, inspect interactive Gantt charts, and submit their chosen algorithm with written rationale.
- **Automated Verification Engine:** The backend independently re-evaluates all allowed algorithms against the workload, determines true mathematical optimality (including handling mathematical ties within $\epsilon \le 0.05$ ms tolerance), awards XP idempotently via a dedicated audit ledger, and delivers actionable diagnostic feedback upon suboptimal attempts.
- **Teacher Gradebook:** Instructors view real-time student submissions via an SQL `LEFT OUTER JOIN` query, showing algorithm choices, achieved objective metrics, attempt counts, and timestamps.

---

## 2. System Architecture & Component Mapping

```
+-------------------------------------------------------------------------------------------------------+
|                                           SYSREALM FRONTEND                                           |
|                                                                                                       |
|  +-------------------------------------+   +-------------------------------------------------------+  |
|  |          TEACHER DASHBOARD          |   |                    STUDENT DASHBOARD                  |  |
|  |                                     |   |                                                       |  |
|  |  * Challenge Publishing Modal       |   |  * Quest Log Assignment Card (Virtual Apps Badge)     |  |
|  |  * Workload Builder (PIDs, Bursts)  |   |  * "Solve Scheduling Challenge" Action Button         |  |
|  |  * Preset Workload Auto-Fill        |   |                                                       |  |
|  |  * Objective & Quantum Selectors    |   |  +-------------------------------------------------+  |  |
|  |  * Live Gradebook (LEFT JOIN Table) |   |  |        VIRTUAL APPS ASSIGNMENT WORKSPACE        |  |  |
|  +------------------^------------------+   |  |                                                 |  |  |
|                     |                      |  |  * Immutable Assigned Workload Table            |  |  |
|                     |                      |  |  * Isolated Algorithm Runner (No side effects)  |  |  |
|                     |                      |  |  * Dedicated Gantt Chart Canvas & Metric Cards  |  |  |
|                     |                      |  |  * Multi-Algorithm Comparison Matrix            |  |  |
|                     |                      |  |  * Submission Form (Algo + Rationale)           |  |  |
|                     |                      |  |  * Real-Time Diagnostic Feedback Banner         |  |  |
|                     |                      |  +-------------------------------------------------+  |  |
|                     |                      +---------------------------^---------------------------+  |
+---------------------|--------------------------------------------------|------------------------------+
                      |                                                  |
                      | POST /api/teacher/assignments                    | POST /api/assignments/<id>/virtual-apps/run
                      | GET  /api/assignments                            | POST /api/assignments/<id>/virtual-apps/submit
                      v                                                  v
+-------------------------------------------------------------------------------------------------------+
|                                         FLASK BACKEND ENGINE                                          |
|                                                                                                       |
|  +-------------------------------------+   +-------------------------------------------------------+  |
|  |          ASSIGNMENT CONTROLLER      |   |            ISOLATED SCHEDULER ENGINE                  |  |
|  |                (app.py)             |   |          (backend/isolated_scheduler.py)              |  |
|  |                                     |   |                                                       |  |
|  |  * Workload Schema Validator        |   |  * Pure In-Memory Workload Deep Copy                  |  |
|  |  * Completion Bypass Blocker        |   |  * Zero Mutation to SimulationEngine / ProcessManager |  |
|  |  * Role & Permission Verification   |   |  * Dispatcher: FCFS, SJF, Priority, Round Robin       |  |
|  |  * Idempotent XP Ledger Manager     |   |  * Metric Computations: AWT, ATAT, ART, Gantt Chart   |  |
|  |  * Diagnostic Feedback Generator    |   |  * Objective Evaluator (Minimization with Ties <=0.05)|  |
|  +------------------^------------------+   +---------------------------^---------------------------+  |
+---------------------|--------------------------------------------------|------------------------------+
                      |                                                  |
                      +------------------+             +-----------------+
                                         |             |
                                         v             v
+-------------------------------------------------------------------------------------------------------+
|                                    RELATIONAL DATABASE LAYER                                          |
|                                    (MySQL / SQLite Dual Mirror)                                       |
|                                                                                                       |
|  * lab_assignments: workload_json, allowed_algorithms_json, optimization_objective, round_robin_quantum|
|  * assignment_submissions: selected_algo, submitted_quantum, objective_value, scheduling_metrics...     |
|  * student_xp_awards: UNIQUE(assignment_id, student_email) atomic ledger preventing duplicate points  |
|  * Dynamic Schema Migration Engine: Automatic column & table bootstrap on application startup        |
+-------------------------------------------------------------------------------------------------------+
```

---

## 3. Database Architecture & Schema Migrations

The assignment system integrates into SysRealm's relational database layer, maintaining strict parity between production MySQL environments and the local SQLite developer mirror.

### 3.1 Schema Modifications: `lab_assignments` Table
To store teacher-published challenge configurations, the `lab_assignments` table was extended with four new attributes:

```sql
ALTER TABLE lab_assignments
    ADD COLUMN workload_json TEXT NULL,
    ADD COLUMN allowed_algorithms_json TEXT NULL,
    ADD COLUMN optimization_objective VARCHAR(64) DEFAULT 'min_avg_waiting_time',
    ADD COLUMN round_robin_quantum INT DEFAULT 2;
```

- `target_panel`: Set to `'virtual_apps'` for scheduling challenges, allowing the UI and API router to distinguish them from standard terminal or memory labs.
- `workload_json`: Serialized JSON array of process objects (`pid`, `name`, `app_name`, `arrival_time`, `burst_time`, `priority`, `memory_mb`).
- `allowed_algorithms_json`: Serialized JSON array of permitted algorithm identifiers (e.g. `["FCFS", "SJF", "RoundRobin"]`).
- `optimization_objective`: The target metric to minimize (`min_avg_waiting_time`, `min_avg_turnaround_time`, or `min_avg_response_time`).
- `round_robin_quantum`: Integer time slice ($q \ge 1$) applied when Round Robin is tested or evaluated.

### 3.2 Schema Modifications: `assignment_submissions` Table
To record student solutions and verification results, `assignment_submissions` was extended:

```sql
ALTER TABLE assignment_submissions
    ADD COLUMN selected_algo VARCHAR(64) NULL,
    ADD COLUMN submitted_quantum INT NULL,
    ADD COLUMN objective_value FLOAT NULL,
    ADD COLUMN scheduling_metrics TEXT NULL,
    ADD COLUMN gantt_json TEXT NULL,
    ADD COLUMN attempts_count INT DEFAULT 1;
```

- `selected_algo`: The algorithm the student claimed is optimal.
- `submitted_quantum`: The Round Robin quantum active during the submission.
- `objective_value`: The verified numeric value achieved by the chosen algorithm on the workload (e.g. $4.80$ ms).
- `scheduling_metrics`: Serialized JSON object storing complete verified metrics (`avg_waiting_time`, `avg_turnaround_time`, `avg_response_time`, `cpu_utilization`, `throughput`).
- `gantt_json`: Serialized JSON representation of the resulting Gantt chart slices.
- `attempts_count`: Running counter tracking how many submissions the student made before achieving optimality.

### 3.3 New Table: `student_xp_awards` (Atomic XP Ledger)
To enforce strict idempotency and prevent students from repeatedly claiming points by re-submitting an already-solved challenge, a dedicated ledger table was created:

```sql
CREATE TABLE IF NOT EXISTS student_xp_awards (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_email VARCHAR(255) NOT NULL,
    student_name VARCHAR(255) NOT NULL,
    assignment_id INT NOT NULL,
    points_awarded INT NOT NULL,
    award_reason VARCHAR(255) NOT NULL,
    awarded_at DATETIME NOT NULL,
    UNIQUE KEY uq_student_asgn_xp (assignment_id, student_email)
);
```
*(In SQLite mirror, `id INTEGER PRIMARY KEY AUTOINCREMENT` and `UNIQUE(assignment_id, student_email)` are utilized).*

**Security Invariant:** The database-level unique constraint `UNIQUE(assignment_id, student_email)` guarantees that no race condition or repeated API request can insert multiple XP credit records for the same student on a given assignment.

### 3.4 Dynamic Runtime Migration Strategy
On application bootstrap (`_init_db` for MySQL and `_init_sqlite_schema` for SQLite), SysRealm queries column metadata via `PRAGMA table_info` (SQLite) or `information_schema.COLUMNS` (MySQL). Any missing columns are added idempotently using `ALTER TABLE ADD COLUMN`, ensuring zero manual database setup is required when deploying code updates.

---

## 4. Isolated Execution Engine (`backend/isolated_scheduler.py`)

### 4.1 The Process Queue Mutation Problem
In SysRealm, the global `SimulationEngine` maintains an active `ProcessManager` instance associated with each user session (`_user_engines[session_id]`). In standard simulation mode, running an algorithm modifies process states (`READY -> RUNNING -> TERMINATED`), mutates process start and completion times, and alters user score and history.

If an assignment simulation were executed inside this global engine:
1. The student's active sandbox processes would be wiped or overwritten.
2. The assignment workload would pollute global session analytics.
3. Intermediate test runs would award false XP or corrupt game state.

### 4.2 Pure Functional Isolation Architecture
To prevent state leakage, `backend/isolated_scheduler.py` implements a pure execution pipeline:

```
[Teacher Workload JSON]
          │
          ▼
validate_workload() ────────► Validates: 1 <= N <= 20, Unique PIDs,
          │                               Burst >= 1, Priority 1..10
          ▼
copy.deepcopy() ────────────► Creates ephemeral dictionary copies
          │
          ▼
scheduler.<algo>() ─────────► Pure algorithmic dispatch (FCFS, SJF, Priority, RR)
          │
          ▼
compute_metrics() ──────────► Pure mathematical reduction (AWT, ATAT, ART, CPU Util)
          │
          ▼
{ metrics, gantt_chart } ───► Returned directly to caller
```

**Key Isolation Invariants:**
- `engine.process_manager` is **never touched**.
- `engine.score` is **never mutated during test runs**.
- The assigned workload is treated as **read-only and immutable**.
- The student can experiment with different algorithms repeatedly without affecting any background processes.

---

## 5. Mathematical Evaluation & Objective Functions

### 5.1 Objective Formulations
SysRealm supports three distinct academic optimization objectives:

#### 1. Minimum Average Waiting Time (`min_avg_waiting_time`)
Waiting time ($W_i$) is the total time process $P_i$ spends waiting in the ready queue before completing execution:
$$W_i = \text{TAT}_i - \text{BT}_i$$
$$\text{AWT} = \frac{1}{n} \sum_{i=1}^{n} W_i$$
*Theoretical Principle:* In non-preemptive scenarios without dynamic arrivals, **Shortest Job First (SJF)** is provably optimal for minimizing Average Waiting Time. When arrival times are non-zero, preemptive SJF (SRTF) or Round Robin with small quanta often compete.

#### 2. Minimum Average Turnaround Time (`min_avg_turnaround_time`)
Turnaround time ($\text{TAT}_i$) is the total elapsed time from process arrival to process completion:
$$\text{TAT}_i = C_i - A_i$$
$$\overline{\text{TAT}} = \frac{1}{n} \sum_{i=1}^{n} \text{TAT}_i$$
where $C_i$ is completion time and $A_i$ is arrival time.

#### 3. Minimum Average Response Time (`min_avg_response_time`)
Response time ($R_i$) is the duration from process submission (arrival) to the first moment it is allocated CPU time:
$$R_i = S_i - A_i$$
$$\text{ART} = \frac{1}{n} \sum_{i=1}^{n} R_i$$
where $S_i$ is the time slice of first dispatch.  
*Theoretical Principle:* **Round Robin** typically minimizes response time for time-sharing systems, providing early feedback to interactive processes.

### 5.2 Mathematical Tie-Handling Tolerance
In discrete scheduling problems with specific workload attributes, two different algorithms can occasionally achieve identical or near-identical metric values (for example, FCFS and SJF when processes arrive in order of increasing burst times).

To ensure academic fairness and prevent floating-point discrepancies, SysRealm evaluates tie candidates using an epsilon threshold:

$$\text{Candidate } A \text{ is optimal if } |V_A - V_{\min}| \le 0.05 \text{ ms}$$

If both `SJF` ($4.80$ ms) and `Priority` ($4.80$ ms) achieve the minimum average waiting time, both are included in `best_algorithms`:
```python
best_algorithms = [
    algo for algo, res in results.items()
    if abs(res['objective_value'] - min_val) <= 0.05
]
```
A student selecting *either* algorithm will be evaluated as correct and awarded full credit.

---

## 6. Security, Anti-Cheating & Idempotency Architecture

### 6.1 Generic Completion Bypass Protection
In legacy or generic assignments, client code could complete tasks by calling `POST /api/assignments/<id>/complete`.  
For Virtual Apps Scheduling Challenges, this generic bypass is strictly blocked:

```python
# In app.py: complete_assignment()
if asgn.get('target_panel') == 'virtual_apps':
    return err(
        'Virtual Apps Scheduling Challenges cannot be marked complete generically. '
        'You must run and submit your solution via the Virtual Apps Lab.',
        400
    )
```
Students cannot spoof completion without passing algorithmic evaluation.

### 6.2 Independent Server-Side Re-Evaluation
The client never submits computed metrics or claim validations to the server. The student submits only:
```json
{
  "selected_algo": "SJF",
  "student_explanation": "Shortest burst scheduled first reduces waiting time."
}
```
The Flask backend loads the immutable assignment workload from the database, executes the simulation independently in Python, and computes the mathematical ground truth. A client tampering with JavaScript variables or Gantt chart canvases cannot falsify the grading decision.

### 6.3 Double-Reward Prevention via Atomic Ledger
When a student submits an optimal solution:
1. The server checks `student_xp_awards` for `(assignment_id, student_email)`.
2. If no record exists, the server inserts a record and increments the student's active engine score by the designated points:
   ```python
   new_score = engine.update_score(points, f"Solved Virtual Apps Challenge #{assignment_id}")
   ```
3. If a record already exists (e.g. student is resubmitting or verifying another algorithm), `xp_awarded` is explicitly returned as `0`, and `engine.update_score()` is bypassed:
   ```python
   xp_awarded = 0
   new_score = engine.score
   ```
4. The submission in `assignment_submissions` is updated with `ON DUPLICATE KEY UPDATE` / `ON CONFLICT DO UPDATE`, preserving the latest timestamp, verified metrics, and incrementing `attempts_count`.

---

## 7. REST API Endpoints

| Method | Endpoint | Access | Purpose |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/teacher/virtual-apps/example-workload` | Teacher | Returns standard 5-process workload preset for rapid challenge publishing. |
| `POST` | `/api/teacher/assignments` | Teacher | Creates new assignment. Validates workload JSON, allowed algorithms, and objective. |
| `GET` | `/api/assignments/<id>/virtual-apps` | Student/Teacher | Retrieves assignment details, parsed workload, allowed algorithms, objective, and previous student submission state. |
| `POST` | `/api/assignments/<id>/virtual-apps/run` | Student | Runs isolated simulation for an allowed algorithm on the immutable workload. Returns Gantt chart and metrics. |
| `POST` | `/api/assignments/<id>/virtual-apps/submit` | Student | Verifies student's selected algorithm against backend ground truth. Awards XP idempotently. Returns detailed diagnostic feedback. |
| `GET` | `/api/assignments` | Student/Teacher | Student retrieves active Quest Log; Teacher retrieves Gradebook with SQL `LEFT OUTER JOIN` submission rows. |

---

## 8. Frontend User Experience Workflow

```
   TEACHER PUBLISHES
   ┌────────────────────────────────────────┐
   │ 1. Open Publish Modal in Dashboard     │
   │ 2. Select "Virtual Apps Challenge"     │
   │ 3. Choose Objective (e.g. Min AWT)     │
   │ 4. Click "Load Example Workload"       │
   │ 5. Click "Publish Assignment"          │
   └───────────────────┬────────────────────┘
                       │
                       ▼
   STUDENT DISCOVERS & OPENS
   ┌────────────────────────────────────────┐
   │ 1. Quest Log displays Challenge Card   │
   │ 2. Click "Solve Scheduling Challenge"  │
   │ 3. Navigates to Virtual Apps Panel     │
   │ 4. Dedicated Workspace unfolds         │
   └───────────────────┬────────────────────┘
                       │
                       ▼
   STUDENT EXPERIMENTS IN ISOLATION
   ┌────────────────────────────────────────┐
   │ 1. Review Immutable Workload Table     │
   │ 2. Select Algorithm (FCFS, SJF, RR...) │
   │ 3. Click "Run Isolated Simulation"     │
   │ 4. Inspect Live Gantt Chart & Metrics  │
   │ 5. Review Benchmark Comparison Matrix  │
   └───────────────────┬────────────────────┘
                       │
                       ▼
   SUBMISSION & AUTOMATED GRADING
   ┌────────────────────────────────────────┐
   │ 1. Select Best Algorithm & Enter Rationale
   │ 2. Click "Submit Final Solution"       │
   │ 3. Optimal? ──► Award +XP & Green Banner
   │    Suboptimal? ──► Diagnostic Feedback  │
   │                   & Unlimited Retries  │
   └────────────────────────────────────────┘
```

---

## 9. Comprehensive Viva Voce Questions & Answers

The following ten questions represent the most rigorous theoretical and practical questions an external university examiner or project evaluator will ask during a third-year B.Tech CSE project defense.

---

### Q1. Why is Shortest Job First (SJF) provably optimal for minimizing Average Waiting Time, and what is its major real-world limitation?
**Answer:**  
**Mathematical Proof Sketch:**  
Let $n$ processes be scheduled non-preemptively with burst times $t_1, t_2, \dots, t_n$.  
Under any schedule, the total waiting time is:
$$\text{Total Waiting Time} = \sum_{i=1}^{n} (n - i) \cdot t_{(i)}$$
where $t_{(i)}$ is the burst time of the process executed in position $i$.  
To minimize this sum of products, by the **Rearrangement Inequality**, the largest multiplier $(n-1)$ must be paired with the smallest burst time $t_{(1)}$, the second largest multiplier $(n-2)$ with the second smallest burst time $t_{(2)}$, and so on. Thus, sorting processes in non-decreasing order of burst times ($t_{(1)} \le t_{(2)} \le \dots \le t_{(n)}$) minimizes total waiting time, and consequently minimizes Average Waiting Time ($\text{AWT}$).

**Real-World Limitation:**  
SJF requires prior knowledge of the exact length of the next CPU burst before the process executes. In real general-purpose operating systems, this value is unknown in advance. Operating systems can at best approximate burst times using exponential smoothing averages:
$$\tau_{n+1} = \alpha t_n + (1 - \alpha) \tau_n \quad (0 \le \alpha \le 1)$$
Furthermore, SJF suffers from **process starvation**: a continuous stream of short processes will indefinitely starve longer jobs of CPU time.

---

### Q2. How does SysRealm guarantee process isolation so that assignment runs do not corrupt a student's active session?
**Answer:**  
SysRealm implements an **Isolated Scheduler Engine** (`backend/isolated_scheduler.py`) that decouples assignment execution from the global session state:
1. **No Shared References:** The assigned workload stored in the database is fetched and deserialized into an immutable list of process dictionaries.
2. **Deep Copying:** Prior to algorithm invocation, `copy.deepcopy()` duplicates all process structures.
3. **Direct Algorithmic Invocation:** Rather than delegating execution to `engine.process_manager` (which holds the student's active sandbox processes), the isolated scheduler invokes the pure algorithmic dispatchers (`fcfs`, `sjf`, `priority_scheduling`, `round_robin` in `backend/scheduler.py`) directly on the duplicate process list.
4. **Zero Side Effects:** The student's active ready queue, running processes, memory allocations, and session scores remain completely untouched.

---

### Q3. Explain the convoy effect in FCFS scheduling. Under what workload characteristics does it manifest?
**Answer:**  
The **convoy effect** occurs in non-preemptive First-Come First-Served scheduling when a CPU-bound process with a very large burst time arrives immediately before multiple short, I/O-bound processes.

**Workload Scenario:**
- Process $P_1$ (CPU-bound): Burst time $= 50$ ms.
- Processes $P_2, P_3, P_4$ (I/O-bound): Burst time $= 2$ ms each.
- Arrival times: $A_1 = 0, A_2 = 0, A_3 = 0, A_4 = 0$.

Under FCFS, $P_1$ holds the CPU for 50 ms. $P_2, P_3,$ and $P_4$ sit idle in the ready queue despite needing only 2 ms to complete and initiate their next I/O operations. This results in:
1. Extremely high Average Waiting Time:
   $$\text{AWT} = \frac{0 + 50 + 52 + 54}{4} = \frac{156}{4} = 39.0 \text{ ms}$$
2. Severe resource underutilization: I/O devices remain idle while processes wait for $P_1$, and CPU utilization drops when $P_1$ finally releases the CPU and all short processes perform I/O simultaneously.
In contrast, SJF schedules $P_2, P_3, P_4$ first ($2 + 2 + 2 = 6$ ms), reducing AWT to:
$$\text{AWT} = \frac{0 + 2 + 4 + 6}{4} = 3.0 \text{ ms}$$
an order-of-magnitude performance improvement.

---

### Q4. How does the assignment evaluation engine handle mathematical ties when two algorithms yield the same objective metric?
**Answer:**  
In scheduling theory, different algorithms can yield mathematically identical metrics under specific workloads. For example, if all processes have identical burst times, FCFS and SJF produce identical schedules. Similarly, if priorities match burst order, Priority Scheduling and SJF produce identical metrics.

To prevent false negatives during grading, SysRealm uses an **$\epsilon$-tolerance threshold**:
$$\epsilon = 0.05 \text{ ms}$$
1. The engine simulates all permitted algorithms on the workload and records each algorithm's achieved objective value $V_a$.
2. It identifies the absolute minimum value across all runs:
   $$V_{\min} = \min_{a \in \mathcal{A}} V_a$$
3. It identifies all algorithms satisfying $|V_a - V_{\min}| \le \epsilon$:
   $$\mathcal{A}_{\text{optimal}} = \{ a \in \mathcal{A} \mid |V_a - V_{\min}| \le 0.05 \}$$
4. If the student selects any algorithm $a^* \in \mathcal{A}_{\text{optimal}}$, the submission is marked correct, regardless of which candidate was first in the evaluation array.

---

### Q5. How does Round Robin quantum selection impact the tradeoff between turnaround time and response time?
**Answer:**  
In Round Robin scheduling, the time quantum ($q$) governs the preemption frequency:
- **Extreme Case $q \to \infty$:** The algorithm degenerates into non-preemptive **FCFS**. Context switching overhead drops to zero, but response time degrades severely for short jobs arriving behind long jobs.
- **Extreme Case $q \to 0$:** The system approaches **Processor Sharing** (pure theoretical time-sharing), where $n$ processes appear to run concurrently at $\frac{1}{n}$-th of the CPU speed. Response time approaches its theoretical optimum (every process receives CPU time almost immediately).
- **Practical Tradeoff:** If $q$ is smaller than the typical process burst time, context switching overhead dominates CPU execution time. A rule of thumb in operating system design is that **80% of CPU bursts should be shorter than the time quantum $q$**. This ensures interactive jobs complete in a single time slice while minimizing context-switch overhead for longer jobs.

---

### Q6. Why is a dedicated ledger table (`student_xp_awards`) necessary instead of simply reading the student's current score?
**Answer:**  
Relying solely on `engine.score` or `assignment_submissions` to govern rewards introduces two severe architectural vulnerabilities:
1. **Score Inconsistency & Decay:** A student's score in the `SimulationEngine` represents active session state. If the session expires or if points are spent on unlocking sandbox features, checking `score >= points` does not indicate whether a specific challenge was previously rewarded.
2. **Race Conditions & Double-Claim Exploits:** In multi-threaded or distributed web applications, a student opening multiple browser tabs or issuing concurrent POST requests could submit the same solution simultaneously. Without a database-level constraint, both requests could see `is_solved == False` and credit points twice.

SysRealm resolves this using the **Accounting Ledger Pattern**:
- The `student_xp_awards` table maintains an immutable record of every point grant.
- A composite unique constraint `UNIQUE(assignment_id, student_email)` is enforced directly by the database engine (MySQL InnoDB / SQLite B-tree).
- Any duplicate insertion attempt raises an integrity violation (`IntegrityError`), guaranteeing atomicity and strict idempotency at the database engine level.

---

### Q7. How does the Teacher Gradebook query reflect student assignment statuses when some students have not yet submitted?
**Answer:**  
The Gradebook uses a relational **`LEFT OUTER JOIN`** between `lab_assignments` and `assignment_submissions`:

```sql
SELECT 
    la.id AS assignment_id,
    la.title,
    la.target_panel,
    la.optimization_objective,
    la.points,
    sub.student_email,
    sub.student_name,
    sub.status,
    sub.selected_algo,
    sub.objective_value,
    sub.attempts_count,
    sub.completed_at
FROM lab_assignments la
LEFT OUTER JOIN assignment_submissions sub
    ON la.id = sub.assignment_id
ORDER BY la.id DESC, sub.completed_at DESC;
```

**Relational Algebra Justification:**
If an inner join (`INNER JOIN`) were used, assignments that no student had attempted yet would be completely excluded from the result set ($R \bowtie S$).  
A `LEFT OUTER JOIN` ($R \rtimes S$) ensures that all published assignment rows in `lab_assignments` ($R$) are preserved in the result. If a student has submitted, their corresponding submission columns (`selected_algo`, `objective_value`, `attempts_count`) are populated; if no submission exists, those attributes evaluate to `NULL`, allowing the Teacher UI to display "Pending Submissions" accurately.

---

### Q8. Why must `round_robin_quantum` be specified by the instructor rather than left to the student during an assignment?
**Answer:**  
In Round Robin scheduling, the objective metric (whether AWT, ATAT, or ART) is a direct mathematical function of the time quantum $q$:
$$\text{Metrics} = f(\text{Workload}, \text{Algorithm}, q)$$
If the quantum were left configurable by the student:
1. The student could manipulate $q$ to artificially force Round Robin to outperform SJF or FCFS on that specific metric.
2. Comparing algorithms would no longer occur on a level playing field because the experimental parameter space would be unconstrained.
By having the instructor fix $q$ (e.g., $q = 2$ ms) at publication time, $q$ becomes part of the fixed environment specification. All algorithms are benchmarked against the identical, immutable workload and configuration parameters.

---

### Q9. What is the difference between Preemptive and Non-Preemptive scheduling, and which algorithms in SysRealm belong to each category?
**Answer:**  
- **Non-Preemptive Scheduling:** Once a process transitions to the `RUNNING` state, it holds the CPU until it terminates or voluntarily transitions to the `WAITING` state (e.g. for I/O). The scheduler cannot forcibly interrupt it.
  - *SysRealm Algorithms:* Standard **FCFS**, Non-Preemptive **SJF**, Non-Preemptive **Priority**.
- **Preemptive Scheduling:** The operating system kernel can interrupt a currently executing process using hardware timer interrupts when a higher-priority process arrives or when its allocated time slice expires.
  - *SysRealm Algorithms:* **Round Robin** (preempts on quantum expiration), Preemptive Priority, Shortest Remaining Time First (**SRTF**).

Preemption improves responsiveness in interactive and real-time operating systems, but introduces additional overhead due to **context switching** (saving program counters, registers, and memory maps into the Process Control Block) and cache invalidation.

---

### Q10. What is Priority Inversion, and how do modern operating systems mitigate it?
**Answer:**  
**Priority Inversion** is an operating system anomaly where a high-priority process is indirectly preempted or delayed by a lower-priority process, inverting their intended scheduling priorities.

**Scenario:**
1. A low-priority process $L$ acquires a shared lock/mutex.
2. A high-priority process $H$ arrives and attempts to acquire the lock held by $L$. $H$ blocks.
3. A medium-priority process $M$ arrives. $M$ does not need the lock, but its priority is higher than $L$.
4. The scheduler dispatches $M$, preempting $L$.
5. Because $L$ cannot run to release the lock, $H$ remains blocked while $M$ executes, even though $H$ has higher priority than $M$.

**Mitigation Mechanisms:**
- **Priority Inheritance Protocol (PIP):** When high-priority process $H$ blocks waiting for a resource held by $L$, $L$ temporarily inherits $H$'s high priority. This prevents medium-priority processes ($M$) from preempting $L$. Once $L$ releases the resource, its priority drops back to normal.
- **Priority Ceiling Protocol (PCP):** Each shared resource is assigned a priority ceiling equal to the highest priority of any task that may access it. A task can acquire a resource only if its priority is strictly higher than the priority ceilings of all currently locked resources.

---

## 10. Automated Test Suite Verification

The implementation of the Virtual Apps Assignment System was validated with comprehensive unit, functional, integration, and security tests.

```bash
$ python3 -m unittest discover tests
.............................................................................................
----------------------------------------------------------------------
Ran 93 tests in 0.342s

OK
```

### Test Suite Breakdown

| Test File | Test Count | Key Features Verified |
| :--- | :---: | :--- |
| `tests/test_virtual_apps_assignments.py` | 10 | Workload validation (1–20 procs, positive bursts), pure isolated simulation without global mutation, objective minimization (AWT, ATAT, ART), tie tolerance ($\le 0.05$ ms), teacher publishing API, generic bypass rejection (HTTP 400), isolated student runs, optimal submission with atomic XP award, idempotency on retry, diagnostic feedback on suboptimal submissions, and gradebook LEFT JOIN inspection. |
| `tests/test_real_process_monitor.py` | 6 | Real OS process monitor agent pairing, token lifecycle, rate limiting, and bounded circular buffer. |
| `tests/test_monitor_api.py` | 2 | Real process monitor REST API endpoints, security authentication, and process filtering. |
| `tests/test_process_isolation.py` | 2 | Mode A virtual application isolation and queue non-interference. |
| `tests/test_query_optimizer.py` | 32 | Relational algebra trees, SQL rewrite rules, subquery unnesting, EXPLAIN plan parsing, and semantic validation. |
| `tests/test_sysrealm.py` | 41 | Core CPU scheduling algorithms (FCFS, SJF, Priority, RR), Gantt chart generation, memory management, deadlock bank algorithm, and disk scheduling. |
| **Total Test Suite** | **93** | **100% Pass Rate across all modules (0.342s execution time)** |

---

## 11. Conclusion

The **Virtual Apps Scheduling Assignment System** successfully bridges the gap between theoretical operating system principles and empirical software engineering. By combining:
- Immutable teacher-defined workloads,
- Isolated execution sandboxes,
- Objective mathematical evaluation with tie resolution,
- Multi-algorithm interactive comparison matrices,
- Double-reward protection via atomic SQL ledgers, and
- Live teacher gradebook reporting via relational joins,

SysRealm delivers a comprehensive, cheat-resistant, and academically rigorous platform suitable for university-level operating systems instruction and evaluation.
