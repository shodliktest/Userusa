import streamlit as st

DEFAULT={
    "session_name":"quiz_userbot",
    "groq_model":"openai/gpt-oss-120b",
    "auto_reply":True
}

def load_settings():
    """Barcha maxfiy sozlamalar Streamlit secrets orqali olinadi
    (.streamlit/secrets.toml mahalliyda, yoki Streamlit Cloud'ning
    'Secrets' bo'limi production'da). Hech qanday API kalit yoki
    sessiya diskka yozilmaydi."""
    s = st.secrets if hasattr(st, "secrets") else {}
    return {
        "api_id": s.get("TELEGRAM_API_ID", ""),
        "api_hash": s.get("TELEGRAM_API_HASH", ""),
        "phone": s.get("TELEGRAM_PHONE", ""),
        "session_string": s.get("TELEGRAM_SESSION_STRING", ""),
        "session_name": DEFAULT["session_name"],
        "groq_api_key": s.get("GROQ_API_KEY", ""),
        "groq_model": DEFAULT["groq_model"],
        "auto_reply": DEFAULT["auto_reply"],
    }

def missing_secrets():
    """UI uchun: qaysi majburiy secretlar hali kiritilmagan."""
    s = load_settings()
    required = {
        "TELEGRAM_API_ID": s["api_id"],
        "TELEGRAM_API_HASH": s["api_hash"],
        "TELEGRAM_SESSION_STRING": s["session_string"],
        "GROQ_API_KEY": s["groq_api_key"],
    }
    return [k for k, v in required.items() if not v]
