"""Create the Finance Hub shortcuts (Desktop and Start menu) — run by install.bat. Windows only; does nothing elsewhere."""
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def main():
    if sys.platform != 'win32':
        print('Shortcuts are made on Windows only.')
        return 0
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    target = pythonw if pythonw.exists() else Path(sys.executable)
    script = BASE / 'FinanceHub.pyw'
    icon = BASE / 'static' / 'hub.ico'
    ps = (
        "$w = New-Object -ComObject WScript.Shell; "
        "foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { "
        "  $s = $w.CreateShortcut((Join-Path $d 'Finance Hub.lnk')); "
        f"  $s.TargetPath = {ps_quote(target)}; $s.Arguments = {ps_quote(chr(34) + str(script) + chr(34))}; "
        f"  $s.WorkingDirectory = {ps_quote(BASE)}; $s.IconLocation = {ps_quote(icon)}; "
        "  $s.Description = 'Finance Hub - personal finance, organised'; $s.Save() }")
    r = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps], capture_output=True, text=True)
    if r.returncode:
        print('  Shortcuts could not be created:', (r.stderr or r.stdout).strip()[:300])
        print('  You can still start the Hub with run.bat.')
    else:
        print('  Shortcuts: Desktop and Start menu > "Finance Hub".')
    return 0


if __name__ == '__main__':
    sys.exit(main())
