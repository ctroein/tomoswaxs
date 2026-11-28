/* Run with node tests/preferences.cjs. */
const assert = require('node:assert/strict');
const {KEY,defaults,normalise,load,save,plotLayout,plotData,heatmapHoverData} = require('../src/tomoswaxs/assets/preferences.js');
module.exports = function checkPreferences() {
  assert.equal(defaults().rememberLayout,true);
  assert.equal(normalise({version:1}).rememberLayout,true);
  assert.equal(normalise({version:1,rememberLayout:false}).rememberLayout,false);
  const values = new Map();
  const storage = {getItem:key => values.get(key) ?? null,
                   setItem:(key,value) => values.set(key,value)};
  assert.deepEqual(load(storage),{prefs:defaults(),unavailable:false});
  const chosen = {rotationFps:12,rotationStep:2.5,voxelArrayMib:512,version:1,theme:'light',textScale:135,plotScale:100,showAxes:true,rememberLayout:true,
                  layout:{height:52,width:61}};
  assert.equal(save(storage,chosen),true);
  assert.deepEqual(load(storage).prefs,chosen,'Preferences must survive reload');
  assert.equal(normalise({...chosen,showAxes:undefined}).showAxes,false);
  assert.deepEqual(normalise({...chosen,rememberLayout:false}).layout,defaults().layout);
  const bad = normalise({version:1,theme:'other',textScale:Infinity,rememberLayout:true,
                         layout:{height:-20,width:200}});
  assert.equal(bad.theme,'system');
  assert.equal(bad.textScale,100);
  assert.equal(normalise({...chosen,rotationFps:Infinity}).rotationFps,20);
  assert.equal(normalise({...chosen,rotationStep:-10}).rotationStep,.1);
  for(const value of [undefined,null,0,-1,Infinity,'512'])assert.equal(normalise({...chosen,voxelArrayMib:value}).voxelArrayMib,null);
  assert.deepEqual(bad.layout,{height:35,width:75});
  assert.equal(normalise({...chosen,textScale:117}).textScale,115);
  assert.equal(normalise({...chosen,textScale:900}).textScale,160);
  assert.deepEqual(normalise({...chosen,version:99}),defaults());
  values.set(KEY,'broken JSON');
  assert.deepEqual(load(storage),{prefs:defaults(),unavailable:false});
  const disabled = {getItem() {throw Error('disabled');}, setItem() {throw Error('full');}};
  assert.deepEqual(load(disabled),{prefs:defaults(),unavailable:true});
  assert.equal(save(disabled,chosen),false);
  const originalLayout = {font:{size:12},xaxis:{range:[.1,1]},yaxis:{type:'log'}};
  const styled = plotLayout(originalLayout,'light',150);
  assert.equal(styled.font.size,21);
  assert.equal(styled.legend.font.size,21);
  assert.equal(plotLayout(originalLayout,'light',100,150).font.size,21);
  assert.equal(normalise({...chosen,plotScale:999}).plotScale,200);
  assert.equal(normalise({...chosen,plotScale:undefined}).plotScale,100);
  assert.equal(styled.paper_bgcolor,'#ffffff');
  assert.deepEqual(styled.xaxis.range,[.1,1]);
  assert.equal(styled.yaxis.type,'log');
  assert.equal(originalLayout.font.size,12,'Never mutate shared plot layout');
  const data = [{type:'scatter',x:[1,2],y:[3,4],line:{color:'red'}}];
  const lightData = plotData(data,'light',150);
  assert.equal(lightData[0].x,data[0].x,'Preserve scientific arrays');
  assert.equal(data[0].line.color,'red','Never mutate shared plot data');
  assert.equal(lightData[0].line.color,'#087e91');
  const pixels=new Float64Array([1,2,3,4,NaN,6]);
  const encoded={dtype:'f8',shape:'2, 3',bdata:Buffer.from(pixels.buffer).toString('base64')};
  const rows=heatmapHoverData(encoded);
  assert.deepEqual(Array.from(rows[0]),[1,2,3]);
  assert.ok(Number.isNaN(rows[1][1]));
  assert.ok(Array.isArray(rows[0]),'Plotly heatmap hover requires ordinary inner arrays');
  assert.equal(heatmapHoverData(encoded),rows,'Reuse decoded hover data during appearance updates');
  const styledHeat=plotData([{type:'heatmap',customdata:encoded,z:encoded}],'dark',100)[0];
  assert.equal(styledHeat.customdata[1][2],6);
  assert.equal(styledHeat.z,encoded,'Preserve the intensity display buffer');
  encoded.bdata=Buffer.from(new Float64Array([7,8,9,10,11,12]).buffer).toString('base64');
  assert.equal(heatmapHoverData(encoded)[0][0],7,'Invalidate cached rows if a frame buffer changes in place');
  assert.equal(save(storage,defaults()),true);
  assert.deepEqual(load(storage).prefs,defaults());
};
if (require.main === module) { module.exports(); console.log('Preference persistence checks passed.'); }
