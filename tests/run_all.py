"""Run every Finance Hub test (synthetic data only):  python tests/run_all.py   → exit code 0 when all pass."""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    tests = sorted(HERE.glob('test_*.py'))
    failed = []
    for t in tests:
        t0 = time.time()
        r = subprocess.run([sys.executable, str(t)], capture_output=True, text=True, cwd=HERE)
        ok = r.returncode == 0
        print(f"{'PASS' if ok else 'FAIL'}  {t.name:28} {time.time() - t0:5.1f}s")
        if not ok:
            failed.append(t.name)
            print('\n'.join('      ' + l for l in (r.stdout + r.stderr).strip().splitlines()[-25:]))
    print(f'{len(tests) - len(failed)}/{len(tests)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
