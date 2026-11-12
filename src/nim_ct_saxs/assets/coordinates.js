/* Local coordinate drafts; only selected, atomic poses reach Python. */
(() => {
  function wrapAngle(value) {
    return value >= -180 && value <= 180 ? value : ((value+180)%360+360)%360-180;
  }
  function createPixelSizes(state) {
    const baselines=new Map();
    function begin(group) {
      const values=['x','y','z'].map(axis=>Number(state.get(`${group}_voxel_${axis}`)));
      if (values.every(n=>Number.isFinite(n) && n>0)) baselines.set(group,values);
    }
    return {begin,change(group,axis,raw) {
      if (!state.get(`${group}_voxel_linked`)) return;
      const values=baselines.get(group),value=Number(raw),index='xyz'.indexOf(axis);
      if (!values || index < 0 || !values.every(n=>Number.isFinite(n) && n>0) || !Number.isFinite(value) || value<=0) return;
      const factor=value/values[index];
      for (let i=0;i<3;i++) state.set(`${group}_voxel_${'xyz'[i]}`,Number((values[i]*factor).toPrecision(12)));
    }};
  }
  function createRotation({getSettings=()=>({frequency:20,step:1.5}),getAngle,setAngle,setPlaying,finish,now=()=>performance.now(),setTimer=setTimeout,clearTimer=clearTimeout}) {
    let playing=false, timer=null, last=0;
    function settings() {
      const {frequency,step}=getSettings();
      return Number.isFinite(frequency) && frequency >= 1 && frequency <= 60 &&
             Number.isFinite(step) && step >= .1 && step <= 180 ? {frequency,step} : null;
    }
    function tick() {
      if (!playing) return;
      const config=settings();
      if (!config) { controls.pause(); return; }
      const current=now(), elapsed=(current-last)/1000;
      last=current;
      setAngle(Math.round(wrapAngle(getAngle()+config.frequency*config.step*elapsed)*1000)/1000);
      timer=setTimer(tick,1000/config.frequency);
    }
    const controls = {
      play() { const config=settings(); if (playing || !config) return; playing=true; last=now(); setPlaying(true); timer=setTimer(tick,1000/config.frequency); },
      configure() { if (!playing) return; controls.pause(); controls.play(); },
      pause() { if (!playing) return; playing=false; clearTimer(timer); setPlaying(false); finish(); },
    };
    return controls;
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports={wrapAngle,createRotation,createPixelSizes}; return;
  }
  const state=window.trame.state;
  window.nimPixelSizes=createPixelSizes(state);
  const fields={beam_x:'draft_x',beam_y:'draft_y',angle:'draft_angle'};
  const dirty=new Set();
  let activeRange=null, finishTimer=null, synchronising=false;
  function valueOf(field) {
    const raw=state.get(fields[field]);
    if (raw === '' || raw == null) return null;
    const value=Number(raw);
    if (!Number.isFinite(value)) return null;
    if (field === 'angle') return wrapAngle(value);
    const limit=Number(state.get('beam_limit_um')) || 1600;
    return value >= -limit && value <= limit ? value : null;
  }
  function submit(finished=false,urgent=false) {
    const values={};
    for (const field of dirty) {
      const value=valueOf(field);
      if (value !== null) values[field]=value;
    }
    window.nimUpdates.submit('pose',{values,finished},urgent);
  }
  function finish() { clearTimeout(finishTimer); submit(true,true); }
  const rotation=createRotation({
    getSettings:()=>({frequency:Number(state.get('rotation_fps')),step:Number(state.get('rotation_step'))}),
    getAngle:()=>valueOf('angle') ?? Number(state.get('angle')),
    setAngle:value=>state.set('draft_angle',value),
    setPlaying:value=>state.set('rotation_playing',value),finish,
  });
  window.nimCoordinates={pause:()=>rotation.pause()};
  state.addListener(({type,keys=[]}) => {
    if (type !== 'dirty-state' || synchronising) return;
    if (keys.some(key=>key === 'rotation_fps' || key === 'rotation_step')) rotation.configure();
    if (keys.includes('sample_context')) {
      clearTimeout(finishTimer);
      activeRange=null;
      dirty.clear();
      rotation.pause();
      synchronising=true;
      try { for (const [field,draft] of Object.entries(fields)) state.set(draft,state.get(field)); }
      finally { synchronising=false; }
    }
    // Server acknowledgements must not overwrite newer local input.
    synchronising=true;
    try {
      for (const [field,draft] of Object.entries(fields)) {
        if (!keys.includes(field)) continue;
        const canonical=Number(state.get(field));
        const desired=valueOf(field);
        if (dirty.has(field) && (desired === null || Math.abs(canonical-desired) > .001)) continue;
        dirty.delete(field);
        state.set(draft,canonical);
      }
    } finally { synchronising=false; }
    const changed=Object.entries(fields).filter(([,draft])=>keys.includes(draft));
    if (!changed.length) return;
    synchronising=true;
    try {
      for (const [field,draft] of changed) {
        const value=valueOf(field);
        if (value === null) continue;
        dirty.add(field);
        if (field === 'angle') state.set(draft,value);
      }
    } finally { synchronising=false; }
    if (!dirty.size) return;
    const playing=!!state.get('rotation_playing');
    // During play, SAXS follows the selected frames. During scrubbing it
    // refreshes at release; the volume follows the bounded interaction queue.
    submit(playing);
    clearTimeout(finishTimer);
    if (!activeRange && !playing) finishTimer=setTimeout(finish,150);
  });
  synchronising=true;
  for (const [field,draft] of Object.entries(fields)) state.set(draft,state.get(field));
  synchronising=false;
  function isCoordinate(target) { return target?.matches?.('input[id^="coord-"]'); }
  document.addEventListener('pointerdown', event => {
    if (event.target.closest('#volume-interaction')) rotation.pause();
    if (isCoordinate(event.target) && event.target.type === 'range') {
      activeRange=event.pointerId;
      event.target.setPointerCapture(event.pointerId);
      clearTimeout(finishTimer);
    }
  },true);
  function release(event) {
    if (activeRange !== event.pointerId) return;
    activeRange=null;
    finish();
  }
  document.addEventListener('pointerup',release,true);
  document.addEventListener('pointercancel',release,true);
  document.addEventListener('lostpointercapture',release,true);
  document.addEventListener('focusout',event=>{if(isCoordinate(event.target)) finish();});
  document.addEventListener('click',event=>{
    if (event.target.closest('#open-volume, #open-project')) rotation.pause();
    if (event.target.closest('#rotation-play')) rotation.play();
    if (event.target.closest('#rotation-pause')) rotation.pause();
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden) rotation.pause();});
})();
