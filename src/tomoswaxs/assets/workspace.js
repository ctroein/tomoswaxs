/* Dockview layout and panel lifecycle stay local to this browser. */
(() => {
  const panels={volume:{title:'µCT volume',template:'nim_volume'},iq:{title:'SAXS 1D',template:'nim_iq'},cake:{title:'SAXS cake',template:'nim_cake'},crop:{title:'Crop and resolution',template:'nim_crop'},saxs:{title:'SAXS measurements',template:'nim_saxs'}};
  const legacyPanels={...panels,resolution:{title:'Resolution',template:'nim_resolution'}};
  function validLayout(layout) {
    if (!layout || !['HORIZONTAL','VERTICAL'].includes(layout.grid?.orientation) ||
        !layout.panels || typeof layout.panels !== 'object') return false;
    if (!Object.entries(layout.panels).every(([id,p])=>legacyPanels[id] && p?.id === id &&
        p.contentComponent === 'DockPanel' && p.params?.templateName === legacyPanels[id].template)) return false;
    function tree(node,depth=0) {
      if (!node || depth>16) return false;
      if (node.type === 'branch') return Array.isArray(node.data) && node.data.every(child=>tree(child,depth+1));
      return node.type === 'leaf' && Array.isArray(node.data?.views) &&
        node.data.views.every(id=>Object.hasOwn(layout.panels,id));
    }
    if(!tree(layout.grid.root)) return false;
    if(layout.floatingGroups !== undefined && (!Array.isArray(layout.floatingGroups) ||
      !layout.floatingGroups.every(group=>group && (group.grid ? tree(group.grid.root) : tree({type:'leaf',data:group.data}))))) return false;
    return true;
  }

  function defaultLayout(width,height,ratios={height:66,width:50}) {
    const w=Math.max(360,width),h=Math.max(200,height),top=h*(ratios.height ?? 66)/100,side=Math.min(360,w*.3),main=w-side,left=main*(ratios.width ?? 50)/100;
    const leaf=(id,group,size)=>({type:'leaf',data:{views:[id],activeView:id,id:group},size});
    return {grid:{width:w,height:h,orientation:'HORIZONTAL',root:{type:'branch',size:h,data:[
      {type:'branch',size:main,data:[leaf('volume','1',top),{type:'branch',size:h-top,data:[leaf('iq','2',left),leaf('cake','3',main-left)]}]},
      {type:'branch',size:side,data:[leaf('crop','crop-controls',h*.64),leaf('saxs','saxs-controls',h*.36)]}
    ]}},nimControlsVersion:3,panels:Object.fromEntries(Object.entries(panels).map(([id,p])=>[id,{id,contentComponent:'DockPanel',params:{templateName:p.template},title:p.title,minimumHeight:100,minimumWidth:['crop','saxs'].includes(id)?260:180}])),activeGroup:'1'};
  }
  // Persist a layout that reopens every panel in the main document. Never
  // replay window URLs or attempt window.open during a browser refresh.
  function mainWindowLayout(layout) {
    const result=JSON.parse(JSON.stringify(layout));
    delete result.popoutGroups;
    mergeVolumeControls(result);
    for (const [id,panel] of Object.entries(result.panels)) panel.title=panels[id].title;
    result.nimControlsVersion=3;
    const present=new Set();
    function visit(node) {
      if(node.type === 'leaf') node.data.views.forEach(id=>present.add(id));
      else node.data.forEach(visit);
    }
    visit(result.grid.root);
    for(const group of result.floatingGroups || []) {
      if(group.grid) visit(group.grid.root);
      else if(group.data?.views) group.data.views.forEach(id=>present.add(id));
    }
    const missing=Object.keys(result.panels).filter(id=>!present.has(id));
    if(missing.length) {
      const root=result.grid.root;
      if(root.type !== 'branch') result.grid.root={type:'branch',size:result.grid.height,data:[root]};
      // Unique group ids avoid collisions with Dockview's generated ids.
      const used=new Set();
      function groups(node) {if(node.type==='leaf') used.add(node.data.id);else node.data.forEach(groups);}
      groups(result.grid.root);
      for(const id of missing) {
        let groupId=`nim-return-${id}`;
        while(used.has(groupId)) groupId+='-';
        used.add(groupId);
        result.grid.root.data.push({type:'leaf',size:200,data:{id:groupId,views:[id],activeView:id}});
        result.activeGroup=groupId;
      }
    }
    return result;
  }
  function mergeVolumeControls(layout) {
    const hadCrop=!!layout.panels.crop;
    if(layout.panels.resolution && !hadCrop) {
      layout.panels.crop={...layout.panels.resolution,id:'crop',title:panels.crop.title,params:{templateName:'nim_crop'}};
    }
    delete layout.panels.resolution;
    function prune(node) {
      if(node.type==='leaf') {
        node.data.views=node.data.views.flatMap(id=>id==='resolution' ? (hadCrop ? [] : ['crop']) : [id]);
        if(!node.data.views.length)return null;
        if(!node.data.views.includes(node.data.activeView))node.data.activeView=node.data.views[0];
      } else {
        const removed=node.data.filter(n=>n.type==='leaf' && n.data.views.length===1 && n.data.views[0]==='resolution' && hadCrop);
        node.data=node.data.map(prune).filter(Boolean);
        if(!node.data.length)return null;
        const crop=node.data.find(n=>n.type==='leaf' && n.data.views.includes('crop'));
        if(crop)crop.size=(crop.size || 0)+removed.reduce((n,c)=>n+(c.size || 0),0);
      }
      return node;
    }
    layout.grid.root=prune(layout.grid.root) || {type:'branch',data:[]};
    if(layout.floatingGroups)layout.floatingGroups=layout.floatingGroups.filter(group=>!!prune(group.grid?.root || {type:'leaf',data:group.data}));
    if(layout.panels.crop)layout.panels.crop.title=panels.crop.title;
    const groups=[];
    function visit(node) {if(node.type==='leaf')groups.push(node.data.id);else node.data.forEach(visit);}
    visit(layout.grid.root);
    if(!groups.includes(layout.activeGroup))layout.activeGroup=groups[0];
    layout.nimControlsVersion=3;
    return layout;
  }
  function placeSaxsBelowResolution(layout) {
    const defaults=defaultLayout(layout.grid.width,layout.grid.height);
    layout.panels.saxs=defaults.panels.saxs;
    function prune(node) {
      if(node.type==='leaf') {
        node.data.views=node.data.views.filter(id=>id!=='saxs');
        if(!node.data.views.length)return null;
        if(!node.data.views.includes(node.data.activeView))node.data.activeView=node.data.views[0];
      } else {node.data=node.data.map(prune).filter(Boolean);if(!node.data.length)return null;}
      return node;
    }
    layout.grid.root=prune(layout.grid.root) || {type:'branch',data:[]};
    layout.floatingGroups=(layout.floatingGroups || []).filter(group=>!!prune(group.grid?.root || {type:'leaf',data:group.data}));
    const added={type:'leaf',size:Math.max(180,layout.grid.height*.3),data:{id:'saxs-controls',views:['saxs'],activeView:'saxs'}};
    function insert(node) {
      if(node.type!=='branch')return false;
      for(let i=0;i<node.data.length;i++) {
        const child=node.data[i];
        if(child.type==='leaf' && (child.data.views.includes('resolution') || child.data.views.includes('crop'))) {node.data.splice(i+1,0,added);return true;}
        if(insert(child))return true;
      }
      return false;
    }
    if(!insert(layout.grid.root)) {
      if(layout.grid.root.type!=='branch')layout.grid.root={type:'branch',data:[layout.grid.root]};
      layout.grid.root.data.push(added);
    }
    layout.nimControlsVersion=2;
    return layout;
  }
  if(typeof module !== 'undefined' && module.exports) {module.exports={validLayout,defaultLayout,mainWindowLayout,placeSaxsBelowResolution,mergeVolumeControls};return;}
  let dock,api;
  const tabs=new WeakMap(),popouts=new Map(),disposables=[];
  const state=()=>window.trame.state;
  function syncLive() {
    if(!api) return;
    state().set('workspace_tabs',api.panels.map(p=>p.id));
    state().set('workspace_detached',api.panels.filter(p=>p.api.location.type==='popout').map(p=>p.id));
  }
  function stylePopout(child) {
    if(child.closed) return;
    const root=child.document.documentElement;
    root.dataset.theme=document.documentElement.dataset.theme;
    root.style.fontSize=document.documentElement.style.fontSize;
    child.document.querySelector('.dv-popout-window')?.classList.add('dock-workspace');
  }
  function addPopout(event) {
    const child=event.window;
    stylePopout(child);
    const detach=window.nimBeam.attach(child.document);
    const resize=()=>window.dispatchEvent(new Event('resize'));
    child.addEventListener('resize',resize);
    let disposed=false;
    const cleanup=()=>{
      if(disposed) return;
      disposed=true;
      child.removeEventListener('pagehide',cleanup);
      detach(); child.removeEventListener('resize',resize);
      popouts.delete(child);
    };
    child.addEventListener('pagehide',cleanup,{once:true});
    popouts.set(child,cleanup);
    syncLive();
    resize();
  }
  function bindApi(containerApi) {
    // Each panel receives a different API facade for the same workspace.
    if(api) return;
    api=containerApi;
    disposables.push(api.onDidAddPopoutGroup(addPopout));
    disposables.push(api.onDidRemovePopoutGroup(()=>{
      for(const [child,cleanup] of popouts) if(child.closed) cleanup();
      syncLive();
    }));
  }
  const appearance=new MutationObserver(()=>{
    for(const child of popouts.keys()) stylePopout(child);
  });
  appearance.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme','style']});
  window.addEventListener('pagehide',()=>{
    appearance.disconnect();
    for(const cleanup of [...popouts.values()]) cleanup();
    disposables.forEach(item=>item.dispose());
  });
  function syncTabs(layout) {
    const ids=Object.keys(layout.panels);
    window.trame.state.set('workspace_tabs',ids);
  }
  function initial(layout) {
    const el=document.querySelector('.dock-workspace');
    return defaultLayout(el.clientWidth,el.clientHeight,layout?.height ? layout : undefined);
  }
  function restore(layout) {
    if(dock) {
      const next=validLayout(layout) ? mainWindowLayout(layout) : initial(layout);
      // Upgrade a saved three-panel workspace once; later closed controls stay closed.
      if(validLayout(layout) && !layout.nimControlsVersion) {
        const defaults=defaultLayout(1200,600);
        const added=['crop'].filter(id=>!next.panels[id]);
        for(const id of added) next.panels[id]=defaults.panels[id];
        if(added.length) {
          if(next.grid.root.type!=='branch') next.grid.root={type:'branch',size:next.grid.height,data:[next.grid.root]};
          next.grid.root.data.push({type:'leaf',size:300,data:{views:added,activeView:added[0],id:'nim-controls-upgrade'}});
        }
      }
      if(validLayout(layout) && (layout.nimControlsVersion || 0)<2)placeSaxsBelowResolution(next);
      mergeVolumeControls(next);dock.restoreLayout(next);syncTabs(next);
    }
  }
  window.nimWorkspace={validLayout,
    viewHelp(event) {
      const button=event.currentTarget, popup=button.nextElementSibling;
      popup.togglePopover();
      if(!popup.matches(':popover-open')) return;
      const rect=button.getBoundingClientRect(), win=button.ownerDocument.defaultView;
      popup.style.left=`${Math.max(8,Math.min(rect.left,win.innerWidth-popup.offsetWidth-8))}px`;
      popup.style.top=`${Math.max(8,Math.min(rect.bottom+6,win.innerHeight-popup.offsetHeight-8))}px`;
    },
    mountTab(element,params) {
      element.closest('[role="tab"]')?.setAttribute('aria-label',params.api.title);
      bindApi(params.containerApi);
      const listener=params.api.onDidLocationChange(()=>{syncLive();window.nimWorkspace.visibility();});
      tabs.set(element,listener);
      syncLive();
    },
    unmountTab(element) { tabs.get(element)?.dispose();tabs.delete(element); },
    async popout(params) {
      const id=params.api.id;
      if(state().get('workspace_busy').includes(id)) return;
      state().set('workspace_error','');
      state().set('workspace_busy',[...state().get('workspace_busy'),id]);
      try {
        if(params.api.location.type==='popout') {
          // PanelApi.moveTo defaults to its *own* group when group is omitted;
          // unlike GroupApi.moveTo it does not create a main-grid destination.
          const target=params.containerApi.addGroup({direction:'right'});
          params.api.moveTo({group:target,position:'center'});
          window.nimWorkspace.visibility();
        } else {
          // The bundled Dockview can leave its promise pending when a child
          // closes during loading. Bound that wait and release the busy state.
          let child,timer,fail,reason='';
          const interrupted=new Promise(resolve=>{fail=resolve;});
          const opening=params.containerApi.addPopoutGroup(params.containerApi.getPanel(id),{
            popoutUrl:'/nim-assets/popout.html',
            onDidOpen:event=>{child=event.window;},
            onWillClose:()=>{reason ||= 'The separate window closed before it finished loading.';fail(false);},
          });
          timer=setTimeout(()=>{
            reason='The separate window did not finish loading.';
            fail(false);child?.close();
          },10000);
          let opened;
          try { opened=await Promise.race([opening,interrupted]); }
          finally { clearTimeout(timer); }
          if(!opened) state().set('workspace_error',reason || 'Could not open a separate window. Check that this browser allows popups for this site.');
        }
      } catch(error) {
        console.error('NIM popout failed',error);
        state().set('workspace_error','Could not move the panel to a separate window.');
      } finally {
        state().set('workspace_busy',state().get('workspace_busy').filter(item=>item!==id));
        syncLive();
      }
    },
    ready(getDock) { const start=()=>Vue.nextTick(()=>{
      dock=getDock();
      restore(window.nimPreferences.getLayout());
      window.trame.state.set('workspace_ready',true);
    });
      if (window.nimPreferences?.getLayout) start();
      else window.addEventListener('nim-preferences-ready',start,{once:true});
    },
    changed(layout) { if(validLayout(layout)) { window.nimWorkspace.currentLayout=layout; syncTabs(layout); syncLive(); window.nimPreferences.updateLayout(mainWindowLayout(layout)); } },
    visibility() { requestAnimationFrame(()=>window.dispatchEvent(new Event('resize'))); },
    restore,
    open(id) { if(!dock || !panels[id]) return; const p=panels[id];dock.addPanel(id,p.title,p.template,{minimumHeight:100,minimumWidth:['crop','saxs'].includes(id)?260:180});dock.activePanel(id); },
    removed(id) { window.trame.state.set('workspace_tabs',(window.trame.state.get('workspace_tabs') || []).filter(item=>item!==id)); },
    toggle(id) {
      if(!dock || !panels[id]) return;
      const open=window.trame.state.get('workspace_tabs') || [];
      if(open.includes(id)) { dock.removePanel(id); window.trame.state.set('workspace_tabs',open.filter(item=>item!==id)); }
      else { window.nimWorkspace.open(id); window.trame.state.set('workspace_tabs',[...open,id]); }
    },
    reset() { restore(null); },
  };
  window.dispatchEvent(new Event('nim-workspace-ready'));
})();
