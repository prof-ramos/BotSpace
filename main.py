import os
import subprocess
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse

from bot_app import run_bot

WORK_DIR = Path(os.getenv("WORK_DIR", "/data/work"))
LOCK_PATH = WORK_DIR / "reindex.lock"
LOG_PATH = WORK_DIR / "reindex.log"

REINDEX_EVERY_SECONDS = int(os.getenv("REINDEX_EVERY_SECONDS", "0"))
REINDEX_API_TOKEN = os.getenv("REINDEX_API_TOKEN")

app = FastAPI()


def ensure_dirs():
    WORK_DIR.mkdir(parents=True, exist_ok=True)


def lock_acquire() -> bool:
    ensure_dirs()
    if LOCK_PATH.exists():
        age = time.time() - LOCK_PATH.stat().st_mtime
        if age < 2 * 60 * 60:
            return False
        try:
            LOCK_PATH.unlink()
        except Exception:
            return False
    LOCK_PATH.write_text(str(time.time()), encoding="utf-8")
    return True


def lock_release():
    try:
        if LOCK_PATH.exists():
            LOCK_PATH.unlink()
    except Exception:
        pass


def run_ingest() -> str:
    if not lock_acquire():
        return "LOCKED: reindex ja em execucao."
    try:
        ensure_dirs()
        p = subprocess.run(["python", "ingest_job.py"], capture_output=True, text=True)
        out = f"EXIT={p.returncode}\n\nSTDOUT:\n{p.stdout}\n\nSTDERR:\n{p.stderr}\n"
        LOG_PATH.write_text(out[-200_000:], encoding="utf-8")
        return out
    finally:
        lock_release()


def scheduler_loop():
    if REINDEX_EVERY_SECONDS <= 0:
        print("[SCHEDULER] disabled (REINDEX_EVERY_SECONDS=0)")
        return

    while True:
        print("[SCHEDULER] running reindex...")
        print(run_ingest()[:2000])
        time.sleep(REINDEX_EVERY_SECONDS)


@app.get("/health", response_class=PlainTextResponse)
def health():
    return "ok"


@app.get("/logs", response_class=PlainTextResponse)
def logs():
    if LOG_PATH.exists():
        return LOG_PATH.read_text(encoding="utf-8", errors="ignore")
    return "no logs yet"


@app.post("/reindex", response_class=PlainTextResponse)
def reindex(request: Request, authorization: str | None = Header(default=None)):
    if REINDEX_API_TOKEN:
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing Authorization header")

        expected = f"Bearer {REINDEX_API_TOKEN}"
        if authorization != expected:
            raise HTTPException(status_code=403, detail="Invalid token")
        return run_ingest()

    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(
            status_code=403,
            detail="External /reindex disabled when REINDEX_API_TOKEN is not set",
        )
    return run_ingest()


def run_api():
    uvicorn.run(app, host="0.0.0.0", port=7860, log_level="info")


def main():
    threading.Thread(target=run_api, daemon=True).start()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    run_bot()


if __name__ == "__main__":
    main()
