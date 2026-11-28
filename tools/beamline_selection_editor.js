(function () {
  'use strict';
  function numbers(value) {
    if (ArrayBuffer.isView(value) || Array.isArray(value)) return value;
    if (!value || !value.bdata) throw Error('Could not read preview geometry.');
    const bytes=Uint8Array.from(atob(value.bdata),c=>c.charCodeAt(0));
    const Type={f4:Float32Array,f8:Float64Array,i4:Int32Array,u4:Uint32Array,i2:Int16Array,u2:Uint16Array}[value.dtype];
    if (!Type) throw Error('Unsupported geometry encoding.');
    return new Type(bytes.buffer);
  }
  function geometry(traces,config) {
    const parts=traces.slice(0,config.sourceMeshCount || 4).map(trace=>Object.fromEntries(['x','y','z','i','j','k'].map(k=>[k,numbers(trace[k])])));
    const count=parts.reduce((n,p)=>n+p.x.length,0), faces=parts.reduce((n,p)=>n+p.i.length,0);
    const g={x:new Float32Array(count),y:new Float32Array(count),z:new Float32Array(count),
             i:new Int32Array(faces),j:new Int32Array(faces),k:new Int32Array(faces)};
    let offset=0,faceOffset=0;
    for (const p of parts) {
      for (let n=0;n<p.x.length;n++) {
        const lab=[p.x[n],p.y[n],p.z[n]];
        for(let axis=0;axis<3;axis++)g['xyz'[axis]][offset+n]=config.sample[axis]+config.rotation.reduce((s,row,r)=>s+row[axis]*lab[r],0);
      }
      for(let n=0;n<p.i.length;n++)for(const key of ['i','j','k'])g[key][faceOffset+n]=p[key][n]+offset;
      offset+=p.x.length;faceOffset+=p.i.length;
    }
    g.low=['x','y','z'].map(key=>g[key].reduce((a,b)=>Math.min(a,b),Infinity));
    g.high=['x','y','z'].map(key=>g[key].reduce((a,b)=>Math.max(a,b),-Infinity));
    return g;
  }
  function insidePoint(g,n,box) {
    return g.x[n]>=box[0][0] && g.x[n]<=box[1][0] && g.y[n]>=box[0][1] && g.y[n]<=box[1][1] && g.z[n]>=box[0][2] && g.z[n]<=box[1][2];
  }
  function classify(g,boxes) {
    const group=new Uint8Array(g.i.length),counts=Array(boxes.length+1).fill(0);
    for(let n=0;n<g.i.length;n++) {
      for(let b=0;b<boxes.length;b++) {
        if(insidePoint(g,g.i[n],boxes[b]) && insidePoint(g,g.j[n],boxes[b]) && insidePoint(g,g.k[n],boxes[b]))group[n]=b+1;
      }
      counts[group[n]]++;
    }
    const result=counts.map(count=>({i:new Int32Array(count),j:new Int32Array(count),k:new Int32Array(count)}));
    const at=Array(boxes.length+1).fill(0);
    for(let n=0;n<group.length;n++) {
      const b=group[n],p=at[b]++;
      result[b].i[p]=g.i[n];result[b].j[p]=g.j[n];result[b].k[p]=g.k[n];
    }
    return result;
  }
  function outline(box) {
    const corners=[];
    for(const x of [box[0][0],box[1][0]])for(const y of [box[0][1],box[1][1]])for(const z of [box[0][2],box[1][2]])corners.push([x,y,z]);
    const points=[];
    for(let a=0;a<8;a++)for(let b=a+1;b<8;b++)if([1,2,4].includes(a^b))points.push(corners[a],corners[b],[null,null,null]);
    return Object.fromEntries(['x','y','z'].map((key,axis)=>[key,points.map(p=>p[axis])]));
  }
  function exportCoordinates(names,boxes) {
    return JSON.stringify({regions_cad_mm:Object.fromEntries(names.map((name,index)=>[name,boxes[index]]))},null,2);
  }
  if(typeof module!=='undefined' && module.exports) {
    module.exports={numbers,geometry,classify,outline,exportCoordinates};return;
  }
  async function start() {
    await window.selectionPlotReady;
    const config=JSON.parse(document.getElementById('selection-config').textContent);
    const plot=document.getElementById('model'),g=geometry(plot._fullData || plot.data,config);
    const initial=config.boxes.map(box=>box.map(row=>row.slice()));
    let boxes=initial.map(box=>box.map(row=>row.slice())),selected=config.initialSelected || 0,revision=0,rendering=false,timer=null;
    const region=document.getElementById('region'),output=document.getElementById('coordinates'),status=document.getElementById('status');
    const axisNames=['X','Y','Z'];
    const meshIds=Array.from({length:boxes.length+1},(_,n)=>n);
    const outlineIds=boxes.map((_,n)=>meshIds.length+n);
    const ids=axisNames.map((_,axis)=>[0,1].map(side=>({number:document.getElementById(`number-${axis}-${side}`),slider:document.getElementById(`range-${axis}-${side}`)})));
    const sliderLimits=initial.map(box=>axisNames.map((_,axis)=>{
      const margin=Math.max(50,(box[1][axis]-box[0][axis])*.5);
      return [Math.floor(Math.max(box[0][axis]-margin,g.low[axis])),Math.ceil(Math.min(box[1][axis]+margin,g.high[axis]))];
    }));
    config.names.forEach((name,index)=>{const option=document.createElement('option');option.value=index;option.textContent=config.labels[index];region.appendChild(option);});
    region.value=String(selected);
    function updateControls() {
      for(let axis=0;axis<3;axis++) {
        const low=Math.min(sliderLimits[selected][axis][0],boxes[selected][0][axis]);
        const high=Math.max(sliderLimits[selected][axis][1],boxes[selected][1][axis]);
        for(let side=0;side<2;side++) {
          const pair=ids[axis][side];pair.number.value=boxes[selected][side][axis];
          pair.slider.min=low;pair.slider.max=high;pair.slider.value=boxes[selected][side][axis];
          pair.slider.style.setProperty('--region-colour',config.colours[selected]);
        }
        const track=document.getElementById(`fill-${axis}`);
        track.style.left=`${100*(boxes[selected][0][axis]-low)/(high-low)}%`;
        track.style.width=`${100*(boxes[selected][1][axis]-boxes[selected][0][axis])/(high-low)}%`;
        track.style.background=config.colours[selected];
      }
      document.getElementById('region-swatch').style.background=config.colours[selected];
      output.value=exportCoordinates(config.names,boxes);
    }
    function edit(axis,side,value,slider) {
      const n=Number(value);
      if(value.trim()==='' || !Number.isFinite(n))return;
      if(slider)boxes[selected][side][axis]=side===0?Math.min(n,boxes[selected][1][axis]-1):Math.max(n,boxes[selected][0][axis]+1);
      else {
        if(side===0 ? n>=boxes[selected][1][axis] : n<=boxes[selected][0][axis]) {
          status.textContent='The lower bound must be smaller than the upper bound.';return;
        }
        boxes[selected][side][axis]=n;
      }
      revision++;updateControls();schedule();
    }
    function schedule() {
      clearTimeout(timer);timer=setTimeout(render,90);
    }
    async function render() {
      if(rendering)return;
      rendering=true;plot.setAttribute('aria-busy','true');status.textContent='Updating…';
      try {
        do {
          const current=revision;
          const grouped=classify(g,boxes),lines=boxes.map(outline);
          const empty=new Float32Array(0);
          await Plotly.restyle(plot,{x:grouped.map(p=>p.i.length?g.x:empty),y:grouped.map(p=>p.i.length?g.y:empty),z:grouped.map(p=>p.i.length?g.z:empty),
                                    i:grouped.map(p=>p.i),j:grouped.map(p=>p.j),k:grouped.map(p=>p.k)},meshIds);
          await Plotly.restyle(plot,{x:lines.map(p=>p.x),y:lines.map(p=>p.y),z:lines.map(p=>p.z)},outlineIds);
          if(revision===current)break;
        }while(true);
        status.textContent='';
      }catch(error){status.textContent='Could not update the preview: '+error.message;}
      finally{rendering=false;plot.setAttribute('aria-busy','false');}
    }
    function camera(detail,side=false) {
      const centre=g.low.map((lo,a)=>(lo+g.high[a])/2),span=Math.max(...g.high.map((hi,a)=>hi-g.low[a]));
      const active=boxes[selected];
      const target=detail?active[0].map((lo,a)=>((lo+active[1][a])/2-centre[a])/span):[0,0,0];
      const direction=detail?(side?[.95,0,.2]:[-.55,.7,.45]):[-1.4,1.6,.9];
      return {center:Object.fromEntries('xyz'.split('').map((k,a)=>[k,target[a]])),eye:Object.fromEntries('xyz'.split('').map((k,a)=>[k,target[a]+direction[a]])),up:{x:0,y:0,z:1}};
    }
    region.addEventListener('change',()=>{selected=Number(region.value);status.textContent='';updateControls();});
    for(let axis=0;axis<3;axis++)for(let side=0;side<2;side++) {
      const pair=ids[axis][side];
      pair.number.addEventListener('change',event=>edit(axis,side,event.target.value,false));
      pair.number.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();edit(axis,side,event.target.value,false);}});
      pair.slider.addEventListener('input',event=>edit(axis,side,event.target.value,true));
    }
    document.getElementById('reset-box').onclick=()=>{boxes[selected]=initial[selected].map(row=>row.slice());revision++;updateControls();schedule();};
    document.getElementById('reset-all').onclick=()=>{boxes=initial.map(box=>box.map(row=>row.slice()));revision++;updateControls();schedule();};
    document.getElementById('detail').onclick=()=>Plotly.relayout(plot,{'scene.camera':camera(true)});
    document.getElementById('side').onclick=()=>Plotly.relayout(plot,{'scene.camera':camera(true,true)});
    document.getElementById('overview').onclick=()=>Plotly.relayout(plot,{'scene.camera':camera(false)});
    document.getElementById('ghost').onchange=event=>Plotly.restyle(plot,{opacity:event.target.checked ? .12 : 1},[0]);
    document.getElementById('boxes').onchange=event=>Plotly.restyle(plot,{visible:event.target.checked},outlineIds);
    document.getElementById('copy').onclick=async()=>{
      const text=exportCoordinates(config.names,boxes);output.value=text;
      try{await navigator.clipboard.writeText(text);status.textContent='Coordinates copied.';}
      catch{
        output.focus();output.select();
        try{status.textContent=document.execCommand('copy')?'Coordinates copied.':'Coordinates selected for copying.';}
        catch{status.textContent='Coordinates selected for copying.';}
      }
    };
    document.getElementById('save').onclick=()=>{
      const url=URL.createObjectURL(new Blob([exportCoordinates(config.names,boxes)+'\n'],{type:'application/json'}));
      const a=document.createElement('a');a.href=url;a.download='beamline-selection.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
    updateControls();
    await render();
    await Plotly.relayout(plot,{'scene.xaxis.title.text':'CAD X (mm)','scene.yaxis.title.text':'CAD Y (mm)',
                               'scene.zaxis.title.text':'CAD Z (mm)','scene.camera':camera(true),
                               'scene.xaxis.autorange':true,'scene.yaxis.autorange':true,'scene.zaxis.autorange':true});
    document.getElementById('controls').disabled=false;
  }
  start().catch(error=>{document.getElementById('status').textContent='Could not initialise the editor: '+error.message;});
})();
