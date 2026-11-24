"""Local configuration and game/profile path discovery. No writes to Paradox's database."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path


def local_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "Victoria3NativeLoader"


def default_userdir() -> Path:
    candidates = [
        Path.home() / "OneDrive" / "Documents" / "Paradox Interactive" / "Victoria 3",
        Path.home() / "Documents" / "Paradox Interactive" / "Victoria 3",
    ]
    return next((p for p in candidates if (p / "launcher-v2.sqlite").exists()), candidates[0])


def default_game_exe() -> Path:
    candidates = [
        Path("C:/Program Files (x86)/Steam/steamapps/common/Victoria 3/binaries/victoria3.exe"),
        Path("C:/Program Files/Steam/steamapps/common/Victoria 3/binaries/victoria3.exe"),
    ]
    return next((p for p in candidates if p.is_file()), candidates[0])


@dataclass
class LauncherConfig:
    game_exe: str = field(default_factory=lambda: str(default_game_exe()))
    base_userdir: str = field(default_factory=lambda: str(default_userdir()))
    profile_name: str = "Default"
    enabled_mod_paths: list[str] = field(default_factory=list)
    enable_plugins: bool = False
    enabled_plugin_ids: list[str] = field(default_factory=list)
    share_saves: bool = True
    share_shaders: bool = True
    additional_args: list[str] = field(default_factory=list)
    last_playset_id: str = ""

    @staticmethod
    def load(path: Path | None = None) -> "LauncherConfig":
        path = path or (local_data() / "config.json")
        if not path.exists():
            return LauncherConfig()
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            cfg = LauncherConfig()
            for key in asdict(cfg):
                if key in data and isinstance(data[key], type(getattr(cfg, key))):
                    setattr(cfg, key, data[key])
            return cfg
        except (OSError, ValueError, TypeError):
            # Preserve corrupt settings for manual recovery rather than overwriting.
            raise ValueError(f"Unable to read launcher settings: {path}")

    def save(self, path: Path | None = None) -> None:
        path = path or (local_data() / "config.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)


def safe_profile_name(name: str) -> str:
    if not name or len(name) > 64 or not all(ch.isalnum() or ch in "-_ " for ch in name):
        raise ValueError("Profile name must contain only letters, numbers, spaces, - or _ (max 64).")
    return name.strip()


def app_profile_dir(cfg: LauncherConfig) -> Path:
    return local_data() / "profiles" / safe_profile_name(cfg.profile_name)
