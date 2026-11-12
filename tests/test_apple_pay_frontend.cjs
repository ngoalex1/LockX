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
}

async function harness(options={}) {
  const events=[], requests=[], scripts=[], listeners={}, sessions=[];
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
    if(url.endsWith('/wallet')){if(options.walletThrows)throw Error('Wallet temporarily unavailable');return response({balance:20,history:[]});}
    if(url.endsWith('/capture')){events.push(['capture',body]);if(options.capture)await options.capture(body);return response({status:'paid'});}
    if(url.endsWith('/checkouts')&&init.method==='POST')return response({id:'checkout-20',paypal_order_id:'server-order',credits:body.pack_id==='large'?40:20,status:'pending'});
    return response({status:'pending'});
  };
  const context={window,document,fetch,ApplePaySession:Session,API_BASE:'https://api.example.test',location:{search:'',origin:'https://lockx.ai'},URL,URLSearchParams,sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},crypto:{randomUUID:()=> 'idempotency-key'},setInterval:()=>1,clearInterval(){},setTimeout(){},console};
  vm.createContext(context);
  const instrumented=source.replace('window.LockXCredits={ready,', 'window.__walletTest={setupApplePay,loadPayPalWalletSDK,renderWallet,updatePackSummary,setSelected:value=>{selected=value;},state:()=>({selected,busy,appleSession})};window.LockXCredits={ready,');
  assert.notEqual(instrumented,source,'Test instrumentation must find the public export.');
  vm.runInContext(instrumented,context,{filename:'credit-wallet.js'});
  await window.LockXCredits.ready;
  return {events,requests,scripts,listeners,sessions,nodes,window,config,applepay,storage,api:window.__walletTest,async setup(){await window.__walletTest.setupApplePay();},click(){const button=nodes.get('#cwApplePay').children[0];assert.ok(button,'Apple Pay button exists');syncGesture=true;button.onclick();syncGesture=false;return sessions.at(-1);},pick(id){listeners.click({preventDefault(){},target:{closest:()=>({dataset:{pickPack:id}})}});}};
}

const tests=[];
function test(name,fn){tests.push([name,fn]);}

test('Apple Pay container precedes PayPal fallback in the actual rendered wallet',async()=>{
  const h=await harness();const content=new Element();h.nodes.set('#cwDialogContent',content);h.nodes.set('#cwPayPal',new Element());
  await h.api.renderWallet();
  assert.ok(content.innerHTML.indexOf('id="cwApplePay"')<content.innerHTML.indexOf('id="cwPayPal"'));
});

test('device or provider ineligibility leaves Apple Pay hidden',async()=>{
  for(const option of [{canMakePayments:false},{eligible:false}]){const h=await harness(option);await h.setup();assert.equal(h.nodes.get('#cwApplePay').hidden,true);assert.equal(h.nodes.get('#cwApplePay').children.length,0);}
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

module.exports=async function run(){const results=[];for(const [name,fn] of tests){try{await fn();results.push({name,status:'PASS'});}catch(error){results.push({name,status:'FAIL',error:error.stack});}}return results;};
