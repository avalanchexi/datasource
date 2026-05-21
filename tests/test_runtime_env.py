import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional


def _write_runtime(root: Path) -> None:
    scripts = root / "scripts"
    scripts.mkdir(exist_ok=True)
    source = Path("scripts/runtime_env.sh")
    if source.exists():
        body = source.read_text(encoding="utf-8").replace("\r\n", "\n")
    else:
        body = "#!/usr/bin/env bash\nreturn 1\n"
    (scripts / "runtime_env.sh").write_bytes(body.replace("\r", "\n").encode("utf-8"))


def _write_env(root: Path) -> None:
    (root / ".env").write_text(
        "TUSHARE_TOKEN=xxxxxxxxxxxxxxxxxxxx\n"
        "TAVILY_API_KEY=yyyyyyyyyyyyyyyyyyyy\n"
        "DEEPSEEK_API_KEY=zzzzzzzzzzzzzzzzzzzz\n"
        "PYTHONPATH=custom_path\n",
        encoding="utf-8",
    )


def _write_fake_uname(root: Path, system_name: str) -> Path:
    fake_bin = root / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    (fake_bin / "uname").write_bytes(
        (
            "#!/usr/bin/env bash\n"
            "if [ \"${1:-}\" = \"-s\" ]; then\n"
            f"  printf '%s\\n' {shlex.quote(system_name)}\n"
            "else\n"
            f"  printf '%s\\n' {shlex.quote(system_name)}\n"
            "fi\n"
        ).encode("utf-8")
    )
    (fake_bin / "uname").chmod(0o755)
    return fake_bin


def _write_fake_python(root: Path, name: str = "python3") -> Path:
    fake_bin = root / "py-bin"
    fake_bin.mkdir(exist_ok=True)
    (fake_bin / name).write_bytes(b"#!/usr/bin/env bash\nprintf 'fake-python\\n'\n")
    (fake_bin / name).chmod(0o755)
    return fake_bin


def _write_fake_venv_python(root: Path, *, windows: bool = False) -> Path:
    if windows:
        python_path = root / ".venv" / "Scripts" / "python.exe"
    else:
        python_path = root / ".venv" / "bin" / "python"
    python_path.write_bytes(b"#!/usr/bin/env bash\nprintf 'fake-venv-python\\n'\n")
    python_path.chmod(0o755)
    return python_path


def _write_fake_bootstrap(root: Path) -> Path:
    scripts = root / "scripts"
    scripts.mkdir(exist_ok=True)
    log_path = root / "bootstrap.log"
    script = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"printf 'called\\n' >> {shlex.quote(str(log_path))}\n"
        "mkdir -p .venv/bin\n"
        "cat > .venv/bin/activate <<'ACT'\n"
        "export RUNTIME_ACTIVATE=bootstrapped\n"
        "ACT\n"
        "cat > .venv/bin/python <<'PY'\n"
        "#!/usr/bin/env bash\n"
        "printf 'fake-bootstrapped-python\\n'\n"
        "PY\n"
        "chmod +x .venv/bin/python\n"
        "printf '[OK] fake bootstrap complete\\n'\n"
    )
    bootstrap = scripts / "bootstrap_venv.sh"
    bootstrap.write_text(script, encoding="utf-8")
    bootstrap.chmod(0o755)
    return bootstrap


def _bash_path(path: str, *, root: Optional[Path] = None) -> str:
    if root is not None:
        try:
            relative = Path(path).resolve().relative_to(root.resolve())
            return f"./{relative.as_posix()}"
        except ValueError:
            pass
    text = str(path)
    if len(text) > 2 and text[1] == ":":
        return f"/mnt/{text[0].lower()}{text[2:].replace(chr(92), '/')}"
    return text


def _run_source(
    root: Path,
    script: str,
    *,
    env: Optional[dict] = None,
    path_prefix: Optional[str] = None,
    pre_source: str = "",
) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    merged.pop("ALLOW_SYSTEM_PYTHON", None)
    merged.update(env or {})
    env_exports = ""
    for key, value in (env or {}).items():
        env_exports += f"export {key}={shlex.quote(str(value))}; "
    command = (
        "set -euo pipefail; "
        f"{env_exports}"
        f"{pre_source}"
        "source scripts/runtime_env.sh; "
        f"{script}"
    )
    if path_prefix:
        quoted_prefix = shlex.quote(_bash_path(path_prefix, root=root))
        command = (
            f"_path_prefix={quoted_prefix}; "
            "PATH=\"$_path_prefix:$PATH\"; export PATH; "
            f"{command}"
        )
    return subprocess.run(
        ["bash"],
        cwd=root,
        env=merged,
        input=command,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def test_runtime_env_missing_env_fails(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)

    result = _run_source(root, "printf 'should-not-run\\n'", env={"ALLOW_SYSTEM_PYTHON": "1"})

    assert result.returncode != 0
    assert "Missing .env" in result.stdout
    assert "should-not-run" not in result.stdout


def test_runtime_env_uses_linux_venv_first(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "activate").write_text(
        "export RUNTIME_ACTIVATE=linux\n",
        encoding="utf-8",
    )
    _write_fake_venv_python(root)

    result = _run_source(root, "printf '%s\\n' \"$RUNTIME_ACTIVATE\"")

    assert result.returncode == 0, result.stdout
    assert result.stdout.strip().splitlines()[-1] == "linux"


def test_runtime_env_venv_python_ignores_env_file_override(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    with (root / ".env").open("a", encoding="utf-8") as handle:
        handle.write("DATASOURCE_PYTHON=bad-python\n")
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "activate").write_text(
        "export RUNTIME_ACTIVATE=linux\n",
        encoding="utf-8",
    )
    venv_python = _write_fake_venv_python(root)

    result = _run_source(root, "printf '%s\\n' \"$DATASOURCE_PYTHON\"")

    assert result.returncode == 0, result.stdout
    assert result.stdout.strip().splitlines()[-1] == _bash_path(str(venv_python))


def test_runtime_env_venv_python_ignores_caller_override(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "activate").write_text(
        "export RUNTIME_ACTIVATE=linux\n",
        encoding="utf-8",
    )
    venv_python = _write_fake_venv_python(root)

    result = _run_source(
        root,
        "printf '%s\\n' \"$DATASOURCE_PYTHON\"",
        env={"DATASOURCE_PYTHON": "bad-python"},
    )

    assert result.returncode == 0, result.stdout
    assert result.stdout.strip().splitlines()[-1] == _bash_path(str(venv_python))


def test_runtime_env_uses_windows_venv_only_on_windows_bash(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    fake_uname = _write_fake_uname(root, "MINGW64_NT-10.0")
    scripts_dir = root / ".venv" / "Scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "activate").write_text(
        "export RUNTIME_ACTIVATE=windows\n",
        encoding="utf-8",
    )
    _write_fake_venv_python(root, windows=True)

    result = _run_source(
        root,
        "printf '%s\\n' \"$RUNTIME_ACTIVATE\"",
        path_prefix=str(fake_uname),
    )

    assert result.returncode == 0, result.stdout
    assert result.stdout.strip().splitlines()[-1] == "windows"


def test_runtime_env_does_not_use_windows_venv_on_linux(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    fake_uname = _write_fake_uname(root, "Linux")
    scripts_dir = root / ".venv" / "Scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "activate").write_text(
        "export RUNTIME_ACTIVATE=windows\n",
        encoding="utf-8",
    )

    result = _run_source(
        root,
        "printf '%s\\n' \"${RUNTIME_ACTIVATE:-not-activated}\"",
        path_prefix=str(fake_uname),
    )

    assert result.returncode != 0
    assert ".venv exists but no usable activate script found" in result.stdout
    assert "windows" not in result.stdout
    assert "not-activated" not in result.stdout


def test_runtime_env_windows_venv_on_linux_hard_fails_even_with_fallback(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    fake_uname = _write_fake_uname(root, "Linux")
    scripts_dir = root / ".venv" / "Scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "activate").write_text(
        "export RUNTIME_ACTIVATE=windows\n",
        encoding="utf-8",
    )

    result = _run_source(
        root,
        "printf '%s\\n' \"${RUNTIME_ACTIVATE:-not-activated}\"",
        env={"ALLOW_SYSTEM_PYTHON": "1"},
        path_prefix=str(fake_uname),
    )

    assert result.returncode != 0
    assert ".venv exists but no usable activate script found" in result.stdout
    assert "using current system Python" not in result.stdout
    assert "windows" not in result.stdout
    assert "not-activated" not in result.stdout


def test_runtime_env_empty_venv_allows_explicit_system_fallback(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    (root / ".venv").mkdir()
    fake_python = _write_fake_python(root, "python3")

    result = _run_source(
        root,
        "printf '%s\\n' \"$DATASOURCE_PYTHON\"",
        env={"ALLOW_SYSTEM_PYTHON": "1"},
        path_prefix=str(fake_python),
    )

    assert result.returncode == 0, result.stdout
    assert "using current system Python because ALLOW_SYSTEM_PYTHON=1" in result.stdout
    assert result.stdout.strip().splitlines()[-1] == "python3"


def test_runtime_env_empty_venv_auto_bootstraps_when_enabled(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    (root / ".venv").mkdir()
    _write_fake_bootstrap(root)
    venv_python = root / ".venv" / "bin" / "python"

    result = _run_source(
        root,
        "printf '%s|%s\\n' \"$RUNTIME_ACTIVATE\" \"$DATASOURCE_PYTHON\"",
        env={"DATASOURCE_AUTO_VENV": "1"},
    )

    assert result.returncode == 0, result.stdout
    assert "[OK] fake bootstrap complete" in result.stdout
    assert (root / "bootstrap.log").read_text(encoding="utf-8") == "called\n"
    assert result.stdout.strip().splitlines()[-1] == (
        f"bootstrapped|{_bash_path(str(venv_python))}"
    )


def test_runtime_env_empty_venv_without_auto_still_requires_fallback(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    (root / ".venv").mkdir()
    _write_fake_bootstrap(root)

    result = _run_source(root, "printf 'should-not-run\\n'")

    assert result.returncode != 0
    assert "Missing virtual environment" in result.stdout
    assert "DATASOURCE_AUTO_VENV=1" in result.stdout
    assert "should-not-run" not in result.stdout
    assert not (root / "bootstrap.log").exists()


def test_runtime_env_venv_activate_without_python_is_hard_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "activate").write_text(
        "export RUNTIME_ACTIVATE=linux\n",
        encoding="utf-8",
    )

    result = _run_source(
        root,
        "printf 'should-not-run\\n'",
        env={"ALLOW_SYSTEM_PYTHON": "1"},
    )

    assert result.returncode != 0
    assert ".venv exists but no usable Python interpreter found" in result.stdout
    assert "using current system Python" not in result.stdout
    assert "should-not-run" not in result.stdout


def test_runtime_env_system_fallback_prefers_python3_and_sets_pythonpath(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    fake_python = _write_fake_python(root, "python3")

    result = _run_source(
        root,
        "printf '%s|%s\\n' \"$DATASOURCE_PYTHON\" \"$PYTHONPATH\"",
        env={"ALLOW_SYSTEM_PYTHON": "1"},
        path_prefix=str(fake_python),
    )

    assert result.returncode == 0, result.stdout
    last = result.stdout.strip().splitlines()[-1]
    assert last.startswith("python3|")
    assert "./src" in last
    assert "custom_path" in last


def test_runtime_env_system_python_ignores_caller_override(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    fake_python = _write_fake_python(root, "python3")

    result = _run_source(
        root,
        "printf '%s\\n' \"$DATASOURCE_PYTHON\"",
        env={"ALLOW_SYSTEM_PYTHON": "1", "DATASOURCE_PYTHON": "bad-python"},
        path_prefix=str(fake_python),
    )

    assert result.returncode == 0, result.stdout
    assert result.stdout.strip().splitlines()[-1] == "python3"


def test_runtime_env_system_python_ignores_env_file_override(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    with (root / ".env").open("a", encoding="utf-8") as handle:
        handle.write("DATASOURCE_PYTHON=bad-python\n")
    fake_python = _write_fake_python(root, "python3")

    result = _run_source(
        root,
        "printf '%s\\n' \"$DATASOURCE_PYTHON\"",
        env={"ALLOW_SYSTEM_PYTHON": "1"},
        path_prefix=str(fake_python),
    )

    assert result.returncode == 0, result.stdout
    assert result.stdout.strip().splitlines()[-1] == "python3"


def test_runtime_env_clears_active_proxies_and_keeps_no_proxy(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    fake_python = _write_fake_python(root, "python3")

    result = _run_source(
        root,
        "printf '%s|%s|%s\\n' \"${http_proxy:-}\" \"${HTTPS_PROXY:-}\" \"${NO_PROXY:-}\"",
        env={
            "ALLOW_SYSTEM_PYTHON": "1",
            "http_proxy": "http://proxy.local:8080",
            "HTTPS_PROXY": "http://secure-proxy.local:8080",
            "NO_PROXY": "localhost,127.0.0.1",
        },
        path_prefix=str(fake_python),
    )

    assert result.returncode == 0, result.stdout
    assert result.stdout.strip().splitlines()[-1] == "||localhost,127.0.0.1"


def test_runtime_env_exports_runtime_dir(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    fake_python = _write_fake_python(root, "python3")

    result = _run_source(
        root,
        "printf '%s\\n' \"$DATASOURCE_RUNTIME_DIR\"",
        env={"ALLOW_SYSTEM_PYTHON": "1"},
        path_prefix=str(fake_python),
    )

    assert result.returncode == 0, result.stdout
    assert result.stdout.strip().splitlines()[-1] == _bash_path(str(root))


def test_runtime_env_preserves_existing_allexport_state(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)
    fake_python = _write_fake_python(root, "python3")

    result = _run_source(
        root,
        "case \"$-\" in *a*) printf 'allexport-on\\n' ;; *) printf 'allexport-off\\n' ;; esac",
        env={"ALLOW_SYSTEM_PYTHON": "1"},
        path_prefix=str(fake_python),
        pre_source="set -a; ",
    )

    assert result.returncode == 0, result.stdout
    assert result.stdout.strip().splitlines()[-1] == "allexport-on"


def test_runtime_env_without_venv_requires_explicit_fallback(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_runtime(root)
    _write_env(root)

    result = _run_source(root, "printf 'should-not-run\\n'")

    assert result.returncode != 0
    assert "Missing virtual environment" in result.stdout
    assert "ALLOW_SYSTEM_PYTHON=1" in result.stdout
    assert "should-not-run" not in result.stdout
