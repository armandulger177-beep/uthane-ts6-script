from flask import Flask, render_template_string, request, redirect, url_for, session, Response, flash, get_flashed_messages
from functools import wraps
import paramiko
import socket
import time
import logging
import subprocess
import datetime
import threading
import glob
import os
import uuid
import urllib.request
import urllib.parse
import json
import re

# --- UTHANE MUTLAK SSH YAMASI ---
import paramiko, time
if getattr(paramiko.SSHClient, '_ts6_ultimate_patched', False) is False:
    _orig_invoke = paramiko.SSHClient.invoke_shell
    def _patched_invoke(self, *args, **kwargs):
        shell = _orig_invoke(self, *args, **kwargs)
        _orig_send = shell.send
        def _new_send(data):
            res = _orig_send(data)
            check = data.decode('utf-8', 'ignore') if isinstance(data, bytes) else str(data)
            if "use 1" in check:
                time.sleep(0.9)
                while shell.recv_ready(): shell.recv(65536)
            return res
        shell.send = _new_send
        return shell
    paramiko.SSHClient.invoke_shell = _patched_invoke
    paramiko.SSHClient._ts6_ultimate_patched = True
# --------------------------------


# --- AYARLAR VE TELEGRAM ---
PANEL_USER, PANEL_PASS = "admin", "UthanePanel123"
TS3_HOST, TS3_PORT = "127.0.0.1", 10022
TS3_USER, TS3_PASS = "serveradmin", ""
TS3_VOICE_PORT = "9987" 
SYSTEMCTL_PATH = "/bin/systemctl" 
LOG_DIR = "/root/teamspeak-server_linux_amd64/logs/"

TELEGRAM_BOT_TOKEN = "" 
TELEGRAM_CHAT_ID = ""

LOG_FILE = 'panel_islemler.log'
SESSION_LOG_FILE = 'baglanti_gecmisi.log'
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s - %(message)s')

PM_HISTORY = {} # {clid: {"name": "Nick", "msgs": [{"from": "Sen/Nick", "msg": "mesaj", "time": "hh:mm"}]}}
KNOWN_CLIENTS = {}
HUNTED_USERS = set()
USER_STATES = {} 
FIRST_RUN = True
CHAT_SOCKET = None

app = Flask(__name__)
app.secret_key = "uthane_ts6_v43_whatsapp_key"

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_tr_time():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=3)

def get_theme_vars():
    t = session.get('theme', 'indigo')
    if t == 'red': return 'red', 'rose'
    return 'indigo', 'indigo'

# --- HTML ŞABLONLARI ---
LOGIN_PAGE = """
<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8"><title>Uthane TS6 - Komuta</title><script src="https://cdn.tailwindcss.com"></script>
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap');
    body { background-color: #0b1120; color: #f8fafc; font-family: 'Outfit', sans-serif; }
</style>
</head><body class="flex items-center justify-center h-screen bg-[#0b1120]">
    <div class="bg-[#151e32] p-10 rounded-2xl shadow-[0_15px_40px_rgba(0,0,0,0.4)] border border-[#1e293b] w-full max-w-sm">
        <div class="text-center mb-8">
            <img src="https://i.hizliresim.com/s20hok7.png" alt="Uthane Logo" class="w-36 mx-auto mb-4 drop-shadow-[0_5px_15px_rgba(0,0,0,0.5)]">
            <h2 class="text-2xl font-extrabold text-white tracking-wide uppercase">Yönetim Paneli</h2>
            <p class="text-slate-400 text-sm mt-1 font-medium">Siber Komuta Ağına Bağlan</p>
        </div>
        {% if error %}<div class="bg-rose-500/10 border border-rose-500/50 text-rose-300 text-sm p-4 rounded-xl mb-6 text-center font-semibold">{{ error }}</div>{% endif %}
        <form action="/login" method="POST" class="space-y-5">
            <input type="text" name="username" placeholder="Kullanıcı Adı" required class="w-full bg-[#0f172a] border border-[#334155] px-5 py-4 rounded-xl text-white font-medium focus:outline-none focus:border-{{ p_color }}-500 transition-colors shadow-inner">
            <input type="password" name="password" placeholder="Şifre" required class="w-full bg-[#0f172a] border border-[#334155] px-5 py-4 rounded-xl text-white font-medium focus:outline-none focus:border-{{ p_color }}-500 transition-colors shadow-inner">
            <button type="submit" class="w-full bg-{{ p_color }}-600 hover:bg-{{ p_color }}-500 text-white font-bold py-4 rounded-xl transition-all mt-2 shadow-[0_5px_15px_rgba(79,70,229,0.3)] tracking-widest uppercase">Bağlantıyı Kur</button>
        </form>
    </div>
</body></html>
"""

BASE_LAYOUT = """
<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8"><title>Uthane TS6 Panel</title><script src="https://cdn.tailwindcss.com"></script>
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700;800&display=swap');
    body { background-color: #0b1120; color: #f1f5f9; font-family: 'Outfit', sans-serif; }
    ::-webkit-scrollbar { width: 6px; } ::-webkit-scrollbar-track { background: transparent; } ::-webkit-scrollbar-thumb { background: #334155; border-radius: 10px; }
    #context-menu { display: none; position: absolute; z-index: 50; width: 220px; background: #151e32; border: 1px solid #334155; border-radius: 12px; box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5); overflow: hidden; }
    .context-item { padding: 12px 18px; font-size: 13px; font-weight: 600; color: #cbd5e1; cursor: pointer; transition: all 0.2s; }
    .context-item:hover { background: #1e293b; color: #fff; padding-left: 22px; }
    .card { background-color: #151e32; border: 1px solid #1e293b; border-radius: 16px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }
    
    /* Canlı Destek Geçiş Animasyonları */
    .slide-in { animation: slideIn 0.3s ease-out forwards; }
    .slide-out { animation: slideOut 0.3s ease-in forwards; }
    @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
    @keyframes slideOut { from { transform: translateX(0); opacity: 1; } to { transform: translateX(100%); opacity: 0; } }
</style>
</head><body class="flex h-screen overflow-hidden">

    <div id="toast-container" class="fixed top-5 right-5 z-[9999] flex flex-col gap-3">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
          {% for category, message in messages %}
            {% set t_color = 'rose' if category == 'error' else ('amber' if category == 'warning' else 'emerald') %}
            <div class="toast-message bg-[#151e32] border border-{{ t_color }}-500 text-{{ t_color }}-400 px-6 py-4 rounded-xl shadow-2xl flex items-center gap-3 transition-opacity duration-500 font-semibold text-sm">
                {{ message }}
            </div>
          {% endfor %}
        <script>setTimeout(() => { document.querySelectorAll('.toast-message').forEach(el => { el.style.opacity = '0'; setTimeout(() => el.remove(), 500); }); }, 4000);</script>
      {% endif %}
    {% endwith %}
    </div>

    <div id="context-menu">
        <div class="context-item text-indigo-400" onclick="openGeoProfile()">🌍 Profil Göster</div>
        <div class="context-item text-emerald-400" onclick="openChatFromMenu()">💬 Yeni Mesaj Başlat</div>
        <div class="context-item text-amber-400" onclick="openMoveModal()">🚀 Odaya Taşı</div>
        <div class="context-item text-purple-400" onclick="openGroupModal()">👑 Yetki Ver/Al</div>
        <div class="border-t border-[#334155] my-1"></div>
        <div class="context-item text-slate-300" onclick="triggerAction('poke')">👉 Dürt (Poke)</div>
        <div class="context-item text-slate-300" onclick="triggerAction('kick')">🚪 Sunucudan At (Kick)</div>
        <div class="context-item text-rose-400" onclick="openBanModal()">🚨 Yasakla (Ban)</div>
    </div>

    <form id="action-form" action="/action" method="POST" class="hidden">
        <input type="hidden" name="clid" id="action-clid"><input type="hidden" name="cldbid" id="action-cldbid"><input type="hidden" name="nickname" id="action-nickname">
        <input type="hidden" name="action" id="action-type"><input type="hidden" name="msg" id="action-msg"><input type="hidden" name="extra" id="action-extra">
    </form>

    <div id="geoProfileModal" class="hidden fixed inset-0 bg-black/70 z-50 flex justify-center items-center"><div class="bg-[#151e32] border border-[#334155] rounded-2xl w-full max-w-sm p-8 shadow-2xl"><h3 class="text-white font-bold mb-5 border-b border-[#334155] pb-3 text-lg">Kullanıcı Profili</h3><div class="space-y-3 text-sm text-slate-300 font-medium bg-[#0f172a] p-5 rounded-xl border border-[#1e293b]"><p>İsim: <span id="geoName" class="text-white font-bold"></span></p><p>UID: <span id="geoUID" class="text-indigo-400 text-xs"></span></p><p>IP: <span id="geoIP" class="text-emerald-400 font-bold"></span></p><p>Konum: <span id="geoLoc" class="text-amber-400 font-bold">Yükleniyor...</span></p><p>Giriş: <span id="geoJoin" class="text-white"></span></p><p>Süre: <span id="geoConn" class="text-white"></span></p></div><button onclick="closeModal('geoProfileModal')" class="w-full mt-6 bg-[#334155] hover:bg-[#475569] text-white font-bold py-3 rounded-xl transition-colors tracking-wide">Kapat</button></div></div>
    <div id="moveModal" class="hidden fixed inset-0 bg-black/70 z-50 flex justify-center items-center"><div class="bg-[#151e32] border border-[#334155] rounded-2xl w-full max-w-sm p-8 shadow-2xl"><h3 class="text-white font-bold mb-5 border-b border-[#334155] pb-3 text-lg">Taşı: <span id="moveTargetName" class="text-indigo-400"></span></h3><select id="moveChannelSelect" class="w-full bg-[#0f172a] border border-[#334155] text-white p-4 rounded-xl mb-5 focus:outline-none focus:border-indigo-500 font-medium">{% for c in channels %}<option value="{{ c.cid }}">{{ c.channel_name }}</option>{% endfor %}</select><div class="flex gap-3"><button onclick="executeMove()" class="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-3 rounded-xl transition-colors">Taşı</button><button onclick="closeModal('moveModal')" class="flex-1 bg-[#334155] hover:bg-[#475569] text-white font-bold py-3 rounded-xl transition-colors">İptal</button></div></div></div>
    <div id="banModal" class="hidden fixed inset-0 bg-black/70 z-50 flex justify-center items-center"><div class="bg-[#151e32] border border-[#334155] rounded-2xl w-full max-w-sm p-8 shadow-2xl"><h3 class="text-rose-400 font-bold mb-5 border-b border-[#334155] pb-3 text-lg">Banla: <span id="banTargetName"></span></h3><input type="text" id="banReasonInput" placeholder="Sebep yazın..." class="w-full bg-[#0f172a] border border-[#334155] text-white p-4 rounded-xl mb-4 focus:outline-none focus:border-rose-500 font-medium"><select id="banTimeSelect" class="w-full bg-[#0f172a] border border-[#334155] text-white p-4 rounded-xl mb-6 focus:outline-none font-medium"><option value="1">1 Saniye (Uyarı)</option><option value="3600">1 Saat</option><option value="86400">1 Gün</option><option value="0">Kalıcı</option></select><div class="flex gap-3"><button onclick="executeBan()" class="flex-1 bg-rose-600 hover:bg-rose-500 text-white font-bold py-3 rounded-xl transition-colors shadow-lg shadow-rose-600/20">Yasakla</button><button onclick="closeModal('banModal')" class="flex-1 bg-[#334155] hover:bg-[#475569] text-white font-bold py-3 rounded-xl transition-colors">İptal</button></div></div></div>
    <div id="groupModal" class="hidden fixed inset-0 bg-black/70 z-50 flex justify-center items-center"><div class="bg-[#151e32] border border-[#334155] rounded-2xl w-full max-w-md p-6 shadow-2xl"><div class="flex justify-between mb-5 border-b border-[#334155] pb-3"><h3 class="text-white font-bold text-lg">Yetki Yönetimi</h3><button onclick="closeModal('groupModal')" class="text-slate-400 hover:text-white font-bold text-xl">✕</button></div><div class="space-y-3 max-h-[350px] overflow-y-auto pr-2">{% for group in groups %}<div class="flex justify-between items-center bg-[#0f172a] p-4 rounded-xl border border-[#1e293b]"><span class="text-white text-sm font-bold">{{ group.name }}</span><div class="flex gap-2"><form action="/action" method="POST"><input type="hidden" name="action" value="addgroup"><input type="hidden" name="cldbid" class="group_cldbid"><input type="hidden" name="msg" value="{{ group.sgid }}"><input type="hidden" name="nickname" class="group_nickname"><button type="submit" class="bg-emerald-600/20 text-emerald-400 hover:bg-emerald-600 hover:text-white border border-emerald-500/30 px-3 py-1.5 rounded-lg text-xs font-bold transition-all">Ver</button></form><form action="/action" method="POST"><input type="hidden" name="action" value="delgroup"><input type="hidden" name="cldbid" class="group_cldbid"><input type="hidden" name="msg" value="{{ group.sgid }}"><input type="hidden" name="nickname" class="group_nickname"><button type="submit" class="bg-rose-600/20 text-rose-400 hover:bg-rose-600 hover:text-white border border-rose-500/30 px-3 py-1.5 rounded-lg text-xs font-bold transition-all">Al</button></form></div></div>{% endfor %}</div></div></div>

    <div id="chatBubble" onclick="toggleChatApp()" class="fixed bottom-8 right-8 w-16 h-16 bg-indigo-600 rounded-full shadow-[0_5px_20px_rgba(79,70,229,0.6)] flex justify-center items-center cursor-pointer hover:bg-indigo-500 transition-all z-[90] group border-2 border-[#1e293b]">
        <svg class="w-8 h-8 text-white group-hover:scale-110 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"></path></svg>
        <span id="chatBadge" class="hidden absolute -top-1 -right-1 bg-rose-500 border border-[#1e293b] text-white text-[10px] font-black px-2 py-0.5 rounded-full animate-pulse shadow-lg">YENİ</span>
    </div>

    <div id="chatApp" class="hidden fixed bottom-28 right-8 z-[100] bg-[#151e32] border border-[#334155] rounded-2xl w-[380px] max-w-[90vw] h-[550px] shadow-[0_15px_50px_rgba(0,0,0,0.7)] flex overflow-hidden">
        
        <div id="chatInbox" class="w-full h-full flex flex-col absolute inset-0 bg-[#151e32] z-20 transition-transform">
            <div class="bg-[#0f172a] px-5 py-4 border-b border-[#334155] flex justify-between items-center">
                <h3 class="text-white font-bold text-lg">Gelen Kutusu</h3>
                <button onclick="toggleChatApp()" class="text-slate-400 hover:text-white font-bold text-lg">✕</button>
            </div>
            <div id="inboxList" class="flex-grow overflow-y-auto p-2">
                <div class="text-center text-slate-500 text-xs mt-10 font-medium">Henüz mesaj yok.</div>
            </div>
        </div>

        <div id="chatWindow" class="w-full h-full flex flex-col absolute inset-0 bg-[#151e32] z-10 translate-x-full transition-transform">
            <div class="bg-[#0f172a] px-4 py-3 border-b border-[#334155] flex items-center gap-3">
                <button onclick="backToInbox()" class="text-slate-400 hover:text-white transition-colors">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path></svg>
                </button>
                <div class="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center text-white font-bold text-sm shadow-inner" id="chatAvatar">A</div>
                <div class="flex-grow overflow-hidden">
                    <h3 class="text-white font-bold text-sm truncate" id="chatTitle">Kullanıcı</h3>
                    <p class="text-[10px] text-emerald-400 font-semibold tracking-wider">Çevrimiçi</p>
                </div>
            </div>
            
            <div id="chatMessages" class="flex-grow overflow-y-auto p-4 space-y-4 bg-[#0b1120]">
                </div>
            
            <div class="p-3 bg-[#0f172a] border-t border-[#334155]">
                <form id="chatForm" onsubmit="sendChatAjax(event)" class="flex gap-2">
                    <input type="hidden" id="pm_clid">
                    <input type="text" id="pm_msg" placeholder="Mesaj yaz..." class="flex-grow bg-[#151e32] border border-[#334155] text-white px-4 py-2.5 rounded-full focus:outline-none focus:border-indigo-500 font-medium text-sm transition-colors" required autocomplete="off">
                    <button type="submit" class="w-10 h-10 rounded-full bg-indigo-600 hover:bg-indigo-500 text-white flex items-center justify-center transition-colors shadow-md shrink-0">
                        <svg class="w-5 h-5 ml-1" fill="currentColor" viewBox="0 0 20 20"><path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z"></path></svg>
                    </button>
                </form>
            </div>
        </div>

    </div>
    
    <div class="w-64 bg-[#0f172a] border-r border-[#1e293b] hidden md:flex flex-col flex-shrink-0 shadow-2xl z-10">
        <div class="p-8 border-b border-[#1e293b] text-center flex flex-col items-center justify-center">
            <img src="https://i.hizliresim.com/s20hok7.png" alt="Uthane Logo" class="w-32 mx-auto mb-4 drop-shadow-md transition-transform hover:scale-105">
            <h1 class="text-lg font-black text-white tracking-widest uppercase">Yönetim<span class="text-{{ p_color }}-500">.</span></h1>
        </div>
        <nav class="flex-grow p-5 space-y-3 overflow-y-auto">
            <a href="/?page=dashboard" class="block px-5 py-3.5 rounded-xl font-bold text-sm transition-all {% if page == 'dashboard' %}bg-{{ p_color }}-600 text-white shadow-lg shadow-{{ p_color }}-600/20{% else %}text-slate-400 hover:bg-[#1e293b] hover:text-white{% endif %}">📊 Genel Bakış</a>
            <a href="/?page=sessions" class="block px-5 py-3.5 rounded-xl font-bold text-sm transition-all {% if page == 'sessions' %}bg-{{ p_color }}-600 text-white shadow-lg shadow-{{ p_color }}-600/20{% else %}text-slate-400 hover:bg-[#1e293b] hover:text-white{% endif %}">🕒 Giriş Çıkışlar</a>
            <a href="/?page=channels" class="block px-5 py-3.5 rounded-xl font-bold text-sm transition-all {% if page == 'channels' %}bg-{{ p_color }}-600 text-white shadow-lg shadow-{{ p_color }}-600/20{% else %}text-slate-400 hover:bg-[#1e293b] hover:text-white{% endif %}">📁 Oda Yönetimi</a>
            <a href="/?page=roles" class="block px-5 py-3.5 rounded-xl font-bold text-sm transition-all {% if page == 'roles' %}bg-{{ p_color }}-600 text-white shadow-lg shadow-{{ p_color }}-600/20{% else %}text-slate-400 hover:bg-[#1e293b] hover:text-white{% endif %}">👑 Roller</a>
            <a href="/?page=chat" class="block px-5 py-3.5 rounded-xl font-bold text-sm transition-all {% if page == 'chat' %}bg-{{ p_color }}-600 text-white shadow-lg shadow-{{ p_color }}-600/20{% else %}text-slate-400 hover:bg-[#1e293b] hover:text-white{% endif %}">📝 Log ve Güvenlik</a>
            <a href="/?page=settings" class="block px-5 py-3.5 rounded-xl font-bold text-sm transition-all {% if page == 'settings' %}bg-{{ p_color }}-600 text-white shadow-lg shadow-{{ p_color }}-600/20{% else %}text-slate-400 hover:bg-[#1e293b] hover:text-white{% endif %}">⚙️ Sistem Ayarları</a>
        </nav>
        <div class="p-5 border-t border-[#1e293b]">
            <a href="/logout" class="block w-full text-center bg-[#1e293b] border border-[#334155] hover:bg-rose-600 hover:border-rose-500 text-slate-300 hover:text-white py-3 rounded-xl text-sm font-bold transition-all uppercase tracking-widest">Çıkış Yap</a>
        </div>
    </div>

    <div class="flex-1 flex flex-col h-screen overflow-hidden bg-[#0b1120]">
        <header class="bg-[#151e32] border-b border-[#1e293b] px-8 py-6 flex justify-between items-center flex-shrink-0 shadow-sm">
            <div>
                <h2 class="text-2xl font-bold text-white tracking-wide">{{ page_title }}</h2>
                <p id="liveClock" class="text-{{ p_color }}-400 text-xs mt-1 font-semibold tracking-widest"></p>
            </div>
            <div class="flex items-center gap-4">
                <a href="ts3server://{{ external_ip }}?port={{ ts3_voice_port }}" class="bg-[#1e293b] hover:bg-[#334155] text-white border border-[#334155] px-5 py-2.5 rounded-xl text-xs font-bold transition-colors hidden sm:block tracking-wide">🎧 Sunucuya Bağlan</a>
                {% if server_online %}
                    <span class="bg-emerald-600/20 border border-emerald-500/50 text-emerald-400 px-4 py-2.5 rounded-xl text-xs font-bold flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse"></span> SİSTEM AKTİF</span>
                {% else %}
                    <span class="bg-rose-600/20 border border-rose-500/50 text-rose-400 px-4 py-2.5 rounded-xl text-xs font-bold flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-rose-400"></span> SİSTEM ÇÖKTÜ</span>
                {% endif %}
            </div>
        </header>

        <main class="flex-1 overflow-y-auto p-8">
            __PAGE_CONTENT__
        </main>
    </div>

    <script>
        document.addEventListener('contextmenu', e => { if (!e.target.closest('.user-row')) e.preventDefault(); });
        setInterval(() => {
            const now = new Date();
            document.getElementById('liveClock').innerText = now.toLocaleDateString('tr-TR', {day:'2-digit',month:'short',year:'numeric'}) + " - " + now.toLocaleTimeString('tr-TR', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
        }, 1000);

        let pmHistory = {{ pm_history | tojson | safe }};
        let currentClid, currentCldbid, currentNickname, currentUid, currentIp, currentConn;
        let activeChatClid = null;
        
        const contextMenu = document.getElementById('context-menu');

        function formatTime(ms) {
            if (!ms) return "0s"; let s = Math.floor(ms/1000); let m = Math.floor(s/60); let h = Math.floor(m/60); s = s % 60;
            return h > 0 ? h + "s " + (m%60) + "dk" : m + " dk " + s + " sn";
        }

        function showContextMenu(e, clid, cldbid, nickname, uid, ip, conn, idle) {
            e.preventDefault();
            currentClid = clid; currentCldbid = cldbid; currentNickname = nickname; currentUid = uid; currentIp = ip; currentConn = conn;
            document.querySelectorAll('.group_cldbid').forEach(f => f.value = cldbid); document.querySelectorAll('.group_nickname').forEach(n => n.value = nickname);
            contextMenu.style.top = `${e.pageY}px`; contextMenu.style.left = `${e.pageX}px`; contextMenu.style.display = 'block';
        }
        document.addEventListener('click', e => { if(!e.target.closest('#context-menu')) contextMenu.style.display = 'none'; });

        async function openGeoProfile() { 
            contextMenu.style.display = 'none'; 
            document.getElementById('geoName').innerText = currentNickname; document.getElementById('geoUID').innerText = currentUid; document.getElementById('geoIP').innerText = currentIp; 
            let jt = new Date(Date.now() - currentConn);
            document.getElementById('geoJoin').innerText = jt.toLocaleTimeString('tr-TR', {hour: '2-digit', minute:'2-digit'});
            document.getElementById('geoConn').innerText = formatTime(currentConn); 
            document.getElementById('geoProfileModal').classList.remove('hidden'); 
            
            let geoLoc = document.getElementById('geoLoc');
            geoLoc.innerText = 'Yükleniyor...';
            if (currentIp === '127.0.0.1' || currentIp.startsWith('192.168.')) { geoLoc.innerText = 'Yerel Ağ'; return; }
            try {
                let res = await fetch('http://ip-api.com/json/' + currentIp);
                let data = await res.json();
                geoLoc.innerText = `${data.city}, ${data.country}`;
            } catch(e) { geoLoc.innerText = 'Bulunamadı'; }
        }
        
        // --- WHATSAPP TARZI JS KODLARI ---
        function updateInbox() {
            const list = document.getElementById('inboxList');
            if (Object.keys(pmHistory).length === 0) {
                list.innerHTML = '<div class="text-center text-slate-500 text-xs mt-10 font-medium">Henüz mesaj yok.</div>';
                return;
            }
            
            let html = '';
            for (let clid in pmHistory) {
                let chatData = pmHistory[clid];
                if (!chatData.msgs || chatData.msgs.length === 0) continue;
                
                let name = chatData.name || "Kullanıcı";
                let lastMsg = chatData.msgs[chatData.msgs.length - 1];
                let preview = lastMsg.msg.length > 25 ? lastMsg.msg.substring(0,25) + '...' : lastMsg.msg;
                let isMe = lastMsg.from === "Sen";
                let prefix = isMe ? "Sen: " : "";
                let unreadDot = (!isMe && activeChatClid !== clid) ? '<div class="w-2.5 h-2.5 bg-rose-500 rounded-full mt-1"></div>' : '';
                let initial = name ? name[0].toUpperCase() : "?";
                
                html += `
                <div onclick="openChatWindow('${clid}')" class="flex items-center gap-3 p-3 hover:bg-[#1e293b] rounded-xl cursor-pointer transition-colors border-b border-transparent hover:border-[#334155]">
                    <div class="w-12 h-12 rounded-full bg-indigo-600 flex items-center justify-center text-white font-bold text-lg shadow-inner flex-shrink-0">${initial}</div>
                    <div class="flex-grow overflow-hidden">
                        <div class="flex justify-between items-center mb-0.5">
                            <h4 class="text-white font-bold text-sm truncate">${name}</h4>
                            <span class="text-[10px] text-slate-500 font-semibold">${lastMsg.time}</span>
                        </div>
                        <div class="flex justify-between items-center">
                            <p class="text-xs text-slate-400 truncate">${prefix}${preview}</p>
                            ${unreadDot}
                        </div>
                    </div>
                </div>`;
            }
            list.innerHTML = html;
        }

        function toggleChatApp() {
            const app = document.getElementById('chatApp');
            const badge = document.getElementById('chatBadge');
            const bubble = document.getElementById('chatBubble');
            
            if (app.classList.contains('hidden')) {
                app.classList.remove('hidden');
                badge.classList.add('hidden');
                bubble.classList.remove('animate-bounce');
                updateInbox();
            } else {
                app.classList.add('hidden');
                backToInbox(); // Kapatınca ana menüye dönsün
            }
        }
        
        function openChatFromMenu() {
            if(contextMenu) contextMenu.style.display = 'none';
            // Sıfırdan mesaj başlatıyorsa veriyi oluştur
            if (!pmHistory[currentClid]) {
                pmHistory[currentClid] = {"name": currentNickname, "msgs": []};
            }
            
            const app = document.getElementById('chatApp');
            const badge = document.getElementById('chatBadge');
            const bubble = document.getElementById('chatBubble');
            
            if (app.classList.contains('hidden')) {
                app.classList.remove('hidden');
                badge.classList.add('hidden');
                bubble.classList.remove('animate-bounce');
            }
            
            updateInbox();
            openChatWindow(currentClid);
        }

        function openChatWindow(clid) {
            activeChatClid = clid;
            let chatData = pmHistory[clid];
            let name = chatData.name || "Kullanıcı";
            let initial = name ? name[0].toUpperCase() : "?";
            
            document.getElementById('pm_clid').value = clid;
            document.getElementById('chatTitle').innerText = name;
            document.getElementById('chatAvatar').innerText = initial;
            
            renderMessages();
            
            // Animasyonlu geçiş
            document.getElementById('chatInbox').classList.add('-translate-x-full');
            document.getElementById('chatWindow').classList.remove('translate-x-full');
            document.getElementById('pm_msg').focus();
        }

        function backToInbox() {
            activeChatClid = null;
            updateInbox();
            document.getElementById('chatInbox').classList.remove('-translate-x-full');
            document.getElementById('chatWindow').classList.add('translate-x-full');
        }

        function renderMessages() {
            if (!activeChatClid || !pmHistory[activeChatClid]) return;
            const chatBox = document.getElementById('chatMessages');
            let isScrolledToBottom = chatBox.scrollHeight - chatBox.clientHeight <= chatBox.scrollTop + 10;
            
            let msgs = pmHistory[activeChatClid].msgs;
            let html = '';
            
            if (msgs.length === 0) {
                html = '<div class="text-center text-slate-500 text-xs mt-6 font-semibold uppercase tracking-widest">Mesaj göndererek sohbeti başlatın.</div>';
            } else {
                msgs.forEach(item => {
                    let isMe = item.from === "Sen";
                    let align = isMe ? "justify-end" : "justify-start";
                    let bg = isMe ? "bg-indigo-600 text-white rounded-br-sm" : "bg-[#1e293b] text-white rounded-bl-sm border border-[#334155]";
                    
                    html += `
                    <div class="flex ${align}">
                        <div class="max-w-[85%] ${bg} px-4 py-2.5 rounded-2xl shadow-sm">
                            <p class="text-sm font-medium leading-snug">${item.msg}</p>
                            <p class="text-[9px] text-right opacity-60 mt-1 font-bold">${item.time}</p>
                        </div>
                    </div>`;
                });
            }
            
            chatBox.innerHTML = html;
            if (isScrolledToBottom) setTimeout(() => chatBox.scrollTop = chatBox.scrollHeight, 50);
        }

        async function sendChatAjax(e) {
            e.preventDefault();
            const clid = document.getElementById('pm_clid').value;
            const msgInput = document.getElementById('pm_msg');
            const msg = msgInput.value.trim();
            if (!msg || !clid) return;

            let now = new Date();
            let timeStr = now.getHours().toString().padStart(2,'0') + ":" + now.getMinutes().toString().padStart(2,'0');

            if (!pmHistory[clid]) pmHistory[clid] = {"name": "Kullanıcı", "msgs": []};
            pmHistory[clid].msgs.push({"from": "Sen", "msg": msg, "time": timeStr});
            
            renderMessages();
            msgInput.value = '';
            msgInput.focus();

            let formData = new FormData();
            formData.append('clid', clid);
            formData.append('msg', msg);
            try { await fetch('/api/send_pm', { method: 'POST', body: formData }); } catch(err) {}
        }
        
        // AJAX SİNKRONİZASYONU
        let lastTotalMsgs = -1;
        setInterval(async () => {
            try {
                let res = await fetch('/api/chat_sync');
                let data = await res.json();
                
                let currentTotal = 0;
                let hasNewRemoteMsg = false;
                let newMsgName = "";
                
                for (let clid in data) {
                    currentTotal += data[clid].msgs.length;
                    // Eğer yeni bir mesaj geldiyse ve atan kişi 'Sen' değilse
                    if (pmHistory[clid]) {
                        if (data[clid].msgs.length > pmHistory[clid].msgs.length) {
                           let lastObj = data[clid].msgs[data[clid].msgs.length - 1];
                           if (lastObj.from !== "Sen") {
                               hasNewRemoteMsg = true;
                               newMsgName = data[clid].name;
                           }
                        }
                    } else if (data[clid].msgs.length > 0) {
                        let lastObj = data[clid].msgs[data[clid].msgs.length - 1];
                        if (lastObj.from !== "Sen") {
                             hasNewRemoteMsg = true;
                             newMsgName = data[clid].name;
                        }
                    }
                }
                
                pmHistory = data;
                
                if (lastTotalMsgs !== -1 && hasNewRemoteMsg) {
                    // Bildirim çıkar
                    const container = document.getElementById('toast-container');
                    const toast = document.createElement('div');
                    toast.className = 'toast-message bg-[#151e32] border border-emerald-500 text-emerald-400 px-6 py-4 rounded-xl shadow-2xl flex items-center gap-3 transition-opacity duration-500 font-semibold text-sm z-[9999]';
                    toast.innerText = "📩 YENİ MESAJ: " + newMsgName;
                    container.appendChild(toast);
                    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 500); }, 4000);
                    
                    // Chat uygulaması kapalıysa balonu zıplat
                    const app = document.getElementById('chatApp');
                    if (app.classList.contains('hidden')) {
                        document.getElementById('chatBadge').classList.remove('hidden');
                        document.getElementById('chatBubble').classList.add('animate-bounce');
                    }
                }
                
                // Ekranları güncelle
                if (!document.getElementById('chatApp').classList.contains('hidden')) {
                    if (activeChatClid) renderMessages();
                    else updateInbox();
                }
                
                lastTotalMsgs = currentTotal;
            } catch(e) {}
        }, 1500);
        
        function openMoveModal() { contextMenu.style.display = 'none'; document.getElementById('moveTargetName').innerText = currentNickname; document.getElementById('moveModal').classList.remove('hidden'); }
        function openBanModal() { contextMenu.style.display = 'none'; document.getElementById('banTargetName').innerText = currentNickname; document.getElementById('banModal').classList.remove('hidden'); }
        function openGroupModal() { contextMenu.style.display = 'none'; document.getElementById('groupModal').classList.remove('hidden'); }
        function closeModal(id) { document.getElementById(id).classList.add('hidden'); }

        function triggerAction(actionType) { contextMenu.style.display = 'none'; let msg = prompt(`${actionType} işlemi için sebep:`, "Sistem Kararı"); if (msg) { document.getElementById('action-clid').value = currentClid; document.getElementById('action-nickname').value = currentNickname; document.getElementById('action-type').value = actionType; document.getElementById('action-msg').value = msg; document.getElementById('action-form').submit(); } }
        function executeMove() { document.getElementById('action-clid').value = currentClid; document.getElementById('action-type').value = 'move'; document.getElementById('action-extra').value = document.getElementById('moveChannelSelect').value; document.getElementById('action-form').submit(); }
        function executeBan() { let banVal = document.getElementById('banTimeSelect').value; let reason = document.getElementById('banReasonInput').value || "Uzaklaştırıldınız."; document.getElementById('action-clid').value = currentClid; document.getElementById('action-nickname').value = currentNickname; document.getElementById('action-type').value = 'timeban'; document.getElementById('action-msg').value = reason; document.getElementById('action-extra').value = banVal; document.getElementById('action-form').submit(); }
        
        {% if page == 'dashboard' %}
        setInterval(() => {
            const modals = ['moveModal', 'banModal', 'geoProfileModal', 'chatApp', 'groupModal'];
            let isOpen = modals.some(m => document.getElementById(m) && !document.getElementById(m).classList.contains('hidden'));
            if (!isOpen && document.getElementById('context-menu').style.display !== 'block') window.location.reload();
        }, 20000);
        {% endif %}
    </script>
</body></html>
"""

PAGE_ROLES = """
<div id="advancedPermModal" class="hidden fixed inset-0 bg-black/70 z-50 flex justify-center items-center">
    <div class="bg-[#151e32] border border-[#334155] rounded-2xl w-full max-w-md p-8 shadow-2xl">
        <div class="flex justify-between items-center border-b border-[#334155] pb-4 mb-5">
            <h3 class="text-white font-bold text-lg">Gelişmiş Yetki Ayarları</h3>
            <button onclick="document.getElementById('advancedPermModal').classList.add('hidden')" class="text-slate-400 hover:text-white text-xl font-bold">✕</button>
        </div>
        <p class="text-sm text-slate-400 mb-5 font-semibold">Grup: <span id="adv_sgid_display" class="text-indigo-400 font-bold"></span></p>
        
        <form action="/advanced_perm_action" method="POST" class="bg-[#0f172a] p-5 rounded-xl border border-[#1e293b] mb-5">
            <input type="hidden" name="sgid" id="adv_sgid_fix">
            <input type="hidden" name="action" value="fix_admin">
            <p class="text-sm text-white mb-3 font-bold">⚠️ Temel Yönetici Yetkilerini Geri Yükle</p>
            <button type="submit" class="w-full bg-amber-600 hover:bg-amber-500 text-white font-bold py-2.5 rounded-lg text-sm transition-colors shadow-lg shadow-amber-600/20">Bozulan Yetkileri Düzelt (God Mode)</button>
        </form>

        <form action="/advanced_perm_action" method="POST" class="bg-[#0f172a] p-5 rounded-xl border border-[#1e293b] space-y-4">
            <input type="hidden" name="sgid" id="adv_sgid_add">
            <input type="hidden" name="action" value="add_perm">
            <p class="text-sm text-white font-bold">Eksik Yetkiyi Manuel Ekle</p>
            <select name="permsid" class="w-full bg-[#151e32] border border-[#334155] text-white p-3 rounded-lg text-sm focus:outline-none focus:border-indigo-500 font-medium">
                <option value="">-- Şablon Seç (Veya alta yaz) --</option>
                <option value="b_serverquery_login">b_serverquery_login</option>
                <option value="i_group_modify_power">i_group_modify_power</option>
                <option value="i_group_member_add_power">i_group_member_add_power</option>
                <option value="i_permission_modify_power">i_permission_modify_power</option>
            </select>
            <input type="text" name="custom_permsid" placeholder="Özel Kod (Örn: b_client_ignore_bans)" class="w-full bg-[#151e32] border border-[#334155] text-white p-3 rounded-lg text-sm focus:outline-none font-medium">
            <input type="number" name="permvalue" placeholder="Değer (Varsayılan: 1 veya 75)" value="1" class="w-full bg-[#151e32] border border-[#334155] text-white p-3 rounded-lg text-sm focus:outline-none font-medium">
            <button type="submit" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-2.5 rounded-lg text-sm transition-colors shadow-lg shadow-indigo-600/20">Yetkiyi İşle</button>
        </form>
    </div>
</div>

<div class="card p-8 mb-8">
    <h3 class="text-lg font-bold text-white mb-5">Yeni Yetki Grubu (Rol) Oluştur</h3>
    <form action="/role_action" method="POST" class="flex gap-4">
        <input type="hidden" name="action" value="create">
        <input type="text" name="gname" placeholder="Grup Adı (Örn: VIP)" required class="flex-grow bg-[#0f172a] border border-[#334155] text-white px-5 py-3 rounded-xl focus:outline-none focus:border-{{ p_color }}-500 font-medium">
        <button type="submit" class="bg-{{ p_color }}-600 hover:bg-{{ p_color }}-500 text-white px-8 py-3 rounded-xl font-bold transition-colors shadow-lg shadow-{{ p_color }}-600/20">Ekle</button>
    </form>
</div>

<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
    {% for group in groups %}
        <div class="card p-6 flex flex-col justify-between">
            <div class="flex justify-between items-center border-b border-[#1e293b] pb-4 mb-5">
                <h4 class="text-white font-bold text-lg truncate pr-2">👑 {{ group.name }}</h4>
                <span class="text-xs bg-[#0f172a] border border-[#334155] text-slate-400 px-2.5 py-1 rounded-lg font-semibold">ID: {{ group.sgid }}</span>
            </div>
            <div class="flex flex-col gap-3">
                <form action="/role_action" method="POST" class="flex gap-2">
                    <input type="hidden" name="sgid" value="{{ group.sgid }}">
                    <input type="text" name="gname" placeholder="Yeni İsim" required class="flex-grow bg-[#0f172a] border border-[#334155] text-white text-sm px-3 py-2 rounded-lg focus:outline-none font-medium">
                    <button type="submit" name="action" value="rename" class="bg-[#1e293b] hover:bg-[#334155] text-white px-4 py-2 rounded-lg text-sm font-bold transition-colors border border-[#334155]">Düzelt</button>
                </form>
                <div class="flex gap-3 mt-1">
                    <button type="button" onclick="openAdvancedPermModal('{{ group.sgid }}', '{{ group.name }}')" class="flex-1 bg-[#1e293b] hover:bg-indigo-600 border border-[#334155] text-white py-2 rounded-lg text-sm font-bold transition-colors">⚙️ Ayarlar</button>
                    <form action="/role_action" method="POST" class="flex-1" onsubmit="return confirm('Kalıcı olarak silinecek. Emin misiniz?');">
                        <input type="hidden" name="sgid" value="{{ group.sgid }}">
                        <button type="submit" name="action" value="delete" class="w-full bg-rose-600/10 hover:bg-rose-600 border border-rose-500/30 text-rose-400 hover:text-white py-2 rounded-lg text-sm font-bold transition-colors">Sil</button>
                    </form>
                </div>
            </div>
        </div>
    {% endfor %}
</div>
<script>
    function openAdvancedPermModal(sgid, name) {
        document.getElementById('adv_sgid_display').innerText = name + " (ID: " + sgid + ")";
        document.getElementById('adv_sgid_fix').value = sgid;
        document.getElementById('adv_sgid_add').value = sgid;
        document.getElementById('advancedPermModal').classList.remove('hidden');
    }
</script>
"""

PAGE_DASHBOARD = """
<div class="card p-8 mb-8">
    <form action="/global_action" method="POST" class="flex gap-4">
        <input type="text" name="msg" placeholder="Tüm sunucuya global mesaj (Anons) gönder..." class="flex-grow bg-[#0f172a] border border-[#334155] text-white px-5 py-3 rounded-xl focus:outline-none focus:border-{{ p_color }}-500 font-medium" required>
        <button type="submit" class="bg-{{ p_color }}-600 hover:bg-{{ p_color }}-500 text-white font-bold px-8 py-3 rounded-xl transition-colors whitespace-nowrap shadow-lg shadow-{{ p_color }}-600/20">Yayınla</button>
    </form>
</div>

<div class="grid grid-cols-1 md:grid-cols-3 gap-8 mb-8">
    <div class="card p-6 text-center flex flex-col justify-center border-t-4 border-indigo-500">
        <p class="text-slate-400 text-sm font-semibold mb-2 uppercase tracking-widest">Kapasite Durumu</p>
        <p class="text-4xl font-extrabold text-white">{{ clients | length }} <span class="text-slate-500 text-2xl font-semibold">/ {{ info.get('virtualserver_maxclients', '0') }}</span></p>
    </div>
    <div class="card p-6 text-center flex flex-col justify-center border-t-4 border-emerald-500">
        <p class="text-slate-400 text-sm font-semibold mb-2 uppercase tracking-widest">Çalışma Süresi</p>
        <p class="text-2xl font-bold text-white">{{ info.get('uptime_formatted', '0 Gün 0 Saat') }}</p>
    </div>
    <div class="card p-6 text-center flex flex-col justify-center border-t-4 border-amber-500">
        <p class="text-slate-400 text-sm font-semibold mb-2 uppercase tracking-widest">Sunucu Sinyali</p>
        <p class="text-4xl font-extrabold text-white">{{ info.get('ping_formatted', '0') }} <span class="text-amber-500 text-lg">ms</span></p>
    </div>
</div>

<div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
    <div class="lg:col-span-2 card p-8 flex flex-col h-[550px]">
        <h3 class="text-xl font-bold text-white mb-5 border-b border-[#1e293b] pb-3 flex items-center justify-between">Bağlı Kullanıcılar <span class="text-xs font-semibold text-indigo-400 bg-indigo-500/10 px-3 py-1 rounded-lg border border-indigo-500/20">İşlem için sağ tıkla</span></h3>
        <div class="overflow-y-auto pr-2 space-y-3 flex-grow">
            {% for client in clients %}
                <div class="user-row bg-[#0f172a] border border-[#1e293b] p-4 rounded-xl flex items-center justify-between hover:border-indigo-500/50 transition-colors shadow-sm cursor-pointer" oncontextmenu="showContextMenu(event, '{{ client.clid }}', '{{ client.client_database_id }}', '{{ client.client_nickname }}', '{{ client.get('client_unique_identifier','') }}', '{{ client.get('connection_client_ip','') }}', '{{ client.get('connection_connected_time','') }}', '{{ client.get('client_idle_time','') }}')">
                    <div class="flex items-center gap-4">
                        <div class="w-10 h-10 rounded-lg bg-indigo-600 text-white flex items-center justify-center font-bold text-lg shadow-inner">{{ client.client_nickname[0] | upper }}</div>
                        <div>
                            <p class="text-white font-bold text-base">{{ client.client_nickname }}</p>
                            <p class="text-slate-400 text-xs font-medium mt-0.5">Oda: <span class="text-indigo-300">{{ client.channel_name_str }}</span></p>
                        </div>
                    </div>
                    <span class="text-xs text-slate-500 font-semibold bg-[#151e32] px-2 py-1 rounded border border-[#334155]">DB: {{ client.client_database_id }}</span>
                </div>
            {% endfor %}
            {% if not clients %}<p class="text-center text-slate-500 text-sm mt-6 font-medium">Sunucuda kimse yok.</p>{% endif %}
        </div>
    </div>
    
    <div class="card p-8 flex flex-col h-[550px]">
        <h3 class="text-xl font-bold text-rose-400 mb-5 border-b border-[#1e293b] pb-3">Kara Liste (Banlılar)</h3>
        <div class="overflow-y-auto pr-2 space-y-3 flex-grow">
            {% for ban in bans %}
            <div class="bg-[#0f172a] border border-[#1e293b] p-4 rounded-xl hover:border-rose-500/30 transition-colors">
                <div class="flex justify-between items-start mb-3">
                    <p class="text-sm font-bold text-rose-400 truncate pr-2">{{ ban.display_name }}</p>
                    <form action="/unban" method="POST"><input type="hidden" name="banid" value="{{ ban.banid }}"><button type="submit" class="text-xs bg-[#151e32] hover:bg-rose-600 text-slate-300 hover:text-white px-2.5 py-1.5 rounded-lg transition-colors border border-[#334155] font-bold">Kaldır</button></form>
                </div>
                <p class="text-xs text-slate-400 font-medium mb-1">Sebep: <span class="text-white">{{ ban.display_reason }}</span></p>
                <p class="text-xs text-slate-500 font-medium">Atan: {{ ban.display_invoker }}</p>
            </div>
            {% endfor %}
            {% if not bans %}<p class="text-center text-slate-500 text-sm mt-6 font-medium">Liste tertemiz.</p>{% endif %}
        </div>
    </div>
</div>
"""

PAGE_SETTINGS = """
<div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
    <div class="space-y-8">
        <div class="card p-8">
            <h3 class="text-xl font-bold text-white border-b border-[#1e293b] pb-3 mb-5">Temel Sunucu Ayarları</h3>
            <form action="/update_server" method="POST" class="space-y-5">
                <div><label class="block text-sm font-semibold text-slate-400 mb-2 uppercase tracking-wide">Sunucu İsim</label><input type="text" name="sname" value="{{ info.get('virtualserver_name', '') | replace('\\\\s', ' ') }}" class="w-full bg-[#0f172a] border border-[#334155] text-white px-4 py-3 rounded-xl focus:outline-none focus:border-indigo-500 font-medium transition-colors"></div>
                <div><label class="block text-sm font-semibold text-slate-400 mb-2 uppercase tracking-wide">Karşılama Mesajı</label><input type="text" name="swelcome" value="{{ info.get('virtualserver_welcomemessage', '') | replace('\\\\s', ' ') }}" class="w-full bg-[#0f172a] border border-[#334155] text-white px-4 py-3 rounded-xl focus:outline-none focus:border-indigo-500 font-medium transition-colors"></div>
                <div><label class="block text-sm font-semibold text-slate-400 mb-2 uppercase tracking-wide">Sunucu Şifresi</label><input type="text" name="spass" placeholder="Yeni şifre (Kaldırmak için boş bırak)" class="w-full bg-[#0f172a] border border-[#334155] text-white px-4 py-3 rounded-xl focus:outline-none focus:border-indigo-500 font-medium transition-colors"></div>
                <button type="submit" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-3 rounded-xl transition-colors mt-2 shadow-lg shadow-indigo-600/20">Değişiklikleri Kaydet</button>
            </form>
        </div>
        
        <div class="card p-8">
            <h3 class="text-xl font-bold text-white border-b border-[#1e293b] pb-3 mb-5">Sistem Motoru</h3>
            <form action="/sys_action" method="POST" class="flex gap-3">
                <button type="submit" name="action" value="start" class="flex-1 bg-[#0f172a] border border-[#334155] hover:bg-emerald-600 text-white font-bold py-3 rounded-xl text-sm transition-colors">Başlat</button>
                <button type="submit" name="action" value="restart" class="flex-1 bg-[#0f172a] border border-[#334155] hover:bg-amber-500 text-white font-bold py-3 rounded-xl text-sm transition-colors">Yeniden Başlat</button>
                <button type="submit" name="action" value="stop" class="flex-1 bg-[#0f172a] border border-[#334155] hover:bg-rose-600 text-white font-bold py-3 rounded-xl text-sm transition-colors">Kapat</button>
            </form>
        </div>
        
        <div class="card p-8 border-t-4 border-emerald-500">
            <h3 class="text-xl font-bold text-emerald-400 border-b border-[#1e293b] pb-3 mb-5">Web Panel Şifresi</h3>
            <form action="/update_panel_pass" method="POST" class="space-y-4">
                <input type="text" name="new_panel_pass" placeholder="Panele giriş için yeni şifreniz" required class="w-full bg-[#0f172a] border border-[#334155] text-white px-4 py-3 rounded-xl focus:outline-none focus:border-emerald-500 font-medium transition-colors">
                <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-3 rounded-xl transition-colors shadow-lg shadow-emerald-600/20">Giriş Şifresini Değiştir</button>
            </form>
        </div>
    </div>
    
    <div class="space-y-8">
        <div class="card p-8 border-t-4 border-rose-500">
            <h3 class="text-xl font-bold text-rose-400 border-b border-[#1e293b] pb-3 mb-5">Sistem Kilidi (Lockdown)</h3>
            <p class="text-sm text-slate-400 mb-5 font-medium leading-relaxed">Acil bir durumda sunucuya rastgele şifre atar ve tüm girişleri mühürler.</p>
            <form action="/lockdown" method="POST" class="flex gap-3">
                <button type="submit" name="state" value="on" class="flex-1 bg-rose-600 hover:bg-rose-500 text-white font-bold py-3 rounded-xl transition-colors shadow-lg shadow-rose-600/20">Kilitle</button>
                <button type="submit" name="state" value="off" class="flex-1 bg-[#0f172a] border border-[#334155] hover:bg-[#334155] text-white font-bold py-3 rounded-xl transition-colors">Kilidi Aç</button>
            </form>
        </div>
        
        <div class="card p-8">
            <h3 class="text-xl font-bold text-amber-400 border-b border-[#1e293b] pb-3 mb-5">Toplu İşlemler</h3>
            <form action="/mass_action" method="POST" class="space-y-4">
                <select name="action" class="w-full bg-[#0f172a] border border-[#334155] text-white px-4 py-3 rounded-xl focus:outline-none focus:border-amber-500 font-medium">
                    <option value="afk_kick">Tüm AFK Kalanları At (Kick)</option>
                    <option value="poke_all">Herkese Dürtme (Poke) Gönder</option>
                </select>
                <input type="text" name="msg" placeholder="Mesaj (Opsiyonel)" class="w-full bg-[#0f172a] border border-[#334155] text-white px-4 py-3 rounded-xl focus:outline-none focus:border-amber-500 font-medium">
                <button type="submit" class="w-full bg-amber-600 hover:bg-amber-500 text-white font-bold py-3 rounded-xl transition-colors shadow-lg shadow-amber-600/20">İşlemi Başlat</button>
            </form>
        </div>
        
        <div class="card p-8 border-t-4 border-blue-500">
            <h3 class="text-xl font-bold text-white border-b border-[#1e293b] pb-3 mb-5">Yedekleme Merkezi</h3>
            <p class="text-sm text-slate-400 mb-5 font-medium leading-relaxed">Sunucunun odalarını ve yetki ayarlarını bilgisayarınıza güvenle indirin.</p>
            <a href="/export_snapshot" class="block text-center bg-blue-600 hover:bg-blue-500 text-white font-bold py-3 rounded-xl transition-colors shadow-lg shadow-blue-600/20">Tam Yedek Al (.bak)</a>
        </div>
    </div>
</div>
"""

PAGE_CHAT = """
<div class="flex justify-between items-center mb-5">
    <h3 class="text-xl font-bold text-white">Sistem ve Güvenlik Logları</h3>
    <a href="/export_logs" class="bg-[#1e293b] hover:bg-indigo-600 border border-[#334155] text-white px-5 py-2.5 rounded-xl text-sm font-bold transition-colors shadow-md">Logları İndir</a>
</div>
<div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
    <div class="card p-6 flex flex-col h-[650px]">
        <h4 class="text-white font-bold mb-4 border-b border-[#1e293b] pb-3 text-lg">Panel İşlemleri</h4>
        <div class="bg-[#0f172a] rounded-xl p-5 font-mono text-sm text-slate-300 flex-grow overflow-y-auto border border-[#1e293b] shadow-inner">
            {% for line in logs %}<div class="mb-2 border-b border-[#1e293b] pb-2">{{ line }}</div>{% endfor %}
            {% if not logs %}<p class="text-slate-500 font-semibold text-center mt-5">Kayıt yok.</p>{% endif %}
        </div>
    </div>
    <div class="card p-6 flex flex-col h-[650px] border-t-4 border-rose-500">
        <h4 class="text-rose-400 font-bold mb-4 border-b border-[#1e293b] pb-3 text-lg">TS3 Çekirdek Logları</h4>
        <div class="bg-[#0f172a] rounded-xl p-5 font-mono text-xs text-slate-400 flex-grow overflow-y-auto border border-[#1e293b] shadow-inner">
            {% for line in ts3_logs %}<div class="mb-1.5">{{ line }}</div>{% endfor %}
            {% if not ts3_logs %}<p class="text-slate-500 font-semibold text-center mt-5">Kayıt yok.</p>{% endif %}
        </div>
    </div>
</div>
"""

PAGE_CHANNELS = """
<div class="card p-8 mb-8">
    <h3 class="text-xl font-bold text-white mb-5">Yeni Oda Ekle</h3>
    <form action="/channel_action" method="POST" class="flex flex-col md:flex-row gap-4">
        <input type="hidden" name="action" value="create">
        <input type="text" name="cname" placeholder="Oda Adı" required class="flex-grow bg-[#0f172a] border border-[#334155] text-white px-4 py-3 rounded-xl focus:outline-none focus:border-indigo-500 font-medium">
        <input type="text" name="cpw" placeholder="Şifre (Opsiyonel)" class="md:w-56 bg-[#0f172a] border border-[#334155] text-white px-4 py-3 rounded-xl focus:outline-none focus:border-indigo-500 font-medium">
        <button type="submit" class="bg-indigo-600 hover:bg-indigo-500 text-white px-8 py-3 rounded-xl font-bold transition-colors shadow-lg shadow-indigo-600/20">Oluştur</button>
    </form>
</div>

<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
    {% for channel in channels %}
        <div class="card p-6 flex flex-col">
            <div class="flex justify-between items-start border-b border-[#1e293b] pb-3 mb-4">
                <h4 class="text-white font-bold text-base truncate pr-2 flex items-center gap-2"><span class="text-indigo-400 text-xl">📁</span> {{ channel.channel_name }}</h4>
                <span class="text-xs bg-[#0f172a] border border-[#334155] text-slate-400 px-2 py-1 rounded font-semibold">CID: {{ channel.cid }}</span>
            </div>
            
            <div class="flex-grow space-y-2 mb-5">
                {% set count = namespace(value=0) %}
                {% for client in clients %}{% if client.cid == channel.cid %}
                    <div class="text-xs text-white bg-[#0f172a] border border-[#1e293b] px-3 py-2 rounded-lg truncate font-medium">👤 {{ client.client_nickname }}</div>
                    {% set count.value = count.value + 1 %}
                {% endif %}{% endfor %}
                {% if count.value == 0 %}<p class="text-xs text-slate-500 italic font-medium">Oda boş.</p>{% endif %}
            </div>

            <form action="/channel_action" method="POST" class="flex gap-2 pt-4 border-t border-[#1e293b] mt-auto">
                <input type="hidden" name="cid" value="{{ channel.cid }}">
                <input type="text" name="cname" placeholder="Yeni Ad" required class="flex-grow bg-[#0f172a] border border-[#334155] text-white text-xs px-3 py-2 rounded-lg focus:outline-none font-medium">
                <button type="submit" name="action" value="edit" class="bg-[#1e293b] hover:bg-[#334155] border border-[#334155] text-white px-3 py-2 rounded-lg text-xs font-bold transition-colors">Düzelt</button>
                <button type="submit" name="action" value="delete" class="bg-rose-600/10 hover:bg-rose-600 text-rose-400 hover:text-white border border-rose-500/30 px-3 py-2 rounded-lg text-xs font-bold transition-colors" onclick="return confirm('Oda silinecek. Emin misiniz?');">Sil</button>
            </form>
        </div>
    {% endfor %}
</div>
"""

PAGE_SESSIONS = """
<div class="card p-8 h-[750px] flex flex-col">
    <div class="flex justify-between items-center border-b border-[#1e293b] pb-5 mb-5">
        <h3 class="text-xl font-bold text-white">Bağlantı Arşivi</h3>
        <form action="/clear_sessions" method="POST" onsubmit="return confirm('Tüm geçmiş silinecek. Onaylıyor musunuz?');">
            <button type="submit" class="bg-[#1e293b] hover:bg-rose-600 text-slate-300 hover:text-white px-4 py-2 rounded-lg text-sm font-bold border border-[#334155] transition-colors">Geçmişi Temizle</button>
        </form>
    </div>
    <div class="bg-[#0f172a] border border-[#1e293b] rounded-xl p-6 font-mono text-sm text-slate-300 flex-grow overflow-y-auto shadow-inner">
        {% if session_logs %}
            {% for log in session_logs %}<div class="mb-3 pb-3 border-b border-[#1e293b]">{{ log }}</div>{% endfor %}
        {% else %}
            <p class="text-center text-slate-500 mt-8 font-semibold text-base">Kayıt bulunamadı. (Sistem arka planda izlemeye devam ediyor)</p>
        {% endif %}
    </div>
</div>
"""

# --- FONKSİYONLAR ---

def parse_ts_line(line):
    results = []
    if 'error id=' in line and 'msg=ok' not in line: return results
    for item in line.split('|'):
        data = {}
        for pair in item.strip().split(' '):
            if '=' in pair:
                k, v = pair.split('=', 1)
                data[k] = v.replace(r'\s', ' ').replace(r'\/', '/').replace(r'\p', '|')
        if data: results.append(data)
    return results

def get_ts6_all_data():
    data = {'clients': [], 'bans': [], 'channels': [], 'groups': [], 'info': {}}
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(TS3_HOST, port=TS3_PORT, username=TS3_USER, password=TS3_PASS, timeout=5)
        shell = ssh.invoke_shell()
        
        def run_query(cmd):
            shell.send(cmd + "\n")
            out = ""; start = time.time()
            while True:
                if shell.recv_ready(): out += shell.recv(65536).decode("utf-8", errors="ignore")
                if "error id=" in out or time.time() - start > 2: break
                time.sleep(0.05)
            lines = out.split('\n'); results = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith('error id=') or line.startswith('TS3') or line.startswith('Welcome'): continue
                results.extend(parse_ts_line(line))
            return results
            
        shell.send("use 1\n"); time.sleep(1.0); 
        while shell.recv_ready(): shell.recv(65536) 

        info_list = run_query("serverinfo")
        if info_list:
            data['info'] = info_list[0]
            up_sec = int(data['info'].get('virtualserver_uptime', 0))
            m, s = divmod(up_sec, 60); h, m = divmod(m, 60); d, h = divmod(h, 24)
            data['info']['uptime_formatted'] = "{} Gün {} Saat {} Dk".format(d, h, m)
            
            ping_val = data['info'].get('virtualserver_total_ping', '0')
            try: data['info']['ping_formatted'] = "{:.0f}".format(float(ping_val))
            except: data['info']['ping_formatted'] = "0"
            
        clients_raw = run_query("clientlist -uid -ip -times")
        data['clients'] = [c for c in clients_raw if (c.get('client_nickname') and 'serveradmin' not in str(c.get('client_nickname')).lower() and 'siber' not in str(c.get('client_nickname')).lower())]
        
        bans_raw = run_query("banlist")
        grouped_bans = {}
        for b in bans_raw:
            d_name = b.get('lastnickname', b.get('name', b.get('ip', b.get('uid', 'Bilinmiyor')))).replace(r'\s', ' ')
            d_invoker = b.get('invokername', 'Sistem').replace(r'\s', ' ')
            d_reason = b.get('banreason', b.get('reason', 'Belirtilmedi')).replace(r'\s', ' ')
            b_id = str(b.get('banid', ''))
            
            g_key = d_name + "_" + d_reason + "_" + d_invoker
            if g_key not in grouped_bans:
                grouped_bans[g_key] = {
                    'display_name': d_name,
                    'display_invoker': d_invoker,
                    'display_reason': d_reason,
                    'banid_list': [b_id]
                }
            else:
                if b_id not in grouped_bans[g_key]['banid_list']:
                    grouped_bans[g_key]['banid_list'].append(b_id)
        
        data['bans'] = []
        for g in grouped_bans.values():
            g['banid'] = ",".join(g['banid_list'])
            data['bans'].append(g)
            
        data['channels'] = run_query("channellist")
        
        groups_raw = run_query("servergrouplist")
        data['groups'] = []
        for g in groups_raw:
            g_name = g.get('name', '').replace(r'\s', ' ')
            g['name'] = g_name
            if g.get('type') == '1': data['groups'].append(g)
        
        chan_map = {ch.get('cid'): ch.get('channel_name', '').replace(r'\s', ' ') for ch in data['channels']}
        for c in data['clients']: 
            c['channel_name_str'] = chan_map.get(c.get('cid'), 'Bilinmeyen Oda')
        
        ssh.close()
    except Exception as e: logging.error("Veri Cekme Hatasi: {}".format(e))
    return data

def get_user_sicil(nickname):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(TS3_HOST, port=TS3_PORT, username=TS3_USER, password=TS3_PASS, timeout=5)
        shell = ssh.invoke_shell()
        def run_query(cmd):
            shell.send(cmd + "\n"); out = ""; start = time.time()
            while True:
                if shell.recv_ready(): out += shell.recv(65536).decode("utf-8", errors="ignore")
                if "error id=" in out or time.time() - start > 2: break
                time.sleep(0.05)
            lines = out.split('\n'); results = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith('error id=') or line.startswith('TS3') or line.startswith('Welcome'): continue
                results.extend(parse_ts_line(line))
            return results
        shell.send("use 1\n"); time.sleep(1.0); 
        while shell.recv_ready(): shell.recv(65536)
        safe_nick = nickname.replace(' ', r'\s')
        find_res = run_query("clientdbfind pattern={}".format(safe_nick))
        if not find_res:
            ssh.close(); return None
        cldbid = find_res[0].get('cldbid')
        real_name = find_res[0].get('client_nickname', nickname).replace(r'\s', ' ')
        info_res = run_query("clientdbinfo cldbid={}".format(cldbid))
        ssh.close()
        if info_res:
            data = info_res[0]
            return {'name': real_name, 'created': data.get('client_created', '0'), 'last_conn': data.get('client_lastconnected', '0'), 'total_conn': data.get('client_totalconnections', '0')}
        return None
    except Exception as e:
        return None

def get_all_sicil():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(TS3_HOST, port=TS3_PORT, username=TS3_USER, password=TS3_PASS, timeout=5)
        shell = ssh.invoke_shell()
        def run_query(cmd):
            shell.send(cmd + "\n"); out = ""; start = time.time()
            while True:
                if shell.recv_ready(): out += shell.recv(65536).decode("utf-8", errors="ignore")
                if "error id=" in out or time.time() - start > 2: break
                time.sleep(0.05)
            lines = out.split('\n'); results = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith('error id=') or line.startswith('TS3') or line.startswith('Welcome'): continue
                results.extend(parse_ts_line(line))
            return results
        shell.send("use 1\n"); time.sleep(1.0); 
        while shell.recv_ready(): shell.recv(65536)
        res = run_query("clientdblist start=0 duration=200")
        ssh.close()
        return res
    except Exception as e:
        return []

def is_ts6_running():
    try: return subprocess.run([SYSTEMCTL_PATH, "is-active", "ts6.service"], capture_output=True, text=True).stdout.strip() == "active"
    except: return False

def execute_ts6_command(command):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(TS3_HOST, port=TS3_PORT, username=TS3_USER, password=TS3_PASS, timeout=5)
        shell = ssh.invoke_shell()
        shell.send("use 1\n"); time.sleep(1.0); shell.send(command + "\n"); time.sleep(0.3); ssh.close()
    except Exception as e: logging.error("Komut Hatasi: {}".format(e))

def get_logs():
    try:
        with open(LOG_FILE, 'r') as f: return f.read().splitlines()[-30:] 
    except: return []

def get_session_logs():
    try:
        with open(SESSION_LOG_FILE, 'r') as f: return f.read().splitlines()[-50:][::-1] 
    except: return []

def get_ts3_core_logs():
    try:
        if not os.path.exists(LOG_DIR): return ["Log dizini bulunamadı."]
        files = glob.glob(os.path.join(LOG_DIR, "ts3server_*"))
        if not files: return ["Çekirdek log dosyası bulunamadı."]
        latest = max(files, key=os.path.getctime)
        with open(latest, 'r') as f: return [line.strip() for line in f.readlines()[-40:]]
    except Exception as e: return ["Sızıntı Hatası: {}".format(e)]

def tg_api(method, payload):
    if not TELEGRAM_BOT_TOKEN: return None
    url = "https://api.telegram.org/bot{}/{}".format(TELEGRAM_BOT_TOKEN, method)
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode())
    except Exception as e: return None

def send_telegram_msg(text, reply_markup=None):
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': text}
    if reply_markup: payload['reply_markup'] = reply_markup
    tg_api('sendMessage', payload)

def telegram_listener():
    global HUNTED_USERS, USER_STATES
    if not TELEGRAM_BOT_TOKEN: return
    offset = 0
    while True:
        try:
            res = tg_api('getUpdates', {'offset': offset, 'timeout': 20})
            if res and res.get("ok"):
                for item in res["result"]:
                    offset = item["update_id"] + 1
                    
                    if "callback_query" in item:
                        cb = item["callback_query"]
                        cb_id = cb["id"]
                        chat_id = str(cb.get("from", {}).get("id", ""))
                        data = cb.get("data", "")
                        msg_id = cb.get("message", {}).get("message_id")
                        
                        if chat_id != str(TELEGRAM_CHAT_ID): continue
                        tg_api("answerCallbackQuery", {"callback_query_id": cb_id})

                        if data == "back":
                            ts_data = get_ts6_all_data()
                            if not ts_data['clients']:
                                tg_api("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": "Sunucuda şu an kimse yok."})
                            else:
                                kb = []
                                for c in ts_data['clients']:
                                    kb.append([{"text": "👤 {}".format(c['client_nickname']), "callback_data": "u_{}".format(c['clid'])}])
                                tg_api("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": "📱 **MOBİL KOMUTA MERKEZİ**\nİşlem yapmak istediğin hedefi seç:", "reply_markup": {"inline_keyboard": kb}})

                        elif data.startswith("u_"):
                            clid = data.split("_")[1]
                            ts_data = get_ts6_all_data()
                            client = next((c for c in ts_data['clients'] if c['clid'] == clid), None)
                            if client:
                                nick = client['client_nickname']
                                kb = [
                                    [{"text": "👁️ İstihbarat (Info)", "callback_data": "i_{}".format(clid)}],
                                    [{"text": "👉 Poke", "callback_data": "p_{}".format(clid)}, {"text": "🚪 Kick", "callback_data": "k_{}".format(clid)}],
                                    [{"text": "🔨 Ban", "callback_data": "b_{}".format(clid)}],
                                    [{"text": "🔙 Listeye Dön", "callback_data": "back"}]
                                ]
                                tg_api("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": "🎯 Hedef: **{}**\nLütfen bir komut seçin:".format(nick), "reply_markup": {"inline_keyboard": kb}})
                            else:
                                tg_api("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": "❌ Hedef sunucudan ayrılmış.", "reply_markup": {"inline_keyboard": [[{"text": "🔙 Listeye Dön", "callback_data": "back"}]]}})

                        elif data.startswith("i_"):
                            clid = data.split("_")[1]
                            ts_data = get_ts6_all_data()
                            client = next((c for c in ts_data['clients'] if c['clid'] == clid), None)
                            if client:
                                nick = client['client_nickname']
                                ip = client.get('connection_client_ip', 'Gizli')
                                dbid = client.get('client_database_id', 'Bilinmiyor')
                                idle_m = int(client.get('client_idle_time', 0)) // 60000
                                conn_m = int(client.get('connection_connected_time', 0)) // 60000
                                msg_str = "👁️ **AKTİF İSTİHBARAT: {}**\n📍 IP Adresi: {}\n💾 DB ID: {}\n⏳ Bağlantı: {} dk aktif\n💤 AFK: {} dk".format(nick, ip, dbid, conn_m, idle_m)
                                tg_api("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": msg_str, "reply_markup": {"inline_keyboard": [[{"text": "🔙 Geri", "callback_data": "u_{}".format(clid)}]]}})

                        elif data.startswith("p_") or data.startswith("k_"):
                            action_type = "poke" if data.startswith("p_") else "kick"
                            clid = data.split("_")[1]
                            ts_data = get_ts6_all_data()
                            c = next((x for x in ts_data['clients'] if x['clid'] == clid), None)
                            nick = c['client_nickname'] if c else "Hedef"
                            
                            USER_STATES[chat_id] = {"action": action_type, "clid": clid, "nick": nick}
                            action_text = "POKE (Dürtme) mesajını" if action_type == "poke" else "KICK (Atma) sebebini"
                            tg_api("sendMessage", {"chat_id": chat_id, "text": "✏️ Lütfen **{}** kişisi için {} yazıp gönderin.\n*(İptal etmek için sohbete 'iptal' yazın)*".format(nick, action_text)})

                        elif data.startswith("b_"):
                            clid = data.split("_")[1]
                            ts_data = get_ts6_all_data()
                            c = next((x for x in ts_data['clients'] if x['clid'] == clid), None)
                            if c:
                                nick = c['client_nickname']
                                kb = [
                                    [{"text": "1 Saniye", "callback_data": "bt_{}_1".format(clid)}, {"text": "5 Dakika", "callback_data": "bt_{}_300".format(clid)}],
                                    [{"text": "1 Saat", "callback_data": "bt_{}_3600".format(clid)}, {"text": "1 Gün", "callback_data": "bt_{}_86400".format(clid)}],
                                    [{"text": "Kalıcı", "callback_data": "bt_{}_0".format(clid)}, {"text": "🔙 İptal", "callback_data": "u_{}".format(clid)}]
                                ]
                                tg_api("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": "⏱️ **{}** kişisi için BAN süresini seçin:".format(nick), "reply_markup": {"inline_keyboard": kb}})
                        
                        elif data.startswith("bt_"):
                            parts = data.split("_")
                            clid = parts[1]
                            b_time = parts[2]
                            ts_data = get_ts6_all_data()
                            c = next((x for x in ts_data['clients'] if x['clid'] == clid), None)
                            nick = c['client_nickname'] if c else "Hedef"
                            
                            USER_STATES[chat_id] = {"action": "ban", "clid": clid, "time": b_time, "nick": nick}
                            tg_api("sendMessage", {"chat_id": chat_id, "text": "✏️ Lütfen **{}** kişisi için **BAN SEBEBİNİ** yazıp gönderin.\n*(İptal etmek için sohbete 'iptal' yazın)*".format(nick)})
                        
                        elif data.startswith("unban_"):
                            banids = data.split("_", 1)[1].split(",")
                            for bid in banids:
                                if bid: execute_ts6_command("bandel banid={}".format(bid))
                            tg_api("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": "✅ Yasak (Ban) başarıyla kaldırıldı!"})

                    elif "message" in item:
                        msg = item["message"]
                        chat_id = str(msg.get("chat", {}).get("id", ""))
                        text = msg.get("text", "").strip()
                        if chat_id != str(TELEGRAM_CHAT_ID): continue

                        if chat_id in USER_STATES:
                            state = USER_STATES[chat_id]
                            if text.lower() == 'iptal':
                                send_telegram_msg("🛑 İşlem iptal edildi.")
                                del USER_STATES[chat_id]
                                continue
                            
                            clid = state['clid']
                            nick = state['nick']
                            reason_esc = text.replace(" ", r"\s")
                            
                            if state['action'] == 'poke':
                                execute_ts6_command("clientpoke clid={} msg={}".format(clid, reason_esc))
                                send_telegram_msg("✅ **{}** kişisine poke gönderildi: {}".format(nick, text))
                            elif state['action'] == 'kick':
                                execute_ts6_command("clientkick clid={} reasonid=5 reasonmsg={}".format(clid, reason_esc))
                                send_telegram_msg("🚪 **{}** sunucudan atıldı. Sebep: {}".format(nick, text))
                            elif state['action'] == 'ban':
                                b_time = state['time']
                                execute_ts6_command("banclient clid={} time={} banreason={}".format(clid, b_time, reason_esc))
                                send_telegram_msg("🔨 **{}** yasaklandı! Sebep: {}".format(nick, text))
                                
                            del USER_STATES[chat_id]
                            continue

                        if text.startswith("/"):
                            if text == "/yonet":
                                ts_data = get_ts6_all_data()
                                if not ts_data['clients']: send_telegram_msg("Sunucuda şu an kimse yok.")
                                else:
                                    kb = []
                                    for c in ts_data['clients']:
                                        kb.append([{"text": "👤 {}".format(c['client_nickname']), "callback_data": "u_{}".format(c['clid'])}])
                                    send_telegram_msg("📱 **MOBİL KOMUTA MERKEZİ**\nİşlem yapmak istediğin hedefi seç:", reply_markup={"inline_keyboard": kb})

                            elif text == "/banliste":
                                data = get_ts6_all_data()
                                bans = data.get('bans', [])
                                if not bans:
                                    send_telegram_msg("✅ Sunucuda şu an yasaklı kimse yok.")
                                else:
                                    msg_lines = ["📜 **KARA LİSTE DETAYLARI:**"]
                                    kb = []
                                    for idx, b in enumerate(bans[:40]): 
                                        name = b.get('display_name', 'Bilinmiyor')
                                        invoker = b.get('display_invoker', 'Sistem')
                                        reason = b.get('display_reason', 'Belirtilmedi')
                                        banid = b.get('banid')
                                        msg_lines.append("{}. 👤 {} | 🛡️ {} | 📝 {}".format(idx+1, name, invoker, reason))
                                        kb.append([{"text": "🔓 Kaldır: {}".format(name), "callback_data": "unban_{}".format(banid)}])
                                    
                                    full_msg = "\n".join(msg_lines)
                                    if len(full_msg) > 4000: full_msg = full_msg[:3900] + "..."
                                    send_telegram_msg(full_msg, reply_markup={"inline_keyboard": kb})

                            elif text == "/durum":
                                data = get_ts6_all_data()
                                count = len(data['clients'])
                                max_c = data['info'].get('virtualserver_maxclients', '0')
                                uptime = data['info'].get('uptime_formatted', 'Bilinmiyor')
                                ping = data['info'].get('ping_formatted', '0')
                                send_telegram_msg("📊 SİSTEM DURUMU\n👥 Aktif: {}/{}\n📶 Ping: {} ms\n⏳ Uptime: {}".format(count, max_c, ping, uptime))
                            
                            elif text == "/liste":
                                data = get_ts6_all_data()
                                if not data['clients']: send_telegram_msg("Sunucuda kimse yok.")
                                else:
                                    msg_lines = ["📋 AKTİF KULLANICILAR VE ODALARI:"]
                                    for c in data['clients']:
                                        msg_lines.append("👤 {} ➔ 🔊 {}".format(c['client_nickname'], c.get('channel_name_str', 'Bilinmeyen Oda')))
                                    send_telegram_msg("\n".join(msg_lines))
                                    
                            elif text.startswith("/sicil "):
                                target = text.replace("/sicil ", "").strip().lower()
                                if target == "hepsi":
                                    send_telegram_msg("🗄️ Veritabanı taranıyor, lütfen bekleyin...")
                                    db_list = get_all_sicil()
                                    if db_list:
                                        msg_lines = ["🗂️ SİSTEME KAYITLI TÜM VARLIKLAR:"]
                                        for c in db_list:
                                            nick = c.get('client_nickname', 'Bilinmiyor').replace(r'\s', ' ')
                                            dbid = c.get('cldbid', '?')
                                            msg_lines.append("👤 {} (ID: {})".format(nick, dbid))
                                        full_msg = "\n".join(msg_lines)
                                        if len(full_msg) > 4000: full_msg = full_msg[:3900] + "\n... (Liste çok uzun, kesildi)"
                                        send_telegram_msg(full_msg)
                                    else:
                                        send_telegram_msg("❌ Veritabanına ulaşılamadı veya liste boş.")
                                else:
                                    sicil_data = get_user_sicil(target)
                                    if sicil_data:
                                        try:
                                            created_dt = datetime.datetime.utcfromtimestamp(int(sicil_data['created']) + 10800).strftime('%d.%m.%Y %H:%M')
                                            last_dt = datetime.datetime.utcfromtimestamp(int(sicil_data['last_conn']) + 10800).strftime('%d.%m.%Y %H:%M')
                                        except:
                                            created_dt = "Bilinmiyor"
                                            last_dt = "Bilinmiyor"
                                        msg_str = "🗄️ DERİN SİCİL DOSYASI: {}\n📅 İlk Kayıt: {}\n🔄 Toplam Giriş: {} kez\n👁️ Son Görülme: {}".format(sicil_data['name'], created_dt, sicil_data['total_conn'], last_dt)
                                        send_telegram_msg(msg_str)
                                    else:
                                        send_telegram_msg("❌ '{}' isminde bir kayıt bulunamadı.".format(target))
                                    
                            elif text.startswith("/info "):
                                target_name = text.replace("/info ", "").strip().lower()
                                data = get_ts6_all_data()
                                found = False
                                for c in data['clients']:
                                    if target_name in c['client_nickname'].lower():
                                        nick = c['client_nickname']
                                        ip = c.get('connection_client_ip', 'Gizli')
                                        dbid = c.get('client_database_id', 'Bilinmiyor')
                                        idle_m = int(c.get('client_idle_time', 0)) // 60000
                                        conn_m = int(c.get('connection_connected_time', 0)) // 60000
                                        msg_str = "👁️ AKTİF İSTİHBARAT: {}\n📍 IP Adresi: {}\n💾 DB ID: {}\n⏳ Bağlantı: {} dakikadır aktif\n💤 AFK Süresi: {} dakika".format(nick, ip, dbid, conn_m, idle_m)
                                        send_telegram_msg(msg_str)
                                        found = True
                                        break
                                if not found: send_telegram_msg("❌ '{}' şu an sunucuda aktif değil.".format(target_name))

                            elif text.startswith("/hedef"):
                                parts = text.split(" ", 1)
                                if len(parts) > 1:
                                    target = parts[1].strip().lower()
                                    if target in HUNTED_USERS:
                                        HUNTED_USERS.remove(target)
                                        send_telegram_msg("🛑 {} hedef listesinden çıkarıldı.".format(target))
                                    else:
                                        HUNTED_USERS.add(target)
                                        send_telegram_msg("🎯 {} hedeflendi! Sunucuya girdiğinde kırmızı alarm verilecek.".format(target))
                                else: send_telegram_msg("❌ Kullanım: /hedef [isim]")
                                    
                            elif text.startswith("/sifre"):
                                parts = text.split(" ", 1)
                                new_pass = parts[1].strip() if len(parts) > 1 else ""
                                pass_esc = new_pass.replace(" ", r"\s")
                                execute_ts6_command("serveredit virtualserver_password={}".format(pass_esc))
                                if new_pass: send_telegram_msg("🔒 Sunucu şifresi güncellendi: {}".format(new_pass))
                                else: send_telegram_msg("🔓 Sunucu şifresi KALDIRILDI. Herkes girebilir.")
                            
                            elif text == "/kilitle":
                                lock_pass = "LOCKDOWN_" + uuid.uuid4().hex[:8]
                                execute_ts6_command("serveredit virtualserver_password={}".format(lock_pass))
                                execute_ts6_command("gm msg=SİSTEM_KİLİTLENDİ:_TÜM_GİRİŞLER_KAPATILDI!")
                                send_telegram_msg("🚨 SİSTEM KİLİTLENDİ! Yüksek güvenlik protokolü devrede.")
                            
                            elif text == "/ac":
                                execute_ts6_command("serveredit virtualserver_password=")
                                execute_ts6_command("gm msg=SİSTEM_NORMALE_DÖNDÜ.")
                                send_telegram_msg("✅ SİSTEM KİLİDİ AÇILDI. Girişler serbest.")
                                
                            elif text == "/baslat":
                                try: subprocess.run([SYSTEMCTL_PATH, "start", "ts6.service"]); send_telegram_msg("🟢 SİSTEM MOTORU BAŞLATILDI: Sunucu aktif ediliyor...")
                                except Exception as e: send_telegram_msg("❌ Başlatma hatası: {}".format(e))
                                    
                            elif text == "/durdur":
                                try: subprocess.run([SYSTEMCTL_PATH, "stop", "ts6.service"]); send_telegram_msg("🔴 SİSTEM KAPATILDI: Çevrimdışı moda geçildi.")
                                except Exception as e: send_telegram_msg("❌ Kapatma hatası: {}".format(e))
                                    
                            elif text == "/sil":
                                send_telegram_msg(".\n" * 60 + "🧹 Siber ekran temizlendi ve sıfırlandı.")
                            
                            elif text.startswith("/duyuru "):
                                duyuru = text.replace("/duyuru ", "").replace(" ", r"\s")
                                execute_ts6_command("gm msg={}".format(duyuru))
                                send_telegram_msg("📢 Global duyuru sunucuya iletildi.")
                                
                            elif text == "/afktemizle":
                                data = get_ts6_all_data()
                                count = 0
                                for c in data['clients']:
                                    if int(c.get('client_idle_time', 0)) > 900000:
                                        execute_ts6_command("clientkick clid={} reasonid=5 reasonmsg=AFK_Kaldiginiz_Icin_Atildiniz".format(c['clid']))
                                        count += 1
                                send_telegram_msg("🧹 Temizlik tamamlandı. {} AFK kullanıcı atıldı.".format(count))
                                
                            elif text == "/help" or text == "/start":
                                help_msg = """🤖 Uthane TS6 Komuta Botu
            
🌟 /yonet - AKTİF KULLANICILARI BUTONLARLA YÖNET
🌟 /banliste - BANLILARI LİSTELE VE TEK TIKLA AÇ
📊 /durum - Sunucu aktiflik ve ping bilgisi
📋 /liste - Kullanıcıları ve odalarını listeler
🗄️ /sicil [isim] VEYA hepsi - Veritabanı sorgusu yapar
🎯 /hedef [isim] - Hedef belirler, girince uyarır
🔒 /sifre [şifre] - Sunucuya şifre koyar/kaldırır
👁️ /info [isim] - Aktif istihbarat çeker
🚨 /kilitle - Sunucuyu kilitler
✅ /ac - Sunucu kilitlenmeyi iptal eder
📢 /duyuru [mesaj] - Kırmızı bülten geçer
🟢 /baslat - TeamSpeak motorunu çalıştırır
🔴 /durdur - TeamSpeak sunucusunu kapatır
🧹 /afktemizle - AFK kalanları atar
🗑️ /sil - Bot ekranını temizler
ℹ️ /help - Bu menüyü gösterir"""
                                send_telegram_msg(help_msg)
        except Exception as e:
            time.sleep(5)

def connection_tracker():
    global KNOWN_CLIENTS, FIRST_RUN, HUNTED_USERS
    while True:
        time.sleep(10) 
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(TS3_HOST, port=TS3_PORT, username=TS3_USER, password=TS3_PASS, timeout=5)
            shell = ssh.invoke_shell(); shell.send("use 1\n"); time.sleep(1.0)
            while shell.recv_ready(): shell.recv(65536)
            shell.send("clientlist -times\n"); out = ""; start = time.time()
            while True:
                if shell.recv_ready(): out += shell.recv(65536).decode("utf-8", errors="ignore")
                if "error id=" in out or time.time() - start > 2: break
                time.sleep(0.05)
            ssh.close()
            
            lines = out.split('\n'); results = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith('error id=') or line.startswith('TS3') or line.startswith('Welcome'): continue
                results.extend(parse_ts_line(line))
            
            current_clients_clids = []
            now = get_tr_time()
            
            for c in results:
                if (c.get('client_nickname') and 'serveradmin' not in str(c.get('client_nickname')).lower() and 'siber' not in str(c.get('client_nickname')).lower()): 
                    clid = c['clid']
                    nick = c['client_nickname'].replace(r'\s', ' ')
                    current_clients_clids.append(clid)
                    
                    if clid not in KNOWN_CLIENTS and not FIRST_RUN:
                        conn_ms = int(c.get('connection_connected_time', 0))
                        join_time = now - datetime.timedelta(milliseconds=conn_ms)
                        KNOWN_CLIENTS[clid] = {'nick': nick, 'join_time': join_time}
                        send_telegram_msg("🟢 [GİRİŞ] {} bağlandı. (Saat: {})".format(nick, join_time.strftime('%H:%M:%S')))
                        
                        for target in HUNTED_USERS:
                            if target in nick.lower():
                                send_telegram_msg("🚨 HEDEF SUNUCUDA: '{}' az önce giriş yaptı! Gözler üzerinde.".format(nick))
                                break
                        
                    elif FIRST_RUN:
                        conn_ms = int(c.get('connection_connected_time', 0))
                        join_time = now - datetime.timedelta(milliseconds=conn_ms)
                        KNOWN_CLIENTS[clid] = {'nick': nick, 'join_time': join_time}
            
            if FIRST_RUN:
                FIRST_RUN = False
                continue

            for clid in list(KNOWN_CLIENTS.keys()):
                if clid not in current_clients_clids:
                    data = KNOWN_CLIENTS[clid]
                    quit_t = now
                    join_t = data['join_time']
                    dur = int((quit_t - join_t).total_seconds())
                    
                    h, rem = divmod(dur, 3600); m, s = divmod(rem, 60)
                    msg = "{} isimli kullanıcı {}'da sunucuya giriş yaptı, {}'da sunucudan çıkış yaptı. Sunucuda geçirdiği süre {} saat {} dakika {} saniye.".format(data['nick'], join_t.strftime('%H:%M:%S'), quit_t.strftime('%H:%M:%S'), h, m, s)
                    
                    with open(SESSION_LOG_FILE, 'a') as f: f.write(msg + "\n")
                    send_telegram_msg("🔴 [ÇIKIŞ] {} ayrıldı. (Saat: {})\n⏳ Süre: {}s {}d {}sn".format(data['nick'], quit_t.strftime('%H:%M:%S'), h, m, s))
                    
                    del KNOWN_CLIENTS[clid]
        except: pass

def connect_chat_socket():
    global CHAT_SOCKET, PM_HISTORY
    while True:
        try:
            import paramiko, time, re, logging
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(TS3_HOST, port=TS3_PORT, username=TS3_USER, password=TS3_PASS, timeout=10)
            shell = ssh.invoke_shell()
            shell.send("use 1\n")
            time.sleep(1.0)
            while shell.recv_ready(): shell.recv(65536)
            shell.send("clientupdate client_nickname=Siber\\sMerkez\\s(Destek)\n")
            time.sleep(0.5)
            shell.send("servernotifyregister event=textprivate\n")
            CHAT_SOCKET = shell
            while True:
                if shell.recv_ready():
                    data = shell.recv(4096).decode('utf-8', errors='ignore')
                    if not data: break
                    if "notifytextmessage" in data and "targetmode=1" in data:
                        msg_match = re.search(r'msg=([^\s]+)', data)
                        clid_match = re.search(r'invokerid=(\d+)', data)
                        name_match = re.search(r'invokername=([^\s]+)', data)
                        if msg_match and clid_match:
                            msg = msg_match.group(1).replace(r'\s', ' ').replace(r'\/', '/')
                            clid = clid_match.group(1)
                            name = name_match.group(1).replace(r'\s', ' ') if name_match else "Kullanıcı"
                            try:
                                now = get_tr_time()
                                time_str = now.strftime('%H:%M')
                            except: time_str = "Şimdi"
                            if clid not in PM_HISTORY: PM_HISTORY[clid] = {"name": name, "msgs": []}
                            else: PM_HISTORY[clid]["name"] = name
                            PM_HISTORY[clid]["msgs"].append({"from": name, "msg": msg, "time": time_str})
                else: time.sleep(0.1)
        except Exception:
            CHAT_SOCKET = None
            time.sleep(5)
        finally:
            CHAT_SOCKET = None
            try: ssh.close()
            except: pass

threading.Thread(target=connection_tracker, daemon=True).start()
threading.Thread(target=connect_chat_socket, daemon=True).start()

# --- ROUTE'LAR ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    t, pc = get_theme_vars()
    if request.method == 'POST':
        if request.form['username'] == PANEL_USER and request.form['password'] == PANEL_PASS:
            session['logged_in'] = True; return redirect(url_for('index'))
        else:
            return render_template_string(LOGIN_PAGE, error="Hatalı kullanıcı adı veya şifre.", p_color=pc)
    return render_template_string(LOGIN_PAGE, p_color=pc)

@app.route('/logout')
def logout(): session.pop('logged_in', None); return redirect(url_for('login'))

@app.route('/toggle_theme')
@login_required
def toggle_theme():
    session['theme'] = 'red' if session.get('theme') != 'red' else 'blue'
    flash("Tema değiştirildi.", "success")
    return redirect(request.referrer or url_for('index'))

@app.route('/clear_sessions', methods=['POST'])
@login_required
def clear_sessions():
    open(SESSION_LOG_FILE, 'w').close(); flash("Bağlantı geçmişi temizlendi.", "warning")
    return redirect(url_for('index', page='sessions'))

@app.route('/')
@login_required
def index():
    page = request.args.get('page', 'dashboard')
    t, pc = get_theme_vars()
    
    server_online = is_ts6_running()
    data = get_ts6_all_data() if server_online else {'clients': [], 'bans': [], 'channels': [], 'groups': [], 'info': {}}
    external_ip = request.host.split(':')[0]
    
    if page == 'sessions': p_title = "İzleme Kayıtları"; content = PAGE_SESSIONS
    elif page == 'channels': p_title = "Oda Yönetimi"; content = PAGE_CHANNELS
    elif page == 'chat': p_title = "Sistem Logları"; content = PAGE_CHAT
    elif page == 'settings': p_title = "Ayarlar"; content = PAGE_SETTINGS
    elif page == 'roles': p_title = "Rol Yönetimi"; content = PAGE_ROLES
    else: 
        p_title = data['info'].get('virtualserver_name', 'Sunucu Adı').replace(r'\s', ' ')
        content = PAGE_DASHBOARD
    
    html = BASE_LAYOUT.replace('__PAGE_CONTENT__', content)
    ts3_logs = get_ts3_core_logs() if page == 'chat' else []
    
    return render_template_string(html, page=page, page_title=p_title, server_online=server_online, info=data['info'], clients=data['clients'], bans=data['bans'], channels=data['channels'], groups=data['groups'], logs=get_logs(), session_logs=get_session_logs(), ts3_logs=ts3_logs, pm_history=PM_HISTORY, theme=t, p_color=pc, external_ip=external_ip, ts3_voice_port=TS3_VOICE_PORT)

@app.route('/api/chat_sync')
@login_required
def api_chat_sync():
    return app.response_class(json.dumps(PM_HISTORY), mimetype='application/json')

@app.route('/api/send_pm', methods=['POST'])
@login_required
def api_send_pm():
    clid = request.form.get('clid')
    msg = request.form.get('msg', '').replace(' ', r'\s')
    if msg and CHAT_SOCKET:
        try:
            CHAT_SOCKET.send(("sendtextmessage targetmode=1 target={} msg={}\n".format(clid, str(msg).replace(" ", r"\s"))).encode("utf-8"))
            
            now = get_tr_time()
            time_str = now.strftime('%H:%M')
            
            if clid not in PM_HISTORY: PM_HISTORY[clid] = {"name": "Kullanıcı", "msgs": []}
            PM_HISTORY[clid]["msgs"].append({"from": "Sen", "msg": request.form.get('msg'), "time": time_str})
            
            return app.response_class(json.dumps({"status": "ok"}), mimetype='application/json')
        except: pass
    return app.response_class(json.dumps({"status": "error"}), mimetype='application/json')

@app.route('/sys_action', methods=['POST'])
@login_required
def handle_sys_action():
    action = request.form.get('action')
    try:
        subprocess.run([SYSTEMCTL_PATH, action, "ts6.service"])
        flash("Sistem motoru '{}' edildi.".format(action), "warning")
        time.sleep(2)
    except: pass
    return redirect(url_for('index', page='settings'))

@app.route('/lockdown', methods=['POST'])
@login_required
def handle_lockdown():
    state = request.form.get('state')
    if state == 'on':
        execute_ts6_command("serveredit virtualserver_password=LOCKDOWN_{}".format(uuid.uuid4().hex[:8]))
        execute_ts6_command("gm msg=Sistem_Kilitlendi!")
        flash("Sunucu Kilitlendi! Yüksek güvenlik aktif.", "error")
    else:
        execute_ts6_command("serveredit virtualserver_password=")
        execute_ts6_command("gm msg=Kilit_Acildi.")
        flash("Sunucu Kilidi Açıldı.", "success")
    return redirect(url_for('index', page='settings'))

@app.route('/update_server', methods=['POST'])
@login_required
def handle_update_server():
    sname = request.form.get('sname', '').replace(' ', r'\s')
    swel = request.form.get('swelcome', '').replace(' ', r'\s')
    spass = request.form.get('spass', '').replace(' ', r'\s')
    cmd = "serveredit virtualserver_name={} virtualserver_welcomemessage={}".format(sname, swel)
    if spass: cmd += " virtualserver_password={}".format(spass)
    else: cmd += " virtualserver_password=" 
    execute_ts6_command(cmd)
    flash("Ayarlar güncellendi.", "success")
    return redirect(url_for('index', page='settings'))

@app.route('/update_panel_pass', methods=['POST'])
@login_required
def update_panel_pass():
    new_pass = request.form.get('new_panel_pass', '').strip()
    if new_pass:
        try:
            path = os.path.abspath(__file__)
            with open(path, 'r', encoding='utf-8') as f: c = f.read()
            c = re.sub(r'(PANEL_USER,\s*PANEL_PASS\s*=\s*["\'].*?["\'],\s*)["\'].*?["\']', r'\g<1>"{}"'.format(new_pass.replace('"', '\\"')), c)
            with open(path, 'w', encoding='utf-8') as f: f.write(c)
            flash("Panel giriş şifresi başarıyla değiştirildi. Yeniden giriş yapın.", "success")
            session.pop('logged_in', None)
            threading.Thread(target=lambda: (time.sleep(1), subprocess.run([SYSTEMCTL_PATH, "restart", "tspanel.service"])), daemon=True).start()
            return redirect(url_for('login'))
        except: flash("Şifre değiştirilirken hata oluştu.", "error")
    return redirect(url_for('index', page='settings'))

@app.route('/mass_action', methods=['POST'])
@login_required
def handle_mass_action():
    action = request.form.get('action')
    msg = request.form.get('msg', 'Sistem_Karari').replace(' ', r'\s')
    data = get_ts6_all_data()
    if action == 'poke_all':
        for c in data['clients']: execute_ts6_command("clientpoke clid={} msg={}".format(c['clid'], msg))
        flash("Herkese dürtme gönderildi.", "warning")
    elif action == 'afk_kick':
        for c in data['clients']:
            if int(c.get('client_idle_time', 0)) > 900000:
                execute_ts6_command("clientkick clid={} reasonid=5 reasonmsg=AFK".format(c['clid']))
        flash("AFK olanlar sunucudan atıldı.", "success")
    return redirect(url_for('index', page='settings'))

@app.route('/global_action', methods=['POST'])
@login_required
def handle_global_action():
    msg = request.form.get('msg', '').replace(' ', r'\s')
    if msg: execute_ts6_command("gm msg={}".format(msg)); flash("Anons gönderildi.", "success")
    return redirect(request.referrer or url_for('index'))

@app.route('/channel_action', methods=['POST'])
@login_required
def handle_channel_action():
    action, cid = request.form.get('action'), request.form.get('cid')
    cname, cpw = request.form.get('cname', '').replace(' ', r'\s'), request.form.get('cpw', '').replace(' ', r'\s')
    if action == 'create':
        cmd = "channelcreate channel_name={} channel_flag_permanent=1".format(cname)
        if cpw: cmd += " channel_password={}".format(cpw)
        execute_ts6_command(cmd); flash("Oda oluşturuldu.", "success")
    elif action == 'edit': execute_ts6_command("channeledit cid={} channel_name={}".format(cid, cname)); flash("Oda güncellendi.", "warning")
    elif action == 'delete': execute_ts6_command("channeldelete cid={} force=1".format(cid)); flash("Oda silindi.", "error")
    return redirect(url_for('index', page='channels'))

@app.route('/role_action', methods=['POST'])
@login_required
def handle_role_action():
    action, sgid, gname = request.form.get('action'), request.form.get('sgid'), request.form.get('gname', '').replace(' ', r'\s')
    if action == 'create': execute_ts6_command("servergroupadd name={}".format(gname)); flash("Rol oluşturuldu.", "success")
    elif action == 'rename': execute_ts6_command("servergrouprename sgid={} name={}".format(sgid, gname)); flash("Rol güncellendi.", "warning")
    elif action == 'delete': execute_ts6_command("servergroupdel sgid={} force=1".format(sgid)); flash("Rol silindi.", "error")
    return redirect(url_for('index', page='roles'))

@app.route('/advanced_perm_action', methods=['POST'])
@login_required
def handle_advanced_perm():
    action, sgid = request.form.get('action'), request.form.get('sgid')
    if action == 'fix_admin':
        for p in ["i_group_modify_power", "i_group_member_add_power", "i_group_member_remove_power", "i_permission_modify_power", "i_client_modify_power", "i_client_permission_modify_power", "i_channel_modify_power", "i_client_kick_power", "i_client_ban_power", "b_virtualserver_modify_name", "b_virtualserver_modify_password", "b_virtualserver_modify_hostmessage", "b_virtualserver_modify_maxclients", "b_serverquery_login", "b_virtualserver_create"]:
            val = "1" if p.startswith("b_") else "75"
            execute_ts6_command("servergroupaddperm sgid={} permsid={} permvalue={} permnegated=0 permskip=0".format(sgid, p, val))
        flash("Temel yetkiler gruba zorla geri verildi.", "success")
    elif action == 'add_perm':
        p_id = request.form.get('custom_permsid') or request.form.get('permsid')
        p_val = request.form.get('permvalue', '1')
        if p_id: execute_ts6_command("servergroupaddperm sgid={} permsid={} permvalue={} permnegated=0 permskip=0".format(sgid, p_id.replace(' ', r'\s'), p_val)); flash("Yetki işlendi.", "warning")
    return redirect(url_for('index', page='roles'))

@app.route('/send_pm', methods=['POST'])
@login_required
def handle_pm():
    clid = request.form.get('clid')
    msg = request.form.get('msg', '').replace(' ', r'\s')
    if msg and CHAT_SOCKET:
        try:
            CHAT_SOCKET.send(("sendtextmessage targetmode=1 target={} msg={}\n".format(clid, str(msg).replace(" ", r"\s"))).encode("utf-8"))
            now = get_tr_time()
            time_str = now.strftime('%H:%M')
            if clid not in PM_HISTORY: PM_HISTORY[clid] = {"name": "Kullanıcı", "msgs": []}
            PM_HISTORY[clid]["msgs"].append({"from": "Sen", "msg": request.form.get('msg'), "time": time_str})
            flash("Mesaj gönderildi.", "success")
        except:
            flash("Bağlantı koptu, mesaj iletilemedi.", "error")
    else:
        flash("Canlı Destek motoru çevrimdışı.", "error")
    return redirect(request.referrer or url_for('index'))

@app.route('/action', methods=['POST'])
@login_required
def handle_action():
    clid, cldbid, action, extra = request.form.get('clid'), request.form.get('cldbid'), request.form.get('action'), request.form.get('extra', '')
    msg = request.form.get('msg', '').replace(' ', r'\s') or r'Sistem\sKarari'
    if action == 'move': execute_ts6_command("clientmove clid={} cid={}".format(clid, extra)); flash("Kullanıcı taşındı.", "success")
    elif action == 'timeban': execute_ts6_command("banclient clid={} time={} banreason={}".format(clid, extra, msg)); flash("Kullanıcı yasaklandı.", "error")
    elif action == 'poke': execute_ts6_command("clientpoke clid={} msg={}".format(clid, msg)); flash("Kullanıcı dürtüldü.", "warning")
    elif action == 'kick': execute_ts6_command("clientkick clid={} reasonid=5 reasonmsg={}".format(clid, msg)); flash("Kullanıcı atıldı.", "error")
    elif action == 'ban': execute_ts6_command("banclient clid={} time=0 banreason={}".format(clid, msg)); flash("Kalıcı yasaklandı.", "error")
    elif action == 'addgroup': execute_ts6_command("servergroupaddclient sgid={} cldbid={}".format(msg, cldbid)); flash("Yetki verildi.", "success")
    elif action == 'delgroup': execute_ts6_command("servergroupdelclient sgid={} cldbid={}".format(msg, cldbid)); flash("Yetki alındı.", "warning")
    return redirect(url_for('index', page='dashboard'))

@app.route('/unban', methods=['POST'])
@login_required
def handle_unban():
    for bid in request.form.get('banid', '').split(','):
        if bid.strip(): execute_ts6_command("bandel banid={}".format(bid.strip()))
    flash("Yasak kaldırıldı.", "success")
    return redirect(request.referrer or url_for('index'))

@app.route('/export_logs')
@login_required
def export_logs():
    try:
        with open(LOG_FILE, 'r') as f: content = f.read()
    except: content = "Log bulunamadi."
    return Response(content, mimetype="text/plain", headers={"Content-disposition": "attachment; filename=ts6_security_log.txt"})

@app.route('/export_snapshot')
@login_required
def export_snapshot():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(TS3_HOST, port=TS3_PORT, username=TS3_USER, password=TS3_PASS, timeout=5)
        shell = ssh.invoke_shell(); shell.send("use 1\n"); time.sleep(1.0)
        while shell.recv_ready(): shell.recv(65536) 
        shell.send("serversnapshotcreate\n"); out = ""; start = time.time()
        while True:
            if shell.recv_ready(): out += shell.recv(65536).decode("utf-8", errors="ignore")
            if "error id=" in out or time.time() - start > 15: break
            time.sleep(0.1)
        ssh.close()
        return Response(out.split('error id=')[0].strip(), mimetype="text/plain", headers={"Content-disposition": "attachment; filename=Yedek_{}.bak".format(datetime.datetime.now().strftime('%Y-%m-%d_%H-%M'))})
    except: return "Yedekleme alinirken hata olustu.", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)