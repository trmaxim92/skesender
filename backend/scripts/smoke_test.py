import json
import urllib.request

base = "http://127.0.0.1:8000"


def req(method: str, path: str, data: dict | None = None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None if data is None else json.dumps(data).encode("utf-8")
    request = urllib.request.Request(base + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request) as resp:
        return json.loads(resp.read().decode("utf-8"))


login = req("POST", "/api/auth/login", {"email": "admin@order-elite.local", "password": "demo"})
print("login", login["token_type"], bool(login["access_token"]))
me = req("GET", "/api/auth/me", token=login["access_token"])
print("me", me)
channels = req("GET", "/api/channels", token=login["access_token"])
print("channels", json.dumps(channels, ensure_ascii=False, indent=2))
