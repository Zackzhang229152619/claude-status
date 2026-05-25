/* ==========================================================
   Claude Status — shared data layer for all design variants.
   Each variant subscribes via StatusCommon.init({...callbacks}).
   ========================================================== */
(function () {
  const DAYS = ['星期日','星期一','星期二','星期三','星期四','星期五','星期六'];
  const pad2 = n => String(n).padStart(2, '0');

  // ───── formatters ─────────────────────────────────────────
  const fmtTime = d => `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
  const fmtTimeHM = d => `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  const fmtDate = d => `${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())} ${DAYS[d.getDay()]}`;

  function timeAgo(iso) {
    if (!iso) return '';
    const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
    if (diff < 5)    return '刚刚';
    if (diff < 60)   return diff + 's';
    if (diff < 3600) return Math.floor(diff/60) + 'm';
    if (diff < 86400) return Math.floor(diff/3600) + 'h';
    return Math.floor(diff/86400) + 'd';
  }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  }

  function fmtTokens(n) {
    if (n === undefined || n === null) return '—';
    if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return String(n);
  }

  function hitRate(bucket) {
    if (!bucket) return null;
    const denom = (bucket.input || 0) + (bucket.cache_read || 0);
    if (!denom) return null;
    return Math.round((bucket.cache_read || 0) / denom * 100);
  }

  // ───── state constants ─────────────────────────────────────
  const STATE_LABEL = {
    idle: '空闲', thinking: '思考中', working: '工作中',
    needConfirm: '等你拍板', done: '完成'
  };
  const STATE_PRIORITY = { needConfirm: 0, working: 1, thinking: 2, done: 3, idle: 4 };

  function sortSessions(arr) {
    return [...arr].sort((a, b) => {
      const pa = STATE_PRIORITY[a.state] ?? 5;
      const pb = STATE_PRIORITY[b.state] ?? 5;
      if (pa !== pb) return pa - pb;
      return new Date(b.updated_at || 0) - new Date(a.updated_at || 0);
    });
  }

  // ───── demo fixtures ───────────────────────────────────────
  const NOW = () => Date.now();
  function ago(ms) { return new Date(NOW() - ms).toISOString(); }

  const DETAILS = [
    { id: '3177462e-aaaa', project: 'artist-dashboard',  current_tool: 'Edit',     current_target: 'src/components/Dashboard.tsx', last_prompt: '把 M3 算法里的 INNER JOIN 改成加和逻辑' },
    { id: '5fdd120d-bbbb', project: 'claude-code',       current_tool: 'Read',     current_target: 'server.py',                     last_prompt: '检查 server 启动逻辑有没有 race condition' },
    { id: '8a91c2e0-cccc', project: 'status-light-pack', current_tool: 'Write',    current_target: 'dashboard.html',                last_prompt: '把 dashboard 重做一下，要 fancy 一点' },
    { id: '12abef34-dddd', project: 'sketches',          current_tool: null,       current_target: null,                            last_prompt: null },
    { id: 'cd45ef67-eeee', project: 'design-notes',      current_tool: null,       current_target: null,                            last_prompt: null },
    { id: 'a7b3c1d5-ffff', project: 'fan-insights',      current_tool: 'Bash',     current_target: 'pnpm test --watch',             last_prompt: '跑一下测试看看修复有没有问题' }
  ];

  function fixtureFor(mode) {
    if (mode === 'empty') return { global_state: 'idle', sessions: [] };
    if (mode === 'idle')  return {
      global_state: 'idle',
      sessions: [
        { id: '12abef34-dddd', state: 'idle', project: 'sketches',     updated_at: ago(1_800_000) },
        { id: 'cd45ef67-eeee', state: 'idle', project: 'design-notes', updated_at: ago(3_600_000) }
      ]
    };
    if (mode === 'thinking') return {
      global_state: 'thinking',
      sessions: [
        { id: '5fdd120d-bbbb', state: 'thinking', project: 'claude-code',       updated_at: ago(3_000) },
        { id: '8a91c2e0-cccc', state: 'done',     project: 'status-light-pack', updated_at: ago(300_000) }
      ]
    };
    if (mode === 'done') return {
      global_state: 'done',
      sessions: [
        { id: '3177462e-aaaa', state: 'done', project: 'artist-dashboard',  updated_at: ago(12_000) },
        { id: '8a91c2e0-cccc', state: 'done', project: 'status-light-pack', updated_at: ago(90_000) }
      ]
    };
    if (mode === 'needConfirm') return {
      global_state: 'needConfirm',
      sessions: [
        { id: '3177462e-aaaa', state: 'needConfirm', project: 'artist-dashboard', updated_at: ago(2_000) },
        { id: '5fdd120d-bbbb', state: 'working',     project: 'claude-code',      updated_at: ago(15_000) }
      ]
    };
    // working (default)
    return {
      global_state: 'working',
      sessions: [
        { id: '3177462e-aaaa', state: 'working',  project: 'artist-dashboard',  updated_at: ago(25_000) },
        { id: '5fdd120d-bbbb', state: 'thinking', project: 'claude-code',       updated_at: ago(8_000) },
        { id: 'a7b3c1d5-ffff', state: 'working',  project: 'fan-insights',      updated_at: ago(45_000) },
        { id: '8a91c2e0-cccc', state: 'done',     project: 'status-light-pack', updated_at: ago(300_000) },
        { id: '12abef34-dddd', state: 'idle',     project: 'sketches',          updated_at: ago(1_800_000) }
      ]
    };
  }

  const TOKEN_FIXTURE = {
    today: { input: 1_234_567,   output: 89_012,    cache_read: 4_500_000 },
    month: { input: 23_456_789,  output: 1_890_123, cache_read: 95_000_000 },
    total: { input: 234_567_890, output: 18_901_234, cache_read: 980_000_000 }
  };

  // ───── init / subscribe ────────────────────────────────────
  // opts: { onState({global_state, sessions}, detailList), onTokens(data), onError(bool) }
  function init(opts = {}) {
    const params = new URLSearchParams(location.search);
    const demoMode = params.get('demo');
    let current = null, detail = null;

    function pushState() {
      if (!current) return;
      opts.onState && opts.onState(current, detail);
    }

    // Wake lock
    (async () => {
      if ('wakeLock' in navigator) {
        try { await navigator.wakeLock.request('screen'); } catch (e) {}
      }
    })();

    // Demo mode — inject fixture & exit (no polling)
    if (demoMode) {
      if (demoMode === 'error') {
        opts.onError && opts.onError(true);
        return;
      }
      current = fixtureFor(demoMode);
      detail  = DETAILS;
      const tok = { ...TOKEN_FIXTURE, last_updated: new Date().toISOString() };
      opts.onTokens && opts.onTokens(tok);
      pushState();
      return;
    }

    // Live polling
    // Relative-path fetch so the URL resolves correctly both:
    //   - local:  http://claude.local:8765/current.json
    //   - cloud:  https://artist.xn--fiqs8s/claude/state/current.json
    // When running inside an iframe (srcdoc), use parent origin + path prefix.
    function getApiBase() {
      try {
        if (window.parent && window.parent !== window) {
          const po = window.parent.location.origin;
          const pp = window.parent.location.pathname.replace(/\/[^/]*$/, '');
          if (po && po !== 'null') return po + (pp && pp !== '/' ? pp : '');
        }
      } catch (e) {}
      // Direct navigation: use the current page's directory as base
      let base = window.location.href.replace(/\/[^/]*(\?.*)?$/, '');
      // If we're under /variants/ subdirectory (direct access fallback), strip it —
      // current.json / sessions_detail.json / token_stats.json live one level up.
      base = base.replace(/\/variants$/, '');
      return base;
    }
    const API_BASE = getApiBase();

    let errCount = 0;

    async function fetchCurrent() {
      try {
        const res = await fetch(API_BASE + '/current.json?_=' + Date.now(), { cache: 'no-store' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        current = await res.json();
        errCount = 0;
        opts.onError && opts.onError(false);
        pushState();
      } catch (e) {
        if (++errCount >= 3) opts.onError && opts.onError(true);
      }
    }
    async function fetchDetail() {
      try {
        const res = await fetch(API_BASE + '/sessions_detail.json?_=' + Date.now(), { cache: 'no-store' });
        if (!res.ok) return;
        detail = await res.json();
        pushState();
      } catch (e) {}
    }
    async function fetchTokens() {
      try {
        const res = await fetch(API_BASE + '/token_stats.json?_=' + Date.now(), { cache: 'no-store' });
        if (!res.ok) return;
        opts.onTokens && opts.onTokens(await res.json());
      } catch (e) {}
    }

    fetchCurrent(); fetchDetail(); fetchTokens();
    setInterval(fetchCurrent, 1000);
    setInterval(fetchDetail,  1000);
    setInterval(fetchTokens,  5000);

    // (file:// fallback removed — caused mock data injection in iframe srcdoc context)
  }

  // ───── export ──────────────────────────────────────────────
  window.StatusCommon = {
    pad2, fmtTime, fmtTimeHM, fmtDate, timeAgo, esc,
    fmtTokens, hitRate, sortSessions,
    STATE_LABEL, STATE_PRIORITY,
    init
  };

  /* ============================================================
     Responsive helpers — body data-attr drives theme CSS
     ============================================================ */
  function applyFormFactor() {
    const w = window.innerWidth, h = window.innerHeight;
    const minD = Math.min(w, h), maxD = Math.max(w, h);
    const portrait = h > w;
    // size class
    let size = 'desktop';
    if (minD < 480)        size = 'phone';
    else if (minD < 720)   size = 'tablet-sm';
    else if (minD < 1100)  size = 'tablet';
    else if (maxD > 2400)  size = 'desktop-xl';
    document.body.dataset.size = size;
    document.body.dataset.orient = portrait ? 'portrait' : 'landscape';
    document.body.style.setProperty('--vw', w + 'px');
    document.body.style.setProperty('--vh', h + 'px');
  }
  window.addEventListener('resize', applyFormFactor);
  window.addEventListener('orientationchange', () => setTimeout(applyFormFactor, 100));
  document.addEventListener('DOMContentLoaded', applyFormFactor);
  applyFormFactor();

  /* ============================================================
     Theme picker — top-right floating button + sheet
     ============================================================ */
  // ?demo=... uses URL navigation; ?theme is just a default override
  const ALL_THEMES = [
    { id: 'aurora',   name: 'Aurora',     desc: '极光环境屏',  swatch: 'radial-gradient(circle at 30% 30%, #6a3bd6, #1e2e8a 60%, #061229)' },
    { id: 'press',    name: 'Press',      desc: '编辑部大屏',  swatch: 'linear-gradient(135deg, #f3eee4 0%, #f3eee4 60%, #15110b 60%)' },
    { id: 'glass',    name: 'Glass',      desc: '玻璃浮层',    swatch: 'linear-gradient(135deg, #4a5878 0%, #283454 50%, #050610 100%)' },
    { id: 'garden',   name: 'Garden',     desc: '信息花园',    swatch: 'linear-gradient(180deg, #0a1820 0%, #1f3024 60%, #4a6a52 100%)' },
    { id: 'lab',      name: 'Lab',        desc: '物理实验台',  swatch: 'linear-gradient(135deg, #e8e6e0 0%, #d8d5cc 60%, #ef8537 100%)' },
    { id: 'jarvis',   name: 'Iron Man',   desc: 'J.A.R.V.I.S 战衣 HUD',  swatch: 'radial-gradient(circle at 50% 50%, #29c6ff 0%, #ff3a3a 50%, #0a0306 100%)' },
    { id: 'stage',    name: 'Stage',      desc: '演出现场聚光灯',swatch: 'radial-gradient(circle at 50% 0%, #ff4ab8 0%, #6a18ff 40%, #0a0218 100%)' }
  ];

  function getCurrentThemeId() {
    // assume file is named "<theme>.html"
    const f = (location.pathname.split('/').pop() || '').replace('.html','');
    return f || 'aurora';
  }
  function gotoTheme(id) {
    if (!id || id === getCurrentThemeId()) { hidePicker(); return; }
    try { localStorage.setItem('claude-status-theme', id); } catch(e) {}
    const search = location.search; // preserve ?demo=...
    location.href = id + '.html' + search;
  }

  let pickerOpen = false;
  function ensurePicker() {
    if (document.getElementById('__sc-picker')) return;

    const css = `
      #__sc-pick-btn {
        position: fixed; top: 14px; right: 14px;
        width: 44px; height: 44px; border-radius: 50%;
        background: rgba(20,20,28,0.75);
        backdrop-filter: blur(20px) saturate(160%);
        border: 1px solid rgba(255,255,255,0.18);
        color: #fff;
        display: flex; align-items: center; justify-content: center;
        cursor: pointer;
        z-index: 9000;
        box-shadow: 0 6px 20px rgba(0,0,0,0.35);
        transition: transform 0.2s, background 0.2s;
        -webkit-tap-highlight-color: transparent;
        font-size: 0;
      }
      #__sc-pick-btn:hover { transform: scale(1.05); }
      #__sc-pick-btn:active { transform: scale(0.96); }
      #__sc-pick-btn svg { width: 22px; height: 22px; }
      body[data-size="phone"] #__sc-pick-btn { width: 38px; height: 38px; top: 10px; right: 10px; }
      body[data-size="desktop-xl"] #__sc-pick-btn { width: 52px; height: 52px; top: 22px; right: 22px; }

      #__sc-picker {
        position: fixed; inset: 0;
        z-index: 9001;
        background: rgba(0,0,0,0.55);
        backdrop-filter: blur(8px);
        display: none;
        align-items: center; justify-content: center;
        padding: 24px;
      }
      #__sc-picker.visible { display: flex; animation: __sc-fade 0.2s ease; }
      @keyframes __sc-fade { from { opacity: 0; } to { opacity: 1; } }

      .__sc-sheet {
        max-width: min(560px, 92vw);
        max-height: 86vh;
        overflow: auto;
        background: rgba(22,24,32,0.96);
        backdrop-filter: blur(40px) saturate(180%);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 24px;
        padding: clamp(18px, 2vw, 28px);
        color: #fff;
        font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
        box-shadow: 0 30px 80px rgba(0,0,0,0.55);
        animation: __sc-pop 0.25s cubic-bezier(0.2,1.5,0.4,1);
      }
      @keyframes __sc-pop {
        from { opacity: 0; transform: translateY(20px) scale(0.95); }
        to   { opacity: 1; transform: none; }
      }
      .__sc-head {
        display: flex; align-items: baseline; justify-content: space-between;
        margin-bottom: 14px;
        padding-bottom: 12px;
        border-bottom: 1px solid rgba(255,255,255,0.08);
      }
      .__sc-title {
        font-size: 17px;
        font-weight: 600;
        letter-spacing: -0.01em;
      }
      .__sc-sub {
        font-size: 11px;
        color: rgba(255,255,255,0.5);
        font-family: ui-monospace, "JetBrains Mono", Menlo, monospace;
        letter-spacing: 0.1em;
        text-transform: uppercase;
      }

      .__sc-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
        gap: 10px;
      }
      .__sc-card {
        position: relative;
        padding: 10px;
        border-radius: 14px;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.06);
        cursor: pointer;
        transition: transform 0.15s, background 0.15s, border-color 0.15s;
        -webkit-tap-highlight-color: transparent;
        text-align: left;
      }
      .__sc-card:hover { background: rgba(255,255,255,0.10); transform: translateY(-2px); border-color: rgba(255,255,255,0.18); }
      .__sc-card.active { border-color: #6cf; background: rgba(80,180,255,0.10); }
      .__sc-card.active::after {
        content: '✓';
        position: absolute;
        top: 8px; right: 10px;
        color: #6cf;
        font-size: 13px;
        font-weight: 700;
      }
      .__sc-swatch {
        width: 100%; aspect-ratio: 16 / 9;
        border-radius: 8px;
        margin-bottom: 8px;
        position: relative;
        overflow: hidden;
        box-shadow: inset 0 0 0 1px rgba(255,255,255,0.08);
      }
      .__sc-name {
        font-size: 13px;
        font-weight: 600;
      }
      .__sc-desc {
        font-size: 10px;
        color: rgba(255,255,255,0.55);
        margin-top: 2px;
        letter-spacing: 0.02em;
      }

      .__sc-close {
        margin-top: 14px;
        width: 100%;
        padding: 10px;
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 10px;
        color: rgba(255,255,255,0.8);
        font: inherit; font-size: 12px;
        cursor: pointer;
        letter-spacing: 0.05em;
      }
      .__sc-close:hover { background: rgba(255,255,255,0.10); color: #fff; }
    `;

    const style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);

    const btn = document.createElement('button');
    btn.id = '__sc-pick-btn';
    btn.setAttribute('aria-label', 'Switch theme');
    btn.title = '切换主题';
    btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="3.2"/>
      <circle cx="12" cy="12" r="9"/>
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>
    </svg>`;
    btn.addEventListener('click', togglePicker);
    document.body.appendChild(btn);

    const sheet = document.createElement('div');
    sheet.id = '__sc-picker';
    sheet.innerHTML = `
      <div class="__sc-sheet">
        <div class="__sc-head">
          <div class="__sc-title">切换主题</div>
          <div class="__sc-sub">${ALL_THEMES.length} themes</div>
        </div>
        <div class="__sc-grid">
          ${ALL_THEMES.map(t => `
            <button class="__sc-card ${t.id === getCurrentThemeId() ? 'active' : ''}" data-theme="${t.id}">
              <div class="__sc-swatch" style="background: ${t.swatch}"></div>
              <div class="__sc-name">${t.name}</div>
              <div class="__sc-desc">${t.desc}</div>
            </button>
          `).join('')}
        </div>
        <button class="__sc-close">关闭</button>
      </div>
    `;
    sheet.addEventListener('click', (e) => {
      if (e.target === sheet) hidePicker();
      const card = e.target.closest('.__sc-card');
      if (card) gotoTheme(card.dataset.theme);
      if (e.target.classList.contains('__sc-close')) hidePicker();
    });
    document.body.appendChild(sheet);

    // Esc to close
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && pickerOpen) hidePicker();
    });
  }
  function togglePicker() { pickerOpen ? hidePicker() : showPicker(); }
  function showPicker() {
    ensurePicker();
    document.getElementById('__sc-picker').classList.add('visible');
    pickerOpen = true;
  }
  function hidePicker() {
    const el = document.getElementById('__sc-picker');
    if (el) el.classList.remove('visible');
    pickerOpen = false;
  }
  // Install picker once DOM is ready  (skip when running inside an iframe —
  // the bundled dashboard's parent has its own picker)
  const _inIframe = (() => { try { return window.self !== window.top; } catch (e) { return true; } })();
  if (!_inIframe) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', ensurePicker);
    } else {
      ensurePicker();
    }
  }
  window.StatusCommon.showPicker = showPicker;
  window.StatusCommon.themes = ALL_THEMES;
})();
