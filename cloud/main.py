from fastapi import FastAPI, Request
from datetime import datetime

app = FastAPI(
    title="Safebox Cloud API",
    version="1.0.0"
)

@app.get("/")
def root():
    return {
        "service": "safebox-cloud",
        "status": "online",
        "time": datetime.utcnow().isoformat()
    }

@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "cloud",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/heartbeat")
def heartbeat(payload: dict, request: Request):
    return {
        "received": True,
        "device_id": payload.get("device_id"),
        "ip": request.client.host,
        "time": datetime.utcnow().isoformat()
    }
