/* Run with node tests/beam_input.cjs; no third-party packages needed. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {createLatestUpdates} = require('../src/tomoswaxs/assets/updates.js');

function fixture() {
  const handlers = {}, calls = [], resolvers = [];
  const element = {
    getBoundingClientRect: () => ({left:10, top:20, width:100, height:200}),
    setPointerCapture() {},
  };
  const context = {
    document: {addEventListener: (name, callback, capture) => {
      handlers[name] = callback;
      assert.equal(capture, true, 'Pointer events must be intercepted before VTK');
    }},
    window: {trame: {trigger: (...args) => {
      calls.push(args);
      return new Promise(resolve => resolvers.push(resolve));
    }}},
    performance: {now: () => 1000}, clearTimeout() {}, setTimeout: () => 1, console,
  };
  context.window.nimUpdates=createLatestUpdates((kind,value)=>context.window.trame.trigger('nim_beam_position',value),
    {now:()=>1000,setTimer:()=>1,clearTimer(){}});
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/tomoswaxs/assets/beam.js'),'utf8'),context);
  function event(type, x, y, options={}) {
    const opts = {viewport:true, ...options};
    return {type, clientX:x, clientY:y, pointerId:1, button:0,
            altKey:false, shiftKey:false, ctrlKey:false, metaKey:false, ...opts,
            preventDefault() { this.prevented = true; },
            stopImmediatePropagation() { this.stopped = true; },
            target:{closest: selector => {
              if (selector === '#volume-interaction') return opts.viewport ? element : null;
              return null;
            }}};
  }
  async function resolve() {
    resolvers.shift()();
    await new Promise(setImmediate);
  }
  return {handlers, calls, event, resolve,beam:context.window.nimBeam};
}

module.exports = async function checkBeamInput() {
  const {handlers, calls, event, resolve} = fixture();
  handlers.pointermove(event('pointermove',25,50));
  assert.equal(calls.length,0,'Hover must send no RPC');
  handlers.pointerdown(event('pointerdown',25,50,{altKey:true,shiftKey:true}));
  for (let i=0;i<1000;i++) handlers.pointermove(event('pointermove',i,i));
  assert.equal(calls.length,1,'Only one RPC may be in flight');
  handlers.pointerup(event('pointerup',60,120));
  assert.equal(calls.length,1,'Release must wait for outstanding RPC');
  await resolve();
  assert.equal(calls.length,2,'Backlog must collapse to the final position');
  assert.equal(JSON.stringify(calls[1]),JSON.stringify(['nim_beam_position',[.5,.5,true,true]]));
  await resolve();
  handlers.pointermove(event('pointermove',70,150));
  assert.equal(calls.length,2,'No stale events or hover RPCs after release');

  const second=fixture(),otherHandlers={};
  const otherDocument={addEventListener:(key,fn)=>{otherHandlers[key]=fn;},removeEventListener:key=>{delete otherHandlers[key];}};
  const off=second.beam.attach(otherDocument);
  assert.equal(second.beam.attach(otherDocument),off,'Bind a document only once');
  otherHandlers.pointerdown(second.event('pointerdown',25,50,{altKey:true,shiftKey:true}));
  otherHandlers.pointerup(second.event('pointerup',60,120));
  await second.resolve();await second.resolve();
  assert.equal(second.calls.length,2,'Beam gestures in the second document use the shared queue');
  off();assert.equal(Object.keys(otherHandlers).length,0);

  const shortcut = fixture();
  for (const modifiers of [{}, {shiftKey:true}, {ctrlKey:true},
                           {ctrlKey:true,shiftKey:true}, {altKey:true},
                           {altKey:true,shiftKey:true,ctrlKey:true},
                           {altKey:true,shiftKey:true,viewport:false}]) {
    const e = shortcut.event('pointerdown',25,50,{...modifiers});
    shortcut.handlers.pointerdown(e);
    assert.equal(shortcut.calls.length,0,'Other gestures must reach VTK unchanged');
    assert.equal(e.stopped,undefined);
  }
  const down = shortcut.event('pointerdown',25,50,{altKey:true,shiftKey:true});
  shortcut.handlers.pointerdown(down);
  assert.equal(down.stopped,true);
  assert.equal(shortcut.calls.length,1);
  // Modifiers may be released first: keep the drag operation until mouse-up.
  shortcut.handlers.pointermove(shortcut.event('pointermove',50,100,{}));
  shortcut.handlers.pointerup(shortcut.event('pointerup',60,120,{}));
  await shortcut.resolve();
  assert.equal(JSON.stringify(shortcut.calls[1]),JSON.stringify(['nim_beam_position',[.5,.5,true,true]]));
  await shortcut.resolve();
  assert.equal(shortcut.calls.length,2);
  assert.equal(handlers.keydown,undefined,'Do not intercept keyboard shortcuts such as Ctrl+arrow');
  console.log('Beam queue and Alt+Shift capture checks passed.');
};
if (require.main === module) module.exports().catch(error => { console.error(error); process.exitCode=1; });
