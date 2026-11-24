/* Project history belongs to this browser; Python owns project loading. */
(() => {
  const KEY='tomoswaxs.projects.v1',LIMIT=8;
  function normalise(value) {
    const projects=[];
    for(const item of Array.isArray(value?.projects) ? value.projects : []) {
      if(typeof item?.path!=='string' || !item.path || typeof item.name!=='string' || projects.some(p=>p.path===item.path))continue;
      projects.push({path:item.path,name:item.name});
      if(projects.length===LIMIT)break;
    }
    return {projects,last:typeof value?.last==='string' ? value.last : ''};
  }
  function load(storage,onError=()=>{}) {try{return normalise(JSON.parse(storage.getItem(KEY)));}catch{onError();return normalise(null);}}
  function remember(history,event) {
    if(event.kind==='closed')return {...history,last:''};
    if(event.kind!=='opened' || !event.path)return history;
    return normalise({last:event.path,projects:[{path:event.path,name:event.name},...history.projects.filter(p=>p.path!==event.path)]});
  }
  if(typeof module!=='undefined' && module.exports) {module.exports={KEY,normalise,load,remember};return;}
  let storage;try{storage=window.localStorage;}catch{}
  let notice='';
  let history=load(storage,()=>{notice='Recent-project history could not be read from this browser.';}),seen='',attempted=false;
  const state=window.trame.state;
  function sync() {
    const event=state.get('project_history_event');
    if(event?.id && event.id!==seen) {
      seen=event.id;history=remember(history,event);
      try{storage.setItem(KEY,JSON.stringify(history));notice='';}catch{notice='Recent projects could not be saved in this browser.';}
    }
    state.set('recent_projects',history.projects);
    state.set('project_history_notice',notice);
    if(!attempted && state.get('restore_project_allowed')===true) {
      attempted=true;
      if(history.last && !state.get('project_name') && !state.get('has_sample'))
        window.trame.trigger('nim_recent_project',[history.last,true]);
    }
  }
  state.addListener(({type,keys=[]})=>{
    if(type==='ready' || type==='refresh' || (type==='dirty-state' && keys.some(k=>['project_history_event','restore_project_allowed'].includes(k))))sync();
  });
  sync();
})();
