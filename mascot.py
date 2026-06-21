import os
import sys
import ctypes
import threading
import math
import time
import json
import base64
import requests

# ── Fix: redirect QtWebEngine disk cache to a local writable folder ──────────
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.qt_cache')
os.makedirs(_CACHE_DIR, exist_ok=True)
os.environ.setdefault('QTWEBENGINE_DISK_CACHE_DIR', _CACHE_DIR)
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = (
    os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', '') +
    ' --disk-cache-dir=' + _CACHE_DIR
).strip()

# ── Fix: add Qt5 DLL directory so QtWebEngineProcess.exe can find Qt5Core.dll ─
import site as _site
def _fix_qt5_dll_path():
    candidates = []
    try:
        usp = _site.getusersitepackages()
        candidates += [usp] if isinstance(usp, str) else usp
    except Exception:
        pass
    candidates += _site.getsitepackages() if hasattr(_site, 'getsitepackages') else []
    for sp in candidates:
        qt5_bin = os.path.join(sp, 'PyQt5', 'Qt5', 'bin')
        if os.path.isdir(qt5_bin) and os.path.exists(os.path.join(qt5_bin, 'Qt5Core.dll')):
            try:
                os.add_dll_directory(qt5_bin)
            except AttributeError:
                pass
            os.environ['PATH'] = qt5_bin + os.pathsep + os.environ.get('PATH', '')
            proc = os.path.join(qt5_bin, 'QtWebEngineProcess.exe')
            if os.path.exists(proc):
                os.environ['QTWEBENGINEPROCESS_PATH'] = proc
            print(f"Qt5 DLL path registered: {qt5_bin}")
            return
    print("Warning: Qt5/bin not found.")
_fix_qt5_dll_path()

# ── Try backends in order: pywebview → PyQt5 → Tkinter ──────────────────────

# 1. pywebview — uses Windows Edge WebView2, no Qt DLL issues
USE_PYWEBVIEW = False
try:
    import webview
    USE_PYWEBVIEW = True
    print("Backend: pywebview (Edge WebView2) ✓")
except Exception as _pwe:
    print(f"pywebview not available: {_pwe}")

# 2. PyQt5 fallback
USE_PYQT5 = False
if not USE_PYWEBVIEW:
    try:
        from PyQt5 import QtCore, QtGui, QtWidgets
        from PyQt5.QtCore import Qt, QUrl, QPoint, QEvent
        from PyQt5.QtWidgets import QApplication, QMainWindow, QMenu, QAction
        from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage, QWebEngineSettings, QWebEngineProfile
        USE_PYQT5 = True
        print("Backend: PyQt5 WebEngine ✓")
    except Exception as _qt_err:
        print(f"PyQt5 not available: {_qt_err}")

# MCI Audio player for Windows (zero deps)
winmm = ctypes.windll.winmm

def play_audio_mci(file_path):
    try:
        abs_path = os.path.abspath(file_path)
        winmm.mciSendStringW("close kiana_tts", None, 0, 0)
        winmm.mciSendStringW(f'open "{abs_path}" type mpegvideo alias kiana_tts', None, 0, 0)
        winmm.mciSendStringW("play kiana_tts", None, 0, 0)
    except Exception as e:
        print("MCI audio playback error:", e)


# ═══════════════════════════════════════════════════════════════════════════════
# BACKEND 1 — pywebview (Edge WebView2) — PRIMARY, no Qt DLL issues
# ═══════════════════════════════════════════════════════════════════════════════
if USE_PYWEBVIEW:
    KIANA_URL = "http://127.0.0.1:5000/static/mascot.html"
    _pywebview_window = None

    class KianaAPI:
        """Python ↔ JS bridge exposed as window.pywebview.api.*"""

        def open_web_ui(self):
            import webbrowser
            webbrowser.open("http://127.0.0.1:5000")

        def share_screen(self):
            threading.Thread(target=self._do_share_screen, daemon=True).start()

        def _do_share_screen(self):
            try:
                from PIL import ImageGrab
                import io
                screenshot = ImageGrab.grab()
                buf = io.BytesIO()
                screenshot.save(buf, format='PNG')
                image_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
                base_url = f"http://127.0.0.1:{os.getenv('PORT', '5000')}"
                res = requests.post(f"{base_url}/api/screenshot",
                                    json={"image_b64": image_b64}, timeout=30).json()
                response_text = res.get("response", "")
                emotion = res.get("emotion", "Curious")
                safe = response_text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
                _js(f"window.receiveKianaMessage && window.receiveKianaMessage('{safe}', '{emotion}');")
                tts = requests.post(f"{base_url}/api/voice-tts",
                                    json={"text": response_text}, timeout=30).json()
                if tts.get("audio_url"):
                    _js(f"window.playAudioUrl && window.playAudioUrl('{tts['audio_url']}');")
            except Exception as e:
                print(f"Screen share error: {e}")

    def _js(code: str):
        """Run JavaScript in the pywebview window safely."""
        global _pywebview_window
        if _pywebview_window:
            try:
                _pywebview_window.evaluate_js(code)
            except Exception as e:
                print(f"JS eval error: {e}")

    def on_wake_word():
        _js("window.showWakeIndicator && window.showWakeIndicator();")

    def on_wake_response(user_text, bot_response, emotion, audio_url):
        safe = bot_response.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
        _js(f"window.receiveKianaMessage && window.receiveKianaMessage('{safe}', '{emotion}');")
        if audio_url:
            _js(f"window.playAudioUrl && window.playAudioUrl('{audio_url}');")

    def run_pywebview():
        global _pywebview_window
        api = KianaAPI()

        # Get screen dimensions for bottom-right positioning
        try:
            import ctypes
            user32 = ctypes.windll.user32
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
        except Exception:
            sw, sh = 1920, 1080

        W, H = 260, 500
        x = sw - W - 40
        y = sh - H - 60

        _pywebview_window = webview.create_window(
            title='Kiana',
            url=KIANA_URL,
            width=W,
            height=H,
            x=x,
            y=y,
            frameless=True,
            on_top=True,
            transparent=True,
            js_api=api,
            min_size=(200, 300),
            background_color='#000000',
            easy_drag=False,
        )

        print("Kiana 3D Desktop Mascot running (Edge WebView2 + Transparent Window)")

        # Start wake word listener
        def _start_wake():
            time.sleep(2)  # wait for window to load
            try:
                import wake_word
                listener = wake_word.get_listener(
                    on_wake=on_wake_word,
                    on_response=on_wake_response
                )
                listener.start()
            except Exception as e:
                print(f"Wake word init failed: {e}")

        threading.Thread(target=_start_wake, daemon=True).start()

        webview.start(debug=False)


# ═══════════════════════════════════════════════════════════════════════════════
# BACKEND 2 — PyQt5 WebEngine (fallback if pywebview not available)
# ═══════════════════════════════════════════════════════════════════════════════
if USE_PYQT5 and not USE_PYWEBVIEW:
    class Kiana3DMascot(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SubWindow)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.web_view = QWebEngineView()
            self.web_view.setStyleSheet("background: transparent;")
            self.web_view.page().setBackgroundColor(Qt.transparent)
            settings = self.web_view.settings()
            settings.setAttribute(QWebEngineSettings.WebGLEnabled, True)
            settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            self.web_view.page().featurePermissionRequested.connect(self.handle_permission)
            self.web_view.load(QUrl("http://127.0.0.1:5000/static/mascot.html"))
            self.setCentralWidget(self.web_view)
            self.width_val = 320
            self.height_val = 460
            self.resize(self.width_val, self.height_val)
            screen = QApplication.primaryScreen().geometry()
            self.move(screen.width() - self.width_val - 50, screen.height() - self.height_val - 80)
            self.web_view.installEventFilter(self)
            self.drag_position = QPoint()
            print("Kiana 3D Desktop Mascot running (PyQt5 WebEngine + Transparent Window)")

        def handle_permission(self, security_origin, feature):
            if feature in (QWebEnginePage.MediaAudioCapture, QWebEnginePage.MediaAudioVideoCapture):
                self.web_view.page().setFeaturePermission(
                    security_origin, feature, QWebEnginePage.PermissionGrantedByUser)

        def eventFilter(self, obj, event):
            if obj == self.web_view:
                if event.type() == QEvent.MouseButtonPress:
                    if event.button() == Qt.LeftButton:
                        self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
                        return True
                    elif event.button() == Qt.RightButton:
                        self.show_context_menu(event.globalPos())
                        return True
                elif event.type() == QEvent.MouseMove:
                    if event.buttons() == Qt.LeftButton and event.y() < 380:
                        self.move(event.globalPos() - self.drag_position)
                        return True
                elif event.type() == QEvent.MouseButtonDblClick:
                    if event.button() == Qt.LeftButton:
                        self.web_view.page().runJavaScript("window.toggleInputBar()")
                        return True
            return super().eventFilter(obj, event)

        def show_context_menu(self, global_pos):
            menu = QMenu(self)
            menu.addAction(QAction("Open Web UI", self, triggered=self.open_web_ui))
            menu.addAction(QAction("Toggle Input Bar (DblClick)", self, triggered=self.toggle_input_bar))
            menu.addAction(QAction("📸 Share Screen with Kiana", self, triggered=self.share_screen))
            menu.addSeparator()
            menu.addAction(QAction("Exit Kiana", self, triggered=QApplication.instance().quit))
            menu.exec_(global_pos)

        def open_web_ui(self):
            import webbrowser; webbrowser.open("http://127.0.0.1:5000")

        def toggle_input_bar(self):
            self.web_view.page().runJavaScript("window.toggleInputBar()")

        def share_screen(self):
            threading.Thread(target=self._do_share_screen, daemon=True).start()

        def _do_share_screen(self):
            try:
                from PIL import ImageGrab
                import io
                screenshot = ImageGrab.grab()
                buf = io.BytesIO()
                screenshot.save(buf, format='PNG')
                image_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
                base_url = f"http://127.0.0.1:{os.getenv('PORT', '5000')}"
                res = requests.post(f"{base_url}/api/screenshot",
                                    json={"image_b64": image_b64}, timeout=30).json()
                response_text = res.get("response", "")
                emotion = res.get("emotion", "Curious")
                safe = response_text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
                self.web_view.page().runJavaScript(
                    f"window.receiveKianaMessage && window.receiveKianaMessage('{safe}', '{emotion}');")
                tts = requests.post(f"{base_url}/api/voice-tts",
                                    json={"text": response_text}, timeout=30).json()
                if tts.get("audio_url"):
                    self.web_view.page().runJavaScript(
                        f"window.playAudioUrl && window.playAudioUrl('{tts['audio_url']}');")
            except Exception as e:
                print(f"Screen share error: {e}")

        def on_wake_word(self):
            self.web_view.page().runJavaScript(
                "window.showWakeIndicator && window.showWakeIndicator();")

        def on_wake_response(self, user_text, bot_response, emotion, audio_url):
            safe = bot_response.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
            self.web_view.page().runJavaScript(
                f"window.receiveKianaMessage && window.receiveKianaMessage('{safe}', '{emotion}');")
            if audio_url:
                self.web_view.page().runJavaScript(
                    f"window.playAudioUrl && window.playAudioUrl('{audio_url}');")


# ═══════════════════════════════════════════════════════════════════════════════
# BACKEND 3 — Tkinter 2D Vector Mascot (ultimate fallback)
# ═══════════════════════════════════════════════════════════════════════════════
import tkinter as tk
from tkinter import messagebox

class KianaVectorMascot:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Kiana Desktop Companion (2D)")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.trans_color = "#ff00ff"
        self.root.config(bg=self.trans_color)
        self.root.attributes("-transparentcolor", self.trans_color)
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        self.width = 300
        self.height = 360
        self.x = self.screen_width - self.width - 50
        self.y = self.screen_height - self.height - 80
        self.root.geometry(f"{self.width}x{self.height}+{self.x}+{self.y}")
        self.canvas = tk.Canvas(self.root, bg=self.trans_color, highlightthickness=0,
                                width=self.width, height=280)
        self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<Double-Button-1>", self.toggle_input)
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Open Web UI", command=self.open_web_ui)
        self.menu.add_command(label="Toggle Input Box", command=self.toggle_input)
        self.menu.add_command(label="Upgrade to 3D Mascot...", command=self.show_upgrade_hint)
        self.menu.add_separator()
        self.menu.add_command(label="Exit Kiana", command=self.root.quit)
        self.canvas.bind("<Button-3>", self.show_menu)
        self.input_frame = tk.Frame(self.root, bg="#14172a", bd=1, relief=tk.SOLID)
        self.input_entry = tk.Entry(self.input_frame, bg="#1e293b", fg="white",
                                    insertbackground="white", font=("Outfit", 10), bd=0)
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, pady=6)
        self.input_entry.bind("<Return>", self.send_message)
        self.send_btn = tk.Button(self.input_frame, text="Send", bg="#3b82f6", fg="white",
                                  font=("Outfit", 9, "bold"), bd=0, command=self.send_message)
        self.send_btn.pack(side=tk.RIGHT, padx=6)
        self.input_visible = False
        self.api_url = "http://127.0.0.1:5000"
        self.breath_offset = 0
        self.breath_dir = 1
        self.is_blinking = False
        self.blink_timer = 0
        self.is_speaking = False
        self.mouth_open_ratio = 0.0
        self.emotion = "Relaxed"
        self.draw_character()
        self.update_tick()
        self.trigger_blink_cycle()
        print("Kiana 2D Mascot running. (Install 'pywebview' to run in full 3D!)")

    def start_drag(self, event):
        self.drag_x = event.x
        self.drag_y = event.y

    def drag(self, event):
        new_x = self.root.winfo_x() + (event.x - self.drag_x)
        new_y = self.root.winfo_y() + (event.y - self.drag_y)
        self.root.geometry(f"+{new_x}+{new_y}")

    def show_menu(self, event):
        self.menu.post(event.x_root, event.y_root)

    def toggle_input(self, event=None):
        if self.input_visible:
            self.input_frame.pack_forget()
            self.input_visible = False
        else:
            self.input_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=10)
            self.input_entry.focus_set()
            self.input_visible = True

    def open_web_ui(self):
        import webbrowser
        webbrowser.open(self.api_url)

    def show_upgrade_hint(self):
        messagebox.showinfo("Upgrade to 3D Mascot",
            "To unlock the premium 3D Mascot, run:\n\npip install pywebview\n\nThen restart mascot.py!")

    def draw_character(self):
        self.canvas.delete("all")
        cx = 150
        cy = 180
        dy = self.breath_offset
        self.canvas.create_polygon(
            [cx-55, cy-40+dy, cx-70, cy+20+dy, cx-60, cy+60+dy, cx-35, cy+30+dy],
            fill="#e2e8f0", outline="#cbd5e1", width=1.5)
        self.canvas.create_polygon(
            [cx+55, cy-40+dy, cx+70, cy+20+dy, cx+60, cy+60+dy, cx+35, cy+30+dy],
            fill="#e2e8f0", outline="#cbd5e1", width=1.5)
        self.canvas.create_polygon(
            [cx-45, cy+80+dy*0.5, cx-30, cy+45+dy*0.8, cx+30, cy+45+dy*0.8, cx+45, cy+80+dy*0.5],
            fill="#cbd5e1", outline="#94a3b8", width=1.5)
        self.canvas.create_polygon(
            [cx-12, cy+25+dy, cx-12, cy+50+dy, cx+12, cy+50+dy, cx+12, cy+25+dy],
            fill="#fce2d6", outline="")
        self.canvas.create_polygon(
            [cx-40, cy-15+dy, cx-40, cy+20+dy, cx-20, cy+40+dy, cx, cy+48+dy,
             cx+20, cy+40+dy, cx+40, cy+20+dy, cx+40, cy-15+dy],
            fill="#fff8f5", outline="")
        self.canvas.create_oval(cx-32, cy+18+dy, cx-18, cy+23+dy, fill="#f43f5e", outline="", stipple="gray25")
        self.canvas.create_oval(cx+18, cy+18+dy, cx+32, cy+23+dy, fill="#f43f5e", outline="", stipple="gray25")
        eyebrow_y = cy - 8 + dy
        if self.emotion in ["Concerned"]:
            self.canvas.create_line(cx-30, eyebrow_y, cx-10, eyebrow_y+4, fill="#64748b", width=3, capstyle=tk.ROUND)
            self.canvas.create_line(cx+30, eyebrow_y, cx+10, eyebrow_y+4, fill="#64748b", width=3, capstyle=tk.ROUND)
        elif self.emotion in ["Happy", "Excited"]:
            self.canvas.create_line(cx-30, eyebrow_y-2, cx-12, eyebrow_y-5, fill="#64748b", width=3, capstyle=tk.ROUND)
            self.canvas.create_line(cx+30, eyebrow_y-2, cx+12, eyebrow_y-5, fill="#64748b", width=3, capstyle=tk.ROUND)
        else:
            self.canvas.create_line(cx-30, eyebrow_y-3, cx-12, eyebrow_y-3, fill="#64748b", width=3, capstyle=tk.ROUND)
            self.canvas.create_line(cx+30, eyebrow_y-3, cx+12, eyebrow_y-3, fill="#64748b", width=3, capstyle=tk.ROUND)
        eye_y = cy + 6 + dy
        if self.is_blinking or self.emotion == "Sleepy":
            self.canvas.create_line(cx-28, eye_y, cx-12, eye_y, fill="#0f172a", width=3.5, capstyle=tk.ROUND)
            self.canvas.create_line(cx+28, eye_y, cx+12, eye_y, fill="#0f172a", width=3.5, capstyle=tk.ROUND)
        elif self.emotion == "Happy":
            self.canvas.create_arc(cx-28, eye_y-8, cx-12, eye_y+8, start=0, extent=180, style=tk.ARC, outline="#0f172a", width=3.5)
            self.canvas.create_arc(cx+12, eye_y-8, cx+28, eye_y+8, start=0, extent=180, style=tk.ARC, outline="#0f172a", width=3.5)
        else:
            self.canvas.create_oval(cx-28, eye_y-12, cx-12, eye_y+12, fill="#0f172a", outline="")
            self.canvas.create_oval(cx-25, eye_y-9, cx-15, eye_y+9, fill="#0ea5e9", outline="")
            self.canvas.create_oval(cx-23, eye_y-7, cx-19, eye_y-1, fill="white", outline="")
            self.canvas.create_oval(cx+12, eye_y-12, cx+28, eye_y+12, fill="#0f172a", outline="")
            self.canvas.create_oval(cx+15, eye_y-9, cx+25, eye_y+9, fill="#0ea5e9", outline="")
            self.canvas.create_oval(cx+17, eye_y-7, cx+21, eye_y-1, fill="white", outline="")
        mouth_y = cy + 28 + dy
        if self.is_speaking:
            open_h = int(12 * self.mouth_open_ratio)
            self.canvas.create_oval(cx-8, mouth_y-open_h//2, cx+8, mouth_y+open_h//2,
                                    fill="#f43f5e", outline="#0f172a", width=2)
        else:
            if self.emotion in ["Happy", "Excited"]:
                self.canvas.create_arc(cx-10, mouth_y-8, cx+10, mouth_y+2,
                                       start=180, extent=180, style=tk.ARC, outline="#0f172a", width=3)
            elif self.emotion == "Concerned":
                self.canvas.create_arc(cx-8, mouth_y, cx+8, mouth_y+8,
                                       start=0, extent=180, style=tk.ARC, outline="#0f172a", width=3)
            else:
                self.canvas.create_line(cx-6, mouth_y, cx+6, mouth_y, fill="#0f172a", width=2.5, capstyle=tk.ROUND)
        self.canvas.create_polygon([cx-42, cy-15+dy, cx-48, cy+30+dy, cx-38, cy+15+dy], fill="#ffffff", outline="#e2e8f0", width=1)
        self.canvas.create_polygon([cx+42, cy-15+dy, cx+48, cy+30+dy, cx+38, cy+15+dy], fill="#ffffff", outline="#e2e8f0", width=1)
        self.canvas.create_polygon([cx-25, cy-25+dy, cx-10, cy-10+dy, cx-15, cy-25+dy], fill="#ffffff", outline="#e2e8f0", width=1)
        self.canvas.create_polygon([cx+25, cy-25+dy, cx+10, cy-10+dy, cx+15, cy-25+dy], fill="#ffffff", outline="#e2e8f0", width=1)
        self.canvas.create_polygon([cx-5, cy-28+dy, cx, cy-5+dy, cx+5, cy-28+dy], fill="#ffffff", outline="#e2e8f0", width=1)
        self.canvas.create_arc(cx-44, cy-45+dy, cx+44, cy-10+dy, start=0, extent=180,
                               style=tk.CHORD, fill="#ffffff", outline="#e2e8f0", width=1)

    def update_tick(self):
        t = time.time() * 2.5
        self.breath_offset = math.sin(t) * 2.5
        if self.is_speaking:
            self.mouth_open_ratio = 0.3 + abs(math.sin(time.time() * 18)) * 0.7
        else:
            self.mouth_open_ratio = 0.0
        self.draw_character()
        self.root.after(33, self.update_tick)

    def trigger_blink_cycle(self):
        self.is_blinking = True
        self.draw_character()
        self.root.after(150, self.end_blink)

    def end_blink(self):
        self.is_blinking = False
        self.draw_character()
        next_blink = int(3000 + (math.sin(time.time()) + 1) * 1500)
        self.root.after(next_blink, self.trigger_blink_cycle)

    def send_message(self, event=None):
        msg = self.input_entry.get().strip()
        if not msg:
            return
        self.input_entry.delete(0, tk.END)
        threading.Thread(target=self.query_api, args=(msg,), daemon=True).start()

    def query_api(self, msg):
        try:
            chat_res = requests.post(f"{self.api_url}/api/chat", json={"message": msg}).json()
            response_text = chat_res.get("response", "")
            self.emotion = chat_res.get("emotion", "Relaxed")
            tts_res = requests.post(f"{self.api_url}/api/voice-tts", json={"text": response_text}).json()
            audio_url = tts_res.get("audio_url")
            if audio_url:
                rel_path = audio_url.replace("/", "\\")
                if rel_path.startswith("\\"):
                    rel_path = rel_path[1:]
                local_audio_path = os.path.join(os.path.dirname(__file__), rel_path)
                if os.path.exists(local_audio_path):
                    self.is_speaking = True
                    threading.Thread(target=play_audio_mci, args=(local_audio_path,), daemon=True).start()
                    duration_ms = max(1500, int(len(response_text) * 85))
                    self.root.after(duration_ms, self.stop_speaking)
            else:
                self.stop_speaking()
        except Exception as e:
            print("API query failed:", e)
            self.stop_speaking()

    def stop_speaking(self):
        self.is_speaking = False
        winmm.mciSendStringW("close kiana_tts", None, 0, 0)

    def run(self):
        self.root.mainloop()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if USE_PYWEBVIEW:
        run_pywebview()

    elif USE_PYQT5:
        app = QApplication(sys.argv)
        _profile = QWebEngineProfile.defaultProfile()
        _profile.setCachePath(_CACHE_DIR)
        _profile.setPersistentStoragePath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '.qt_storage'))
        mascot = Kiana3DMascot()
        mascot.show()
        try:
            import wake_word
            listener = wake_word.get_listener(
                on_wake=mascot.on_wake_word,
                on_response=mascot.on_wake_response)
            listener.start()
        except Exception as _ww_err:
            print(f"Wake word init failed: {_ww_err}")
        sys.exit(app.exec_())

    else:
        # Tkinter 2D fallback
        app = KianaVectorMascot()
        app.run()
