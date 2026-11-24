"""Version-pinned native DLL plugin discovery, validation and dependency ordering."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Iterable

from .config import local_data
from . import PLUGIN_ABI_VERSION


ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
SHA_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")


def plugins_dir() -> Path:
    return local_data() / "plugins"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class NativePlugin:
    id: str
    name: str
    version: str
    manifest: Path
    dll: Path
    dll_sha256: str
    supported_game_sha256: tuple[str, ...]
    dependencies: tuple[str, ...]
    abi_version: int = PLUGIN_ABI_VERSION
    init_export: str = "V3NL_PluginInit"

    def validate(self, game_sha256: str) -> None:
        if self.abi_version != PLUGIN_ABI_VERSION:
            raise ValueError(f"{self.id}: plugin ABI {self.abi_version} is unsupported.")
        if not self.dll.is_file() or self.dll.suffix.casefold() != ".dll":
            raise ValueError(f"{self.id}: native DLL not found: {self.dll}")
        if not SHA_PATTERN.fullmatch(self.dll_sha256):
            raise ValueError(f"{self.id}: a pinned DLL SHA-256 is required.")
        if file_sha256(self.dll).lower() != self.dll_sha256.lower():
            raise ValueError(f"{self.id}: native DLL hash mismatch.")
        if not self.supported_game_sha256 or game_sha256.lower() not in self.supported_game_sha256:
            raise ValueError(
                f"{self.id}: this plugin has not been approved for game executable SHA256 {game_sha256}.")
        if self.init_export != "V3NL_PluginInit":
            raise ValueError(f"{self.id}: unsupported plugin entrypoint {self.init_export}")
        self._validate_pe()

    def _validate_pe(self) -> None:
        import pefile
        pe = pefile.PE(str(self.dll), fast_load=True)
        try:
            if pe.FILE_HEADER.Machine != 0x8664:
                raise ValueError(f"{self.id}: plugin DLL must be x64.")
            if not (pe.FILE_HEADER.Characteristics & 0x2000):
                raise ValueError(f"{self.id}: file is not a DLL.")
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])
            if not hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
                raise ValueError(f"{self.id}: DLL has no exports.")
            if not any(s.name == self.init_export.encode("ascii")
                       for s in pe.DIRECTORY_ENTRY_EXPORT.symbols):
                raise ValueError(f"{self.id}: required export {self.init_export} is missing.")
        finally:
            # Windows refuses to rename a staged DLL while pefile holds its mmap.
            pe.close()


def parse_plugin(path: Path) -> NativePlugin:
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(obj, dict) or obj.get("schema_version") != 1:
        raise ValueError(f"{path}: unsupported plugin manifest schema")
    plugin_id = obj.get("id")
    if not isinstance(plugin_id, str) or not ID_PATTERN.fullmatch(plugin_id):
        raise ValueError(f"{path}: invalid plugin ID")
    relative = obj.get("dll")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or "\\" in relative:
        raise ValueError(f"{plugin_id}: plugin dll must be a relative forward-slash path")
    relative_path = Path(relative)
    if any(x in ("..", "", ".") for x in relative_path.parts):
        raise ValueError(f"{plugin_id}: DLL path traverses outside plugin folder")
    dll = (path.parent / relative_path).resolve()
    dll.relative_to(path.parent.resolve())  # Cannot refer to a file outside own plugin directory.
    allowed = obj.get("supported_game_sha256")
    deps = obj.get("dependencies", [])
    if not isinstance(allowed, list) or not all(
        isinstance(v, str) and SHA_PATTERN.fullmatch(v) for v in allowed):
        raise ValueError(f"{plugin_id}: provide pinned supported_game_sha256 array")
    if not isinstance(deps, list) or not all(
        isinstance(v, str) and ID_PATTERN.fullmatch(v) for v in deps):
        raise ValueError(f"{plugin_id}: invalid dependency IDs")
    return NativePlugin(
        id=plugin_id, name=str(obj.get("name") or plugin_id),
        version=str(obj.get("version") or "0"),
        manifest=path, dll=dll,
        dll_sha256=str(obj.get("dll_sha256") or ""),
        supported_game_sha256=tuple(v.lower() for v in allowed),
        dependencies=tuple(deps),
        abi_version=obj.get("abi_version", 1),
        init_export=str(obj.get("init_export") or "V3NL_PluginInit"),
    )


def discover_plugins(root: Path | None = None) -> tuple[list[NativePlugin], list[str]]:
    root = root or plugins_dir()
    result: list[NativePlugin] = []
    errors: list[str] = []
    if not root.is_dir():
        return result, errors
    for folder in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        manifest = folder / "plugin.json"
        if not folder.is_dir() or not manifest.is_file():
            continue
        try:
            plugin = parse_plugin(manifest)
            if any(other.id == plugin.id for other in result):
                raise ValueError(f"Duplicate plugin identifier {plugin.id}")
            result.append(plugin)
        except Exception as exc:
            errors.append(f"{folder.name}: {exc}")
    return result, errors


def resolve_selected(plugins: Iterable[NativePlugin], selected: list[str],
                     game_sha256: str) -> list[NativePlugin]:
    by_id = {p.id: p for p in plugins}
    ordered: list[NativePlugin] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def add(plugin_id: str) -> None:
        if plugin_id in visiting:
            raise ValueError(f"Native plugin dependency cycle involving {plugin_id}.")
        if plugin_id in visited:
            return
        if plugin_id not in by_id:
            raise ValueError(f"Missing required native plugin {plugin_id}.")
        visiting.add(plugin_id)
        obj = by_id[plugin_id]
        obj.validate(game_sha256)
        for dep in obj.dependencies:
            add(dep)
        visiting.remove(plugin_id)
        visited.add(plugin_id)
        ordered.append(obj)

    for ident in selected:
        add(ident)
    return ordered


def install_plugin_directory(source: Path, target_root: Path | None = None) -> Path:
    """Copy one explicit user-selected plugin folder; never download or auto-enable."""
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError("Select a plugin directory.")
    plugin = parse_plugin(source / "plugin.json")
    dest_root = target_root or plugins_dir()
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / plugin.id
    if dest.exists():
        raise FileExistsError(f"Plugin {plugin.id} is already installed; remove it explicitly first.")
    shutil.copytree(source, dest, symlinks=False)
    return dest
