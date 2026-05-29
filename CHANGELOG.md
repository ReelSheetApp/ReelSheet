# Changelog

All notable ReelSheet changes are tracked here.

ReelSheet is currently in early preview. The `v0.1.x` entries below are development snapshots, not public commercial releases. Public releases should use cleaner release notes focused on user-visible changes, fixed issues, known limitations, and upgrade guidance.

## Unreleased

Planned work:

- Add backup of the current embedded thumbnail before replacing it.
- Add `Restore Previous Thumbnail`.
- Add Premiere-style timecode shuttle dragging.
- Add Dark, Light, and Colorblind theme options.
- Decide whether `Set All Thumbnails` should remain or be replaced by a staged batch workflow.

## v0.1.24 - 2026-05-28

Lower control layout refinement.

- Kept volume controls left-aligned.
- Centered transport controls independently.
- Centered action buttons independently.
- Kept action buttons equal width.
- Status: needs visual confirmation.

## v0.1.23 - 2026-05-28

Layout persistence fix.

- Fixed saved/default layout restore behavior.
- Continued transport and action row alignment work.

## v0.1.22 - 2026-05-28

Layout controls and proposed-frame polish.

- Added golden-ratio default layout behavior.
- Added save/default layout controls.
- Added proposed image border highlight.
- Stored layout sizing as ratios for better window resize behavior.

## v0.1.21 - 2026-05-28

Playback and proposed-frame interaction fixes.

- Fixed scrub slider behavior while playback is active.
- Improved centered control layout.
- Added clearer proposed-state visual feedback.

## v0.1.20 - 2026-05-28

Action row polish.

- Centered equal-width action buttons.
- Expanded export labels for clarity.

## v0.1.19 - 2026-05-28

Visual design pass.

- Added mockup-inspired video player frame.
- Added filmstrip well styling.
- Revised action row presentation.
- Added ReelSheet header icon direction.

## v0.1.18 - 2026-05-28

Shortcut startup fix.

- Fixed shortcut binding startup crash.
- Moved shortcut binding to the root window because CustomTkinter widgets blocked the previous binding path.

## v0.1.17 - 2026-05-28

Usability and visual polish pass.

- Added graphite visual styling.
- Added larger labeled transport controls.
- Added previous/next video controls.
- Added keyboard shortcuts.

## v0.1.16 - 2026-05-28

Thumbnail pane sizing fix.

- Adjusted thumbnail canvases so the inner sash can shrink the left preview column.

## v0.1.15 - 2026-05-28

Inner sash behavior fix.

- Updated the inner sash guide so it tracks the actual thumbnail/video split.

## v0.1.14 - 2026-05-28

Sash drag behavior refinement.

- Added rubber-band sash drag behavior.
- Deferred pane resizing until release to avoid paint trails.

## v0.1.13 - 2026-05-28

Custom sash handle implementation.

- Replaced Tk PanedWindow splitters with custom grid-based sash handles.

## v0.1.12 - 2026-05-28

Smoother pane resizing.

- Added non-opaque pane resize behavior.
- Deferred redraws during sash movement for smoother interaction.

## v0.1.11 - 2026-05-28

Launcher compatibility hardening.

- Hardened FFmpeg path resolution for launches that do not inherit a normal console environment.

## v0.1.10 - 2026-05-28

Canvas redraw and diagnostics polish.

- Added canvas resize redraw for current/proposed thumbnail previews.
- Improved Diagnostics player meter presentation.
- Updated launcher behavior during this development phase.

## v0.1.9 - 2026-05-28

Three-pane layout restoration.

- Restored the draggable sash layout from earlier layout work.
- Reintroduced separate file list, preview thumbnail, and main video areas.

## v0.1.8 - 2026-05-28

Primary audio stack change.

- Added `python-vlc` as the primary audio path for direct MP4 audio.
- Kept pygame extraction audio as fallback.
- Added header audio indicator.
- Added mutable speaker icon.
- Updated Diagnostics for VLC monitoring.

## v0.1.7 - 2026-05-28

Diagnostics tooling.

- Added a separate Diagnostics window.
- Added audio/player state display.
- Added timestamped audio event logging.

## v0.1.6 - 2026-05-28

Audio and layout iteration.

- Continued audio playback experiments.
- Continued layout refinement.

## v0.1.5 - 2026-05-28

Sash divider iteration.

- Added or refined draggable sash divider behavior during layout exploration.

## v0.1.4 - 2026-05-28

Layout iteration.

- Continued UI structure and panel layout refinement.

## v0.1.3 - 2026-05-28

Early layout refinement.

- Began post-playback UI layout iterations.

## v0.1.2 - 2026-05-28

Playback fix and first audio path.

- Fixed playback approach using sequential `cap.read()` plus `cap.grab()` frame skipping.
- Added pygame-ce audio path with OGG extraction on load.

## v0.1.1 - 2026-05-28

Playback experiment.

- Attempted wall-clock playback.
- Identified that seeking every tick was too slow for smooth playback.

## v0.1.0 - 2026-05-28

Initial app snapshot.

- Added working Thumbnail Picker tab.
- Added video folder browsing.
- Added frame preview and thumbnail selection workflow.
- Added Contact Sheet placeholder for future `v0.2.0`.
