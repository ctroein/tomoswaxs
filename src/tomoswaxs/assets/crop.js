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
  function display(axis,index,units=state.get('crop_units')) {
    if(index === '' || index == null)return '';
    const i='xyz'.indexOf(axis);
    const value=units==='um' ? state.get('crop_origin_um')[i]+Number(index)*state.get('crop_spacing_um')[i] : Number(index);
    return Number(value.toPrecision(12));
  }
  window.nimCrop={submit,display,
    detail(finished=false,enabled=null,depth=null) {
      if(enabled!==null)state.set('detail_enabled',!!enabled);
      if(depth!==null)state.set('detail_depth',Number(depth));
      window.nimUpdates.submit('detail',{enabled:!!state.get('detail_enabled'),depth:Number(state.get('detail_depth'))},finished);
    },
    freeze() {
      window.nimUpdates.submit('detail',{enabled:!!state.get('detail_enabled'),depth:Number(state.get('detail_depth')),
        freeze:!state.get('detail_frozen')},true);
    },
    input(axis,side,event) {
      if(state.get('crop_units')!=='um')this.edit(axis,side,event.target.value);
    },
    commit(axis,side,event) {
      this.editDisplay(axis,side,event.target.value);
      event.target.value=display(axis,state.get(`crop_draft_${axis}`)[side]);
    },
    editDisplay(axis,side,raw) {
      const i='xyz'.indexOf(axis);
      const index=raw==='' ? '' : state.get('crop_units')==='um'
        ? Math.round((Number(raw)-state.get('crop_origin_um')[i])/state.get('crop_spacing_um')[i]) : Number(raw);
      const key=`crop_draft_${axis}`;
      state.set(key,{...state.get(key),[side]:index});submit(true);
    },
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
  window.dispatchEvent(new Event('nim-crop-ready'));
})();
