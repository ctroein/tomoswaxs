/* Browser-local UI preferences. No appearance values enter shared Python state. */
(function initialise(workspace) {
  if (!workspace) {
    window.addEventListener('nim-workspace-ready',()=>initialise(window.nimWorkspace),{once:true});
    return;
  }
  const {validLayout}=workspace;
  const KEY = 'nim-uct-saxs.preferences.v1';
  const defaults = () => ({version:1, theme:'system', textScale:100, plotScale:100,
                           rotationFps:20, rotationStep:1.5, voxelArrayMib:null, showAxes:false, rememberLayout:false, layout:{height:66, width:50}});
  const clamp = (n, low, high, fallback) =>
    typeof n === 'number' && Number.isFinite(n) ? Math.min(high, Math.max(low,n)) : fallback;
  function normalise(raw) {
    const result = defaults();
    if (!raw || raw.version !== 1) return result;
    if (['system','light','dark'].includes(raw.theme)) result.theme = raw.theme;
    result.textScale = Math.round(clamp(raw.textScale,80,160,100)/5)*5;
    result.plotScale = Math.round(clamp(raw.plotScale,50,200,100));
    result.rotationFps = clamp(raw.rotationFps,1,60,20);
    result.rotationStep = clamp(raw.rotationStep,.1,180,1.5);
    if (typeof raw.voxelArrayMib === 'number' && Number.isFinite(raw.voxelArrayMib) && raw.voxelArrayMib >= 1) result.voxelArrayMib = raw.voxelArrayMib;
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
  const hoverArrays=new WeakMap();
  function heatmapHoverData(encoded) {
    if (!encoded?.bdata || !encoded.shape) return encoded;
    const cached=hoverArrays.get(encoded);
    if (cached && cached.bdata===encoded.bdata && cached.dtype===encoded.dtype && cached.shape===encoded.shape) return cached.rows;
    const shape=String(encoded.shape).split(',').map(Number);
    const Type={f8:Float64Array,f4:Float32Array,i4:Int32Array,u4:Uint32Array,
      i2:Int16Array,u2:Uint16Array,i1:Int8Array,u1:Uint8Array}[encoded.dtype];
    if (!Type || shape.length!==2 || !shape.every(n=>Number.isInteger(n) && n>=0)) return encoded;
    // The bundled heatmap hover code requires ordinary nested arrays.
    // Adapt once in the browser while retaining binary NumPy transport.
    const bytes=Uint8Array.from(atob(encoded.bdata),c=>c.charCodeAt(0));
    if (bytes.byteLength!==shape[0]*shape[1]*Type.BYTES_PER_ELEMENT) return encoded;
    const flat=new Type(bytes.buffer);
    const rows=Array.from({length:shape[0]},(_,i)=>Array.from(flat.subarray(i*shape[1],(i+1)*shape[1])));
    hoverArrays.set(encoded,{bdata:encoded.bdata,dtype:encoded.dtype,shape:encoded.shape,rows});
    return rows;
  }
  function plotLayout(layout,theme,scale,plotScale=100) {
    const p = palette(theme), size = 14*scale/100*plotScale/100;
    const axis = original => ({...original, color:p.fg, gridcolor:p.grid,
      zerolinecolor:p.grid, automargin:true, nticks:4,
      tickfont:{...original?.tickfont, color:p.fg, size},
      title:{...original?.title, font:{...original?.title?.font,color:p.fg,size}}});
    return {...layout, paper_bgcolor:p.bg, plot_bgcolor:p.bg,
      font:{...layout?.font, color:p.fg, size},
      legend:{...layout?.legend,font:{...layout?.legend?.font,color:p.fg,size}},
      hoverlabel:{...layout?.hoverlabel,font:{...layout?.hoverlabel?.font,size}},
      xaxis:axis(layout?.xaxis), yaxis:axis(layout?.yaxis)};
  }
  function plotData(data,theme,scale,plotScale=100) {
    const p = palette(theme), size = 14*scale/100*plotScale/100;
    return data.map(trace => trace.type === 'scatter'
      ? {...trace,line:{...trace.line,color:p.line}}
      : {...trace,...(trace.customdata ? {customdata:heatmapHoverData(trace.customdata)} : {}),colorbar:{...trace.colorbar,nticks:3,
          tickfont:{color:p.fg,size},title:{...trace.colorbar?.title,font:{color:p.fg,size}}}});
  }
  // Dependency-free unit checks can import the persistence and styling layer.
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {KEY,defaults,normalise,load,save,plotLayout,plotData,heatmapHoverData};
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
  const initialArrayLimit=Number(state.get('volume_preview_mib'));
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
    dialog.querySelector('#pref-scale-number').value = prefs.textScale;
    dialog.querySelector('#pref-plot-scale').value = prefs.plotScale;
    dialog.querySelector('#pref-layout').checked = prefs.rememberLayout;
    dialog.querySelector('#pref-axes').checked = prefs.showAxes;
    dialog.querySelector('#pref-array-limit').value = prefs.voxelArrayMib ?? state.get('volume_preview_mib');
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
    const limit=prefs.voxelArrayMib ?? initialArrayLimit;
    if (Number.isFinite(limit) && limit>=1) {
      prefs.voxelArrayMib=limit;
      const changed=Number(state.get('volume_preview_mib'))!==limit;
      state.set('volume_preview_mib',limit);
      if(changed && state.get('has_volume') && !state.get('volume_loading'))window.nimCrop?.submit(true);
    }
    state.set('ui_theme',theme);
    state.set('ui_text_scale',prefs.textScale);
    state.set('ui_plot_scale',prefs.plotScale);
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
        <div class="settings-row"><label for="pref-theme">Theme</label>
          <select id="pref-theme"><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></div>
        <div class="settings-row"><label for="pref-scale-number">Text size</label>
          <input id="pref-scale" aria-label="Text size slider" type="range" min="80" max="160" step="5">
          <span class="settings-number"><input id="pref-scale-number" type="number" min="80" max="160" step="5"><span>%</span></span></div>
        <div class="settings-row"><label for="pref-plot-scale">Plot font size</label>
          <span class="settings-number"><input id="pref-plot-scale" title="Relative to interface text size" type="number" min="50" max="200" step="5"><span>%</span></span></div>
        <div class="settings-row"><label for="pref-array-limit">Voxel array limit (MiB)</label>
          <input id="pref-array-limit" type="number" min="1" step="1"></div>
        <label class="settings-check"><input id="pref-layout" type="checkbox"> Remember panel layout and sizes</label>
        <label class="settings-check"><input id="pref-axes" type="checkbox"> Show coordinate axes</label>
        <p class="settings-help" data-storage-notice></p>
        <div class="settings-actions"><button type="button" id="pref-reset">Reset preferences</button><button value="close">Close</button></div>
      </form>`;
    document.body.appendChild(dialog);
    dialog.addEventListener('input', event => {
      if (event.target.id === 'pref-array-limit') {
        const limit=Number(event.target.value);
        if (Number.isFinite(limit) && limit>=1) {
          state.set('volume_preview_mib',limit);
          if(state.get('has_volume') && !state.get('volume_loading'))window.nimCrop.submit();
        }
        return;
      }
      if (event.target.id === 'pref-theme') prefs.theme = event.target.value;
      if (['pref-scale','pref-scale-number'].includes(event.target.id)) {
        if(!event.target.value || !event.target.validity.valid)return;
        prefs.textScale = Number(event.target.value);
      }
      if (event.target.id === 'pref-plot-scale') {
        if(!event.target.value || !event.target.validity.valid)return;
        prefs.plotScale = Number(event.target.value);
      }
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
    if(type==='dirty-state' && keys.includes('volume_preview_mib')) {
      const limit=Number(state.get('volume_preview_mib'));
      if(Number.isFinite(limit) && limit>=1) {
        prefs.voxelArrayMib=limit;
        const input=dialog?.querySelector('#pref-array-limit');
        if(input && document.activeElement!==input)input.value=limit;
        clearTimeout(saveTimer);saveTimer=setTimeout(persist,150);
      }
    }
    if (type === 'dirty-state' && keys.some(key => key === 'rotation_fps' || key === 'rotation_step')) {
      const frequency=Number(state.get('rotation_fps')),step=Number(state.get('rotation_step'));
      if (Number.isFinite(frequency) && frequency >= 1 && frequency <= 60 &&
          Number.isFinite(step) && step >= .1 && step <= 180) {
        prefs.rotationFps=frequency; prefs.rotationStep=step;
        clearTimeout(saveTimer); saveTimer=setTimeout(persist,150);
      }
    }

  });
  window.addEventListener('pagehide', () => { clearTimeout(saveTimer);persist(); });
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
