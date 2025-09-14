# a2a-host/app.py
import os, re, json, hmac, hashlib, base64, time
from typing import List, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# LLM + Tools + Agents
from core import llm
from core.mcp_client import call_tool
from core.scheduler_agent_pyd import scheduler_agent  # keep existing Scheduler
# NEW: PydanticAI Planner
from core.planner_agent import plan_sync
from core.models import MeetingPlan

app = FastAPI()

# =========================
# Models
# =========================
class ChatIn(BaseModel):
    message: str

class ChatOut(BaseModel):
    reply: str

class CreateEventIn(BaseModel):
    title: str
    start: str
    end: str
    attendees: List[str]
    time_zone: str
    conference: str = "google_meet"
    send_updates: str = "all"

class A2ADryIn(BaseModel):
    prompt: str

class A2APlanIn(BaseModel):
    prompt: str
    time_zone: str = "America/Los_Angeles"

class A2AConfirmIn(BaseModel):
    token: str
    send_updates: str = "all"  # allow override

# =========================
# Helpers
# =========================
def _parse_json_from_md(s: str):
    """
    Accepts raw model text. If it contains ```json ... ``` fences,
    strips them and returns a parsed dict. Raises if still not JSON.
    (Used for Scheduler output; Planner now returns a typed object.)
    """
    s = s.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.S | re.I)
    if m:
        s = m.group(1).strip()
    return json.loads(s)

SIGNING_KEY = os.environ.get("SIGNING_KEY")  # set on Heroku

def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

def _b64u_dec(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)

def _make_token(payload: dict, ttl_seconds: int = 900) -> str:
    if not SIGNING_KEY:
        raise HTTPException(status_code=500, detail="SIGNING_KEY not set")
    body = payload.copy()
    body["exp"] = int(time.time()) + ttl_seconds
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    sig = hmac.new(SIGNING_KEY.encode(), body_bytes, hashlib.sha256).digest()
    return _b64u(body_bytes) + "." + _b64u(sig)

def _verify_token(token: str) -> dict:
    if not SIGNING_KEY:
        raise HTTPException(status_code=500, detail="SIGNING_KEY not set")
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body = _b64u_dec(body_b64)
        sig = _b64u_dec(sig_b64)
        good = hmac.compare_digest(
            sig, hmac.new(SIGNING_KEY.encode(), body, hashlib.sha256).digest()
        )
        if not good:
            raise ValueError("bad signature")
        obj = json.loads(body)
        if obj.get("exp", 0) < int(time.time()):
            raise ValueError("expired")
        return obj
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

# =========================
# Routes
# =========================
@app.get("/health")
def health():
    return {"ok": True}

@app.post("/chat", response_model=ChatOut)
def chat_endpoint(body: ChatIn):
    try:
        msgs = [
            {"role": "system", "content": "Be concise. One short sentence. Do not repeat the user text."},
            {"role": "user", "content": body.message}
        ]
        reply_text = llm.chat(msgs)
        return {"reply": reply_text}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")

@app.post("/tool/create-event")
def tool_create_event(body: CreateEventIn):
    try:
        result = call_tool("calendar.create_event", body.dict())
        return {"tool_result": result}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Tool error: {e}")

@app.post("/a2a/dry-run")
def a2a_dry_run(body: A2ADryIn):
    """
    Agent 1 (Planner) → JSON
    Agent 2 (Scheduler) ← Planner JSON → action JSON
    Returns both raw and parsed forms.
    """
    # Agent 1 (PydanticAI): get a validated MeetingPlan
    planner_parsed = plan_sync(body.prompt)
    # Provide a pretty "raw" string for visibility (keeps old shape)
    planner_raw = json.dumps(planner_parsed, indent=2)

    # Agent 2 (feed parsed JSON)
    scheduler_input = json.dumps(planner_parsed)
    scheduler_raw = scheduler_agent(scheduler_input)
    try:
        scheduler_parsed = _parse_json_from_md(scheduler_raw)
    except Exception:
        scheduler_parsed = None

    return {
        "planner": {"raw": planner_raw, "parsed": planner_parsed},
        "scheduler": {"raw": scheduler_raw, "parsed": scheduler_parsed}
    }

@app.post("/a2a/plan")
def a2a_plan(body: A2APlanIn):
    """
    Planner → Scheduler → free/busy.
    If free, returns a signed confirm_token (no server memory).
    """
    # Agent 1 (PydanticAI): validated MeetingPlan object as dict
    planner_obj = plan_sync(body.prompt)

    # default time_zone if missing
    planner_obj.setdefault("time_zone", body.time_zone)

    # Agent 2: Scheduler → action + args
    scheduler_raw = scheduler_agent(json.dumps(planner_obj))
    try:
        scheduler_obj = _parse_json_from_md(scheduler_raw)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Scheduler returned non-JSON: {scheduler_raw}")

    action = scheduler_obj.get("action")
    args = scheduler_obj.get("args") or {}
    reason = scheduler_obj.get("reason", "")

    # Fill sensible defaults
    args.setdefault("time_zone", body.time_zone)
    args.setdefault("send_updates", "all")
    args.setdefault("conference", "google_meet")

    if action == "ASK_USER":
        return {
            "status": "needs_input",
            "question": reason,
            "planner": planner_obj,
            "scheduler": scheduler_obj,
        }

    if action not in ("CHECK_FREEBUSY", "BOOK"):
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    # Always check free/busy before booking
    fb = call_tool("calendar.freebusy", {
        "start": args["start"],
        "end": args["end"],
        "time_zone": args["time_zone"]
    })

    result = {
        "status": "free" if fb.get("free") else "busy",
        "availability": fb,
        "proposed": args,
        "reason": reason
    }

    # If free, return a signed token (stateless)
    if fb.get("free"):
        token = _make_token(args, ttl_seconds=900)  # 15 minutes
        result["confirm_token"] = token
        result["next"] = 'POST /a2a/confirm with {"token":"<confirm_token>"}'
    else:
        result["next"] = "Pick a different time or modify the prompt."

    return result

@app.post("/a2a/confirm")
def a2a_confirm(body: A2AConfirmIn):
    """
    Verify token → create event via tool server → return booking JSON.
    """
    # decode signed token to recover proposed args
    args = _verify_token(body.token)

    # apply overrides/defaults
    args["send_updates"] = body.send_updates
    args.setdefault("conference", "google_meet")

    try:
        result = call_tool("calendar.create_event", args)
        return {"booked": result, "args": args}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Booking failed: {e}")
