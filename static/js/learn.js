// SysRealm — Step-by-Step Learning Mode
// Walks through scheduling events one at a time, quizzes the user at key moments

var LearnController = {

  // ── State ──
  events:      [],
  processes:   {},     // pid → process data (for formulas)
  currentIdx:  0,
  algo:        'FCFS',
  quantum:     2,
  score:       0,
  correct:     0,
  wrong:       0,
  quizAnswered: false,
  currentQuiz:  null,  // {type, answer, pid}
  quizLog:      [],    // [{q, correct, userAns, rightAns}]

  COLORS: {
    FCFS:'#3b82f6', SJF:'#22c55e', Priority:'#f59e0b', RoundRobin:'#e74c3c'
  },

  PROC_COLORS: ['#e74c3c','#3b82f6','#2ecc71','#f39c12','#9b59b6','#1abc9c','#e67e22','#e91e63'],

  // ── Init ──
  init: function() {
    var self = this;
    var btnStart   = document.getElementById('btn-learn-start');
    var btnNext    = document.getElementById('btn-learn-next');
    var btnCheck   = document.getElementById('btn-learn-check');
    var btnSkip    = document.getElementById('btn-learn-skip-q');
    var btnRestart = document.getElementById('btn-learn-restart');
    var btnAgain   = document.getElementById('btn-learn-again');
    var algoSel    = document.getElementById('learn-algo');

    if (btnStart)   btnStart.addEventListener('click',   function() { self.startLearning(); });
    if (btnNext)    btnNext.addEventListener('click',    function() { self.nextStep(); });
    if (btnCheck)   btnCheck.addEventListener('click',   function() { self.checkAnswer(); });
    if (btnSkip)    btnSkip.addEventListener('click',    function() { self.skipQuestion(); });
    if (btnRestart) btnRestart.addEventListener('click', function() { self.restart(); });
    if (btnAgain)   btnAgain.addEventListener('click',   function() { self.showSetup(); });

    // Show/hide quantum input for RR
    if (algoSel) {
      algoSel.addEventListener('change', function() {
        var qg = document.getElementById('learn-quantum-group');
        if (qg) qg.style.display = algoSel.value === 'RoundRobin' ? 'block' : 'none';
      });
      // trigger on load
      var qg = document.getElementById('learn-quantum-group');
      if (qg) qg.style.display = 'none';
    }

    // Enter key on answer input
    var ansInput = document.getElementById('learn-answer-input');
    if (ansInput) {
      ansInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') self.checkAnswer();
      });
    }
  },

  // ── Start Session ──
  startLearning: async function() {
    var algoEl = document.getElementById('learn-algo');
    var qEl    = document.getElementById('learn-quantum');
    this.algo    = algoEl ? algoEl.value : 'FCFS';
    this.quantum = qEl ? (parseInt(qEl.value, 10) || 2) : 2;
    this.score   = 0;
    this.correct = 0;
    this.wrong   = 0;
    this.quizLog = [];
    this.currentIdx = 0;
    this.quizAnswered = true;  // start as answered so Next Step is enabled

    var btnStart = document.getElementById('btn-learn-start');
    if (btnStart) { btnStart.disabled = true; btnStart.textContent = 'Loading...'; }

    try {
      // Load demo + run algorithm
      await fetch('/api/demo/load');
      var res  = await fetch('/api/scheduler/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ algorithm: this.algo, quantum: this.quantum })
      });
      var data = await res.json();

      if (!data.success || !data.events || data.events.length === 0) {
        alert('Could not load learning data. Make sure Flask is running.');
        return;
      }

      // Build process lookup
      this.processes = {};
      var self = this;
      (data.processes || []).forEach(function(p, i) {
        self.processes[p.pid] = p;
        self.processes[p.pid]._color = self.PROC_COLORS[i % self.PROC_COLORS.length];
      });

      // Filter to interesting events only (reduce noise)
      this.events = data.events.filter(function(e) {
        return ['PROCESS_STARTED','PROCESS_COMPLETED','PROCESS_ARRIVED',
                'QUANTUM_EXPIRED','CPU_IDLE'].indexOf(e.event) !== -1;
      });

      // Show workspace
      document.getElementById('learn-setup').style.display = 'none';
      document.getElementById('learn-workspace').style.display = 'block';
      document.getElementById('learn-results').style.display = 'none';

      // Set header
      var algoLabel = document.getElementById('learn-algo-label');
      if (algoLabel) algoLabel.textContent = this.algo;

      var stepTotal = document.getElementById('learn-step-total');
      if (stepTotal) stepTotal.textContent = this.events.length;

      this.updateScoreDisplay();
      this.showStep(0);

    } catch(e) {
      alert('Error: ' + e.message);
    } finally {
      if (btnStart) { btnStart.disabled = false; btnStart.textContent = '🎓 Start Learning'; }
    }
  },

  // ── Show a Step ──
  showStep: function(idx) {
    if (idx >= this.events.length) {
      this.finishSession();
      return;
    }

    var ev   = this.events[idx];
    var self = this;

    // Progress
    var pct = Math.round((idx / this.events.length) * 100);
    var pb  = document.getElementById('learn-progress-bar');
    if (pb) pb.style.width = pct + '%';
    var sn  = document.getElementById('learn-step-num');
    if (sn) sn.textContent = idx + 1;

    // Time
    var tEl = document.getElementById('learn-time');
    if (tEl) tEl.textContent = (ev.time || 0) + ' ms';

    // CPU Box
    this.updateCPU(ev);

    // Queue
    this.updateQueue(ev.queue || []);

    // Explanation
    var expEl = document.getElementById('learn-explanation');
    if (expEl) expEl.textContent = ev.explanation || (ev.event + ' at time ' + ev.time);

    // Hide formula box initially
    var fBox = document.getElementById('learn-formula-box');
    if (fBox) fBox.style.display = 'none';

    // Hide quiz card
    this.hideQuiz();

    // Enable/disable Next Step
    var btnNext = document.getElementById('btn-learn-next');

    // Decide if this step gets a quiz
    var quiz = this.buildQuiz(ev, idx);
    if (quiz) {
      this.currentQuiz = quiz;
      this.quizAnswered = false;

      // Show formula first
      this.showFormula(ev);

      // Then show quiz
      setTimeout(function() {
        self.showQuiz(quiz);
        if (btnNext) btnNext.disabled = true;
      }, 400);
    } else {
      this.currentQuiz = null;
      this.quizAnswered = true;
      if (btnNext) {
        btnNext.disabled = false;
        btnNext.textContent = idx + 1 >= this.events.length - 1 ? '🏁 See Results' : '⏭ Next Step';
      }
    }
  },

  // ── Build Quiz for an event ──
  buildQuiz: function(ev, idx) {
    var pid  = ev.process_id;
    var proc = pid ? this.processes[pid] : null;

    // Quiz 1: At PROCESS_COMPLETED — ask Waiting Time
    if (ev.event === 'PROCESS_COMPLETED' && proc) {
      var ct  = ev.time;
      var at  = proc.arrival_time != null ? proc.arrival_time : 0;
      var bt  = proc.burst_time   != null ? proc.burst_time   : 0;
      var tat = ct - at;
      var wt  = tat - bt;
      return {
        type: 'number',
        subtype: 'waiting_time',
        pid: pid,
        name: proc.name || pid,
        answer: wt,
        ct: ct, at: at, bt: bt, tat: tat,
        question: 'Process ' + (proc.name || pid) + ' just completed at time ' + ct + ' ms.\n\n' +
                  'Using the formula: Waiting Time = Turnaround Time − Burst Time\n' +
                  'Where: TAT = Completion Time − Arrival Time = ' + ct + ' − ' + at + ' = ' + tat + ' ms\n\n' +
                  'What is the Waiting Time (WT) for ' + (proc.name || pid) + '?',
        unit: 'ms',
        explanation_right: 'Correct! WT = TAT − BT = ' + tat + ' − ' + bt + ' = ' + wt + ' ms.',
        explanation_wrong: 'The correct answer is ' + wt + ' ms.\nWT = TAT − BT = ' + tat + ' − ' + bt + ' = ' + wt + ' ms.'
      };
    }

    // Quiz 2: At PROCESS_STARTED — ask which algo rule selected it (every 3rd started event)
    if (ev.event === 'PROCESS_STARTED' && proc && idx % 3 === 0) {
      var queuePids = ev.queue || [];
      // Only quiz if there are multiple processes in queue
      if (queuePids.length >= 1) {
        var options = [pid];
        queuePids.forEach(function(p) { if (p !== pid && options.length < 4) options.push(p); });
        // shuffle
        options.sort(function() { return Math.random() - 0.5; });

        return {
          type: 'mcq',
          subtype: 'next_process',
          pid: pid,
          name: proc.name || pid,
          answer: pid,
          options: options,
          question: 'The CPU is now executing a process at time ' + ev.time + ' ms.\n' +
                    'According to ' + this.algo + ', which process was selected to run?',
          explanation_right: 'Correct! ' + (proc.name || pid) + ' (' + pid + ') was selected by ' + this.algo + '.',
          explanation_wrong: (proc.name || pid) + ' (' + pid + ') was the correct choice per ' + this.algo + ' rules.'
        };
      }
    }

    return null;  // no quiz for this event
  },

  // ── Show formula spotlight ──
  showFormula: function(ev) {
    var pid  = ev.process_id;
    var proc = pid ? this.processes[pid] : null;
    if (!proc) return;

    var fBox = document.getElementById('learn-formula-box');
    var fEl  = document.getElementById('learn-formula');
    if (!fBox || !fEl) return;

    var lines = [];

    if (ev.event === 'PROCESS_COMPLETED') {
      var ct  = ev.time;
      var at  = proc.arrival_time != null ? proc.arrival_time : 0;
      var bt  = proc.burst_time   != null ? proc.burst_time   : 0;
      var tat = ct - at;
      var wt  = tat - bt;
      lines.push('For process ' + (proc.name || pid) + ' (' + pid + '):');
      lines.push('');
      lines.push('Turnaround Time (TAT) = CT − AT');
      lines.push('                      = ' + ct + ' − ' + at + ' = ' + tat + ' ms');
      lines.push('');
      lines.push('Waiting Time (WT)     = TAT − BT');
      lines.push('                      = ' + tat + ' − ' + bt + ' = ??? ms  ← YOU CALCULATE');
    } else if (ev.event === 'PROCESS_STARTED') {
      lines.push('Algorithm: ' + this.algo);
      lines.push('');
      if (this.algo === 'FCFS') {
        lines.push('FCFS Rule: Pick process with LOWEST arrival time');
        lines.push('Arrival time of ' + (proc.name || pid) + ': ' + proc.arrival_time + ' ms');
      } else if (this.algo === 'SJF') {
        lines.push('SJF Rule: Pick process with LOWEST burst time');
        lines.push('Burst time of ' + (proc.name || pid) + ': ' + proc.burst_time + ' ms');
      } else if (this.algo === 'Priority') {
        lines.push('Priority Rule: Pick process with LOWEST priority number');
        lines.push('Priority of ' + (proc.name || pid) + ': ' + proc.priority);
      } else if (this.algo === 'RoundRobin') {
        lines.push('RR Rule: Each process gets ' + this.quantum + ' ms quantum (time slice)');
        lines.push('After ' + this.quantum + ' ms, next process in queue gets the CPU');
      }
    }

    if (lines.length > 0) {
      fEl.textContent = lines.join('\n');
      fBox.style.display = 'block';
    }
  },

  // ── Show quiz card ──
  showQuiz: function(quiz) {
    var card = document.getElementById('learn-quiz-card');
    var qEl  = document.getElementById('learn-question');
    if (!card || !qEl) return;

    qEl.textContent = quiz.question;
    card.style.display = 'block';

    var feedEl = document.getElementById('learn-feedback');
    if (feedEl) feedEl.style.display = 'none';

    var checkBtn = document.getElementById('btn-learn-check');
    if (checkBtn) checkBtn.disabled = false;

    if (quiz.type === 'mcq') {
      document.getElementById('learn-mcq-options').style.display = 'flex';
      document.getElementById('learn-num-input').style.display   = 'none';
      this.buildMCQ(quiz.options);
    } else {
      document.getElementById('learn-mcq-options').style.display = 'none';
      document.getElementById('learn-num-input').style.display   = 'flex';
      var inp = document.getElementById('learn-answer-input');
      if (inp) { inp.value = ''; inp.focus(); }
      var unitEl = document.getElementById('learn-unit');
      if (unitEl) unitEl.textContent = quiz.unit || 'ms';
    }
  },

  buildMCQ: function(options) {
    var container = document.getElementById('learn-mcq-options');
    if (!container) return;
    container.innerHTML = '';
    var self = this;
    options.forEach(function(pid) {
      var proc  = self.processes[pid];
      var label = proc ? (proc.name || pid) + ' (' + pid + ')' : pid;
      var btn   = document.createElement('button');
      btn.className = 'btn';
      btn.textContent = label;
      btn.dataset.pid = pid;
      btn.style.cssText = 'background:var(--secondary);border:2px solid var(--border-color);min-width:120px;';
      btn.addEventListener('click', function() {
        container.querySelectorAll('button').forEach(function(b) {
          b.style.border = '2px solid var(--border-color)';
          b.style.background = 'var(--secondary)';
        });
        btn.style.border = '2px solid var(--primary)';
        btn.style.background = 'var(--primary)';
        container.dataset.selected = pid;
      });
      container.appendChild(btn);
    });
  },

  hideQuiz: function() {
    var card = document.getElementById('learn-quiz-card');
    if (card) card.style.display = 'none';
  },

  // ── Check Answer ──
  checkAnswer: function() {
    var quiz = this.currentQuiz;
    if (!quiz || this.quizAnswered) return;

    var userAnswer;
    if (quiz.type === 'mcq') {
      var container = document.getElementById('learn-mcq-options');
      userAnswer = container ? container.dataset.selected : null;
      if (!userAnswer) {
        if (window.SysAnimations) window.SysAnimations.showToast('Select a process first', 'warning');
        return;
      }
    } else {
      var inp = document.getElementById('learn-answer-input');
      userAnswer = inp ? parseFloat(inp.value) : null;
      if (userAnswer === null || isNaN(userAnswer)) {
        if (window.SysAnimations) window.SysAnimations.showToast('Enter a number first', 'warning');
        return;
      }
    }

    var isCorrect;
    if (quiz.type === 'mcq') {
      isCorrect = (userAnswer === quiz.answer);
    } else {
      isCorrect = (Math.abs(userAnswer - quiz.answer) < 0.01);
    }

    this.quizAnswered = true;
    this.quizLog.push({
      question: quiz.question.split('\n')[0],
      correct:  isCorrect,
      userAns:  userAnswer,
      rightAns: quiz.answer
    });

    if (isCorrect) {
      this.correct++;
      this.score += 10;
      this.showFeedback(true, quiz.explanation_right);
    } else {
      this.wrong++;
      this.showFeedback(false, quiz.explanation_wrong);
    }

    this.updateScoreDisplay();

    // Disable check button
    var checkBtn = document.getElementById('btn-learn-check');
    if (checkBtn) checkBtn.disabled = true;

    // Enable Next Step
    var btnNext = document.getElementById('btn-learn-next');
    if (btnNext) {
      btnNext.disabled = false;
      var isLast = this.currentIdx >= this.events.length - 1;
      btnNext.textContent = isLast ? '🏁 See Results' : '⏭ Next Step';
    }
  },

  showFeedback: function(correct, text) {
    var feedEl = document.getElementById('learn-feedback');
    if (!feedEl) return;
    feedEl.style.display = 'block';
    feedEl.style.background = correct ? '#14532d' : '#7f1d1d';
    feedEl.style.border     = '1px solid ' + (correct ? '#22c55e' : '#ef4444');
    feedEl.style.color      = correct ? '#86efac' : '#fca5a5';
    feedEl.innerHTML = (correct ? '✅ ' : '❌ ') + text.replace(/\n/g, '<br>');
  },

  skipQuestion: function() {
    var quiz = this.currentQuiz;
    if (quiz) {
      this.quizAnswered = true;
      this.quizLog.push({
        question: quiz.question.split('\n')[0],
        correct:  false,
        userAns:  '(skipped)',
        rightAns: quiz.answer
      });
      this.wrong++;
      this.showFeedback(false, 'Skipped. ' + quiz.explanation_wrong);
      this.updateScoreDisplay();
    }
    var btnNext = document.getElementById('btn-learn-next');
    if (btnNext) {
      btnNext.disabled = false;
      btnNext.textContent = this.currentIdx >= this.events.length - 1 ? '🏁 See Results' : '⏭ Next Step';
    }
    var checkBtn = document.getElementById('btn-learn-check');
    if (checkBtn) checkBtn.disabled = true;
  },

  // ── Next Step ──
  nextStep: function() {
    if (!this.quizAnswered) return;
    this.currentIdx++;
    if (this.currentIdx >= this.events.length) {
      this.finishSession();
    } else {
      this.showStep(this.currentIdx);
    }
  },

  // ── CPU + Queue display ──
  updateCPU: function(ev) {
    var box = document.getElementById('learn-cpu-box');
    if (!box) return;
    var pid  = ev.process_id;
    var proc = pid ? this.processes[pid] : null;

    if (ev.event === 'CPU_IDLE' || ev.event === 'PROCESS_COMPLETED' || !pid) {
      box.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">CPU IDLE</div>';
      box.style.borderColor = 'var(--border-color)';
      return;
    }
    if (!proc) {
      box.innerHTML = '<div>' + pid + '</div>';
      return;
    }
    var color = proc._color || '#3b82f6';
    box.style.borderColor = color;
    box.innerHTML =
      '<div style="display:flex;align-items:center;gap:10px;">' +
        '<div style="width:40px;height:40px;border-radius:8px;background:' + color + ';display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:16px;">' + pid + '</div>' +
        '<div>' +
          '<div style="font-weight:bold;color:' + color + ';">' + (proc.name || pid) + '</div>' +
          '<div style="font-size:12px;color:var(--text-muted);">Burst: ' + proc.burst_time + ' ms | Priority: ' + proc.priority + '</div>' +
        '</div>' +
      '</div>';
  },

  updateQueue: function(pids) {
    var qEl = document.getElementById('learn-queue');
    if (!qEl) return;
    qEl.innerHTML = '';
    if (!pids || pids.length === 0) {
      qEl.innerHTML = '<span style="color:var(--text-muted);font-size:12px;">Empty</span>';
      return;
    }
    var self = this;
    pids.forEach(function(pid) {
      var proc  = self.processes[pid];
      var color = (proc && proc._color) || '#64748b';
      var span  = document.createElement('span');
      span.style.cssText = 'background:' + color + '33;border:1px solid ' + color + ';border-radius:6px;padding:3px 10px;font-size:12px;font-weight:bold;color:' + color + ';';
      span.textContent = pid;
      qEl.appendChild(span);
    });
  },

  updateScoreDisplay: function() {
    var sc = document.getElementById('learn-score');
    var co = document.getElementById('learn-correct');
    var wr = document.getElementById('learn-wrong');
    if (sc) sc.textContent = this.score;
    if (co) co.textContent = this.correct;
    if (wr) wr.textContent = this.wrong;
  },

  // ── Finish Session ──
  finishSession: function() {
    document.getElementById('learn-workspace').style.display = 'none';
    document.getElementById('learn-results').style.display   = 'block';

    var doneHint = document.getElementById('learn-done-hint');
    if (doneHint) doneHint.style.display = 'block';

    var total    = this.quizLog.length;
    var pct      = total > 0 ? Math.round((this.correct / total) * 100) : 100;
    var grade    = pct >= 90 ? { letter:'A+', color:'#22c55e', emoji:'🏆' }
                 : pct >= 75 ? { letter:'A',  color:'#3b82f6', emoji:'🎉' }
                 : pct >= 60 ? { letter:'B',  color:'#f59e0b', emoji:'👍' }
                 : pct >= 40 ? { letter:'C',  color:'#f97316', emoji:'📚' }
                 :             { letter:'D',  color:'#ef4444', emoji:'💪' };

    var bannerEl = document.getElementById('learn-grade-banner');
    if (bannerEl) {
      bannerEl.innerHTML =
        '<div style="font-size:60px;margin-bottom:8px;">' + grade.emoji + '</div>' +
        '<div style="font-size:48px;font-weight:bold;color:' + grade.color + ';">' + grade.letter + '</div>' +
        '<div style="font-size:18px;margin:8px 0;color:' + grade.color + ';">' + pct + '% Accuracy</div>' +
        '<div style="color:var(--text-muted);font-size:14px;">' +
          this.correct + ' correct &nbsp;|&nbsp; ' + this.wrong + ' wrong &nbsp;|&nbsp; ' + this.score + ' pts' +
        '</div>';
    }

    // Quiz log table
    var summEl = document.getElementById('learn-summary-table');
    if (summEl && this.quizLog.length > 0) {
      var rows = this.quizLog.map(function(q, i) {
        return '<tr>' +
          '<td>' + (i+1) + '</td>' +
          '<td style="max-width:300px;font-size:13px;">' + q.question + '</td>' +
          '<td style="color:' + (q.correct ? '#22c55e' : '#ef4444') + ';">' +
            (q.correct ? '✅ ' + q.userAns : '❌ ' + q.userAns) +
          '</td>' +
          '<td style="color:#f59e0b;">' + q.rightAns + '</td>' +
        '</tr>';
      }).join('');
      summEl.innerHTML =
        '<div style="font-weight:bold;margin-bottom:10px;">📋 Quiz Summary</div>' +
        '<div class="table-container"><table>' +
          '<thead><tr><th>#</th><th>Question</th><th>Your Answer</th><th>Correct Answer</th></tr></thead>' +
          '<tbody>' + rows + '</tbody>' +
        '</table></div>';
    } else if (summEl) {
      summEl.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:16px;">No quiz questions this session — try a longer algorithm or more processes!</div>';
    }
  },

  // ── Restart / Setup ──
  restart: function() {
    this.showSetup();
  },

  showSetup: function() {
    document.getElementById('learn-setup').style.display     = 'block';
    document.getElementById('learn-workspace').style.display = 'none';
    document.getElementById('learn-results').style.display   = 'none';
    this.events = [];
    this.currentIdx = 0;
  }
};

window.LearnController = LearnController;

document.addEventListener('DOMContentLoaded', function() {
  LearnController.init();
});
