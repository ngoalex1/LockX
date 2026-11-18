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
  const nodes=new Map(),requests=[],timers=new Map(),events={},calls={ensure:0,refresh:0,camera:0,recording:0,clipboard:[],shares:[],navigation:[]};let timer=0;
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
  for(const id of ['main','#ihStandalone','#ihRequestForm','#ihChoosePhotos','#ihPhotoInput','#ihPhotoGrid','#ihLoadListingPhotos','#ihListingImportStatus','#ihMarketplacePolicy','#ihPhotoError','#ihCreate','#ihCreateError','#ihCreated','#ihListingURL','#ihBuyerTitle','#ihBuyerCaptureMode','#ihServiceState','#ihExport','.ih-report-head','#ihCopyBuyerMessage','#ihShareBuyerMessage','#ihCancelBuyerRequest','#ihBuyerMessage','#ihBuyerMessageReview','#ihMarketplaceCopyStatus','#ihBuyerActionError','#ihSellerEmail','#ihSellerEmailRecipient','#ihSellerEmailContact','#ihSellerEmailSubject','#ihSellerEmailBody','#ihSendSellerEmail','#ihOpenSellerEmail','#ihRetrySellerEmailDraft','#ihStartCapture','#ihSellerConsent','#ihShareEvidence','#ihVoiceConsent','#ihCaptureError','#ihDeclineBuyerRequest','#ihLiveVideo','#ihLightStatus','#ihRecorderState','#ihInstructionTitle','#ihInstruction','.ih-auto-camera','#ihElapsed','#ihRemaining','#ihStepProgress','#ihPublicEvidence','#ihRetryCapture','#ihRetryCaptureConsent','#ihQualityRetryError','#ihRetryAnalysis','#ihRetrySelectionLabel'])nodes.set(id,new Element());
  nodes.get('#ihRequestForm').dataset.buyer='true';nodes.get('#ihBuyerCaptureMode').value='handheld';nodes.get('#ihBuyerTitle').value='Listing camera';nodes.get('#ihListingURL').value='https://market.example/items/123';
  const document={body:new Element(),hidden:false,readyState:'loading',querySelector:selector=>nodes.get(selector)||null,querySelectorAll:selector=>[...nodes.values()].filter(node=>selector==='[data-retry-photo-index]'?node.dataset?.retryPhotoIndex!==undefined:selector==='[data-retry-this-photo]'?node.dataset?.retryThisPhoto!==undefined:selector==='[data-retry-all-failed]'?node.dataset?.retryAllFailed!==undefined:false),createElement:()=>new Element(),addEventListener(){}};
  const stream={getTracks:()=>[{stop(){}}],getVideoTracks:()=>[{stop(){}}]};
  class Recorder {static isTypeSupported(){return true;}constructor(){this.state='inactive';}start(){this.state='recording';calls.recording++;}}
  const window={isSecureContext:true,MediaRecorder:Recorder,LockXCapture:{stopRecorder(){}},innerHeight:800,innerWidth:400,speechSynthesis:{},matchMedia:()=>({matches:true}),scrollTo(){},addEventListener:(name,fn)=>events[name]=fn,LockXCredits:{authorization:async()=>options.noAuthorization?'':'Bearer fake-owner',ensureForVerification:async()=>{calls.ensure++;await options.ensure?.();},refresh:()=>{calls.refresh++;},decorate(){}}};
  const navigator={userAgent:'iPhone',clipboard:{writeText:async text=>{if(options.clipboardFail)throw Error('Clipboard unavailable');await options.clipboardWrite?.(text);calls.clipboard.push(text);}},mediaDevices:{getUserMedia:async()=>{calls.camera++;return stream;}}};
  if(options.share)navigator.share=async data=>{calls.shares.push(data);if(options.shareFail)throw Error('Share unavailable');};
  const context={window,document,navigator,API_BASE:'https://api.example/v1',location:{hash:'#other',origin:'https://lockx.example',pathname:'/',assign:url=>calls.navigation.push(url)},URL,URLSearchParams,Headers,Blob,Uint8Array,atob,FormData:FormDataFake,AbortController,Date,Intl,JSON,Promise,Map,Set,Number,Math,Error,crypto:webcrypto,MediaRecorder:Recorder,performance:{now:()=>100},btoa:value=>Buffer.from(value,'binary').toString('base64'),localStorage:{getItem:()=>null,setItem(){}},setTimeout:(fn,ms)=>{timers.set(++timer,{fn,ms});return timer;},clearTimeout:id=>timers.delete(id),setInterval:()=>999,clearInterval(){},go(){},toast(){},fetch:async(url,init={})=>{requests.push({url,init});if(url.endsWith('/capabilities'))return response({visual_comparison_ready:true,buyer_requests:true,listing_photo_import:true});return options.fetch?options.fetch(url,init):response(record());}};
  let code=source.replace(/\}\)\(\);\s*$/,`window.testBuyer={page,showBuyer,loadListingPhotos,scheduleListingImport,addPhotos,renderPhotos,createRequest,buyerMessage,buyerRequestBox,bindBuyerRequest,copyBuyerMessage,safeListingURL,sourceLink,reportFingerprint,pollReport,showReport,showSeller,showSellerResult,showPublic,startCapture,route,loadSellerEmail,sellerEmailState,preparedEmailURL,safeSellerEmail,captureRetryState,rootPhotoIndex,rootRetryPolicy,rootPhotoRetryPanel,retrySelection,setRetrySelection,captureNavigation,captureAttemptLabel,captureRetryBox,captureAttemptHistory,bindCaptureRetry,captureGuidance,watchCaptureAttempts,photoResultCards,photoMatchPercentage,photoMatchScope,processingActivity,publicationBox,managementBox,setManagementKey(value){managementKey=value;},setCapabilities(value){capabilities=value;},setPhotos(value){photos=value;},getPhotos(){return photos;},getAttempt(){return buyerAttempt;},setCompressor(fn){compressPhoto=fn;},setRoute(value){routeNumber=value;},setupCapture(record){document.querySelector('#ihSellerConsent').checked=true;sellerData=record;sellerToken='capture-token';routeNumber=1;isStandalone=true;location.hash='#in-hand/capture/capture-token';browserAccess.records[record.id]='${managementKey}';prepareCaptureLocation=async()=>false;renderCamera=()=>{document.querySelector('#ihShareEvidence').checked=false;};positionReticle=()=>{};requestCaptureLocation=()=>{};renderUploadStatus=()=>{};updateCameraFeedback=()=>{};pumpChunks=()=>{};speak=()=>{};}};})();`);
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

test('Facebook Marketplace and eBay copy the reviewed request and open the original listing in the same tab without email calls',async()=>{
  for(const [listing_url,name] of [[facebookURL,'Facebook Marketplace'],[ebayURL,'eBay']]){
    const r=record();r.buyer_request.listing_url=listing_url;
    const h=harness({fetch:async()=>assert.fail('A platform conversation request must not fetch an email draft')});await flush();h.api.setRoute(1);h.api.setManagementKey(managementKey);await h.api.showReport(r.id,1,r);await flush();
    const html=h.api.page.innerHTML;assert.match(html,/Copy request &amp; open listing/);assert.ok(html.includes('Open '+name+' ↗'));assert.ok(html.includes('href="'+listing_url+'"'));assert.match(html,/target="_blank" rel="noopener noreferrer"/);assert.ok(html.includes('Copy the request and open '+name+' in one tap.'));assert.match(html,/<h2>Your request is ready\.<\/h2>/);assert.match(html,/Paste in the seller chat, then tap Send/);assert.match(html,/id="ihBuyerMessage"[^>]*readonly/);assert.match(html,/Paste in the seller chat, then tap Send\. Same 1-credit check; no extra charge\./);assert.match(html,/<details id="ihBuyerMessageReview"[^>]*><summary>Review message<\/summary>/);assert.match(html,/Same 1-credit check; no extra charge/);
    assert.doesNotMatch(html,/id="ihSellerEmail"|ih-buyer-share-alternative|seller\/contact|messenger\.com|request (?:was )?sent/i);assert.ok(html.indexOf('Copy request &amp; open listing')<html.indexOf('id="ihBuyerMessage"'));
    await h.nodes.get('#ihCopyBuyerMessage').onclick();assert.equal(h.calls.clipboard[0],h.api.buyerMessage(r));assert.match(h.calls.clipboard[0],/#in-hand\/capture\/seller-capture-token/);assert.ok(h.calls.clipboard[0].includes('Listing: '+listing_url));assert.match(h.calls.clipboard[0],/10-second LockX video/);assert.match(h.calls.clipboard[0],/50¢ check/);assert.match(h.calls.clipboard[0],/free for you/);assert.match(h.calls.clipboard[0],/no LockX account/);assert.match(h.calls.clipboard[0],/review the recording and sharing permissions/);assert.doesNotMatch(h.calls.clipboard[0],/report\/|kkkkk|manage|already verified|eBay approved|eBay endorsed|pay me|payment link/i);
    assert.deepEqual(h.calls.navigation,[listing_url]);assert.equal(h.nodes.get('#ihMarketplaceCopyStatus').textContent,'Copied. Paste in the seller chat, then tap Send.');
    assert.equal(h.requests.filter(request=>request.url.endsWith('/seller-email')).length,0);assert.equal(h.requests.filter(request=>request.init.method==='POST').length,0);assert.equal(h.calls.ensure,0);assert.equal(h.calls.refresh,0);assert.equal(h.calls.camera,0);
    await h.api.loadSellerEmail(r,1);assert.equal(h.requests.filter(request=>request.url.endsWith('/seller-email')).length,0);
  }
});

test('the combined marketplace action waits for successful clipboard access before navigating',async()=>{
  for(const listing_url of [facebookURL,ebayURL]){
    let finish;const h=harness({clipboardWrite:()=>new Promise(resolve=>finish=resolve)});await flush();const r=record();r.buyer_request.listing_url=listing_url;h.api.bindBuyerRequest(r,1);
    const copying=h.nodes.get('#ihCopyBuyerMessage').onclick();assert.deepEqual(h.calls.navigation,[]);assert.deepEqual(h.calls.clipboard,[]);
    finish();await copying;assert.deepEqual(h.calls.clipboard,[h.api.buyerMessage(r)]);assert.deepEqual(h.calls.navigation,[listing_url]);assert.equal(h.requests.filter(request=>request.init.method==='POST'||request.url.endsWith('/seller-email')).length,0);
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
  const html=h.api.buyerRequestBox(r);assert.match(html,/eBay restricts external links and may block this request\. Keep your purchase and payment on eBay\./);assert.ok(html.indexOf('eBay restricts external links')<html.indexOf('Copy request &amp; open listing'));assert.match(h.api.buyerMessage(r),/Purchase and payment stay on eBay; this is only an item verification request\./);
  h.api.showBuyer(ebayURL);assert.equal(h.nodes.get('#ihMarketplacePolicy').hidden,false);assert.match(h.nodes.get('#ihMarketplacePolicy').textContent,/before creating a request and reserving 1 credit/);assert.equal(h.calls.ensure,0);assert.equal(h.requests.filter(request=>request.init.method==='POST').length,0);
  h.nodes.get('#ihListingURL').value=facebookURL;h.nodes.get('#ihListingURL').oninput();assert.equal(h.nodes.get('#ihMarketplacePolicy').hidden,true);r.buyer_request.listing_url=facebookURL;assert.doesNotMatch(h.api.buyerRequestBox(r),/eBay restricts/);assert.doesNotMatch(h.api.buyerMessage(r),/payment stay on eBay/);
  h.nodes.get('#ihListingURL').value=ebayURL;h.nodes.get('#ihListingURL').oninput();assert.equal(h.nodes.get('#ihMarketplacePolicy').hidden,false);assert.equal(h.calls.ensure,0);
});

test('ambiguous paths and spoofed platform domains retain the generic email workflow',async()=>{
  for(const listing_url of ['https://facebook.com/marketplacefake/item/123','https://www.facebook.com/profile.php?id=123','https://facebook.com.evil.example/marketplace/item/123','https://notfacebook.com/marketplace/item/123','https://ebay.com.evil.example/itm/123','https://notebay.com/itm/123','https://ebay.example/itm/123','https://ebay.com@evil.example/itm/123','javascript:alert(1)']){
    const r=record();r.buyer_request.listing_url=listing_url;
    const h=harness({fetch:async()=>response(emailDraft())});await flush();h.api.setRoute(1);await h.api.showReport(r.id,1,r);await flush();
    assert.match(h.api.page.innerHTML,/id="ihSellerEmail"/);assert.doesNotMatch(h.api.page.innerHTML,/Open Facebook Marketplace|Open eBay|Copy request &amp; open listing/);assert.equal(h.requests.filter(request=>request.url.endsWith('/seller-email')).length,1);
    await h.nodes.get('#ihCopyBuyerMessage').onclick();assert.deepEqual(h.calls.navigation,[]);
  }
});

test('failed marketplace clipboard access expands and selects the prepared message without navigating or sending',async()=>{
  for(const listing_url of [facebookURL,ebayURL]){
    const r=record();r.buyer_request.listing_url=listing_url;
    const h=harness({clipboardFail:true});await flush();h.api.setRoute(1);await h.api.showReport(r.id,1,r);h.nodes.get('#ihBuyerMessage').hidden=true;await h.nodes.get('#ihCopyBuyerMessage').onclick();
    assert.equal(h.nodes.get('#ihBuyerMessageReview').open,true);assert.equal(h.nodes.get('#ihBuyerMessage').hidden,false);assert.equal(h.nodes.get('#ihBuyerMessage').focused,true);assert.equal(h.nodes.get('#ihBuyerMessage').selected,true);assert.deepEqual(h.calls.navigation,[]);assert.match(h.nodes.get('#ihMarketplaceCopyStatus').textContent,/Copy the selected message.*Paste in the seller chat, then tap Send/);assert.equal(h.requests.filter(request=>request.init.method==='POST'||request.url.endsWith('/seller-email')).length,0);assert.equal(h.calls.ensure,0);
  }
});

test('generic listing and Craigslist copy actions keep the current page',async()=>{
  for(const listing_url of [listingURL,craigslistURL]){
    const h=harness();await flush();const r=record();r.buyer_request.listing_url=listing_url;h.api.bindBuyerRequest(r,1);await h.nodes.get('#ihCopyBuyerMessage').onclick();
    assert.deepEqual(h.calls.clipboard,[h.api.buyerMessage(r)]);assert.deepEqual(h.calls.navigation,[]);assert.match(h.api.buyerRequestBox(r),/id="ihSellerEmail"/);
  }
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

const attemptRecord=(number=1,extra={})=>({id:'attempt-'+number,token:'t'.repeat(43),status:'inconclusive',analysis_status:'complete',publication_status:'not_eligible',media:[],photos:[{photo_index:0,finding:'not_established',evidence:'Printed number unreadable.'}],identifier_checks:[],eligible_photo_indices:[],verified_count:0,total_count:1,summary:'More evidence is needed.',capture_mode:'handheld',capture_retry:{attempt_number:number,max_attempts:3,remaining_attempts:3-number,allowed:number<3,action:number<3?'create':'none',next_attempt_number:number<3?number+1:null,light_assist_reason:null,blocked_reason:number===3?'limit_reached':null},...extra});

test('server-counted attempts show one of three, two of three and exhausted three without a fourth recording CTA',()=>{
  const h=harness();
  for(const number of [1,2,3]){
    const data=attemptRecord(number),caption=h.api.captureAttemptLabel(data),html=h.api.captureRetryBox(data);
    assert.match(caption,new RegExp(`Attempt ${number} of 3`));
    if(number<3){assert.match(html,new RegExp(`Try again \\(${3-number} attempt${number===1?'s':''} left\\)`));assert.match(html,/no additional credit/);assert.match(html,/same original photos/);assert.match(html,/id="ihRetryCaptureConsent"/);assert.doesNotMatch(html,/id="ihRetryCaptureConsent"[^>]*checked/);}
    else {assert.match(html,/All 3 attempts have been used/);assert.doesNotMatch(html,/ihRetryCapture|Try again|attempt 4|Record another/);}
  }
});

test('invalid attempt metadata cannot offer a new recording or invent a count',()=>{
  const h=harness(),base=attemptRecord();
  for(const change of [{max_attempts:4},{attempt_number:0},{attempt_number:4},{attempt_number:1.5},{attempt_number:'1'},{remaining_attempts:-1},{remaining_attempts:3},{remaining_attempts:'2'},{allowed:'yes'}]){
    const data={...base,capture_retry:{...base.capture_retry,...change}};
    assert.equal(h.api.captureRetryState(data),null);assert.equal(h.api.captureAttemptLabel(data),'');assert.equal(h.api.captureRetryBox(data),'');
  }
  for(const change of [{allowed:false},{action:'unknown'},{remaining_attempts:0},{next_attempt_number:4},{next_attempt_number:1}])assert.doesNotMatch(h.api.captureRetryBox({...base,capture_retry:{...base.capture_retry,...change}}),/id="ihRetryCapture"/);
  assert.equal(h.api.captureRetryBox({...base,capture_retry:null}),'');
});

test('server-denied, unfinished, technical and withdrawn checks do not offer a fresh capture; partial matches stay independent',()=>{
  const h=harness(),base=attemptRecord();
  for(const change of [{status:'processing'},{status:'waiting'},{status:'confirmed'},{analysis_status:'failed'},{analysis_status:'unavailable'},{publication_status:'withdrawn'},{capture_retry:{...base.capture_retry,allowed:false,action:'none'}}])assert.doesNotMatch(h.api.captureRetryBox({...base,...change}),/id="ihRetryCapture"/);
  const partial=attemptRecord(1,{status:'mismatch',verified_count:1,total_count:2,eligible_photo_indices:[0],publication_status:'ready',publication:{id:'historical-proof'}});
  const html=h.api.captureRetryBox(partial);assert.match(html,/Try again \(2 attempts left\)/);assert.match(html,/individual results stay saved/);assert.equal(partial.publication.id,'historical-proof');
});

test('resuming a saved child works at zero remaining slots and requests no new recording consent',()=>{
  const h=harness(),data=attemptRecord(2);data.capture_retry={...data.capture_retry,remaining_attempts:0,allowed:true,action:'resume',next_attempt_number:3};
  const html=h.api.captureRetryBox(data);assert.match(html,/Continue attempt 3 of 3/);assert.match(html,/without creating another recording slot/);assert.doesNotMatch(html,/ihRetryCaptureConsent|Try again \(0|light turns on|no additional credit/);
});

test('new recording requires a fresh explicit consent and double clicks submit exactly once without a credit preflight',async()=>{
  let finish;
  const h=harness({fetch:async(_url,init)=>init.method==='POST'?new Promise(resolve=>finish=resolve):response(attemptRecord())});await flush();h.api.setRoute(1);h.api.bindCaptureRetry('t'.repeat(43),1);
  await h.nodes.get('#ihRetryCapture').onclick();assert.match(h.nodes.get('#ihQualityRetryError').textContent,/agree to the new recording/);assert.equal(h.requests.filter(r=>r.init.method==='POST').length,0);
  h.nodes.get('#ihRetryCaptureConsent').checked=true;
  const first=h.nodes.get('#ihRetryCapture').onclick(),second=h.nodes.get('#ihRetryCapture').onclick();await flush();
  const posts=h.requests.filter(r=>r.init.method==='POST');assert.equal(posts.length,1);assert.deepEqual(JSON.parse(posts[0].init.body),{consent:true});assert.match(posts[0].url,/\/seller\/t{43}\/retry-capture$/);assert.equal(h.nodes.get('#ihRetryCapture').disabled,true);
  finish(response({id:'attempt-2',token:'u'.repeat(43),capture_retry:attemptRecord(2).capture_retry}));await Promise.all([first,second]);
  assert.equal(h.context.location.hash,'in-hand/capture/'+'u'.repeat(43));assert.equal(h.calls.ensure,0);assert.equal(h.calls.refresh,0);assert.equal(h.calls.camera,0);
});

test('generic retry responses need no lighting reason and resume opens an existing attempt with no new credit action',async()=>{
  const h=harness({fetch:async()=>response({id:'attempt-3',token:'v'.repeat(43),capture_retry:attemptRecord(3).capture_retry})});await flush();h.api.setRoute(1);h.nodes.delete('#ihRetryCaptureConsent');h.api.bindCaptureRetry('u'.repeat(43),1);await h.nodes.get('#ihRetryCapture').onclick();
  assert.equal(h.context.location.hash,'in-hand/capture/'+'v'.repeat(43));assert.equal(h.requests.filter(r=>r.init.method==='POST').length,1);assert.equal(h.calls.ensure,0);assert.equal(h.calls.camera,0);
});

test('a late retry POST cannot navigate another page and a failed or malformed response preserves the result for retry',async()=>{
  let finish;const h=harness({fetch:async()=>new Promise(resolve=>finish=resolve)});await flush();h.api.setRoute(1);h.nodes.get('#ihRetryCaptureConsent').checked=true;h.api.bindCaptureRetry('t'.repeat(43),1);
  const pending=h.nodes.get('#ihRetryCapture').onclick();await flush();h.api.setRoute(2);finish(response({token:'u'.repeat(43)}));await pending;assert.equal(h.context.location.hash,'#other');
  for(const value of [response({detail:'The request could not finish.'},false,503),response({token:'javascript:bad'})]){
    const failed=harness({fetch:async()=>value});await flush();failed.api.setRoute(1);failed.nodes.get('#ihRetryCaptureConsent').checked=true;failed.api.bindCaptureRetry('t'.repeat(43),1);await failed.nodes.get('#ihRetryCapture').onclick();assert.equal(failed.context.location.hash,'#other');assert.equal(failed.nodes.get('#ihRetryCapture').disabled,false);assert.equal(failed.nodes.get('#ihQualityRetryError').hidden,false);assert.equal(failed.calls.ensure,0);
  }
});

test('a concurrent attempt-limit conflict reloads server policy rather than enabling a stale fourth-attempt button',async()=>{
  const h=harness({fetch:async(_url,init)=>init.method==='POST'?response({detail:'The 3-attempt limit has been reached.'},false,409):response(attemptRecord(3))});await flush();h.api.setRoute(1);h.nodes.get('#ihRetryCaptureConsent').checked=true;h.api.bindCaptureRetry('v'.repeat(43),1);await h.nodes.get('#ihRetryCapture').onclick();await flush();
  assert.equal(h.requests.filter(r=>r.init.method==='POST').length,1);assert.match(h.nodes.get('#ihStandalone').innerHTML,/Attempt 3 of 3/);assert.match(h.nodes.get('#ihStandalone').innerHTML,/All 3 attempts have been used/);assert.doesNotMatch(h.nodes.get('#ihStandalone').innerHTML,/id="ihRetryCapture"/);assert.equal(h.calls.ensure,0);
});

test('handheld and flat recording guidance matches photo angles while stationary and digital modes preserve their exceptions',async()=>{
  for(const mode of ['handheld','flat','stationary','digital']){
    const h=harness({fetch:async()=>response(attemptRecord(1,{status:'waiting',capture_mode:mode}))});await flush();h.api.setRoute(1);await h.api.showSeller('t'.repeat(43),1);
    const html=h.nodes.get('#ihStandalone').innerHTML;assert.match(html,/Attempt 1 of 3/);assert.match(html,/Match these views/);assert.match(html,/angle and position shown in each photo/);
    if(mode==='stationary'){assert.match(html,/Do not lift or move a heavy appliance/);assert.doesNotMatch(html,/Hold the item in your hand/);}
    else if(mode==='digital'){assert.match(html,/second screen/);assert.match(html,/Hide usable barcodes/);assert.doesNotMatch(html,/Hold the item in your hand/);}
    else {assert.match(html,/Hold the item in your hand/);assert.match(html,/Slowly turn it so every selected view is visible/);}
    assert.match(h.api.captureRetryBox(attemptRecord(),{mode}),new RegExp(mode==='stationary'?'Do not lift':mode==='digital'?'second screen':'Hold the item in your hand'));
    assert.equal(h.calls.camera,0);
  }
});

test('an old seller link follows only the server provided valid newer capture and buyer retries keep sharing unchecked',async()=>{
  const next='u'.repeat(43),r=attemptRecord(1,{capture_redirect:{id:'attempt-2',token:next,attempt_number:2}});
  const h=harness({fetch:async()=>response(r)});await flush();h.api.setRoute(1);await h.api.showSeller('t'.repeat(43),1);assert.equal(h.context.location.hash,'in-hand/capture/'+next);assert.equal(h.calls.camera,0);
  const buyer=harness({fetch:async()=>response(attemptRecord(2,{status:'waiting',request_kind:'buyer',buyer_request:{state:'submitted',listing_url:listingURL}}))});await flush();buyer.api.setRoute(1);await buyer.api.showSeller(next,1);const html=buyer.nodes.get('#ihStandalone').innerHTML;assert.match(html,/Attempt 2 of 3/);assert.doesNotMatch(html,/id="ihShareEvidence"[^>]*checked/);assert.match(html,/Required for this buyer request/);
});

test('attempt histories link separate authorized records and metadata-only child changes refresh the owner report',()=>{
  const h=harness();h.api.setManagementKey(managementKey);
  const first=attemptRecord(1),second=attemptRecord(2),r={...first,capture_attempts:{root_request_id:first.id,latest_request_id:second.id,attempts:[{...first,attempt_number:1,is_latest:false},{...second,attempt_number:2,is_latest:true}],latest_attempt:second}};
  const html=h.api.captureAttemptHistory(r);assert.match(html,/Attempt 1 · This record/);assert.match(html,/View latest attempt · 2 of 3/);assert.ok(html.includes('#in-hand/report/attempt-2/'+managementKey));assert.match(html,/not combined across attempts/);assert.doesNotMatch(html,/capture\/|seller-capture-token|data-private/);
  assert.notEqual(h.api.reportFingerprint(first),h.api.reportFingerprint(r));assert.equal(h.api.watchCaptureAttempts(r),true);
  const done=attemptRecord(3,{status:'confirmed',verified_count:1,total_count:1});assert.equal(h.api.watchCaptureAttempts({...r,capture_attempts:{...r.capture_attempts,latest_attempt:done}}),false);
});

test('visual match percentage accepts only real integer bounds and never substitutes a categorical or missing score',()=>{
  const h=harness();
  for(const score of [0,87,100])assert.match(h.api.photoMatchPercentage({match_percentage:score}),new RegExp(`Visual match · ${score}%`));
  for(const score of [undefined,null,'87',true,-1,101,87.5,Infinity,NaN,'<script>']){
    const html=h.api.photoMatchPercentage({finding:'supported',match_percentage:score});assert.match(html,/score unavailable/);assert.doesNotMatch(html,/[0-9]+%|<script>/);assert.equal(h.api.photoMatchPercentage({match_percentage:score},{hideMissing:true}),'');
  }
  assert.equal(h.api.photoMatchPercentage({match_percentage:100},{pending:true}),'');assert.equal(h.api.photoMatchScope([{}]),'');assert.match(h.api.photoMatchScope([{match_percentage:87}]),/Visual similarity estimate; verification also checks identifying details/);
});

test('high visual scores keep supported but unverified and contradicted photos unverified without changing eligible photos',()=>{
  const h=harness(),refs=[{id:'one'}];
  for(const [finding,label] of [['supported','Match found; verification not established'],['contradicted','Did not match'],['not_established','Not verified']]){
    const html=h.api.photoResultCards({refs,findings:new Map([[0,{finding,evidence:'Identifying detail unreadable.',match_percentage:99}]]),eligible:new Set()});assert.match(html,/Visual match · 99%/);assert.ok(html.includes(label));assert.match(html,/No verified marking or QR code/);assert.doesNotMatch(html,/Photo 1 · Verified match/);
  }
  const verified=h.api.photoResultCards({refs,findings:new Map([[0,{finding:'supported',match_percentage:100}]]),eligible:new Set([0])});assert.match(verified,/Photo 1 · Verified match/);assert.match(verified,/Visual match · 100%/);
});

test('seller results render server attempt and visual score independently of verification success',async()=>{
  const r=attemptRecord(2,{media:[{id:'reference-photo'}],photos:[{photo_index:0,finding:'supported',evidence:'Number could not be read.',match_percentage:88}]});
  const h=harness({fetch:async()=>response(r)});await flush();h.api.setupCapture(r);await h.api.showSellerResult('u'.repeat(43),1);const html=h.nodes.get('#ihStandalone').innerHTML;
  assert.match(html,/Attempt 2 of 3/);assert.match(html,/Try again \(1 attempt left\)/);assert.match(html,/same original photos/);assert.match(html,/Visual match · 88%/);assert.match(html,/verification also checks identifying details/);assert.match(html,/No verified marking|More evidence is needed/);assert.doesNotMatch(html,/All photos matched|verified photos are ready/);
});

test('explicit read-only detail responses preserve evidence/history while hiding unsupported mutations',async()=>{
  const child=attemptRecord(2,{title:'Child result',management_read_only:true,analysis_status:'failed',analysis:{summary:'Retry comparison later.'}});
  const h=harness();await flush();h.api.setRoute(1);h.api.setManagementKey(managementKey);await h.api.showReport(child.id,1,child);assert.doesNotMatch(h.api.page.innerHTML,/id="ihRetryAnalysis"|id="ihPublishForm"|id="ihWithdraw"/);assert.match(h.api.page.innerHTML,/Selected photos/);assert.equal(h.requests.filter(r=>r.init.method==='POST').length,0);
});

test('an explicit withdraw permission remains available in a read-only view without enabling other mutations',()=>{
  const h=harness();h.api.setManagementKey(managementKey);
  const child=attemptRecord(2,{management_read_only:true,can_withdraw:true,media:[{id:'reference-photo',role:'listing'}],eligible_photo_indices:[0],verified_count:1,publication_status:'ready',publication:{id:'child-proof',photos:[{id:'marked-photo',photo_index:0}]}});
  const publication=h.api.publicationBox(child);assert.match(publication,/id="ihWithdraw"/);assert.doesNotMatch(publication,/ihPublishForm|ihRetryAnalysis/);assert.match(h.api.managementBox(child),/withdraw its public record/);assert.doesNotMatch(h.api.managementBox(child),/Anyone with it can manage this photo set/);
  assert.doesNotMatch(h.api.publicationBox({...child,can_withdraw:false}),/id="ihWithdraw"/);
});

test('server-approved root lineage retains normal child reprocessing, publication and withdrawal controls with the original key',async()=>{
  const h=harness();await flush();h.api.setRoute(1);h.api.setManagementKey(managementKey);
  const child=attemptRecord(2,{title:'Retry result',management_read_only:false,can_withdraw:true,analysis_status:'failed',analysis:{summary:'Comparison interrupted.'}});
  await h.api.showReport(child.id,1,child);assert.match(h.api.page.innerHTML,/id="ihRetryAnalysis"/);assert.ok(h.api.managementBox(child).includes('#in-hand/report/attempt-2/'+managementKey));assert.doesNotMatch(h.api.managementBox(child),/read-only/);
  const eligible={...child,analysis_status:'complete',total_count:1,verified_count:1,eligible_photo_indices:[0],media:[{id:'reference-photo',role:'listing'}],publication:null};assert.match(h.api.publicationBox(eligible),/id="ihPublishForm"/);
  assert.match(h.api.publicationBox({...eligible,publication:{id:'derived-proof',photos:[{id:'marked-photo',photo_index:0}]}}),/id="ihWithdraw"/);assert.equal(h.requests.filter(r=>r.init.method==='POST').length,0);
});

const selectorRecord=(number=1,verified=[],extra={})=>{
  const data=attemptRecord(number,{root_photo_indices:[0,1,2,3],root_photos:[0,1,2,3].map(index=>({photo_index:index,media_id:'root-photo-'+index,url:'/root-photos/'+index})),...extra});
  data.capture_retry={...data.capture_retry,limit_scope:'item',recording_sequence_number:number,retryable_photo_indices:[0,1,2,3].filter(index=>!verified.includes(index)),photo_attempts:[0,1,2,3].map(index=>({photo_index:index,attempts_used:1,max_attempts:3,remaining_attempts:3-number,allowed:!verified.includes(index)&&number<3,verified:verified.includes(index),publication_id:verified.includes(index)?'source-proof-'+index:null,source_request_id:verified.includes(index)?'earlier-record':null}))};return data;
};
function selectorNodes(h,indices=[0,1,2,3]){
  for(const index of indices){h.nodes.set('retry-photo-'+index,{dataset:{retryPhotoIndex:String(index)},checked:true});h.nodes.set('retry-one-'+index,{dataset:{retryThisPhoto:String(index)}});}
  h.nodes.set('retry-all',{dataset:{retryAllFailed:''}});
}

test('all truly unverified root images get retry controls, including categorically supported photos; verified proof keeps its source',()=>{
  const h=harness(),r=selectorRecord(1,[1]);r.photos=[0,1,2,3].map(index=>({photo_index:index,finding:[0,3].includes(index)?'supported':'not_established',evidence:'Needs identifying detail.',match_percentage:84}));
  const html=h.api.rootPhotoRetryPanel(r,{token:r.token});assert.equal((html.match(/data-retry-this-photo=/g)||[]).length,3);assert.match(html,/data-retry-this-photo="0"/);assert.match(html,/data-retry-this-photo="3"/);assert.doesNotMatch(html,/data-retry-this-photo="1"/);assert.match(html,/Retry all failed photos/);assert.match(html,/#in-hand\/verify\/source-proof-1/);assert.match(html,/Verified in its source record/);assert.match(html,/matches are not combined into one video/);assert.ok(html.includes('/seller/'+r.token+'/root-photos/3'));assert.match(h.api.captureAttemptLabel(r),/2 retries left for this item · Shared across all photos/);
  assert.equal(h.api.rootPhotoRetryPanel({...r,root_photos:[{photo_index:0,url:'https://outside.example/image.jpg'}]},{token:r.token}),'');
});

test('Retry this photo maps to immutable Photo4 and bulk selects only failed root indices',async()=>{
  let finish;const r=selectorRecord(1,[1]);const h=harness({fetch:async(_url,init)=>init.method==='POST'?new Promise(resolve=>finish=resolve):response(r)});await flush();selectorNodes(h);h.api.setRoute(1);h.api.bindCaptureRetry(r.token,1,r);
  h.nodes.get('retry-one-3').onclick();assert.deepEqual([...h.api.retrySelection(r)],[3]);assert.match(h.nodes.get('#ihRetrySelectionLabel').textContent,/Selected photos: 4/);
  h.nodes.get('retry-all').onclick();assert.deepEqual([...h.api.retrySelection(r)],[0,2,3]);assert.equal(h.nodes.get('retry-photo-1').checked,false);
  h.nodes.get('retry-one-3').onclick();h.nodes.get('#ihRetryCaptureConsent').checked=true;const first=h.nodes.get('#ihRetryCapture').onclick(),second=h.nodes.get('#ihRetryCapture').onclick();await flush();const posts=h.requests.filter(request=>request.init.method==='POST');assert.equal(posts.length,1);const payload=JSON.parse(posts[0].init.body);assert.deepEqual(payload.photo_indices,[3]);assert.match(payload.request_key,/^[A-Za-z0-9_-]{43}$/);assert.equal(payload.consent,true);assert.equal(h.calls.ensure,0);
  finish(response({id:'photo-four-attempt',token:'u'.repeat(43),root_photo_indices:[3]}));await Promise.all([first,second]);assert.equal(h.context.location.hash,'in-hand/capture/'+'u'.repeat(43));
});

test('ambiguous selected-photo requests reuse the same intent key and original index bytes until acknowledged',async()=>{
  const r=selectorRecord();let count=0;const h=harness({fetch:async()=>{if(++count===1)throw Error('Connection lost');return response({id:'child',token:'u'.repeat(43)});}});await flush();h.api.setRoute(1);h.api.setRetrySelection(r,[3]);h.nodes.get('#ihRetryCaptureConsent').checked=true;h.api.bindCaptureRetry(r.token,1,r);await h.nodes.get('#ihRetryCapture').onclick();await h.nodes.get('#ihRetryCapture').onclick();const posts=h.requests.filter(request=>request.init.method==='POST');assert.equal(posts.length,2);assert.equal(posts[0].init.body,posts[1].init.body);assert.deepEqual(JSON.parse(posts[1].init.body).photo_indices,[3]);assert.equal(h.calls.ensure,0);
});

test('lost-response then legacy resume does not replay attempt2 when the same photo legitimately needs attempt3',async()=>{
  let count=0;const root=selectorRecord(),h=harness({fetch:async()=>{count++;if(count===1)throw Error('Lost creation response');return response({id:count===2?'child-2':'child-3',token:(count===2?'u':'v').repeat(43)});}});await flush();h.api.setRoute(1);const consent=h.nodes.get('#ihRetryCaptureConsent');consent.checked=true;h.api.setRetrySelection(root,[3]);h.api.bindCaptureRetry(root.token,1,root);await h.nodes.get('#ihRetryCapture').onclick();
  const resume={...root,capture_retry:{...root.capture_retry,action:'resume',remaining_attempts:1,next_attempt_number:2}};h.nodes.delete('#ihRetryCaptureConsent');h.api.bindCaptureRetry(root.token,1,resume);await h.nodes.get('#ihRetryCapture').onclick();
  const next={...root,capture_retry:{...root.capture_retry,remaining_attempts:1,next_attempt_number:3}};h.nodes.set('#ihRetryCaptureConsent',consent);h.api.setRetrySelection(next,[3]);h.api.bindCaptureRetry(root.token,1,next);await h.nodes.get('#ihRetryCapture').onclick();
  const posts=h.requests.filter(request=>request.init.method==='POST').map(request=>JSON.parse(request.init.body));assert.equal(posts.length,3);assert.deepEqual(posts[0].photo_indices,[3]);assert.deepEqual(posts[1],{consent:true});assert.deepEqual(posts[2].photo_indices,[3]);assert.notEqual(posts[0].request_key,posts[2].request_key);assert.equal(h.context.location.hash,'in-hand/capture/'+'v'.repeat(43));assert.equal(h.calls.ensure,0);
});

test('active different-subset conflicts identify the existing selection and never silently record the requested new subset',async()=>{
  const r=selectorRecord(),activeToken='a'.repeat(43);const h=harness({fetch:async()=>response({detail:{code:'active_capture',message:'A recording is active.',active_attempt:{id:'active-photo-one',token:activeToken,root_photo_indices:[0],recording_sequence_number:2}}},false,409)});await flush();h.api.setRoute(1);h.api.setRetrySelection(r,[3]);h.nodes.get('#ihRetryCaptureConsent').checked=true;h.api.bindCaptureRetry(r.token,1,r);await h.nodes.get('#ihRetryCapture').onclick();const html=h.nodes.get('#ihQualityRetryError').innerHTML;assert.match(html,/photo 1/);assert.match(html,/Continue existing recording/);assert.ok(html.includes('#in-hand/capture/'+activeToken));assert.equal(h.context.location.hash,'#other');assert.equal(h.requests.filter(request=>request.init.method==='POST').length,1);assert.equal(h.calls.camera,0);assert.equal(h.calls.ensure,0);
});

test('stale already-verified selections refresh server policy and cannot submit verified indices again',async()=>{
  const before=selectorRecord(),after=selectorRecord(2,[3]);const h=harness({fetch:async(_url,init)=>init.method==='POST'?response({detail:{code:'already_verified',message:'Photo 4 is already verified.'}},false,409):response(after)});await flush();h.api.setRoute(1);h.api.setRetrySelection(before,[3]);h.nodes.get('#ihRetryCaptureConsent').checked=true;h.api.bindCaptureRetry(before.token,1,before);await h.nodes.get('#ihRetryCapture').onclick();await flush();assert.equal(h.requests.filter(request=>request.init.method==='POST').length,1);assert.doesNotMatch(h.nodes.get('#ihStandalone').innerHTML,/data-retry-this-photo="3"/);assert.match(h.nodes.get('#ihStandalone').innerHTML,/source-proof-3/);assert.equal(h.calls.ensure,0);
});

test('Photo4-only captures and public proof keep original numbering with local evidence index zero',async()=>{
  const r=attemptRecord(2,{status:'waiting',root_photo_indices:[3],media:[{id:'selected-photo-four'}]});const h=harness({fetch:async()=>response(r)});await flush();h.api.setRoute(1);await h.api.showSeller('u'.repeat(43),1);assert.match(h.nodes.get('#ihStandalone').innerHTML,/<figcaption>Photo 4<\/figcaption>/);assert.doesNotMatch(h.nodes.get('#ihStandalone').innerHTML,/<figcaption>Photo 1<\/figcaption>/);
  const cards=h.api.photoResultCards({refs:[{id:'selected-photo-four'}],findings:new Map([[0,{photo_index:0,root_photo_index:3,finding:'supported',match_percentage:91}]]),eligible:new Set(),record:r});assert.match(cards,/Photo 4 ·/);assert.match(cards,/data-result-photo-index="0" data-root-photo-index="3"/);
  const p=harness({fetch:async()=>response({id:'proof-four',status:'verified',title:'Photo4 proof',total_count:1,photo_count:1,photos:[{id:'marked',photo_index:0,root_photo_index:3,match_percentage:91}]})});await flush();p.api.setRoute(1);await p.api.showPublic('proof-four',1);assert.match(p.nodes.get('#ihStandalone').innerHTML,/Photo 4 · Verified match/);assert.doesNotMatch(p.nodes.get('#ihStandalone').innerHTML,/Photo 1 · Verified match/);
});

test('root overview retains all photo controls instead of redirecting to a narrow child, while fresh child links reveal no root capability',async()=>{
  const childToken='u'.repeat(43),r=selectorRecord(1,[3]);r.capture_redirect={id:'child-four',token:childToken,attempt_number:2};r.latest_capture=r.capture_redirect;
  const root=harness({fetch:async()=>response(r)});await flush();root.api.setRoute(1);await root.api.showSeller(r.token,1);await flush();assert.equal(root.context.location.hash,'#other');assert.equal((root.nodes.get('#ihStandalone').innerHTML.match(/Original listing photo/g)||[]).length,4);assert.match(root.nodes.get('#ihStandalone').innerHTML,/View latest recording/);assert.match(root.nodes.get('#ihStandalone').innerHTML,/data-retry-this-photo="0"/);assert.doesNotMatch(root.nodes.get('#ihStandalone').innerHTML,/data-retry-this-photo="3"/);
  const fresh=harness();assert.equal(fresh.api.captureNavigation(attemptRecord(2),childToken),'');
});

test('processing activity prints actual queue/comparison states without invented logs or numeric progress',()=>{
  const h=harness();
  for(const status of ['queued','decoding','processing','running','pending']){
    const html=h.api.processingActivity({status:'processing',analysis_status:status,queue:{state:'running',queued_at:1700000000},publication_status:'not_eligible'});assert.ok(html.includes('comparison.state = '+status));assert.match(html,/queue.state = running/);assert.match(html,/ih-working-dots/);assert.doesNotMatch(html,/\d+%|token|frame [0-9]+|estimated|executing|scanning/i);
  }
  assert.equal(h.api.processingActivity({status:'inconclusive',analysis_status:'complete',publication_status:'not_eligible'}),'');assert.equal(h.api.processingActivity({status:'waiting',analysis_status:'pending'}),'');
  assert.doesNotMatch(h.api.processingActivity({status:'processing',analysis_status:'<script>bad'}),/<script>/);
  const css=fs.readFileSync(path.join(__dirname,'..','in-hand.css'),'utf8');assert.match(css,/@media\(prefers-reduced-motion:reduce\).*ih-working-dots[^}]+animation:none/s);
});

test('queued root images suppress stale numeric scores and old evidence while preserving already verified source proof',()=>{
  const h=harness(),r=selectorRecord(1,[1]);r.status='processing';r.analysis_status='queued';r.queue={state:'queued',queued_at:1700000000};r.photos=[0,1,2,3].map(index=>({photo_index:index,finding:'supported',match_percentage:95,evidence:'STALE_OLD_EVIDENCE'}));
  const html=h.api.rootPhotoRetryPanel(r,{token:r.token});assert.doesNotMatch(html,/95%|STALE_OLD_EVIDENCE|Retry this photo|Retry all failed photos/);assert.match(html,/Waiting for comparison/);assert.match(html,/current comparison has not finished/);assert.match(html,/source-proof-1/);assert.match(html,/Verified in its source record/);
});
