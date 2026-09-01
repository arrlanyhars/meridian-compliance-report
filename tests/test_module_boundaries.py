"""
Constraint 3, the structural half. Static, not a convention: this walks the
actual AST of every file under src/meridian/compute/ and src/meridian/graph/
and fails the build if any of them imports narrative/ or an LLM SDK, so the
guarantee "the LLM cannot be in the number-producing path" survives a future
change rather than resting on someone remembering the rule.
"""

import ast
from pathlib import Path

FORBIDDEN_MODULE_PREFIXES = ("meridian.narrative", "google.genai", "google.generativeai")
CHECKED_PACKAGES = ("compute", "graph")

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "meridian"


def _imported_module_names(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_compute_and_graph_never_import_narrative_or_an_llm_sdk():
    violations: list[str] = []
    for package in CHECKED_PACKAGES:
        for py_file in (SRC_ROOT / package).rglob("*.py"):
            for module_name in _imported_module_names(py_file):
                if any(module_name == prefix or module_name.startswith(prefix + ".") for prefix in FORBIDDEN_MODULE_PREFIXES):
                    violations.append(f"{py_file.relative_to(SRC_ROOT.parent)} imports {module_name!r}")

    assert not violations, "the number-producing layer must never import the narrative layer:\n" + "\n".join(violations)
