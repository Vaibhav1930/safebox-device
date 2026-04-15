from datetime import datetime, timezone
from pathlib import Path
import hashlib
import tarfile

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.logger import get_logger

log = get_logger("cloud")

app = FastAPI(
    title="Safebox Cloud API",
    version="1.1.0"
)

BASE_DIR = Path(__file__).resolve().parents[1]
BUNDLES_DIR = BASE_DIR / "cloud" / "config_bundles"
LATEST_VERSION_FILE = BUNDLES_DIR / "latest_version.txt"


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


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _bundle_release_dir(version: str) -> Path:
    return BUNDLES_DIR / version


def _bundle_archive_path(version: str) -> Path:
    return BUNDLES_DIR / f"{version}.tar.gz"


def _ensure_bundle_archive(version: str) -> Path:
    release_dir = _bundle_release_dir(version)
    if not release_dir.exists():
        raise FileNotFoundError(f"release dir missing for version={version}")

    archive_path = _bundle_archive_path(version)
    if archive_path.exists():
        return archive_path

    with tarfile.open(archive_path, "w:gz") as tar:
        for item in release_dir.iterdir():
            tar.add(item, arcname=item.name)

    return archive_path


def _get_latest_version() -> str | None:
    if not LATEST_VERSION_FILE.exists():
        return None
    return LATEST_VERSION_FILE.read_text(encoding="utf-8").strip() or None


@app.get("/config/check")
def config_check(
    request: Request,
    device_id: str = Query(...),
    current_version: str = Query("local-bootstrap"),
):
    latest_version = _get_latest_version()

    if latest_version is None:
        return {
            "device_id": device_id,
            "update_available": False,
            "target_version": current_version,
            "bundle_url": None,
            "sha256": None,
        }

    if latest_version == current_version:
        return {
            "device_id": device_id,
            "update_available": False,
            "target_version": current_version,
            "bundle_url": None,
            "sha256": None,
        }

    archive_path = _ensure_bundle_archive(latest_version)
    sha256 = _sha256_file(archive_path)
    base_url = str(request.base_url).rstrip("/")

    return {
        "device_id": device_id,
        "update_available": True,
        "target_version": latest_version,
        "bundle_url": f"{base_url}/config/bundles/{latest_version}",
        "sha256": sha256,
    }


@app.get("/config/bundles/{version}")
def get_config_bundle(version: str):
    archive_path = _bundle_archive_path(version)

    if not archive_path.exists():
        try:
            archive_path = _ensure_bundle_archive(version)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="bundle not found")

    return FileResponse(
        path=str(archive_path),
        media_type="application/gzip",
        filename=f"{version}.tar.gz",
    )
