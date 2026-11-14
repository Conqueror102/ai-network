"""Doc 11 §3: a module may import another module only through its `public.py`."""

import ast
from pathlib import Path

MODULES = Path(__file__).resolve().parents[2] / "app" / "modules"


def _violations() -> list[str]:
    out = []
    for path in MODULES.rglob("*.py"):
        owner = path.relative_to(MODULES).parts[0]
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                parts = name.split(".")
                if parts[:2] != ["app", "modules"] or len(parts) < 3 or parts[2] == owner:
                    continue
                if len(parts) == 3 or parts[3] != "public":
                    if len(parts) == 3 and isinstance(node, ast.ImportFrom) and all(
                            a.name == "public" for a in node.names):
                        continue
                    out.append(f"{path.relative_to(MODULES)} imports {name}")
    return sorted(set(out))


def test_modules_only_import_each_others_public_api():
    assert _violations() == []
