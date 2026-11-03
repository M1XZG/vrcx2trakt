# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.2] - 2026-11-03

### Changed

- CLI and GUI errors now create timestamped diagnostic logs and show the saved path.
- Saving changed Trakt credentials now removes the stale token so the next login starts cleanly.

## [1.1.1] - 2026-11-03

### Changed

- Code-changing merges to `main` now publish the next patch release automatically.
- Package and runtime versions now come from the release tag so every downloadable format reports the same version.

## [1.1.0] - 2026-11-03

### Added

- Illumination Media Player watch extraction from VRChat log files, including automatic path detection and manual path overrides.
- CodeQL scanning and a security policy.

### Fixed

- TV show matching when Trakt and source titles differ only in punctuation.
- Ambiguous episode matches by checking the exact show title, year, and episode title.

## [1.0.0] - 2026-06-30

### Added

- Initial public release for syncing VRCX VRChat cinema watches to Trakt watched history.
- Multi-format distribution: Python package or source install, standalone Windows CLI or wizard EXE, and standalone Windows GUI EXE.
- Command-line workflow covering `setup`, `login`, `whoami`, `extract`, `match`, `push`, `sync`, `wizard`, `gui`, and `paths`.
- Guided wizard and GUI paths for users who do not want to run each pipeline step manually.
- Auto-detection for the VRCX SQLite database on Windows and WSL, with environment variable overrides.
- Parsing for Popcorn Palace, Movie&Chill, and LSMedia, including movie, episode, and unknown classification.
- Review-first CSV workflow before anything is pushed to Trakt.
- Idempotent sync using local pushed state and optional remote Trakt history checks.
- Scheduler-friendly `sync` command and wrapper scripts for Bash and PowerShell.
