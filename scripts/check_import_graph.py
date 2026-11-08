#!/usr/bin/env python3
"""CI import-graph gate for the advisory-layer locked invariants.

Statically checks ``src/aegiscore`` for two spec invariants (Nov 2026
OpenVINO design update):

1. **Decoupled cores.** No module of the deterministic cores — governor, SCAL,
   gateway — may reach ``aegiscore.advisory``, directly or through transitive
   local imports. The governor defines its own consumption of advisory
   constraints (structural, no package dependency).
2. **No stray inference runtimes.** physicalai, openvino, and onnxruntime may
   be imported only inside ``aegiscore.advisory`` — the deterministic cores
   gain no third-party inference dependencies.

Exit 0 silent when clean; exit 1 with a violation list otherwise.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "aegiscore"
ADVISORY_ROOT = "aegiscore.advisory"
PROTECTED_ROOTS = ("aegiscore.governor", "aegiscore.scal", "aegiscore.gateway")
INFERENCE_RUNTIMES = ("physicalai", "openvino", "onnxruntime")


def module_name(path: Path) -> str:
    rel = path.relative_to(SRC_ROOT.parent)
    if rel.name == "__init__.py":
        rel = rel.parent
    else:
        rel = rel.with_suffix("")
    return ".".join(rel.parts)


def resolve_local(target: str) -> str | None:
    """Map an imported aegiscore name to the longest existing module path."""
    if target == "aegiscore":
        return target
    rest = target.split(".")[1:]  # drop the leading "aegiscore"
    while rest:
        candidate = SRC_ROOT.joinpath(*rest)
        if candidate.with_suffix(".py").is_file() or (candidate / "__init__.py").is_file():
            return ".".join(["aegiscore", *rest])
        rest.pop()
    return None


def local_imports(path: Path) -> set[str]:
    """Return aegiscore.* modules imported by the file at *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "aegiscore" or alias.name.startswith("aegiscore."):
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # Relative import: resolve against the current package.
                base = module_name(path).split(".")
                if path.name != "__init__.py":
                    base = base[:-1]
                for _ in range(node.level - 1):
                    base.pop()
                target = ".".join([*base, node.module or ""]).strip(".")
            else:
                target = node.module or ""
            if target and (target == "aegiscore" or target.startswith("aegiscore.")):
                found.add(target)
    return {resolved for raw in found if (resolved := resolve_local(raw))}


def is_advisory(module: str) -> bool:
    return module == ADVISORY_ROOT or module.startswith(ADVISORY_ROOT + ".")


def main() -> int:
    files = sorted(SRC_ROOT.rglob("*.py"))
    imports_by_module: dict[str, set[str]] = {}
    for path in files:
        imports_by_module[module_name(path)] = local_imports(path)

    violations: list[str] = []

    # Invariant 1: protected cores must not reach the advisory package, even
    # transitively (a core importing aegiscore.core which imported advisory
    # would be the same violation one hop removed).
    for module, deps in imports_by_module.items():
        if not any(module == root or module.startswith(root + ".") for root in PROTECTED_ROOTS):
            continue
        seen: set[str] = set()
        stack = list(deps)
        while stack:
            dep = stack.pop()
            if dep in seen:
                continue
            seen.add(dep)
            if is_advisory(dep):
                violations.append(
                    f"core module {module} reaches {dep} (transitive local imports)"
                )
                break
            stack.extend(imports_by_module.get(dep, ()))

    # Invariant 2: inference runtimes only inside aegiscore.advisory.
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            roots: set[str] = set()
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                roots = {node.module.split(".")[0]}
            for root in roots & set(INFERENCE_RUNTIMES):
                if not is_advisory(module_name(path)):
                    violations.append(
                        f"{path}: imports {root} — inference runtimes are allowed "
                        "only inside aegiscore.advisory"
                    )

    for violation in sorted(set(violations)):
        print(f"IMPORT GRAPH VIOLATION: {violation}", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
