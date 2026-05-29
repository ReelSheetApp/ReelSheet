"""
ReelSheet v0.1.14
Video thumbnail picker and contact sheet generator
https://github.com/ReelSheetApp/ReelSheet
License: MIT

Changes:
  v0.1.2 — fixed playback; pygame OGG extraction audio
  v0.1.7 — Diagnostics window
  v0.1.8 — python-vlc primary audio; header audio indicator; mutable speaker icon
  v0.1.9 — Three-pane draggable sash layout restored from v0.1.5:
              Outer pane: file list | content area
              Inner pane: thumbnail column (Current + Proposed stacked) | video
            Sash positions saved/restored via reelsheet_prefs.json.
            Browse Folder + folder path moved to full-width topbar above panes.
            Volume row + export buttons integrated into transport row.
            Fixed SyntaxWarning in v0.1.8 docstring (invalid escape sequence).
  v0.1.10 — Canvas resize redraw for current/proposed thumbnails.
             Aspect-correct filmstrip thumbnails with resize rebuild.
             Stereo-style Diagnostics player VU.
             Auto-load last folder.
             Unique export filenames.
             run.bat uses pythonw to avoid persistent console window.
  v0.1.11 — Hardened FFmpeg resolution for pythonw launches.
  v0.1.12 — Smoother sash movement: non-opaque pane resize and deferred redraws.
  v0.1.13 — Custom grid-based sash handles replace Tk PanedWindow splitters.
  v0.1.14 — Rubber-band sash drag; panes resize once on release to avoid paint trails.
"""

import customtkinter as ctk
import cv2
import subprocess
import threading
import tempfile
import shutil
import os
import time
import json
import math
from pathlib import Path
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime

# ── Audio stack detection ─────────────────────────────────────
# Priority: VLC > pygame > silent

VLC_OK    = False
PYGAME_OK = False
vlc       = None

try:
    import vlc as _vlc
    _test = _vlc.Instance("--intf=dummy")
    _test.release()
    vlc    = _vlc
    VLC_OK = True
except Exception as _vlc_err:
    pass

if not VLC_OK:
    try:
        import pygame as _pygame
        _pygame.mixer.pre_init(44100, -16, 2, 1024)
        _pygame.mixer.init()
        import pygame
        PYGAME_OK = True
    except Exception:
        pass

# ── App config ────────────────────────────────────────────────
APP_NAME    = "ReelSheet"
APP_VERSION = "0.1.14"
ACCENT      = "#0078d4"
GREEN       = "#107c10"
RED         = "#c42b1c"
YELLOW      = "#c07c10"
BG          = "#1a1a1a"
BG2         = "#141414"
BG3         = "#0d0d0d"
BORDER      = "#2a2a2a"
SASH_COLOR  = "#3a3a3a"
FG          = "#e0e0e0"
FG2         = "#888888"
FG3         = "#555555"

LOG_FILE    = Path(__file__).parent / "reelsheet_audio.log"
PREFS_FILE  = Path(__file__).parent / "reelsheet_prefs.json"

def resolve_exe(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    candidates = [
        Path("C:/ffmpeg/bin") / f"{name}.exe",
        Path(__file__).parent / "ffmpeg" / "bin" / f"{name}.exe",
        Path(__file__).parent / "ffmpeg" / f"{name}.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None

FFMPEG_EXE  = resolve_exe("ffmpeg")
FFPROBE_EXE = resolve_exe("ffprobe")

if FFMPEG_EXE:
    ffmpeg_dir = str(Path(FFMPEG_EXE).parent)
    os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
if FFPROBE_EXE:
    ffprobe_dir = str(Path(FFPROBE_EXE).parent)
    if ffprobe_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffprobe_dir + os.pathsep + os.environ.get("PATH", "")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── Prefs ─────────────────────────────────────────────────────
def load_prefs() -> dict:
    try:
        if PREFS_FILE.exists():
            return json.loads(PREFS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def save_prefs(prefs: dict):
    try:
        PREFS_FILE.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except Exception:
        pass

# ── Audio event log ───────────────────────────────────────────
_audio_log = []
_log_lock  = threading.Lock()

def audio_log(msg: str, color: str = "#cccccc"):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    with _log_lock:
        _audio_log.append((ts, msg, color))
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# ── Diagnostics Window ────────────────────────────────────────
class DiagnosticsWindow:
    METER_W  = 180
    METER_H  = 120
    POLL_MS  = 120

    def __init__(self, root, picker):
        self._root     = root
        self._picker   = picker
        self._win      = None
        self._poll_job = None
        self._visible  = False
        self._log_seen = 0
        self._extract_start_time   = None
        self._last_play_time       = None
        self._last_audio_play_time = None

    def toggle(self):
        if self._visible:
            self.hide()
        else:
            self.show()

    def show(self):
        if self._win is None or not self._win.winfo_exists():
            self._build()
        self._win.deiconify()
        self._win.lift()
        self._visible = True
        self._poll()

    def hide(self):
        self._visible = False
        if self._poll_job:
            self._root.after_cancel(self._poll_job)
            self._poll_job = None
        if self._win and self._win.winfo_exists():
            self._win.withdraw()

    def destroy(self):
        self._visible = False
        if self._poll_job:
            self._root.after_cancel(self._poll_job)
        if self._win and self._win.winfo_exists():
            self._win.destroy()

    def _build(self):
        win = tk.Toplevel(self._root)
        win.title("ReelSheet — Diagnostics")
        win.geometry("740x680")
        win.configure(bg=BG)
        win.protocol("WM_DELETE_WINDOW", self.hide)
        win.resizable(True, True)
        self._win = win

        hdr = tk.Frame(win, bg=BG2, height=36)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="  \U0001f50d  Diagnostics",
                 bg=BG2, fg=FG,
                 font=("Consolas", 13, "bold")).pack(side="left", padx=4)

        stack_txt = ("VLC (direct)" if VLC_OK
                     else "pygame (extraction)" if PYGAME_OK
                     else "NO AUDIO")
        stack_col = ("#27ae60" if VLC_OK
                     else "#f39c12" if PYGAME_OK
                     else "#c42b1c")
        tk.Label(hdr, text=f"  Audio: {stack_txt}",
                 bg=BG2, fg=stack_col,
                 font=("Consolas", 10, "bold")).pack(side="left", padx=8)

        btn_frame = tk.Frame(hdr, bg=BG2)
        btn_frame.pack(side="right", padx=8)
        tk.Button(btn_frame, text="Clear Log", bg="#2a2a2a", fg=FG2,
                  relief="flat", bd=0, padx=8,
                  command=self._clear_log).pack(side="left", padx=(0, 4))
        tk.Button(btn_frame, text="Save Log", bg="#2a2a2a", fg=FG2,
                  relief="flat", bd=0, padx=8,
                  command=self._save_log).pack(side="left")

        meter_row = tk.Frame(win, bg=BG)
        meter_row.pack(fill="x", padx=8, pady=(8, 4))

        self._meters = {}
        meter_defs = [
            ("EXTRACT", "extract", "OGG extraction\n(pygame fallback only)"),
            ("PLAYER",  "player",  "VLC / pygame\nplayer state"),
            ("VOLUME",  "volume",  "Output volume\nlevel"),
        ]
        for label, key, subtitle in meter_defs:
            col = tk.Frame(meter_row, bg=BG2,
                           highlightbackground=BORDER, highlightthickness=1)
            col.pack(side="left", fill="both", expand=True,
                     padx=(0, 6) if key != "volume" else 0)
            tk.Label(col, text=label, bg=BG2, fg="#aaaaaa",
                     font=("Consolas", 10, "bold")).pack(pady=(6, 0))
            tk.Label(col, text=subtitle, bg=BG2, fg=FG3,
                     font=("Consolas", 8), justify="center").pack(pady=(0, 2))
            c = tk.Canvas(col, bg=BG3, width=self.METER_W,
                          height=self.METER_H, highlightthickness=0)
            c.pack(padx=6, pady=(0, 4))
            val_lbl = tk.Label(col, text="—", bg=BG2, fg=FG2,
                               font=("Consolas", 9))
            val_lbl.pack(pady=(0, 6))
            self._meters[key] = {"canvas": c, "label": val_lbl}

        grid_frame = tk.Frame(win, bg=BG2,
                              highlightbackground=BORDER, highlightthickness=1)
        grid_frame.pack(fill="x", padx=8, pady=(0, 6))

        self._stat_labels = {}
        fields = [
            ("audio_stack",   "Audio stack"),
            ("vlc_state",     "VLC state"),
            ("vlc_position",  "VLC position"),
            ("vlc_length",    "VLC length"),
            ("extract_state", "Extract state"),
            ("ogg_size",      "OGG size"),
            ("audio_ready",   "audio_ready"),
            ("play_pressed",  "Last Play @"),
            ("audio_called",  "Last _audio_play @"),
        ]
        for row_i, (key, label) in enumerate(fields):
            r = row_i // 3
            c = (row_i % 3) * 2
            tk.Label(grid_frame, text=label + ":", bg=BG2, fg=FG3,
                     font=("Consolas", 9), anchor="e").grid(
                row=r, column=c, sticky="e", padx=(8, 2), pady=2)
            lbl = tk.Label(grid_frame, text="—", bg=BG2, fg=FG2,
                           font=("Consolas", 9), anchor="w")
            lbl.grid(row=r, column=c + 1, sticky="w", padx=(0, 16), pady=2)
            self._stat_labels[key] = lbl

        tk.Label(win, text="EVENT LOG", bg=BG, fg="#aaaaaa",
                 font=("Consolas", 9, "bold")).pack(fill="x", padx=8, pady=(0, 2))
        log_frame = tk.Frame(win, bg=BG3)
        log_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._log_text = tk.Text(
            log_frame, bg=BG3, fg=FG2, font=("Consolas", 9),
            relief="flat", bd=0, state="disabled", wrap="none",
            highlightthickness=0)
        self._log_text.pack(side="left", fill="both", expand=True)
        vsb = tk.Scrollbar(log_frame, command=self._log_text.yview,
                           bg=BG2, troughcolor=BG3)
        vsb.pack(side="right", fill="y")
        self._log_text.configure(yscrollcommand=vsb.set)
        self._log_text.tag_configure("green",  foreground="#27ae60")
        self._log_text.tag_configure("yellow", foreground="#f39c12")
        self._log_text.tag_configure("red",    foreground="#c42b1c")
        self._log_text.tag_configure("blue",   foreground="#0078d4")
        self._log_text.tag_configure("dim",    foreground=FG3)
        self._log_text.tag_configure("white",  foreground=FG)

        audio_log("Diagnostics window opened", "#0078d4")

    # ── Poll ──────────────────────────────────────────────────
    def _poll(self):
        if not self._visible:
            return
        try:
            self._update_meters()
            self._update_status()
            self._flush_log()
        except Exception:
            pass
        self._poll_job = self._root.after(self.POLL_MS, self._poll)

    def _draw_meter(self, key, level, color, text):
        m = self._meters[key]
        c = m["canvas"]
        w, h = self.METER_W, self.METER_H
        c.delete("all")
        seg_h = h / 10
        for i in range(10):
            y0 = h - (i + 1) * seg_h + 1
            y1 = h - i * seg_h - 1
            bg = "#1a2a1a" if i < 7 else ("#2a2a00" if i < 9 else "#2a0000")
            c.create_rectangle(4, y0, w - 4, y1, fill=bg, outline="")
        for i in range(10):
            y0   = h - (i + 1) * seg_h + 1
            y1   = h - i * seg_h - 1
            frac = (i + 1) / 10
            if frac <= level:
                fill = "#27ae60" if i < 7 else "#f39c12" if i < 9 else "#c42b1c"
                c.create_rectangle(4, y0, w - 4, y1, fill=fill, outline="")
        m["label"].configure(text=text, fg=color)

    def _draw_stereo_meter(self, key, left, right, color, text):
        m = self._meters[key]
        c = m["canvas"]
        w, h = self.METER_W, self.METER_H
        c.delete("all")
        lane_w = (w - 18) / 2
        seg_h = h / 10
        for lane, level in enumerate((left, right)):
            x0 = 6 + lane * (lane_w + 6)
            x1 = x0 + lane_w
            for i in range(10):
                y0 = h - (i + 1) * seg_h + 1
                y1 = h - i * seg_h - 1
                bg = "#1a2a1a" if i < 7 else ("#2a2a00" if i < 9 else "#2a0000")
                c.create_rectangle(x0, y0, x1, y1, fill=bg, outline="")
                if (i + 1) / 10 <= level:
                    fill = "#27ae60" if i < 7 else "#f39c12" if i < 9 else "#c42b1c"
                    c.create_rectangle(x0, y0, x1, y1, fill=fill, outline="")
            c.create_text((x0 + x1) / 2, h - 5, text="L" if lane == 0 else "R",
                          fill="#cccccc", font=("Consolas", 8, "bold"))
        m["label"].configure(text=text, fg=color)

    def _update_meters(self):
        p = self._picker

        if VLC_OK:
            self._draw_meter("extract", 0.0, FG3, "N/A (VLC mode)")
        else:
            ogg = os.path.join(p.temp_dir, "audio_track.ogg")
            ogg_exists = os.path.exists(ogg)
            if p._audio_ready and ogg_exists:
                self._draw_meter("extract", 1.0, "#27ae60", "DONE")
            elif ogg_exists:
                self._draw_meter("extract", 0.7, "#f39c12", "WRITING\u2026")
            elif p.current_file:
                self._draw_meter("extract", 0.4, "#0078d4", "EXTRACTING")
            else:
                self._draw_meter("extract", 0.0, FG3, "IDLE")

        if VLC_OK and p._vlc_player:
            state   = p._vlc_player.get_state()
            state_s = str(state).split(".")[-1]
            pos_ms  = p._vlc_player.get_time()
            if state_s == "Playing":
                vol = max(0.0, p._vlc_player.audio_get_volume() / 100.0)
                left, right = stereo_vu_levels(True, vol, time.time())
                self._draw_stereo_meter("player", left, right, "#27ae60",
                                        f"VLC L {int(left*100)}%  R {int(right*100)}%")
            elif state_s == "Paused":
                self._draw_stereo_meter("player", 0.05, 0.05, "#f39c12", "VLC PAUSED")
            elif state_s in ("Stopped", "Ended", "NothingSpecial"):
                self._draw_stereo_meter("player", 0.0, 0.0, FG3, f"VLC {state_s.upper()}")
            else:
                self._draw_stereo_meter("player", 0.0, 0.0, FG2, f"VLC {state_s}")
        elif PYGAME_OK:
            try:
                busy   = pygame.mixer.music.get_busy()
                pos_ms = pygame.mixer.music.get_pos()
                if busy:
                    vol = pygame.mixer.music.get_volume()
                    left, right = stereo_vu_levels(True, vol, time.time())
                    self._draw_stereo_meter("player", left, right, "#27ae60",
                                            f"PG L {int(left*100)}%  R {int(right*100)}%")
                else:
                    self._draw_stereo_meter("player", 0.0, 0.0, FG3, "PG STOPPED")
            except Exception:
                self._draw_stereo_meter("player", 0.0, 0.0, RED, "PG ERROR")
        else:
            self._draw_stereo_meter("player", 0.0, 0.0, RED, "NO AUDIO")

        if VLC_OK and p._vlc_player:
            vol     = p._vlc_player.audio_get_volume() / 100.0
            playing = str(p._vlc_player.get_state()).split(".")[-1] == "Playing"
            self._draw_meter("volume",
                             vol if playing else vol * 0.3,
                             "#27ae60" if playing else FG3,
                             f"{int(vol*100)}%  {'\u25b6' if playing else '\u25a0'}")
        elif PYGAME_OK:
            try:
                vol  = pygame.mixer.music.get_volume()
                busy = pygame.mixer.music.get_busy()
                self._draw_meter("volume",
                                 vol if busy else vol * 0.3,
                                 "#27ae60" if busy else FG3,
                                 f"{int(vol*100)}%  {'\u25b6' if busy else '\u25a0'}")
            except Exception:
                self._draw_meter("volume", 0.0, RED, "ERROR")
        else:
            self._draw_meter("volume", 0.0, RED, "N/A")

    def _update_status(self):
        p   = self._picker
        ogg = os.path.join(p.temp_dir, "audio_track.ogg")

        def _set(key, val, color=FG2):
            lbl = self._stat_labels.get(key)
            if lbl:
                lbl.configure(text=str(val), fg=color)

        _set("audio_stack",
             "VLC (direct)" if VLC_OK else "pygame (extraction)" if PYGAME_OK else "NONE",
             "#27ae60" if VLC_OK else "#f39c12" if PYGAME_OK else RED)

        if VLC_OK and p._vlc_player:
            state  = str(p._vlc_player.get_state()).split(".")[-1]
            pos_ms = p._vlc_player.get_time()
            length = p._vlc_player.get_length()
            _set("vlc_state",    state, "#27ae60" if state == "Playing" else FG2)
            _set("vlc_position", f"{pos_ms} ms" if pos_ms >= 0 else "—")
            _set("vlc_length",   f"{length} ms" if length > 0 else "—")
        else:
            _set("vlc_state",    "N/A" if VLC_OK else "not loaded", FG3)
            _set("vlc_position", "—", FG3)
            _set("vlc_length",   "—", FG3)

        if not VLC_OK:
            if p._audio_ready:
                _set("extract_state", "COMPLETE", "#27ae60")
            elif p.current_file:
                _set("extract_state", "RUNNING", "#f39c12")
            else:
                _set("extract_state", "IDLE", FG3)
            if os.path.exists(ogg):
                _set("ogg_size", f"{os.path.getsize(ogg)/1024:,.0f} KB", "#27ae60")
            else:
                _set("ogg_size", "—", FG3)
            _set("audio_ready", str(p._audio_ready),
                 "#27ae60" if p._audio_ready else "#f39c12")
        else:
            _set("extract_state", "N/A (VLC)", FG3)
            _set("ogg_size",      "N/A (VLC)", FG3)
            _set("audio_ready",   "N/A (VLC)", FG3)

        _set("play_pressed",  self._last_play_time or "—")
        _set("audio_called",  self._last_audio_play_time or "—")

    def _flush_log(self):
        with _log_lock:
            new_entries = _audio_log[self._log_seen:]
            self._log_seen = len(_audio_log)
        if not new_entries:
            return
        self._log_text.configure(state="normal")
        for ts, msg, color in new_entries:
            tag = {
                "#27ae60": "green", "#f39c12": "yellow",
                "#c42b1c": "red",   "#0078d4": "blue",
                FG3: "dim",
            }.get(color, "white")
            self._log_text.insert("end", f"[{ts}] ", "dim")
            self._log_text.insert("end", msg + "\n", tag)
        self._log_text.configure(state="disabled")
        self._log_text.see("end")

    def _clear_log(self):
        global _audio_log
        with _log_lock:
            _audio_log.clear()
        self._log_seen = 0
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def _save_log(self):
        out = filedialog.asksaveasfilename(
            title="Save Log", defaultextension=".log",
            filetypes=[("Log", "*.log"), ("Text", "*.txt")],
            initialfile="reelsheet_audio.log")
        if out:
            with _log_lock:
                entries = list(_audio_log)
            with open(out, "w", encoding="utf-8") as f:
                for ts, msg, _ in entries:
                    f.write(f"[{ts}] {msg}\n")
            audio_log(f"Log saved \u2192 {out}", "#27ae60")

    # ── Event hooks ───────────────────────────────────────────
    def on_file_selected(self, name):
        self._extract_start_time = time.time()
        audio_log(f"File selected: {name}", "#0078d4")

    def on_extract_start(self):
        audio_log("_extract_audio thread started", "#0078d4")

    def on_extract_done(self, path, success):
        if success:
            size_kb = os.path.getsize(path) / 1024 if os.path.exists(path) else 0
            elapsed = time.time() - self._extract_start_time if self._extract_start_time else 0
            audio_log(f"Extraction COMPLETE — {size_kb:,.0f} KB in {elapsed:.1f}s", "#27ae60")
        else:
            audio_log("Extraction FAILED", "#c42b1c")

    def on_play_pressed(self, position, audio_ready):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._last_play_time = ts
        audio_log(
            f"Play pressed @ {format_time(position)} — "
            f"{'VLC' if VLC_OK else 'pygame'} ready={audio_ready}",
            "#27ae60" if audio_ready else "#f39c12")

    def on_audio_play_called(self, position):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._last_audio_play_time = ts
        audio_log(f"_audio_play() called @ {format_time(position)}", "#27ae60")

    def on_audio_play_skipped(self, position, reason):
        audio_log(
            f"_audio_play() SKIPPED @ {format_time(position)} — {reason}",
            "#c42b1c")


# ── Utilities ─────────────────────────────────────────────────
def ffmpeg_available():
    if not FFMPEG_EXE:
        return False
    try:
        subprocess.run([FFMPEG_EXE, "-version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False

def ffprobe_duration(path: str) -> float:
    if not FFPROBE_EXE:
        return 0.0
    try:
        r = subprocess.run(
            [FFPROBE_EXE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15)
        return float(r.stdout.strip())
    except Exception:
        return 0.0

def get_stored_thumb_pos(path: str) -> float:
    if not FFPROBE_EXE:
        return 0.0
    try:
        r = subprocess.run(
            [FFPROBE_EXE, "-v", "error", "-show_entries", "format_tags=comment",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10)
        val = r.stdout.strip()
        if "thumb_pos=" in val:
            return float(val.split("thumb_pos=")[1].split()[0])
    except Exception:
        pass
    return 0.0

def embed_thumbnail(video_path: str, seconds: float, temp_dir: str) -> bool:
    base  = Path(video_path).stem
    thumb = os.path.join(temp_dir, f"{base}_thumb.jpg")
    outf  = os.path.join(Path(video_path).parent, f"{base}_tmp.mp4")
    try:
        subprocess.run(
            [FFMPEG_EXE, "-y", "-ss", str(seconds), "-i", video_path,
             "-frames:v", "1", "-q:v", "2", thumb],
            capture_output=True, timeout=30)
        if not os.path.exists(thumb):
            return False
        subprocess.run(
            [FFMPEG_EXE, "-y", "-i", video_path, "-i", thumb,
             "-map", "0", "-map", "1", "-c", "copy",
             "-disposition:v:1", "attached_pic",
             "-metadata", f"comment=thumb_pos={round(seconds, 3)}", outf],
            capture_output=True, timeout=60)
        if not os.path.exists(outf):
            return False
        os.remove(video_path)
        os.rename(outf, video_path)
        try:
            import ctypes
            ctypes.windll.shell32.SHChangeNotify(0x00000008, 0x0005, video_path, None)
        except Exception:
            pass
        return True
    except Exception:
        return False
    finally:
        try:
            if os.path.exists(thumb):
                os.remove(thumb)
        except Exception:
            pass

def format_time(seconds: float) -> str:
    s = max(0, int(seconds))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}"

def cv_frame_at(cap: cv2.VideoCapture, seconds: float):
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(seconds * fps))
    ok, img = cap.read()
    if not ok:
        return None
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))

def fit_rect(src_w: int, src_h: int, max_w: int, max_h: int) -> tuple[int, int]:
    if src_w <= 0 or src_h <= 0 or max_w <= 0 or max_h <= 0:
        return (0, 0)
    scale = min(max_w / src_w, max_h / src_h)
    return (max(1, int(src_w * scale)), max(1, int(src_h * scale)))

def fit_image_to_box(img: Image.Image, box_w: int, box_h: int) -> Image.Image:
    out = Image.new("RGB", (max(1, box_w), max(1, box_h)), "#000000")
    nw, nh = fit_rect(img.width, img.height, box_w, box_h)
    if nw <= 0 or nh <= 0:
        return out
    fitted = img.copy()
    fitted.thumbnail((nw, nh), Image.LANCZOS)
    x = (box_w - fitted.width) // 2
    y = (box_h - fitted.height) // 2
    out.paste(fitted, (x, y))
    return out

def unique_export_path(folder, base_name: str, ext: str) -> Path:
    folder = Path(folder)
    ext = ext if ext.startswith(".") else f".{ext}"
    candidate = folder / f"{base_name}{ext}"
    if not candidate.exists():
        return candidate
    i = 1
    while True:
        candidate = folder / f"{base_name}_{i:03d}{ext}"
        if not candidate.exists():
            return candidate
        i += 1

def stereo_vu_levels(active: bool, volume: float, phase: float) -> tuple[float, float]:
    if not active or volume <= 0:
        return (0.0, 0.0)
    volume = max(0.0, min(1.0, float(volume)))
    left = (0.52 + 0.30 * math.sin(phase * 5.1)) * volume
    right = (0.50 + 0.28 * math.sin(phase * 4.3 + 1.2)) * volume
    return (max(0.05, min(volume, left)), max(0.05, min(volume, right)))


# ── Thumbnail Picker Tab ───────────────────────────────────────
class ThumbnailPickerTab(ctk.CTkFrame):
    def __init__(self, master, temp_dir: str, **kwargs):
        super().__init__(master, fg_color=BG, **kwargs)
        self.temp_dir             = temp_dir
        self.video_files          = []
        self.current_file         = None
        self.cap                  = None
        self.duration             = 0.0
        self.position             = 0.0
        self.fps                  = 30.0
        self.playing              = False
        self.proposed_ready       = False
        self.file_status          = {}
        self.filmstrip_images     = []
        self.filmstrip_count      = 20
        self._play_job            = None
        self._play_start_wall     = 0.0
        self._play_start_pos      = 0.0
        self._fs_width            = 0
        self._filmstrip_resize_job = None
        self._filmstrip_generation = 0
        self._redraw_jobs         = {}
        self._drag_sash           = None
        self._video_img_ref       = None
        self._canvas_current_ref  = None
        self._canvas_proposed_ref = None
        self._canvas_current_ref_source = None
        self._canvas_proposed_ref_source = None
        self._video_img_ref_source = None
        self._muted               = False
        self._pre_mute            = 0.8
        self._prefs               = load_prefs()
        self.diag                 = None

        # VLC audio
        self._vlc_instance = None
        self._vlc_player   = None
        if VLC_OK:
            try:
                self._vlc_instance = vlc.Instance("--intf=dummy", "--no-video")
                self._vlc_player   = self._vlc_instance.media_player_new()
                audio_log("VLC instance created OK", "#27ae60")
            except Exception as e:
                audio_log(f"VLC instance failed: {e}", "#c42b1c")

        # pygame fallback state
        self._audio_file  = None
        self._audio_ready = False

        self._build_ui()
        self.after(250, self._load_last_dir)

    # ── UI ────────────────────────────────────────────────────
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Top bar: Browse + folder path ─────────────────────
        topbar = ctk.CTkFrame(self, fg_color=BG2, height=40, corner_radius=0)
        topbar.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 4))
        topbar.grid_columnconfigure(1, weight=1)
        topbar.grid_propagate(False)

        ctk.CTkButton(topbar, text="Browse Folder\u2026",
                      width=140, command=self._browse).grid(
            row=0, column=0, padx=(8, 10), pady=5)
        self.folder_label = ctk.CTkLabel(
            topbar, text="No folder selected",
            font=ctk.CTkFont(family="Consolas", size=13),
            text_color=FG, anchor="w")
        self.folder_label.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        # ── Custom split layout: file list | thumbnails | video ─
        body = tk.Frame(self, bg=SASH_COLOR)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, minsize=self._prefs.get("sash_outer", 240))
        body.grid_columnconfigure(1, minsize=8)
        body.grid_columnconfigure(2, weight=1)
        self._body = body
        self._outer_guide = self._make_drag_guide(body)

        # ── Left pane: file list ──────────────────────────────
        left = tk.Frame(body, bg=BG2)
        left.grid(row=0, column=0, sticky="nsew")

        outer_sash = self._make_sash(body, "outer")
        outer_sash.grid(row=0, column=1, sticky="ns")
        self._outer_sash = outer_sash

        self.file_count = tk.Label(
            left, text="", bg=BG2, fg=FG2, font=("Segoe UI", 11))
        self.file_count.pack(side="bottom", fill="x", padx=8, pady=(0, 2))

        btn_bot = tk.Frame(left, bg=BG2)
        btn_bot.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        self.btn_process_all = ctk.CTkButton(
            btn_bot, text="Set All Thumbnails",
            state="disabled", command=self._process_all)
        self.btn_process_all.pack(fill="x")

        list_frame = tk.Frame(left, bg=BG2)
        list_frame.pack(fill="both", expand=True, padx=4, pady=4)
        self.file_list = tk.Listbox(
            list_frame, bg="#111111", fg=FG,
            selectbackground=ACCENT, selectforeground="white",
            relief="flat", bd=0, font=("Consolas", 11),
            activestyle="none", highlightthickness=0, exportselection=False)
        self.file_list.pack(side="left", fill="both", expand=True)
        self.file_list.bind("<<ListboxSelect>>", self._on_file_select)
        sb = tk.Scrollbar(list_frame, command=self.file_list.yview,
                          bg=BG2, troughcolor=BG3)
        sb.pack(side="right", fill="y")
        self.file_list.configure(yscrollcommand=sb.set)

        # ── Content split: thumbnail col | video ──────────────
        content = tk.Frame(body, bg=BG)
        content.grid(row=0, column=2, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, minsize=self._prefs.get("sash_inner", 200))
        content.grid_columnconfigure(1, minsize=8)
        content.grid_columnconfigure(2, weight=1)
        self._content = content
        self._inner_guide = self._make_drag_guide(content)

        # ── Thumbnail column ──────────────────────────────────
        thumb_col = tk.Frame(content, bg=BG)
        thumb_col.grid(row=0, column=0, sticky="nsew")

        inner_sash = self._make_sash(content, "inner")
        inner_sash.grid(row=0, column=1, sticky="ns")
        self._inner_sash = inner_sash

        tk.Label(thumb_col, text="CURRENT THUMBNAIL",
                 bg=BG, fg="#aaaaaa",
                 font=("Consolas", 10, "bold")).pack(
            fill="x", padx=4, pady=(6, 2))
        cur_frame = tk.Frame(thumb_col, bg=BG3)
        cur_frame.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.canvas_current = tk.Canvas(
            cur_frame, bg=BG3, highlightthickness=0)
        self.canvas_current.pack(fill="both", expand=True)
        self.canvas_current.bind(
            "<Configure>",
            lambda _: self._schedule_canvas_redraw(
                self.canvas_current, "_canvas_current_ref"))

        tk.Label(thumb_col, text="PROPOSED FRAME",
                 bg=BG, fg="#aaaaaa",
                 font=("Consolas", 10, "bold")).pack(
            fill="x", padx=4, pady=(4, 2))
        prop_frame = tk.Frame(thumb_col, bg=BG3)
        prop_frame.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.canvas_proposed = tk.Canvas(
            prop_frame, bg=BG3, highlightthickness=0)
        self.canvas_proposed.pack(fill="both", expand=True)
        self.canvas_proposed.bind(
            "<Configure>",
            lambda _: self._schedule_canvas_redraw(
                self.canvas_proposed, "_canvas_proposed_ref"))

        # ── Video + controls column ────────────────────────────
        right = tk.Frame(content, bg=BG)
        right.grid(row=0, column=2, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)

        # Video canvas
        vf = tk.Frame(right, bg="#000")
        vf.grid(row=0, column=0, sticky="nsew", padx=4, pady=(4, 4))
        vf.grid_columnconfigure(0, weight=1)
        vf.grid_rowconfigure(0, weight=1)
        self.video_canvas = tk.Canvas(vf, bg="#000", highlightthickness=0)
        self.video_canvas.grid(row=0, column=0, sticky="nsew")
        self.video_canvas.bind("<Configure>",
                               lambda _: self._schedule_canvas_redraw(
                                   self.video_canvas, "_video_img_ref"))
        self.no_video_label = ctk.CTkLabel(
            vf, text="Select a video from the list",
            font=ctk.CTkFont(size=14), text_color=FG3, fg_color="#000")
        self.no_video_label.place(relx=0.5, rely=0.5, anchor="center")

        # Filmstrip
        fsf = tk.Frame(right, bg="#000", height=88)
        fsf.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 2))
        fsf.grid_propagate(False)
        fsf.grid_columnconfigure(0, weight=1)
        self.filmstrip_canvas = tk.Canvas(
            fsf, bg="#000", highlightthickness=0, height=68)
        self.filmstrip_canvas.grid(row=0, column=0, sticky="ew")
        self.timeline_canvas = tk.Canvas(
            fsf, bg="#0a0a0a", highlightthickness=0, height=18)
        self.timeline_canvas.grid(row=1, column=0, sticky="ew")
        self.filmstrip_canvas.bind("<Button-1>", self._filmstrip_click)
        self.filmstrip_canvas.bind("<Configure>",
                                   lambda e: self._on_filmstrip_resize(e.width))

        # Scrub row
        sr = tk.Frame(right, bg=BG)
        sr.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 2))
        sr.grid_columnconfigure(0, weight=1)
        self.scrub = ctk.CTkSlider(sr, from_=0, to=100, command=self._on_scrub)
        self.scrub.grid(row=0, column=0, sticky="ew")
        self.scrub.set(0)
        self.scrub.configure(state="disabled")
        self.scrub.bind("<ButtonRelease-1>", self._on_scrub_release)
        self.time_label = ctk.CTkLabel(
            sr, text="--:--:-- / --:--:--",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=FG2, width=140)
        self.time_label.grid(row=0, column=1, padx=(8, 0))

        # Transport + volume + export (single row)
        tr = tk.Frame(right, bg=BG)
        tr.grid(row=3, column=0, sticky="ew", padx=4, pady=(0, 4))

        col = 0

        # Volume: icon + slider
        self.vol_icon = ctk.CTkLabel(tr, text="\U0001f50a",
                                     font=ctk.CTkFont(size=16),
                                     fg_color=BG, cursor="hand2")
        self.vol_icon.grid(row=0, column=col, padx=(0, 2))
        self.vol_icon.bind("<Button-1>", self._toggle_mute)
        col += 1
        self.vol_slider = ctk.CTkSlider(
            tr, from_=0, to=1, command=self._on_volume, width=90)
        self.vol_slider.set(0.8)
        self.vol_slider.grid(row=0, column=col, padx=(0, 10))
        self._set_volume(0.8)
        col += 1

        # Transport buttons
        transport_defs = [
            ("\u25c4 10s",  lambda: self._step(-10), False),
            ("\u25c4 1s",   lambda: self._step(-1),  False),
            ("\u25b6  Play", self._toggle_play,       True),
            ("1s \u25ba",   lambda: self._step(1),   False),
            ("10s \u25ba",  lambda: self._step(10),  False),
        ]
        for txt, cmd, is_play in transport_defs:
            b = ctk.CTkButton(
                tr, text=txt,
                width=95 if is_play else 76,
                command=cmd, state="disabled",
                fg_color="#1a3a1a" if is_play else "transparent",
                border_color="#0a5c0a" if is_play else BORDER,
                border_width=1,
                hover_color="#2a4a2a" if is_play else "#333")
            b.grid(row=0, column=col, padx=(0, 4))
            if is_play:
                self.btn_play = b
            col += 1

        tr.grid_columnconfigure(col, weight=1)
        col += 1

        self.btn_export_current = ctk.CTkButton(
            tr, text="\u2193 Current", width=90,
            state="disabled", command=lambda: self._export_frame(True))
        self.btn_export_current.grid(row=0, column=col, padx=(0, 4))
        col += 1

        self.btn_export_proposed = ctk.CTkButton(
            tr, text="\u2193 Proposed", width=90,
            state="disabled", command=lambda: self._export_frame(False))
        self.btn_export_proposed.grid(row=0, column=col)

        self._transport_buttons = [
            w for w in tr.winfo_children()
            if isinstance(w, ctk.CTkButton)
            and w not in (self.btn_export_current, self.btn_export_proposed)
        ]

        # Set thumbnail button
        self.btn_set = ctk.CTkButton(
            right, text="\u2b24  Set This Frame as Thumbnail",
            height=42, font=ctk.CTkFont(size=14),
            fg_color=GREEN, hover_color="#0a5c0a",
            state="disabled", command=self._set_thumbnail)
        self.btn_set.grid(row=4, column=0, sticky="ew", padx=4, pady=(0, 4))

        # Status bar
        self.status = ctk.CTkLabel(
            right, text="Load a folder to begin.",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=FG3, anchor="w", fg_color=BG2,
            corner_radius=4, height=28)
        self.status.grid(row=5, column=0, sticky="ew", padx=4, pady=(0, 4))

        self.after(100, self._apply_sash_positions)

    # ── Sash persistence ───────────────────────────────────────
    def _make_sash(self, parent, which: str):
        sash = tk.Canvas(
            parent, width=8, bg=SASH_COLOR, highlightthickness=0,
            cursor="sb_h_double_arrow")
        sash.create_line(3, 0, 3, 2000, fill="#202020", tags="grip")
        sash.create_line(5, 0, 5, 2000, fill="#505050", tags="grip")
        sash.bind("<Enter>", lambda _e, s=sash: s.configure(bg="#4a4a4a"))
        sash.bind("<Leave>", lambda _e, s=sash: s.configure(bg=SASH_COLOR))
        sash.bind("<Button-1>", lambda e, w=which: self._sash_press(w, e))
        sash.bind("<B1-Motion>", lambda e, w=which: self._sash_drag(w, e))
        sash.bind("<ButtonRelease-1>", lambda e, w=which: self._sash_release(w, e))
        return sash

    def _make_drag_guide(self, parent):
        guide = tk.Frame(
            parent, width=3, bg=ACCENT,
            highlightbackground="#b8dcff", highlightthickness=1)
        guide.place_forget()
        return guide

    def _apply_sash_positions(self):
        self._set_outer_width(self._prefs.get("sash_outer", 240))
        self._set_inner_width(self._prefs.get("sash_inner", 200))

    def _set_outer_width(self, width: int):
        body_w = max(1, self._body.winfo_width())
        width = max(160, min(int(width), max(160, body_w - 420)))
        self._body.grid_columnconfigure(0, minsize=width)
        self._prefs["sash_outer"] = width

    def _set_inner_width(self, width: int):
        content_w = max(1, self._content.winfo_width())
        width = max(120, min(int(width), max(120, content_w - 320)))
        self._content.grid_columnconfigure(0, minsize=width)
        self._prefs["sash_inner"] = width

    def _sash_press(self, which: str, event):
        if which == "outer":
            width = self._prefs.get("sash_outer", 240)
            parent = self._body
            guide = self._outer_guide
        else:
            width = self._prefs.get("sash_inner", 200)
            parent = self._content
            guide = self._inner_guide
        x = max(0, min(width, parent.winfo_width()))
        guide.place(x=x, y=0, relheight=1.0)
        guide.lift()
        self._drag_sash = {
            "which": which,
            "x": event.x_root,
            "width": width,
            "current": width,
            "parent": parent,
            "guide": guide,
        }

    def _sash_drag(self, which: str, event):
        drag = getattr(self, "_drag_sash", None)
        if not drag or drag["which"] != which:
            return
        width = drag["width"] + (event.x_root - drag["x"])
        parent = drag["parent"]
        if which == "outer":
            body_w = max(1, parent.winfo_width())
            width = max(160, min(int(width), max(160, body_w - 420)))
        else:
            content_w = max(1, parent.winfo_width())
            width = max(120, min(int(width), max(120, content_w - 320)))
        drag["current"] = width
        drag["guide"].place_configure(x=width)

    def _sash_release(self, which: str, event):
        self._sash_drag(which, event)
        drag = getattr(self, "_drag_sash", None)
        if drag and drag["which"] == which:
            if which == "outer":
                self._set_outer_width(drag["current"])
            else:
                self._set_inner_width(drag["current"])
            drag["guide"].place_forget()
        self._drag_sash = None
        self._save_sash_positions()
        self._schedule_canvas_redraw(self.canvas_current, "_canvas_current_ref", 40)
        self._schedule_canvas_redraw(self.canvas_proposed, "_canvas_proposed_ref", 40)
        self._schedule_canvas_redraw(self.video_canvas, "_video_img_ref", 40)

    def _save_sash_positions(self, _=None):
        save_prefs(self._prefs)

    # ── Helpers ────────────────────────────────────────────────
    def set_status(self, msg: str, color: str = FG3):
        self.status.configure(text=f"  {msg}", text_color=color)

    def _enable_transport(self, on: bool):
        s = "normal" if on else "disabled"
        for w in self._transport_buttons:
            w.configure(state=s)
        self.scrub.configure(state=s)
        self.btn_set.configure(state=s)
        self.btn_export_current.configure(state=s)

    def _show_on_canvas(self, canvas: tk.Canvas, img, attr: str):
        if img is None:
            canvas.delete("all")
            setattr(self, attr, None)
            setattr(self, f"{attr}_source", None)
            return
        setattr(self, f"{attr}_source", img.copy())
        self._render_canvas_image(canvas, img, attr)

    def _redraw_canvas_image(self, canvas: tk.Canvas, attr: str):
        src = getattr(self, f"{attr}_source", None)
        if src is not None:
            self._render_canvas_image(canvas, src, attr)

    def _schedule_canvas_redraw(self, canvas: tk.Canvas, attr: str, delay_ms: int = 90):
        job = self._redraw_jobs.get(attr)
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._redraw_jobs[attr] = self.after(
            delay_ms, lambda: self._run_scheduled_canvas_redraw(canvas, attr))

    def _run_scheduled_canvas_redraw(self, canvas: tk.Canvas, attr: str):
        self._redraw_jobs.pop(attr, None)
        self._redraw_canvas_image(canvas, attr)

    def _render_canvas_image(self, canvas: tk.Canvas, img, attr: str):
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        if cw < 2 or ch < 2:
            return
        img = img.copy()
        img.thumbnail((cw, ch), Image.LANCZOS)
        tk_img = ImageTk.PhotoImage(img)
        setattr(self, attr, tk_img)
        canvas.delete("all")
        canvas.create_image(cw // 2, ch // 2, anchor="center", image=tk_img)

    def _update_time(self):
        self.time_label.configure(
            text=f"{format_time(self.position)} / {format_time(self.duration)}")

    def _update_cursor(self):
        if self._fs_width <= 0 or self.duration <= 0:
            return
        x = (self.position / self.duration) * self._fs_width
        self.filmstrip_canvas.delete("cursor")
        self.filmstrip_canvas.create_rectangle(
            x - 1.5, 0, x + 1.5, 68, fill=ACCENT, outline="", tags="cursor")

    # ── Volume / mute ──────────────────────────────────────────
    def _set_volume(self, val: float):
        if VLC_OK and self._vlc_player:
            self._vlc_player.audio_set_volume(int(val * 100))
        elif PYGAME_OK:
            try:
                pygame.mixer.music.set_volume(float(val))
            except Exception:
                pass

    def _on_volume(self, val):
        val = float(val)
        if val > 0 and self._muted:
            self._muted = False
            self.vol_icon.configure(text="\U0001f50a")
        self._set_volume(val)

    def _toggle_mute(self, _=None):
        if self._muted:
            self._muted = False
            self.vol_slider.set(self._pre_mute)
            self._set_volume(self._pre_mute)
            self.vol_icon.configure(text="\U0001f50a")
            audio_log("Unmuted", FG3)
        else:
            self._pre_mute = self.vol_slider.get()
            self._muted    = True
            self.vol_slider.set(0)
            self._set_volume(0)
            self.vol_icon.configure(text="\U0001f507")
            audio_log("Muted", FG3)

    # ── Browse ─────────────────────────────────────────────────
    def _browse(self):
        last    = self._prefs.get("last_dir", "")
        initial = last if (last and os.path.isdir(last)) else os.path.expanduser("~")
        path    = filedialog.askdirectory(
            title="Select folder containing MP4 files", initialdir=initial)
        if path:
            path = os.path.abspath(path)
            self._prefs["last_dir"] = path
            save_prefs(self._prefs)
            self._load_folder(path)

    def _load_last_dir(self):
        last = self._prefs.get("last_dir", "")
        if last and os.path.isdir(last):
            self._load_folder(last)

    def _load_folder(self, path: str):
        self.video_files = sorted(
            Path(path).glob("*.mp4"), key=lambda p: p.name.lower())
        self.file_status = {}
        self.file_list.delete(0, tk.END)
        for f in self.video_files:
            self.file_list.insert(tk.END, f"  {f.name}")
        n = len(self.video_files)
        self.folder_label.configure(text=path)
        self.file_count.configure(text=f"{n} MP4 file(s) found")
        self.btn_process_all.configure(state="normal" if n else "disabled")
        self.set_status(f"Folder loaded \u2014 {n} file(s). Select a video.", FG2)

    def _on_file_select(self, _=None):
        sel = self.file_list.curselection()
        if sel:
            self._load_video(self.video_files[sel[0]])

    def _load_video(self, path: Path):
        self._stop_play()
        self.current_file   = path
        self.proposed_ready = False
        self._audio_ready   = False
        self.btn_export_proposed.configure(state="disabled")
        self.set_status(f"Loading {path.name}\u2026", ACCENT)
        self.update_idletasks()

        if self.diag:
            self.diag.on_file_selected(path.name)

        if self.cap:
            self.cap.release()
        self.cap      = cv2.VideoCapture(str(path))
        self.fps      = self.cap.get(cv2.CAP_PROP_FPS) or 30
        total         = self.cap.get(cv2.CAP_PROP_FRAME_COUNT)
        self.duration = (total / self.fps if self.fps > 0
                         else ffprobe_duration(str(path)))

        start         = min(get_stored_thumb_pos(str(path)),
                            max(0, self.duration - 1))
        self.position = start
        self.scrub.configure(to=self.duration)
        self.scrub.set(start)
        self._update_time()
        self._enable_transport(True)
        self.no_video_label.place_forget()
        self._refresh_video_canvas()

        if VLC_OK and self._vlc_player:
            try:
                media = self._vlc_instance.media_new(str(path))
                self._vlc_player.set_media(media)
                audio_log(f"VLC media set: {path.name}", "#0078d4")
            except Exception as e:
                audio_log(f"VLC media_new failed: {e}", "#c42b1c")
        elif PYGAME_OK:
            if self.diag:
                self.after(0, self.diag.on_extract_start)
            threading.Thread(target=self._extract_audio, daemon=True).start()

        threading.Thread(target=self._load_current_thumb, daemon=True).start()
        self._show_on_canvas(self.canvas_proposed, None, "_canvas_proposed_ref")
        self.filmstrip_canvas.delete("all")
        self.timeline_canvas.delete("all")
        self.filmstrip_images = []
        self._filmstrip_generation += 1
        generation = self._filmstrip_generation
        threading.Thread(
            target=self._build_filmstrip, args=(generation,), daemon=True).start()

        stack = ("VLC direct" if VLC_OK
                 else "pygame extraction" if PYGAME_OK
                 else "no audio")
        self.set_status(
            f"Loaded: {path.name}  ({format_time(self.duration)})  [{stack}]", FG2)

    def _refresh_video_canvas(self):
        if self.cap:
            img = cv_frame_at(self.cap, self.position)
            if img:
                self._show_on_canvas(self.video_canvas, img, "_video_img_ref")

    # ── Audio — VLC primary, pygame fallback ───────────────────
    def _audio_play(self, position: float):
        if VLC_OK and self._vlc_player:
            try:
                self._vlc_player.set_time(int(position * 1000))
                self._vlc_player.play()
                if self.diag:
                    self.diag.on_audio_play_called(position)
                audio_log(
                    f"VLC play @ {format_time(position)} ({int(position*1000)} ms)",
                    "#27ae60")
            except Exception as e:
                audio_log(f"VLC play error: {e}", "#c42b1c")
        elif PYGAME_OK:
            if not self._audio_ready or not self._audio_file:
                reason = ("audio_ready=False" if not self._audio_ready
                          else "audio_file=None")
                if self.diag:
                    self.diag.on_audio_play_skipped(position, reason)
                audio_log(
                    f"_audio_play SKIPPED @ {format_time(position)}: {reason}",
                    "#c42b1c")
                return
            try:
                pygame.mixer.music.load(self._audio_file)
                pygame.mixer.music.play(start=position)
                if self.diag:
                    self.diag.on_audio_play_called(position)
                audio_log(f"pygame play(start={position:.2f})", "#27ae60")
            except Exception as e:
                audio_log(f"pygame play error: {e}", "#c42b1c")

    def _audio_pause(self):
        if VLC_OK and self._vlc_player:
            try:
                self._vlc_player.pause()
                audio_log("VLC pause()", FG3)
            except Exception:
                pass
        elif PYGAME_OK:
            try:
                pygame.mixer.music.pause()
                audio_log("pygame pause()", FG3)
            except Exception:
                pass

    def _audio_stop(self):
        if VLC_OK and self._vlc_player:
            try:
                self._vlc_player.stop()
                audio_log("VLC stop()", FG3)
            except Exception:
                pass
        elif PYGAME_OK:
            try:
                pygame.mixer.music.stop()
                audio_log("pygame stop()", FG3)
            except Exception:
                pass

    # ── pygame fallback extraction ─────────────────────────────
    def _extract_audio(self):
        if not PYGAME_OK or not self.current_file:
            return
        out = os.path.join(self.temp_dir, "audio_track.ogg")
        try:
            if os.path.exists(out):
                os.remove(out)
            subprocess.run(
                [FFMPEG_EXE, "-y", "-i", str(self.current_file),
                 "-vn", "-ac", "2", "-ar", "44100", "-q:a", "4", out],
                capture_output=True, timeout=120)
            if os.path.exists(out):
                self._audio_file  = out
                self._audio_ready = True
                if self.diag:
                    self.after(0, lambda: self.diag.on_extract_done(out, True))
            else:
                self._audio_ready = False
                if self.diag:
                    self.after(0, lambda: self.diag.on_extract_done(out, False))
        except Exception as e:
            self._audio_ready = False
            audio_log(f"Extraction exception: {e}", "#c42b1c")

    def _load_current_thumb(self):
        if not self.current_file:
            return
        tmp = os.path.join(self.temp_dir, "current_thumb.jpg")
        for args in [
            [FFMPEG_EXE, "-y", "-i", str(self.current_file),
             "-map", "0:v:1", "-frames:v", "1", "-q:v", "2", tmp],
            [FFMPEG_EXE, "-y", "-ss", "0", "-i", str(self.current_file),
             "-frames:v", "1", "-q:v", "2", tmp],
        ]:
            subprocess.run(args, capture_output=True, timeout=15)
            if os.path.exists(tmp):
                break
        if os.path.exists(tmp):
            try:
                img = Image.open(tmp).copy()
                self.after(0, lambda: self._show_on_canvas(
                    self.canvas_current, img, "_canvas_current_ref"))
            except Exception:
                pass

    # ── Playback ───────────────────────────────────────────────
    def _toggle_play(self):
        if self.playing:
            self._stop_play()
            self._extract_proposed()
        else:
            if self.diag:
                self.diag.on_play_pressed(
                    self.position, True if VLC_OK else self._audio_ready)
            self.playing          = True
            self._play_start_wall = time.time()
            self._play_start_pos  = self.position
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, int(self.position * self.fps))
            self._audio_play(self.position)
            self.btn_play.configure(text="\u23f8  Pause",
                                    fg_color="#3a1a1a",
                                    border_color="#5a0a0a")
            self._play_tick()

    def _stop_play(self):
        self.playing = False
        if self._play_job:
            self.after_cancel(self._play_job)
            self._play_job = None
        self._audio_pause()
        self.btn_play.configure(text="\u25b6  Play",
                                fg_color="#1a3a1a",
                                border_color="#0a5c0a")

    def _play_tick(self):
        if not self.playing or not self.cap:
            return
        wall_pos = self._play_start_pos + (time.time() - self._play_start_wall)
        if wall_pos >= self.duration:
            self.position = self.duration
            self._stop_play()
            self._extract_proposed()
            return

        cap_pos       = self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        frames_behind = int((wall_pos - cap_pos) * self.fps)
        if frames_behind > 0:
            for _ in range(min(frames_behind, 8)):
                self.cap.grab()

        ok, frame = self.cap.read()
        if ok:
            self.position = self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            cw = self.video_canvas.winfo_width()
            ch = self.video_canvas.winfo_height()
            if cw > 1 and ch > 1:
                ih, iw = frame.shape[:2]
                scale  = min(cw / iw, ch / ih)
                nw, nh = int(iw * scale), int(ih * scale)
                frame  = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
            rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            tk_img = ImageTk.PhotoImage(Image.fromarray(rgb))
            self._video_img_ref = tk_img
            self.video_canvas.delete("all")
            self.video_canvas.create_image(
                self.video_canvas.winfo_width()  // 2,
                self.video_canvas.winfo_height() // 2,
                anchor="center", image=tk_img)

        self.scrub.set(self.position)
        self._update_time()
        self._update_cursor()
        self._play_job = self.after(8, self._play_tick)

    def _step(self, secs: float):
        if not self.cap:
            return
        was_playing = self.playing
        if was_playing:
            self._stop_play()
        self.position = max(0, min(self.duration, self.position + secs))
        self._play_start_wall = time.time()
        self._play_start_pos  = self.position
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, int(self.position * self.fps))
        self.scrub.set(self.position)
        self._update_time()
        self._refresh_video_canvas()
        self._update_cursor()
        if was_playing:
            self.playing          = True
            self._play_start_wall = time.time()
            self._play_start_pos  = self.position
            self._audio_play(self.position)
            self.btn_play.configure(text="\u23f8  Pause",
                                    fg_color="#3a1a1a",
                                    border_color="#5a0a0a")
            self._play_tick()
        else:
            self._extract_proposed()

    def _on_scrub(self, val):
        self.position = float(val)
        self._update_time()
        self._update_cursor()

    def _on_scrub_release(self, _=None):
        self.position = self.scrub.get()
        self._play_start_wall = time.time()
        self._play_start_pos  = self.position
        if self.cap:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, int(self.position * self.fps))
        self._refresh_video_canvas()
        self._update_cursor()
        if self.playing:
            self._audio_play(self.position)
        else:
            self._extract_proposed()

    def _extract_proposed(self):
        if not self.cap:
            return
        img = cv_frame_at(self.cap, self.position)
        if img:
            self.proposed_ready = True
            self._show_on_canvas(self.canvas_proposed, img, "_canvas_proposed_ref")
            self.btn_export_proposed.configure(state="normal")

    def _set_thumbnail(self):
        if not self.current_file or not self.proposed_ready:
            self.set_status("No frame selected \u2014 scrub or pause first.", "#e67e22")
            return
        secs, path = self.position, self.current_file
        self.set_status(f"Embedding: {path.name} @ {format_time(secs)}\u2026", "#f39c12")
        self.update_idletasks()
        self._audio_stop()
        if self.cap:
            self.cap.release()
            self.cap = None

        def do_embed():
            ok = embed_thumbnail(str(path), secs, self.temp_dir)
            def finish():
                self.cap = cv2.VideoCapture(str(path))
                self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
                if ok:
                    try:
                        idx = self.video_files.index(path)
                        self._set_file_status(idx, "done")
                    except ValueError:
                        pass
                    threading.Thread(target=self._load_current_thumb,
                                     daemon=True).start()
                    self.set_status(
                        f"Done: {path.name} @ {format_time(secs)}", "#27ae60")
                    sel = self.file_list.curselection()
                    if sel:
                        nxt = sel[0] + 1
                        if nxt < len(self.video_files):
                            self.file_list.selection_clear(0, tk.END)
                            self.file_list.selection_set(nxt)
                            self.file_list.see(nxt)
                            self._load_video(self.video_files[nxt])
                else:
                    self.set_status(f"Embed failed for {path.name}", RED)
            self.after(0, finish)
        threading.Thread(target=do_embed, daemon=True).start()

    def _set_file_status(self, idx: int, status: str):
        if not (0 <= idx < len(self.video_files)):
            return
        self.file_status[idx] = status
        name   = self.video_files[idx].name
        prefix = {"proposed": "\u25c6 ", "done": "\u2713 "}.get(status, "  ")
        color  = {"proposed": "#f0a500", "done": "#27ae60"}.get(status, FG)
        self.file_list.delete(idx)
        self.file_list.insert(idx, f"{prefix}{name}")
        self.file_list.itemconfigure(idx, fg=color)

    def _export_frame(self, current: bool):
        if not self.current_file:
            return
        ts_str  = format_time(self.position).replace(":", "-")
        default = (f"{self.current_file.stem}_thumbnail" if current
                   else f"{self.current_file.stem}_frame_{ts_str}")
        default_path = unique_export_path(self.current_file.parent, default, ".jpg")
        out = filedialog.asksaveasfilename(
            title="Export Frame", defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png"), ("TIFF", "*.tiff")],
            initialdir=str(default_path.parent),
            initialfile=default_path.name)
        if not out:
            return
        out_path = Path(out)
        ext = out_path.suffix or ".jpg"
        if out_path.exists():
            out_path = unique_export_path(out_path.parent, out_path.stem, ext)
        out = str(out_path)
        self.set_status("Exporting\u2026", "#f39c12")
        if current:
            tmp = os.path.join(self.temp_dir, "export_current.jpg")
            for args in [
                [FFMPEG_EXE, "-y", "-i", str(self.current_file),
                 "-map", "0:v:1", "-frames:v", "1", tmp],
                [FFMPEG_EXE, "-y", "-ss", "0", "-i", str(self.current_file),
                 "-frames:v", "1", tmp],
            ]:
                subprocess.run(args, capture_output=True, timeout=15)
                if os.path.exists(tmp):
                    break
            src = tmp if os.path.exists(tmp) else None
        else:
            if not self.cap:
                self.cap = cv2.VideoCapture(str(self.current_file))
            img = cv_frame_at(self.cap, self.position)
            if img:
                src = os.path.join(self.temp_dir, "export_proposed.png")
                img.save(src)
            else:
                src = None
        if src and os.path.exists(src):
            Image.open(src).save(out)
            self.set_status(f"Exported: {Path(out).name}", "#27ae60")
        else:
            self.set_status("Export failed.", RED)

    def _on_filmstrip_resize(self, width: int):
        self._fs_width = width
        self._build_timeline()
        self._update_cursor()
        if not self.current_file or self.duration <= 0:
            return
        if self._filmstrip_resize_job:
            self.after_cancel(self._filmstrip_resize_job)
        self._filmstrip_resize_job = self.after(180, self._rebuild_filmstrip)

    def _rebuild_filmstrip(self):
        self._filmstrip_resize_job = None
        self.filmstrip_canvas.delete("all")
        self.filmstrip_images = []
        self._filmstrip_generation += 1
        generation = self._filmstrip_generation
        threading.Thread(
            target=self._build_filmstrip, args=(generation,), daemon=True).start()

    def _add_filmstrip_image(self, x: int, img: Image.Image, generation: int):
        if generation != self._filmstrip_generation:
            return
        tk_img = ImageTk.PhotoImage(img)
        self.filmstrip_images.append(tk_img)
        self.filmstrip_canvas.create_image(x, 0, anchor="nw", image=tk_img)

    def _build_filmstrip(self, generation: int):
        if not self.current_file or self.duration <= 0:
            return
        path = self.current_file
        n  = self.filmstrip_count
        w  = self._fs_width or 800
        cw = max(1, w // n)
        local_cap = cv2.VideoCapture(str(path))
        try:
            for i in range(n):
                if path != self.current_file or generation != self._filmstrip_generation:
                    return
                ts  = (i + 0.5) * (self.duration / n)
                img = cv_frame_at(local_cap, ts)
                if img:
                    img = fit_image_to_box(img, cw, 68)
                    x = i * cw
                    self.after(0, lambda x=x, img=img, generation=generation:
                               self._add_filmstrip_image(x, img, generation))
            self.after(0, self._update_cursor)
            self.after(0, self._build_timeline)
        finally:
            local_cap.release()

    def _build_timeline(self):
        self.timeline_canvas.delete("all")
        w = self._fs_width
        if w < 2 or self.duration <= 0:
            return
        candidates = [15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200]
        interval   = next((c for c in candidates
                           if self.duration / c <= 12), 7200)
        t = interval
        while t < self.duration:
            x = (t / self.duration) * w
            self.timeline_canvas.create_line(x, 0, x, 5, fill="#444")
            self.timeline_canvas.create_text(
                x, 12, text=format_time(t),
                fill="#666", font=("Consolas", 8), anchor="center")
            t += interval

    def _filmstrip_click(self, event):
        if self.duration <= 0 or self._fs_width <= 0:
            return
        secs = max(0, min(self.duration,
                          (event.x / self._fs_width) * self.duration))
        self.position         = secs
        self._play_start_wall = time.time()
        self._play_start_pos  = secs
        self.scrub.set(secs)
        self._update_time()
        self._update_cursor()
        if self.cap:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, int(secs * self.fps))
        self._refresh_video_canvas()
        if self.playing:
            self._audio_play(secs)
        else:
            self._extract_proposed()

    def _process_all(self):
        if not messagebox.askyesno(
                "Set All Thumbnails",
                f"Process {len(self.video_files)} file(s)?\n"
                "Only files with a proposed frame will be updated."):
            return
        for idx, path in enumerate(self.video_files):
            if self.file_status.get(idx) == "proposed":
                self.set_status(f"Processing {path.name}\u2026", "#f39c12")
                self.update_idletasks()
                if self.cap:
                    self.cap.release()
                    self.cap = None
                if embed_thumbnail(str(path), self.position, self.temp_dir):
                    self._set_file_status(idx, "done")
                self.cap = cv2.VideoCapture(str(path))
                self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.set_status("Batch complete.", "#27ae60")

    def cleanup(self):
        self._stop_play()
        self._audio_stop()
        if self._vlc_player:
            try:
                self._vlc_player.release()
            except Exception:
                pass
        if self._vlc_instance:
            try:
                self._vlc_instance.release()
            except Exception:
                pass
        if PYGAME_OK:
            try:
                pygame.mixer.quit()
            except Exception:
                pass
        if self.cap:
            self.cap.release()
            self.cap = None


# ── Main window ────────────────────────────────────────────────
class ReelSheetApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1400x860")
        self.minsize(900, 600)
        self.configure(fg_color=BG)

        if not ffmpeg_available():
            messagebox.showerror("FFmpeg Missing",
                "FFmpeg not found in PATH.\n"
                f"Resolved path: {FFMPEG_EXE or 'None'}\n"
                "Expected fallback: C:\\ffmpeg\\bin\\ffmpeg.exe")
            self.destroy()
            return

        self.temp_dir = tempfile.mkdtemp(prefix="reelsheet_")
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n{'-'*60}\n"
                        f"Session: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                        f"VLC_OK={VLC_OK}  PYGAME_OK={PYGAME_OK}\n"
                        f"FFMPEG_EXE={FFMPEG_EXE}\n"
                        f"FFPROBE_EXE={FFPROBE_EXE}\n"
                        f"{'-'*60}\n")
        except Exception:
            pass

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(self, fg_color=BG2, height=44, corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(hdr, text=f"  \U0001f3ac  {APP_NAME}",
                     font=ctk.CTkFont(family="Consolas", size=16, weight="bold"),
                     text_color=FG).pack(side="left", padx=8)
        ctk.CTkLabel(hdr, text=f"v{APP_VERSION}",
                     font=ctk.CTkFont(size=11),
                     text_color=FG3).pack(side="left")

        # Audio stack indicator
        if VLC_OK:
            ind_text  = "\u25cf VLC"
            ind_color = "#27ae60"
            ind_tip   = "Direct MP4 audio via VLC"
        elif PYGAME_OK:
            ind_text  = "\u25cf pygame"
            ind_color = "#f39c12"
            ind_tip   = "Audio via OGG extraction (slower start)"
        else:
            ind_text  = "\u26a0 no audio"
            ind_color = "#c42b1c"
            ind_tip   = "Install python-vlc or pygame-ce for audio"

        ctk.CTkLabel(hdr, text=f"  {ind_text}",
                     font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
                     text_color=ind_color).pack(side="left", padx=(12, 0))
        ctk.CTkLabel(hdr, text=ind_tip,
                     font=ctk.CTkFont(size=10),
                     text_color=FG3).pack(side="left", padx=(4, 0))

        self.btn_diag = ctk.CTkButton(
            hdr, text="\U0001f50d  Diagnostics",
            width=140,
            fg_color="transparent",
            border_color=BORDER, border_width=1,
            hover_color="#2a2a2a",
            command=self._toggle_diag)
        self.btn_diag.pack(side="right", padx=12, pady=6)

        self.tabs = ctk.CTkTabview(
            self, fg_color=BG,
            segmented_button_fg_color=BG2,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color="#0068c0",
            segmented_button_unselected_color=BG2,
            segmented_button_unselected_hover_color="#2a2a2a",
            text_color=FG)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))
        self.tabs.add("  \U0001f3ac  Thumbnail Picker  ")
        self.tabs.add("  \U0001f4cb  Contact Sheet  ")

        self.picker = ThumbnailPickerTab(
            self.tabs.tab("  \U0001f3ac  Thumbnail Picker  "),
            temp_dir=self.temp_dir)
        self.picker.pack(fill="both", expand=True)

        self._diag = DiagnosticsWindow(self, self.picker)
        self.picker.diag = self._diag

        cs = ctk.CTkFrame(
            self.tabs.tab("  \U0001f4cb  Contact Sheet  "), fg_color=BG)
        cs.pack(fill="both", expand=True)
        ctk.CTkLabel(cs, text="Contact Sheet\nComing in v0.2.0",
                     font=ctk.CTkFont(size=18),
                     text_color=FG3).place(relx=0.5, rely=0.5, anchor="center")

        audio_log(f"App started \u2014 VLC_OK={VLC_OK}  PYGAME_OK={PYGAME_OK}", "#0078d4")

    def _toggle_diag(self):
        self._diag.toggle()
        active = self._diag._visible
        self.btn_diag.configure(
            fg_color=ACCENT if active else "transparent",
            border_color=ACCENT if active else BORDER)

    def _on_close(self):
        self._diag.destroy()
        self.picker.cleanup()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.destroy()


if __name__ == "__main__":
    app = ReelSheetApp()
    app.mainloop()
