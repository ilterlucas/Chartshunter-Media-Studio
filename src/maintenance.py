from __future__ import annotations
import hashlib, json, os, shutil, subprocess, sys, time
from pathlib import Path

WEEK=7*24*3600; MONTH=30*24*3600
APP_DIR=Path(os.environ.get("CHARTSHUNTER_APP_DIR") or Path(__file__).resolve().parent)
DATA_DIR=Path(os.environ.get("CHARTSHUNTER_DATA_DIR") or (Path(os.environ.get("LOCALAPPDATA",Path.home()))/"ChartshunterMediaStudio"))
STATE_FILE=DATA_DIR/"maintenance_state.json"; USAGE_FILE=DATA_DIR/"usage.json"; STATUS_FILE=DATA_DIR/"setup_status.json"
LOG_DIR=DATA_DIR/"logs"; LOG_DIR.mkdir(parents=True,exist_ok=True); LOG_FILE=LOG_DIR/"maintenance.log"
REQ_FILE=APP_DIR/"requirements.txt"; LOCK=DATA_DIR/"maintenance.lock"
WHISPER_CACHE=Path(os.environ.get("CHARTSHUNTER_WHISPER_CACHE") or (DATA_DIR/"cache"/"whisper")); WHISPER_CACHE.mkdir(parents=True,exist_ok=True)
WHISPER_REPOS={"tiny":"Systran/faster-whisper-tiny","base":"Systran/faster-whisper-base","small":"Systran/faster-whisper-small","medium":"Systran/faster-whisper-medium"}

def log(msg):
    try:
        with LOG_FILE.open("a",encoding="utf-8") as f: f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ")+msg+"\n")
    except Exception: pass

def status(msg,pct,detail="",running=True):
    try: STATUS_FILE.write_text(json.dumps({"status":msg,"percent":float(pct),"detail":detail,"running":bool(running),"updated_at":time.time()},ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception: pass

def load(path):
    try: return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception: return {}
def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+".tmp"); tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8"); tmp.replace(path)
def hidden():
    if os.name!="nt": return {}
    kw={}
    try: kw["creationflags"]=subprocess.CREATE_NO_WINDOW
    except Exception: pass
    try:
        si=subprocess.STARTUPINFO(); si.dwFlags|=subprocess.STARTF_USESHOWWINDOW; si.wShowWindow=0; kw["startupinfo"]=si
    except Exception: pass
    return kw
def req_hash(): return hashlib.sha256(REQ_FILE.read_bytes()).hexdigest()
def due(st,key,interval): return time.time()-float(st.get(key,0) or 0)>=interval
def run(cmd,timeout=1800):
    log("RUN: "+" ".join(map(str,cmd)))
    try:
        p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout,**hidden()); log("RC=%s %s"%(p.returncode,(p.stdout or "")[-2500:].replace("\n"," | "))); return p.returncode==0
    except Exception as e: log("ERR: "+repr(e)); return False
def acquire():
    try:
        if LOCK.exists() and time.time()-LOCK.stat().st_mtime<4*3600: return False
        LOCK.write_text(str(os.getpid()),encoding="utf-8"); return True
    except Exception: return False

def install_requirements(st,force=False):
    current=req_hash()
    if not force and st.get("requirements_hash")==current:
        return True
    start=time.time(); status("Bileşenler hazırlanıyor",35,"İlk kurulumda birkaç dakika sürebilir")
    cmd=[sys.executable,"-m","pip","install","--disable-pip-version-check","--prefer-binary","-r",str(REQ_FILE)]
    # Arayüz açık kalsın; kullanıcı süreyi görebilsin diye işlem arka planda çalışırken heartbeat yaz.
    log("RUN: "+" ".join(cmd))
    try:
        pip_log = LOG_DIR / "pip_install.log"
        with pip_log.open("a", encoding="utf-8") as stream:
            stream.write("\n" + time.strftime("[%Y-%m-%d %H:%M:%S] ") + "requirements install\n")
            stream.flush()
            p=subprocess.Popen(cmd,stdout=stream,stderr=subprocess.STDOUT,text=True,**hidden())
            while p.poll() is None:
                elapsed=int(time.time()-start); status("Bileşenler hazırlanıyor",45,f"Geçen süre: {elapsed//60:02}:{elapsed%60:02} • uygulama kullanılabilir")
                time.sleep(1.5)
        log("requirements pip RC=%s; ayrıntı: %s"%(p.returncode,pip_log))
        if p.returncode!=0: return False
        st["requirements_hash"]=current; st["requirements_ready_at"]=time.time(); save(STATE_FILE,st); return True
    except Exception as e: log("pip error: "+repr(e)); return False

def main():
    if not acquire(): return
    repair="--repair" in sys.argv; ensure="--ensure" in sys.argv
    st=load(STATE_FILE); usage=load(USAGE_FILE)
    try:
        if not install_requirements(st,force=repair):
            status("Bileşen kurulumu tamamlanamadı",0,"Kontrol sekmesinden sistem kontrolü yap",False); return 2
        status("Temel bileşenler hazır",78,"Güncelleme kontrolleri arka planda",True)

        # Hafif downloader araçları haftalık; ilk kurulumdan sonra uygulamayı engellemez.
        if repair or due(st,"tools_check",WEEK):
            status("İndirme motorları kontrol ediliyor",82,"Haftalık bakım",True)
            run([sys.executable,"-m","pip","install","--disable-pip-version-check","--upgrade","yt-dlp","gallery-dl","streamlink","you-get","curl_cffi"],1200)
            st["tools_check"]=time.time(); save(STATE_FILE,st)

        # Whisper sadece gerçekten kullanılan modeller için haftalık revision kontrolü. Aynıysa indirme yok.
        whisper=usage.get("whisper",{}) if isinstance(usage.get("whisper"),dict) else {}; models=list((whisper.get("details") or {}).keys()) if isinstance(whisper.get("details"),dict) else []
        if models and (repair or due(st,"whisper_check",WEEK)):
            status("Whisper modeli kontrol ediliyor",88,"Model aynıysa indirme yapılmaz",True)
            try:
                from huggingface_hub import model_info, snapshot_download
                revs=st.get("whisper_revisions",{}) if isinstance(st.get("whisper_revisions"),dict) else {}
                for model in models:
                    repo=WHISPER_REPOS.get(model)
                    if not repo: continue
                    try:
                        sha=model_info(repo).sha; old=revs.get(model)
                        if old is None: revs[model]=sha; log(f"Whisper {model}: baseline {sha}")
                        elif sha and sha!=old:
                            status(f"Whisper {model} güncelleniyor",90,"Yeni model revizyonu bulundu",True); snapshot_download(repo_id=repo,cache_dir=str(WHISPER_CACHE)); revs[model]=sha
                        else: log(f"Whisper {model}: current")
                    except Exception as e: log(f"Whisper {model} check error: {e}")
                st["whisper_revisions"]=revs
            except Exception as e: log("Whisper maintenance unavailable: "+repr(e))
            st["whisper_check"]=time.time(); save(STATE_FILE,st)

        # Chromium büyük: yalnızca browser gerçekten kullanıldıysa ve ayda bir.
        if usage.get("browser") and (repair or due(st,"browser_check",MONTH)):
            status("Dahili browser kontrol ediliyor",93,"Büyük indirme sadece gerekiyorsa yapılır",True)
            run([sys.executable,"-m","playwright","install","chromium"],1800); st["browser_check"]=time.time(); save(STATE_FILE,st)

        # FFmpeg / aria2 eksikse aylık bakımda sessizce kurmayı dene.
        if repair or due(st,"system_tools_check",MONTH):
            status("Sistem araçları kontrol ediliyor",96,"FFmpeg / aria2",True)
            if os.name=="nt" and shutil.which("winget"):
                if not shutil.which("ffmpeg"): run(["winget","install","--id","Gyan.FFmpeg","-e","--accept-package-agreements","--accept-source-agreements"],1800)
                if not shutil.which("aria2c"): run(["winget","install","--id","aria2.aria2","-e","--accept-package-agreements","--accept-source-agreements"],1800)
            st["system_tools_check"]=time.time(); save(STATE_FILE,st)

        status("Hazır",100,"Tüm rutin kontroller tamamlandı",False); return 0
    finally:
        try: LOCK.unlink(missing_ok=True)
        except Exception: pass

if __name__=="__main__": raise SystemExit(main() or 0)
