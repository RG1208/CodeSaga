"""Regression test: parsing many real source files must not crash the interpreter.

tree-sitter 0.26.0 segfaulted (a native crash that would take down the API process)
while analyzing larger files; 0.25.2 is pinned. The workload runs in a subprocess so
a crash fails this test instead of killing the test run.
"""

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

SCRIPT = """
from pathlib import Path
from app.analysis.registry import default_registry

registry = default_registry()
files = sorted(p for p in Path("app").rglob("*.py")) + sorted(Path("tests").rglob("*.py"))
fixtures = sorted(p for p in Path("tests/fixtures").rglob("*") if p.is_file())
analyzed = 0
for _ in range(3):
    for path in files + fixtures:
        analyzer = registry.analyzer_for(str(path))
        if analyzer is not None:
            analyzer.analyze(path.read_bytes(), str(path))
            analyzed += 1
# A large synthetic file exercises deep node traversal.
template = "def f{i}(a: int, b=1, *args, c: str = 'x', **kw) -> int:\\n    return g(a)\\n"
big = "".join(template.format(i=i) for i in range(3000))
registry.analyzer_for("big.py").analyze(big.encode(), "big.py")
print("analyzed", analyzed)
"""


def test_parsing_real_files_repeatedly_does_not_crash() -> None:
    completed = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", SCRIPT],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert completed.returncode == 0, completed.stderr[-2000:]
    assert completed.stdout.startswith("analyzed")
