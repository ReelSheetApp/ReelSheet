# ReelSheet — Project Handoff Summary
*Load this into a new Claude chat to continue development*

---

## What Is ReelSheet

A Python desktop app for video thumbnail picking and contact sheet generation.
Open source, MIT license. Target users: anyone managing large video libraries.
Built for Windows, planned cross-platform eventually.

**GitHub:** https://github.com/ReelSheetApp/ReelSheet
**GitHub account:** ReelSheetApp (reelsheet40@gmail.com)
**Local repo:** C:\ReelSheet\
**Claude has Filesystem MCP access to C:\ReelSheet\ — read/write directly.**

---

## Tech Stack

- Python 3.14.0 at C:\Python314\
- customtkinter 5.2.2 — dark UI framework
- opencv-python 4.13 — frame-accurate video seeking
- Pillow 12.2 — image operations
- pygame-ce — audio playback (install status unknown at handoff; pygame 2.6.1
  fails on Python 3.14 due to distutils removal. Try: pip install pygame-ce)
- pyinstaller 6.20 — exe compilation at end of project
- FFmpeg in PATH — thumbnail embedding, audio extraction, frame export
- VS Code with Codex extension, open at C:\ReelSheet\

---

## Current Version: v0.1.2

**File:** C:\ReelSheet\reelsheet_v0.1.2.py
**Run:** python reelsheet_v0.1.2.py or double-click run.bat

### Version History
- v0.1.0 — full Thumbnail Picker tab, Contact Sheet placeholder
- v0.1.1 — wall-clock playback attempt (still slow, seeking every tick)
- v0.1.2 — fixed playback: sequential cap.read() + cap.grab() frame skipping;
            added pygame-ce audio (OGG extraction on load, play/pause/seek sync)

### File Naming Convention
Scripts: reelsheet_vX.Y.Z.py in C:\ReelSheet\
Zips when needed: ReelSheet_vX.Y.Z.zip
run.bat always points to latest version

---

## App Architecture — Single File

### ThumbnailPickerTab(ctk.CTkFrame) — Tab 1, fully working
Left panel:
- Browse Folder button
- Folder path label (Consolas 10pt, dim)
- MP4 file listbox with ◆ (proposed) / ✓ (done) status coloring
- File count label
- "Set All Thumbnails" batch button

Right panel (top to bottom):
- Video canvas (tk.Canvas, black bg)
- Dual preview row: CURRENT THUMBNAIL | PROPOSED FRAME (both tk.Canvas)
- Filmstrip (20 frames, 68px tall) + timeline (18px) — built in background thread
- Scrub slider + time label (Consolas HH:MM:SS / HH:MM:SS)
- Volume slider (only shown if pygame available)
- Transport: ◀10s  ◀1s  ▶Play/⏸Pause  1s▶  10s▶
- "⬤ Set This Frame as Thumbnail" (green, 42px tall)
- Export Current Thumbnail | Export Proposed Frame
- Status bar (Consolas 12pt, BG2 background)

### ContactSheetTab — Tab 2, placeholder only ("Coming in v0.2.0")

### ReelSheetApp(ctk.CTk) — main window
- 1200x820, min 900x600
- Header bar: app name + version + pygame warning if not installed
- CTkTabview with both tabs
- Temp dir created on launch, cleaned on close

---

## Key Functions

```python
cv_frame_at(cap, seconds)
# Seeks OpenCV cap to seconds, returns PIL Image or None

embed_thumbnail(video_path, seconds, temp_dir)
# FFmpeg: extract frame → re-mux MP4 with attached_pic
# Writes comment=thumb_pos={seconds} in format metadata
# Calls SHChangeNotify to refresh Windows Explorer thumbnail cache

get_stored_thumb_pos(path)
# ffprobe reads format_tags=comment, parses thumb_pos=X.XXX
# Used to restore scrub position when re-opening a file

_play_tick()
# Wall clock determines target position
# cap.grab() skips frames without decode (fast) when behind
# cap.read() decodes and displays current frame
# 8ms timer interval — frame skipping controls speed, not timer

_extract_audio()
# Background thread: ffmpeg -vn → temp OGG → pygame.mixer.music.load()
# Runs on every video load

_build_filmstrip()
# Background thread, 20 evenly-spaced frames
# after(0, lambda) posts each frame to main thread as it completes

format_time(seconds) → "H:MM:SS"
```

---

## Open Issues at Handoff

1. pygame-ce install not yet confirmed — may need troubleshooting
2. v0.1.2 playback speed not yet confirmed by user
3. Audio/video sync on seek not yet tested
4. No git commits pushed yet — repo has only GitHub's initial commit

---

## Roadmap

### v0.1.x — Thumbnail Picker polish (current phase)
- [ ] Confirm v0.1.2 playback speed correct
- [ ] Confirm audio works with pygame-ce
- [ ] First git commit and push
- [ ] End-to-end test: embed thumbnail, verify Explorer updates
- [ ] Test auto-advance after setting thumbnail

### v0.2.0 — Contact Sheet tab (next major milestone)
Full Python port of the proven PowerShell design:
- Grid size picker: 4, 6, 9, 12, 16, 20, 25 frames
- Random Fill: evenly-spaced segments, ±10% jitter, 15s offset from ends
- Click frame to remove → shows gap fill slot with time range
- Gap fill: random frame from deleted frame's time window
- Drag to reorder frames
- Timestamp overlay toggle
- Blur toggle (display + export)
- Export via Pillow compositing → JPG/PNG
- Filename: {stem}_{cols}x{rows}_contact_sheet.{ext}

### Later
- Multi-format: MKV, AVI, WMV, MOV, MPG
- PyInstaller exe compile
- GitHub README + Release with exe artifact

---

## Design Constants

```python
ACCENT = "#0078d4"   # blue
GREEN  = "#107c10"
RED    = "#c42b1c"
BG     = "#1a1a1a"   # main bg
BG2    = "#141414"   # left panel, header
BG3    = "#0d0d0d"   # canvas areas
BORDER = "#2a2a2a"
FG     = "#e0e0e0"   # primary text
FG2    = "#888888"   # secondary text
FG3    = "#555555"   # dim / status
```

---

## Interaction Notes for Claude

- Kevin is PM/director — not a coder. Explain decisions clearly.
- All responses begin with [YYYY-MM-DD HH:mm] PT timestamp.
- Version every file. Never overwrite without bumping version number.
- Direct, factual communication. No filler phrases.
- Claude has Filesystem MCP write access to C:\ReelSheet\ — write files
  directly there instead of sending zips unless Kevin asks for a zip.
- Zip files named ReelSheet_vX.Y.Z.zip when needed.
- Patch bumps (0.1.x) for bug fixes. Minor bumps (0.x.0) for new features.
