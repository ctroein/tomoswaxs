/* Dockview layout and panel lifecycle stay local to this browser. */
(() => {
  const panels={volume:{title:'µCT volume',template:'nim_volume'},iq:{title:'SAXS 1D · synthetic',template:'nim_iq'},cake:{title:'SAXS cake · synthetic',template:'nim_cake'}};
  function validLayout(layout) {
    if (!layout || !['HORIZONTAL','VERTICAL'].includes(layout.grid?.orientation) ||
        !layout.panels || typeof layout.panels !== 'object') return false;
    if (!Object.entries(layout.panels).every(([id,p])=>panels[id] && p?.id === id &&
        p.contentComponent === 'DockPanel' && p.params?.templateName === panels[id].template)) return false;
    function tree(node,depth=0) {
      if (!node || depth>16) return false;
      if (node.type === 'branch') return Array.isArray(node.data) && node.data.every(child=>tree(child,depth+1));
      return node.type === 'leaf' && Array.isArray(node.data?.views) &&
        node.data.views.every(id=>Object.hasOwn(layout.panels,id));
    }
    return tree(layout.grid.root);
  }

  function defaultLayout(width,height,ratios={height:66,width:50}) {
    const w=Math.max(360,width),h=Math.max(200,height),top=h*(ratios.height ?? 66)/100,left=w*(ratios.width ?? 50)/100;
    const leaf=(id,group,size)=>({type:'leaf',data:{views:[id],activeView:id,id:group},size});
    return {grid:{width:w,height:h,orientation:'HORIZONTAL',root:{type:'branch',size:h,data:[
      {type:'branch',size:w,data:[leaf('volume','1',top),{type:'branch',size:h-top,data:[leaf('iq','2',left),leaf('cake','3',w-left)]}]}
    ]}},panels:Object.fromEntries(Object.entries(panels).map(([id,p])=>[id,{id,contentComponent:'DockPanel',params:{templateName:p.template},title:p.title,minimumHeight:100,minimumWidth:180}])),activeGroup:'1'};
  }
  if(typeof module !== 'undefined' && module.exports) {module.exports={validLayout,defaultLayout};return;}
  let dock;
  function initial(layout) {
    const el=document.querySelector('.dock-workspace');
    return defaultLayout(el.clientWidth,el.clientHeight,layout?.height ? layout : undefined);
  }
  function restore(layout) {
    if(dock) dock.restoreLayout(validLayout(layout) ? layout : initial(layout));
  }
  window.nimWorkspace={validLayout,
    ready(getDock) { const start=()=>Vue.nextTick(()=>{
      dock=getDock();
      restore(window.nimPreferences.getLayout());
      window.trame.state.set('workspace_ready',true);
    });
      if (window.nimPreferences?.getLayout) start();
      else window.addEventListener('nim-preferences-ready',start,{once:true});
    },
    changed(layout) { if(validLayout(layout)) { window.nimWorkspace.currentLayout=layout; window.nimPreferences.updateLayout(layout); } },
    visibility() { requestAnimationFrame(()=>window.dispatchEvent(new Event('resize'))); },
    restore,
    open(id) { if(!dock || !panels[id]) return; const p=panels[id];dock.addPanel(id,p.title,p.template,{minimumHeight:100,minimumWidth:180});dock.activePanel(id); },
    reset() { restore(null); },
  };
  window.dispatchEvent(new Event('nim-workspace-ready'));
})();
