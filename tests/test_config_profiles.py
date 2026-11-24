import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v3nl.config import LauncherConfig, safe_profile_name
from v3nl.profiles import prepare_profile, preview_profile


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "original"
        self.base.mkdir()
        (self.base / "shadercache").mkdir()
        (self.base / "save games").mkdir()
        (self.base / "pdx_settings.json").write_text(json.dumps({"Graphics":{"device":"GPU TEST"}}))
        (self.base / "content_load.json").write_text(json.dumps({
            "enabledMods":[], "disabledDLC": ["original_disabled_dlc"], "enabledUGC": []
        }))
        self.mod = self.root / "some-mod"
        (self.mod / ".metadata").mkdir(parents=True)
        (self.mod / ".metadata" / "metadata.json").write_text(
            json.dumps({"id":"test","name":"Test Mod"}))
        self.cfg = LauncherConfig(base_userdir=str(self.base),profile_name="Testing",
                                  enabled_mod_paths=[str(self.mod)],
                                  share_saves=True,share_shaders=True)
        self.local_data = self.root / "appdata"
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": str(self.local_data)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_managed_profile_shares_directories_but_not_database(self):
        profile, content = prepare_profile(self.cfg)
        self.assertTrue((profile / "shadercache").exists())
        self.assertTrue((profile / "save games").exists())
        self.assertTrue(os.path.samefile(profile / "shadercache", self.base / "shadercache"))
        self.assertTrue(os.path.samefile(profile / "save games", self.base / "save games"))
        self.assertEqual(content["disabledDLC"], ["original_disabled_dlc"])
        self.assertEqual(content["enabledMods"][0]["path"], str(self.mod.resolve()))
        self.assertEqual(json.loads((self.base / "content_load.json").read_text())["enabledMods"],[])
        self.assertFalse((self.base / ".v3nl.json").exists())
        # Running again should reuse the same safe junctions, not delete/relink them.
        prepare_profile(self.cfg)

    def test_preview_has_no_profile_side_effects(self):
        info = preview_profile(self.cfg)
        self.assertEqual(len(info["enabled_mods"]),1)
        self.assertFalse((self.local_data / "Victoria3NativeLoader").exists())

    def test_profile_name_validation(self):
        self.assertEqual(safe_profile_name("My-Profile"),"My-Profile")
        for x in ("", "../evil", "a/b", "a"*65):
            with self.assertRaises(ValueError):
                safe_profile_name(x)
