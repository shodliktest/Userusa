from dataclasses import dataclass
import streamlit as st
@dataclass
class Settings:
    api_id:int; api_hash:str; phone:str; session_string:str; groq_model:str; groq_keys:list
def sec(k,d=None):
    try:return st.secrets.get(k,d)
    except Exception:return d
def load_settings():
    keys=[]
    for i in range(10):
        k='GROQ_API_KEY' if i==0 else f'GROQ_API_KEY{i}'
        v=sec(k,'')
        if v and str(v).strip():keys.append(str(v).strip())
    return Settings(int(sec('TELEGRAM_API_ID',0) or 0),str(sec('TELEGRAM_API_HASH','') or ''),str(sec('TELEGRAM_PHONE','') or ''),str(sec('TELEGRAM_SESSION_STRING','') or ''),str(sec('GROQ_MODEL','openai/gpt-oss-120b')),keys)
def missing_secrets():
    s=load_settings(); return ([x for x,v in [('TELEGRAM_API_ID',s.api_id),('TELEGRAM_API_HASH',s.api_hash),('TELEGRAM_SESSION_STRING',s.session_string),('GROQ_API_KEY',s.groq_keys)] if not v])
