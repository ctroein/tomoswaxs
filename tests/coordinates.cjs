const assert = require('node:assert/strict');
const fs=require('node:fs'), vm=require('node:vm'), path=require('node:path');
const {createLatestUpdates} = require('../src/nim_ct_saxs/assets/updates.js');
const {wrapAngle,createRotation,createPixelSizes} = require('../src/nim_ct_saxs/assets/coordinates.js');
module.exports = async function checkCoordinates() {
  assert.equal(wrapAngle(185),-175);
  assert.equal(wrapAngle(-185),175);
  assert.equal(wrapAngle(180),180);
  assert.equal(wrapAngle(1085),5);
  let clock=0, angle=179, callback, cancelled=false, playing=false, finals=0;
  const rotation=createRotation({getAngle:()=>angle,setAngle:value=>{angle=value;},
    setPlaying:value=>{playing=value;},finish:()=>{finals++;},now:()=>clock,
    setTimer:fn=>{callback=fn;return 1;},clearTimer:()=>{cancelled=true;}});
  rotation.play();
  clock=200;callback();
  assert.equal(angle,-175);
  clock=1200;callback();
  assert.equal(angle,-145,'Rotation uses elapsed time, not queued ticks');
  rotation.pause();
  assert.equal(playing,false);
  assert.equal(cancelled,true);
  assert.equal(finals,1);
  clock=2000;callback();
  assert.equal(angle,-145,'Paused callbacks cannot move the sample');

  let frequency=10, step=2, delay;
  clock=0;angle=0;
  const adjustable=createRotation({getSettings:()=>({frequency,step}),getAngle:()=>angle,
    setAngle:value=>{angle=value;},setPlaying:value=>{playing=value;},finish(){},now:()=>clock,
    setTimer:(fn,ms)=>{callback=fn;delay=ms;return 1;},clearTimer(){}});
  adjustable.play();
  assert.equal(delay,100);
  clock=100;callback();assert.equal(angle,2);
  frequency=40;step=.5;adjustable.configure();
  assert.equal(delay,25);
  clock=125;callback();assert.equal(angle,2.5);
  clock=1125;callback();assert.equal(angle,22.5,'Late ticks advance to the current pose without replaying missed frames');
  frequency=0;adjustable.configure();assert.equal(playing,false,'Invalid playback settings pause rotation');

  const sizes={sample_voxel_x:2,sample_voxel_y:3,sample_voxel_z:5,sample_voxel_linked:true};
  const linked=createPixelSizes({get:key=>sizes[key],set:(key,value)=>{sizes[key]=value;}});
  linked.begin('sample');sizes.sample_voxel_x=4;linked.change('sample','x','4');
  assert.deepEqual([sizes.sample_voxel_x,sizes.sample_voxel_y,sizes.sample_voxel_z],[4,6,10]);
  linked.begin('sample');sizes.sample_voxel_y=3;linked.change('sample','y','3');
  assert.deepEqual([sizes.sample_voxel_x,sizes.sample_voxel_y,sizes.sample_voxel_z],[2,3,5]);
  sizes.sample_voxel_linked=false;linked.begin('sample');sizes.sample_voxel_z=8;linked.change('sample','z','8');
  assert.deepEqual([sizes.sample_voxel_x,sizes.sample_voxel_y,sizes.sample_voxel_z],[2,3,8]);
  sizes.sample_voxel_linked=true;linked.begin('sample');
  assert.deepEqual([sizes.sample_voxel_x,sizes.sample_voxel_y,sizes.sample_voxel_z],[2,3,8],'Locking preserves existing dimensions');
  sizes.sample_voxel_z=4;linked.change('sample','z','4');
  assert.deepEqual([sizes.sample_voxel_x,sizes.sample_voxel_y,sizes.sample_voxel_z],[1,1.5,4]);
  linked.begin('sample');sizes.sample_voxel_x=0;linked.change('sample','x','0');linked.begin('sample');
  sizes.sample_voxel_x=2;linked.change('sample','x','2');
  assert.deepEqual([sizes.sample_voxel_x,sizes.sample_voxel_y,sizes.sample_voxel_z],[2,3,8],'An invalid edit preserves the last valid ratio');

  const values={beam_x:250,beam_y:0,angle:35,draft_x:250,draft_y:0,draft_angle:0,rotation_playing:false};
  const listeners=[], submitted=[], handlers={};
  const state={get:key=>values[key],addListener:fn=>listeners.push(fn),set(key,value){
    if(values[key] === value)return;
    values[key]=value;
    listeners.forEach(fn=>fn({type:'dirty-state',keys:[key]}));
  }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/nim_ct_saxs/assets/coordinates.js'),'utf8'),{
    window:{trame:{state},nimUpdates:{submit:(kind,value)=>submitted.push([kind,value])}},
    document:{addEventListener:(name,fn)=>{handlers[name]=fn;},hidden:false},
    performance:{now:()=>0},setTimeout:()=>1,clearTimeout(){},console,
  });
  assert.equal(values.draft_angle,35,'Initial drafts follow the current server pose');
  assert.equal(submitted.length,0,'Initial sync must not submit a pose');
  state.set('draft_x','1000');
  state.set('beam_x',500);
  assert.equal(values.draft_x,'1000','An old acknowledgement must not overwrite newer input');
  state.set('beam_x',1000);
  assert.equal(values.draft_x,1000);
  state.set('draft_angle',185);
  assert.equal(values.draft_angle,-175);
  assert.equal(submitted.at(-1)[1].values.angle,-175);
  state.set('angle',170);
  assert.equal(values.draft_angle,-175);
  state.set('angle',-175);
  state.set('draft_x','0');
  state.set('draft_x','');
  state.set('beam_x',0);
  assert.equal(values.draft_x,'','Preserve an in-progress numeric edit');
  state.set('sample_context','next-sample');
  assert.equal(values.draft_x,0,'A new sample discards unfinished drafts from the previous sample');
  assert.equal(handlers.keydown,undefined);

  let sent=0, queueClock=0, requestedFrequency=2, retry;
  const paced=createLatestUpdates(async()=>{sent++;}, {
    now:()=>queueClock,interval:()=>1000/requestedFrequency,
    setTimer:fn=>{retry=fn;return 1;},clearTimer(){},
  });
  paced.submit('pose',{values:{angle:1}});
  await new Promise(setImmediate);
  queueClock=100;paced.submit('pose',{values:{angle:2}});
  assert.equal(sent,1);
  requestedFrequency=20;queueClock=150;retry();
  assert.equal(sent,2,'Playback frequency replaces the fixed interaction interval');
  await new Promise(setImmediate);

  const calls=[], resolvers=[];
  const queue=createLatestUpdates((kind,value)=>{
    calls.push([kind,value]);return new Promise(resolve=>resolvers.push(resolve));
  },{now:()=>1000,setTimer:()=>1,clearTimer(){}});
  queue.submit('pose',{values:{angle:1},finished:false});
  for(let i=2;i<=1000;i++) queue.submit('pose',{values:{angle:i},finished:false});
  queue.submit('pose',{values:{beam_x:500},finished:false});
  queue.submit('pose',{values:{beam_y:-200},finished:true},true);
  queue.submit('beam',[.5,.5,true,true],true);
  assert.equal(calls.length,1,'Controls and pointer share one in-flight request');
  resolvers.shift()();await new Promise(setImmediate);
  assert.deepEqual(calls[1],['pose',{values:{angle:1000,beam_x:500,beam_y:-200},finished:true}]);
  resolvers.shift()();await new Promise(setImmediate);
  assert.equal(calls[2][0],'beam','Pending pointer update is serviced after the latest pose');
  resolvers.shift()();await new Promise(setImmediate);
  assert.equal(calls.length,3,'No stale frames remain after final positions');

  let sample='first';
  const tagged=[],complete=[];
  const taggedQueue=createLatestUpdates((kind,value,context)=>{
    tagged.push({kind,value,context});return new Promise(resolve=>complete.push(resolve));
  },{context:()=>sample,now:()=>1000,setTimer:()=>1,clearTimer(){}});
  taggedQueue.submit('pose',{values:{angle:1},finished:false});
  taggedQueue.submit('pose',{values:{beam_x:400},finished:false});
  sample='second';
  taggedQueue.submit('pose',{values:{angle:37},finished:true},true);
  complete.shift()();await new Promise(setImmediate);
  assert.deepEqual(tagged[1],{kind:'pose',value:{values:{angle:37},finished:true},context:'second'},
    'Pending values must never merge across sample contexts');
  complete.shift()();await new Promise(setImmediate);
};
if(require.main===module)module.exports().then(()=>console.log('Coordinate checks passed.')).catch(e=>{console.error(e);process.exitCode=1;});
