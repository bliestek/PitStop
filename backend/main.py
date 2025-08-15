from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import redis
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ValidationError
import uuid
import traceback

app = FastAPI(title='PitStop API', version='1.0.1')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# Hot-fix: rewrite /api/api/... -> /api/...
async def _strip_double_api_mw(request, call_next):
    path = request.scope.get("path","")
    if path.startswith("/api/api/"):
        request.scope["path"] = path.replace("/api/api/","/api/",1)
    return await call_next(request)

app.add_middleware(BaseHTTPMiddleware, dispatch=_strip_double_api_mw)

def get_redis():
    try:
        redis_url = os.getenv('REDIS_URL', 'redis://redis:6379')
        r = redis.from_url(redis_url, decode_responses=True)
        r.ping()
        return r
    except Exception as e:
        print(f"Redis connection failed: {e}")
        return None

def now(): return datetime.now().isoformat()

class Vehicle(BaseModel):
    id: Optional[str]=None
    make: str; model: str; year: int; vin: str; license_plate: str
    color: str; mileage: int
    created_at: Optional[str]=None; updated_at: Optional[str]=None

class MaintenanceRecord(BaseModel):
    id: Optional[str]=None; vehicle_id: Optional[str]=None
    type: str; description: str; date: str
    mileage: int; cost: float; service_provider: str
    notes: Optional[str]=None; next_due_date: Optional[str]=None; next_due_mileage: Optional[int]=None
    created_at: Optional[str]=None; updated_at: Optional[str]=None

class Insurance(BaseModel):
    id: Optional[str]=None; vehicle_id: str; provider: str; policy_number: str
    start_date: str; end_date: str; premium: float; deductible: float
    coverage_type: str; notes: Optional[str]=None; created_at: Optional[str]=None

class Registration(BaseModel):
    id: Optional[str]=None; vehicle_id: str; registration_number: str
    issue_date: str; expiry_date: str; state: str; fee: float
    notes: Optional[str]=None; created_at: Optional[str]=None

@app.get('/')
def root(): return {'message':'PitStop API is running!','status':'healthy','version':'1.0.1'}

@app.get('/health')
@app.get('/api/health')
def health(): r=get_redis(); return {'status':'healthy','redis_connected': r is not None,'timestamp': now()}

@app.get('/api/dashboard/stats')
def stats():
    r=get_redis()
    if not r: return {'total_vehicles':0,'total_maintenance_records':0,'total_insurance_records':0,'total_registration_records':0,'redis_status':'disconnected'}
    try:
        return {
            'total_vehicles': len(r.keys('vehicle:*')),
            'total_maintenance_records': len(r.keys('maintenance:*')),
            'total_insurance_records': len(r.keys('insurance:*')),
            'total_registration_records': len(r.keys('registration:*')),
            'redis_status':'connected'
        }
    except Exception as e:
        print('Stats error', e); return {'total_vehicles':0,'total_maintenance_records':0,'total_insurance_records':0,'total_registration_records':0,'redis_status':'error'}

@app.get('/api/vehicles', response_model=List[Vehicle])
def get_vehicles():
    r=get_redis(); 
    if not r: return []
    out=[]
    for key in r.keys('vehicle:*'):
        d=r.hgetall(key)
        if d:
            if 'year' in d: d['year']=int(d['year'])
            if 'mileage' in d: d['mileage']=int(d['mileage'])
            out.append(Vehicle(**d))
    return out

@app.get('/api/vehicles/{vehicle_id}', response_model=Vehicle)
def get_vehicle(vehicle_id:str):
    r=get_redis()
    if not r: raise HTTPException(503,'Database unavailable')
    d=r.hgetall(f'vehicle:{vehicle_id}')
    if not d: raise HTTPException(404,'Vehicle not found')
    if 'year' in d: d['year']=int(d['year'])
    if 'mileage' in d: d['mileage']=int(d['mileage'])
    return Vehicle(**d)

@app.post('/api/vehicles', response_model=Vehicle)
def create_vehicle(v:Vehicle):
    r=get_redis()
    if not r: raise HTTPException(503,'Database unavailable')
    vid=str(uuid.uuid4()); v.id=vid; v.created_at=now(); v.updated_at=now()
    m=v.dict(); m={k:str(v) for k,v in m.items() if v is not None}
    r.hset(f'vehicle:{vid}', mapping=m); return v

@app.put('/api/vehicles/{vehicle_id}', response_model=Vehicle)
def update_vehicle(vehicle_id:str, v:Vehicle):
    r=get_redis()
    if not r: raise HTTPException(503,'Database unavailable')
    ex=r.hgetall(f'vehicle:{vehicle_id}')
    if not ex: raise HTTPException(404,'Vehicle not found')
    v.id=vehicle_id; v.created_at=ex.get('created_at'); v.updated_at=now()
    m=v.dict(); m={k:str(v) for k,v in m.items() if v is not None}
    r.hset(f'vehicle:{vehicle_id}', mapping=m); return v

@app.delete('/api/vehicles/{vehicle_id}')
def delete_vehicle(vehicle_id:str):
    r=get_redis()
    if not r: raise HTTPException(503,'Database unavailable')
    if not r.exists(f'vehicle:{vehicle_id}'): raise HTTPException(404,'Vehicle not found')
    for key in list(r.keys(f'maintenance:{vehicle_id}:*')) + list(r.keys(f'insurance:{vehicle_id}:*')) + list(r.keys(f'registration:{vehicle_id}:*')):
        r.delete(key)
    r.delete(f'vehicle:{vehicle_id}'); return {'message':'Vehicle deleted successfully'}

@app.get('/api/vehicles/{vehicle_id}/maintenance', response_model=List[MaintenanceRecord])
def get_maint(vehicle_id:str):
    r=get_redis(); 
    if not r: return []
    rows=[]
    for key in r.keys(f'maintenance:{vehicle_id}:*'):
        d=r.hgetall(key)
        if d:
            if d.get('mileage'): d['mileage']=int(d['mileage'])
            if d.get('cost'): d['cost']=float(d['cost'])
            if d.get('next_due_mileage'): d['next_due_mileage']=int(d['next_due_mileage'])
            rows.append(MaintenanceRecord(**d))
    return sorted(rows, key=lambda x: x.date, reverse=True)

@app.get('/api/maintenance/{maintenance_id}')
def get_maint_one(maintenance_id:str):
    r=get_redis()
    if not r: raise HTTPException(503,'Database unavailable')
    for key in r.keys('maintenance:*'):
        if key.endswith(f':{maintenance_id}'):
            d=r.hgetall(key)
            if d:
                if d.get('mileage'): d['mileage']=int(d['mileage'])
                if d.get('cost'): d['cost']=float(d['cost'])
                if d.get('next_due_mileage'): d['next_due_mileage']=int(d['next_due_mileage'])
                return d
    raise HTTPException(404,'Maintenance record not found')

@app.post('/api/vehicles/{vehicle_id}/maintenance')
def create_maint(vehicle_id:str, data:Dict[str,Any]):
    r=get_redis()
    if not r: raise HTTPException(503,'Database unavailable')
    if not r.exists(f'vehicle:{vehicle_id}'): raise HTTPException(404,'Vehicle not found')
    try: mileage=int(data.get('mileage',0))
    except: raise HTTPException(422,'Invalid mileage value')
    try: cost=float(data.get('cost',0.0))
    except: raise HTTPException(422,'Invalid cost value')
    clean=dict(vehicle_id=vehicle_id, type=data.get('type',''), description=data.get('description',''),
               date=data.get('date',''), service_provider=data.get('service_provider',''),
               mileage=mileage, cost=cost, notes=data.get('notes') or None,
               next_due_date=data.get('next_due_date') or None,
               next_due_mileage=int(data['next_due_mileage']) if data.get('next_due_mileage') else None)
    rec=MaintenanceRecord(**clean); rid=str(uuid.uuid4()); rec.id=rid; rec.created_at=now(); rec.updated_at=now()
    d={k: ('' if v is None else str(v)) for k,v in rec.dict().items()}
    r.hset(f'maintenance:{vehicle_id}:{rid}', mapping=d); return rec.dict()

@app.put('/api/maintenance/{maintenance_id}')
def update_maint(maintenance_id:str, data:Dict[str,Any]):
    r=get_redis()
    if not r: raise HTTPException(503,'Database unavailable')
    mkey=None
    for key in r.keys('maintenance:*'):
        if key.endswith(f':{maintenance_id}'): mkey=key; break
    if not mkey: raise HTTPException(404,'Maintenance record not found')
    ex=r.hgetall(mkey); 
    try: mileage=int(data.get('mileage', ex.get('mileage',0)))
    except: raise HTTPException(422,'Invalid mileage value')
    try: cost=float(data.get('cost', ex.get('cost',0.0)))
    except: raise HTTPException(422,'Invalid cost value')
    clean=dict(vehicle_id=ex.get('vehicle_id',''), type=data.get('type',ex.get('type','')),
               description=data.get('description',ex.get('description','')), date=data.get('date',ex.get('date','')),
               service_provider=data.get('service_provider',ex.get('service_provider','')),
               mileage=mileage, cost=cost, notes=data.get('notes') or None,
               next_due_date=data.get('next_due_date') or None,
               next_due_mileage=int(data['next_due_mileage']) if data.get('next_due_mileage') else None)
    rec=MaintenanceRecord(**clean); rec.id=maintenance_id; rec.created_at=ex.get('created_at'); rec.updated_at=now()
    d={k: ('' if v is None else str(v)) for k,v in rec.dict().items()}
    r.hset(mkey, mapping=d); return rec.dict()

@app.delete('/api/maintenance/{maintenance_id}')
def delete_maint(maintenance_id:str):
    r=get_redis()
    if not r: raise HTTPException(503,'Database unavailable')
    mkey=None
    for key in r.keys('maintenance:*'):
        if key.endswith(f':{maintenance_id}'): mkey=key; break
    if not mkey: raise HTTPException(404,'Maintenance record not found')
    r.delete(mkey); return {'message':'Maintenance record deleted successfully'}

@app.get('/api/vehicles/{vehicle_id}/insurance', response_model=List[Insurance])
def get_ins(vehicle_id:str):
    r=get_redis()
    if not r: return []
    rows=[]
    for key in r.keys(f'insurance:{vehicle_id}:*'):
        d=r.hgetall(key)
        if d:
            if d.get('premium'): d['premium']=float(d['premium'])
            if d.get('deductible'): d['deductible']=float(d['deductible'])
            rows.append(Insurance(**d))
    return sorted(rows, key=lambda x: x.start_date, reverse=True)

@app.post('/api/vehicles/{vehicle_id}/insurance', response_model=Insurance)
def create_ins(vehicle_id:str, rec:Insurance):
    r=get_redis()
    if not r: raise HTTPException(503,'Database unavailable')
    if not r.exists(f'vehicle:{vehicle_id}'): raise HTTPException(404,'Vehicle not found')
    rid=str(uuid.uuid4()); rec.id=rid; rec.vehicle_id=vehicle_id; rec.created_at=now()
    d={k: ('' if v is None else str(v)) for k,v in rec.dict().items()}
    r.hset(f'insurance:{vehicle_id}:{rid}', mapping=d); return rec

@app.get('/api/vehicles/{vehicle_id}/registration', response_model=List[Registration])
def get_reg(vehicle_id:str):
    r=get_redis()
    if not r: return []
    rows=[]
    for key in r.keys(f'registration:{vehicle_id}:*'):
        d=r.hgetall(key)
        if d:
            if d.get('fee'): d['fee']=float(d['fee'])
            rows.append(Registration(**d))
    return sorted(rows, key=lambda x: x.issue_date, reverse=True)

@app.post('/api/vehicles/{vehicle_id}/registration', response_model=Registration)
def create_reg(vehicle_id:str, rec:Registration):
    r=get_redis()
    if not r: raise HTTPException(503,'Database unavailable')
    if not r.exists(f'vehicle:{vehicle_id}'): raise HTTPException(404,'Vehicle not found')
    rid=str(uuid.uuid4()); rec.id=rid; rec.vehicle_id=vehicle_id; rec.created_at=now()
    d={k: ('' if v is None else str(v)) for k,v in rec.dict().items()}
    r.hset(f'registration:{vehicle_id}:{rid}', mapping=d); return rec
