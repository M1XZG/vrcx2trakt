# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
