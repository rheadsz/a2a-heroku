import os, requests

BASE_URL = os.environ["BASE_URL"].rstrip("/")
API_KEY = os.environ["API_KEY"]
MODEL = os.environ["MODEL_NAME"]

def chat(messages):
    """
    messages: list of dicts like [{"role":"user", "content": "hi"}]
    returns: model text (string)

    """
    url = f"{BASE_URL}/chat/completions"
    payload = {"model": MODEL, "messages": messages}
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    r = requests.post(url, json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]