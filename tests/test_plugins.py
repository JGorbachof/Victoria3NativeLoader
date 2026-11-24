import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v3nl.plugins import NativePlugin, parse_plugin, resolve_selected, discover_plugins


SHA = "a"*64
DLL_SHA = "b"*64


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_plugin(self, name="example", deps=None, relative="test.dll"):
        folder=self.root/name
        folder.mkdir(exist_ok=True)
        manifest=folder/"plugin.json"
        manifest.write_text(json.dumps({
            "schema_version":1,"abi_version":1,"id":name,
            "name":name,"version":"0.1","dll":relative,
            "dll_sha256":DLL_SHA,"supported_game_sha256":[SHA],
            "dependencies":deps or [],"init_export":"V3NL_PluginInit"
        }),encoding="utf-8")
        return parse_plugin(manifest)

    def test_no_path_traversal(self):
        with self.assertRaises(ValueError):
            self.write_plugin(relative="../not-my-file.dll")

    def test_dependency_order(self):
        p1=self.write_plugin("first")
        p2=self.write_plugin("second",deps=["first"])
        with patch.object(NativePlugin,"validate",return_value=None):
            result=resolve_selected([p1,p2],["second"],SHA)
        self.assertEqual([x.id for x in result],["first","second"])

    def test_missing_and_cycles_rejected(self):
        p=self.write_plugin("first",deps=["second"])
        with patch.object(NativePlugin,"validate",return_value=None):
            with self.assertRaises(ValueError):
                resolve_selected([p],["first"],SHA)
        second=self.write_plugin("second",deps=["first"])
        with patch.object(NativePlugin,"validate",return_value=None):
            with self.assertRaises(ValueError):
                resolve_selected([p,second],["first"],SHA)

    def test_does_not_install_or_enable_plugins_automatically(self):
        self.write_plugin()
        plugins,warnings=discover_plugins(self.root)
        self.assertEqual([p.id for p in plugins],["example"])
        self.assertEqual(warnings,[])
        self.assertFalse((self.root/"example"/"test.dll").exists())
