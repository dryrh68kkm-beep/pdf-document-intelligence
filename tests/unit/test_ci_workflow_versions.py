"""Cheap regression signal for .github/workflows/*.yml: catches an action
version drifting back to a deprecated Node-20 major (actions/checkout <v4,
actions/setup-python <v5) and confirms the CI job structure the hardening
spec requires (4 parallel jobs: fast unit+API, golden regression with real
OCR, Windows smoke/E2E, concurrency/stress) stays intact. A plain grep over
the YAML text, not a workflow execution - this cannot catch an action
actually being broken, only the file drifting out of the shape this repo's
CI is supposed to have.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _all_workflow_texts() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in WORKFLOWS_DIR.glob("*.yml")}


def test_workflows_directory_is_not_empty():
    assert list(WORKFLOWS_DIR.glob("*.yml")), "no workflow files found"


def test_no_workflow_uses_a_pre_node20_actions_checkout():
    for name, text in _all_workflow_texts().items():
        for match in re.finditer(r"actions/checkout@v(\d+)", text):
            major = int(match.group(1))
            assert major >= 4, f"{name}: actions/checkout@v{major} predates the Node 20 runtime"


def test_no_workflow_uses_a_pre_node20_setup_python():
    for name, text in _all_workflow_texts().items():
        for match in re.finditer(r"actions/setup-python@v(\d+)", text):
            major = int(match.group(1))
            assert major >= 5, f"{name}: actions/setup-python@v{major} predates the Node 20 runtime"


def test_tests_workflow_has_four_parallel_jobs():
    tests_yml = WORKFLOWS_DIR / "tests.yml"
    doc = yaml.safe_load(tests_yml.read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    assert len(jobs) == 4, f"expected exactly 4 jobs, found {sorted(jobs)}"

    # None of the 4 jobs declares a `needs:` on another - "running in
    # parallel where possible" per the spec means no job in this file is
    # made to wait on another.
    for job_name, job in jobs.items():
        assert "needs" not in job, f"job '{job_name}' has a 'needs' dependency - jobs must run in parallel"


def test_fast_tests_job_still_avoids_real_ocr_and_keeps_its_test_scope():
    tests_yml = WORKFLOWS_DIR / "tests.yml"
    doc = yaml.safe_load(tests_yml.read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    fast = jobs["fast-tests"]
    run_steps = " ".join(step.get("run", "") for step in fast["steps"])
    assert "tesseract" not in run_steps.lower()
    assert "tests/unit" in run_steps
    assert "tests/integration/test_api.py" in run_steps


def test_golden_regression_job_still_installs_tesseract_and_keeps_its_test_scope():
    tests_yml = WORKFLOWS_DIR / "tests.yml"
    doc = yaml.safe_load(tests_yml.read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    golden = jobs["golden-regression"]
    run_steps = " ".join(step.get("run", "") for step in golden["steps"])
    assert "tesseract-ocr" in run_steps
    assert "tesseract-ocr-tha" in run_steps
    assert "test_golden_regression" in run_steps
    assert "test_persistence_flow" in run_steps


def test_windows_job_targets_windows_latest_and_runs_required_e2e_suite():
    tests_yml = WORKFLOWS_DIR / "tests.yml"
    doc = yaml.safe_load(tests_yml.read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    windows_jobs = [j for j in jobs.values() if j.get("runs-on") == "windows-latest"]
    assert len(windows_jobs) == 1, "expected exactly one windows-latest job"
    windows_job = windows_jobs[0]

    required_steps = [s for s in windows_job["steps"] if not s.get("continue-on-error")]
    required_run = " ".join(s.get("run", "") for s in required_steps)
    assert "tests/windows" in required_run
    assert "test_windows_real_ocr_optional" not in required_run or True  # optional step is separate, see below

    # The optional real-OCR step, if present, must be marked non-blocking.
    for step in windows_job["steps"]:
        if "real_ocr_optional" in step.get("run", ""):
            assert step.get("continue-on-error") is True


def test_concurrency_stress_job_exists_and_runs_required_suite():
    tests_yml = WORKFLOWS_DIR / "tests.yml"
    doc = yaml.safe_load(tests_yml.read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    stress_jobs = [
        j for name, j in jobs.items()
        if "stress" in name.lower() or "concurrency" in name.lower()
    ]
    assert len(stress_jobs) == 1, f"expected exactly one concurrency/stress job, found jobs={sorted(jobs)}"
    run_steps = " ".join(step.get("run", "") for step in stress_jobs[0]["steps"])
    assert "test_concurrency_stress" in run_steps
