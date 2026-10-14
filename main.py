
import os,hashlib
from datetime import datetime,timezone
from uuid import uuid4
import httpx
from fastapi import FastAPI,Header,HTTPException,Depends,UploadFile,File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
app=FastAPI()
app.add_middleware(CORSMiddleware,allow_origins=["https://lockx.ai","https://www.lockx.ai"],allow_methods=["GET","POST"],allow_headers=["*"])
class C(BaseModel):
 brand:str;model:str;reference:str|None=None;serial_number:str|None=None;distinctive_details:str|None=None
def cfg():
 u,k=os.getenv("SUPABASE_URL"),os.getenv("SUPABASE_SERVICE_ROLE_KEY")
 if not u or not k:raise HTTPException(503,"Case storage is not configured")
 return u.rstrip("/"),k
def req(method,path,data=None):
 u,k=cfg()
 try:
  # Supabase's current sb_secret keys are API keys, not JWT bearer tokens.
  # Supplying one as Authorization makes PostgREST treat the request as an
  # unprivileged user request, which causes the RLS failure seen in case intake.
  r=httpx.request(method,f"{u}/rest/v1/{path}",headers={"apikey":k,"Content-Type":"application/json","Prefer":"return=representation"},json=data,timeout=30);r.raise_for_status();return r
 except httpx.HTTPError as e:raise HTTPException(503,"Case storage is temporarily unavailable") from e
def who(a:str|None=Header(default=None)):
 if not a or not a.startswith("Bearer "):raise HTTPException(401,"Sign in to access recovery cases")
 u,k=cfg();r=httpx.get(f"{u}/auth/v1/user",headers={"apikey":k,"Authorization":a},timeout=10)
 if r.status_code!=200 or not r.json().get("id"):raise HTTPException(401,"Your session has expired; please sign in again")
 return r.json()["id"]
def out(x):return {"id":x["id"],"case_number":x["case_number"],"brand":x["brand"],"model":x.get("model") or "Unknown model","reference":x.get("reference_number"),"serial_number":x.get("serial_number"),"distinctive_details":x.get("distinctive_marks"),"status":"paused" if x.get("status")=="paused" else "monitoring","created_at":x["created_at"]}
def owned(i,o):
 if not req("GET",f"watch_cases?id=eq.{i}&owner_id=eq.{o}&select=id").json():raise HTTPException(404,"Recovery case not found")
@app.get("/health")
def health():
 try:u,k=cfg();httpx.get(f"{u}/rest/v1/",headers={"apikey":k},timeout=5).raise_for_status();d="connected"
 except Exception:d="unavailable"
 return {"status":"ok" if d=="connected" else "degraded","database":d,"time":datetime.now(timezone.utc)}
@app.post("/api/v1/cases",status_code=201)
def create(c:C,o=Depends(who)):
 i=str(uuid4());return out(req("POST","watch_cases",{"id":i,"owner_id":o,"case_number":f"LX-{i.replace('-','')[-8:].upper()}","brand":c.brand,"model":c.model,"reference_number":c.reference,"serial_number":c.serial_number,"distinctive_marks":c.distinctive_details,"status":"open"}).json()[0])
@app.get("/api/v1/cases")
def cases(o=Depends(who)):return [out(x) for x in req("GET",f"watch_cases?owner_id=eq.{o}&select=id,case_number,brand,model,reference_number,serial_number,distinctive_marks,status,created_at&order=created_at.desc").json()]
@app.post("/api/v1/cases/{i}/photos",status_code=201)
async def photo(i:str,photo:UploadFile=File(...),o=Depends(who)):
 owned(i,o);t=(photo.content_type or "").lower()
 if t not in {"image/jpeg","image/png","image/heic"}:raise HTTPException(415,"Use a JPG, PNG, or HEIC reference photo")
 b=await photo.read(10485761)
 if not b or len(b)>10485760:raise HTTPException(413,"Each reference photo must be 10 MB or smaller")
 e={"image/jpeg":"jpg","image/png":"png","image/heic":"heic"}[t];p=str(uuid4());path=f"{o}/{i}/{p}.{e}";u,k=cfg()
 try:r=httpx.put(f"{u}/storage/v1/object/case-photos/{path}",headers={"apikey":k,"Content-Type":t},content=b,timeout=30);r.raise_for_status()
 except httpx.HTTPError as x:raise HTTPException(503,"Photo storage is temporarily unavailable") from x
 h=hashlib.sha256(b).hexdigest();req("POST","case_photos",{"id":p,"case_id":i,"owner_id":o,"object_path":path,"original_name":(photo.filename or f"reference.{e}")[:255],"content_type":t,"byte_size":len(b),"sha256":h});return {"id":p,"sha256":h,"retention":"private_evidence"}
@app.post("/api/v1/cases/{i}/scan",status_code=202)
def scan(i:str,o=Depends(who)):owned(i,o);return {"job_id":str(uuid4()),"case_id":i,"status":"queued","access_policy":"approved_sources_only"}
@app.get("/api/v1/sources")
def sources():return [{"key":"official-api-example","status":"not_configured","access":"official_api_only"}]
