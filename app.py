import streamlit as st
from pathlib import Path

from config.settings import load_settings, missing_secrets
from storage.database import Database
from userbot.worker import ensure_worker_started, get_worker
from utils.exporter import export

st.set_page_config(page_title='Telegram Quiz UserBot Pro', page_icon='🤖', layout='wide')
s = load_settings()
db = Database()
miss = missing_secrets()
st.title('🤖 Telegram Quiz UserBot Pro')

if miss:
    st.error('Secrets yetishmayapti: ' + ', '.join(miss))
else:
    ensure_worker_started()

w = get_worker()
hb = db.heartbeat()
if w.running:
    st.success('🟢 UserBot Telegramga ulangan')
elif hb and hb.get('status') == 'error':
    st.error('🔴 UserBot xatosi: ' + str(hb.get('detail', '')))
else:
    st.warning('🟡 UserBot ulanmoqda...')

t = st.tabs(['🤖 Operator', '📡 Scanner', '📤 Export', '📊 Statistika', '📜 Log'])

with t[0]:
    p = Path('config/agent_prompt.txt')
    x = st.text_area('Operator prompt', p.read_text(encoding='utf-8'), height=500)
    if st.button('💾 Promptni saqlash'):
        p.write_text(x, encoding='utf-8')
        st.success('Saqlandi')
    st.caption(f'Groq keylar: {len(s.groq_keys)} | 429 bo‘lsa key avtomatik almashtiriladi')

with t[1]:
    st.subheader('📡 Scanner')
    src = st.text_input('Kanal/Guruh', placeholder='@kanal yoki -100...')
    c1, c2, c3 = st.columns(3)
    target = c1.number_input('Manbadan nechta quiz?', min_value=1, max_value=100000, value=100)
    pf = c2.number_input('Har TXT faylda nechta?', min_value=1, max_value=1000, value=20)
    out = c3.text_input('Quiz yuboriladigan kanal/guruh (ixtiyoriy)', placeholder='@mening_kanalim')
    publish = st.checkbox('Topilgan quizlarni native Telegram Quiz sifatida yuborish', value=False)

    if st.button('➕ Manbani saqlash', type='secondary'):
        if not src.strip():
            st.warning('Avval kanal/guruhni kiriting.')
        else:
            db.add_source(src.strip(), target, pf, out.strip(), publish)
            st.success('Manba saqlandi. Endi Scanner-ni boshlashingiz mumkin.')

    rows = db.sources()
    if rows:
        display_rows = [{
            'Manba': r['source'], 'Yoqilgan': bool(r.get('enabled', 1)),
            'Maqsad': r['target_count'], 'TXT': r['per_file'],
            'Output': r.get('output_chat', ''), 'Publish': bool(r.get('publish_enabled', 0))
        } for r in rows]
        st.dataframe(display_rows, width='stretch')
    else:
        st.info('Hali scanner manbasi qo‘shilmagan.')

    c1, c2, c3 = st.columns(3)
    if c1.button('▶️ SCANNERNI BOSHLASH', disabled=w.scanning):
        ok = w.start_scan(rows)
        if ok:
            st.success('Scanner ishga tushirildi.')
        else:
            st.error(w.stats.get('error') or 'Scanner ishga tushmadi.')
    if c2.button('⏹ SCANNERNI TO‘XTATISH', disabled=not w.scanning):
        if w.stop_scan():
            st.warning('To‘xtatish buyrug‘i berildi. Joriy Telegram so‘rovi tugagach to‘xtaydi.')
    if c3.button('🔄 HOLATNI YANGILASH'):
        st.rerun()

    status = w.stats.get('status', 'stopped')
    labels = {'starting': '🟡 boshlanmoqda', 'scanning': '🟢 ishlayapti', 'stopping': '🟠 to‘xtatilmoqda', 'stopped': '⚪ to‘xtagan', 'completed': '🔵 tugagan', 'flood_wait': '🟠 Telegram FloodWait', 'error': '🔴 xato'}
    st.write('**Scanner holati:**', labels.get(status, status))
    if w.stats.get('source'):
        st.write('**Manba:**', w.stats['source'])
    m1, m2, m3, m4 = st.columns(4)
    m1.metric('Tekshirilgan', w.stats.get('checked', 0))
    m2.metric('Topilgan', w.stats.get('found', 0))
    m3.metric('O‘tkazib yuborilgan', w.stats.get('skipped', 0))
    m4.metric('Yuborilgan', w.stats.get('published', 0))
    if w.stats.get('error'):
        st.error(w.stats['error'])
    st.caption('Statusni real vaqtda ko‘rish uchun “🔄 HOLATNI YANGILASH” tugmasini bosing.')

with t[2]:
    srcf = st.text_input('Manba filter (ixtiyoriy)')
    n = st.number_input('Har faylda testlar', 1, 1000, 20)
    name = st.text_input('Fayl nomi/mavzu', 'quiz_test')
    if st.button('📄 TXT tayyorlash'):
        qs = db.quizzes(srcf.strip() or None)
        if not qs:
            st.warning('Export qilish uchun hali saqlangan quiz yo‘q. Avval Scanner orqali quizlarni yig‘ing.')
        else:
            for p in export(qs, n, name):
                st.download_button('⬇️ ' + p.name, p.read_bytes(), file_name=p.name, mime='text/plain', key='dl_' + p.name)

with t[3]:
    for label, tbl in [('Quizlar', 'quizzes'), ('Fingerprintlar', 'fingerprints'), ('Buyurtmalar', 'orders')]:
        st.metric(label, db.count(tbl))

with t[4]:
    st.text_area('Log', db.logs(), height=550)
