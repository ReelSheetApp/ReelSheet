"""
ReelSheet v0.1.3
Video thumbnail picker and contact sheet generator
https://github.com/ReelSheetApp/ReelSheet
License: MIT

Changes:
  v0.1.1 — wall-clock playback (still slow due to per-tick seeking)
  v0.1.2 — fixed playback speed: sequential cap.read() + cap.grab()
            frame-skipping instead of seeking every tick.
            Added audio playback via pygame-ce.
  v0.1.3 — audio now starts reliably on Play (waits for extraction,
            retries if not yet ready).
            Video canvas made larger (weight 4 vs preview weight 1).
            Folder path label: larger font, brighter color.
            File count label: larger font, brighter color.
            Volume slider moved into transport row (next to ◀10s).
            Export buttons moved into same row as volume/transport.
            Last-used directory persisted to reelsheet_prefs.json.
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
APP_VERSION = "0.1.3"
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

PREFS_FILE  = Path(__file__).parent / "reelsheet_prefs.json"

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
        PREFS_FILE.write_text(
            json.dumps(prefs, indent=2), encoding="utf-8")
    except Exception:
        pass

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
    """Seek to seconds and return PIL Image, or None."""
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
        self.temp_dir           = temp_dir
        self.video_files        = []
        self.current_file       = None
        self.cap                = None
        self.duration           = 0.0
        self.position           = 0.0
        self.fps                = 30.0
        self.playing            = False
        self.proposed_ready     = False
        self.file_status        = {}
        self.filmstrip_images   = []
        self.filmstrip_count    = 20
        self._play_job          = None
        self._play_start_wall   = 0.0
        self._play_start_pos    = 0.0
        self._fs_width          = 0
        self._audio_file        = None
        self._audio_ready       = False
        self._audio_pending_play= False   # play requested before extraction done
        self._audio_pending_pos = 0.0
        self._video_img_ref     = None
        self._canvas_current_ref  = None
        self._canvas_proposed_ref = None
        self._prefs             = load_prefs()
        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Left panel ────────────────────────────────────────
        left = ctk.CTkFrame(self, fg_color=BG2, width=260)
        left.grid(row=0, column=0, sticky="nsew", padx=(8,4), pady=8)
        left.grid_propagate(False)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)

        ctk.CTkButton(left, text="Browse Folder…",
                      command=self._browse).grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(8,4))

        # Folder label — bigger, brighter
        self.folder_label = ctk.CTkLabel(
            left, text="No folder loaded",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color=FG2, wraplength=240, anchor="w", justify="left")
        self.folder_label.grid(row=1, column=0, columnspan=2,
                               sticky="ew", padx=8, pady=(0,4))

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

        # File count — bigger, brighter
        self.file_count = ctk.CTkLabel(
            left, text="No folder loaded",
            font=ctk.CTkFont(size=12), text_color=FG2)
        self.file_count.grid(row=3, column=0, columnspan=2,
                             sticky="ew", padx=8, pady=4)

        self.btn_process_all = ctk.CTkButton(
            left, text="Set All Thumbnails",
            state="disabled", command=self._process_all)
        self.btn_process_all.grid(row=4, column=0, columnspan=2,
                                  sticky="ew", padx=8, pady=(0,8))

        # ── Right panel ───────────────────────────────────────
        right = ctk.CTkFrame(self, fg_color=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(4,8), pady=8)
        right.grid_columnconfigure(0, weight=1)
        # Video canvas gets 4x the vertical space vs the preview row
        right.grid_rowconfigure(0, weight=4)
        right.grid_rowconfigure(1, weight=1)

        # Video canvas
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

        # Dual preview row (much smaller — weight=1 vs video weight=4)
        prow = ctk.CTkFrame(right, fg_color=BG)
        prow.grid(row=1, column=0, sticky="nsew", pady=(0,6))
        prow.grid_columnconfigure((0,1), weight=1, uniform="p")
        prow.grid_rowconfigure(1, weight=1)
        for col, (title, cname) in enumerate([
            ("CURRENT THUMBNAIL", "canvas_current"),
            ("PROPOSED FRAME",    "canvas_proposed"),
        ]):
            ctk.CTkLabel(prow, text=title,
                         font=ctk.CTkFont(family="Consolas", size=11,
                                          weight="bold"),
                         text_color="#aaaaaa").grid(
                row=0, column=col, sticky="w", pady=(0,2))
            pf = ctk.CTkFrame(prow, fg_color=BG3, corner_radius=4)
            pf.grid(row=1, column=col, sticky="nsew",
                    padx=(0,6) if col == 0 else 0)
            pf.grid_columnconfigure(0, weight=1)
            pf.grid_rowconfigure(0, weight=1)
            c = tk.Canvas(pf, bg="#0d0d0d", highlightthickness=0)
            c.grid(row=0, column=0, sticky="nsew")
            setattr(self, cname, c)

        # Filmstrip
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

        # Scrub slider
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

        # ── Combined transport + volume + export row ───────────
        # Layout (L→R):
        #   🔊 [vol] | ◀10s ◀1s ▶Play 1s▶ 10s▶ | ↓Current ↓Proposed
        tr = ctk.CTkFrame(right, fg_color=BG)
        tr.grid(row=4, column=0, sticky="ew", pady=(0,6))

        col = 0

        # Volume (only if pygame available)
        if PYGAME_OK:
            ctk.CTkLabel(tr, text="🔊",
                         font=ctk.CTkFont(size=13)).grid(
                row=0, column=col, padx=(0,2))
            col += 1
            self.vol_slider = ctk.CTkSlider(
                tr, from_=0, to=1,
                command=self._on_volume, width=90)
            self.vol_slider.set(0.8)
            self.vol_slider.grid(row=0, column=col, padx=(0,10))
            pygame.mixer.music.set_volume(0.8)
            col += 1

        # Transport buttons
        transport_defs = [
            ("◀ 10s",  lambda: self._step(-10), False),
            ("◀ 1s",   lambda: self._step(-1),  False),
            ("▶  Play", self._toggle_play,       True),
            ("1s ▶",   lambda: self._step(1),   False),
            ("10s ▶",  lambda: self._step(10),  False),
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
            b.grid(row=0, column=col, padx=(0,4))
            if is_play:
                self.btn_play = b
            col += 1

        # Spacer pushes export buttons to the right
        tr.grid_columnconfigure(col, weight=1)
        col += 1

        # Export buttons
        self.btn_export_current = ctk.CTkButton(
            tr, text="↓ Current",
            width=90, state="disabled",
            command=lambda: self._export_frame(True))
        self.btn_export_current.grid(row=0, column=col, padx=(0,4))
        col += 1

        self.btn_export_proposed = ctk.CTkButton(
            tr, text="↓ Proposed",
            width=90, state="disabled",
            command=lambda: self._export_frame(False))
        self.btn_export_proposed.grid(row=0, column=col)

        # Collect transport buttons for enable/disable
        self._transport_buttons = [
            w for w in tr.winfo_children()
            if isinstance(w, ctk.CTkButton)
            and w not in (self.btn_export_current, self.btn_export_proposed)
        ]

        # Set thumbnail button
        self.btn_set = ctk.CTkButton(
            right, text="⬤  Set This Frame as Thumbnail",
            height=42, font=ctk.CTkFont(size=14),
            fg_color=GREEN, hover_color="#0a5c0a",
            state="disabled", command=self._set_thumbnail)
        self.btn_set.grid(row=5, column=0, sticky="ew", pady=(0,6))

        # Status bar
        self.status = ctk.CTkLabel(
            right, text="Load a folder to begin.",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=FG3, anchor="w", fg_color=BG2,
            corner_radius=4, height=30)
        self.status.grid(row=6, column=0, sticky="ew")

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

    # ── Volume ─────────────────────────────────────────────────
    def _on_volume(self, val):
        if PYGAME_OK:
            pygame.mixer.music.set_volume(float(val))

    # ── Browse / load folder ───────────────────────────────────
    def _browse(self):
        initial = self._prefs.get("last_dir", "")
        if initial and not os.path.isdir(initial):
            initial = ""
        path = filedialog.askdirectory(
            title="Select folder containing MP4 files",
            initialdir=initial or None)
        if path:
            self._prefs["last_dir"] = path
            save_prefs(self._prefs)
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

    # ── File selection ─────────────────────────────────────────
    def _on_file_select(self, _=None):
        sel = self.file_list.curselection()
        if sel:
            self._load_video(self.video_files[sel[0]])

    def _load_video(self, path: Path):
        self._stop_play()
        self.current_file       = path
        self.proposed_ready     = False
        self._audio_ready       = False
        self._audio_pending_play= False
        self.btn_export_proposed.configure(state="disabled")
        self.set_status(f"Loading {path.name}…", ACCENT)
        self.update_idletasks()

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
            + ("" if PYGAME_OK else "  [install pygame-ce for audio]"), FG2)

    def _refresh_video_canvas(self):
        if self.cap:
            img = cv_frame_at(self.cap, self.position)
            if img:
                self._show_on_canvas(self.video_canvas, img, "_video_img_ref")

    # ── Audio extraction ───────────────────────────────────────
    def _extract_audio(self):
        """Extract full audio track to OGG in background thread.
        If play was requested before extraction finished, starts audio
        once the file is ready."""
        if not PYGAME_OK or not self.current_file:
            return
        out = os.path.join(self.temp_dir, "audio_track.ogg")
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
                # If play was hit before extraction finished, start now
                if self._audio_pending_play and self.playing:
                    self.after(0, lambda: self._audio_play(
                        self._audio_pending_pos))
                    self._audio_pending_play = False
        except Exception:
            self._audio_ready = False

    # ── Current thumbnail ──────────────────────────────────────
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

    # ── Audio helpers ──────────────────────────────────────────
    def _audio_play(self, position: float):
        """Start audio at position. If extraction not done yet, mark
        pending so _extract_audio() will fire it when ready."""
        if not PYGAME_OK:
            return
        if not self._audio_ready or not self._audio_file:
            self._audio_pending_play = True
            self._audio_pending_pos  = position
            return
        try:
            pygame.mixer.music.load(self._audio_file)
            pygame.mixer.music.play(start=position)
        except Exception:
            pass

    def _audio_pause(self):
        if PYGAME_OK:
            try:
                pygame.mixer.music.pause()
            except Exception:
                pass

    def _audio_stop(self):
        if PYGAME_OK:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass

    # ── Playback ───────────────────────────────────────────────
    def _toggle_play(self):
        if self.playing:
            self._stop_play()
            self._extract_proposed()
        else:
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
        self.playing             = False
        self._audio_pending_play = False
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

    # ── Proposed frame ─────────────────────────────────────────
    def _extract_proposed(self):
        if not self.cap:
            return
        img = cv_frame_at(self.cap, self.position)
        if img:
            self.proposed_ready = True
            self._show_on_canvas(self.canvas_proposed, img,
                                 "_canvas_proposed_ref")
            self.btn_export_proposed.configure(state="normal")

    # ── Set thumbnail ──────────────────────────────────────────
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

    # ── File list coloring ─────────────────────────────────────
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

    # ── Export ─────────────────────────────────────────────────
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

    # ── Filmstrip ──────────────────────────────────────────────
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

    # ── Batch ──────────────────────────────────────────────────
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
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(self, fg_color=BG2, height=44, corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(hdr, text=f"  🎬  {APP_NAME}",
                     font=ctk.CTkFont(family="Consolas", size=16, weight="bold"),
                     text_color=FG).pack(side="left", padx=8)
        ctk.CTkLabel(hdr, text=f"v{APP_VERSION}",
                     font=ctk.CTkFont(size=11),
                     text_color=FG3).pack(side="left")
        if not PYGAME_OK:
            ctk.CTkLabel(hdr,
                text="  ⚠  No audio — run: pip install pygame-ce",
                font=ctk.CTkFont(size=11), text_color="#e67e22"
            ).pack(side="left", padx=16)

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

        cs = ctk.CTkFrame(
            self.tabs.tab("  📋  Contact Sheet  "), fg_color=BG)
        cs.pack(fill="both", expand=True)
        ctk.CTkLabel(cs, text="Contact Sheet\nComing in v0.2.0",
                     font=ctk.CTkFont(size=18), text_color=FG3
                     ).place(relx=0.5, rely=0.5, anchor="center")

    def _on_close(self):
        self.picker.cleanup()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.destroy()


if __name__ == "__main__":
    app = ReelSheetApp()
    app.mainloop()
