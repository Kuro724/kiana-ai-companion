"""
fix_qt5_path.py - Adds Qt5\bin to the user's PATH registry key so that
QtWebEngineProcess.exe (spawned as a child process) can find Qt5Core.dll.
Run this once with: python fix_qt5_path.py
"""
import os
import site
import winreg

# Find the Qt5 bin directory
qt5_bin = None
candidates = []
try:
    usp = site.getusersitepackages()
    if isinstance(usp, str):
        candidates.append(usp)
    else:
        candidates += usp
except Exception:
    pass
candidates += site.getsitepackages() if hasattr(site, 'getsitepackages') else []

for sp in candidates:
    candidate = os.path.join(sp, 'PyQt5', 'Qt5', 'bin')
    if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, 'Qt5Core.dll')):
        qt5_bin = candidate
        break

if not qt5_bin:
    print("ERROR: Could not find PyQt5/Qt5/bin directory!")
    exit(1)

print(f"Found Qt5 bin: {qt5_bin}")

# Read current user PATH from registry
key = winreg.OpenKey(
    winreg.HKEY_CURRENT_USER,
    'Environment',
    0,
    winreg.KEY_READ | winreg.KEY_WRITE
)

try:
    val, reg_type = winreg.QueryValueEx(key, 'PATH')
except FileNotFoundError:
    val = ''
    reg_type = winreg.REG_EXPAND_SZ

# Remove old PyQt5 path entries and prepend new one
parts = [p for p in val.split(';') if p and 'PyQt5' not in p]
parts.insert(0, qt5_bin)
new_val = ';'.join(parts)

winreg.SetValueEx(key, 'PATH', 0, winreg.REG_EXPAND_SZ, new_val)
winreg.CloseKey(key)

print(f"SUCCESS: User PATH updated. Qt5Core.dll path registered.")
print(f"  {qt5_bin}")
print("")
print("NOTE: Open a NEW command prompt for the change to take effect.")
print("Then run: python mascot.py")
