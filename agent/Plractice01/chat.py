import configparser
import json
import urllib.request

cfg = configparser.ConfigParser()
cfg.read("config.ini", encoding="utf-8-sig")
API_KEY = cfg["llm"]["api_key"]
BASE_URL = cfg["llm"]["base_url"]
MODEL = cfg["llm"]["model"]

URL = BASE_URL.rstrip("/") + "/chat/completions"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}
messages = [{"role": "system", "content": "You are a helpful assistant."}]


def stream(prompt):
    messages.append({"role": "user", "content": prompt})
    data = json.dumps(
        {"model": MODEL, "messages": messages, "stream": True}
    ).encode("utf-8")
    req = urllib.request.Request(URL, data=data, headers=HEADERS, method="POST")
    full = []
    with urllib.request.urlopen(req) as resp:
        for line in resp:
            line = line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
            try:
                delta = json.loads(chunk)["choices"][0]["delta"].get("content", "")
            except KeyError:
                continue
            if delta:
                full.append(delta)
                print(delta, end="", flush=True)
    print()
    messages.append({"role": "assistant", "content": "".join(full)})


if __name__ == "__main__":
    print("chat started, Ctrl+C to exit")
    try:
        while True:
            prompt = input("you> ")
            if not prompt.strip():
                continue
            print("ai> ", end="", flush=True)
            stream(prompt)
    except KeyboardInterrupt:
        print("\nbye")