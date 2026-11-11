import { mapActions } from "./maps-actions.mjs";
const { chromium, devices } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const BASE=process.env.NETOPS_E2E_URL || 'http://127.0.0.1:8771';
const meta=await (await fetch(BASE+'/api/config/meta')).json();
if(!meta.isolated_data) throw Error('Teste recusa dados reais. Inicie com NETOPS_UI_DATA_ROOT.');
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE,args:['--no-sandbox']});
const results=[];
for(const [mode,options] of [['desktop',{viewport:{width:1440,height:950}}],['mobile',{...devices['iPhone 13']}]]){
 const ctx=await browser.newContext(options),page=await ctx.newPage(),errors=[],passed=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{
  // O provider global consulta o catálogo mesmo com a aba Claude desabilitada na fixture.
  const disabledClaude=!meta.claude_enabled&&m.location().url.endsWith('/api/claude/models')&&m.text().includes('403');
  if(m.type()==='error'&&!disabledClaude)errors.push(m.text());
 });
 const click=async l=>{await l.scrollIntoViewIfNeeded();if(mode==='mobile')await l.tap();else await l.click();};
 const actions=mapActions(page,mode);
 const btn=n=>page.getByRole('button',{name:n,exact:true});
 const snapshot=async()=>{const r=await ctx.request.get(BASE+'/api/maps');assert.equal(r.status(),200);return r.json();};
 const wait=async predicate=>{for(let i=0;i<80;i++){const s=await snapshot();if(predicate(s))return s;await page.waitForTimeout(80);}throw Error('Persistência não observada');};
 const modal=()=>page.locator('.modal');
 const field=(text)=>modal().locator('.field').filter({has:page.locator('label').filter({hasText:text})});
 async function hostForm(name){
  await modal().waitFor();
  await field('Nome do host').locator('input').fill(name);
  await field('IP de gerência').locator('input').fill('192.0.2.45');
  await field('Grupo (herança').locator('select').selectOption('linux-servers');
  await field('Site').locator('input').fill('Local-'+mode);
  const created=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/hosts');
  await click(btn('Criar'));
  const response=await created;assert.equal(response.status(),201,await response.text());
  await modal().waitFor({state:'detached'});
  const id=(await response.json()).id;assert.equal(typeof id,'number');return id;
 }
 async function maps(){await click(page.locator('.sidebar a[href="#maps"]'));await page.locator('.netops-maps').waitFor();await page.waitForTimeout(200);}
 const n=id=>page.locator(`.react-flow__node[data-id="host:${id}"]`);
 async function drag(l,dx,dy){await page.waitForTimeout(250);const box=await l.boundingBox();assert.ok(box);const x=box.x+box.width/2,y=box.y+box.height/2;
  if(mode==='mobile'){const c=await ctx.newCDPSession(page);await c.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y,id:0}]});for(let i=1;i<=15;i++){await c.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+dx*i/15,y:y+dy*i/15,id:0}]});await page.waitForTimeout(20);}await c.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await c.detach();}
  else{await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+dx,y+dy,{steps:15});await page.mouse.up();}
 }
 try{
  for (const name of ['map-host-'+mode, 'map-host-'+mode+'-renamed', 'list-host-'+mode]) {
   const s=await snapshot(),host=s.hosts.find(h=>h.hostname===name);if(host)await ctx.request.delete(BASE+'/api/hosts/'+host.id,{headers:{'If-Match':s.hosts_rev}});
  }
  for (const m of (await snapshot()).maps.filter(m=>m.kind==='custom'&&m.name==='Mapa adicional '+mode)) {
   const s=await snapshot();await ctx.request.delete(BASE+'/api/maps/'+m.id,{headers:{'If-Match':s.rev}});
  }
  await page.goto(BASE+'/#topology');await page.locator('.netops-maps').waitFor();await page.waitForTimeout(300);
  assert.equal(new URL(page.url()).hash,'#maps');
  assert.equal(await page.locator('.sidebar a[href="#topology"]').count(),0);
  assert.equal((await ctx.request.get(BASE+'/js/pages/topology.js')).status(),404);
  passed.push('página antiga e menu removidos, URL #topology abre Mapas');
  passed.push('console real e editor compartilham o mesmo Preact sem erros');
  const hostName='map-host-'+mode;
  await actions.pane('Adicionar host');const id=await hostForm(hostName);await wait(s=>s.hosts.some(h=>h.id===id));await n(id).waitFor();passed.push('cadastro no mapa grava host canônico com ID inteiro');
  await click(page.locator('.sidebar a[href="#hosts"]'));await page.getByRole('cell',{name:hostName,exact:true}).waitFor();passed.push('dispositivo do mapa aparece na lista Hosts');
  const listName='list-host-'+mode;
  await click(btn('+ Novo host'));const fromList=await hostForm(listName);await page.getByRole('cell',{name:listName,exact:true}).waitFor();
  await maps();await n(fromList).waitFor();passed.push('host cadastrado pela lista aparece no mapa geral');
  const site=(await snapshot()).maps.find(m=>m.site==='Local-'+mode);assert.ok(site);
  await page.locator('#map-select').selectOption(site.id);await n(fromList).waitFor();await n(id).waitFor();passed.push('mapa da localidade inclui os dois hosts automaticamente');
  const old=(await snapshot()).maps.find(m=>m.id===site.id).positions.find(p=>p.host_id===id);await drag(n(id),mode==='mobile'?18:50,mode==='mobile'?-65:150);
  await wait(s=>JSON.stringify(s.maps.find(m=>m.id===site.id).positions.find(p=>p.host_id===id))!==JSON.stringify(old));passed.push('arraste de host salva posição no servidor com '+(mode==='mobile'?'toque':'mouse'));
  await actions.pane('Ligar hosts');await click(n(id));await click(n(fromList));await modal().waitFor();
  await field('Porta A').locator('input').fill('ether1');await field('Porta B').locator('input').fill('ether2');await field('Velocidade').locator('input').fill('10G');
  await click(btn('Salvar'));await modal().waitFor({state:'detached'});let s=await wait(s=>s.topology.links.some(l=>l.a.host===id&&l.b.host===fromList));
  let line=s.topology.links.find(l=>l.a.host===id&&l.b.host===fromList);const label=()=>page.locator(`[data-line-id="${line.id}"][data-line-part="line"]`);
  await actions.on(label(), '+ Dobra');await wait(s=>s.maps.find(m=>m.id===site.id).edges[line.id]?.route?.tracks.length===0);passed.push('um clique cria somente uma dobra, mantida no YAML');
  for(let i=1;i<=3;i++){await actions.on(label(), '+ Dobra');await wait(s=>s.maps.find(m=>m.id===site.id).edges[line.id]?.route?.tracks.length===i);}
  await actions.on(label(), 'Remover dobra');await wait(s=>s.maps.find(m=>m.id===site.id).edges[line.id]?.route?.tracks.length===2);passed.push('adicionar e remover dobras é unitário');
  await page.screenshot({path:`/tmp/netops-integrated-${mode}-editing.png`});
  await page.reload();await page.locator('.netops-maps').waitFor();await page.locator('#map-select').selectOption(site.id);await label().waitFor();await click(label());assert.equal((await snapshot()).maps.find(m=>m.id===site.id).edges[line.id].route.tracks.length,2);passed.push('reload mantém layout e dobras');
  await actions.pane('Adicionar texto');await page.locator('.map-modal textarea').fill('Observação '+mode);await click(page.locator('.map-modal').getByRole('button',{name:'Salvar',exact:true}));await wait(s=>s.maps.find(m=>m.id===site.id).objects.some(o=>o.label==='Observação '+mode));passed.push('anotações persistidas');
  await actions.pane('Adicionar forma');await page.locator('.map-modal textarea').fill('Área '+mode);await click(page.locator('.map-modal').getByRole('button',{name:'Salvar',exact:true}));await wait(s=>s.maps.find(m=>m.id===site.id).objects.some(o=>o.type==='shape'));passed.push('formas persistidas');
  await click(page.getByRole('button',{name:'Novo mapa',exact:true}));await page.locator('.modal input[name="name"]').fill('Mapa adicional '+mode);await click(btn('Criar mapa'));s=await wait(s=>s.maps.some(m=>m.name==='Mapa adicional '+mode));const custom=s.maps.find(m=>m.name==='Mapa adicional '+mode);
  await actions.pane('Host existente');await page.locator('.map-modal select[name="host"]').selectOption(String(id));await click(page.locator('.map-modal').getByRole('button',{name:'Salvar',exact:true}));await wait(s=>s.maps.find(m=>m.id===custom.id).host_ids.includes(id));passed.push('mapa adicional reutiliza cadastro existente sem duplicação');
  await actions.pane('Referenciar mapa');await page.locator('.map-modal select[name="map_id"]').selectOption(site.id);await click(page.locator('.map-modal').getByRole('button',{name:'Salvar',exact:true}));s=await wait(s=>s.maps.find(m=>m.id===custom.id).objects.some(o=>o.type==='reference'));
  const ref=s.maps.find(m=>m.id===custom.id).objects.find(o=>o.type==='reference');await actions.on(page.locator(`.react-flow__node[data-id="object:${ref.id}"]`), 'Abrir mapa');await page.waitForFunction(site=>document.querySelector('#map-select').value===site,site.id);passed.push('referência entre mapas navega sem cadastrar host falso');
  const second=await browser.newContext(options),p2=await second.newPage();await p2.goto(BASE+'/#maps');await p2.locator('.netops-maps').waitFor();await p2.locator('#map-select').selectOption(site.id);await p2.locator(`[data-line-id="${line.id}"]`).first().waitFor();passed.push('outro navegador recebe o mesmo mapa salvo');await second.close();
  await click(page.locator('.topbar button').filter({hasText:'escuro'}));await page.waitForFunction(()=>document.documentElement.dataset.theme==='dark');await page.screenshot({path:`/tmp/netops-integrated-${mode}-dark.png`});passed.push('tema escuro funcional');
  await click(page.locator('.sidebar a[href="#hosts"]'));await click(page.getByRole('cell',{name:hostName,exact:true}));await modal().waitFor();const renamed=hostName+'-renamed';await field('Nome do host').locator('input').fill(renamed);await click(btn('Salvar'));await modal().waitFor({state:'detached'});s=await wait(s=>s.hosts.some(h=>h.id===id&&h.hostname===renamed));assert.ok(s.topology.links.some(l=>l.id===line.id&&l.a.host===id));passed.push('edição do nome na lista preserva ID inteiro, enlace e posições nos mapas');
  await maps();await page.locator('#map-select').selectOption(site.id);await n(id).getByText(renamed,{exact:true}).waitFor();passed.push('nome atualizado refletido no mapa');
  assert.equal(await page.locator('.react-flow__handle:visible').count(),0);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);
  results.push({mode,status:'PASS',passed,errors});
 }catch(e){await page.screenshot({path:`/tmp/netops-integrated-${mode}-failed.png`});results.push({mode,status:'FAIL',passed,errors,failure:e.stack});}
 await ctx.close();
}
await browser.close();await fs.writeFile('/tmp/netops-maps-e2e-results.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));if(results.some(r=>r.status==='FAIL'))process.exitCode=1;
