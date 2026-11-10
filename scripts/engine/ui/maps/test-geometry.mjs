import assert from 'node:assert/strict';
import { anchorPoint, nodeRect, straightGeometry } from './parallel-edges.js';
import { addBend, removeBend, orientRoute, routeGeometry, moveSingleBend, moveRoute } from './orthogonal-route.js';
const normals={left:{x:-1,y:0},right:{x:1,y:0},top:{x:0,y:-1},bottom:{x:0,y:1}};
const rect=(x,y)=>nodeRect({position:{x,y},width:198,height:91});
function apply(base,patch){assert.ok(patch);return {...base,anchors:patch.anchors,start:anchorPoint(base.a,patch.anchors.source),end:anchorPoint(base.b,patch.anchors.target)};}
function verify(base,route,count){
 const original=JSON.stringify(route),corrected=orientRoute(base,route),points=routeGeometry(base,corrected).points;
 assert.equal(JSON.stringify(route),original);assert.deepEqual(orientRoute(base,corrected),corrected);
 if(count!==undefined){assert.deepEqual(corrected,route);assert.equal(points.length-2,count);}
 assert.deepEqual(points[0],base.start);assert.deepEqual(points.at(-1),base.end);
 for(let i=1;i<points.length;i++){const dx=points[i].x-points[i-1].x,dy=points[i].y-points[i-1].y;assert.ok(Math.abs(dx)<1e-7||Math.abs(dy)<1e-7);if(count!==undefined)assert.ok(Math.hypot(dx,dy)>1,'nonzero segment');}
 for(let i=1;i<points.length-1;i++){const a={x:points[i].x-points[i-1].x,y:points[i].y-points[i-1].y},b={x:points[i+1].x-points[i].x,y:points[i+1].y-points[i].y};if(count!==undefined)assert.ok(Math.abs(a.x*b.x+a.y*b.y)<1e-7,'real right angle');}
 for(const [near,end,side] of [[points[1],points[0],base.anchors.source.side],[points.at(-2),points.at(-1),base.anchors.target.side]]){const n=normals[side],dx=near.x-end.x,dy=near.y-end.y;assert.ok(Math.abs(dx*n.y-dy*n.x)<1e-7,`${side}: perpendicular`);assert.ok(dx*n.x+dy*n.y>=35.999,`${side}: outside`);}
 return corrected;
}
let edited=0,aligned=0,legacy=0;
for(const pos of [[500,330],[-400,-300],[40,400],[500,40],[500,-250],[-400,330]]) {
 const a=rect(40,40),b=rect(...pos);
 for(const source of Object.keys(normals))for(const target of Object.keys(normals)){
  const anchors={source:{side:source,ratio:.5},target:{side:target,ratio:.5}};
  let base={a,b,anchors,start:anchorPoint(a,anchors.source),end:anchorPoint(b,anchors.target)};
  const first=addBend(base,null);
  if(!first){aligned++;continue;}
  base=apply(base,first);let route=first.route;verify(base,route,1);
  for(const delta of [{x:16,y:-16},{x:-35,y:80}]){const patch=moveSingleBend(base,delta);verify(apply(base,patch),patch.route,1);}
  for(let n=2;n<=40;n++){
   const patch=addBend(base,route,n%3===0?1:undefined);base=apply(base,patch);route=patch.route;verify(base,route,n);edited++;
  }
  for(let n=39;n>=1;n--){const patch=removeBend(base,route,n%3===0?2:undefined);base=apply(base,patch);route=patch.route;verify(base,route,n);edited++;}
  assert.equal(removeBend(base,route).route,null);
  for(const raw of [{axis:'x',tracks:[370]},{axis:'y',tracks:[230]},{axis:'x',tracks:[330,280,410,350]},{axis:'y',tracks:[270,250,360]},{axis:'x',tracks:[]},{axis:'y',tracks:[]}]){
   const anchors={source:{side:source,ratio:.5},target:{side:target,ratio:.5}};
   const original={a,b,anchors,start:anchorPoint(a,anchors.source),end:anchorPoint(b,anchors.target)};
   const normalized=verify(original,raw),count=normalized.tracks.length+1;
   for(const action of [addBend,removeBend]){const patch=action(original,normalized);if(!patch){assert.equal(action,removeBend);continue;}if(patch.route)verify(apply(original,patch),patch.route,count+(action===addBend?1:-1));}
   for(let i=1;i<normalized.tracks.length+2;i++)verify(original,moveRoute(normalized,'corner',i,{x:-100,y:100}));
   legacy++;
  }
 }
}
// Mesma linha horizontal: só dois segmentos não conseguem formar um L sem entrar no host.
const a=rect(0,0),b=rect(500,0),base={a,b,...straightGeometry({source:'a',target:'b',a,b,lane:{index:0,count:1}})};
assert.equal(addBend(base,null),null);
console.log(JSON.stringify({status:'PASS',unitEdits:edited,legacyRoutes:legacy,alignedCases:aligned,singleBendDragging:true,minimumExit:36}));
