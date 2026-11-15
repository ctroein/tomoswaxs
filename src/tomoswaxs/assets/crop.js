/* Crop drafts stay local; complete requests share the bounded update queue. */
(() => {
  const state=window.trame.state;
  function syncDrafts() {
    const crop=state.get('crop_bounds');
    if(!Array.isArray(crop) || crop.length!==3)return;
    for(const [i,axis] of [...'xyz'].entries()) state.set(`crop_draft_${axis}`,{min:crop[i][0],max:crop[i][1]});
  }
  state.addListener(({type,keys=[]})=>{
    if(type==='ready' || type==='refresh' || (type==='dirty-state' && keys.some(key=>key==='crop_revision' || key==='sample_context'))) syncDrafts();
  });
  syncDrafts();
  function selection() {
    const crop='xyz'.split('').map(axis=>{
      const pair=state.get(`crop_draft_${axis}`);
      return [pair?.min,pair?.max];
    });
    if(crop.some(([a,b],i)=> !Number.isInteger(a) || !Number.isInteger(b) || a<0 || a>=b || b>state.get(`crop_max_${'xyz'[i]}`))) {state.set('crop_notice','Enter whole voxel indices with start smaller than end, within the sample.');return null;}
    const limit=Number(state.get('volume_preview_mib'));
    if(!Number.isFinite(limit) || limit<1) {state.set('crop_notice','Enter a voxel array size limit of at least 1 MiB.');return null;}
    return {crop,level:state.get('render_level'),limit};
  }
  function submit(finished=false) {
    const spec=selection();
    if(spec) {state.set('crop_notice','');window.nimUpdates.submit('volume',spec,finished);}
  }
  window.nimCrop={submit,
    limit(value) {state.set('volume_preview_mib',value==='' ? '' : Number(value));submit();},
    edit(axis,side,value) {
      const key=`crop_draft_${axis}`;
      state.set(key,{...state.get(key),[side]:value==='' ? '' : Number(value)});
      submit();
    },
    change(axis,value,finished=false) {
      if(!['x','y','z'].includes(axis))return;
      // A range slider can collapse its handles; keep at least one voxel.
      const max=state.get(`crop_max_${axis}`);
      let lo=Math.min(max-1,Math.max(0,Math.round(value.min)));
      let hi=Math.min(max,Math.max(lo+1,Math.round(value.max)));
      state.set(`crop_draft_${axis}`,{min:lo,max:hi});
      submit(finished);
    },
    reset() {
      for(const axis of 'xyz') state.set(`crop_draft_${axis}`,{min:0,max:state.get(`crop_max_${axis}`)});
      submit(true);
    },
    async copy() {
      const spec=selection();
      if(!spec)return;
      const text='['+[...spec.crop].reverse().map(([a,b])=>`${a}:${b}`).join(', ')+']';
      try {await navigator.clipboard.writeText(text);state.set('crop_notice',`Copied ${text}`);}
      catch {state.set('crop_notice',`Coordinates: ${text}`);}
    },
  };
})();
