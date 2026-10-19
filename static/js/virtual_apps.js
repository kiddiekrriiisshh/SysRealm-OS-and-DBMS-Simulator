// SysRealm Virtual Apps Lab
// Turns app interactions into normal process records, so the existing CPU scheduler
// remains the single source of truth for the simulation.
(function () {
  'use strict';

  const VIRTUAL_PREFIX = 'Virtual App · ';
  const STORAGE_KEY = 'sysrealm_virtual_app_catalog_v1';
  const ALLOWED_ACCENTS = new Set(['#0f766e', '#6d28d9', '#be123c', '#b45309', '#1d4ed8']);

  const BUILTIN_APPS = [
    {
      id: 'browser', name: 'Lab Browser', icon: '🌐', accent: '#0f766e', type: 'browser',
      description: 'Browse the local systems guide and search its pages.',
      startupTasks: [
        { name: 'Browser Core UI', burst: 4, priority: 2, memory: 256 },
        { name: 'Tab Renderer Engine', burst: 5, priority: 3, memory: 512 }
      ],
      actions: {
        navigate: [
          { name: 'Resolve address', burst: 2, priority: 3 },
          { name: 'Fetch local page', burst: 4, priority: 3 },
          { name: 'Render page', burst: 3, priority: 3 }
        ],
        search: [
          { name: 'Parse search query', burst: 1, priority: 2 },
          { name: 'Search page index', burst: 4, priority: 2 },
          { name: 'Render search results', burst: 2, priority: 2 }
        ]
      }
    },
    {
      id: 'music', name: 'Tone Player', icon: '🎧', accent: '#6d28d9', type: 'music',
      description: 'Load a local track and model its audio-buffer work.',
      startupTasks: [
        { name: 'Player UI Controller', burst: 3, priority: 2, memory: 192 },
        { name: 'Audio DSP Engine', burst: 4, priority: 1, memory: 256 }
      ],
      actions: {
        play: [
          { name: 'Read track metadata', burst: 2, priority: 3 },
          { name: 'Decode audio', burst: 4, priority: 3 },
          { name: 'Fill playback buffer', burst: 2, priority: 3 }
        ],
        switch: [
          { name: 'Load selected track', burst: 2, priority: 3 },
          { name: 'Decode audio', burst: 3, priority: 3 },
          { name: 'Refresh playback buffer', burst: 2, priority: 3 }
        ]
      }
    },
    {
      id: 'game', name: 'Signal Sprint', icon: '🎮', accent: '#407a55', type: 'game',
      description: 'Start a reaction round and process each correct input.',
      startupTasks: [
        { name: 'Game Engine Loop', burst: 5, priority: 2, memory: 384 },
        { name: 'Graphics Compositor', burst: 3, priority: 2, memory: 256 }
      ],
      actions: {
        start: [
          { name: 'Load game level', burst: 3, priority: 2 },
          { name: 'Initialize game state', burst: 2, priority: 2 },
          { name: 'Render first frame', burst: 2, priority: 2 }
        ],
        input: [
          { name: 'Read player input', burst: 1, priority: 1 },
          { name: 'Update game state', burst: 2, priority: 1 },
          { name: 'Render next frame', burst: 2, priority: 1 }
        ]
      }
    },
    {
      id: 'downloads', name: 'Download Desk', icon: '⇩', accent: '#b27b21', type: 'downloads',
      description: 'Queue a local sample transfer for the virtual CPU.',
      startupTasks: [
        { name: 'Download Manager Daemon', burst: 4, priority: 3, memory: 192 },
        { name: 'Network Socket Buffer', burst: 3, priority: 4, memory: 128 }
      ],
      actions: {
        download: [
          { name: 'Connect to source', burst: 2, priority: 4 },
          { name: 'Transfer file blocks', burst: 5, priority: 4 },
          { name: 'Verify file', burst: 2, priority: 4 },
          { name: 'Save virtual file', burst: 1, priority: 4 }
        ]
      }
    }
  ];

  const BROWSER_PAGES = [
    { path: 'lab://start', label: 'THE SYSTEMS LAB', title: 'A process is a program in motion.', body: 'Every navigation asks the scheduler for a few modeled CPU slices.' },
    { path: 'lab://processes', label: 'FIELD GUIDE / 02', title: 'A process has a story.', body: 'Arrival, burst, and priority tell the scheduler how a workload should be handled.' },
    { path: 'lab://queues', label: 'FIELD GUIDE / 03', title: 'Waiting is part of the work.', body: 'The ready queue holds work until a scheduling policy chooses it.' }
  ];
  const TRACKS = ['Low Orbit', 'Green Room', 'Night Transit'];
  const FILES = ['scheduler-notes.txt · 18 KB', 'kernel-map.svg · 640 KB', 'tone-table.csv · 12 KB'];
  const PROCESS_COLORS = ['#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c', '#e67e22', '#e91e63', '#00bcd4', '#8bc34a'];
  const POLICY_TEXT = {
    FCFS: 'FCFS condition: among ready processes, the one with the earliest arrival time is dispatched next.',
    SJF: 'SJF condition: among ready processes, the one with the shortest remaining burst is dispatched next.',
    Priority: 'Priority condition: among ready processes, the lowest priority number (highest urgency) is dispatched next. Game input is typically 1; downloads are typically 4.',
    RoundRobin: 'Round Robin condition: ready processes share the CPU in queue order, each for one time quantum, then the remainder goes to the back of the ready queue.'
  };

  function byId(id) { return document.getElementById(id); }
  function clampInt(value, fallback, min, max) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.min(max, Math.max(min, parsed));
  }
  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }
  function toast(message, kind) {
    if (window.SysAnimations && typeof window.SysAnimations.showToast === 'function') {
      window.SysAnimations.showToast(message, kind || 'info');
    }
  }

  const VirtualApps = {
    customApps: [],
    opened: new Set(),
    launchedApps: new Set(),
    downloads: [],
    appState: {
      browserUrl: 'lab://start',
      browserQuery: '',
      selectedTrack: 0,
      playing: false,
      gameActive: false,
      gameTarget: 4,
      gameScore: 0,
      selectedFile: 0
    },
    creating: false,
    queuedProcesses: [],
    liveStates: {},
    sim: {
      running: false,
      paused: false,
      events: [],
      index: 0,
      timer: null,
      gantt: [],
      colors: {},
      cpuPid: null,
      ready: [],
      clock: 0
    },

    init() {
      if (!byId('va-app-grid')) return;
      this.restoreCustomApps();
      this.bindStaticControls();
      this.addTaskRow({ name: 'Start application', burst: 2, priority: 2, memory: 128 });
      this.renderApps();
      this.refreshQueue();
      this.updatePolicy();
      this.drawGantt([]);
      window.addEventListener('resize', () => this.drawGantt(this.progressiveGantt(this.sim.clock)));
      document.querySelectorAll('#sidebar-nav li[data-target="virtual-apps"]').forEach((item) => {
        item.addEventListener('click', () => window.setTimeout(() => {
          this.refreshQueue();
          this.drawGantt(this.sim.gantt);
        }, 80));
      });
    },

    bindStaticControls() {
      byId('va-launch-all')?.addEventListener('click', () => this.launchAllApps());
      byId('va-start-clean')?.addEventListener('click', () => this.startCleanLab());
      byId('va-open-scheduler')?.addEventListener('click', () => this.openScheduler());
      byId('va-run-schedule')?.addEventListener('click', () => this.startSimulation());
      byId('va-sim-run')?.addEventListener('click', () => this.startSimulation());
      byId('va-sim-pause')?.addEventListener('click', () => this.togglePause());
      byId('va-sim-step')?.addEventListener('click', () => this.stepSimulation());
      byId('va-sim-reset')?.addEventListener('click', () => this.resetSimulation(true));
      byId('va-algorithm')?.addEventListener('change', () => this.updatePolicy());
      byId('va-refresh-queue')?.addEventListener('click', () => this.refreshQueue());
      byId('va-add-task')?.addEventListener('click', () => this.addTaskRow());
      byId('va-custom-form')?.addEventListener('submit', (event) => {
        event.preventDefault();
        this.addCustomApp();
      });
      byId('va-task-rows')?.addEventListener('click', (event) => {
        const button = event.target.closest('[data-va-remove-step]');
        if (!button) return;
        const rows = byId('va-task-rows');
        if (rows.children.length <= 1) {
          toast('A custom app needs at least one process step.', 'warning');
          return;
        }
        button.closest('.va-task-row')?.remove();
      });
      byId('va-tab-sim')?.addEventListener('click', () => this.switchMode('simulation'));
      byId('va-tab-real')?.addEventListener('click', () => this.switchMode('real-monitor'));
      byId('va-btn-pair-agent')?.addEventListener('click', () => this.pairAgent());
      byId('va-btn-stop-agent')?.addEventListener('click', () => this.stopMonitoring());
      byId('va-btn-refresh-real')?.addEventListener('click', () => this.refreshRealData());
      byId('va-btn-copy-cmd')?.addEventListener('click', () => {
        const cmd = byId('va-pair-cmd-text')?.textContent || '';
        if (cmd && navigator.clipboard) {
          navigator.clipboard.writeText(cmd).then(() => toast('Command copied to clipboard!', 'success'));
        }
      });
      byId('va-proc-search')?.addEventListener('input', (e) => {
        this.realState.search = e.target.value.trim();
        this.refreshRealData();
      });
      byId('va-proc-sort')?.addEventListener('change', (e) => {
        this.realState.sort = e.target.value;
        this.refreshRealData();
      });
      byId('va-proc-filter-app')?.addEventListener('change', (e) => {
        this.realState.filterApp = e.target.value;
        this.refreshRealData();
      });
      byId('va-detected-apps-grid')?.addEventListener('click', (e) => {
        const card = e.target.closest('[data-app-name]');
        if (card) {
          const appName = card.dataset.appName;
          this.realState.filterApp = this.realState.filterApp === appName ? '' : appName;
          const select = byId('va-proc-filter-app');
          if (select) select.value = this.realState.filterApp;
          this.refreshRealData();
        }
      });
      byId('va-app-grid')?.addEventListener('click', (event) => this.handleAppClick(event));
      byId('va-app-grid')?.addEventListener('submit', (event) => this.handleAppSubmit(event));
      byId('va-app-grid')?.addEventListener('input', (event) => this.handleAppInput(event));
      byId('va-app-grid')?.addEventListener('change', (event) => this.handleAppChange(event));
    },

    getApps() { return [...BUILTIN_APPS, ...this.customApps]; },

    restoreCustomApps() {
      try {
        const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
        this.customApps = Array.isArray(raw) ? raw.map((app) => this.cleanCustomApp(app)).filter(Boolean) : [];
      } catch (_) {
        this.customApps = [];
      }
    },

    persistCustomApps() {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.customApps));
    },

    cleanCustomApp(app) {
      if (!app || typeof app.name !== 'string' || typeof app.actionLabel !== 'string' || !Array.isArray(app.tasks)) return null;
      const tasks = app.tasks.map((task) => ({
        name: String(task.name || '').trim().slice(0, 50),
        burst: clampInt(task.burst, 1, 1, 60),
        priority: clampInt(task.priority, 2, 1, 10),
        memory: clampInt(task.memory, 128, 64, 4096)
      })).filter((task) => task.name);
      if (!tasks.length) return null;
      return {
        id: String(app.id || `custom-${Date.now()}`).replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 60),
        name: app.name.trim().slice(0, 40), icon: String(app.icon || '⚙️').trim().slice(0, 4) || '⚙️',
        accent: ALLOWED_ACCENTS.has(app.accent) ? app.accent : '#0f766e',
        type: 'custom', description: 'A user-defined app workload.', actionLabel: app.actionLabel.trim().slice(0, 32),
        tasks,
        startupTasks: tasks
      };
    },

    addTaskRow(task) {
      const rows = byId('va-task-rows');
      if (!rows) return;
      const source = task || { name: '', burst: 2, priority: 2, memory: 128 };
      const row = document.createElement('div');
      row.className = 'va-task-row';
      row.innerHTML = `
        <label>Task name<input class="va-task-name" maxlength="50" required value="${escapeHtml(source.name)}" placeholder="e.g. Render canvas"></label>
        <label>Burst (ticks)<input class="va-task-burst" type="number" min="1" max="60" required value="${clampInt(source.burst, 2, 1, 60)}"></label>
        <label>Priority<input class="va-task-priority" type="number" min="1" max="10" required value="${clampInt(source.priority, 2, 1, 10)}"></label>
        <label>Memory (MB)<input class="va-task-memory" type="number" min="64" max="4096" required value="${clampInt(source.memory, 128, 64, 4096)}"></label>
        <button type="button" data-va-remove-step aria-label="Remove process step"><i class="fas fa-times"></i></button>`;
      rows.appendChild(row);
    },

    addCustomApp() {
      const tasks = [...byId('va-task-rows').querySelectorAll('.va-task-row')].map((row) => ({
        name: row.querySelector('.va-task-name').value.trim(),
        burst: clampInt(row.querySelector('.va-task-burst').value, 2, 1, 60),
        priority: clampInt(row.querySelector('.va-task-priority').value, 2, 1, 10),
        memory: clampInt(row.querySelector('.va-task-memory').value, 128, 64, 4096)
      })).filter((task) => task.name);
      const app = this.cleanCustomApp({
        id: `custom-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        name: byId('va-custom-name').value,
        icon: byId('va-custom-icon').value,
        accent: byId('va-custom-accent').value,
        actionLabel: byId('va-custom-action').value,
        tasks
      });
      if (!app || !app.name || !app.actionLabel || !app.tasks.length) {
        toast('Give the app a name, action, and at least one complete process step.', 'error');
        return;
      }
      this.customApps.push(app);
      this.persistCustomApps();
      byId('va-custom-form').reset();
      byId('va-custom-icon').value = '⚙️';
      byId('va-custom-action').value = 'Run workload';
      byId('va-task-rows').innerHTML = '';
      this.addTaskRow({ name: 'Start application', burst: 2, priority: 2, memory: 128 });
      this.opened.add(app.id);
      this.renderApps();
      toast(`${app.name} is ready to launch.`, 'success');
    },

    renderApps() {
      const grid = byId('va-app-grid');
      if (!grid) return;
      grid.innerHTML = this.getApps().map((app) => this.appCard(app)).join('');
    },

    appCard(app) {
      const open = this.opened.has(app.id);
      const isLaunched = this.launchedApps.has(app.id);
      const runningName = this.runningAppName();
      const isRunning = runningName === app.name;
      const appProcs = this.queuedProcesses.filter((p) => {
        const name = String(p.name || '');
        return name.startsWith(VIRTUAL_PREFIX) && name.slice(VIRTUAL_PREFIX.length).split(' · ')[0] === app.name;
      });
      const activeProcsCount = appProcs.filter((p) => (this.liveStates[p.pid]?.state || p.state) !== 'TERMINATED').length;
      const style = `--va-accent:${escapeHtml(app.accent)};`;

      let statusBadge = 'APP CLOSED';
      let badgeClass = '';
      if (isRunning) {
        statusBadge = 'ON CPU';
        badgeClass = 'is-on-cpu';
      } else if (isLaunched && activeProcsCount > 0) {
        statusBadge = `ACTIVE · ${activeProcsCount} PROC${activeProcsCount === 1 ? '' : 'S'}`;
        badgeClass = 'is-open';
      } else if (isLaunched) {
        statusBadge = 'COMPLETED';
        badgeClass = 'is-completed';
      } else if (open) {
        statusBadge = 'APP OPEN';
        badgeClass = 'is-open';
      }

      return `<article class="va-app-card${isRunning ? ' is-running' : isLaunched ? ' is-launched' : ''}" data-app-id="${escapeHtml(app.id)}" data-open="${open}" style="${style}">
        <div class="va-card-top">
          <div class="va-card-icon">${escapeHtml(app.icon)}</div>
          <div class="va-card-copy">
            <h3>${escapeHtml(app.name)}</h3>
            <p>${escapeHtml(app.description)}</p>
            <span class="va-live ${badgeClass}">${escapeHtml(statusBadge)}</span>
          </div>
          <div class="va-card-actions">
            ${!isLaunched ? `
              <button type="button" class="va-launch-btn" data-va-launch="${escapeHtml(app.id)}" title="Launch app and initiate its processes">
                <i class="fas fa-play"></i> Launch
              </button>
              <button type="button" class="va-schedule-btn" data-va-schedule-app="${escapeHtml(app.id)}" title="Launch app and immediately simulate CPU scheduling">
                <i class="fas fa-microchip"></i> Schedule
              </button>
            ` : `
              <button type="button" class="va-schedule-btn" data-va-schedule-app="${escapeHtml(app.id)}" title="Simulate CPU scheduling on this app's processes">
                <i class="fas fa-microchip"></i> Run CPU
              </button>
              <button type="button" class="va-relaunch-btn" data-va-relaunch="${escapeHtml(app.id)}" title="Queue additional workload processes">
                <i class="fas fa-plus"></i> Workload
              </button>
              <button type="button" class="va-close-btn" data-va-close="${escapeHtml(app.id)}" title="Terminate app and remove processes">
                <i class="fas fa-stop"></i>
              </button>
            `}
            <button type="button" class="va-toggle-btn" data-va-toggle="${escapeHtml(app.id)}" title="${open ? 'Collapse' : 'Expand'} controls">
              <i class="fas fa-chevron-${open ? 'up' : 'down'}"></i>
            </button>
          </div>
        </div>
        ${open ? `<div class="va-card-body">${this.appBody(app)}<div class="va-app-foot">WORKLOADS ARE SHARED WITH THE CPU SCHEDULER</div></div>` : ''}
      </article>`;
    },

    appBody(app) {
      if (app.type === 'browser') return this.browserBody();
      if (app.type === 'music') return this.musicBody();
      if (app.type === 'game') return this.gameBody();
      if (app.type === 'downloads') return this.downloadBody();
      return this.customBody(app);
    },

    browserBody() {
      const page = BROWSER_PAGES.find((entry) => entry.path === this.appState.browserUrl) || BROWSER_PAGES[0];
      return `<form class="va-browser-bar" data-va-browser-form><input aria-label="Lab browser address" data-va-browser-url value="${escapeHtml(this.appState.browserUrl)}"><button class="va-mini-btn" type="submit"><i class="fas fa-arrow-right"></i> Go</button></form>
        <form class="va-browser-search" data-va-search-form><input aria-label="Search the guide" data-va-browser-search value="${escapeHtml(this.appState.browserQuery)}" placeholder="Search the local guide"><button class="va-mini-btn" type="submit"><i class="fas fa-search"></i></button></form>
        <div class="va-browser-page"><span>${page.label}</span><strong>${page.title}</strong><p>${page.body}</p></div>`;
    },

    musicBody() {
      const index = this.appState.selectedTrack;
      return `<div class="va-player-row"><div class="va-player-art"><i class="fas fa-music"></i></div><div class="va-player-track"><strong>${escapeHtml(TRACKS[index])}</strong><small>${this.appState.playing ? 'PLAYING · VIRTUAL BUFFER ACTIVE' : 'PAUSED · READY TO LOAD'}</small></div><button type="button" class="va-mini-btn" data-va-music-play><i class="fas fa-${this.appState.playing ? 'pause' : 'play'}"></i>${this.appState.playing ? 'Pause' : 'Play'}</button></div>
        <div class="va-track-list">${TRACKS.map((track, idx) => `<button type="button" data-va-track="${idx}" class="${idx === index ? 'is-current' : ''}">${escapeHtml(track)}</button>`).join('')}</div>`;
    },

    gameBody() {
      const active = this.appState.gameActive;
      return `<div class="va-game-head"><span>${active ? 'TARGET ACTIVE · CLICK THE LIT TILE' : '20-SECOND REACTION ROUND'}</span><span class="va-game-score">SCORE ${String(this.appState.gameScore).padStart(2, '0')}</span></div>
        <div class="va-game-grid">${Array.from({ length: 12 }, (_, index) => `<button type="button" data-va-game-cell="${index}" class="${active && index === this.appState.gameTarget ? 'is-target' : ''}" aria-label="Game cell ${index + 1}"></button>`).join('')}</div>
        <div class="va-game-actions"><small>${active ? 'Each correct input creates a high-priority workload.' : 'Starting creates level-load, state, and render processes.'}</small><button type="button" class="va-game-start" data-va-game-start><i class="fas fa-play"></i>${active ? 'Restart' : 'Start round'}</button></div>`;
    },

    downloadBody() {
      const latest = this.downloads[0];
      return `<div class="va-download-row"><i class="fas fa-file-arrow-down"></i><select data-va-download-file aria-label="Select sample file">${FILES.map((file, index) => `<option value="${index}" ${index === this.appState.selectedFile ? 'selected' : ''}>${escapeHtml(file)}</option>`).join('')}</select><button type="button" class="va-download-button" data-va-download><i class="fas fa-download"></i> Queue</button></div>
        <div class="va-download-list">${latest ? `<div class="va-download-item"><span>${escapeHtml(latest)}</span><em>CPU WORK QUEUED</em></div>` : 'Queued virtual downloads appear here.'}</div>`;
    },

    customBody(app) {
      return `<div class="va-custom-run"><div><strong>${escapeHtml(app.actionLabel)}</strong>${app.tasks.length} process ${app.tasks.length === 1 ? 'step' : 'steps'} · ${app.tasks.reduce((sum, task) => sum + task.burst, 0)} total CPU ticks</div><button type="button" class="va-custom-action" data-va-custom-run="${escapeHtml(app.id)}"><i class="fas fa-bolt"></i>${escapeHtml(app.actionLabel)}</button></div><button type="button" class="va-remove-app" data-va-remove-app="${escapeHtml(app.id)}">Remove this custom app</button>`;
    },

    handleAppInput(event) {
      if (event.target.matches('[data-va-browser-url]')) this.appState.browserUrl = event.target.value;
      if (event.target.matches('[data-va-browser-search]')) this.appState.browserQuery = event.target.value;
    },

    handleAppChange(event) {
      if (event.target.matches('[data-va-download-file]')) this.appState.selectedFile = clampInt(event.target.value, 0, 0, FILES.length - 1);
    },

    handleAppSubmit(event) {
      if (event.target.matches('[data-va-browser-form]')) {
        event.preventDefault();
        const supplied = this.appState.browserUrl.trim().toLowerCase();
        const page = BROWSER_PAGES.find((entry) => entry.path === supplied) || BROWSER_PAGES[0];
        this.appState.browserUrl = page.path;
        this.queueAction(this.findApp('browser'), 'navigate');
        this.renderApps();
      } else if (event.target.matches('[data-va-search-form]')) {
        event.preventDefault();
        const query = this.appState.browserQuery.trim().toLowerCase();
        const page = BROWSER_PAGES.find((entry) => entry.title.toLowerCase().includes(query) || entry.path.includes(query)) || BROWSER_PAGES[1];
        this.appState.browserUrl = page.path;
        this.queueAction(this.findApp('browser'), 'search');
        this.renderApps();
      }
    },

    handleAppClick(event) {
      const launch = event.target.closest('[data-va-launch]');
      if (launch) {
        this.launchApp(launch.dataset.vaLaunch);
        return;
      }
      const scheduleBtn = event.target.closest('[data-va-schedule-app]');
      if (scheduleBtn) {
        this.scheduleApp(scheduleBtn.dataset.vaScheduleApp);
        return;
      }
      const relaunch = event.target.closest('[data-va-relaunch]');
      if (relaunch) {
        this.relaunchApp(relaunch.dataset.vaRelaunch);
        return;
      }
      const close = event.target.closest('[data-va-close]');
      if (close) {
        this.closeApp(close.dataset.vaClose);
        return;
      }
      const toggle = event.target.closest('[data-va-toggle]');
      if (toggle) {
        const appId = toggle.dataset.vaToggle;
        this.opened.has(appId) ? this.opened.delete(appId) : this.opened.add(appId);
        this.renderApps();
        return;
      }
      const track = event.target.closest('[data-va-track]');
      if (track) {
        const next = clampInt(track.dataset.vaTrack, 0, 0, TRACKS.length - 1);
        if (next !== this.appState.selectedTrack) {
          this.appState.selectedTrack = next;
          this.appState.playing = false;
          this.queueAction(this.findApp('music'), 'switch');
        }
        this.renderApps();
        return;
      }
      if (event.target.closest('[data-va-music-play]')) {
        const wasPlaying = this.appState.playing;
        this.appState.playing = !wasPlaying;
        if (!wasPlaying) this.queueAction(this.findApp('music'), 'play');
        this.renderApps();
        return;
      }
      if (event.target.closest('[data-va-game-start]')) {
        this.appState.gameActive = true;
        this.appState.gameScore = 0;
        this.appState.gameTarget = Math.floor(Math.random() * 12);
        this.queueAction(this.findApp('game'), 'start');
        this.renderApps();
        return;
      }
      const cell = event.target.closest('[data-va-game-cell]');
      if (cell && this.appState.gameActive && Number(cell.dataset.vaGameCell) === this.appState.gameTarget) {
        this.appState.gameScore += 1;
        this.appState.gameTarget = (this.appState.gameTarget * 7 + 5) % 12;
        this.queueAction(this.findApp('game'), 'input');
        this.renderApps();
        return;
      }
      if (event.target.closest('[data-va-download]')) {
        const label = FILES[this.appState.selectedFile];
        this.downloads.unshift(label);
        this.queueAction(this.findApp('downloads'), 'download');
        this.renderApps();
        return;
      }
      const customRun = event.target.closest('[data-va-custom-run]');
      if (customRun) {
        const app = this.findApp(customRun.dataset.vaCustomRun);
        if (app) this.queueTasks(app, app.tasks, app.actionLabel);
        return;
      }
      const remove = event.target.closest('[data-va-remove-app]');
      if (remove) {
        const appId = remove.dataset.vaRemoveApp;
        this.closeApp(appId).then(() => {
          this.customApps = this.customApps.filter((app) => app.id !== appId);
          this.persistCustomApps();
          this.renderApps();
          toast('Custom app removed from this browser.', 'info');
        });
      }
    },

    findApp(id) { return this.getApps().find((app) => app.id === id); },

    async launchApp(appId) {
      const app = this.findApp(appId);
      if (!app) return;
      const tasks = (app.startupTasks && app.startupTasks.length) ? app.startupTasks : (app.tasks || []);
      if (!tasks.length) {
        toast(`No startup tasks defined for ${app.name}.`, 'warning');
        return;
      }
      this.launchedApps.add(app.id);
      this.opened.add(app.id);
      this.renderApps();
      await this.queueTasks(app, tasks, 'Launch application');
    },

    async scheduleApp(appId) {
      const app = this.findApp(appId);
      if (!app) return;
      this.selectedApp = app;
      const scopeSelect = byId('va-sim-scope');
      if (scopeSelect) scopeSelect.value = 'selected';
      if (!this.launchedApps.has(app.id)) {
        await this.launchApp(app.id);
      }
      byId('va-sim-board')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      await this.startSimulation();
    },

    async relaunchApp(appId) {
      const app = this.findApp(appId);
      if (!app) return;
      const tasks = (app.startupTasks && app.startupTasks.length) ? app.startupTasks : (app.tasks || []);
      await this.queueTasks(app, tasks, 'Workload queue');
    },

    async closeApp(appId) {
      const app = this.findApp(appId);
      if (!app) return;
      const procsToRemove = this.queuedProcesses.filter((p) => {
        const name = String(p.name || '');
        return name.startsWith(VIRTUAL_PREFIX) && name.slice(VIRTUAL_PREFIX.length).split(' · ')[0] === app.name;
      });
      for (const p of procsToRemove) {
        try {
          await fetch(`/api/processes/${p.pid}`, { method: 'DELETE' });
        } catch (_) {}
      }
      this.launchedApps.delete(appId);
      this.opened.delete(appId);
      if (app.type === 'music') this.appState.playing = false;
      if (app.type === 'game') this.appState.gameActive = false;
      toast(`Closed ${app.name} and removed ${procsToRemove.length} process${procsToRemove.length === 1 ? '' : 'es'}.`, 'info');
      await this.refreshQueue();
      this.renderApps();
      if (window.SysRealm && typeof window.SysRealm.refreshProcessList === 'function') window.SysRealm.refreshProcessList();
    },

    async launchAllApps() {
      if (this.creating) {
        toast('Please wait for current operation to complete.', 'warning');
        return;
      }
      toast('Launching all 4 built-in apps and initiating processes...', 'info');
      for (const app of BUILTIN_APPS) {
        if (!this.launchedApps.has(app.id)) {
          await this.launchApp(app.id);
        }
      }
      toast('All built-in apps launched! Ready to simulate CPU scheduling.', 'success');
    },

    async queueAction(app, action) {
      if (!app || !app.actions || !app.actions[action]) return;
      this.launchedApps.add(app.id);
      await this.queueTasks(app, app.actions[action], action);
    },

    async queueTasks(app, tasks, actionLabel) {
      if (this.creating) {
        toast('Please wait for the current app action to be added.', 'warning');
        return;
      }
      this.creating = true;
      const arrivalInput = byId('va-arrival-time');
      const arrival = clampInt(arrivalInput?.value, 0, 0, 10000);
      try {
        if (window.SysRealm && !window.SysRealm.currentSession && typeof window.SysRealm.createSession === 'function') {
          await window.SysRealm.createSession();
        }
        const created = [];
        for (const task of tasks) {
          const response = await fetch('/api/processes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              name: `${VIRTUAL_PREFIX}${app.name} · ${task.name}`,
              arrival_time: arrival,
              burst_time: clampInt(task.burst, 1, 1, 60),
              priority: clampInt(task.priority, 2, 1, 10),
              memory_mb: clampInt(task.memory, 128, 64, 4096)
            })
          });
          const data = await response.json();
          if (!response.ok || !data.success) throw new Error(data.error || 'The process could not be created.');
          created.push(data.process);
        }
        if (arrivalInput) arrivalInput.value = String(arrival + 1);
        const actionName = actionLabel || 'action';
        toast(`${app.name}: ${created.length} process ${created.length === 1 ? 'was' : 'were'} queued for ${actionName}.`, 'success');
        await this.refreshQueue();
        if (window.SysRealm && typeof window.SysRealm.refreshProcessList === 'function') window.SysRealm.refreshProcessList();
      } catch (error) {
        console.error('Virtual workload creation failed:', error);
        toast(error.message || 'Could not add the virtual workload.', 'error');
      } finally {
        this.creating = false;
      }
    },

    async refreshQueue() {
      const status = byId('va-queue-status');
      try {
        const response = await fetch('/api/processes');
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || 'Could not read processes.');
        const all = data.processes || [];
        const virtual = all.filter((process) => String(process.name || '').startsWith(VIRTUAL_PREFIX));
        this.queuedProcesses = all;
        virtual.forEach((proc) => {
          const fullName = String(proc.name || '');
          const shortName = fullName.slice(VIRTUAL_PREFIX.length);
          const appName = shortName.split(' · ')[0];
          const matchedApp = this.getApps().find((a) => a.name === appName);
          if (matchedApp) {
            this.launchedApps.add(matchedApp.id);
          }
        });
        if (!this.sim.running) {
          this.liveStates = {};
          virtual.forEach((process) => {
            this.liveStates[process.pid] = {
              state: process.state || 'NEW',
              remaining: process.remaining_time != null ? process.remaining_time : process.burst_time
            };
          });
        }
        if (status) status.textContent = `${all.length} process${all.length === 1 ? '' : 'es'} currently in the shared scheduler queue (${virtual.length} from virtual apps).`;
        const count = byId('va-virtual-count');
        if (count) count.textContent = `${virtual.length} virtual process${virtual.length === 1 ? '' : 'es'}`;
        this.renderQueue(virtual);
      } catch (error) {
        if (status) status.textContent = 'Could not read the scheduler queue. Refresh the page and try again.';
        console.error('Virtual queue refresh failed:', error);
      }
    },

    renderQueue(processes) {
      const body = byId('va-process-table');
      if (!body) return;
      if (!processes.length) {
        body.innerHTML = '<tr><td colspan="7" class="va-empty-row">No virtual app activity yet. Launch an app from the panel above to initiate processes.</td></tr>';
        return;
      }
      body.innerHTML = processes.slice().reverse().slice(0, 16).map((process) => {
        const fullName = String(process.name || 'Virtual app task');
        const shortName = fullName.startsWith(VIRTUAL_PREFIX) ? fullName.slice(VIRTUAL_PREFIX.length) : fullName;
        const [appName, ...taskParts] = shortName.split(' · ');
        const live = this.liveStates[process.pid] || {};
        const state = String(live.state || process.state || 'NEW');
        const remaining = live.remaining != null ? live.remaining : (process.remaining_time != null ? process.remaining_time : process.burst_time);
        const rowClass = state === 'RUNNING' ? 'va-row-running' : state === 'TERMINATED' ? 'va-row-terminated' : '';
        return `<tr class="${rowClass}"><td><strong>${escapeHtml(process.pid || '—')}</strong></td><td class="va-process-name">${escapeHtml(appName)}<small>${escapeHtml(taskParts.join(' · ') || 'Workload')} · AT ${escapeHtml(process.arrival_time)} / BT ${escapeHtml(process.burst_time)} / PRI ${escapeHtml(process.priority)}</small></td><td>${escapeHtml(process.arrival_time)}</td><td>${escapeHtml(process.burst_time)}</td><td>${escapeHtml(process.priority)}</td><td>${escapeHtml(remaining)}</td><td><span class="badge badge-${escapeHtml(state.toLowerCase())}">${escapeHtml(state)}</span></td></tr>`;
      }).join('');
    },

    async startCleanLab() {
      if (!window.confirm('Start a clean app lab? This clears the current simulated process queue, memory allocations, and scheduler timeline.')) return;
      try {
        if (window.SysRealm && typeof window.SysRealm.fullReset === 'function') {
          const success = await window.SysRealm.fullReset();
          if (!success) throw new Error('The simulated lab could not be reset.');
        } else {
          const response = await fetch('/api/full/reset', { method: 'POST' });
          if (!response.ok) throw new Error('The simulated lab could not be reset.');
        }
        this.launchedApps.clear();
        this.opened.clear();
        this.downloads = [];
        this.appState.playing = false;
        this.appState.gameActive = false;
        this.appState.gameScore = 0;
        byId('va-arrival-time').value = '0';
        this.resetSimulation(false);
        this.renderApps();
        await this.refreshQueue();
        toast('Clean virtual app lab started. Launch an app to initiate processes, then simulate the schedule.', 'success');
      } catch (error) {
        console.error('Clean virtual lab failed:', error);
        toast(error.message || 'Could not reset the virtual lab.', 'error');
      }
    },

    openScheduler() {
      const nav = document.querySelector('#sidebar-nav li[data-target="scheduler"]');
      if (nav) nav.click();
    },

    updatePolicy() {
      const algorithm = byId('va-algorithm')?.value || 'FCFS';
      const quantumWrap = byId('va-quantum-wrap');
      if (quantumWrap) quantumWrap.hidden = algorithm !== 'RoundRobin';
      const policy = byId('va-policy');
      if (policy) policy.textContent = POLICY_TEXT[algorithm] || POLICY_TEXT.FCFS;
    },

    setSimButtons() {
      const pause = byId('va-sim-pause');
      const step = byId('va-sim-step');
      if (pause) {
        pause.disabled = !this.sim.running;
        pause.innerHTML = this.sim.paused
          ? '<i class="fas fa-play"></i> Resume'
          : '<i class="fas fa-pause"></i> Pause';
      }
      if (step) step.disabled = !this.sim.running || !this.sim.paused;
    },

    processByPid(pid) {
      return this.queuedProcesses.find((process) => process.pid === pid);
    },

    displayName(process) {
      const name = String(process?.name || pidFallback(process));
      return name.startsWith(VIRTUAL_PREFIX) ? name.slice(VIRTUAL_PREFIX.length) : name;
    },

    runningAppName() {
      if (!this.sim.cpuPid) return '';
      const process = this.processByPid(this.sim.cpuPid);
      const shortName = this.displayName(process);
      return shortName.split(' · ')[0] || '';
    },

    conditionReason(event, algorithm) {
      const process = this.processByPid(event.process_id);
      if (!process) return event.explanation || '';
      const name = this.displayName(process);
      if (event.event === 'PROCESS_STARTED' || event.event === 'PROCESS_DISPATCHED') {
        if (algorithm === 'SJF') return `t=${event.time}: SJF dispatches ${name} because burst ${process.burst_time} is the shortest among ready work.`;
        if (algorithm === 'Priority') return `t=${event.time}: Priority dispatches ${name} because priority ${process.priority} is the most urgent among ready work.`;
        if (algorithm === 'RoundRobin') return `t=${event.time}: Round Robin gives ${name} the CPU for one quantum (${byId('va-quantum')?.value || 2} ticks). Remaining burst: ${this.liveStates[process.pid]?.remaining ?? process.burst_time}.`;
        return `t=${event.time}: FCFS dispatches ${name} because it arrived first (arrival ${process.arrival_time}).`;
      }
      return event.explanation || `${event.event} at t=${event.time}`;
    },

    async startSimulation() {
      if (this.sim.running && this.sim.paused) {
        this.sim.paused = false;
        this.setSimButtons();
        this.scheduleNext();
        return;
      }
      if (this.sim.running) return;
      await this.refreshQueue();
      if (!this.queuedProcesses.length) {
        toast('Launch an app from the panel above to initiate processes, then simulate.', 'warning');
        return;
      }
      const algorithm = byId('va-algorithm')?.value || 'FCFS';
      const quantum = clampInt(byId('va-quantum')?.value, 2, 1, 20);
      const scope = byId('va-sim-scope')?.value || 'selected';

      let targetProcesses = [];
      if (scope === 'selected') {
        const app = this.selectedApp || this.getApps()[0];
        this.selectedApp = app;
        const prefix = `${VIRTUAL_PREFIX}${app.name}`;
        targetProcesses = this.queuedProcesses.filter((p) => String(p.name || '').startsWith(prefix));
        if (!targetProcesses.length) {
          toast(`Initiating startup tasks for ${app.name}...`, 'info');
          await this.launchApp(app.id);
          await this.refreshQueue();
          targetProcesses = this.queuedProcesses.filter((p) => String(p.name || '').startsWith(prefix));
        }
      } else if (scope === 'all-virtual') {
        targetProcesses = this.queuedProcesses.filter((p) => String(p.name || '').startsWith(VIRTUAL_PREFIX));
      } else {
        targetProcesses = this.queuedProcesses;
      }

      if (!targetProcesses.length) {
        toast('No processes match the selected scheduling scope. Launch an app first.', 'warning');
        return;
      }

      const processIds = targetProcesses.map((p) => p.pid);
      byId('va-sim-run')?.closest('.va-sim-board')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      try {
        const response = await fetch('/api/scheduler/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ algorithm, quantum, process_ids: processIds })
        });
        const data = await response.json();
        if (!response.ok || !data.success || !data.events?.length) {
          throw new Error(data.error || 'No processes are queued for scheduling.');
        }
        this.resetSimulation(false);
        this.sim.running = true;
        this.sim.paused = false;
        this.sim.events = data.events;
        this.sim.gantt = data.gantt_chart || [];
        this.sim.colors = {};
        const scheduledList = data.processes || targetProcesses;
        scheduledList.forEach((process, index) => {
          this.sim.colors[process.pid] = PROCESS_COLORS[index % PROCESS_COLORS.length];
          this.liveStates[process.pid] = {
            state: Number(process.arrival_time) === 0 ? 'READY' : 'NEW',
            remaining: process.burst_time
          };
        });
        this.scheduledProcesses = scheduledList;
        this.setMetrics(null);
        this.updatePolicy();
        this.setSimButtons();
        this.drawGantt([]);
        const scopeLabel = scope === 'selected' ? ` (${this.selectedApp?.name || 'Selected App'})` : '';
        this.setExplain(`Starting ${algorithm} on ${scheduledList.length} process${scheduledList.length === 1 ? '' : 'es'}${scopeLabel} using arrival, burst, and priority.`);
        toast(`${algorithm} simulation started on ${scheduledList.length} process${scheduledList.length === 1 ? '' : 'es'}.`, 'success');
        this.renderQueue(this.virtualProcesses());
        this.scheduleNext();
        if (window.SchedulerController && typeof window.SchedulerController.setProcesses === 'function') {
          window.SchedulerController.setProcesses(scheduledList);
        }
      } catch (error) {
        console.error('Virtual app scheduling failed:', error);
        toast(error.message || 'Could not simulate the schedule.', 'error');
        this.sim.running = false;
        this.setSimButtons();
      }
    },

    togglePause() {
      if (!this.sim.running) return;
      this.sim.paused = !this.sim.paused;
      if (this.sim.timer) {
        window.clearTimeout(this.sim.timer);
        this.sim.timer = null;
      }
      this.setSimButtons();
      if (!this.sim.paused) this.scheduleNext();
    },

    stepSimulation() {
      if (!this.sim.running) return;
      this.sim.paused = true;
      if (this.sim.timer) {
        window.clearTimeout(this.sim.timer);
        this.sim.timer = null;
      }
      this.setSimButtons();
      this.advanceEvent();
    },

    resetSimulation(refresh) {
      if (this.sim.timer) window.clearTimeout(this.sim.timer);
      this.liveStates = {};
      this.sim = {
        running: false,
        paused: false,
        events: [],
        index: 0,
        timer: null,
        gantt: [],
        colors: {},
        cpuPid: null,
        ready: [],
        clock: 0
      };
      this.setSimButtons();
      this.setCpu(null);
      this.setReady([]);
      this.setClock(0);
      this.setMetrics(null);
      this.drawGantt([]);
      this.setExplain('Interact with an app to queue work, then run a schedule. The dispatcher explains each choice from the current process conditions.');
      if (refresh) {
        this.liveStates = {};
        this.refreshQueue();
        this.renderApps();
      }
    },

    scheduleNext() {
      if (!this.sim.running || this.sim.paused) return;
      const delay = clampInt(byId('va-sim-speed')?.value, 650, 120, 3000);
      this.sim.timer = window.setTimeout(() => this.advanceEvent(), delay);
    },

    advanceEvent() {
      const event = this.sim.events[this.sim.index];
      if (!event) {
        this.finishSimulation();
        return;
      }
      this.sim.index += 1;
      this.applyEvent(event);
      if (this.sim.index >= this.sim.events.length) {
        this.finishSimulation();
        return;
      }
      if (!this.sim.paused) this.scheduleNext();
    },

    applyEvent(event) {
      const algorithm = byId('va-algorithm')?.value || 'FCFS';
      this.setClock(event.time || 0);
      this.sim.ready = event.queue || [];
      this.setReady(this.sim.ready);
      const pid = event.process_id;
      if (pid && !this.liveStates[pid]) {
        const process = this.processByPid(pid);
        this.liveStates[pid] = { state: 'NEW', remaining: process?.burst_time ?? 0 };
      }
      if (event.event === 'PROCESS_ARRIVED' && pid) this.liveStates[pid].state = 'READY';
      if (event.event === 'PROCESS_STARTED' || event.event === 'PROCESS_DISPATCHED') {
        this.sim.cpuPid = pid;
        if (pid) {
          this.liveStates[pid].state = 'RUNNING';
          if (event.remaining != null) this.liveStates[pid].remaining = event.remaining;
        }
        this.setCpu(pid);
      }
      if (event.event === 'QUANTUM_EXPIRED' && pid) {
        this.liveStates[pid].state = 'READY';
        if (event.remaining != null) this.liveStates[pid].remaining = event.remaining;
        this.sim.cpuPid = null;
        this.setCpu(null);
      }
      if (event.event === 'PROCESS_COMPLETED' && pid) {
        this.liveStates[pid].state = 'TERMINATED';
        this.liveStates[pid].remaining = 0;
        this.sim.cpuPid = null;
        this.setCpu(null);
      }
      if (event.event === 'CPU_IDLE') {
        this.sim.cpuPid = null;
        this.setCpu(null);
      }
      this.setExplain(this.conditionReason(event, algorithm));
      this.drawGantt(this.progressiveGantt(event.time || 0));
      this.renderQueue(this.virtualProcesses());
      this.renderApps();
      if (event.metrics) this.setMetrics(event.metrics);
    },

    finishSimulation() {
      this.sim.running = false;
      this.sim.paused = false;
      if (this.sim.timer) window.clearTimeout(this.sim.timer);
      this.sim.timer = null;
      this.setSimButtons();
      this.drawGantt(this.sim.gantt);
      const last = this.sim.events[this.sim.events.length - 1];
      if (last?.metrics) this.setMetrics(last.metrics);
      this.setExplain('Schedule complete. Compare waiting and turnaround times, change the algorithm or quantum, and run again on the same virtual app queue.');
      toast('Virtual app schedule finished.', 'success');
      this.refreshQueue();
    },

    virtualProcesses() {
      return this.queuedProcesses.filter((process) => String(process.name || '').startsWith(VIRTUAL_PREFIX));
    },

    setClock(time) {
      this.sim.clock = time;
      const clock = byId('va-clock');
      if (clock) clock.textContent = String(time);
    },

    setCpu(pid) {
      const slot = byId('va-cpu');
      if (!slot) return;
      if (!pid) {
        slot.className = 'va-cpu-slot';
        slot.textContent = 'Idle — waiting for a dispatch';
        return;
      }
      const process = this.processByPid(pid);
      const color = this.sim.colors[pid] || '#0f766e';
      const remaining = this.liveStates[pid]?.remaining;
      slot.className = 'va-cpu-slot is-busy';
      slot.style.setProperty('--va-cpu-color', color);
      slot.innerHTML = `${escapeHtml(pid)} · ${escapeHtml(this.displayName(process))}<small>AT ${escapeHtml(process?.arrival_time)} · BT ${escapeHtml(process?.burst_time)} · PRI ${escapeHtml(process?.priority)}${remaining != null ? ` · left ${remaining}` : ''}</small>`;
    },

    setReady(queue) {
      const box = byId('va-ready-queue');
      if (!box) return;
      if (!queue.length) {
        box.textContent = 'No ready processes yet.';
        return;
      }
      box.innerHTML = queue.map((pid) => {
        const process = this.processByPid(pid);
        const color = this.sim.colors[pid] || '#144743';
        return `<span class="va-chip" style="background:${color}">${escapeHtml(pid)} ${escapeHtml(this.displayName(process).split(' · ').slice(-1)[0] || '')}</span>`;
      }).join('');
    },

    setExplain(text) {
      const node = byId('va-explain');
      if (node) node.textContent = text;
    },

    setMetrics(metrics) {
      const map = {
        'va-metric-wt': metrics ? metrics.avg_waiting_time : '—',
        'va-metric-tat': metrics ? metrics.avg_turnaround_time : '—',
        'va-metric-rt': metrics ? metrics.avg_response_time : '—',
        'va-metric-cpu': metrics ? `${metrics.cpu_utilization}%` : '—'
      };
      Object.entries(map).forEach(([id, value]) => {
        const node = byId(id);
        if (node) node.textContent = value;
      });
    },

    progressiveGantt(time) {
      return (this.sim.gantt || []).filter((seg) => seg.start <= time).map((seg) => (
        seg.end > time ? { ...seg, end: Math.max(seg.start + 1, time) } : seg
      ));
    },

    drawGantt(segments) {
      const canvas = byId('va-gantt-canvas');
      if (!canvas) return;
      const parent = canvas.parentElement;
      const width = parent ? parent.clientWidth : 800;
      canvas.width = Math.max(320, width);
      canvas.height = 110;
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const maxEnd = segments.length ? Math.max(...segments.map((seg) => seg.end || 0), 8) : 8;
      const maxTime = Math.max(8, maxEnd);
      const left = 18;
      const right = 18;
      const top = 18;
      const height = 52;
      const usable = canvas.width - left - right;
      const xAt = (t) => left + (t / maxTime) * usable;
      ctx.strokeStyle = 'rgba(255,255,255,.08)';
      for (let t = 0; t <= maxTime; t++) {
        ctx.beginPath();
        ctx.moveTo(xAt(t), 8);
        ctx.lineTo(xAt(t), top + height + 8);
        ctx.stroke();
      }
      segments.forEach((seg) => {
        const x = xAt(seg.start);
        const w = Math.max(3, xAt(seg.end) - x);
        ctx.fillStyle = this.sim.colors[seg.process] || seg.color || '#0f766e';
        ctx.fillRect(x, top, w, height);
        if (w > 52) {
          const proc = this.processByPid(seg.process);
          const short = proc ? this.displayName(proc).split(' · ').slice(-1)[0] : '';
          ctx.fillStyle = '#fff';
          ctx.font = 'bold 10px Inter, sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(short ? `${seg.process} · ${short}` : seg.process, x + w / 2, top + height / 2);
        } else if (w > 20) {
          ctx.fillStyle = '#fff';
          ctx.font = 'bold 11px Inter, sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(seg.process, x + w / 2, top + height / 2);
        }
      });
      ctx.fillStyle = '#9cc9c2';
      ctx.font = '11px JetBrains Mono, monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      const step = maxTime > 24 ? 4 : 1;
      for (let t = 0; t <= maxTime; t += step) ctx.fillText(String(t), xAt(t), top + height + 12);
    },

    realState: {
      mode: 'simulation',
      connected: false,
      hasSession: false,
      pollTimer: null,
      pairTimer: null,
      pairExpires: 0,
      search: '',
      sort: 'cpu',
      filterApp: '',
      history: [],
      applications: [],
      processes: []
    },

    switchMode(mode) {
      this.realState.mode = mode;
      const simTab = byId('va-tab-sim');
      const realTab = byId('va-tab-real');
      const simContainer = byId('va-mode-simulation-container');
      const realContainer = byId('va-mode-real-container');

      if (mode === 'real-monitor') {
        simTab?.classList.remove('active');
        simTab?.setAttribute('aria-selected', 'false');
        realTab?.classList.add('active');
        realTab?.setAttribute('aria-selected', 'true');
        if (simContainer) simContainer.style.display = 'none';
        if (realContainer) realContainer.style.display = 'block';

        this.refreshRealData();
        if (!this.realState.pollTimer) {
          this.realState.pollTimer = window.setInterval(() => {
            if (this.realState.mode === 'real-monitor') {
              this.refreshRealData();
            }
          }, 2000);
        }
      } else {
        realTab?.classList.remove('active');
        realTab?.setAttribute('aria-selected', 'false');
        simTab?.classList.add('active');
        simTab?.setAttribute('aria-selected', 'true');
        if (realContainer) realContainer.style.display = 'none';
        if (simContainer) simContainer.style.display = 'block';

        if (this.realState.pollTimer) {
          window.clearInterval(this.realState.pollTimer);
          this.realState.pollTimer = null;
        }
      }
    },

    async pairAgent() {
      try {
        const res = await fetch('/api/real-monitor/pair', { method: 'POST' });
        const data = await res.json();
        if (!res.ok || !data.success) {
          throw new Error(data.error || 'Failed to generate pairing code.');
        }

        const tray = byId('va-pairing-tray');
        const codeDisplay = byId('va-pair-code-display');
        const cmdText = byId('va-pair-cmd-text');
        const timerDisplay = byId('va-pair-timer');
        const badge = byId('va-agent-badge');
        const meta = byId('va-agent-meta-info');

        if (tray) tray.style.display = 'block';
        if (codeDisplay) codeDisplay.textContent = data.pair_code;
        if (cmdText) cmdText.textContent = data.command;
        if (badge) {
          badge.className = 'va-badge-waiting';
          badge.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Waiting for Agent...';
        }
        if (meta) meta.textContent = `Pairing code '${data.pair_code}' active. Run the agent in terminal.`;

        this.realState.pairExpires = Date.now() + (data.expires_in * 1000);
        if (this.realState.pairTimer) window.clearInterval(this.realState.pairTimer);
        this.realState.pairTimer = window.setInterval(() => {
          const remaining = Math.max(0, Math.floor((this.realState.pairExpires - Date.now()) / 1000));
          const mins = Math.floor(remaining / 60);
          const secs = String(remaining % 60).padStart(2, '0');
          if (timerDisplay) timerDisplay.textContent = `${mins}:${secs}`;
          if (remaining <= 0) {
            window.clearInterval(this.realState.pairTimer);
            this.realState.pairTimer = null;
            if (badge) {
              badge.className = 'va-badge-disconnected';
              badge.innerHTML = '<i class="fas fa-circle-xmark"></i> Pairing Code Expired';
            }
          }
        }, 1000);

        toast(`Pairing code ${data.pair_code} generated. Ready for agent.`, 'info');
      } catch (err) {
        toast(err.message || 'Error generating pair code', 'error');
      }
    },

    async stopMonitoring() {
      try {
        const res = await fetch('/api/real-monitor/stop', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          this.realState.connected = false;
          this.realState.hasSession = false;
          if (this.realState.pairTimer) {
            window.clearInterval(this.realState.pairTimer);
            this.realState.pairTimer = null;
          }
          const tray = byId('va-pairing-tray');
          const stopBtn = byId('va-btn-stop-agent');
          const pairBtn = byId('va-btn-pair-agent');
          const badge = byId('va-agent-badge');
          const meta = byId('va-agent-meta-info');

          if (tray) tray.style.display = 'none';
          if (stopBtn) stopBtn.style.display = 'none';
          if (pairBtn) pairBtn.style.display = 'inline-flex';
          if (badge) {
            badge.className = 'va-badge-disconnected';
            badge.innerHTML = '<i class="fas fa-circle-xmark"></i> Agent Disconnected';
          }
          if (meta) meta.textContent = 'Monitoring session stopped and token revoked.';

          this.renderTimeline([]);
          this.renderRealApps([]);
          this.renderRealProcesses([]);
          toast('Monitoring session stopped.', 'info');
        }
      } catch (err) {
        toast('Failed to stop monitoring session', 'error');
      }
    },

    async refreshRealData() {
      try {
        const sRes = await fetch('/api/real-monitor/status');
        const sData = await sRes.json();
        if (!sRes.ok || !sData.success) return;

        const isConn = Boolean(sData.connected);
        this.realState.connected = isConn;
        this.realState.hasSession = Boolean(sData.has_session);

        const badge = byId('va-agent-badge');
        const meta = byId('va-agent-meta-info');
        const stopBtn = byId('va-btn-stop-agent');
        const pairBtn = byId('va-btn-pair-agent');
        const tray = byId('va-pairing-tray');

        if (isConn) {
          if (badge) {
            badge.className = 'va-badge-connected';
            badge.innerHTML = '<i class="fas fa-circle-check"></i> Live Agent Connected';
          }
          if (tray) tray.style.display = 'none';
          if (stopBtn) stopBtn.style.display = 'inline-flex';
          if (pairBtn) pairBtn.style.display = 'none';

          const host = sData.agent_metadata?.hostname || 'Local Machine';
          const plat = sData.agent_metadata?.platform || sData.agent_metadata?.os_name || 'Host OS';
          const ago = sData.last_heartbeat_ago != null ? `${sData.last_heartbeat_ago}s ago` : 'active';
          if (meta) meta.textContent = `Streaming from ${host} (${plat}) · Heartbeat ${ago}`;

          const sys = sData.system_summary;
          if (sys) {
            const cpu = sys.cpu_total_percent != null ? Number(sys.cpu_total_percent) : 0;
            const ramUsed = sys.memory_used_mb != null ? Number(sys.memory_used_mb) : 0;
            const ramTot = sys.memory_total_mb != null ? Number(sys.memory_total_mb) : 0;
            const ramPct = sys.memory_percent != null ? Number(sys.memory_percent) : 0;
            const procs = sys.process_count || 0;

            if (byId('va-kpi-cpu')) byId('va-kpi-cpu').textContent = `${cpu.toFixed(1)}%`;
            if (byId('va-kpi-cpu-bar')) byId('va-kpi-cpu-bar').style.width = `${Math.min(100, cpu)}%`;
            if (byId('va-kpi-ram')) byId('va-kpi-ram').textContent = `${Math.round(ramUsed)} MB`;
            if (byId('va-kpi-ram-bar')) byId('va-kpi-ram-bar').style.width = `${Math.min(100, ramPct)}%`;
            if (byId('va-kpi-ram-sub')) byId('va-kpi-ram-sub').textContent = `${ramPct}% of ${Math.round(ramTot)} MB`;
            if (byId('va-kpi-proc-count')) byId('va-kpi-proc-count').textContent = String(procs);
            if (byId('va-kpi-host-info')) byId('va-kpi-host-info').textContent = plat;
          }

          const hRes = await fetch('/api/real-monitor/history?window=120');
          const hData = await hRes.json();
          if (hData.success) {
            this.realState.history = hData.timeline || [];
            this.renderTimeline(this.realState.history);
          }

          const aRes = await fetch('/api/real-monitor/applications');
          const aData = await aRes.json();
          if (aData.success) {
            this.realState.applications = aData.applications || [];
            if (byId('va-kpi-apps-count')) byId('va-kpi-apps-count').textContent = String(this.realState.applications.length);
            this.renderRealApps(this.realState.applications);
          }

          const query = new URLSearchParams();
          if (this.realState.filterApp) query.set('app', this.realState.filterApp);
          if (this.realState.search) query.set('search', this.realState.search);
          if (this.realState.sort) query.set('sort', this.realState.sort);
          query.set('limit', '50');

          const pRes = await fetch(`/api/real-monitor/processes?${query.toString()}`);
          const pData = await pRes.json();
          if (pData.success) {
            this.realState.processes = pData.processes || [];
            this.renderRealProcesses(this.realState.processes);
          }
        } else if (!this.realState.pairTimer) {
          if (badge) {
            badge.className = 'va-badge-disconnected';
            badge.innerHTML = '<i class="fas fa-circle-xmark"></i> Agent Disconnected';
          }
          if (stopBtn) stopBtn.style.display = 'none';
          if (pairBtn) pairBtn.style.display = 'inline-flex';
          if (meta) meta.textContent = 'No active telemetry stream detected. Pair your agent below.';
        }
      } catch (err) {
        console.warn('Real telemetry refresh error:', err);
      }
    },

    renderTimeline(timeline) {
      const container = byId('va-timeline-stream');
      if (!container) return;
      if (!timeline || !timeline.length) {
        container.innerHTML = '<div class="va-empty-timeline"><i class="fas fa-satellite-dish"></i> Waiting for telemetry snapshots from local agent...</div>';
        return;
      }

      const ticksHtml = timeline.slice(-25).map((snap) => {
        const timeStr = snap.timestamp || '--:--:--';
        const topApps = snap.top_apps || [];
        const segmentsHtml = topApps.slice(0, 5).map((app) => {
          const act = (app.activity || 'IDLE').toLowerCase();
          const bandClass = act === 'high' ? 'band-high' : act === 'active' ? 'band-active' : act === 'low' ? 'band-low' : 'band-idle';
          const height = Math.max(4, Math.min(24, Math.round(Number(app.cpu_percent || 0) * 1.5)));
          return `<div class="va-tick-segment ${bandClass}" style="height:${height}px;" title="${escapeHtml(app.name)}: ${app.cpu_percent}% CPU (${app.activity})"></div>`;
        }).join('');

        return `<div class="va-timeline-tick" title="Time: ${escapeHtml(timeStr)} | Total CPU: ${snap.system_cpu}%">
          <div class="va-tick-bar-stack">${segmentsHtml}</div>
          <span class="va-tick-time">${escapeHtml(timeStr.slice(-5))}</span>
        </div>`;
      }).join('');

      container.innerHTML = ticksHtml;
      container.scrollLeft = container.scrollWidth;
    },

    renderRealApps(apps) {
      const grid = byId('va-detected-apps-grid');
      const select = byId('va-proc-filter-app');
      if (!grid) return;

      if (!apps || !apps.length) {
        grid.innerHTML = '<div class="va-empty-card">No applications detected yet. Connect the local agent to stream process groups.</div>';
        return;
      }

      if (select && select.children.length <= 1) {
        const currentVal = select.value;
        const opts = ['<option value="">All Applications</option>'].concat(
          apps.map(a => `<option value="${escapeHtml(a.name)}" ${currentVal === a.name ? 'selected' : ''}>${escapeHtml(a.icon || '⚙️')} ${escapeHtml(a.name)}</option>`)
        );
        select.innerHTML = opts.join('');
      }

      const cardsHtml = apps.map((app) => {
        const isSelected = this.realState.filterApp === app.name;
        return `<div class="va-real-app-card ${isSelected ? 'selected' : ''}" data-app-name="${escapeHtml(app.name)}">
          <div class="va-real-app-header">
            <div class="va-real-app-title">
              <span class="va-real-app-icon">${escapeHtml(app.icon || '⚙️')}</span>
              <span>${escapeHtml(app.name)}</span>
            </div>
            <span class="va-pill-outline">${escapeHtml(app.category || 'App')}</span>
          </div>
          <div class="va-real-app-stats">
            <div class="va-real-app-stat">
              <span>CPU UTILIZATION</span>
              <strong>${Number(app.cpu_percent || 0).toFixed(1)}%</strong>
            </div>
            <div class="va-real-app-stat">
              <span>RAM CONSUMPTION</span>
              <strong>${Math.round(Number(app.memory_rss_mb || 0))} MB</strong>
            </div>
          </div>
          <div style="margin-top:8px; font-size:11px; color:#64748b; font-family:'JetBrains Mono',monospace;">
            <i class="fas fa-layer-group"></i> ${app.process_count || 1} active OS process${(app.process_count || 1) === 1 ? '' : 'es'}
          </div>
        </div>`;
      }).join('');

      grid.innerHTML = cardsHtml;
    },

    renderRealProcesses(procs) {
      const tbody = byId('va-real-process-tbody');
      if (!tbody) return;

      if (!procs || !procs.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="va-empty-row">No matching processes found.</td></tr>';
        return;
      }

      const rows = procs.map((p) => {
        const cpu = Number(p.cpu_percent || 0);
        const cpuClass = cpu >= 5.0 ? 'cpu-high' : 'cpu-normal';
        const ram = Math.round(Number(p.memory_rss_mb || 0));
        const status = escapeHtml(p.status || 'running');
        return `<tr>
          <td><span style="margin-right:6px;">${escapeHtml(p.app_icon || '⚙️')}</span>${escapeHtml(p.app_name || 'Process')}</td>
          <td><span class="pid-badge">${escapeHtml(p.pid)}</span></td>
          <td>${escapeHtml(p.ppid || '1')}</td>
          <td><strong>${escapeHtml(p.name)}</strong></td>
          <td class="${cpuClass}">${cpu.toFixed(1)}%</td>
          <td>${ram} MB</td>
          <td><span class="va-live is-open">${status}</span></td>
          <td>${escapeHtml(p.threads || 1)}</td>
        </tr>`;
      }).join('');

      tbody.innerHTML = rows;
    },

    // ── Virtual Apps Scheduling Assignment Workspace ──
    assignmentState: {
      active: null,
      comparisonResults: {},
      colors: {}
    },

    async openAssignment(assignmentId) {
      try {
        const res = await fetch(`/api/assignments/${assignmentId}/virtual-apps`);
        const data = await res.json();
        if (!data.success) {
          alert(data.error || 'Failed to load assignment details.');
          return;
        }

        const asgn = data.assignment;
        const sub = data.submission;
        this.assignmentState.active = asgn;
        this.assignmentState.comparisonResults = {};

        // Ensure Mode A tab is active
        const tabSim = byId('va-tab-sim');
        if (tabSim && !tabSim.classList.contains('active')) {
          tabSim.click();
        }

        // Color palette for workload processes
        const palette = ['#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c', '#e67e22', '#e91e63'];
        this.assignmentState.colors = {};
        (asgn.workload || []).forEach((p, idx) => {
          this.assignmentState.colors[p.pid] = palette[idx % palette.length];
        });

        // Set metadata
        const titleEl = byId('va-asgn-title');
        const descEl = byId('va-asgn-desc');
        const xpEl = byId('va-asgn-badge-xp');
        const objTextEl = byId('va-asgn-objective-text');
        const pillsEl = byId('va-asgn-allowed-pills');
        const statusEl = byId('va-asgn-badge-status');

        if (titleEl) titleEl.textContent = asgn.title;
        if (descEl) descEl.textContent = asgn.description || '';
        if (xpEl) xpEl.textContent = `+${asgn.points} XP`;
        if (objTextEl) objTextEl.textContent = `Objective: ${asgn.objective_label}`;
        if (pillsEl) pillsEl.textContent = `Allowed: ${(asgn.allowed_algorithms || []).join(', ')} (Quantum = ${asgn.round_robin_quantum || 2})`;

        const isCompleted = sub && (sub.status === 'COMPLETED' || sub.status === 'VERIFIED');
        if (statusEl) {
          if (isCompleted) {
            statusEl.innerHTML = '✅ COMPLETED';
            statusEl.style.background = 'rgba(16,185,129,.2)';
            statusEl.style.color = '#34d399';
          } else if (sub && sub.status === 'IN_PROGRESS') {
            statusEl.innerHTML = '⏳ IN PROGRESS';
            statusEl.style.background = 'rgba(245,158,11,.2)';
            statusEl.style.color = '#fbbf24';
          } else {
            statusEl.innerHTML = '🎯 ASSIGNED';
            statusEl.style.background = 'rgba(20,184,166,.2)';
            statusEl.style.color = '#5eead4';
          }
        }

        // Render Immutable Workload Table
        const wTbody = byId('va-asgn-workload-tbody');
        if (wTbody) {
          wTbody.innerHTML = (asgn.workload || []).map((p) => `
            <tr style="border-top:1px solid rgba(255,255,255,.05);">
              <td style="padding:6px 8px;"><span style="color:#5eead4;font-family:'JetBrains Mono',monospace;font-weight:700;">${escapeHtml(p.pid)}</span></td>
              <td style="padding:6px 8px;"><strong>${escapeHtml(p.app_name || 'App')}</strong> <span style="color:#94a3b8;font-size:10px;">(${escapeHtml(p.name || '')})</span></td>
              <td style="padding:6px 8px;font-family:'JetBrains Mono',monospace;">${p.arrival_time}</td>
              <td style="padding:6px 8px;font-family:'JetBrains Mono',monospace;">${p.burst_time}</td>
              <td style="padding:6px 8px;font-family:'JetBrains Mono',monospace;">${p.priority}</td>
              <td style="padding:6px 8px;font-family:'JetBrains Mono',monospace;color:#94a3b8;">${p.memory_mb || 512} MB</td>
            </tr>
          `).join('');
        }

        // Populate Algorithm Selectors
        const runSelect = byId('va-asgn-run-algo');
        const submitSelect = byId('va-asgn-submit-algo');
        const algos = asgn.allowed_algorithms || ['FCFS', 'SJF', 'Priority', 'RoundRobin'];

        const optsHtml = algos.map((a) => `<option value="${a}">${a}${a === 'RoundRobin' ? ` (Q=${asgn.round_robin_quantum || 2})` : ''}</option>`).join('');
        if (runSelect) runSelect.innerHTML = optsHtml;
        if (submitSelect) submitSelect.innerHTML = optsHtml;

        // Reset metrics and feedback
        this.resetAssignmentDashboard();

        // If prior submission exists, restore its metrics
        if (sub) {
          const attemptsEl = byId('va-asgn-attempts-note');
          if (attemptsEl) attemptsEl.textContent = `Attempts count: ${sub.attempts_count || 1}`;
          const expEl = byId('va-asgn-explanation');
          if (expEl && sub.student_explanation) expEl.value = sub.student_explanation;
          if (submitSelect && sub.selected_algo) submitSelect.value = sub.selected_algo;
          if (runSelect && sub.selected_algo) runSelect.value = sub.selected_algo;

          if (sub.scheduling_metrics && sub.selected_algo) {
            this.updateAssignmentMetrics(sub.selected_algo, sub.scheduling_metrics);
            if (sub.gantt_chart) {
              this.drawAssignmentGantt(sub.gantt_chart);
            }
            this.assignmentState.comparisonResults[sub.selected_algo] = {
              algorithm: sub.selected_algo,
              metrics: sub.scheduling_metrics,
              objective_value: sub.objective_value,
              gantt_chart: sub.gantt_chart || []
            };
            this.renderAssignmentComparisonTable();
          }

          const fbEl = byId('va-asgn-feedback-msg');
          if (fbEl && sub.verification_note) {
            const isOk = sub.status === 'COMPLETED' || sub.status === 'VERIFIED';
            fbEl.innerHTML = `<div style="padding:8px 12px;border-radius:6px;background:${isOk ? 'rgba(16,185,129,.15)' : 'rgba(239,68,68,.15)'};border:1px solid ${isOk ? 'rgba(16,185,129,.4)' : 'rgba(239,68,68,.4)'};color:${isOk ? '#34d399' : '#f87171'};font-size:11.5px;">${escapeHtml(sub.verification_note)}</div>`;
          }
        }

        // Show workspace and smooth scroll
        const ws = byId('va-assignment-workspace');
        if (ws) {
          ws.style.display = 'block';
          ws.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      } catch (err) {
        console.error('Error opening virtual apps assignment:', err);
      }
    },

    closeAssignment() {
      const ws = byId('va-assignment-workspace');
      if (ws) ws.style.display = 'none';
      this.assignmentState.active = null;
    },

    resetAssignmentDashboard() {
      const awtEl = byId('va-asgn-m-awt');
      const tatEl = byId('va-asgn-m-tat');
      const rtEl = byId('va-asgn-m-rt');
      if (awtEl) awtEl.textContent = '—';
      if (tatEl) tatEl.textContent = '—';
      if (rtEl) rtEl.textContent = '—';
      const label = byId('va-asgn-gantt-algo-label');
      if (label) label.textContent = 'None';
      const canvas = byId('va-asgn-gantt-canvas');
      if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
      const cmpTbody = byId('va-asgn-comparison-tbody');
      if (cmpTbody) {
        cmpTbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:12px;">Run any allowed algorithm above to begin comparative analysis.</td></tr>';
      }
      const fbEl = byId('va-asgn-feedback-msg');
      if (fbEl) fbEl.innerHTML = '';
    },

    async runAssignmentAlgorithm() {
      if (!this.assignmentState.active) return;
      const runSelect = byId('va-asgn-run-algo');
      const algo = runSelect ? runSelect.value : 'RoundRobin';
      const btn = byId('va-asgn-btn-run');
      if (btn) btn.disabled = true;

      try {
        const res = await fetch(`/api/assignments/${this.assignmentState.active.id}/virtual-apps/run`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ algorithm: algo })
        });
        const data = await res.json();
        if (!data.success) {
          alert(data.error || 'Failed to execute algorithm simulation.');
          return;
        }

        // Update Gantt and Metrics
        this.updateAssignmentMetrics(data.algorithm, data.metrics);
        this.drawAssignmentGantt(data.gantt_chart);

        // Store comparison result
        this.assignmentState.comparisonResults[data.algorithm] = data;
        this.renderAssignmentComparisonTable();

        // Pre-select submitted algorithm to match this test run
        const submitSelect = byId('va-asgn-submit-algo');
        if (submitSelect) submitSelect.value = data.algorithm;
      } catch (err) {
        console.error('Error running assignment algorithm:', err);
      } finally {
        if (btn) btn.disabled = false;
      }
    },

    updateAssignmentMetrics(algo, metrics) {
      const label = byId('va-asgn-gantt-algo-label');
      if (label) label.textContent = algo;
      const awtEl = byId('va-asgn-m-awt');
      const tatEl = byId('va-asgn-m-tat');
      const rtEl = byId('va-asgn-m-rt');
      if (awtEl) awtEl.textContent = metrics.avg_waiting_time != null ? `${metrics.avg_waiting_time} ms` : '—';
      if (tatEl) tatEl.textContent = metrics.avg_turnaround_time != null ? `${metrics.avg_turnaround_time} ms` : '—';
      if (rtEl) rtEl.textContent = metrics.avg_response_time != null ? `${metrics.avg_response_time} ms` : '—';
    },

    drawAssignmentGantt(segments) {
      const canvas = byId('va-asgn-gantt-canvas');
      if (!canvas) return;
      const parent = canvas.parentElement;
      const width = parent ? parent.clientWidth : 600;
      canvas.width = Math.max(320, width);
      canvas.height = 90;
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      if (!segments || segments.length === 0) return;

      const maxEnd = Math.max(...segments.map((seg) => seg.end || 0), 8);
      const maxTime = Math.max(8, maxEnd);
      const left = 16;
      const right = 16;
      const top = 14;
      const height = 44;
      const usable = canvas.width - left - right;
      const xAt = (t) => left + (t / maxTime) * usable;

      // Grid vertical lines
      ctx.strokeStyle = 'rgba(255,255,255,.07)';
      for (let t = 0; t <= maxTime; t++) {
        ctx.beginPath();
        ctx.moveTo(xAt(t), 6);
        ctx.lineTo(xAt(t), top + height + 6);
        ctx.stroke();
      }

      // Segments
      segments.forEach((seg) => {
        const x = xAt(seg.start);
        const w = Math.max(3, xAt(seg.end) - x);
        ctx.fillStyle = this.assignmentState.colors[seg.process] || seg.color || '#0f766e';
        ctx.fillRect(x, top, w, height);

        if (w > 20) {
          ctx.fillStyle = '#fff';
          ctx.font = 'bold 11px Inter, sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(seg.process, x + w / 2, top + height / 2);
        }
      });

      // Axis ticks
      ctx.fillStyle = '#94a3b8';
      ctx.font = '10px JetBrains Mono, monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      const step = maxTime > 24 ? 4 : (maxTime > 12 ? 2 : 1);
      for (let t = 0; t <= maxTime; t += step) {
        ctx.fillText(String(t), xAt(t), top + height + 8);
      }
    },

    renderAssignmentComparisonTable() {
      const tbody = byId('va-asgn-comparison-tbody');
      if (!tbody) return;

      const entries = Object.values(this.assignmentState.comparisonResults);
      if (entries.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:12px;">Run any allowed algorithm above to begin comparative analysis.</td></tr>';
        return;
      }

      const active = this.assignmentState.active;
      const objKey = active ? active.optimization_objective : 'min_avg_waiting_time';
      const metricField = objKey === 'min_avg_response_time' ? 'avg_response_time' : (objKey === 'min_avg_turnaround_time' ? 'avg_turnaround_time' : 'avg_waiting_time');

      // Find best value among tested
      const values = entries.map((e) => (e.metrics ? Number(e.metrics[metricField] || 999999) : 999999));
      const minVal = Math.min(...values);

      tbody.innerHTML = entries.map((entry) => {
        const m = entry.metrics || {};
        const val = Number(m[metricField] || 0);
        const isOptimal = Math.abs(val - minVal) <= 0.05 && entries.length > 1;

        return `
          <tr class="${isOptimal ? 'is-optimal' : ''}">
            <td><strong>${escapeHtml(entry.algorithm)}</strong></td>
            <td>${m.avg_waiting_time != null ? `${m.avg_waiting_time} ms` : '—'}</td>
            <td>${m.avg_turnaround_time != null ? `${m.avg_turnaround_time} ms` : '—'}</td>
            <td>${m.avg_response_time != null ? `${m.avg_response_time} ms` : '—'}</td>
            <td>${m.cpu_utilization != null ? `${m.cpu_utilization}%` : '—'}</td>
            <td>${m.throughput != null ? m.throughput : '—'}</td>
            <td><strong style="color:${isOptimal ? '#34d399' : '#38bdf8'};">${val.toFixed(2)} ms</strong></td>
            <td>
              ${isOptimal
                ? '<span style="background:rgba(16,185,129,.2);color:#34d399;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;">⭐ BEST TESTED</span>'
                : '<span style="color:#94a3b8;font-size:10px;">Tested</span>'}
            </td>
          </tr>
        `;
      }).join('');
    },

    async submitAssignment() {
      if (!this.assignmentState.active) return;
      const submitSelect = byId('va-asgn-submit-algo');
      const algo = submitSelect ? submitSelect.value : '';
      const expEl = byId('va-asgn-explanation');
      const explanation = expEl ? expEl.value : '';
      const btn = byId('va-asgn-btn-submit');
      const fbEl = byId('va-asgn-feedback-msg');

      if (!algo) {
        alert('Please choose an algorithm to submit.');
        return;
      }

      if (btn) btn.disabled = true;
      if (fbEl) fbEl.innerHTML = '<span style="color:#38bdf8;">Submitting and running automated verification engine...</span>';

      try {
        const res = await fetch(`/api/assignments/${this.assignmentState.active.id}/virtual-apps/submit`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            selected_algo: algo,
            student_explanation: explanation
          })
        });
        const data = await res.json();
        if (!data.success) {
          if (fbEl) fbEl.innerHTML = `<span style="color:#f87171;">❌ ${escapeHtml(data.error || 'Submission failed.')}</span>`;
          return;
        }

        const attemptsEl = byId('va-asgn-attempts-note');
        if (attemptsEl) attemptsEl.textContent = `Attempts count: ${data.attempts_count || 1}`;

        if (data.is_correct) {
          const statusEl = byId('va-asgn-badge-status');
          if (statusEl) {
            statusEl.innerHTML = '✅ COMPLETED';
            statusEl.style.background = 'rgba(16,185,129,.2)';
            statusEl.style.color = '#34d399';
          }
          if (fbEl) {
            fbEl.innerHTML = `
              <div style="padding:10px 14px;border-radius:8px;background:rgba(16,185,129,.18);border:1px solid rgba(16,185,129,.45);color:#34d399;font-size:12px;line-height:1.45;">
                <div style="font-weight:700;font-size:13px;margin-bottom:2px;">🎉 Solution Verified as Optimal!</div>
                <div>${escapeHtml(data.message)}</div>
              </div>
            `;
          }
        } else {
          if (fbEl) {
            fbEl.innerHTML = `
              <div style="padding:10px 14px;border-radius:8px;background:rgba(239,68,68,.16);border:1px solid rgba(239,68,68,.4);color:#fca5a5;font-size:12px;line-height:1.45;">
                <div style="font-weight:700;font-size:13px;margin-bottom:2px;">⚠️ Suboptimal Algorithm Choice</div>
                <div>${escapeHtml(data.feedback || data.message)}</div>
                <div style="margin-top:6px;font-size:11px;color:#94a3b8;">You can run simulations on other allowed algorithms and submit again without penalty!</div>
              </div>
            `;
          }
        }
      } catch (err) {
        console.error('Error submitting assignment:', err);
        if (fbEl) fbEl.innerHTML = `<span style="color:#f87171;">❌ Submission error: ${escapeHtml(err.message)}</span>`;
      } finally {
        if (btn) btn.disabled = false;
      }
    }
  };

  function pidFallback(process) {
    return process?.pid || 'process';
  }

  window.VirtualApps = VirtualApps;
  document.addEventListener('DOMContentLoaded', () => VirtualApps.init());
}());
