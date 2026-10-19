// SysRealm Gantt Chart Renderer
// Draws animated dual-track Gantt chart on <canvas id="gantt-canvas">
// Supports Lane 1 (CPU Core Execution) and Lane 2 (Disk I/O Wait) with CPU-I/O Overlap

const GanttChart = {
  canvas: null,
  ctx: null,
  segments: [],        // [{process, name, start, end, color, type, track}]
  currentTime: 0,
  maxTime: 20,
  animating: false,

  init(canvasId = 'gantt-canvas') {
    this.canvas = document.getElementById(canvasId);
    if (!this.canvas) return;
    this.ctx = this.canvas.getContext('2d');

    const resizeObserver = new ResizeObserver(() => this.resize());
    if (this.canvas.parentElement) {
      resizeObserver.observe(this.canvas.parentElement);
    }
    this.resize();
  },

  reset() {
    this.segments = [];
    this.currentTime = 0;
    this.maxTime = 20;
    this.animating = false;
    this.resize();
    this.draw();
  },

  hasDualTrack() {
    return this.segments && this.segments.some(s => s.track === 'io' || s.type === 'io_wait');
  },

  addSegment(segment) {
    if (!segment) return;
    this.segments.push(segment);
    if (segment.end > this.maxTime) {
      this.maxTime = Math.max(this.maxTime + 5, segment.end + 1);
    }
    this.draw();
  },

  loadChart(segments) {
    this.segments = segments || [];
    if (this.segments.length > 0) {
      const maxEnd = Math.max(...this.segments.map(s => s.end || 0));
      this.maxTime = Math.max(15, maxEnd + 1);
    } else {
      this.maxTime = 20;
    }
    this.resize();
    this.draw();
  },

  timeToX(t) {
    const isDual = this.hasDualTrack();
    const marginLeft = isDual ? 90 : 25;
    const marginRight = 25;
    const availableWidth = this.canvas.width - marginLeft - marginRight;
    return marginLeft + (t / (this.maxTime || 20)) * availableWidth;
  },

  durationToWidth(duration) {
    const isDual = this.hasDualTrack();
    const marginLeft = isDual ? 90 : 25;
    const marginRight = 25;
    const availableWidth = this.canvas.width - marginLeft - marginRight;
    return (duration / (this.maxTime || 20)) * availableWidth;
  },

  resize() {
    if (!this.canvas) return;
    const parent = this.canvas.parentElement;
    this.canvas.width = parent ? parent.clientWidth : 800;
    this.canvas.height = this.hasDualTrack() ? 150 : 100;
    this.draw();
  },

  draw() {
    if (!this.ctx || !this.canvas) return;
    const { width, height } = this.canvas;
    const isDual = this.hasDualTrack();

    this.ctx.clearRect(0, 0, width, height);

    // Grid lines
    this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
    this.ctx.lineWidth = 1;
    const axisY = isDual ? 122 : 75;

    for (let i = 0; i <= this.maxTime; i++) {
      const x = this.timeToX(i);
      this.ctx.beginPath();
      this.ctx.moveTo(x, 8);
      this.ctx.lineTo(x, axisY);
      this.ctx.stroke();
    }

    if (isDual) {
      // Draw lane dividers & track labels
      this.ctx.fillStyle = 'rgba(255, 255, 255, 0.02)';
      this.ctx.fillRect(90, 10, width - 115, 44);
      this.ctx.fillRect(90, 66, width - 115, 44);

      // Lane 1 divider
      this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
      this.ctx.beginPath();
      this.ctx.moveTo(10, 59);
      this.ctx.lineTo(width - 10, 59);
      this.ctx.stroke();

      // Lane labels on left
      this.ctx.font = 'bold 11px Inter, system-ui, sans-serif';
      this.ctx.textAlign = 'left';
      this.ctx.textBaseline = 'middle';

      this.ctx.fillStyle = '#60a5fa';
      this.ctx.fillText('⚡ CPU Core', 12, 32);

      this.ctx.fillStyle = '#fbbf24';
      this.ctx.fillText('💾 Disk I/O', 12, 88);
    }

    // Draw Segments
    this.segments.forEach(seg => this.drawSegment(seg, isDual));

    // Time Axis
    this.drawTimeAxis(isDual, axisY);
  },

  drawSegment(seg, isDual) {
    if (!this.ctx) return;

    const x = this.timeToX(seg.start);
    const w = Math.max(2, this.durationToWidth(seg.end - seg.start));

    let y = 10;
    let h = isDual ? 44 : 58;

    const isIo = seg.track === 'io' || seg.type === 'io_wait';
    if (isDual && isIo) {
      y = 66;
    }

    if (isIo) {
      // Distinct Hatched Amber block for Disk I/O wait
      this.ctx.fillStyle = 'rgba(245, 158, 11, 0.2)';
      this.ctx.fillRect(x, y, w, h);

      // Draw diagonal stripes
      this.ctx.save();
      this.ctx.beginPath();
      this.ctx.rect(x, y, w, h);
      this.ctx.clip();
      this.ctx.strokeStyle = 'rgba(245, 158, 11, 0.45)';
      this.ctx.lineWidth = 2;
      for (let sx = x - h; sx < x + w + h; sx += 8) {
        this.ctx.moveTo(sx, y + h);
        this.ctx.lineTo(sx + h, y);
      }
      this.ctx.stroke();
      this.ctx.restore();

      this.ctx.strokeStyle = '#f59e0b';
      this.ctx.lineWidth = 1.5;
      this.ctx.setLineDash([4, 2]);
      this.ctx.strokeRect(x, y, w, h);
      this.ctx.setLineDash([]);

      // Label
      if (w > 22) {
        this.ctx.fillStyle = '#fde68a';
        this.ctx.font = 'bold 11px Inter, system-ui, sans-serif';
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        const label = `${seg.process} (I/O)`;
        this.ctx.fillText(label, x + w / 2, y + h / 2);
      }
    } else if (seg.type === 'idle') {
      this.ctx.fillStyle = 'rgba(51, 65, 85, 0.4)';
      this.ctx.fillRect(x, y, w, h);
      this.ctx.strokeStyle = 'rgba(100, 116, 139, 0.4)';
      this.ctx.lineWidth = 1;
      this.ctx.strokeRect(x, y, w, h);

      if (w > 25) {
        this.ctx.fillStyle = '#64748b';
        this.ctx.font = 'italic 11px Inter, system-ui, sans-serif';
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        this.ctx.fillText('Idle', x + w / 2, y + h / 2);
      }
    } else {
      // Regular CPU burst
      this.ctx.fillStyle = seg.color || '#3b82f6';
      this.ctx.fillRect(x, y, w, h);

      this.ctx.strokeStyle = 'rgba(15, 23, 42, 0.9)';
      this.ctx.lineWidth = 2;
      this.ctx.strokeRect(x, y, w, h);

      if (w > 20) {
        this.ctx.fillStyle = '#ffffff';
        this.ctx.font = 'bold 12px Inter, system-ui, sans-serif';
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        const label = w > 60 && seg.name ? `${seg.process}: ${seg.name.split(' ')[0]}` : seg.process;
        this.ctx.fillText(label, x + w / 2, y + h / 2);
      }
    }
  },

  drawTimeAxis(isDual, axisY) {
    this.ctx.fillStyle = '#94a3b8';
    this.ctx.font = '11px Inter, system-ui, sans-serif';
    this.ctx.textAlign = 'center';
    this.ctx.textBaseline = 'top';

    const tickStep = this.maxTime > 40 ? 5 : (this.maxTime > 25 ? 2 : 1);

    for (let i = 0; i <= this.maxTime; i += tickStep) {
      const x = this.timeToX(i);
      this.ctx.fillText(i.toString(), x, axisY + 5);

      this.ctx.beginPath();
      this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
      this.ctx.moveTo(x, axisY - 5);
      this.ctx.lineTo(x, axisY);
      this.ctx.stroke();
    }

    this.ctx.beginPath();
    this.ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
    this.ctx.moveTo(this.timeToX(0), axisY);
    this.ctx.lineTo(this.timeToX(this.maxTime), axisY);
    this.ctx.stroke();
  }
};

window.GanttChart = GanttChart;
