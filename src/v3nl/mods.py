"""Read installed Paradox launcher playsets and local mod manifests without editing them."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
import json
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class Mod:
    key: str
    name: str
    path: str
    version: str = ""
    source: str = "local"
    supported_game_version: str = ""

    @property
    def exists(self) -> bool:
        return Path(self.path).is_dir()


@dataclass(frozen=True)
class Playset:
    id: str
    name: str
    active: bool = False


def read_metadata(folder: Path) -> dict:
    paths = [
        folder / ".metadata" / "metadata.json",
        folder / "metadata.json",
    ]
    for path in paths:
        if not path.is_file():
            continue
        try:
            obj = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(obj, dict):
                return obj
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def local_mods(base_userdir: Path) -> list[Mod]:
    result: list[Mod] = []
    moddir = base_userdir / "mod"
    if not moddir.is_dir():
        return result
    for folder in sorted(moddir.iterdir(), key=lambda p: p.name.casefold()):
        if not folder.is_dir():
            continue
        m = read_metadata(folder)
        if not m:
            continue
        result.append(Mod(
            key=f"local:{folder.resolve()}",
            name=str(m.get("name") or folder.name),
            path=str(folder.resolve()),
            version=str(m.get("version") or ""),
            source="local",
            supported_game_version=str(m.get("supported_game_version") or ""),
        ))
    return result


def _connect_readonly(db: Path) -> sqlite3.Connection:
    if not db.is_file():
        raise FileNotFoundError(f"Paradox playset database not found: {db}")
    # Uses SQLite's readonly URI. No writes or launcher schema migrations.
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2.0)


def launcher_mods(base_userdir: Path) -> list[Mod]:
    db = base_userdir / "launcher-v2.sqlite"
    with closing(_connect_readonly(db)) as conn:
        rows = conn.execute("""
            SELECT id, COALESCE(NULLIF(displayName,''),NULLIF(name,''),id),
                   COALESCE(version,''), COALESCE(source,'launcher'),
                   COALESCE(dirPath,''), COALESCE(repositoryPath,''),
                   COALESCE(requiredVersion,'')
            FROM mods
        """).fetchall()
    mods: list[Mod] = []
    for key, name, version, source, dirpath, repo, supported in rows:
        path = next((Path(x) for x in (dirpath, repo) if x and Path(x).is_dir()), None)
        if path is not None:
            mods.append(Mod(str(key), str(name), str(path.resolve()),
                            str(version), str(source), str(supported)))
    return mods


def all_mods(base_userdir: Path) -> list[Mod]:
    found: dict[str, Mod] = {}
    try:
        values = launcher_mods(base_userdir)
    except (FileNotFoundError, sqlite3.Error):
        values = []
    values.extend(local_mods(base_userdir))
    for mod in values:
        # Prefer the launcher database's richer entry for duplicate mod paths.
        norm = str(Path(mod.path).resolve()).casefold()
        found.setdefault(norm, mod)
    return sorted(found.values(), key=lambda x: x.name.casefold())


def playsets(base_userdir: Path) -> list[Playset]:
    with closing(_connect_readonly(base_userdir / "launcher-v2.sqlite")) as conn:
        rows = conn.execute("""
            SELECT id, name, COALESCE(isActive,0)
            FROM playsets WHERE COALESCE(isRemoved,0)=0
            ORDER BY isActive DESC, name COLLATE NOCASE, id
        """).fetchall()
    return [Playset(str(id), str(name), bool(active)) for id, name, active in rows]


def playset_mods(base_userdir: Path, playset_id: str) -> tuple[list[Mod], list[str]]:
    with closing(_connect_readonly(base_userdir / "launcher-v2.sqlite")) as conn:
        rows = conn.execute("""
            SELECT pm.modId, pm.enabled, pm.position,
                   COALESCE(NULLIF(m.displayName,''),NULLIF(m.name,''),pm.modId),
                   COALESCE(m.version,''), COALESCE(m.source,'launcher'),
                   COALESCE(m.dirPath,''), COALESCE(m.repositoryPath,''),
                   COALESCE(m.requiredVersion,'')
            FROM playsets_mods pm
            JOIN mods m ON m.id=pm.modId
            WHERE pm.playsetId=?
            ORDER BY COALESCE(pm.position,999999), pm.modId
        """, (playset_id,)).fetchall()
    enabled: list[Mod] = []
    warnings: list[str] = []
    for id, is_enabled, pos, name, version, source, directory, repository, supported in rows:
        if not is_enabled:
            continue
        valid = next((Path(x) for x in (directory, repository) if x and Path(x).is_dir()), None)
        if valid is None:
            warnings.append(f"Unavailable mod in playset: {name}")
            continue
        enabled.append(Mod(str(id), str(name), str(valid.resolve()),str(version),str(source),str(supported)))
    return enabled, warnings


def choose_mod(mod: Mod, selected: list[str]) -> list[str]:
    p = str(Path(mod.path).resolve())
    if p.casefold() in {x.casefold() for x in selected}:
        return list(selected)
    return [*selected, p]


def validate_mods(paths: list[str]) -> list[str]:
    if len(paths) > 400:
        raise ValueError("Too many enabled mods (limit 400).")
    seen: set[str] = set()
    clean: list[str] = []
    for raw in paths:
        p = Path(raw).resolve(strict=True)
        if not p.is_dir():
            raise ValueError(f"Enabled mod path is not a directory: {p}")
        if not (read_metadata(p) or (p / "descriptor.mod").is_file()):
            raise ValueError(f"Not a recognized Victoria 3 mod directory: {p}")
        key = str(p).casefold()
        if key in seen:
            raise ValueError(f"Duplicate mod entry: {p}")
        seen.add(key)
        clean.append(str(p))
    return clean
