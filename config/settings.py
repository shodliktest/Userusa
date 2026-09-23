import json
from pathlib import Path

PATH=Path("config/settings.json")
DEFAULT={
    "api_id":"",
    "api_hash":"",
    "phone":"",
    "session_name":"quiz_userbot",
    "groq_api_key":"",
    "groq_model":"openai/gpt-oss-120b",
    "auto_reply":True
}

def load_settings():
    if PATH.exists():
        try:
            data=json.loads(PATH.read_text(encoding="utf-8"))
            return {**DEFAULT, **data}
        except Exception:
            pass
    return DEFAULT.copy()

def save_settings(data):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
