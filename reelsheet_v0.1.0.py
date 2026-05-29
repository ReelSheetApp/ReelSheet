"""
ReelSheet v0.1.0
Video thumbnail picker and contact sheet generator
https://github.com/ReelSheetApp/ReelSheet
License: MIT
"""

import customtkinter as ctk
import cv2
import subprocess
import threading
import tempfile
import shutil
import os
import sys
import math
import json
from pathlib import Path
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import filedialog, messagebox

# ── App config ────────────────────────────────────────────────
APP_NAME    = "ReelSheet"
APP_VERSION = "0.1.0"
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

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

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
            capture_output=True, text=True, timeout=15
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0

def ffprobe_info(path: str) -> dict:
    """Return width, height, codec, aspect ratio string."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,codec_name",
             "-of", "default=noprint_wrappers=1", path],
            capture_output=True, text=True, timeout=15
        )
        info = {}
        for line in r.stdout.strip().splitlines():
            k, _, v = line.partition("=")
            info[k.strip()] = v.strip()
        w = int(info.get("width", 0))
        h = int(info.get("height", 0))
        from math import gcd
        g = gcd(w, h) or 1
        return {
            "width": w, "height": h,
            "codec": info.get("codec_name", "?").upper(),
            "ar": f"{w//g}:{h//g}"
        }
    except Exception:
        return {"width": 0, "height": 0, "codec": "?", "ar": "?"}

def get_stored_thumb_pos(path: str) -> float:
    """Read thumb_pos from MP4 comment metadata."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags=comment",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10
        )
        val = r.stdout.strip()
        if "thumb_pos=" in val:
            return float(val.split("thumb_pos=")[1].split()[0])
    except Exception:
        pass
    return 0.0

def embed_thumbnail(video_path: str, seconds: float, temp_dir: str) -> bool:
    """Extract frame at seconds, embed as MP4 thumbnail, notify Explorer."""
    base   = Path(video_path).stem
    thumb  = os.path.join(temp_dir, f"{base}_thumb.jpg")
    outf   = os.path.join(Path(video_path).parent, f"{base}_tmp.mp4")
    try:
        # Extract frame
        r1 = subprocess.run(
            ["ffmpeg", "-y", "-ss", str(seconds), "-i", video_path,
             "-frames:v", "1", "-q:v", "2", thumb],
            capture_output=True, timeout=30
        )
        if not os.path.exists(thumb):
            return False
        # Embed as attached_pic with timestamp metadata
        r2 = subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-i", thumb,
             "-map", "0", "-map", "1", "-c", "copy",
             "-disposition:v:1", "attached_pic",
             "-metadata", f"comment=thumb_pos={round(seconds, 3)}",
             outf],
            capture_output=True, timeout=60
        )
        if not os.path.exists(outf):
            return False
        os.remove(video_path)
        os.rename(outf, video_path)
        # Notify Windows Explorer
        try:
            import ctypes
            SHCNE_UPDATEITEM = 0x00000008
            SHCNF_PATHW      = 0x0005
            ctypes.windll.shell32.SHChangeNotify(
                SHCNE_UPDATEITEM, SHCNF_PATHW, video_path, None)
        except Exception:
            pass
        return True
    except Exception:
        return False
    finally:
        for f in [thumb]:
            try:
                if os.path.exists(f): os.remove(f)
            except Exception:
                pass

def format_time(seconds: float) -> str:
    s = max(0, int(seconds))
    h = s // 3600
    m = (s % 3600) // 60
    s = s % 60
    return f"{h}:{m:02d}:{s:02d}"

def cv_frame_at(cap: cv2.VideoCapture, seconds: float) -> Image.Image | None:
    """Seek OpenCV capture to seconds, return PIL Image or None."""
    fps   = cap.get(cv2.CAP_PROP_FPS) or 30
    frame = int(seconds * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
    ok, img = cap.read()
    if not ok:
        return None
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return Image.fromarray(img)

# ── Thumbnail Picker Tab ───────────────────────────────────────
class ThumbnailPickerTab(ctk.CTkFrame):
    def __init__(self, master, temp_dir: str, **kwargs):
        super().__init__(master, fg_color=BG, **kwargs)
        self.temp_dir  = temp_dir
        self.video_files: list[Path] = []
        self.current_file: Path | None = None
        self.cap: cv2.VideoCapture | None = None
        self.duration   = 0.0
        self.position   = 0.0
        self.playing    = False
        self.proposed_ready = False
        self.file_status: dict[int, str] = {}   # "proposed" | "done"
        self.filmstrip_images: list[ImageTk.PhotoImage] = []
        self.filmstrip_count  = 20
        self._play_job  = None
        self._build_ui()

    # ── UI layout ─────────────────────────────────────────────
    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left panel
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
        self.folder_label.grid(row=1, column=0, sticky="ew", padx=8, pady=(0,4))

        self.file_list = tk.Listbox(
            left, bg="#111111", fg=FG, selectbackground=ACCENT,
            selectforeground="white", relief="flat", bd=0,
            font=("Consolas", 11), activestyle="none",
            highlightthickness=0, exportselection=False)
        self.file_list.grid(row=2, column=0, sticky="nsew", padx=4, pady=0)
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

        # Right panel
        right = ctk.CTkFrame(self, fg_color=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(4,8), pady=8)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=3)
        right.grid_rowconfigure(1, weight=2)

        # Video canvas
        video_frame = ctk.CTkFrame(right, fg_color=BG3, corner_radius=4)
        video_frame.grid(row=0, column=0, sticky="nsew", pady=(0,6))
        video_frame.grid_columnconfigure(0, weight=1)
        video_frame.grid_rowconfigure(0, weight=1)
        self.video_canvas = tk.Canvas(
            video_frame, bg="#000000", highlightthickness=0)
        self.video_canvas.grid(row=0, column=0, sticky="nsew")
        self.video_canvas.bind("<Configure>", self._on_canvas_resize)
        self._video_img_ref = None

        self.no_video_label = ctk.CTkLabel(
            video_frame, text="Select a video from the list",
            font=ctk.CTkFont(size=14), text_color=FG3)
        self.no_video_label.place(relx=0.5, rely=0.5, anchor="center")

        # Dual preview panels
        preview_row = ctk.CTkFrame(right, fg_color=BG)
        preview_row.grid(row=1, column=0, sticky="nsew", pady=(0,6))
        preview_row.grid_columnconfigure((0,1), weight=1, uniform="col")
        preview_row.grid_rowconfigure(1, weight=1)

        for col, (title, attr_lbl, attr_img) in enumerate([
            ("CURRENT THUMBNAIL", "lbl_current", "canvas_current"),
            ("PROPOSED FRAME",    "lbl_proposed", "canvas_proposed")
        ]):
            lbl = ctk.CTkLabel(preview_row, text=title,
                               font=ctk.CTkFont(family="Consolas", size=12,
                                                weight="bold"),
                               text_color="#aaaaaa")
            lbl.grid(row=0, column=col, sticky="w",
                     padx=(0 if col else 0, 0), pady=(0,3))
            setattr(self, attr_lbl, lbl)

            pf = ctk.CTkFrame(preview_row, fg_color=BG3, corner_radius=4)
            pf.grid(row=1, column=col, sticky="nsew",
                    padx=(0, 6) if col == 0 else (0,0))
            pf.grid_columnconfigure(0, weight=1)
            pf.grid_rowconfigure(0, weight=1)
            c = tk.Canvas(pf, bg="#0d0d0d", highlightthickness=0)
            c.grid(row=0, column=0, sticky="nsew")
            setattr(self, attr_img, c)
            setattr(self, f"_{attr_img}_ref", None)

        # Filmstrip
        fs_frame = ctk.CTkFrame(right, fg_color="#000000",
                                corner_radius=0, height=88)
        fs_frame.grid(row=2, column=0, sticky="ew", pady=(0,4))
        fs_frame.grid_propagate(False)
        fs_frame.grid_columnconfigure(0, weight=1)
        fs_frame.grid_rowconfigure(0, weight=1)
        self.filmstrip_canvas = tk.Canvas(
            fs_frame, bg="#000000", highlightthickness=0, height=68)
        self.filmstrip_canvas.grid(row=0, column=0, sticky="ew")
        self.timeline_canvas = tk.Canvas(
            fs_frame, bg="#0a0a0a", highlightthickness=0, height=18)
        self.timeline_canvas.grid(row=1, column=0, sticky="ew")
        self.filmstrip_canvas.bind("<Button-1>", self._filmstrip_click)
        self.filmstrip_canvas.bind("<Configure>", self._on_filmstrip_resize)
        self._fs_width = 0
        self._cursor_x = 0

        # Scrub slider
        slider_row = ctk.CTkFrame(right, fg_color=BG)
        slider_row.grid(row=3, column=0, sticky="ew", pady=(0,4))
        slider_row.grid_columnconfigure(0, weight=1)

        self.scrub = ctk.CTkSlider(slider_row, from_=0, to=100,
                                   command=self._on_scrub)
        self.scrub.grid(row=0, column=0, sticky="ew")
        self.scrub.set(0)
        self.scrub.configure(state="disabled")
        self.scrub.bind("<ButtonRelease-1>", self._on_scrub_release)

        self.time_label = ctk.CTkLabel(
            slider_row, text="--:--:-- / --:--:--",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=FG2, width=140)
        self.time_label.grid(row=0, column=1, padx=(8,0))

        # Transport
        transport = ctk.CTkFrame(right, fg_color=BG)
        transport.grid(row=4, column=0, sticky="ew", pady=(0,6))

        btn_cfg = [
            ("◀ 10s", lambda: self._step(-10)),
            ("◀ 1s",  lambda: self._step(-1)),
            ("▶  Play", self._toggle_play),
            ("1s ▶",  lambda: self._step(1)),
            ("10s ▶", lambda: self._step(10)),
        ]
        for i, (txt, cmd) in enumerate(btn_cfg):
            is_play = txt == "▶  Play"
            b = ctk.CTkButton(
                transport, text=txt, width=80 if not is_play else 95,
                command=cmd, state="disabled",
                fg_color=("#1a3a1a" if is_play else "transparent"),
                border_color=("#0a5c0a" if is_play else BORDER),
                border_width=1,
                hover_color=("#2a4a2a" if is_play else "#333333"))
            b.grid(row=0, column=i, padx=(0, 6))
            if is_play:
                self.btn_play = b

        self._transport_buttons = transport.winfo_children()

        # Set thumbnail button
        self.btn_set = ctk.CTkButton(
            right, text="⬤  Set This Frame as Thumbnail",
            height=42, font=ctk.CTkFont(size=14),
            fg_color=GREEN, hover_color="#0a5c0a",
            state="disabled", command=self._set_thumbnail)
        self.btn_set.grid(row=5, column=0, sticky="ew", pady=(0,6))

        # Export buttons
        export_row = ctk.CTkFrame(right, fg_color=BG)
        export_row.grid(row=6, column=0, sticky="ew", pady=(0,6))
        self.btn_export_current = ctk.CTkButton(
            export_row, text="↓  Export Current Thumbnail…",
            width=220, state="disabled",
            command=lambda: self._export_frame(current=True))
        self.btn_export_current.grid(row=0, column=0, padx=(0,8))
        self.btn_export_proposed = ctk.CTkButton(
            export_row, text="↓  Export Proposed Frame…",
            width=220, state="disabled",
            command=lambda: self._export_frame(current=False))
        self.btn_export_proposed.grid(row=0, column=1)

        # Status bar
        self.status = ctk.CTkLabel(
            right, text="Load a folder to begin.",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=FG3, anchor="w",
            fg_color=BG2, corner_radius=4, height=30)
        self.status.grid(row=7, column=0, sticky="ew", pady=(0,0))

    # ── Helpers ───────────────────────────────────────────────
    def set_status(self, msg: str, color: str = FG3):
        self.status.configure(text=f"  {msg}", text_color=color)

    def _enable_transport(self, on: bool):
        state = "normal" if on else "disabled"
        for w in self._transport_buttons:
            w.configure(state=state)
        self.scrub.configure(state=state if on else "disabled")
        self.btn_set.configure(state=state)
        self.btn_export_current.configure(state=state)

    def _show_image_on_canvas(self, canvas: tk.Canvas,
                               pil_img: Image.Image | None,
                               attr: str):
        if pil_img is None:
            canvas.delete("all")
            setattr(self, attr, None)
            return
        cw = canvas.winfo_width()
        ch = canvas.winfo_height()
        if cw < 2 or ch < 2:
            return
        pil_img.thumbnail((cw, ch), Image.LANCZOS)
        tk_img = ImageTk.PhotoImage(pil_img)
        setattr(self, attr, tk_img)
        canvas.delete("all")
        canvas.create_image(cw//2, ch//2, anchor="center", image=tk_img)

    def _update_time_label(self):
        self.time_label.configure(
            text=f"{format_time(self.position)} / {format_time(self.duration)}")

    def _update_cursor(self):
        if self._fs_width <= 0 or self.duration <= 0:
            return
        frac = max(0, min(1, self.position / self.duration))
        self._cursor_x = frac * self._fs_width
        self.filmstrip_canvas.delete("cursor")
        self.filmstrip_canvas.create_rectangle(
            self._cursor_x - 1.5, 0,
            self._cursor_x + 1.5, 68,
            fill=ACCENT, outline="", tags="cursor")

    # ── Folder loading ────────────────────────────────────────
    def _browse(self):
        path = filedialog.askdirectory(title="Select folder containing MP4 files")
        if not path:
            return
        self._load_folder(path)

    def _load_folder(self, path: str):
        self.video_files = sorted(Path(path).glob("*.mp4"),
                                  key=lambda p: p.name.lower())
        self.file_status = {}
        self.file_list.delete(0, tk.END)
        for f in self.video_files:
            self.file_list.insert(tk.END, f"  {f.name}")
        count = len(self.video_files)
        self.folder_label.configure(text=path)
        self.file_count.configure(text=f"{count} MP4 file(s) found")
        self.btn_process_all.configure(
            state="normal" if count > 0 else "disabled")
        self.set_status(f"Folder loaded — {count} file(s). Select a video.",
                        FG2)

    # ── File selection ────────────────────────────────────────
    def _on_file_select(self, _=None):
        sel = self.file_list.curselection()
        if not sel:
            return
        idx  = sel[0]
        path = self.video_files[idx]
        self._load_video(path)

    def _load_video(self, path: Path):
        self._stop_play()
        self.current_file  = path
        self.proposed_ready = False
        self.btn_export_proposed.configure(state="disabled")

        self.set_status(f"Loading {path.name}…", ACCENT)
        self.update_idletasks()

        # Release old capture
        if self.cap:
            self.cap.release()
        self.cap = cv2.VideoCapture(str(path))

        fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = self.cap.get(cv2.CAP_PROP_FRAME_COUNT)
        self.duration = total_frames / fps if fps > 0 else ffprobe_duration(str(path))

        # Seek to stored thumbnail position
        start_pos = get_stored_thumb_pos(str(path))
        start_pos = max(0, min(start_pos, self.duration - 1))
        self.position = start_pos

        self.scrub.configure(to=self.duration)
        self.scrub.set(self.position)
        self._update_time_label()
        self._enable_transport(True)
        self.no_video_label.place_forget()

        # Show current frame on video canvas
        self._refresh_video_canvas()

        # Extract current thumbnail
        threading.Thread(target=self._load_current_thumb,
                         daemon=True).start()
        # Clear proposed
        self._show_image_on_canvas(self.canvas_proposed, None,
                                   "_canvas_proposed_ref")
        # Build filmstrip
        self.filmstrip_canvas.delete("all")
        self.timeline_canvas.delete("all")
        threading.Thread(target=self._build_filmstrip, daemon=True).start()

        self.set_status(
            f"Loaded: {path.name}  ({format_time(self.duration)})", FG2)

    def _refresh_video_canvas(self):
        """Draw current position frame on video canvas."""
        if not self.cap:
            return
        img = cv_frame_at(self.cap, self.position)
        if img:
            self._show_image_on_canvas(self.video_canvas, img,
                                       "_video_img_ref")

    def _on_canvas_resize(self, _=None):
        self._refresh_video_canvas()

    # ── Current thumbnail ─────────────────────────────────────
    def _load_current_thumb(self):
        if not self.current_file:
            return
        tmp = os.path.join(self.temp_dir, "current_thumb.jpg")
        try:
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", str(self.current_file),
                 "-map", "0:v:1", "-frames:v", "1", "-q:v", "2", tmp],
                capture_output=True, timeout=15
            )
            if not os.path.exists(tmp):
                # Fallback: frame at position 0
                subprocess.run(
                    ["ffmpeg", "-y", "-ss", "0", "-i", str(self.current_file),
                     "-frames:v", "1", "-q:v", "2", tmp],
                    capture_output=True, timeout=15
                )
        except Exception:
            pass
        if os.path.exists(tmp):
            try:
                img = Image.open(tmp).copy()
                self.after(0, lambda: self._show_image_on_canvas(
                    self.canvas_current, img, "_canvas_current_ref"))
            except Exception:
                pass

    # ── Playback ──────────────────────────────────────────────
    def _toggle_play(self):
        if self.playing:
            self._stop_play()
            self._extract_proposed()
        else:
            self.playing = True
            self.btn_play.configure(text="⏸  Pause",
                                    fg_color="#3a1a1a",
                                    border_color="#5a0a0a")
            self._play_tick()

    def _stop_play(self):
        self.playing = False
        if self._play_job:
            self.after_cancel(self._play_job)
            self._play_job = None
        self.btn_play.configure(text="▶  Play",
                                fg_color="#1a3a1a",
                                border_color="#0a5c0a")

    def _play_tick(self):
        if not self.playing or not self.cap:
            return
        ok, frame = self.cap.read()
        if not ok or self.position >= self.duration:
            self._stop_play()
            self._extract_proposed()
            return
        self.position = self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(img)
        self._show_image_on_canvas(self.video_canvas, pil, "_video_img_ref")
        self.scrub.set(self.position)
        self._update_time_label()
        self._update_cursor()
        # ~30fps tick
        self._play_job = self.after(33, self._play_tick)

    def _step(self, secs: float):
        if not self.cap:
            return
        self.position = max(0, min(self.duration, self.position + secs))
        self.scrub.set(self.position)
        self._update_time_label()
        self._refresh_video_canvas()
        self._update_cursor()
        self._extract_proposed()

    def _on_scrub(self, val):
        self.position = float(val)
        self._update_time_label()
        self._update_cursor()

    def _on_scrub_release(self, _=None):
        self.position = self.scrub.get()
        if self.cap:
            fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
            self.cap.set(cv2.CAP_PROP_POS_FRAMES,
                         int(self.position * fps))
        self._refresh_video_canvas()
        self._update_cursor()
        if not self.playing:
            self._extract_proposed()

    # ── Proposed frame ────────────────────────────────────────
    def _extract_proposed(self):
        if not self.cap or not self.current_file:
            return
        img = cv_frame_at(self.cap, self.position)
        if img:
            self.proposed_ready = True
            self._show_image_on_canvas(self.canvas_proposed, img,
                                       "_canvas_proposed_ref")
            self.btn_export_proposed.configure(state="normal")

    # ── Set thumbnail ─────────────────────────────────────────
    def _set_thumbnail(self):
        if not self.current_file or not self.proposed_ready:
            self.set_status("No frame selected — scrub or pause first.",
                            "#e67e22")
            return
        secs = self.position
        path = self.current_file
        name = path.name

        self.set_status(f"Embedding thumbnail: {name} @ {format_time(secs)}…",
                        "#f39c12")
        self.update_idletasks()

        # Release cap so FFmpeg can write the file
        if self.cap:
            self.cap.release()
            self.cap = None

        def do_embed():
            ok = embed_thumbnail(str(path), secs, self.temp_dir)
            def finish():
                # Reload cap
                self.cap = cv2.VideoCapture(str(path))
                if ok:
                    idx = self.video_files.index(path)
                    self._set_file_status(idx, "done")
                    # Refresh current thumb panel
                    threading.Thread(target=self._load_current_thumb,
                                     daemon=True).start()
                    self.set_status(
                        f"Done: {name} @ {format_time(secs)}", "#27ae60")
                    # Auto-advance
                    cur_sel = self.file_list.curselection()
                    if cur_sel:
                        next_idx = cur_sel[0] + 1
                        if next_idx < len(self.video_files):
                            self.file_list.selection_clear(0, tk.END)
                            self.file_list.selection_set(next_idx)
                            self.file_list.see(next_idx)
                            self._load_video(self.video_files[next_idx])
                else:
                    self.set_status(f"Embed failed for {name}", RED)
            self.after(0, finish)

        threading.Thread(target=do_embed, daemon=True).start()

    # ── File list status coloring ─────────────────────────────
    def _set_file_status(self, idx: int, status: str):
        if idx < 0 or idx >= len(self.video_files):
            return
        self.file_status[idx] = status
        name = self.video_files[idx].name
        prefix = "◆ " if status == "proposed" else "✓ " if status == "done" else "  "
        color  = "#f0a500" if status == "proposed" else "#27ae60" if status == "done" else FG
        self.file_list.delete(idx)
        self.file_list.insert(idx, f"{prefix}{name}")
        self.file_list.itemconfigure(idx, fg=color)

    # ── Export ────────────────────────────────────────────────
    def _export_frame(self, current: bool):
        if not self.current_file:
            return
        ext_map = [("JPEG", "*.jpg"), ("PNG", "*.png"), ("TIFF", "*.tiff")]
        out = filedialog.asksaveasfilename(
            title="Export Current Thumbnail" if current else "Export Proposed Frame",
            defaultextension=".jpg", filetypes=ext_map,
            initialfile=f"{self.current_file.stem}_"
                        f"{'thumbnail' if current else f'frame_{format_time(self.position).replace(':', '-')}'}",
        )
        if not out:
            return
        self.set_status("Exporting…", "#f39c12")
        if current:
            tmp = os.path.join(self.temp_dir, "export_thumb.jpg")
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(self.current_file),
                 "-map", "0:v:1", "-frames:v", "1", tmp],
                capture_output=True, timeout=15
            )
            src = tmp if os.path.exists(tmp) else None
            if not src:
                subprocess.run(
                    ["ffmpeg", "-y", "-ss", "0", "-i", str(self.current_file),
                     "-frames:v", "1", src := os.path.join(self.temp_dir, "export_f0.jpg")],
                    capture_output=True, timeout=15
                )
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

    # ── Filmstrip ─────────────────────────────────────────────
    def _on_filmstrip_resize(self, event):
        self._fs_width = event.width
        self._build_timeline()
        self._update_cursor()

    def _build_filmstrip(self):
        if not self.current_file or not self.cap:
            return
        n    = self.filmstrip_count
        dur  = self.duration
        if dur <= 0:
            return
        w = self._fs_width or self.filmstrip_canvas.winfo_width()
        if w < 2:
            w = 800

        cell_w = w // n
        cell_h = 68

        self.filmstrip_images = []
        for i in range(n):
            ts = (i + 0.5) * (dur / n)
            img = cv_frame_at(self.cap, ts)
            if img:
                img = img.resize((cell_w, cell_h), Image.LANCZOS)
                tk_img = ImageTk.PhotoImage(img)
                self.filmstrip_images.append(tk_img)
                x = i * cell_w
                self.after(0, lambda x=x, tk_img=tk_img:
                           self.filmstrip_canvas.create_image(
                               x, 0, anchor="nw", image=tk_img))
            self.after(0, self._update_cursor)
        self.after(0, self._build_timeline)

    def _build_timeline(self):
        self.timeline_canvas.delete("all")
        w = self._fs_width or self.timeline_canvas.winfo_width()
        if w < 2 or self.duration <= 0:
            return
        candidates = [15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200]
        interval   = next((c for c in candidates
                           if self.duration / c <= 12), 7200)
        t = interval
        while t < self.duration:
            x = (t / self.duration) * w
            self.timeline_canvas.create_line(x, 0, x, 5, fill="#444444")
            self.timeline_canvas.create_text(
                x, 12, text=format_time(t),
                fill="#666666", font=("Consolas", 8), anchor="center")
            t += interval

    def _filmstrip_click(self, event):
        if self.duration <= 0 or self._fs_width <= 0:
            return
        secs = (event.x / self._fs_width) * self.duration
        secs = max(0, min(self.duration, secs))
        self.position = secs
        self.scrub.set(secs)
        self._update_time_label()
        self._update_cursor()
        if self.cap:
            fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, int(secs * fps))
        self._refresh_video_canvas()
        if not self.playing:
            self._extract_proposed()

    # ── Batch process ─────────────────────────────────────────
    def _process_all(self):
        if not messagebox.askyesno(
                "Set All Thumbnails",
                f"Process all {len(self.video_files)} MP4 files?\n"
                "Only files with a proposed frame selected will be changed."):
            return
        for idx, path in enumerate(self.video_files):
            if self.file_status.get(idx) in ("proposed",):
                self.set_status(f"Processing {path.name}…", "#f39c12")
                self.update_idletasks()
                if self.cap:
                    self.cap.release()
                    self.cap = None
                ok = embed_thumbnail(str(path), self.position, self.temp_dir)
                if ok:
                    self._set_file_status(idx, "done")
                self.cap = cv2.VideoCapture(str(path))
        self.set_status("Batch complete.", "#27ae60")

    def cleanup(self):
        self._stop_play()
        if self.cap:
            self.cap.release()
            self.cap = None


# ── Main window ───────────────────────────────────────────────
class ReelSheetApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1200x820")
        self.minsize(900, 600)
        self.configure(fg_color=BG)

        if not ffmpeg_available():
            messagebox.showerror(
                "FFmpeg Missing",
                "FFmpeg is not found in PATH.\n"
                "Please install FFmpeg and ensure it's in your PATH.")
            self.destroy()
            return

        self.temp_dir = tempfile.mkdtemp(prefix="reelsheet_")
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color=BG2, height=44, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            header,
            text=f"  🎬  {APP_NAME}",
            font=ctk.CTkFont(family="Consolas", size=16, weight="bold"),
            text_color=FG
        ).pack(side="left", padx=8)
        ctk.CTkLabel(
            header,
            text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=11),
            text_color=FG3
        ).pack(side="left")

        # Tabs
        self.tabs = ctk.CTkTabview(self, fg_color=BG,
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

        # Contact Sheet tab — placeholder for v0.2.0
        cs_frame = ctk.CTkFrame(
            self.tabs.tab("  📋  Contact Sheet  "), fg_color=BG)
        cs_frame.pack(fill="both", expand=True)
        ctk.CTkLabel(
            cs_frame,
            text="Contact Sheet\nComing in v0.2.0",
            font=ctk.CTkFont(size=18),
            text_color=FG3
        ).place(relx=0.5, rely=0.5, anchor="center")

    def _on_close(self):
        self.picker.cleanup()
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    app = ReelSheetApp()
    app.mainloop()
