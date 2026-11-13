/* Credits are granted and spent by the server, never by this interface. */
(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const base = API_BASE + '/credits';
  let config, authClient, authBoot, balance = null, selected = 'regular', polling, busy = false, googleBoot, appleBoot, paypalBoot, appleSession;
  let lastFocus, waitingCheckout, refreshNumber = 0, googlePurchase, paymentWarm;
  let balanceLoading = false, balanceFailed = false, activeOwner = null, walletGeneration = 0, walletFlight = null, balanceWarm = null;
  const pendingKey = 'lockx.pendingCheckout';
  const attemptKey = 'lockx.checkoutAttempt';
  const scriptLoads = new Map();
  function stored(key) { try { return JSON.parse(sessionStorage.getItem(key) || 'null'); } catch { return null; } }
  function save(key, value) { try { if (value) sessionStorage.setItem(key, JSON.stringify(value)); else sessionStorage.removeItem(key); } catch {} }
  function checkoutAttempt(provider, packId) {
    let attempt = stored(attemptKey);
    if (!attempt || attempt.provider !== provider || attempt.packId !== packId) {
      attempt = {provider, packId, key:crypto.randomUUID()}; save(attemptKey, attempt);
    }
    return attempt;
  }
  const query = new URLSearchParams(location.search);
  const isReturn = query.get('wallet') === 'return';
  const ready = fetch(base + '/catalog', {cache:'no-store'}).then(async r => {
    if (!r.ok) throw Error('Credit purchases are temporarily unavailable.');
    config = await r.json(); decorate();
    if (isReturn) open();
    return config;
  }).catch(error => { config = {error:error.message, credits_required:null}; return config; });

  function active() { return config?.credits_required || window.LOCKX_CREDITS_PREVIEW; }
  async function initializeAuth() {
    if (!authBoot) authBoot = window.ensureLockXAuthClient().then(value => {
      authClient = value;
      // Invalidate old-account responses synchronously; never await SDK calls in this callback.
      value.auth.onAuthStateChange?.((_event,current)=>adoptSession(current));
      return value;
    }).catch(error => {authBoot=null;throw error;});
    return authBoot;
  }
  async function authorization(forWallet = false) {
    await ready;
    if (!active() && !forWallet) return '';
    const current=await walletSession();
    return current?.access_token ? 'Bearer ' + current.access_token : '';
  }
  async function request(path, options = {}) {
    const token = await authorization(true);
    if (!token) throw Error('Sign in with your email to use your credits.');
    const response = await fetch(base + path, {...options, cache:'no-store', headers:{
      Authorization:token, ...(options.body ? {'Content-Type':'application/json'} : {}), ...options.headers,
    }});
    const data = await response.json().catch(()=>({}));
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Please try again.');
    return data;
  }
  async function post(path, body) {
    if(path==='/checkouts'){
      const pending=window.LockXMarketing?.getVisit?.();
      const visit=pending?await Promise.race([pending,new Promise(resolve=>setTimeout(()=>resolve(null),250))]):null;
      if(visit)body={...body,marketing_visit_id:visit};
    }
    return request(path, {method:'POST',body:JSON.stringify(body)});
  }
  function pack() { return config?.packs?.find(p=>p.id===selected); }
  const price = cents => '$' + (cents/100).toFixed(cents%100 ? 2 : 0);
  function pricingCards() {
    return (config?.packs || []).map(p=>`<article class="cw-pack${p.id==='regular'?' cw-pack-featured':''}">
      <p class="cw-pack-name">${esc(p.name)}</p><h3>${p.credits}<span>credits</span></h3>
      <p class="cw-pack-price">${price(p.amount_cents)}<small>50¢ per verification</small></p>
      <button type="button" class="cw-button${p.id==='regular'?'':' cw-secondary'}" data-credit-pack="${p.id}">Buy ${p.credits} credits <span aria-hidden="true">↗</span></button>
    </article>`).join('');
  }
  function decorate() {
    if (!active()) return;
    const heroNote=$('.lx-hero-note');if(heroNote)heroNote.textContent='No app. No password. Just your photos and camera.';
    const accountFAQ=[...document.querySelectorAll('.lx-faq details')].find(el=>el.querySelector('summary')?.textContent.includes('app or an account'));
    if(accountFAQ){accountFAQ.querySelector('summary').innerHTML='Do I need an app or a password?<span aria-hidden="true">+</span>';accountFAQ.querySelector('p').textContent='No app or password is needed. Sign in with an email link to buy credits and recover your balance on another device. One credit covers one item verification.';}
    const pill=$('.ih-pills span');if(pill)pill.textContent='No app. No password.';
    const nav = $('#lockxPublicHeader nav');
    if (nav && !$('#cwHeaderButton')) {
      const button=document.createElement('button'); button.id='cwHeaderButton';button.className='cw-wallet-button';button.type='button';button.dataset.creditWallet='';
      button.textContent='Your credits';nav.insertBefore(button,nav.lastElementChild);
    }
    const faq=$('#lxQuestions');
    if (faq && !$('#lockxPricing')) {
      const section=document.createElement('section');section.id='lockxPricing';section.className='cw-pricing lx-wrap';section.setAttribute('aria-labelledby','cwPricingTitle');
      section.innerHTML=`<div class="cw-pricing-heading"><p class="lx-eyebrow">A little credit. A little confidence.</p><h2 id="cwPricingTitle">Ready when you are.</h2><p>One credit. One item verification.<br>Buy once, use your credits whenever you need them.</p></div><div class="cw-packs">${pricingCards()}</div><p class="cw-pricing-note">No subscription. Credits never expire. One item check includes up to six photos and a 10-second video.</p><p class="cw-payment-note">PayPal · Apple Pay · Credit &amp; debit cards${config.google_pay_ready?' · Google Pay':''}</p>`;
      faq.before(section);
      const links=$('#lockxPublicHeader .lx-header-links');
      if (links&&!links.querySelector('[data-home-scroll="lockxPricing"]')) {
        const button=document.createElement('button');button.type='button';button.dataset.homeScroll='lockxPricing';button.textContent='Pricing';links.prepend(button);
      }
    }
    const form=$('#ihRequestForm');
    if (form&&!$('#ihCreditStatus')) {
      const bar=document.createElement('div');bar.id='ihCreditStatus';bar.className='cw-inline-wallet';
      bar.innerHTML='<div><strong data-credit-balance>Your credits</strong><span class="cw-wallet-suffix" hidden> in wallet</span><small>1 credit per item verification</small></div><button type="button" class="cw-text-button" data-credit-wallet>Buy credits / sign in</button>';
      form.prepend(bar);
    }
    updateBalanceLabels();
  }
  function updateBalanceLabels() {
    const label=balance===null?'Your credits':`${balance} credit${balance===1?'':'s'}`;
    document.querySelectorAll('[data-credit-balance]').forEach(el=>{
      el.textContent=balance===null&&balanceLoading?'Credits loading…':balance===null&&balanceFailed?'Credits unavailable':label;
      el.classList.toggle('cw-balance-loading',balance===null&&balanceLoading);
      el.setAttribute('aria-busy',String(balance===null&&balanceLoading));
    });
    const header=$('#cwHeaderButton');if(header)header.textContent=label;
    document.querySelectorAll('.cw-wallet-suffix').forEach(el=>el.hidden=balance===null);
    const note=$('#ihRequestForm .ih-form-footer small');
    if(note)note.textContent='1 credit covers this item check. A completed check uses a credit even if no match is found.';
  }
  function adoptSession(current) {
    const owner=current?.user?.id||null;
    if(owner!==activeOwner){
      activeOwner=owner;walletGeneration++;refreshNumber++;walletFlight=null;
      balance=null;balanceLoading=false;balanceFailed=false;updateBalanceLabels();
    }
  }
  async function walletSession() {
    const client=await initializeAuth();
    for(let attempt=0;attempt<2;attempt++){
      const generation=walletGeneration;
      const {data,error}=await client.auth.getSession();if(error)throw error;
      if(generation!==walletGeneration&&(data.session?.user?.id||null)!==activeOwner)continue;
      adoptSession(data.session);return data.session;
    }
    throw Error('Your sign-in changed. Please try again.');
  }
  function warmBalance() {
    if(!balanceWarm)balanceWarm=(async()=>{
      if(balance===null){balanceLoading=true;balanceFailed=false;updateBalanceLabels();}
      // Start the SDK/session restore while the independent catalog is in flight.
      await Promise.all([ready,initializeAuth()]);
      if(config.error)throw Error(config.error);
      if(!active()){balanceLoading=false;updateBalanceLabels();return;}
      const current=await walletSession();
      if(current?.access_token)await refreshWallet();
      else{balanceLoading=false;updateBalanceLabels();}
    })().catch(()=>{
      if(balance===null&&!walletFlight){balanceLoading=false;balanceFailed=true;updateBalanceLabels();}
    }).finally(()=>{balanceWarm=null;});
    return balanceWarm;
  }
  function dialog() {
    let el=$('#creditWalletDialog');
    if (!el) {
      el=document.createElement('dialog');el.id='creditWalletDialog';el.className='cw-dialog';el.setAttribute('aria-labelledby','cwWalletTitle');
      el.innerHTML='<button type="button" class="cw-close" aria-label="Close credit wallet">×</button><div id="cwDialogContent"></div>';
      document.body.append(el);
      $('.cw-close',el).onclick=()=>el.close();
      el.addEventListener('close',()=>{clearInterval(polling);lastFocus?.focus();});
      el.addEventListener('click',event=>{if(event.target===el){const r=el.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)el.close();}});
    }
    return el;
  }
  function message(copy, error=false) {
    const el=$('#cwMessage');if(el){el.hidden=false;el.className='cw-message'+(error?' cw-error':'');el.textContent=copy;}
  }
  async function renderWallet() {
    const el=$('#cwDialogContent'); if(!el)return;
    const client=await initializeAuth();
    const data={session:await walletSession()};
    const signed=!!data.session;
    el.innerHTML=`<p class="lx-eyebrow">Your LockX credits</p><h2 id="cwWalletTitle">${signed?'A little proof, on hand.':'Your email. Your credits.'}</h2>
      ${signed?`<div class="cw-balance"><strong>${balance===null?'…':balance}</strong><span>available credits</span></div><div class="cw-account"><span>${esc(data.session.user.email)}</span><button type="button" class="cw-text-button" id="cwSignOut">Sign out</button></div><button type="button" class="cw-text-button" id="cwOpenAdmin" hidden>Admin dashboard →</button>`:
      `<p class="cw-intro">Get a sign-in link to buy credits and use them on any device. No password needed.</p><form id="cwEmailForm"><label for="cwEmail">Email address</label><div class="cw-email-row"><input id="cwEmail" name="email" type="email" inputmode="email" autocomplete="email" placeholder="you@example.com" required maxlength="254"><button class="cw-button" type="submit">Send sign-in link</button></div></form>`}
      <div id="cwMessage" class="cw-message" role="status" hidden></div>
      <div class="cw-pack-picker" role="group" aria-label="Choose your credit pack">${config.packs.map(p=>`<button type="button" data-pick-pack="${p.id}" aria-pressed="${p.id===selected}"><strong>${p.credits} credits</strong><span>${price(p.amount_cents)}</span></button>`).join('')}</div>
      <p class="cw-selected-summary" id="cwSelectedSummary"></p>
      <div id="cwApplePay" class="cw-apple-pay" hidden></div>
      <button type="button" class="cw-button cw-paypal" id="cwPayPal" ${signed&&config.payment_ready?'':'disabled'}>PayPal or card <span aria-hidden="true">↗</span></button>
      <p class="cw-methods">PayPal, Apple Pay, and credit or debit card</p><div id="cwGooglePay"></div>
      ${!config.payment_ready?'<p class="cw-availability">Credit purchases are not available yet. No payment will be taken.</p>':''}
      <p class="cw-terms">One-time purchase. Credits never expire. One credit covers one item check, whether the result matches, mismatches, or needs more evidence. Technical failures restore your credit.</p>
      ${signed?'<details class="cw-history"><summary>Credit history</summary><div id="cwHistory">Loading…</div></details>':''}`;
    updatePackSummary();
    $('#cwEmailForm')?.addEventListener('submit',async event=>{
      event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;
      try{
        const {error}=await client.auth.signInWithOtp({email:$('#cwEmail').value.trim(),options:{emailRedirectTo:location.origin+'/?wallet=return'}});
        if(error)throw error;
        message('Check your email and open the sign-in link. Your credits stay with this email.');
      }catch(error){message(error.message||'The sign-in email could not be sent.',true);}
      finally{button.disabled=false;}
    });
    $('#cwSignOut')?.addEventListener('click',async()=>{
      const {error}=await client.auth.signOut();if(error){message(error.message,true);return;}
      adoptSession(null);waitingCheckout=null;save(pendingKey,null);save(attemptKey,null);clearInterval(polling);await renderWallet();updateBalanceLabels();
    });
    $('#cwPayPal').onclick=buyPayPal;
    if(signed&&window.LockXAdmin){
      const owner=data.session.user.id;
      window.LockXAdmin.checkAccess().then(allowed=>{
        const link=$('#cwOpenAdmin');
        if(link&&activeOwner===owner){link.hidden=!allowed;link.onclick=()=>{dialog().close();window.LockXAdmin.open();};}
      }).catch(()=>{});
    }
    if(signed&&config.apple_pay_ready)setupApplePay();
    if(signed&&config.google_pay_ready)setupGooglePay().catch(()=>{const el=$('#cwGooglePay');if(el)el.textContent='Google Pay is unavailable on this device. You can use the payment options above.';});
    if(signed)refreshWallet().catch(()=>{
      const history=$('#cwHistory');if(history)history.textContent='Your balance could not refresh. Close and reopen your wallet to try again.';
      message('Your balance could not refresh. You can still choose a payment option below.',true);
    });
  }
  function updatePackSummary() {
    const p=pack();const el=$('#cwSelectedSummary');
    if(el&&p)el.textContent=`${p.credits} verification credits · ${price(p.amount_cents)} USD`;
    document.querySelectorAll('[data-pick-pack]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.pickPack===selected)));
  }
  async function refreshWallet({force=false}={}) {
    await ready;
    const current=await walletSession();
    if(!current?.access_token){balanceLoading=false;updateBalanceLabels();return;}
    if(!activeOwner)throw Error('Sign in again to refresh your credits.');
    const owner=activeOwner,generation=walletGeneration;
    if(!force&&walletFlight?.owner===owner&&walletFlight.generation===generation)return walletFlight.promise;
    const number=++refreshNumber;
    if(balance===null)balanceLoading=true;
    balanceFailed=false;updateBalanceLabels();
    const flight={owner,generation,promise:null};
    const isCurrent=()=>owner===activeOwner&&generation===walletGeneration&&number===refreshNumber;
    flight.promise=(async()=>{try{
      const response=await fetch(base+'/wallet',{cache:'no-store',headers:{Authorization:'Bearer '+current.access_token}});
      const wallet=await response.json().catch(()=>({}));
      if(!response.ok)throw Error(typeof wallet.detail==='string'?wallet.detail:'Your credits could not refresh. Please try again.');
      if(!isCurrent())return;
      if(!Number.isSafeInteger(wallet.balance)||wallet.balance<0)throw Error('Your credits could not refresh. Please try again.');
      balanceLoading=false;balanceFailed=false;
      balance=wallet.balance;updateBalanceLabels();
      const count=$('.cw-balance strong');if(count)count.textContent=balance;
      const labels={purchase:'Credits purchased',verification:'Item verification',technical_refund:'Credit restored — technical issue',payment_refund:'Payment refunded',admin_grant:'Free credits from LockX'};
      const history=$('#cwHistory');
      if(history)history.innerHTML=wallet.history.length?wallet.history.map(row=>`<div><span>${esc(labels[row.kind]||'Credit adjustment')}<small>${new Date(row.created*1000).toLocaleDateString()}</small></span><strong>${row.delta>0?'+':''}${row.delta}</strong></div>`).join(''):'Your credit purchases and verifications will appear here.';
      if(wallet.credit_debt)message('A refunded payment included credits already used. Your next purchase first covers that balance.',true);
      return wallet;
    }catch(error){
      if(isCurrent()){
        balanceLoading=false;balanceFailed=true;updateBalanceLabels();
        if($('#creditWalletDialog')?.open)message(error.message,true);
      }
      throw error;
    }finally{if(walletFlight===flight)walletFlight=null;}})();
    walletFlight=flight;return flight.promise;
  }
  async function open(packId) {
    window.LockXMarketing?.track?.('wallet_open');
    warmPaymentOptions();
    await ready;if(config.error){toast('Credits unavailable',config.error);return;}
    if(packId&&config.packs.some(p=>p.id===packId))selected=packId;
    const el=dialog();lastFocus=document.activeElement;
    if(!el.open)el.showModal();
    $('#cwDialogContent').innerHTML='<p class="cw-intro" role="status">Opening your credit wallet…</p>';
    try{
      await renderWallet();
      const checkout=query.get('checkout') || stored(pendingKey);
      if(checkout&&await authorization(true))watchCheckout(checkout);
    }catch(error){$('#cwDialogContent').innerHTML=`<h2 id="cwWalletTitle">Your credit wallet</h2><p class="cw-message cw-error">${esc(error.message)}</p><button type="button" class="cw-button" id="cwTryAgain">Try again</button>`;$('#cwTryAgain').onclick=()=>open();}
  }
  async function buyPayPal() {
    if(busy)return;busy=true;const button=$('#cwPayPal');button.disabled=true;
    // Open synchronously from the tap so mobile popup blockers do not discard the checkout.
    const popup=window.open('about:blank','_blank');if(popup)popup.opener=null;
    try{
      const attempt=checkoutAttempt('paypal_link', selected);
      const checkout=await post('/checkouts',{pack_id:attempt.packId,provider:'paypal_link',request_key:attempt.key});
      waitingCheckout=checkout.id;save(pendingKey,checkout.id);
      if(popup){popup.location.replace(checkout.payment_url);message('Complete your payment in the PayPal tab. Your credits will appear here after confirmation.');watchCheckout(checkout.id);}
      else location.assign(checkout.payment_url);
    }catch(error){popup?.close();message(error.message,true);}
    finally{busy=false;if(button?.isConnected)button.disabled=false;}
  }
  function watchCheckout(checkoutId) {
    clearInterval(polling);let attempts=0;
    const check=async()=>{
      if(++attempts>120){clearInterval(polling);message('Payment confirmation is taking longer than usual. Your credits will appear once PayPal confirms it.');return;}
      try{
        const checkout=await request('/checkouts/'+encodeURIComponent(checkoutId));
        if(checkout.status==='paid'){
          clearInterval(polling);waitingCheckout=null;save(pendingKey,null);save(attemptKey,null);await refreshWallet({force:true});message(`${checkout.credits} credits added. You’re ready to verify.`);
          const el=$('#cwMessage');if(el&&!$('#cwStartVerification'))el.insertAdjacentHTML('afterend','<a class="cw-button cw-verify-link" id="cwStartVerification" href="#in-hand">Start a verification →</a>');
          $('#cwStartVerification')?.addEventListener('click',()=>dialog().close());
          if(isReturn){const clean=new URL(location.href);['wallet','checkout','tx','st','amt','cc'].forEach(k=>clean.searchParams.delete(k));history.replaceState(null,'',clean.pathname+clean.search+clean.hash);}
        }
      }catch(error){clearInterval(polling);message(error.message,true);}
    };
    check();polling=setInterval(check,2500);
  }
  function loadScript(src) {
    if(scriptLoads.has(src))return scriptLoads.get(src);
    const pending=new Promise((resolve,reject)=>{
      const script=document.createElement('script');script.src=src;
      let settled=false;
      const finish=error=>{
        if(settled)return;settled=true;clearTimeout(timer);script.onload=null;script.onerror=null;
        if(error){script.remove();scriptLoads.delete(src);reject(error);}else resolve();
      };
      const timer=setTimeout(()=>finish(Error('Payment options took too long to load.')),15000);
      script.onload=()=>finish();script.onerror=()=>finish(Error('Payment options could not load.'));
      document.head.append(script);
    });
    scriptLoads.set(src,pending);return pending;
  }
  function loadPayPalWalletSDK() {
    const components=[config.apple_pay_ready?'applepay':null,config.google_pay_ready?'googlepay':null].filter(Boolean);
    if(components.every(name=>window.paypal?.[name==='applepay'?'Applepay':'Googlepay']))return Promise.resolve();
    if(!paypalBoot){
      const url=new URL('https://www.paypal.com/sdk/js');
      url.search=new URLSearchParams({'client-id':config.paypal_client_id,components:components.join(','),currency:'USD'});
      paypalBoot=loadScript(url.href).catch(error=>{paypalBoot=null;throw error;});
    }
    return paypalBoot;
  }
  function prepareApplePay() {
    if(!appleBoot)appleBoot=(async()=>{
      const appleScript=loadScript('https://applepay.cdn-apple.com/jsapi/1.latest/apple-pay-sdk.js');
      // Safari already has the payment API. Other browsers need Apple's SDK first.
      const paymentAPI=window.ApplePaySession?Promise.resolve():appleScript;
      const provider=Promise.all([loadPayPalWalletSDK(),paymentAPI]).then(async()=>{
        const applepay=window.paypal.Applepay();let deadline;
        const settings=await Promise.race([
          applepay.config(),
          new Promise((resolve,reject)=>{deadline=setTimeout(()=>reject(Error('Apple Pay took too long to respond.')),15000);}),
        ]).finally(()=>clearTimeout(deadline));
        return {applepay,settings};
      });
      const [available]=await Promise.all([provider,appleScript]);
      if(!window.ApplePaySession||!ApplePaySession.canMakePayments())return null;
      return available.settings.isEligible?available:null;
    })().then(available=>{if(!available)appleBoot=null;return available;}).catch(error=>{appleBoot=null;throw error;});
    return appleBoot;
  }
  function warmPaymentOptions() {
    // Only a wallet interaction starts this work. It creates no checkout or payment session.
    if(!paymentWarm){
      initializeAuth().catch(()=>null);
      paymentWarm=ready.then(()=>config.apple_pay_ready?prepareApplePay():null).catch(()=>null);
    }
    return paymentWarm;
  }
  async function setupApplePay() {
    const container=$('#cwApplePay');if(!container)return;
    applePayState(container,'Loading Apple Pay…');
    let available;
    try{available=await prepareApplePay();}
    catch{applePayState(container,'Apple Pay could not load. Please try again, or use PayPal or card.',true);return;}
    if(!available){appleBoot=null;applePayState(container,'Apple Pay is unavailable right now. You can use PayPal or card.',true);return;}
    if(!container.isConnected)return;
    const {applepay,settings}=available;
    const button=document.createElement('apple-pay-button');
    button.setAttribute('buttonstyle','black');button.setAttribute('type','buy');button.setAttribute('locale','en-US');
    button.setAttribute('aria-label','Buy credits with Apple Pay');
    button.onclick=()=>{
      if(busy)return;
      const p=pack();if(!p)return;
      const attempt=checkoutAttempt('apple_pay',p.id);
      let session,checkout,cancelled=false,captureStarted=false,captured=false;
      const finish=()=>{
        if(appleSession!==session)return;
        appleSession=null;busy=false;container.classList.remove('cw-wallet-busy');button.removeAttribute('aria-disabled');
      };
      const complete=status=>{try{session.completePayment(status);}catch{}finally{finish();}};
      try{
        // Apple requires session creation and begin() inside this user gesture.
        const total={label:'LockX — '+p.credits+' verification credits',type:'final',amount:(p.amount_cents/100).toFixed(2)};
        session=new ApplePaySession(4,{countryCode:settings.countryCode,currencyCode:'USD',
          merchantCapabilities:settings.merchantCapabilities,supportedNetworks:settings.supportedNetworks,
          requiredBillingContactFields:['postalAddress'],
          total});
        appleSession=session;busy=true;container.classList.add('cw-wallet-busy');button.setAttribute('aria-disabled','true');
        session.oncancel=()=>{
          cancelled=true;
          // Once capture starts, wait for its result before allowing another charge.
          if(captureStarted)return;
          finish();save(attemptKey,null);
          if(checkout&&waitingCheckout===checkout.id){waitingCheckout=null;save(pendingKey,null);}
        };
        session.onpaymentmethodselected=()=>{
          if(!cancelled&&appleSession===session)session.completePaymentMethodSelection({newTotal:total});
        };
        session.onvalidatemerchant=async event=>{
          try{
            const result=await applepay.validateMerchant({validationUrl:event.validationURL,displayName:'LockX'});
            if(!cancelled&&appleSession===session)session.completeMerchantValidation(result.merchantSession);
          }catch{
            if(appleSession!==session)return;
            try{session.abort();}catch{}finally{finish();}
            message('Apple Pay could not connect. Please try again or use PayPal or card.',true);
          }
        };
        session.onpaymentauthorized=async event=>{
          try{
            if(cancelled||appleSession!==session)return;
            checkout=await post('/checkouts',{pack_id:attempt.packId,provider:'apple_pay',request_key:attempt.key});
            if(cancelled||appleSession!==session)return;
            if(checkout.status!=='paid'){
              waitingCheckout=checkout.id;save(pendingKey,checkout.id);
              const confirmation=await applepay.confirmOrder({orderId:checkout.paypal_order_id,token:event.payment.token,billingContact:event.payment.billingContact});
              if(cancelled||appleSession!==session)return;
              if(confirmation.status&&confirmation.status!=='APPROVED')throw Error('Apple Pay has not approved this payment.');
              captureStarted=true;
              await post('/checkouts/'+checkout.id+'/capture',{order_id:checkout.paypal_order_id});
            }
            captured=true;
            if(!cancelled)complete(ApplePaySession.STATUS_SUCCESS);else finish();
            waitingCheckout=null;save(pendingKey,null);save(attemptKey,null);
            await refreshWallet({force:true});message(`${checkout.credits} credits added. You’re ready to verify.`);
          }catch(error){
            if(appleSession===session){if(!cancelled)complete(ApplePaySession.STATUS_FAILURE);else finish();}
            if(cancelled&&!captureStarted)return;
            message(captured?'Payment confirmed. Refresh your wallet to see your credits.':checkout?'Payment confirmation is incomplete. Check your credits before trying again.':'Apple Pay could not complete the payment. Please try again.',!captured);
            if(checkout)watchCheckout(checkout.id);
          }
        };
        session.begin();
      }catch{
        finish();message('Apple Pay could not open on this device. Please use PayPal or card.',true);
      }
    };
    container.replaceChildren(button);container.hidden=false;
  }
  function applePayState(container,copy,retry=false) {
    if(!container.isConnected)return;
    const status=document.createElement('p');status.className='cw-apple-pay-status';status.setAttribute('role','status');status.textContent=copy;
    const children=[status];
    if(retry){
      const button=document.createElement('button');button.type='button';button.className='cw-text-button cw-apple-pay-retry';button.textContent='Try Apple Pay again';
      button.onclick=()=>setupApplePay();children.push(button);
    }
    container.replaceChildren(...children);container.hidden=false;
  }
  async function setupGooglePay() {
    if(!googleBoot)googleBoot=(async()=>{
      await Promise.all([window.google?.payments?Promise.resolve():loadScript('https://pay.google.com/gp/p/js/pay.js'),loadPayPalWalletSDK()]);
      const paypalGoogle=window.paypal.Googlepay();const settings=await paypalGoogle.config();
      const googleClient=new google.payments.api.PaymentsClient({environment:config.environment==='live'?'PRODUCTION':'TEST',paymentDataCallbacks:{onPaymentAuthorized:async data=>{
        try{
          if(!googlePurchase)throw Error('Please reopen Google Pay to confirm this purchase.');
          const checkout=await post('/checkouts',{pack_id:googlePurchase.packId,provider:'google_pay',request_key:googlePurchase.key});
          if(checkout.status==='paid'){
            save(attemptKey,null);await refreshWallet({force:true});return {transactionState:'SUCCESS'};
          }
          const confirmation=await paypalGoogle.confirmOrder({orderId:checkout.paypal_order_id,paymentMethodData:data.paymentMethodData});
          if(confirmation.status==='PAYER_ACTION_REQUIRED')await paypalGoogle.initiatePayerAction({orderId:checkout.paypal_order_id});
          else if(confirmation.status!=='APPROVED')throw Error('Payment has not been approved.');
          await post('/checkouts/'+checkout.id+'/capture',{order_id:checkout.paypal_order_id});
          save(attemptKey,null);await refreshWallet({force:true});message(`${checkout.credits} credits added. You’re ready to verify.`);
          return {transactionState:'SUCCESS'};
        }catch(error){return {transactionState:'ERROR',error:{intent:'PAYMENT_AUTHORIZATION',message:error.message}};}
      }}});
      const eligible=await googleClient.isReadyToPay({apiVersion:2,apiVersionMinor:0,allowedPaymentMethods:settings.allowedPaymentMethods});
      if(!eligible.result)throw Error('Google Pay is not available on this device.');
      return {googleClient,settings};
    })().catch(error=>{googleBoot=null;throw error;});
    const {googleClient,settings}=await googleBoot;
    const el=$('#cwGooglePay');if(!el)return;
    el.replaceChildren(googleClient.createButton({buttonColor:'black',buttonType:'pay',buttonSizeMode:'fill',allowedPaymentMethods:settings.allowedPaymentMethods,onClick:()=>{
      if(busy)return;busy=true;
      const p=pack();googlePurchase=checkoutAttempt('google_pay',p.id);
      googleClient.loadPaymentData({apiVersion:2,apiVersionMinor:0,allowedPaymentMethods:settings.allowedPaymentMethods,
        merchantInfo:{...settings.merchantInfo,merchantId:config.google_merchant_id},
        transactionInfo:{currencyCode:'USD',countryCode:'US',totalPriceStatus:'FINAL',totalPrice:(p.amount_cents/100).toFixed(2)},
        callbackIntents:['PAYMENT_AUTHORIZATION']}).catch(error=>{if(error.statusCode!=='CANCELED')message('Google Pay could not complete the payment. Please try again.',true);}).finally(()=>{busy=false;googlePurchase=null;});
    }}));
  }
  async function ensureForVerification() {
    await ready;
    if(config.error)throw Error(config.error);
    if(!config.credits_required)return;
    if(!await authorization()){await open();throw Error('Open the email sign-in link, then continue your verification.');}
    await refreshWallet({force:true});
    if(balance<1){await open();throw Error('Buy a credit pack, then continue your verification.');}
  }
  document.addEventListener('click',event=>{
    const control=event.target.closest('[data-credit-pack],[data-credit-wallet],[data-pick-pack]');if(!control)return;
    event.preventDefault();
    if(control.dataset.pickPack){if(!busy){selected=control.dataset.pickPack;updatePackSummary();}return;}
    open(control.dataset.creditPack);
  });
  const warmOnWalletIntent=event=>{
    if(event.target.closest('[data-credit-pack],[data-credit-wallet],[data-pick-pack],#cwEmail'))warmPaymentOptions();
  };
  document.addEventListener('pointerdown',warmOnWalletIntent,{passive:true});
  document.addEventListener('pointerover',warmOnWalletIntent,{passive:true});
  document.addEventListener('touchstart',warmOnWalletIntent,{passive:true});
  document.addEventListener('focusin',warmOnWalletIntent);
  window.addEventListener('lockx-page',decorate);
  document.addEventListener('DOMContentLoaded',decorate,{once:true});
  window.addEventListener('lockx-session',()=>setTimeout(async()=>{
    if(!active())return;
    try{
      const current=await walletSession();
      if(!current?.access_token){balanceLoading=false;updateBalanceLabels();return;}
      if($('#creditWalletDialog')?.open)await renderWallet();else await refreshWallet();
    }catch{}
  },0));
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&waitingCheckout&&$('#creditWalletDialog')?.open)watchCheckout(waitingCheckout);});
  window.LockXCredits={ready,authorization,ensureForVerification,refresh:refreshWallet,open,decorate};
  // A stored entry is only a reason to restore the SDK session, never authentication.
  let returningSession=false;
  try{returningSession=!!localStorage.getItem('sb-'+new URL(SUPABASE_URL).hostname.split('.')[0]+'-auth-token');}catch{}
  if(returningSession||location.hash==='#in-hand'||isReturn)warmBalance();
})();
