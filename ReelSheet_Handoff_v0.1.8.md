# ReelSheet — Project Handoff Summary v0.1.8
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
- opencv-python 4.13 — frame-accurate video seeking and display
- Pillow 12.2 — image operations
- python-vlc 3.0.21203 — primary audio (direct MP4, no extraction)
- pygame-ce — audio fallback if VLC not found (OGG extraction path)
- pyinstaller 6.20 — exe compilation at end of project
- FFmpeg in PATH — thumbnail embedding, frame export, audio fallback extraction
- VS Code with Codex extension, open at C:\ReelSheet\

---

## Current Version: v0.1.8

**File:** C:\ReelSheet\reelsheet_v0.1.8.py
**Run:** python reelsheet_v0.1.8.py or double-click run.bat

### Version History
- v0.1.0 — full Thumbnail Picker tab, Contact Sheet placeholder
- v0.1.1 — wall-clock playback attempt (still slow)
- v0.1.2 — fixed playback: sequential cap.read() + cap.grab(); pygame-ce audio (OGG extraction)
- v0.1.3–v0.1.6 — UI iterations: sash dividers, layout changes, audio attempts (see files)
- v0.1.7 — Diagnostics window (separate Toplevel, toggled from header)
- v0.1.8 — **current**: python-vlc as primary audio stack; pygame OGG extraction as fallback; header audio indicator; mutable speaker icon; Diagnostics updated for VLC monitoring

### File Naming Convention
Scripts: reelsheet_vX.Y.Z.py in C:\ReelSheet\
run.bat always points to latest version

---

## Audio Architecture — Critical Context

**The problem we solved:** pygame-ce cannot decode MP4/AAC directly (`XMP: Unrecognized file format`). The OGG extraction workaround (FFmpeg converts entire audio track to OGG before pygame can play) took 44 seconds on a typical file — confirmed via Diagnostics log at C:\ReelSheet\reelsheet_audio.log.

**The solution:** python-vlc loads the source MP4 directly via libvlc.dll from the system VLC installation. No extraction, no temp files, instant audio start on Play.

**Stack priority at startup:**
1. `VLC_OK = True` — python-vlc imports and `vlc.Instance()` succeeds → direct MP4 audio
2. `PYGAME_OK = True` — pygame-ce imports → OGG extraction fallback (slow but works)
3. Both fail → silent, warning shown in header

**Header indicator** (always visible):
- `● VLC` green — VLC direct, instant audio
- `● pygame` yellow — extraction fallback, ~44s wait for audio
- `⚠ no audio` red — neither found

**v0.1.8 was just written and not yet tested.** First run will confirm whether VLC initializes correctly and whether audio starts immediately on Play.

**Planned next step:** Once VLC audio confirmed working, copy VLC runtime (`libvlc.dll`, `libvlccore.dll`, full `plugins\` folder) from system VLC install into `C:\ReelSheet\vlc_runtime\`, point python-vlc at that directory. App becomes self-contained, no system VLC required for end users. Full plugin set kept for broad codec support (MKV, AVI, MOV, etc.).

---

## App Architecture — Single File

### ThumbnailPickerTab(ctk.CTkFrame) — Tab 1, fully working
Left panel (fixed 260px):
- Browse Folder button
- Folder path label (Consolas 10pt)
- MP4 file listbox with ◆ (proposed) / ✓ (done) status coloring
- File count label
- "Set All Thumbnails" batch button

Right panel (top to bottom):
- Video canvas (tk.Canvas, black bg) — weight=3
- Dual preview row: CURRENT THUMBNAIL | PROPOSED FRAME — weight=2
- Filmstrip (20 frames, 68px tall) + timeline (18px) — built in background thread
- Scrub slider + time label (Consolas HH:MM:SS / HH:MM:SS)
- Volume row: 🔊 icon (size 18, clickable to mute/unmute) + slider
- Transport: ◀10s  ◀1s  ▶Play/⏸Pause  1s▶  10s▶
- "⬤ Set This Frame as Thumbnail" (green, 42px tall)
- Export Current Thumbnail | Export Proposed Frame
- Status bar (Consolas 12pt, BG2 background)

### DiagnosticsWindow — separate Toplevel
- Toggled by 🔍 Diagnostics button in header bar (turns blue when open)
- Three VU meters: EXTRACT / PLAYER / VOLUME
- Status grid: audio stack, VLC state, VLC position, VLC length, extract state, OGG size, audio_ready, last Play timestamp, last _audio_play timestamp
- Scrolling timestamped event log with color coding
- Clear Log / Save Log buttons
- All events also written to C:\ReelSheet\reelsheet_audio.log
- Polling pauses when window hidden

### ContactSheetTab — Tab 2, placeholder only ("Coming in v0.2.0")

### ReelSheetApp(ctk.CTk) — main window
- 1200x820, min 900x600
- Header: app name + version + audio stack indicator + Diagnostics toggle
- CTkTabview with both tabs

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

_audio_play(position)
# VLC: set_time(ms) + play() — instant, no extraction
# pygame fallback: load OGG + play(start=position)

_play_tick()
# Wall clock determines target position
# cap.grab() skips frames without decode when behind
# cap.read() decodes and displays current frame
# 8ms timer interval

_build_filmstrip()
# Background thread, 20 evenly-spaced frames
# after(0, lambda) posts each frame to main thread as it completes
```

---

## Design Constants

```python
ACCENT = "#0078d4"   # blue
GREEN  = "#107c10"
RED    = "#c42b1c"
YELLOW = "#c07c10"
BG     = "#1a1a1a"   # main bg
BG2    = "#141414"   # left panel, header
BG3    = "#0d0d0d"   # canvas areas
BORDER = "#2a2a2a"
FG     = "#e0e0e0"   # primary text
FG2    = "#888888"   # secondary text
FG3    = "#555555"   # dim / status
```

---

## Open Issues / Immediate Next Steps

1. **v0.1.8 not yet tested** — run and confirm `● VLC` green in header and audio works on first Play press
2. **If VLC works:** copy VLC runtime into `C:\ReelSheet\vlc_runtime\` and point python-vlc at it (self-contained, no system VLC dependency)
3. **Sash dividers from v0.1.5** were removed when rolling back to v0.1.2 base — re-add once audio is confirmed stable
4. **Contact Sheet tab** — v0.2.0 milestone, full Python port of proven PowerShell design

---

## Roadmap

### v0.1.x — Thumbnail Picker polish (current phase)
- [x] Confirm v0.1.2 playback speed correct
- [ ] **Confirm VLC audio works (v0.1.8 — immediate)**
- [ ] Bundle VLC runtime into vlc_runtime\ dir
- [ ] Re-add sash dividers (v0.1.5 layout)
- [ ] First git commit and push
- [ ] End-to-end test: embed thumbnail, verify Explorer updates

### v0.2.0 — Contact Sheet tab (next major milestone)
Full Python port of the proven PowerShell design:
- Grid size picker: 4, 6, 9, 12, 16, 20, 25 frames
- Random Fill: evenly-spaced segments, ±10% jitter, 15s offset from ends
- Click frame to remove → gap fill slot with time range
- Gap fill: random frame from deleted frame's time window
- Drag to reorder frames
- Timestamp overlay toggle
- Blur toggle (display + export)
- Export via Pillow compositing → JPG/PNG
- Filename: {stem}_{cols}x{rows}_contact_sheet.{ext}

### Later
- Multi-format: MKV, AVI, WMV, MOV, MPG (VLC handles these natively)
- PyInstaller exe compile with bundled VLC runtime
- GitHub README + Release with exe artifact

---

## Interaction Notes for Claude

- Kevin is PM/director — not a coder. Explain decisions clearly.
- All responses begin with [YYYY-MM-DD HH:mm] PT timestamp.
- Version every file. Never overwrite without bumping version number.
- Direct, factual communication. No filler phrases.
- Claude has Filesystem MCP write access to C:\ReelSheet\ — write files directly there instead of sending zips unless Kevin asks for a zip.
- Patch bumps (0.1.x) for bug fixes. Minor bumps (0.x.0) for new features.
- Log file at C:\ReelSheet\reelsheet_audio.log — Claude can read this directly to diagnose audio issues.
- Do not change audio logic without reading the log first.
- v0.1.8 is the active development base. Do not revert to earlier versions without explicit instruction.
