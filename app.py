import streamlit as st
from pathlib import Path
from datetime import datetime, timezone
from userbot.client import UserBotController
from config.settings import load_settings, save_settings
from storage.database import Database

st.set_page_config(page_title="Quiz UserBot", page_icon="🤖", layout="wide")

settings = load_settings()
db = Database()

st.title("🤖 Telegram Quiz UserBot")
st.caption("Mustaqil Streamlit + Telethon + Groq loyihasi")

# --- UserBot holati (heartbeat) ---
STALE_AFTER = 45  # soniya — shu vaqtdan ortiq yangilanmasa, offline hisoblanadi

hb = db.get_heartbeat()
if not hb or not hb.get("updated_at"):
    st.warning("⚪ UserBot holati noma'lum — hali birorta ishga tushish yozuvi yo'q. Worker alohida ishga tushirilganmi, tekshiring.")
else:
    updated = datetime.fromisoformat(hb["updated_at"]).replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - updated).total_seconds()
    status = hb.get("status", "")
    detail = hb.get("detail", "")

    if age > STALE_AFTER:
        st.error(f"🔴 UserBot offline ko'rinadi — oxirgi signal {int(age)} soniya oldin ({status}).")
    elif status == "running":
        label = f" ({detail})" if detail else ""
        st.success(f"🟢 UserBot ishlayapti{label} — {int(age)} soniya oldin tasdiqlangan.")
    elif status == "reconnecting":
        st.warning(f"🟡 UserBot qayta ulanmoqda — {int(age)} soniya oldin.")
    elif status == "error":
        st.error(f"🔴 UserBot xatolik bilan to'xtagan: {detail}")
    elif status == "stopped":
        st.error("🔴 UserBot to'xtatilgan.")
    else:
        st.info(f"Holat: {status} — {int(age)} soniya oldin.")

    if st.button("🔄 Holatni yangilash"):
        st.rerun()

with st.sidebar:
    st.header("⚙️ Sozlamalar")
    api_id = st.text_input("Telegram API ID", value=str(settings.get("api_id","")))
    api_hash = st.text_input("Telegram API HASH", value=settings.get("api_hash",""), type="password")
    phone = st.text_input("Telefon raqam", value=settings.get("phone",""))
    groq_key = st.text_input("Groq API Key", value=settings.get("groq_api_key",""), type="password")
    model = st.text_input("Groq model", value=settings.get("groq_model","openai/gpt-oss-120b"))
    if st.button("💾 Saqlash", use_container_width=True):
        settings.update({"api_id":api_id, "api_hash":api_hash, "phone":phone,
                         "groq_api_key":groq_key, "groq_model":model})
        save_settings(settings)
        st.success("Saqlandi.")

tabs=st.tabs(["🤖 Operator","📡 Scanner","📤 Export","📊 Statistika","📜 Log"])

with tabs[0]:
    st.subheader("AI operator prompt")
    prompt_path=Path("config/agent_prompt.txt")
    prompt=prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    new_prompt=st.text_area("Prompt", prompt, height=420)
    if st.button("Promptni saqlash"):
        prompt_path.write_text(new_prompt, encoding="utf-8")
        st.success("Prompt saqlandi.")

    st.divider()
    st.info("UserBotni ishga tushirish uchun Streamlit worker rejimi yoki alohida process/hostingdan foydalaning. Community Cloud doimiy worker sifatida kafolatlanmaydi.")

with tabs[1]:
    st.subheader("📡 Manbalar")
    source=st.text_input("Kanal/guruh username yoki ID")
    col1,col2=st.columns(2)
    with col1:
        limit=st.number_input("Scan limiti (0 = mavjud tarix)", min_value=0, value=1000, step=100)
    with col2:
        mode=st.selectbox("Rejim",["Faqat yangi xabarlar","Tanlangan limit","Butun tarix"])
    if st.button("➕ Manba qo‘shish"):
        if source:
            db.add_source(source)
            st.success("Manba qo‘shildi.")
    st.write("**Saqlangan manbalar:**")
    st.dataframe(db.list_sources(), use_container_width=True)

with tabs[2]:
    st.subheader("📤 Quiz eksport")
    fmt=st.selectbox("Format",["TXT","JSON"])
    if st.button("Eksport qilish"):
        path=db.export_quizzes(fmt.lower())
        if path:
            with open(path,"rb") as f:
                st.download_button("⬇️ Faylni olish", f, file_name=Path(path).name)
        else:
            st.warning("Eksport qilinadigan quiz yo‘q.")

with tabs[3]:
    st.subheader("📊 Statistika")
    st.metric("Saqlangan quizlar", db.count_quizzes())
    st.metric("Fingerprintlar", db.count_fingerprints())
    st.metric("Buyurtmalar", db.count_orders())

with tabs[4]:
    st.subheader("📜 Log")
    st.text_area("Log", db.get_logs(), height=500)
