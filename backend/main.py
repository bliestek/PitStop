from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import redis
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ValidationError
import uuid
import traceback
import json

app = FastAPI(title='PitStop API', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

SECRET_KEY = os.getenv('SECRET_KEY', 'default-secret-key-change-me')

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
    return {'message': 'PitStop API is running!', 'status': 'healthy', 'version': '1.0.0'}

@app.get('/health')
def health_check():
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
                if 'year' in vehicle_data:
                    vehicle_data['year'] = int(vehicle_data['year'])
                if 'mileage' in vehicle_data:
                    vehicle_data['mileage'] = int(vehicle_data['mileage'])
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
        
        if 'year' in vehicle_data:
            vehicle_data['year'] = int(vehicle_data['year'])
        if 'mileage' in vehicle_data:
            vehicle_data['mileage'] = int(vehicle_data['mileage'])
        
        return Vehicle(**vehicle_data)
    except HTTPException:
        raise
    except Exception as e:
        print(f'Get vehicle error: {e}')
        raise HTTPException(status_code=500, detail=str(e))

@app.post('/api/vehicles', response_model=Vehicle)
def create_vehicle(vehicle: Vehicle):
    r = get_redis()
    if not r:
        raise HTTPException(status_code=503, detail='Database unavailable')
    
    try:
        print(f'Creating vehicle: {vehicle}')
        vehicle_id = str(uuid.uuid4())
        vehicle.id = vehicle_id
        vehicle.created_at = get_current_timestamp()
        vehicle.updated_at = get_current_timestamp()
        
        vehicle_dict = vehicle.dict()
        for key, value in vehicle_dict.items():
            if value is not None:
                vehicle_dict[key] = str(value)
        
        r.hset(f'vehicle:{vehicle_id}', mapping=vehicle_dict)
        print(f'Created vehicle: {vehicle_id}')
        return vehicle
    except Exception as e:
        print(f'Create vehicle error: {e}')
        print(f'Traceback: {traceback.format_exc()}')
        raise HTTPException(status_code=500, detail=str(e))

@app.put('/api/vehicles/{vehicle_id}', response_model=Vehicle)
def update_vehicle(vehicle_id: str, vehicle: Vehicle):
    r = get_redis()
    if not r:
        raise HTTPException(status_code=503, detail='Database unavailable')
    
    try:
        existing = r.hgetall(f'vehicle:{vehicle_id}')
        if not existing:
            raise HTTPException(status_code=404, detail='Vehicle not found')
        
        vehicle.id = vehicle_id
        vehicle.created_at = existing.get('created_at')
        vehicle.updated_at = get_current_timestamp()
        
        vehicle_dict = vehicle.dict()
        for key, value in vehicle_dict.items():
            if value is not None:
                vehicle_dict[key] = str(value)
        
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
    if not r:
        raise HTTPException(status_code=503, detail='Database unavailable')
    
    try:
        if not r.exists(f'vehicle:{vehicle_id}'):
            raise HTTPException(status_code=404, detail='Vehicle not found')
        
        maintenance_keys = r.keys(f'maintenance:{vehicle_id}:*')
        insurance_keys = r.keys(f'insurance:{vehicle_id}:*')
        registration_keys = r.keys(f'registration:{vehicle_id}:*')
        
        for key in maintenance_keys + insurance_keys + registration_keys:
            r.delete(key)
        
        r.delete(f'vehicle:{vehicle_id}')
        print(f'Deleted vehicle: {vehicle_id}')
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
    if not r:
        return []
    
    try:
        maintenance_keys = r.keys(f'maintenance:{vehicle_id}:*')
        records = []
        for key in maintenance_keys:
            record_data = r.hgetall(key)
            if record_data:
                if 'mileage' in record_data and record_data['mileage']:
                    record_data['mileage'] = int(record_data['mileage'])
                if 'cost' in record_data and record_data['cost']:
                    record_data['cost'] = float(record_data['cost'])
                if 'next_due_mileage' in record_data and record_data['next_due_mileage']:
                    record_data['next_due_mileage'] = int(record_data['next_due_mileage'])
                records.append(MaintenanceRecord(**record_data))
        return sorted(records, key=lambda x: x.date, reverse=True)
    except Exception as e:
        print(f'Get maintenance error: {e}')
        return []

@app.get('/api/maintenance/{maintenance_id}')
def get_maintenance_record(maintenance_id: str):
    r = get_redis()
    if not r:
        raise HTTPException(status_code=503, detail='Database unavailable')
    
    try:
        all_maintenance_keys = r.keys('maintenance:*')
        for key in all_maintenance_keys:
            if key.endswith(f':{maintenance_id}'):
                record_data = r.hgetall(key)
                if record_data:
                    if 'mileage' in record_data and record_data['mileage']:
                        record_data['mileage'] = int(record_data['mileage'])
                    if 'cost' in record_data and record_data['cost']:
                        record_data['cost'] = float(record_data['cost'])
                    if 'next_due_mileage' in record_data and record_data['next_due_mileage']:
                        record_data['next_due_mileage'] = int(record_data['next_due_mileage'])
                    return record_data
        
        raise HTTPException(status_code=404, detail='Maintenance record not found')
    except HTTPException:
        raise
    except Exception as e:
        print(f'Get maintenance record error: {e}')
        raise HTTPException(status_code=500, detail=str(e))

@app.post('/api/vehicles/{vehicle_id}/maintenance')
def create_maintenance_record(vehicle_id: str, request: Request, data: Dict[str, Any]):
    r = get_redis()
    if not r:
        print('Redis not available')
        raise HTTPException(status_code=503, detail='Database unavailable')
    
    try:
        print(f'=== MAINTENANCE RECORD CREATION ===')
        print(f'Vehicle ID: {vehicle_id}')
        print(f'Raw request data: {data}')
        
        if not r.exists(f'vehicle:{vehicle_id}'):
            print(f'Vehicle {vehicle_id} not found in Redis')
            raise HTTPException(status_code=404, detail='Vehicle not found')
        
        clean_data = {}
        clean_data['vehicle_id'] = vehicle_id
        clean_data['type'] = data.get('type', '')
        clean_data['description'] = data.get('description', '')
        clean_data['date'] = data.get('date', '')
        clean_data['service_provider'] = data.get('service_provider', '')
        
        try:
            clean_data['mileage'] = int(data.get('mileage', 0))
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail='Invalid mileage value')
        
        try:
            clean_data['cost'] = float(data.get('cost', 0.0))
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail='Invalid cost value')
        
        clean_data['notes'] = data.get('notes', '') if data.get('notes') else None
        clean_data['next_due_date'] = data.get('next_due_date', '') if data.get('next_due_date') else None
        
        if data.get('next_due_mileage'):
            try:
                clean_data['next_due_mileage'] = int(data.get('next_due_mileage'))
            except (ValueError, TypeError):
                clean_data['next_due_mileage'] = None
        else:
            clean_data['next_due_mileage'] = None
        
        print(f'Cleaned data: {clean_data}')
        
        try:
            record = MaintenanceRecord(**clean_data)
            print(f'Pydantic validation successful: {record}')
        except ValidationError as ve:
            print(f'Pydantic validation failed: {ve}')
            raise HTTPException(status_code=422, detail=f'Validation error: {ve}')
        
        record_id = str(uuid.uuid4())
        record.id = record_id
        record.vehicle_id = vehicle_id
        record.created_at = get_current_timestamp()
        record.updated_at = get_current_timestamp()
        
        record_dict = record.dict()
        print(f'Record dict for Redis: {record_dict}')
        
        redis_data = {}
        for key, value in record_dict.items():
            if value is not None:
                redis_data[key] = str(value)
            else:
                redis_data[key] = ''
        
        print(f'Redis storage data: {redis_data}')
        
        result = r.hset(f'maintenance:{vehicle_id}:{record_id}', mapping=redis_data)
        print(f'Redis hset result: {result}')
        
        saved_record = r.hgetall(f'maintenance:{vehicle_id}:{record_id}')
        print(f'Verified saved record: {saved_record}')
        
        print(f'✅ Successfully created maintenance record: {record_id} for vehicle: {vehicle_id}')
        
        return record.dict()
        
    except HTTPException:
        raise
    except Exception as e:
        print(f'❌ Create maintenance error: {e}')
        print(f'Traceback: {traceback.format_exc()}')
        raise HTTPException(status_code=500, detail=str(e))

@app.put('/api/maintenance/{maintenance_id}')
def update_maintenance_record(maintenance_id: str, data: Dict[str, Any]):
    r = get_redis()
    if not r:
        print('Redis not available')
        raise HTTPException(status_code=503, detail='Database unavailable')
    
    try:
        print(f'=== MAINTENANCE RECORD UPDATE ===')
        print(f'Maintenance ID: {maintenance_id}')
        print(f'Raw request data: {data}')
        
        maintenance_key = None
        all_maintenance_keys = r.keys('maintenance:*')
        for key in all_maintenance_keys:
            if key.endswith(f':{maintenance_id}'):
                maintenance_key = key
                break
        
        if not maintenance_key:
            print(f'Maintenance record {maintenance_id} not found')
            raise HTTPException(status_code=404, detail='Maintenance record not found')
        
        existing_data = r.hgetall(maintenance_key)
        if not existing_data:
            raise HTTPException(status_code=404, detail='Maintenance record not found')
        
        clean_data = {}
        clean_data['vehicle_id'] = existing_data.get('vehicle_id', '')
        clean_data['type'] = data.get('type', existing_data.get('type', ''))
        clean_data['description'] = data.get('description', existing_data.get('description', ''))
        clean_data['date'] = data.get('date', existing_data.get('date', ''))
        clean_data['service_provider'] = data.get('service_provider', existing_data.get('service_provider', ''))
        
        try:
            clean_data['mileage'] = int(data.get('mileage', existing_data.get('mileage', 0)))
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail='Invalid mileage value')
        
        try:
            clean_data['cost'] = float(data.get('cost', existing_data.get('cost', 0.0)))
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail='Invalid cost value')
        
        clean_data['notes'] = data.get('notes', '') if data.get('notes') else None
        clean_data['next_due_date'] = data.get('next_due_date', '') if data.get('next_due_date') else None
        
        if data.get('next_due_mileage'):
            try:
                clean_data['next_due_mileage'] = int(data.get('next_due_mileage'))
            except (ValueError, TypeError):
                clean_data['next_due_mileage'] = None
        else:
            clean_data['next_due_mileage'] = None
        
        print(f'Cleaned data: {clean_data}')
        
        try:
            record = MaintenanceRecord(**clean_data)
            print(f'Pydantic validation successful: {record}')
        except ValidationError as ve:
            print(f'Pydantic validation failed: {ve}')
            raise HTTPException(status_code=422, detail=f'Validation error: {ve}')
        
        record.id = maintenance_id
        record.created_at = existing_data.get('created_at')
        record.updated_at = get_current_timestamp()
        
        record_dict = record.dict()
        print(f'Record dict for Redis: {record_dict}')
        
        redis_data = {}
        for key, value in record_dict.items():
            if value is not None:
                redis_data[key] = str(value)
            else:
                redis_data[key] = ''
        
        print(f'Redis storage data: {redis_data}')
        
        result = r.hset(maintenance_key, mapping=redis_data)
        print(f'Redis hset result: {result}')
        
        print(f'✅ Successfully updated maintenance record: {maintenance_id}')
        
        return record.dict()
        
    except HTTPException:
        raise
    except Exception as e:
        print(f'❌ Update maintenance error: {e}')
        print(f'Traceback: {traceback.format_exc()}')
        raise HTTPException(status_code=500, detail=str(e))

@app.delete('/api/maintenance/{maintenance_id}')
def delete_maintenance_record(maintenance_id: str):
    r = get_redis()
    if not r:
        raise HTTPException(status_code=503, detail='Database unavailable')
    
    try:
        print(f'=== MAINTENANCE RECORD DELETION ===')
        print(f'Maintenance ID: {maintenance_id}')
        
        maintenance_key = None
        all_maintenance_keys = r.keys('maintenance:*')
        for key in all_maintenance_keys:
            if key.endswith(f':{maintenance_id}'):
                maintenance_key = key
                break
        
        if not maintenance_key:
            print(f'Maintenance record {maintenance_id} not found')
            raise HTTPException(status_code=404, detail='Maintenance record not found')
        
        result = r.delete(maintenance_key)
        print(f'Redis delete result: {result}')
        
        print(f'✅ Successfully deleted maintenance record: {maintenance_id}')
        
        return {'message': 'Maintenance record deleted successfully'}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f'❌ Delete maintenance error: {e}')
        print(f'Traceback: {traceback.format_exc()}')
        raise HTTPException(status_code=500, detail=str(e))

# Insurance endpoints
@app.get('/api/vehicles/{vehicle_id}/insurance', response_model=List[Insurance])
def get_insurance_records(vehicle_id: str):
    r = get_redis()
    if not r:
        return []
    
    try:
        insurance_keys = r.keys(f'insurance:{vehicle_id}:*')
        records = []
        for key in insurance_keys:
            record_data = r.hgetall(key)
            if record_data:
                if 'premium' in record_data and record_data['premium']:
                    record_data['premium'] = float(record_data['premium'])
                if 'deductible' in record_data and record_data['deductible']:
                    record_data['deductible'] = float(record_data['deductible'])
                records.append(Insurance(**record_data))
        return sorted(records, key=lambda x: x.start_date, reverse=True)
    except Exception as e:
        print(f'Get insurance error: {e}')
        return []

@app.post('/api/vehicles/{vehicle_id}/insurance', response_model=Insurance)
def create_insurance_record(vehicle_id: str, record: Insurance):
    r = get_redis()
    if not r:
        raise HTTPException(status_code=503, detail='Database unavailable')
    
    try:
        if not r.exists(f'vehicle:{vehicle_id}'):
            raise HTTPException(status_code=404, detail='Vehicle not found')
        
        record_id = str(uuid.uuid4())
        record.id = record_id
        record.vehicle_id = vehicle_id
        record.created_at = get_current_timestamp()
        
        record_dict = record.dict()
        for key, value in record_dict.items():
            if value is not None:
                record_dict[key] = str(value)
            else:
                record_dict[key] = ''
        
        r.hset(f'insurance:{vehicle_id}:{record_id}', mapping=record_dict)
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
    if not r:
        return []
    
    try:
        registration_keys = r.keys(f'registration:{vehicle_id}:*')
        records = []
        for key in registration_keys:
            record_data = r.hgetall(key)
            if record_data:
                if 'fee' in record_data and record_data['fee']:
                    record_data['fee'] = float(record_data['fee'])
                records.append(Registration(**record_data))
        return sorted(records, key=lambda x: x.issue_date, reverse=True)
    except Exception as e:
        print(f'Get registration error: {e}')
        return []

@app.post('/api/vehicles/{vehicle_id}/registration', response_model=Registration)
def create_registration_record(vehicle_id: str, record: Registration):
    r = get_redis()
    if not r:
        raise HTTPException(status_code=503, detail='Database unavailable')
    
    try:
        if not r.exists(f'vehicle:{vehicle_id}'):
            raise HTTPException(status_code=404, detail='Vehicle not found')
        
        record_id = str(uuid.uuid4())
        record.id = record_id
        record.vehicle_id = vehicle_id
        record.created_at = get_current_timestamp()
        
        record_dict = record.dict()
        for key, value in record_dict.items():
            if value is not None:
                record_dict[key] = str(value)
            else:
                record_dict[key] = ''
        
        r.hset(f'registration:{vehicle_id}:{record_id}', mapping=record_dict)
        return record
    except HTTPException:
        raise
    except Exception as e:
        print(f'Create registration error: {e}')
        raise HTTPException(status_code=500, detail=str(e))
