// SysRealm — Banker's Algorithm for Deadlock Avoidance & Safety Proof
// Implements:
//   Part 1: Dijkstra's Safety Algorithm (Need = Max - Allocation, Work = Available, Safe Sequence Proof)
//   Part 2: Dynamic Resource-Request Deadlock Avoidance Algorithm (Request_i <= Need_i, Request_i <= Available, Provisional Allocation & Rollback)

var BankerController = {

  procCount: 5,
  resCount:  3,
  resNames:  ['A', 'B', 'C', 'D'],
  procNames: ['P0', 'P1', 'P2', 'P3', 'P4'],

  // Classic OS textbook Safe State example (Silberschatz)
  CLASSIC_EXAMPLE: {
    processes:  ['P0', 'P1', 'P2', 'P3', 'P4'],
    resources:  ['A', 'B', 'C'],
    allocation: [[0, 1, 0], [2, 0, 0], [3, 0, 2], [2, 1, 1], [0, 0, 2]],
    max_matrix: [[7, 5, 3], [3, 2, 2], [9, 0, 2], [2, 2, 2], [4, 3, 3]],
    available:  [3, 3, 2]
  },

  // Classic Unsafe State example (Deadlock Prone)
  UNSAFE_EXAMPLE: {
    processes:  ['P0', 'P1', 'P2', 'P3', 'P4'],
    resources:  ['A', 'B', 'C'],
    allocation: [[0, 1, 0], [2, 0, 0], [3, 0, 2], [2, 1, 1], [3, 3, 2]],
    max_matrix: [[7, 5, 3], [3, 2, 2], [9, 0, 2], [2, 2, 2], [4, 3, 3]],
    available:  [0, 0, 2]
  },

  init: function() {
    var self = this;
    var btnBuild       = document.getElementById('btn-bnk-build');
    var btnExample     = document.getElementById('btn-bnk-example');
    var btnUnsafe      = document.getElementById('btn-bnk-unsafe-example');
    var btnSyncOS      = document.getElementById('btn-bnk-sync-os');
    var btnCalcNeed    = document.getElementById('btn-bnk-calc-need');
    var btnProve       = document.getElementById('btn-bnk-prove');
    var btnRequest     = document.getElementById('btn-bnk-request');
    var btnPresetSafe  = document.getElementById('btn-bnk-preset-safe');
    var btnPresetUnsf  = document.getElementById('btn-bnk-preset-unsafe');
    var btnPresetExcd  = document.getElementById('btn-bnk-preset-exceed');

    if (btnBuild)      btnBuild.addEventListener('click',      function() { self.buildTables(); });
    if (btnExample)    btnExample.addEventListener('click',    function() { self.loadClassicExample(false); });
    if (btnUnsafe)     btnUnsafe.addEventListener('click',     function() { self.loadUnsafeExample(); });
    if (btnSyncOS)     btnSyncOS.addEventListener('click',     function() { self.syncLiveProcesses(); });
    if (btnCalcNeed)   btnCalcNeed.addEventListener('click',   function() { self.calcNeed(true); });
    if (btnProve)      btnProve.addEventListener('click',      function() { self.prove(); });
    if (btnRequest)    btnRequest.addEventListener('click',    function() { self.runResourceRequest(); });

    if (btnPresetSafe) {
      btnPresetSafe.addEventListener('click', function() {
        self.loadClassicExample(true);
        self.setRequestControls(1, [1, 0, 2]);
        self.runResourceRequest();
      });
    }
    if (btnPresetUnsf) {
      btnPresetUnsf.addEventListener('click', function() {
        self.loadClassicExample(true);
        self.setRequestControls(4, [3, 3, 0]);
        self.runResourceRequest();
      });
    }
    if (btnPresetExcd) {
      btnPresetExcd.addEventListener('click', function() {
        self.loadClassicExample(true);
        self.setRequestControls(1, [2, 0, 0]);
        self.runResourceRequest();
      });
    }

    // Auto-populate the Classic Safe Example on initial load
    this.loadClassicExample(true);
  },

  // ── Build empty tables from dropdowns ──
  buildTables: function() {
    var pcEl = document.getElementById('bnk-proc-count');
    var rcEl = document.getElementById('bnk-res-count');
    this.procCount = pcEl ? parseInt(pcEl.value, 10) : 3;
    this.resCount  = rcEl ? parseInt(rcEl.value,  10) : 3;

    this.procNames = ['P0', 'P1', 'P2', 'P3', 'P4'].slice(0, this.procCount);
    this.resNames  = ['A', 'B', 'C', 'D'].slice(0, this.resCount);

    var alloc = [];
    var maxM  = [];
    for (var i = 0; i < this.procCount; i++) {
      alloc.push(new Array(this.resCount).fill(0));
      maxM.push(new Array(this.resCount).fill(2));
    }
    var avail = new Array(this.resCount).fill(2);

    this.renderMatrix('bnk-alloc-table', 'alloc', this.procNames, this.resNames, alloc, true);
    this.renderMatrix('bnk-max-table',   'maxm',  this.procNames, this.resNames, maxM,  true);
    this.renderAvailable(avail);
    this.renderRequestControls();
    this.calcNeed(false);

    document.getElementById('bnk-matrix-area').style.display = 'block';
    document.getElementById('bnk-proof-area').style.display  = 'none';
    this.hideAvoidanceResult();
  },

  // ── Load the classic Silberschatz Safe example ──
  loadClassicExample: function(silent) {
    var ex = this.CLASSIC_EXAMPLE;
    this.procCount = ex.processes.length;
    this.resCount  = ex.resources.length;
    this.procNames = ex.processes.slice();
    this.resNames  = ex.resources.slice();

    var pcEl = document.getElementById('bnk-proc-count');
    var rcEl = document.getElementById('bnk-res-count');
    if (pcEl) pcEl.value = this.procCount;
    if (rcEl) rcEl.value = this.resCount;

    this.renderMatrix('bnk-alloc-table', 'alloc', this.procNames, this.resNames, ex.allocation, true);
    this.renderMatrix('bnk-max-table',   'maxm',  this.procNames, this.resNames, ex.max_matrix,  true);
    this.renderAvailable(ex.available);
    this.renderRequestControls();
    this.setRequestControls(1, [1, 0, 2]);
    this.calcNeed(false);

    document.getElementById('bnk-matrix-area').style.display = 'block';
    document.getElementById('bnk-proof-area').style.display  = 'none';
    this.hideAvoidanceResult();

    if (!silent && window.SysAnimations) {
      window.SysAnimations.showToast('Classic 5-process Safe State example loaded!', 'success');
    }
  },

  // ── Load the Unsafe State example ──
  loadUnsafeExample: function() {
    var ex = this.UNSAFE_EXAMPLE;
    this.procCount = ex.processes.length;
    this.resCount  = ex.resources.length;
    this.procNames = ex.processes.slice();
    this.resNames  = ex.resources.slice();

    var pcEl = document.getElementById('bnk-proc-count');
    var rcEl = document.getElementById('bnk-res-count');
    if (pcEl) pcEl.value = this.procCount;
    if (rcEl) rcEl.value = this.resCount;

    this.renderMatrix('bnk-alloc-table', 'alloc', this.procNames, this.resNames, ex.allocation, true);
    this.renderMatrix('bnk-max-table',   'maxm',  this.procNames, this.resNames, ex.max_matrix,  true);
    this.renderAvailable(ex.available);
    this.renderRequestControls();
    this.calcNeed(false);

    document.getElementById('bnk-matrix-area').style.display = 'block';
    this.hideAvoidanceResult();

    if (window.SysAnimations) {
      window.SysAnimations.showToast('Unsafe State loaded — running Safety Proof to show stuck processes!', 'warning');
    }
    this.prove();
  },

  // ── Sync from Live OS Processes (/api/processes) ──
  syncLiveProcesses: async function() {
    try {
      var res = await fetch('/api/processes');
      var data = await res.json();
      var procs = (data && data.processes) ? data.processes.slice(0, 5) : [];
      if (!procs.length) {
        if (window.SysAnimations) window.SysAnimations.showToast('No live OS processes found. Using Classic Example.', 'info');
        this.loadClassicExample(false);
        return;
      }

      this.procCount = Math.max(2, Math.min(5, procs.length));
      this.resCount  = 3;
      this.procNames = procs.slice(0, this.procCount).map(function(p) { return p.pid + ' (' + p.name.slice(0, 10) + ')'; });
      this.resNames  = ['PRINTER', 'DISK', 'NET'];

      var alloc = [];
      var maxM  = [];
      for (var i = 0; i < this.procCount; i++) {
        var p = procs[i];
        var a0 = i % 2;
        var a1 = (p.burst_time % 2);
        var a2 = (p.priority % 2);
        alloc.push([a0, a1, a2]);
        maxM.push([a0 + 1, a1 + 2, a2 + 1]);
      }
      var avail = [2, 2, 2];

      this.renderMatrix('bnk-alloc-table', 'alloc', this.procNames, this.resNames, alloc, true);
      this.renderMatrix('bnk-max-table',   'maxm',  this.procNames, this.resNames, maxM,  true);
      this.renderAvailable(avail);
      this.renderRequestControls();
      this.calcNeed(false);

      if (window.SysAnimations) {
        window.SysAnimations.showToast('Synced ' + this.procCount + ' live OS processes into Banker\'s matrices!', 'success');
      }
    } catch (e) {
      console.error('Sync OS processes error:', e);
    }
  },

  // ── Render Requesting Process dropdown & Request_i vector inputs ──
  renderRequestControls: function() {
    var procSel = document.getElementById('bnk-req-proc');
    if (procSel) {
      procSel.innerHTML = this.procNames.map(function(p, idx) {
        return '<option value="' + idx + '">' + p + '</option>';
      }).join('');
    }

    var reqContainer = document.getElementById('bnk-req-inputs');
    if (reqContainer) {
      var html = '';
      for (var j = 0; j < this.resCount; j++) {
        html +=
          '<div style="display:flex;flex-direction:column;align-items:center;">' +
            '<span style="font-size:11px;color:#60a5fa;font-weight:bold;margin-bottom:2px;">' + this.resNames[j] + '</span>' +
            '<input type="number" min="0" max="99" value="0" id="bnk_req_' + j + '" ' +
              'style="width:56px;text-align:center;padding:6px;border-radius:6px;background:var(--bg-color);border:1px solid #3b82f6;color:var(--text-primary);font-weight:bold;font-size:14px;">' +
          '</div>';
      }
      reqContainer.innerHTML = html;
    }
  },

  setRequestControls: function(procIdx, vec) {
    var procSel = document.getElementById('bnk-req-proc');
    if (procSel && procIdx < this.procCount) {
      procSel.value = String(procIdx);
    }
    for (var j = 0; j < this.resCount; j++) {
      var el = document.getElementById('bnk_req_' + j);
      if (el) el.value = (vec && vec[j] != null) ? vec[j] : 0;
    }
  },

  readRequestVector: function() {
    var vec = [];
    for (var j = 0; j < this.resCount; j++) {
      var el = document.getElementById('bnk_req_' + j);
      var val = el ? parseInt(el.value, 10) : 0;
      vec.push(isNaN(val) ? 0 : val);
    }
    return vec;
  },

  hideAvoidanceResult: function() {
    var el = document.getElementById('bnk-avoidance-result');
    if (el) el.style.display = 'none';
  },

  // ── Render an editable table ──
  renderMatrix: function(containerId, prefix, procs, ress, data, editable) {
    var container = document.getElementById(containerId);
    if (!container) return;
    var self = this;

    var headerCells = '<th style="color:var(--text-muted);font-weight:normal;">Process</th>';
    ress.forEach(function(r) {
      headerCells += '<th style="text-align:center;color:var(--primary);">' + r + '</th>';
    });

    var rows = '';
    procs.forEach(function(p, i) {
      rows += '<tr><td style="font-weight:bold;color:var(--primary);padding-right:12px;">' + p + '</td>';
      ress.forEach(function(r, j) {
        var val = (data && data[i] && data[i][j] != null) ? data[i][j] : 0;
        if (editable) {
          rows += '<td><input type="number" min="0" max="99" value="' + val + '" ' +
                  'id="' + prefix + '_' + i + '_' + j + '" ' +
                  'class="bnk-matrix-input" ' +
                  'style="width:54px;text-align:center;padding:4px;border-radius:4px;' +
                  'background:var(--bg-color);border:1px solid var(--border-color);color:var(--text-primary);font-size:14px;">' +
                  '</td>';
        } else {
          rows += '<td style="text-align:center;font-family:monospace;">' + val + '</td>';
        }
      });
      rows += '</tr>';
    });

    container.innerHTML =
      '<table style="border-collapse:collapse;width:100%;">' +
        '<thead><tr>' + headerCells + '</tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
      '</table>';

    if (editable) {
      container.querySelectorAll('.bnk-matrix-input').forEach(function(inp) {
        inp.addEventListener('input', function() { self.calcNeed(false); });
      });
    }
  },

  // ── Render Available row (editable) ──
  renderAvailable: function(data) {
    var container = document.getElementById('bnk-avail-table');
    if (!container) return;

    var cells = '';
    for (var j = 0; j < this.resCount; j++) {
      var val = data ? (data[j] != null ? data[j] : 0) : 0;
      cells +=
        '<td style="padding-right:12px;text-align:center;">' +
          '<div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">' + this.resNames[j] + '</div>' +
          '<input type="number" min="0" max="99" value="' + val + '" ' +
          'id="avail_' + j + '" ' +
          'style="width:60px;text-align:center;padding:6px;border-radius:4px;' +
          'background:var(--bg-color);border:1px solid var(--border-color);color:var(--text-primary);font-size:16px;font-weight:bold;">' +
        '</td>';
    }
    container.innerHTML = '<table><tr>' + cells + '</tr></table>';
  },

  // ── Read matrix values from inputs ──
  readMatrix: function(prefix, n, m) {
    var result = [];
    for (var i = 0; i < n; i++) {
      var row = [];
      for (var j = 0; j < m; j++) {
        var el  = document.getElementById(prefix + '_' + i + '_' + j);
        var val = el ? parseInt(el.value, 10) : 0;
        row.push(isNaN(val) ? 0 : val);
      }
      result.push(row);
    }
    return result;
  },

  readAvailable: function() {
    var result = [];
    for (var j = 0; j < this.resCount; j++) {
      var el  = document.getElementById('avail_' + j);
      var val = el ? parseInt(el.value, 10) : 0;
      result.push(isNaN(val) ? 0 : val);
    }
    return result;
  },

  // ── Calculate and display Need = Max − Allocation ──
  calcNeed: function(showToast) {
    var alloc    = this.readMatrix('alloc', this.procCount, this.resCount);
    var maxM     = this.readMatrix('maxm',  this.procCount, this.resCount);
    var needDisp = document.getElementById('bnk-need-display');
    if (!needDisp) return;

    var need = [];
    var valid = true;
    var errMsg = '';
    for (var i = 0; i < this.procCount; i++) {
      var row = [];
      for (var j = 0; j < this.resCount; j++) {
        var val = maxM[i][j] - alloc[i][j];
        if (val < 0) {
          valid = false;
          errMsg = this.procNames[i] + ' Allocation[' + this.resNames[j] + ']=' + alloc[i][j] +
                   ' > Max[' + this.resNames[j] + ']=' + maxM[i][j] + ' — invalid!';
        }
        row.push(val < 0 ? 0 : val);
      }
      need.push(row);
    }

    if (!valid) {
      needDisp.innerHTML = '<div style="color:#ef4444;font-weight:bold;">⚠️ ' + errMsg + '</div>';
      return;
    }

    var headerCells = '<th style="color:var(--text-muted);font-weight:normal;">Process</th>';
    this.resNames.forEach(function(r) {
      headerCells += '<th style="text-align:center;color:#f59e0b;">' + r + '</th>';
    });
    var rows = '';
    this.procNames.forEach(function(p, i) {
      rows += '<tr><td style="font-weight:bold;color:var(--primary);padding-right:12px;">' + p + '</td>';
      need[i].forEach(function(val) {
        var color = val === 0 ? '#22c55e' : val > 5 ? '#ef4444' : '#f59e0b';
        rows += '<td style="text-align:center;font-family:monospace;font-weight:bold;color:' + color + ';">' + val + '</td>';
      });
      rows += '</tr>';
    });

    needDisp.innerHTML =
      '<table style="border-collapse:collapse;width:100%;">' +
        '<thead><tr>' + headerCells + '</tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
      '</table>' +
      '<div style="font-size:12px;color:var(--text-muted);margin-top:8px;">✅ <code>Need[i][j] = Max[i][j] − Allocation[i][j]</code> auto-synced.</div>';

    if (showToast && window.SysAnimations) {
      window.SysAnimations.showToast('Need matrix calculated!', 'success');
    }
  },

  // ── Part 2: Run Dynamic Resource-Request Deadlock Avoidance Algorithm ──
  runResourceRequest: async function() {
    var alloc   = this.readMatrix('alloc', this.procCount, this.resCount);
    var maxM    = this.readMatrix('maxm',  this.procCount, this.resCount);
    var avail   = this.readAvailable();
    var reqVec  = this.readRequestVector();
    var procSel = document.getElementById('bnk-req-proc');
    var procIdx = procSel ? parseInt(procSel.value, 10) : 0;
    var commitEl= document.getElementById('bnk-req-commit');
    var autoCommit = commitEl ? commitEl.checked : true;

    var btnReq = document.getElementById('btn-bnk-request');
    if (btnReq) { btnReq.disabled = true; btnReq.textContent = '⏳ Checking Avoidance...'; }

    try {
      var res = await fetch('/api/banker/request', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          processes:      this.procNames,
          resources:      this.resNames,
          allocation:     alloc,
          max_matrix:     maxM,
          available:      avail,
          process_index:  procIdx,
          request_vector: reqVec
        })
      });
      var data = await res.json();
      if (!data.success) {
        if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'Request check failed', 'error');
        return;
      }

      this.renderAvoidanceResult(data, autoCommit);

      // If granted and autoCommit is enabled, update the Allocation, Available, and Need tables
      if (data.granted && autoCommit) {
        this.renderMatrix('bnk-alloc-table', 'alloc', this.procNames, this.resNames, data.committed_allocation, true);
        this.renderAvailable(data.committed_available);
        this.calcNeed(false);
      }

      // If Step 3 ran the safety algorithm, also display its full safety proof below!
      if (data.provisional_result) {
        this.renderProof(data.provisional_result);
        document.getElementById('bnk-proof-area').style.display = 'block';
      }

      if (window.SysAnimations) {
        if (data.granted) {
          window.SysAnimations.showToast('✅ Request Granted! State remains SAFE.', 'success');
        } else if (data.avoided_deadlock) {
          window.SysAnimations.showToast('🚫 Deadlock Avoided! Unsafe request denied & rolled back.', 'warning');
        } else {
          window.SysAnimations.showToast('⚠️ Request rejected at validation step.', 'error');
        }
      }
    } catch (e) {
      console.error('Banker request error:', e);
      if (window.SysAnimations) window.SysAnimations.showToast('Error: ' + e.message, 'error');
    } finally {
      if (btnReq) { btnReq.disabled = false; btnReq.textContent = '🛡️ Test & Avoid Deadlock (Run Request Algorithm)'; }
    }
  },

  renderAvoidanceResult: function(data, autoCommit) {
    var box = document.getElementById('bnk-avoidance-result');
    if (!box) return;
    box.style.display = 'block';

    var pName  = data.process;
    var reqStr = '[' + (data.request_vector || []).join(', ') + ']';
    var s1     = data.step1_max_claim;
    var s2     = data.step2_available;
    var s3     = data.step3_provisional_safety;

    var renderStepCard = function(stepTitle, stepObj) {
      if (!stepObj) {
        return (
          '<div style="background:rgba(15,23,42,0.5);border:1px dashed #334155;border-radius:8px;padding:12px;opacity:0.6;">' +
            '<div style="font-weight:700;font-size:13px;color:#64748b;">' + stepTitle + '</div>' +
            '<div style="font-size:12px;color:#475569;margin-top:4px;">Skipped (previous condition failed)</div>' +
          '</div>'
        );
      }
      var passed = stepObj.passed;
      var borderCol = passed ? '#22c55e' : '#ef4444';
      var bgCol     = passed ? 'rgba(20,83,45,0.25)' : 'rgba(127,29,29,0.28)';
      var badge     = passed
        ? '<span style="background:#166534;color:#86efac;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;">PASSED ✓</span>'
        : '<span style="background:#991b1b;color:#fca5a5;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;">FAILED ✗</span>';

      var chips = '';
      if (stepObj.details) {
        chips = '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;">' +
          stepObj.details.map(function(d) {
            var rhs = d.need != null ? d.need : d.available;
            var c = d.passed ? '#4ade80' : '#f87171';
            return '<span style="font-family:monospace;font-size:12px;background:rgba(15,23,42,0.8);border:1px solid ' + c + ';color:' + c + ';padding:2px 8px;border-radius:4px;">' +
              d.resource + ': ' + d.request + ' ≤ ' + rhs + (d.passed ? ' ✓' : ' ✗') +
            '</span>';
          }).join('') +
        '</div>';
      }

      return (
        '<div style="background:' + bgCol + ';border:1px solid ' + borderCol + ';border-left:4px solid ' + borderCol + ';border-radius:8px;padding:12px;">' +
          '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px;">' +
            '<span style="font-weight:700;font-size:13px;color:#f8fafc;">' + stepTitle + '</span>' +
            badge +
          '</div>' +
          '<div style="font-family:monospace;font-size:12px;color:#cbd5e1;margin-bottom:4px;">' + (stepObj.formula || '') + '</div>' +
          '<div style="font-size:12px;color:#94a3b8;">' + (stepObj.message || '') + '</div>' +
          chips +
        '</div>'
      );
    };

    var step3Html = '';
    if (!s3) {
      step3Html = renderStepCard('Step 3: Provisional Allocation & Safety Check', null);
    } else {
      var isSafe = s3.passed;
      var s3Border = isSafe ? '#22c55e' : '#ef4444';
      var s3Bg     = isSafe ? 'rgba(20,83,45,0.28)' : 'rgba(127,29,29,0.32)';
      var seq      = (s3.safety_result && s3.safety_result.safe_sequence) ? s3.safety_result.safe_sequence : [];
      var stuck    = (s3.safety_result && s3.safety_result.stuck_processes) ? s3.safety_result.stuck_processes : [];

      step3Html =
        '<div style="background:' + s3Bg + ';border:1px solid ' + s3Border + ';border-left:4px solid ' + s3Border + ';border-radius:8px;padding:12px;">' +
          '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px;">' +
            '<span style="font-weight:700;font-size:13px;color:#f8fafc;">Step 3: Provisional Allocation &amp; Safety Check</span>' +
            (isSafe
              ? '<span style="background:#166534;color:#86efac;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;">SAFE → GRANTED ✓</span>'
              : '<span style="background:#991b1b;color:#fca5a5;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;">UNSAFE → AVOIDED &amp; ROLLED BACK 🛡️</span>') +
          '</div>' +
          '<div style="font-family:monospace;font-size:12px;color:#e2e8f0;background:rgba(15,23,42,0.75);padding:8px;border-radius:6px;margin-bottom:8px;line-height:1.7;">' +
            'Available\': [' + s3.available_before.join(', ') + '] − ' + reqStr + ' = <strong>[' + s3.available_provisional.join(', ') + ']</strong><br>' +
            'Allocation\'[' + pName + ']: [' + s3.alloc_before.join(', ') + '] + ' + reqStr + ' = <strong>[' + s3.alloc_provisional.join(', ') + ']</strong><br>' +
            'Need\'[' + pName + ']: [' + s3.need_before.join(', ') + '] − ' + reqStr + ' = <strong>[' + s3.need_provisional.join(', ') + ']</strong>' +
          '</div>' +
          (isSafe
            ? '<div style="font-size:12px;color:#86efac;">✅ Safe Sequence Found: <strong>' + seq.join(' → ') + '</strong>' +
              (autoCommit ? ' (Matrices updated!)' : '') + '</div>'
            : '<div style="font-size:12px;color:#fca5a5;">🚫 Provisional Work <code>[' + s3.available_provisional.join(', ') + ']</code> cannot satisfy any process! Stuck: <strong>' + stuck.join(', ') + '</strong>.<br>' +
              '🔄 <strong>Rollback Executed:</strong> Restored <code>Available = [' + s3.available_before.join(', ') + ']</code> to avoid deadlock!</div>') +
        '</div>';
    }

    var bannerHtml = '';
    if (data.status === 'GRANTED_SAFE') {
      bannerHtml =
        '<div style="background:linear-gradient(135deg,rgba(22,101,52,0.45),rgba(15,23,42,0.9));border:1px solid #22c55e;border-radius:10px;padding:14px 16px;margin-bottom:14px;display:flex;align-items:center;gap:14px;">' +
          '<div style="font-size:32px;">✅</div>' +
          '<div>' +
            '<div style="font-size:16px;font-weight:800;color:#4ade80;">REQUEST GRANTED — OS REMAINS IN A SAFE STATE</div>' +
            '<div style="font-size:13px;color:#cbd5e1;margin-top:2px;">' + data.verdict_message + '</div>' +
          '</div>' +
        '</div>';
    } else if (data.status === 'AVOIDED_UNSAFE') {
      bannerHtml =
        '<div style="background:linear-gradient(135deg,rgba(153,27,27,0.5),rgba(15,23,42,0.9));border:1px solid #ef4444;border-radius:10px;padding:14px 16px;margin-bottom:14px;display:flex;align-items:center;gap:14px;">' +
          '<div style="font-size:32px;">🛡️</div>' +
          '<div>' +
            '<div style="font-size:16px;font-weight:800;color:#f87171;">DEADLOCK AVOIDED! REQUEST DENIED &amp; PROVISIONAL STATE ROLLED BACK</div>' +
            '<div style="font-size:13px;color:#fecaca;margin-top:2px;">' + data.verdict_message + '</div>' +
          '</div>' +
        '</div>';
    } else {
      bannerHtml =
        '<div style="background:linear-gradient(135deg,rgba(146,64,14,0.45),rgba(15,23,42,0.9));border:1px solid #f59e0b;border-radius:10px;padding:14px 16px;margin-bottom:14px;display:flex;align-items:center;gap:14px;">' +
          '<div style="font-size:32px;">⚠️</div>' +
          '<div>' +
            '<div style="font-size:16px;font-weight:800;color:#fbbf24;">REQUEST REJECTED / DEFERRED (' + data.status + ')</div>' +
            '<div style="font-size:13px;color:#fde68a;margin-top:2px;">' +
              ((s2 && !s2.passed) ? s2.message : (s1 ? s1.message : '')) +
            '</div>' +
          '</div>' +
        '</div>';
    }

    box.innerHTML =
      bannerHtml +
      '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;">' +
        renderStepCard('Step 1: Max Claim Check (Request ≤ Need)', s1) +
        renderStepCard('Step 2: Availability Check (Request ≤ Available)', s2) +
        step3Html +
      '</div>';
  },

  // ── Part 1: Run Banker's Safety Algorithm ──
  prove: async function() {
    var alloc = this.readMatrix('alloc', this.procCount, this.resCount);
    var maxM  = this.readMatrix('maxm',  this.procCount, this.resCount);
    var avail = this.readAvailable();

    var btnProve = document.getElementById('btn-bnk-prove');
    if (btnProve) { btnProve.disabled = true; btnProve.textContent = '⏳ Running...'; }

    try {
      var res  = await fetch('/api/banker/check', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          processes:  this.procNames,
          resources:  this.resNames,
          allocation: alloc,
          max_matrix: maxM,
          available:  avail
        })
      });
      var data = await res.json();

      if (!data.success) {
        if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'Banker check failed', 'error');
        return;
      }

      this.calcNeed(false);
      this.renderProof(data);
      document.getElementById('bnk-proof-area').style.display = 'block';
      document.getElementById('bnk-proof-area').scrollIntoView({ behavior: 'smooth' });

    } catch(e) {
      console.error('Banker error:', e);
      if (window.SysAnimations) window.SysAnimations.showToast('Error: ' + e.message, 'error');
    } finally {
      if (btnProve) { btnProve.disabled = false; btnProve.textContent = '🔍 Part 1: Run Safety Algorithm (Prove Safe / Unsafe State)'; }
    }
  },

  // ── Render proof results ──
  renderProof: function(data) {
    this.renderVerdict(data);
    this.renderSteps(data);
    this.renderExplanation(data);
  },

  renderVerdict: function(data) {
    var el = document.getElementById('bnk-verdict');
    if (!el) return;
    var safe = data.safe;

    if (safe) {
      var seq = data.safe_sequence || [];
      el.style.background    = 'linear-gradient(135deg,#14532d44,var(--card-bg))';
      el.style.borderLeft    = '5px solid #22c55e';
      el.innerHTML =
        '<div style="font-size:48px;margin-bottom:8px;">✅</div>' +
        '<div style="font-size:22px;font-weight:bold;color:#22c55e;margin-bottom:8px;">SAFE STATE — DEADLOCK AVOIDED</div>' +
        '<div style="font-size:16px;color:var(--text-muted);margin-bottom:12px;">Every process can finish in a guaranteed safe sequence without deadlock.</div>' +
        '<div style="font-size:13px;color:var(--text-muted);margin-bottom:8px;">Safe Execution Sequence:</div>' +
        '<div style="display:flex;justify-content:center;gap:8px;flex-wrap:wrap;">' +
          seq.map(function(p, i) {
            return '<span style="background:#22c55e;color:white;padding:6px 16px;border-radius:20px;font-weight:bold;font-size:15px;">' +
              p +
            '</span>' + (i < seq.length - 1 ? '<span style="color:#22c55e;font-size:20px;display:flex;align-items:center;">→</span>' : '');
          }).join('') +
        '</div>';
    } else {
      var stuck = data.stuck_processes || [];
      data.steps.forEach(function(s) { if (s.stuck) stuck = s.stuck; });
      el.style.background = 'linear-gradient(135deg,#7f1d1d44,var(--card-bg))';
      el.style.borderLeft = '5px solid #ef4444';
      el.innerHTML =
        '<div style="font-size:48px;margin-bottom:8px;">🔴</div>' +
        '<div style="font-size:22px;font-weight:bold;color:#ef4444;margin-bottom:8px;">UNSAFE STATE — DEADLOCK RISK DETECTED</div>' +
        '<div style="font-size:16px;color:var(--text-muted);margin-bottom:12px;">Banker\'s Algorithm rejects entering this state to avoid deadlock!</div>' +
        '<div style="font-size:13px;color:#fca5a5;">Stuck processes (Need &gt; Work): <strong>' + stuck.join(', ') + '</strong></div>';
    }
  },

  renderSteps: function(data) {
    var tbody = document.getElementById('bnk-steps-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    var steps = data.steps || [];
    var res   = data.resources || this.resNames;

    steps.forEach(function(step) {
      var tr = document.createElement('tr');
      var isUnsafe = !step.process;

      if (isUnsafe) {
        var stuck = step.stuck ? step.stuck.join(', ') : '?';
        tr.innerHTML =
          '<td colspan="7" style="background:#7f1d1d;color:#fca5a5;text-align:center;padding:12px;border-radius:6px;">' +
            '🔴 BLOCKED — No remaining process satisfies Need[i] ≤ Work [' + (step.work_before || []).join(', ') + ']. Stuck: <strong>' + stuck + '</strong>' +
          '</td>';
      } else {
        var needStr   = '[' + step.need.join(', ') + ']';
        var workBStr  = '[' + step.work_before.join(', ') + ']';
        var allocStr  = '[' + step.allocation.join(', ') + ']';
        var workAStr  = '[' + step.work_after.join(', ') + ']';

        var checks = step.need.map(function(n, j) {
          var ok = n <= step.work_before[j];
          return '<span style="color:' + (ok ? '#22c55e' : '#ef4444') + ';">' +
            (res[j] || j) + ':' + n + '≤' + step.work_before[j] +
          '</span>';
        }).join(' ');

        tr.innerHTML =
          '<td style="text-align:center;font-weight:bold;">' + step.step + '</td>' +
          '<td><strong style="color:#3b82f6;">' + step.process + '</strong></td>' +
          '<td style="font-family:monospace;color:#f59e0b;">' + needStr + '</td>' +
          '<td style="font-family:monospace;color:#94a3b8;">' + workBStr + '</td>' +
          '<td style="font-size:12px;">' + checks + ' <span style="color:#22c55e;">✓</span></td>' +
          '<td style="font-family:monospace;color:#e74c3c;">+' + allocStr + '</td>' +
          '<td style="font-family:monospace;color:#22c55e;font-weight:bold;">' + workAStr + '</td>';
      }
      tbody.appendChild(tr);
    });
  },

  renderExplanation: function(data) {
    var el = document.getElementById('bnk-explanation');
    if (!el) return;

    var safe  = data.safe;
    var seq   = data.safe_sequence || [];
    var steps = data.steps || [];

    var html = '';
    html += '<div style="margin-bottom:12px;"><strong>Initial Work Vector:</strong> ';
    html += '<code>Work = Available = [' + (data.available || []).join(', ') + ']</code></div>';

    html += '<div style="margin-bottom:12px;"><strong>Step-by-Step Safety Trace:</strong></div>';
    steps.forEach(function(step) {
      if (!step.process) {
        html += '<div style="background:#7f1d1d;padding:10px;border-radius:6px;margin-bottom:8px;color:#fca5a5;">' +
          '<strong>Step ' + step.step + ':</strong> ' + step.explanation + '</div>';
      } else {
        html += '<div style="background:var(--bg-color);border:1px solid var(--border-color);border-left:3px solid #22c55e;' +
                'padding:10px;border-radius:6px;margin-bottom:8px;">' +
          '<strong style="color:#22c55e;">Step ' + step.step + ' → ' + step.process + '</strong><br>' +
          '<span style="color:var(--text-muted);font-size:13px;">' + step.explanation + '</span>' +
        '</div>';
      }
    });

    if (safe) {
      html += '<div style="background:#14532d;border-radius:8px;padding:14px;margin-top:8px;">' +
        '<div style="font-weight:bold;color:#22c55e;font-size:15px;margin-bottom:6px;">✅ Conclusion: SAFE STATE</div>' +
        '<div style="color:#86efac;">All processes completed: Finish[] = [' + (data.finish||[]).map(function(){ return 'True'; }).join(', ') + ']</div>' +
        '<div style="color:#86efac;margin-top:4px;">Safe Sequence: <strong>&lt;' + seq.join(', ') + '&gt;</strong></div>' +
        '<div style="color:#4ade80;margin-top:6px;font-size:13px;">Deadlock Avoidance Guarantee: The OS can safely satisfy all maximum claims in this order.</div>' +
      '</div>';
    } else {
      var scheduled = seq.length;
      var total     = (data.processes || []).length;
      html += '<div style="background:#7f1d1d;border-radius:8px;padding:14px;margin-top:8px;">' +
        '<div style="font-weight:bold;color:#ef4444;font-size:15px;margin-bottom:6px;">🔴 Conclusion: UNSAFE STATE</div>' +
        '<div style="color:#fca5a5;">Only ' + scheduled + ' of ' + total + ' processes could finish.</div>' +
        '<div style="color:#f87171;margin-top:6px;font-size:13px;">Banker\'s Algorithm avoids deadlock by refusing any resource request that transitions into this Unsafe State.</div>' +
      '</div>';
    }

    el.innerHTML = html;
  },

  clearNeed: function() {
    var nd = document.getElementById('bnk-need-display');
    if (nd) nd.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:8px;">Fill Allocation + Max then click Calculate Need ↓</div>';
  }
};

window.BankerController = BankerController;

document.addEventListener('DOMContentLoaded', function() {
  BankerController.init();
});
