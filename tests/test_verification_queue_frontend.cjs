/* The real browser modules run in a VM. All uploads, account sessions and jobs are fake. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const sourcePath=path.join(__dirname,'..');
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const response=(data,ok=true,status=200)=>({ok,status,json:async()=>data});
const queue=(state='queued',extra={})=>({state,queued_at:1700000000,started_at:null,retry_at:null,position:2,estimated_wait_seconds:null,...extra});
const result=q=>({id:'test-record',status:'processing',analysis_status:'pending',total_count:1,photos:[],summary:'Comparison pending.',publication_status:null,auto_publish:true,queue:q});

class Element {
  constructor(){this.innerHTML='';this.textContent='';this.hidden=false;this.isConnected=true;this.children=[];this.dataset={};this.classList={add(){},remove(){},toggle(){}};}
  append(node){this.children.push(node);}
  setAttribute(){}
  addEventListener(){}
  insertAdjacentHTML(){}
  querySelector(selector){return this.nodes?.get(selector)||null;}
  querySelectorAll(){return [];}
}
function harness(kind,options={}) {
  const nodes=new Map(),requests=[],events={},documentEvents={},timers=new Map();let timer=0;
  for(const id of ['main','#ihStandalone','#ihRetryUpload','#ihUploadError','#ihUploadProgress','#ihUploadLabel','#ihRefreshSellerResult','#ihExport','.ih-report-head','#caQueueSummary','#caQueueStatus','#caQueueBudget','#caQueueJobs','#caAnalyticsStatus','#caSocialStatus','#caGrants','#caMetrics','#caPeriod'])nodes.set(id,new Element());
  const pageNodes=new Map(nodes);
  const body=new Element();body.insertAdjacentHTML=()=>{};
  const document={body,hidden:false,readyState:'loading',querySelector:s=>nodes.get(s)||null,querySelectorAll:()=>[],createElement:()=>{const el=new Element();el.nodes=pageNodes;return el;},addEventListener:(name,fn)=>documentEvents[name]=fn};
  const window={addEventListener:(name,fn)=>events[name]=fn,dispatchEvent(){},LockXCredits:{authorization:async()=> 'Bearer owner-test'},ensureLockXAuthClient:async()=>({auth:{getSession:options.session|| (async()=>({data:{session:{access_token:'admin-test'}}}))}})};
  const context={window,document,navigator:{},location:{hash:'#other',pathname:'/',origin:'https://lockx.ai'},history:{},API_BASE:'https://api.example/v1',URL,URLSearchParams,Headers,AbortController,Date,Intl,JSON,Promise,Map,Set,Number,Math,Error,crypto:webcrypto,performance:{now:()=>100},localStorage:{getItem:()=>null,setItem(){}},btoa:s=>Buffer.from(s,'binary').toString('base64'),Event:class{},CustomEvent:class{},setTimeout:fn=>{timers.set(++timer,fn);return timer;},clearTimeout:id=>timers.delete(id),clearInterval(){},go(){},fetch:async(url,init={})=>{requests.push({url,init});return options.fetch?options.fetch(url,init):response({visual_comparison_ready:true});}};
  let code=fs.readFileSync(path.join(sourcePath,kind==='seller'?'in-hand.js':'credit-admin.js'),'utf8');
  const expose=kind==='seller'?`window.testQueue={queueInfo,queuePresentation,savedSubmissionBox,recordLabel,reportFingerprint,photoResultCards,queueKicker,showSellerResult,showReport,uploadCapture,setCapture(current,token='private-test',media=[]){capture=current;routeNumber=current.route;sellerToken=token;sellerData={media};},getCapture:()=>capture};`:`window.testQueue={renderQueue,loadData,request,setAccess(value){access=value;},changeGeneration(){generation++;},page};`;
  code=code.replace(/\}\)\(\);\s*$/,expose+'\n})();');
  vm.createContext(context);vm.runInContext(code,context);
  return {api:window.testQueue,page:kind==='admin'?window.testQueue.page:nodes.get('#ihStandalone'),nodes,requests,context,events,timers};
}

const tests=[];const test=(name,fn)=>tests.push([name,fn]);
test('safe-close confirmation requires durable server queue timestamp and known state',()=>{
  const h=harness('seller');
  for(const record of [{},{queue:{state:'queued'}},{queue:{state:'queued',queued_at:null}},{queue:queue('unknown')}])assert.equal(h.api.savedSubmissionBox(record),'');
  assert.match(h.api.savedSubmissionBox({queue:queue()}),/Submission saved\. You can close this page\./);
  assert.match(h.api.savedSubmissionBox({queue:queue()}),/href="#in-hand"/);
});
test('queued, running, retry and capacity waits have distinct truthful messages',()=>{
  const h=harness('seller');
  assert.match(h.api.queuePresentation({queue:queue()}).detail,/Position in line: 2/);
  assert.doesNotMatch(h.api.queuePresentation({queue:queue()}).detail,/Estimated wait/);
  assert.match(h.api.queuePresentation({queue:queue('queued',{estimated_wait_seconds:125})}).detail,/about 3 minutes/);
  assert.match(h.api.queuePresentation({queue:queue('running')}).title,/Checking/);
  assert.match(h.api.queuePresentation({queue:queue('retrying')}).detail,/automatically.*No new recording/s);
  assert.match(h.api.queuePresentation({queue:queue('budget_wait')}).detail,/place is kept.*continue automatically/s);
});
test('queue-only state changes trigger owner report refresh',()=>{
  const h=harness('seller'),record={...result(queue()),media:[]};
  assert.notEqual(h.api.reportFingerprint(record),h.api.reportFingerprint({...record,queue:queue('running')}));
  assert.match(h.api.recordLabel(record),/Waiting/);
});
test('unacknowledged finish retains local recording and safe upload retry',async()=>{
  const h=harness('seller',{fetch:async url=>response(url.endsWith('/scan/finish')?{status:'processing'}:{})});
  const capture={route:1,queue:[],sessionID:'fake-session',uploadedCount:1,uploadedBytes:20,bytesTotal:20,recordingSeconds:10};h.api.setCapture(capture);
  await h.api.uploadCapture(capture);
  assert.equal(h.api.getCapture(),capture);assert.equal(h.nodes.get('#ihRetryUpload').hidden,false);
  assert.match(h.nodes.get('#ihUploadError').textContent,/saving has not been confirmed/);
  assert.doesNotMatch(h.page.innerHTML,/You can close this page/);
});
test('acknowledged finish remains safely saved if subsequent result loading fails',async()=>{
  const h=harness('seller',{fetch:async url=>{if(url.endsWith('/result'))throw Error('Network unavailable.');return response(url.endsWith('/scan/finish')?{queue:queue()}:{visual_comparison_ready:true});}});
  const capture={route:1,queue:[],sessionID:'fake-session',uploadedCount:1,uploadedBytes:20,bytesTotal:20,recordingSeconds:10};h.api.setCapture(capture);
  await h.api.uploadCapture(capture);
  assert.equal(h.api.getCapture(),null);assert.match(h.page.innerHTML,/Submission saved\. You can close this page/);
});
test('duplicate finish accepts only server-confirmed durable receipt',async()=>{
  const h=harness('seller',{fetch:async url=>url.endsWith('/scan/finish')?response({detail:'Already submitted'},false,409):url.endsWith('/result')?response(result(queue('retrying'))):response({status:'processing',queue:queue()})});
  const capture={route:1,queue:[],sessionID:'fake-session',uploadedCount:1,uploadedBytes:20,bytesTotal:20,recordingSeconds:10};h.api.setCapture(capture);
  await h.api.uploadCapture(capture);assert.equal(h.api.getCapture(),null);assert.match(h.page.innerHTML,/Retrying your comparison/);assert.doesNotMatch(h.page.innerHTML,/Record again with light/);
});
test('unconfirmed result fetch failure does not claim upload saved',async()=>{
  const h=harness('seller',{fetch:async url=>{if(url.endsWith('/result'))throw Error('Offline.');return response({});}});h.api.setCapture({route:1});
  await h.api.showSellerResult('unknown-token',1);
  assert.doesNotMatch(h.page.innerHTML,/Submission saved|recording received|recording has been sent/i);
});
test('admin queue shows real counts and provisional USD costs without private fields',()=>{
  const h=harness('admin');h.api.renderQueue({enabled:true,states:{queued:3,running:2,retrying:1,budget_wait:4},oldest_wait_seconds:121,completed_last_hour:7,failed_last_hour:1,active_workers:2,concurrency:2,max_workers:8,hourly_budget_usd:100,budget_reserved_usd:1.25,budget_actual_usd:0.42,budget_remaining_usd:98.75,recent:[{state:'retrying',queued_at:1700000000,attempts:2,reason:'provider_retry',email:'private@example.test',token:'secret-evidence'}]});
  assert.match(h.nodes.get('#caQueueSummary').innerHTML,/Queued.*>3<.*Oldest wait.*3 min/s);
  assert.match(h.nodes.get('#caQueueBudget').innerHTML,/\$100\.00.*\$1\.25.*\$0\.42/s);assert.match(h.nodes.get('#caQueueBudget').innerHTML,/provisional/);
  assert.match(h.nodes.get('#caQueueBudget').innerHTML,/Used or reserved/);assert.match(h.nodes.get('#caQueueBudget').innerHTML,/rolling last 60 minutes/);assert.match(h.nodes.get('#caQueueBudget').innerHTML,/already included in used or reserved/);assert.doesNotMatch(h.nodes.get('#caQueueBudget').innerHTML,/Estimated reservations/);
  assert.doesNotMatch(h.nodes.get('#caQueueJobs').innerHTML,/private@example|secret-evidence/);
});
test('admin unknown data stays dash and untrusted status or reason never becomes markup',()=>{
  const h=harness('admin');h.api.renderQueue({states:{},recent:[{state:'<img src=x>',reason:'<script>bad</script>'}]});
  assert.match(h.nodes.get('#caQueueSummary').innerHTML,/—/);assert.match(h.nodes.get('#caQueueBudget').innerHTML,/—/);
  assert.doesNotMatch(h.nodes.get('#caQueueJobs').innerHTML,/<img|<script/);
});
test('estimated budget remaining uses only known limit and reservations and never goes negative',()=>{
  const h=harness('admin');h.api.renderQueue({hourly_budget_usd:100,budget_reserved_usd:2.35,recent:[]});
  assert.match(h.nodes.get('#caQueueBudget').innerHTML,/Estimated remaining<\/dt><dd>\$97\.65/);
  h.api.renderQueue({hourly_budget_usd:100,budget_reserved_usd:101,recent:[]});
  assert.match(h.nodes.get('#caQueueBudget').innerHTML,/Estimated remaining<\/dt><dd>\$0\.00/);
});
test('queue fetch uses admin authentication and cannot paint after account changes',async()=>{
  const hold=deferred();const h=harness('admin',{fetch:async url=>url.endsWith('/queue')?hold.promise:response(url.includes('/social')?{summary:{}}:{grants:[]})});h.api.setAccess(true);
  const loading=h.api.loadData();for(let i=0;i<20;i++)await Promise.resolve();
  const call=h.requests.find(row=>row.url.endsWith('/queue'));assert.equal(call.init.headers.Authorization,'Bearer admin-test');
  h.api.changeGeneration();hold.resolve(response({states:{queued:999},recent:[]}));await loading;
  assert.doesNotMatch(h.nodes.get('#caQueueSummary').innerHTML,/999/);
});
test('waiting seller headings and shared photo cards never imply AI has started',async()=>{
  for(const state of ['queued','retrying','budget_wait']){
    const h=harness('seller',{fetch:async()=>response(result(queue(state)))});h.api.setCapture({route:1},'private-test',[{id:'photo',role:'listing'}]);await h.api.showSellerResult('private-test',1);
    assert.match(h.page.innerHTML,/Submission saved · (Waiting|Automatic retry)/);
    assert.doesNotMatch(h.page.innerHTML,/AI comparison in progress|Checking against frames|Comparing…/);
    assert.match(h.page.innerHTML,/Photo 1 · Waiting/);
  }
  const h=harness('seller'),cards=h.api.photoResultCards({refs:[{id:'photo'}],findings:new Map([[0,{finding:'supported',evidence:'Distinctive mark matched.'}]]),eligible:new Set([0]),pending:false,queue:queue('completed')});
  assert.match(cards,/Verified match/);assert.match(cards,/Distinctive mark matched/);assert.doesNotMatch(cards,/Waiting for/);
});
module.exports=async()=>{const results=[];for(const[name,fn]of tests){try{await fn();results.push({name,status:'PASS'});}catch(error){results.push({name,status:'FAIL',error:error.stack});}}return results;};
