/* A shared, bounded queue for volume gestures and coordinated controls. */
(() => {
  function createLatestUpdates(send, options={}) {
    const now = options.now || (() => performance.now());
    const setTimer = options.setTimer || setTimeout;
    const clearTimer = options.clearTimer || clearTimeout;
    const interval = options.interval ?? 100;
    const pending = new Map();
    let inFlight = false, timer = null, lastSent = -Infinity;
    async function pump() {
      if (inFlight || !pending.size) return;
      clearTimer(timer);
      const [kind,item] = pending.entries().next().value;
      const delay = (typeof interval === 'function' ? interval(kind) : interval)-(now()-lastSent);
      if (!item.urgent && delay > 0) { timer=setTimer(pump,delay); return; }
      pending.delete(kind);
      inFlight=true;
      lastSent=now();
      try { await send(kind,item.value,item.context); }
      catch (error) { (options.onError || console.error)('Interaction update failed',error); }
      finally { inFlight=false; pump(); }
    }
    return {
      submit(kind,value,urgent=false) {
        const previous=pending.get(kind);
        const context=options.context?.();
        if (kind === 'pose' && previous && previous.context === context) value={...value,values:{...previous.value.values,...value.values}};
        pending.set(kind,{value,urgent,context});
        pump();
      },
    };
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports={createLatestUpdates}; return;
  }
  window.nimUpdates=createLatestUpdates((kind,value,context) => kind === 'beam'
    ? window.trame.trigger('nim_beam_position',[...value,context])
    : kind === 'volume' ? window.trame.trigger('nim_volume_view',[value,context])
    : kind === 'detail' ? window.trame.trigger('nim_auto_detail',[value,context])
    : kind === 'saxs' ? window.trame.trigger('nim_saxs_selection',[value,context])
    : kind === 'camera' ? (value.action === 'beam-view'
      ? window.trame.trigger('nim_beam_view',[context])
      : window.trame.trigger('nim_camera_angle',[value.angle,value.finished,context]))
    : window.trame.trigger('nim_pose',[value.values,value.finished,context]),
    {context:()=>window.trame.state.get('sample_context'),
     interval:kind => kind === 'camera' && window.trame.state.get('rotation_playing')
       ? 1000/(Number(window.trame.state.get('rotation_fps')) || 20) : 100});
})();
