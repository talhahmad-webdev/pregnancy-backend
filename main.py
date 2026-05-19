"""
=============================================================
  IoT Pregnancy Monitor — FastAPI + MongoDB Backend
  Sensors: AD8232 (HR), DS18B20 (Temp), SW420 (Kicks)
=============================================================
  Run: python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
=============================================================
"""
import os 
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime, timedelta

app = FastAPI(title="Pregnancy Monitor API", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



# ─────────────────────────────────────────────
#  MONGODB
# ─────────────────────────────────────────────
import os
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URL)
db           = client["pregnancy_monitor"]
users_col    = db["users"]
patients_col = db["patients"]
readings_col = db["readings"]

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
def fix_id(doc):
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc

def fix_ids(docs):
    return [fix_id(d) for d in docs]

# ─────────────────────────────────────────────
#  THRESHOLDS
# ─────────────────────────────────────────────
ESP32_API_KEY = "ESP32_SECRET_KEY_2024"

THRESHOLDS = {
    "hr_min":      60,
    "hr_max":     100,
    "temp_max":   38.0,
    "temp_min":   36.0,
    "kicks_min":  10,
}

def get_alerts(hr, temp):
    alerts = []
    if hr and hr > 0:
        if hr < THRESHOLDS["hr_min"]:
            alerts.append(f"Mother HR bohot kam: {hr:.0f} bpm")
        elif hr > THRESHOLDS["hr_max"]:
            alerts.append(f"Mother HR bohot zyada: {hr:.0f} bpm")
    if temp and temp > 0:
        if temp > THRESHOLDS["temp_max"]:
            alerts.append(f"Temperature high: {temp:.1f}C")
        elif temp < THRESHOLDS["temp_min"]:
            alerts.append(f"Temperature low: {temp:.1f}C")
    return alerts

# ─────────────────────────────────────────────
#  MODELS
# ─────────────────────────────────────────────
class LoginData(BaseModel):
    email:    str
    password: str

class RegisterPatient(BaseModel):
    name:        str
    email:       str
    password:    str
    age:         int
    weight:      float
    height:      float
    week:        int
    blood_group: str

class SensorData(BaseModel):
    patient_id:  str
    mother_hr:   float = 0    # AD8232
    mother_temp: float = 0    # DS18B20
    kicks_count: int   = 0    # SW420
    api_key:     str

# ─────────────────────────────────────────────
#  STARTUP — Sample data
# ─────────────────────────────────────────────
@app.on_event("startup")
def startup():
    if users_col.count_documents({}) > 0:
        print("Database ready.")
        return

    print("Sample data insert ho raha hai...")

    pat_user_id = users_col.insert_one({
        "name": "Fatima Malik", "email": "patient@test.com",
        "password": "patient123", "role": "patient",
        "age": 28, "weight": 65.0, "height": 162.0,
        "week": 32, "blood_group": "B+",
        "created_at": datetime.now(),
    }).inserted_id

    pat_id = patients_col.insert_one({
        "user_id": str(pat_user_id),
        "name": "Fatima Malik",
        "age": 28, "week": 32,
        "created_at": datetime.now(),
    }).inserted_id

    samples = [
        {"mother_hr": 82, "mother_temp": 37.1, "kicks_count": 3, "min": 25},
        {"mother_hr": 79, "mother_temp": 37.0, "kicks_count": 5, "min": 20},
        {"mother_hr": 85, "mother_temp": 37.2, "kicks_count": 2, "min": 15},
        {"mother_hr": 88, "mother_temp": 37.4, "kicks_count": 6, "min": 10},
        {"mother_hr": 95, "mother_temp": 38.2, "kicks_count": 1, "min":  5},
        {"mother_hr": 84, "mother_temp": 37.1, "kicks_count": 4, "min":  0},
    ]

    for s in samples:
        mins = s.pop("min")
        alerts = get_alerts(s["mother_hr"], s["mother_temp"])
        readings_col.insert_one({
            "patient_id":  str(pat_id),
            "alert_flags": ", ".join(alerts) if alerts else None,
            "recorded_at": datetime.now() - timedelta(minutes=mins),
            **s
        })

    print("Sample data ready! Login: patient@test.com / patient123")

# ─────────────────────────────────────────────
#  PAGE ROUTES
# ─────────────────────────────────────────────
@app.get("/")
def root():
    return {"message": "Pregnancy Monitor API Running!"}

# ─────────────────────────────────────────────
#  AUTH
# ─────────────────────────────────────────────
@app.post("/api/login")
def login(data: LoginData):
    user = users_col.find_one({"email": data.email, "password": data.password})
    if not user:
        raise HTTPException(401, "Email ya password galat hai")

    patient_id = None
    p = patients_col.find_one({"user_id": str(user["_id"])})
    if p:
        patient_id = str(p["_id"])

    return {
        "id":          str(user["_id"]),
        "name":        user["name"],
        "role":        user.get("role", "patient"),
        "email":       user["email"],
        "age":         user.get("age"),
        "weight":      user.get("weight"),
        "height":      user.get("height"),
        "week":        user.get("week"),
        "blood_group": user.get("blood_group"),
        "patient_id":  patient_id,
    }

@app.post("/api/register/patient")
def register_patient(data: RegisterPatient):
    if users_col.find_one({"email": data.email}):
        raise HTTPException(400, "Yeh email already registered hai")

    uid = users_col.insert_one({
        "name": data.name, "email": data.email,
        "password": data.password, "role": "patient",
        "age": data.age, "weight": data.weight,
        "height": data.height, "week": data.week,
        "blood_group": data.blood_group,
        "created_at": datetime.now(),
    }).inserted_id

    patients_col.insert_one({
        "user_id": str(uid), "name": data.name,
        "age": data.age, "week": data.week,
        "created_at": datetime.now(),
    })
    return {"message": "Registration successful! Ab login karo."}

# ─────────────────────────────────────────────
#  SENSOR DATA (ESP32 yahan POST karta hai)
# ─────────────────────────────────────────────
@app.post("/api/sensor-data")
def receive_data(data: SensorData):
    if data.api_key != ESP32_API_KEY:
        raise HTTPException(403, "Invalid API key")

    alerts = get_alerts(data.mother_hr, data.mother_temp)

    readings_col.insert_one({
        "patient_id":  data.patient_id,
        "mother_hr":   round(data.mother_hr, 1),
        "mother_temp": round(data.mother_temp, 1),
        "kicks_count": data.kicks_count,
        "alert_flags": ", ".join(alerts) if alerts else None,
        "recorded_at": datetime.now(),
    })

    return {
        "status":  "ok",
        "alerts":  alerts,
        "message": f"{len(alerts)} alert(s)" if alerts else "All vitals normal",
    }

# ─────────────────────────────────────────────
#  DASHBOARD APIs
# ─────────────────────────────────────────────
@app.get("/api/latest/{patient_id}")
def get_latest(patient_id: str):
    r = readings_col.find_one(
        {"patient_id": patient_id},
        sort=[("recorded_at", -1)]
    )
    if not r:
        raise HTTPException(404, "Koi data nahi mila")
    r["recorded_at"] = str(r["recorded_at"])
    return fix_id(r)

@app.get("/api/history/{patient_id}")
def get_history(patient_id: str, limit: int = 30):
    rows = list(readings_col.find(
        {"patient_id": patient_id},
        sort=[("recorded_at", -1)],
        limit=limit
    ))
    for r in rows:
        r["recorded_at"] = str(r["recorded_at"])
    return fix_ids(list(reversed(rows)))

@app.get("/api/alerts/{patient_id}")
def get_patient_alerts(patient_id: str):
    rows = list(readings_col.find(
        {"patient_id": patient_id, "alert_flags": {"$ne": None}},
        sort=[("recorded_at", -1)],
        limit=20
    ))
    for r in rows:
        r["recorded_at"] = str(r["recorded_at"])
    return fix_ids(rows)

@app.get("/api/kicks/{patient_id}")
def get_kicks(patient_id: str):
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    rows  = list(readings_col.find({
        "patient_id":  patient_id,
        "recorded_at": {"$gte": today}
    }))
    total = sum(r.get("kicks_count", 0) for r in rows)
    last  = readings_col.find_one(
        {"patient_id": patient_id},
        sort=[("recorded_at", -1)]
    )
    return {
        "total_kicks_today": total,
        "last_kicks": last.get("kicks_count", 0) if last else 0,
    }
