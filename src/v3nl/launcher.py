"""Build and execute a normal game launch with optional, explicitly opted-in native plugins."""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable

import psutil

from .config import LauncherConfig, local_data
from .plugins import file_sha256, discover_plugins, resolve_selected
from .profiles import preview_profile, prepare_profile


@dataclass
class LaunchResult:
    process_id: int
    created_epoch: float
    profile: Path
    session_file: Path
    loaded_plugins: list[str]
    errors: list[str]


def safe_game_executable(path: Path) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Launching Victoria 3 requires Windows.")
    if not path.is_file() or path.name.casefold() != "victoria3.exe":
        raise ValueError(f"Select the actual Victoria 3 game executable: {path}")
    if not os.access(path, os.R_OK):
        raise PermissionError(f"Cannot read game executable: {path}")
    import pefile
    pe = pefile.PE(str(path), fast_load=True)
    if pe.FILE_HEADER.Machine != 0x8664:
        raise ValueError("Expected 64-bit Victoria 3 executable.")


def running_game_pids() -> list[int]:
    return [p.pid for p in psutil.process_iter(["name"])
            if (p.info.get("name") or "").casefold() == "victoria3.exe"]


def build_plan(cfg: LauncherConfig, strict_plugins: bool = True) -> dict:
    exe = Path(cfg.game_exe).expanduser().resolve()
    if not exe.is_file() or exe.name.casefold() != "victoria3.exe":
        raise ValueError(f"Victoria 3 executable was not found: {exe}")
    base = Path(cfg.base_userdir).expanduser().resolve()
    if not base.is_dir():
        raise ValueError(f"Original Victoria 3 data directory was not found: {base}")
    profile = preview_profile(cfg)
    game_hash = file_sha256(exe)
    plugins, issues = discover_plugins()
    chosen = resolve_selected(plugins, cfg.enabled_plugin_ids, game_hash) if cfg.enable_plugins else []
    if issues and strict_plugins and cfg.enable_plugins:
        # Invalid *unused* plugin manifests are reported but don't prevent a valid launch.
        pass
    args = list(cfg.additional_args)
    for item in args:
        if not isinstance(item, str) or "\x00" in item:
            raise ValueError("Invalid extra game argument.")
        if item.casefold().startswith("--userdir="):
            raise ValueError("Do not override --userdir; profiles are managed by this launcher.")
    return {
        "game_executable": str(exe),
        "executable_sha256": game_hash,
        "game_userdir": profile["game_userdir"],
        "enabled_mods": profile["enabled_mods"],
        "enabled_plugins": [{"id": p.id, "dll": str(p.dll), "sha256": p.dll_sha256}
                            for p in chosen],
        "plugin_manifest_warnings": issues,
        "share_saves": cfg.share_saves,
        "share_shaders": cfg.share_shaders,
        "game_arguments": ["-gdpr-compliant", *args,
                           "--userdir=" + profile["game_userdir"]],
        "will_patch_original_game_exe": False,
        "will_write_paradox_playset_database": False,
        "will_suspend_game_process": False,
    }


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def launch_game(cfg: LauncherConfig, notify: Callable[[str], None] = print) -> LaunchResult:
    plan = build_plan(cfg)
    if running_game_pids():
        raise RuntimeError("Another Victoria 3 process is already running. Close it before launching.")
    exe = Path(plan["game_executable"])
    safe_game_executable(exe)

    installed, _ = discover_plugins()
    active = resolve_selected(installed, cfg.enabled_plugin_ids, plan["executable_sha256"]) \
        if cfg.enable_plugins else []

    # Validate everything before making any userdir changes.
    profile, _ = prepare_profile(cfg)
    if running_game_pids():
        raise RuntimeError("Another Victoria 3 process started during preparation.")
    session_root = local_data() / "sessions"
    session_root.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    session = session_root / stamp
    session.mkdir(parents=True, exist_ok=False)
    manifest_path = session / "session.json"
    manifest = {
        "schema": 1, "status": "STARTING",
        "launched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "game_exe": str(exe), "game_exe_sha256": plan["executable_sha256"],
        "profile": str(profile), "mods": plan["enabled_mods"],
        "plugins_requested": [p.id for p in active],
        "plugins_loaded": [], "plugin_errors": [],
        "command": [str(exe), *plan["game_arguments"]],
    }
    _save_json(manifest_path, manifest)

    output = (session / "game_stdout.log").open("w", encoding="utf-8")
    errors_file = (session / "game_stderr.log").open("w", encoding="utf-8")
    try:
        proc = subprocess.Popen(manifest["command"], cwd=str(exe.parent),
                                stdin=subprocess.DEVNULL, stdout=output,
                                stderr=errors_file,
                                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    finally:
        output.close()
        errors_file.close()
    game = psutil.Process(proc.pid)
    created = game.create_time()
    manifest.update(status="RUNNING", pid=proc.pid, process_created_epoch=created)
    _save_json(manifest_path, manifest)
    notify(f"Victoria 3 started (PID {proc.pid}) with {len(plan['enabled_mods'])} mod(s).")

    loaded: list[str] = []
    failures: list[str] = []
    if active:
        # Native plugins are run by the game process, not injected into user-owned
        # preexisting processes. This thread remains outside the game process.
        time.sleep(2.0)
        from .win_inject import inject_plugin
        for plugin in active:
            if proc.poll() is not None:
                failures.append("Game exited before plugin initialization.")
                break
            try:
                notify(f"Loading native plugin: {plugin.name}")
                record = inject_plugin(proc.pid, created, exe, plugin,
                                       plan["executable_sha256"])
                loaded.append(plugin.id)
                notify(f"Native plugin initialized: {plugin.name}")
                (session / f"plugin_{plugin.id}.json").write_text(
                    json.dumps(record, indent=2) + "\n", encoding="utf-8")
            except Exception as exc:
                failures.append(f"{plugin.id}: {exc}")
                notify(f"Plugin injection failed: {exc}")
                # No more potentially unsafe DLL loads. The launched game is left
                # running; an injected DLL can't always be rolled back safely.
                break
    manifest["plugins_loaded"] = loaded
    manifest["plugin_errors"] = failures
    manifest["status"] = "RUNNING" if proc.poll() is None else "EXITED"
    if proc.poll() is not None:
        manifest["exit_code"] = proc.returncode
    _save_json(manifest_path, manifest)
    return LaunchResult(proc.pid, created, profile, manifest_path, loaded, failures)


def refresh_session_status(result: LaunchResult) -> str:
    try:
        p = psutil.Process(result.process_id)
        if abs(p.create_time() - result.created_epoch) < 2 and p.is_running():
            return "RUNNING"
    except psutil.NoSuchProcess:
        pass
    try:
        old = json.loads(result.session_file.read_text(encoding="utf-8"))
        old["status"] = "EXITED"
        old["last_checked_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        _save_json(result.session_file, old)
    except (OSError, ValueError):
        pass
    return "EXITED"
