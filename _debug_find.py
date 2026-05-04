import tempfile, subprocess
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
repo = tmp / "test_repo"
repo.mkdir()
subprocess.run(["git", "init", "-q", str(repo)], check=True)
subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@test.com"], check=True)
subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
(repo / "src").mkdir()
(repo / "src" / "a.py").write_text("def add(a,b): return a-b\n")
(repo / "tests").mkdir()
(repo / "tests" / "test_a.py").write_text("import pytest\n")
subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)

from taskprep.git_ops import _is_test_path, _git as gops_git

main_files = ["src/a.py"]
search_roots = set()
for mf in main_files:
    p = Path(mf)
    parent_dir = repo / p.parent
    search_roots.add(parent_dir)
    search_roots.add(parent_dir / "tests")
    search_roots.add(parent_dir / "__tests__")
    if p.parent.parent != Path():
        search_roots.add(repo / p.parent.parent)
        search_roots.add(repo / p.parent.parent / "tests")
        search_roots.add(repo / p.parent.parent / "__tests__")

print("Search roots:")
for r in search_roots:
    print(f"  {r} exists={r.exists()}")

candidates = set()
for root in search_roots:
    if not root.exists():
        continue
    for entry in root.rglob("*"):
        if entry.is_file():
            rel = str(entry.relative_to(repo)).replace("\\", "/")
            if _is_test_path(rel):
                candidates.add(rel)
print("Candidates:", candidates)

scored = []
for c in candidates:
    try:
        ts = gops_git(repo, "log", "-1", "--format=%ct", "HEAD", "--", c)
        print(f"  {c}: git log OK, ts={ts!r}")
        scored.append((int(ts.strip() or "0"), c))
    except subprocess.CalledProcessError as e:
        print(f"  {c}: git log FAILED, stderr={e.stderr!r}")
        scored.append((0, c))

print("Scored:", scored)
