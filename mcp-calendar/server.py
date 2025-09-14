import os, requests
from fastapi import FastAPI
from fastapi import Header, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
from urllib.parse import urlencode
import uuid

TOOLS_KEY = os.environ.get("TOOLS_KEY")

app = FastAPI()

GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
OAUTH_REDIRECT_URI = os.environ["OAUTH_REDIRECT_URI"]

# Minimal scopes for our use
GOOGLE_SCOPES = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly"

GOOGLE_REFRESH_TOKEN = os.environ["GOOGLE_REFRESH_TOKEN"]

def _get_access_token():
    data = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": GOOGLE_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }
    r = requests.post("https://oauth2.googleapis.com/token", data=data, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]

class CallBody(BaseModel):
    name: str
    arguments: Dict[str, Any]

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/oauth/start")
def oauth_start():
    """
    Redirects you to Google's consent screen.
    After you allow access, Google will send you back to /oauth/callback with ?code=...
    """
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_type": "code",
        "access_type": "offline",                # ensures we get a refresh_token
        "include_granted_scopes": "true",
        "prompt": "consent",                     # force consent so refresh_token is issued
        "scope": GOOGLE_SCOPES,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return RedirectResponse(url)

@app.get("/oauth/callback")
def oauth_callback(code: str):
    """
    Exchanges the ?code for tokens. Copy the refresh_token and set it in Heroku.
    """
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    r = requests.post("https://oauth2.googleapis.com/token", data=data, timeout=30)
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"Token exchange failed: {r.text}")

    token = r.json()
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        # Most common cause: consent not forced or you already granted the app.
        # Remove prior access at https://myaccount.google.com/permissions and try again,
        # or ensure prompt=consent & access_type=offline are set.
        raise HTTPException(status_code=400, detail="No refresh_token returned. Revoke old access and try again.")

    # Return it so you can set it as a config var (don’t share this with anyone).
    return {
        "message": "Copy refresh_token and set as GOOGLE_REFRESH_TOKEN in Heroku config.",
        "refresh_token": refresh_token
    }

@app.get("/tools/list")
def tools_list():
    return{
        "tools": [
            {
                "name": "calendar.freebusy",
                "description": "Check if a time window is free",
                "input_schema":{
                    "type":"object",
                    "properties":{
                        "start":{"type": "string"}, #ISO datetime
                        "end":{"type": "string"}, #ISO datetime
                        "time_zone":{"type": "string"} #America/LA

                    },
                    "required": ["start","end","time_zone"]
                }

            },
            
            {
                "name":"calendar.create_event",
                "description":"Create a calendar event",
                "input_schema":{
                    "type":"object",
                    "properties":{
                        "title":{"type": "string"},
                        "start":{"type": "string"},
                        "end":{"type":"string"},
                        "attendees":{
                            "type": "array",
                            "items":{"type": "string"} #email addresses

                        },
                        "time_zone": {"type": "string"},
                        "conference": {"type": "string"}, #google meet
                        "send_updates": {"type": "string"} #all | none
                    },
                    "required": ["title","start", "end", "time_zone"]
                }
            }
        ]
    }

@app.post("/tools/call")
def tools_call(body: CallBody, x_tool_key: Optional[str]=Header(None)):
    #simple auth: require the shared secret header
    if TOOLS_KEY and x_tool_key != TOOLS_KEY:
        raise HTTPException(status_code=401, detail="Bad tool key")

    #handle the tool by name
    if body.name == "calendar.freebusy":
        args = body.arguments
        access_token = _get_access_token()
        headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",

        }

        payload = {
        "timeMin": args["start"],           # RFC3339 (your input string is fine)
        "timeMax": args["end"],
        "timeZone": args["time_zone"],
        "items": [{"id": "primary"}],       # check your primary calendar
    }
        r = requests.post("https://www.googleapis.com/calendar/v3/freeBusy",
                      headers=headers, json=payload, timeout=30)
        if not r.ok:
            raise HTTPException(status_code=502, detail=f"FreeBusy failed: {r.text}")
        data = r.json()
        busy = data.get("calendars", {}).get("primary", {}).get("busy", [])
        return {"content": {"free": len(busy) == 0, "busy": busy}}

       
       

    elif body.name == "calendar.create_event":
        args = body.arguments
        access_token = _get_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        attendees = [{"email": e} for e in args.get("attendees",[])]

        request_id = "req-" + uuid.uuid4().hex[:12]
        conference = args.get("conference", "google_meet")
        conference_data = None

        if conference == "google_meet":
            conference_data = {
                "createRequest":{
                    "requestId": request_id,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"}
                }
            }

        event = {
            "summary": args["title"],
            "start": {"dateTime": args["start"], "timeZone": args["time_zone"]},
            "end":   {"dateTime": args["end"],   "timeZone": args["time_zone"]},
            "attendees": attendees
        }
        if conference_data:
            event["conferenceData"] = conference_data

        # send email invites
        send_updates = args.get("send_updates", "all")
        url = (
            "https://www.googleapis.com/calendar/v3/calendars/primary/events"
            f"?conferenceDataVersion=1&sendUpdates={send_updates}"
        )

        r = requests.post(url, headers=headers, json=event, timeout=30)
        if not r.ok:
            raise HTTPException(status_code=502, detail=f"Events.insert failed: {r.text}")

        data = r.json()

        # try to extract a Google Meet link
        meet_link = None
        cd = data.get("conferenceData", {}) or {}
        for ep in cd.get("entryPoints", []) or []:
            if ep.get("entryPointType") == "video" and ep.get("uri"):
                meet_link = ep["uri"]
                break
        meet_link = meet_link or data.get("hangoutLink")  # fallback

        return {
            "content": {
                "event_id": data.get("id"),
                "html_link": data.get("htmlLink"),
                "meet_link": meet_link,
                "attendees_saved": data.get("attendees", []),
                "attendees_sent": attendees
            }
        }

    #unknown tool
    raise HTTPException(status_code=400, detail=f"Unknown tool: {body.name}")
