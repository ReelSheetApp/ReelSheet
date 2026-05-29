"""
ReelSheet v0.1.7
Video thumbnail picker and contact sheet generator
https://github.com/ReelSheetApp/ReelSheet
License: MIT

Changes:
  v0.1.1 — wall-clock playback (still slow due to per-tick seeking)
  v0.1.2 — fixed playback speed: sequential cap.read() + cap.grab()
            frame-skipping. Added pygame audio (OGG extraction).
  v0.1.7 — Diagnostics window (separate Toplevel, toggled from header).
            Monitors audio extraction state, pygame mixer state, OGG
            file presence/size, and timing. Three VU-style meters:
            EXTRACT / MIXER / VOLUME. Scrolling timestamped log.
            All events written to reelsheet_audio.log.
            Zero changes to v0.1.2 audio or playback logic.
"""

import customtkinter as ctk
import cv2
import subprocess
import threading
import tempfile
import shutil
import os
import time
import math
from pathlib import Path
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime

# Optional pygame for audio
try:
    import pygame
    pygame.mixer.pre_init(44100, -16, 2, 1024)
    pygame.mixer.init()
    PYGAME_OK = True
except Exception:
    PYGAME_OK = False

# ── App config ────────────────────────────────────────────────
APP_NAME    = "ReelSheet"
APP_VERSION = "0.1.7"
ACCENT      = "#0078d4"
GREEN       = "#107c10"
RED         = "#c42b1c"
BG          = "#1a1a1a"
BG2         = "#141414"
BG3         = "#0d0d0d"
BORDER      = "#2a2a2a"
FG          = "#e0e0e0"
FG2         = "#888888"
FG3         = "#555555"

LOG_FILE    = Path(__file__).parent / "reelsheet_audio.log"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ── Audio event log (module-level, shared) ────────────────────
_audio_log   = []          # list of (timestamp_str, message, color)
_log_lock    = threading.Lock()

def audio_log(msg: str, color: str = "#cccccc"):
    """Append a timestamped entry to the in-memory log and log file."""
    ts  = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry = (ts, msg, color)
    with _log_lock:
        _audio_log.append(entry)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# ── Diagnostics Window ────────────────────────────────────────
class DiagnosticsWindow:
    """
    Separate Toplevel window. Purely observational — reads state from
    the picker instance. No writes to picker state.
    Toggle with show()/hide(). Polling pauses when hidden.
    """
    METER_W = 180
    METER_H = 120
    POLL_MS = 120

    def __init__(self, root: tk.Tk, picker):
        self._root    = root
        self._picker  = picker
        self._win     = None
        self._poll_job = None
        self._visible  = False
        self._log_seen = 0   # index into _audio_log already rendered

    # ── Show / hide ───────────────────────────────────────────
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

    # ── Build window ──────────────────────────────────────────
    def _build(self):
        win = tk.Toplevel(self._root)
        win.title("ReelSheet — Diagnostics")
        win.geometry("700x640")
        win.configure(bg=BG)
        win.protocol("WM_DELETE_WINDOW", self.hide)
        win.resizable(True, True)
        self._win = win

        # ── Header ────────────────────────────────────────────
        hdr = tk.Frame(win, bg=BG2, height=36)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="  🔍  Diagnostics",
                 bg=BG2, fg=FG,
                 font=("Consolas", 13, "bold")).pack(side="left", padx=4)
        tk.Label(hdr, text="Audio pipeline monitor — read-only",
                 bg=BG2, fg=FG3,
                 font=("Consolas", 10)).pack(side="left", padx=8)

        btn_frame = tk.Frame(hdr, bg=BG2)
        btn_frame.pack(side="right", padx=8)
        tk.Button(btn_frame, text="Clear Log", bg="#2a2a2a", fg=FG2,
                  relief="flat", bd=0, padx=8,
                  command=self._clear_log).pack(side="left", padx=(0,4))
        tk.Button(btn_frame, text="Save Log", bg="#2a2a2a", fg=FG2,
                  relief="flat", bd=0, padx=8,
                  command=self._save_log).pack(side="left")

        # ── Three VU meters ───────────────────────────────────
        meter_row = tk.Frame(win, bg=BG)
        meter_row.pack(fill="x", padx=8, pady=(8, 4))

        self._meters = {}
        for label, key in [
            ("EXTRACT",  "extract"),
            ("MIXER",    "mixer"),
            ("VOLUME",   "volume"),
        ]:
            col = tk.Frame(meter_row, bg=BG2,
                           relief="flat", bd=1,
                           highlightbackground=BORDER,
                           highlightthickness=1)
            col.pack(side="left", fill="both", expand=True,
                     padx=(0, 6) if key != "volume" else 0)

            tk.Label(col, text=label, bg=BG2, fg="#aaaaaa",
                     font=("Consolas", 10, "bold")).pack(pady=(6,2))

            c = tk.Canvas(col, bg=BG3, width=self.METER_W,
                          height=self.METER_H, highlightthickness=0)
            c.pack(padx=6, pady=(0,4))

            val_lbl = tk.Label(col, text="—", bg=BG2, fg=FG2,
                               font=("Consolas", 9))
            val_lbl.pack(pady=(0,6))

            self._meters[key] = {"canvas": c, "label": val_lbl, "level": 0.0}

        # ── Status grid ───────────────────────────────────────
        grid_frame = tk.Frame(win, bg=BG2,
                              highlightbackground=BORDER,
                              highlightthickness=1)
        grid_frame.pack(fill="x", padx=8, pady=(0,6))

        self._stat_labels = {}
        fields = [
            ("extract_state",  "Extract state"),
            ("ogg_exists",     "OGG file"),
            ("ogg_size",       "OGG size"),
            ("extract_elapsed","Extract elapsed"),
            ("audio_ready",    "audio_ready flag"),
            ("mixer_busy",     "mixer.get_busy()"),
            ("mixer_pos",      "mixer.get_pos()"),
            ("play_pressed",   "Last Play pressed"),
            ("audio_play_called", "Last _audio_play()"),
        ]
        for row_i, (key, label) in enumerate(fields):
            r = row_i // 3
            c = (row_i % 3) * 2
            tk.Label(grid_frame, text=label + ":", bg=BG2, fg=FG3,
                     font=("Consolas", 9), anchor="e").grid(
                row=r, column=c, sticky="e", padx=(8,2), pady=2)
            lbl = tk.Label(grid_frame, text="—", bg=BG2, fg=FG2,
                           font=("Consolas", 9), anchor="w")
            lbl.grid(row=r, column=c+1, sticky="w", padx=(0,16), pady=2)
            self._stat_labels[key] = lbl

        # ── Log pane ──────────────────────────────────────────
        log_hdr = tk.Frame(win, bg=BG)
        log_hdr.pack(fill="x", padx=8)
        tk.Label(log_hdr, text="EVENT LOG", bg=BG, fg="#aaaaaa",
                 font=("Consolas", 9, "bold")).pack(side="left")

        log_frame = tk.Frame(win, bg=BG3)
        log_frame.pack(fill="both", expand=True, padx=8, pady=(2,8))

        self._log_text = tk.Text(
            log_frame, bg=BG3, fg=FG2,
            font=("Consolas", 9),
            relief="flat", bd=0,
            state="disabled",
            wrap="none",
            highlightthickness=0)
        self._log_text.pack(side="left", fill="both", expand=True)

        vsb = tk.Scrollbar(log_frame, command=self._log_text.yview,
                           bg=BG2, troughcolor=BG3)
        vsb.pack(side="right", fill="y")
        self._log_text.configure(yscrollcommand=vsb.set)

        # Color tags
        self._log_text.tag_configure("green",  foreground="#27ae60")
        self._log_text.tag_configure("yellow", foreground="#f39c12")
        self._log_text.tag_configure("red",    foreground="#c42b1c")
        self._log_text.tag_configure("blue",   foreground="#0078d4")
        self._log_text.tag_configure("dim",    foreground=FG3)
        self._log_text.tag_configure("white",  foreground=FG)

        # Timestamps stored for extraction timing
        self._extract_start_time = None
        self._last_play_time     = None
        self._last_audio_play_time = None

        audio_log("Diagnostics window opened", "#0078d4")

    # ── Poll loop ─────────────────────────────────────────────
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

    # ── Meter drawing ─────────────────────────────────────────
    def _draw_meter(self, key: str, level: float, color: str, text: str):
        """level: 0.0–1.0. Draws a vertical bar with peak hold."""
        m  = self._meters[key]
        c  = m["canvas"]
        w  = self.METER_W
        h  = self.METER_H
        c.delete("all")

        # Background segments (10 divisions)
        seg_h = h / 10
        for i in range(10):
            y0 = h - (i + 1) * seg_h + 1
            y1 = h - i * seg_h - 1
            bg = "#1a2a1a" if i < 7 else ("#2a2a00" if i < 9 else "#2a0000")
            c.create_rectangle(4, y0, w - 4, y1, fill=bg, outline="")

        # Filled bar
        if level > 0:
            bar_h = int(level * h)
            for i in range(10):
                y0 = h - (i + 1) * seg_h + 1
                y1 = h - i * seg_h - 1
                frac = (i + 1) / 10
                if frac <= level:
                    fill = ("#27ae60" if i < 7
                            else ("#f39c12" if i < 9 else "#c42b1c"))
                    c.create_rectangle(4, y0, w - 4, y1,
                                       fill=fill, outline="")

        m["label"].configure(text=text, fg=color)

    def _update_meters(self):
        p = self._picker

        # ── EXTRACT meter ─────────────────────────────────────
        # Level = 0 (idle), 0.5 (running), 1.0 (done), 0.2 (failed)
        ogg = os.path.join(p.temp_dir, "audio_track.ogg")
        ogg_exists = os.path.exists(ogg)

        if p._audio_ready and ogg_exists:
            ext_level = 1.0
            ext_color = "#27ae60"
            ext_text  = "DONE"
        elif not p._audio_ready and ogg_exists:
            # File appeared but flag not set yet — in progress
            ext_level = 0.7
            ext_color = "#f39c12"
            ext_text  = "WRITING…"
        elif p.current_file and not p._audio_ready and not ogg_exists:
            # File selected, extraction presumably running
            ext_level = 0.4
            ext_color = "#0078d4"
            ext_text  = "EXTRACTING"
        else:
            ext_level = 0.0
            ext_color = FG3
            ext_text  = "IDLE"
        self._draw_meter("extract", ext_level, ext_color, ext_text)

        # ── MIXER meter ───────────────────────────────────────
        if PYGAME_OK:
            busy    = pygame.mixer.music.get_busy()
            pos_ms  = pygame.mixer.music.get_pos()   # ms since play(), -1 if stopped
            if busy:
                mix_level = 1.0
                mix_color = "#27ae60"
                mix_text  = f"PLAYING  +{pos_ms/1000:.1f}s"
            elif pos_ms == -1:
                mix_level = 0.0
                mix_color = FG3
                mix_text  = "STOPPED"
            else:
                mix_level = 0.1
                mix_color = "#f39c12"
                mix_text  = "PAUSED"
        else:
            mix_level = 0.0
            mix_color = RED
            mix_text  = "NO PYGAME"
        self._draw_meter("mixer", mix_level, mix_color, mix_text)

        # ── VOLUME meter ──────────────────────────────────────
        if PYGAME_OK:
            vol = pygame.mixer.music.get_volume()
            busy = pygame.mixer.music.get_busy()
            # Animate level: if playing, show volume; if not, show set level dimly
            vol_level = vol if busy else vol * 0.3
            vol_color = "#27ae60" if busy else FG3
            vol_text  = f"{int(vol*100)}%  {'▶' if busy else '■'}"
        else:
            vol_level = 0.0
            vol_color = RED
            vol_text  = "NO PYGAME"
        self._draw_meter("volume", vol_level, vol_color, vol_text)

    def _update_status(self):
        p   = self._picker
        ogg = os.path.join(p.temp_dir, "audio_track.ogg")

        def _set(key, val, color=FG2):
            lbl = self._stat_labels.get(key)
            if lbl:
                lbl.configure(text=str(val), fg=color)

        # Extract state
        if p._audio_ready:
            _set("extract_state", "COMPLETE", "#27ae60")
        elif p.current_file:
            _set("extract_state", "RUNNING / PENDING", "#f39c12")
        else:
            _set("extract_state", "IDLE", FG3)

        # OGG file
        if os.path.exists(ogg):
            size_kb = os.path.getsize(ogg) / 1024
            _set("ogg_exists", "YES", "#27ae60")
            _set("ogg_size",   f"{size_kb:,.0f} KB",
                 "#27ae60" if size_kb > 10 else "#f39c12")
        else:
            _set("ogg_exists", "NO", FG3)
            _set("ogg_size",   "—", FG3)

        # Extract elapsed — approximate from file mtime if available
        if os.path.exists(ogg) and self._extract_start_time:
            elapsed = os.path.getmtime(ogg) - self._extract_start_time
            _set("extract_elapsed", f"{elapsed:.1f}s", FG2)
        else:
            _set("extract_elapsed", "—", FG3)

        # audio_ready flag
        _set("audio_ready",
             str(p._audio_ready),
             "#27ae60" if p._audio_ready else "#f39c12")

        # Mixer state
        if PYGAME_OK:
            busy   = pygame.mixer.music.get_busy()
            pos_ms = pygame.mixer.music.get_pos()
            _set("mixer_busy",
                 "True" if busy else "False",
                 "#27ae60" if busy else FG3)
            _set("mixer_pos",
                 f"{pos_ms} ms" if pos_ms >= 0 else "—",
                 "#27ae60" if pos_ms >= 0 else FG3)
        else:
            _set("mixer_busy", "N/A", FG3)
            _set("mixer_pos",  "N/A", FG3)

        _set("play_pressed",
             self._last_play_time or "—", FG2)
        _set("audio_play_called",
             self._last_audio_play_time or "—", FG2)

    # ── Log rendering ─────────────────────────────────────────
    def _flush_log(self):
        with _log_lock:
            new_entries = _audio_log[self._log_seen:]
            self._log_seen = len(_audio_log)

        if not new_entries:
            return

        self._log_text.configure(state="normal")
        for ts, msg, color in new_entries:
            tag = self._color_tag(color)
            self._log_text.insert("end", f"[{ts}] ", "dim")
            self._log_text.insert("end", msg + "\n", tag)
        self._log_text.configure(state="disabled")
        self._log_text.see("end")

    def _color_tag(self, color: str) -> str:
        mapping = {
            "#27ae60": "green",
            "#f39c12": "yellow",
            "#c42b1c": "red",
            "#0078d4": "blue",
            FG3:       "dim",
            FG:        "white",
        }
        return mapping.get(color, "white")

    def _clear_log(self):
        global _audio_log
        with _log_lock:
            _audio_log.clear()
        self._log_seen = 0
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")
        audio_log("Log cleared", FG3)

    def _save_log(self):
        out = filedialog.asksaveasfilename(
            title="Save Log",
            defaultextension=".log",
            filetypes=[("Log file", "*.log"), ("Text", "*.txt")],
            initialfile="reelsheet_audio.log")
        if out:
            with _log_lock:
                entries = list(_audio_log)
            with open(out, "w", encoding="utf-8") as f:
                for ts, msg, _ in entries:
                    f.write(f"[{ts}] {msg}\n")
            audio_log(f"Log saved → {out}", "#27ae60")

    # ── Called by picker to record timing events ───────────────
    def on_file_selected(self, name: str):
        self._extract_start_time = time.time()
        audio_log(f"File selected: {name}", "#0078d4")

    def on_extract_start(self):
        audio_log("_extract_audio thread started", "#0078d4")

    def on_extract_done(self, path: str, success: bool):
        if success:
            size_kb = os.path.getsize(path) / 1024 if os.path.exists(path) else 0
            elapsed = (time.time() - self._extract_start_time
                       if self._extract_start_time else 0)
            audio_log(
                f"Extraction COMPLETE — {size_kb:,.0f} KB in {elapsed:.1f}s",
                "#27ae60")
        else:
            audio_log("Extraction FAILED", "#c42b1c")

    def on_play_pressed(self, position: float, audio_ready: bool):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._last_play_time = ts
        audio_log(
            f"Play pressed @ {format_time(position)} — "
            f"audio_ready={audio_ready}",
            "#27ae60" if audio_ready else "#f39c12")

    def on_audio_play_called(self, position: float):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._last_audio_play_time = ts
        audio_log(
            f"_audio_play() called @ {format_time(position)}", "#27ae60")

    def on_audio_play_skipped(self, position: float, reason: str):
        audio_log(
            f"_audio_play() SKIPPED @ {format_time(position)} — {reason}",
            "#c42b1c")


# ── Utilities ─────────────────────────────────────────────────
def ffmpeg_available():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False

def ffprobe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15)
        return float(r.stdout.strip())
    except Exception:
        return 0.0

def get_stored_thumb_pos(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags=comment",
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
            ["ffmpeg", "-y", "-ss", str(seconds), "-i", video_path,
             "-frames:v", "1", "-q:v", "2", thumb],
            capture_output=True, timeout=30)
        if not os.path.exists(thumb):
            return False
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-i", thumb,
             "-map", "0", "-map", "1", "-c", "copy",
             "-disposition:v:1", "attached_pic",
             "-metadata", f"comment=thumb_pos={round(seconds, 3)}",
             outf],
            capture_output=True, timeout=60)
        if not os.path.exists(outf):
            return False
        os.remove(video_path)
        os.rename(outf, video_path)
        try:
            import ctypes
            ctypes.windll.shell32.SHChangeNotify(0x00000008, 0x0005,
                                                  video_path, None)
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
        self._audio_file          = None
        self._audio_ready         = False
        self._video_img_ref       = None
        self._canvas_current_ref  = None
        self._canvas_proposed_ref = None
        self.diag                 = None   # set by ReelSheetApp after init
        self._build_ui()

    # ── UI (unchanged from v0.1.2) ─────────────────────────────
    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self, fg_color=BG2, width=260)
        left.grid(row=0, column=0, sticky="nsew", padx=(8,4), pady=8)
        left.grid_propagate(False)
        left.grid_rowconfigure(2, weight=1)

        ctk.CTkButton(left, text="Browse Folder…",
                      command=self._browse).grid(
            row=0, column=0, sticky="ew", padx=8, pady=(8,2))

        self.folder_label = ctk.CTkLabel(
            left, text="No folder loaded",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color=FG3, wraplength=240, anchor="w")
        self.folder_label.grid(row=1, column=0, sticky="ew",
                               padx=8, pady=(0,4))

        self.file_list = tk.Listbox(
            left, bg="#111111", fg=FG, selectbackground=ACCENT,
            selectforeground="white", relief="flat", bd=0,
            font=("Consolas", 11), activestyle="none",
            highlightthickness=0, exportselection=False)
        self.file_list.grid(row=2, column=0, sticky="nsew", padx=4)
        self.file_list.bind("<<ListboxSelect>>", self._on_file_select)

        sb = ctk.CTkScrollbar(left, command=self.file_list.yview)
        sb.grid(row=2, column=1, sticky="ns")
        self.file_list.configure(yscrollcommand=sb.set)

        self.file_count = ctk.CTkLabel(
            left, text="No folder loaded",
            font=ctk.CTkFont(size=11), text_color=FG3)
        self.file_count.grid(row=3, column=0, columnspan=2,
                             sticky="ew", padx=8, pady=4)

        self.btn_process_all = ctk.CTkButton(
            left, text="Set All Thumbnails",
            state="disabled", command=self._process_all)
        self.btn_process_all.grid(row=4, column=0, columnspan=2,
                                  sticky="ew", padx=8, pady=(0,8))

        right = ctk.CTkFrame(self, fg_color=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(4,8), pady=8)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=3)
        right.grid_rowconfigure(1, weight=2)

        vf = ctk.CTkFrame(right, fg_color=BG3, corner_radius=4)
        vf.grid(row=0, column=0, sticky="nsew", pady=(0,6))
        vf.grid_columnconfigure(0, weight=1)
        vf.grid_rowconfigure(0, weight=1)
        self.video_canvas = tk.Canvas(vf, bg="#000", highlightthickness=0)
        self.video_canvas.grid(row=0, column=0, sticky="nsew")
        self.video_canvas.bind("<Configure>",
                               lambda _: self._refresh_video_canvas())
        self.no_video_label = ctk.CTkLabel(
            vf, text="Select a video from the list",
            font=ctk.CTkFont(size=14), text_color=FG3)
        self.no_video_label.place(relx=0.5, rely=0.5, anchor="center")

        prow = ctk.CTkFrame(right, fg_color=BG)
        prow.grid(row=1, column=0, sticky="nsew", pady=(0,6))
        prow.grid_columnconfigure((0,1), weight=1, uniform="p")
        prow.grid_rowconfigure(1, weight=1)
        for col, (title, cname) in enumerate([
            ("CURRENT THUMBNAIL", "canvas_current"),
            ("PROPOSED FRAME",    "canvas_proposed"),
        ]):
            ctk.CTkLabel(prow, text=title,
                         font=ctk.CTkFont(family="Consolas", size=12,
                                          weight="bold"),
                         text_color="#aaaaaa").grid(
                row=0, column=col, sticky="w", pady=(0,3))
            pf = ctk.CTkFrame(prow, fg_color=BG3, corner_radius=4)
            pf.grid(row=1, column=col, sticky="nsew",
                    padx=(0,6) if col == 0 else 0)
            pf.grid_columnconfigure(0, weight=1)
            pf.grid_rowconfigure(0, weight=1)
            c = tk.Canvas(pf, bg="#0d0d0d", highlightthickness=0)
            c.grid(row=0, column=0, sticky="nsew")
            setattr(self, cname, c)

        fsf = ctk.CTkFrame(right, fg_color="#000", corner_radius=0, height=88)
        fsf.grid(row=2, column=0, sticky="ew", pady=(0,4))
        fsf.grid_propagate(False)
        fsf.grid_columnconfigure(0, weight=1)
        self.filmstrip_canvas = tk.Canvas(fsf, bg="#000",
                                          highlightthickness=0, height=68)
        self.filmstrip_canvas.grid(row=0, column=0, sticky="ew")
        self.timeline_canvas = tk.Canvas(fsf, bg="#0a0a0a",
                                         highlightthickness=0, height=18)
        self.timeline_canvas.grid(row=1, column=0, sticky="ew")
        self.filmstrip_canvas.bind("<Button-1>", self._filmstrip_click)
        self.filmstrip_canvas.bind("<Configure>",
                                   lambda e: self._on_filmstrip_resize(e.width))

        sr = ctk.CTkFrame(right, fg_color=BG)
        sr.grid(row=3, column=0, sticky="ew", pady=(0,4))
        sr.grid_columnconfigure(0, weight=1)
        self.scrub = ctk.CTkSlider(sr, from_=0, to=100,
                                   command=self._on_scrub)
        self.scrub.grid(row=0, column=0, sticky="ew")
        self.scrub.set(0)
        self.scrub.configure(state="disabled")
        self.scrub.bind("<ButtonRelease-1>", self._on_scrub_release)
        self.time_label = ctk.CTkLabel(
            sr, text="--:--:-- / --:--:--",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=FG2, width=140)
        self.time_label.grid(row=0, column=1, padx=(8,0))

        if PYGAME_OK:
            vol_row = ctk.CTkFrame(right, fg_color=BG)
            vol_row.grid(row=4, column=0, sticky="ew", pady=(0,2))
            vol_row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(vol_row, text="🔊",
                         font=ctk.CTkFont(size=13)).grid(
                row=0, column=0, padx=(0,6))
            self.vol_slider = ctk.CTkSlider(
                vol_row, from_=0, to=1,
                command=self._on_volume, width=120)
            self.vol_slider.set(0.8)
            self.vol_slider.grid(row=0, column=1, sticky="w")
            pygame.mixer.music.set_volume(0.8)

        tr_row = 5 if PYGAME_OK else 4
        tr = ctk.CTkFrame(right, fg_color=BG)
        tr.grid(row=tr_row, column=0, sticky="ew", pady=(0,6))
        for i, (txt, cmd) in enumerate([
            ("◀ 10s", lambda: self._step(-10)),
            ("◀ 1s",  lambda: self._step(-1)),
            ("▶  Play", self._toggle_play),
            ("1s ▶",  lambda: self._step(1)),
            ("10s ▶", lambda: self._step(10)),
        ]):
            is_play = "Play" in txt
            b = ctk.CTkButton(tr, text=txt,
                              width=95 if is_play else 80,
                              command=cmd, state="disabled",
                              fg_color="#1a3a1a" if is_play else "transparent",
                              border_color="#0a5c0a" if is_play else BORDER,
                              border_width=1,
                              hover_color="#2a4a2a" if is_play else "#333")
            b.grid(row=0, column=i, padx=(0,6))
            if is_play:
                self.btn_play = b
        self._transport_buttons = tr.winfo_children()

        set_row = tr_row + 1
        self.btn_set = ctk.CTkButton(
            right, text="⬤  Set This Frame as Thumbnail",
            height=42, font=ctk.CTkFont(size=14),
            fg_color=GREEN, hover_color="#0a5c0a",
            state="disabled", command=self._set_thumbnail)
        self.btn_set.grid(row=set_row, column=0, sticky="ew", pady=(0,6))

        er = ctk.CTkFrame(right, fg_color=BG)
        er.grid(row=set_row+1, column=0, sticky="ew", pady=(0,6))
        self.btn_export_current = ctk.CTkButton(
            er, text="↓  Export Current Thumbnail…", width=220,
            state="disabled", command=lambda: self._export_frame(True))
        self.btn_export_current.grid(row=0, column=0, padx=(0,8))
        self.btn_export_proposed = ctk.CTkButton(
            er, text="↓  Export Proposed Frame…", width=220,
            state="disabled", command=lambda: self._export_frame(False))
        self.btn_export_proposed.grid(row=0, column=1)

        self.status = ctk.CTkLabel(
            right, text="Load a folder to begin.",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=FG3, anchor="w", fg_color=BG2,
            corner_radius=4, height=30)
        self.status.grid(row=set_row+2, column=0, sticky="ew")

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
            return
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        if cw < 2 or ch < 2:
            return
        img = img.copy()
        img.thumbnail((cw, ch), Image.LANCZOS)
        tk_img = ImageTk.PhotoImage(img)
        setattr(self, attr, tk_img)
        canvas.delete("all")
        canvas.create_image(cw//2, ch//2, anchor="center", image=tk_img)

    def _update_time(self):
        self.time_label.configure(
            text=f"{format_time(self.position)} / {format_time(self.duration)}")

    def _update_cursor(self):
        if self._fs_width <= 0 or self.duration <= 0:
            return
        x = (self.position / self.duration) * self._fs_width
        self.filmstrip_canvas.delete("cursor")
        self.filmstrip_canvas.create_rectangle(
            x-1.5, 0, x+1.5, 68, fill=ACCENT, outline="", tags="cursor")

    def _on_volume(self, val):
        if PYGAME_OK:
            pygame.mixer.music.set_volume(float(val))

    def _browse(self):
        path = filedialog.askdirectory(
            title="Select folder containing MP4 files")
        if path:
            self._load_folder(path)

    def _load_folder(self, path: str):
        self.video_files = sorted(Path(path).glob("*.mp4"),
                                  key=lambda p: p.name.lower())
        self.file_status = {}
        self.file_list.delete(0, tk.END)
        for f in self.video_files:
            self.file_list.insert(tk.END, f"  {f.name}")
        n = len(self.video_files)
        self.folder_label.configure(text=path)
        self.file_count.configure(text=f"{n} MP4 file(s) found")
        self.btn_process_all.configure(state="normal" if n else "disabled")
        self.set_status(f"Folder loaded — {n} file(s). Select a video.", FG2)

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
        self.set_status(f"Loading {path.name}…", ACCENT)
        self.update_idletasks()

        # ── Diag hook ─────────────────────────────────────────
        if self.diag:
            self.diag.on_file_selected(path.name)

        if self.cap:
            self.cap.release()
        self.cap      = cv2.VideoCapture(str(path))
        self.fps      = self.cap.get(cv2.CAP_PROP_FPS) or 30
        total         = self.cap.get(cv2.CAP_PROP_FRAME_COUNT)
        self.duration = total / self.fps if self.fps > 0 \
                        else ffprobe_duration(str(path))

        start         = min(get_stored_thumb_pos(str(path)),
                            max(0, self.duration - 1))
        self.position = start
        self.scrub.configure(to=self.duration)
        self.scrub.set(start)
        self._update_time()
        self._enable_transport(True)
        self.no_video_label.place_forget()
        self._refresh_video_canvas()

        threading.Thread(target=self._load_current_thumb, daemon=True).start()
        threading.Thread(target=self._extract_audio,      daemon=True).start()
        self._show_on_canvas(self.canvas_proposed, None, "_canvas_proposed_ref")
        self.filmstrip_canvas.delete("all")
        self.timeline_canvas.delete("all")
        threading.Thread(target=self._build_filmstrip,    daemon=True).start()
        self.set_status(
            f"Loaded: {path.name}  ({format_time(self.duration)})"
            + ("" if PYGAME_OK else "  [install pygame for audio]"), FG2)

    def _refresh_video_canvas(self):
        if self.cap:
            img = cv_frame_at(self.cap, self.position)
            if img:
                self._show_on_canvas(self.video_canvas, img, "_video_img_ref")

    # ── Audio extraction (v0.1.2 logic, diag hooks added) ─────
    def _extract_audio(self):
        if not PYGAME_OK or not self.current_file:
            return
        out = os.path.join(self.temp_dir, "audio_track.ogg")

        # ── Diag hook ─────────────────────────────────────────
        if self.diag:
            self.after(0, self.diag.on_extract_start)

        try:
            if os.path.exists(out):
                os.remove(out)
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(self.current_file),
                 "-vn", "-ac", "2", "-ar", "44100",
                 "-q:a", "4", out],
                capture_output=True, timeout=120)
            if os.path.exists(out):
                self._audio_file  = out
                self._audio_ready = True
                # ── Diag hook ─────────────────────────────────
                if self.diag:
                    self.after(0, lambda: self.diag.on_extract_done(
                        out, True))
            else:
                self._audio_ready = False
                if self.diag:
                    self.after(0, lambda: self.diag.on_extract_done(
                        out, False))
        except Exception as e:
            self._audio_ready = False
            audio_log(f"Extraction exception: {e}", "#c42b1c")
            if self.diag:
                self.after(0, lambda: self.diag.on_extract_done(out, False))

    def _load_current_thumb(self):
        if not self.current_file:
            return
        tmp = os.path.join(self.temp_dir, "current_thumb.jpg")
        for args in [
            ["ffmpeg", "-y", "-i", str(self.current_file),
             "-map", "0:v:1", "-frames:v", "1", "-q:v", "2", tmp],
            ["ffmpeg", "-y", "-ss", "0", "-i", str(self.current_file),
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

    # ── Audio play (v0.1.2 logic, diag hooks added) ────────────
    def _audio_play(self, position: float):
        if not PYGAME_OK:
            return
        if not self._audio_ready or not self._audio_file:
            # ── Diag hook ─────────────────────────────────────
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
            # ── Diag hook ─────────────────────────────────────
            if self.diag:
                self.diag.on_audio_play_called(position)
            audio_log(
                f"pygame.mixer.music.play(start={position:.2f}) called",
                "#27ae60")
        except Exception as e:
            audio_log(f"pygame play exception: {e}", "#c42b1c")

    def _audio_pause(self):
        if PYGAME_OK:
            try:
                pygame.mixer.music.pause()
                audio_log("mixer.pause()", FG3)
            except Exception:
                pass

    def _audio_stop(self):
        if PYGAME_OK:
            try:
                pygame.mixer.music.stop()
                audio_log("mixer.stop()", FG3)
            except Exception:
                pass

    # ── Playback (unchanged from v0.1.2, diag hook on Play) ───
    def _toggle_play(self):
        if self.playing:
            self._stop_play()
            self._extract_proposed()
        else:
            # ── Diag hook ─────────────────────────────────────
            if self.diag:
                self.diag.on_play_pressed(self.position, self._audio_ready)
            self.playing          = True
            self._play_start_wall = time.time()
            self._play_start_pos  = self.position
            self.cap.set(cv2.CAP_PROP_POS_FRAMES,
                         int(self.position * self.fps))
            self._audio_play(self.position)
            self.btn_play.configure(text="⏸  Pause",
                                    fg_color="#3a1a1a",
                                    border_color="#5a0a0a")
            self._play_tick()

    def _stop_play(self):
        self.playing = False
        if self._play_job:
            self.after_cancel(self._play_job)
            self._play_job = None
        self._audio_pause()
        self.btn_play.configure(text="▶  Play",
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
            skip = min(frames_behind, 8)
            for _ in range(skip):
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
                frame  = cv2.resize(frame, (nw, nh),
                                    interpolation=cv2.INTER_LINEAR)
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
            self.btn_play.configure(text="⏸  Pause",
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
            self.cap.set(cv2.CAP_PROP_POS_FRAMES,
                         int(self.position * self.fps))
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
            self._show_on_canvas(self.canvas_proposed, img,
                                 "_canvas_proposed_ref")
            self.btn_export_proposed.configure(state="normal")

    def _set_thumbnail(self):
        if not self.current_file or not self.proposed_ready:
            self.set_status("No frame selected — scrub or pause first.",
                            "#e67e22")
            return
        secs, path = self.position, self.current_file
        self.set_status(f"Embedding: {path.name} @ {format_time(secs)}…",
                        "#f39c12")
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
        prefix = {"proposed": "◆ ", "done": "✓ "}.get(status, "  ")
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
        out = filedialog.asksaveasfilename(
            title="Export Frame", defaultextension=".jpg",
            filetypes=[("JPEG","*.jpg"),("PNG","*.png"),("TIFF","*.tiff")],
            initialfile=default)
        if not out:
            return
        self.set_status("Exporting…", "#f39c12")
        if current:
            tmp = os.path.join(self.temp_dir, "export_current.jpg")
            for args in [
                ["ffmpeg", "-y", "-i", str(self.current_file),
                 "-map", "0:v:1", "-frames:v", "1", tmp],
                ["ffmpeg", "-y", "-ss", "0", "-i", str(self.current_file),
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

    def _build_filmstrip(self):
        if not self.current_file or not self.cap or self.duration <= 0:
            return
        n  = self.filmstrip_count
        w  = self._fs_width or 800
        cw = max(1, w // n)
        self.filmstrip_images = []
        for i in range(n):
            ts  = (i + 0.5) * (self.duration / n)
            img = cv_frame_at(self.cap, ts)
            if img:
                img    = img.resize((cw, 68), Image.LANCZOS)
                tk_img = ImageTk.PhotoImage(img)
                self.filmstrip_images.append(tk_img)
                x = i * cw
                self.after(0, lambda x=x, t=tk_img:
                           self.filmstrip_canvas.create_image(
                               x, 0, anchor="nw", image=t))
        self.after(0, self._update_cursor)
        self.after(0, self._build_timeline)

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
                self.set_status(f"Processing {path.name}…", "#f39c12")
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
        if self.cap:
            self.cap.release()
            self.cap = None
        if PYGAME_OK:
            try:
                pygame.mixer.quit()
            except Exception:
                pass


# ── Main window ────────────────────────────────────────────────
class ReelSheetApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1200x820")
        self.minsize(900, 600)
        self.configure(fg_color=BG)

        if not ffmpeg_available():
            messagebox.showerror("FFmpeg Missing",
                "FFmpeg not found in PATH.\n"
                "Please install FFmpeg and ensure it's accessible.")
            self.destroy()
            return

        self.temp_dir = tempfile.mkdtemp(prefix="reelsheet_")

        # Write fresh log header
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n{'─'*60}\n")
                f.write(f"Session started: "
                        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"{'─'*60}\n")
        except Exception:
            pass

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(self, fg_color=BG2, height=44, corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(hdr, text=f"  🎬  {APP_NAME}",
                     font=ctk.CTkFont(family="Consolas", size=16,
                                      weight="bold"),
                     text_color=FG).pack(side="left", padx=8)
        ctk.CTkLabel(hdr, text=f"v{APP_VERSION}",
                     font=ctk.CTkFont(size=11),
                     text_color=FG3).pack(side="left")
        if not PYGAME_OK:
            ctk.CTkLabel(hdr,
                text="  ⚠  No audio — run: pip install pygame-ce",
                font=ctk.CTkFont(size=11),
                text_color="#e67e22").pack(side="left", padx=16)

        # Diagnostics toggle button — right side of header
        self.btn_diag = ctk.CTkButton(
            hdr, text="🔍  Diagnostics",
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
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4,8))
        self.tabs.add("  🎬  Thumbnail Picker  ")
        self.tabs.add("  📋  Contact Sheet  ")

        self.picker = ThumbnailPickerTab(
            self.tabs.tab("  🎬  Thumbnail Picker  "),
            temp_dir=self.temp_dir)
        self.picker.pack(fill="both", expand=True)

        # Wire diagnostics window to picker
        self._diag = DiagnosticsWindow(self, self.picker)
        self.picker.diag = self._diag

        cs = ctk.CTkFrame(
            self.tabs.tab("  📋  Contact Sheet  "), fg_color=BG)
        cs.pack(fill="both", expand=True)
        ctk.CTkLabel(cs, text="Contact Sheet\nComing in v0.2.0",
                     font=ctk.CTkFont(size=18), text_color=FG3
                     ).place(relx=0.5, rely=0.5, anchor="center")

        audio_log("ReelSheet started — pygame OK: " + str(PYGAME_OK),
                  "#0078d4")

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
