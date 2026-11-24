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
  let dirty=false, synchronising=false, activeRange=null, finishTimer=null;
  function angle() {
    const raw=state.get('draft_camera_angle');
    return raw==='' || raw==null || !Number.isFinite(Number(raw)) ? null : wrapAngle(Number(raw));
  }
  function submit(finished=false,urgent=false) {
    const value=angle();
    if(dirty && value!==null)window.nimUpdates.submit('camera',{angle:value,finished},urgent);
  }
  function finish() {clearTimeout(finishTimer);submit(true,true);}
  const rotation=createRotation({
    getSettings:()=>({frequency:Number(state.get('rotation_fps')),step:Number(state.get('rotation_step'))}),
    getAngle:()=>angle() ?? Number(state.get('camera_angle')),
    setAngle:value=>state.set('draft_camera_angle',value),
    setPlaying:value=>state.set('rotation_playing',value),finish,
  });
  window.nimCoordinates={pause:()=>rotation.pause(),beamView() {
    dirty=false;activeRange=null;clearTimeout(finishTimer);
    rotation.pause();
    synchronising=true;state.set('draft_camera_angle',0);synchronising=false;
    // Replace any pending angle, and run after the in-flight camera request.
    window.nimUpdates.submit('camera',{action:'beam-view'},true);
  }};
  function sync() {
    synchronising=true;
    try {
      state.set('draft_camera_angle',Number(state.get('camera_angle')) || 0);
      for(const [field,draft] of [['beam_x','draft_x'],['beam_y','draft_y'],['angle','draft_angle']])state.set(draft,state.get(field));
    } finally{synchronising=false;}
  }
  state.addListener(({type,keys=[]})=>{
    if(synchronising)return;
    if(type==='ready' || type==='refresh' || keys.includes('sample_context')) {
      clearTimeout(finishTimer);dirty=false;activeRange=null;rotation.pause();sync();return;
    }
    if(type!=='dirty-state')return;
    if(keys.some(k=>k==='rotation_fps' || k==='rotation_step'))rotation.configure();
    if(keys.some(k=>['beam_x','beam_y','angle','saxs_pose_revision'].includes(k))) {
      synchronising=true;
      for(const [field,draft] of [['beam_x','draft_x'],['beam_y','draft_y'],['angle','draft_angle']])state.set(draft,state.get(field));
      synchronising=false;
    }
    if(keys.includes('camera_angle')) {
      const target=angle(),canonical=Number(state.get('camera_angle'));
      if(!dirty || (target!==null && Math.abs(wrapAngle(canonical-target))<=.001)) {
        dirty=false;synchronising=true;state.set('draft_camera_angle',canonical);synchronising=false;
      }
    }
    if(!keys.includes('draft_camera_angle'))return;
    dirty=true;
    if(angle()===null){clearTimeout(finishTimer);return;}
    synchronising=true;state.set('draft_camera_angle',angle());synchronising=false;
    submit(!!state.get('rotation_playing'));
    clearTimeout(finishTimer);
    if(!activeRange && !state.get('rotation_playing'))finishTimer=setTimeout(finish,150);
  });
  sync();
  function isControl(target) {return target?.matches?.('input[id^="camera-angle-"]');}
  document.addEventListener('pointerdown',event=>{
    if(event.target.closest('#volume-interaction')) {rotation.pause();dirty=false;}
    if(isControl(event.target) && event.target.type==='range') {
      activeRange=event.pointerId;event.target.setPointerCapture(event.pointerId);clearTimeout(finishTimer);
    }
  },true);
  function release(event) {if(activeRange===event.pointerId){activeRange=null;finish();}}
  for(const name of ['pointerup','pointercancel','lostpointercapture'])document.addEventListener(name,release,true);
  document.addEventListener('focusout',event=>{if(isControl(event.target))finish();});
  document.addEventListener('click',event=>{
    if(event.target.closest('#open-volume, #open-project, #saved-views'))rotation.pause();
    if(event.target.closest('#rotation-toggle')) {
      if(state.get('rotation_playing'))rotation.pause();else rotation.play();
    }
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden)rotation.pause();});
})();
