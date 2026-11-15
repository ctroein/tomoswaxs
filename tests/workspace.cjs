const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const {defaultLayout,validLayout,mainWindowLayout}=require('../src/tomoswaxs/assets/workspace.js');
module.exports=function checkWorkspace(){
  const layout=defaultLayout(1200,600);
  assert.equal(validLayout(layout),true);
  assert.equal(layout.grid.root.data[0].data[0].size,396);
  assert.equal(layout.grid.root.data[0].data[1].data[0].size,420);
  assert.deepEqual(Object.keys(layout.panels),['volume','iq','cake','crop','resolution']);
  assert.equal(validLayout(null),false);
  assert.equal(validLayout({grid:{},panels:{}}),false);
  const invalid=JSON.parse(JSON.stringify(layout));
  invalid.panels.iq.params.templateName='wrong_template';
  assert.equal(validLayout(invalid),false);
  const grouped=JSON.parse(JSON.stringify(layout));
  grouped.grid.root.data[0].data[1].data=[{type:'leaf',size:1200,data:{id:'2',views:['iq','cake'],activeView:'cake'}}];
  assert.equal(validLayout(grouped),true);
  const detached=JSON.parse(JSON.stringify(layout));
  detached.grid.root.data[0].data[1].data.pop();
  detached.popoutGroups=[{data:{id:'4',views:['cake'],activeView:'cake'},url:'/nim-assets/popout.html'}];
  const restoredDetached=mainWindowLayout(detached);
  assert.equal(restoredDetached.popoutGroups,undefined);
  assert.equal(validLayout(restoredDetached),true);
  assert.equal(restoredDetached.grid.root.data.at(-1).data.views[0],'cake');
  assert.equal(detached.popoutGroups.length,1,'Do not mutate the live layout');
  assert.deepEqual(mainWindowLayout(layout),layout);
  const allDetached={grid:{width:1200,height:600,orientation:'HORIZONTAL',root:{type:'branch',data:[]}},panels:layout.panels,popoutGroups:[{url:'javascript:bad'}]};
  assert.equal(mainWindowLayout(allDetached).grid.root.data.length,5);
  const {save,load}=require('../src/tomoswaxs/assets/preferences.js');
  let encoded;
  const storage={setItem:(_,value)=>{encoded=value;},getItem:()=>encoded};
  save(storage,{version:1,rememberLayout:true,layout:grouped});
  assert.deepEqual(load(storage).prefs.layout,grouped);
  for(const order of [['workspace.js','preferences.js'],['preferences.js','workspace.js']]) {
    const events=new Map(),values={},stateListeners=[];let restored; const actions=[];
    const window={localStorage:{getItem:()=>null,setItem(){}},matchMedia:()=>({matches:false,addEventListener(){}}),
      addEventListener(type,fn,options={}) {const entries=events.get(type)||[];entries.push({fn,once:options.once});events.set(type,entries);},
      dispatchEvent(event) {for(const entry of [...(events.get(event.type)||[])]) {if(entry.once)events.set(event.type,events.get(event.type).filter(e=>e!==entry));entry.fn(event);}},
      trame:{state:{get:key=>values[key],set(key,value){values[key]=value;for(const fn of stateListeners)fn({type:'dirty-state',keys:[key]});},addListener:fn=>stateListeners.push(fn)},trigger:()=>Promise.resolve()},
    };
    const document={documentElement:{dataset:{},style:{}},addEventListener(){},querySelector:()=>({clientWidth:1200,clientHeight:600})};
    const context=vm.createContext({window,document,MutationObserver:class{observe(){} disconnect(){}},Vue:{nextTick:fn=>fn()},Event:class{constructor(type){this.type=type;}},setTimeout:()=>1,clearTimeout(){},requestAnimationFrame:fn=>fn(),console});
    let ready=false;
    for(const name of order) {
      vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/tomoswaxs/assets',name),'utf8'),context);
      if(window.nimWorkspace && !ready) {ready=true;window.nimWorkspace.ready(()=>({restoreLayout:layout=>{restored=layout;},removePanel:id=>actions.push(['close',id]),addPanel:id=>actions.push(['open',id]),activePanel:()=>{}}));}
    }
    assert.ok(restored,`Workspace initializes when scripts load as ${order}`);
    assert.equal(validLayout(restored),true);
    assert.equal(values.workspace_ready,true);
    assert.deepEqual(Array.from(values.workspace_tabs),['volume','iq','cake','crop','resolution']);
    window.nimWorkspace.toggle('cake');
    assert.deepEqual(actions.pop(),['close','cake']);
    assert.deepEqual(Array.from(values.workspace_tabs),['volume','iq','crop','resolution']);
    window.nimWorkspace.toggle('cake');
    assert.deepEqual(actions.pop(),['open','cake']);
    window.nimWorkspace.removed('iq');
    assert.deepEqual(Array.from(values.workspace_tabs),['volume','crop','resolution','cake']);
    window.nimWorkspace.changed(grouped);
    assert.deepEqual(Array.from(values.workspace_tabs),['volume','iq','cake','crop','resolution']);
    assert.equal(document.documentElement.dataset.theme,'light');
  }

};
if(require.main===module)module.exports();
