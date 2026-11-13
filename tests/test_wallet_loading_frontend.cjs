/* Execute the real wallet in an isolated VM; every HTTP response is fake. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'credit-wallet.js'), 'utf8');
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return {promise, resolve, reject};
};
const response = body => ({ok: true, json: async () => body});
const wallet = balance => ({balance, credit_debt: 0, history: []});
const account = id => ({access_token: 'token-' + id, user: {id, email: id + '@example.test'}});
const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
async function until(predicate, message) {
  for (let i = 0; i < 200; i++) {
    if (predicate()) return;
    await Promise.resolve();
  }
  assert.ok(predicate(), message);
}

class Element {
  constructor(tag = 'div') {
    this.tag = tag; this.hidden = false; this.isConnected = true;
    this.textContent = ''; this.innerHTML = ''; this.children = []; this.attributes = {};
    const classes = new Set();
    this.classList = {
      add: (...names) => names.forEach(name => classes.add(name)),
      remove: (...names) => names.forEach(name => classes.delete(name)),
      contains: name => classes.has(name),
      toggle(name, force) {
        const enabled = force === undefined ? !classes.has(name) : force;
        if (enabled) classes.add(name); else classes.delete(name);
        return enabled;
      },
    };
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  replaceChildren(...children) { this.children = children; }
  addEventListener() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
  focus() {}
}

function storage(initial = {}) {
  const result = {...initial};
  Object.defineProperties(result, {
    getItem: {value: key => Object.prototype.hasOwnProperty.call(result, key) ? result[key] : null},
    setItem: {value: (key, value) => { result[key] = String(value); }},
    removeItem: {value: key => { delete result[key]; }},
    key: {value: index => Object.keys(result)[index] ?? null},
    length: {get: () => Object.keys(result).length},
  });
  return result;
}

function harness(options = {}) {
  const catalog = options.catalog || deferred();
  const requests = [], authCalls = [], scripts = [], errors = [];
  const listeners = {}, documentListeners = {}, timerCallbacks = new Map(), authListeners = [];
  let sessionReads = 0;
  let current = options.session === undefined ? account('owner-a') : options.session;
  const inline = new Element('strong'), suffix = new Element('span'), header = new Element('button');
  inline.textContent = header.textContent = 'Your credits'; suffix.hidden = true;
  const nodes = new Map([
    ['[data-credit-balance]', inline], ['.cw-wallet-suffix', suffix], ['#cwHeaderButton', header],
    ['#cwSelectedSummary', new Element()], ['#cwMessage', new Element()],
    ['#creditWalletDialog', new Element('dialog')], ['#cwDialogContent', new Element()],
    ['#cwPayPal', new Element('button')], ['#cwSignOut', new Element('button')],
    ['#cwHistory', new Element()], ['.cw-balance strong', new Element('strong')],
  ]);
  const config = {
    credits_required: true, payment_ready: true, apple_pay_ready: false, google_pay_ready: false,
    currency: 'USD', environment: 'live',
    packs: [{id: 'regular', name: 'Regular', credits: 10, amount_cents: 500}],
  };
  const document = {
    hidden: false, activeElement: null,
    querySelector: selector => nodes.get(selector) || null,
    querySelectorAll: selector => selector.split(',').flatMap(part => {
      const node = nodes.get(part.trim()); return node ? [node] : [];
    }),
    getElementById: id => nodes.get('#' + id) || null,
    createElement: tag => new Element(tag),
    addEventListener: (type, callback) => { documentListeners[type] = callback; },
    head: {append: script => scripts.push(script)}, body: {append() {}},
  };
  const client = {auth: {
    getSession: async () => ({data: {session: options.sessionResponse ?
      await options.sessionResponse(current, ++sessionReads) : current}, error: null}),
    onAuthStateChange: callback => { authListeners.push(callback); },
    signOut: async () => { current = null; return {error: null}; },
  }};
  const location = {
    search: options.search || '', hash: options.hash || '#landing', origin: 'https://lockx.ai',
    href: 'https://lockx.ai/' + (options.search || '') + (options.hash || '#landing'),
  };
  const localStorage = storage(options.storedSession ? {
    'sb-vlxrryhfaaxjqyzhzhxg-auth-token': JSON.stringify({access_token: 'untrusted-storage-hint'}),
  } : {});
  const window = {
    addEventListener(type, callback) { listeners[type] = callback; },
    ensureLockXAuthClient: async () => {
      authCalls.push(true);
      if (options.authPending) await options.authPending;
      return client;
    },
  };
  let nextTimer = 0;
  const context = {
    window, document, location, localStorage, sessionStorage: storage(),
    API_BASE: 'https://api.example.test', SUPABASE_URL: 'https://vlxrryhfaaxjqyzhzhxg.supabase.co',
    URL, URLSearchParams, console,
    crypto: {randomUUID: () => 'test-request-key'},
    setInterval: () => 1, clearInterval() {}, clearTimeout: id => timerCallbacks.delete(id),
    setTimeout(callback, delay) {
      const id = ++nextTimer;
      if (!delay) Promise.resolve().then(callback).catch(error => errors.push(error));
      else timerCallbacks.set(id, callback);
      return id;
    },
    toast: (...args) => errors.push(new Error(args.join(': '))),
    fetch: async (url, init = {}) => {
      if (url.endsWith('/catalog')) return response(await catalog.promise);
      const entry = {url, init}; requests.push(entry);
      assert.ok(url.endsWith('/wallet'), 'Loading credits must not create a checkout or payment');
      const value = options.walletResponse ? await options.walletResponse(entry, requests.length) : wallet(2);
      return value && typeof value.json === 'function' ? value : response(value);
    },
  };
  vm.createContext(context);
  const marker = 'window.LockXCredits={ready,';
  const instrumented = source.replace(marker,
    'window.__loadingTest={warmBalance,refreshWallet,adoptSession,updateBalanceLabels,state:()=>({balance,balanceLoading,balanceFailed,activeOwner,walletGeneration,walletFlight})};' + marker);
  assert.notEqual(instrumented, source, 'Private test instrumentation must find the public export.');
  vm.runInContext(instrumented, context, {filename: 'credit-wallet.js'});
  return {
    api: window.__loadingTest, window, inline, suffix, header, nodes, requests, scripts, authCalls, errors,
    ready: window.LockXCredits.ready,
    resolveCatalog: () => catalog.resolve(config),
    setSession: value => { current = value; },
    authEvent(value) {
      current = value;
      for (const callback of authListeners) callback(value ? 'SIGNED_IN' : 'SIGNED_OUT', value);
    },
    sessionReads: () => sessionReads,
    async sessionEvent() { listeners['lockx-session'](); await flush(); },
  };
}

const tests = [];
function test(name, run) { tests.push([name, run]); }

test('stored-session startup overlaps auth with a pending catalog, without trusting the hint', async () => {
  const auth = deferred();
  const h = harness({storedSession: true, authPending: auth.promise});
  await until(() => h.authCalls.length === 1, 'Auth should start before the catalog finishes.');
  assert.equal(h.requests.length, 0);
  h.resolveCatalog(); await h.ready; await flush();
  assert.equal(h.requests.length, 0, 'Catalog alone must not authorize a wallet request.');
  auth.resolve();
  await until(() => h.api.state().balance === 2, 'SDK-restored session should load the real balance.');
  assert.equal(h.authCalls.length, 1);
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].init.headers.Authorization, 'Bearer token-owner-a');
});

test('the verification route preloads balance without a stored session or wallet click', async () => {
  const h = harness({hash: '#in-hand'});
  await until(() => h.authCalls.length === 1, 'Verification should start auth while catalog is pending.');
  h.resolveCatalog(); await h.ready;
  await until(() => h.api.state().balance === 2, 'Verification should load credits before opening a wallet.');
  assert.equal(h.requests.length, 1);
});

test('an anonymous landing visit does not boot auth or fetch a wallet', async () => {
  const h = harness({session: null}); h.resolveCatalog(); await h.ready; await flush();
  assert.equal(h.authCalls.length, 0);
  assert.equal(h.requests.length, 0);
  assert.equal(h.scripts.length, 0);
  assert.equal(h.inline.textContent, 'Your credits');
  assert.equal(h.inline.classList.contains('cw-balance-loading'), false);
  assert.equal(h.suffix.hidden, true);
});

test('a stale storage hint with no SDK session cannot fetch or display credits', async () => {
  const h = harness({storedSession: true, session: null});
  h.resolveCatalog(); await h.ready; await h.api.warmBalance(); await flush();
  assert.equal(h.requests.length, 0);
  assert.equal(h.api.state().balance, null);
  assert.equal(h.inline.textContent, 'Your credits');
  assert.equal(h.inline.classList.contains('cw-balance-loading'), false);
  assert.equal(h.suffix.hidden, true);
});

test('concurrent startup, explicit refresh and session events share one owner wallet request', async () => {
  const pending = deferred();
  const h = harness({storedSession: true, walletResponse: () => pending.promise});
  h.resolveCatalog(); await h.ready;
  await until(() => h.requests.length === 1, 'The first wallet request should start.');
  const refreshing = h.api.refreshWallet();
  const warming = h.api.warmBalance();
  await h.sessionEvent();
  assert.equal(h.requests.length, 1, 'Overlapping consumers should reuse the same request.');
  pending.resolve(wallet(4)); await Promise.all([refreshing, warming]); await flush();
  assert.equal(h.api.state().balance, 4);
  assert.equal(h.requests.length, 1);
});

test('a late wallet response cannot restore credits after sign-out', async () => {
  const pending = deferred(); const h = harness({walletResponse: () => pending.promise});
  h.resolveCatalog(); await h.ready;
  const refreshing = h.api.refreshWallet();
  await until(() => h.requests.length === 1, 'A signed-in request should start.');
  h.setSession(null); h.api.adoptSession(null); h.api.updateBalanceLabels();
  pending.resolve(wallet(99)); await refreshing; await flush();
  assert.equal(h.api.state().activeOwner, null);
  assert.equal(h.api.state().balance, null);
  assert.equal(h.inline.textContent, 'Your credits');
  assert.equal(h.header.textContent, 'Your credits');
  assert.equal(h.suffix.hidden, true);
});

test('account B keeps its own balance when account A finishes later', async () => {
  const pendingA = deferred(), pendingB = deferred();
  const h = harness({walletResponse: (_, count) => count === 1 ? pendingA.promise : pendingB.promise});
  h.resolveCatalog(); await h.ready;
  const oldRefresh = h.api.refreshWallet(); await until(() => h.requests.length === 1, 'Account A should start.');
  const b = account('owner-b'); h.setSession(b); h.api.adoptSession(b);
  const newRefresh = h.api.refreshWallet(); await until(() => h.requests.length === 2, 'Account B needs a separate request.');
  assert.equal(h.requests[1].init.headers.Authorization, 'Bearer token-owner-b');
  pendingB.resolve(wallet(3)); await newRefresh;
  pendingA.resolve(wallet(99)); await oldRefresh;
  assert.equal(h.api.state().activeOwner, 'owner-b');
  assert.equal(h.api.state().balance, 3);
  assert.equal(h.inline.textContent, '3 credits');
  assert.equal(h.header.textContent, '3 credits');
  assert.equal(h.suffix.hidden, false);
});

test('a pending SDK session snapshot cannot re-adopt an account after sign-out', async () => {
  const snapshot = deferred();
  const h = harness({sessionResponse: (current, count) => count === 1 ? snapshot.promise : current});
  h.resolveCatalog(); await h.ready; h.api.adoptSession(account('owner-a'));
  const refreshing = h.api.refreshWallet();
  await until(() => h.sessionReads() === 1, 'SDK session lookup should be pending.');
  h.authEvent(null);
  snapshot.resolve(account('owner-a')); await refreshing;
  assert.equal(h.requests.length, 0, 'A pre-sign-out SDK snapshot cannot authorize another wallet request.');
  assert.equal(h.api.state().activeOwner, null);
  assert.equal(h.api.state().balance, null);
  assert.equal(h.inline.textContent, 'Your credits');
});

test('a stale SDK snapshot retries the new account rather than requesting the old wallet', async () => {
  const snapshot = deferred();
  const h = harness({sessionResponse: (current, count) => count === 1 ? snapshot.promise : current,
    walletResponse: () => wallet(3)});
  h.resolveCatalog(); await h.ready; h.api.adoptSession(account('owner-a'));
  const refreshing = h.api.refreshWallet();
  await until(() => h.sessionReads() === 1, 'Account A session lookup should be pending.');
  h.authEvent(account('owner-b'));
  snapshot.resolve(account('owner-a')); await refreshing;
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].init.headers.Authorization, 'Bearer token-owner-b');
  assert.equal(h.api.state().activeOwner, 'owner-b');
  assert.equal(h.api.state().balance, 3);
});

test('repeated SDK snapshots crossing account changes stop after a bounded retry', async () => {
  const snapshots = [deferred(), deferred()];
  const h = harness({sessionResponse: (_, count) => {
    assert.ok(count <= 2, 'An unstable SDK session must not retry without a bound.');
    return snapshots[count - 1].promise;
  }});
  h.resolveCatalog(); await h.ready; h.api.adoptSession(account('owner-a'));
  const refreshing = h.api.refreshWallet();
  await until(() => h.sessionReads() === 1, 'The first session lookup should start.');
  h.authEvent(account('owner-b')); snapshots[0].resolve(account('owner-a'));
  await until(() => h.sessionReads() === 2, 'A changed account should trigger one retry.');
  h.authEvent(account('owner-c')); snapshots[1].resolve(account('owner-b'));
  await assert.rejects(refreshing);
  assert.equal(h.requests.length, 0);
  assert.equal(h.api.state().activeOwner, 'owner-c');
  assert.equal(h.api.state().balance, null);
});

test('loading is inline-only and clears to a singular balance with the wallet suffix', async () => {
  const pending = deferred(); const h = harness({walletResponse: () => pending.promise});
  h.resolveCatalog(); await h.ready;
  const refreshing = h.api.refreshWallet(); await until(() => h.requests.length === 1, 'Wallet fetch should be pending.');
  assert.equal(h.inline.textContent, 'Credits loading…');
  assert.equal(h.inline.classList.contains('cw-balance-loading'), true);
  assert.equal(h.header.textContent, 'Your credits');
  assert.equal(h.suffix.hidden, true);
  pending.resolve(wallet(1)); await refreshing;
  assert.equal(h.inline.textContent, '1 credit');
  assert.equal(h.inline.classList.contains('cw-balance-loading'), false);
  assert.equal(h.header.textContent, '1 credit');
  assert.equal(h.suffix.hidden, false);
});

test('a failed balance request stops loading and a later request can retry', async () => {
  const pending = deferred();
  const h = harness({walletResponse: (_, count) => count === 1 ? pending.promise : wallet(7)});
  h.resolveCatalog(); await h.ready;
  const refreshing = h.api.refreshWallet().catch(() => null);
  await until(() => h.requests.length === 1, 'The failing request should start.');
  pending.reject(Error('Test connection failed')); await refreshing; await flush();
  assert.equal(h.inline.textContent, 'Credits unavailable');
  assert.equal(h.inline.classList.contains('cw-balance-loading'), false);
  assert.equal(h.suffix.hidden, true);
  assert.equal(h.header.textContent, 'Your credits');
  await h.api.refreshWallet();
  assert.equal(h.requests.length, 2);
  assert.equal(h.inline.textContent, '7 credits');
  assert.equal(h.inline.classList.contains('cw-balance-loading'), false);
  assert.equal(h.suffix.hidden, false);
});

test('a forced refresh supersedes a request started before a credit mutation', async () => {
  const oldResponse = deferred(), freshResponse = deferred();
  const h = harness({walletResponse: (_, count) => count === 1 ? oldResponse.promise : freshResponse.promise});
  h.resolveCatalog(); await h.ready;
  const oldRefresh = h.api.refreshWallet(); await until(() => h.requests.length === 1, 'Old refresh should start.');
  const freshRefresh = h.api.refreshWallet({force: true});
  await until(() => h.requests.length === 2, 'A post-mutation force refresh cannot reuse the old response.');
  freshResponse.resolve(wallet(1)); await freshRefresh;
  oldResponse.resolve(wallet(40)); await oldRefresh;
  assert.equal(h.api.state().balance, 1);
  assert.equal(h.inline.textContent, '1 credit');
});

module.exports = async function run() {
  const results = [];
  for (const [name, testCase] of tests) {
    try { await testCase(); results.push({name, status: 'PASS'}); }
    catch (error) { results.push({name, status: 'FAIL', error: error.stack}); }
  }
  return results;
};
