import os
import secrets
import threading
import time
from typing import Literal

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
import runner
from log import log
import traceback

load_dotenv()

app = FastAPI(title="Attribute Agent")

_lock = threading.Lock()  # فقط یک اجرا در هر لحظه (سرور با یک worker اجرا می‌شود)
_state = {
    "running": False,
    "job": None,
    "started_at": None,
    "finished_at": None,
    "last_result": None,
}


class RunRequest(BaseModel):
    job: Literal["attributes", "articles"]
    limit: int = Field(5, ge=1, le=20)
    update: bool = False


def require_token(x_agent_token: str = Header(default="")) -> None:
    expected = os.getenv("AGENT_API_TOKEN", "")
    if not expected or not secrets.compare_digest(x_agent_token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="unauthorized")


def _execute(request: RunRequest) -> None:
    log(f"درخواست دریافت شد: job={request.job} limit={request.limit} update={request.update}")
    try:
        result = runner.run_job(request.job, request.limit, request.update)
    except Exception as error:
        traceback.print_exc()
        log(f"❌ job با خطا متوقف شد: {type(error).__name__}: {error}")
        result = {"error": f"{type(error).__name__}: {error}"}
    with _lock:
        _state.update(running=False, finished_at=time.time(), last_result=result)


@app.post("/run", status_code=202, dependencies=[Depends(require_token)])
def run(request: RunRequest, background: BackgroundTasks):
    with _lock:
        if _state["running"]:
            raise HTTPException(status_code=409, detail="agent در حال اجراست")
        _state.update(running=True, job=request.job, started_at=time.time(), finished_at=None)
    background.add_task(_execute, request)
    return {"status": "started"}


@app.get("/status", dependencies=[Depends(require_token)])
def status():
    with _lock:
        return dict(_state)