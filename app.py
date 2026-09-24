import streamlit as st
from pathlib import Path
from config.settings import load_settings,missing_secrets
from storage.database import Database
from userbot.worker import ensure_worker_started,get_worker
from utils.exporter import export
st.set_page_config(page_title='Telegram Quiz UserBot Pro',page_icon='🤖',layout='wide')
s=load_settings();db=Database();miss=missing_secrets();st.title('🤖 Telegram Quiz UserBot Pro')
if miss:st.error('Secrets yetishmayapti: '+', '.join(miss))
else:ensure_worker_started()
w=get_worker();hb=db.heartbeat();st.success('🟢 UserBot ishlayapti') if hb and hb['status']=='running' else st.warning('🟡 UserBot holati: '+str(hb))
t=st.tabs(['🤖 Operator','📡 Scanner','📤 Export','📊 Statistika','📜 Log'])
with t[0]:
 p=Path('config/agent_prompt.txt');x=st.text_area('Operator prompt',p.read_text(encoding='utf-8'),height=500)
 if st.button('💾 Promptni saqlash'):p.write_text(x,encoding='utf-8');st.success('Saqlandi')
 st.caption(f'Groq keylar: {len(s.groq_keys)} | 429 bo‘lsa key avtomatik almashtiriladi')
with t[1]:
 st.subheader('📡 Scanner')
 src=st.text_input('Kanal/Guruh');a,b,c=st.columns(3);target=a.number_input('Manbadan nechta?',1,100000,100);pf=b.number_input('Har TXT faylda nechta?',1,1000,20);out=c.text_input('Kerakli Quiz kanal/guruh (ixtiyoriy)')
 if st.button('➕ Saqlash'):db.add_source(src,target,pf,out) if src else None
 rows=db.sources();st.dataframe(rows,use_container_width=True)
 a,b=st.columns(2)
 if a.button('▶️ SCANNERNI BOSHLASH',disabled=w.scanning):
  if w.running:w.start_scan(rows)
  else:st.error('UserBot ulanmagan')
 if b.button('⏹ SCANNERNI TO‘XTATISH',disabled=not w.scanning):w.stop_scan()
 st.write('Holat:', '🟢 ishlayapti' if w.scanning else '⚪ to‘xtagan');st.json(w.stats)
with t[2]:
 srcf=st.text_input('Manba filter (ixtiyoriy)');n=st.number_input('Har faylda testlar',1,1000,20);name=st.text_input('Fayl nomi/mavzu','quiz_test')
 if st.button('📄 TXT tayyorlash'):
  qs=db.quizzes(srcf or None)
  for p in export(qs,n,name):st.download_button('⬇️ '+p.name,p.read_bytes(),file_name=p.name,key=p.name)
with t[3]:
 for label,tbl in [('Quizlar','quizzes'),('Fingerprintlar','fingerprints'),('Buyurtmalar','orders')]:st.metric(label,db.count(tbl))
with t[4]:st.text_area('Log',db.logs(),height=550)
