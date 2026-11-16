/* The caller supplies only a one-use Railway ticket. No browser capability is public. */
import {readFile} from 'node:fs/promises';

export const CLAIM_URL='https://lockx-production.up.railway.app/api/v1/in-hand/contact-lookup/claim';
export const DEFAULT_CONTACT_SNAPSHOT_ID=''; // Set only after the authenticated bootstrap probe passes.
export const VM_DIR='/vercel/sandbox/lockx-contact';
const PYTHON='/vercel/sandbox/contact-venv/bin/python';
const BROWSER_ENV=Object.freeze({PLAYWRIGHT_BROWSERS_PATH:'/vercel/sandbox/contact-browsers',PYTHONDONTWRITEBYTECODE:'1'});
const EXACT_CLAIM=['expires','listing_url','nonce','purpose','version'];
const LISTING=/^\/(?:view\/d\/[^/]+\/[A-Za-z0-9_-]{6,80}|(?:[a-z]{3}\/)?[a-z]{3}\/d\/[^/]+\/[0-9]{6,20}\.html)\/?$/;
const NONCE=/^[A-Za-z0-9_-]{43}$/;
const isObject=value=>!!value&&typeof value==='object'&&!Array.isArray(value);
const exactKeys=(value,keys)=>isObject(value)&&Object.keys(value).sort().join(',')===[...keys].sort().join(',');

export function eligibleListing(value){
  if(typeof value!=='string'||!value||value.length>4000||/[\x00-\x20\x7f\\]/.test(value))return false;
  try{
    const url=new URL(value),decoded=decodeURIComponent(value);
    return url.protocol==='https:'&&!url.username&&!url.password&&!url.port&&!url.hash&&
      /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*craigslist\.org$/.test(url.hostname)&&
      LISTING.test(url.pathname)&&!/%(?:2f|5c|25)/i.test(url.pathname)&&!/[\x00-\x20\x7f\\]/.test(decoded)&&url.href===value;
  }catch{return false;}
}

export function validClaim(value,now=Date.now()){
  return exactKeys(value,EXACT_CLAIM)&&value.version===1&&typeof value.nonce==='string'&&NONCE.test(value.nonce)&&
    ['lookup','bootstrap'].includes(value.purpose)&&Number.isSafeInteger(value.expires)&&value.expires>now/1000&&value.expires<=now/1000+600&&
    eligibleListing(value.listing_url);
}

async function boundedResponse(response,limit=8192){
  if(!response.ok)throw Error('Claim rejected');
  if(!/\bapplication\/json\b/i.test(response.headers.get('content-type')||''))throw Error('Invalid claim');
  const reader=response.body.getReader();let size=0;const chunks=[];
  try{for(;;){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>limit)throw Error('Oversized claim');chunks.push(Buffer.from(value));}}
  finally{await reader.cancel().catch(()=>{});}
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

async function command(sandbox,cmd,args,{timeoutMs=10000,maxBytes=16384,sudo=false}={}){
  const signal=AbortSignal.timeout(timeoutMs+1500);
  const child=await sandbox.runCommand({cmd,args,cwd:'/vercel/sandbox',env:{...BROWSER_ENV},sudo,detached:true,timeoutMs,signal});
  let bytes=0,stdout='';
  try{
    for await(const log of child.logs({signal})){
      bytes+=Buffer.byteLength(log.data);if(bytes>maxBytes)throw Error('Command output limit');
      if(log.stream==='stdout')stdout+=log.data;
    }
    const finished=await child.wait({signal});if(finished.exitCode!==0)throw Error('Sandbox command failed');
    return stdout;
  }catch(error){await child.kill('SIGKILL',{signal:AbortSignal.timeout(1000)}).catch(()=>{});throw error;}
}

async function uploadCode(sandbox,read=readFile){
  const [helper,worker]=await Promise.all([
    read(new URL('../craigslist_contact.py',import.meta.url)),
    read(new URL('../scripts/contact_worker.py',import.meta.url))
  ]);
  await sandbox.writeFiles([{path:VM_DIR+'/craigslist_contact.py',content:helper,mode:0o600},
    {path:VM_DIR+'/contact_worker.py',content:worker,mode:0o600}]);
}

function result(claim,status='unavailable',email=null){return {...claim,status,email};}
function workerResult(raw,claim){
  if(Buffer.byteLength(raw)>4096)throw Error('Oversized worker result');
  const value=JSON.parse(raw);
  if(!exactKeys(value,['version','nonce','url','status','email'])||value.version!==1||value.nonce!==claim.nonce||value.url!==claim.listing_url||!['revealed','unavailable','blocked','busy'].includes(value.status))throw Error('Unbound worker result');
  if(value.status==='revealed'){
    if(typeof value.email!=='string'||value.email.length>254||!/^[A-Za-z0-9!#$&'*+\-/=?^_`{|}~]+(?:\.[A-Za-z0-9!#$&'*+\-/=?^_`{|}~]+)*@sale\.craigslist\.org$/.test(value.email)||value.email.split('@')[0].length>64||/^(support|help|privacy|legal|noreply|no[._-]reply|donotreply|do[._-]not[._-]reply|abuse|webmaster|security)(?:[+._-].*)?$/i.test(value.email.split('@')[0]))throw Error('Invalid relay');
  }else if(value.email!==null)throw Error('Unexpected relay');
  return result(claim,value.status,value.email);
}

async function bootstrap(sandbox,read,onStage){
  // Fixed dependency commands only. No ticket, listing, backend credentials or user data enters this VM.
  onStage('system-dependencies');
  await command(sandbox,'sudo',['-n','true'],{timeoutMs:5000});
  await command(sandbox,'apt-get',['update','-qq'],{sudo:true,timeoutMs:30000,maxBytes:262144});
  await command(sandbox,'apt-get',['install','-y','-qq','python3-venv','util-linux'],{sudo:true,timeoutMs:30000,maxBytes:262144});
  onStage('python-dependencies');
  await command(sandbox,'python3',['-m','venv','/vercel/sandbox/contact-venv'],{timeoutMs:10000});
  await command(sandbox,PYTHON,['-m','pip','install','--no-cache-dir','playwright==1.64.0','httpx==0.28.1'],{timeoutMs:35000,maxBytes:262144});
  onStage('chromium-install');
  await command(sandbox,PYTHON,['-m','playwright','install','--with-deps','chromium'],{sudo:true,timeoutMs:60000,maxBytes:524288});
  onStage('sandbox-probe');
  await sandbox.update({networkPolicy:'deny-all'});
  await uploadCode(sandbox,read);
  const probe=JSON.parse(await command(sandbox,PYTHON,[VM_DIR+'/contact_worker.py','--probe'],{timeoutMs:12000,maxBytes:4096}));
  if(!exactKeys(probe,['version','status','sandbox','userns'])||probe.version!==1||probe.status!=='ready'||probe.sandbox!==true||probe.userns!==true)throw Error('Sandbox probe failed');
  await command(sandbox,'rm',['-rf',VM_DIR],{timeoutMs:3000});
  onStage('clean-snapshot');
  const snapshot=await sandbox.snapshot({expiration:30*24*60*60*1000});
  if(snapshot.status!=='created'||typeof snapshot.snapshotId!=='string'||!/^snap_[A-Za-z0-9_-]{4,180}$/.test(snapshot.snapshotId))throw Error('Invalid snapshot');
  return snapshot.snapshotId;
}

export async function contactRequest(body,{fetchImpl=fetch,loadSandbox=async()=> (await import('@vercel/sandbox')).Sandbox,
  snapshotId=DEFAULT_CONTACT_SNAPSHOT_ID,readFileImpl=readFile,now=Date.now}={}){
  if(!exactKeys(body,['ticket'])||typeof body.ticket!=='string'||!NONCE.test(body.ticket))return {code:400,body:{error:'A valid lookup ticket is required.'}};
  let claim;
  try{
    claim=await boundedResponse(await fetchImpl(CLAIM_URL,{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify({ticket:body.ticket}),redirect:'error',signal:AbortSignal.timeout(4000)}));
    if(!validClaim(claim,now()))throw Error('Invalid claim');
  }catch{return {code:403,body:{error:'The lookup ticket could not be claimed.'}};}
  // Authentication and one-use budget admission must precede SDK loading or VM creation.
  if(claim.purpose==='lookup'&&(!snapshotId||!/^snap_[A-Za-z0-9_-]{4,180}$/.test(snapshotId)))return {code:200,body:result(claim)};
  let sandbox,stage='sdk';
  try{
    const Sandbox=await loadSandbox();
    if(claim.expires<=now()/1000)throw Error('Expired claim');
    stage='vm-create';
    sandbox=await Sandbox.create({persistent:false,resources:{vcpus:1},env:{},ports:[],
      timeout:claim.purpose==='bootstrap'?180000:20000,
      ...(claim.purpose==='lookup'?{source:{type:'snapshot',snapshotId},networkPolicy:{allow:['craigslist.org','*.craigslist.org']}}:{networkPolicy:'allow-all'})});
    if(claim.purpose==='bootstrap'){
      const snapshot_id=await bootstrap(sandbox,readFileImpl,value=>stage=value);
      return {code:200,body:{...claim,status:'ready',snapshot_id,id:sandbox.name}};
    }
    await uploadCode(sandbox,readFileImpl);
    await sandbox.writeFiles([{path:VM_DIR+'/job.json',content:JSON.stringify({version:1,nonce:claim.nonce,listing_url:claim.listing_url}),mode:0o600}]);
    const raw=await command(sandbox,PYTHON,[VM_DIR+'/contact_worker.py',VM_DIR+'/job.json'],{timeoutMs:10000,maxBytes:4096});
    return {code:200,body:workerResult(raw,claim)};
  }catch{return {code:claim.purpose==='bootstrap'?503:200,body:claim.purpose==='bootstrap'?{...claim,status:'unavailable',snapshot_id:null,stage}:result(claim)};}
  finally{
    if(sandbox){
      let closed=false;
      try{await sandbox.stop({signal:AbortSignal.timeout(3000)});closed=true;}catch{}
      // Keep the clean shared dependency snapshot; nonpersistent lookup VMs
      // never create a new snapshot containing the request or its contact.
      try{await sandbox.delete({deleteOrphanSnapshots:false,signal:AbortSignal.timeout(3000)});closed=true;}catch{}
      // Do not let Railway release its admission lease while VM termination
      // is uncertain. Its lease/VM TTL will recover this failure safely.
      if(!closed)return {code:503,body:{error:'Contact worker cleanup could not be confirmed.'}};
    }
  }
}
