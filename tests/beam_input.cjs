/* Run with node tests/beam_input.cjs; no third-party packages needed. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

module.exports = async function checkBeamInput() {
  const handlers = {};
  const calls = [];
  const resolvers = [];
  const element = {
    getBoundingClientRect: () => ({left: 10, top: 20, width: 100, height: 200}),
    setPointerCapture: () => {},
  };
  const context = {
    document: { addEventListener: (name, callback) => { handlers[name] = callback; } },
    window: { trame: { trigger: (...args) => {
      calls.push(args);
      return new Promise(resolve => resolvers.push(resolve));
    }}},
    performance: {now: () => 1000},
    clearTimeout: () => {},
    setTimeout: () => 1,
    console,
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../assets/beam.js'),'utf8'),context);
  function event(type, x, y) {
    return {type, clientX:x, clientY:y, pointerId:1, button:0,
            preventDefault() {}, target:{closest: () => element}};
  }
  handlers.pointermove(event('pointermove',25,50));
  assert.equal(calls.length,0,'Hover must send no RPC');
  handlers.pointerdown(event('pointerdown',25,50));
  for (let i=0;i<1000;i++) handlers.pointermove(event('pointermove',i,i));
  assert.equal(calls.length,1,'Only one RPC may be in flight');
  handlers.pointerup(event('pointerup',60,120));
  assert.equal(calls.length,1,'Release must wait for outstanding RPC');
  resolvers.shift()();
  await new Promise(setImmediate);
  assert.equal(calls.length,2,'Backlog must collapse to the final position');
  assert.equal(JSON.stringify(calls[1]),JSON.stringify(['nim_beam_position',[.5,.5,true]]));
  resolvers.shift()();
  await new Promise(setImmediate);
  assert.equal(calls.length,2,'No stale events after release');
  handlers.pointermove(event('pointermove',70,150));
  assert.equal(calls.length,2,'Post-release hover must send no RPC');
  console.log('Beam input: 1000 moves coalesced; final release retained; hover silent.');
};
if (require.main === module) module.exports().catch(error => { console.error(error); process.exitCode = 1; });
