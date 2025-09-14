# a2a-host/core/agents.py
from .llm import chat

def planner_agent(user_prompt: str) -> str:
    """
    Return STRICT JSON only:
    {
      "title": string,
      "start": string,      // ISO 8601 e.g. 2025-09-13T16:00:00-07:00
      "end": string,        // ISO 8601
      "attendees": [string],// emails
      "time_zone": string
    }
    """
    messages = [
        {"role": "system", "content":
         "You are the Planner. Extract meeting details from the user. "
         "Return STRICT JSON only (no extra text) with fields: "
         "title, start, end, attendees[], time_zone."},
        {"role": "user", "content": user_prompt}
    ]
    return chat(messages)

def scheduler_agent(planner_json: str) -> str:
    """
    Return STRICT JSON only (no code fences), shape:
    {
      "action": "CHECK_FREEBUSY" | "BOOK" | "ASK_USER",
      "args": { "title": string, "start": string, "end": string,
                "attendees": [string], "time_zone": string,
                "send_updates": "all" },
      "reason": string
    }
    Rules:
    - Always populate args by COPYING fields from the planner JSON.
    - If any required field is missing/invalid → action="ASK_USER" (include reason).
    - If fields look complete → action="CHECK_FREEBUSY".
    - Default send_updates to "all".
    - Respond with STRICT JSON ONLY (no prose, no code fences).
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are the Scheduler. You receive a planner JSON and must decide the next step. "
                "Validate required fields: title, start, end, attendees (array of emails), time_zone. "
                "ALWAYS return STRICT JSON ONLY (no code fences), with keys action, args, reason. "
                "ALWAYS fill args by copying the provided fields and adding send_updates='all'. "
                "If anything is missing or malformed → action='ASK_USER' with a short reason. "
                "If everything looks present → action='CHECK_FREEBUSY' with a short reason."
            ),
        },
        {
            "role": "user",
            "content": f"Planner JSON:\n{planner_json}\nToday is 2025-09-12.",
        },
    ]
    return chat(messages)

