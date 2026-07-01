/* ============================================================
   Lithops landing page — interactions & hero visualization
   ============================================================ */
(function () {
  'use strict';

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- year ---------- */
  $('#year').textContent = new Date().getFullYear();

  const burger = $('#burger');
  const navLinks = $('.nav-links');
  if (burger && navLinks) {
    burger.addEventListener('click', () => navLinks.classList.toggle('open'));
    $$('.nav-links a').forEach((a) => a.addEventListener('click', () => navLinks.classList.remove('open')));
  }

  /* ---------- copy buttons ---------- */
  $$('.copy-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(btn.dataset.copy);
        btn.classList.add('copied');
        setTimeout(() => btn.classList.remove('copied'), 1400);
      } catch (e) { /* clipboard blocked */ }
    });
  });

  /* ---------- copy buttons ---------- */
  $$('.section, .flow-node, .feature, .uc, .backend-col, .cta-card, .trustbar').forEach((el) => el.classList.add('reveal'));
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
  }, { threshold: 0.12 });
  $$('.reveal').forEach((el) => io.observe(el));

  /* ---------- count-up stats ---------- */
  const fmt = (n) => n.toLocaleString('en-US');
  const runCount = (el) => {
    const target = parseFloat(el.dataset.count);
    const suffix = el.dataset.suffix || '';
    const dur = 1500;
    const t0 = performance.now();
    const tick = (t) => {
      const p = Math.min(1, (t - t0) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(Math.round(target * eased)) + suffix;
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };
  const statIO = new IntersectionObserver((entries) => {
    entries.forEach((e) => { if (e.isIntersecting) { runCount(e.target); statIO.unobserve(e.target); } });
  }, { threshold: 0.6 });
  $$('.stat-num').forEach((el) => statIO.observe(el));

  /* ---------- code tabs + terminal sim ---------- */
  const runFile = $('#runFile');
  const editorFile = $('#editorFile');
  const runBody = $('#runBody');
  const files = {
    hello: 'hello.py',
    map: 'estimate_pi.py',
    reduce: 'map_reduce.py',
    storage: 'storage.py',
  };
  const outputs = {
    hello: [
      { c: 'dim', t: '[INFO] lithops.executor — ExecutorID a1b2 | dispatching' },
      { c: 'dim', t: '[INFO] invoker — 1 activation invoked (localhost)' },
      { c: 'ok', t: 'Hello World!' },
    ],
    map: [
      { c: 'dim', t: '[INFO] executor — 10 activations invoked' },
      { c: 'acc', t: '  ▸ workers 10/10 running…' },
      { c: 'dim', t: '[INFO] wait — 10/10 done in 3.42s' },
      { c: 'ok', t: 'Estimated Pi: 3.14159...' },
    ],
    reduce: [
      { c: 'dim', t: '[INFO] executor — map: 4 activations invoked' },
      { c: 'dim', t: '[INFO] executor — reduce: 1 activation invoked' },
      { c: 'ok', t: '38' },
    ],
    storage: [
      { c: 'dim', t: '[INFO] storage — backend: s3 | bucket: mybucket' },
      { c: 'dim', t: '[INFO] put_object test.txt (11 B)' },
      { c: 'ok', t: 'Hello World' },
    ],
  };

  let termTimer = null;
  function playTerminal(key) {
    if (termTimer) { clearTimeout(termTimer); termTimer = null; }
    runBody.innerHTML = `<div class="run-line"><span class="prompt">$</span> python ${files[key]}</div>`;
    const lines = outputs[key];
    let i = 0;
    const step = () => {
      if (i >= lines.length) {
        const cur = document.createElement('div');
        cur.className = 'run-line';
        cur.innerHTML = '<span class="run-cursor"></span>';
        runBody.appendChild(cur);
        return;
      }
      const l = lines[i++];
      const div = document.createElement('div');
      div.className = 'run-line ' + (l.c || '');
      div.textContent = l.t;
      runBody.appendChild(div);
      termTimer = setTimeout(step, reduced ? 60 : 520);
    };
    termTimer = setTimeout(step, reduced ? 60 : 420);
  }

  $$('.code-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const key = tab.dataset.tab;
      $$('.code-tab').forEach((t) => t.classList.remove('active'));
      tab.classList.add('active');
      $$('.code-pane').forEach((p) => p.classList.remove('active'));
      $('#pane-' + key).classList.add('active');
      editorFile.textContent = files[key];
      runFile.textContent = files[key];
      playTerminal(key);
    });
  });
  // kick off first terminal when code section is visible
  const codeIO = new IntersectionObserver((entries) => {
    entries.forEach((e) => { if (e.isIntersecting) { playTerminal('hello'); codeIO.unobserve(e.target); } });
  }, { threshold: 0.3 });
  codeIO.observe($('#code'));

  /* ============================================================
     Hero canvas — laptop invoking thousands of functions
     ============================================================ */
  const canvas = $('#scaleCanvas');
  const ctx = canvas.getContext('2d');
  let W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 2);

  const CY = '#2ec5ff';
  const OR = '#ff8c1a';
  const GRN = '#37d67a';

  const INVOKED_TOTAL = 10000;

  let laptop = { x: 0, y: 0, w: 0, h: 0 };
  let grid = { x0: 0, y0: 0, cell: 0, gap: 0, cols: 0, rows: 0 };
  let cells = [];
  let particles = [];
  let hud = { active: 0, done: 0, total: 0 };
  const hudActive = $('#hudActive');
  const hudDone = $('#hudDone');
  const hudState = $('#hudState');
  const hudPct = $('#hudPct');
  const hudProgress = $('#hudProgress');
  const hudThroughput = $('#hudThroughput');
  const hudWorkers = $('#hudWorkers');
  const hudWorkerPool = $('#hudWorkerPool');
  let donePrev = 0;
  let throughput = 0;
  let throughputAcc = 0;
  let jobProgress = 0;
  let jobPhase = 'running';
  let jobStart = 0;
  let completeHoldStart = 0;
  const JOB_MS = 13000;
  const HOLD_MS = 5000;

  function layout() {
    const r = canvas.getBoundingClientRect();
    W = r.width; H = r.height;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const padBottom = 72;
    const padTop = H * 0.06;
    const sceneH = H - padTop - padBottom;

    const laptopW = Math.max(68, W * 0.13);
    const laptopH = laptopW * 0.62;

    laptop.w = laptopW;
    laptop.h = laptopH;
    laptop.x = W * 0.18;
    laptop.y = padTop + sceneH * 0.5;

    const gx0 = W * 0.42;
    const gx1 = W * 0.94;
    const gy0 = padTop + sceneH * 0.04;
    const gy1 = padTop + sceneH * 0.96;
    const gw = gx1 - gx0;
    const gh = gy1 - gy0;
    grid.cols = W < 420 ? 10 : (W < 620 ? 13 : 17);
    grid.gap = Math.max(3, gw / grid.cols * 0.2);
    grid.cell = (gw - grid.gap * (grid.cols - 1)) / grid.cols;
    grid.rows = Math.max(8, Math.floor((gh + grid.gap) / (grid.cell + grid.gap)));
    grid.x0 = gx0;
    grid.y0 = gy0 + (gh - (grid.rows * grid.cell + (grid.rows - 1) * grid.gap)) / 2;

    cells = [];
    for (let row = 0; row < grid.rows; row++) {
      for (let col = 0; col < grid.cols; col++) {
        cells.push({
          x: grid.x0 + col * (grid.cell + grid.gap),
          y: grid.y0 + row * (grid.cell + grid.gap),
          state: 'idle',
          t: 0,
          life: 0,
        });
      }
    }
    hud.total = cells.length;
    hud.done = 0;
    donePrev = 0;
    if (hudWorkerPool) hudWorkerPool.textContent = fmt(cells.length);
  }

  function cloudPath(x, y, w, h) {
    // soft blobby outline behind the grid
    ctx.beginPath();
    const r = h * 0.28;
    ctx.moveTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.quadraticCurveTo(x, y + h * 0.5, x + w * 0.12, y + h * 0.45);
    ctx.quadraticCurveTo(x + w * 0.14, y, x + w * 0.42, y + h * 0.1);
    ctx.quadraticCurveTo(x + w * 0.62, y - h * 0.05, x + w * 0.72, y + h * 0.2);
    ctx.quadraticCurveTo(x + w, y + h * 0.15, x + w, y + h * 0.5);
    ctx.quadraticCurveTo(x + w + r * 0.4, y + h, x + w - r, y + h);
    ctx.closePath();
  }

  function spawnParticle() {
    // find an idle cell to invoke
    const idle = [];
    for (let i = 0; i < cells.length; i++) if (cells[i].state === 'idle') idle.push(i);
    if (!idle.length) return;
    const idx = idle[(Math.random() * idle.length) | 0];
    const c = cells[idx];
    const sx = laptop.x + laptop.w * 0.28;
    const sy = laptop.y - laptop.h * 0.1;
    const tx = c.x + grid.cell / 2;
    const ty = c.y + grid.cell / 2;
    // control point for a curved arc
    const cx = (sx + tx) / 2 + (Math.random() - 0.5) * 40;
    const cy = (sy + ty) / 2 - 60 - Math.random() * 40;
    particles.push({
      dir: 'out', cell: idx, sx, sy, cx, cy, tx, ty,
      p: 0, speed: 0.012 + Math.random() * 0.01,
    });
  }

  function bez(a, b, c, t) {
    const u = 1 - t;
    return u * u * a + 2 * u * t * b + t * t * c;
  }

  let last = performance.now();
  let spawnAcc = 0;

  function frame(now) {
    const dt = Math.min(50, now - last); last = now;
    if (!jobStart) jobStart = now;
    ctx.clearRect(0, 0, W, H);

    if (jobPhase === 'running') {
      jobProgress = Math.min(1, (now - jobStart) / JOB_MS);
      if (jobProgress >= 1) {
        jobPhase = 'complete';
        completeHoldStart = now;
      }
    } else if (jobPhase === 'complete') {
      jobProgress = 1;
      if (now - completeHoldStart > HOLD_MS) {
        jobPhase = 'running';
        jobStart = now;
        jobProgress = 0;
        donePrev = hud.done;
        throughputAcc = 0;
      }
    }

    const spawning = jobPhase === 'running' && jobProgress < 0.98;
    if (spawning) {
      spawnAcc += dt;
      const interval = 26;
      while (spawnAcc > interval) {
        spawnAcc -= interval;
        for (let k = 0; k < 3; k++) spawnParticle();
      }
    }

    // ---- cloud outline ----
    const pad = grid.cell * 1.4;
    cloudPath(grid.x0 - pad, grid.y0 - pad, (grid.cols * (grid.cell + grid.gap)) + pad * 1.6, (grid.rows * (grid.cell + grid.gap)) + pad * 1.4);
    ctx.strokeStyle = 'rgba(46,197,255,0.18)';
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.fillStyle = 'rgba(46,197,255,0.03)';
    ctx.fill();

    // ---- cells ----
    let active = 0;
    for (const c of cells) {
      let col = 'rgba(120,140,170,0.14)';
      let glow = 0;
      if (c.state === 'running') {
        c.t += dt;
        const pulse = 0.55 + 0.45 * Math.sin(c.t / 130);
        col = `rgba(255,140,26,${0.55 + 0.4 * pulse})`;
        glow = 10 + 6 * pulse;
        active++;
        if (c.t > c.life) {
          c.state = 'done'; c.t = 0;
          hud.done++;
          // return particle to laptop
          particles.push({
            dir: 'in',
            sx: c.x + grid.cell / 2, sy: c.y + grid.cell / 2,
            cx: (laptop.x + c.x) / 2, cy: (laptop.y + c.y) / 2 + 70,
            tx: laptop.x + laptop.w * 0.28, ty: laptop.y - laptop.h * 0.1,
            p: 0, speed: 0.02 + Math.random() * 0.012,
          });
        }
      } else if (c.state === 'done') {
        c.t += dt;
        const f = Math.max(0, 1 - c.t / 900);
        col = `rgba(55,214,122,${0.15 + 0.6 * f})`;
        glow = 8 * f;
        if (c.t > 900) { c.state = 'idle'; c.t = 0; }
      }
      const s = grid.cell;
      const rr = Math.max(2, s * 0.22);
      if (glow > 0) { ctx.shadowColor = c.state === 'running' ? OR : GRN; ctx.shadowBlur = glow; }
      ctx.fillStyle = col;
      roundRect(c.x, c.y, s, s, rr); ctx.fill();
      ctx.shadowBlur = 0;
    }

    // ---- particles ----
    for (let i = particles.length - 1; i >= 0; i--) {
      const pt = particles[i];
      pt.p += pt.speed * (dt / 16.67);
      const t = pt.p;
      if (t >= 1) {
        if (pt.dir === 'out') {
          const c = cells[pt.cell];
          if (c && c.state === 'idle') { c.state = 'running'; c.t = 0; c.life = 900 + Math.random() * 1600; }
        }
        particles.splice(i, 1);
        continue;
      }
      const x = bez(pt.sx, pt.cx, pt.tx, t);
      const y = bez(pt.sy, pt.cy, pt.ty, t);
      const color = pt.dir === 'out' ? CY : GRN;
      // trail
      const tt = Math.max(0, t - 0.06);
      const x2 = bez(pt.sx, pt.cx, pt.tx, tt);
      const y2 = bez(pt.sy, pt.cy, pt.ty, tt);
      ctx.strokeStyle = pt.dir === 'out' ? 'rgba(46,197,255,0.5)' : 'rgba(55,214,122,0.5)';
      ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.moveTo(x2, y2); ctx.lineTo(x, y); ctx.stroke();
      ctx.fillStyle = color;
      ctx.shadowColor = color; ctx.shadowBlur = 8;
      ctx.beginPath(); ctx.arc(x, y, 2.2, 0, Math.PI * 2); ctx.fill();
      ctx.shadowBlur = 0;
    }

    drawLaptop();
    drawInvokeArc();

    hud.active = active;
    const pct = Math.round(jobProgress * 100);
    const simDone = Math.round(jobProgress * INVOKED_TOTAL);

    hudActive.textContent = fmt(active);
    hudDone.textContent = fmt(simDone);
    if (jobPhase === 'complete') {
      hudState.textContent = 'complete';
    } else if (jobProgress > 0.75) {
      hudState.textContent = 'collecting…';
    } else if (active > 12) {
      hudState.textContent = 'scaling out…';
    } else if (active > 0) {
      hudState.textContent = 'invoking…';
    } else {
      hudState.textContent = 'dispatching…';
    }
    if (hudPct) hudPct.textContent = pct + '%';
    if (hudProgress) hudProgress.style.width = pct + '%';
    if (hudWorkers) hudWorkers.textContent = fmt(INVOKED_TOTAL) + ' invoked';

    throughputAcc += dt;
    if (throughputAcc > 420) {
      if (jobPhase === 'complete') {
        throughput = 0;
      } else {
        const delta = hud.done - donePrev;
        throughput = Math.round((delta / throughputAcc) * 1000);
        donePrev = hud.done;
      }
      throughputAcc = 0;
      if (hudThroughput) hudThroughput.textContent = fmt(throughput) + ' fn/s';
    }

    rafId = requestAnimationFrame(frame);
  }

  function drawInvokeArc() {
    const sx = laptop.x + laptop.w * 0.32;
    const sy = laptop.y - laptop.h * 0.05;
    const tx = grid.x0 - grid.cell * 0.4;
    const ty = laptop.y;
    const cx = (sx + tx) / 2;
    const cy = sy - Math.max(24, H * 0.06);

    ctx.save();
    ctx.strokeStyle = 'rgba(46,197,255,0.22)';
    ctx.lineWidth = 1.2;
    ctx.setLineDash([4, 6]);
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.quadraticCurveTo(cx, cy, tx, ty);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = 'rgba(139,150,173,0.75)';
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText('invoke', cx, cy - 6);
    ctx.restore();
  }

  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function drawLaptop() {
    const { x, y, w, h } = laptop;
    const sx = x - w / 2, sy = y - h / 2;
    // screen
    ctx.fillStyle = '#0b1120';
    ctx.strokeStyle = 'rgba(46,197,255,0.55)';
    ctx.lineWidth = 2;
    roundRect(sx, sy, w, h, 8); ctx.fill(); ctx.stroke();
    // inner glow
    ctx.fillStyle = 'rgba(46,197,255,0.06)';
    roundRect(sx + 4, sy + 4, w - 8, h - 8, 6); ctx.fill();
    // prompt lines (code)
    ctx.save();
    ctx.beginPath(); roundRect(sx + 8, sy + 8, w - 16, h - 16, 5); ctx.clip();
    const ly = sy + h * 0.26;
    const lh = h * 0.16;
    const rows = [
      [OR, 0.10, 0.34], [CY, 0.10, 0.5], [CY, 0.18, 0.62], ['#9ae86b', 0.18, 0.44],
    ];
    rows.forEach((rw, i) => {
      ctx.fillStyle = rw[0];
      ctx.globalAlpha = 0.85;
      ctx.fillRect(sx + w * rw[1], ly + i * lh, w * (rw[2] - rw[1]), lh * 0.34);
    });
    ctx.globalAlpha = 1;
    ctx.restore();
    // base
    ctx.fillStyle = 'rgba(46,197,255,0.5)';
    ctx.beginPath();
    ctx.moveTo(sx - w * 0.12, sy + h + 6);
    ctx.lineTo(sx + w + w * 0.12, sy + h + 6);
    ctx.lineTo(sx + w + w * 0.05, sy + h + 12);
    ctx.lineTo(sx - w * 0.05, sy + h + 12);
    ctx.closePath(); ctx.fill();
    // label
    ctx.fillStyle = 'rgba(139,150,173,0.9)';
    ctx.font = '11px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText('your laptop', x, sy + h + 30);
  }

  let rafId = null;
  function start() {
    layout();
    if (reduced) {
      // static-ish: light a few cells
      cells.forEach((c, i) => { if (i % 5 === 0) { c.state = 'running'; c.life = 1e9; c.t = Math.random() * 300; } });
      // single render
      last = performance.now();
      frame(last);
      cancelAnimationFrame(rafId);
      return;
    }
    last = performance.now();
    rafId = requestAnimationFrame(frame);
  }

  let resizeTO = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTO);
    resizeTO = setTimeout(() => { layout(); }, 150);
  });

  // pause when offscreen to save CPU
  const heroIO = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) { if (!rafId && !reduced) { last = performance.now(); rafId = requestAnimationFrame(frame); } }
      else { if (rafId) { cancelAnimationFrame(rafId); rafId = null; } }
    });
  }, { threshold: 0.05 });

  start();
  heroIO.observe(canvas);
})();
