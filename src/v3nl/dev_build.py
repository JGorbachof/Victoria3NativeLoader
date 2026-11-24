"""Build and stage developer-owned native DLLs for reproducible launcher experiments.

Production user plugin installations are never overwritten by this pipeline.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Callable

from .plugins import file_sha256, parse_plugin, plugins_dir


def validate_build_spec(build: dict) -> dict:
    if not isinstance(build, dict):
        raise ValueError("Build definition must be an object.")
    required = ("command", "cwd", "dll", "manifest")
    if any(k not in build for k in required):
        raise ValueError(f"Build definition requires: {', '.join(required)}.")
    command = build["command"]
    if (not isinstance(command, list) or not command or
            not all(isinstance(x, str) and x and "\0" not in x for x in command)):
        raise ValueError("Build command must be a list of nonempty argument strings.")
    cwd = Path(build["cwd"]).expanduser().resolve()
    manifest = Path(build["manifest"]).expanduser().resolve()
    dll = Path(build["dll"]).expanduser().resolve()
    if not cwd.is_dir() or not manifest.is_file() or manifest.suffix.casefold() != ".json":
        raise ValueError("Build source directory or plugin manifest template is missing.")
    if dll.suffix.casefold() != ".dll":
        raise ValueError("Build output must be an x64 DLL.")
    # Keep a bounded runtime and no shell so build arguments remain exact.
    seconds = build.get("timeout_seconds", 300)
    if not isinstance(seconds, int) or not 10 <= seconds <= 1200:
        raise ValueError("Build timeout_seconds must be 10–1200 seconds.")
    return {"command": command, "cwd": cwd, "manifest": manifest,
            "dll": dll, "timeout_seconds": seconds}


def preview_build(build: dict, game_sha256: str, expected_id: str) -> dict:
    info = validate_build_spec(build)
    obj = json.loads(info["manifest"].read_text(encoding="utf-8-sig"))
    if not isinstance(obj, dict) or obj.get("id") != expected_id:
        raise ValueError(f"Plugin template must identify {expected_id}.")
    if game_sha256 not in obj.get("supported_game_sha256", []):
        raise ValueError("Plugin template does not allowlist this exact Victoria 3 executable.")
    if obj.get("init_export", "V3NL_PluginInit") != "V3NL_PluginInit":
        raise ValueError("New performance plugins must use the V3NL_PluginInit ABI.")
    if obj.get("dll") != info["dll"].name:
        raise ValueError("Plugin template DLL filename differs from the expected build output.")
    return {
        "command": info["command"], "cwd": str(info["cwd"]),
        "dll": str(info["dll"]), "manifest": str(info["manifest"]),
        "plugin_id": expected_id,
        "game_sha256": game_sha256,
        "build_timeout_seconds": info["timeout_seconds"],
    }


def build_and_stage(build: dict, game_sha256: str, expected_id: str,
                    output_dir: Path, notify: Callable[[str], None] = print,
                    root: Path | None = None) -> dict:
    """Build exactly once and stage a manifest+DLL with hash binding.

    Called before any game is started. Not safe to update a plugin that is loaded
    in another game, so any Victoria 3 instance blocks staging.
    """
    from .launcher import running_game_pids
    if running_game_pids():
        raise RuntimeError("A Victoria 3 instance is active; cannot replace developer DLL files.")
    preview = preview_build(build, game_sha256, expected_id)
    info = validate_build_spec(build)
    output_dir.mkdir(parents=True, exist_ok=True)
    notify("Building native performance plugin through the launcher pipeline.")
    result = subprocess.run(info["command"], cwd=info["cwd"], shell=False,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=info["timeout_seconds"], check=False)
    (output_dir / "build.log").write_text(result.stdout or "", encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"Native build failed with code {result.returncode}; see build.log.")
    if not info["dll"].is_file():
        raise FileNotFoundError(f"Compiler did not produce expected plugin DLL: {info['dll']}")
    obj = json.loads(info["manifest"].read_text(encoding="utf-8-sig"))
    obj["dll_sha256"] = file_sha256(info["dll"])
    plugin_root = root or plugins_dir()
    plugin_root.mkdir(parents=True, exist_ok=True)
    dest = plugin_root / expected_id
    stamp = ".v3nl_dev_build.json"
    if dest.exists():
        marker = dest / stamp
        if not marker.is_file():
            raise FileExistsError(
                f"Existing plugin {expected_id} was not staged by this pipeline; refusing overwrite.")
        old = json.loads(marker.read_text(encoding="utf-8"))
        if old.get("template") != str(info["manifest"]):
            raise FileExistsError("Existing developer plugin belongs to another build source.")
    with tempfile.TemporaryDirectory(prefix=".v3nl_stage_", dir=plugin_root) as temp:
        stage = Path(temp) / expected_id
        stage.mkdir()
        shutil.copy2(info["dll"], stage / info["dll"].name)
        (stage / "plugin.json").write_text(json.dumps(obj, indent=2) + "\n",
                                           encoding="utf-8")
        (stage / stamp).write_text(json.dumps({
            "template": str(info["manifest"]), "dll_source": str(info["dll"]),
            "built_dll_sha256": obj["dll_sha256"],
            "game_sha256": game_sha256}, indent=2) + "\n", encoding="utf-8")
        verified = parse_plugin(stage / "plugin.json")
        verified.validate(game_sha256)
        if dest.exists():
            # Keep old files intact until replacement is completely validated.
            backup = Path(temp) / "old_plugin"
            dest.rename(backup)
            try:
                stage.rename(dest)
            except Exception:
                backup.rename(dest)
                raise
        else:
            stage.rename(dest)
    notify(f"Staged {expected_id}: {obj['dll_sha256'][:16]}…")
    return {"id": expected_id, "dll_sha256": obj["dll_sha256"],
            "game_sha256": game_sha256, "plugin_folder": str(dest),
            "build_command": preview["command"], "log": str(output_dir / "build.log")}
