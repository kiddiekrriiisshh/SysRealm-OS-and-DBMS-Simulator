/**
 * SysRealm Disk Scheduling Controller
 * Handles FCFS, SSTF, SCAN, C-SCAN, LOOK, C-LOOK simulations,
 * canvas textbook seek graph rendering, step animation, and comparison metrics.
 */

const DiskController = {
  currentAlgo: 'FCFS',
  currentDirection: 'right',
  currentData: null,
  animationTimer: null,

  init() {
    this.setupListeners();
    // Auto-run textbook demo on startup
    this.runSimulation();
  },

  setupListeners() {
    // Algo tab buttons
    document.querySelectorAll('#disk-algo-tabs .algo-tab').forEach(tab => {
      tab.addEventListener('click', (e) => {
        document.querySelectorAll('#disk-algo-tabs .algo-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        this.currentAlgo = tab.getAttribute('data-algo') || 'FCFS';
        this.updateDirectionVisibility();
        this.runSimulation();
      });
    });

    // Direction buttons
    const dirRight = document.getElementById('disk-dir-right');
    const dirLeft = document.getElementById('disk-dir-left');
    if (dirRight) {
      dirRight.addEventListener('click', () => {
        this.currentDirection = 'right';
        dirRight.classList.add('active');
        if (dirLeft) dirLeft.classList.remove('active');
        this.runSimulation();
      });
    }
    if (dirLeft) {
      dirLeft.addEventListener('click', () => {
        this.currentDirection = 'left';
        dirLeft.classList.add('active');
        if (dirRight) dirRight.classList.remove('active');
        this.runSimulation();
      });
    }

    // Run button
    const btnSim = document.getElementById('btn-disk-run');
    if (btnSim) btnSim.addEventListener('click', () => this.runSimulation());

    // Compare button
    const btnCmp = document.getElementById('btn-disk-compare');
    if (btnCmp) btnCmp.addEventListener('click', () => this.runCompareAll());

    // Presets
    const pGalvin = document.getElementById('disk-preset-galvin');
    if (pGalvin) {
      pGalvin.addEventListener('click', () => {
        document.getElementById('disk-head').value = '53';
        document.getElementById('disk-tracks').value = '200';
        document.getElementById('disk-requests').value = '98, 183, 37, 122, 14, 124, 65, 67';
        this.runSimulation();
      });
    }

    const pCluster = document.getElementById('disk-preset-cluster');
    if (pCluster) {
      pCluster.addEventListener('click', () => {
        document.getElementById('disk-head').value = '100';
        document.getElementById('disk-tracks').value = '200';
        document.getElementById('disk-requests').value = '95, 105, 90, 110, 85, 115, 102, 98';
        this.runSimulation();
      });
    }

    const pExtreme = document.getElementById('disk-preset-extreme');
    if (pExtreme) {
      pExtreme.addEventListener('click', () => {
        document.getElementById('disk-head').value = '50';
        document.getElementById('disk-tracks').value = '200';
        document.getElementById('disk-requests').value = '10, 190, 20, 180, 30, 170, 5, 195';
        this.runSimulation();
      });
    }

    const pRandom = document.getElementById('disk-preset-random');
    if (pRandom) {
      pRandom.addEventListener('click', () => {
        const total = parseInt(document.getElementById('disk-tracks').value || '200', 10);
        const head = Math.floor(Math.random() * (total - 20)) + 10;
        const reqs = [];
        for (let i = 0; i < 8; i++) {
          reqs.push(Math.floor(Math.random() * (total - 10)) + 5);
        }
        document.getElementById('disk-head').value = head;
        document.getElementById('disk-requests').value = reqs.join(', ');
        this.runSimulation();
      });
    }

    // Auto-resize canvas on window resize
    window.addEventListener('resize', () => {
      if (this.currentData) this.drawSeekGraph(this.currentData.sequence, this.currentData.total_tracks);
    });
  },

  updateDirectionVisibility() {
    const dirWrap = document.getElementById('disk-dir-wrapper');
    if (!dirWrap) return;
    const needsDir = ['SCAN', 'C-SCAN', 'LOOK', 'C-LOOK'].includes(this.currentAlgo);
    dirWrap.style.opacity = needsDir ? '1' : '0.4';
    dirWrap.title = needsDir ? 'Head movement direction' : 'Direction is only used by SCAN, C-SCAN, LOOK, C-LOOK';
  },

  async runSimulation() {
    const head = parseInt(document.getElementById('disk-head')?.value || '53', 10);
    const total_tracks = parseInt(document.getElementById('disk-tracks')?.value || '200', 10);
    const reqStr = (document.getElementById('disk-requests')?.value || '98, 183, 37, 122, 14, 124, 65, 67').trim();

    try {
      const res = await fetch('/api/disk/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          algorithm: this.currentAlgo,
          head: head,
          total_tracks: total_tracks,
          direction: this.currentDirection,
          requests: reqStr
        })
      });

      const data = await res.json();
      if (!data.success) {
        if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'Disk simulation error', 'error');
        return;
      }

      this.currentData = data;
      this.renderUI(data);
      if (window.SysAnimations) {
        window.SysAnimations.showToast(`${data.name} simulated: ${data.total_seek} cylinders total seek`, 'success');
      }
    } catch (e) {
      console.error('Disk simulate error:', e);
    }
  },

  async runCompareAll() {
    const head = parseInt(document.getElementById('disk-head')?.value || '53', 10);
    const total_tracks = parseInt(document.getElementById('disk-tracks')?.value || '200', 10);
    const reqStr = (document.getElementById('disk-requests')?.value || '98, 183, 37, 122, 14, 124, 65, 67').trim();

    try {
      const res = await fetch('/api/disk/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          head: head,
          total_tracks: total_tracks,
          direction: this.currentDirection,
          requests: reqStr
        })
      });

      const data = await res.json();
      if (!data.success) {
        if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'Comparison error', 'error');
        return;
      }

      this.renderComparisonBars(data.comparison, data.best_algorithm);
      const cmpCard = document.getElementById('disk-comparison-card');
      if (cmpCard) cmpCard.scrollIntoView({ behavior: 'smooth' });
    } catch (e) {
      console.error('Disk compare error:', e);
    }
  },

  renderUI(data) {
    // 1. Metrics Cards
    const elTotal = document.getElementById('disk-stat-total');
    const elAvg = document.getElementById('disk-stat-avg');
    const elCount = document.getElementById('disk-stat-count');
    const elAlgoName = document.getElementById('disk-stat-algo');
    const elExp = document.getElementById('disk-explanation');

    if (elTotal) elTotal.textContent = `${data.total_seek} cyl`;
    if (elAvg) elAvg.textContent = `${data.avg_seek} cyl/req`;
    if (elCount) elCount.textContent = `${data.steps ? data.steps.length : 0}`;
    if (elAlgoName) elAlgoName.textContent = data.name;
    if (elExp) elExp.textContent = data.explanation;

    // 2. Physical Cylinder Arm Slider
    this.renderCylinderBar(data.sequence, data.initial_head, data.total_tracks);

    // 3. Textbook Seek Graph (Canvas)
    this.drawSeekGraph(data.sequence, data.total_tracks);

    // 4. Mathematical Steps Table
    this.renderStepsTable(data.steps);

    // 5. Comparison Bars
    if (data.all_algorithms) {
      this.renderComparisonBars(data.all_algorithms, data.best_algorithm);
    }
  },

  renderCylinderBar(sequence, initialHead, totalTracks) {
    const bar = document.getElementById('disk-cylinder-track');
    const headMarker = document.getElementById('disk-head-pointer');
    const headLabel = document.getElementById('disk-head-cyl-val');
    if (!bar) return;

    // Clear old request markers
    bar.querySelectorAll('.disk-req-dot').forEach(d => d.remove());

    const maxTrack = totalTracks - 1;
    // Add dots for each track in sequence
    const uniqueTracks = Array.from(new Set(sequence));
    uniqueTracks.forEach(t => {
      const pct = (t / maxTrack) * 100;
      const dot = document.createElement('div');
      dot.className = 'disk-req-dot';
      dot.style.position = 'absolute';
      dot.style.left = `${pct}%`;
      dot.style.top = '50%';
      dot.style.transform = 'translate(-50%, -50%)';
      dot.style.width = '8px';
      dot.style.height = '8px';
      dot.style.borderRadius = '50%';
      dot.style.background = t === initialHead ? '#22c55e' : '#38bdf8';
      dot.style.boxShadow = `0 0 8px ${t === initialHead ? '#22c55e' : '#38bdf8'}`;
      dot.title = `Cylinder ${t}`;
      bar.appendChild(dot);
    });

    // Animate head pointer along the sequence
    if (headMarker) {
      if (this.animationTimer) clearInterval(this.animationTimer);
      let stepIdx = 0;
      const animateStep = () => {
        if (stepIdx >= sequence.length) {
          stepIdx = sequence.length - 1;
          return;
        }
        const cyl = sequence[stepIdx];
        const pct = (cyl / maxTrack) * 100;
        headMarker.style.left = `${pct}%`;
        if (headLabel) headLabel.textContent = `Head: ${cyl}`;
        stepIdx++;
      };

      animateStep();
      this.animationTimer = setInterval(animateStep, 650);
    }
  },

  drawSeekGraph(sequence, totalTracks) {
    const canvas = document.getElementById('disk-seek-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    // High DPI scaling
    const rect = canvas.getBoundingClientRect();
    const width = rect.width || 720;
    const height = 360;
    canvas.width = width * window.devicePixelRatio;
    canvas.height = height * window.devicePixelRatio;
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

    ctx.clearRect(0, 0, width, height);

    const padLeft = 45;
    const padRight = 35;
    const padTop = 35;
    const padBottom = 35;
    const plotWidth = width - padLeft - padRight;
    const plotHeight = height - padTop - padBottom;
    const maxTrack = totalTracks - 1;

    // Background Grid
    ctx.strokeStyle = 'rgba(71, 85, 105, 0.18)';
    ctx.lineWidth = 1;

    // Vertical cylinder guide lines (every 25 tracks or 8 intervals)
    const intervals = 8;
    for (let i = 0; i <= intervals; i++) {
      const trackVal = Math.round((i / intervals) * maxTrack);
      const x = padLeft + (trackVal / maxTrack) * plotWidth;
      ctx.beginPath();
      ctx.moveTo(x, padTop);
      ctx.lineTo(x, height - padBottom);
      ctx.stroke();

      // Track label on top
      ctx.fillStyle = '#64748b';
      ctx.font = '10px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(trackVal, x, padTop - 12);
    }

    // Step coordinates
    const points = [];
    const stepCount = sequence.length;
    for (let i = 0; i < stepCount; i++) {
      const cyl = sequence[i];
      const x = padLeft + (cyl / maxTrack) * plotWidth;
      const y = padTop + (i / Math.max(1, stepCount - 1)) * plotHeight;
      points.push({ x, y, cyl, step: i });
    }

    // Draw Seek Path Lines
    ctx.beginPath();
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 2.5;
    ctx.shadowColor = 'rgba(56, 189, 248, 0.5)';
    ctx.shadowBlur = 10;

    for (let i = 0; i < points.length; i++) {
      if (i === 0) ctx.moveTo(points[i].x, points[i].y);
      else ctx.lineTo(points[i].x, points[i].y);
    }
    ctx.stroke();
    ctx.shadowBlur = 0; // Reset shadow

    // Draw Points & Labels
    points.forEach((pt, i) => {
      // Step number on left axis
      ctx.fillStyle = '#94a3b8';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(i === 0 ? 'Start' : `S${i}`, padLeft - 10, pt.y + 3);

      // Node circle
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, i === 0 ? 6 : 4.5, 0, Math.PI * 2);
      ctx.fillStyle = i === 0 ? '#22c55e' : (pt.cyl === 0 || pt.cyl === maxTrack ? '#f59e0b' : '#38bdf8');
      ctx.fill();
      ctx.strokeStyle = '#0f172a';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Cylinder value label beside point
      ctx.fillStyle = '#e2e8f0';
      ctx.font = 'bold 10px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(pt.cyl, pt.x + 8, pt.y + 3);
    });

    // Axis captions
    ctx.fillStyle = '#94a3b8';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Cylinder / Track Number ⟶', width / 2, height - 10);
  },

  renderStepsTable(steps) {
    const tbody = document.getElementById('disk-steps-table');
    if (!tbody) return;

    if (!steps || steps.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:16px;">No steps available.</td></tr>';
      return;
    }

    tbody.innerHTML = steps.map(s => {
      const formula = `|${s.to_track} - ${s.from_track}| = ${s.distance}`;
      const statusBadge = s.serviced
        ? `<span class="badge" style="background:rgba(34,197,94,0.18);border:1px solid rgba(34,197,94,0.4);color:#4ade80;">Serviced</span>`
        : `<span class="badge" style="background:rgba(245,158,11,0.18);border:1px solid rgba(245,158,11,0.4);color:#fbbf24;">Boundary / Jump</span>`;

      return `
        <tr>
          <td style="font-weight:700;color:var(--accent-blue);">#${s.step}</td>
          <td><code style="font-size:12px;">${s.from_track} ⟶ ${s.to_track}</code></td>
          <td style="color:#e2e8f0;"><code>${formula}</code></td>
          <td style="font-weight:700;color:#38bdf8;">${s.cumulative} cyl</td>
          <td>${statusBadge}</td>
        </tr>
      `;
    }).join('');
  },

  renderComparisonBars(chartData, bestAlgo) {
    const container = document.getElementById('disk-comparison-bars');
    if (!container) return;

    if (!chartData || chartData.length === 0) {
      container.innerHTML = '<div style="color:var(--text-muted);padding:16px;">No comparison data.</div>';
      return;
    }

    const maxSeek = Math.max(...chartData.map(d => d.total_seek), 1);

    container.innerHTML = chartData.map(d => {
      const pct = Math.max(8, Math.round((d.total_seek / maxSeek) * 100));
      const isWinner = d.algorithm === bestAlgo;
      const barColor = isWinner
        ? 'linear-gradient(90deg, #10b981, #22c55e)'
        : 'linear-gradient(90deg, #3b82f6, #06b6d4)';
      const winnerBadge = isWinner
        ? `<span class="badge" style="background:rgba(34,197,94,0.2);color:#4ade80;border:1px solid rgba(34,197,94,0.4);margin-left:8px;">🏆 Optimal</span>`
        : '';

      return `
        <div style="margin-bottom:12px;">
          <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px;">
            <span style="font-weight:700;color:#e2e8f0;">
              ${d.name} (${d.algorithm}) ${winnerBadge}
            </span>
            <span style="font-weight:700;color:${isWinner ? '#4ade80' : '#38bdf8'};">
              ${d.total_seek} cyl (${d.avg_seek} cyl/req)
            </span>
          </div>
          <div style="height:10px;background:rgba(30,41,59,0.8);border-radius:99px;overflow:hidden;">
            <div style="width:${pct}%;height:100%;background:${barColor};border-radius:99px;transition:width 0.6s ease;"></div>
          </div>
        </div>
      `;
    }).join('');
  }
};

document.addEventListener('DOMContentLoaded', () => {
  DiskController.init();
});
