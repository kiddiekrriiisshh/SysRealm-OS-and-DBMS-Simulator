// SysRealm Resources Controller
// Manages resource allocation/release UI and deadlock visualization

const ResourcesController = {
  resources: {},
  deadlockGraph: null,
  customProcesses: [],      // [{pid, holds, wants}]
  lastDetectResult: null,   // store for prevention strategies

  // Map HTML select values → API resource_id keys
  RESOURCE_MAP: {
    'Printer': 'PRINTER',
    'Disk':    'DISK',
    'Network': 'NETWORK',
    'IO':      'IO_DEVICE'
  },

  init() {
    this.loadResources();
    this.setupButtons();
  },

  setupButtons() {
    // Resource request button
    const btnReq = document.getElementById('btn-request-resource');
    if (btnReq) btnReq.addEventListener('click', () => {
      const pid    = (document.getElementById('req-pid')      || {}).value || '';
      const resVal = (document.getElementById('req-resource') || {}).value || '';
      if (!pid) { if(window.SysAnimations) window.SysAnimations.showToast('Enter a Process ID', 'error'); return; }
      const resId = this.RESOURCE_MAP[resVal] || resVal.toUpperCase();
      this.requestResource(pid.trim(), resId);
    });

    // Resource release button
    const btnRel = document.getElementById('btn-release-resource');
    if (btnRel) btnRel.addEventListener('click', () => {
      const pid    = (document.getElementById('rel-pid')      || {}).value || '';
      const resVal = (document.getElementById('rel-resource') || {}).value || '';
      if (!pid) { if(window.SysAnimations) window.SysAnimations.showToast('Enter a Process ID', 'error'); return; }
      const resId = this.RESOURCE_MAP[resVal] || resVal.toUpperCase();
      this.releaseResource(pid.trim(), resId);
    });

    // Deadlock scenario buttons (pre-built examples)
    const btn2p = document.getElementById('btn-deadlock-2proc');
    if (btn2p) btn2p.addEventListener('click', () => this.loadDeadlockScenario('two_process'));

    const btn3p = document.getElementById('btn-deadlock-3proc');
    if (btn3p) btn3p.addEventListener('click', () => this.loadDeadlockScenario('three_process'));

    // Legacy detect button (for pre-built scenarios)
    const btnDetect = document.getElementById('btn-deadlock-detect');
    if (btnDetect) btnDetect.addEventListener('click', () => this.detectDeadlock());

    // ── NEW: Custom process builder ──
    const btnAdd = document.getElementById('btn-dl-add-proc');
    if (btnAdd) btnAdd.addEventListener('click', () => this.addCustomProcess());

    const btnClear = document.getElementById('btn-dl-clear');
    if (btnClear) btnClear.addEventListener('click', () => this.clearCustomProcesses());

    const btnDetectCustom = document.getElementById('btn-dl-detect-custom');
    if (btnDetectCustom) btnDetectCustom.addEventListener('click', () => this.detectCustomDeadlock());

    // ── NEW: 4 strategy buttons ──
    document.querySelectorAll('.dl-strategy-btn').forEach(btn => {
      btn.addEventListener('click', () => this.applyStrategy(btn.dataset.strategy));
    });
  },


  async loadResources() {
    try {
      const res  = await fetch('/api/resources');
      const data = await res.json();
      // API returns { resources: { PRINTER: {...}, DISK: {...}, ... } }
      const resMap = data.resources || data;
      this.resources = resMap;
      this.renderResourceCards(Object.values(resMap));
    } catch (e) {
      console.error('Failed to load resources:', e);
    }
  },

  renderResourceCards(resArray) {
    const container = document.getElementById('resource-cards-container');
    if (!container) return;

    container.innerHTML = '';

    resArray.forEach(r => {
      const allocCount = r.allocated ? Object.keys(r.allocated).length : 0;
      // Use the 'available' field directly from API (already computed)
      const avail = r.available !== undefined ? r.available : (r.total - allocCount);
      const isFullyAllocated = avail <= 0;

      const card = document.createElement('div');
      card.className = 'card';
      card.style.minWidth = '180px';
      card.style.flex = '1';
      card.dataset.resourceId = r.resource_id;

      const allocBadges = r.allocated && Object.keys(r.allocated).length > 0
        ? Object.entries(r.allocated).map(([pid, count]) =>
            `<span style="background:#3b82f6;color:white;padding:2px 7px;border-radius:10px;font-size:12px;margin:2px;display:inline-block;">${pid}:${count}</span>`
          ).join('')
        : '<span style="color:var(--text-muted);font-size:13px;">None</span>';

      const waitingBadges = r.waiting_queue && r.waiting_queue.length > 0
        ? r.waiting_queue.map(pid =>
            `<span style="background:#f39c12;color:white;padding:2px 7px;border-radius:10px;font-size:12px;margin:2px;display:inline-block;">⏳${pid}</span>`
          ).join('')
        : '';

      card.innerHTML = `
        <div style="font-size:28px;margin-bottom:8px;">${r.icon || '📦'}</div>
        <h3 style="margin:0 0 8px;">${r.name || r.resource_id}</h3>
        <div style="display:flex;justify-content:space-between;margin-bottom:6px;font-size:13px;">
          <span>Total: <strong>${r.total}</strong></span>
          <span>Available: <strong style="color:${isFullyAllocated ? 'var(--accent-red,#e74c3c)' : 'var(--accent-green,#2ecc71)'};">${avail}</strong></span>
        </div>
        <div style="background:var(--bg-secondary,#1e2a3a);border-radius:6px;overflow:hidden;height:8px;margin-bottom:10px;">
          <div style="height:100%;width:${Math.round((allocCount/r.total)*100)}%;background:${isFullyAllocated ? '#e74c3c' : '#3b82f6'};transition:width 0.5s;"></div>
        </div>
        <div style="font-size:12px;margin-bottom:4px;"><strong>Allocated:</strong> ${allocBadges}</div>
        ${waitingBadges ? `<div style="font-size:12px;"><strong>Waiting:</strong> ${waitingBadges}</div>` : ''}
      `;
      container.appendChild(card);
    });
  },

  async requestResource(pid, resourceId) {
    try {
      const res  = await fetch('/api/resources/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pid, resource_id: resourceId })
      });
      const data = await res.json();
      if (data.success) {
        if (window.SysAnimations) window.SysAnimations.showToast(`✅ ${resourceId} allocated to ${pid}`, 'success');
      } else if (data.waiting) {
        if (window.SysAnimations) window.SysAnimations.showToast(`⏳ ${resourceId} busy — ${pid} added to wait queue`, 'warning');
      } else {
        if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'Request failed', 'error');
      }
      this.loadResources();
    } catch (e) {
      console.error(e);
      if (window.SysAnimations) window.SysAnimations.showToast('Network error', 'error');
    }
  },

  async releaseResource(pid, resourceId) {
    try {
      const res  = await fetch('/api/resources/release', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pid, resource_id: resourceId })
      });
      const data = await res.json();
      if (data.success) {
        const msg = data.granted_to
          ? `✅ ${resourceId} released — granted to ${data.granted_to}`
          : `✅ ${resourceId} released by ${pid}`;
        if (window.SysAnimations) window.SysAnimations.showToast(msg, 'success');
      } else {
        if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'Release failed', 'error');
      }
      this.loadResources();
    } catch (e) {
      console.error(e);
    }
  },

  async loadDeadlockScenario(type) {
    try {
      if (window.SysAnimations) window.SysAnimations.showToast(`Loading ${type === 'two_process' ? '2' : '3'}-process deadlock scenario...`, 'info');
      const res  = await fetch('/api/deadlock/scenario', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type })
      });
      const data = await res.json();
      if (data.success && data.graph) {
        this.drawRAG(data.graph);
        // Show result
        const resEl = document.getElementById('deadlock-result');
        if (resEl) resEl.innerHTML = `<span style="color:var(--text-muted)">Scenario loaded. Click <strong>Detect Deadlock</strong> to analyze.</span>`;
      } else {
        if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'Failed to load scenario', 'error');
      }
    } catch (e) {
      console.error(e);
    }
  },

  async detectDeadlock() {
    try {
      const res  = await fetch('/api/deadlock/detect', { method: 'POST' });
      const data = await res.json();
      this.showDeadlockResult(data);
      if (data.deadlock && data.cycle && data.cycle.length > 0) {
        const svgEl = document.getElementById('deadlock-svg');
        if (svgEl) this.highlightCycle(data.cycle, svgEl);
      }
    } catch (e) {
      console.error(e);
    }
  },

  drawRAG(graphData) {
    const container = document.getElementById('deadlock-svg');
    if (!container) return;

    container.innerHTML = '';

    // Fixed canvas size — don't rely on clientHeight which may be 0 before paint
    const W = 700;
    const H = 380;

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width',   '100%');
    svg.setAttribute('height',  '100%');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    svg.style.display = 'block';

    // Arrow markers
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    defs.innerHTML = `
      <marker id="arr-normal" viewBox="0 0 10 10" refX="9" refY="5"
              markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8"/>
      </marker>
      <marker id="arr-red" viewBox="0 0 10 10" refX="9" refY="5"
              markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#ef4444"/>
      </marker>
    `;
    svg.appendChild(defs);

    // API returns { nodes: [{id, type, label, ...}], edges: [...] }
    const allNodes  = graphData.nodes  || [];
    const edges     = graphData.edges  || [];

    // Split nodes into processes (circles) and resources (rectangles)
    const processes = allNodes.filter(n => n.type === 'process');
    const resources = allNodes.filter(n => n.type === 'resource');

    const positions = {};
    const pCount = processes.length;
    const rCount = resources.length;

    // Processes on LEFT column, resources on RIGHT column — clear & spread out
    const leftX  = W * 0.22;
    const rightX = W * 0.78;
    const topPad = 70;
    const botPad = 70;

    processes.forEach((p, i) => {
      const y = pCount === 1
        ? H / 2
        : topPad + (i / (pCount - 1)) * (H - topPad - botPad);
      positions[p.id] = { x: leftX, y };
    });

    resources.forEach((r, i) => {
      const y = rCount === 1
        ? H / 2
        : topPad + (i / (rCount - 1)) * (H - topPad - botPad);
      positions[r.id] = { x: rightX, y };
    });

    // Draw edges FIRST (behind nodes)
    edges.forEach(edge => {
      const from = positions[edge.from];
      const to   = positions[edge.to];
      if (!from || !to) return;

      // Slightly offset overlapping parallel edges
      const dx = to.x - from.x, dy = to.y - from.y;
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      const ox = -dy / len * 6, oy = dx / len * 6;

      const isReq = edge.type === 'request';
      const line  = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', from.x + ox);
      line.setAttribute('y1', from.y + oy);
      line.setAttribute('x2', to.x + ox);
      line.setAttribute('y2', to.y + oy);
      line.setAttribute('stroke', '#94a3b8');
      line.setAttribute('stroke-width', '2');
      line.setAttribute('id', `edge-${edge.from}-${edge.to}`);
      if (isReq) line.setAttribute('stroke-dasharray', '8,4');
      line.setAttribute('marker-end', 'url(#arr-normal)');
      svg.appendChild(line);

      // Edge label (count)
      if (edge.count && edge.count > 1) {
        const midX = (from.x + to.x) / 2 + ox;
        const midY = (from.y + to.y) / 2 + oy;
        const lbl  = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        lbl.setAttribute('x', midX); lbl.setAttribute('y', midY - 6);
        lbl.setAttribute('text-anchor', 'middle');
        lbl.setAttribute('fill', '#94a3b8'); lbl.setAttribute('font-size', '11');
        lbl.textContent = `×${edge.count}`;
        svg.appendChild(lbl);
      }
    });

    // Draw PROCESS nodes (blue circles)
    processes.forEach(p => {
      const { x, y } = positions[p.id];
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('id', `node-${p.id}`);

      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', x); circle.setAttribute('cy', y); circle.setAttribute('r', 32);
      circle.setAttribute('fill', '#1d4ed8');
      circle.setAttribute('stroke', '#3b82f6'); circle.setAttribute('stroke-width', '2');
      g.appendChild(circle);

      const lbl1 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      lbl1.setAttribute('x', x); lbl1.setAttribute('y', y - 6);
      lbl1.setAttribute('text-anchor', 'middle');
      lbl1.setAttribute('fill', 'white'); lbl1.setAttribute('font-size', '13');
      lbl1.setAttribute('font-weight', 'bold');
      lbl1.textContent = p.id;
      g.appendChild(lbl1);

      const lbl2 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      lbl2.setAttribute('x', x); lbl2.setAttribute('y', y + 13);
      lbl2.setAttribute('text-anchor', 'middle');
      lbl2.setAttribute('fill', '#bfdbfe'); lbl2.setAttribute('font-size', '10');
      lbl2.textContent = p.label || '';
      g.appendChild(lbl2);

      svg.appendChild(g);
    });

    // Draw RESOURCE nodes (amber rectangles)
    resources.forEach(r => {
      const { x, y } = positions[r.id];
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('id', `node-${r.id}`);

      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', x - 45); rect.setAttribute('y', y - 28);
      rect.setAttribute('width', 90); rect.setAttribute('height', 56);
      rect.setAttribute('rx', 8);
      rect.setAttribute('fill', '#78350f');
      rect.setAttribute('stroke', '#f59e0b'); rect.setAttribute('stroke-width', '2');
      g.appendChild(rect);

      const lbl1 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      lbl1.setAttribute('x', x); lbl1.setAttribute('y', y - 6);
      lbl1.setAttribute('text-anchor', 'middle');
      lbl1.setAttribute('fill', 'white'); lbl1.setAttribute('font-size', '12');
      lbl1.setAttribute('font-weight', 'bold');
      lbl1.textContent = r.id;
      g.appendChild(lbl1);

      const lbl2 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      lbl2.setAttribute('x', x); lbl2.setAttribute('y', y + 12);
      lbl2.setAttribute('text-anchor', 'middle');
      lbl2.setAttribute('fill', '#fde68a'); lbl2.setAttribute('font-size', '10');
      lbl2.textContent = r.label || r.id;
      g.appendChild(lbl2);

      // Available dot indicator
      const avail = r.available != null ? r.available : 1;
      const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      dot.setAttribute('cx', x + 36); dot.setAttribute('cy', y - 22);
      dot.setAttribute('r', 6);
      dot.setAttribute('fill', avail > 0 ? '#22c55e' : '#ef4444');
      g.appendChild(dot);

      svg.appendChild(g);
    });

    // Column labels
    const mkLabel = (text, x, y) => {
      const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t.setAttribute('x', x); t.setAttribute('y', y);
      t.setAttribute('text-anchor', 'middle');
      t.setAttribute('fill', '#64748b'); t.setAttribute('font-size', '12');
      t.setAttribute('font-weight', 'bold');
      t.textContent = text;
      svg.appendChild(t);
    };
    mkLabel('PROCESSES', leftX,  30);
    mkLabel('RESOURCES', rightX, 30);

    // Legend at bottom
    const leg = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    leg.setAttribute('x', W / 2); leg.setAttribute('y', H - 8);
    leg.setAttribute('text-anchor', 'middle');
    leg.setAttribute('fill', '#64748b'); leg.setAttribute('font-size', '11');
    leg.textContent = '●  Process    ▬  Resource    ───  Allocation    - - -  Request';
    svg.appendChild(leg);

    container.appendChild(svg);
  },

  highlightCycle(cycle, container) {

    const svg = container.querySelector('svg') || container;
    for (let i = 0; i < cycle.length; i++) {
      const from = cycle[i];
      const to   = cycle[(i + 1) % cycle.length];

      // Try both edge directions
      const edge = svg.querySelector(`#edge-${from}-${to}`) || svg.querySelector(`#edge-${to}-${from}`);
      if (edge) {
        edge.setAttribute('stroke', '#e74c3c');
        edge.setAttribute('stroke-width', '3');
        edge.setAttribute('marker-end', 'url(#arr-red)');
      }

      // Highlight process nodes in cycle
      const node = svg.querySelector(`#node-${from}`);
      if (node) {
        const shape = node.querySelector('circle') || node.querySelector('rect');
        if (shape) { shape.setAttribute('stroke', '#e74c3c'); shape.setAttribute('stroke-width', '4'); }
      }
    }
  },

  showDeadlockResult(result) {
    const resEl = document.getElementById('deadlock-result');
    if (!resEl) return;

    if (result.deadlock) {
      const cycle = (result.cycle || result.deadlocked_processes || []).join(' → ');
      resEl.innerHTML = `
        <div style="color:#e74c3c;font-size:18px;margin-bottom:10px;">🔴 DEADLOCK DETECTED!</div>
        <div style="color:#fca5a5;margin-bottom:8px;">Circular wait cycle:</div>
        <div style="background:#450a0a;padding:10px;border-radius:6px;font-family:monospace;color:#fca5a5;">${cycle}</div>
        <div style="color:#94a3b8;margin-top:10px;font-size:13px;">${result.explanation || ''}</div>
      `;
      if (window.SysAnimations) window.SysAnimations.showToast('🔴 Deadlock detected!', 'error');
    } else {
      resEl.innerHTML = `
        <div style="color:#22c55e;font-size:18px;margin-bottom:10px;">✅ No Deadlock</div>
        <div style="color:#86efac;">System is in a safe state. All processes can complete.</div>
        <div style="color:#94a3b8;margin-top:10px;font-size:13px;">${result.explanation || ''}</div>
      `;
      if (window.SysAnimations) window.SysAnimations.showToast('✅ System is safe', 'success');
    }
  },

  // ── Custom process builder methods ──

  addCustomProcess() {
    const pidEl   = document.getElementById('dl-pid');
    const holdsEl = document.getElementById('dl-holds');
    const wantsEl = document.getElementById('dl-wants');
    if (!pidEl) return;

    const pid   = pidEl.value.trim().toUpperCase();
    const holds = holdsEl ? holdsEl.value : '';
    const wants = wantsEl ? wantsEl.value : '';

    if (!pid) {
      if (window.SysAnimations) window.SysAnimations.showToast('Enter a Process ID (e.g. P1)', 'error');
      return;
    }
    if (!holds && !wants) {
      if (window.SysAnimations) window.SysAnimations.showToast('Select at least one resource (holds or wants)', 'error');
      return;
    }
    if (holds === wants && holds !== '') {
      if (window.SysAnimations) window.SysAnimations.showToast('A process cannot hold and want the same resource', 'error');
      return;
    }
    if (this.customProcesses.find(p => p.pid === pid)) {
      if (window.SysAnimations) window.SysAnimations.showToast(`Process ${pid} already added`, 'warning');
      return;
    }

    this.customProcesses.push({ pid, holds, wants });
    this.renderCustomProcessList();
    this.updateOSResourcePanel();

    // Clear inputs
    pidEl.value = '';
    if (holdsEl) holdsEl.value = '';
    if (wantsEl) wantsEl.value = '';

    if (window.SysAnimations) window.SysAnimations.showToast(`✅ Process ${pid} added`, 'success');
  },

  clearCustomProcesses() {
    this.customProcesses = [];
    this.lastDetectResult = null;
    this.renderCustomProcessList();
    this.updateOSResourcePanel();

    const resEl = document.getElementById('deadlock-result');
    if (resEl) resEl.innerHTML = 'Add processes and click <strong>Detect Deadlock</strong>.';

    const container = document.getElementById('deadlock-svg');
    if (container) container.innerHTML = '';

    const stratRes = document.getElementById('dl-strategy-result');
    if (stratRes) stratRes.style.display = 'none';

    if (window.SysAnimations) window.SysAnimations.showToast('Cleared all processes', 'info');
  },

  renderCustomProcessList() {
    const list = document.getElementById('dl-process-list');
    if (!list) return;
    const hint = document.getElementById('dl-empty-hint');
    if (hint) hint.style.display = this.customProcesses.length === 0 ? 'inline' : 'none';

    // Remove existing process tags
    list.querySelectorAll('.dl-proc-tag').forEach(t => t.remove());

    const ICONS = { PRINTER: '🖨️', DISK: '💾', NETWORK: '🌐', IO_DEVICE: '⌨️' };

    this.customProcesses.forEach((proc, i) => {
      const tag = document.createElement('div');
      tag.className = 'dl-proc-tag';
      tag.style.cssText = 'background:var(--card-bg);border:1px solid var(--primary);border-radius:8px;padding:6px 12px;font-size:13px;display:flex;align-items:center;gap:8px;';
      tag.innerHTML = `
        <strong style="color:var(--primary);">${proc.pid}</strong>
        ${proc.holds ? `<span>holds ${ICONS[proc.holds] || ''} ${proc.holds}</span>` : ''}
        ${proc.holds && proc.wants ? '<span style="color:var(--text-muted)">→</span>' : ''}
        ${proc.wants ? `<span>wants ${ICONS[proc.wants] || ''} ${proc.wants}</span>` : ''}
        <button onclick="ResourcesController.removeCustomProcess(${i})" style="background:none;border:none;color:#e74c3c;cursor:pointer;font-size:16px;padding:0;">✕</button>
      `;
      list.appendChild(tag);
    });
  },

  removeCustomProcess(index) {
    this.customProcesses.splice(index, 1);
    this.renderCustomProcessList();
    this.updateOSResourcePanel();
  },

  updateOSResourcePanel() {
    const resources = ['PRINTER', 'DISK', 'NETWORK', 'IO_DEVICE'];
    const held = {};
    this.customProcesses.forEach(p => {
      if (p.holds) held[p.holds] = (held[p.holds] || 0) + 1;
    });

    resources.forEach(r => {
      const el = document.getElementById(`dl-res-${r}`);
      if (!el) return;
      const totalHeld = held[r] || 0;
      const avail = Math.max(0, 1 - totalHeld);
      el.textContent = `Available: ${avail}`;
      el.style.color = avail > 0 ? 'var(--success, #22c55e)' : '#ef4444';
    });
  },

  async detectCustomDeadlock() {
    if (this.customProcesses.length === 0) {
      if (window.SysAnimations) window.SysAnimations.showToast('Add at least 2 processes first', 'warning');
      return;
    }

    try {
      const res  = await fetch('/api/deadlock/custom', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ processes: this.customProcesses })
      });
      const data = await res.json();

      // Store for strategy use
      this.lastDetectResult = data;

      // Draw graph
      if (data.graph) this.drawRAG(data.graph);

      // Show result
      this.showDeadlockResult(data);

      // Highlight cycle if deadlock
      if (data.deadlock && data.cycle && data.cycle.length) {
        const container = document.getElementById('deadlock-svg');
        if (container) this.highlightCycle(data.cycle, container);
      }

      // Hide previous strategy result
      const stratRes = document.getElementById('dl-strategy-result');
      if (stratRes) stratRes.style.display = 'none';

    } catch (e) {
      console.error('Custom detect error:', e);
      if (window.SysAnimations) window.SysAnimations.showToast('Detection failed: ' + e.message, 'error');
    }
  },

  async applyStrategy(strategy) {
    if (!this.lastDetectResult) {
      if (window.SysAnimations) window.SysAnimations.showToast('⚠️ Run "Detect Deadlock" first to analyze your processes', 'warning');
      return;
    }

    try {
      const res  = await fetch('/api/deadlock/prevent', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          strategy,
          processes:  this.lastDetectResult.processes  || this.customProcesses,
          allocation: this.lastDetectResult.allocation || {},
          request:    this.lastDetectResult.request    || {},
          available:  this.lastDetectResult.available  || {}
        })
      });
      const data = await res.json();

      if (data.success) {
        this.showStrategyResult(data);
      } else {
        if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'Strategy failed', 'error');
      }
    } catch (e) {
      console.error('Strategy error:', e);
      if (window.SysAnimations) window.SysAnimations.showToast('Error: ' + e.message, 'error');
    }
  },

  showStrategyResult(data) {
    const panel = document.getElementById('dl-strategy-result');
    const title = document.getElementById('dl-strategy-title');
    const steps = document.getElementById('dl-strategy-steps');
    if (!panel || !steps) return;

    title.textContent = data.title || data.strategy;
    steps.innerHTML   = '';

    (data.steps || []).forEach(step => {
      const li = document.createElement('li');
      li.style.marginBottom = '6px';
      li.textContent = step;

      // Color code by emoji prefix
      if (step.startsWith('✅')) li.style.color = '#22c55e';
      else if (step.startsWith('🔴') || step.startsWith('❌')) li.style.color = '#ef4444';
      else if (step.startsWith('⏳') || step.startsWith('⚠️')) li.style.color = '#eab308';
      else if (step.startsWith('🟠')) li.style.color = '#f97316';
      else if (step.startsWith('🟢')) li.style.color = '#22c55e';

      steps.appendChild(li);
    });

    panel.style.display = 'block';
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    const resolved = data.resolved;
    if (window.SysAnimations) {
      window.SysAnimations.showToast(
        resolved ? `✅ ${data.title} — Deadlock Resolved` : `⚠️ ${data.title} — Partial prevention`,
        resolved ? 'success' : 'warning'
      );
    }
  }
};

window.ResourcesController = ResourcesController;

