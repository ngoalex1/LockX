/* Run this module in Node. It evaluates the actual wallet code in an isolated VM. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'credit-wallet.js'), 'utf8');
const deferred = () => { let resolve, reject; const promise = new Promise((a,b)=>{resolve=a;reject=b;}); return {promise,resolve,reject}; };
const response = data => ({ok:true,json:async()=>data});

class Element {
  constructor(tag='div') { this.tag=tag; this.hidden=true; this.isConnected=true; this.attributes={}; this.children=[]; this.classList={add(){},remove(){}}; }
  setAttribute(name,value){this.attributes[name]=value;}
  removeAttribute(name){delete this.attributes[name];}
  replaceChildren(...children){this.children=children;}
  addEventListener(){}
  remove(){this.isConnected=false;}
}

async function harness(options={}) {
  const events=[], requests=[], scripts=[], listeners={}, sessions=[], timers=new Map();let nextTimer=0;
  const nodes=new Map([['#cwApplePay',new Element()],['#cwGooglePay',new Element()],['#cwMessage',new Element()],['#cwSelectedSummary',new Element()]]);
  const config={credits_required:false,payment_ready:true,apple_pay_ready:true,google_pay_ready:false,paypal_client_id:'public-client',packs:[{id:'regular',credits:20,amount_cents:1000},{id:'large',credits:40,amount_cents:2000}]};
  let syncGesture=false;
  const settings={isEligible:options.eligible!==false,countryCode:'US',merchantCapabilities:['supports3DS'],supportedNetworks:['visa']};
  const applepay={config:async()=>settings,validateMerchant:async()=>{if(options.validationThrows)throw Error('Validation unavailable');return {merchantSession:{proof:'provider-session'}};},confirmOrder:async value=>{events.push(['confirm',value]); return options.confirm ? options.confirm(value) : {status:'APPROVED'};}};
  class Session {
    static STATUS_SUCCESS=1; static STATUS_FAILURE=0;
    static canMakePayments(){return options.canMakePayments!==false;}
    constructor(version,request){events.push(['construct',syncGesture]);this.request=request;this.results=[];sessions.push(this);}
    begin(){events.push(['begin',syncGesture]);}
    completeMerchantValidation(value){events.push(['merchant',value]);}
    completePayment(result){this.results.push(result);events.push(['complete',result]);if(options.completeThrows)throw Error('Session already ended');}
    completePaymentMethodSelection(value){events.push(['methodSelection',value]);}
    abort(){events.push(['abort']);if(options.abortThrows)throw Error('Session already aborted');}
  }
  const document={querySelector:s=>nodes.get(s)||null,querySelectorAll:()=>[],createElement:tag=>new Element(tag),addEventListener:(type,fn)=>{listeners[type]=fn;},head:{append(script){scripts.push(script);if(!options.manualScripts)queueMicrotask(()=>script.onload());}}};
  const storage=new Map();
  const window={ApplePaySession:Session,paypal:options.manualScripts?undefined:{Applepay:()=>applepay,Googlepay:()=>({})},addEventListener(){},ensureLockXAuthClient:async()=>({auth:{getSession:async()=>({data:{session:{access_token:'test-token',user:{email:'test@example.com'}}}})}})};
  const fetch=async (url,init={})=>{
    if(url.endsWith('/catalog'))return response(config);
    const body=init.body?JSON.parse(init.body):undefined;requests.push({url,body});
    if(url.endsWith('/wallet')){if(options.walletThrows)throw Error('Wallet temporarily unavailable');if(options.walletPending)await options.walletPending;return response({balance:20,history:[]});}
    if(url.endsWith('/capture')){events.push(['capture',body]);if(options.capture)await options.capture(body);return response({status:'paid'});}
    if(url.endsWith('/checkouts')&&init.method==='POST')return response({id:'checkout-20',paypal_order_id:'server-order',credits:body.pack_id==='large'?40:20,status:'pending'});
    return response({status:'pending'});
  };
  const context={window,document,fetch,ApplePaySession:Session,API_BASE:'https://api.example.test',location:{search:'',origin:'https://lockx.ai'},URL,URLSearchParams,sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},crypto:{randomUUID:()=> 'idempotency-key'},setInterval:()=>1,clearInterval(){},setTimeout(fn,delay){const id=++nextTimer;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);},console};
  vm.createContext(context);
  const instrumented=source.replace('window.LockXCredits={ready,', 'window.__walletTest={setupApplePay,loadScript,loadPayPalWalletSDK,renderWallet,updatePackSummary,setSelected:value=>{selected=value;},state:()=>({selected,busy,appleSession})};window.LockXCredits={ready,');
  assert.notEqual(instrumented,source,'Test instrumentation must find the public export.');
  vm.runInContext(instrumented,context,{filename:'credit-wallet.js'});
  await window.LockXCredits.ready;
  return {events,requests,scripts,listeners,sessions,nodes,window,config,applepay,settings,storage,timers,api:window.__walletTest,async setup(){await window.__walletTest.setupApplePay();},click(){const button=nodes.get('#cwApplePay').children.find(el=>el.tag==='apple-pay-button');assert.ok(button,'Apple Pay button exists');syncGesture=true;button.onclick();syncGesture=false;return sessions.at(-1);},pick(id){listeners.click({preventDefault(){},target:{closest:()=>({dataset:{pickPack:id}})}});}};
}

const tests=[];
function test(name,fn){tests.push([name,fn]);}

test('Apple Pay container precedes PayPal fallback in the actual rendered wallet',async()=>{
  const h=await harness();const content=new Element();h.nodes.set('#cwDialogContent',content);h.nodes.set('#cwPayPal',new Element());
  await h.api.renderWallet();
  assert.ok(content.innerHTML.indexOf('id="cwApplePay"')<content.innerHTML.indexOf('id="cwPayPal"'));
});

test('device or provider ineligibility shows truthful status without an Apple Pay button',async()=>{
  for(const option of [{canMakePayments:false},{eligible:false}]){const h=await harness(option);await h.setup();assert.equal(h.nodes.get('#cwApplePay').children.some(el=>el.tag==='apple-pay-button'),false);assert.match(h.nodes.get('#cwApplePay').children[0].textContent,/unavailable/);}
});

test('Apple session begins synchronously and binds the selected 20 or 40 credit pack',async()=>{
  for(const [id,credits,amount] of [['regular',20,'10.00'],['large',40,'20.00']]){
    const h=await harness();await h.setup();h.api.setSelected(id);const session=h.click();
    assert.equal(session.request.total.amount,amount);assert.match(session.request.total.label,new RegExp(String(credits)));
    assert.deepEqual(h.events.slice(0,2),[['construct',true],['begin',true]]);
    h.pick(id==='regular'?'large':'regular');assert.equal(h.api.state().selected,id,'A different pack cannot replace the active pack');
    await session.onpaymentauthorized({payment:{token:{signed:'token'},billingContact:{postalCode:'12345'}}});
    const checkout=h.requests.find(r=>r.url.endsWith('/checkouts'));assert.equal(checkout.body.pack_id,id);assert.equal(checkout.body.provider,'apple_pay');assert.equal(session.results[0],1);
  }
});

test('provider token confirms the server order, then capture must complete before Apple success',async()=>{
  const capture=deferred(),captureStarted=deferred();const h=await harness({capture:()=>{captureStarted.resolve();return capture.promise;}});await h.setup();const session=h.click();
  const pending=session.onpaymentauthorized({payment:{token:{signed:'token'},billingContact:{postalCode:'12345'}}});await captureStarted.promise;
  assert.equal(h.events.find(e=>e[0]==='confirm')[1].orderId,'server-order');assert.equal(h.events.find(e=>e[0]==='confirm')[1].token.signed,'token');
  assert.equal(h.events.find(e=>e[0]==='capture')[1].order_id,'server-order');assert.equal(session.results.length,0,'No Apple success while capture is unresolved');
  capture.resolve();await pending;
  assert.equal(session.results[0],1);assert.ok(h.events.findIndex(e=>e[0]==='confirm')<h.events.findIndex(e=>e[0]==='capture'));assert.ok(h.events.findIndex(e=>e[0]==='capture')<h.events.findIndex(e=>e[0]==='complete'));
});

test('provider rejection or capture failure never reports Apple success and releases busy',async()=>{
  for(const options of [{confirm:async()=>({status:'DECLINED'})},{capture:async()=>{throw Error('Capture declined');}}]){
    const h=await harness(options);await h.setup();const session=h.click();await session.onpaymentauthorized({payment:{token:{}}});
    assert.equal(session.results.includes(1),false);assert.equal(session.results[0],0);assert.equal(h.api.state().busy,false);
  }
});

test('cancel releases busy and allows a new Apple session',async()=>{
  const h=await harness();await h.setup();const first=h.click();assert.equal(h.api.state().busy,true);first.oncancel();assert.equal(h.api.state().busy,false);h.pick('large');assert.equal(h.api.state().selected,'large');const second=h.click();assert.notEqual(first,second);assert.equal(second.request.total.amount,'20.00');
});

test('cancel while provider confirmation is pending prevents capture and Apple success',async()=>{
  const confirmation=deferred(),confirmStarted=deferred();const h=await harness({confirm:()=>{confirmStarted.resolve();return confirmation.promise;}});await h.setup();const session=h.click();
  const pending=session.onpaymentauthorized({payment:{token:{}}});await confirmStarted.promise;session.oncancel();assert.equal(h.api.state().busy,false);assert.equal(h.storage.has('lockx.checkoutAttempt'),false);
  confirmation.resolve({status:'APPROVED'});await pending;assert.equal(h.requests.some(r=>r.url.endsWith('/capture')),false);assert.equal(session.results.length,0);
});

test('cancel after capture starts holds busy until capture resolves and avoids ended-session success',async()=>{
  const capture=deferred(),captureStarted=deferred();const h=await harness({capture:()=>{captureStarted.resolve();return capture.promise;}});await h.setup();const session=h.click();
  const pending=session.onpaymentauthorized({payment:{token:{}}});await captureStarted.promise;session.oncancel();assert.equal(h.api.state().busy,true);h.click();assert.equal(h.sessions.length,1,'A pending capture cannot start another charge');
  capture.resolve();await pending;assert.equal(h.api.state().busy,false);assert.equal(session.results.length,0);assert.ok(h.requests.some(r=>r.url.endsWith('/wallet')),'Confirmed capture still refreshes credits');
});

test('SDK completion or abort exceptions always release busy',async()=>{
  const completed=await harness({completeThrows:true});await completed.setup();const success=completed.click();await success.onpaymentauthorized({payment:{token:{}}});assert.equal(completed.api.state().busy,false);assert.equal(success.results[0],1);
  const aborted=await harness({validationThrows:true,abortThrows:true});await aborted.setup();const failed=aborted.click();await failed.onvalidatemerchant({validationURL:'https://apple.example.test/session'});assert.equal(aborted.api.state().busy,false);assert.equal(failed.results.length,0);assert.ok(aborted.events.some(e=>e[0]==='abort'));
});

test('payment-method selection retains the amount and pack from the initial Apple sheet',async()=>{
  const h=await harness();await h.setup();const session=h.click();h.pick('large');session.onpaymentmethodselected();const update=h.events.find(e=>e[0]==='methodSelection')[1];assert.equal(update.newTotal.amount,'10.00');assert.equal(update.newTotal.label,session.request.total.label);assert.equal(h.api.state().selected,'regular');
});

test('confirmed capture followed by wallet refresh error does not claim payment failed',async()=>{
  const h=await harness({walletThrows:true});await h.setup();const session=h.click();await session.onpaymentauthorized({payment:{token:{}}});assert.equal(session.results[0],1);assert.equal(h.api.state().busy,false);assert.match(h.nodes.get('#cwMessage').textContent,/Payment confirmed/);assert.equal(h.nodes.get('#cwMessage').className,'cw-message');
});

test('concurrent wallet setup shares one PayPal SDK script containing both components',async()=>{
  const h=await harness({manualScripts:true});h.config.google_pay_ready=true;
  const a=h.api.loadPayPalWalletSDK();const b=h.api.loadPayPalWalletSDK();assert.equal(a,b);assert.equal(h.scripts.length,1);
  const url=new URL(h.scripts[0].src);assert.equal(url.origin,'https://www.paypal.com');assert.equal(url.searchParams.get('components'),'applepay,googlepay');
  h.window.paypal={Applepay:()=>h.applepay,Googlepay:()=>({})};h.scripts[0].onload();await Promise.all([a,b]);await h.api.loadPayPalWalletSDK();assert.equal(h.scripts.length,1);
});

test('wallet refresh failure cannot prevent independent Apple Pay setup',async()=>{
  const h=await harness({walletThrows:true});h.nodes.set('#cwDialogContent',new Element());h.nodes.set('#cwPayPal',new Element());
  await h.api.renderWallet();assert.equal(h.scripts.length,1,'Apple SDK starts without waiting for the wallet');await h.setup();assert.ok(h.nodes.get('#cwApplePay').children.some(el=>el.tag==='apple-pay-button'));
});

test('a pending wallet response does not block rendering or Apple Pay',async()=>{
  const wallet=deferred();const h=await harness({walletPending:wallet.promise});h.nodes.set('#cwDialogContent',new Element());h.nodes.set('#cwPayPal',new Element());
  await h.api.renderWallet();await h.setup();assert.ok(h.nodes.get('#cwApplePay').children.some(el=>el.tag==='apple-pay-button'));wallet.resolve();
});

test('provider and device ineligibility are checked again on retry without duplicating scripts',async()=>{
  for(const reason of ['provider','device']){
    const options=reason==='provider'?{eligible:false}:{canMakePayments:false};const h=await harness(options);await h.setup();assert.equal(h.scripts.length,1);h.settings.isEligible=true;options.canMakePayments=true;
    const retry=h.nodes.get('#cwApplePay').children.find(el=>el.tag==='button');assert.equal(retry.textContent,'Try Apple Pay again');await retry.onclick();
    assert.ok(h.nodes.get('#cwApplePay').children.some(el=>el.tag==='apple-pay-button'));assert.equal(h.scripts.length,1,'A loaded Apple SDK is reused on eligibility retry');
  }
});

test('a configuration error is visible and its retry can render the real Apple button',async()=>{
  const h=await harness();let calls=0;h.applepay.config=async()=>{if(++calls===1)throw Error('Provider unreachable');return h.settings;};await h.setup();assert.match(h.nodes.get('#cwApplePay').children[0].textContent,/could not load/);
  await h.nodes.get('#cwApplePay').children.find(el=>el.tag==='button').onclick();assert.ok(h.nodes.get('#cwApplePay').children.some(el=>el.tag==='apple-pay-button'));assert.equal(calls,2);
});

test('provider configuration times out after 15 seconds and retry resets initialization',async()=>{
  const h=await harness(),configuration=deferred(),started=deferred();h.applepay.config=()=>{started.resolve();return configuration.promise;};
  const pending=h.setup();await started.promise;assert.equal(h.timers.size,1,'Only the provider configuration deadline remains');const timer=[...h.timers.values()][0];assert.equal(timer.delay,15000);timer.fn();await pending;
  assert.equal(h.timers.size,0);assert.match(h.nodes.get('#cwApplePay').children[0].textContent,/could not load/);assert.equal(h.nodes.get('#cwApplePay').children.some(el=>el.tag==='apple-pay-button'),false);
  h.applepay.config=async()=>h.settings;await h.nodes.get('#cwApplePay').children.find(el=>el.tag==='button').onclick();assert.ok(h.nodes.get('#cwApplePay').children.some(el=>el.tag==='apple-pay-button'));assert.equal(h.timers.size,0);assert.equal(h.scripts.length,1,'The loaded SDK is reused after provider timeout');
  configuration.resolve({isEligible:false});assert.ok(h.nodes.get('#cwApplePay').children.some(el=>el.tag==='apple-pay-button'),'A late expired response cannot replace the recovered button');
});

test('script network error removes the failed element and allows a clean shared retry',async()=>{
  const h=await harness({manualScripts:true});const url='https://sdk.example.test/payment.js';const first=h.api.loadScript(url).catch(error=>error);h.scripts[0].onerror();const error=await first;assert.match(error.message,/could not load/);assert.equal(h.scripts[0].isConnected,false);assert.equal(h.timers.size,0);
  const retry=h.api.loadScript(url);assert.equal(h.api.loadScript(url),retry);assert.equal(h.scripts.length,2);h.scripts[1].onload();await retry;assert.equal(h.timers.size,0);
});

test('script loading times out after 15 seconds and a retry can succeed',async()=>{
  const h=await harness({manualScripts:true});const url='https://sdk.example.test/slow.js';const first=h.api.loadScript(url).catch(error=>error);const timer=[...h.timers.values()][0];assert.equal(timer.delay,15000);timer.fn();const error=await first;assert.match(error.message,/too long/);assert.equal(h.scripts[0].isConnected,false);
  const retry=h.api.loadScript(url);assert.equal(h.scripts.length,2);h.scripts[1].onload();await retry;assert.equal(h.timers.size,0);
});

module.exports=async function run(){const results=[];for(const [name,fn] of tests){try{await fn();results.push({name,status:'PASS'});}catch(error){results.push({name,status:'FAIL',error:error.stack});}}return results;};
