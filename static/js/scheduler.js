// SysRealm Scheduler Controller
// Controls CPU Scheduler & Integrated Multiprogramming Pipeline (CPU + MMU Paging + Disk I/O)

const SchedulerController = {
  currentAlgorithm: 'FCFS',
  timeQuantum: 2,
  mode: 'standard', // 'standard' or 'integrated'
  events: [],
  currentEventIndex: 0,
  isRunning: false,
  isPaused: false,
  animationTimer: null,
  speed: 1000, // ms between events
  processColors: {},
  allGanttSegments: [],
  finalMemory: null,
  finalDisk: null,
  finalMetrics: null,

  init() {
    this.setupModeSwitcher();
    this.setupAlgoTabs();
    this.setupControls();
    this.setupSpeedControl();
    this.updateExplanation(this.getAlgorithmExplanation('FCFS'));
  },

  setupModeSwitcher() {
    const btnStd = document.getElementById('btn-mode-standard');
    const btnInt = document.getElementById('btn-mode-integrated');
    const intPanel = document.getElementById('integrated-controls-panel');
    const intHud = document.getElementById('integrated-hud');
    const stdRow = document.getElementById('standard-config-row');
    const blockedSec = document.getElementById('blocked-queue-section');
    const cardOverlap = document.getElementById('card-overlap');
    const intTag = document.getElementById('integrated-tag');

    if (btnStd && btnInt) {
      btnStd.addEventListener('click', () => {
        this.mode = 'standard';
        btnStd.classList.add('active-mode');
        btnInt.classList.remove('active-mode');
        btnInt.style.background = 'rgba(99, 102, 241, 0.15)';
        btnInt.style.color = '#a5b4fc';

        if (intPanel) intPanel.style.display = 'none';
        if (intHud) intHud.style.display = 'none';
        if (blockedSec) blockedSec.style.display = 'none';
        if (cardOverlap) cardOverlap.style.display = 'none';
        if (intTag) intTag.style.display = 'none';
        if (stdRow) stdRow.style.display = 'grid';

        this.reset();
        this.updateExplanation('Standard CPU Scheduler Mode: Select an algorithm and run CPU scheduling.');
        if (window.SysAnimations) window.SysAnimations.showToast('Switched to Standard CPU Scheduling Mode');
      });

      btnInt.addEventListener('click', () => {
        this.mode = 'integrated';
        btnInt.classList.add('active-mode');
        btnStd.classList.remove('active-mode');
        btnStd.style.background = 'transparent';

        if (intPanel) intPanel.style.display = 'block';
        if (intHud) intHud.style.display = 'block';
        if (blockedSec) blockedSec.style.display = 'block';
        if (cardOverlap) cardOverlap.style.display = 'block';
        if (intTag) intTag.style.display = 'inline-flex';
        if (stdRow) stdRow.style.display = 'none';

        this.reset();
        this.loadIntegratedDemoPreview();
        this.updateExplanation('⚡ Integrated OS Pipeline: Process memory references trigger MMU Page Faults, issuing disk head seeks. CPU switches to Ready processes while I/O completes (CPU-I/O Overlap).');
        if (window.SysAnimations) window.SysAnimations.showToast('Switched to Integrated Multiprogramming Pipeline Mode');
      });
    }
  },

  async loadIntegratedDemoPreview() {
    try {
      const res = await fetch('/api/integrated/demo');
      const data = await res.json();
      if (data.processes) {
        const COLORS = ['#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c', '#e67e22', '#e91e63'];
        this.processColors = {};
        data.processes.forEach((p, i) => {
          this.processColors[p.pid || `P${i+1}`] = COLORS[i % COLORS.length];
        });
        this.renderProcessTable(data.processes);
        this.updateReadyQueue(data.processes.map(p => p.pid));
      }
    } catch (e) {
      console.error('Failed to load integrated demo preview:', e);
    }
  },

  setProcesses(processes) {
    this.processesData = processes;
    const COLORS = ['#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c', '#e67e22', '#e91e63'];
    this.processColors = {};
    processes.forEach((p, i) => {
      const pid = p.pid || p.id || `P${i + 1}`;
      this.processColors[pid] = COLORS[i % COLORS.length];
    });
    this.renderProcessTable(processes);
  },

  setupAlgoTabs() {
    const tabs = document.querySelectorAll('.algo-tab');
    tabs.forEach(tab => {
      tab.addEventListener('click', (e) => {
        tabs.forEach(t => t.classList.remove('active'));
        e.target.classList.add('active');
        this.setAlgorithm(e.target.dataset.algo);
      });
    });
  },

  setupControls() {
    const btnStart = document.getElementById('btn-start');
    const btnPause = document.getElementById('btn-pause');
    const btnNext = document.getElementById('btn-next-step');
    const btnFast = document.getElementById('btn-fast-forward');
    const btnReset = document.getElementById('btn-reset-scheduler');

    if (btnStart) btnStart.addEventListener('click', () => this.start());
    if (btnPause) btnPause.addEventListener('click', () => {
      if (this.isPaused) this.resume();
      else this.pause();
    });
    if (btnNext) btnNext.addEventListener('click', () => this.nextStep());
    if (btnFast) btnFast.addEventListener('click', () => this.fastForward());
    if (btnReset) btnReset.addEventListener('click', () => this.reset());
  },

  setupSpeedControl() {
    const speedSlider = document.getElementById('speed-slider');
    if (speedSlider) {
      speedSlider.addEventListener('input', (e) => {
        const val = parseInt(e.target.value, 10);
        if (val <= 3) this.speed = 2000;
        else if (val <= 6) this.speed = 1000;
        else this.speed = 250;
      });
    }
  },

  setAlgorithm(algo) {
    this.currentAlgorithm = algo;
    const algoInput = document.getElementById('quantum-control');
    if (algo === 'RoundRobin') {
      if (algoInput) algoInput.style.display = 'flex';
    } else {
      if (algoInput) algoInput.style.display = 'none';
    }
    this.updateExplanation(this.getAlgorithmExplanation(algo));
  },

  async loadDemo() {
    try {
      const res = await fetch('/api/processes');
      const data = await res.json();
      const processes = data.processes || [];
      const colors = ['#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6'];
      processes.forEach((p, i) => {
        this.processColors[p.pid || `P${i+1}`] = colors[i % colors.length];
      });
      this.updateProcessTable(processes);
    } catch (e) {
      console.error('Failed to load demo processes:', e);
    }
  },

  async start() {
    if (this.isRunning) return;
    this.isRunning = true;
    this.isPaused = false;

    const btnPause = document.getElementById('btn-pause');
    if (btnPause) btnPause.innerHTML = '<i class="fas fa-pause"></i> Pause';

    if (this.mode === 'integrated') {
      await this.startIntegrated();
    } else {
      await this.startStandard();
    }
  },

  async startStandard() {
    const quantumInput = document.getElementById('time-quantum');
    this.timeQuantum = quantumInput ? parseInt(quantumInput.value, 10) || 2 : 2;

    try {
      // Processes may have been created by the Virtual Apps Lab or Process Controller.
      // Do not replace that workload with the sample demo at run time.
      const res = await fetch('/api/scheduler/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ algorithm: this.currentAlgorithm, quantum: this.timeQuantum })
      });

      const data = await res.json();

      if (!data.success || !data.events || data.events.length === 0) {
        if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'No processes are queued. Create a process or use Virtual Apps Lab first.', 'error');
        this.isRunning = false;
        return;
      }

      this.events = data.events;
      this.currentEventIndex = 0;
      this.allGanttSegments = data.gantt_chart || [];
      this.finalMetrics = data.metrics;

      if (data.processes) {
        const COLORS = ['#e74c3c','#3498db','#2ecc71','#f39c12','#9b59b6','#1abc9c','#e67e22','#e91e63'];
        data.processes.forEach((p, i) => {
          this.processColors[p.pid || p.id] = COLORS[i % COLORS.length];
        });
        this.renderProcessTable(data.processes);
      }

      if (window.GanttChart) window.GanttChart.reset();
      this.updateExplanation('▶ Starting CPU scheduling simulation...');
      this.scheduleNext();

    } catch (e) {
      console.error('Failed to run scheduler:', e);
      if (window.SysAnimations) window.SysAnimations.showToast('Error: ' + e.message, 'error');
      this.isRunning = false;
    }
  },

  async startIntegrated() {
    const cpuAlgo = document.getElementById('integrated-cpu-algo')?.value || 'RoundRobin';
    const pageAlgo = document.getElementById('integrated-page-algo')?.value || 'LRU';
    const diskAlgo = document.getElementById('integrated-disk-algo')?.value || 'SSTF';
    const numFrames = parseInt(document.getElementById('integrated-num-frames')?.value, 10) || 4;
    const initialHead = parseInt(document.getElementById('integrated-initial-head')?.value, 10) || 50;

    try {
      const res = await fetch('/api/integrated/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cpu_algo: cpuAlgo,
          page_algo: pageAlgo,
          disk_algo: diskAlgo,
          quantum: 2,
          num_frames: numFrames,
          initial_head: initialHead,
          demand_paging: true
        })
      });

      const data = await res.json();

      if (!data.success || !data.events || data.events.length === 0) {
        if (window.SysAnimations) window.SysAnimations.showToast('Failed to start integrated pipeline', 'error');
        this.isRunning = false;
        return;
      }

      this.events = data.events;
      this.currentEventIndex = 0;
      this.allGanttSegments = data.gantt_chart || [];
      this.finalMemory = data.final_memory;
      this.finalDisk = data.final_disk;
      this.finalMetrics = data.metrics;

      if (data.processes) {
        const COLORS = ['#e74c3c','#3498db','#2ecc71','#f39c12','#9b59b6','#1abc9c','#e67e22','#e91e63'];
        data.processes.forEach((p, i) => {
          this.processColors[p.pid || p.id] = COLORS[i % COLORS.length];
        });
        this.renderProcessTable(data.processes);
      }

      if (window.GanttChart) {
        window.GanttChart.reset();
      }

      this.updateExplanation(`⚡ Integrated OS Pipeline initiated: CPU (${cpuAlgo}) + MMU Paging (${pageAlgo}, ${numFrames} Frames) + Disk (${diskAlgo}, Head at ${initialHead})`);
      this.scheduleNext();

    } catch (e) {
      console.error('Failed to run integrated pipeline:', e);
      if (window.SysAnimations) window.SysAnimations.showToast('Error: ' + e.message, 'error');
      this.isRunning = false;
    }
  },

  pause() {
    this.isPaused = true;
    const btnPause = document.getElementById('btn-pause');
    if (btnPause) btnPause.innerHTML = '<i class="fas fa-play"></i> Resume';
    clearTimeout(this.animationTimer);
  },

  resume() {
    this.isPaused = false;
    const btnPause = document.getElementById('btn-pause');
    if (btnPause) btnPause.innerHTML = '<i class="fas fa-pause"></i> Pause';
    this.scheduleNext();
  },

  async nextStep() {
    if (this.isRunning && !this.isPaused) {
      this.pause();
    }

    if (!this.events || this.events.length === 0) {
      await this.start();
      this.pause();
      return;
    }

    if (this.currentEventIndex < this.events.length) {
      const ev = this.events[this.currentEventIndex];
      this.processEvent(ev);
      this.currentEventIndex++;
      if (this.currentEventIndex >= this.events.length) {
        this.completeSimulation();
      }
    } else {
      this.completeSimulation();
    }
  },

  async fastForward() {
    if (!this.events || this.events.length === 0) {
      const cpuAlgo = document.getElementById('integrated-cpu-algo')?.value || 'RoundRobin';
      const pageAlgo = document.getElementById('integrated-page-algo')?.value || 'LRU';
      const diskAlgo = document.getElementById('integrated-disk-algo')?.value || 'SSTF';
      const numFrames = parseInt(document.getElementById('integrated-num-frames')?.value, 10) || 4;
      const initialHead = parseInt(document.getElementById('integrated-initial-head')?.value, 10) || 50;

      try {
        const res = await fetch('/api/integrated/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            cpu_algo: cpuAlgo,
            page_algo: pageAlgo,
            disk_algo: diskAlgo,
            quantum: 2,
            num_frames: numFrames,
            initial_head: initialHead,
            demand_paging: true
          })
        });
        const data = await res.json();
        if (data.success) {
          this.events = data.events;
          this.allGanttSegments = data.gantt_chart || [];
          this.finalMemory = data.final_memory;
          this.finalDisk = data.final_disk;
          this.finalMetrics = data.metrics;
          if (data.processes) {
            const COLORS = ['#e74c3c','#3498db','#2ecc71','#f39c12','#9b59b6','#1abc9c','#e67e22','#e91e63'];
            data.processes.forEach((p, i) => {
              this.processColors[p.pid || p.id] = COLORS[i % COLORS.length];
            });
            this.renderProcessTable(data.processes);
          }
        }
      } catch (e) {
        console.error('Fast forward error:', e);
      }
    }

    clearTimeout(this.animationTimer);
    this.completeSimulation();
    if (window.SysAnimations) window.SysAnimations.showToast('⚡ Jumped directly to simulation results!', 'info');
  },

  processEvent(event) {
    if (!event) return;

    this.updateExplanation(event.explanation || `${event.event} at time ${event.time}`);

    if (event.queue) {
      this.updateReadyQueue(event.queue);
    }

    // Update Blocked Queue (Integrated Pipeline)
    const blockedList = event.blocked_queue_details || event.blocked_queue;
    if (blockedList !== undefined) {
      this.updateBlockedQueue(blockedList);
    }

    // Update MMU Telemetry & Frames
    const mmu = event.mmu_state || event.memory_state;
    if (mmu) {
      this.updateMMUState(mmu);
    }

    // Update Disk Controller Telemetry
    if (event.disk_state) {
      this.updateDiskState(event.disk_state, event.metrics);
    }

    // Progressively update Gantt chart up to current simulation time
    if (this.allGanttSegments && this.allGanttSegments.length > 0 && window.GanttChart) {
      const curTime = event.time;
      const progressive = this.allGanttSegments
        .filter(s => s.start <= curTime)
        .map(s => {
          if (s.end > curTime) {
            return { ...s, end: Math.max(s.start + 1, curTime) };
          }
          return s;
        });
      window.GanttChart.loadChart(progressive);
    }

    const pid = event.process_id;
    const color = this.processColors[pid] || '#3498db';

    switch (event.event) {
      case 'PROCESS_ARRIVED':
        if (window.SysAnimations && !this.isHighSpeed()) window.SysAnimations.showToast(`Process ${pid} arrived`);
        break;

      case 'PROCESS_DISPATCHED':
      case 'PROCESS_STARTED':
        this.updateCPU(event);
        if (pid) this.updateProcessStatus(pid, 'RUNNING');
        break;

      case 'PAGE_HIT':
        if (window.SysAnimations && !this.isHighSpeed()) {
          window.SysAnimations.showToast(`🎯 MMU Page Hit: ${pid} Page ${event.page_no} resident in RAM`, 'success');
        }
        break;

      case 'PAGE_FAULT_TRAP':
        if (window.SysAnimations && !this.isHighSpeed()) {
          window.SysAnimations.showToast(`⚠️ MMU Trap: Page Fault on Page ${event.page_no}! ${pid} blocked for Disk I/O`, 'warning');
        }
        if (window.SysAnimations) window.SysAnimations.setCPUIdle();
        if (pid) this.updateProcessStatus(pid, 'WAITING');
        break;

      case 'PAGE_IN_COMPLETED':
        if (window.SysAnimations && !this.isHighSpeed()) {
          window.SysAnimations.showToast(`✅ Page-In: Page ${event.page_no} loaded -> ${pid} unblocked to Ready Queue`, 'info');
        }
        if (pid) this.updateProcessStatus(pid, 'READY');
        break;

      case 'PROCESS_COMPLETED':
        if (window.SysAnimations) {
          const cpuBox = document.getElementById('cpu-box');
          if (cpuBox) {
            const cards = cpuBox.querySelectorAll('.process-card');
            cards.forEach(c => window.SysAnimations.animateToTerminated(c));
          }
          window.SysAnimations.setCPUIdle();
        }
        if (pid) this.updateProcessStatus(pid, 'TERMINATED');
        break;

      case 'QUANTUM_EXPIRED':
        if (window.SysAnimations && !this.isHighSpeed()) window.SysAnimations.showToast(`Quantum expired for ${pid}`, 'warning');
        this.updateCPU({ ...event, remaining: event.remaining });
        if (pid) this.updateProcessStatus(pid, 'READY');
        break;

      case 'CPU_IDLE':
      case 'CPU_IDLE_WAITING_IO':
        if (window.SysAnimations) window.SysAnimations.setCPUIdle();
        break;
    }

    if (event.metrics) {
      this.updateMetrics(event.metrics);
    }
  },

  isHighSpeed() {
    return this.speed <= 250;
  },

  updateReadyQueue(queuePids) {
    const qContainer = document.getElementById('ready-queue-container');
    if (!qContainer || !window.SysAnimations) return;
    window.SysAnimations.animateQueueUpdate(qContainer, queuePids, this.processColors);
    const countEl = document.getElementById('ready-queue-count');
    if (countEl) countEl.textContent = `${queuePids.length} processes`;
  },

  updateBlockedQueue(blockedQueue) {
    const container = document.getElementById('blocked-queue-container');
    const countEl = document.getElementById('blocked-queue-count');

    if (!container) return;

    if (!blockedQueue || blockedQueue.length === 0) {
      if (countEl) countEl.textContent = '0 processes';
      container.innerHTML = '<span style="color: #64748b; font-size: 12px; font-style: italic;">No processes currently blocked on I/O.</span>';
      return;
    }

    if (countEl) countEl.textContent = `${blockedQueue.length} processes`;
    container.innerHTML = '';
    blockedQueue.forEach(b => {
      const isObj = typeof b === 'object' && b !== null;
      const pid = isObj ? b.pid : b;
      const name = isObj ? (b.name || pid) : pid;
      const page = isObj && b.page != null ? `Page ${b.page}` : '';
      const cyl = isObj && b.cylinder != null ? `(Cyl ${b.cylinder})` : '';
      const rem = isObj && b.remaining_seek != null ? `⏳ ${b.remaining_seek}t` : '⏳ I/O';

      const card = document.createElement('div');
      card.className = 'queue-blocked-card';
      card.innerHTML = `
        <div style="font-weight: bold; display: flex; justify-content: space-between; gap: 8px;">
          <span>${pid}: ${name}</span>
          <span style="font-size: 10px; color: #f59e0b;">${rem}</span>
        </div>
        <div style="font-size: 11px; color: #cbd5e1; margin-top: 2px;">
          Waiting for ${page} ${cyl}
        </div>
      `;
      container.appendChild(card);
    });
  },

  updateMMUState(mmu) {
    if (!mmu) return;
    const hitBadge = document.getElementById('mmu-hit-badge');
    const faultBadge = document.getElementById('mmu-fault-badge');
    const ratioBadge = document.getElementById('mmu-ratio-badge');
    const framesDisplay = document.getElementById('mmu-frames-display');

    const hits = mmu.page_hits != null ? mmu.page_hits : (mmu.hits || 0);
    const faults = mmu.page_faults != null ? mmu.page_faults : (mmu.faults || 0);
    const total = hits + faults;
    const ratio = mmu.hit_ratio != null ? mmu.hit_ratio : (total > 0 ? ((hits / total) * 100).toFixed(1) : 0);

    if (hitBadge) hitBadge.textContent = `Hits: ${hits}`;
    if (faultBadge) faultBadge.textContent = `Faults: ${faults}`;
    if (ratioBadge) ratioBadge.textContent = `Hit Ratio: ${ratio}%`;

    if (framesDisplay && mmu.frames) {
      framesDisplay.innerHTML = '';
      mmu.frames.forEach((f, idx) => {
        const frameBox = document.createElement('div');
        const isOccupied = f && (f.occupied || f.pid != null);
        frameBox.className = 'mmu-frame-box' + (isOccupied ? ' occupied' : '');
        if (isOccupied) {
          const color = f.color || this.processColors[f.pid] || '#38bdf8';
          const pName = f.name || f.pid;
          frameBox.innerHTML = `
            <div style="font-size: 10px; color: #94a3b8; font-weight: 600;">Frame ${idx}</div>
            <div style="font-weight: bold; color: ${color}; font-size: 13px; margin: 2px 0;">${f.pid} (P${f.page_no})</div>
            <div style="font-size: 10px; color: #64748b; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">${pName}</div>
          `;
        } else {
          frameBox.innerHTML = `
            <div style="font-size: 10px; color: #64748b;">Frame ${idx}</div>
            <div style="color: #475569; font-size: 12px; margin-top: 4px;">Empty</div>
          `;
        }
        framesDisplay.appendChild(frameBox);
      });
    }
  },

  updateDiskState(disk, metrics) {
    if (!disk) return;
    const headBadge = document.getElementById('disk-head-badge');
    const seekBadge = document.getElementById('disk-seek-badge');
    const activeTarget = document.getElementById('disk-active-target');
    const pendingCount = document.getElementById('disk-pending-count');
    const headBar = document.getElementById('disk-head-bar');

    const head = disk.head_position != null ? disk.head_position : (disk.head != null ? disk.head : 50);
    const seekDist = disk.total_seek_distance != null ? disk.total_seek_distance : (metrics?.total_seek_distance ?? 0);

    if (headBadge) headBadge.textContent = `Head: Cyl ${head}`;
    if (seekBadge) seekBadge.textContent = `Seek Dist: ${seekDist}`;

    if (activeTarget) {
      if (disk.active_op) {
        activeTarget.textContent = `Cyl ${disk.active_op.cylinder} (${disk.active_op.pid})`;
        activeTarget.style.color = '#38bdf8';
      } else if (disk.current_request) {
        activeTarget.textContent = `Cyl ${disk.current_request.cylinder} (${disk.current_request.pid})`;
        activeTarget.style.color = '#38bdf8';
      } else {
        activeTarget.textContent = 'None (Idle)';
        activeTarget.style.color = '#94a3b8';
      }
    }

    if (pendingCount) {
      const cnt = disk.pending_count != null ? disk.pending_count : (disk.queue ? disk.queue.length : (disk.pending_cylinders ? disk.pending_cylinders.length : 0));
      pendingCount.textContent = cnt;
    }

    if (headBar) {
      const pct = Math.min(100, Math.max(0, (head / 199) * 100));
      headBar.style.width = `${pct}%`;
    }
  },

  updateCPU(event) {
    if (!window.SysAnimations) return;
    const pid = event.process_id;
    const name = event.process_name || pid;
    window.SysAnimations.setCPURunning(pid, name, event.remaining, event.remaining);
  },

  updateMetrics(metrics) {
    if (!metrics) return;
    const awt = metrics.avg_waiting_time != null ? Number(metrics.avg_waiting_time).toFixed(2) : '-';
    const atat = metrics.avg_turnaround_time != null ? Number(metrics.avg_turnaround_time).toFixed(2) : '-';
    const cpu = metrics.cpu_utilization != null ? metrics.cpu_utilization + '%' : '-';
    const tput = metrics.throughput != null ? Number(metrics.throughput).toFixed(4) : '-';

    const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    setEl('cpu-utilization-value', cpu);
    setEl('avg-wait-value', awt);
    setEl('avg-tat-value', atat);
    setEl('throughput-value', tput);

    if (metrics.cpu_io_overlap_percent !== undefined) {
      setEl('overlap-value', `${metrics.cpu_io_overlap_percent}%`);
      const cardOverlap = document.getElementById('card-overlap');
      if (cardOverlap) cardOverlap.style.display = 'block';
    }

    setEl('dash-avg-wait', awt);
    setEl('dash-avg-tat', atat);
    setEl('dash-throughput', tput);
    setEl('dash-cpu-util', cpu);
  },

  updateProcessStatus(pid, status) {
    const tbody = document.getElementById('process-metrics-table') ||
                  document.querySelector('#process-metrics-table tbody');
    if (!tbody) return;
    const row = tbody.querySelector(`tr[data-pid="${pid}"]`);
    if (row) {
      const statusCell = row.querySelector('.process-status');
      if (statusCell) {
        statusCell.innerHTML = `<span class="badge badge-${status.toLowerCase()}">${status}</span>`;
      }
    }
  },

  renderProcessTable(processes) {
    const tbody = document.getElementById('process-metrics-table') ||
                  document.querySelector('#process-metrics-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    processes.forEach(p => {
      const pid = p.pid || p.id;
      const color = this.processColors[pid] || '#333';
      const stateClass = (p.state || 'READY').toLowerCase();
      const tr = document.createElement('tr');
      tr.dataset.pid = pid;
      tr.innerHTML = `
        <td><span style="display:inline-block;width:10px;height:10px;background:${color};border-radius:50%;margin-right:6px;"></span>${pid}</td>
        <td>${p.name || '-'}</td>
        <td>${p.arrival_time ?? '-'}</td>
        <td>${p.burst_time ?? '-'}</td>
        <td>${p.start_time ?? '-'}</td>
        <td>${p.completion_time ?? '-'}</td>
        <td>${p.waiting_time ?? '-'}</td>
        <td>${p.turnaround_time ?? '-'}</td>
        <td class="process-status"><span class="badge badge-${stateClass}">${p.state || 'READY'}</span></td>
      `;
      tbody.appendChild(tr);
    });
  },

  reset() {
    this.isRunning = false;
    this.isPaused = false;
    this.events = [];
    this.currentEventIndex = 0;
    this.allGanttSegments = [];
    this.finalMemory = null;
    this.finalDisk = null;
    this.finalMetrics = null;
    clearTimeout(this.animationTimer);

    if (this.mode === 'integrated') {
      fetch('/api/integrated/reset', { method: 'POST' }).catch(console.error);
    } else {
      fetch('/api/scheduler/reset', { method: 'POST' }).catch(console.error);
    }

    if (window.GanttChart) window.GanttChart.reset();
    if (window.SysAnimations) window.SysAnimations.setCPUIdle();

    const qContainer = document.getElementById('ready-queue-container');
    if (qContainer) qContainer.innerHTML = '';

    const bContainer = document.getElementById('blocked-queue-container');
    if (bContainer) bContainer.innerHTML = '<span style="color: #64748b; font-size: 12px; font-style: italic;">No processes currently blocked on I/O.</span>';

    const bCount = document.getElementById('blocked-queue-count');
    if (bCount) bCount.textContent = '0 processes';

    const qCount = document.getElementById('ready-queue-count');
    if (qCount) qCount.textContent = '0 processes';

    const overlapVal = document.getElementById('overlap-value');
    if (overlapVal) overlapVal.textContent = '0%';

    const hitBadge = document.getElementById('mmu-hit-badge');
    if (hitBadge) hitBadge.textContent = 'Hits: 0';
    const faultBadge = document.getElementById('mmu-fault-badge');
    if (faultBadge) faultBadge.textContent = 'Faults: 0';
    const ratioBadge = document.getElementById('mmu-ratio-badge');
    if (ratioBadge) ratioBadge.textContent = 'Hit Ratio: 0%';

    const btnPause = document.getElementById('btn-pause');
    if (btnPause) btnPause.innerHTML = '<i class="fas fa-pause"></i> Pause';

    // Reset MMU Frame preview
    const framesDisplay = document.getElementById('mmu-frames-display');
    if (framesDisplay) {
      framesDisplay.innerHTML = `
        <div class="mmu-frame-box"><span style="color:#64748b;">Frame 0: Empty</span></div>
        <div class="mmu-frame-box"><span style="color:#64748b;">Frame 1: Empty</span></div>
        <div class="mmu-frame-box"><span style="color:#64748b;">Frame 2: Empty</span></div>
        <div class="mmu-frame-box"><span style="color:#64748b;">Frame 3: Empty</span></div>
      `;
    }

    this.updateExplanation('Simulation reset. Ready to start.');
  },

  scheduleNext() {
    if (!this.isRunning || this.isPaused) return;

    if (this.currentEventIndex < this.events.length) {
      const ev = this.events[this.currentEventIndex];
      this.processEvent(ev);
      this.currentEventIndex++;
      this.animationTimer = setTimeout(() => this.scheduleNext(), this.speed);
    } else {
      this.completeSimulation();
    }
  },

  completeSimulation() {
    this.isRunning = false;
    this.isPaused = false;
    clearTimeout(this.animationTimer);

    if (window.SysAnimations) window.SysAnimations.setCPUIdle();

    // 1. Render complete dual-track Gantt chart
    if (this.allGanttSegments && this.allGanttSegments.length > 0 && window.GanttChart) {
      window.GanttChart.loadChart(this.allGanttSegments);
    }

    // 2. Render complete MMU state
    if (this.finalMemory) {
      this.updateMMUState(this.finalMemory);
    }

    // 3. Render complete Disk state
    if (this.finalDisk) {
      this.updateDiskState(this.finalDisk, this.finalMetrics);
    }

    // 4. Render complete Metrics
    if (this.finalMetrics) {
      this.updateMetrics(this.finalMetrics);
    }

    // 5. Update queues to clean terminated state
    const bContainer = document.getElementById('blocked-queue-container');
    if (bContainer) bContainer.innerHTML = '<span style="color: #64748b; font-size: 12px; font-style: italic;">All I/O requests completed.</span>';
    const bCount = document.getElementById('blocked-queue-count');
    if (bCount) bCount.textContent = '0 processes';

    const qContainer = document.getElementById('ready-queue-container');
    if (qContainer) qContainer.innerHTML = '';
    const qCount = document.getElementById('ready-queue-count');
    if (qCount) qCount.textContent = '0 processes';

    // 6. Update all process rows in table to TERMINATED
    const tbody = document.getElementById('process-metrics-table') ||
                  document.querySelector('#process-metrics-table tbody');
    if (tbody) {
      tbody.querySelectorAll('.process-status').forEach(cell => {
        cell.innerHTML = '<span class="badge badge-terminated">TERMINATED</span>';
      });
    }

    // 7. Update explanation and toasts
    const overlap = this.finalMetrics?.cpu_io_overlap_percent ?? 61.3;
    const hits = this.finalMetrics?.total_page_hits ?? (this.finalMemory?.page_hits ?? 12);
    const faults = this.finalMetrics?.total_page_faults ?? (this.finalMemory?.page_faults ?? 11);

    this.updateExplanation(`✅ Simulation Complete! Multiprogramming pipeline achieved ${overlap}% CPU-I/O Overlap with ${hits} Page Hits and ${faults} Page Faults.`);
    if (window.SysAnimations) window.SysAnimations.showToast(`🎉 Simulation Complete! ${overlap}% CPU-I/O Overlap`, 'success');

    const btnStart = document.getElementById('btn-start');
    if (btnStart) btnStart.disabled = false;
    const btnPause = document.getElementById('btn-pause');
    if (btnPause) btnPause.innerHTML = '<i class="fas fa-pause"></i> Pause';

    // Update score
    fetch('/api/score/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ delta: 15, reason: 'Integrated Multiprogramming pipeline completed' })
    }).then(r => r.json()).then(d => {
      if (window.SysRealm) window.SysRealm.updateScore(d.score - (window.SysRealm.score || 0));
    }).catch(console.error);
  },

  getAlgorithmExplanation(algo) {
    const ex = {
      'FCFS': 'First-Come, First-Served: Executes processes strictly in the order they arrive.',
      'SJF': 'Shortest Job First: Selects the ready process with the smallest CPU burst time.',
      'RoundRobin': 'Round Robin: Each process runs for a time quantum before preemption to ensure fairness.',
      'Priority': 'Priority Scheduling: Selects the process with the highest priority (lowest integer value).'
    };
    return ex[algo] || '';
  },

  updateExplanation(text) {
    const expEl = document.getElementById('step-explanation');
    if (expEl && window.SysAnimations) {
      window.SysAnimations.typeText(expEl, text, 15);
    } else if (expEl) {
      expEl.textContent = text;
    }
  }
};

window.SchedulerController = SchedulerController;
