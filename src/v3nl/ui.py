"""Standard-library Tk/ttk GUI: playsets, mod load order, native plugins and launch settings."""
from __future__ import annotations

from dataclasses import replace
import datetime as dt
import json
import os
from pathlib import Path
import queue
import shlex
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .config import LauncherConfig, local_data
from .launcher import build_plan, launch_game, refresh_session_status
from .mods import Mod, all_mods, playsets, playset_mods, read_metadata
from .plugins import discover_plugins, install_plugin_directory, plugins_dir


BG = "#101521"
PANEL = "#1c2535"
FG = "#e5ecf7"
MUTED = "#93a6bd"
ACCENT = "#76a8f8"


def main_ui(cfg: LauncherConfig) -> None:
    root = tk.Tk()
    LoaderUI(root, cfg)
    root.mainloop()


class LoaderUI:
    def __init__(self, root: tk.Tk, cfg: LauncherConfig) -> None:
        self.root = root
        self.cfg = cfg
        self.events: queue.Queue = queue.Queue()
        self._busy = False
        self.current_launch = None
        self.mods: list[Mod] = []
        self.mod_by_path: dict[str, Mod] = {}
        self.selected_paths: list[str] = list(cfg.enabled_mod_paths)
        self.plugins = []
        self.playset_by_label = {}
        self.root.title(f"Victoria 3 Native Loader {__version__}")
        self.root.geometry("1120x760")
        self.root.minsize(850, 610)
        self.root.configure(bg=BG)
        self._theme()
        self._build()
        self.reload_library()
        self.reload_playsets()
        self.reload_plugins()
        self.root.after(120, self._poll_events)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _theme(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Title.TLabel", background=BG, foreground=FG,
                        font=("Segoe UI Semibold", 18))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("TButton", background=PANEL, foreground=FG, padding=(12, 7))
        style.map("TButton", background=[("active", "#35435a")],
                  foreground=[("disabled", "#6a7c94")])
        style.configure("Accent.TButton", background="#2563bd", foreground="white",
                        font=("Segoe UI Semibold", 10), padding=(14, 9))
        style.map("Accent.TButton", background=[("active", "#3481e2")])
        style.configure("TCheckbutton", background=BG, foreground=FG, padding=3)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("TEntry", fieldbackground=PANEL, foreground=FG, insertcolor=FG)
        style.configure("TCombobox", fieldbackground=PANEL, foreground=FG, padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL)],
                  foreground=[("readonly", FG)])
        style.configure("Treeview", background=PANEL, foreground=FG,
                        fieldbackground=PANEL, rowheight=27, borderwidth=0)
        style.map("Treeview", background=[("selected", "#2a4a7a")],
                  foreground=[("selected", "white")])
        style.configure("Treeview.Heading", background="#243148", foreground=FG,
                        font=("Segoe UI Semibold", 10), relief="flat", padding=(8, 7))
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 10), background=PANEL, foreground=MUTED)
        style.map("TNotebook.Tab", background=[("selected", "#2c3c56")],
                  foreground=[("selected", "white")])

    def _build(self):
        header = ttk.Frame(self.root, padding=(22, 17, 22, 10))
        header.pack(fill="x")
        ttk.Label(header, text="Victoria 3 Native Loader", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text=f"v{__version__}  ·  Local, version-checked DLL plugins",
                  style="Muted.TLabel").pack(side="left", padx=18)

        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(6, 12))
        self.play = ttk.Frame(self.tabs, padding=16)
        self.plugin_tab = ttk.Frame(self.tabs, padding=16)
        self.settings_tab = ttk.Frame(self.tabs, padding=16)
        self.log_tab = ttk.Frame(self.tabs, padding=16)
        self.tabs.add(self.play, text="Play & Mods")
        self.tabs.add(self.plugin_tab, text="Native Plugins")
        self.tabs.add(self.settings_tab, text="Game Settings")
        self.tabs.add(self.log_tab, text="Activity Log")
        self._build_play()
        self._build_plugins()
        self._build_settings()
        self._build_logs()

        footer = ttk.Frame(self.root, padding=(22, 6, 22, 16))
        footer.pack(fill="x")
        self.status_var = tk.StringVar(value="Ready — no changes made to the Paradox launcher.")
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel").pack(side="left")
        self.launch_btn = ttk.Button(footer, text="Launch Victoria 3",
                                     command=lambda:self._launch(False),
                                     style="Accent.TButton")
        self.launch_btn.pack(side="right")
        self.safe_btn = ttk.Button(footer, text="Launch without DLLs",
                                   command=lambda:self._launch(True))
        self.safe_btn.pack(side="right", padx=(0, 9))

    def _table(self, parent, cols: list[tuple[str, str, int]]):
        wrap = ttk.Frame(parent)
        tree = ttk.Treeview(wrap, columns=[c[0] for c in cols], show="headings",
                            selectmode="browse")
        for key, label, width in cols:
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=60, stretch=key == cols[0][0])
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return wrap, tree

    def _build_play(self):
        upper = ttk.Frame(self.play)
        upper.pack(fill="x", pady=(0, 12))
        ttk.Label(upper, text="Paradox playset", style="Muted.TLabel").pack(side="left", padx=(0, 9))
        self.playset_var = tk.StringVar()
        self.playsets_box = ttk.Combobox(upper, textvariable=self.playset_var,
                                          state="readonly", width=45)
        self.playsets_box.pack(side="left", fill="x", expand=True)
        ttk.Button(upper, text="Import playset", command=self._import_playset).pack(side="left", padx=8)
        ttk.Button(upper, text="Refresh", command=self._refresh_all).pack(side="left")

        area = ttk.Frame(self.play)
        area.pack(fill="both", expand=True)
        left = ttk.Frame(area)
        left.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="Installed Mods", font=("Segoe UI Semibold", 11)).pack(anchor="w")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._rebuild_available())
        ttk.Entry(left, textvariable=self.filter_var).pack(fill="x", pady=(8, 8))
        available, self.available_tree = self._table(
            left, [("name", "Name", 260), ("version", "Version", 85), ("source", "Source", 90)])
        available.pack(fill="both", expand=True)
        self.available_tree.bind("<Double-1>", lambda _: self._add_mod())

        middle = ttk.Frame(area, padding=(10, 50, 10, 0))
        middle.pack(side="left", fill="y")
        ttk.Button(middle, text="Add →", command=self._add_mod).pack(fill="x", pady=4)
        ttk.Button(middle, text="← Remove", command=self._remove_mod).pack(fill="x", pady=4)
        ttk.Button(middle, text="↑ Higher", command=lambda:self._move_mod(-1)).pack(fill="x", pady=14)
        ttk.Button(middle, text="↓ Lower", command=lambda:self._move_mod(1)).pack(fill="x", pady=4)
        ttk.Button(middle, text="Add folder…", command=self._add_folder).pack(fill="x", pady=17)

        right = ttk.Frame(area)
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="Enabled Mods — Top loads first",
                  font=("Segoe UI Semibold", 11)).pack(anchor="w")
        self.selected_summary = tk.StringVar(value="0 mods")
        ttk.Label(right, textvariable=self.selected_summary, style="Muted.TLabel").pack(anchor="w", pady=8)
        enabled, self.enabled_tree = self._table(right,
                    [("order", "#", 40), ("name", "Name", 270), ("version", "Version", 80)])
        enabled.pack(fill="both", expand=True)
        self.enabled_tree.bind("<Double-1>", lambda _:self._remove_mod())

        bottom = ttk.Frame(self.play)
        bottom.pack(fill="x", pady=(12, 0))
        ttk.Button(bottom, text="Preview launch", command=self._preview).pack(side="left")
        ttk.Button(bottom, text="Save selection", command=self._save_config).pack(side="left", padx=8)
        ttk.Label(bottom, text="Mods load in the displayed order; drag-free Up/Down controls preserve it.",
                  style="Muted.TLabel").pack(side="left", padx=14)

    def _build_plugins(self):
        intro = ttk.Frame(self.plugin_tab)
        intro.pack(fill="x", pady=(0, 12))
        self.enable_plugins_var = tk.BooleanVar(value=self.cfg.enable_plugins)
        ttk.Checkbutton(intro, text="Enable native DLL injection for this launch",
                        variable=self.enable_plugins_var).pack(side="left")
        ttk.Label(intro, text="Off by default. Only trust DLLs whose authors you know.",
                  style="Muted.TLabel").pack(side="left", padx=22)
        frame, self.plugin_tree = self._table(self.plugin_tab,
            [("enabled", "On", 50), ("name", "Plugin", 300),
             ("version", "Version", 90), ("state", "Validation", 310)])
        frame.pack(fill="both", expand=True)
        self.plugin_tree.bind("<Double-1>", lambda _:self._toggle_plugin())
        actions = ttk.Frame(self.plugin_tab)
        actions.pack(fill="x", pady=(12, 8))
        ttk.Button(actions, text="Enable/disable selected", command=self._toggle_plugin).pack(side="left")
        ttk.Button(actions, text="Install plugin folder…", command=self._install_plugin).pack(side="left", padx=8)
        ttk.Button(actions, text="Open plugins directory", command=self._open_plugins).pack(side="left")
        ttk.Button(actions, text="Refresh", command=self.reload_plugins).pack(side="left", padx=8)
        ttk.Label(self.plugin_tab,
                  text="Each plugin has a pinned DLL SHA-256, allowed game-executable hashes, and a native initialization export.",
                  style="Muted.TLabel").pack(anchor="w", pady=(5, 0))

    def _build_settings(self):
        self.exe_var = tk.StringVar(value=self.cfg.game_exe)
        self.userdir_var = tk.StringVar(value=self.cfg.base_userdir)
        self.profile_var = tk.StringVar(value=self.cfg.profile_name)
        self.shaders_var = tk.BooleanVar(value=self.cfg.share_shaders)
        self.saves_var = tk.BooleanVar(value=self.cfg.share_saves)
        self.args_var = tk.StringVar(value=" ".join(self.cfg.additional_args))

        def path_row(label, variable, browse):
            f = ttk.Frame(self.settings_tab)
            f.pack(fill="x", pady=10)
            ttk.Label(f, text=label, width=27).pack(side="left")
            ttk.Entry(f, textvariable=variable).pack(side="left", fill="x", expand=True, padx=8)
            ttk.Button(f, text="Browse…", command=browse).pack(side="right")

        path_row("Victoria 3 executable", self.exe_var,
                 lambda:self._choose_exe())
        path_row("Paradox user data folder", self.userdir_var,
                 lambda:self._choose_userdir())
        f = ttk.Frame(self.settings_tab)
        f.pack(fill="x", pady=12)
        ttk.Label(f, text="Managed profile name", width=27).pack(side="left")
        ttk.Entry(f, textvariable=self.profile_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(f, text="Local AppData", style="Muted.TLabel").pack(side="right")
        ttk.Checkbutton(self.settings_tab, text="Reuse existing shader cache (avoids unnecessary shader rebuilds)",
                        variable=self.shaders_var).pack(anchor="w", pady=6)
        ttk.Checkbutton(self.settings_tab, text="Share normal Victoria 3 save games",
                        variable=self.saves_var).pack(anchor="w", pady=6)
        f = ttk.Frame(self.settings_tab)
        f.pack(fill="x", pady=15)
        ttk.Label(f, text="Extra game arguments", width=27).pack(side="left")
        ttk.Entry(f, textvariable=self.args_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(self.settings_tab,
                  text="The launcher reads Paradox playsets but never writes launcher-v2.sqlite or the original content_load.json.",
                  style="Muted.TLabel").pack(anchor="w", pady=12)
        ttk.Label(self.settings_tab,
                  text="The game runs using a separate managed profile. Shared directories are linked only with consent.",
                  style="Muted.TLabel").pack(anchor="w", pady=4)
        ttk.Button(self.settings_tab, text="Save settings", command=self._save_config).pack(anchor="w", pady=18)

    def _build_logs(self):
        holder = ttk.Frame(self.log_tab)
        holder.pack(fill="both", expand=True)
        self.log_box = tk.Text(holder, bg=PANEL, fg=FG, insertbackground=FG,
                               font=("Consolas", 10), wrap="word", relief="flat",
                               padx=16, pady=12)
        scroll = ttk.Scrollbar(holder, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=scroll.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.log_box.insert("end", "Victoria 3 Native Loader ready. No game process launched.\n")
        self.log_box.configure(state="disabled")

    def _log(self, text: str):
        at = dt.datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{at}] {text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self.status_var.set(text[:150])

    def _refresh_all(self):
        self.reload_library()
        self.reload_playsets()
        self.reload_plugins()

    def reload_library(self):
        try:
            self._sync_settings()
            self.mods = all_mods(Path(self.cfg.base_userdir))
            self.mod_by_path = {m.path.casefold():m for m in self.mods}
            self._rebuild_available()
            self._rebuild_enabled()
            self._log(f"Indexed {len(self.mods)} installed mod directories.")
        except Exception as exc:
            self._log(f"Could not scan mods: {exc}")

    def reload_playsets(self):
        try:
            items = playsets(Path(self.userdir_var.get()))
            self.playset_by_label = {}
            for row in items:
                label = f"{row.name}  [{row.id[:8]}]" + (" (active)" if row.active else "")
                self.playset_by_label[label] = row
            self.playsets_box["values"] = list(self.playset_by_label)
            match = next((s for s, row in self.playset_by_label.items()
                          if row.id == self.cfg.last_playset_id), None)
            if not match:
                match = next(iter(self.playset_by_label), "")
            self.playset_var.set(match)
            self._log(f"Imported {len(items)} Paradox playsets read-only.")
        except Exception as exc:
            self._log(f"Paradox playset import unavailable: {exc}")

    def _import_playset(self):
        row = self.playset_by_label.get(self.playset_var.get())
        if row is None:
            return
        try:
            mods, warnings = playset_mods(Path(self.userdir_var.get()), row.id)
            self.selected_paths = [m.path for m in mods]
            self.cfg.last_playset_id = row.id
            self._rebuild_enabled()
            self._log(f"Imported {len(mods)} enabled mods from {row.name}.")
            if warnings:
                messagebox.showwarning("Missing mods", "\n".join(warnings[:20]))
        except Exception as exc:
            messagebox.showerror("Playset import failed", str(exc))

    def _rebuild_available(self):
        if not hasattr(self, "available_tree"):
            return
        for item in self.available_tree.get_children():
            self.available_tree.delete(item)
        query = self.filter_var.get().casefold().strip()
        for mod in self.mods:
            if query and query not in (mod.name + " " + mod.source).casefold():
                continue
            self.available_tree.insert("", "end", iid=mod.path,
                values=(mod.name, mod.version, mod.source))

    def _display_mod(self, p: str) -> Mod:
        known = self.mod_by_path.get(p.casefold())
        if known is not None:
            return known
        data = read_metadata(Path(p))
        return Mod(p, str(data.get("name") or Path(p).name), p,
                   str(data.get("version") or ""), "custom")

    def _rebuild_enabled(self):
        if not hasattr(self, "enabled_tree"):
            return
        for item in self.enabled_tree.get_children():
            self.enabled_tree.delete(item)
        for i, p in enumerate(self.selected_paths):
            m = self._display_mod(p)
            self.enabled_tree.insert("", "end", iid=p, values=(i+1, m.name, m.version))
        self.selected_summary.set(f"{len(self.selected_paths)} enabled mods")

    def _add_mod(self):
        selected = self.available_tree.selection()
        if not selected:
            return
        path = selected[0]
        if path.casefold() not in {p.casefold() for p in self.selected_paths}:
            self.selected_paths.append(path)
            self._rebuild_enabled()
            self.enabled_tree.selection_set(path)

    def _add_folder(self):
        path = filedialog.askdirectory(title="Select a Victoria 3 mod directory")
        if not path:
            return
        p = str(Path(path).resolve())
        if not read_metadata(Path(p)) and not (Path(p)/"descriptor.mod").is_file():
            messagebox.showerror("Invalid mod", "This folder lacks a Victoria 3 mod manifest.")
            return
        if p.casefold() not in {x.casefold() for x in self.selected_paths}:
            self.selected_paths.append(p)
            self._rebuild_enabled()

    def _remove_mod(self):
        selected = self.enabled_tree.selection()
        if not selected:
            return
        self.selected_paths = [p for p in self.selected_paths if p != selected[0]]
        self._rebuild_enabled()

    def _move_mod(self, direction: int):
        selected = self.enabled_tree.selection()
        if not selected:
            return
        item = selected[0]
        idx = self.selected_paths.index(item)
        to = idx + direction
        if to<0 or to>=len(self.selected_paths):
            return
        self.selected_paths[idx],self.selected_paths[to]=self.selected_paths[to],self.selected_paths[idx]
        self._rebuild_enabled()
        self.enabled_tree.selection_set(item)

    def reload_plugins(self):
        self.plugins, warnings = discover_plugins()
        for item in self.plugin_tree.get_children():
            self.plugin_tree.delete(item)
        for plugin in self.plugins:
            state = "Ready" if plugin.dll.is_file() else "DLL missing"
            self.plugin_tree.insert("", "end", iid=plugin.id,
                values=("✓" if plugin.id in self.cfg.enabled_plugin_ids else "—",
                        plugin.name, plugin.version, state))
        for warning in warnings:
            self._log(f"Plugin manifest warning: {warning}")
        self._log(f"Discovered {len(self.plugins)} native plugin manifests.")

    def _toggle_plugin(self):
        ids = self.plugin_tree.selection()
        if not ids:
            return
        key = ids[0]
        if key in self.cfg.enabled_plugin_ids:
            self.cfg.enabled_plugin_ids.remove(key)
        else:
            self.cfg.enabled_plugin_ids.append(key)
        self.reload_plugins()

    def _install_plugin(self):
        src = filedialog.askdirectory(title="Select plugin folder containing plugin.json")
        if not src:
            return
        try:
            dest = install_plugin_directory(Path(src))
            self._log(f"Installed native plugin to {dest}. Still disabled until selected.")
            self.reload_plugins()
        except Exception as exc:
            messagebox.showerror("Plugin installation failed", str(exc))

    def _open_plugins(self):
        folder = plugins_dir()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def _choose_exe(self):
        value = filedialog.askopenfilename(title="Select victoria3.exe", filetypes=[("Executable", "*.exe")])
        if value:
            self.exe_var.set(value)

    def _choose_userdir(self):
        value = filedialog.askdirectory(title="Select Paradox Interactive/Victoria 3 user folder")
        if value:
            self.userdir_var.set(value)
            self.reload_library()
            self.reload_playsets()

    def _sync_settings(self):
        self.cfg.game_exe = self.exe_var.get().strip()
        self.cfg.base_userdir = self.userdir_var.get().strip()
        self.cfg.profile_name = self.profile_var.get().strip()
        self.cfg.share_saves = self.saves_var.get()
        self.cfg.share_shaders = self.shaders_var.get()
        self.cfg.enable_plugins = self.enable_plugins_var.get()
        raw = self.args_var.get().strip()
        self.cfg.additional_args = [s.strip('"') for s in shlex.split(raw, posix=False)] if raw else []
        self.cfg.enabled_mod_paths = list(self.selected_paths)

    def _save_config(self):
        try:
            self._sync_settings()
            self.cfg.save()
            self._log("Selection and settings saved in Local AppData.")
        except Exception as exc:
            messagebox.showerror("Cannot save settings", str(exc))

    def _preview(self):
        try:
            self._sync_settings()
            plan = build_plan(self.cfg)
            self._log("Launch preview:\n" + json.dumps(plan, indent=2))
            self.tabs.select(self.log_tab)
        except Exception as exc:
            messagebox.showerror("Launch validation failed", str(exc))

    def _launch(self, without_plugins: bool):
        if self._busy:
            return
        try:
            self._sync_settings()
            self.cfg.save()
            cfg = replace(self.cfg, enable_plugins=False) if without_plugins else replace(self.cfg)
            plan = build_plan(cfg)
        except Exception as exc:
            messagebox.showerror("Launch validation failed", str(exc))
            return
        if plan["enabled_plugins"]:
            label = ", ".join(x["id"] for x in plan["enabled_plugins"])
            if not messagebox.askyesno(
                "Confirm native code injection",
                "Native DLL plugins run arbitrary code inside Victoria 3 and are not sandboxed.\n\n"
                f"Enable these plugins?\n{label}\n\n"
                "Only continue with trusted plugins for your exact game version."):
                return
        self._busy = True
        self.launch_btn.configure(state="disabled")
        self.safe_btn.configure(state="disabled")
        self.tabs.select(self.log_tab)
        self._log("Preparing isolated profile and launching Victoria 3…")
        thread = threading.Thread(target=self._launch_worker, args=(cfg,), daemon=True)
        thread.start()

    def _launch_worker(self, cfg):
        try:
            result = launch_game(cfg, notify=lambda message:self.events.put(("log",message)))
            self.events.put(("launch_completed", result))
        except Exception as exc:
            self.events.put(("launch_failed", str(exc)))

    def _poll_events(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._log(value)
            elif kind == "launch_failed":
                self._log("Launch error: " + value)
                self._busy = False
                messagebox.showerror("Game launch failed", value)
                self.launch_btn.configure(state="normal")
                self.safe_btn.configure(state="normal")
            elif kind == "launch_completed":
                self._busy = False
                self.current_launch = value
                self.launch_btn.configure(state="normal")
                self.safe_btn.configure(state="normal")
                if value.errors:
                    messagebox.showwarning("Native plugins did not load",
                        "Game started but one or more plugins failed:\n\n" + "\n".join(value.errors))
                self._log(f"Game PID {value.process_id}; profile {value.profile}; "
                          f"loaded native plugins: {len(value.loaded_plugins)}.")
        if self.current_launch is not None:
            status = refresh_session_status(self.current_launch)
            if status == "EXITED":
                self._log(f"Victoria 3 PID {self.current_launch.process_id} has exited.")
                self.current_launch = None
        self.root.after(400, self._poll_events)

    def _close(self):
        try:
            self._sync_settings()
            self.cfg.save()
        except Exception:
            pass
        self.root.destroy()
