/* No Vercel credentials, VMs, marketplace requests, or seller messages are used. */
const test=require('node:test');
const assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const path=require('node:path');
const library=import('../lib/contact-sandbox.mjs');
const endpoint=import('../api/craigslist-contact.mjs');
const NOW=1795000000000,TICKET='t'.repeat(43);
const URL='https://sfbay.craigslist.org/sby/ele/d/city-item/1234567890.html';
const NONCE='n'.repeat(43),SNAPSHOT='snap_fixtureclean1234';
const claim=(extra={})=>({version:1,nonce:NONCE,listing_url:URL,purpose:'lookup',expires:NOW/1000+30,...extra});
const response=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});

function fixture(options={}){
  const events=[],files=[],creates=[],commands=[];
  const observed=options.claim||claim();
  const sandbox={name:'sbx_fixture',cwd:options.cwd||'/vercel/sandbox',
    async writeFiles(values){events.push('write');files.push(...values);if(options.writeFail)throw Error('private write detail');},
    async runCommand(params){
      commands.push(params);events.push('command:'+params.cmd);
      if(options.commandThrow)throw Error('private command detail');
      let output='';
      if(params.args?.includes('--probe'))output=JSON.stringify(options.probe||{version:1,status:'ready',sandbox:true,userns:true});
      else if(params.args?.some(value=>value.endsWith('/lockx-contact/job.json')))output=options.output===undefined?JSON.stringify({version:1,nonce:NONCE,url:URL,status:'revealed',email:'seller-relay@sale.craigslist.org'}):options.output;
      return {async *logs(){if(output)yield {stream:'stdout',data:output};},async wait(){return {exitCode:options.exitCode||0};},async kill(){events.push('kill');}};
    },
    async update(value){events.push('network:'+value.networkPolicy);},
    async snapshot(value){events.push('snapshot');return {snapshotId:SNAPSHOT,status:'created'};},
    async stop(){events.push('stop');if(options.stopFail)throw Error('private cleanup detail');},
    async delete(value){events.push('delete');assert.equal(value.deleteOrphanSnapshots,false);if(options.deleteFail)throw Error('private deletion detail');}
  };
  const dependencies={now:()=>NOW,snapshotId:SNAPSHOT,readFileImpl:async file=>Buffer.from('trusted '+path.basename(file.pathname)),
    fetchImpl:async(url,init)=>{events.push('claim');assert.equal(url,'https://lockx-production.up.railway.app/api/v1/in-hand/contact-lookup/claim');assert.equal(init.redirect,'error');assert.deepEqual(JSON.parse(init.body),{ticket:TICKET});assert.deepEqual(Object.keys(init.headers).sort(),['Accept','Content-Type']);return options.fetchResponse||response(observed);},
    loadSandbox:async()=>{events.push('sdk');return {async create(value){events.push('create');creates.push(value);if(options.createFail)throw Error('private SDK detail');return sandbox;}};}
  };
  return {events,files,creates,commands,dependencies};
}

test('only an exact opaque ticket body is accepted before any claim or VM work',async()=>{
  const {contactRequest}=await library;
  for(const body of [null,[],{}, {ticket:TICKET,url:URL},{ticket:TICKET,snapshotId:SNAPSHOT},{ticket:'short'},{ticket:'x'.repeat(8193)},{ticket:TICKET+'\n'}]){
    const f=fixture();const answer=await contactRequest(body,f.dependencies);assert.equal(answer.code,400);assert.deepEqual(f.events,[]);
  }
});

test('denied, expired, malformed, or unrelated claims incur no sandbox work',async()=>{
  const {contactRequest}=await library;
  const bad=[claim({version:2}),claim({nonce:'bad'}),claim({purpose:'send'}),claim({expires:NOW/1000}),claim({expires:NOW/1000+601}),claim({listing_url:'https://craigslist.org.evil.example/pho/d/a/1234567890.html'}),claim({listing_url:null}),{...claim(),resources:{vcpus:8}}];
  for(const value of bad){const f=fixture({claim:value});assert.equal((await contactRequest({ticket:TICKET},f.dependencies)).code,403);assert.deepEqual(f.events,['claim']);}
  for(const fetchResponse of [new Response('{}',{status:403,headers:{'Content-Type':'application/json'}}),new Response('x'.repeat(9000),{headers:{'Content-Type':'application/json'}}),new Response('{}')]){
    const f=fixture({fetchResponse});assert.equal((await contactRequest({ticket:TICKET},f.dependencies)).code,403);assert.deepEqual(f.events,['claim']);
  }
});

test('sandbox loading and creation wait until the fixed-origin claim completes',async()=>{
  const {contactRequest}=await library;const f=fixture();let accept;
  f.dependencies.fetchImpl=()=>new Promise(resolve=>accept=resolve);
  const pending=contactRequest({ticket:TICKET},f.dependencies);assert.deepEqual(f.events,[]);
  accept(response(claim()));await pending;assert.deepEqual(f.events.slice(0,2),['sdk','create']);
});

test('lookup creates one fresh constrained VM, uploads no secrets, and returns exact claim-bound output',async()=>{
  const {contactRequest}=await library;const f=fixture();
  const answer=await contactRequest({ticket:TICKET},f.dependencies);
  assert.deepEqual(answer,{code:200,body:{...claim(),status:'revealed',email:'seller-relay@sale.craigslist.org'}});
  assert.deepEqual(f.events.slice(0,3),['claim','sdk','create']);assert.equal(f.creates.length,1);
  assert.deepEqual(f.creates[0],{persistent:false,resources:{vcpus:1},env:{},ports:[],timeout:20000,source:{type:'snapshot',snapshotId:SNAPSHOT},networkPolicy:{allow:['craigslist.org','*.craigslist.org']}});
  assert.deepEqual(f.files.map(file=>file.path),['/vercel/sandbox/lockx-contact/craigslist_contact.py','/vercel/sandbox/lockx-contact/contact_worker.py','/vercel/sandbox/lockx-contact/job.json']);
  assert.ok(f.files.every(file=>file.mode===0o600));assert.deepEqual(JSON.parse(f.files[2].content),{version:1,nonce:NONCE,listing_url:URL});assert.ok(!JSON.stringify(f.files).includes(TICKET));
  assert.deepEqual(f.commands[0].args,['/vercel/sandbox/lockx-contact/contact_worker.py','/vercel/sandbox/lockx-contact/job.json']);assert.equal(f.commands[0].sudo,false);assert.equal(f.commands[0].timeoutMs,10000);assert.equal(f.commands[0].detached,true);
  assert.deepEqual(Object.keys(f.commands[0].env).sort(),['PLAYWRIGHT_BROWSERS_PATH','PYTHONDONTWRITEBYTECODE']);assert.deepEqual(f.events.slice(-2),['stop','delete']);
});

test('each lookup creates and deletes its own VM without persistent session reuse',async()=>{
  const {contactRequest}=await library;const f=fixture();await contactRequest({ticket:TICKET},f.dependencies);await contactRequest({ticket:TICKET},f.dependencies);
  assert.equal(f.creates.length,2);assert.equal(f.events.filter(value=>value==='stop').length,2);assert.equal(f.events.filter(value=>value==='delete').length,2);assert.ok(f.creates.every(value=>value.persistent===false));
});

test('all worker paths follow the actual managed-image working directory',async()=>{
  const {contactRequest}=await library;const f=fixture({cwd:'/home/sandbox'});
  const answer=await contactRequest({ticket:TICKET},f.dependencies);assert.equal(answer.body.status,'revealed');
  assert.ok(f.files.every(file=>file.path.startsWith('/home/sandbox/lockx-contact/')));
  assert.equal(f.commands[0].cwd,'/home/sandbox');assert.equal(f.commands[0].cmd,'/home/sandbox/contact-venv/bin/python');
  assert.equal(f.commands[0].env.PLAYWRIGHT_BROWSERS_PATH,'/home/sandbox/contact-browsers');
});

test('missing clean snapshot fails closed after admission without creating a VM',async()=>{
  const {contactRequest}=await library;const f=fixture();f.dependencies.snapshotId='';
  assert.deepEqual((await contactRequest({ticket:TICKET},f.dependencies)).body,{...claim(),status:'unavailable',email:null});assert.deepEqual(f.events,['claim']);
});

test('unbound, oversized, or invalid worker results cannot become a seller address',async()=>{
  const {contactRequest}=await library;
  const good={version:1,nonce:NONCE,url:URL,status:'revealed',email:'seller@sale.craigslist.org'};
  for(const output of ['x'.repeat(4097),'not json',JSON.stringify({...good,nonce:'different_nonce_1234567890'}),JSON.stringify({...good,url:URL.replace('city-item','other-item')}),JSON.stringify({...good,email:'seller@sale.craigslist.org.evil.example'}),JSON.stringify({...good,email:'support@sale.craigslist.org'}),JSON.stringify({...good,status:'blocked'}),JSON.stringify({...good,extra:'private'}),JSON.stringify({...good,status:'sent'})]){
    const f=fixture({output});assert.deepEqual((await contactRequest({ticket:TICKET},f.dependencies)).body,{...claim(),status:'unavailable',email:null});assert.deepEqual(f.events.slice(-2),['stop','delete']);
  }
});

test('an unconfirmed VM termination cannot release the backend lease through a valid lookup result',async()=>{
  const {contactRequest}=await library;const f=fixture({stopFail:true,deleteFail:true});
  const answer=await contactRequest({ticket:TICKET},f.dependencies);assert.equal(answer.code,503);assert.deepEqual(Object.keys(answer.body),['error']);assert.deepEqual(f.events.slice(-2),['stop','delete']);
});

test('blocked and busy lookup results retain their status and null recipient',async()=>{
  const {contactRequest}=await library;
  for(const status of ['blocked','busy','unavailable']){const f=fixture({output:JSON.stringify({version:1,nonce:NONCE,url:URL,status,email:null})});assert.deepEqual((await contactRequest({ticket:TICKET},f.dependencies)).body,{...claim(),status,email:null});}
});

test('upload, command, and stop failures still attempt deletion and expose no internal details',async()=>{
  const {contactRequest}=await library;
  for(const options of [{writeFail:true},{commandThrow:true},{exitCode:1},{stopFail:true}]){
    const f=fixture(options);const answer=await contactRequest({ticket:TICKET},f.dependencies);assert.deepEqual(f.events.slice(-2),['stop','delete']);assert.ok(!JSON.stringify(answer).includes('private'));
  }
});

test('bootstrap performs only fixed dependency setup and a deny-network sandbox probe before a clean snapshot',async()=>{
  const {contactRequest}=await library;const f=fixture({claim:claim({purpose:'bootstrap'})});
  const answer=await contactRequest({ticket:TICKET},f.dependencies);assert.equal(answer.code,200);assert.deepEqual(answer.body,{...claim({purpose:'bootstrap'}),status:'ready',snapshot_id:SNAPSHOT,id:'sbx_fixture'});
  assert.deepEqual(f.creates[0],{persistent:false,resources:{vcpus:1},env:{},ports:[],timeout:180000,image:'vcr.vercel.com/vercel/sandbox/universal:latest',networkPolicy:'allow-all'});
  assert.ok(f.commands.some(command=>command.args.includes('playwright==1.64.0')));assert.ok(f.commands.some(command=>command.sudo&&command.args.join(' ')==='-m playwright install --with-deps chromium'));
  assert.ok(f.events.indexOf('network:deny-all')<f.events.indexOf('command:/vercel/sandbox/contact-venv/bin/python',f.events.indexOf('network:deny-all')));
  assert.ok(f.commands.some(command=>command.args.includes('--probe')&&!command.sudo));assert.deepEqual(f.commands.at(-1).args,['-rf','/vercel/sandbox/lockx-contact']);assert.ok(f.events.indexOf('command:rm')<f.events.indexOf('snapshot'));
  assert.equal(f.files.length,2);assert.ok(!JSON.stringify(f.files).includes(URL));assert.ok(!JSON.stringify(f.files).includes(NONCE));assert.deepEqual(f.events.slice(-2),['stop','delete']);
});

test('a failed Chromium or user namespace probe never snapshots the bootstrap VM',async()=>{
  const {contactRequest}=await library;
  for(const probe of [{version:1,status:'unavailable',sandbox:false,userns:true},{version:1,status:'ready',sandbox:true,userns:false}]){
    const f=fixture({claim:claim({purpose:'bootstrap'}),probe});const answer=await contactRequest({ticket:TICKET},f.dependencies);assert.equal(answer.code,503);assert.equal(answer.body.stage,'sandbox-probe');assert.ok(!f.events.includes('snapshot'));assert.deepEqual(f.events.slice(-2),['stop','delete']);
  }
});

test('bootstrap diagnostics redact connection URLs and credential-shaped values',async()=>{
  const {contactRequest}=await library;const f=fixture({claim:claim({purpose:'bootstrap'})});
  const secret='sensitive'.repeat(10);
  f.dependencies.loadSandbox=async()=>{throw Error('Request failed https://provider.example/?token='+secret+' Bearer '+secret);};
  const answer=await contactRequest({ticket:TICKET},f.dependencies);
  assert.equal(answer.code,503);assert.equal(answer.body.stage,'sdk');
  assert.ok(!JSON.stringify(answer).includes(secret));assert.ok(!JSON.stringify(answer).includes('provider.example'));
  assert.deepEqual(f.events,['claim']);
});

test('an internal diagnostic ticket follows the constrained browser path and excludes addresses and exception text',async()=>{
  const {contactRequest}=await library;
  const trace={result_status:'unavailable',relay_present:false,elapsed_s:7,events:[{stage:'fetch',host:'www.craigslist.org',resource:'document',error:'ConnectError',message:'never return seller@example.test'}]};
  const f=fixture({claim:claim({purpose:'diagnostic'}),output:JSON.stringify({version:1,nonce:NONCE,url:URL,status:'diagnostic',trace})});
  const answer=await contactRequest({ticket:TICKET},f.dependencies);
  assert.equal(answer.code,200);assert.equal(answer.body.status,'diagnostic');assert.equal(answer.body.purpose,'diagnostic');
  assert.equal(f.creates[0].source.snapshotId,SNAPSHOT);assert.deepEqual(f.creates[0].networkPolicy,{allow:['craigslist.org','*.craigslist.org']});
  assert.ok(f.commands[0].args.includes('--diagnostic'));assert.ok(!JSON.stringify(answer.body).includes('seller@example.test'));
  assert.deepEqual(f.events.slice(-2),['stop','delete']);
});

test('endpoint is POST JSON only, returns no CORS capability, and never reflects tickets',async()=>{
  const {createContactHandler}=await endpoint;
  for(const [method,type,body,status] of [['GET','application/json',{},405],['OPTIONS','application/json',{},405],['POST','text/plain',{ticket:TICKET},415],['POST','application/json','{bad',400]]){
    const f=fixture(),headers={};let code,answer;
    const res={setHeader:(key,value)=>headers[key]=value,status(value){code=value;return this;},json(value){answer=value;}};
    await createContactHandler(f.dependencies)({method,headers:{'content-type':type},body},res);
    assert.equal(code,status);assert.ok(!Object.keys(headers).some(value=>value.toLowerCase().startsWith('access-control')));assert.ok(!JSON.stringify(answer).includes(TICKET));assert.deepEqual(f.events,[]);
  }
});

test('standalone worker uses verbatim transport and mailbox guards and requires a real nested sandbox probe',()=>{
  const script=String.raw`
import ast, pathlib
root=pathlib.Path('.')
worker=ast.parse((root/'scripts/contact_worker.py').read_text())
def nodes(tree):
 result={}
 for node in tree.body:
  name=getattr(node,'name',None)
  if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name): name=node.targets[0].id
  if name: result[name]=node
 return result
w=nodes(worker)
for filename,names in [('listing_import.py',['ImportUnavailable','_bounded_work','_public_address','resolve_public']),('listing_contacts.py',['_EMAIL','_ROLE','clean_email'])]:
 original=nodes(ast.parse((root/filename).read_text()))
 for name in names: assert ast.dump(w[name],include_attributes=False)==ast.dump(original[name],include_attributes=False), name
code=(root/'scripts/contact_worker.py').read_text()
assert 'chromium_sandbox=True' in code and 'os.geteuid() == 0' in code
assert "['unshare', '--user', '--map-root-user', 'true']" in code
assert '--no-sandbox' not in code
`;
  execFileSync('python3',['-c',script],{cwd:path.join(__dirname,'..')});
});
