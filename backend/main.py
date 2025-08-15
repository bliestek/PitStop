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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# --- Hot-fix middleware ---
# If an old UI calls /api/api/... this rewrites to /api/...
async def _strip_double_api_mw(request, call_next):
    path = request.scope.get("path", "")
    if path.startswith("/api/api/"):
        request.scope["path"] = path.replace("/api/api/", "/api/", 1)
    return await call_next(request)

app.add_middleware(BaseHTTPMiddleware, dispatch=_strip_double_api_mw)

def get_redis():
    try:
        redis_url = os.getenv('REDIS_URL', 'redis://redis:6379')
        r = redis.from_url(redis_url, decode_responses=True)
        r.ping()
        return r
    except Exception as e:
        print(f'Redis connection failed: {e}')
        return None

def get_current_timestamp():
    return datetime.now().isoformat()

# Models
class Vehicle(BaseModel):
    id: Optional[str] = None
    make: str
    model: str
    year: int
    vin: str
    license_plate: str
    color: str
    mileage: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class MaintenanceRecord(BaseModel):
    id: Optional[str] = None
    vehicle_id: Optional[str] = None
    type: str
    description: str
    date: str
    mileage: int
    cost: float
    service_provider: str
    notes: Optional[str] = None
    next_due_date: Optional[str] = None
    next_due_mileage: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class Insurance(BaseModel):
    id: Optional[str] = None
    vehicle_id: str
    provider: str
    policy_number: str
    start_date: str
    end_date: str
    premium: float
    deductible: float
    coverage_type: str
    notes: Optional[str] = None
    created_at: Optional[str] = None

class Registration(BaseModel):
    id: Optional[str] = None
    vehicle_id: str
    registration_number: str
    issue_date: str
    expiry_date: str
    state: str
    fee: float
    notes: Optional[str] = None
    created_at: Optional[str] = None

# Basic endpoints
@app.get('/')
def root():
    return {'message': 'PitStop API is running!', 'status': 'healthy', 'version': '1.0.1'}

@app.get('/health')
def health_check():
    r = get_redis()
    return {
        'status': 'healthy',
        'redis_connected': r is not None,
        'timestamp': get_current_timestamp()
    }

# Compatibility for frontend via nginx
@app.get('/api/health')
def health_check_api():
    r = get_redis()
    return {
        'status': 'healthy',
        'redis_connected': r is not None,
        'timestamp': get_current_timestamp()
    }

@app.get('/api/dashboard/stats')
def get_stats():
    r = get_redis()
    if not r:
        return {
            'total_vehicles': 0,
            'total_maintenance_records': 0,
            'total_insurance_records': 0,
            'total_registration_records': 0,
            'redis_status': 'disconnected'
        }
    try:
        total_vehicles = len(r.keys('vehicle:*'))
        total_maintenance = len(r.keys('maintenance:*'))
        total_insurance = len(r.keys('insurance:*'))
        total_registration = len(r.keys('registration:*'))
        return {
            'total_vehicles': total_vehicles,
            'total_maintenance_records': total_maintenance,
            'total_insurance_records': total_insurance,
            'total_registration_records': total_registration,
            'redis_status': 'connected'
        }
    except Exception as e:
        print(f'Stats error: {e}')
        return {
            'total_vehicles': 0,
            'total_maintenance_records': 0,
            'total_insurance_records': 0,
            'total_registration_records': 0,
            'redis_status': 'error'
        }

# Vehicle endpoints
@app.get('/api/vehicles', response_model=List[Vehicle])
def get_vehicles():
    r = get_redis()
    if not r:
        return []
    try:
        vehicle_keys = r.keys('vehicle:*')
        vehicles = []
        for key in vehicle_keys:
            vehicle_data = r.hgetall(key)
            if vehicle_data:
                if 'year' in vehicle_data: vehicle_data['year'] = int(vehicle_data['year'])
                if 'mileage' in vehicle_data: vehicle_data['mileage'] = int(vehicle_data['mileage'])
                vehicles.append(Vehicle(**vehicle_data))
        return vehicles
    except Exception as e:
        print(f'Get vehicles error: {e}')
        return []

@app.get('/api/vehicles/{vehicle_id}', response_model=Vehicle)
def get_vehicle(vehicle_id: str):
    r = get_redis()
    if not r:
        raise HTTPException(status_code=503, detail='Database unavailable')
    try:
        vehicle_data = r.hgetall(f'vehicle:{vehicle_id}')
        if not vehicle_data:
            raise HTTPException(status_code=404, detail='Vehicle not found')
        if 'year' in vehicle_data: vehicle_data['year'] = int(vehicle_data['year'])
        if 'mileage' in vehicle_data: vehicle_data['mileage'] = int(vehicle_data['mileage'])
        return Vehicle(**vehicle_data)
    except HTTPException:
        raise
    except Exception as e:
        print(f'Get vehicle error: {e}')
        raise HTTPException(status_code=500, detail=str(e))

@app.post('/api/vehicles', response_model=Vehicle)
def create_vehicle(vehicle: Vehicle):
    r = get_redis()
    if not r: raise HTTPException(status_code=503, detail='Database unavailable')
    try:
        vehicle_id = str(uuid.uuid4())
        vehicle.id = vehicle_id
        vehicle.created_at = get_current_timestamp()
        vehicle.updated_at = get_current_timestamp()
        vehicle_dict = vehicle.dict()
        for k, v in vehicle_dict.items():
            if v is not None: vehicle_dict[k] = str(v)
        r.hset(f'vehicle:{vehicle_id}', mapping=vehicle_dict)
        return vehicle
    except Exception as e:
        print(f'Create vehicle error: {e}'); print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.put('/api/vehicles/{vehicle_id}', response_model=Vehicle)
def update_vehicle(vehicle_id: str, vehicle: Vehicle):
    r = get_redis()
    if not r: raise HTTPException(status_code=503, detail='Database unavailable')
    try:
        existing = r.hgetall(f'vehicle:{vehicle_id}')
        if not existing: raise HTTPException(status_code=404, detail='Vehicle not found')
        vehicle.id = vehicle_id
        vehicle.created_at = existing.get('created_at')
        vehicle.updated_at = get_current_timestamp()
        vehicle_dict = vehicle.dict()
        for k, v in vehicle_dict.items():
            if v is not None: vehicle_dict[k] = str(v)
        r.hset(f'vehicle:{vehicle_id}', mapping=vehicle_dict)
        return vehicle
    except HTTPException:
        raise
    except Exception as e:
        print(f'Update vehicle error: {e}')
        raise HTTPException(status_code=500, detail=str(e))

@app.delete('/api/vehicles/{vehicle_id}')
def delete_vehicle(vehicle_id: str):
    r = get_redis()
    if not r: raise HTTPException(status_code=503, detail='Database unavailable')
    try:
        if not r.exists(f'vehicle:{vehicle_id}'):
            raise HTTPException(status_code=404, detail='Vehicle not found')
        for key in list(r.keys(f'maintenance:{vehicle_id}:*')) + list(r.keys(f'insurance:{vehicle_id}:*')) + list(r.keys(f'registration:{vehicle_id}:*')):
            r.delete(key)
        r.delete(f'vehicle:{vehicle_id}')
        return {'message': 'Vehicle deleted successfully'}
    except HTTPException:
        raise
    except Exception as e:
        print(f'Delete vehicle error: {e}')
        raise HTTPException(status_code=500, detail=str(e))

# Maintenance endpoints
@app.get('/api/vehicles/{vehicle_id}/maintenance', response_model=List[MaintenanceRecord])
def get_maintenance_records(vehicle_id: str):
    r = get_redis()
    if not r: return []
    try:
        records = []
        for key in r.keys(f'maintenance:{vehicle_id}:*'):
            d = r.hgetall(key)
            if d:
                if d.get('mileage'): d['mileage'] = int(d['mileage'])
                if d.get('cost'): d['cost'] = float(d['cost'])
                if d.get('next_due_mileage'): d['next_due_mileage'] = int(d['next_due_mileage'])
                records.append(MaintenanceRecord(**d))
        return sorted(records, key=lambda x: x.date, reverse=True)
    except Exception as e:
        print(f'Get maintenance error: {e}')
        return []

@app.get('/api/maintenance/{maintenance_id}')
def get_maintenance_record(maintenance_id: str):
    r = get_redis()
    if not r: raise HTTPException(status_code=503, detail='Database unavailable')
    try:
        for key in r.keys('maintenance:*'):
            if key.endswith(f':{maintenance_id}'):
                d = r.hgetall(key)
                if d:
                    if d.get('mileage'): d['mileage'] = int(d['mileage'])
                    if d.get('cost'): d['cost'] = float(d['cost'])
                    if d.get('next_due_mileage'): d['next_due_mileage'] = int(d['next_due_mileage'])
                    return d
        raise HTTPException(status_code=404, detail='Maintenance record not found')
    except HTTPException:
        raise
    except Exception as e:
        print(f'Get maintenance record error: {e}')
        raise HTTPException(status_code=500, detail=str(e))

@app.post('/api/vehicles/{vehicle_id}/maintenance')
def create_maintenance_record(vehicle_id: str, data: Dict[str, Any]):
    r = get_redis()
    if not r: raise HTTPException(status_code=503, detail='Database unavailable')
    try:
        if not r.exists(f'vehicle:{vehicle_id}'): raise HTTPException(status_code=404, detail='Vehicle not found')
        clean = {
            'vehicle_id': vehicle_id,
            'type': data.get('type',''),
            'description': data.get('description',''),
            'date': data.get('date',''),
            'service_provider': data.get('service_provider','')
        }
        try: clean['mileage'] = int(data.get('mileage',0))
        except: raise HTTPException(status_code=422, detail='Invalid mileage value')
        try: clean['cost'] = float(data.get('cost',0.0))
        except: raise HTTPException(status_code=422, detail='Invalid cost value')
        clean['notes'] = data.get('notes') or None
        clean['next_due_date'] = data.get('next_due_date') or None
        if data.get('next_due_mileage'):
            try: clean['next_due_mileage'] = int(data.get('next_due_mileage'))
            except: clean['next_due_mileage'] = None
        else: clean['next_due_mileage'] = None
        record = MaintenanceRecord(**clean)
        rid = str(uuid.uuid4())
        record.id = rid
        record.created_at = get_current_timestamp()
        record.updated_at = get_current_timestamp()
        d = {k: ('' if v is None else str(v)) for k,v in record.dict().items()}
        r.hset(f'maintenance:{vehicle_id}:{rid}', mapping=d)
        return record.dict()
    except HTTPException:
        raise
    except Exception as e:
        print(f'Create maintenance error: {e}'); print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.put('/api/maintenance/{maintenance_id}')
def update_maintenance_record(maintenance_id: str, data: Dict[str, Any]):
    r = get_redis()
    if not r: raise HTTPException(status_code=503, detail='Database unavailable')
    try:
        maintenance_key = None
        for key in r.keys('maintenance:*'):
            if key.endswith(f':{maintenance_id}'):
                maintenance_key = key; break
        if not maintenance_key: raise HTTPException(status_code=404, detail='Maintenance record not found')
        existing = r.hgetall(maintenance_key)
        if not existing: raise HTTPException(status_code=404, detail='Maintenance record not found')
        clean = {
            'vehicle_id': existing.get('vehicle_id',''),
            'type': data.get('type', existing.get('type','')),
            'description': data.get('description', existing.get('description','')),
            'date': data.get('date', existing.get('date','')),
            'service_provider': data.get('service_provider', existing.get('service_provider','')),
        }
        try: clean['mileage'] = int(data.get('mileage', existing.get('mileage',0)))
        except: raise HTTPException(status_code=422, detail='Invalid mileage value')
        try: clean['cost'] = float(data.get('cost', existing.get('cost',0.0)))
        except: raise HTTPException(status_code=422, detail='Invalid cost value')
        clean['notes'] = data.get('notes') or None
        clean['next_due_date'] = data.get('next_due_date') or None
        if data.get('next_due_mileage'):
            try: clean['next_due_mileage'] = int(data.get('next_due_mileage'))
            except: clean['next_due_mileage'] = None
        else: clean['next_due_mileage'] = None
        record = MaintenanceRecord(**clean)
        record.id = maintenance_id
        record.created_at = existing.get('created_at')
        record.updated_at = get_current_timestamp()
        d = {k: ('' if v is None else str(v)) for k,v in record.dict().items()}
        r.hset(maintenance_key, mapping=d)
        return record.dict()
    except HTTPException:
        raise
    except Exception as e:
        print(f'Update maintenance error: {e}'); print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.delete('/api/maintenance/{maintenance_id}')
def delete_maintenance_record(maintenance_id: str):
    r = get_redis()
    if not r: raise HTTPException(status_code=503, detail='Database unavailable')
    try:
        maintenance_key = None
        for key in r.keys('maintenance:*'):
            if key.endswith(f':{maintenance_id}'):
                maintenance_key = key; break
        if not maintenance_key: raise HTTPException(status_code=404, detail='Maintenance record not found')
        r.delete(maintenance_key)
        return {'message':'Maintenance record deleted successfully'}
    except HTTPException:
        raise
    except Exception as e:
        print(f'Delete maintenance error: {e}')
        raise HTTPException(status_code=500, detail=str(e))

# Insurance endpoints
@app.get('/api/vehicles/{vehicle_id}/insurance', response_model=List[Insurance])
def get_insurance_records(vehicle_id: str):
    r = get_redis()
    if not r: return []
    try:
        records = []
        for key in r.keys(f'insurance:{vehicle_id}:*'):
            d = r.hgetall(key)
            if d:
                if d.get('premium'): d['premium'] = float(d['premium'])
                if d.get('deductible'): d['deductible'] = float(d['deductible'])
                records.append(Insurance(**d))
        return sorted(records, key=lambda x: x.start_date, reverse=True)
    except Exception as e:
        print(f'Get insurance error: {e}')
        return []

@app.post('/api/vehicles/{vehicle_id}/insurance', response_model=Insurance)
def create_insurance_record(vehicle_id: str, record: Insurance):
    r = get_redis()
    if not r: raise HTTPException(status_code=503, detail='Database unavailable')
    try:
        if not r.exists(f'vehicle:{vehicle_id}'): raise HTTPException(status_code=404, detail='Vehicle not found')
        rid = str(uuid.uuid4())
        record.id = rid
        record.vehicle_id = vehicle_id
        record.created_at = get_current_timestamp()
        d = {k: ('' if v is None else str(v)) for k,v in record.dict().items()}
        r.hset(f'insurance:{vehicle_id}:{rid}', mapping=d)
        return record
    except HTTPException:
        raise
    except Exception as e:
        print(f'Create insurance error: {e}')
        raise HTTPException(status_code=500, detail=str(e))

# Registration endpoints
@app.get('/api/vehicles/{vehicle_id}/registration', response_model=List[Registration])
def get_registration_records(vehicle_id: str):
    r = get_redis()
    if not r: return []
    try:
        records = []
        for key in r.keys(f'registration:{vehicle_id}:*'):
            d = r.hgetall(key)
            if d:
                if d.get('fee'): d['fee'] = float(d['fee'])
                records.append(Registration(**d))
        return sorted(records, key=lambda x: x.issue_date, reverse=True)
    except Exception as e:
        print(f'Get registration error: {e}')
        return []

@app.post('/api/vehicles/{vehicle_id}/registration', response_model=Registration)
def create_registration_record(vehicle_id: str, record: Registration):
    r = get_redis()
    if not r: raise HTTPException(status_code=503, detail='Database unavailable')
    try:
        if not r.exists(f'vehicle:{vehicle_id}'): raise HTTPException(status_code=404, detail='Vehicle not found')
        rid = str(uuid.uuid4())
        record.id = rid
        record.vehicle_id = vehicle_id
        record.created_at = get_current_timestamp()
        d = {k: ('' if v is None else str(v)) for k,v in record.dict().items()}
        r.hset(f'registration:{vehicle_id}:{rid}', mapping=d)
        return record
    except HTTPException:
        raise
    except Exception as e:
        print(f'Create registration error: {e}')
        raise HTTPException(status_code=500, detail=str(e))
