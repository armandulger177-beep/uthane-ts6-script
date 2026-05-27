from flask import Flask, render_template_string, request, redirect, url_for, session, Response, flash, get_flashed_messages
from functools import wraps
import paramiko, socket, time, logging, subprocess, datetime, threading, glob, os, uuid, urllib.request, urllib.parse, json, re

# --- UTHANE MUTLAK SSH YAMASI ---
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

# --- AYARLAR VE TELEGRAM ---
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

PM_HISTORY = {} 
KNOWN_CLIENTS = {}
HUNTED_USERS = set()
USER_STATES = {} 
FIRST_RUN = True
CHAT_SOCKET = None

app = Flask(__name__)
app.secret_key = "uthane_ts6_v43_whatsapp_key"

# --- DİNAMİK KULLANICI GİRİŞ SİSTEMİ ---
def get_panel_creds():
    try:
        with open("/root/panel_config.json", "r") as f:
            data = json.load(f)
            return data.get("username", "admin"), data.get("password", "UthanePanel123")
    except:
        return "admin", "UthanePanel123"

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
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="bg-emerald-500/10 border border-emerald-500/50 text-emerald-300 text-sm p-4 rounded-xl mb-6 text-center font-semibold">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
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
        setInterval(() => {
            const now = new Date();
            document.getElementById('liveClock').innerText = now.toLocaleDateString('tr-TR', {day:'2-digit',month:'short',year:'numeric'}) + " - " + now.toLocaleTimeString('tr-TR', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
        }, 1000);
    </script>
</body></html>
"""

# SETTINGS ŞABLONU DEĞİŞTİRİLDİ: Kullanıcı Adı ve Şifre güncellenebiliyor
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
        
        <div class="card p-8 border-t-4 border-emerald-500">
            <h3 class="text-xl font-bold text-emerald-400 border-b border-[#1e293b] pb-3 mb-5">Web Panel Giriş Bilgileri</h3>
            <form action="/update_panel_pass" method="POST" class="space-y-4">
                <input type="text" name="new_panel_user" placeholder="Yeni Kullanıcı Adı (Değiştirmeyecekseniz boş bırakın)" class="w-full bg-[#0f172a] border border-[#334155] text-white px-4 py-3 rounded-xl focus:outline-none focus:border-emerald-500 font-medium transition-colors">
                <input type="text" name="new_panel_pass" placeholder="Yeni Şifre" required class="w-full bg-[#0f172a] border border-[#334155] text-white px-4 py-3 rounded-xl focus:outline-none focus:border-emerald-500 font-medium transition-colors">
                <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-3 rounded-xl transition-colors shadow-lg shadow-emerald-600/20">Giriş Bilgilerini Değiştir</button>
            </form>
        </div>
    </div>
    
    <div class="space-y-8">
        <div class="card p-8">
            <h3 class="text-xl font-bold text-white border-b border-[#1e293b] pb-3 mb-5">Sistem Motoru</h3>
            <form action="/sys_action" method="POST" class="flex gap-3">
                <button type="submit" name="action" value="start" class="flex-1 bg-[#0f172a] border border-[#334155] hover:bg-emerald-600 text-white font-bold py-3 rounded-xl text-sm transition-colors">Başlat</button>
                <button type="submit" name="action" value="restart" class="flex-1 bg-[#0f172a] border border-[#334155] hover:bg-amber-500 text-white font-bold py-3 rounded-xl text-sm transition-colors">Yeniden Başlat</button>
                <button type="submit" name="action" value="stop" class="flex-1 bg-[#0f172a] border border-[#334155] hover:bg-rose-600 text-white font-bold py-3 rounded-xl text-sm transition-colors">Kapat</button>
            </form>
        </div>
        
        <div class="card p-8 border-t-4 border-rose-500">
            <h3 class="text-xl font-bold text-rose-400 border-b border-[#1e293b] pb-3 mb-5">Sistem Kilidi (Lockdown)</h3>
            <p class="text-sm text-slate-400 mb-5 font-medium leading-relaxed">Acil bir durumda sunucuya rastgele şifre atar ve tüm girişleri mühürler.</p>
            <form action="/lockdown" method="POST" class="flex gap-3">
                <button type="submit" name="state" value="on" class="flex-1 bg-rose-600 hover:bg-rose-500 text-white font-bold py-3 rounded-xl transition-colors shadow-lg shadow-rose-600/20">Kilitle</button>
                <button type="submit" name="state" value="off" class="flex-1 bg-[#0f172a] border border-[#334155] hover:bg-[#334155] text-white font-bold py-3 rounded-xl transition-colors">Kilidi Aç</button>
            </form>
        </div>
    </div>
</div>
"""
# Not: PAGE_DASHBOARD, PAGE_CHAT, PAGE_CHANNELS, PAGE_ROLES, PAGE_SESSIONS değişkenlerini orijinal dosyanızdaki gibi aynen tuttuğunuzu varsayıyorum (yer kaplamaması için kısalttım).

# Gerekli fonksiyonların orijinal halleri...
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

def execute_ts6_command(command):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(TS3_HOST, port=TS3_PORT, username=TS3_USER, password=TS3_PASS, timeout=5)
        shell = ssh.invoke_shell()
        shell.send("use 1\n"); time.sleep(1.0); shell.send(command + "\n"); time.sleep(0.3); ssh.close()
    except Exception as e: logging.error("Komut Hatasi: {}".format(e))

def is_ts6_running():
    try: return subprocess.run([SYSTEMCTL_PATH, "is-active", "ts6.service"], capture_output=True, text=True).stdout.strip() == "active"
    except: return False

def get_ts6_all_data():
    data = {'clients': [], 'bans': [], 'channels': [], 'groups': [], 'info': {}}
    # ... Orijinal veri çekme kodlarınız ...
    return data

@app.route('/login', methods=['GET', 'POST'])
def login():
    t, pc = get_theme_vars()
    real_user, real_pass = get_panel_creds()
    
    if request.method == 'POST':
        if request.form['username'] == real_user and request.form['password'] == real_pass:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            return render_template_string(LOGIN_PAGE, error="Hatalı kullanıcı adı veya şifre.", p_color=pc)
    return render_template_string(LOGIN_PAGE, p_color=pc)

@app.route('/logout')
def logout(): session.pop('logged_in', None); return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    page = request.args.get('page', 'dashboard')
    t, pc = get_theme_vars()
    server_online = is_ts6_running()
    data = get_ts6_all_data() if server_online else {'clients': [], 'bans': [], 'channels': [], 'groups': [], 'info': {}}
    external_ip = request.host.split(':')[0]
    
    if page == 'settings': p_title = "Ayarlar"; content = PAGE_SETTINGS
    # Diğer sayfaları burada atayabilirsiniz...
    else: p_title = "Genel Bakış"; content = PAGE_SETTINGS # Örnek
    
    html = BASE_LAYOUT.replace('__PAGE_CONTENT__', content)
    return render_template_string(html, page=page, page_title=p_title, server_online=server_online, info=data['info'], theme=t, p_color=pc, external_ip=external_ip, ts3_voice_port=TS3_VOICE_PORT)

@app.route('/update_panel_pass', methods=['POST'])
@login_required
def update_panel_pass():
    new_user = request.form.get('new_panel_user', '').strip()
    new_pass = request.form.get('new_panel_pass', '').strip()
    curr_user, curr_pass = get_panel_creds()
    
    final_user = new_user if new_user else curr_user
    
    if new_pass:
        try:
            with open("/root/panel_config.json", "w") as f:
                json.dump({"username": final_user, "password": new_pass}, f)
            flash("Giriş bilgileri başarıyla değiştirildi. Lütfen yeniden giriş yapın.", "success")
            session.pop('logged_in', None)
            return redirect(url_for('login'))
        except: 
            flash("Bilgiler güncellenirken hata oluştu.", "error")
    return redirect(url_for('index', page='settings'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
