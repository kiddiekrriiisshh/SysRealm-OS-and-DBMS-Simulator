// SysRealm Animation Engine
// Handles all UI animations and transitions

const SysAnimations = {
  // Toast notifications
  showToast(message, type = 'info', duration = 3000) {
    const toastContainer = document.getElementById('toast-container') || this.createToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<div class="toast-body">${message}</div>`;
    
    toastContainer.appendChild(toast);
    
    // Animate in
    setTimeout(() => toast.classList.add('show'), 10);
    
    // Animate out
    setTimeout(() => {
      toast.classList.remove('show');
      setTimeout(() => toast.remove(), 300);
    }, duration);
  },
  
  createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.style.position = 'fixed';
    container.style.bottom = '20px';
    container.style.right = '20px';
    container.style.zIndex = '9999';
    document.body.appendChild(container);
    return container;
  },

  // Process card creation 
  createProcessCard(process, options = {}) {
    const card = document.createElement('div');
    card.className = 'process-card';
    card.id = `process-card-${process.id || process.pid || process.process_id}`;
    card.style.backgroundColor = options.color || '#3498db';
    card.style.color = '#fff';
    card.style.padding = '10px';
    card.style.margin = '5px';
    card.style.borderRadius = '5px';
    card.style.display = 'inline-block';
    card.style.transition = 'all 0.3s ease';
    card.innerHTML = `
      <div style="font-weight: bold">${process.name || process.process_name || process.id}</div>
      <div style="font-size: 0.8em">Burst: ${process.burst_time || process.remaining || 0}</div>
    `;
    return card;
  },
  
  // Animate process moving to CPU
  animateToQueue(processCard, queueContainer) {
    processCard.style.opacity = '0';
    processCard.style.transform = 'translateX(-20px)';
    queueContainer.appendChild(processCard);
    
    setTimeout(() => {
      processCard.style.opacity = '1';
      processCard.style.transform = 'translateX(0)';
    }, 50);
  },
  
  animateToCPU(processCard, cpuBox) {
    // Basic transition, moving visually from queue to CPU
    processCard.style.transform = 'scale(1.1)';
    setTimeout(() => {
      cpuBox.innerHTML = '';
      processCard.style.transform = 'scale(1)';
      cpuBox.appendChild(processCard);
    }, 300);
  },
  
  animateToTerminated(processCard) {
    processCard.style.transform = 'scale(0.8)';
    processCard.style.opacity = '0.5';
    const termContainer = document.getElementById('terminated-container');
    if (termContainer) {
      termContainer.appendChild(processCard);
    } else {
      setTimeout(() => processCard.remove(), 300);
    }
  },
  
  // Queue animations
  animateQueueUpdate(queueContainer, queue, processColors) {
    queueContainer.innerHTML = '';
    queue.forEach((pid, index) => {
      const card = this.createProcessCard({ id: pid, name: pid }, { color: processColors[pid] });
      card.style.animationDelay = `${index * 0.1}s`;
      card.classList.add('slide-in');
      queueContainer.appendChild(card);
    });
  },
  
  // CPU box state
  setCPURunning(pid, name, remaining, totalBurst) {
    const cpuBox = document.getElementById('cpu-box');
    if (!cpuBox) return;
    
    cpuBox.className = 'cpu-box running';
    cpuBox.style.borderColor = '#2ecc71';
    cpuBox.innerHTML = `
      <h4>Running</h4>
      <div class="cpu-process">
        <strong>${name} (${pid})</strong>
        <div>Remaining: ${remaining}</div>
      </div>
    `;
  },
  
  setCPUIdle() {
    const cpuBox = document.getElementById('cpu-box');
    if (!cpuBox) return;
    
    cpuBox.className = 'cpu-box idle';
    cpuBox.style.borderColor = '#95a5a6';
    cpuBox.innerHTML = `<h4>CPU Idle</h4>`;
  },
  
  // Status badge creation
  createStatusBadge(state) {
    const colors = {
      'READY': '#f39c12',
      'RUNNING': '#2ecc71',
      'WAITING': '#e74c3c',
      'TERMINATED': '#95a5a6',
      'NEW': '#3498db'
    };
    const color = colors[state] || '#333';
    return `<span class="badge" style="background-color: ${color}; color: white; padding: 3px 8px; border-radius: 12px; font-size: 0.8em;">${state}</span>`;
  },
  
  // Pulse/highlight element
  highlight(element, color = '#f1c40f', duration = 1000) {
    if (!element) return;
    const origBg = element.style.backgroundColor;
    const origTransition = element.style.transition;
    
    element.style.transition = 'background-color 0.3s ease';
    element.style.backgroundColor = color;
    
    setTimeout(() => {
      element.style.backgroundColor = origBg;
      setTimeout(() => {
        element.style.transition = origTransition;
      }, 300);
    }, duration);
  },
  
  // Counter animation
  animateCounter(element, from, to, duration = 1000) {
    if (!element) return;
    const startTime = performance.now();
    
    const updateCounter = (time) => {
      const elapsed = time - startTime;
      const progress = Math.min(elapsed / duration, 1);
      
      const current = Math.floor(from + (to - from) * progress);
      element.textContent = current;
      
      if (progress < 1) {
        requestAnimationFrame(updateCounter);
      } else {
        element.textContent = to;
      }
    };
    
    requestAnimationFrame(updateCounter);
  },
  
  // Score update animation
  showScoreUpdate(delta, reason) {
    const scoreElement = document.getElementById('score-display');
    if (!scoreElement) return;
    
    const update = document.createElement('div');
    update.className = `score-update ${delta >= 0 ? 'positive' : 'negative'}`;
    update.textContent = `${delta >= 0 ? '+' : ''}${delta} ${reason}`;
    update.style.position = 'absolute';
    update.style.color = delta >= 0 ? '#2ecc71' : '#e74c3c';
    update.style.fontWeight = 'bold';
    update.style.top = '-20px';
    update.style.opacity = '1';
    update.style.transition = 'all 1s ease-out';
    
    scoreElement.parentElement.appendChild(update);
    
    setTimeout(() => {
      update.style.transform = 'translateY(-30px)';
      update.style.opacity = '0';
    }, 50);
    
    setTimeout(() => update.remove(), 1050);
  },
  
  // Typing effect for explanation text
  typeText(element, text, speed = 20) {
    if (!element) return;
    // Just set the text directly — fast and no race conditions
    element.textContent = text;
  }
};

window.SysAnimations = SysAnimations;
