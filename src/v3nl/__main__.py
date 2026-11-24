"""CLI entrypoint and graphical application bootstrap."""
from __future__ import annotations

import argparse
import json
import sys
from .config import LauncherConfig
from .launcher import build_plan
from .mods import playsets, playset_mods


def main() -> int:
    p = argparse.ArgumentParser(prog="v3nl", description="Victoria 3 Native Loader")
    p.add_argument("--dry-run", action="store_true", help="Validate current selection; never launch game")
    p.add_argument("--list-playsets", action="store_true", help="Read the Paradox launcher database")
    p.add_argument("--playset-id", help="Dry-run a specific Paradox launcher playset")
    args = p.parse_args()
    try:
        cfg = LauncherConfig.load()
        if args.list_playsets:
            print(json.dumps([x.__dict__ for x in playsets(__import__("pathlib").Path(cfg.base_userdir))],
                             indent=2))
            return 0
        if args.playset_id:
            mods, warnings = playset_mods(__import__("pathlib").Path(cfg.base_userdir), args.playset_id)
            cfg.enabled_mod_paths = [m.path for m in mods]
            print("Playset warnings:", warnings, file=sys.stderr)
        if args.dry_run or args.playset_id:
            print(json.dumps(build_plan(cfg), indent=2))
            return 0
        from .ui import main_ui
        main_ui(cfg)
        return 0
    except Exception as exc:
        print(f"Victoria 3 Native Loader error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
