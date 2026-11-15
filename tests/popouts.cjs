/* Window lifecycle checks with a deterministic Dockview API and DOM fixture. */
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
module.exports=async function checkPopouts(){
  const values={workspace_busy:[],workspace_error:'',workspace_tabs:[],workspace_detached:[]};
  const callbacks={},childEvents={},locationListeners=new Set();
  let subscriptions=0;
  let observer,attached=0,detached=0,closed=0,openedPanel,openResult=true;
  const root={dataset:{theme:'light'},style:{fontSize:'16px'}};
  const child={closed:false,document:{documentElement:{dataset:{},style:{}},querySelector:()=>({classList:{add(){}}})},
    addEventListener:(key,fn)=>{childEvents[key]=fn;},removeEventListener:key=>{delete childEvents[key];}};
  const mainGroup={id:'main-return',api:{location:{type:'grid'}}};
  const panelApi={id:'cake',title:'SAXS cake',location:{type:'grid'},
    onDidLocationChange(fn){locationListeners.add(fn);return {dispose:()=>locationListeners.delete(fn)};},
    moveTo(position){assert.equal(position.group,mainGroup,'Panel moves require an explicit main-grid group');assert.equal(position.position,'center');closed++;this.location={type:'grid'};for(const fn of locationListeners)fn();},
  };
  const panel={id:'cake',api:panelApi};
  const api={panels:[panel],addGroup:options=>{assert.equal(options.direction,'right');return mainGroup;},getPanel:id=>{assert.equal(id,'cake');return panel;},
    onDidAddPopoutGroup(fn){subscriptions++;callbacks.add=fn;return{dispose(){}};},
    onDidRemovePopoutGroup(fn){callbacks.remove=fn;return{dispose(){}};},
    async addPopoutGroup(p,options){
      openedPanel=p;assert.equal(options.popoutUrl,'/nim-assets/popout.html');
      if(openResult==='early-close') { options.onWillClose();return new Promise(()=>{}); }
      if(openResult instanceof Error)throw openResult;
      if(!openResult)return false;
      panelApi.location={type:'popout'};callbacks.add({window:child});
      for(const fn of locationListeners)fn();return true;
    },
  };
  const window={trame:{state:{get:key=>values[key],set:(key,val)=>{values[key]=val;}}},
    nimBeam:{attach:doc=>{assert.equal(doc,child.document);attached++;return()=>{detached++;};}},
    addEventListener:(key,fn)=>{callbacks[key]=fn;},dispatchEvent(){},
  };
  const document={documentElement:root};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/tomoswaxs/assets/workspace.js'),'utf8'),{
    window,document,MutationObserver:class{constructor(fn){observer=fn;}observe(){}disconnect(){}},
    setTimeout,clearTimeout,requestAnimationFrame:fn=>fn(),Event:class{},console:{error(){}},
  });
  const params={api:panelApi,containerApi:api};
  const element={closest:()=>({setAttribute(){}})};
  window.nimWorkspace.mountTab(element,params);
  const otherElement={closest:()=>({setAttribute(){}})};
  window.nimWorkspace.mountTab(otherElement,{...params,containerApi:{...api}});
  assert.equal(subscriptions,1,'Panel API facades share one workspace lifecycle subscription');
  window.nimWorkspace.unmountTab(otherElement);
  await window.nimWorkspace.popout(params);
  assert.equal(openedPanel,panel,'Detach the requested panel, not the whole tab group');
  assert.deepEqual(Array.from(values.workspace_detached),['cake']);
  assert.equal(values.workspace_error,'');
  assert.equal(attached,1);
  assert.equal(child.document.documentElement.dataset.theme,'light');
  assert.equal(child.document.documentElement.style.fontSize,'16px');
  root.dataset.theme='dark';root.style.fontSize='18px';observer();
  assert.equal(child.document.documentElement.dataset.theme,'dark');
  assert.equal(child.document.documentElement.style.fontSize,'18px');
  await window.nimWorkspace.popout(params);
  assert.equal(closed,1);
  assert.equal(values.workspace_detached.length,0);
  childEvents.pagehide();
  assert.equal(detached,1);
  assert.equal(childEvents.resize,undefined);
  openResult=false;
  await window.nimWorkspace.popout(params);
  assert.match(values.workspace_error,/allows popups/);
  assert.equal(panelApi.location.type,'grid');
  assert.equal(values.workspace_busy.length,0);
  openResult='early-close';
  await window.nimWorkspace.popout(params);
  assert.match(values.workspace_error,/closed before/);
  assert.equal(values.workspace_busy.length,0);
  openResult=new Error('closed during load');
  await window.nimWorkspace.popout(params);
  assert.match(values.workspace_error,/Could not move/);
  assert.equal(values.workspace_busy.length,0);
  window.nimWorkspace.unmountTab(element);
  assert.equal(locationListeners.size,0);
  callbacks.pagehide();
};
if(require.main===module)module.exports().catch(error=>{console.error(error);process.exitCode=1;});
