import os, json
from pydantic_ai import Agent
from core.models import ScheduleDecision

# Bridge Heroku Inference → OpenAI-compatible env
if os.getenv("INFERENCE_KEY") and not os.getenv("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = os.environ["INFERENCE_KEY"]
if os.getenv("INFERENCE_URL") and not os.getenv("OPENAI_BASE_URL"):
    os.environ["OPENAI_BASE_URL"] = os.environ["INFERENCE_URL"]

_raw = os.getenv("INFERENCE_MODEL")
MODEL = (f"openai:{_raw}" if _raw and ":" not in _raw else (_raw or "openai:gpt-4o-mini"))

SYSTEM_PROMPT = (
    "You are Scheduler. Input is a JSON with fields: title, start, end, attendees, time_zone. "
    "Decide one of:\n"
    "• CHECK_FREEBUSY — default; verify availability before booking.\n"
    "• ASK_USER — if required info is missing/ambiguous; ask a short, specific question.\n"
    "• BOOK — only if explicitly instructed *and* time is confirmed free.\n\n"
    "Always return JSON matching ScheduleDecision: {action, args, reason}. "
    "For CHECK_FREEBUSY include args with start, end, time_zone and pass through title/attendees if present. "
    "Do not wrap the JSON in code fences."
)

agent = Agent(MODEL, system_prompt=SYSTEM_PROMPT)

def scheduler_agent(planner_json: str) -> str:
    result = agent.run_sync(planner_json)
    
    # Parse the output which might be wrapped in markdown code blocks
    output = result.output
    
    # Check if the output is wrapped in markdown code blocks
    import re
    json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", output, re.DOTALL)
    if json_match:
        output = json_match.group(1)
    
    # Convert string to dictionary
    try:
        output_dict = json.loads(output)
    except json.JSONDecodeError:
        raise ValueError(f"Failed to parse JSON from LLM output: {output}")
    
    # Validate with Pydantic
    schedule_decision = ScheduleDecision.model_validate(output_dict)
    return json.dumps(schedule_decision.model_dump())
