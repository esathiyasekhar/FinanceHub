import sys, time, zipfile, tempfile, glob, importlib.util
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import tkinter
pkg = Path(sys.argv[1])
from importlib.machinery import SourceFileLoader
spec = importlib.util.spec_from_loader('setup_mod', SourceFileLoader('setup_mod', str(pkg / 'setup.pyw')))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
calls = {}
S.full_install = lambda opts, log: (calls.update(opts), log('fake install done'))
S.wizard()
btn = lambda text: next(w for w in tkinter.ALL if w.kw.get('text', '').startswith(text) or str(w.kw.get('text')).startswith(text))
nxt = next(w for w in tkinter.ALL if w.kw.get('text') == 'Next >')
for i in range(3):
    nxt['command']()
    texts = [w.kw.get('text', '') for w in tkinter.ALL if isinstance(w.kw.get('text'), str)]
print('pages driven; summary shown:', any('Program:' in t for t in texts))
# drain after() callbacks until the worker finishes
for _ in range(50):
    if not tkinter.AFTER: break
    fn = tkinter.AFTER.pop(0); time.sleep(0.05); fn()
print('install called with', sorted(calls))
assert calls['program'] and calls['data'] and calls['start'] is True
print('wizard flow OK')
