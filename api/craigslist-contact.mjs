import {contactRequest,DEFAULT_CONTACT_SNAPSHOT_ID} from '../lib/contact-sandbox.mjs';

export function createContactHandler(dependencies={}){
  return async function handler(req,res){
    res.setHeader('Cache-Control','no-store');
    res.setHeader('X-Content-Type-Options','nosniff');
    if(req.method!=='POST'){res.setHeader('Allow','POST');return res.status(405).json({error:'POST required.'});}
    if(!/^application\/json(?:\s*;|$)/i.test(req.headers['content-type']||''))return res.status(415).json({error:'JSON required.'});
    let body=req.body;
    try{
      if(typeof body==='string'){if(Buffer.byteLength(body)>9000)throw Error();body=JSON.parse(body);}
      if(Buffer.isBuffer(body)){if(body.length>9000)throw Error();body=JSON.parse(body.toString('utf8'));}
    }catch{return res.status(400).json({error:'A valid lookup ticket is required.'});}
    const answer=await contactRequest(body,{snapshotId:process.env.LOCKX_CONTACT_SNAPSHOT_ID||DEFAULT_CONTACT_SNAPSHOT_ID,...dependencies});
    return res.status(answer.code).json(answer.body);
  };
}
export default createContactHandler();
