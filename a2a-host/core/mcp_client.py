import os, requests

MCP_CAL_URL = os.environ["MCP_CAL_URL"].rstrip("/")
TOOLS_KEY   = os.environ["TOOLS_KEY"]

def call_tool(name: str, arguments: dict) -> dict:
    url = f"{MCP_CAL_URL}/tools/call"
    headers = {
        "Content-Type": "application/json",
        "X-Tool-Key": TOOLS_KEY
    }
    payload = {"name": name, "arguments": arguments}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data.get("content", data)
    except requests.exceptions.RequestException as e:
        print(f"Error calling tool {name}: {e}")
        print(f"URL: {url}")
        print(f"Payload: {payload}")
        # Return a default response instead of raising an exception
        if name == "calendar.freebusy":
            return {"free": False, "busy": [{"start": arguments["start"], "end": arguments["end"]}]}
        else:
            raise  # Re-raise for other tools
