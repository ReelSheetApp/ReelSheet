# ReelSheet Handoff

## Current State

ReelSheet is a Python desktop app for video thumbnail picking and future contact sheet generation. The active version is `reelsheet_v0.1.24.py`.

Use:

```bat
cd /d C:\ReelSheet
run.bat
```

Current `run.bat`:

```bat
@echo off
python reelsheet_v0.1.24.py
pause
```

The project folder is `C:\ReelSheet`. The user accidentally referenced `C:\ReelSheets`, but that folder does not exist.

## Architecture

The app is still single-file Python per version:

- `ReelSheetApp`: main CustomTkinter window, header, tabs, diagnostics toggle.
- `ThumbnailPickerTab`: main working tab for browsing videos, previewing current/proposed frames, playback, thumbnail embedding, export, layout controls.
- `DiagnosticsWindow`: separate Tk toplevel for audio/player diagnostics and log viewing.
- `ContactSheetTab`: placeholder for v0.2.0.

Main stack:

- `customtkinter`
- `tkinter`
- `opencv-python`
- `Pillow`
- `python-vlc`
- FFmpeg / ffprobe at `C:\ffmpeg\bin`

Audio architecture remains:

- VLC direct MP4 audio is primary.
- pygame fallback still exists for extraction-based audio if VLC is unavailable.
- Do not change audio logic without reading `C:\ReelSheet\reelsheet_audio.log`.

## Important Files

| File | Purpose |
| --- | --- |
| `C:\ReelSheet\reelsheet_v0.1.24.py` | Active app version |
| `C:\ReelSheet\run.bat` | Launches active version |
| `C:\ReelSheet\reelsheet_prefs.json` | Stores last folder and layout values |
| `C:\ReelSheet\reelsheet_audio.log` | Audio/session diagnostic log |
| `C:\ReelSheet\test_reelsheet_v0_1_10_helpers.py` | Helper tests, currently points at latest active file |
| `C:\Users\Kevin\.codex\skills\markdown-doc-architect\SKILL.md` | Newly created Markdown documentation skill |

## Recent Version History

| Version | Summary |
| --- | --- |
| `v0.1.17` | Graphite visual polish, larger labeled transport, previous/next video, shortcuts |
| `v0.1.18` | Fixed shortcut binding startup crash by binding to root window |
| `v0.1.19` | Mockup-inspired player frame, filmstrip well, action row, header icon |
| `v0.1.20` | Centered equal-width action buttons with full export labels |
| `v0.1.21` | Fixed scrub slider while playing, centered controls, proposed-state highlight |
| `v0.1.22` | Golden-ratio default layout, save/default layout controls, proposed image border |
| `v0.1.23` | Fixed saved/default layout restore and attempted row alignment |
| `v0.1.24` | Attempted lower control fix: volume left, transport/action groups centered |

## Current Preferences

Current `reelsheet_prefs.json`:

```json
{
  "last_dir": "D:\\E\\Wicked Smoking SVP\\Hot lesbian Stepmothers & stepdaughters",
  "sash_outer": 160,
  "sash_inner": 378,
  "layout_outer": 340,
  "layout_inner": 432,
  "layout_outer_ratio": 0.18,
  "layout_inner_ratio": 0.28
}
```

The latest layout system stores ratios:

- `layout_outer_ratio`: file list width relative to main body.
- `layout_inner_ratio`: thumbnail column width relative to content area.

`Save Layout` should persist ratios. `Default Layout` should restore the defaults.

## Known Issues

1. Lower controls need visual verification in `v0.1.24`.
   - User reported in `v0.1.23` that volume was broken and buttons were not centered.
   - `v0.1.24` attempted to fix this by making volume left-aligned and transport/action groups independently centered.
   - The user has not yet confirmed the `v0.1.24` result.

2. Backup/restore thumbnail is planned.
   - Before embedding a new thumbnail, save the existing embedded thumbnail as a sidecar backup.
   - Add `Restore Previous Thumbnail`.
   - Prefer backing up only the embedded thumbnail image, not the full video file.

3. Timecode shuttle is planned.
   - Premiere-style drag on timecode.
   - Drag right scans forward, drag left scans backward.
   - Audio can stay stopped during shuttle.

4. Theme selector is planned.
   - Dark, Light, Colorblind.
   - Do not combine with playback fixes in the same pass.

5. `Set All Thumbnails` may be removed.
   - Current workflow embeds immediately with `Set This Frame`.
   - Batch set only makes sense if the app supports staging multiple proposed frames.

## Decisions Made

- Keep versioned files. Do not overwrite a previous working version for intentional changes.
- If a new version fails to launch immediately, fix that same version until it launches instead of creating another bump.
- Use normal `python ...py` launcher with `pause`. Do not switch to `pythonw` without a separately tested launcher plan.
- Keep `run.bat` pointed to latest intended test version.
- Keep proposed image highlight. User liked image border better than pane border.
- Keep labeled transport buttons; no icon-only core workflow buttons.
- Keep `1s` and `10s` buttons.
- Keep `Prev Video` and `Next Video`.
- Keep volume separate from centered transport controls.

## UI Direction

The user liked the generated mockup direction:

- Graphite dark UI.
- Video player frame.
- Filmstrip borders/well.
- Clean button layout.
- ReelSheet header icon direction.
- Exports and Set button grouped under the player.

Current intent for lower controls:

- Row 1: scrubber/timecode full width.
- Row 2: volume fixed far-left, transport fixed-width group centered.
- Row 3: action fixed-width group centered on same axis as transport.

Action buttons should be equal width and centered:

- `Set This Frame as Thumbnail`
- `Export Current Frame`
- `Export Proposed Frame`

Set button default color:

- Blue by default.
- Amber/orange when a proposed frame exists.

## Keyboard Shortcuts

Current shortcuts:

| Shortcut | Action |
| --- | --- |
| `Space` | Play/Pause |
| `Left` | Step back 1 second |
| `Right` | Step forward 1 second |
| `Shift+Left` | Step back 10 seconds |
| `Shift+Right` | Step forward 10 seconds |
| `Ctrl+Left` | Previous video |
| `Ctrl+Right` | Next video |

## Verification Commands

Run after edits:

```powershell
python -m py_compile C:\ReelSheet\reelsheet_v0.1.24.py
python C:\ReelSheet\test_reelsheet_v0_1_10_helpers.py
```

Startup smoke pattern:

```powershell
@'
import importlib.util
from pathlib import Path
p=Path('C:/ReelSheet/reelsheet_v0.1.24.py')
spec=importlib.util.spec_from_file_location('rs', p)
rs=importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)
app = rs.ReelSheetApp()
app.after(50, app.destroy)
app.mainloop()
print('startup smoke ok')
'@ | python -
```

## Markdown Skill

A new Codex skill was created:

`C:\Users\Kevin\.codex\skills\markdown-doc-architect`

Purpose:

- Build structurally correct Markdown docs.
- Includes `SKILL.md`, `agents/openai.yaml`, templates, and a Markdown structure validator.

Restart VS Code / Codex to auto-discover it. In the current session, it can be used by explicitly reading:

`C:\Users\Kevin\.codex\skills\markdown-doc-architect\SKILL.md`

## Notes For Future Agents

- Begin responses with `[YYYY-MM-DD HH:mm] PT` if continuing the ReelSheet style.
- Kevin is PM/director, not a coder. Explain decisions clearly and avoid jargon without context.
- Treat software process as part of the deliverable: explain what you are doing and why, especially around GitHub, releases, changelogs, packaging, and professional project hygiene.
- Use `apply_patch` for manual file edits.
- Do not use destructive git commands.
- This repo currently appears uncommitted/untracked; do not assume git history protects changes.
- `C:\ReelSheet` is the real project folder.
- Verify GUI startup before saying a version is ready.
- Prefer scoped versions:
  - patch bump for bug fixes and visual iterations
  - minor bump for Contact Sheet milestone
