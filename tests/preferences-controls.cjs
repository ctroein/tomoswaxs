/* Font sliders preview their number during input and apply once on change. */
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const elements=new Map(),listeners={},events={},windowListeners={},values={volume_preview_mib:256,has_volume:true,volume_loading:false},updates=[],stored=new Map();
stored.set('nim-uct-saxs.preferences.v1',JSON.stringify({version:1,voxelArrayMib:32}));
const element=id=>{
  if(!elements.has(id))elements.set(id,{value:'',checked:false,validity:{valid:true},textContent:'',addEventListener(){}});
  return elements.get(id);
};
const dialog={querySelector:selector=>element(selector),setAttribute(){},showModal(){this.open=true;},addEventListener:(type,fn)=>events[type]=fn};
const document={documentElement:{dataset:{},style:{}},body:{appendChild(){}},
  createElement:()=>dialog,addEventListener:(type,fn)=>listeners[type]=fn};
const state={get:key=>values[key],set:(key,value)=>{updates.push(key);values[key]=value;},addListener(){}};
const window={nimWorkspace:{validLayout:()=>false,restore(){},captureLayout(){}},
  localStorage:{getItem:key=>stored.get(key)??null,setItem:(key,value)=>stored.set(key,value)},
  matchMedia:()=>({matches:false,addEventListener(){}}),trame:{state,trigger:()=>Promise.resolve()},
  addEventListener:(name,callback)=>windowListeners[name]=callback,dispatchEvent(){}};
vm.runInNewContext(fs.readFileSync('src/tomoswaxs/assets/preferences.js','utf8'),{
  window,document,console,Event:class{},setTimeout,clearTimeout,
});
assert.equal(values.volume_preview_mib,32);
const reloads=[];window.nimCrop={submit:finished=>reloads.push(finished)};
windowListeners['nim-crop-ready']();
assert.deepEqual(reloads,[true],'Apply a saved limit after crop controls become ready');
listeners.click({target:{closest:()=>true}});
assert.equal(element('#pref-layout').checked,true);
for(const [slider,number,key,target] of [
  ['pref-scale','pref-scale-number','ui_text_scale',130],
  ['pref-plot-scale-slider','pref-plot-scale','ui_plot_scale',150],
]){
  updates.length=0;
  const previous=values[key],font=document.documentElement.style.fontSize;
  const input=element('#'+slider);input.id=slider;
  for(const value of [110,120,target]){
    input.value=String(value);events.input({target:input});
    assert.equal(element('#'+number).value,String(value));
    assert.equal(values[key],previous);
    assert.equal(document.documentElement.style.fontSize,font);
    assert.equal(updates.length,0,'Dragging must not apply preferences or resize the viewer');
  }
  events.change({target:input});
  assert.equal(values[key],target);
  assert.equal(updates.filter(k=>k===key).length,1);
  assert.equal(JSON.parse(stored.get('nim-uct-saxs.preferences.v1'))[key==='ui_text_scale'?'textScale':'plotScale'],target);
}
console.log('Font slider release checks passed.');
