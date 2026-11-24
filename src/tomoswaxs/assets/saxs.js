/* Acquisition-grid drafts; the shared queue sends only the newest selection. */
(() => {
  const state=window.trame.state;
  let pending=null,lastSelection=null,lockedX=null;
  const editing=new Set();
  const get=name=>state.get(name);
  const formatCoordinate=value=>value==null || value==='' ? '' : Number(Number(value).toFixed(4));
  function axis(kind) {
    const axes=get('saxs_axes')?.[Number(get('saxs_draft_scan'))];
    return (kind==='x' ? axes?.x_by_angle?.[Number(get('saxs_draft_row'))] : null) || axes?.[kind] || [];
  }
  function numbers() {
    for(const [kind,key] of [['x','column'],['angle','row']]) {
      if(!editing.has(kind))state.set(`saxs_input_${kind}`,formatCoordinate(axis(kind)[get(`saxs_draft_${key}`)]));
    }
  }
  function sync(force=false) {
    const current=['scan','row','column'].map(name=>get(`saxs_${name}`) || 0);
    if(!force && pending && pending.some((value,i)=>value!==current[i]))return;
    pending=null;
    if(force)editing.clear();
    for(const name of ['scan','row','column']) state.set(`saxs_draft_${name}`,get(`saxs_${name}`) || 0);
    lastSelection=current;
    if(force || !get('saxs_lock_x'))lockedX=axis('x')[current[2]];
    numbers();
    state.set('saxs_input_notice','');
  }
  function select(finished=false) {
    const scan=Number(get('saxs_draft_scan'));
    const row=Number(get('saxs_draft_row'));let column=Number(get('saxs_draft_column'));
    if(![scan,row,column].every(Number.isInteger) || row<0 || column<0 || row>=axis('angle').length || column>=axis('x').length) return;
    if(get('saxs_lock_x') && Number.isFinite(lockedX) && lastSelection?.[0]===scan && lastSelection[1]!==row) {
      const xs=axis('x');
      column=xs.reduce((best,x,i)=>Math.abs(x-lockedX)<Math.abs(xs[best]-lockedX) ? i : best,0);
      state.set('saxs_draft_column',column);
    } else if(!lastSelection || lastSelection[0]!==scan || lastSelection[2]!==column)lockedX=axis('x')[column];
    const placement={};
    for(const key of ['x_origin','y_origin','x_offset','y_offset','x_sign','y_sign','angle_offset','angle_sign','camera_x','camera_y','pivot_x','pivot_z']) {
      const value=get(`saxs_map_${key}`) ?? (key.endsWith('_sign') ? 1 : 0);
      if(value === '' || value === null || !Number.isFinite(Number(value))) {
        state.set('saxs_input_notice','Enter finite CT placement values.');return;
      }
      placement[key]=Number(value);
    }
    state.set('saxs_input_notice','');
    placement.model=get('saxs_map_model') || 'manual';
    const rows=get('saxs_map_motors') || [];
    if(rows.some(row=>['reference','x','y'].some(key=>row[key] === '' || row[key] == null || !Number.isFinite(Number(row[key]))))) {state.set('saxs_input_notice','Enter finite motor registration values.');return;}
    placement.motors=rows.map(row=>({...row,reference:Number(row.reference),x:Number(row.x),y:Number(row.y)}));
    pending=[scan,row,column];
    lastSelection=[scan,row,column];
    numbers();
    window.nimCoordinates?.pause();
    window.nimUpdates.submit('saxs',{scan,row,column,placement,link_ct:get('saxs_link_ct')},finished);
  }
  window.nimSaxs={select,
    formatCoordinate,
    placement(key,value) {
      state.set(`saxs_map_${key}`,value==='' ? '' : Number(value));
      select(true);
    },
    motorPlacement(name,key,value) {
      const rows=get('saxs_map_motors').map(row=>row.name===name ? {...row,[key]:value==='' ? '' : Number(value)} : row);
      state.set('saxs_map_motors',rows);select(true);
    },
    toggleXLock() {
      state.set('saxs_lock_x',!get('saxs_lock_x'));
      lockedX=axis('x')[Number(get('saxs_draft_column'))];
    },
    edit(kind) {editing.add(kind);},
    scan() {
      state.set('saxs_draft_row',Math.min(Number(get('saxs_draft_row')) || 0,axis('angle').length-1));
      state.set('saxs_draft_column',Math.min(Number(get('saxs_draft_column')) || 0,axis('x').length-1));
      select(true);
    },
    position(kind,value) {
      if(!['x','angle'].includes(kind))return;
      if(value === '' || !Number.isFinite(Number(value))) {state.set('saxs_input_notice','Enter a position or angle.');return;}
      const coordinates=axis(kind);
      if(!coordinates.length)return;
      const distance=(a,b)=>kind==='angle' ? Math.abs(((a-b)%360+540)%360-180) : Math.abs(a-b);
      const nearest=coordinates.reduce((best,v,i)=>distance(v,Number(value))<distance(coordinates[best],Number(value)) ? i : best,0);
      if(distance(coordinates[nearest],Number(value))>.000050001) {editing.delete(kind);numbers();state.set('saxs_input_notice','Choose an acquired position or rotation.');return;}
      editing.delete(kind);
      state.set(kind==='x' ? 'saxs_draft_column' : 'saxs_draft_row',nearest);select(true);
    },
    step(kind,direction) {
      const key=kind==='x' ? 'saxs_draft_column' : 'saxs_draft_row';
      editing.delete(kind);
      const next=Math.max(0,Math.min(axis(kind).length-1,Number(get(key))+direction));
      if(next===Number(get(key))) {numbers();return;}
      state.set(key,next);select(true);
    },

  };
  state.addListener(({type,keys=[]})=>{
    if(type==='ready' || type==='refresh' || (type==='dirty-state' && keys.some(k=>['saxs_axes','sample_context'].includes(k))))sync(true);
    else if(type==='dirty-state' && keys.includes('saxs_revision'))sync();
  });
  sync();
})();
