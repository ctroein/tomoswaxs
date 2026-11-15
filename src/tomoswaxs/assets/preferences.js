/* Browser-local UI preferences. No appearance values enter shared Python state. */
(function initialise(workspace) {
  if (!workspace) {
    window.addEventListener('nim-workspace-ready',()=>initialise(window.nimWorkspace),{once:true});
    return;
  }
  const {validLayout}=workspace;
  const KEY = 'nim-uct-saxs.preferences.v1';
  const defaults = () => ({version:1, theme:'system', textScale:100,
                           rotationFps:20, rotationStep:1.5, showAxes:false, rememberLayout:false, layout:{height:66, width:50}});
  const clamp = (n, low, high, fallback) =>
    typeof n === 'number' && Number.isFinite(n) ? Math.min(high, Math.max(low,n)) : fallback;
  function normalise(raw) {
    const result = defaults();
    if (!raw || raw.version !== 1) return result;
    if (['system','light','dark'].includes(raw.theme)) result.theme = raw.theme;
    result.textScale = Math.round(clamp(raw.textScale,80,160,100)/5)*5;
    result.rotationFps = clamp(raw.rotationFps,1,60,20);
    result.rotationStep = clamp(raw.rotationStep,.1,180,1.5);
    result.rememberLayout = raw.rememberLayout === true;
    result.showAxes = raw.showAxes === true;
    if (result.rememberLayout) {
      if (validLayout(raw.layout)) result.layout = JSON.parse(JSON.stringify(raw.layout));
      else {
        result.layout.height = clamp(raw.layout?.height,35,78,66);
        result.layout.width = clamp(raw.layout?.width,25,75,50);
      }
    }
    return result;
  }
  function load(storage) {
    let raw;
    try { raw = storage.getItem(KEY); }
    catch { return {prefs:defaults(), unavailable:true}; }
    try { return {prefs:normalise(JSON.parse(raw)), unavailable:false}; }
    catch { return {prefs:defaults(), unavailable:false}; }
  }
  function save(storage, prefs) {
    try { storage.setItem(KEY,JSON.stringify(normalise(prefs))); return true; }
    catch { return false; }
  }
  const palette = theme => theme === 'dark'
    ? {bg:'#101722', fg:'#e1e7ef', grid:'#2a394c', line:'#67deeb'}
    : {bg:'#ffffff', fg:'#202e3d', grid:'#d7e0e9', line:'#087e91'};
  function plotLayout(layout,theme,scale) {
    const p = palette(theme), size = 12*scale/100;
    const axis = original => ({...original, color:p.fg, gridcolor:p.grid,
      zerolinecolor:p.grid, automargin:true, nticks:4,
      tickfont:{...original?.tickfont, color:p.fg, size},
      title:{...original?.title, font:{...original?.title?.font,color:p.fg,size:size*1.15}}});
    return {...layout, paper_bgcolor:p.bg, plot_bgcolor:p.bg,
      font:{...layout?.font, color:p.fg, size},
      xaxis:axis(layout?.xaxis), yaxis:axis(layout?.yaxis)};
  }
  function plotData(data,theme,scale) {
    const p = palette(theme), size = 12*scale/100;
    return data.map(trace => trace.type === 'scatter'
      ? {...trace,line:{...trace.line,color:p.line}}
      : {...trace,colorbar:{...trace.colorbar,nticks:3,
          tickfont:{color:p.fg,size},title:{...trace.colorbar?.title,font:{color:p.fg,size}}}});
  }
  // Dependency-free unit checks can import the persistence and styling layer.
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {KEY,defaults,normalise,load,save,plotLayout,plotData};
    return;
  }
  window.nimPreferences = {plotLayout,plotData,
    getLayout:()=>prefs.layout,
    updateLayout(layout) {
      if (!prefs.rememberLayout || !validLayout(layout)) return;
      prefs.layout=layout; clearTimeout(saveTimer);saveTimer=setTimeout(persist,150);
    },
  };
  let storage;
  try { storage = window.localStorage; } catch { /* storage may be disabled */ }
  let {prefs, unavailable} = load(storage);
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  const state = window.trame.state;
  let dialog, saveTimer = null;

  function updateNotice() {
    if (dialog) dialog.querySelector('[data-storage-notice]').textContent = unavailable
      ? 'Changes apply now, but browser storage is unavailable.'
      : 'Preferences saved in this browser.';
  }
  function persist() {
    unavailable = !save(storage,prefs);
    updateNotice();
  }
  function restoreLayout() { window.nimWorkspace.restore(prefs.layout); }
  function syncControls() {
    if (!dialog) return;
    dialog.querySelector('#pref-theme').value = prefs.theme;
    dialog.querySelector('#pref-scale').value = prefs.textScale;
    dialog.querySelector('#pref-scale-value').value = `${prefs.textScale}%`;
    dialog.querySelector('#pref-layout').checked = prefs.rememberLayout;
    dialog.querySelector('#pref-axes').checked = prefs.showAxes;
    updateNotice();
  }
  function apply() {
    const theme = prefs.theme === 'system' ? (media.matches ? 'dark' : 'light') : prefs.theme;
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.fontSize = `${14*prefs.textScale/100}px`;
    syncControls();
    const {rotationFps,rotationStep}=prefs;
    state.set('rotation_fps',rotationFps);
    state.set('rotation_step',rotationStep);
    state.set('ui_theme',theme);
    state.set('ui_text_scale',prefs.textScale);
    window.trame.trigger('nim_axes_visibility',[prefs.showAxes]).catch(console.error);
    // Plotly and the remote VTK view both observe their container dimensions.
    window.dispatchEvent(new Event('resize'));
  }
  function buildDialog() {
    dialog = document.createElement('dialog');
    dialog.className = 'settings-dialog';
    dialog.setAttribute('aria-labelledby','settings-title');
    dialog.innerHTML = `
      <form method="dialog">
        <h2 id="settings-title">Settings</h2>
        <label for="pref-theme">Appearance</label>
        <select id="pref-theme"><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select>
        <label for="pref-scale">Text size <output id="pref-scale-value" for="pref-scale">100%</output></label>
        <input id="pref-scale" type="range" min="80" max="160" step="5">
        <p class="settings-help">Scales controls and plot labels.</p>
        <label class="settings-check"><input id="pref-layout" type="checkbox"> Remember panel layout</label>
        <label class="settings-check"><input id="pref-axes" type="checkbox"> Show coordinate axes</label>
        <p class="settings-help" data-storage-notice></p>
        <div class="settings-actions"><button type="button" id="pref-reset">Reset preferences</button><button value="close">Close</button></div>
      </form>`;
    document.body.appendChild(dialog);
    dialog.addEventListener('input', event => {
      if (event.target.id === 'pref-theme') prefs.theme = event.target.value;
      if (event.target.id === 'pref-scale') prefs.textScale = Number(event.target.value);
      if (event.target.id === 'pref-axes') prefs.showAxes = event.target.checked;
      if (event.target.id === 'pref-layout') {
        prefs.rememberLayout = event.target.checked;
        if (!prefs.rememberLayout) prefs.layout = defaults().layout;
        // Capture the current dock arrangement even when the toggle is enabled
        // after a drag (no subsequent layout-change event is needed).
        if (prefs.rememberLayout && window.nimWorkspace.currentLayout) prefs.layout=window.nimWorkspace.currentLayout;
      }
      prefs = normalise(prefs);
      apply();
      persist();
    });
    dialog.querySelector('#pref-reset').addEventListener('click', () => {
      clearTimeout(saveTimer);
      prefs = defaults();
      restoreLayout();
      apply();
      persist();
    });
    syncControls();
  }
  state.addListener(({type,keys=[]}) => {
    if (type === 'dirty-state' && keys.some(key => key === 'rotation_fps' || key === 'rotation_step')) {
      const frequency=Number(state.get('rotation_fps')),step=Number(state.get('rotation_step'));
      if (Number.isFinite(frequency) && frequency >= 1 && frequency <= 60 &&
          Number.isFinite(step) && step >= .1 && step <= 180) {
        prefs.rotationFps=frequency; prefs.rotationStep=step;
        clearTimeout(saveTimer); saveTimer=setTimeout(persist,150);
      }
    }

  });
  window.addEventListener('pagehide', () => { if (prefs.rememberLayout) persist(); });
  media.addEventListener('change', () => { if (prefs.theme === 'system') apply(); });
  document.addEventListener('click', event => {
    if (!event.target.closest('#open-settings')) return;
    if (!dialog) buildDialog();
    syncControls();
    if (!dialog.open) dialog.showModal();
  });
  restoreLayout();
  apply();
  window.dispatchEvent(new Event('nim-preferences-ready'));
})(typeof module !== 'undefined' && module.exports ? require('./workspace.js') : window.nimWorkspace);
