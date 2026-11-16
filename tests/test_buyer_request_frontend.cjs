/* Real browser module in a VM. No account, payment, AI call, or seller message is sent. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, '..', 'in-hand.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const response = (body, ok=true, status=200) => ({ok,status,json:async()=>body});
const managementKey = 'k'.repeat(43);
const record = (state='pending',extra={}) => ({id:'buyer-record',title:'Listing camera',status:state==='pending'?'waiting':'processing',token:'seller-capture-token',manage_key:managementKey,media:[],auto_publish:true,analysis_status:'pending',buyer_request:{state,listing_url:'https://market.example/items/123',buyer_funded:true,credit_reserved:true,expires:1795000000},...extra});
const listingURL='https://market.example/items/123';
const craigslistURL='https://sfbay.craigslist.org/sfc/pho/d/san-francisco-camera/7912345678.html';
const facebookURL='https://www.facebook.com/marketplace/item/123456789012345/';
const ebayURL='https://www.ebay.com/itm/123456789012';
const importResult=(url=listingURL,extra={})=>({status:'ready',listing_url:url,title:'Imported camera',imported_at:1795000000,expires:1795003600,import_token:'signed-import-snapshot',max_photos:4,photos:Array.from({length:4},(_,index)=>({index,mime:'image/jpeg',data_url:'data:image/jpeg;base64,'+Buffer.from([255,216,index,255,217]).toString('base64')})),...extra});
const emailDraft=(extra={})=>({contacts:[{email:'seller@market.example',label:'Listing seller',source:'Public listing'}],contact_url:null,recipient:'seller@market.example',subject:'Please verify the listing camera',body:'Hello seller,\n\nRecord here: https://lockx.example/#in-hand/capture/seller-capture-token\nListing: '+listingURL,draft_digest:'signed-email-draft',send_ready:true,status:'draft',...extra});
const manualPhoto=()=>{const blob=new Blob(['manual bytes'],{type:'image/jpeg'});return {blob,url:URL.createObjectURL(blob),selected:true,source:'manual'};};
const runTimer=async(h,ms)=>{const entry=[...h.timers].find(([,timer])=>timer.ms===ms);assert.ok(entry,`Timer ${ms} exists`);h.timers.delete(entry[0]);await entry[1].fn();await flush();};
class FormDataFake {
  constructor(){this.entries=[];}
  append(...entry){this.entries.push(entry);}
  get(key){return this.entries.find(entry=>entry[0]===key)?.[1];}
}
function harness(options={}) {
  const nodes=new Map(),requests=[],timers=new Map(),events={},calls={ensure:0,refresh:0,camera:0,recording:0,clipboard:[],shares:[]};let timer=0;
  class Element {
    constructor(){this._html='';this.htmlWrites=0;this.textContent='';this.hidden=false;this.isConnected=true;this.dataset={};this.style={};this.checked=false;this.disabled=false;this.value='';this.attributes={};this.classList={add(){},remove(){},toggle(){}};}
    get innerHTML(){return this._html;}
    set innerHTML(html){this._html=html;this.htmlWrites++;
      const decode=value=>value.replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
      for(const id of ['ihSellerEmailRecipient','ihSellerEmailSubject','ihSendSellerEmail','ihOpenSellerEmail']){
        const tag=html.match(new RegExp('<[^>]+id="'+id+'"[^>]*>'))?.[0],node=nodes.get('#'+id);
        if(tag&&node){node.value=decode(tag.match(/value="([^"]*)"/)?.[1]||'');node.disabled=/\sdisabled(?:\s|>)/.test(tag);node.attributes={};const href=tag.match(/href="([^"]*)"/)?.[1];if(href)node.attributes.href=decode(href);}
      }
      if(this.id==='in-hand'&&html.includes('id="ihRequestForm"')){
        nodes.get('#ihRequestForm').dataset.buyer=html.includes('data-buyer="true"')?'true':'false';
        nodes.get('#ihListingURL').value=html.match(/id="ihListingURL"[^>]*value="([^"]*)"/)?.[1]||'';
        nodes.get('#ihBuyerTitle').value='';
      }
    }
    append(node){if(node.id==='in-hand')nodes.set('#in-hand',node);}
    prepend(){}
    setAttribute(name,value){this.attributes[name]=value;}
    removeAttribute(name){delete this.attributes[name];}
    insertAdjacentHTML(){}
    addEventListener(){}
    scrollIntoView(){}
    closest(){return new Element();}
    focus(){this.focused=true;}
    select(){this.selected=true;}
    async play(){}
    querySelector(selector){return nodes.get(selector)||null;}
    querySelectorAll(selector){return selector==='input,select,[data-remove],[data-select],#ihChoosePhotos,#ihLoadListingPhotos'?['#ihListingURL','#ihBuyerTitle','#ihBuyerCaptureMode','#ihChoosePhotos','#ihLoadListingPhotos'].map(id=>nodes.get(id)):[];}
  }
  for(const id of ['main','#ihStandalone','#ihRequestForm','#ihChoosePhotos','#ihPhotoInput','#ihPhotoGrid','#ihLoadListingPhotos','#ihListingImportStatus','#ihMarketplacePolicy','#ihPhotoError','#ihCreate','#ihCreateError','#ihCreated','#ihListingURL','#ihBuyerTitle','#ihBuyerCaptureMode','#ihServiceState','#ihExport','.ih-report-head','#ihCopyBuyerMessage','#ihShareBuyerMessage','#ihCancelBuyerRequest','#ihBuyerMessage','#ihBuyerActionError','#ihSellerEmail','#ihSellerEmailRecipient','#ihSellerEmailContact','#ihSellerEmailSubject','#ihSellerEmailBody','#ihSendSellerEmail','#ihOpenSellerEmail','#ihRetrySellerEmailDraft','#ihStartCapture','#ihSellerConsent','#ihShareEvidence','#ihVoiceConsent','#ihCaptureError','#ihDeclineBuyerRequest','#ihLiveVideo','#ihLightStatus','#ihRecorderState','#ihInstructionTitle','#ihInstruction','.ih-auto-camera','#ihElapsed','#ihRemaining','#ihStepProgress','#ihPublicEvidence'])nodes.set(id,new Element());
  nodes.get('#ihRequestForm').dataset.buyer='true';nodes.get('#ihBuyerCaptureMode').value='handheld';nodes.get('#ihBuyerTitle').value='Listing camera';nodes.get('#ihListingURL').value='https://market.example/items/123';
  const document={body:new Element(),hidden:false,readyState:'loading',querySelector:selector=>nodes.get(selector)||null,querySelectorAll:()=>[],createElement:()=>new Element(),addEventListener(){}};
  const stream={getTracks:()=>[{stop(){}}],getVideoTracks:()=>[{stop(){}}]};
  class Recorder {static isTypeSupported(){return true;}constructor(){this.state='inactive';}start(){this.state='recording';calls.recording++;}}
  const window={isSecureContext:true,MediaRecorder:Recorder,LockXCapture:{stopRecorder(){}},innerHeight:800,innerWidth:400,speechSynthesis:{},matchMedia:()=>({matches:true}),scrollTo(){},addEventListener:(name,fn)=>events[name]=fn,LockXCredits:{authorization:async()=>options.noAuthorization?'':'Bearer fake-owner',ensureForVerification:async()=>{calls.ensure++;await options.ensure?.();},refresh:()=>{calls.refresh++;},decorate(){}}};
  const navigator={userAgent:'iPhone',clipboard:{writeText:async text=>{if(options.clipboardFail)throw Error('Clipboard unavailable');calls.clipboard.push(text);}},mediaDevices:{getUserMedia:async()=>{calls.camera++;return stream;}}};
  if(options.share)navigator.share=async data=>{calls.shares.push(data);if(options.shareFail)throw Error('Share unavailable');};
  const context={window,document,navigator,API_BASE:'https://api.example/v1',location:{hash:'#other',origin:'https://lockx.example',pathname:'/'},URL,URLSearchParams,Headers,Blob,Uint8Array,atob,FormData:FormDataFake,AbortController,Date,Intl,JSON,Promise,Map,Set,Number,Math,Error,crypto:webcrypto,MediaRecorder:Recorder,performance:{now:()=>100},btoa:value=>Buffer.from(value,'binary').toString('base64'),localStorage:{getItem:()=>null,setItem(){}},setTimeout:(fn,ms)=>{timers.set(++timer,{fn,ms});return timer;},clearTimeout:id=>timers.delete(id),setInterval:()=>999,clearInterval(){},go(){},toast(){},fetch:async(url,init={})=>{requests.push({url,init});if(url.endsWith('/capabilities'))return response({visual_comparison_ready:true,buyer_requests:true,listing_photo_import:true});return options.fetch?options.fetch(url,init):response(record());}};
  let code=source.replace(/\}\)\(\);\s*$/,`window.testBuyer={page,showBuyer,loadListingPhotos,scheduleListingImport,addPhotos,renderPhotos,createRequest,buyerMessage,buyerRequestBox,bindBuyerRequest,copyBuyerMessage,safeListingURL,sourceLink,reportFingerprint,pollReport,showReport,showSeller,showPublic,startCapture,route,loadSellerEmail,sellerEmailState,preparedEmailURL,safeSellerEmail,setManagementKey(value){managementKey=value;},setCapabilities(value){capabilities=value;},setPhotos(value){photos=value;},getPhotos(){return photos;},getAttempt(){return buyerAttempt;},setCompressor(fn){compressPhoto=fn;},setRoute(value){routeNumber=value;},setupCapture(record){document.querySelector('#ihSellerConsent').checked=true;sellerData=record;sellerToken='capture-token';routeNumber=1;isStandalone=true;location.hash='#in-hand/capture/capture-token';browserAccess.records[record.id]='${managementKey}';prepareCaptureLocation=async()=>false;renderCamera=()=>{document.querySelector('#ihShareEvidence').checked=false;};positionReticle=()=>{};requestCaptureLocation=()=>{};renderUploadStatus=()=>{};updateCameraFeedback=()=>{};pumpChunks=()=>{};speak=()=>{};}};})();`);
  vm.createContext(context);vm.runInContext(code,context);
  return {api:window.testBuyer,nodes,requests,timers,calls,context,events};
}

test('buyer create waits for fresh credit preflight and never starts buyer phone capture',async()=>{
  let finish;const gate=new Promise(resolve=>finish=resolve);
  const h=harness({ensure:()=>gate,fetch:async()=>response(record())});await flush();h.api.setPhotos([{blob:{bytes:'same-photo'},selected:true}]);
  const creation=h.api.createRequest({preventDefault(){}});await flush();assert.equal(h.requests.filter(r=>r.init.method==='POST').length,0);assert.equal(h.calls.ensure,1);
  finish();await creation;
  const request=h.requests.find(r=>r.url.endsWith('/requests')&&r.init.method==='POST'),payload=JSON.parse(request.init.body.get('payload'));
  assert.equal(payload.request_kind,'buyer');assert.ok(['handheld','flat','stationary','digital'].includes(payload.capture_mode));assert.equal(payload.listing_url,'https://market.example/items/123');assert.equal(payload.auto_publish,true);assert.equal(payload.publish_matched_photos,true);assert.equal(payload.consent,true);assert.match(payload.request_key,/^[A-Za-z0-9_-]{16,80}$/);
  assert.equal(h.context.location.hash,'in-hand/report/buyer-record/'+managementKey);assert.doesNotMatch(h.context.location.hash,/capture/);assert.equal(h.calls.refresh,1);
});

test('ambiguous creation retry uses original nonce, title, listing, and photo bytes without a second preflight',async()=>{
  let count=0;const h=harness({fetch:async()=>{if(++count===1)throw Error('Connection lost');return response(record());}});await flush();const photo={blob:{bytes:'original'},selected:true};h.api.setPhotos([photo]);
  await h.api.createRequest({preventDefault(){}});assert.ok(h.api.getAttempt());assert.equal(h.nodes.get('#ihBuyerTitle').disabled,true);
  h.nodes.get('#ihBuyerTitle').value='A changed title';h.nodes.get('#ihListingURL').value='https://other.example/other';h.api.setPhotos([{blob:{bytes:'changed'},selected:true}]);
  await h.api.createRequest({preventDefault(){}});
  const requests=h.requests.filter(r=>r.url.endsWith('/requests')&&r.init.method==='POST');assert.equal(requests.length,2);assert.equal(requests[0].init.body.get('payload'),requests[1].init.body.get('payload'));assert.equal(requests[1].init.body.get('photos'),photo.blob);assert.equal(h.calls.ensure,1);assert.equal(h.api.getAttempt(),null);
});

test('old-server capability and unsafe listing URL fail before any credit reservation',async()=>{
  const h=harness();await flush();h.api.setPhotos([{blob:{},selected:true}]);h.api.setCapabilities({visual_comparison_ready:true});await h.api.createRequest({preventDefault(){}});assert.equal(h.calls.ensure,0);assert.match(h.nodes.get('#ihCreateError').textContent,/not available.*No credit/);
  h.api.setCapabilities({buyer_requests:true});h.nodes.get('#ihListingURL').value='javascript:alert(1)';await h.api.createRequest({preventDefault(){}});assert.equal(h.calls.ensure,0);assert.equal(h.api.safeListingURL('https://user:password@market.example/item'),'');assert.equal(h.api.sourceLink({listing_url:'javascript:alert(1)'}),'');
});

test('seller invitation keeps email first and offers the same safe marketplace-share alternative',()=>{
  const h=harness({share:true}),r=record();const message=h.api.buyerMessage(r),html=h.api.buyerRequestBox(r);
  assert.match(message,/#in-hand\/capture\/seller-capture-token/);assert.match(message,/https:\/\/market.example\/items\/123/);assert.doesNotMatch(message,/report\/|kkkkk|manage/i);assert.match(html,/Copy or share this message yourself/);assert.ok(html.indexOf('ihSellerEmail')<html.indexOf('ihCopyBuyerMessage'));assert.doesNotMatch(html,/request sent|message sent/i);assert.match(html,/Copy message/);assert.match(html,/Share message/);assert.match(html,/Cancel request/);assert.match(html,/noopener noreferrer/);
});

test('Facebook Marketplace and eBay show a visible copy-first request with the actual listing and no email draft fetch',async()=>{
  for(const [listing_url,name] of [[facebookURL,'Facebook Marketplace'],[ebayURL,'eBay']]){
    const r=record();r.buyer_request.listing_url=listing_url;
    const h=harness({fetch:async()=>assert.fail('A platform conversation request must not fetch an email draft')});await flush();h.api.setRoute(1);h.api.setManagementKey(managementKey);await h.api.showReport(r.id,1,r);await flush();
    const html=h.api.page.innerHTML;assert.match(html,/Copy verification request/);assert.ok(html.includes('Open '+name+' ↗'));assert.ok(html.includes('href="'+listing_url+'"'));assert.match(html,/target="_blank" rel="noopener noreferrer"/);assert.ok(html.includes('existing '+name+' conversation'));assert.match(html,/paste it, and click Send there/);assert.match(html,/id="ihBuyerMessage"[^>]*readonly/);assert.match(html,/Copying only puts the message on your clipboard/);assert.match(html,/same 1-credit check; no extra charge/);
    assert.doesNotMatch(html,/id="ihSellerEmail"|ih-buyer-share-alternative|seller\/contact|messenger\.com|request (?:was )?sent/i);assert.ok(html.indexOf('Copy verification request')<html.indexOf('id="ihBuyerMessage"'));
    await h.nodes.get('#ihCopyBuyerMessage').onclick();assert.equal(h.calls.clipboard[0],h.api.buyerMessage(r));assert.match(h.calls.clipboard[0],/#in-hand\/capture\/seller-capture-token/);assert.ok(h.calls.clipboard[0].includes('Listing: '+listing_url));assert.match(h.calls.clipboard[0],/10-second LockX video/);assert.match(h.calls.clipboard[0],/50¢ check/);assert.match(h.calls.clipboard[0],/free for you/);assert.match(h.calls.clipboard[0],/no LockX account/);assert.match(h.calls.clipboard[0],/review the recording and sharing permissions/);assert.doesNotMatch(h.calls.clipboard[0],/report\/|kkkkk|manage|already verified|eBay approved|eBay endorsed|pay me|payment link/i);
    assert.equal(h.requests.filter(request=>request.url.endsWith('/seller-email')).length,0);assert.equal(h.requests.filter(request=>request.init.method==='POST').length,0);assert.equal(h.calls.ensure,0);assert.equal(h.calls.refresh,0);assert.equal(h.calls.camera,0);
    await h.api.loadSellerEmail(r,1);assert.equal(h.requests.filter(request=>request.url.endsWith('/seller-email')).length,0);
  }
});

test('marketplace conversation detection recognizes mobile Facebook paths and known eBay country domains',()=>{
  const h=harness();
  for(const listing_url of ['https://m.facebook.com/marketplace/item/123/','https://mbasic.facebook.com/marketplace/item/123/','https://facebook.com/marketplace/item/123/']){
    const r=record();r.buyer_request.listing_url=listing_url;assert.match(h.api.buyerRequestBox(r),/Open Facebook Marketplace ↗/);
  }
  for(const domain of ['ebay.com','ebay.ca','ebay.co.uk','ebay.com.au','ebay.at','ebay.be','ebay.fr','ebay.de','ebay.it','ebay.nl','ebay.es','ebay.ch','ebay.com.hk','ebay.ie','ebay.ph','ebay.pl','ebay.co.th','ebay.vn','ebay.co.jp']){
    const r=record();r.buyer_request.listing_url='https://www.'+domain+'/itm/123456789012';assert.match(h.api.buyerRequestBox(r),/Open eBay ↗/,domain);
  }
  const r=record();r.buyer_request.listing_url='https://m.ebay.co.uk/itm/123456789012';assert.match(h.api.buyerRequestBox(r),/Open eBay ↗/);assert.match(h.api.buyerMessage(r),/this is only an item verification request/);
});

test('eBay link restrictions are visible beside Copy and before request creation without affecting Facebook',async()=>{
  const r=record();r.buyer_request.listing_url=ebayURL;const h=harness();await flush();
  const html=h.api.buyerRequestBox(r);assert.match(html,/eBay restricts external links and may block this request\. Keep your purchase and payment on eBay\./);assert.ok(html.indexOf('eBay restricts external links')<html.indexOf('Copy verification request'));assert.match(html,/if the platform allows the verification link/);assert.match(h.api.buyerMessage(r),/Purchase and payment stay on eBay; this is only an item verification request\./);
  h.api.showBuyer(ebayURL);assert.equal(h.nodes.get('#ihMarketplacePolicy').hidden,false);assert.match(h.nodes.get('#ihMarketplacePolicy').textContent,/before creating a request and reserving 1 credit/);assert.equal(h.calls.ensure,0);assert.equal(h.requests.filter(request=>request.init.method==='POST').length,0);
  h.nodes.get('#ihListingURL').value=facebookURL;h.nodes.get('#ihListingURL').oninput();assert.equal(h.nodes.get('#ihMarketplacePolicy').hidden,true);r.buyer_request.listing_url=facebookURL;assert.doesNotMatch(h.api.buyerRequestBox(r),/eBay restricts|if the platform allows/);assert.doesNotMatch(h.api.buyerMessage(r),/payment stay on eBay/);
  h.nodes.get('#ihListingURL').value=ebayURL;h.nodes.get('#ihListingURL').oninput();assert.equal(h.nodes.get('#ihMarketplacePolicy').hidden,false);assert.equal(h.calls.ensure,0);
});

test('ambiguous paths and spoofed platform domains retain the generic email workflow',async()=>{
  for(const listing_url of ['https://facebook.com/marketplacefake/item/123','https://www.facebook.com/profile.php?id=123','https://facebook.com.evil.example/marketplace/item/123','https://notfacebook.com/marketplace/item/123','https://ebay.com.evil.example/itm/123','https://notebay.com/itm/123','https://ebay.example/itm/123']){
    const r=record();r.buyer_request.listing_url=listing_url;
    const h=harness({fetch:async()=>response(emailDraft())});await flush();h.api.setRoute(1);await h.api.showReport(r.id,1,r);await flush();
    assert.match(h.api.page.innerHTML,/id="ihSellerEmail"/);assert.doesNotMatch(h.api.page.innerHTML,/Open Facebook Marketplace|Open eBay|Copy verification request/);assert.equal(h.requests.filter(request=>request.url.endsWith('/seller-email')).length,1);
  }
});

test('platform clipboard failure selects the visible prepared message without sending',async()=>{
  const r=record();r.buyer_request.listing_url=facebookURL;
  const h=harness({clipboardFail:true});await flush();h.api.setRoute(1);await h.api.showReport(r.id,1,r);await h.nodes.get('#ihCopyBuyerMessage').onclick();
  assert.equal(h.nodes.get('#ihBuyerMessage').focused,true);assert.equal(h.nodes.get('#ihBuyerMessage').selected,true);assert.equal(h.requests.filter(request=>request.init.method==='POST'||request.url.endsWith('/seller-email')).length,0);assert.equal(h.calls.ensure,0);
});

test('native sharing failure falls back to copying the same seller message',async()=>{
  const h=harness({share:true,shareFail:true});h.api.bindBuyerRequest(record(),0);await h.nodes.get('#ihShareBuyerMessage').onclick();assert.equal(h.calls.shares.length,1);assert.equal(h.calls.clipboard[0],h.api.buyerMessage(record()));assert.doesNotMatch(JSON.stringify(h.calls.shares[0]),/report\/|kkkkk/);
});

test('clipboard failure selects the visible message for manual copy',async()=>{
  const h=harness({clipboardFail:true});await h.api.copyBuyerMessage(record(),h.nodes.get('#ihCopyBuyerMessage'));assert.equal(h.nodes.get('#ihBuyerMessage').focused,true);assert.equal(h.nodes.get('#ihBuyerMessage').selected,true);
});

test('seller sharing consent always starts unchecked, including locally saved recording permission',async()=>{
  const h=harness({fetch:async()=>response(record())});await flush();h.api.setRoute(1);await h.api.showSeller('seller-capture-token',1);const html=h.nodes.get('#ihStandalone').innerHTML;
  assert.match(html,/id="ihShareEvidence"/);assert.doesNotMatch(html,/id="ihShareEvidence"[^>]*checked/);assert.match(html,/The requester can view the private recording/);assert.match(html,/Decline request/);assert.match(html,/free for you, with no account/);
});

test('buyer and buyer retry captures require a fresh sharing decision; saved permission never grants it',async()=>{
  for(const data of [record(),{id:'retry',request_kind:'buyer',media:[]}]){
    const h=harness();h.api.setupCapture(data);await h.api.startCapture();assert.equal(h.calls.camera,0);assert.match(h.nodes.get('#ihCaptureError').textContent,/Agree to sharing/);assert.equal(h.requests.filter(r=>r.url.endsWith('/video/start')).length,0);
  }
});

test('capture sends the explicit sharing choice saved before camera rendering clears the checkbox',async()=>{
  for(const share of [true,false]){
    const h=harness({fetch:async url=>response(url.endsWith('/video/start')?{session_id:'session',stage:{instruction:'Turn item'}}:{})});h.api.setupCapture({id:'self-seller',media:[]});h.nodes.get('#ihShareEvidence').checked=share;await h.api.startCapture();
    const request=h.requests.find(r=>r.url.endsWith('/video/start'));assert.ok(request);assert.deepEqual(JSON.parse(request.init.body),{share_evidence:share});assert.equal(h.nodes.get('#ihShareEvidence').checked,false);assert.equal(h.calls.recording,1);
  }
});

test('buyer waiting polls leave copy controls untouched until the server state changes',async()=>{
  const r=record();const h=harness({fetch:async()=>response(r)});await flush();h.api.setRoute(1);await h.api.showReport(r.id,1,r);const before=h.api.page.htmlWrites;
  const timer=[...h.timers.values()].find(t=>t.ms===1800);assert.ok(timer);await timer.fn();assert.equal(h.api.page.htmlWrites,before);assert.match(h.api.page.innerHTML,/Awaiting seller/);assert.doesNotMatch(h.api.page.innerHTML,/Checking against frames from your recording/);
  assert.notEqual(h.api.reportFingerprint(r),h.api.reportFingerprint({...r,buyer_request:{...r.buyer_request,state:'declined'}}));
});

test('owner cancellation and seller decline use their own scoped authorities and explicit consent',async()=>{
  const h=harness({fetch:async url=>response(url.endsWith('/decline')?{}:record('cancelled',{status:'expired'}))});await flush();h.api.bindBuyerRequest(record(),0);await h.nodes.get('#ihCancelBuyerRequest').onclick();const cancel=h.requests.find(r=>r.url.endsWith('/cancel'));assert.deepEqual(JSON.parse(cancel.init.body),{consent:true});assert.equal(cancel.init.headers.get('Authorization'),'Bearer fake-owner');
  const seller=harness({fetch:async url=>response(url.endsWith('/decline')?{}:record())});await flush();seller.api.setRoute(1);await seller.api.showSeller('seller-capture-token',1);await seller.nodes.get('#ihDeclineBuyerRequest').onclick();const decline=seller.requests.find(r=>r.url.endsWith('/decline'));assert.deepEqual(JSON.parse(decline.init.body),{consent:true});assert.equal(decline.init.headers.get('Authorization'),null);assert.match(decline.url,/\/seller\/seller-capture-token\/decline$/);
});

test('public proof mounts the optional evidence viewer before the existing photo gallery',async()=>{
  const mounts=[];const h=harness({fetch:async()=>response({id:'proof',status:'verified',title:'Camera',total_count:1,photo_count:1,photos:[{id:'photo'}],scope:'Visual correspondence'})});h.context.window.LockXEvidence={mount:async(container,options)=>mounts.push({container,options})};await flush();h.api.setRoute(1);await h.api.showPublic('proof',1);assert.equal(mounts.length,1);assert.equal(mounts[0].options.apiBase,'https://api.example/v1/in-hand');assert.equal(mounts[0].options.publicationId,'proof');const html=h.nodes.get('#ihStandalone').innerHTML;assert.ok(html.indexOf('ihPublicEvidence')<html.indexOf('ih-public-gallery'));assert.match(html,/\/public\/proof\/photos\/photo/);
});

test('landing listing automatically loads four exact-byte JPEG Blobs without sign-in or credit preflight',async()=>{
  const result=importResult(),h=harness({fetch:async()=>response(result)});await flush();
  h.api.setCompressor(()=>assert.fail('Imported bytes must never be recompressed'));
  h.api.showBuyer(listingURL);await runTimer(h,0);
  const request=h.requests.find(request=>request.url.endsWith('/listing-import'));
  assert.deepEqual(JSON.parse(request.init.body),{url:listingURL});assert.equal(request.init.headers.get('Authorization'),null);assert.equal(request.init.headers.get('X-LockX-Guest-Key'),null);
  assert.equal(h.calls.ensure,0);assert.equal(h.calls.refresh,0);assert.equal(h.calls.camera,0);
  assert.equal(h.nodes.get('#ihBuyerTitle').value,'Imported camera');assert.equal(h.api.getPhotos().length,4);
  for(const [index,photo] of h.api.getPhotos().entries()){
    assert.ok(photo.blob instanceof Blob);assert.equal(photo.source,'listing_import');assert.equal(photo.importedIndex,index);assert.equal(photo.listingURL,listingURL);
    assert.deepEqual(Buffer.from(await photo.blob.arrayBuffer()),Buffer.from([255,216,index,255,217]));
  }
  assert.equal((h.nodes.get('#ihPhotoGrid').innerHTML.match(/From listing/g)||[]).length,4);assert.match(h.nodes.get('#ihListingImportStatus').textContent,/Loaded 4.*No credit/);
  assert.match(h.api.page.innerHTML,/Add screenshot or photos/);assert.doesNotMatch(h.api.page.innerHTML,/1–6|does not import|Save 1/);
});

test('form typing debounces imports and paste/change and the retry button load the current URL',async()=>{
  const h=harness({fetch:async(_url,init)=>response(importResult(JSON.parse(init.body).url))});await flush();h.api.showBuyer();
  const field=h.nodes.get('#ihListingURL');field.value=listingURL;field.oninput();field.oninput();
  assert.equal([...h.timers.values()].filter(timer=>timer.ms===550).length,1);assert.equal(h.requests.filter(request=>request.url.endsWith('/listing-import')).length,0);
  await runTimer(h,550);assert.equal(h.api.getPhotos().length,4);
  field.value='https://market.example/items/456';field.onchange();await runTimer(h,0);assert.equal(h.api.getPhotos()[0].listingURL,field.value);
  field.value='';field.onpaste();field.value=listingURL;await runTimer(h,0);
  await h.nodes.get('#ihLoadListingPhotos').onclick();assert.equal(h.requests.filter(request=>request.url.endsWith('/listing-import')).length,4);assert.equal(h.calls.ensure,0);
});

test('blocked imports and network errors keep the current photos and offer the screenshot fallback',async()=>{
  for(const fail of [()=>response(importResult(listingURL,{status:'unavailable',photos:[],import_token:''})),()=>{throw Error('Connection lost');}]){
    const h=harness({fetch:async()=>fail()});await flush();const original=manualPhoto();h.api.setPhotos([original]);await h.api.loadListingPhotos();
    assert.equal(h.api.getPhotos()[0],original);assert.equal(h.nodes.get('#ihLoadListingPhotos').disabled,false);assert.match(h.nodes.get('#ihListingImportStatus').textContent,/Add screenshot or photos.*current photos are kept/);assert.equal(h.calls.ensure,0);
  }
});

test('an import stalled in the browser times out with a usable retry and no credit action',async()=>{
  const h=harness({fetch:(_url,init)=>new Promise((_resolve,reject)=>init.signal.addEventListener('abort',()=>reject(Error('Timed out'))))});await flush();
  const original=manualPhoto();h.api.setPhotos([original]);const loading=h.api.loadListingPhotos();await runTimer(h,25000);await loading;
  assert.equal(h.api.getPhotos()[0],original);assert.equal(h.nodes.get('#ihLoadListingPhotos').disabled,false);assert.match(h.nodes.get('#ihListingImportStatus').textContent,/Add screenshot or photos/);assert.equal(h.calls.ensure,0);
});

test('Craigslist import explains the Reply email attempt while loading and keeps it free',async()=>{
  let finish;const h=harness({fetch:()=>new Promise(resolve=>finish=resolve)});await flush();h.nodes.get('#ihListingURL').value=craigslistURL;
  const original=manualPhoto();h.api.setPhotos([original]);const loading=h.api.loadListingPhotos();
  assert.match(h.nodes.get('#ihListingImportStatus').textContent,/Loading listing photos and trying Craigslist Reply → email/);assert.equal(h.api.getPhotos()[0],original);assert.equal(h.nodes.get('#ihLoadListingPhotos').disabled,true);
  finish(response(importResult(craigslistURL,{seller_contact:{reveal_status:'revealed',candidates:[{email:'camera-relay@sale.craigslist.org',source:'craigslist_reply'}]}})));await loading;
  assert.equal(h.api.getPhotos().length,4);assert.match(h.nodes.get('#ihListingImportStatus').textContent,/Seller email found through Craigslist Reply/);assert.equal(h.calls.ensure,0);assert.equal(h.calls.refresh,0);assert.equal(h.calls.camera,0);
});

test('blocked and busy Craigslist Reply checks preserve successful photos and signed contact provenance',async()=>{
  for(const reveal_status of ['blocked','busy','unavailable']){
    const h=harness({fetch:async url=>response(url.endsWith('/listing-import')?importResult(craigslistURL,{seller_contact:{reveal_status,candidates:[],contact_url:reveal_status==='blocked'?craigslistURL:null}}):record())});await flush();h.nodes.get('#ihListingURL').value=craigslistURL;
    await h.api.loadListingPhotos();assert.equal(h.api.getPhotos().length,4);assert.equal(h.nodes.get('#ihListingImportStatus').dataset.state,'ready');assert.match(h.nodes.get('#ihListingImportStatus').textContent,/Loaded 4 listing photos.*No credit was used.*Reply email could not load automatically/);assert.equal(h.calls.ensure,0);assert.equal(h.calls.refresh,0);
    h.api.setPhotos([manualPhoto()]);await h.api.createRequest({preventDefault(){}});const payload=JSON.parse(h.requests.find(request=>request.url.endsWith('/requests')).init.body.get('payload'));
    assert.equal(payload.contact_import_token,'signed-import-snapshot');assert.equal(payload.import_token,undefined);assert.equal(h.requests.filter(request=>request.url.endsWith('/seller-email')&&request.init.method==='POST').length,0);
  }
});

test('a Craigslist contact fallback survives an unavailable photo import without replacing manual photos',async()=>{
  const h=harness({fetch:async url=>response(url.endsWith('/listing-import')?importResult(craigslistURL,{status:'unavailable',photos:[],import_token:'signed-contact-fallback',seller_contact:{reveal_status:'blocked',candidates:[],contact_url:craigslistURL}}):record())});await flush();h.nodes.get('#ihListingURL').value=craigslistURL;
  const original=manualPhoto();h.api.setPhotos([original]);await h.api.loadListingPhotos();assert.equal(h.api.getPhotos()[0],original);assert.match(h.nodes.get('#ihListingImportStatus').textContent,/current photos are kept.*Reply email could not load automatically/);assert.equal(h.calls.ensure,0);
  await h.api.createRequest({preventDefault(){}});const payload=JSON.parse(h.requests.find(request=>request.url.endsWith('/requests')).init.body.get('payload'));assert.equal(payload.contact_import_token,'signed-contact-fallback');assert.equal(payload.import_token,undefined);
});

test('new URL input immediately aborts a pending import and its late response cannot replace photos',async()=>{
  let finish;const h=harness({fetch:()=>new Promise(resolve=>finish=resolve)});await flush();h.api.showBuyer();
  const original=manualPhoto();h.api.setPhotos([original]);h.nodes.get('#ihListingURL').value=listingURL;
  const pending=h.api.loadListingPhotos();const request=h.requests.find(request=>request.url.endsWith('/listing-import'));
  h.nodes.get('#ihListingURL').value='https://other.example/item';h.nodes.get('#ihListingURL').oninput();assert.equal(request.init.signal.aborted,true);
  finish(response(importResult()));await pending;assert.equal(h.api.getPhotos()[0],original);assert.equal(h.nodes.get('#ihBuyerTitle').value,'');
});

test('a newer successful import wins when an older fetch ignores abort and returns late',async()=>{
  const pending=[];const h=harness({fetch:()=>new Promise(resolve=>pending.push(resolve))});await flush();
  const first=h.api.loadListingPhotos();h.nodes.get('#ihListingURL').value='https://other.example/item';const second=h.api.loadListingPhotos();
  pending[1](response(importResult('https://other.example/item',{import_token:'new-token'})));await second;
  pending[0](response(importResult()));await first;assert.equal(h.api.getPhotos().length,4);assert.equal(h.api.getPhotos()[0].importToken,'new-token');
});

test('manual selection, removal, added photos, and title edits all invalidate pending imports',async()=>{
  for(const edit of ['select','remove','add','title']){
    let finish;const h=harness({fetch:()=>new Promise(resolve=>finish=resolve)});await flush();h.api.showBuyer();h.nodes.get('#ihListingURL').value=listingURL;
    const original=manualPhoto();h.api.setPhotos([original]);h.api.renderPhotos();const pending=h.api.loadListingPhotos();
    if(edit==='select')h.nodes.get('#ihPhotoGrid').oninput({target:{dataset:{select:'0'},checked:false}});
    if(edit==='remove')h.nodes.get('#ihPhotoGrid').onclick({target:{closest:()=>({dataset:{remove:'0'}})}});
    if(edit==='add'){h.api.setCompressor(async()=>manualPhoto());await h.api.addPhotos({target:{files:[{}],value:'chosen'}});}
    if(edit==='title'){h.nodes.get('#ihBuyerTitle').value='My title';h.nodes.get('#ihBuyerTitle').oninput();}
    finish(response(importResult()));await pending;
    assert.equal(h.api.getPhotos().some(photo=>photo.source==='listing_import'),false,edit);
    assert.equal(h.api.getPhotos().length,edit==='remove'?0:edit==='add'?2:1,edit);
    if(edit==='select')assert.equal(original.selected,false);
    if(edit==='title')assert.equal(h.nodes.get('#ihBuyerTitle').value,'My title');
  }
});

test('route changes and pagehide discard in-flight imports even if fetch returns a usable result',async()=>{
  for(const leave of ['route','pagehide']){
    let finish;const h=harness({fetch:()=>new Promise(resolve=>finish=resolve)});await flush();const original=manualPhoto();h.api.setPhotos([original]);const pending=h.api.loadListingPhotos();
    if(leave==='route')h.api.route();else h.events.pagehide();
    finish(response(importResult()));await pending;assert.equal(h.api.getPhotos()[0],original);assert.equal(h.requests.find(request=>request.url.endsWith('/listing-import')).init.signal.aborted,true);
  }
});

test('mixed manual and imported selections send aligned provenance and unchanged imported bytes',async()=>{
  const h=harness({fetch:async url=>response(url.endsWith('/listing-import')?importResult():record())});await flush();await h.api.loadListingPhotos();
  const imported=h.api.getPhotos();imported[1].selected=false;imported[2].selected=false;const manual=manualPhoto();h.api.setPhotos([...imported,manual]);
  await h.api.createRequest({preventDefault(){}});const request=h.requests.find(request=>request.url.endsWith('/requests')&&request.init.method==='POST');
  const payload=JSON.parse(request.init.body.get('payload'));assert.equal(payload.import_token,'signed-import-snapshot');assert.deepEqual(payload.imported_photo_indices,[0,3,null]);
  const blobs=request.init.body.entries.filter(entry=>entry[0]==='photos').map(entry=>entry[1]);assert.equal(blobs.length,3);assert.equal(blobs[0],imported[0].blob);assert.equal(blobs[1],imported[3].blob);assert.equal(blobs[2],manual.blob);assert.equal(h.calls.ensure,1);
});

test('selected imports from a different listing or snapshot fail before credit preflight',async()=>{
  for(const mismatch of ['listing','snapshot']){
    const h=harness({fetch:async()=>response(importResult())});await flush();await h.api.loadListingPhotos();
    if(mismatch==='listing')h.nodes.get('#ihListingURL').value='https://other.example/item';else h.api.getPhotos()[1].importToken='different-token';
    await h.api.createRequest({preventDefault(){}});assert.equal(h.calls.ensure,0);assert.match(h.nodes.get('#ihCreateError').textContent,/another listing or an earlier import.*No credit/);
  }
});

test('creation freezes the draft before credit preflight and blocks import replacement and retries',async()=>{
  let imported,credit;const importGate=new Promise(resolve=>imported=resolve),creditGate=new Promise(resolve=>credit=resolve);
  const h=harness({ensure:()=>creditGate,fetch:async url=>{if(url.endsWith('/listing-import'))return importGate;throw Error('Connection lost');}});await flush();
  const original=manualPhoto();h.api.setPhotos([original]);const loading=h.api.loadListingPhotos(),creation=h.api.createRequest({preventDefault(){}});
  imported(response(importResult()));await loading;assert.equal(h.api.getPhotos()[0],original);assert.equal(h.nodes.get('#ihLoadListingPhotos').disabled,true);
  h.nodes.get('#ihBuyerTitle').value='Programmatically changed';credit();await creation;
  const attempt=h.api.getAttempt();assert.equal(attempt.payload.title,'Listing camera');assert.equal(attempt.photos[0].blob,original.blob);assert.equal(h.nodes.get('#ihLoadListingPhotos').disabled,true);
  h.api.setPhotos([manualPhoto()]);
  await h.api.loadListingPhotos();h.api.showBuyer('https://other.example/item');
  assert.equal(h.requests.filter(request=>request.url.endsWith('/listing-import')).length,1);assert.equal([...h.timers.values()].filter(timer=>timer.ms===0||timer.ms===550).length,0);assert.equal(h.api.getAttempt(),attempt);assert.equal(h.api.getPhotos()[0].blob,original.blob);
});

test('seller and buyer creation and file selection enforce a four-photo cap before credits or decoding',async()=>{
  for(const buyer of [true,false]){
    const h=harness();await flush();h.nodes.get('#ihRequestForm').dataset.buyer=String(buyer);h.api.setPhotos(Array.from({length:5},manualPhoto));
    await h.api.createRequest({preventDefault(){}});assert.equal(h.calls.ensure,0);assert.match(h.nodes.get('#ihCreateError').textContent,/up to four/);
    h.api.setPhotos([]);h.api.setCompressor(()=>assert.fail('Over-limit files must not decode'));await h.api.addPhotos({target:{files:[{},{},{},{},{}],value:'chosen'}});assert.match(h.nodes.get('#ihPhotoError').textContent,/up to four/);assert.equal(h.api.getPhotos().length,0);
  }
  const wallet=fs.readFileSync(path.join(__dirname,'..','credit-wallet.js'),'utf8');assert.match(wallet,/includes up to four photos/);assert.doesNotMatch(wallet,/up to six photos/);
});

test('malformed, duplicate, and oversized listing photo sets cannot partially replace the selection',async()=>{
  const valid=importResult();
  for(const photos of [[...valid.photos,valid.photos[0]],[valid.photos[0],valid.photos[0]],[valid.photos[0],{index:1,mime:'image/jpeg',data_url:'https://bad.example/image.jpg'}]]){
    const h=harness({fetch:async()=>response(importResult(listingURL,{photos}))});await flush();const original=manualPhoto();h.api.setPhotos([original]);await h.api.loadListingPhotos();assert.equal(h.api.getPhotos()[0],original);assert.equal(h.nodes.get('#ihLoadListingPhotos').disabled,false);assert.equal(h.calls.ensure,0);
  }
});

test('private pending report prepares one email draft without sending, and polling preserves recipient edits',async()=>{
  const r=record(),h=harness({fetch:async url=>response(url.endsWith('/seller-email')?emailDraft():r)});await flush();h.api.setManagementKey(managementKey);h.api.setRoute(1);
  await h.api.showReport(r.id,1,r);await flush();
  assert.equal(h.requests.filter(request=>request.url.endsWith('/seller-email')).length,1);assert.equal(h.requests.filter(request=>request.init.method==='POST').length,0);
  const draftRequest=h.requests.find(request=>request.url.endsWith('/seller-email'));assert.equal(draftRequest.init.headers.get('X-LockX-Manage-Key'),managementKey);
  assert.equal(h.nodes.get('#ihSellerEmailRecipient').value,'seller@market.example');assert.equal(h.nodes.get('#ihSendSellerEmail').disabled,false);
  assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/id="ihSellerEmailSubject"[^>]*readonly/);assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/id="ihSellerEmailBody"[^>]*readonly/);assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/no extra charge/);
  h.nodes.get('#ihSellerEmailRecipient').value='reviewed@market.example';h.nodes.get('#ihSellerEmailRecipient').oninput();
  await h.api.showReport(r.id,1,{...r,status:'capturing'});await flush();
  assert.equal(h.nodes.get('#ihSellerEmailRecipient').value,'reviewed@market.example');assert.equal(h.requests.filter(request=>request.url.endsWith('/seller-email')).length,1);
  assert.equal(h.calls.ensure,0);assert.equal(h.calls.refresh,0);
});

test('seller email send is an explicit click, uses buyer Bearer despite management authority, and reports provider acceptance',async()=>{
  const h=harness({fetch:async(_url,init)=>response(emailDraft(init.method==='POST'?{status:'accepted',sent_to:'reviewed@market.example',send_ready:false,recipient_locked:true}:{}))});await flush();h.api.setManagementKey(managementKey);await h.api.loadSellerEmail(record(),1);
  h.nodes.get('#ihSellerEmailRecipient').value='reviewed@market.example';h.nodes.get('#ihSellerEmailRecipient').oninput();
  assert.equal(h.requests.filter(request=>request.init.method==='POST').length,0);
  await h.nodes.get('#ihSendSellerEmail').onclick();const sent=h.requests.find(request=>request.init.method==='POST');
  assert.equal(sent.init.headers.get('Authorization'),'Bearer fake-owner');assert.deepEqual(JSON.parse(sent.init.body),{recipient:'reviewed@market.example',draft_digest:'signed-email-draft',consent:true});
  assert.equal(h.nodes.get('#ihSendSellerEmail').disabled,true);assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/Email accepted for sending/);assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/does not confirm delivery/);assert.doesNotMatch(h.nodes.get('#ihSellerEmail').innerHTML,/Email delivered|Open prepared email|mailto:/);
  assert.equal(h.calls.ensure,0);assert.equal(h.calls.refresh,0);
});

test('simultaneous send clicks submit once and an uncertain retry keeps the exact recipient and draft',async()=>{
  let finish,count=0;const h=harness({fetch:async(_url,init)=>{if(init.method!=='POST')return response(emailDraft());if(++count===1)return new Promise((_resolve,reject)=>finish=()=>reject(Error('Connection lost')));return response(emailDraft({status:'accepted',sent_to:'seller@market.example'}));}});await flush();await h.api.loadSellerEmail(record(),1);
  const first=h.nodes.get('#ihSendSellerEmail').onclick();await flush();assert.equal(h.nodes.get('#ihSendSellerEmail').disabled,true);await h.nodes.get('#ihSendSellerEmail').onclick();assert.equal(count,1);
  finish();await first;assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/send result is not confirmed/);assert.equal(h.nodes.get('#ihSellerEmailRecipient').disabled,true);
  h.nodes.get('#ihSellerEmailRecipient').value='changed@market.example';h.nodes.get('#ihSellerEmailRecipient').oninput();await h.nodes.get('#ihSendSellerEmail').onclick();
  const sends=h.requests.filter(request=>request.init.method==='POST');assert.equal(sends.length,2);assert.equal(sends[0].init.body,sends[1].init.body);assert.equal(h.calls.ensure,0);assert.ok(sends.every(request=>request.url.endsWith('/seller-email')));
});

test('ambiguous contacts require an explicit choice, and manual recipient validation blocks header injection',async()=>{
  const h=harness({fetch:async()=>response(emailDraft({contacts:[{email:'sales@market.example',label:'Sales'},{email:'support@market.example',label:'Support'}],recipient:'sales@market.example'}))});await flush();await h.api.loadSellerEmail(record(),1);
  assert.equal(h.nodes.get('#ihSellerEmailRecipient').value,'');assert.equal(h.nodes.get('#ihSendSellerEmail').disabled,true);assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/more than one email contact/);
  h.nodes.get('#ihSellerEmailContact').value='sales@market.example';h.nodes.get('#ihSellerEmailContact').onchange();assert.equal(h.nodes.get('#ihSellerEmailRecipient').value,'sales@market.example');assert.equal(h.nodes.get('#ihSendSellerEmail').disabled,false);
  for(const invalid of ['seller@market.example\r\nBcc:other@market.example','one@market.example,two@market.example','Name <seller@market.example>']){h.nodes.get('#ihSellerEmailRecipient').value=invalid;h.nodes.get('#ihSellerEmailRecipient').oninput();assert.equal(h.nodes.get('#ihSendSellerEmail').disabled,true);assert.equal(h.api.safeSellerEmail(invalid),'');}
});

test('mail-app fallback encodes the reviewed email and template, strips subject line breaks, and never claims to send',async()=>{
  const h=harness({fetch:async()=>response(emailDraft({contacts:[],recipient:'',send_ready:false,contact_url:'https://market.example/seller/contact',subject:'Verify camera\r\nBcc: intruder@market.example',body:'Hi seller,\nItem? & details #1'}))});await flush();await h.api.loadSellerEmail(record(),1);
  assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/No seller email was found/);assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/Open seller contact page/);assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/Open prepared email/);assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/opening it does not send/);
  assert.equal(h.api.preparedEmailURL(h.api.sellerEmailState(record())),'');h.nodes.get('#ihSellerEmailRecipient').value='manual@market.example';h.nodes.get('#ihSellerEmailRecipient').oninput();
  const url=h.nodes.get('#ihOpenSellerEmail').attributes.href;assert.ok(url.startsWith('mailto:manual%40market.example?subject='));assert.ok(url.includes('body=Hi%20seller%2C%0D%0AItem%3F%20%26%20details%20%231'));assert.ok(!url.split('&body=')[0].includes('%0D'));assert.equal((url.match(/&/g)||[]).length,1);assert.equal(h.requests.filter(request=>request.init.method==='POST').length,0);
});

test('Craigslist Reply email is selected automatically for review without sending or exposing source codes',async()=>{
  const r=record();r.buyer_request.listing_url=craigslistURL;
  const h=harness({fetch:async()=>response(emailDraft({contacts:[{email:'camera-relay@sale.craigslist.org',label:'Listing seller',source:'craigslist_reply'}],recipient:'camera-relay@sale.craigslist.org',contact_reveal_status:'revealed'}))});await flush();await h.api.loadSellerEmail(r,1);
  assert.equal(h.nodes.get('#ihSellerEmailRecipient').value,'camera-relay@sale.craigslist.org');assert.equal(h.nodes.get('#ihSendSellerEmail').disabled,false);assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/Found through Craigslist Reply/);assert.doesNotMatch(h.nodes.get('#ihSellerEmail').innerHTML,/craigslist_reply|contact_reveal_status|No seller email|request sent/i);
  assert.equal(h.requests.filter(request=>request.init.method==='POST').length,0);assert.equal(h.calls.ensure,0);assert.equal(h.calls.refresh,0);
});

test('Craigslist blocked, busy, and unavailable Reply checks offer a paste relay fallback without claiming no email exists',async()=>{
  for(const contact_reveal_status of ['blocked','busy','unavailable']){
    const r=record();r.buyer_request.listing_url=craigslistURL;
    const contact_url=contact_reveal_status==='blocked'?craigslistURL:null,h=harness({fetch:async()=>response(emailDraft({contacts:[],recipient:'',contact_reveal_status,contact_url}))});await flush();await h.api.loadSellerEmail(r,1);
    const html=h.nodes.get('#ihSellerEmail').innerHTML;assert.match(html,/This listing keeps contact details behind Reply\. Open Craigslist, choose Reply then email, and paste the relay address here\./);assert.match(html,/Craigslist relay email/);assert.match(html,/aria-describedby="ihSellerEmailContactHelp"/);assert.match(html,/Copy the full email address shown under Reply → email/);assert.doesNotMatch(html,/No seller email was found|craigslist_reply|contact_reveal_status/);
    if(contact_url){assert.ok(html.includes('href="'+craigslistURL+'"'));assert.match(html,/Open Craigslist ↗/);assert.ok(html.indexOf('Open Craigslist ↗')<html.indexOf('id="ihSellerEmailRecipient"'));}else assert.doesNotMatch(html,/Open Craigslist ↗/);
    assert.equal(h.nodes.get('#ihSendSellerEmail').disabled,true);h.nodes.get('#ihSellerEmailRecipient').value='pasted-relay@sale.craigslist.org';h.nodes.get('#ihSellerEmailRecipient').oninput();assert.equal(h.nodes.get('#ihSendSellerEmail').disabled,false);
    assert.equal(h.requests.filter(request=>request.init.method==='POST').length,0);assert.equal(h.calls.ensure,0);assert.equal(h.calls.refresh,0);
  }
});

test('Craigslist contact assistance is scoped to the actual marketplace hostname and safe observed contact URLs',async()=>{
  for(const listing_url of ['https://craigslist.org.evil.example/item','https://notcraigslist.org/item']){
    const r=record();r.buyer_request.listing_url=listing_url;
    const h=harness({fetch:async()=>response(emailDraft({contacts:[],recipient:'',contact_reveal_status:'blocked',contact_url:'javascript:alert(1)'}))});await flush();await h.api.loadSellerEmail(r,1);
    assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/No seller email was found/);assert.doesNotMatch(h.nodes.get('#ihSellerEmail').innerHTML,/Craigslist relay email|Open Craigslist|javascript:/);
  }
});

test('a locked Craigslist email retry keeps the reviewed relay recipient without restarting contact fallback',async()=>{
  const r=record();r.buyer_request.listing_url=craigslistURL;
  const h=harness({fetch:async()=>response(emailDraft({contacts:[],recipient:'reviewed-relay@sale.craigslist.org',recipient_locked:true,contact_reveal_status:'blocked'}))});await flush();await h.api.loadSellerEmail(r,1);
  assert.equal(h.nodes.get('#ihSellerEmailRecipient').value,'reviewed-relay@sale.craigslist.org');assert.equal(h.nodes.get('#ihSellerEmailRecipient').disabled,true);assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/Review the fixed recipient and retry this same email/);assert.doesNotMatch(h.nodes.get('#ihSellerEmail').innerHTML,/No seller email was found|paste the relay address here|ihSellerEmailContactHelp/);assert.equal(h.requests.filter(request=>request.init.method==='POST').length,0);
});

test('draft preparation failure keeps copy/share available and retries only when clicked',async()=>{
  let count=0;const h=harness({fetch:async()=>{if(++count===1)throw Error('Offline');return response(emailDraft());}});await flush();await h.api.loadSellerEmail(record(),1);
  assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/Offline/);assert.match(h.api.buyerRequestBox(record()),/Copy message/);await h.api.loadSellerEmail(record(),1);assert.equal(count,1);
  await h.nodes.get('#ihRetrySellerEmailDraft').onclick();await flush();assert.equal(count,2);assert.equal(h.nodes.get('#ihSellerEmailRecipient').value,'seller@market.example');
});

test('sending requires the buyer account and leaves the prepared email intact when signed out',async()=>{
  const h=harness({noAuthorization:true,fetch:async()=>response(emailDraft())});await flush();await h.api.loadSellerEmail(record(),1);await h.nodes.get('#ihSendSellerEmail').onclick();assert.equal(h.requests.filter(request=>request.init.method==='POST').length,0);assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/Sign in to the buyer account/);assert.equal(h.nodes.get('#ihSellerEmailRecipient').value,'seller@market.example');assert.equal(h.nodes.get('#ihSendSellerEmail').disabled,false);
});

test('reloaded uncertain emails retain their frozen recipient even when the listing has no contacts',async()=>{
  const h=harness({fetch:async(_url,init)=>response(emailDraft({contacts:[],recipient:'original@market.example',recipient_locked:true,status:init.method==='POST'?'accepted':'uncertain',sent_to:init.method==='POST'?'original@market.example':null}))});await flush();await h.api.loadSellerEmail(record(),1);assert.equal(h.nodes.get('#ihSellerEmailRecipient').value,'original@market.example');assert.equal(h.nodes.get('#ihSellerEmailRecipient').disabled,true);await h.nodes.get('#ihSendSellerEmail').onclick();assert.deepEqual(JSON.parse(h.requests.find(request=>request.init.method==='POST').init.body),{recipient:'original@market.example',draft_digest:'signed-email-draft',consent:true});
});

test('late email draft loads update only the currently displayed request and are reusable after route return',async()=>{
  let finish;const h=harness({fetch:()=>new Promise(resolve=>finish=resolve)});await flush();h.api.setRoute(1);const first=h.api.loadSellerEmail(record(),1);h.api.setRoute(2);await h.api.loadSellerEmail(record(),2);finish(response(emailDraft()));await first;assert.equal(h.nodes.get('#ihSellerEmailRecipient').value,'seller@market.example');assert.equal(h.requests.filter(request=>request.url.endsWith('/seller-email')).length,1);
});

test('contact provenance survives manual photos or unavailable photo imports, and never crosses listing URLs',async()=>{
  for(const unavailable of [false,true]){
    const h=harness({fetch:async url=>response(url.endsWith('/listing-import')?importResult(listingURL,unavailable?{status:'unavailable',photos:[],import_token:'signed-contacts-only',seller_contact:{emails:[{email:'seller@market.example'}]}}:{}):record())});await flush();await h.api.loadListingPhotos();h.api.setPhotos([manualPhoto()]);await h.api.createRequest({preventDefault(){}});
    const payload=JSON.parse(h.requests.find(request=>request.url.endsWith('/requests')).init.body.get('payload'));assert.equal(payload.contact_import_token,unavailable?'signed-contacts-only':'signed-import-snapshot');assert.equal(payload.import_token,undefined);
  }
  const h=harness({fetch:async url=>response(url.endsWith('/listing-import')?importResult():record())});await flush();await h.api.loadListingPhotos();h.api.setPhotos([manualPhoto()]);h.nodes.get('#ihListingURL').value='https://other.example/item';await h.api.createRequest({preventDefault(){}});const payload=JSON.parse(h.requests.find(request=>request.url.endsWith('/requests')).init.body.get('payload'));assert.equal(payload.contact_import_token,undefined);
});

test('attempted emails never offer a mail-app duplicate and a provider cooldown permits only the same retry',async()=>{
  for(const status of ['accepted','sending','uncertain']){
    const h=harness({fetch:async()=>response(emailDraft({status,recipient_locked:true,send_ready:false,message:'Check the seller conversation first.'}))});await flush();await h.api.loadSellerEmail(record(),1);assert.doesNotMatch(h.nodes.get('#ihSellerEmail').innerHTML,/Open prepared email|mailto:/);assert.equal(h.nodes.get('#ihSellerEmailRecipient').disabled,true);assert.equal(h.nodes.get('#ihSendSellerEmail').disabled,status!=='sending');
  }
  const h=harness({fetch:async(_url,init)=>response(emailDraft({status:init.method==='POST'?'accepted':'draft',recipient_locked:true,send_ready:false,retry_after:init.method==='POST'?0:60}))});await flush();await h.api.loadSellerEmail(record(),1);assert.match(h.nodes.get('#ihSellerEmail').innerHTML,/Retry available shortly/);assert.equal(h.nodes.get('#ihSendSellerEmail').disabled,true);assert.equal(h.requests.filter(request=>request.init.method==='POST').length,0);
  await runTimer(h,60000);assert.equal(h.nodes.get('#ihSendSellerEmail').disabled,false);assert.equal(h.requests.filter(request=>request.init.method==='POST').length,0);await h.nodes.get('#ihSendSellerEmail').onclick();assert.equal(h.requests.filter(request=>request.init.method==='POST').length,1);assert.equal(h.calls.ensure,0);
});
