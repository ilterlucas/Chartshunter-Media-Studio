from pathlib import Path
import ast, sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
checks=[]

def check(name, fn):
    try:
        fn(); checks.append((name, True, 'OK'))
    except Exception as e:
        checks.append((name, False, str(e)))

def assert_true(v, msg='assertion failed'):
    if not v: raise AssertionError(msg)

for name in ['app.py','bootstrap.py','maintenance.py','self_test.py']:
    check(f'{name} syntax', lambda n=name: ast.parse((ROOT/n).read_text(encoding='utf-8')))

import app
check('version', lambda: assert_true(app.APP_VERSION=='v40', app.APP_VERSION))
check('group parser', lambda: assert_true(len(app.parse_download_input_grouped('alpha\nhttps://example.com/a\nhttps://example.com/b'))==2))
check('filename sanitize', lambda: assert_true(app.sanitize_file_base('chart hunter: 2026!*')=='chart_hunter_2026'))
check('fatal download detection', lambda: assert_true(app.is_fatal_download_error_text('NameResolutionError: failed to resolve host')))
check('speed parser', lambda: assert_true(bool(app.extract_speed_from_line('[download] 10% of 10MiB at 2.5MiB/s ETA 00:03'))))
app_text=(ROOT/'app.py').read_text(encoding='utf-8')
check('default speed fast', lambda: assert_true('self.dl_speed_mode = tk.StringVar(value="Hızlı")' in app_text))
check('hard mode default ON', lambda: assert_true('self.dl_hard_mode = tk.BooleanVar(value=True)' in app_text))
check('adult profile default ON', lambda: assert_true('self.dl_adult_profile = tk.BooleanVar(value=True)' in app_text))
check('update package map', lambda: assert_true(app.UPDATE_PACKAGE_MAP.get('yt_dlp')=='yt-dlp'))
check('whisper repo map', lambda: assert_true('small' in app.WHISPER_REPOS))
check('no startup warmup install', lambda: assert_true('_start_balanced_startup_warmup' not in app_text))
check('first-session metadata check', lambda: assert_true('_start_first_session_update_check' in app_text))
check('README', lambda: (ROOT.parent/'README.md').read_text(encoding='utf-8'))
check('usage guide', lambda: (ROOT.parent/'docs'/'KULLANIM_KILAVUZU_TR.md').read_text(encoding='utf-8'))

for n,ok,msg in checks:
    print(f"[{'PASS' if ok else 'FAIL'}] {n}: {msg}")
if not all(x[1] for x in checks): sys.exit(1)
print('All static/core checks passed.')
