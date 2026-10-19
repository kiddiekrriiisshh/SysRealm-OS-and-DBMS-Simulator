# SysRealm Local Process Monitoring Agent

> **Academic Level:** Third-Year B.Tech Computer Science & Engineering (OS & DBMS)  
> **Module:** Mode B — Real Applications Monitor & Observed CPU Activity Timeline

---

## 1. Overview

The **SysRealm Local Process Monitoring Agent** is a secure, read-only Python utility that collects live operating system process metrics from your personal machine and streams them to your SysRealm web dashboard.

### Core Architectural Principle: Strict Separation of Modes
* **Mode A (Virtual Simulator):** Operates on simulated processes inside SysRealm. Workloads are scheduled using simulated scheduling algorithms (FCFS, SJF, Priority, Round Robin) and visualized on a discrete Gantt chart.
* **Mode B (Real Applications Monitor):** Operates on real OS processes (Google Chrome, VS Code, Spotify, Terminal, etc.) running on your computer. **SysRealm monitors these processes; it does NOT schedule them.** Your actual OS kernel (Darwin XNU on macOS, Linux CFS, Windows Kernel) schedules them. The timeline displays **observed sampled telemetry**, not simulated dispatch slices.

---

## 2. Requirements & Setup

### Prerequisites
* Python 3.8 or newer
* `pip` package manager

### Installation (Virtual Environment Recommended)
```bash
# 1. Navigate to the project root directory
cd "SysRealm 2"

# 2. (Optional but recommended) Create and activate a Python virtual environment
python3 -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate

# 3. Install agent dependencies
pip install -r local_monitor/requirements.txt
```

Dependencies installed:
* `psutil>=5.9.0`: Non-blocking process and memory sampling.
* `requests>=2.28.0`: HTTP/HTTPS client for posting telemetry.

---

## 3. How to Pair and Run the Agent

1. **Start the SysRealm Web Application:**
   ```bash
   python3 app.py
   ```
   Open your browser to `http://localhost:5000` and log in to your account.

2. **Navigate to the Virtual Apps Lab:**
   * Click **Virtual Apps Lab** in the sidebar.
   * Switch to **Mode B: Real Applications Monitor**.

3. **Generate a Pairing Code:**
   * Click the **Pair Local Agent** button.
   * A 6-character single-use code will appear (e.g., `SR-8F2K`), valid for 5 minutes.

4. **Launch the Agent in Your Terminal:**
   ```bash
   python3 local_monitor/agent.py --server http://127.0.0.1:5000 --pair SR-8F2K
   ```
   *The agent exchanges the pairing code for a persistent bearer token and immediately begins streaming live telemetry.*

5. **Stop Monitoring:**
   * In your terminal: Press `Ctrl+C`.
   * Or in the web dashboard: Click **Stop Monitoring** to revoke the session token immediately.

---

## 4. Security & Safety Guarantees

| Guarantee | Technical Implementation |
| :--- | :--- |
| **Strictly Read-Only** | The agent calls only read functions (`psutil.process_iter`, `cpu_percent`, `memory_info`). It contains **no code** to kill, signal, or modify processes. |
| **No Elevated Privileges** | Runs entirely in user space. **Never** run with `sudo` or as administrator. |
| **PID Reuse Protection** | Processes are tracked using a compound key: `PID + creation_timestamp` to prevent collision when the OS recycles process IDs. |
| **Ephemeral Pairing** | Pairing codes expire in 5 minutes and are single-use. The resulting bearer token can be revoked with a single click. |
| **Privacy Safeguards** | Process command lines are stripped and truncated to at most 120 characters to prevent exposing sensitive arguments or tokens. |

---

## 5. Command-Line Options

```text
usage: agent.py [-h] [--server SERVER] [--pair PAIR] [--token TOKEN]
                [--interval INTERVAL] [--max-procs MAX_PROCS] [--config CONFIG]

optional arguments:
  --server SERVER       SysRealm server base URL (default: http://127.0.0.1:5000)
  --pair PAIR           6-character pairing code from the SysRealm UI
  --token TOKEN         Bearer token (if already paired)
  --interval INTERVAL   Sampling interval in seconds (default: 2.0, min: 1.0)
  --max-procs MAX_PROCS Max individual processes per snapshot (default: 50)
  --config CONFIG       Path to JSON configuration file
```

---

## 6. Troubleshooting

* **Permission Denied on macOS:**  
  Standard user processes can read their own CPU and memory without special permissions. For system-wide statistics, ensure your terminal application has normal permissions in macOS System Settings > Privacy & Security.
* **Connection Refused:**  
  Verify that `app.py` is running on `http://127.0.0.1:5000` before launching the agent.
* **Pairing Code Expired:**  
  Pairing codes are valid for 5 minutes. If expired, click "Generate New Code" in the SysRealm UI.
