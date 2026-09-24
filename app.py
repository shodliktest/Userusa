import streamlit as st
from pathlib import Path
from datetime import datetime, timezone
from userbot.client import ensure_worker_started, worker_is_alive
from config.settings import load_settings, missing_secrets
from storage.database import Database

st.set_page_config(page_title="Quiz UserBot", page_icon="🤖", layout="wide")

settings = load_settings()
db = Database()

st.title("🤖 Telegram Quiz UserBot")
st.caption("Mustaqil Streamlit + Telethon + Groq loyihasi")

# --- Sozlamalar: to'liq Streamlit secrets orqali ---
# API ID/HASH, telefon, session string va Groq kaliti hech qachon UI'dan
# kiritilmaydi yoki diskka yozilmaydi — barchasi .streamlit/secrets.toml
# (mahalliy) yoki Streamlit Cloud'ning "Secrets" bo'limidan (production) olinadi.
missing = missing_secrets()
if missing:
    st.error(
        "⚠️ Quyidagi secretlar sozlanmagan: **" + ", ".join(missing) + "**.\n\n"
        "Streamlit Cloud'da: App → Settings → Secrets bo'limiga qo'shing:\n"
        "```\nTELEGRAM_API_ID = \"...\"\nTELEGRAM_API_HASH = \"...\"\n"
        "TELEGRAM_SESSION_STRING = \"...\"\nGROQ_API_KEY = \"...\"\n```\n\n"
        "`TELEGRAM_SESSION_STRING` ni olish uchun `generate_session_string.py` "
        "skriptini mahalliyda bir marta ishga tushiring (OTP so'raydi)."
    )
else:
    # Worker threadni faqat secretlar to'liq bo'lsa avtomatik ishga tushiramiz.
    started = ensure_worker_started()
    if started:
        st.toast("UserBot worker background threadda ishga tushirildi.")

# --- UserBot holati (heartbeat) ---
STALE_AFTER = 45  # soniya — shu vaqtdan ortiq yangilanmasa, offline hisoblanadi

hb = db.get_heartbeat()
if not hb or not hb.get("updated_at"):
    st.warning("⚪ UserBot holati noma'lum — hali birorta ishga tushish yozuvi yo'q.")
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

st.caption(f"Worker thread jonmi (shu Streamlit sessiyasi nuqtai nazaridan): {'✅ ha' if worker_is_alive() else '❌ yo‘q'}")
if st.button("🔄 Holatni yangilash"):
    st.rerun()

with st.sidebar:
    st.header("⚙️ Sozlamalar")
    st.caption("Barcha maxfiy qiymatlar Streamlit **Secrets**dan o'qiladi — bu yerda tahrirlanmaydi.")
    def _mask(v):
        return "•" * 8 + v[-4:] if v and len(v) > 4 else ("— kiritilmagan —" if not v else "•" * len(v))
    st.text(f"API ID: {settings.get('api_id') or '— kiritilmagan —'}")
    st.text(f"API HASH: {_mask(settings.get('api_hash',''))}")
    st.text(f"Session string: {_mask(settings.get('session_string',''))}")
    st.text(f"Groq API Key: {_mask(settings.get('groq_api_key',''))}")
    st.text(f"Groq model: {settings.get('groq_model')}")

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
    st.info("UserBot shu Streamlit ilovasi ochilganda background thread sifatida avtomatik ishga tushadi (yuqoridagi holat ko'rsatkichiga qarang). Community Cloud ilova 'uxlab qolsa' yoki qayta deploy bo'lsa, thread ham qayta ishga tushadi — bu holatda birinchi so'rov sekinroq bo'lishi mumkin.")

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
