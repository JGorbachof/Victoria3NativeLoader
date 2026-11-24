"""Native experiment contract tests; these never start a game."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from v3nl.dev_build import preview_build
from v3nl.experiments import load_spec, preview_trial, execute_trial
from v3nl.launcher import LaunchResult
from v3nl.plugins import file_sha256


class NativeExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.exe = self.root / "victoria3.exe"
        self.exe.write_bytes(b"fake test-exe: NEVER EXECUTE")
        self.user = self.root / "ParadoxUser"
        self.user.mkdir()
        self.mod = self.root / "test_mod"
        (self.mod / ".metadata").mkdir(parents=True)
        (self.mod / ".metadata" / "metadata.json").write_text(
            '{"id":"test","name":"Test"}', encoding="utf-8")
        self.bin = self.root / "build" / "sched_test.dll"
        self.bin.parent.mkdir(parents=True)
        self.manifest = self.root / "test_plugin_manifest.json"
        self.hash = file_sha256(self.exe)
        self.manifest.write_text(json.dumps({
            "schema_version": 1, "abi_version": 1,
            "id": "sched-test", "name": "test", "version": "1",
            "dll": self.bin.name,
            "supported_game_sha256": [self.hash],
            "dependencies": [], "init_export": "V3NL_PluginInit"
        }), encoding="utf-8")
        self.spec = {
            "schema_version": 1, "id": "tu_sched_probe", "candidate_plugin_id": "sched-test",
            "game_exe": str(self.exe), "base_userdir": str(self.user),
            "mods": [str(self.mod)],
            "game_arguments": ["-handsoff", "-automated_test", "-run_until=1337.05.01"],
            "repetitions": 1, "timeout_seconds": 120,
            "min_complete_days": 2,
            "build": {"command": ["python", "-c", "print('dummy build')"],
                      "cwd": str(self.root), "dll": str(self.bin),
                      "manifest": str(self.manifest)},
        }
        self.specfile = self.root / "experiment.json"
        self.specfile.write_text(json.dumps(self.spec), encoding="utf-8")
        self.local_patch = patch.dict(os.environ, {
            "LOCALAPPDATA": str(self.root / "local_appdata")})
        self.local_patch.start()
        self.addCleanup(self.local_patch.stop)

    def test_plan_is_read_only_and_uses_launcher_profiles(self):
        spec = load_spec(self.specfile)
        plan = preview_trial(spec)
        self.assertEqual([x["arm"] for x in plan["arms"]], ["baseline", "candidate"])
        self.assertEqual(plan["arms"][0]["plan"]["enabled_plugins"], [])
        self.assertEqual(plan["arms"][1]["plan"]["enabled_plugins"][0]["id"], "sched-test")
        self.assertEqual(plan["arms"][1]["plan"]["enabled_plugins"][0]["status"],
                         "TO_BUILD_AND_VALIDATE_BEFORE_LAUNCH")
        self.assertEqual(plan["build"]["game_sha256"], self.hash)
        self.assertNotEqual(plan["arms"][0]["plan"]["game_userdir"],
                            plan["arms"][1]["plan"]["game_userdir"])
        self.assertFalse(plan["arms"][0]["plan"]["share_saves"])
        self.assertTrue(plan["arms"][0]["plan"]["share_shaders"])
        self.assertFalse((self.root / "local_appdata").exists())

    def test_bounded_run_until_required(self):
        self.spec["game_arguments"] = ["-automated_test"]
        self.specfile.write_text(json.dumps(self.spec))
        with self.assertRaises(ValueError):
            load_spec(self.specfile)

    def test_untrusted_build_template_cannot_change_plugin_id(self):
        raw = json.loads(self.manifest.read_text())
        raw["id"] = "some-other-plugin"
        self.manifest.write_text(json.dumps(raw))
        with self.assertRaises(ValueError):
            preview_build(self.spec["build"], self.hash, "sched-test")

    def test_execution_routes_both_arms_through_launcher(self):
        spec = load_spec(self.specfile)
        log = []
        def mocked_launch(cfg, notify=print):
            log.append(("launch", cfg.enable_plugins, cfg.enabled_plugin_ids[:]))
            run_num = len(log)
            session = self.root / f"session_{run_num}.json"
            session.write_text("{}")
            return LaunchResult(run_num, 10.0, self.root / f"profile_{run_num}",
                                session, ["sched-test"] if cfg.enable_plugins else [], [])
        days = {"1337_04_02": 2.0, "1337_04_03": 3.0}
        with (
            patch("v3nl.experiments.running_game_pids", return_value=[]),
            patch("v3nl.dev_build.build_and_stage", return_value={"id":"sched-test"}),
            patch("v3nl.experiments.build_and_stage", return_value={"id":"sched-test"}),
            patch("v3nl.experiments.launch_game", side_effect=mocked_launch),
            patch("v3nl.experiments._wait_owned", return_value=0) as wait_mock,
            patch("v3nl.experiments._days", return_value=days),
            patch("v3nl.experiments.build_plan", side_effect=lambda cfg: {
                 "executable_sha256": self.hash,
                 "game_userdir": str(self.root / cfg.profile_name),
                 "enabled_plugins": ([{"id":"sched-test"}] if cfg.enable_plugins else []),
            }),
            patch("v3nl.experiments.preview_trial", return_value={
                 "id":spec["id"],"game_exe_sha256":self.hash}) ,
        ):
            result = execute_trial(spec, notify=lambda message: None)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual([x[1] for x in log], [False, True])
        self.assertEqual(log[1][2], ["sched-test"])
        self.assertEqual(wait_mock.call_count, 2)
        self.assertEqual(result["matched_comparisons"][0]["matched_days"], 2)

    def test_plugin_injection_errors_do_not_count_as_success(self):
        spec = load_spec(self.specfile)
        def failed_launch(cfg, notify=print):
            session = self.root / "failed_session.json"
            session.write_text("{}")
            return LaunchResult(41, 1, self.root, session, [],
                                ["Plugin failed"] if cfg.enable_plugins else [])
        with (
            patch("v3nl.experiments.running_game_pids", return_value=[]),
            patch("v3nl.experiments.build_and_stage", return_value={"id":"sched-test"}),
            patch("v3nl.experiments.launch_game", side_effect=failed_launch),
            patch("v3nl.experiments._wait_owned", return_value=0),
            patch("v3nl.experiments._days", return_value={
                "1337_04_02":2.0,"1337_04_03":2.0}),
            patch("v3nl.experiments.build_plan", side_effect=lambda cfg: {
                "executable_sha256": self.hash, "game_userdir": "test",
                "enabled_plugins": ([{"id":"sched-test"}] if cfg.enable_plugins else [])}),
            patch("v3nl.experiments.preview_trial", return_value={
                "id":spec["id"],"game_exe_sha256":self.hash}),
        ):
            with self.assertRaisesRegex(RuntimeError,"initialization failed"):
                execute_trial(spec, notify=lambda message: None)
