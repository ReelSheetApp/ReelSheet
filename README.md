# ReelSheet

ReelSheet is a Windows-focused Python desktop app for browsing videos, choosing better thumbnail frames, and embedding those thumbnails back into MP4 files.

The current app is an early preview. The thumbnail picker is the working area. Contact sheet generation is planned for `v0.2.0`.

## Current Version

Active development version:

```text
reelsheet_v0.1.24.py
```

Launch from the project folder:

```bat
cd /d C:\ReelSheet
run.bat
```

Current `run.bat` launches `reelsheet_v0.1.24.py`.

## Current Features

- Browse a folder of MP4 files.
- Preview the currently embedded thumbnail.
- Scrub, play, pause, and step through video frames.
- Pick a proposed frame as the new thumbnail.
- Embed the selected frame into the MP4 file.
- Export the current frame or proposed frame as an image.
- Use VLC direct audio when available.
- View diagnostics for audio/player state.
- Save and restore layout sizing preferences.
- Use keyboard shortcuts for common playback and navigation actions.

## Requirements

Development currently expects:

- Windows
- Python 3.14
- FFmpeg and ffprobe available at `C:\ffmpeg\bin`
- VLC installed for direct MP4 audio
- Python packages listed in `requirements.txt`
- `python-vlc` for VLC audio support

Install Python packages from the project folder:

```powershell
python -m pip install -r requirements.txt
python -m pip install python-vlc
```

## Keyboard Shortcuts

| Shortcut | Action |
| --- | --- |
| `Space` | Play or pause |
| `Left` | Step back 1 second |
| `Right` | Step forward 1 second |
| `Shift+Left` | Step back 10 seconds |
| `Shift+Right` | Step forward 10 seconds |
| `Ctrl+Left` | Previous video |
| `Ctrl+Right` | Next video |

## Project Layout

The app is currently kept as versioned single-file Python scripts:

```text
reelsheet_v0.1.24.py       Active app version
run.bat                    Launches the active app version
requirements.txt           Python package requirements
CHANGELOG.md               Version history
ReelSheet_Handoff_*.md     Development handoff notes
test_reelsheet_*.py        Helper tests
```

Local videos, logs, debug frames, caches, and user preferences are intentionally ignored by Git.

## Known Limitations

- The app is not packaged as an installer or `.exe` yet.
- Contact Sheet is still a placeholder.
- MP4 is the primary tested workflow.
- VLC runtime is not bundled yet, so local VLC installation is expected for direct audio.
- `v0.1.24` lower control layout still needs visual confirmation.
- Thumbnail backup/restore is planned but not implemented yet.

## Roadmap

Near-term `v0.1.x` work:

- Confirm and polish lower control layout.
- Add embedded thumbnail backup before replacement.
- Add `Restore Previous Thumbnail`.
- Add timecode shuttle dragging.
- Add Dark, Light, and Colorblind theme options.
- Decide whether `Set All Thumbnails` belongs in the app.

Planned `v0.2.0` work:

- Build the Contact Sheet tab.
- Support grid size selection.
- Add random fill and gap fill workflows.
- Add drag reorder.
- Add timestamp and blur toggles.
- Export contact sheets as JPG or PNG.

## Release Status

ReelSheet is not public-release ready yet. A future public release should include a packaged Windows download, screenshots, release notes, known issues, and clear install/run instructions.

## License

MIT License. See `LICENSE`.
