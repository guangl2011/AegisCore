"""Import-graph gate tests: the decoupling invariants, both directions of proof.

The gate script itself is CI's enforcement point; these tests verify it
detects what it must (direct, transitive, runtime-import violations) and
stays silent on a clean tree — including the real one.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_import_graph.py"


def load_gate() -> object:
    spec = importlib.util.spec_from_file_location("check_import_graph_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_tree(root: Path, files: dict[str, str]) -> Path:
    src = root / "aegiscore"
    for rel, content in files.items():
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return src


def test_real_tree_is_clean() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_direct_core_import_of_advisory_is_a_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gate = load_gate()
    src = build_tree(
        tmp_path,
        {
            "__init__.py": "",
            "advisory/__init__.py": "",
            "governor/__init__.py": "from aegiscore.advisory import AdvisoryConstraint\n",
        },
    )
    monkeypatch.setattr(gate, "SRC_ROOT", src)
    assert gate.main() == 1
    assert "aegiscore.advisory" in capsys.readouterr().err


def test_transitive_core_import_of_advisory_is_a_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gate = load_gate()
    src = build_tree(
        tmp_path,
        {
            "__init__.py": "",
            "advisory/__init__.py": "",
            "core/__init__.py": "from aegiscore.advisory import AdvisoryConstraint\n",
            "governor/__init__.py": "from aegiscore.core import GovernorConfig\n",
        },
    )
    monkeypatch.setattr(gate, "SRC_ROOT", src)
    assert gate.main() == 1
    captured = capsys.readouterr().err
    assert "transitive" in captured


def test_runtime_import_outside_advisory_is_a_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gate = load_gate()
    src = build_tree(
        tmp_path,
        {
            "__init__.py": "",
            "advisory/__init__.py": "",
            "governor/__init__.py": "",
            "governor/loop.py": "import onnxruntime\n",
        },
    )
    monkeypatch.setattr(gate, "SRC_ROOT", src)
    assert gate.main() == 1
    assert "onnxruntime" in capsys.readouterr().err


def test_runtime_import_inside_advisory_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gate = load_gate()
    src = build_tree(
        tmp_path,
        {
            "__init__.py": "",
            "advisory/__init__.py": "import onnxruntime\n",
            "governor/__init__.py": "",
        },
    )
    monkeypatch.setattr(gate, "SRC_ROOT", src)
    assert gate.main() == 0
    assert capsys.readouterr().err == ""
