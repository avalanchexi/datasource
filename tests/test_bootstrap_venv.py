import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional


def _write_bootstrap(root: Path) -> None:
    scripts = root / "scripts"
    scripts.mkdir(exist_ok=True)
    source = Path("scripts/bootstrap_venv.sh")
    assert source.exists(), "scripts/bootstrap_venv.sh must exist"
    body = source.read_text(encoding="utf-8").replace("\r\n", "\n")
    target = scripts / "bootstrap_venv.sh"
    target.write_bytes(body.replace("\r", "\n").encode("utf-8"))
    target.chmod(0o755)


def _write_fake_python(root: Path, *, fail_pip: bool = False) -> Path:
    fake_bin = root / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    log_path = root / "fake-python.log"
    script = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"LOG={shlex.quote(str(log_path))}\n"
        "printf '%s\\n' \"$*\" >> \"$LOG\"\n"
        "if [ \"${DATASOURCE_BOOTSTRAP_ENV_LOADED:-}\" = \"1\" ]; then\n"
        "  printf 'env-loaded\\n' >> \"$LOG\"\n"
        "fi\n"
        "if [ \"${1:-}\" = \"--version\" ]; then\n"
        "  printf 'Python 3.11.0\\n'\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"${1:-}\" = \"-m\" ] && [ \"${2:-}\" = \"venv\" ]; then\n"
        "  venv_dir=\"${3:-.venv}\"\n"
        "  mkdir -p \"$venv_dir/bin\"\n"
        "  cat > \"$venv_dir/bin/python\" <<'PY'\n"
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [ \"${1:-}\" = \"--version\" ]; then\n"
        "  printf 'Python 3.11.0\\n'\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"${1:-}\" = \"-m\" ] && [ \"${2:-}\" = \"pip\" ]; then\n"
        f"  {'exit 23' if fail_pip else 'exit 0'}\n"
        "fi\n"
        "printf 'fake-venv-python\\n'\n"
        "PY\n"
        "  chmod +x \"$venv_dir/bin/python\"\n"
        "  cat > \"$venv_dir/bin/activate\" <<'ACT'\n"
        "export VIRTUAL_ENV=\"$PWD/.venv\"\n"
        "ACT\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    python = fake_bin / "python3"
    python.write_text(script, encoding="utf-8")
    python.chmod(0o755)
    return fake_bin


def _write_existing_venv_python(root: Path) -> Path:
    python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"${1:-}\" = \"--version\" ]; then\n"
        "  printf 'Python 3.11.0\\n'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    return python


def _run_bootstrap(
    root: Path,
    *args: str,
    env: Optional[dict] = None,
    path_prefix: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    merged.update(env or {})
    if path_prefix is not None:
        merged["PATH"] = f"{path_prefix}{os.pathsep}{merged.get('PATH', '')}"
    return subprocess.run(
        ["bash", "scripts/bootstrap_venv.sh", *args],
        cwd=root,
        env=merged,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def test_bootstrap_no_install_creates_usable_venv_and_does_not_load_env(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_bootstrap(root)
    (root / ".env").write_text(
        "DATASOURCE_BOOTSTRAP_ENV_LOADED=1\n",
        encoding="utf-8",
    )
    fake_python = _write_fake_python(root)

    result = _run_bootstrap(root, "--no-install", path_prefix=fake_python)

    assert result.returncode == 0, result.stdout
    assert "[OK] .venv bootstrap complete" in result.stdout
    assert (root / ".venv" / "bin" / "python").is_file()
    assert os.access(root / ".venv" / "bin" / "python", os.X_OK)
    assert (root / ".venv" / "bin" / "activate").is_file()
    stamp = root / ".venv" / ".datasource_bootstrapped"
    assert stamp.is_file()
    assert "python_version=Python 3.11.0" in stamp.read_text(encoding="utf-8")
    assert not (root / ".venv" / ".datasource_bootstrap_failed").exists()
    log_text = (root / "fake-python.log").read_text(encoding="utf-8")
    assert "-m venv .venv" in log_text
    assert "env-loaded" not in log_text


def test_bootstrap_failed_normal_install_writes_failed_stamp(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_bootstrap(root)
    (root / "setup.py").write_text("from setuptools import setup\nsetup()\n", encoding="utf-8")
    fake_python = _write_fake_python(root, fail_pip=True)

    result = _run_bootstrap(root, path_prefix=fake_python)

    assert result.returncode != 0
    assert "bootstrap failed" in result.stdout
    failed = root / ".venv" / ".datasource_bootstrap_failed"
    assert failed.is_file()
    assert "timestamp=" in failed.read_text(encoding="utf-8")
    assert not (root / ".venv" / ".datasource_bootstrapped").exists()


def test_bootstrap_existing_venv_python_without_activate_hard_fails(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_bootstrap(root)
    _write_existing_venv_python(root)

    result = _run_bootstrap(root, "--no-install")

    assert result.returncode != 0
    assert "bootstrap failed" in result.stdout
    assert "activate" in result.stdout
    failed = root / ".venv" / ".datasource_bootstrap_failed"
    assert failed.is_file()
    failed_text = failed.read_text(encoding="utf-8")
    assert "timestamp=" in failed_text
    assert "activate" in failed_text
    assert not (root / ".venv" / ".datasource_bootstrapped").exists()
