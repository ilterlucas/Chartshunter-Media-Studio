from __future__ import annotations
import json, os, subprocess, sys, time
from pathlib import Path
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(APP_DIR))) / "ChartshunterMediaStudio"
RUNTIME_DIR = DATA_DIR / "runtime"
VENV_DIR = RUNTIME_DIR / ".venv"
APP_FILE = APP_DIR / "app.py"
MAINT_FILE = APP_DIR / "maintenance.py"
STATUS_FILE = DATA_DIR / "setup_status.json"
LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "bootstrap.log"
WHISPER_CACHE = DATA_DIR / "cache" / "whisper"
for p in (RUNTIME_DIR, LOG_DIR, WHISPER_CACHE): p.mkdir(parents=True, exist_ok=True)

def write_status(status, percent, detail="", running=True):
    try:
        STATUS_FILE.write_text(json.dumps({"status":status,"percent":float(percent),"detail":detail,"running":bool(running),"updated_at":time.time()},ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception: pass

def log(msg):
    try:
        with LOG_FILE.open("a",encoding="utf-8") as f: f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ")+msg+"\n")
    except Exception: pass

def hidden_kwargs():
    if os.name != "nt": return {}
    kw={}
    try: kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    except Exception: pass
    try:
        si=subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow=0; kw["startupinfo"]=si
    except Exception: pass
    return kw

def base_python(gui=False):
    exe=Path(sys.executable)
    if os.name == "nt":
        if gui:
            if exe.name.lower()=="python.exe":
                p=exe.with_name("pythonw.exe")
                if p.exists(): return p
            return exe
        if exe.name.lower()=="pythonw.exe":
            p=exe.with_name("python.exe")
            if p.exists(): return p
    return exe

def env_for_app():
    env=os.environ.copy()
    py=VENV_DIR/("Scripts/python.exe" if os.name=="nt" else "bin/python")
    if py.exists(): env["CHARTSHUNTER_TOOL_PYTHON"] = str(py)
    env["CHARTSHUNTER_DATA_DIR"] = str(DATA_DIR)
    env["CHARTSHUNTER_WHISPER_CACHE"] = str(WHISPER_CACHE)
    env["CHARTSHUNTER_APP_DIR"] = str(APP_DIR)
    env["CHARTSHUNTER_RUNTIME_DIR"] = str(RUNTIME_DIR)
    return env

def ensure_venv_for_repair():
    py=VENV_DIR/("Scripts/python.exe" if os.name=="nt" else "bin/python")
    if py.exists(): return py
    write_status("Onarım ortamı hazırlanıyor",15,"Bu sadece Repair & Update için gerekir")
    p=subprocess.run([str(base_python(False)),"-m","venv",str(VENV_DIR)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,**hidden_kwargs())
    log((p.stdout or "")[-4000:])
    if p.returncode != 0 or not py.exists(): raise RuntimeError("Onarım çalışma ortamı oluşturulamadı")
    return py

def launch_app():
    env=env_for_app()
    write_status("Hazır",100,"Açılışta büyük bileşen kurulmaz; seçenek kullanım anında sunulur",False)
    subprocess.Popen([str(base_python(True)),str(APP_FILE)],cwd=str(APP_DIR),env=env,**hidden_kwargs())

def main():
    repair = "--repair" in sys.argv
    if repair:
        py=ensure_venv_for_repair(); env=env_for_app(); env["CHARTSHUNTER_TOOL_PYTHON"] = str(py)
        write_status("Onarım ve tam güncelleme",20,"Tüm isteğe bağlı bileşenler kontrol ediliyor")
        p=subprocess.run([str(py),str(MAINT_FILE),"--repair"],cwd=str(APP_DIR),env=env,**hidden_kwargs())
        if p.returncode != 0: raise RuntimeError("Onarım tamamlanamadı. Log klasörünü kontrol et.")
        write_status("Onarım tamamlandı",100,"Ana uygulamayı açabilirsin",False); return
    launch_app()

if __name__=="__main__":
    try: main()
    except Exception as e:
        log("FATAL: "+repr(e)); write_status("Başlatma hatası",0,str(e),False); raise
