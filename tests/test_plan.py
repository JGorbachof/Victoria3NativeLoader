import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v3nl.config import LauncherConfig
from v3nl.launcher import build_plan


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.base = self.root / "original"
        self.base.mkdir()
        self.exe = self.root / "victoria3.exe"
        self.exe.write_bytes(b"test-game")
        self.mod = self.root / "localmod"
        (self.mod/".metadata").mkdir(parents=True)
        (self.mod/".metadata"/"metadata.json").write_text(json.dumps({"name":"Test"}))
        self.cfg = LauncherConfig(game_exe=str(self.exe),base_userdir=str(self.base),
            enabled_mod_paths=[str(self.mod)],enable_plugins=False,
            additional_args=["-debug_mode"])

    def test_dry_run_has_no_side_effects(self):
        with patch.dict(os.environ,{"LOCALAPPDATA":str(self.root/"data")}):
            plan=build_plan(self.cfg)
        self.assertEqual(len(plan["enabled_mods"]),1)
        self.assertEqual(plan["enabled_plugins"],[])
        self.assertIn("-debug_mode",plan["game_arguments"])
        self.assertFalse((self.root/"data").exists())
        self.assertFalse(plan["will_patch_original_game_exe"])
        self.assertFalse(plan["will_suspend_game_process"])

    def test_userdir_override_rejected(self):
        self.cfg.additional_args=["--userdir=C:\\evil"]
        with self.assertRaises(ValueError):
            build_plan(self.cfg)
