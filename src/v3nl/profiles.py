"""Create dedicated Victoria 3 profiles without editing the Paradox launcher or its playsets."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .config import LauncherConfig, app_profile_dir
from .mods import validate_mods


def _directory_junction(link: Path, target: Path) -> None:
    target = target.resolve(strict=True)
    if not target.is_dir():
        raise ValueError(f"Shared directory does not exist: {target}")
    if link.exists():
        if not link.is_dir() or not os.path.samefile(link, target):
            raise ValueError(
                f"Refusing to replace an existing profile directory: {link}. "
                "Choose a new profile name or restore the directory manually.")
        return
    if link.is_symlink():
        raise ValueError(f"Broken profile directory symlink: {link}")
    if sys.platform == "win32":
        cp = subprocess.run(
            ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if cp.returncode:
            raise RuntimeError(f"Could not link {link} to {target}: {cp.stdout} {cp.stderr}")
    else:
        os.symlink(target, link, target_is_directory=True)


def _atomic_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".new")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def prepare_profile(cfg: LauncherConfig) -> tuple[Path, dict]:
    base = Path(cfg.base_userdir).resolve(strict=True)
    if not base.is_dir():
        raise ValueError(f"Original Victoria 3 user folder missing: {base}")
    profile = app_profile_dir(cfg)
    # Avoid using a base folder or arbitrary path as a managed profile.
    if profile.resolve() == base:
        raise ValueError("Managed profile must be separate from the Paradox user directory.")
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "logs").mkdir(exist_ok=True)

    settings_dest = profile / "pdx_settings.json"
    base_settings = base / "pdx_settings.json"
    if not settings_dest.exists():
        if base_settings.is_file():
            shutil.copy2(base_settings, settings_dest)
        else:
            _atomic_json(settings_dest, {"game": {"autosave": "yearly"}})

    if cfg.share_saves and (base / "save games").is_dir():
        _directory_junction(profile / "save games", base / "save games")
    else:
        (profile / "save games").mkdir(exist_ok=True)

    if cfg.share_shaders and (base / "shadercache").is_dir():
        _directory_junction(profile / "shadercache", base / "shadercache")

    selected = validate_mods(cfg.enabled_mod_paths)
    content = {"enabledMods": [{"path": p} for p in selected],
               "disabledDLC": [], "enabledUGC": []}
    old_content = base / "content_load.json"
    if old_content.is_file():
        try:
            old = json.loads(old_content.read_text(encoding="utf-8-sig"))
            for name in ("disabledDLC", "enabledUGC"):
                if isinstance(old.get(name), list):
                    content[name] = old[name]
        except (OSError, ValueError):
            pass
    _atomic_json(profile / "content_load.json", content)
    _atomic_json(profile / ".v3nl.json", {
        "schema": 1, "managed_by": "Victoria3NativeLoader",
        "base_userdir": str(base), "mod_paths": selected,
        "share_saves": cfg.share_saves, "share_shaders": cfg.share_shaders})
    return profile, content


def preview_profile(cfg: LauncherConfig) -> dict:
    # Validation-only path; no mkdir, junction or game settings changes.
    base = Path(cfg.base_userdir)
    mods = validate_mods(cfg.enabled_mod_paths)
    return {
        "game_userdir": str(app_profile_dir(cfg)),
        "paradox_source_userdir": str(base),
        "enabled_mods": mods,
        "share_save_directory": bool(cfg.share_saves),
        "share_shader_cache": bool(cfg.share_shaders),
        "writes_paradox_playset_database": False,
        "rebuilds_native_shaders_intentionally": False,
    }
