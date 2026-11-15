const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
module.exports=async function checkCrop(){
  const values={render_level:'auto',volume_preview_mib:64};
  for(const axis of 'xyz'){values[`crop_max_${axis}`]=160;values[`crop_draft_${axis}`]={min:0,max:160};}
  const calls=[],copied=[];
  const listeners=[];
  const state={addListener:fn=>listeners.push(fn),get:key=>values[key],set:(key,val)=>{values[key]=val;}};
  const window={trame:{state},nimUpdates:{submit:(...args)=>calls.push(args)}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/tomoswaxs/assets/crop.js'),'utf8'),{
    window,navigator:{clipboard:{writeText:async text=>copied.push(text)}},
  });
  window.nimCrop.edit('x','min','40');
  assert.equal(calls.length,1,'Numeric input submits without relying on a browser change event');
  assert.equal(JSON.stringify(calls[0][1].crop),'[[40,160],[0,160],[0,160]]');
  window.nimCrop.edit('x','min','');assert.equal(calls.length,1,'Incomplete fields do not issue reads');
  window.nimCrop.edit('x','min','40');
  window.nimCrop.change('y',{min:10,max:120},true);
  assert.equal(calls.at(-1)[2],true);
  assert.equal(JSON.stringify(calls.at(-1)[1].crop),'[[40,160],[10,120],[0,160]]');
  await window.nimCrop.copy();assert.equal(copied[0],'[0:160, 10:120, 40:160]');
  window.nimCrop.change('z',{min:160,max:160},true);
  assert.equal(JSON.stringify(calls.at(-1)[1].crop[2]),'[159,160]');
  window.nimCrop.reset();
  assert.equal(JSON.stringify(calls.at(-1)[1].crop),'[[0,160],[0,160],[0,160]]');
  assert.equal(calls.at(-1)[1].level,'auto');
  values.crop_bounds=[[20,100],[30,110],[40,120]];
  listeners[0]({type:'ready'});
  assert.equal(values.crop_draft_x.min,20,'Reload reconstructs local drafts from the committed crop');
  window.nimCrop.edit('x','min','50');
  listeners[0]({type:'dirty-state',keys:['crop_bounds']});
  assert.equal(values.crop_draft_x.min,50,'An acknowledgement cannot overwrite newer local edits');
  window.nimCrop.limit('1');assert.equal(calls.at(-1)[1].limit,1);
  window.nimCrop.limit('');assert.equal(calls.at(-1)[1].limit,1,'Incomplete limits do not request reads');
};
if(require.main===module)module.exports().catch(error=>{console.error(error);process.exitCode=1;});
