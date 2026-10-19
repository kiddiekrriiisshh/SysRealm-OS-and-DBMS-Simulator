// ═══════════════════════════════════════════════════════════════════════════
// SysRealm — DBMS Engine Room Controller
// 1. Live SQL Triggers Lab (BEFORE/AFTER INSERT/UPDATE)
// 2. Visual SQL JOINs Explorer (INNER, LEFT OUTER, 3-Table, GROUP BY)
// 3. ACID Transactions Simulator (START TRANSACTION, COMMIT, ROLLBACK, SAVEPOINT)
// 4. Interactive ER Diagram & 3NF / BCNF Normalization Explorer
// ═══════════════════════════════════════════════════════════════════════════

var DBMSController = {
    currentTab: 'triggers',
    currentJoin: 'inner_join',
    schemaCatalog: null,
    selectedTable: 'simulation_sessions',

    init: function() {
        var self = this;

        var refreshBtn = document.getElementById('btn-dbms-refresh');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', function() {
                self.loadStatus();
                if (self.currentTab === 'joins') {
                    self.runJoin(self.currentJoin);
                } else if (self.currentTab === 'schema') {
                    self.loadSchema();
                }
            });
        }

        var cfgBtn = document.getElementById('btn-toggle-mysql-cfg');
        var drawer = document.getElementById('mysql-cfg-drawer');
        if (cfgBtn && drawer) {
            cfgBtn.addEventListener('click', function() {
                drawer.style.display = drawer.style.display === 'none' ? 'block' : 'none';
            });
        }

        var connBtn = document.getElementById('btn-mysql-connect');
        if (connBtn) {
            connBtn.addEventListener('click', function() {
                self.connectMySQL();
            });
        }

        // Auto-load when DBMS Engine Room or Query Optimizer panel is opened from sidebar
        document.querySelectorAll('#sidebar-nav li').forEach(function(li) {
            li.addEventListener('click', function() {
                var tgt = li.getAttribute('data-target');
                if (tgt === 'dbms') {
                    setTimeout(function() {
                        self.loadStatus();
                        if (self.currentTab === 'joins') {
                            self.runJoin(self.currentJoin);
                        } else if (self.currentTab === 'schema') {
                            self.loadSchema();
                        }
                    }, 80);
                } else if (tgt === 'optimizer') {
                    setTimeout(function() {
                        self.runOptimizer(self.currentOptPreset || 'join_filter');
                    }, 80);
                }
            });
        });

        this.loadStatus();
        this.showNormStep('1NF');
    },

    switchTab: function(tab) {
        if (tab === 'optimizer') {
            var nav = document.getElementById('nav-optimizer');
            if (nav) nav.click();
            return;
        }
        this.currentTab = tab;
        var tabs = {
            'triggers': { panel: 'dbms-sub-triggers', btn: 'tab-btn-triggers' },
            'joins':    { panel: 'dbms-sub-joins',    btn: 'tab-btn-joins' },
            'history':  { panel: 'dbms-sub-history',  btn: 'tab-btn-history' },
            'acid':     { panel: 'dbms-sub-acid',     btn: 'tab-btn-acid' },
            'schema':   { panel: 'dbms-sub-schema',   btn: 'tab-btn-schema' }
        };

        Object.keys(tabs).forEach(function(k) {
            var pEl = document.getElementById(tabs[k].panel);
            var bEl = document.getElementById(tabs[k].btn);
            if (pEl) pEl.style.display = (k === tab) ? 'block' : 'none';
            if (bEl) {
                if (k === tab) bEl.classList.add('active');
                else bEl.classList.remove('active');
            }
        });

        if (tab === 'triggers') {
            this.loadStatus();
        } else if (tab === 'joins') {
            this.runJoin(this.currentJoin);
        } else if (tab === 'history') {
            this.loadProcessHistory();
        } else if (tab === 'acid') {
            this.loadStatus();
        } else if (tab === 'schema') {
            this.loadSchema();
            this.showNormStep('3NF');
        }
    },

    loadStatus: async function() {
        try {
            var res  = await fetch('/api/dbms/status');
            var data = await res.json();
            if (!data.success) return;

            // Connection badge: accurately reflect active database engine
            var badge = document.getElementById('dbms-conn-badge');
            if (badge) {
                if (data.mysql_connected) {
                    badge.innerHTML = '🟢 MySQL 8.0 Connected (' + data.user + '@' + data.host + ':' + data.port + '/' + data.database + ')';
                    badge.style.background = 'rgba(16,185,129,.16)';
                    badge.style.borderColor = 'rgba(16,185,129,.4)';
                    badge.style.color = '#34d399';
                } else {
                    badge.innerHTML = '🟡 SQLite Fallback Mirror Active (sysrealm_mysql_mirror.db)';
                    badge.style.background = 'rgba(245,158,11,.15)';
                    badge.style.borderColor = 'rgba(245,158,11,.4)';
                    badge.style.color = '#fbbf24';
                }
            }

            var histBadge = document.getElementById('hist-engine-badge');
            if (histBadge) {
                histBadge.textContent = data.engine_name || (data.mysql_connected ? 'MySQL 8.0' : 'SQLite Fallback Mirror');
            }

            // Table counts strip
            var countsEl = document.getElementById('dbms-table-counts');
            if (countsEl && data.table_counts) {
                var tc = data.table_counts;
                var items = [
                    { key: 'simulation_sessions',  label: 'sessions',              icon: '🗂️', color: '#3b82f6' },
                    { key: 'processes',            label: 'processes',             icon: '⚙️', color: '#10b981' },
                    { key: 'process_state_history',label: 'state_history',         icon: '⏱️', color: '#0284c7' },
                    { key: 'resources',            label: 'resources',             icon: '🖨️', color: '#a855f7' },
                    { key: 'resource_allocations', label: 'resource_allocations',  icon: '🔒', color: '#f59e0b' },
                    { key: 'process_activity_logs',label: 'activity_logs',         icon: '📜', color: '#06b6d4' },
                    { key: 'scores',               label: 'scores',                icon: '🏆', color: '#ec4899' },
                    { key: 'lab_assignments',      label: 'lab_assignments',       icon: '🎓', color: '#8b5cf6' }
                ];
                countsEl.innerHTML = items.map(function(it) {
                    var val = tc[it.key] != null ? tc[it.key] : 0;
                    return '<div class="card" style="padding:10px 12px;min-width:115px;text-align:center;">' +
                        '<div style="font-size:20px;font-weight:800;color:' + it.color + ';">' + val + '</div>' +
                        '<div style="font-size:10px;color:var(--text-muted);font-family:monospace;margin-top:2px;">' + it.icon + ' ' + it.label + '</div>' +
                    '</div>';
                }).join('');
            }

            // Populate DDL blocks for all 7 triggers
            if (data.triggers && data.triggers.length >= 4) {
                var map = {
                    'trg_before_process_insert':     'ddl-before_insert',
                    'trg_before_process_update':     'ddl-before_update',
                    'trg_after_process_insert':      'ddl-after_insert',
                    'trg_after_process_state_update':'ddl-after_update_state',
                    'trg_after_process_terminated':  'ddl-after_update',
                    'trg_after_process_delete':      'ddl-after_delete',
                    'trg_after_resource_allocation': 'ddl-after_resource'
                };
                data.triggers.forEach(function(t) {
                    var el = document.getElementById(map[t.name]);
                    if (el) el.textContent = t.create_sql;
                });
            }

            this.renderTriggerFeed(data.trigger_feed || []);
        } catch (e) {
            console.error('DBMS status error:', e);
        }
    },

    connectMySQL: async function() {
        var host = (document.getElementById('mysql-cfg-host') || {}).value || 'localhost';
        var port = (document.getElementById('mysql-cfg-port') || {}).value || 3306;
        var user = (document.getElementById('mysql-cfg-user') || {}).value || 'root';
        var pw   = (document.getElementById('mysql-cfg-pw')   || {}).value || '';
        var msgEl = document.getElementById('mysql-cfg-msg');
        if (msgEl) msgEl.innerHTML = '<span style="color:#38bdf8;">⏳ Connecting to MySQL &amp; installing triggers...</span>';

        try {
            var res  = await fetch('/api/dbms/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ host: host, port: port, user: user, password: pw, database: 'sysrealm' })
            });
            var data = await res.json();
            if (data.success) {
                if (msgEl) msgEl.innerHTML = '<span style="color:#10b981;font-weight:700;">✅ ' + data.message + '</span>';
                this.loadStatus();
                if (this.currentTab === 'joins') this.runJoin(this.currentJoin);
                if (this.currentTab === 'history') this.loadProcessHistory();
            } else {
                if (msgEl) msgEl.innerHTML = '<span style="color:#f87171;">❌ ' + (data.error || 'Connection failed') + '</span>';
            }
        } catch (e) {
            if (msgEl) msgEl.innerHTML = '<span style="color:#f87171;">❌ Error: ' + e.message + '</span>';
        }
    },

    // ═══════════════════════════════════════════════════════════════════════
    // 1. LIVE SQL TRIGGERS LAB
    // ═══════════════════════════════════════════════════════════════════════
    fireTrigger: async function(triggerType) {
        var liveEl = document.getElementById('trigger-live-result');
        if (liveEl) {
            liveEl.innerHTML = '<div style="color:#38bdf8;">⚡ Executing SQL statement &amp; firing trigger...</div>';
        }
        try {
            var res  = await fetch('/api/dbms/fire-trigger', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ trigger_type: triggerType })
            });
            var data = await res.json();
            if (!data.success || !data.result) return;

            var r = data.result;
            var isBlocked = r.status.indexOf('BLOCKED') !== -1;
            var badgeBg   = isBlocked ? 'rgba(239,68,68,.2)' : 'rgba(16,185,129,.2)';
            var badgeCol  = isBlocked ? '#f87171' : '#34d399';

            if (liveEl) {
                liveEl.innerHTML =
                    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">' +
                        '<strong style="color:#fff;font-size:13px;">⚡ ' + r.trigger_name + '</strong>' +
                        '<span style="background:' + badgeBg + ';color:' + badgeCol + ';padding:2px 8px;border-radius:6px;font-size:11px;font-weight:700;">' + r.status + '</span>' +
                    '</div>' +
                    '<div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">SQL Statement Executed (' + (data.engine || 'Active Engine') + '):</div>' +
                    '<pre style="background:#0b1120;border:1px solid var(--border-color);padding:8px;border-radius:6px;color:#38bdf8;font-size:11px;overflow-x:auto;margin-bottom:8px;">' + r.sql_executed + '</pre>' +
                    '<div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">Trigger Effect on Database:</div>' +
                    '<div style="background:rgba(255,255,255,.04);border-left:3px solid ' + badgeCol + ';padding:8px 10px;border-radius:4px;color:#e2e8f0;white-space:pre-wrap;font-size:12px;">' + r.effect + '</div>';
            }

            this.loadStatus();
            if (this.currentTab === 'history') {
                this.loadProcessHistory();
            }
        } catch (e) {
            console.error('Fire trigger error:', e);
        }
    },

    renderTriggerFeed: function(feed) {
        var el = document.getElementById('trigger-feed-list');
        if (!el) return;
        if (!feed || feed.length === 0) {
            el.innerHTML = '<div style="color:var(--text-muted);padding:12px;text-align:center;">No triggers fired in this session yet.</div>';
            return;
        }
        el.innerHTML = feed.map(function(f) {
            var isBlocked = f.status.indexOf('BLOCKED') !== -1;
            var dot = isBlocked ? '#ef4444' : '#10b981';
            return '<div style="padding:9px 10px;border-bottom:1px solid var(--border-color);background:rgba(0,0,0,.2);border-radius:6px;margin-bottom:6px;">' +
                '<div style="display:flex;justify-content:space-between;align-items:center;">' +
                    '<span style="font-weight:700;color:#fff;font-family:monospace;font-size:12px;">' +
                        '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + dot + ';margin-right:6px;"></span>' +
                        f.trigger_name +
                    '</span>' +
                    '<span style="font-size:11px;color:var(--text-muted);">' + f.time + '</span>' +
                '</div>' +
                '<div style="font-size:11px;color:#94a3b8;margin-top:4px;white-space:pre-wrap;">' + f.effect + '</div>' +
            '</div>';
        }).join('');
    },

    // ═══════════════════════════════════════════════════════════════════════
    // 2. PROCESS STATE TRANSITION HISTORY LAB
    // ═══════════════════════════════════════════════════════════════════════
    loadProcessHistory: async function() {
        var sidInput = document.getElementById('hist-session-id');
        var sessionId = sidInput ? sidInput.value.trim() : 'DEMO_SES_01';
        var tableWrap = document.getElementById('process-history-table-wrap');
        var countEl = document.getElementById('hist-record-count');
        var badgeEl = document.getElementById('hist-engine-badge');

        try {
            var res = await fetch('/api/dbms/process-history?session_id=' + encodeURIComponent(sessionId));
            var data = await res.json();
            if (!data.success) return;

            if (countEl) countEl.textContent = data.count + ' transitions';
            if (badgeEl) badgeEl.textContent = data.engine || 'Active Engine';

            if (!tableWrap) return;
            var rows = data.history || [];
            if (rows.length === 0) {
                tableWrap.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-muted);">No state transitions recorded for session <code>' + sessionId + '</code> yet.<br>Click one of the state change buttons on the left to fire the trigger!</div>';
                return;
            }

            var html = '<table><thead><tr>' +
                '<th style="font-family:monospace;">ID</th>' +
                '<th style="font-family:monospace;">PID</th>' +
                '<th style="font-family:monospace;">Old State</th>' +
                '<th style="font-family:monospace;">&rarr;</th>' +
                '<th style="font-family:monospace;">New State</th>' +
                '<th style="font-family:monospace;">Timestamp (Trigger Logged)</th>' +
                '</tr></thead><tbody>';

            html += rows.map(function(r) {
                var stateColors = {
                    'NEW': '#94a3b8',
                    'READY': '#3b82f6',
                    'RUNNING': '#10b981',
                    'WAITING': '#f59e0b',
                    'TERMINATED': '#ef4444'
                };
                var oldCol = stateColors[r.old_state] || '#94a3b8';
                var newCol = stateColors[r.new_state] || '#38bdf8';

                return '<tr>' +
                    '<td style="font-family:monospace;font-weight:700;">#' + r.id + '</td>' +
                    '<td style="font-family:monospace;font-weight:800;color:#38bdf8;">' + r.pid + '</td>' +
                    '<td><span style="background:rgba(255,255,255,.08);color:' + oldCol + ';padding:2px 8px;border-radius:4px;font-weight:700;font-family:monospace;font-size:11px;">' + r.old_state + '</span></td>' +
                    '<td style="color:var(--text-muted);">&rarr;</td>' +
                    '<td><span style="background:rgba(255,255,255,.08);color:' + newCol + ';padding:2px 8px;border-radius:4px;font-weight:700;font-family:monospace;font-size:11px;">' + r.new_state + '</span></td>' +
                    '<td style="font-family:monospace;font-size:11px;color:#94a3b8;">' + (r.changed_at || '—') + '</td>' +
                '</tr>';
            }).join('');

            html += '</tbody></table>';
            tableWrap.innerHTML = html;
        } catch (e) {
            console.error('Process history fetch error:', e);
        }
    },

    transitionState: async function(newState) {
        var sidInput = document.getElementById('hist-session-id');
        var sessionId = sidInput ? sidInput.value.trim() : 'DEMO_SES_01';
        var pidSelect = document.getElementById('hist-target-pid');
        var pid = pidSelect ? pidSelect.value : 'P1';
        var resEl = document.getElementById('hist-action-result');

        if (resEl) {
            resEl.innerHTML = '<span style="color:#38bdf8;">⚡ Executing UPDATE processes SET state = \'' + newState + '\'...</span>';
        }

        try {
            var res = await fetch('/api/processes/' + encodeURIComponent(pid) + '/state', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ state: newState, session_id: sessionId })
            });
            var data = await res.json();
            if (data.success) {
                if (resEl) {
                    resEl.innerHTML = '<div style="color:#34d399;font-weight:700;margin-bottom:4px;">✅ ' + data.message + '</div>' +
                        '<div style="font-size:11px;color:#94a3b8;">Trigger <code>trg_after_process_state_update</code> executed on ' + data.engine + '! Captured state change into <code>process_state_history</code>.</div>';
                }
                this.loadProcessHistory();
                this.loadStatus();
            } else {
                if (resEl) {
                    resEl.innerHTML = '<div style="color:#f87171;font-weight:700;">❌ ' + (data.error || 'State update rejected') + '</div>';
                }
            }
        } catch (e) {
            if (resEl) resEl.innerHTML = '<div style="color:#f87171;">❌ Error: ' + e.message + '</div>';
        }
    },

    // ═══════════════════════════════════════════════════════════════════════
    // 3. VISUAL SQL JOINS EXPLORER (7 Reports)
    // ═══════════════════════════════════════════════════════════════════════
    runJoin: async function(joinType) {
        this.currentJoin = joinType;

        document.querySelectorAll('.join-type-btn').forEach(function(btn) {
            var active = btn.getAttribute('data-join') === joinType;
            btn.style.background = active ? 'var(--primary)' : 'var(--secondary)';
            btn.style.color      = '#fff';
        });

        this.renderVennDiagram(joinType);

        try {
            var res  = await fetch('/api/dbms/join', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ join_type: joinType })
            });
            var data = await res.json();
            if (!data.success) return;

            var titleEl = document.getElementById('join-title-display');
            var keyEl   = document.getElementById('join-key-display');
            var expEl   = document.getElementById('join-explanation-display');
            var sqlEl   = document.getElementById('join-sql-display');
            var tblEl   = document.getElementById('join-tables-display');
            var cntEl   = document.getElementById('join-rowcount-display');
            var badgeEl = document.getElementById('join-engine-badge');

            if (titleEl) titleEl.textContent = data.title;
            if (keyEl)   keyEl.textContent   = data.join_key;
            if (expEl)   expEl.textContent   = data.explanation;
            if (sqlEl)   sqlEl.textContent   = data.sql;
            if (tblEl)   tblEl.textContent   = (data.tables || []).join('  ⋈  ');
            if (cntEl)   cntEl.textContent   = data.row_count + ' rows';
            if (badgeEl) badgeEl.textContent = data.engine || (data.mysql_connected ? 'MySQL 8.0' : 'SQLite Fallback Mirror');

            var container = document.getElementById('join-result-container');
            if (!container) return;
            var cols = data.columns || [];
            var rows = data.rows || [];

            if (rows.length === 0) {
                container.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);">No rows returned.</div>';
                return;
            }

            var thead = '<thead><tr>' + cols.map(function(c) {
                return '<th style="font-family:monospace;font-size:12px;color:#38bdf8;">' + c + '</th>';
            }).join('') + '</tr></thead>';

            var tbody = '<tbody>' + rows.map(function(r) {
                return '<tr>' + cols.map(function(c) {
                    var val = r[c];
                    if (val === null || val === undefined) {
                        return '<td><span style="background:rgba(244,63,94,.18);color:#fda4af;padding:2px 7px;border-radius:4px;font-family:monospace;font-size:11px;">NULL</span></td>';
                    }
                    return '<td style="font-size:13px;">' + val + '</td>';
                }).join('') + '</tr>';
            }).join('') + '</tbody>';

            container.innerHTML = '<table>' + thead + tbody + '</table>';
        } catch (e) {
            console.error('Join error:', e);
        }
    },

    renderVennDiagram: function(joinType) {
        var el = document.getElementById('join-venn-svg');
        if (!el) return;

        if (joinType === 'inner_join') {
            el.innerHTML =
                '<svg width="260" height="120" viewBox="0 0 260 120">' +
                    '<defs><clipPath id="clipA"><circle cx="100" cy="60" r="46"/></clipPath></defs>' +
                    '<circle cx="100" cy="60" r="46" fill="rgba(59,130,246,0.12)" stroke="#3b82f6" stroke-width="2"/>' +
                    '<circle cx="160" cy="60" r="46" fill="rgba(16,185,129,0.12)" stroke="#10b981" stroke-width="2"/>' +
                    '<circle cx="160" cy="60" r="46" clip-path="url(#clipA)" fill="rgba(56,189,248,0.65)"/>' +
                    '<text x="72" y="64" fill="#93c5fd" font-size="11" font-weight="bold">processes</text>' +
                    '<text x="165" y="64" fill="#6ee7b7" font-size="11" font-weight="bold">sessions</text>' +
                    '<text x="130" y="63" fill="#fff" font-size="10" font-weight="bold" text-anchor="middle">MATCH</text>' +
                '</svg>';
        } else if (joinType === 'left_join') {
            el.innerHTML =
                '<svg width="260" height="120" viewBox="0 0 260 120">' +
                    '<circle cx="100" cy="60" r="46" fill="rgba(168,85,247,0.55)" stroke="#a855f7" stroke-width="2.5"/>' +
                    '<circle cx="160" cy="60" r="46" fill="rgba(59,130,246,0.10)" stroke="#64748b" stroke-width="2" stroke-dasharray="4 3"/>' +
                    '<text x="75" y="64" fill="#fff" font-size="11" font-weight="bold">resources</text>' +
                    '<text x="162" y="64" fill="#94a3b8" font-size="11">allocations</text>' +
                '</svg>';
        } else if (joinType === 'three_table_join') {
            el.innerHTML =
                '<svg width="260" height="130" viewBox="0 0 260 130">' +
                    '<circle cx="105" cy="50" r="36" fill="rgba(59,130,246,0.35)" stroke="#3b82f6" stroke-width="2"/>' +
                    '<circle cx="155" cy="50" r="36" fill="rgba(16,185,129,0.35)" stroke="#10b981" stroke-width="2"/>' +
                    '<circle cx="130" cy="85" r="36" fill="rgba(245,158,11,0.35)" stroke="#f59e0b" stroke-width="2"/>' +
                    '<text x="85" y="45" fill="#fff" font-size="10" font-weight="bold">sessions</text>' +
                    '<text x="148" y="45" fill="#fff" font-size="10" font-weight="bold">processes</text>' +
                    '<text x="115" y="98" fill="#fff" font-size="10" font-weight="bold">scores</text>' +
                '</svg>';
        } else if (joinType === 'session_summary') {
            el.innerHTML =
                '<svg width="260" height="120" viewBox="0 0 260 120">' +
                    '<rect x="25" y="25" width="90" height="70" rx="8" fill="rgba(2,132,199,0.25)" stroke="#0284c7" stroke-width="2"/>' +
                    '<rect x="145" y="25" width="90" height="70" rx="8" fill="rgba(16,185,129,0.25)" stroke="#10b981" stroke-width="2"/>' +
                    '<path d="M 115 60 L 145 60" stroke="#38bdf8" stroke-width="2.5" marker-end="url(#arrow)"/>' +
                    '<text x="70" y="55" fill="#fff" font-size="11" font-weight="bold" text-anchor="middle">Sessions</text>' +
                    '<text x="70" y="72" fill="#93c5fd" font-size="9" text-anchor="middle">1 Row/Session</text>' +
                    '<text x="190" y="55" fill="#fff" font-size="11" font-weight="bold" text-anchor="middle">Subquery</text>' +
                    '<text x="190" y="72" fill="#6ee7b7" font-size="9" text-anchor="middle">Pre-aggregated</text>' +
                '</svg>';
        } else if (joinType === 'resource_utilization') {
            el.innerHTML =
                '<svg width="260" height="120" viewBox="0 0 260 120">' +
                    '<circle cx="80" cy="60" r="38" fill="rgba(124,58,237,0.3)" stroke="#7c3aed" stroke-width="2"/>' +
                    '<circle cx="130" cy="60" r="38" fill="rgba(245,158,11,0.3)" stroke="#f59e0b" stroke-width="2"/>' +
                    '<circle cx="180" cy="60" r="38" fill="rgba(16,185,129,0.3)" stroke="#10b981" stroke-width="2"/>' +
                    '<text x="65" y="64" fill="#c084fc" font-size="9" font-weight="bold">Resources</text>' +
                    '<text x="118" y="64" fill="#fcd34d" font-size="9" font-weight="bold">Allocations</text>' +
                    '<text x="168" y="64" fill="#6ee7b7" font-size="9" font-weight="bold">Processes</text>' +
                '</svg>';
        } else if (joinType === 'assignment_submissions_report') {
            el.innerHTML =
                '<svg width="260" height="120" viewBox="0 0 260 120">' +
                    '<circle cx="95" cy="60" r="44" fill="rgba(5,150,105,0.4)" stroke="#059669" stroke-width="2.5"/>' +
                    '<circle cx="165" cy="60" r="44" fill="rgba(99,102,241,0.2)" stroke="#6366f1" stroke-width="2"/>' +
                    '<text x="68" y="64" fill="#fff" font-size="10" font-weight="bold">Challenges</text>' +
                    '<text x="155" y="64" fill="#a5b4fc" font-size="10" font-weight="bold">Submissions</text>' +
                '</svg>';
        } else {
            el.innerHTML =
                '<svg width="260" height="120" viewBox="0 0 260 120">' +
                    '<circle cx="100" cy="60" r="46" fill="rgba(245,158,11,0.45)" stroke="#f59e0b" stroke-width="2"/>' +
                    '<circle cx="160" cy="60" r="46" fill="rgba(6,182,212,0.35)" stroke="#06b6d4" stroke-width="2"/>' +
                    '<text x="72" y="64" fill="#fff" font-size="11" font-weight="bold">GROUP BY</text>' +
                    '<text x="155" y="64" fill="#fff" font-size="11" font-weight="bold">COUNT/AVG</text>' +
                '</svg>';
        }
    },

    // ═══════════════════════════════════════════════════════════════════════
    // 3. ACID TRANSACTIONS SIMULATOR (COMMIT vs. ROLLBACK vs. SAVEPOINT)
    // ═══════════════════════════════════════════════════════════════════════
    runTransaction: async function(scenario) {
        var titleEl   = document.getElementById('tx-live-title');
        var badgeEl   = document.getElementById('tx-outcome-badge');
        var expEl     = document.getElementById('tx-live-explanation');
        var tbodyEl   = document.getElementById('tx-snapshot-tbody');
        var stepsEl   = document.getElementById('tx-steps-timeline');

        if (badgeEl) {
            badgeEl.textContent = '⏳ Executing SQL Transaction...';
            badgeEl.style.background = 'rgba(56,189,248,.18)';
            badgeEl.style.color = '#38bdf8';
        }

        try {
            var res  = await fetch('/api/dbms/transaction', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ scenario: scenario })
            });
            var data = await res.json();
            if (!data.success) return;

            if (titleEl) titleEl.textContent = '🔄 ' + data.title;
            if (expEl)   expEl.textContent   = data.explanation;

            if (badgeEl) {
                badgeEl.textContent = data.outcome;
                if (scenario === 'rollback_demo') {
                    badgeEl.style.background = 'rgba(239,68,68,.2)';
                    badgeEl.style.color = '#f87171';
                } else if (scenario === 'commit_demo') {
                    badgeEl.style.background = 'rgba(16,185,129,.2)';
                    badgeEl.style.color = '#34d399';
                } else {
                    badgeEl.style.background = 'rgba(245,158,11,.2)';
                    badgeEl.style.color = '#fbbf24';
                }
            }

            // Render Before / During / After Comparison Table
            if (tbodyEl && data.counts_before && data.counts_during && data.counts_after) {
                var rowsSpec = [
                    { key: 'processes',             label: '⚙️ processes (rows)' },
                    { key: 'resource_allocations',  label: '🔒 resource_allocations (rows)' },
                    { key: 'process_activity_logs', label: '📜 process_activity_logs (rows)' },
                    { key: 'session_score',         label: '🏆 scores.total_score (pts)' }
                ];
                tbodyEl.innerHTML = rowsSpec.map(function(rs) {
                    var b = data.counts_before[rs.key] || 0;
                    var d = data.counts_during[rs.key] || 0;
                    var a = data.counts_after[rs.key]  || 0;
                    var duringDiff = d - b;
                    var netDiff    = a - b;
                    var duringTag  = duringDiff > 0 ? ' <span style="color:#fbbf24;font-weight:700;">(+' + duringDiff + ' uncommitted)</span>' : '';
                    var netTag     = netDiff > 0
                        ? '<span style="background:rgba(16,185,129,.18);color:#34d399;padding:2px 8px;border-radius:6px;font-weight:700;font-size:11px;">+' + netDiff + ' COMMITTED</span>'
                        : '<span style="background:rgba(148,163,184,.15);color:#cbd5e1;padding:2px 8px;border-radius:6px;font-weight:700;font-size:11px;">0 (ROLLED BACK)</span>';
                    return '<tr>' +
                        '<td style="font-family:monospace;font-weight:700;">' + rs.label + '</td>' +
                        '<td>' + b + '</td>' +
                        '<td>' + d + duringTag + '</td>' +
                        '<td style="font-weight:800;color:#fff;">' + a + '</td>' +
                        '<td>' + netTag + '</td>' +
                    '</tr>';
                }).join('');
            }

            // Render Step-by-Step Timeline
            if (stepsEl && data.steps) {
                stepsEl.innerHTML = data.steps.map(function(st) {
                    var col = '#38bdf8';
                    var bg  = 'rgba(56,189,248,.15)';
                    if (st.status.indexOf('ABORTED') !== -1 || st.status.indexOf('ROLLED BACK') !== -1) {
                        col = '#f87171';
                        bg  = 'rgba(239,68,68,.18)';
                    } else if (st.status === 'COMMITTED') {
                        col = '#34d399';
                        bg  = 'rgba(16,185,129,.18)';
                    } else if (st.status.indexOf('SAVEPOINT') !== -1 || st.status.indexOf('PARTIAL') !== -1 || st.status.indexOf('UNCOMMITTED') !== -1) {
                        col = '#fbbf24';
                        bg  = 'rgba(245,158,11,.18)';
                    }
                    return '<div style="background:#060911;border:1px solid var(--border-color);border-left:3px solid ' + col + ';border-radius:8px;padding:10px 12px;margin-bottom:8px;">' +
                        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">' +
                            '<strong style="color:#fff;font-size:12px;">Step ' + st.step + '</strong>' +
                            '<span style="background:' + bg + ';color:' + col + ';padding:2px 8px;border-radius:6px;font-size:10px;font-weight:800;font-family:monospace;">' + st.status + '</span>' +
                        '</div>' +
                        '<pre style="background:#0b1120;padding:7px 9px;border-radius:6px;color:#93c5fd;font-size:11px;overflow-x:auto;margin-bottom:6px;">' + st.sql + '</pre>' +
                        '<div style="font-size:12px;color:#cbd5e1;">' + st.detail + '</div>' +
                    '</div>';
                }).join('');
            }

            this.loadStatus();
        } catch (e) {
            console.error('Transaction error:', e);
        }
    },

    // ═══════════════════════════════════════════════════════════════════════
    // 4. INTERACTIVE ER DIAGRAM & 3NF / BCNF NORMALIZATION EXPLORER
    // ═══════════════════════════════════════════════════════════════════════
    loadSchema: async function() {
        try {
            var res  = await fetch('/api/dbms/schema');
            var data = await res.json();
            if (!data.success || !data.tables) return;
            this.schemaCatalog = data.tables;
            this.selectSchemaTable(this.selectedTable || 'simulation_sessions');
        } catch (e) {
            console.error('Schema load error:', e);
        }
    },

    selectSchemaTable: function(tableName) {
        this.selectedTable = tableName;

        // Highlight pill button
        document.querySelectorAll('.schema-pill-btn').forEach(function(btn) {
            var active = btn.getAttribute('data-tbl') === tableName;
            btn.style.background = active ? 'var(--primary)' : 'var(--secondary)';
            btn.style.color      = '#fff';
        });

        // Highlight SVG ER node box
        document.querySelectorAll('#er-diagram-svg .er-node').forEach(function(g) {
            var rect = g.querySelector('rect');
            if (!rect) return;
            if (g.getAttribute('data-tbl') === tableName) {
                rect.setAttribute('stroke-width', '3.5');
                rect.setAttribute('filter', 'drop-shadow(0 0 8px rgba(56,189,248,0.65))');
            } else {
                rect.setAttribute('stroke-width', '2');
                rect.removeAttribute('filter');
            }
        });

        if (!this.schemaCatalog || !this.schemaCatalog[tableName]) return;
        var meta = this.schemaCatalog[tableName];

        var nameEl  = document.getElementById('schema-insp-name');
        var nfEl    = document.getElementById('schema-insp-nf');
        var typeEl  = document.getElementById('schema-insp-type');
        var fdEl    = document.getElementById('schema-insp-fd');
        var proofEl = document.getElementById('schema-insp-proof');
        var colsEl  = document.getElementById('schema-insp-cols');

        if (nameEl)  nameEl.textContent  = '📋 ' + meta.name + ' (' + (meta.row_count || 0) + ' rows)';
        if (nfEl)    nfEl.textContent    = meta.normal_form;
        if (typeEl)  typeEl.textContent  = meta.entity_type;
        if (fdEl)    fdEl.textContent    = meta.fd;
        if (proofEl) proofEl.innerHTML   = '<strong>BCNF / 3NF Proof:</strong> ' + meta.bcnf_proof;

        if (colsEl && meta.columns) {
            var thead = '<thead><tr><th>Column</th><th>Data Type</th><th>Key</th><th>Purpose</th></tr></thead>';
            var tbody = '<tbody>' + meta.columns.map(function(c) {
                var keyBadge = '—';
                if (c.key === 'PK') {
                    keyBadge = '<span style="background:rgba(245,158,11,.2);color:#fbbf24;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:800;font-family:monospace;">🔑 PK</span>';
                } else if (c.key === 'FK') {
                    keyBadge = '<span style="background:rgba(56,189,248,.2);color:#38bdf8;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:800;font-family:monospace;">🔗 FK</span>';
                } else if (c.key === 'UK') {
                    keyBadge = '<span style="background:rgba(168,85,247,.2);color:#c084fc;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:800;font-family:monospace;">🔹 UK</span>';
                } else if (c.key === 'IDX') {
                    keyBadge = '<span style="background:rgba(148,163,184,.2);color:#cbd5e1;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:800;font-family:monospace;">⚡ IDX</span>';
                }
                return '<tr>' +
                    '<td style="font-family:monospace;font-weight:700;color:#fff;font-size:12px;">' + c.col + '</td>' +
                    '<td style="font-family:monospace;color:#93c5fd;font-size:11px;">' + c.type + '</td>' +
                    '<td>' + keyBadge + '</td>' +
                    '<td style="font-size:12px;color:var(--text-muted);">' + c.desc + '</td>' +
                '</tr>';
            }).join('') + '</tbody>';
            colsEl.innerHTML = '<table>' + thead + tbody + '</table>';
        }
    },

    showNormStep: function(nf) {
        document.querySelectorAll('.norm-step-btn').forEach(function(btn) {
            var active = btn.getAttribute('data-nf') === nf;
            btn.style.background = active ? 'var(--primary)' : 'var(--secondary)';
            btn.style.color      = '#fff';
        });

        var el = document.getElementById('norm-step-content');
        if (!el) return;

        if (nf === '1NF') {
            el.innerHTML =
                '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">' +
                    '<div style="background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.3);border-radius:8px;padding:14px;">' +
                        '<div style="font-weight:800;color:#f87171;margin-bottom:6px;font-size:13px;">❌ Unnormalized Form (UNF) — Violates 1NF</div>' +
                        '<p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">Storing comma-separated multi-valued lists of processes and files inside a single session row causes repeating groups and prevents SQL indexing:</p>' +
                        '<pre style="background:#060911;padding:10px;border-radius:6px;font-size:11px;color:#fca5a5;overflow-x:auto;">session_id | algorithm  | processes_list            | allocated_resources\n-----------+------------+---------------------------+--------------------\nDEMO_SES_01| RoundRobin | "P1:Browser, P2:Music..." | "PRINTER, DISK"</pre>' +
                    '</div>' +
                    '<div style="background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.3);border-radius:8px;padding:14px;">' +
                        '<div style="font-weight:800;color:#34d399;margin-bottom:6px;font-size:13px;">✅ First Normal Form (1NF) Achieved in SysRealm</div>' +
                        '<p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">Every attribute in <code>processes</code>, <code>files</code>, and <code>resource_allocations</code> holds a single <strong>atomic value</strong>, and repeating groups are extracted into child tables with foreign keys:</p>' +
                        '<pre style="background:#060911;padding:10px;border-radius:6px;font-size:11px;color:#6ee7b7;overflow-x:auto;">processes(id PK, session_id FK, pid, name, arrival_time, burst_time)\nresource_allocations(id PK, resource_id FK, pid, session_id FK, count)</pre>' +
                    '</div>' +
                '</div>';
        } else if (nf === '2NF') {
            el.innerHTML =
                '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">' +
                    '<div style="background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.3);border-radius:8px;padding:14px;">' +
                        '<div style="font-weight:800;color:#f87171;margin-bottom:6px;font-size:13px;">❌ Partial Dependency Anomaly — Violates 2NF</div>' +
                        '<p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">If <code>algorithm</code> and <code>quantum</code> were stored in the same table as composite key <code>(session_id, pid)</code>, then <code>session_id &rarr; algorithm</code> depends on only PART of the primary key:</p>' +
                        '<pre style="background:#060911;padding:10px;border-radius:6px;font-size:11px;color:#fca5a5;overflow-x:auto;">Composite Key: (session_id, pid)\nPartial FD:    session_id → {algorithm, quantum, cpu_utilization}\nAnomaly:       Deleting all processes of a session wipes the session itself!</pre>' +
                    '</div>' +
                    '<div style="background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.3);border-radius:8px;padding:14px;">' +
                        '<div style="font-weight:800;color:#34d399;margin-bottom:6px;font-size:13px;">✅ Second Normal Form (2NF) Achieved in SysRealm</div>' +
                        '<p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">Decomposed into <code>simulation_sessions</code> (keyed by <code>session_id</code>) and <code>processes</code> (where every PCB attribute fully depends on both <code>session_id</code> and <code>pid</code>):</p>' +
                        '<pre style="background:#060911;padding:10px;border-radius:6px;font-size:11px;color:#6ee7b7;overflow-x:auto;">R1: simulation_sessions(session_id PK, algorithm, quantum, status)\nR2: processes(session_id FK, pid, name, burst_time, memory_mb, state)\nFull FD: (session_id, pid) → {name, burst_time, memory_mb, state}</pre>' +
                    '</div>' +
                '</div>';
        } else {
            el.innerHTML =
                '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">' +
                    '<div style="background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.3);border-radius:8px;padding:14px;">' +
                        '<div style="font-weight:800;color:#f87171;margin-bottom:6px;font-size:13px;">❌ Transitive Dependency Anomaly — Violates 3NF</div>' +
                        '<p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">If <code>resource_allocations</code> stored <code>resource_name</code> and <code>total_units</code> directly, a non-key attribute determines another non-key attribute (<code>allocation_id &rarr; resource_id &rarr; resource_name</code>):</p>' +
                        '<pre style="background:#060911;padding:10px;border-radius:6px;font-size:11px;color:#fca5a5;overflow-x:auto;">allocation_id (PK) → resource_id → {resource_name, total_units, icon}\nUpdate Anomaly: Updating DISK total from 2 to 4 requires updating N rows!</pre>' +
                    '</div>' +
                    '<div style="background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.3);border-radius:8px;padding:14px;">' +
                        '<div style="font-weight:800;color:#34d399;margin-bottom:6px;font-size:13px;">✅ 3NF &amp; Boyce-Codd Normal Form (BCNF) Achieved</div>' +
                        '<p style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">Extracted <code>resources</code> catalog table so for every non-trivial Functional Dependency <code>X &rarr; Y</code> across all 8 tables, <strong>X is a Superkey</strong>:</p>' +
                        '<pre style="background:#060911;padding:10px;border-radius:6px;font-size:11px;color:#6ee7b7;overflow-x:auto;">R1: resources(resource_id PK, name, total, icon)\nR2: resource_allocations(id PK, resource_id FK, pid, session_id FK, status)\nLossless-Join &amp; Dependency-Preserving 3NF/BCNF Decomposition ✔</pre>' +
                    '</div>' +
                '</div>';
        }
    },

    currentOptPreset: 'join_filter',
    optPresets: {
        'join_filter': "SELECT u.username, p.name, p.burst_time\nFROM users u\nJOIN processes p ON u.email = p.session_id\nWHERE p.burst_time > 4 AND p.priority = 1;",
        'multi_join': "SELECT s.session_id, p.name, r.resource_id\nFROM simulation_sessions s\nJOIN processes p ON s.session_id = p.session_id\nJOIN resource_allocations r ON p.pid = r.pid\nWHERE s.algorithm = 'RoundRobin' AND p.memory_mb > 512;",
        'aggregate_filter': "SELECT s.algorithm, COUNT(p.id) as proc_count, AVG(p.burst_time) as avg_burst\nFROM simulation_sessions s\nJOIN processes p ON s.session_id = p.session_id\nWHERE s.status = 'ACTIVE'\nGROUP BY s.algorithm;"
    },

    selectOptPreset: function(presetKey) {
        this.currentOptPreset = presetKey;
        document.querySelectorAll('.opt-preset-btn').forEach(function(b) {
            b.classList.remove('active');
            b.style.background = 'var(--secondary)';
        });
        var activeBtn = document.getElementById('btn-opt-' + presetKey);
        if (activeBtn) {
            activeBtn.classList.add('active');
            activeBtn.style.background = 'var(--accent-blue)';
        }
        var sqlBox = document.getElementById('dbms-opt-sql');
        if (sqlBox) sqlBox.value = this.optPresets[presetKey] || '';
        this.runOptimizer(presetKey);
    },

    runOptimizer: async function(presetKey) {
        var key = presetKey || this.currentOptPreset || 'join_filter';
        var sqlBox = document.getElementById('dbms-opt-sql');
        if (sqlBox && !sqlBox.value.trim()) {
            sqlBox.value = this.optPresets[key] || '';
        }
        var customSql = sqlBox ? sqlBox.value.trim() : '';

        try {
            var res = await fetch('/api/dbms/optimize-query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ preset_key: key, custom_sql: customSql })
            });
            var data = await res.json();
            if (!data.success) {
                if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'Optimization error', 'error');
                return;
            }
            this.renderOptimizerUI(data);
            if (window.SysAnimations) {
                var redNote = (data.metrics && data.metrics.reduction_pct !== undefined) ? ' (' + data.metrics.reduction_pct + '% Heuristic Tuple Reduction)' : '';
                window.SysAnimations.showToast('Query transformed & optimized' + redNote, 'success');
            }
        } catch(e) {
            console.error('Optimizer error:', e);
        }
    },

    renderOptimizerUI: function(data) {
        var m = data.metrics || {};
        var elRed = document.getElementById('opt-stat-reduction');
        var elCost = document.getElementById('opt-stat-cost-detail');
        var elRows = document.getElementById('opt-stat-rows');
        var elTime = document.getElementById('opt-stat-time');
        var elTimeDet = document.getElementById('opt-stat-time-detail');
        var elEquiv = document.getElementById('opt-stat-equiv');
        var elEquivDet = document.getElementById('opt-stat-equiv-detail');
        var elEng = document.getElementById('opt-stat-engine');

        if (elRed) elRed.textContent = (m.reduction_pct || 0) + '%';
        if (elCost) {
            if (data.optimization_applied) {
                elCost.textContent = (m.naive_cost || 0) + ' ⟶ ' + (m.opt_cost || 0) + ' tuples';
            } else {
                elCost.textContent = 'Unchanged (Heuristic optimum)';
            }
        }
        if (elRows) elRows.textContent = Number(m.intermediate_rows_saved || 0).toLocaleString() + ' tuples';

        // Live measured execution time
        if (elTime) {
            if (m.measured_available && m.optimized_time_ms !== undefined && m.optimized_time_ms !== null) {
                elTime.textContent = m.optimized_time_ms + ' ms';
                if (elTimeDet) elTimeDet.textContent = 'Orig: ' + m.original_time_ms + 'ms ⟶ Opt: ' + m.optimized_time_ms + 'ms';
            } else {
                elTime.textContent = '—';
                if (elTimeDet) elTimeDet.textContent = 'Live timing unavailable';
            }
        }

        // Result equivalence status
        if (elEquiv) {
            if (m.results_equivalent === true) {
                elEquiv.textContent = '✔ Verified';
                elEquiv.style.color = '#4ade80';
                if (elEquivDet) elEquivDet.textContent = (m.optimized_row_count || 0) + ' rows identical';
            } else if (m.results_equivalent === false) {
                elEquiv.textContent = '✖ Fallback';
                elEquiv.style.color = '#f87171';
                if (elEquivDet) elEquivDet.textContent = 'Reverted to original';
            } else {
                elEquiv.textContent = '—';
                elEquiv.style.color = '#94a3b8';
                if (elEquivDet) elEquivDet.textContent = 'Equivalence not checked';
            }
        }

        if (elEng) elEng.textContent = data.engine_mode || 'MySQL CBO';

        // Status badge above generated SQL
        var statusBadge = document.getElementById('teacher-opt-status-badge');
        if (statusBadge) {
            statusBadge.style.display = 'block';
            if (!data.optimization_applied) {
                if (data.validation_error) {
                    statusBadge.innerHTML = '<div style="background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.4);border-radius:6px;padding:8px 12px;font-size:12px;color:#fca5a5;"><i class="fas fa-shield-alt" style="margin-right:6px;"></i> ' + data.validation_error + '</div>';
                } else {
                    statusBadge.innerHTML = '<div style="background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.4);border-radius:6px;padding:8px 12px;font-size:12px;color:#93c5fd;"><i class="fas fa-info-circle" style="margin-right:6px;"></i> ' + (data.reason || 'Query already follows optimal form or transformation not applicable; original query preserved.') + '</div>';
                }
            } else {
                statusBadge.innerHTML = '<div style="background:rgba(34,197,94,0.15);border:1px solid rgba(34,197,94,0.4);border-radius:6px;padding:8px 12px;font-size:12px;color:#86efac;"><i class="fas fa-check-circle" style="margin-right:6px;"></i> Heuristic Rewrite Applied &amp; Result Equivalence Verified (' + (m.reduction_pct || 0) + '% Estimated Reduction)</div>';
            }
        }

        // Synchronize teacher custom SQL input if empty or on preset load
        var teacherInput = document.getElementById('teacher-query-input');
        if (teacherInput && (!teacherInput.value.trim() || data.preset_key)) {
            teacherInput.value = data.sql || '';
        }

        // Render optimized SQL and transformation breakdown
        this.renderOptimizedSqlResult(data);

        // Trees
        this.renderTree('opt-tree-canonical', data.canonical_tree);
        this.renderTree('opt-tree-optimized', data.optimized_tree);

        // Rules
        this.renderRules(data.rules || []);

        // Real EXPLAIN output caching and rendering
        this.currentExplainData = {
            optimized: data.optimized_explain_plan || { available: true, plan_rows: data.explain_plan || [] },
            original: data.original_explain_plan || { available: true, plan_rows: [] }
        };
        this.switchExplainTab('optimized');
    },

    switchExplainTab: function(tabKey) {
        var optBtn = document.getElementById('btn-explain-tab-opt');
        var origBtn = document.getElementById('btn-explain-tab-orig');
        if (optBtn && origBtn) {
            if (tabKey === 'optimized') {
                optBtn.style.background = 'rgba(34,197,94,0.2)';
                optBtn.style.color = '#4ade80';
                optBtn.style.borderColor = '#4ade80';
                origBtn.style.background = 'rgba(255,255,255,0.06)';
                origBtn.style.color = '#cbd5e1';
                origBtn.style.borderColor = 'var(--border-color)';
            } else {
                origBtn.style.background = 'rgba(59,130,246,0.2)';
                origBtn.style.color = '#60a5fa';
                origBtn.style.borderColor = '#60a5fa';
                optBtn.style.background = 'rgba(255,255,255,0.06)';
                optBtn.style.color = '#cbd5e1';
                optBtn.style.borderColor = 'var(--border-color)';
            }
        }

        var planObj = (this.currentExplainData && this.currentExplainData[tabKey]) || { plan_rows: [] };
        this.renderExplainPlan(planObj.plan_rows || [], planObj.error, tabKey);
    },

    renderTree: function(containerId, treeData) {
        var container = document.getElementById(containerId);
        if (!container || !treeData) return;
        var nodes = treeData.nodes || [];

        container.innerHTML = nodes.map(function(n, idx) {
            var isArrow = idx < nodes.length - 1;
            var badgeBg = n.status === 'danger' ? 'rgba(239,68,68,0.2)' : 
                         (n.status === 'warning' ? 'rgba(245,158,11,0.2)' : 
                         (n.status === 'optimal' ? 'rgba(34,197,94,0.2)' : 'rgba(59,130,246,0.15)'));
            var badgeColor = n.status === 'danger' ? '#f87171' : 
                            (n.status === 'warning' ? '#fbbf24' : 
                            (n.status === 'optimal' ? '#4ade80' : '#60a5fa'));
            var borderColor = n.status === 'danger' ? 'rgba(239,68,68,0.4)' : 
                              (n.status === 'warning' ? 'rgba(245,158,11,0.4)' : 
                              (n.status === 'optimal' ? 'rgba(34,197,94,0.4)' : 'var(--border-color)'));

            return '<div style="width:100%;max-width:440px;background:#060911;border:1px solid ' + borderColor + ';border-radius:8px;padding:10px 14px;box-shadow:0 4px 12px rgba(0,0,0,0.3);">' +
                    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">' +
                        '<div style="font-weight:800;font-size:13px;color:' + badgeColor + ';font-family:monospace;">' +
                            '<span style="display:inline-block;width:22px;height:22px;line-height:22px;text-align:center;background:' + badgeBg + ';border-radius:4px;margin-right:8px;">' + n.symbol + '</span>' +
                            n.label +
                        '</div>' +
                        '<span class="badge" style="font-size:10px;background:' + badgeBg + ';color:' + badgeColor + ';">~' + Number(n.rows || 0).toLocaleString() + ' rows</span>' +
                    '</div>' +
                    '<div style="font-size:11px;color:var(--text-muted);line-height:1.4;">' + n.desc + '</div>' +
                '</div>' +
                (isArrow ? '<div style="color:var(--text-muted);font-size:16px;line-height:1;margin:-4px 0;">↓</div>' : '');
        }).join('');
    },

    renderRules: function(rules) {
        var container = document.getElementById('opt-rules-list');
        if (!container) return;
        container.innerHTML = rules.map(function(r) {
            return '<div style="background:#060911;border:1px solid var(--border-color);border-radius:8px;padding:12px;">' +
                    '<div style="font-weight:700;color:#38bdf8;font-size:13px;margin-bottom:6px;">' +
                        'Rule ' + r.rule_number + ': ' + r.title +
                    '</div>' +
                    '<div style="background:rgba(59,130,246,0.1);padding:6px 10px;border-radius:6px;font-family:monospace;font-size:12px;color:#fcd34d;margin-bottom:6px;">' +
                        r.math +
                    '</div>' +
                    '<div style="font-size:12px;color:var(--text-muted);line-height:1.4;">' +
                        r.explanation +
                    '</div>' +
                '</div>';
        }).join('');
    },

    renderExplainPlan: function(plan, errorMsg, tabType) {
        var tbody = document.getElementById('opt-explain-table');
        var badge = document.getElementById('opt-explain-plan-badge');
        if (badge) {
            badge.textContent = tabType === 'original' ? 'Execution plan for original SQL query' : 'Execution plan for heuristically rewritten SQL query';
        }
        if (!tbody) return;
        if (errorMsg) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#f87171;padding:14px;"><i class="fas fa-exclamation-triangle" style="margin-right:6px;"></i> ' + errorMsg + '</td></tr>';
            return;
        }
        if (!plan || plan.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:14px;">No execution plan steps returned by database engine.</td></tr>';
            return;
        }
        tbody.innerHTML = plan.map(function(row) {
            var typeBadge = (row.type && row.type.indexOf('ALL') !== -1)
                ? '<span class="badge" style="background:rgba(239,68,68,0.2);color:#fca5a5;border:1px solid rgba(239,68,68,0.4);">' + row.type + '</span>'
                : '<span class="badge" style="background:rgba(34,197,94,0.2);color:#86efac;border:1px solid rgba(34,197,94,0.4);">' + (row.type || 'Index Scan') + '</span>';
            return '<tr>' +
                    '<td style="font-weight:700;color:#fff;">' + (row.table || 'unknown') + '</td>' +
                    '<td>' + typeBadge + '</td>' +
                    '<td><code style="font-size:11px;">' + (row.possible_keys || 'None') + '</code></td>' +
                    '<td><code style="font-size:11px;color:#38bdf8;">' + (row.key || 'None') + '</code></td>' +
                    '<td style="font-weight:600;">' + (row.rows !== undefined ? row.rows : '—') + '</td>' +
                    '<td style="color:#f59e0b;">' + (row.filtered !== undefined ? row.filtered : '—') + '</td>' +
                    '<td style="font-size:11px;color:var(--text-muted);">' + (row.extra || '—') + '</td>' +
                '</tr>';
        }).join('');
    },

    teacherQuerySamples: {
        'comma_join': "SELECT *\nFROM processes p, simulation_sessions s\nWHERE p.session_id = s.session_id\n  AND p.burst_time > 4\n  AND p.priority = 1;",
        'multi_join_wildcard': "SELECT *\nFROM simulation_sessions s\nJOIN processes p ON s.session_id = p.session_id\nJOIN resource_allocations r ON p.pid = r.pid\nWHERE p.memory_mb > 512;",
        'subquery_in': "SELECT *\nFROM simulation_sessions\nWHERE session_id IN (\n    SELECT session_id\n    FROM processes\n    WHERE burst_time > 6\n);",
        'single_table_scan': "SELECT pid, name, memory_mb\nFROM processes\nWHERE burst_time > 5 AND priority = 1;",
        'left_join': "SELECT s.session_id, s.algorithm, p.pid\nFROM simulation_sessions s\nLEFT JOIN processes p ON s.session_id = p.session_id;",
        'resource_schema': "SELECT resource_id, name, total\nFROM resources\nWHERE total > 1;"
    },

    loadTeacherQuerySample: function(sampleKey) {
        var sql = this.teacherQuerySamples[sampleKey] || '';
        var inputEl = document.getElementById('teacher-query-input');
        if (inputEl) inputEl.value = sql;
        document.querySelectorAll('.teacher-sample-btn').forEach(function(b) {
            b.classList.remove('active');
            b.style.borderColor = 'var(--border-color)';
        });
        var activeBtn = document.getElementById('sample-btn-' + sampleKey);
        if (activeBtn) {
            activeBtn.classList.add('active');
            activeBtn.style.borderColor = '#c084fc';
        }
        this.runCustomQueryOptimizer();
    },

    runCustomQueryOptimizer: async function() {
        var inputEl = document.getElementById('teacher-query-input');
        var sql = inputEl ? inputEl.value.trim() : '';
        if (!sql) {
            if (window.SysAnimations) window.SysAnimations.showToast('Please enter an SQL query first', 'warning');
            return;
        }

        var btn = document.getElementById('btn-run-query-optimizer');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin" style="margin-right:6px;"></i> Optimizing &amp; Rewriting...';
        }

        try {
            var res = await fetch('/api/dbms/optimize-query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ custom_sql: sql })
            });
            var data = await res.json();
            if (!data.success) {
                if (window.SysAnimations) window.SysAnimations.showToast(data.error || 'Optimization error', 'error');
                return;
            }

            // Render both the rewritten SQL section and update trees & metrics
            this.renderOptimizedSqlResult(data);
            this.renderOptimizerUI(data);

            if (window.SysAnimations) {
                var pctText = (data.metrics && data.metrics.reduction_pct !== undefined) ? ' (' + data.metrics.reduction_pct + '% Heuristic Tuple Reduction)' : '';
                window.SysAnimations.showToast('✨ Optimized SQL Query & Relational Trees Generated' + pctText, 'success');
            }
        } catch(e) {
            console.error('Custom query optimizer error:', e);
            if (window.SysAnimations) window.SysAnimations.showToast('Failed to optimize query', 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '⚡ Generate Optimized Query &amp; Relational Trees';
            }
        }
    },

    renderOptimizedSqlResult: function(data) {
        var sqlBox = document.getElementById('teacher-optimized-sql');
        if (sqlBox) {
            this.currentOptimizedSql = data.optimized_sql || '';
            sqlBox.innerHTML = this.highlightSql(data.optimized_sql || '');
        }

        // Transformations
        var tfContainer = document.getElementById('teacher-opt-transformations');
        if (tfContainer) {
            var tfs = data.transformations || [];
            if (tfs.length === 0) {
                tfContainer.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px 0;">No heuristic transformations required. Query is already minimal.</div>';
            } else {
                tfContainer.innerHTML = tfs.map(function(t) {
                    return '<div style="background:#090d16;border:1px solid rgba(255,255,255,0.08);border-left:3px solid ' + (t.color || '#3b82f6') + ';border-radius:6px;padding:10px 12px;margin-bottom:8px;">' +
                        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;flex-wrap:wrap;gap:6px;">' +
                            '<strong style="color:#fff;font-size:12px;">' + t.name + '</strong>' +
                            '<span class="badge" style="font-size:10px;background:' + (t.color || '#3b82f6') + '22;color:' + (t.color || '#3b82f6') + ';border:1px solid ' + (t.color || '#3b82f6') + '44;">' + t.badge + '</span>' +
                        '</div>' +
                        '<div style="font-family:monospace;font-size:11px;color:#fcd34d;background:rgba(0,0,0,0.3);padding:4px 8px;border-radius:4px;margin-bottom:6px;">' +
                            t.rule +
                        '</div>' +
                        '<div style="font-size:11px;color:var(--text-muted);line-height:1.4;">' +
                            t.description +
                        '</div>' +
                    '</div>';
                }).join('');
            }
        }

        // Index recommendations
        var idxContainer = document.getElementById('teacher-opt-indexes');
        if (idxContainer) {
            var idxs = data.index_recommendations || [];
            if (idxs.length === 0) {
                idxContainer.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Existing indexes cover this access path.</div>';
            } else {
                idxContainer.innerHTML = idxs.map(function(idx) {
                    return '<div style="background:#090d16;border:1px solid rgba(59,130,246,0.3);border-radius:6px;padding:10px 12px;margin-bottom:8px;">' +
                        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">' +
                            '<span style="font-size:11px;font-weight:700;color:#60a5fa;"><i class="fas fa-key" style="margin-right:4px;"></i> Recommended Index (' + idx.table + ')</span>' +
                            '<button type="button" class="btn" onclick="navigator.clipboard.writeText(\'' + idx.sql.replace(/'/g, "\\'") + '\'); if(window.SysAnimations) window.SysAnimations.showToast(\'Index DDL Copied!\', \'info\');" style="font-size:10px;padding:2px 8px;">Copy DDL</button>' +
                        '</div>' +
                        '<code style="display:block;background:rgba(0,0,0,0.4);color:#a5f3fc;font-size:11px;padding:6px 8px;border-radius:4px;word-break:break-all;margin-bottom:4px;">' + idx.sql + '</code>' +
                        '<div style="font-size:11px;color:var(--text-muted);">' + idx.impact + '</div>' +
                    '</div>';
                }).join('');
            }
        }
    },

    copyOptimizedSql: function() {
        if (!this.currentOptimizedSql) {
            var sqlBox = document.getElementById('teacher-optimized-sql');
            this.currentOptimizedSql = sqlBox ? sqlBox.innerText : '';
        }
        if (this.currentOptimizedSql) {
            navigator.clipboard.writeText(this.currentOptimizedSql);
            if (window.SysAnimations) window.SysAnimations.showToast('📋 Optimized SQL copied to clipboard!', 'success');
        }
    },

    clearTeacherQueryInput: function() {
        var inputEl = document.getElementById('teacher-query-input');
        if (inputEl) {
            inputEl.value = '';
            inputEl.focus();
        }
    },

    prettifyTeacherQuery: function() {
        var inputEl = document.getElementById('teacher-query-input');
        if (!inputEl || !inputEl.value.trim()) return;
        var s = inputEl.value.trim();
        var kws = ['SELECT', 'FROM', 'INNER JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'JOIN', 'WHERE', 'GROUP BY', 'HAVING', 'ORDER BY', 'LIMIT', 'AND', 'OR', 'ON', 'AS', 'DISTINCT'];
        kws.forEach(function(kw) {
            var re = new RegExp('\\b' + kw + '\\b', 'gi');
            s = s.replace(re, kw);
        });
        inputEl.value = s;
        if (window.SysAnimations) window.SysAnimations.showToast('SQL formatted with uppercase keywords', 'info');
    },

    highlightSql: function(sql) {
        if (!sql) return '';
        var esc = sql.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        // Comments
        esc = esc.replace(/(\/\*[\s\S]*?\*\/)/g, '<span style="color:#fbbf24;font-style:italic;">$1</span>');
        // Keywords
        var kws = ['SELECT', 'FROM', 'INNER JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'JOIN', 'WHERE', 'ON', 'AS', 'AND', 'OR', 'ORDER BY', 'GROUP BY', 'LIMIT', 'DISTINCT', 'COUNT', 'AVG', 'SUM', 'MIN', 'MAX', 'IN'];
        kws.forEach(function(kw) {
            var re = new RegExp('\\b(' + kw + ')\\b', 'g');
            esc = esc.replace(re, '<span style="color:#38bdf8;font-weight:700;">$1</span>');
        });
        return esc;
    }
};

document.addEventListener('DOMContentLoaded', function() {
    DBMSController.init();
});
