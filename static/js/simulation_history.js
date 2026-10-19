/**
 * SysRealm — Simulation History & Performance Analytics Controller
 * 
 * Manages experiment archive, multi-algorithm side-by-side comparisons,
 * workload equivalence hash verification, process-level PCB inspection,
 * workload reproduction (rerun), and relational DBMS analytics reporting.
 */

const SimulationHistoryController = {
    activeTab: 'runs',
    selectedRunIds: new Set(),
    currentPage: 1,
    limit: 15,
    totalPages: 1,
    currentFilter: {
        algorithm: '',
        search: '',
        sort_by: 'created_at',
        order: 'desc',
        start_date: '',
        end_date: '',
        workload_hash: ''
    },
    runsCache: [],
    initialized: false,

    ALGO_COLORS: {
        'FCFS': '#3b82f6',
        'SJF': '#10b981',
        'Priority': '#f59e0b',
        'RoundRobin': '#ef4444'
    },

    init() {
        if (this.initialized) {
            this.refreshCurrentTab();
            return;
        }
        this.initialized = true;

        // Search and filter listeners
        const searchInput = document.getElementById('sim-filter-search');
        if (searchInput) {
            let debounceTimer = null;
            searchInput.addEventListener('input', (e) => {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    this.currentFilter.search = e.target.value.trim();
                    this.currentPage = 1;
                    this.loadRuns();
                }, 300);
            });
        }

        const algoSelect = document.getElementById('sim-filter-algo');
        if (algoSelect) {
            algoSelect.addEventListener('change', (e) => {
                this.currentFilter.algorithm = e.target.value;
                this.currentPage = 1;
                this.loadRuns();
            });
        }

        const sortSelect = document.getElementById('sim-filter-sort');
        if (sortSelect) {
            sortSelect.addEventListener('change', (e) => {
                const val = e.target.value;
                if (val.endsWith('_asc')) {
                    this.currentFilter.sort_by = val.replace('_asc', '');
                    this.currentFilter.order = 'asc';
                } else if (val.endsWith('_desc')) {
                    this.currentFilter.sort_by = val.replace('_desc', '');
                    this.currentFilter.order = 'desc';
                } else {
                    this.currentFilter.sort_by = val;
                    this.currentFilter.order = 'desc';
                }
                this.currentPage = 1;
                this.loadRuns();
            });
        }

        // Pagination buttons
        const prevBtn = document.getElementById('sim-page-prev');
        if (prevBtn) {
            prevBtn.addEventListener('click', () => {
                if (this.currentPage > 1) {
                    this.currentPage--;
                    this.loadRuns();
                }
            });
        }

        const nextBtn = document.getElementById('sim-page-next');
        if (nextBtn) {
            nextBtn.addEventListener('click', () => {
                if (this.currentPage < this.totalPages) {
                    this.currentPage++;
                    this.loadRuns();
                }
            });
        }

        // Initial load
        this.loadRuns();
        this.loadAnalytics();
    },

    refreshCurrentTab() {
        if (this.activeTab === 'runs') {
            this.loadRuns();
        } else if (this.activeTab === 'analytics') {
            this.loadAnalytics();
        }
    },

    switchTab(tabName) {
        this.activeTab = tabName;
        ['runs', 'compare', 'analytics'].forEach(t => {
            const btn = document.getElementById(`tab-btn-sim-${t}`);
            const pane = document.getElementById(`sim-subtab-${t}`);
            if (btn) {
                if (t === tabName) {
                    btn.classList.add('active');
                    btn.style.borderBottom = '3px solid var(--primary, #3b82f6)';
                    btn.style.color = 'var(--text-color, #1e293b)';
                } else {
                    btn.classList.remove('active');
                    btn.style.borderBottom = 'none';
                    btn.style.color = 'var(--text-muted, #64748b)';
                }
            }
            if (pane) {
                pane.style.display = (t === tabName) ? 'block' : 'none';
            }
        });

        if (tabName === 'runs') {
            this.loadRuns();
        } else if (tabName === 'analytics') {
            this.loadAnalytics();
        }
    },

    async loadRuns() {
        const tbody = document.getElementById('sim-runs-tbody');
        if (!tbody) return;

        tbody.innerHTML = `<tr><td colspan="10" style="text-align:center;padding:30px;color:var(--text-muted);"><i class="fas fa-spinner fa-spin"></i> Loading simulation runs from relational database...</td></tr>`;

        const params = new URLSearchParams({
            page: this.currentPage,
            limit: this.limit,
            sort_by: this.currentFilter.sort_by,
            order: this.currentFilter.order
        });

        if (this.currentFilter.algorithm) params.append('algorithm', this.currentFilter.algorithm);
        if (this.currentFilter.search) params.append('search', this.currentFilter.search);
        if (this.currentFilter.workload_hash) params.append('workload_hash', this.currentFilter.workload_hash);

        try {
            const res = await fetch(`/api/simulation/history?${params.toString()}`);
            const data = await res.json();
            if (!data.success) {
                tbody.innerHTML = `<tr><td colspan="10" style="text-align:center;padding:24px;color:#ef4444;"><i class="fas fa-exclamation-triangle"></i> Error: ${data.error || 'Failed to load runs'}</td></tr>`;
                return;
            }

            this.runsCache = data.runs || [];
            this.totalPages = data.pages || 1;

            // Update pagination UI
            const pageInfo = document.getElementById('sim-page-info');
            if (pageInfo) pageInfo.textContent = `Page ${data.page} of ${this.totalPages} (${data.total} total runs)`;
            const prevBtn = document.getElementById('sim-page-prev');
            if (prevBtn) prevBtn.disabled = (this.currentPage <= 1);
            const nextBtn = document.getElementById('sim-page-next');
            if (nextBtn) nextBtn.disabled = (this.currentPage >= this.totalPages);

            if (this.runsCache.length === 0) {
                tbody.innerHTML = `<tr><td colspan="10" style="text-align:center;padding:40px;color:var(--text-muted);">
                    <i class="fas fa-inbox" style="font-size:32px;margin-bottom:10px;opacity:0.5;"></i><br>
                    No simulation runs match the specified filter.<br>
                    <span style="font-size:12px;">Run CPU scheduling simulations or click "Reset Filters".</span>
                </td></tr>`;
                return;
            }

            tbody.innerHTML = '';
            this.runsCache.forEach(run => {
                const tr = document.createElement('tr');
                const isChecked = this.selectedRunIds.has(run.run_id);
                const algoColor = this.ALGO_COLORS[run.algorithm] || '#3b82f6';
                const qText = run.quantum ? ` <span style="font-size:11px;opacity:0.8;">(Q=${run.quantum})</span>` : '';

                tr.innerHTML = `
                    <td style="text-align:center;width:40px;">
                        <input type="checkbox" value="${run.run_id}" ${isChecked ? 'checked' : ''} onchange="SimulationHistoryController.toggleSelectRun('${run.run_id}', this.checked)">
                    </td>
                    <td>
                        <strong style="font-family:monospace;color:var(--primary);font-size:13px;">${run.run_id}</strong>
                        <div style="font-size:12px;color:var(--text-muted);">${escapeHtml(run.run_name || 'Experiment Run')}</div>
                    </td>
                    <td>
                        <span style="background:${algoColor}18;color:${algoColor};border:1px solid ${algoColor}40;padding:3px 8px;border-radius:12px;font-size:12px;font-weight:700;">
                            ${run.algorithm}${qText}
                        </span>
                    </td>
                    <td style="text-align:center;">
                        <span class="badge" style="background:rgba(100,116,139,0.15);color:var(--text-color);padding:2px 8px;border-radius:8px;font-size:12px;">
                            ${run.process_count} procs
                        </span>
                    </td>
                    <td>
                        <span style="font-family:monospace;font-size:11px;background:#f1f5f9;color:#475569;padding:2px 6px;border-radius:6px;border:1px solid #cbd5e1;" title="Workload Hash: Identifies unique process arrival, burst, and priority sets">
                            #${(run.workload_hash || '----').substring(0, 8)}
                        </span>
                    </td>
                    <td style="font-weight:600;color:#0ea5e9;">${Number(run.avg_waiting_time).toFixed(2)} ms</td>
                    <td style="font-weight:600;color:#8b5cf6;">${Number(run.avg_turnaround_time).toFixed(2)} ms</td>
                    <td><strong style="color:${Number(run.cpu_utilization) >= 90 ? '#10b981' : '#f59e0b'};">${Number(run.cpu_utilization).toFixed(1)}%</strong></td>
                    <td style="font-family:monospace;font-size:12px;">${Number(run.throughput).toFixed(3)}</td>
                    <td style="text-align:center;">
                        <span style="background:rgba(148,163,184,0.15);padding:2px 6px;border-radius:6px;font-size:12px;font-weight:600;">
                            ${run.context_switches || 0}
                        </span>
                    </td>
                    <td style="font-size:12px;color:var(--text-muted);white-space:nowrap;">
                        ${formatDate(run.created_at)}
                    </td>
                    <td style="text-align:right;white-space:nowrap;">
                        <button type="button" class="btn btn-sm" onclick="SimulationHistoryController.inspectRun('${run.run_id}')" title="Inspect Process Execution Details & Gantt" style="background:#f1f5f9;color:#1e293b;border:1px solid #cbd5e1;padding:4px 8px;margin-right:4px;">
                            <i class="fas fa-search"></i> Details
                        </button>
                        <button type="button" class="btn btn-sm btn-primary" onclick="SimulationHistoryController.rerunWorkload('${run.run_id}')" title="Load Workload into Simulator for Fair Testing" style="padding:4px 8px;margin-right:4px;">
                            <i class="fas fa-redo"></i> Rerun
                        </button>
                        <button type="button" class="btn btn-sm" onclick="SimulationHistoryController.deleteRun('${run.run_id}')" title="Delete Saved Run" style="background:#fee2e2;color:#dc2626;border:1px solid #fecaca;padding:4px 8px;">
                            <i class="fas fa-trash-alt"></i>
                        </button>
                    </td>
                `;
                tbody.appendChild(tr);
            });

            this.updateCompareButtonState();

        } catch (e) {
            console.error('Error loading simulation history runs:', e);
            tbody.innerHTML = `<tr><td colspan="10" style="text-align:center;padding:24px;color:#ef4444;"><i class="fas fa-exclamation-triangle"></i> Failed to communicate with backend: ${e.message}</td></tr>`;
        }
    },

    toggleSelectRun(runId, isChecked) {
        if (isChecked) {
            this.selectedRunIds.add(runId);
        } else {
            this.selectedRunIds.delete(runId);
        }
        this.updateCompareButtonState();
    },

    toggleSelectAll(checked) {
        this.runsCache.forEach(r => {
            if (checked) {
                this.selectedRunIds.add(r.run_id);
            } else {
                this.selectedRunIds.delete(r.run_id);
            }
        });
        const checkboxes = document.querySelectorAll('#sim-runs-tbody input[type="checkbox"]');
        checkboxes.forEach(cb => cb.checked = checked);
        this.updateCompareButtonState();
    },

    updateCompareButtonState() {
        const count = this.selectedRunIds.size;
        const countEl = document.getElementById('sim-selected-count');
        if (countEl) countEl.textContent = count;
        const btn = document.getElementById('btn-sim-compare-selected');
        if (btn) {
            btn.disabled = (count < 2 || count > 5);
            if (count < 2) {
                btn.title = "Select at least 2 runs to compare";
            } else if (count > 5) {
                btn.title = "Select maximum 5 runs to compare";
            } else {
                btn.title = `Compare ${count} selected simulation runs side-by-side`;
            }
        }
    },

    compareSelected() {
        if (this.selectedRunIds.size < 2) {
            alert('Please select at least 2 simulation runs from the table to compare.');
            return;
        }
        if (this.selectedRunIds.size > 5) {
            alert('You can select a maximum of 5 runs to compare simultaneously.');
            return;
        }
        this.compareRuns(Array.from(this.selectedRunIds));
    },

    async compareRuns(runIds) {
        const wrap = document.getElementById('sim-subtab-compare');
        if (!wrap) return;

        this.switchTab('compare');
        wrap.innerHTML = `<div style="text-align:center;padding:60px;color:var(--text-muted);"><i class="fas fa-spinner fa-spin fa-2x"></i><br><br>Analyzing algorithm performance &amp; workload equivalence...</div>`;

        try {
            const res = await fetch('/api/simulation/compare', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ run_ids: runIds })
            });
            const data = await res.json();
            if (!data.success) {
                wrap.innerHTML = `<div class="card" style="padding:24px;border-left:4px solid #ef4444;">
                    <h3 style="color:#ef4444;"><i class="fas fa-exclamation-triangle"></i> Comparison Error</h3>
                    <p style="color:var(--text-muted);">${data.error || 'Failed to compare runs.'}</p>
                    <button class="btn btn-secondary" onclick="SimulationHistoryController.switchTab('runs')">Back to Archive</button>
                </div>`;
                return;
            }

            this.renderComparisonView(data);

        } catch (e) {
            console.error('Comparison error:', e);
            wrap.innerHTML = `<div class="card" style="padding:24px;border-left:4px solid #ef4444;">
                <h3 style="color:#ef4444;"><i class="fas fa-exclamation-triangle"></i> Network Error</h3>
                <p>${e.message}</p>
            </div>`;
        }
    },

    renderComparisonView(data) {
        const wrap = document.getElementById('sim-subtab-compare');
        if (!wrap) return;

        const runs = data.runs || [];
        const isFair = data.fair_comparison;
        const winner = data.winner || {};
        const analysis = data.educational_analysis || {};

        let alertBanner = '';
        if (isFair) {
            alertBanner = `
                <div style="background:#ecfdf5;border:1px solid #a7f3d0;border-left:5px solid #10b981;border-radius:10px;padding:16px;margin-bottom:20px;display:flex;align-items:flex-start;gap:12px;">
                    <div style="color:#10b981;font-size:24px;"><i class="fas fa-check-circle"></i></div>
                    <div>
                        <strong style="color:#065f46;font-size:15px;">Workload Equivalence Verified: 100% Fair Benchmark</strong>
                        <p style="margin:4px 0 0;font-size:13px;color:#047857;line-height:1.5;">
                            All <strong>${runs.length}</strong> compared simulation runs executed against the exact identical process workload 
                            (Workload Hash: <code style="background:#d1fae5;padding:2px 6px;border-radius:4px;">${data.workload_hashes[0]}</code>).
                            Since arrival times, burst times, and process counts are identical, differences in metrics directly reflect operating systems scheduling algorithm trade-offs!
                        </p>
                    </div>
                </div>
            `;
        } else {
            alertBanner = `
                <div style="background:#fffbeb;border:1px solid #fde68a;border-left:5px solid #f59e0b;border-radius:10px;padding:16px;margin-bottom:20px;display:flex;align-items:flex-start;gap:12px;">
                    <div style="color:#f59e0b;font-size:24px;"><i class="fas fa-exclamation-triangle"></i></div>
                    <div>
                        <strong style="color:#92400e;font-size:15px;">Workload Mismatch Detected</strong>
                        <p style="margin:4px 0 0;font-size:13px;color:#b45309;line-height:1.5;">
                            ${escapeHtml(data.workload_warning || 'The selected runs used different process workloads. Comparing algorithms across non-identical workloads is scientifically invalid.')}
                        </p>
                    </div>
                </div>
            `;
        }

        // Winner cards
        const winnerCards = `
            <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(210px, 1fr));gap:14px;margin-bottom:24px;">
                <div class="card" style="background:#f8fafc;border-top:3px solid #0ea5e9;padding:14px;">
                    <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;">Lowest Avg Waiting Time</div>
                    <div style="font-size:22px;font-weight:800;color:#0ea5e9;margin:6px 0;">${winner.lowest_waiting_time ? winner.lowest_waiting_time.value + ' ms' : '-'}</div>
                    <div style="font-size:12px;font-weight:600;color:#1e293b;">🏆 ${winner.lowest_waiting_time ? winner.lowest_waiting_time.algorithm : '-'}</div>
                </div>
                <div class="card" style="background:#f8fafc;border-top:3px solid #8b5cf6;padding:14px;">
                    <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;">Lowest Avg Turnaround</div>
                    <div style="font-size:22px;font-weight:800;color:#8b5cf6;margin:6px 0;">${winner.lowest_turnaround_time ? winner.lowest_turnaround_time.value + ' ms' : '-'}</div>
                    <div style="font-size:12px;font-weight:600;color:#1e293b;">🏆 ${winner.lowest_turnaround_time ? winner.lowest_turnaround_time.algorithm : '-'}</div>
                </div>
                <div class="card" style="background:#f8fafc;border-top:3px solid #10b981;padding:14px;">
                    <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;">Peak CPU Utilization</div>
                    <div style="font-size:22px;font-weight:800;color:#10b981;margin:6px 0;">${winner.highest_cpu_utilization ? winner.highest_cpu_utilization.value + '%' : '-'}</div>
                    <div style="font-size:12px;font-weight:600;color:#1e293b;">🏆 ${winner.highest_cpu_utilization ? winner.highest_cpu_utilization.algorithm : '-'}</div>
                </div>
                <div class="card" style="background:#f8fafc;border-top:3px solid #f59e0b;padding:14px;">
                    <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;">Peak Throughput</div>
                    <div style="font-size:22px;font-weight:800;color:#f59e0b;margin:6px 0;">${winner.highest_throughput ? Number(winner.highest_throughput.value).toFixed(3) : '-'}</div>
                    <div style="font-size:12px;font-weight:600;color:#1e293b;">🏆 ${winner.highest_throughput ? winner.highest_throughput.algorithm : '-'}</div>
                </div>
                <div class="card" style="background:#f8fafc;border-top:3px solid #64748b;padding:14px;">
                    <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;">Fewest Context Switches</div>
                    <div style="font-size:22px;font-weight:800;color:#64748b;margin:6px 0;">${winner.fewest_context_switches ? winner.fewest_context_switches.value : '-'}</div>
                    <div style="font-size:12px;font-weight:600;color:#1e293b;">🏆 ${winner.fewest_context_switches ? winner.fewest_context_switches.algorithm : '-'}</div>
                </div>
            </div>
        `;

        // Side-by-side Table Header & Rows
        let tableHeader = `<th>Metric / Property</th>`;
        runs.forEach(r => {
            const algoColor = this.ALGO_COLORS[r.algorithm] || '#3b82f6';
            tableHeader += `
                <th style="min-width:180px;">
                    <div style="display:flex;align-items:center;gap:6px;">
                        <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${algoColor};"></span>
                        <strong style="color:#0f172a;">${r.algorithm}</strong>
                        ${r.quantum ? `<span style="font-size:11px;color:var(--text-muted);">(Q=${r.quantum})</span>` : ''}
                    </div>
                    <div style="font-size:11px;font-family:monospace;color:var(--text-muted);margin-top:2px;">${r.run_id}</div>
                </th>
            `;
        });

        const rowsData = [
            { label: 'Processes Count', key: r => `${r.process_count} procs` },
            { label: 'Workload Hash', key: r => `<code style="font-size:11px;background:#f1f5f9;padding:2px 4px;border-radius:4px;">#${(r.workload_hash || '').substring(0, 8)}</code>` },
            { label: 'Average Waiting Time (AWT)', key: r => `<strong style="color:#0ea5e9;">${Number(r.avg_waiting_time).toFixed(2)} ms</strong> ${winner.lowest_waiting_time && winner.lowest_waiting_time.run_id === r.run_id ? '🏆' : ''}` },
            { label: 'Average Turnaround Time (ATAT)', key: r => `<strong style="color:#8b5cf6;">${Number(r.avg_turnaround_time).toFixed(2)} ms</strong> ${winner.lowest_turnaround_time && winner.lowest_turnaround_time.run_id === r.run_id ? '🏆' : ''}` },
            { label: 'Average Response Time (ART)', key: r => `${Number(r.avg_response_time).toFixed(2)} ms` },
            { label: 'CPU Utilization', key: r => `<strong>${Number(r.cpu_utilization).toFixed(1)}%</strong> ${winner.highest_cpu_utilization && winner.highest_cpu_utilization.run_id === r.run_id ? '🏆' : ''}` },
            { label: 'Throughput', key: r => `${Number(r.throughput).toFixed(4)} proc/ms ${winner.highest_throughput && winner.highest_throughput.run_id === r.run_id ? '🏆' : ''}` },
            { label: 'Context Switches', key: r => `<strong>${r.context_switches || 0}</strong> ${winner.fewest_context_switches && winner.fewest_context_switches.run_id === r.run_id ? '🏆' : ''}` },
            { label: 'Execution Timestamp', key: r => formatDate(r.created_at) }
        ];

        let tableRows = '';
        rowsData.forEach(row => {
            tableRows += `<tr><td style="font-weight:600;color:#334155;background:#f8fafc;">${row.label}</td>`;
            runs.forEach(r => {
                tableRows += `<td>${row.key(r)}</td>`;
            });
            tableRows += `</tr>`;
        });

        // Gantt timelines side-by-side
        let ganttBars = '';
        runs.forEach(r => {
            const ganttId = `gantt-cmp-${r.run_id.replace(/[^a-zA-Z0-9]/g, '_')}`;
            ganttBars += `
                <div style="margin-bottom:16px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                        <div>
                            <strong style="color:#0f172a;">${r.algorithm}</strong> 
                            ${r.quantum ? `<span style="font-size:12px;color:var(--text-muted);">(Quantum=${r.quantum})</span>` : ''}
                            <span style="font-size:11px;font-family:monospace;color:var(--text-muted);margin-left:8px;">${r.run_id}</span>
                        </div>
                        <span style="font-size:12px;font-weight:600;color:var(--text-muted);">${r.context_switches || 0} switches</span>
                    </div>
                    <div id="${ganttId}" style="display:flex;height:36px;background:#f1f5f9;border-radius:6px;overflow:hidden;border:1px solid #e2e8f0;position:relative;"></div>
                </div>
            `;
        });

        // Educational insights
        let insightsHtml = '';
        if (analysis.insights && analysis.insights.length > 0) {
            insightsHtml = `
                <div class="card" style="margin-top:20px;background:#f8fafc;border-left:4px solid var(--primary);">
                    <h3 style="margin-top:0;font-size:16px;color:#0f172a;"><i class="fas fa-graduation-cap"></i> Operating Systems Analysis &amp; Trade-offs</h3>
                    <ul style="margin:8px 0;padding-left:20px;color:#334155;line-height:1.7;font-size:13px;">
                        ${analysis.insights.map(i => `<li>${escapeHtml(i)}</li>`).join('')}
                    </ul>
                </div>
            `;
        }

        wrap.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">
                <div>
                    <h2 style="margin:0;font-size:20px;color:#0f172a;">Multi-Algorithm Benchmark Comparison</h2>
                    <div style="font-size:13px;color:var(--text-muted);">Comparing ${runs.length} simulation experiments side-by-side</div>
                </div>
                <button class="btn btn-secondary btn-sm" onclick="SimulationHistoryController.switchTab('runs')">
                    <i class="fas fa-arrow-left"></i> Back to Archive
                </button>
            </div>

            ${alertBanner}
            ${winnerCards}

            <div class="card" style="margin-bottom:20px;">
                <h3 style="margin-top:0;font-size:16px;color:#0f172a;margin-bottom:14px;"><i class="fas fa-table"></i> Metric Comparison Grid</h3>
                <div class="table-container">
                    <table>
                        <thead><tr>${tableHeader}</tr></thead>
                        <tbody>${tableRows}</tbody>
                    </table>
                </div>
            </div>

            <div class="card" style="margin-bottom:20px;">
                <h3 style="margin-top:0;font-size:16px;color:#0f172a;margin-bottom:14px;"><i class="fas fa-stream"></i> Timeline Comparison (Gantt Execution Orders)</h3>
                ${ganttBars}
            </div>

            ${insightsHtml}
        `;

        // Render each Gantt bar
        setTimeout(() => {
            runs.forEach(r => {
                const ganttId = `gantt-cmp-${r.run_id.replace(/[^a-zA-Z0-9]/g, '_')}`;
                this.renderGanttSegments(r.gantt_chart, ganttId);
            });
        }, 50);
    },

    renderGanttSegments(segments, containerId) {
        const container = document.getElementById(containerId);
        if (!container || !segments || segments.length === 0) return;

        const maxTime = Math.max(...segments.map(s => s.end || 0), 1);
        container.innerHTML = '';

        segments.forEach(seg => {
            const start = seg.start || 0;
            const end = seg.end || 0;
            const duration = end - start;
            if (duration <= 0) return;

            const widthPercent = (duration / maxTime) * 100;
            const isIdle = (seg.process === 'IDLE');
            const color = isIdle ? '#cbd5e1' : (seg.color || this.ALGO_COLORS[seg.process] || '#3b82f6');

            const block = document.createElement('div');
            block.style.width = `${widthPercent}%`;
            block.style.height = '100%';
            block.style.background = color;
            block.style.display = 'flex';
            block.style.flexDirection = 'column';
            block.style.alignItems = 'center';
            block.style.justifyContent = 'center';
            block.style.color = isIdle ? '#475569' : '#ffffff';
            block.style.fontSize = '11px';
            block.style.fontWeight = '700';
            block.style.borderRight = '1px solid rgba(255,255,255,0.3)';
            block.style.boxSizing = 'border-box';
            block.title = `${seg.process}: ${start}ms → ${end}ms (${duration}ms)`;

            if (widthPercent > 6) {
                block.innerHTML = `<span>${seg.process}</span><span style="font-size:9px;opacity:0.85;">${start}-${end}</span>`;
            } else if (widthPercent > 3) {
                block.innerHTML = `<span>${seg.process}</span>`;
            }

            container.appendChild(block);
        });
    },

    async inspectRun(runId) {
        try {
            const res = await fetch(`/api/simulation/history/${runId}`);
            const data = await res.json();
            if (!data.success) {
                alert(`Error: ${data.error || 'Failed to fetch run details'}`);
                return;
            }

            const run = data.run;
            const procs = data.processes || [];
            const gantt = data.gantt_chart || [];
            const expl = data.educational_explanation || {};

            const modal = document.getElementById('sim-run-modal');
            const content = document.getElementById('sim-run-modal-content');
            if (!modal || !content) return;

            const algoColor = this.ALGO_COLORS[run.algorithm] || '#3b82f6';
            const qStr = run.quantum ? ` (Quantum = ${run.quantum})` : '';

            let procRows = '';
            procs.forEach(p => {
                procRows += `
                    <tr>
                        <td><strong style="color:var(--primary);">${p.pid}</strong></td>
                        <td>${escapeHtml(p.name)}</td>
                        <td style="text-align:center;">${p.arrival_time} ms</td>
                        <td style="text-align:center;font-weight:600;">${p.burst_time} ms</td>
                        <td style="text-align:center;"><span class="badge" style="background:#f1f5f9;color:#334155;padding:2px 6px;">${p.priority}</span></td>
                        <td style="text-align:center;">${p.memory_mb} MB</td>
                        <td style="text-align:center;">${p.start_time != null ? p.start_time + ' ms' : '-'}</td>
                        <td style="text-align:center;font-weight:600;">${p.completion_time != null ? p.completion_time + ' ms' : '-'}</td>
                        <td style="text-align:center;color:#0ea5e9;font-weight:700;">${p.waiting_time} ms</td>
                        <td style="text-align:center;color:#8b5cf6;font-weight:700;">${p.turnaround_time} ms</td>
                        <td style="text-align:center;">${p.response_time != null ? p.response_time + ' ms' : '-'}</td>
                    </tr>
                `;
            });

            content.innerHTML = `
                <div style="display:flex;justify-content:space-between;align-items:flex-start;border-bottom:1px solid #e2e8f0;padding-bottom:16px;margin-bottom:16px;">
                    <div>
                        <div style="display:flex;align-items:center;gap:10px;">
                            <h2 style="margin:0;font-size:20px;color:#0f172a;">${escapeHtml(run.run_name || 'Simulation Run')}</h2>
                            <span style="background:${algoColor}18;color:${algoColor};border:1px solid ${algoColor}40;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:700;">
                                ${run.algorithm}${qStr}
                            </span>
                        </div>
                        <div style="font-size:12px;color:var(--text-muted);margin-top:4px;display:flex;gap:14px;">
                            <span>Run ID: <code style="font-family:monospace;font-weight:700;">${run.run_id}</code></span>
                            <span>Session: <code style="font-family:monospace;">${run.session_id || 'N/A'}</code></span>
                            <span>Workload Hash: <code style="font-family:monospace;">#${(run.workload_hash || '').substring(0, 8)}</code></span>
                            <span>Executed: ${formatDate(run.created_at)}</span>
                        </div>
                    </div>
                    <button type="button" class="btn btn-secondary btn-sm" onclick="SimulationHistoryController.closeModal()" style="font-size:16px;line-height:1;padding:6px 10px;">✕</button>
                </div>

                <!-- KPI Metric Pills -->
                <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(130px, 1fr));gap:10px;margin-bottom:18px;">
                    <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;padding:10px;text-align:center;">
                        <div style="font-size:11px;color:#0369a1;font-weight:600;">Avg Waiting Time</div>
                        <div style="font-size:18px;font-weight:800;color:#0284c7;margin-top:2px;">${Number(run.avg_waiting_time).toFixed(2)} ms</div>
                    </div>
                    <div style="background:#f5f3ff;border:1px solid #ddd6fe;border-radius:8px;padding:10px;text-align:center;">
                        <div style="font-size:11px;color:#6d28d9;font-weight:600;">Avg Turnaround</div>
                        <div style="font-size:18px;font-weight:800;color:#7c3aed;margin-top:2px;">${Number(run.avg_turnaround_time).toFixed(2)} ms</div>
                    </div>
                    <div style="background:#ecfdf5;border:1px solid #a7f3d0;border-radius:8px;padding:10px;text-align:center;">
                        <div style="font-size:11px;color:#047857;font-weight:600;">CPU Utilization</div>
                        <div style="font-size:18px;font-weight:800;color:#059669;margin-top:2px;">${Number(run.cpu_utilization).toFixed(1)}%</div>
                    </div>
                    <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:10px;text-align:center;">
                        <div style="font-size:11px;color:#b45309;font-weight:600;">Throughput</div>
                        <div style="font-size:18px;font-weight:800;color:#d97706;margin-top:2px;">${Number(run.throughput).toFixed(3)}</div>
                    </div>
                    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px;text-align:center;">
                        <div style="font-size:11px;color:#475569;font-weight:600;">Context Switches</div>
                        <div style="font-size:18px;font-weight:800;color:#334155;margin-top:2px;">${run.context_switches || 0}</div>
                    </div>
                </div>

                <!-- Visual Gantt Timeline -->
                <div style="margin-bottom:18px;">
                    <div style="font-size:13px;font-weight:700;color:#0f172a;margin-bottom:6px;"><i class="fas fa-stream"></i> Reconstructed Gantt Timeline</div>
                    <div id="sim-modal-gantt" style="display:flex;height:40px;background:#f8fafc;border-radius:6px;overflow:hidden;border:1px solid #cbd5e1;"></div>
                </div>

                <!-- Process PCB Table -->
                <div style="margin-bottom:18px;">
                    <div style="font-size:13px;font-weight:700;color:#0f172a;margin-bottom:6px;"><i class="fas fa-table"></i> Process-Level Execution Records (Process Control Blocks)</div>
                    <div class="table-container" style="max-height:260px;overflow-y:auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>PID</th>
                                    <th>Name</th>
                                    <th style="text-align:center;">Arrival</th>
                                    <th style="text-align:center;">Burst</th>
                                    <th style="text-align:center;">Priority</th>
                                    <th style="text-align:center;">Memory</th>
                                    <th style="text-align:center;">Start</th>
                                    <th style="text-align:center;">Completion</th>
                                    <th style="text-align:center;">Waiting</th>
                                    <th style="text-align:center;">Turnaround</th>
                                    <th style="text-align:center;">Response</th>
                                </tr>
                            </thead>
                            <tbody>${procRows}</tbody>
                        </table>
                    </div>
                </div>

                <!-- Educational Explanation Card -->
                <div style="background:#f8fafc;border:1px solid #e2e8f0;border-left:4px solid var(--primary);border-radius:6px;padding:12px;margin-bottom:16px;font-size:12px;line-height:1.6;color:#334155;">
                    <strong style="color:#0f172a;display:block;margin-bottom:4px;"><i class="fas fa-calculator"></i> Metric Derivation &amp; Operating Systems Principles:</strong>
                    <div>• <strong>Average Waiting Time:</strong> ${escapeHtml(expl.avg_waiting_time_analysis || '')}</div>
                    <div>• <strong>Average Turnaround Time:</strong> ${escapeHtml(expl.avg_turnaround_time_analysis || '')}</div>
                    <div>• <strong>Turnaround / Waiting Relationship:</strong> ${escapeHtml(expl.tat_wt_formula || '')}</div>
                    <div>• <strong>Context Switches:</strong> ${escapeHtml(expl.context_switches_analysis || '')}</div>
                </div>

                <!-- Modal Actions -->
                <div style="display:flex;justify-content:flex-end;gap:10px;border-top:1px solid #e2e8f0;padding-top:14px;">
                    <button type="button" class="btn btn-secondary" onclick="SimulationHistoryController.closeModal()">Close</button>
                    <button type="button" class="btn btn-primary" onclick="SimulationHistoryController.rerunWorkload('${run.run_id}'); SimulationHistoryController.closeModal();">
                        <i class="fas fa-redo"></i> Load Workload into CPU Scheduler
                    </button>
                </div>
            `;

            modal.style.display = 'flex';
            setTimeout(() => {
                this.renderGanttSegments(gantt, 'sim-modal-gantt');
            }, 50);

        } catch (e) {
            console.error('Error fetching run details:', e);
            alert(`Network error: ${e.message}`);
        }
    },

    closeModal() {
        const modal = document.getElementById('sim-run-modal');
        if (modal) modal.style.display = 'none';
    },

    async rerunWorkload(runId) {
        try {
            const res = await fetch(`/api/simulation/history/${runId}/rerun`, { method: 'POST' });
            const data = await res.json();
            if (!data.success) {
                alert(`Rerun error: ${data.error || 'Failed to load workload'}`);
                return;
            }

            if (window.SysAnimations && window.SysAnimations.showToast) {
                window.SysAnimations.showToast(`✅ Workload from ${runId} loaded into CPU Scheduler!`, 'success');
            } else {
                alert(`Workload from ${runId} (${data.process_count} processes) loaded! Opening CPU Scheduler.`);
            }

            // Switch to scheduler panel in SysRealm navigation
            const navScheduler = document.querySelector('li[data-target="scheduler"]');
            if (navScheduler) {
                navScheduler.click();
            }

            // Trigger scheduler UI reload if window.SysRealm or ProcessManager exists
            if (window.SysRealm && window.SysRealm.loadProcesses) {
                window.SysRealm.loadProcesses();
            }

        } catch (e) {
            console.error('Error rerunning workload:', e);
            alert(`Network error: ${e.message}`);
        }
    },

    async deleteRun(runId) {
        if (!confirm(`Are you sure you want to remove simulation run '${runId}' and its process records from the database?`)) {
            return;
        }

        try {
            const res = await fetch(`/api/simulation/history/${runId}`, { method: 'DELETE' });
            const data = await res.json();
            if (!data.success) {
                alert(`Delete failed: ${data.error || 'Could not delete run'}`);
                return;
            }

            this.selectedRunIds.delete(runId);
            this.loadRuns();
            this.loadAnalytics();

            if (window.SysAnimations && window.SysAnimations.showToast) {
                window.SysAnimations.showToast(`Run ${runId} deleted.`, 'info');
            }

        } catch (e) {
            console.error('Error deleting run:', e);
            alert(`Network error: ${e.message}`);
        }
    },

    async loadAnalytics() {
        const wrap = document.getElementById('sim-subtab-analytics');
        if (!wrap) return;

        try {
            const res = await fetch('/api/simulation/analytics');
            const data = await res.json();
            if (!data.success) return;

            // 1. Update KPI overview cards
            const elTotal = document.getElementById('sim-analytics-total');
            if (elTotal) elTotal.textContent = data.total_runs || 0;
            const elTop = document.getElementById('sim-analytics-top');
            if (elTop) elTop.textContent = data.top_algorithm || 'None';
            const elBestWt = document.getElementById('sim-analytics-best-wt');
            if (elBestWt) elBestWt.textContent = data.best_observed && data.best_observed.best_waiting_time != null ? data.best_observed.best_waiting_time + ' ms' : '-';
            const elBestTat = document.getElementById('sim-analytics-best-tat');
            if (elBestTat) elBestTat.textContent = data.best_observed && data.best_observed.best_turnaround_time != null ? data.best_observed.best_turnaround_time + ' ms' : '-';
            const elPeakCpu = document.getElementById('sim-analytics-peak-cpu');
            if (elPeakCpu) elPeakCpu.textContent = data.best_observed && data.best_observed.best_cpu_utilization != null ? data.best_observed.best_cpu_utilization + '%' : '-';
            const elWorkloads = document.getElementById('sim-analytics-workloads');
            if (elWorkloads) elWorkloads.textContent = data.unique_workloads || 0;

            // 2. Algorithm Breakdown Table
            const tbodyStats = document.getElementById('sim-analytics-stats-tbody');
            if (tbodyStats) {
                tbodyStats.innerHTML = '';
                (data.algorithm_statistics || []).forEach(st => {
                    const tr = document.createElement('tr');
                    const color = this.ALGO_COLORS[st.algorithm] || '#3b82f6';
                    tr.innerHTML = `
                        <td>
                            <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${color};margin-right:6px;"></span>
                            <strong style="color:#0f172a;">${st.algorithm}</strong>
                        </td>
                        <td style="text-align:center;"><span class="badge" style="background:#f1f5f9;color:#334155;font-weight:700;">${st.run_count}</span></td>
                        <td style="font-weight:600;color:#0ea5e9;">${st.avg_waiting_time != null ? Number(st.avg_waiting_time).toFixed(2) + ' ms' : '-'}</td>
                        <td style="font-weight:600;color:#8b5cf6;">${st.avg_turnaround_time != null ? Number(st.avg_turnaround_time).toFixed(2) + ' ms' : '-'}</td>
                        <td>${st.avg_response_time != null ? Number(st.avg_response_time).toFixed(2) + ' ms' : '-'}</td>
                        <td><strong>${st.avg_cpu_utilization != null ? Number(st.avg_cpu_utilization).toFixed(1) + '%' : '-'}</strong></td>
                        <td style="font-family:monospace;">${st.avg_throughput != null ? Number(st.avg_throughput).toFixed(4) : '-'}</td>
                        <td style="text-align:center;">${st.avg_context_switches != null ? Number(st.avg_context_switches).toFixed(1) : '-'}</td>
                    `;
                    tbodyStats.appendChild(tr);
                });
            }

            // 3. Relational DBMS Query Inspector
            const queryWrap = document.getElementById('sim-analytics-queries-wrap');
            if (queryWrap && data.sql_demonstration) {
                queryWrap.innerHTML = '';
                data.sql_demonstration.forEach(q => {
                    const card = document.createElement('div');
                    card.style.background = '#f8fafc';
                    card.style.border = '1px solid #e2e8f0';
                    card.style.borderRadius = '8px';
                    card.style.padding = '12px 16px';
                    card.style.marginBottom = '10px';
                    card.innerHTML = `
                        <div style="font-size:12px;font-weight:700;color:#0f172a;margin-bottom:4px;">
                            <i class="fas fa-database" style="color:var(--primary);margin-right:6px;"></i>${escapeHtml(q.concept)}
                        </div>
                        <pre style="background:#0f172a;color:#38bdf8;padding:8px 12px;border-radius:6px;font-size:11px;overflow-x:auto;margin:6px 0;"><code>${escapeHtml(q.sql)}</code></pre>
                        <div style="font-size:11px;color:var(--text-muted);">${escapeHtml(q.explanation)}</div>
                    `;
                    queryWrap.appendChild(card);
                });
            }

        } catch (e) {
            console.error('Error loading simulation analytics:', e);
        }
    }
};

// Utilities
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function formatDate(dateStr) {
    if (!dateStr) return '-';
    try {
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return String(dateStr);
        return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
        return String(dateStr);
    }
}

// Expose globally
window.SimulationHistoryController = SimulationHistoryController;
