// SysRealm Dashboard Controller  
// Main app controller: navigation, dashboard panel, process management, memory, logs

const SysRealm = {
  currentPanel: 'dashboard',
  currentSession: null,
  refreshInterval: null,
  score: 0,
  simTime: 0,
  simStatus: 'IDLE',
  
  async init() {
    this.setupNavigation();
    this.setupProcessPanel();
    this.setupMemoryPanel();
    this.setupFilesPanel();
    
    await this.checkDbStatus();
    await this.createSession();
    await this.loadDemo();
    
    this.showPanel('dashboard');
    
    // Auto-refresh stats every 3 seconds when on dashboard
    this.refreshInterval = setInterval(() => {
      if (this.currentPanel === 'dashboard') this.refreshDashboard();
    }, 3000);
  },
  
  setupNavigation() {
    const links = document.querySelectorAll('.nav-link');
    links.forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        links.forEach(l => l.classList.remove('active'));
        e.currentTarget.classList.add('active');
        const panelId = e.currentTarget.getAttribute('href').substring(1);
        this.showPanel(panelId);
      });
    });

    // Reset button in top bar
    const btnResetAll = document.getElementById('btn-reset-all');
    if (btnResetAll) btnResetAll.addEventListener('click', () => this.fullReset());

    // Load demo button in processes panel
    const btnLoadDemo = document.getElementById('btn-load-demo');
    if (btnLoadDemo) btnLoadDemo.addEventListener('click', () => this.loadDemo());
  },
  
  showPanel(panelId) {
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    const panel = document.getElementById(`panel-${panelId}`);
    if (panel) panel.classList.add('active');
    this.currentPanel = panelId;
    
    // Update active nav link
    document.querySelectorAll('.nav-link').forEach(l => {
      l.classList.toggle('active', l.getAttribute('href') === `#${panelId}`);
    });
    
    // Load specific data based on panel
    if (panelId === 'dashboard') this.refreshDashboard();
    else if (panelId === 'processes') this.refreshProcessList();
    else if (panelId === 'memory') this.refreshMemory();
    else if (panelId === 'files') this.loadFiles();
    else if (panelId === 'disk') { if(window.DiskController) window.DiskController.runSimulation(); }
    else if (panelId === 'optimizer') { if(window.DBMSController) window.DBMSController.runOptimizer(); }
    else if (panelId === 'logs') this.loadLogs();
    else if (panelId === 'history') this.loadHistory();
    else if (panelId === 'resources') { if(window.ResourcesController) window.ResourcesController.loadResources(); }
  },
  
  async loadDemo() {
    try {
      const res = await fetch('/api/demo/load');
      const data = await res.json();
      if (data.success) {
        if (window.SysAnimations) window.SysAnimations.showToast('Demo data loaded! 4 processes ready.', 'success');
        const processes = data.processes || [];
        // Pass processes to scheduler controller
        if (window.SchedulerController) window.SchedulerController.setProcesses(processes);
        this.refreshDashboard();
        if (data.memory) this.updateMemoryPanel(data.memory);
      }
    } catch (e) {
      console.error('Failed to load demo:', e);
    }
  },
  
  async refreshDashboard() {
    try {
      const [stateRes, memRes, statRes] = await Promise.all([
        fetch('/api/scheduler/state'),
        fetch('/api/memory'),
        fetch('/api/statistics')
      ]);
      
      if (stateRes.ok) {
        const state = await stateRes.json();
        this.updateCPUPanel(state);
        this.updateProcessTable(state.processes || []);
        if (state.storage) this.updateStoragePanel(state.storage);
        if (state.score !== undefined) this.updateScore(state.score - this.score);
      }
      if (memRes.ok) {
        const memData = await memRes.json();
        this.updateMemoryPanel(memData);
      }
      if (statRes.ok) {
        const statData = await statRes.json();
        this.updateMetrics(statData.metrics || {});
      }
    } catch (e) {
      console.error('Dashboard refresh failed:', e);
    }
  },
  
  updateCPUPanel(state) {
    const fields = {
      'cpu-algorithm':   state.algorithm || 'FCFS',
      'cpu-sim-time':    state.simulation_time || 0,
      'cpu-status':      state.simulation_running ? 'RUNNING' : 'IDLE',
      'sim-time-display': `T = ${state.simulation_time || 0}`,
      'sim-status-badge': state.simulation_running ? '● RUNNING' : '○ IDLE',
      'score-display':   state.score || 0,
    };
    Object.entries(fields).forEach(([id, val]) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    });
  },
  
  updateMemoryPanel(memory) {
    // memory object from /api/memory: {total_mb, used_mb, free_mb, utilization, allocations[]}
    const fields = {
      'memory-total': memory.total_gb ? `${memory.total_gb} GB` : (memory.total_mb ? `${(memory.total_mb/1024).toFixed(1)} GB` : '-'),
      'memory-used':  memory.used_gb ? `${memory.used_gb} GB` : (memory.used_mb ? `${(memory.used_mb/1024).toFixed(2)} GB` : '-'),
      'memory-free':  memory.free_gb ? `${memory.free_gb} GB` : (memory.free_mb ? `${(memory.free_mb/1024).toFixed(2)} GB` : '-'),
    };
    Object.entries(fields).forEach(([id, val]) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    });

    // Update memory bar
    const totalMb = memory.total_mb || 16384;
    this.renderMemoryBar(memory.allocations || [], totalMb);

    // Update utilization bar
    const utilBar = document.getElementById('memory-util-bar');
    if (utilBar) utilBar.style.width = `${memory.utilization || 0}%`;
  },
  
  updateStoragePanel(storage) {
    const fields = {
      'storage-total': `${storage.total_gb} GB`,
      'storage-used':  `${storage.used_gb} GB`,
      'storage-free':  `${storage.free_gb} GB`,
    };
    Object.entries(fields).forEach(([id, val]) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    });
  },
  
  updateProcessTable(processes) {
    // Update both the dashboard table and any other process tables
    const tbody = document.querySelector('#dash-active-processes') ||
                  document.querySelector('#dashboard-process-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    
    processes.slice(0, 8).forEach(p => {
      const pid = p.pid || p.id;
      const stateClass = (p.state || 'READY').toLowerCase();
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><strong>${pid}</strong></td>
        <td>${p.name || '-'}</td>
        <td><span class="badge badge-${stateClass}">${p.state || 'READY'}</span></td>
        <td>${p.remaining_time ?? p.burst_time ?? '-'}</td>
        <td>${p.priority ?? '-'}</td>
      `;
      tbody.appendChild(tr);
    });
  },
  
  updateMetrics(metrics) {
    const fields = {
      'dash-avg-wait':  metrics.avg_waiting_time != null ? metrics.avg_waiting_time.toFixed(2) : '-',
      'dash-avg-tat':   metrics.avg_turnaround_time != null ? metrics.avg_turnaround_time.toFixed(2) : '-',
      'dash-cpu-util':  metrics.cpu_utilization != null ? `${metrics.cpu_utilization}%` : '-',
      'dash-throughput':metrics.throughput != null ? metrics.throughput.toFixed(4) : '-',
    };
    Object.entries(fields).forEach(([id, val]) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    });
  },
  
  async createSession() {
    try {
      const res = await fetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ algorithm: 'FCFS' })
      });
      const data = await res.json();
      if (data.success) this.currentSession = data.session_id;
    } catch(e) {
      console.error('Session create failed:', e);
    }
  },
  
  setupProcessPanel() {
    const form = document.getElementById('form-create-process');
    if (form) {
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        this.createProcess();
      });
    }
  },
  
  async createProcess() {
    const name     = (document.getElementById('proc-name')    || {}).value || '';
    const arrival  = parseInt((document.getElementById('proc-arrival') || {}).value || '0', 10);
    const burst    = parseInt((document.getElementById('proc-burst')   || {}).value || '1', 10);
    const priority = parseInt((document.getElementById('proc-priority') || {}).value || '2', 10);
    const memory   = parseInt((document.getElementById('proc-memory')  || {}).value || '512', 10);

    if (!name.trim()) {
      if (window.SysAnimations) window.SysAnimations.showToast('Process name required', 'error');
      return;
    }
    if (burst <= 0) {
      if (window.SysAnimations) window.SysAnimations.showToast('Burst time must be positive', 'error');
      return;
    }
    
    try {
      const res = await fetch('/api/processes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          arrival_time: arrival,
          burst_time: burst,
          priority: priority,
          memory_mb: memory
        })
      });
      const data = await res.json();
      if (data.success || res.status === 201) {
        if (window.SysAnimations) window.SysAnimations.showToast(`Process "${name}" created!`, 'success');
        document.getElementById('form-create-process').reset();
        this.refreshProcessList();
        // Also update scheduler process list
        const procRes = await fetch('/api/processes');
        const procData = await procRes.json();
        if (window.SchedulerController) window.SchedulerController.setProcesses(procData.processes || []);
      } else {
        if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'Failed to create process', 'error');
      }
    } catch (e) {
      console.error(e);
      if (window.SysAnimations) window.SysAnimations.showToast('Network error', 'error');
    }
  },
  
  async deleteProcess(pid) {
    try {
      const res = await fetch(`/api/processes/${pid}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        if (window.SysAnimations) window.SysAnimations.showToast(`Process ${pid} deleted`, 'info');
        this.refreshProcessList();
      }
    } catch (e) {
      console.error(e);
    }
  },
  
  async refreshProcessList() {
    try {
      const res = await fetch('/api/processes');
      const data = await res.json();
      const processes = data.processes || [];
      
      // Update processes panel table
      const tbody = document.querySelector('#processes-table tbody');
      if (tbody) {
        tbody.innerHTML = '';
        processes.forEach(p => {
          const pid = p.pid || p.id;
          const stateClass = (p.state || 'READY').toLowerCase();
          const tr = document.createElement('tr');
          tr.innerHTML = `
            <td><strong>${pid}</strong></td>
            <td>${p.name || '-'}</td>
            <td>${p.arrival_time ?? 0}</td>
            <td>${p.burst_time ?? 0}</td>
            <td>${p.priority ?? 2}</td>
            <td>${p.memory_mb ?? 512} MB</td>
            <td><span class="badge badge-${stateClass}">${p.state || 'READY'}</span></td>
            <td>${p.remaining_time ?? p.burst_time ?? 0}</td>
            <td>
              <button class="btn btn-danger btn-sm" onclick="SysRealm.deleteProcess('${pid}')">
                <i class="fas fa-trash"></i>
              </button>
            </td>
          `;
          tbody.appendChild(tr);
        });
      }
      
      // Also update dashboard table
      this.updateProcessTable(processes);
      
      // Sync with SchedulerController
      if (window.SchedulerController) window.SchedulerController.setProcesses(processes);
    } catch (e) {
      console.error(e);
    }
  },

  setupFilesPanel() {
    const btnCreate = document.getElementById('btn-create-file');
    if (btnCreate) {
      btnCreate.addEventListener('click', (e) => {
        e.preventDefault();
        this.createFile();
      });
    }

    ['file-name', 'file-size'].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            this.createFile();
          }
        });
      }
    });

    this.loadFiles();
  },

  async createFile() {
    const nameEl = document.getElementById('file-name');
    const sizeEl = document.getElementById('file-size');
    const ownerEl = document.getElementById('file-owner');

    const filename = (nameEl ? nameEl.value : '').trim();
    const size_kb = parseInt(sizeEl ? sizeEl.value : '0', 10);
    const owner_pid = ownerEl ? ownerEl.value : '';

    if (!filename) {
      if (window.SysAnimations) window.SysAnimations.showToast('Please enter a filename', 'error');
      else alert('Please enter a filename');
      if (nameEl) nameEl.focus();
      return;
    }
    if (isNaN(size_kb) || size_kb <= 0) {
      if (window.SysAnimations) window.SysAnimations.showToast('Please enter a valid size (> 0 KB)', 'error');
      else alert('Please enter a valid size (> 0 KB)');
      if (sizeEl) sizeEl.focus();
      return;
    }

    try {
      const res = await fetch('/api/files', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename, size_kb, owner_pid })
      });
      const data = await res.json();
      if (data.success) {
        if (window.SysAnimations) window.SysAnimations.showToast(`File "${filename}" created successfully! (+5 XP)`, 'success');
        if (nameEl) nameEl.value = '';
        if (sizeEl) sizeEl.value = '';
        await this.loadFiles();
        if (data.storage) this.updateStoragePanel(data.storage);
        this.refreshDashboard();
      } else {
        if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'Failed to create file', 'error');
      }
    } catch (e) {
      console.error('Create file error:', e);
      if (window.SysAnimations) window.SysAnimations.showToast('Network error while creating file', 'error');
    }
  },

  async loadFiles() {
    const tbody = document.getElementById('files-table');
    if (!tbody) return;
    try {
      const res = await fetch('/api/files');
      const data = await res.json();
      if (!data.success) return;
      const files = data.files || [];
      if (files.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">No files created yet. Enter a filename and size above to allocate disk blocks!</td></tr>';
        return;
      }
      tbody.innerHTML = files.map(f => {
        const safeName = (f.filename || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        const safePid = (f.owner_pid || 'P1').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const sizeFormatted = f.size_kb >= 1024 
          ? `${(f.size_kb / 1024).toFixed(1)} MB (${Number(f.size_kb).toLocaleString()} KB)` 
          : `${Number(f.size_kb).toLocaleString()} KB`;
        const dateStr = f.created_at ? f.created_at.substring(0, 19).replace('T', ' ') : '—';
        return `
          <tr>
            <td style="font-weight:600;"><i class="fas fa-file-alt" style="color:var(--accent-blue);margin-right:8px;"></i>${safeName}</td>
            <td><code>${sizeFormatted}</code></td>
            <td><span class="badge badge-ready" style="font-size:11px;font-weight:700;">${safePid}</span></td>
            <td style="color:var(--text-muted);font-size:12px;">${dateStr}</td>
            <td>
              <button class="btn btn-sm btn-danger" onclick="SysRealm.deleteFile(${f.id})" style="padding:4px 10px;font-size:11px;border-radius:6px;background:rgba(239,68,68,0.2);border:1px solid rgba(239,68,68,0.5);color:#fca5a5;cursor:pointer;" title="Delete file">
                <i class="fas fa-trash"></i>
              </button>
            </td>
          </tr>
        `;
      }).join('');
      if (data.storage) this.updateStoragePanel(data.storage);
    } catch (e) {
      console.error('Load files error:', e);
    }
  },

  async deleteFile(fileId) {
    if (!confirm('Are you sure you want to delete this file from storage?')) return;
    try {
      const res = await fetch(`/api/files/${fileId}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        if (window.SysAnimations) window.SysAnimations.showToast('File deleted from secondary storage', 'info');
        await this.loadFiles();
        if (data.storage) this.updateStoragePanel(data.storage);
        this.refreshDashboard();
      }
    } catch (e) {
      console.error('Delete file error:', e);
    }
  },
  
  selectedPagingPid: null,
  lastMemoryState: null,
  highlightedFrameNo: null,
  highlightedPageNo: null,

  setupMemoryPanel() {
    const btnPagingDemo = document.getElementById('btn-paging-demo');
    if (btnPagingDemo) {
      btnPagingDemo.addEventListener('click', async () => {
        const res = await fetch('/api/memory/paging-demo', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          this.selectedPagingPid = 'P1';
          this.updateMemoryPanel(data);
          this.renderPagingUI(data);
          this.runMMUTranslation('P1', 700, true);
          if (window.SysAnimations) {
            window.SysAnimations.showToast('Loaded 4-process Non-Contiguous Paging & Internal Fragmentation Demo!', 'success');
          }
        }
      });
    }

    const btnScatter = document.getElementById('btn-paging-scatter');
    if (btnScatter) {
      btnScatter.addEventListener('click', async () => {
        const res = await fetch('/api/memory/scatter', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ scatter: true })
        });
        const data = await res.json();
        if (data.success) {
          this.updateMemoryPanel(data);
          this.renderPagingUI(data);
          if (this.selectedPagingPid) this.runMMUTranslation(this.selectedPagingPid, null, true);
          if (window.SysAnimations) {
            window.SysAnimations.showToast('Frames scattered non-contiguously across RAM! Page Tables updated.', 'info');
          }
        }
      });
    }

    const btnContig = document.getElementById('btn-paging-contiguous');
    if (btnContig) {
      btnContig.addEventListener('click', async () => {
        const res = await fetch('/api/memory/scatter', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ scatter: false })
        });
        const data = await res.json();
        if (data.success) {
          this.updateMemoryPanel(data);
          this.renderPagingUI(data);
          if (this.selectedPagingPid) this.runMMUTranslation(this.selectedPagingPid, null, true);
          if (window.SysAnimations) {
            window.SysAnimations.showToast('Frames packed contiguously in physical RAM.', 'info');
          }
        }
      });
    }

    const btnPagingAlloc = document.getElementById('btn-paging-alloc');
    if (btnPagingAlloc) {
      btnPagingAlloc.addEventListener('click', async () => {
        const pid  = ((document.getElementById('paging-alloc-pid') || {}).value || '').trim();
        const name = ((document.getElementById('paging-alloc-name') || {}).value || pid).trim();
        const size = parseInt((document.getElementById('paging-alloc-size') || {}).value || '512', 10);
        if (!pid) {
          if (window.SysAnimations) window.SysAnimations.showToast('Process ID required', 'error');
          return;
        }
        const res = await fetch('/api/memory/allocate', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pid, name, size_mb: size })
        });
        const data = await res.json();
        if (data.success) {
          this.selectedPagingPid = pid;
          if (window.SysAnimations) {
            const pt = data.page_table || {};
            window.SysAnimations.showToast(
              `Allocated ${size} MB (${pt.num_pages} pages, ${pt.internal_frag_mb} MB Internal Frag) to ${pid}!`,
              'success'
            );
          }
          await this.refreshMemory();
          this.runMMUTranslation(pid, Math.min(128, size - 1), true);
        } else {
          if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'Allocation failed', 'error');
        }
      });
    }

    const btnMMU = document.getElementById('btn-mmu-translate');
    if (btnMMU) {
      btnMMU.addEventListener('click', () => {
        const pid  = (document.getElementById('mmu-proc-select') || {}).value;
        const addr = parseInt((document.getElementById('mmu-logical-addr') || {}).value || '0', 10);
        this.runMMUTranslation(pid, addr, false);
      });
    }

    const mmuProcSel = document.getElementById('mmu-proc-select');
    if (mmuProcSel) {
      mmuProcSel.addEventListener('change', () => {
        this.selectedPagingPid = mmuProcSel.value;
        if (this.lastMemoryState) this.renderPagingUI(this.lastMemoryState);
      });
    }

    // 1-Click MMU Presets
    const btnPresetHit = document.getElementById('btn-mmu-preset-hit');
    if (btnPresetHit) {
      btnPresetHit.addEventListener('click', async () => {
        await this._ensurePagingDemoForPreset();
        const addrEl = document.getElementById('mmu-logical-addr');
        if (addrEl) addrEl.value = 700;
        this.runMMUTranslation(this.selectedPagingPid || 'P1', 700, false);
      });
    }

    const btnPresetFrag = document.getElementById('btn-mmu-preset-frag');
    if (btnPresetFrag) {
      btnPresetFrag.addEventListener('click', async () => {
        await this._ensurePagingDemoForPreset();
        const pt = ((this.lastMemoryState || {}).paging || {}).page_tables || {};
        let targetPid = this.selectedPagingPid || 'P1';
        if (!pt[targetPid] || pt[targetPid].internal_frag_mb === 0) {
          const fragPid = Object.keys(pt).find(k => pt[k].internal_frag_mb > 0);
          if (fragPid) targetPid = fragPid;
          else {
            const res = await fetch('/api/memory/paging-demo', { method: 'POST' });
            const d = await res.json();
            this.updateMemoryPanel(d);
            this.renderPagingUI(d);
            targetPid = 'P1';
          }
        }
        const procInfo = (((this.lastMemoryState || {}).paging || {}).page_tables || {})[targetPid];
        const fragAddr = procInfo ? (procInfo.size_mb + Math.max(10, Math.floor(procInfo.internal_frag_mb / 2))) : 1350;
        const addrEl = document.getElementById('mmu-logical-addr');
        if (addrEl) addrEl.value = fragAddr;
        this.runMMUTranslation(targetPid, fragAddr, false);
      });
    }

    const btnPresetFault = document.getElementById('btn-mmu-preset-fault');
    if (btnPresetFault) {
      btnPresetFault.addEventListener('click', async () => {
        await this._ensurePagingDemoForPreset();
        const targetPid = this.selectedPagingPid || 'P1';
        const addrEl = document.getElementById('mmu-logical-addr');
        if (addrEl) addrEl.value = 2500;
        this.runMMUTranslation(targetPid, 2500, false);
      });
    }

    // ── Tab 3: Demand Paging & Page Replacement Controls ──
    document.querySelectorAll('.pr-algo-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const algo = btn.getAttribute('data-algo') || 'FIFO';
        this.setPRAlgorithm(algo);
        this.runPageReplacement();
      });
    });

    const btnPRSim = document.getElementById('btn-pr-simulate');
    if (btnPRSim) {
      btnPRSim.addEventListener('click', () => this.runPageReplacement());
    }

    const prFramesSel = document.getElementById('pr-num-frames');
    if (prFramesSel) {
      prFramesSel.addEventListener('change', () => this.runPageReplacement());
    }

    const btnPRClassic = document.getElementById('btn-pr-preset-classic');
    if (btnPRClassic) {
      btnPRClassic.addEventListener('click', () => {
        const refEl = document.getElementById('pr-ref-string');
        const frmEl = document.getElementById('pr-num-frames');
        if (refEl) refEl.value = '7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2, 1, 2, 0, 1, 7, 0, 1';
        if (frmEl) frmEl.value = '3';
        this.runPageReplacement();
        if (window.SysAnimations) window.SysAnimations.showToast('Loaded Silberschatz 20-Reference Classic String!', 'success');
      });
    }

    const btnPRBelady3 = document.getElementById('btn-pr-preset-belady3');
    if (btnPRBelady3) {
      btnPRBelady3.addEventListener('click', () => {
        const refEl = document.getElementById('pr-ref-string');
        const frmEl = document.getElementById('pr-num-frames');
        if (refEl) refEl.value = '1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5';
        if (frmEl) frmEl.value = '3';
        this.setPRAlgorithm('FIFO');
        this.runPageReplacement();
        if (window.SysAnimations) window.SysAnimations.showToast('Belady String @ 3 Frames: 9 Page Faults. Now click 4 Frames!', 'info');
      });
    }

    const btnPRBelady4 = document.getElementById('btn-pr-preset-belady4');
    if (btnPRBelady4) {
      btnPRBelady4.addEventListener('click', () => {
        const refEl = document.getElementById('pr-ref-string');
        const frmEl = document.getElementById('pr-num-frames');
        if (refEl) refEl.value = '1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5';
        if (frmEl) frmEl.value = '4';
        this.setPRAlgorithm('FIFO');
        this.runPageReplacement();
        if (window.SysAnimations) window.SysAnimations.showToast('🚨 Belady\'s Anomaly! 4 Frames produced 10 Page Faults (> 9 Faults at 3 Frames)!', 'warning');
      });
    }
  },

  currentPRAlgo: 'FIFO',

  switchMemoryTab(tab) {
    const tabPaging = document.getElementById('mem-subtab-paging');
    const tabRepl   = document.getElementById('mem-subtab-replacement');
    const btnPaging = document.getElementById('btn-mem-tab-paging');
    const btnRepl   = document.getElementById('btn-mem-tab-replacement');

    if (tab === 'replacement') {
      if (tabPaging) tabPaging.style.display = 'none';
      if (tabRepl)   tabRepl.style.display   = 'block';
      if (btnRepl) {
        btnRepl.style.background = 'linear-gradient(135deg,#2563eb,#7c3aed)';
        btnRepl.style.color = '#fff';
      }
      if (btnPaging) {
        btnPaging.style.background = 'transparent';
        btnPaging.style.color = '#94a3b8';
      }
      this.runPageReplacement();
    } else {
      if (tabPaging) tabPaging.style.display = 'block';
      if (tabRepl)   tabRepl.style.display   = 'none';
      if (btnPaging) {
        btnPaging.style.background = 'linear-gradient(135deg,#2563eb,#7c3aed)';
        btnPaging.style.color = '#fff';
      }
      if (btnRepl) {
        btnRepl.style.background = 'transparent';
        btnRepl.style.color = '#94a3b8';
      }
      this.refreshMemory();
    }
  },

  setPRAlgorithm(algo) {
    this.currentPRAlgo = (algo || 'FIFO').toUpperCase();
    document.querySelectorAll('.pr-algo-btn').forEach(btn => {
      const a = (btn.getAttribute('data-algo') || '').toUpperCase();
      if (a === this.currentPRAlgo) {
        btn.style.background = 'var(--primary)';
        btn.style.color = '#fff';
      } else {
        btn.style.background = 'var(--secondary)';
        btn.style.color = '#cbd5e1';
      }
    });
  },

  async runPageReplacement() {
    const refStr = ((document.getElementById('pr-ref-string') || {}).value || '7, 0, 1, 2, 0, 3, 0, 4, 2, 3').trim();
    const numFrames = parseInt((document.getElementById('pr-num-frames') || {}).value || '3', 10);
    const algo = this.currentPRAlgo || 'FIFO';

    try {
      const res = await fetch('/api/memory/page-replacement', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reference_string: refStr,
          num_frames: numFrames,
          algorithm: algo
        })
      });
      const data = await res.json();
      if (!data.success) {
        if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'Simulation failed', 'error');
        return;
      }
      this.renderPageReplacementUI(data);
    } catch (e) {
      console.error('Page replacement error:', e);
    }
  },

  renderPageReplacementUI(data) {
    const act = data.active || {};
    const cmp = data.comparison || {};
    const belady = data.belady_check || {};
    const steps = act.steps || [];
    const numFrames = act.num_frames || 3;

    // 1. Update KPI cards
    const elFaults = document.getElementById('pr-kpi-faults');
    const elHits   = document.getElementById('pr-kpi-hits');
    const elHitR   = document.getElementById('pr-kpi-hit-ratio');
    const elFaultR = document.getElementById('pr-kpi-fault-ratio');
    const elTitle  = document.getElementById('pr-matrix-algo-title');

    if (elFaults) elFaults.textContent = `${act.page_faults ?? 0} / ${act.total_references ?? 0}`;
    if (elHits)   elHits.textContent   = `${act.page_hits ?? 0} / ${act.total_references ?? 0}`;
    if (elHitR)   elHitR.textContent   = `${act.hit_ratio ?? 0}%`;
    if (elFaultR) elFaultR.textContent = `${act.fault_ratio ?? 0}%`;
    if (elTitle)  elTitle.textContent  = `${act.algorithm} — ${numFrames} Physical Frames`;

    // 2. Belady's Anomaly Banner
    const beladyEl = document.getElementById('pr-belady-banner');
    if (beladyEl) {
      if (belady.detected) {
        beladyEl.innerHTML = `
          <div style="background:linear-gradient(135deg,rgba(153,27,27,0.5),rgba(15,23,42,0.92));border:1px solid #ef4444;border-left:5px solid #ef4444;border-radius:10px;padding:12px 16px;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">
            <div>
              <div style="font-size:14px;font-weight:800;color:#f87171;">🚨 BELADY'S ANOMALY DETECTED ON THIS REFERENCE STRING!</div>
              <div style="font-size:12px;color:#fecaca;margin-top:3px;">${belady.explanation}</div>
            </div>
            <div style="display:flex;gap:8px;font-family:monospace;font-size:12px;">
              <span style="background:#1e293b;border:1px solid #f59e0b;color:#fbbf24;padding:6px 10px;border-radius:6px;font-weight:700;">
                FIFO 3 Frames: ${belady.fifo_3_frames_faults} Faults
              </span>
              <span style="background:#7f1d1d;border:1px solid #ef4444;color:#fca5a5;padding:6px 10px;border-radius:6px;font-weight:800;">
                FIFO 4 Frames: ${belady.fifo_4_frames_faults} Faults (+${belady.fifo_4_frames_faults - belady.fifo_3_frames_faults} MORE!)
              </span>
            </div>
          </div>
        `;
      } else {
        beladyEl.innerHTML = `
          <div style="background:rgba(15,23,42,0.75);border:1px solid var(--border-color);border-left:4px solid #3b82f6;border-radius:8px;padding:10px 14px;font-size:12px;color:#cbd5e1;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
            <span>ℹ️ <strong>Belady's Anomaly Check:</strong> ${belady.explanation}</span>
          </div>
        `;
      }
    }

    // 3. Render Classic OS Exam Frame-by-Step Matrix
    const matrixBox = document.getElementById('pr-matrix-container');
    if (matrixBox) {
      let headerRow = `<th style="min-width:95px;background:#0f172a;color:#94a3b8;font-size:11px;text-align:left;padding:8px 10px;position:sticky;left:0;">Step / Ref</th>`;
      steps.forEach(s => {
        const colColor = s.status === 'HIT' ? '#4ade80' : '#f87171';
        headerRow += `
          <th style="min-width:52px;text-align:center;background:#0f172a;padding:6px 4px;border-bottom:2px solid ${colColor};">
            <div style="font-size:10px;color:#64748b;">#${s.step}</div>
            <div style="font-size:15px;font-weight:800;color:#f8fafc;font-family:monospace;">P${s.page}</div>
          </th>
        `;
      });

      let frameRows = '';
      for (let fIdx = 0; fIdx < numFrames; fIdx++) {
        frameRows += `<tr><td style="font-weight:700;color:#60a5fa;background:#0f172a;padding:8px 10px;font-size:12px;position:sticky;left:0;">Frame ${fIdx}</td>`;
        steps.forEach(s => {
          const val = s.frames[fIdx];
          const isTarget = (s.target_frame === fIdx);
          const isHit = (s.status === 'HIT' && isTarget);
          const isFaultLoad = (s.status === 'FAULT' && isTarget);

          let cellBg = 'rgba(15,23,42,0.55)';
          let cellBorder = '1px solid #1e293b';
          let textColor = '#cbd5e1';
          if (isHit) {
            cellBg = 'rgba(22,101,52,0.45)';
            cellBorder = '2px solid #22c55e';
            textColor = '#86efac';
          } else if (isFaultLoad) {
            cellBg = 'rgba(153,27,27,0.45)';
            cellBorder = '2px solid #ef4444';
            textColor = '#fecaca';
          }

          frameRows += `
            <td style="text-align:center;font-family:monospace;font-size:14px;font-weight:700;padding:8px 4px;background:${cellBg};border:${cellBorder};color:${textColor};"
                title="Step ${s.step}: ${s.reason}">
              ${val != null ? val : '—'}
            </td>
          `;
        });
        frameRows += `</tr>`;
      }

      // Victim evicted row
      let victimRow = `<tr><td style="font-size:11px;color:#94a3b8;background:#0f172a;padding:6px 10px;position:sticky;left:0;">Evicted Victim</td>`;
      steps.forEach(s => {
        victimRow += `
          <td style="text-align:center;font-family:monospace;font-size:11px;padding:6px 4px;color:${s.victim != null ? '#fbbf24' : '#475569'};">
            ${s.victim != null ? `Out:${s.victim}` : '·'}
          </td>
        `;
      });
      victimRow += `</tr>`;

      // Hit / Fault verdict row
      let statusRow = `<tr><td style="font-size:11px;font-weight:700;color:#e2e8f0;background:#0f172a;padding:8px 10px;position:sticky;left:0;">Verdict</td>`;
      steps.forEach(s => {
        const isHit = s.status === 'HIT';
        statusRow += `
          <td style="text-align:center;padding:6px 4px;">
            <span style="display:inline-block;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:800;
                         background:${isHit ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)'};
                         color:${isHit ? '#4ade80' : '#f87171'};
                         border:1px solid ${isHit ? '#22c55e66' : '#ef444466'};">
              ${isHit ? '🟢 HIT' : '🔴 FAULT'}
            </span>
          </td>
        `;
      });
      statusRow += `</tr>`;

      matrixBox.innerHTML = `
        <table style="border-collapse:collapse;width:100%;">
          <thead><tr>${headerRow}</tr></thead>
          <tbody>
            ${frameRows}
            ${victimRow}
            ${statusRow}
          </tbody>
        </table>
      `;
    }

    // 4. Render Side-by-Side 3-Algorithm Comparison Table
    const cmpBox = document.getElementById('pr-comparison-container');
    if (cmpBox) {
      const algos = ['FIFO', 'LRU', 'OPTIMAL'];
      const minFaults = Math.min(...algos.map(a => (cmp[a] || {}).page_faults ?? 999));

      const rows = algos.map(a => {
        const c = cmp[a] || {};
        const isBest = (c.page_faults === minFaults);
        const isActive = (a === act.algorithm);
        return `
          <tr onclick="SysRealm.setPRAlgorithm('${a}'); SysRealm.runPageReplacement();"
              style="cursor:pointer;${isActive ? 'background:rgba(59,130,246,0.18);' : ''}">
            <td>
              <strong style="color:${isActive ? '#60a5fa' : '#f8fafc'};">${a}</strong>
              ${isBest ? `<span style="background:#065f46;color:#6ee7b7;font-size:10px;padding:1px 6px;border-radius:4px;margin-left:6px;font-weight:700;">BEST</span>` : ''}
            </td>
            <td style="color:#f87171;font-weight:800;font-family:monospace;">${c.page_faults ?? 0}</td>
            <td style="color:#4ade80;font-weight:800;font-family:monospace;">${c.page_hits ?? 0}</td>
            <td>
              <div style="display:flex;align-items:center;gap:6px;">
                <div style="flex:1;height:7px;background:#1e293b;border-radius:4px;overflow:hidden;">
                  <div style="width:${c.hit_ratio || 0}%;height:100%;background:#22c55e;"></div>
                </div>
                <span style="font-family:monospace;font-size:12px;color:#cbd5e1;">${c.hit_ratio ?? 0}%</span>
              </div>
            </td>
          </tr>
        `;
      }).join('');

      cmpBox.innerHTML = `
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>Algorithm</th>
                <th>Faults (🔴)</th>
                <th>Hits (🟢)</th>
                <th>Hit Ratio %</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:8px;">
          💡 Click any algorithm row above to view its full Frame-by-Step Matrix!
        </div>
      `;
    }

    // 5. Render Step-by-Step Eviction Log
    const logBox = document.getElementById('pr-step-log');
    if (logBox) {
      logBox.innerHTML = steps.map(s => {
        const isHit = s.status === 'HIT';
        return `
          <div style="padding:6px 10px;margin-bottom:6px;border-radius:6px;font-size:12px;
                      background:rgba(15,23,42,0.7);
                      border-left:3px solid ${isHit ? '#22c55e' : '#ef4444'};">
            <strong style="color:#f8fafc;font-family:monospace;">Step ${s.step} [Ref P${s.page}]:</strong>
            <span style="color:${isHit ? '#86efac' : '#fca5a5'};margin-left:6px;">${s.reason}</span>
          </div>
        `;
      }).join('');
    }
  },

  async _ensurePagingDemoForPreset() {
    if (!this.lastMemoryState || !this.lastMemoryState.allocations || this.lastMemoryState.allocations.length === 0) {
      const res = await fetch('/api/memory/paging-demo', { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        this.selectedPagingPid = 'P1';
        this.updateMemoryPanel(data);
        this.renderPagingUI(data);
      }
    }
  },

  async refreshMemory() {
    try {
      const res = await fetch('/api/memory');
      if (!res.ok) return;
      let memory = await res.json();

      // If no allocations have internal fragmentation yet or empty, ensure rich state
      if (!memory.allocations || memory.allocations.length === 0) {
        const demoRes = await fetch('/api/memory/paging-demo', { method: 'POST' });
        if (demoRes.ok) memory = await demoRes.json();
      }

      this.updateMemoryPanel(memory);
      this.renderPagingUI(memory);

      // Run initial MMU translation if result box is empty
      const mmuBox = document.getElementById('mmu-result-box');
      if (mmuBox && !mmuBox.innerHTML.trim() && this.selectedPagingPid) {
        this.runMMUTranslation(this.selectedPagingPid, 700, true);
      }
    } catch (e) {
      console.error(e);
    }
  },

  renderPagingUI(memory) {
    this.lastMemoryState = memory;
    const paging = memory.paging || {};
    const frames = paging.frames || [];
    const pageTables = paging.page_tables || {};
    const pids = Object.keys(pageTables);

    if (!this.selectedPagingPid || !pageTables[this.selectedPagingPid]) {
      this.selectedPagingPid = pids[0] || null;
    }

    // Update KPI cards
    const framesUsedEl = document.getElementById('paging-frames-used');
    if (framesUsedEl) framesUsedEl.textContent = `${paging.used_frames || 0} / ${paging.total_frames || 32}`;
    const framesMbEl = document.getElementById('paging-frames-mb');
    if (framesMbEl) framesMbEl.textContent = `${paging.allocated_frames_mb || 0} MB`;
    const fragTotalEl = document.getElementById('paging-frag-total');
    if (fragTotalEl) fragTotalEl.textContent = `${paging.total_internal_frag_mb || 0} MB`;

    // 1. Render 32-Frame Physical RAM Grid
    const grid = document.getElementById('paging-frame-grid');
    if (grid) {
      grid.innerHTML = frames.map(f => {
        const isTargetFrame = (this.highlightedFrameNo === f.frame_no);
        const isSelectedProc = (f.allocated && f.pid === this.selectedPagingPid);
        const borderStyle = isTargetFrame
          ? '2px solid #facc15'
          : isSelectedProc
          ? `2px solid ${f.color || '#3b82f6'}`
          : f.allocated
          ? `1px solid ${f.color || '#3b82f6'}88`
          : '1px solid #334155';
        const glowStyle = isTargetFrame ? 'box-shadow: 0 0 14px rgba(250,204,21,0.55); transform: translateY(-2px);' : '';
        const bgStyle = f.allocated ? 'rgba(15, 23, 42, 0.9)' : 'rgba(15, 23, 42, 0.45)';

        if (!f.allocated) {
          return `
            <div style="background:${bgStyle};border:${borderStyle};border-radius:8px;padding:8px 10px;opacity:0.65;">
              <div style="display:flex;justify-content:space-between;font-size:11px;color:#64748b;font-family:monospace;">
                <strong>Frame ${f.frame_no}</strong>
                <span>${f.phys_start_mb}–${f.phys_end_mb}</span>
              </div>
              <div style="font-size:12px;color:#475569;margin:8px 0 6px 0;text-align:center;font-weight:600;">FREE FRAME</div>
              <div style="height:8px;background:#1e293b;border-radius:4px;"></div>
            </div>
          `;
        }

        const usedPct = Math.round((f.used_mb / (paging.page_size_mb || 512)) * 100);
        const fragPct = 100 - usedPct;
        const clickAddr = (f.page_no * (paging.page_size_mb || 512)) + Math.min(64, Math.max(0, f.used_mb - 1));

        return `
          <div onclick="SysRealm.selectFrame('${f.pid}', ${f.frame_no}, ${clickAddr})"
               style="background:${bgStyle};border:${borderStyle};${glowStyle}border-radius:8px;padding:8px 10px;cursor:pointer;transition:all 0.18s;">
            <div style="display:flex;justify-content:space-between;font-size:11px;color:#94a3b8;font-family:monospace;">
              <strong style="color:#f8fafc;">Frame ${f.frame_no}</strong>
              <span>${f.phys_start_mb}–${f.phys_end_mb}</span>
            </div>
            <div style="margin:6px 0;display:flex;justify-content:space-between;align-items:center;">
              <span style="background:${f.color};color:#fff;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:800;">
                ${f.pid} : Page ${f.page_no}
              </span>
              ${f.internal_frag_mb > 0
                ? `<span style="font-size:10px;color:#f87171;font-weight:700;" title="Internal Fragmentation on last page">-${f.internal_frag_mb}MB</span>`
                : `<span style="font-size:10px;color:#4ade80;">Full</span>`}
            </div>
            <div style="height:8px;background:#1e293b;border-radius:4px;overflow:hidden;display:flex;" title="Used: ${f.used_mb} MB | Internal Frag: ${f.internal_frag_mb} MB">
              <div style="width:${usedPct}%;background:${f.color};height:100%;"></div>
              ${fragPct > 0 ? `<div style="width:${fragPct}%;background:repeating-linear-gradient(45deg,#ef4444,#ef4444 3px,#7f1d1d 3px,#7f1d1d 6px);height:100%;"></div>` : ''}
            </div>
          </div>
        `;
      }).join('');
    }

    // 2. Render Process Tabs & Per-Process Page Table
    const tabsEl = document.getElementById('paging-proc-tabs');
    if (tabsEl) {
      tabsEl.innerHTML = pids.map(pid => {
        const pt = pageTables[pid];
        const active = (pid === this.selectedPagingPid);
        return `
          <button type="button" class="btn" onclick="SysRealm.selectPagingProcess('${pid}')"
            style="padding:6px 12px;font-size:12px;font-weight:700;border-radius:6px;
                   background:${active ? pt.color : 'rgba(15,23,42,0.8)'};
                   color:${active ? '#fff' : '#cbd5e1'};
                   border:2px solid ${pt.color};">
            ${pid}: ${pt.name} (${pt.size_mb} MB)
          </button>
        `;
      }).join('');
    }

    // Sync MMU Process Selector
    const mmuSel = document.getElementById('mmu-proc-select');
    if (mmuSel) {
      mmuSel.innerHTML = pids.map(pid => {
        const pt = pageTables[pid];
        const sel = (pid === this.selectedPagingPid) ? 'selected' : '';
        return `<option value="${pid}" ${sel}>${pid} — ${pt.name} (${pt.size_mb} MB)</option>`;
      }).join('');
    }

    const summaryEl = document.getElementById('paging-proc-summary');
    const ptBody = document.getElementById('paging-table-body');
    const activePT = this.selectedPagingPid ? pageTables[this.selectedPagingPid] : null;

    if (summaryEl && activePT) {
      summaryEl.innerHTML = `
        <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;">
          <span><strong style="color:${activePT.color};">${activePT.pid} (${activePT.name})</strong> • Logical Size: <strong>${activePT.size_mb} MB</strong></span>
          <span>Pages: <strong>⌈${activePT.size_mb} / ${activePT.page_size_mb}⌉ = ${activePT.num_pages} Pages</strong> (${activePT.allocated_frame_mb} MB)</span>
          <span style="color:${activePT.internal_frag_mb > 0 ? '#f87171' : '#4ade80'};">
            Internal Fragmentation: <strong>${activePT.internal_frag_mb} MB</strong>
          </span>
        </div>
      `;
    }

    if (ptBody) {
      if (!activePT) {
        ptBody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);">No processes allocated in RAM</td></tr>';
      } else {
        ptBody.innerHTML = activePT.entries.map(e => {
          const isHighlighted = (this.highlightedPageNo === e.page_no && this.selectedPagingPid === activePT.pid);
          const rowBg = isHighlighted ? 'background:rgba(250,204,21,0.16);' : '';
          const sampleAddr = e.logical_start_mb + Math.min(100, Math.max(0, e.used_mb - 1));
          return `
            <tr onclick="SysRealm.selectFrame('${activePT.pid}', ${e.frame_no}, ${sampleAddr})"
                style="cursor:pointer;${rowBg}">
              <td><strong style="color:${activePT.color};">Page ${e.page_no}</strong></td>
              <td style="font-family:monospace;font-size:12px;color:#94a3b8;">${e.logical_start_mb}–${e.logical_end_mb} MB</td>
              <td><span style="background:rgba(59,130,246,0.2);border:1px solid #3b82f6;color:#93c5fd;padding:2px 8px;border-radius:4px;font-family:monospace;font-weight:700;">Frame ${e.frame_no}</span></td>
              <td><span style="color:#4ade80;font-family:monospace;font-weight:700;">1 (Valid)</span></td>
              <td style="font-family:monospace;font-size:12px;color:#cbd5e1;">${e.phys_start_mb}–${e.phys_end_mb} MB</td>
              <td style="font-size:12px;">
                <span style="color:#4ade80;">${e.used_mb} MB used</span>
                ${e.internal_frag_mb > 0 ? ` / <span style="color:#f87171;font-weight:700;">${e.internal_frag_mb} MB frag</span>` : ''}
              </td>
            </tr>
          `;
        }).join('');
      }
    }

    // 3. Update bottom Process Allocation summary table
    const allocTbody = document.getElementById('memory-alloc-table');
    if (allocTbody) {
      allocTbody.innerHTML = pids.map(pid => {
        const pt = pageTables[pid];
        const frameBadges = (pt.frames_list || []).map(fn => `<code style="background:#1e293b;padding:2px 6px;border-radius:4px;margin-right:4px;color:#93c5fd;">F${fn}</code>`).join('');
        return `
          <tr>
            <td><span style="display:inline-block;width:10px;height:10px;background:${pt.color};border-radius:2px;margin-right:6px;"></span><strong>${pt.pid}</strong></td>
            <td>${pt.name}</td>
            <td><strong>${pt.size_mb} MB</strong></td>
            <td>${pt.num_pages} Pages (${pt.allocated_frame_mb} MB)</td>
            <td>${frameBadges}</td>
            <td style="color:${pt.internal_frag_mb > 0 ? '#f87171' : '#4ade80'};font-weight:700;">${pt.internal_frag_mb} MB</td>
            <td>
              <button class="btn btn-sm btn-danger" onclick="SysRealm._releaseMemory('${pt.pid}')" title="Release Pages">
                <i class="fas fa-trash"></i> Release
              </button>
            </td>
          </tr>
        `;
      }).join('');
    }
  },

  selectPagingProcess(pid) {
    this.selectedPagingPid = pid;
    this.highlightedFrameNo = null;
    this.highlightedPageNo = null;
    if (this.lastMemoryState) {
      this.renderPagingUI(this.lastMemoryState);
      this.runMMUTranslation(pid, 200, true);
    }
  },

  selectFrame(pid, frameNo, logicalAddr) {
    this.selectedPagingPid = pid;
    const addrEl = document.getElementById('mmu-logical-addr');
    if (addrEl && logicalAddr != null) addrEl.value = logicalAddr;
    this.runMMUTranslation(pid, logicalAddr, false);
  },

  async runMMUTranslation(pid, logicalAddr, silent) {
    const targetPid = pid || this.selectedPagingPid || 'P1';
    const addrInput = document.getElementById('mmu-logical-addr');
    const addr = logicalAddr != null ? logicalAddr : parseInt((addrInput || {}).value || '0', 10);
    if (addrInput && logicalAddr != null) addrInput.value = addr;

    try {
      const res = await fetch('/api/memory/translate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pid: targetPid, logical_address: addr })
      });
      const data = await res.json();
      const box = document.getElementById('mmu-result-box');
      if (!box) return;

      if (!data.success) {
        box.innerHTML = `<div style="color:#ef4444;padding:10px;">⚠️ ${data.error || 'MMU translation error'}</div>`;
        return;
      }

      this.selectedPagingPid = targetPid;
      this.highlightedFrameNo = data.frame_no;
      this.highlightedPageNo = data.page_no;
      if (this.lastMemoryState) this.renderPagingUI(this.lastMemoryState);

      if (data.status === 'PAGE_FAULT_OUT_OF_BOUNDS') {
        box.innerHTML = `
          <div style="background:rgba(127,29,29,0.35);border:1px solid #ef4444;border-left:4px solid #ef4444;border-radius:8px;padding:12px;">
            <div style="font-weight:800;color:#f87171;font-size:14px;margin-bottom:6px;">
              🔴 MMU PAGE FAULT / INVALID PAGE TRAP
            </div>
            <div style="font-family:monospace;font-size:12px;color:#fecaca;line-height:1.8;background:rgba(15,23,42,0.75);padding:8px;border-radius:6px;margin-bottom:6px;">
              1. Page Number (p) = ⌊${data.logical_address} / ${data.page_size_mb}⌋ = <strong>Page ${data.page_no}</strong><br>
              2. Offset (d)      = ${data.logical_address} mod ${data.page_size_mb} = <strong>${data.offset} MB</strong><br>
              3. Page Table Check: Page ${data.page_no} &gt; Max Page ${data.max_page_no} → <strong>Valid Bit = 0 (TRAP!)</strong>
            </div>
            <div style="font-size:12px;color:#fca5a5;">${data.message}</div>
          </div>
        `;
      } else {
        const isFrag = data.in_internal_fragmentation;
        const borderCol = isFrag ? '#f59e0b' : '#22c55e';
        const bgCol     = isFrag ? 'rgba(120,53,15,0.3)' : 'rgba(20,83,45,0.3)';
        const titleCol  = isFrag ? '#fbbf24' : '#4ade80';
        const f = data.formulas || {};

        box.innerHTML = `
          <div style="background:${bgCol};border:1px solid ${borderCol};border-left:4px solid ${borderCol};border-radius:8px;padding:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
              <span style="font-weight:800;color:${titleCol};font-size:14px;">
                ${isFrag ? '⚠️ INTERNAL FRAGMENTATION TAIL DETECTED' : '✅ MMU HARDWARE TRANSLATION COMPLETE'}
              </span>
              <span style="background:#1e293b;border:1px solid ${borderCol};color:#f8fafc;padding:2px 8px;border-radius:6px;font-family:monospace;font-size:12px;font-weight:700;">
                Phys = ${data.physical_address} MB
              </span>
            </div>

            <!-- Visual Pipeline Badges -->
            <div style="display:flex;align-items:center;justify-content:space-between;gap:6px;flex-wrap:wrap;background:rgba(15,23,42,0.85);padding:8px 10px;border-radius:6px;margin-bottom:8px;font-family:monospace;font-size:12px;">
              <span style="color:#93c5fd;">Logical: <strong>${data.logical_address} MB</strong></span>
              <span>→</span>
              <span style="color:#f59e0b;">(p=${data.page_no}, d=${data.offset})</span>
              <span>→</span>
              <span style="color:#c084fc;">Frame <strong>${data.frame_no}</strong></span>
              <span>→</span>
              <span style="color:#4ade80;font-weight:800;">Physical: ${data.physical_address} MB</span>
            </div>

            <div style="font-family:monospace;font-size:12px;color:#e2e8f0;line-height:1.8;margin-bottom:6px;">
              1. ${f.page_calc}<br>
              2. ${f.offset_calc}<br>
              3. ${f.frame_lookup}<br>
              4. <strong>${f.phys_calc}</strong>
            </div>
            <div style="font-size:12px;color:#cbd5e1;">${data.message}</div>
          </div>
        `;
      }
    } catch (e) {
      console.error('MMU translation error:', e);
    }
  },

  async _releaseMemory(pid) {
    const res = await fetch('/api/memory/release', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ pid })
    });
    const data = await res.json();
    if(window.SysAnimations) window.SysAnimations.showToast(data.success ? `Released ${pid} frames` : data.error, data.success ? 'info' : 'error');
    this.refreshMemory();
  },
  
  renderMemoryBar(allocations, totalMb) {
    const bar = document.getElementById('memory-bar');
    if (!bar) return;
    bar.innerHTML = '';
    
    allocations.forEach(alloc => {
      const pct = (alloc.size_mb / totalMb) * 100;
      const seg = document.createElement('div');
      seg.style.cssText = `width:${pct}%;background:${alloc.color || '#3498db'};height:100%;transition:width 0.5s;`;
      seg.title = `${alloc.pid}: ${alloc.size_mb}MB (${pct.toFixed(1)}%)`;
      bar.appendChild(seg);
    });

    // Free space
    const usedPct = allocations.reduce((s, a) => s + a.size_mb, 0) / totalMb * 100;
    if (usedPct < 100) {
      const freeSeg = document.createElement('div');
      freeSeg.style.cssText = `width:${100 - usedPct}%;background:#2d3748;height:100%;`;
      freeSeg.title = 'Free';
      bar.appendChild(freeSeg);
    }
  },
  
  async loadLogs() {
    try {
      const res = await fetch('/api/logs');
      const data = await res.json();
      this.renderLogs(data.logs || []);
    } catch (e) {
      console.error(e);
    }
  },
  
  renderLogs(logs) {
    const tbody = document.querySelector('#activity-logs-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    
    const eventColors = {
      'PROCESS_CREATED': '#3498db', 'PROCESS_STARTED': '#2ecc71', 'PROCESS_COMPLETED': '#27ae60',
      'PROCESS_TERMINATED': '#e74c3c', 'RESOURCE_ALLOCATED': '#f39c12', 'RESOURCE_RELEASED': '#1abc9c',
      'DEADLOCK_DETECTED': '#e74c3c', 'SCHEDULING_STARTED': '#9b59b6', 'PROCESS_WAITING': '#e67e22'
    };
    
    logs.forEach(log => {
      const color = eventColors[log.event_type] || '#64748b';
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${log.id || '-'}</td>
        <td><code>${log.session_id || '-'}</code></td>
        <td>${log.process_id || '-'}</td>
        <td><span class="badge" style="background:${color}">${log.event_type || '-'}</span></td>
        <td>T=${log.simulation_time ?? '-'}</td>
        <td>${log.description || '-'}</td>
        <td>${log.created_at ? new Date(log.created_at).toLocaleTimeString() : '-'}</td>
      `;
      tbody.appendChild(tr);
    });

    if (logs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">No logs yet. Run a simulation.</td></tr>';
    }
  },
  
  async loadHistory() {
    try {
      const res = await fetch('/api/sessions');
      const data = await res.json();
      this.renderHistory(data.sessions || []);
    } catch (e) {
      console.error(e);
    }
  },
  
  renderHistory(sessions) {
    const tbody = document.querySelector('#history-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (sessions.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted)">No history yet.</td></tr>';
      return;
    }
    
    sessions.forEach(s => {
      const tr = document.createElement('tr');
      tr.style.cursor = 'pointer';
      tr.innerHTML = `
        <td><code>${s.session_id || s.id || '-'}</code></td>
        <td>${s.created_at ? new Date(s.created_at).toLocaleDateString() : '-'}</td>
        <td><span class="badge badge-ready">${s.algorithm || '-'}</span></td>
        <td>${s.num_processes || '-'}</td>
        <td>${s.cpu_utilization != null ? s.cpu_utilization + '%' : '-'}</td>
        <td>${s.avg_waiting_time != null ? s.avg_waiting_time : '-'}</td>
        <td>${s.avg_turnaround_time != null ? s.avg_turnaround_time : '-'}</td>
        <td><strong style="color:var(--accent-green)">${s.score || 0}</strong></td>
      `;
      tr.addEventListener('click', () => this.loadSessionLogs(s.session_id || s.id));
      tbody.appendChild(tr);
    });
  },

  async loadSessionLogs(sessionId) {
    try {
      const res = await fetch(`/api/sessions/${sessionId}`);
      const data = await res.json();
      if (data.success) {
        const panel = document.getElementById('session-logs-panel');
        if (panel) {
          panel.style.display = 'block';
          this.renderLogs(data.logs || []);
        } else {
          // Switch to logs panel and show
          this.showPanel('logs');
          this.renderLogs(data.logs || []);
        }
      }
    } catch(e) { console.error(e); }
  },
  
  updateScore(delta) {
    if (delta === 0) return;
    this.score += delta;
    const el = document.getElementById('score-display');
    if (el) el.textContent = this.score;
    if (delta !== 0 && window.SysAnimations && window.SysAnimations.showScoreUpdate) {
      window.SysAnimations.showScoreUpdate(delta, delta > 0 ? 'Event completed' : 'Penalty');
    }
  },
  
  startSimTimer() {
    if (this._timerInterval) clearInterval(this._timerInterval);
    this._timerInterval = setInterval(() => {
      this.simTime++;
      const el = document.getElementById('sim-time-display');
      if (el) el.textContent = `T = ${this.simTime}`;
    }, 1000);
  },
  
  stopSimTimer() {
    if (this._timerInterval) clearInterval(this._timerInterval);
  },
  
  async fullReset() {
    try {
      const res = await fetch('/api/full/reset', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || 'System reset failed');
      }
      this.score = 0;
      this.simTime = 0;
      // Keep the simulator ready for newly-created app workloads after a reset.
      await this.createSession();
      this.updateScore(0);
      if (window.SysAnimations) window.SysAnimations.showToast('System fully reset', 'info');
      this.refreshDashboard();
      if (window.SchedulerController) window.SchedulerController.reset();
      if (window.GanttChart) window.GanttChart.reset();
      return true;
    } catch (e) {
      console.error(e);
      if (window.SysAnimations) window.SysAnimations.showToast(e.message || 'System reset failed', 'error');
      return false;
    }
  },
  
  async checkDbStatus() {
    try {
      const res = await fetch('/api/db/status');
      const data = await res.json();
      const el = document.getElementById('db-status');
      if (el) {
        el.textContent = data.connected ? '● DB Connected' : '○ DB Offline';
        el.style.color = data.connected ? 'var(--accent-green)' : 'var(--accent-orange)';
      }
      if (data.connected && window.SysAnimations) {
        window.SysAnimations.showToast(`MySQL connected: ${data.database}`, 'success', 2000);
      }
    } catch (e) {
      const el = document.getElementById('db-status');
      if (el) { el.textContent = '○ DB Offline'; el.style.color = 'var(--accent-orange)'; }
    }
  },
  
  formatSize(mb) {
    if (mb >= 1024) return (mb / 1024).toFixed(2) + ' GB';
    return mb + ' MB';
  },
  
  formatTime(seconds) {
    return seconds + 's';
  }
};

window.SysRealm = SysRealm;

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
  if (window.GanttChart) window.GanttChart.init('gantt-canvas');
  await SysRealm.init();
  if (window.SchedulerController) window.SchedulerController.init();
  if (window.ResourcesController) window.ResourcesController.init();
});
