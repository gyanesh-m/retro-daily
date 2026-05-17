/* ============================================================
   retro-daily landing page — terminal teletype

   Page narrative:
     1. user is at a project prompt
     2. types `claude`, hits enter
     3. Claude Code welcome screen renders (sprite + title + cwd)
     4. Input prompt placeholder appears
     5. SessionStart hook fires → retro-daily dashboard streams in
        line by line, viewport-gated: pauses when the next line would
        sit below the visible area; resumes when the user scrolls.
   ============================================================ */

(function () {
  'use strict';

  const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const sleep = (ms) => new Promise(r => setTimeout(r, REDUCED ? 0 : ms));

  // ----- "Today" computed at page-load so the demo never reads as stale.
  // Format mirrors what generate-metrics.py prints: e.g. "Sun May 17".
  const _now = new Date();
  const TODAY_LABEL = _now.toLocaleDateString('en-US', {
    weekday: 'short', month: 'short', day: '2-digit',
  }).replace(',', '');
  // Scout runs on a weekly cadence; show a recent-but-plausibly-aged run.
  const SCOUT_DATE = new Date(_now.getTime() - 2 * 86400000).toISOString().slice(0, 10);

  // ============================================================
  // Helpers
  // ============================================================

  const RULE_W = 68;
  const RULE   = '━'.repeat(RULE_W);

  // Inline color span helper. cls is a space-separated class list.
  const tag = (cls, s) => `<span class="${cls}">${s}</span>`;
  const dim    = (s) => tag('dim', s);
  const cyan   = (s) => tag('cyan', s);
  const white  = (s) => tag('white', s);
  const green  = (s) => tag('green', s);
  const yellow = (s) => tag('yellow', s);
  const red    = (s) => tag('red', s);
  const mag    = (s) => tag('magenta', s);
  const bold   = (s) => tag('bold', s);
  const head   = (s) => tag('head', s);
  const ruleC  = (s) => tag('rule', s);

  // Visible length (strip HTML tags)
  const vlen = (html) => html.replace(/<[^>]+>/g, '').length;
  // Pad to the right of a string (which may contain HTML)
  const pad = (s, w) => s + ' '.repeat(Math.max(0, w - vlen(s)));
  // Pad to the left
  const padL = (s, w) => ' '.repeat(Math.max(0, w - vlen(s))) + s;

  // Sparkline glyphs (1-8). value out of range clamps.
  const BLOCKS = '▁▂▃▄▅▆▇█';
  const spark = (vals) => vals.map(v => BLOCKS[Math.max(0, Math.min(7, v - 1))]).join('');

  // Gauge bar: width chars, `pct` 0-100. `sev` controls fill color class.
  function gauge(pct, width, sev) {
    const filled = Math.round(width * pct / 100);
    const fillCls = (sev === 'bad' ? 'gauge-bad' : sev === 'warn' ? 'gauge-warn' : 'gauge-fill');
    return tag(fillCls, '█'.repeat(filled)) + tag('gauge-empty', '░'.repeat(width - filled));
  }

  // Heatmap cell glyph (■) colored by level
  const heat = (lvl) => tag(`h${Math.max(0, Math.min(4, lvl))}`, '■');

  // Severity dot
  const sevDot = (sev) => tag(`sev-${sev}`, '⬤');

  // ============================================================
  // Data (matches the live SessionStart sample output)
  // ============================================================

  const META = {
    date: TODAY_LABEL,
    sessions: 1197, tools: 10626, days: 21, projects: 15, costAll: '$6436.49',
    tokens: { in: '239.0K', out: '10.6M', cacheRead: '1.82B', cacheWrite: '127.2M' },
    week: { sessions: 10, tools: 632, days: 3, projects: 4, cost: '$1040.15' },
    weekDelta: { sessions: -72, tools: -71, cost: -62 },
    weekBars: [
      { day: 'Tue', count: 0 },
      { day: 'Wed', count: 0 },
      { day: 'Thu', count: 1 },
      { day: 'Fri', count: 8 },
      { day: 'Sat', count: 0 },
      { day: 'Sun', count: 1 },
      { day: 'Mon', count: 0 },
    ],
    competency: { score: 62.1, grade: 'D' },
    breakdown: [
      { name: 'Edit/Read',    value: 100, sev: 'good' },
      { name: 'Auto-approve', value:  29, sev: 'bad'  },
      { name: 'First-try',    value: 100, sev: 'good' },
      { name: 'Corrections',  value:  50, sev: 'warn' },
      { name: 'Tool errors',  value:  28, sev: 'bad'  },
      { name: 'Ctx hygiene',  value:  67, sev: 'warn' },
    ],
    efficiency: [
      { name: 'Edit / Read',  value: '1.0',   bars: [4,2,1,3,2,3,2,5,4,8,4,8,4,1], d7: '→', d30: '↑', status: 'good' },
      { name: 'Auto-approve', value: '65.7%', bars: [7,6,1,7,3,6,6,4,6,8,7,8,8,2], d7: '↑', d30: '→', status: 'bad'  },
      { name: 'First-try',    value: '83.4%', bars: [7,8,8,7,7,8,8,8,7,7,8,7,8,1], d7: '↑', d30: '↑', status: 'good' },
      { name: 'Corrections',  value: '15.1%', bars: [7,4,3,4,8,2,1,2,1,1,3,1,1,1], d7: '↓', d30: '↓', status: 'bad',  invertGood: true },
      { name: 'Tool errors',  value: '10.2%', bars: [2,4,5,1,3,2,2,2,3,8,3,8,3,1], d7: '→', d30: '↓', status: 'bad',  invertGood: true },
      { name: 'Ctx hygiene',  value: '50.0%', bars: [1,1,1,1,1,1,1,1,1,2,2,2,8,8], d7: '↑', d30: '→', status: 'warn' },
    ],
    prompts: { approved: 475, fresh: 678, refined: 117, corrected: 112 },
    yesterday: { sessions: 1, tools: 2, cost: '$3.16', project: 'your-project', branch: 'main' },
    focus: [
      { sev: 'bad',  name: 'Auto-approve', value: '65.7%', warn: '70%', good: '80%',
        rec: 'Most tools need manual approval. Consider sandbox mode or add allowedTools' },
      { sev: 'bad',  name: 'Corrections',  value: '15.1%', warn: '15%', good: '5%',
        rec: 'High correction rate. Split complex prompts. Use /compact between focus changes.' },
      { sev: 'bad',  name: 'Tool errors',  value: '10.2%', warn: '8%',  good: '3%',
        rec: 'Many tool failures. Check CLAUDE.md for missing workflow instructions or stale paths.' },
      { sev: 'warn', name: 'Ctx hygiene',  value: '50.0%', warn: '40%', good: '70%',
        rec: 'Some long sessions run past 40 turns without /compact. Compact at task boundaries.' },
    ],
    scout: [
      { q: 'claude code sandbox permissions',
        actionable: 'Enable sandboxing in ~/.claude/settings.json so Bash auto-runs without prompts inside the sandbox; keep allow/denyWrite tight.',
        repo: 'PACHAKUTlQ/ClaudeCage',
        repoNote: 'Try ClaudeCage when you scout untrusted repos so you can keep auto-approve high.' },
      { q: 'claude code auto approve setup',
        actionable: "If on Team plan, run `claude --permission-mode auto` for this repo — your 65.7% auto-approve will jump.",
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
    ],
  };

  // ============================================================
  // Line generator — emits one HTML string per terminal line
  // ============================================================

  function lines() {
    const out = [];

    // --- Top header --------------------------------------------------------
    const titleLeft = head('R E T R O  ·  D A I L Y');
    const titleRight = dim(META.date);
    out.push(pad(titleLeft, RULE_W - vlen(titleRight)) + titleRight);
    out.push(ruleC(RULE));
    out.push('');

    // --- ALL-TIME ----------------------------------------------------------
    out.push(head('A L L - T I M E'));
    out.push(ruleC(RULE));
    out.push(`   ${white(bold(META.sessions))} ${dim('sessions')}  ${white(bold(META.tools))} ${dim('tools')}  ${white(bold(META.days))} ${dim('days')}  ${white(bold(META.projects))} ${dim('projects')}   ${green(META.costAll)}${dim(' est.')}`);
    out.push(`  ${dim('API-equivalent estimate · not your actual bill if on a Claude subscription')}`);
    out.push(`  ${dim('tokens')}  ${white(META.tokens.in)} ${dim('in')}  ${white(META.tokens.out)} ${dim('out')}  ${white(META.tokens.cacheRead)} ${dim('cache-read')}  ${white(META.tokens.cacheWrite)} ${dim('cache-write')}`);
    out.push('');

    // --- LAST 7 DAYS -------------------------------------------------------
    const wd = META.weekDelta;
    const arr = (n) => (n < 0 ? '↓' : '↑') + Math.abs(n) + '%';
    out.push(head('L A S T   7   D A Y S'));
    out.push(ruleC(RULE));
    const w = META.week;
    out.push(`   ${white(bold(w.sessions))} ${dim('sessions')}  ${white(bold(w.tools))} ${dim('tools')}  ${white(bold(w.days))} ${dim('days')}  ${white(bold(w.projects))} ${dim('projects')}   ${green(w.cost)}${dim(' est.')}`);
    out.push(`  ${dim('vs prior 7d')}  ${dim('sessions')} ${red(arr(wd.sessions))}  ${dim('tools')} ${red(arr(wd.tools))}  ${dim('cost')} ${red(arr(wd.cost))}`);
    out.push('');

    // Week bar chart (3 lines: labels, bars, counts)
    const dayLabel  = META.weekBars.map(d => dim(' ' + d.day + ' ')).join(' ');
    const dayBar    = META.weekBars.map(d => {
      const lvl = d.count === 0 ? 0 : d.count <= 1 ? 1 : d.count <= 3 ? 2 : d.count <= 6 ? 3 : 4;
      return tag(`h${lvl}`, '████');
    }).join(' ');
    const dayCount  = META.weekBars.map(d => {
      const t = d.count === 0 ? dim(' ' + d.count + '  ') : white(bold(' ' + d.count + '  '));
      return t;
    }).join(' ');
    out.push('  ' + dayLabel);
    out.push('  ' + dayBar);
    out.push('  ' + dayCount);
    out.push('');

    // --- COMPETENCY --------------------------------------------------------
    out.push(head('C O M P E T E N C Y'));
    out.push(ruleC(RULE));
    const score = META.competency.score;
    out.push(`  ${gauge(score, 30, 'warn')}  ${white(bold(score.toFixed(1)))}${dim('/100')}   ${yellow(bold(META.competency.grade))}`);

    // breakdown chips, all on one line, dim labels + colored numbers
    const colorBy = (sev, n) => sev === 'good' ? green(n) : sev === 'warn' ? yellow(n) : red(bold(n));
    const chips = META.breakdown.map(b => `${dim(b.name)} ${colorBy(b.sev, b.value)}`).join('  ');
    out.push(`  ${dim('breakdown   ')}${chips}`);
    out.push('');

    // --- EFFICIENCY --------------------------------------------------------
    out.push(head('E F F I C I E N C Y'));
    out.push(ruleC(RULE));
    out.push(`  ${dim('metric            value   14-day trend     7d   30d   status')}`);
    // Color each arrow based on whether its direction is good for THIS metric.
    // For invertGood metrics (lower is better), down=good. Otherwise up=good.
    // Flat arrows render as dim — neither good nor bad.
    const arrowColor = (m, arrow) => {
      if (arrow === '→' || arrow === '·') return 'dim';
      const up = arrow === '↑';
      const good = m.invertGood ? !up : up;
      return good ? 'green' : 'red';
    };
    for (const m of META.efficiency) {
      const name  = pad(white(m.name), 18);
      const value = padL(white(bold(m.value)), 6);
      const sp    = cyan(spark(m.bars));
      const d7  = tag(arrowColor(m, m.d7),  m.d7);
      const d30 = tag(arrowColor(m, m.d30), m.d30);
      const dot = sevDot(m.status);
      const lbl = tag(`sev-${m.status}`, m.status);
      out.push(`  ${name}${value}   ${sp}   ${d7}    ${d30}     ${dot} ${dim(lbl)}`);
    }
    out.push('');
    const p = META.prompts;
    out.push(`  ${dim('prompts:')} ${green(p.approved + ' approved')}${dim(' · ')}${cyan(p.fresh + ' new')}${dim(' · ')}${yellow(p.refined + ' refined')}${dim(' · ')}${mag(p.corrected + ' corrected')}`);
    out.push('');

    // --- CONTRIBUTIONS -----------------------------------------------------
    out.push(head('C O N T R I B U T I O N S'));
    out.push(ruleC(RULE));
    // Month label row
    out.push('      ' + dim('May Jun  Jul Aug  Sep Oct Nov  Dec Jan Feb Mar  Apr  '));
    const heatRows = buildHeatmap();
    const dayLabels = ['   ', 'Mon', '   ', 'Wed', '   ', 'Fri', '   '];
    for (let r = 0; r < 7; r++) {
      const label = dim(dayLabels[r]);
      const row = heatRows[r].map(lvl => heat(lvl)).join('');
      out.push('  ' + label + ' ' + row);
    }
    out.push('');
    const legend = `${tag('h0', '■')}${tag('h1', '■')}${tag('h2', '■')}${tag('h3', '■')}${tag('h4', '■')}`;
    out.push(`  ${dim('less')} ${legend} ${dim('more')}   ${white(bold('1197'))}${dim(' sessions across ')}${white(bold('21'))}${dim(' days this year')}`);
    out.push('');

    // --- YESTERDAY ---------------------------------------------------------
    out.push(head('Y E S T E R D A Y'));
    out.push(ruleC(RULE));
    const y = META.yesterday;
    out.push(`  ${white(bold(y.sessions))} ${dim('sessions')}   ${white(bold(y.tools))} ${dim('tools')}  ${green(y.cost)}${dim(' est.')}  ${dim('[' + y.project + ']')}`);
    out.push(`  ${dim('branches ' + y.branch)}`);
    out.push('');

    // --- FOCUS AREAS -------------------------------------------------------
    out.push(head('F O C U S   A R E A S'));
    out.push(ruleC(RULE));
    for (const f of META.focus) {
      const pct = parseFloat(f.value);
      const fillCls = f.sev === 'bad' ? 'gauge-bad' : 'gauge-warn';
      const filled = Math.round(18 * Math.min(100, pct) / 100);
      const bar = tag(fillCls, '█'.repeat(filled)) + tag('gauge-empty', '░'.repeat(18 - filled));
      const sevTag = f.sev === 'bad' ? red(bold('BAD ')) : yellow(bold('WARN'));
      const line1 = `  ${sevDot(f.sev)} ${sevTag} ${pad(white(f.name), 14)}${bar} ${white(bold(f.value))}   ${dim('warn ' + f.warn + ' · good ' + f.good)}`;
      out.push(line1);
      out.push(`      ${green('→')} ${dim(f.rec)}`);
    }
    out.push('');
    out.push(`  ${dim('scout queued · last run ' + SCOUT_DATE)}`);
    out.push('');

    // --- SCOUT FINDINGS ----------------------------------------------------
    out.push(head('S C O U T   F I N D I N G S'));
    out.push(ruleC(RULE));
    out.push(`  ${dim('6 queries · ' + SCOUT_DATE + ' · full detail: ' + dim('~/.claude/metrics/scout-results.json'))}`);
    out.push('');
    for (const s of META.scout) {
      out.push(`  ${yellow('●')} ${white(bold(s.q))}`);
      out.push(`      ${green('→')} ${dim(s.actionable)}`);
      out.push(`      ${dim('★ ')}${white(s.repo)}${dim(' · ' + s.repoNote)}`);
      out.push('');
    }
    out.push(dim('─'.repeat(RULE_W)));
    out.push('');

    return out;
  }

  // Build a deterministic 7×53 heatmap (rows = days, cols = weeks)
  function buildHeatmap() {
    const WEEKS = 53;
    const seed = 42;
    const prng = (x) => ((Math.sin(x * 12.9898) * 43758.5453) % 1 + 1) % 1;
    const rows = Array.from({ length: 7 }, () => new Array(WEEKS).fill(0));
    for (let w = 0; w < WEEKS; w++) {
      for (let d = 0; d < 7; d++) {
        const r = prng(seed + w * 7 + d);
        let lvl = 0;
        if (r > 0.985) lvl = 4;
        else if (r > 0.97) lvl = 3;
        else if (r > 0.95) lvl = 2;
        else if (r > 0.92) lvl = 1;
        if (w > WEEKS - 6 && r > 0.55) lvl = Math.max(lvl, Math.round((r - 0.55) * 8));
        rows[d][w] = Math.min(4, lvl);
      }
    }
    return rows;
  }

  // ============================================================
  // Progressive printer
  // ============================================================

  const ALL_LINES = lines();
  const stream    = document.getElementById('stream');
  const sentinel  = document.getElementById('print-sentinel');
  const caretLine = document.querySelector('.caret-line');

  // Hide the trailing caret until the first dashboard line prints
  if (caretLine) caretLine.style.opacity = '0';

  let nextIdx = 0;
  let printing = false;
  let started  = false;

  function nearViewport() {
    const r = sentinel.getBoundingClientRect();
    // Print more if the sentinel is in/near the visible viewport.
    // 240px buffer means we print a few lines below the fold so the user
    // sees content arriving as they scroll.
    return r.top < window.innerHeight + 240;
  }

  async function pump() {
    if (!started || printing) return;
    printing = true;
    while (nextIdx < ALL_LINES.length && nearViewport()) {
      const line = document.createElement('div');
      line.className = 'dline';
      line.innerHTML = ALL_LINES[nextIdx] || '&nbsp;';
      // Insert before the sentinel so the sentinel stays at the bottom
      stream.appendChild(line);
      nextIdx++;
      await sleep(REDUCED ? 0 : 14);
    }
    if (nextIdx >= ALL_LINES.length && caretLine) {
      caretLine.style.transition = 'opacity 0.3s';
      caretLine.style.opacity = '1';
    }
    printing = false;
  }

  // Boot the printer once the welcome sequence finishes
  function startStream() {
    started = true;
    pump();
  }

  // Scroll + resize re-pump
  window.addEventListener('scroll',  pump, { passive: true });
  window.addEventListener('resize',  pump, { passive: true });

  // Safety pump: in case scroll never fires (e.g. headless capture), keep
  // poking the pump every 600ms. Cheap — `pump` exits fast when sentinel
  // is below the viewport.
  setInterval(pump, 600);

  // ============================================================
  // Welcome sequence (terminal opening)
  // ============================================================

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

  async function run() {
    const typedCmd  = document.getElementById('typed-cmd');
    const welcome   = document.getElementById('welcome');
    const inputLine = document.getElementById('input-line');
    const divider   = document.getElementById('divider');
    const hookOut   = document.getElementById('hook-output');

    await sleep(550);
    await typeInto(typedCmd, 'claude');
    await sleep(280);

    // Hide the typing cursor (the welcome appears below)
    const pc = document.querySelector('.prompt-line .cmd-cursor');
    if (pc) pc.style.display = 'none';
    await sleep(180);

    welcome.classList.add('ready');
    await sleep(REDUCED ? 0 : 380);
    inputLine.classList.add('ready');
    await sleep(REDUCED ? 0 : 220);
    divider.classList.add('ready');
    hookOut.classList.add('ready');
    await sleep(REDUCED ? 0 : 120);

    // SessionStart hook begins printing
    startStream();
  }

  // ============================================================
  // Status-bar clock (matches Claude Code's bottom bar)
  // ============================================================

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

  // ============================================================
  // Page-level reveal-on-scroll for the sections under the terminal
  // ============================================================

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
    setTimeout(() => targets.forEach((el) => el.classList.add('in-view')), 1500);
  }

  // ============================================================
  // "Press any key to continue" easter egg
  //
  // Pressing any key (or clicking/tapping the prompt) pulses the
  // install instructions block — codeblocks + their captions, but
  // not the CTA buttons. Capped at 5 fires per page load so a
  // held-down key doesn't strobe forever.
  // ============================================================

  function setupEasterEgg() {
    const trigger = document.getElementById('press-any-key');
    const target  = document.getElementById('install-body');
    if (!trigger || !target) return;

    const MAX_FIRES = 5;
    let fires = 0;
    let removeTimer = null;

    const pulse = () => {
      if (fires >= MAX_FIRES) return;
      fires++;
      target.classList.remove('flash');
      // eslint-disable-next-line no-void
      void target.offsetWidth;
      target.classList.add('flash');
      if (removeTimer) window.clearTimeout(removeTimer);
      removeTimer = window.setTimeout(() => {
        target.classList.remove('flash');
        removeTimer = null;
      }, 1800);
    };

    window.addEventListener('keydown', (ev) => {
      if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
      if (ev.target && /^(input|textarea|select)$/i.test(ev.target.tagName)) return;
      pulse();
    });

    trigger.addEventListener('click', pulse);
    trigger.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pulse(); }
    });
  }

  setupPageReveal();
  setupEasterEgg();
  run();
})();
