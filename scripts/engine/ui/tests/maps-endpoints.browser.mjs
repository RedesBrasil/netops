const { chromium, devices } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');import assert from'node:assert/strict';import fs from'node:fs/promises';
const BASE=process.env.NETOPS_E2E_URL || 'http://127.0.0.1:8771';if(!(await(await fetch(BASE+'/api/config/meta')).json()).isolated_data)throw Error('Teste recusa inventário real');const browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,args:['--no-sandbox']});const results=[];
for(const[mode,options]of [['desktop',{viewport:{width:1440,height:950}}],['mobile',{...devices['iPhone 13']}]]){
 const c=await browser.newContext(options),p=await c.newPage(),errors=[];p.on('pageerror',e=>errors.push(e.message));const get=async()=> (await c.request.get(BASE+'/api/maps')).json();let s=await get();const map=s.maps.find(m=>m.site==='Local-'+mode);const line=s.topology.links.find(l=>l.a.host.startsWith('map-host-'+mode)&&l.b.host==='list-host-'+mode);
 const m=structuredClone(map);delete m.host_ids;m.positions={[line.a.host]:{x:80,y:80},[line.b.host]:{x:500,y:330}};m.objects=[];m.visual_links=[];m.edges={[line.id]:{anchors:{source:{side:'bottom',ratio:.5},target:{side:'top',ratio:.5}},route:{axis:'y',tracks:[250]}}};
 const resp=await c.request.put(BASE+'/api/maps/'+m.id,{headers:{'If-Match':s.rev},data:{map:m,hosts_rev:s.hosts_rev,topology_rev:s.topology.rev}});assert.equal(resp.status(),200,await resp.text());
 const norm={left:{x:-1,y:0},right:{x:1,y:0},top:{x:0,y:-1},bottom:{x:0,y:1}};
 try{
 await p.goto(BASE+'/#maps');await p.locator('.netops-maps').waitFor();await p.locator('#map-select').selectOption(m.id);await p.locator(`[data-line-id="${line.id}"][data-line-part="line"]`).click();await p.waitForTimeout(300);
 for(const part of ['source','target'])for(const side of ['right','top','left','bottom']){
  const end=p.locator(`[data-line-id="${line.id}"][data-line-part="${part}"]`),f=await end.boundingBox(),node=await p.locator(`.react-flow__node[data-id="host:${part==='source'?line.a.host:line.b.host}"]`).boundingBox();
  const x=f.x+f.width/2,y=f.y+f.height/2,tx=side==='left'?node.x:side==='right'?node.x+node.width:node.x+node.width/2,ty=side==='top'?node.y:side==='bottom'?node.y+node.height:node.y+node.height/2;

  if(mode==='mobile'){const cd=await c.newCDPSession(p);await cd.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y,id:0}]});for(let i=1;i<=16;i++){await cd.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+(tx-x)*i/16,y:y+(ty-y)*i/16,id:0}]});await p.waitForTimeout(20);}await cd.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await cd.detach();}
  else{await p.mouse.move(x,y);await p.mouse.down();await p.mouse.move(tx,ty,{steps:16});await p.mouse.up();}
  let data;for(let i=0;i<60;i++){s=await get();data=s.maps.find(m=>m.id===map.id).edges[line.id];if(data.anchors[part].side===side)break;await p.waitForTimeout(50);}
  assert.equal(data.anchors[part].side,side);await p.waitForTimeout(80);
  const d=await p.locator(`.react-flow__edge[data-id="${line.id}"] .react-flow__edge-path`).getAttribute('d');const points=[...d.matchAll(/[ML] ([-\d.e+]+),([-\d.e+]+)/g)].map(m=>({x:+m[1],y:+m[2]}));for(const[near,end,side]of [[points[1],points[0],data.anchors.source.side],[points.at(-2),points.at(-1),data.anchors.target.side]]){const n=norm[side],dx=near.x-end.x,dy=near.y-end.y;assert.ok(Math.abs(dx*n.y-dy*n.x)<.001);assert.ok(dx*n.x+dy*n.y>=35.9);}
 }
 await p.screenshot({path:`/tmp/netops-endpoints-final-${mode}.png`});assert.deepEqual(errors,[]);results.push({mode,status:'PASS',cases:8});
 }catch(e){await p.screenshot({path:`/tmp/netops-endpoints-final-${mode}-failed.png`});results.push({mode,status:'FAIL',error:e.stack});}await c.close();
}await browser.close();console.log(JSON.stringify(results,null,2));await fs.writeFile('/tmp/netops-endpoints-final-results.json',JSON.stringify(results,null,2));if(results.some(r=>r.status==='FAIL'))process.exitCode=1;
