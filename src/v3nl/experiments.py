"""Reproducible native performance experiments: build -> launcher -> evidence.

No standalone injector or direct game subprocess is allowed in this module.
Game startup and native plugin injection occur exclusively in launch_game().
"""
from __future__ import annotations

from dataclasses import asdict, replace
import csv
import datetime as dt
import json
from pathlib import Path
import re
import statistics
import time
import uuid
from typing import Callable

import psutil

from .config import LauncherConfig, local_data
from .dev_build import build_and_stage, preview_build
from .launcher import build_plan, launch_game, running_game_pids
from .plugins import file_sha256

ID = re.compile(r"^[a-z0-9][a-z0-9_-]{2,40}$")


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".new")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_spec(path: Path) -> dict:
    spec = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(spec, dict) or spec.get("schema_version") != 1:
        raise ValueError("Unsupported native experiment manifest schema.")
    name = spec.get("id")
    if not isinstance(name, str) or not ID.fullmatch(name):
        raise ValueError("Experiment id must be lowercase letters, digits, - or _, 3–41 chars.")
    plugin_id = spec.get("candidate_plugin_id")
    if not isinstance(plugin_id, str) or not plugin_id:
        raise ValueError("candidate_plugin_id is required.")
    if not isinstance(spec.get("mods"), list) or not all(
            isinstance(v, str) for v in spec["mods"]):
        raise ValueError("mods must be an ordered list of absolute mod folder paths.")
    args = spec.get("game_arguments", [
        "-handsoff", "-automated_test", "-scripted_tests",
        "-no_notifications", "-run_until=1337.05.01"])
    if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
        raise ValueError("game_arguments must be a list of argument strings.")
    if not any(x.startswith("-run_until=") for x in args):
        raise ValueError("Experiments must specify a bounded -run_until=YYYY.MM.DD argument.")
    for forbidden in ("-no_crash_reporter", "-nographics", "-disable-gui"):
        # These aren't inherently forbidden generally; avoid silently choosing
        # unsupported headless modes for the native plugin test harness.
        if forbidden in args:
            raise ValueError(f"Experimental launch argument {forbidden} requires a validated alternative.")
    repetitions = spec.get("repetitions", 1)
    if not isinstance(repetitions, int) or not 1 <= repetitions <= 5:
        raise ValueError("repetitions must be 1–5.")
    timeout = spec.get("timeout_seconds", 900)
    if not isinstance(timeout, int) or not 60 <= timeout <= 7200:
        raise ValueError("timeout_seconds must be 60–7200.")
    expected = spec.get("min_complete_days", 1)
    if not isinstance(expected, int) or not 1 <= expected <= 3650:
        raise ValueError("min_complete_days must be positive.")
    for key in ("game_exe", "base_userdir"):
        if not isinstance(spec.get(key), str) or not spec[key]:
            raise ValueError(f"{key} is required.")
    spec["game_arguments"] = args
    spec["repetitions"] = repetitions
    spec["timeout_seconds"] = timeout
    spec["min_complete_days"] = expected
    return spec


def _cfg(spec: dict, repetition: int, arm: str, run_tag: str = "preview") -> LauncherConfig:
    # Unique profile per invocation, so stale settings/timer files from a prior
    # trial cannot contaminate new A/B measurements. Keep the suffix intact.
    name = f"Perf-{spec['id'][:24]}-{run_tag[:14]}-{repetition}-{arm}"
    return LauncherConfig(
        game_exe=spec["game_exe"],
        base_userdir=spec["base_userdir"],
        profile_name=name,
        enabled_mod_paths=list(spec["mods"]),
        enable_plugins=arm == "candidate",
        enabled_plugin_ids=[spec["candidate_plugin_id"]] if arm == "candidate" else [],
        # Isolate saves by default; the shadercache can be reused to avoid unnecessary rebuilds.
        share_saves=False,
        share_shaders=True,
        additional_args=list(spec["game_arguments"]),
    )


def preview_trial(spec: dict) -> dict:
    exe = Path(spec["game_exe"]).resolve()
    if not exe.is_file():
        raise FileNotFoundError(f"Victoria 3 executable unavailable: {exe}")
    hash_value = file_sha256(exe)
    rows = []
    for repetition in range(1, spec["repetitions"] + 1):
        for arm in ("baseline", "candidate"):
            cfg = _cfg(spec, repetition, arm)
            # If we are compiling a new plugin, candidate won't exist yet.
            # For a dry run, validate the game/profile arguments but do not
            # pretend its future plugin is already built.
            if arm == "candidate" and "build" in spec:
                cfg = replace(cfg, enable_plugins=False, enabled_plugin_ids=[])
            plan = build_plan(cfg)
            if arm == "candidate" and "build" in spec:
                plan["enabled_plugins"] = [{"id": spec["candidate_plugin_id"],
                    "status": "TO_BUILD_AND_VALIDATE_BEFORE_LAUNCH"}]
            rows.append({"arm": arm, "repetition": repetition, "plan": plan})
    build = (preview_build(spec["build"], hash_value, spec["candidate_plugin_id"])
             if "build" in spec else None)
    return {"id": spec["id"], "game_exe_sha256": hash_value,
            "build": build, "arms": rows, "will_launch_now": False,
            "stops_if_other_game_exists": True,
            "original_mods_and_saves_unchanged": True,
            "game_launch_implementation": "v3nl.launcher.launch_game"}


def _days(profile: Path) -> dict[str, float]:
    days: dict[str, float] = {}
    for path in sorted((profile / "logs").glob("gametimer*.tsv")):
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
            by_day: dict[str, list[float]] = {}
            for raw in csv.DictReader(f, delimiter="\t"):
                row = {str(k).strip(): str(v).strip()
                       for k, v in raw.items() if k is not None and v is not None}
                if row.get("Time Unit") != "Day":
                    continue
                try:
                    by_day.setdefault(row["Game Date"], []).append(float(row["Seconds"]))
                except (KeyError, ValueError):
                    continue
            days.update({name: round(sum(values), 5)
                         for name, values in by_day.items() if len(values) == 4})
    return dict(sorted(days.items()))


def _wait_owned(pid: int, created: float, timeout: int,
                notify: Callable[[str], None]) -> int | None:
    process = psutil.Process(pid)
    if abs(process.create_time() - created) >= 2:
        raise RuntimeError("Game process identity changed; refusing to manage it.")
    try:
        return process.wait(timeout=timeout)
    except psutil.TimeoutExpired:
        if abs(process.create_time() - created) >= 2:
            raise RuntimeError("PID reuse after timeout; refusing termination.")
        notify(f"Test game exceeded {timeout}s; terminating only test-owned PID {pid}.")
        process.terminate()
        try:
            process.wait(timeout=15)
        except psutil.TimeoutExpired:
            if abs(process.create_time() - created) < 2:
                process.kill()
                process.wait(timeout=10)
        raise TimeoutError("Bounded game run exceeded timeout; no other processes affected.")


def execute_trial(spec: dict, notify: Callable[[str], None] = print) -> dict:
    """Run only following caller-supplied explicit --execute authorization."""
    plan = preview_trial(spec)
    if running_game_pids():
        raise RuntimeError("Another Victoria 3 session is active. No experiment started.")
    tag = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid.uuid4().hex[:8]
    root = local_data() / "experiments" / f"{spec['id']}_{tag}"
    root.mkdir(parents=True, exist_ok=False)
    _save(root / "spec.json", spec)
    _save(root / "validated_plan.json", plan)
    if "build" in spec:
        build = build_and_stage(spec["build"], plan["game_exe_sha256"],
                                spec["candidate_plugin_id"], root, notify)
        _save(root / "build_receipt.json", build)
    results: list[dict] = []
    for repetition in range(1, spec["repetitions"] + 1):
        for arm in ("baseline", "candidate"):
            if running_game_pids():
                raise RuntimeError("Another Victoria 3 session is active; refusing next trial.")
            cfg = _cfg(spec, repetition, arm, run_tag=tag[-14:])
            # Force the candidate's exact DLL, export and executable hash check
            # through the same validation path used by UI launches.
            checked = build_plan(cfg)
            receipt = {
                "arm": arm, "repetition": repetition,
                "plugin_ids": [p["id"] for p in checked["enabled_plugins"]],
                "game_exe_sha256": checked["executable_sha256"],
                "profile": checked["game_userdir"],
                "status": "STARTING",
            }
            target = root / f"{repetition}_{arm}.json"
            _save(target, receipt)
            try:
                notify(f"Launcher: starting {arm} run {repetition}/{spec['repetitions']}.")
                launched = launch_game(cfg, notify)
                receipt.update(pid=launched.process_id,
                    session_manifest=str(launched.session_file),
                    loaded_plugins=launched.loaded_plugins,
                    injection_errors=launched.errors,
                    status="RUNNING")
                _save(target, receipt)
                if launched.errors or (arm == "candidate" and
                                       spec["candidate_plugin_id"] not in launched.loaded_plugins):
                    raise RuntimeError("Native plugin initialization failed; see session manifest.")
                result_code = _wait_owned(launched.process_id, launched.created_epoch,
                                          spec["timeout_seconds"], notify)
                values = _days(launched.profile)
                receipt.update(status="COMPLETE" if (result_code in (None, 0) and
                    len(values) >= spec["min_complete_days"]) else "INVALID",
                    exit_code=result_code, days=values,
                    n_complete_days=len(values),
                    median_seconds_per_day=(round(statistics.median(values.values()), 4)
                                            if values else None))
                if receipt["status"] != "COMPLETE":
                    raise RuntimeError(
                        f"{arm} did not complete valid simulation: exit={result_code}, days={len(values)}")
                results.append(receipt)
                notify(f"Completed {arm}: {len(values)} days, median "
                       f"{receipt['median_seconds_per_day']}s/day.")
            except Exception as exc:
                receipt.update(status="FAILED", failure=str(exc))
                raise
            finally:
                _save(target, receipt)
    baseline = [x for x in results if x["arm"] == "baseline"]
    candidate = [x for x in results if x["arm"] == "candidate"]
    pairs = []
    for old, new in zip(baseline, candidate):
        dates = sorted(set(old["days"]) & set(new["days"]))
        if len(dates) < spec["min_complete_days"]:
            raise RuntimeError("Baseline/candidate have too few matched simulation days.")
        a = [old["days"][date] for date in dates]
        b = [new["days"][date] for date in dates]
        pairs.append({
            "repetition": old["repetition"], "matched_days": len(dates),
            "dates": [dates[0], dates[-1]],
            "baseline_median_s": round(statistics.median(a), 4),
            "candidate_median_s": round(statistics.median(b), 4),
            "baseline_sum_s": round(sum(a), 4),
            "candidate_sum_s": round(sum(b), 4),
            "ratio_candidate_to_baseline": round(sum(b)/sum(a), 4) if sum(a) else None
        })
    outcome = {"status": "COMPLETED", "id": spec["id"],
               "game_exe_sha256": plan["game_exe_sha256"],
               "runs": results, "matched_comparisons": pairs,
               "limitations": [
                   "Observed timer differences are not causal proof of optimization.",
                   "Run comparisons require workload parity and machine-load controls.",
                   "Save/world-state parity remains a separate acceptance gate."
               ]}
    _save(root / "result.json", outcome)
    notify(f"Trial evidence saved: {root}")
    return outcome
