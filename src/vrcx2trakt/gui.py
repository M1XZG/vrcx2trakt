"""Tkinter desktop interface for vrcx2trakt."""
from __future__ import annotations

import csv
import os
import queue
import threading
import webbrowser

from . import config, extract, match, push
from .trakt_client import TraktAuthError, TraktClient, TraktError


def _clean_message(value: object) -> str:
    """Make upstream exception text fit the GUI tone."""
    text = str(value)
    replacements = {
        "\u2014": "-",
        "authorization": "authorisation",
        "Authorization": "Authorisation",
        "authorize": "authorise",
        "Authorize": "Authorise",
        "authorized": "authorised",
        "Authorized": "Authorised",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def main() -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext, ttk
    except Exception as exc:  # pragma: no cover, depends on host Python build
        print(f"tkinter is unavailable, cannot start the vrcx2trakt desktop app: {exc}")
        return 1

    class Vrcx2TraktApp:
        REVIEW_COLUMNS = (
            "include",
            "watched_date",
            "media_type",
            "parsed_title",
            "trakt_title",
            "trakt_id",
            "notes",
        )

        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            self.ui_queue: queue.Queue[tuple] = queue.Queue()
            self.review_rows: list[dict[str, str]] = []
            self.review_fieldnames: list[str] = []
            self.tree_iid_to_index: dict[str, int] = {}
            self.login_window: tk.Toplevel | None = None

            self.root.title("vrcx2trakt")
            self.root.geometry("980x780")
            self.root.minsize(860, 650)

            self.status_var = tk.StringVar()
            self.db_var = tk.StringVar(value=self._detected_db_text())
            self.progress_text_var = tk.StringVar(value="Ready to resolve matches.")

            self._build_ui()
            self.refresh_status()
            self._load_review_if_exists()
            self.root.after(100, self._process_queue)

        def _build_ui(self) -> None:
            outer = ttk.Frame(self.root, padding=12)
            outer.pack(fill="both", expand=True)

            status_row = ttk.Frame(outer)
            status_row.pack(fill="x", pady=(0, 8))
            ttk.Label(status_row, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
            ttk.Button(status_row, text="Refresh status", command=self.refresh_status).pack(side="right")

            step1 = ttk.LabelFrame(outer, text="Step 1, Trakt account", padding=10)
            step1.pack(fill="x", pady=4)
            ttk.Label(
                step1,
                text="Add your Trakt app credentials, then authorise this app with your Trakt account.",
            ).pack(anchor="w", pady=(0, 6))
            step1_buttons = ttk.Frame(step1)
            step1_buttons.pack(fill="x")
            ttk.Button(
                step1_buttons,
                text="Set Trakt credentials...",
                command=self.open_credentials_dialog,
            ).pack(side="left")
            self.login_button = ttk.Button(
                step1_buttons,
                text="Log in to Trakt",
                command=self.start_trakt_login,
            )
            self.login_button.pack(side="left", padx=(8, 0))

            step2 = ttk.LabelFrame(outer, text="Step 2, VRChat data (VRCX)", padding=10)
            step2.pack(fill="x", pady=4)
            ttk.Label(step2, text="Choose your VRCX SQLite database, or leave blank to auto-detect it.").pack(
                anchor="w", pady=(0, 6)
            )
            db_row = ttk.Frame(step2)
            db_row.pack(fill="x")
            ttk.Entry(db_row, textvariable=self.db_var).pack(side="left", fill="x", expand=True)
            ttk.Button(db_row, text="Browse...", command=self.browse_vrcx_db).pack(side="left", padx=(8, 0))
            self.extract_button = ttk.Button(step2, text="Extract watches", command=self.start_extract)
            self.extract_button.pack(anchor="w", pady=(8, 0))

            step3 = ttk.LabelFrame(outer, text="Step 3, Match against Trakt", padding=10)
            step3.pack(fill="x", pady=4)
            match_row = ttk.Frame(step3)
            match_row.pack(fill="x")
            self.match_button = ttk.Button(match_row, text="Resolve matches", command=self.start_match)
            self.match_button.pack(side="left")
            self.match_progress = ttk.Progressbar(match_row, orient="horizontal", mode="determinate", maximum=1)
            self.match_progress.pack(side="left", fill="x", expand=True, padx=(8, 0))
            ttk.Label(step3, textvariable=self.progress_text_var).pack(anchor="w", pady=(6, 0))

            step4 = ttk.LabelFrame(outer, text="Step 4, Review", padding=10)
            step4.pack(fill="both", expand=True, pady=4)
            review_buttons = ttk.Frame(step4)
            review_buttons.pack(fill="x", pady=(0, 6))
            self.toggle_button = ttk.Button(review_buttons, text="Toggle include", command=self.toggle_selected_review)
            self.toggle_button.pack(side="left")
            self.save_review_button = ttk.Button(review_buttons, text="Save review", command=self.save_review)
            self.save_review_button.pack(side="left", padx=(8, 0))
            ttk.Button(
                review_buttons,
                text="Open review CSV in default editor",
                command=self.open_review_csv,
            ).pack(side="left", padx=(8, 0))

            tree_frame = ttk.Frame(step4)
            tree_frame.pack(fill="both", expand=True)
            self.review_tree = ttk.Treeview(
                tree_frame,
                columns=self.REVIEW_COLUMNS,
                show="headings",
                selectmode="browse",
                height=8,
            )
            headings = {
                "include": "Include",
                "watched_date": "Watched date",
                "media_type": "Type",
                "parsed_title": "Parsed title",
                "trakt_title": "Trakt title",
                "trakt_id": "Trakt ID",
                "notes": "Notes",
            }
            widths = {
                "include": 70,
                "watched_date": 95,
                "media_type": 80,
                "parsed_title": 190,
                "trakt_title": 230,
                "trakt_id": 80,
                "notes": 260,
            }
            for column in self.REVIEW_COLUMNS:
                self.review_tree.heading(column, text=headings[column])
                self.review_tree.column(column, width=widths[column], minwidth=50, stretch=column in {"parsed_title", "trakt_title", "notes"})
            tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.review_tree.yview)
            self.review_tree.configure(yscrollcommand=tree_scroll.set)
            self.review_tree.pack(side="left", fill="both", expand=True)
            tree_scroll.pack(side="right", fill="y")
            self.review_tree.bind("<Double-1>", self.toggle_selected_review)

            step5 = ttk.LabelFrame(outer, text="Step 5, Push to Trakt", padding=10)
            step5.pack(fill="x", pady=4)
            self.preview_button = ttk.Button(step5, text="Preview (dry run)", command=self.start_preview)
            self.preview_button.pack(side="left")
            self.push_button = ttk.Button(step5, text="Push to Trakt", command=self.confirm_and_push)
            self.push_button.pack(side="left", padx=(8, 0))

            log_frame = ttk.LabelFrame(outer, text="Log", padding=10)
            log_frame.pack(fill="both", expand=False, pady=(4, 0))
            self.log_text = scrolledtext.ScrolledText(log_frame, height=10, wrap="word", state="disabled")
            self.log_text.pack(fill="both", expand=True)
            self._append_log("Welcome. Work from Step 1 to Step 5, and review carefully before pushing to Trakt.")

        def _detected_db_text(self) -> str:
            try:
                detected = config.detect_vrcx_db()
            except Exception:
                return ""
            return str(detected) if detected else ""

        def refresh_status(self) -> None:
            credentials = "found" if TraktClient.credentials_exist() else "missing"
            token = "found" if TraktClient.token_exists() else "missing"
            self.status_var.set(f"Status: Trakt credentials {credentials}, Trakt login token {token}")

        def post_log(self, message: str) -> None:
            self.ui_queue.put(("log", message))

        def _append_log(self, message: str) -> None:
            text = _clean_message(message)
            self.log_text.configure(state="normal")
            self.log_text.insert("end", text.rstrip() + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        def _process_queue(self) -> None:
            try:
                while True:
                    item = self.ui_queue.get_nowait()
                    self._handle_queue_item(item)
            except queue.Empty:
                pass
            if self.root.winfo_exists():
                self.root.after(100, self._process_queue)

        def _handle_queue_item(self, item: tuple) -> None:
            kind = item[0]
            if kind == "log":
                self._append_log(item[1])
                return
            if kind == "worker_success":
                _, title, result, button, on_success = item
                if button is not None:
                    button.configure(state="normal")
                self.refresh_status()
                if on_success is not None:
                    on_success(result)
                self._append_log(f"{title} complete.")
                return
            if kind == "worker_error":
                _, title, exc, button = item
                if button is not None:
                    button.configure(state="normal")
                self.refresh_status()
                message = _clean_message(exc)
                self._append_log(f"{title} failed: {message}")
                messagebox.showerror(title, message)
                return
            if kind == "match_progress":
                _, done, total, label = item
                self.match_progress.configure(maximum=max(total, 1), value=done)
                self.progress_text_var.set(f"Resolving {done} of {total}: {label}")
                return
            if kind == "login_code":
                self._show_login_code(item[1])
                return
            if kind == "credentials_saved":
                _, dialog, save_button, path = item
                if dialog.winfo_exists():
                    save_button.configure(state="normal")
                    dialog.destroy()
                self.refresh_status()
                self._append_log(f"Trakt credentials saved to {path}")
                messagebox.showinfo("Trakt credentials saved", "Credentials saved. You can now log in to Trakt.")
                return
            if kind == "dialog_error":
                _, title, dialog, save_button, exc = item
                if dialog.winfo_exists():
                    save_button.configure(state="normal")
                message = _clean_message(exc)
                self._append_log(f"{title} failed: {message}")
                messagebox.showerror(title, message)

        def _start_worker(self, title: str, button: ttk.Button | None, work, on_success=None) -> None:
            if button is not None:
                button.configure(state="disabled")
            self._append_log(f"{title} started.")

            def runner() -> None:
                try:
                    result = work()
                except (TraktError, TraktAuthError, FileNotFoundError, Exception) as exc:  # noqa: BLE001
                    self.ui_queue.put(("worker_error", title, exc, button))
                else:
                    self.ui_queue.put(("worker_success", title, result, button, on_success))

            threading.Thread(target=runner, daemon=True).start()

        def open_credentials_dialog(self) -> None:
            dialog = tk.Toplevel(self.root)
            dialog.title("Set Trakt credentials")
            dialog.transient(self.root)
            dialog.grab_set()
            dialog.resizable(False, False)

            frame = ttk.Frame(dialog, padding=12)
            frame.pack(fill="both", expand=True)
            ttk.Label(
                frame,
                text=(
                    "Create a Trakt application, then paste its client ID and client secret here. "
                    "Use this redirect URI: urn:ietf:wg:oauth:2.0:oob"
                ),
                wraplength=460,
            ).pack(anchor="w")
            ttk.Button(
                frame,
                text="Open Trakt apps page",
                command=lambda: webbrowser.open("https://trakt.tv/oauth/applications/new"),
            ).pack(anchor="w", pady=(8, 10))

            client_id_var = tk.StringVar()
            client_secret_var = tk.StringVar()
            ttk.Label(frame, text="Client ID").pack(anchor="w")
            client_id_entry = ttk.Entry(frame, textvariable=client_id_var, width=58)
            client_id_entry.pack(fill="x", pady=(0, 6))
            ttk.Label(frame, text="Client secret").pack(anchor="w")
            ttk.Entry(frame, textvariable=client_secret_var, width=58, show="*").pack(fill="x", pady=(0, 10))

            buttons = ttk.Frame(frame)
            buttons.pack(fill="x")
            save_button = ttk.Button(buttons, text="Save")
            save_button.pack(side="right")
            ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right", padx=(0, 8))

            def save() -> None:
                client_id = client_id_var.get().strip()
                client_secret = client_secret_var.get().strip()
                if not client_id or not client_secret:
                    messagebox.showerror("Missing credentials", "Enter both the client ID and client secret.")
                    return
                save_button.configure(state="disabled")

                def runner() -> None:
                    try:
                        path = TraktClient.save_credentials(client_id, client_secret)
                    except Exception as exc:  # noqa: BLE001
                        self.ui_queue.put(("dialog_error", "Saving Trakt credentials", dialog, save_button, exc))
                    else:
                        self.ui_queue.put(("credentials_saved", dialog, save_button, str(path)))

                threading.Thread(target=runner, daemon=True).start()

            save_button.configure(command=save)
            client_id_entry.focus_set()
            dialog.wait_visibility()
            dialog.grab_set()

        def start_trakt_login(self) -> None:
            def work() -> dict:
                client = TraktClient()
                code_data = client.start_device_code()
                self.ui_queue.put(("login_code", code_data))
                user_code = code_data.get("user_code", "")
                device_code = code_data["device_code"]
                interval = max(1, _as_int(code_data.get("interval"), 5))
                expires_in = max(interval, _as_int(code_data.get("expires_in"), 600))
                attempts = max(1, (expires_in + interval - 1) // interval)
                sleeper = threading.Event()
                self.ui_queue.put(("log", f"Waiting for Trakt authorisation using code {user_code}."))
                for attempt in range(attempts):
                    sleeper.wait(interval)
                    token = client.poll_device_token(device_code)
                    if token:
                        user = client.whoami()
                        return {"token": token, "user": user}
                    self.ui_queue.put(("log", f"Still waiting for Trakt authorisation ({attempt + 1} of {attempts})."))
                raise TraktAuthError("Trakt device code expired. Start login again.")

            self._start_worker("Trakt login", self.login_button, work, self._on_login_success)

        def _show_login_code(self, code_data: dict) -> None:
            if self.login_window is not None and self.login_window.winfo_exists():
                self.login_window.destroy()
            user_code = str(code_data.get("user_code", ""))
            url = str(code_data.get("verification_url") or "https://trakt.tv/activate")
            window = tk.Toplevel(self.root)
            self.login_window = window
            window.title("Authorise Trakt")
            window.transient(self.root)
            window.resizable(False, False)
            frame = ttk.Frame(window, padding=14)
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text="Open the Trakt activation page and enter this code:").pack(anchor="w")
            ttk.Label(frame, text=user_code, font=("TkDefaultFont", 22, "bold")).pack(anchor="w", pady=(8, 4))
            ttk.Label(frame, text=url, wraplength=420).pack(anchor="w", pady=(0, 10))
            buttons = ttk.Frame(frame)
            buttons.pack(fill="x")
            ttk.Button(buttons, text="Open activation page", command=lambda: webbrowser.open(url)).pack(side="left")
            ttk.Button(buttons, text="Copy code", command=lambda: self._copy_to_clipboard(user_code)).pack(
                side="left", padx=(8, 0)
            )
            ttk.Button(buttons, text="Close", command=window.destroy).pack(side="right")
            self._append_log(f"Trakt code ready: {user_code}. Open {url} to authorise.")

        def _copy_to_clipboard(self, text: str) -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._append_log("Code copied to the clipboard.")

        def _on_login_success(self, result: dict) -> None:
            if self.login_window is not None and self.login_window.winfo_exists():
                self.login_window.destroy()
            user = result.get("user") or {}
            username = user.get("username") or user.get("name") or "your Trakt account"
            self._append_log(f"Trakt login complete for {username}.")
            messagebox.showinfo("Trakt login complete", f"Logged in to Trakt as {username}.")

        def browse_vrcx_db(self) -> None:
            filename = filedialog.askopenfilename(
                title="Choose VRCX database",
                filetypes=(
                    ("SQLite databases", "*.sqlite3 *.sqlite *.db"),
                    ("All files", "*.*"),
                ),
            )
            if filename:
                self.db_var.set(filename)

        def start_extract(self) -> None:
            db_path = self.db_var.get().strip() or None

            def work() -> dict:
                return extract.run_extract(db=db_path)

            self._start_worker("Extract watches", self.extract_button, work, self._on_extract_success)

        def _on_extract_success(self, result: dict) -> None:
            count = len(result.get("candidates") or [])
            summary = result.get("summary") or "Extraction complete."
            self._append_log(summary)
            messagebox.showinfo("Extraction complete", f"Extracted {count} watch candidates.")

        def start_match(self) -> None:
            self.match_progress.configure(maximum=1, value=0)
            self.progress_text_var.set("Starting live Trakt matching...")

            def progress(done: int, total: int, label: str) -> None:
                self.ui_queue.put(("match_progress", done, total, label))

            def work() -> dict:
                result = match.run_match(live=True, progress=progress)
                fieldnames, rows = self._read_review_csv(config.review_path())
                result["review_fieldnames"] = fieldnames
                result["review_rows"] = rows
                return result

            self._start_worker("Resolve matches", self.match_button, work, self._on_match_success)

        def _on_match_success(self, result: dict) -> None:
            stats = result.get("stats") or {}
            rows = result.get("review_rows") or result.get("rows") or []
            self.progress_text_var.set(
                "Resolved {resolved}, unresolved {unresolved}, from cache {from_cache}, included {included}.".format(
                    resolved=stats.get("resolved", 0),
                    unresolved=stats.get("unresolved", 0),
                    from_cache=stats.get("from_cache", 0),
                    included=stats.get("included", 0),
                )
            )
            self.review_fieldnames = list(result.get("review_fieldnames") or getattr(match, "CSV_HEADER", []))
            self.review_rows = [{key: str(row.get(key, "")) for key in self.review_fieldnames} for row in rows]
            self._populate_review_tree()
            self._append_log(f"Loaded {len(self.review_rows)} review rows from {config.review_path()}.")
            messagebox.showinfo("Matching complete", f"Matched {len(self.review_rows)} rows. Review the include column before pushing.")

        def _read_review_csv(self, path) -> tuple[list[str], list[dict[str, str]]]:  # noqa: ANN001
            with path.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                fieldnames = list(reader.fieldnames or [])
                rows = [
                    {key: (row.get(key, "") if row.get(key, "") is not None else "") for key in fieldnames}
                    for row in reader
                ]
            return fieldnames, rows

        def _load_review_if_exists(self) -> None:
            path = config.review_path()
            if not path.exists():
                return
            try:
                self.review_fieldnames, self.review_rows = self._read_review_csv(path)
            except Exception as exc:  # noqa: BLE001
                self._append_log(f"Could not load existing review CSV: {_clean_message(exc)}")
                return
            self._populate_review_tree()
            self._append_log(f"Loaded existing review CSV: {path}")

        def _populate_review_tree(self) -> None:
            self.review_tree.delete(*self.review_tree.get_children())
            self.tree_iid_to_index.clear()
            for index, row in enumerate(self.review_rows):
                iid = str(index)
                values = [self._review_value(row, column) for column in self.REVIEW_COLUMNS]
                self.review_tree.insert("", "end", iid=iid, values=values)
                self.tree_iid_to_index[iid] = index

        def _review_value(self, row: dict[str, str], column: str) -> str:
            if column == "include":
                return "☑" if self._included(row.get("include", "")) else "☐"
            return str(row.get(column, ""))

        def _included(self, value: str) -> bool:
            return str(value).strip().lower() in {"1", "true", "yes", "y", "x"}

        def toggle_selected_review(self, event=None) -> None:  # noqa: ANN001
            selected = self.review_tree.selection()
            if not selected:
                focus = self.review_tree.focus()
                selected = (focus,) if focus else ()
            if not selected:
                messagebox.showinfo("No row selected", "Select a review row to toggle.")
                return
            iid = selected[0]
            index = self.tree_iid_to_index.get(iid)
            if index is None:
                return
            row = self.review_rows[index]
            row["include"] = "0" if self._included(row.get("include", "")) else "1"
            self.review_tree.set(iid, "include", self._review_value(row, "include"))
            self._append_log(f"Set include={row['include']} for {row.get('parsed_title', 'selected row')}.")

        def save_review(self) -> None:
            if not self.review_rows or not self.review_fieldnames:
                messagebox.showinfo("No review loaded", "Resolve matches first, then save the review.")
                return
            rows = [{key: row.get(key, "") for key in self.review_fieldnames} for row in self.review_rows]
            fieldnames = list(self.review_fieldnames)

            def work() -> dict:
                path = config.review_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                return {"path": str(path), "rows": len(rows)}

            self._start_worker("Save review", self.save_review_button, work, self._on_save_review_success)

        def _on_save_review_success(self, result: dict) -> None:
            self._append_log(f"Saved {result['rows']} review rows to {result['path']}.")
            messagebox.showinfo("Review saved", f"Saved {result['rows']} rows.")

        def open_review_csv(self) -> None:
            path = config.review_path()
            if path.exists():
                self._append_log(f"Opening review CSV: {path}")
                if config.is_windows() and hasattr(os, "startfile"):
                    os.startfile(str(path))  # type: ignore[attr-defined]
                else:
                    webbrowser.open(path.parent.as_uri())
                return
            folder = config.ensure_state_dir()
            self._append_log(f"Review CSV not found, opening state folder: {folder}")
            messagebox.showinfo("Review CSV not found", "Resolve matches first. Opening the state folder instead.")
            webbrowser.open(folder.as_uri())

        def start_preview(self) -> None:
            def work() -> dict:
                return push.run_push(dry_run=True, check_remote=True)

            self._start_worker("Preview dry run", self.preview_button, work, self._on_preview_success)

        def _on_preview_success(self, result: dict) -> None:
            text = self._format_push_result(result, preview=True)
            self._append_log(text)
            messagebox.showinfo("Dry run complete", self._push_summary_line(result))

        def confirm_and_push(self) -> None:
            if not messagebox.askyesno(
                "Push to Trakt",
                "This will add all included review rows that are not already on Trakt. Continue?",
            ):
                return

            def work() -> dict:
                return push.run_push(check_remote=True)

            self._start_worker("Push to Trakt", self.push_button, work, self._on_push_success)

        def _on_push_success(self, result: dict) -> None:
            text = self._format_push_result(result, preview=False)
            self._append_log(text)
            title = "Push complete" if result.get("pushed") else "Nothing new to push"
            messagebox.showinfo(title, self._push_summary_line(result))

        def _push_summary_line(self, result: dict) -> str:
            return (
                f"To push: {result.get('to_push_movies', 0)} films, "
                f"{result.get('to_push_episodes', 0)} episodes. "
                f"Skipped: {result.get('skipped_local_dupes', 0)} local duplicates, "
                f"{result.get('skipped_remote_dupes', 0)} already on Trakt."
            )

        def _format_push_result(self, result: dict, *, preview: bool) -> str:
            lines = [
                "Dry run preview:" if preview else "Push result:",
                f"Review rows: {result.get('review_rows', 0)}",
                f"Included with Trakt ID: {result.get('included', 0)}",
                f"Included but missing Trakt ID: {result.get('skipped_no_id', 0)}",
                self._push_summary_line(result),
            ]
            if result.get("remote_history_events"):
                lines.append(f"Remote history events checked: {result.get('remote_history_events')}")
            preview_items = result.get("preview") or []
            if preview_items:
                lines.append("Preview items, first 25:")
                for item in preview_items[:25]:
                    lines.append(
                        "  {type:<7} {date}  trakt:{tid:<8} {title}".format(
                            type=str(item.get("trakt_type", "")),
                            date=str(item.get("watched_date", "")),
                            tid=str(item.get("trakt_id", "")),
                            title=str(item.get("trakt_title", "")),
                        )
                    )
            elif preview:
                lines.append("No new items are ready to push.")
            if not preview:
                if result.get("pushed"):
                    lines.append(f"Trakt response: {result.get('response')}")
                    if result.get("log_path"):
                        lines.append(f"Push log: {result.get('log_path')}")
                else:
                    lines.append("Nothing new was pushed.")
            return "\n".join(lines)

    try:
        root = tk.Tk()
    except Exception as exc:  # pragma: no cover, depends on display availability
        print(f"Could not start the vrcx2trakt desktop app: {exc}")
        return 1

    Vrcx2TraktApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
