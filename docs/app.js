/* ============================================================
   claude-daily landing page — animation orchestration

   The page tells a story:
     1. user is at their project's prompt
     2. types `claude`, hits enter
     3. Claude Code welcome screen renders
     4. SessionStart hook fires → ASCII banner + dashboard streams in
   ============================================================ */

(function () {
  'use strict';

  const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // -----------------------------------------------------------
  // ASCII banner (rendered once SessionStart hook fires)
  // -----------------------------------------------------------
  const BANNER = [
    '   ▄████▄   ██▓    ▄▄▄       █    ██ ▓█████▄ ▓█████ ',
    '  ▒██▀ ▀█  ▓██▒   ▒████▄     ██  ▓██▒▒██▀ ██▌▓█   ▀ ',
    '  ▒▓█    ▄ ▒██░   ▒██  ▀█▄  ▓██  ▒██░░██   █▌▒███   ',
    '  ▒▓▓▄ ▄██▒▒██░   ░██▄▄▄▄██ ▓▓█  ░██░░▓█▄   ▌▒▓█  ▄ ',
    '  ▒ ▓███▀ ░░██████▒▓█   ▓██▒▒▒█████▓ ░▒████▓ ░▒████▒',
    '  ░ ░▒ ▒  ░░ ▒░▓  ░▒▒   ▓▒█░░▒▓▒ ▒ ▒  ▒▒▓  ▒ ░░ ▒░ ░',
    '    ░  ▒   ░ ░ ▒  ░ ▒   ▒▒ ░░░▒░ ░ ░  ░ ▒  ▒  ░ ░  ░',
    '  ░          ░ ░    ░   ▒    ░░░ ░ ░  ░ ░  ░    ░   ',
    '  ░ ░          ░  ░     ░  ░   ░        ░       ░  ░',
    '                                                     ',
    '           D · A · I · L · Y    [v0.1]',
  ].join('\n');

  // -----------------------------------------------------------
  // Static data
  // -----------------------------------------------------------
  const WEEK = [
    { day: 'Tue', count: 0 },
    { day: 'Wed', count: 0 },
    { day: 'Thu', count: 1 },
    { day: 'Fri', count: 8 },
    { day: 'Sat', count: 0 },
    { day: 'Sun', count: 1 },
    { day: 'Mon', count: 0 },
  ];

  const EFF = [
    { name: 'Edit / Read',  value: '1.0',   bars: [4,2,1,3,2,3,2,5,4,8,4,8,4,1], d7: '↓', d30: '↓', status: 'good' },
    { name: 'Auto-approve', value: '65.7%', bars: [7,6,1,7,3,6,6,4,6,8,7,8,8,2], d7: '↓', d30: '↓', status: 'bad' },
    { name: 'First-try',    value: '83.4%', bars: [7,8,8,7,7,8,8,8,7,7,8,7,8,1], d7: '↓', d30: '↓', status: 'good' },
    { name: 'Corrections',  value: '15.1%', bars: [7,4,3,4,8,2,1,2,1,1,3,1,1,1], d7: '↓', d30: '↓', status: 'bad',  invertGood: true },
    { name: 'Tool errors',  value: '10.2%', bars: [2,4,5,1,3,2,2,2,3,8,3,8,3,1], d7: '↓', d30: '↓', status: 'bad',  invertGood: true },
    { name: 'Ctx hygiene',  value: '50.0%', bars: [0,0,0,0,0,0,0,0,0,1,1,1,8,8], d7: '↓', d30: '↓', status: 'warn' },
  ];

  const FOCUS = [
    { sev: 'bad',  name: 'Auto-approve', value: '65.7%', target: 33, warn: '70%', good: '80%',
      rec: 'Most tools need manual approval. Consider sandbox mode or add allowedTools.' },
    { sev: 'bad',  name: 'Corrections',  value: '15.1%', target: 65, warn: '15%', good: '5%',
      rec: 'High correction rate. Split complex prompts. Use /compact between focus changes.' },
    { sev: 'bad',  name: 'Tool errors',  value: '10.2%', target: 60, warn: '8%',  good: '3%',
      rec: 'Many tool failures. Check CLAUDE.md for missing workflow instructions or stale paths.' },
    { sev: 'warn', name: 'Ctx hygiene',  value: '50.0%', target: 55, warn: '40%', good: '70%',
      rec: 'Long sessions run past 40 turns without /compact. Compact at task boundaries.' },
  ];

  const SCOUT = [
    { q: 'claude code sandbox permissions',
      actionable: 'Enable sandboxing in ~/.claude/settings.json so Bash auto-runs without prompts inside the sandbox; keep allow/denyWrite tight.',
      repo: 'PACHAKUTlQ/ClaudeCage',
      repoNote: 'Try ClaudeCage when you scout untrusted repos so you can keep auto-approve high.' },
    { q: 'claude code auto approve setup',
      actionable: 'If on Team plan, run `claude --permission-mode auto` for this repo — your 65.7% auto-approve will jump.',
      repo: 'oryband/claude-code-auto-approve',
      repoNote: 'Install as a PreToolUse hook so chained commands like `rtk npm run lint && rtk` auto-pass.' },
    { q: 'claude code session management',
      actionable: 'Delegate one-off research to subagents (Explore/Plan) instead of running it in main thread — keeps ctx hygiene healthy.',
      repo: 'thedotmack/claude-mem',
      repoNote: 'Try claude-mem alongside your existing ~/.claude/memory dir to test cross-session memory.' },
    { q: 'claude code prompt engineering tips',
      actionable: "Replace 'look at scripts/validate.js' with '@scripts/validate.js' in prompts — cuts a Read round-trip.",
      repo: 'Piebald-AI/claude-code-system-prompts',
      repoNote: 'Read the Plan/Explore/Task subagent prompts there before writing your own.' },
    { q: 'claude code error handling patterns',
      actionable: 'When tool_error_rate spikes, run /doctor as the first step — fastest path to spotting a stale setting.',
      repo: 'cheapestinference/claude-auto-retry',
      repoNote: 'Install if you hit Max plan caps mid-task — avoids the manual resume.' },
    { q: 'claude code CLAUDE.md audit tool',
      actionable: "Run an audit on this repo's CLAUDE.md — the RTK section is verbose and could be pushed behind a reference link.",
      repo: 'AgentLint marketplace action',
      repoNote: 'Wire AgentLint into the main-branch workflow to score the whole .claude/ setup.' },
  ];

  // -----------------------------------------------------------
  // Build dashboard content (DOM, not visible yet — `.stage`
  // elements are hidden until JS adds `.ready`).
  // -----------------------------------------------------------
  function levelFor(n) {
    if (n === 0) return 0;
    if (n <= 1) return 1;
    if (n <= 3) return 2;
    if (n <= 6) return 3;
    return 4;
  }

  function buildWeekBars() {
    const host = document.getElementById('weekbars');
    WEEK.forEach((d) => {
      const wrap = document.createElement('div');
      wrap.className = `bar count-${d.count}`;
      wrap.innerHTML = `
        <div class="label">${d.day}</div>
        <div class="cell lvl-${levelFor(d.count)}"></div>
        <div class="count">${d.count}</div>
      `;
      host.appendChild(wrap);
    });
  }

  function buildEfficiency() {
    const host = document.getElementById('efficiency-grid');
    EFF.forEach((m) => {
      const row = document.createElement('div');
      row.className = 'eff-row';
      const barsHtml = m.bars.map(h => `<span class="b" style="height:${Math.max(8, h * 12.5)}%"></span>`).join('');
      const arrowClass = m.invertGood
        ? (m.status === 'good' ? 'red' : 'green')
        : (m.status === 'good' ? 'green' : 'red');
      row.innerHTML = `
        <span class="eff-name">${m.name}</span>
        <span class="eff-value">${m.value}</span>
        <span class="sparkline eff-spark">${barsHtml}</span>
        <span class="eff-arrow eff-deltas ${arrowClass}">${m.d7}</span>
        <span class="eff-arrow eff-deltas ${arrowClass}">${m.d30}</span>
        <span class="eff-status">
          <span class="dot ${m.status}"></span>
          <span class="lbl ${m.status}">${m.status}</span>
        </span>
      `;
      host.appendChild(row);
    });
  }

  function buildContributions() {
    const host = document.getElementById('contributions');
    const WEEKS = 53;
    const seed = 42;
    const prng = (x) => ((Math.sin(x * 12.9898) * 43758.5453) % 1 + 1) % 1;
    for (let w = 0; w < WEEKS; w++) {
      for (let d = 0; d < 7; d++) {
        const i = w * 7 + d;
        const r = prng(seed + i);
        let lvl = 0;
        if (r > 0.985) lvl = 4;
        else if (r > 0.97) lvl = 3;
        else if (r > 0.95) lvl = 2;
        else if (r > 0.92) lvl = 1;
        if (w > WEEKS - 6 && r > 0.55) lvl = Math.max(lvl, Math.round((r - 0.55) * 8));
        const cell = document.createElement('div');
        cell.className = `cell lvl-${Math.min(4, lvl)}`;
        cell.style.transitionDelay = `${(w * 7 + d) * 1.2}ms`;
        host.appendChild(cell);
      }
    }
  }

  function buildFocus() {
    const host = document.getElementById('focus-areas');
    FOCUS.forEach((f) => {
      const row = document.createElement('div');
      row.className = `focus-row ${f.sev}`;
      row.style.setProperty('--target', `${f.target}%`);
      row.innerHTML = `
        <span class="sev-dot"></span>
        <span class="sev-tag">${f.sev.toUpperCase()}</span>
        <span class="name">${f.name}</span>
        <span class="fgauge"><span class="fill"></span></span>
        <span class="val">${f.value}</span>
        <span class="range">warn ${f.warn} · good ${f.good}</span>
        <span class="rec">${f.rec}</span>
      `;
      host.appendChild(row);
    });
  }

  function buildScout() {
    const host = document.getElementById('scout-findings');
    SCOUT.forEach((s) => {
      const div = document.createElement('div');
      div.className = 'scout-item';
      div.innerHTML = `
        <div class="q">${s.q}</div>
        <div class="actionable">${s.actionable}</div>
        <div class="repo"><span class="name">${s.repo}</span> · ${s.repoNote}</div>
      `;
      host.appendChild(div);
    });
  }

  buildWeekBars();
  buildEfficiency();
  buildContributions();
  buildFocus();
  buildScout();

  // -----------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------
  const sleep = (ms) => new Promise(r => setTimeout(r, REDUCED ? 0 : ms));

  function typeInto(el, text, perChar = 90) {
    if (REDUCED) { el.textContent = text; return Promise.resolve(); }
    el.textContent = '';
    return new Promise((resolve) => {
      let i = 0;
      const tick = () => {
        if (i >= text.length) return resolve();
        el.textContent += text[i++];
        setTimeout(tick, perChar + Math.random() * 40);
      };
      tick();
    });
  }

  function typeLines(el, text, perLine = 16) {
    if (REDUCED) { el.textContent = text; return Promise.resolve(); }
    el.textContent = '';
    const lines = text.split('\n');
    return new Promise((resolve) => {
      let i = 0;
      const tick = () => {
        if (i >= lines.length) return resolve();
        el.textContent += (i === 0 ? '' : '\n') + lines[i++];
        setTimeout(tick, perLine);
      };
      tick();
    });
  }

  // -----------------------------------------------------------
  // Sequence the story
  // -----------------------------------------------------------
  async function run() {
    const typedCmd  = document.getElementById('typed-cmd');
    const welcome   = document.getElementById('welcome');
    const banner    = document.getElementById('ascii-banner');
    const hookOut   = document.getElementById('hook-output');
    const blocks    = document.querySelectorAll('.hook-output .block.stage');

    // 1. Pause briefly so the user sees the empty prompt
    await sleep(550);

    // 2. Type `claude`
    await typeInto(typedCmd, 'claude');
    await sleep(280);

    // 3. Press enter — collapse the cursor onto the next line by hiding
    //    it on the prompt line (the welcome box will appear below)
    document.querySelector('.prompt-line .cmd-cursor').style.display = 'none';
    await sleep(180);

    // 4. Welcome screen fades in (sprite + Claude Code title + cwd)
    welcome.classList.add('ready');
    await sleep(REDUCED ? 0 : 380);

    // 5. Input prompt line appears below the welcome (`> Try ...`)
    document.getElementById('input-line').classList.add('ready');
    await sleep(REDUCED ? 0 : 220);

    // 6. Divider then the SessionStart hook output region
    document.getElementById('divider').classList.add('ready');
    hookOut.classList.add('ready');
    await sleep(REDUCED ? 0 : 120);

    // 7. ASCII banner typewriter
    await typeLines(banner, BANNER, 14);
    await sleep(REDUCED ? 0 : 200);

    // 8. Cascade-reveal each dashboard block + its animated children
    for (const block of blocks) {
      block.classList.add('ready', 'in-view');
      // Also light up the animatable children inside (sparklines, gauges,
      // heatmap, focus rows, scout list) so their CSS transitions play.
      block.querySelectorAll('.gauge-wide, .sparkline, .contributions, .focus-row, .scout')
        .forEach(el => el.classList.add('in-view'));
      await sleep(REDUCED ? 0 : 220);
    }
  }

  // -----------------------------------------------------------
  // Page-level reveal-on-scroll for the sections under the terminal.
  // Generous rootMargin + 1.2s safety net so headless captures don't
  // leave anything stuck at opacity 0.
  // -----------------------------------------------------------
  function setupPageReveal() {
    const targets = document.querySelectorAll('.page-section.reveal');
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          e.target.classList.add('in-view');
          io.unobserve(e.target);
        }
      });
    }, { rootMargin: '0px 0px 25% 0px', threshold: 0.01 });
    targets.forEach((el) => io.observe(el));
    // Safety net for non-scrolling environments (headless captures, etc.)
    setTimeout(() => targets.forEach((el) => el.classList.add('in-view')), 1500);
  }

  // -----------------------------------------------------------
  // Status-bar clock (matches Claude Code's bottom bar)
  // -----------------------------------------------------------
  function tickClock() {
    const el = document.getElementById('sb-time');
    if (!el) return;
    const update = () => {
      const d = new Date();
      const hh = String(d.getHours()).padStart(2, '0');
      const mm = String(d.getMinutes()).padStart(2, '0');
      el.textContent = `${hh}:${mm}`;
    };
    update();
    setInterval(update, 30000);
  }
  tickClock();

  // -----------------------------------------------------------
  // Subtle ambient CRT noise on the ASCII banner
  // -----------------------------------------------------------
  function ambientJitter() {
    if (REDUCED) return;
    const banner = document.getElementById('ascii-banner');
    setInterval(() => {
      banner.style.transform = `translateX(${(Math.random() - 0.5) * 0.6}px)`;
    }, 220);
  }

  // -----------------------------------------------------------
  // Boot
  // -----------------------------------------------------------
  setupPageReveal();
  run().then(ambientJitter);
})();
