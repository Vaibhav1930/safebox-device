from fastapi import FastAPI, Request
from pydantic import BaseModel
from datetime import datetime, timezone
from core.logger import get_logger

log = get_logger("cloud")

app = FastAPI(
    title="Safebox Cloud API",
    version="1.0.0"
)

class HeartbeatPayload(BaseModel):
    device_id: str
    mode: str
    online: bool
    uptime: str
    timestamp: float

@app.get("/")
def root():
    return {
        "service": "safebox-cloud",
        "status": "online",
        "time": datetime.now(timezone.utc).isoformat()
    }

@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "cloud",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post("/heartbeat")
def heartbeat(payload: HeartbeatPayload, request: Request):
    log.info(
        f"heartbeat received device_id={payload.device_id} "
        f"mode={payload.mode} online={payload.online} "
        f"ip={request.client.host}"
    )
    return {
        "received": True,
        "device_id": payload.device_id,
        "mode": payload.mode,
        "ip": request.client.host,
        "time": datetime.now(timezone.utc).isoformat()
    }
