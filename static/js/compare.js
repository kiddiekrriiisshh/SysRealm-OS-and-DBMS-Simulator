// SysRealm — Algorithm Comparison Report
// Draws bar charts with plain Canvas API (no external chart library)

const CompareController = {
  data: null,
  activeAlgo: 'FCFS',

  COLORS: {
    FCFS:       '#3b82f6',
    SJF:        '#22c55e',
    Priority:   '#f59e0b',
    RoundRobin: '#e74c3c',
  },

  ALGO_LABELS: {
    FCFS:       'FCFS',
    SJF:        'SJF',
    Priority:   'Priority',
    RoundRobin: 'Round Robin',
  },

  init() {
    const btnRun = document.getElementById('btn-run-compare');
    if (btnRun) btnRun.addEventListener('click', () => this.runComparison());

    document.querySelectorAll('.cmp-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.cmp-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.activeAlgo = btn.dataset.algo;
        if (this.data) this.renderProcessTable(this.activeAlgo);
      });
    });
  },

  async runComparison() {
    const quantum = parseInt(document.getElementById('cmp-quantum') ? document.getElementById('cmp-quantum').value : 2, 10);
    const loadEl  = document.getElementById('cmp-loading');
    const resEl   = document.getElementById('cmp-results');
    const btnRun  = document.getElementById('btn-run-compare');

    if (loadEl) loadEl.style.display = 'block';
    if (resEl)  resEl.style.display  = 'none';
    if (btnRun) btnRun.disabled = true;

    try {
      const res  = await fetch('/api/scheduler/compare', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ quantum: quantum })
      });
      const data = await res.json();

      if (!data.success) {
        if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'Comparison failed', 'error');
        return;
      }

      this.data = data;
      this.render(data);
      if (resEl) resEl.style.display = 'block';
      if (window.SysAnimations) window.SysAnimations.showToast('Comparison complete!', 'success');

    } catch (e) {
      console.error('Compare error:', e);
      if (window.SysAnimations) window.SysAnimations.showToast('Error: ' + e.message, 'error');
    } finally {
      if (loadEl) loadEl.style.display = 'none';
      if (btnRun) btnRun.disabled = false;
    }
  },

  render(data) {
    this.renderRecommendation(data);
    this.renderTable(data);
    this.renderCharts(data);
    this.renderProcessTable(this.activeAlgo);
  },

  renderRecommendation(data) {
    var el = document.getElementById('cmp-recommendation');
    if (!el) return;
    var winner = (data.best && data.best.overall) || '';
    var color  = this.COLORS[winner] || '#22c55e';
    el.innerHTML =
      '<div style="display:flex;align-items:flex-start;gap:14px;">' +
        '<div style="font-size:36px;">🏆</div>' +
        '<div>' +
          '<div style="font-size:18px;font-weight:bold;color:' + color + ';margin-bottom:6px;">' +
            'Best Algorithm: ' + (this.ALGO_LABELS[winner] || winner) +
          '</div>' +
          '<div style="color:var(--text-muted);line-height:1.7;">' + (data.recommendation || '') + '</div>' +
          '<div style="margin-top:10px;display:flex;gap:14px;flex-wrap:wrap;font-size:13px;">' +
            this._bestBadge('Lowest Avg Wait',  data.best && data.best.avg_waiting_time) +
            this._bestBadge('Lowest Avg TAT',   data.best && data.best.avg_turnaround_time) +
            this._bestBadge('Highest CPU %',    data.best && data.best.cpu_utilization) +
            this._bestBadge('Best Throughput',  data.best && data.best.throughput) +
          '</div>' +
        '</div>' +
      '</div>';
  },

  _bestBadge: function(label, algoKey) {
    if (!algoKey) return '';
    var color = this.COLORS[algoKey] || '#888';
    return '<span style="background:' + color + '22;border:1px solid ' + color + ';border-radius:8px;padding:3px 10px;color:' + color + ';">' +
      label + ': <strong>' + (this.ALGO_LABELS[algoKey] || algoKey) + '</strong></span>';
  },

  renderTable: function(data) {
    var tbody = document.getElementById('cmp-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';
    var algos   = data.algorithms || ['FCFS', 'SJF', 'Priority', 'RoundRobin'];
    var best    = data.best    || {};
    var results = data.results || {};
    var self    = this;

    algos.forEach(function(algo) {
      var r = results[algo];
      if (!r || r.error) return;
      var isOverall = best.overall === algo;
      var color     = self.COLORS[algo] || '#888';

      function td(val, isBest, unit) {
        return '<td style="color:' + (isBest ? '#22c55e' : 'inherit') + ';font-weight:' + (isBest ? 'bold' : 'normal') + ';">' +
          val + (unit || '') + (isBest ? ' ✓' : '') + '</td>';
      }

      var tr = document.createElement('tr');
      tr.innerHTML =
        '<td><span style="display:inline-flex;align-items:center;gap:8px;">' +
          '<span style="width:12px;height:12px;border-radius:3px;background:' + color + ';display:inline-block;"></span>' +
          '<strong>' + (self.ALGO_LABELS[algo] || algo) + '</strong>' +
          (isOverall ? '<span style="background:#22c55e;color:white;padding:1px 7px;border-radius:10px;font-size:11px;">BEST</span>' : '') +
        '</span></td>' +
        td(r.avg_waiting_time,    best.avg_waiting_time    === algo, ' ms') +
        td(r.avg_turnaround_time, best.avg_turnaround_time === algo, ' ms') +
        td(r.cpu_utilization,     best.cpu_utilization     === algo, '%')   +
        td(r.throughput,          best.throughput          === algo, '')     +
        '<td>' + r.completed + '</td>';
      tbody.appendChild(tr);
    });
  },

  renderCharts: function(data) {
    var algos   = data.algorithms || ['FCFS', 'SJF', 'Priority', 'RoundRobin'];
    var results = data.results   || {};
    var labels  = algos.map(function(a) { return CompareController.ALGO_LABELS[a] || a; });
    var colors  = algos.map(function(a) { return CompareController.COLORS[a] || '#888'; });

    this._drawBarChart('chart-awt',  labels, colors,
      algos.map(function(a) { return results[a] ? results[a].avg_waiting_time    : 0; }), 'ms', false);
    this._drawBarChart('chart-tat',  labels, colors,
      algos.map(function(a) { return results[a] ? results[a].avg_turnaround_time : 0; }), 'ms', false);
    this._drawBarChart('chart-cpu',  labels, colors,
      algos.map(function(a) { return results[a] ? results[a].cpu_utilization     : 0; }), '%',  true);
    this._drawBarChart('chart-tput', labels, colors,
      algos.map(function(a) { return results[a] ? results[a].throughput          : 0; }), '',   true);
  },

  _drawBarChart: function(canvasId, labels, colors, values, unit, higherBetter) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    canvas.width  = (canvas.parentElement.clientWidth - 40) || 400;
    canvas.height = 200;

    var ctx  = canvas.getContext('2d');
    var W    = canvas.width;
    var H    = canvas.height;
    var padL = 55, padR = 20, padT = 35, padB = 50;
    var maxV = Math.max.apply(null, values.concat([0.001]));
    var barW = (W - padL - padR) / labels.length;

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, W, H);

    // Grid
    for (var i = 0; i <= 4; i++) {
      var y = padT + (H - padT - padB) * (1 - i / 4);
      ctx.strokeStyle = '#1e293b'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
      ctx.fillStyle = '#64748b'; ctx.font = '11px monospace'; ctx.textAlign = 'right';
      ctx.fillText(((maxV / 4) * i).toFixed(1), padL - 4, y + 4);
    }

    // Y-axis
    ctx.strokeStyle = '#334155'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(padL, padT); ctx.lineTo(padL, H - padB); ctx.stroke();

    // Best index
    var bestIdx = 0;
    if (higherBetter) {
      var maxVal = values[0];
      values.forEach(function(v, i) { if (v > maxVal) { maxVal = v; bestIdx = i; } });
    } else {
      var minVal = values[0];
      values.forEach(function(v, i) { if (v < minVal) { minVal = v; bestIdx = i; } });
    }

    values.forEach(function(val, i) {
      var barH = ((val / maxV) * (H - padT - padB)) || 0;
      var x    = padL + i * barW + barW * 0.15;
      var y    = H - padB - barH;
      var bw   = barW * 0.7;

      var grad = ctx.createLinearGradient(x, y, x, H - padB);
      grad.addColorStop(0, colors[i]);
      grad.addColorStop(1, colors[i] + '55');
      ctx.fillStyle = grad;
      ctx.fillRect(x, y, bw, barH);

      // Value label
      ctx.fillStyle = '#f1f5f9'; ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'center';
      ctx.fillText(val + unit, x + bw / 2, Math.max(y - 6, padT + 14));

      // Star for best
      if (i === bestIdx) {
        ctx.fillStyle = '#fbbf24'; ctx.font = '15px sans-serif';
        ctx.fillText('★', x + bw / 2, Math.max(y - 20, padT));
      }

      // X label
      ctx.fillStyle = '#94a3b8'; ctx.font = '12px sans-serif';
      ctx.fillText(labels[i], x + bw / 2, H - padB + 18);
    });
  },

  renderProcessTable: function(algo) {
    var tbody = document.getElementById('cmp-proc-table');
    if (!tbody || !this.data) return;
    var result    = this.data.results && this.data.results[algo];
    var processes = (result && result.processes) || [];
    tbody.innerHTML = '';

    if (!processes.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);">No data</td></tr>';
      return;
    }

    var color = this.COLORS[algo] || '#888';
    processes.forEach(function(p) {
      var tr = document.createElement('tr');
      tr.innerHTML =
        '<td><strong style="color:' + color + ';">' + p.pid + '</strong></td>' +
        '<td>' + (p.name || '-') + '</td>' +
        '<td>' + (p.arrival_time    != null ? p.arrival_time    : '-') + '</td>' +
        '<td>' + (p.burst_time      != null ? p.burst_time      : '-') + '</td>' +
        '<td>' + (p.completion_time != null ? p.completion_time : '-') + '</td>' +
        '<td style="color:' + (p.waiting_time > 10 ? '#ef4444' : '#22c55e') + ';">' +
          (p.waiting_time != null ? p.waiting_time : '-') + '</td>' +
        '<td>' + (p.turnaround_time != null ? p.turnaround_time : '-') + '</td>';
      tbody.appendChild(tr);
    });
  }
};

window.CompareController = CompareController;

document.addEventListener('DOMContentLoaded', function() {
  CompareController.init();
});
