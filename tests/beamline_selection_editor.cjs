const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const editor=require('../tools/beamline_selection_editor.js');
const regions=JSON.parse(fs.readFileSync(path.join(__dirname,'../tools/beamline_regions.json'))).regions_cad_mm;
const triangles=[
  [[0,995,-660],[1,1139,-660],[0,1139,-659]],
  [[0,1190,-660],[1,1207,-660],[0,1190,-659]],
  [[250,325,-450],[251,325,-450],[250,326,-450]],
];
const points=triangles.flat();
const trace=Object.fromEntries('xyz'.split('').map((key,axis)=>[key,points.map(p=>p[axis])]));
for(const [axis,key] of ['i','j','k'].entries())trace[key]=triangles.map((_,n)=>3*n+axis);
const config={sourceMeshCount:1,sample:[0,0,0],rotation:[[1,0,0],[0,1,0],[0,0,1]]};
const geometry=editor.geometry([trace],config);
const groups=editor.classify(geometry,Object.values(regions));
assert.deepEqual(groups.map(g=>g.i.length),[1,0,1,0,1]);
assert.deepEqual(JSON.parse(editor.exportCoordinates(Object.keys(regions),Object.values(regions))).regions_cad_mm,regions);
assert.equal(editor.outline(regions['upstream beam pipe']).x.filter(x=>x===null).length,12);
console.log('Beamline editor: triangle containment and coordinate export passed.');
