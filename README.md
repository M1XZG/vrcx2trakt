# vrcx2trakt

[![Licence: MIT](https://img.shields.io/badge/Licence-MIT-blue.svg)](LICENSE)

Sync movies and episodes watched in VRChat cinema worlds to your Trakt.tv watched history.

`vrcx2trakt` reads the SQLite database kept by the VRCX desktop app, finds watches from VRChat cinema worlds, helps you review the matches, then pushes approved items to Trakt. It is designed for both Python users and Windows users who just want a downloadable app.

## Why

If you watch films, TV, or anime in VRChat cinema worlds such as Popcorn Palace, those plays can be trapped in VRCX logs. This tool organises them into a Trakt-friendly workflow so your watched history stays useful without manual re-entry.

## Choose your install

| Format | Best for | How to run |
| --- | --- | --- |
| Windows EXE, no Python needed | Most Windows users | Download `vrcx2trakt-gui.exe` for point-and-click use, or `vrcx2trakt.exe` for the guided console wizard, from the [GitHub Releases page](https://github.com/M1XZG/vrcx2trakt/releases). Double-click to run. |
| Python package | Python users | `pip install .`, then run `vrcx2trakt`, `vrcx2trakt-gui`, or `python -m vrcx2trakt`. |
| From source | Contributors and testers | Clone the repo, run `pip install -r requirements.txt`, then `PYTHONPATH=src python -m vrcx2trakt`. |

Running `vrcx2trakt` with no arguments launches the guided wizard.

## One-time Trakt setup

1. Create a Trakt API app at <https://trakt.tv/oauth/applications/new>.
2. Use this redirect uri:

   ```text
   urn:ietf:wg:oauth:2.0:oob
   ```

3. Save the app credentials locally:

   ```bash
   vrcx2trakt setup
   ```

4. Authorise this device with Trakt:

   ```bash
   vrcx2trakt login
   ```

You can confirm the login with:

```bash
vrcx2trakt whoami
```

## Usage

### Easy paths

For the guided console flow:

```bash
vrcx2trakt wizard
```

For the no-console path:

```bash
vrcx2trakt gui
```

On Windows, double-click `vrcx2trakt.exe` for the wizard or `vrcx2trakt-gui.exe` for the GUI.

### Manual pipeline

```bash
# 1. Extract candidates from VRCX
vrcx2trakt extract

# Optional: point at a database manually, or read without copying
vrcx2trakt extract --db "C:\Users\you\AppData\Roaming\VRCX\VRCX.sqlite3"
vrcx2trakt extract --db ./VRCX.sqlite3 --no-copy

# 2. Match candidates against Trakt
vrcx2trakt match --live

# 3. Review the CSV
# Open review.csv, set include=1 to push or include=0 to skip.
# Fix any wrong trakt_id, trakt_type, or title before continuing.

# 4. Preview, then push
vrcx2trakt push --dry-run --check-remote
vrcx2trakt push --check-remote
```

The review CSV is the safety step. The `include` column controls what is pushed, `1` means push and `0` means skip. If a match is wrong, correct the `trakt_id` before pushing, or set `include` to `0`.

Available commands:

```text
setup, login, whoami, extract, match, push, sync, wizard, gui, paths
```

## Automated and scheduled sync

`vrcx2trakt sync` runs the full non-interactive pipeline: extract, live match, and push with remote duplicate checks. It is safe to run repeatedly because local state and optional Trakt history checks make the sync idempotent. Run `vrcx2trakt setup` and `vrcx2trakt login` once before scheduling.

Wrapper scripts are included:

- `scripts/auto_sync.sh` for Linux, WSL, and macOS.
- `scripts/auto_sync.ps1` for Windows PowerShell.

Example cron entry:

```cron
0 3 * * 0 cd /path/to/vrcx2trakt && scripts/auto_sync.sh
```

Example systemd user service command:

```ini
ExecStart=/path/to/vrcx2trakt/scripts/auto_sync.sh
```

Example Windows Task Scheduler action:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\path\to\vrcx2trakt\scripts\auto_sync.ps1"
```

## Where files live

Secrets and long-lived configuration:

- Windows: `%APPDATA%\vrcx2trakt`
- Linux and macOS: `~/.config/vrcx2trakt`

Working state, logs, the database copy, `candidates.json`, `review.csv`, and `pushed-state.json`:

- Windows: `%LOCALAPPDATA%\vrcx2trakt`
- Linux and macOS: `~/.local/state/vrcx2trakt`

Files in the config directory:

- `credentials.json`, your Trakt app `client_id` and `client_secret`.
- `token.json`, your Trakt device-flow access and refresh tokens.

Override paths with environment variables:

- `VRCX2TRAKT_CONFIG_DIR`
- `VRCX2TRAKT_STATE_DIR`
- `VRCX_DB`

VRCX database auto-detection checks the Windows VRCX path, `%APPDATA%\VRCX\VRCX.sqlite3`, and WSL paths such as `/mnt/c/Users/*/AppData/Roaming/VRCX/VRCX.sqlite3`.

Print the resolved paths with:

```bash
vrcx2trakt paths
```

## How it works

1. Extract reads VRCX `gamelog_video_play` rows for supported VRChat cinema worlds such as Popcorn Palace.
2. Parsing classifies each entry as a movie, episode, or unknown using source-specific patterns and episode heuristics.
3. Duplicate plays for the same source, title, year, and watch date are collapsed into one candidate with a play count.
4. Match writes a review-first CSV, optionally resolving items against Trakt with `--live`.
5. Push sends approved rows to Trakt and records local pushed state. With `--check-remote`, it also skips items already in Trakt history.

## Caveats

- Classification is heuristic, especially for YouTube-style titles, trailers, music, and unusual anime episode names.
- Always review the CSV before pushing.
- VRCX must have logged the play. If the desktop app did not record it, `vrcx2trakt` cannot recover it.
- Trakt matching is only as good as the parsed title, year, and episode data.

## Building the Windows EXEs yourself

The Windows builds are produced on a Windows runner and attached to GitHub Releases when a release tag is published. To build locally, use `packaging/build-windows.ps1` from a Windows PowerShell session with the project dependencies installed.

## Contributing

Issues and pull requests are welcome at <https://github.com/M1XZG/vrcx2trakt>. Please keep changes focused, include tests for parsing or path behaviour where possible, and avoid committing credentials, tokens, database copies, or generated logs.

## Credits and acknowledgements

`vrcx2trakt` grew from a personal VRCX to Trakt script. Thanks to Trakt.tv for the API and to VRCX for making local VRChat history available.

## Licence

MIT. See [LICENSE](LICENSE).
