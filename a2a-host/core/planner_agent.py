import os
from pydantic_ai import Agent
from core.models import MeetingPlan
import datetime

# Bridge Heroku Inference → OpenAI-compatible env
if os.getenv("INFERENCE_KEY") and not os.getenv("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = os.environ["INFERENCE_KEY"]
if os.getenv("INFERENCE_URL") and not os.getenv("OPENAI_BASE_URL"):
    os.environ["OPENAI_BASE_URL"] = os.environ["INFERENCE_URL"]

_raw = os.getenv("INFERENCE_MODEL")
MODEL = (f"openai:{_raw}" if _raw and ":" not in _raw else (_raw or "openai:gpt-4o-mini"))

# Get current date for context
current_date = datetime.datetime.now().strftime("%Y-%m-%d")

SYSTEM_PROMPT = (
    f"You are Planner. Extract meeting details from a natural-language request and "
    f"produce a clean, unambiguous plan.\n\n"
    f"Today's date is {current_date}.\n\n"
    f"Rules:\n"
    f"• Return ONLY the fields of MeetingPlan (title, start, end, attendees, time_zone).\n"
    f"• Convert relative dates like 'tomorrow' into explicit ISO 8601 datetimes with offset.\n"
    f"• Keep attendees as email strings (array).\n"
    f"• If no time zone is given, default to 'America/Los_Angeles'.\n"
)

agent = Agent(MODEL, system_prompt=SYSTEM_PROMPT)

def plan_sync(prompt: str) -> dict:
    # Use a more compatible approach to handle the result
    result = agent.run_sync(prompt)
    
    # Parse the output which might be wrapped in markdown code blocks
    output = result.output
    
    # Check if the output is wrapped in markdown code blocks
    import re
    json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", output, re.DOTALL)
    if json_match:
        output = json_match.group(1)
    
    # Convert string to dictionary
    import json
    try:
        output_dict = json.loads(output)
    except json.JSONDecodeError:
        raise ValueError(f"Failed to parse JSON from LLM output: {output}")
    
    # Validate with Pydantic
    meeting_plan = MeetingPlan.model_validate(output_dict)
    return meeting_plan.model_dump()
