# ReelSheet TODO

This file tracks planned work and product questions. Items here are not promises for the next version; they are the working backlog.

## Product Positioning

ReelSheet helps Windows users visually organize large local video libraries with custom video thumbnails, folder thumbnails, and contact sheets in one workflow.

Use this as the product direction filter:

- If a feature helps users visually organize local video libraries, it probably belongs.
- If a feature is mostly for online publishing, social media thumbnails, or general image editing, it probably does not belong unless it supports the core workflow.
- The product value is workflow polish, not inventing brand-new thumbnail technology.

## Near-Term App Polish

- [ ] Decide whether the filename is still needed in the lower area.
  - Current note: "Do I need the filename down below."
  - Product question: if the selected filename is clearly visible near the directory path or in the title/status area, duplicate filename text below the player may be unnecessary.

- [ ] Add an in-app TODO or task list view.
  - Current note: "Get a list of to do's."
  - Product question: decide whether this belongs inside the app, in project docs only, or as a developer-only diagnostics/help panel.

- [ ] Explore undockable panels/tools like Adobe Creative Cloud apps.
  - Current idea: allow areas/tools to undock into separate windows to reduce clutter.
  - Product question: which areas should be dockable first: diagnostics, current/proposed thumbnails, filmstrip, file list, details, or contact sheet tools?
  - Product question: should undocked panels remember their size and position?
  - Product question: should users be able to redock panels with one click?
  - Product question: should this be a professional power-user feature after core workflows are stable, rather than near-term polish?
  - Technical caution: undocking changes layout architecture and should be designed separately from small UI fixes.

## Updates And Release Notes

- [ ] Add a GitHub update check.
  - Current note: "Have it check github for an update."
  - Professional approach: check the latest GitHub Release, compare it to the app version, and show a non-intrusive update message.
  - Decision needed: manual "Check for Updates" button first, automatic startup checks later.

- [ ] Start adding update notes inside the app.
  - Current note: "start adding update notes."
  - Professional approach: use `CHANGELOG.md` as the source of truth, then show recent release notes in an About/Updates window.

## Thumbnail Workflow

- [ ] End-to-end test thumbnail embedding.
  - Confirm `Set This Frame as Thumbnail` writes the selected frame into the MP4.
  - Confirm Windows Explorer refreshes and shows the updated thumbnail.
  - Confirm stored thumbnail position is restored when reopening a video.

- [ ] Test auto-advance after setting a thumbnail.
  - Product question: after setting a thumbnail, should ReelSheet automatically move to the next video?
  - If yes, decide whether auto-advance should be always on or a setting.

- [ ] Discuss folder thumbnail updater.
  - Current idea: Windows can show a custom picture for a folder, similar in purpose to how ReelSheet sets a video thumbnail.
  - Possible feature name: `Set Folder Thumbnail`.
  - Likely Windows mechanism: save a folder image such as `Folder.jpg`, update `desktop.ini`, set folder attributes, and refresh Explorer.
  - Product question: should it use the currently selected video frame?
  - Product question: should it let the user choose a separate still image instead?
  - Product question: should it update the current video's folder, the selected folder in the file list, or any folder chosen by Browse?
  - Product question: should this be a one-click action or a confirmation dialog with preview?
  - Product question: should ReelSheet create a backup of the previous folder thumbnail/customization before changing it?
  - Product question: should there be `Restore Previous Folder Thumbnail`?
  - Product question: should the file be named `Folder.jpg`, `.folder.jpg`, or something ReelSheet-specific?
  - Product question: should generated folder thumbnail files be hidden/system files or visible to users?
  - Product question: how should the app explain that Windows Explorer may cache thumbnails and not update instantly?
  - Professional caution: folder thumbnails are Windows-specific and Explorer behavior can vary by view mode, cache state, and Windows version.

- [ ] Add external thumbnail import from user-provided image URL.
  - Current idea: user provides a direct image URL; ReelSheet downloads that image and makes it available as a thumbnail candidate.
  - Important boundary: no web search and no automated scraping.
  - Product name idea: `Import Thumbnail from URL`.
  - Product question: should imported images appear alongside proposed video frames, in a separate "External Thumbnails" strip, or in a small library?
  - Product question: should ReelSheet save the source URL with the imported image for reference?
  - Product question: should imported images be stored per video, per folder, or in a shared thumbnail library?
  - Product question: should imported images be allowed for video thumbnails, folder thumbnails, contact sheet covers, or all three?
  - Product question: should the app validate image type, image dimensions, and file size before import?
  - Professional caution: the user is responsible for rights to images they provide; ReelSheet should avoid presenting this as permission to use copyrighted images commercially.
  - Security caution: only download image content, reject unexpected file types, and avoid executing or opening downloaded files directly.

## Audio And Runtime Dependencies

- [ ] Bundle VLC runtime with the app.
  - Earlier plan: copy `libvlc.dll`, `libvlccore.dll`, and the VLC `plugins` folder into `C:\ReelSheet\vlc_runtime\`.
  - Goal: make audio work without requiring users to install VLC separately.
  - Professional caution: confirm VLC redistribution/licensing requirements before shipping a paid product with bundled VLC files.

- [ ] Confirm audio behavior in the current active version.
  - Logs show `VLC_OK=True`, but user-facing testing should still confirm play/pause/seek audio sync with real files.
  - Do not change audio logic without reading `reelsheet_audio.log` first.

## Licensing And Commercial Planning

- [ ] Explore trial and fully licensed versions.
  - Current note: "maybe create a trial and fully licensed version."
  - Product question: decide what the trial limits are before implementing licensing.
  - Possible trial limits:
    - Limit number of videos processed per session.
    - Add watermark to exported contact sheets.
    - Disable batch operations.
    - Time-limited trial.
  - Professional caution: licensing should be designed carefully and not mixed with core thumbnail/playback fixes.

## Version And Release Roadmap

- [ ] Define the next `v0.1.x` polish milestone.
  - Purpose: finish the current Thumbnail Picker workflow before expanding too far.
  - Candidate scope: selected filename display, thumbnail backup/restore, folder thumbnail discussion/design, and end-to-end thumbnail verification.
  - Professional rule: patch versions should stay focused on fixes and polish.

- [ ] Define `v0.2.0` as the Contact Sheet milestone.
  - Purpose: first major feature expansion beyond video thumbnail picking.
  - Candidate scope: Contact Sheet tab, grid picker, random fill, gap fill, reorder, timestamp/blur toggles, and export.
  - Professional rule: minor versions are good for new user-facing feature areas.

- [ ] Define a private alpha release checkpoint.
  - Purpose: a version for internal testing only, not public sale.
  - Candidate requirement: thumbnail picker works reliably, basic docs exist, known issues are written down, and GitHub has a clean release artifact.
  - Possible version label: `v0.2.0-alpha` or `v0.2.0-preview`.

- [ ] Define a public beta release checkpoint.
  - Purpose: a version safe enough for outside testers.
  - Candidate requirement: packaged Windows app, no known startup crashes, update notes, screenshots, basic support instructions, and clear limitations.
  - Possible version label: `v0.3.0-beta`.

- [ ] Define first paid/commercial release criteria.
  - Purpose: avoid selling before the product is stable enough to protect trust.
  - Candidate requirement: packaged app, clear license/trial behavior, tested install/run path, thumbnail and contact sheet workflows stable, update checking or update instructions, and known issues documented.
  - Possible version label: `v1.0.0`.

- [ ] Decide what qualifies as a major version.
  - Patch version example: `v0.1.25` for bug fixes, layout polish, small workflow improvements.
  - Minor version example: `v0.2.0` for Contact Sheet, `v0.3.0` for packaging/update system, `v0.4.0` for licensing/trial features.
  - Major version example: `v1.0.0` for first version suitable for paid public release.

## Contact Sheet v0.2.0

- [ ] Build Contact Sheet tab for `v0.2.0`.
  - Port the proven PowerShell contact sheet design into Python.

- [ ] Add contact sheet grid size picker.
  - Planned grid sizes: 4, 6, 9, 12, 16, 20, 25 frames.

- [ ] Add Random Fill.
  - Use evenly spaced video segments.
  - Add about 10 percent jitter.
  - Avoid the first and last 15 seconds where possible.

- [ ] Add click-to-remove frame behavior.
  - Removed frames should create a gap fill slot with the original time range.

- [ ] Add Gap Fill.
  - Fill a removed slot with a random frame from that slot's original time window.

- [ ] Add drag-to-reorder frames.

- [ ] Add timestamp overlay toggle.

- [ ] Add blur toggle.
  - Apply to display preview and export.

- [ ] Add contact sheet export.
  - Export via Pillow compositing.
  - Support JPG and PNG.
  - Filename pattern: `{stem}_{cols}x{rows}_contact_sheet.{ext}`.

## Packaging And Public Release

- [ ] Add multi-format video support.
  - Planned formats: MKV, AVI, WMV, MOV, MPG.
  - Professional approach: confirm OpenCV frame extraction and VLC audio behavior per format.

- [ ] Evaluate macOS version after a Mac test machine is available.
  - Current note: Kevin expects to get a Mac mini later this year.
  - Product question: should macOS be a true supported product or an experimental port?
  - Technical question: replace Windows Explorer thumbnail/folder-thumbnail behavior with macOS Finder-compatible behavior where possible.
  - Packaging question: decide whether to ship outside the Mac App Store with Developer ID signing and notarization.
  - Professional caution: macOS support is not just a rebuild; Finder integration, packaging, signing, notarization, and dependency bundling need separate testing.

- [ ] Build a Windows executable with PyInstaller.
  - Include required Python packages.
  - Eventually include bundled VLC runtime if licensing and technical testing are acceptable.

- [ ] Create a GitHub Release with downloadable artifact.
  - Include release notes.
  - Include known issues.
  - Include a `.zip` or installer artifact.
  - Confirm the downloaded package runs on a clean test machine or clean Windows profile.

- [ ] Add screenshots or short demo media to the GitHub README/release page.
  - Professional purpose: users should immediately understand what the app does before downloading it.

## Already Planned App Polish

- [ ] Back up existing embedded thumbnail before replacing it.
- [ ] Add `Restore Previous Thumbnail`.
- [ ] Add Premiere-style timecode shuttle dragging.
- [ ] Add Dark, Light, and Colorblind theme options.
- [ ] Decide whether `Set All Thumbnails` should remain or be replaced by a staged workflow.

## Completed Or No Longer Primary

- [x] Make the first Git commit and push to GitHub.
- [x] Add README project documentation.
- [x] Add CHANGELOG version history.
- [x] Confirm `v0.1.24` lower control alignment.
- [x] Add selected filename to path bar and compact file details row.
