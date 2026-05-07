import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional


def _copy_runner(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    scripts = root / "scripts"
    scripts.mkdir()
    runner = Path("run_clean.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    runtime = Path("scripts/runtime_env.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    (root / "run_clean.sh").write_bytes(runner.encode("utf-8"))
    (scripts / "runtime_env.sh").write_bytes(runtime.encode("utf-8"))
    (root / ".env").write_bytes(
        b"TUSHARE_TOKEN=x\nTAVILY_API_KEY=y\nDEEPSEEK_API_KEY=z\n"
    )
    return root


def _write_fake_uname(root: Path, system_name: str) -> None:
    fake_bin = root / "fake-bin"
    fake_bin.mkdir()
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


def _write_fake_venv_python(root: Path, *, windows: bool = False) -> Path:
    if windows:
        python_path = root / ".venv" / "Scripts" / "python.exe"
    else:
        python_path = root / ".venv" / "bin" / "python"
    python_path.write_bytes(b"#!/usr/bin/env bash\nprintf 'fake-venv-python\\n'\n")
    python_path.chmod(0o755)
    return python_path


def _write_fake_python_commands(root: Path) -> Path:
    fake_bin = root / "py-bin"
    fake_bin.mkdir()
    (fake_bin / "python").write_bytes(
        b"#!/usr/bin/env bash\nprintf 'wrong-python\\n'\nexit 42\n"
    )
    (fake_bin / "python3").write_bytes(
        b"#!/usr/bin/env bash\nprintf 'fake-python3\\n'\n"
    )
    (fake_bin / "python").chmod(0o755)
    (fake_bin / "python3").chmod(0o755)
    return fake_bin


def _run(
    root: Path,
    *args: str,
    env: Optional[dict] = None,
    path_prefix: Optional[str] = None,
) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    merged.pop("ALLOW_SYSTEM_PYTHON", None)
    merged.update(env or {})
    env_args = ["-u", "ALLOW_SYSTEM_PYTHON"]
    env_args.extend(f"{key}={shlex.quote(value)}" for key, value in (env or {}).items())
    command = " ".join(
        [
            "exec",
            "env",
            *env_args,
            "bash",
            "run_clean.sh",
            *[shlex.quote(arg) for arg in args],
        ]
    )
    if path_prefix is not None:
        command = f"PATH={shlex.quote(path_prefix)}:\"$PATH\"; export PATH; {command}"
    return subprocess.run(
        ["bash", "-c", command],
        cwd=root,
        env=merged,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _last_output_line(result: subprocess.CompletedProcess) -> str:
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def test_run_clean_script_uses_lf_line_endings() -> None:
    body = Path("run_clean.sh").read_bytes()
    assert b"\r\n" not in body


def test_empty_venv_directory_fails_even_with_system_fallback(tmp_path: Path) -> None:
    root = _copy_runner(tmp_path)
    (root / ".venv").mkdir()

    result = _run(
        root,
        "printf",
        "should not run\n",
        env={"ALLOW_SYSTEM_PYTHON": "1"},
    )

    assert result.returncode == 1
    assert ".venv exists but no usable activate script found" in result.stdout
    assert "should not run" not in result.stdout


def test_uses_windows_venv_activate_when_windows_native_bash(tmp_path: Path) -> None:
    root = _copy_runner(tmp_path)
    _write_fake_uname(root, "MINGW64_NT-10.0")
    scripts_dir = root / ".venv" / "Scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "activate").write_bytes(b"export RUN_CLEAN_ACTIVATE=windows\n")
    _write_fake_venv_python(root, windows=True)

    result = _run(
        root,
        "printenv",
        "RUN_CLEAN_ACTIVATE",
        path_prefix="./fake-bin",
    )

    assert result.returncode == 0, result.stdout
    assert _last_output_line(result) == "windows"


def test_rejects_windows_venv_activate_under_linux_without_system_fallback(
    tmp_path: Path,
) -> None:
    root = _copy_runner(tmp_path)
    _write_fake_uname(root, "Linux")
    scripts_dir = root / ".venv" / "Scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "activate").write_bytes(b"export RUN_CLEAN_ACTIVATE=windows\n")

    result = _run(
        root,
        "printenv",
        "RUN_CLEAN_ACTIVATE",
        path_prefix="./fake-bin",
    )

    assert result.returncode == 1
    assert ".venv exists but no usable activate script found" in result.stdout
    assert "windows" not in result.stdout


def test_linux_with_only_windows_venv_fails_even_with_system_fallback(
    tmp_path: Path,
) -> None:
    root = _copy_runner(tmp_path)
    _write_fake_uname(root, "Linux")
    scripts_dir = root / ".venv" / "Scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "activate").write_bytes(b"export RUN_CLEAN_ACTIVATE=windows\n")

    result = _run(
        root,
        "printenv",
        "PYTHONPATH",
        env={"ALLOW_SYSTEM_PYTHON": "1", "PYTHONPATH": ""},
        path_prefix="./fake-bin",
    )

    assert result.returncode == 1
    assert ".venv exists but no usable activate script found" in result.stdout
    assert "windows" not in result.stdout


def test_system_fallback_flag_still_prefers_existing_linux_venv(
    tmp_path: Path,
) -> None:
    root = _copy_runner(tmp_path)
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "activate").write_bytes(b"export RUN_CLEAN_ACTIVATE=linux\n")
    _write_fake_venv_python(root)

    result = _run(
        root,
        "printenv",
        "RUN_CLEAN_ACTIVATE",
        env={"ALLOW_SYSTEM_PYTHON": "1"},
    )

    assert result.returncode == 0, result.stdout
    assert "WARNING" not in result.stdout
    assert _last_output_line(result) == "linux"


def test_missing_venv_without_system_fallback_fails(tmp_path: Path) -> None:
    root = _copy_runner(tmp_path)

    result = _run(root, "printf", "should not run\n")

    assert result.returncode == 1
    assert "Missing virtual environment" in result.stdout
    assert "ALLOW_SYSTEM_PYTHON=1" in result.stdout
    assert "should not run" not in result.stdout


def test_explicit_system_fallback_succeeds_and_sets_pythonpath(tmp_path: Path) -> None:
    root = _copy_runner(tmp_path)

    result = _run(
        root,
        "printenv",
        "PYTHONPATH",
        env={"ALLOW_SYSTEM_PYTHON": "1", "PYTHONPATH": ""},
    )

    assert result.returncode == 0, result.stdout
    assert "WARNING" in result.stdout
    assert _last_output_line(result) == "./src"


def test_python_command_uses_selected_system_python3(tmp_path: Path) -> None:
    root = _copy_runner(tmp_path)
    fake_bin = _write_fake_python_commands(root)

    result = _run(
        root,
        "python",
        "-c",
        "print('should use python3')",
        env={"ALLOW_SYSTEM_PYTHON": "1", "PYTHONPATH": ""},
        path_prefix=str(fake_bin),
    )

    assert result.returncode == 0, result.stdout
    assert _last_output_line(result) == "fake-python3"
    assert "wrong-python" not in result.stdout


def test_missing_env_fails_even_with_system_fallback(tmp_path: Path) -> None:
    root = _copy_runner(tmp_path)
    (root / ".env").unlink()

    result = _run(
        root,
        "printf",
        "should not run\n",
        env={"ALLOW_SYSTEM_PYTHON": "1"},
    )

    assert result.returncode == 1
    assert "Missing .env" in result.stdout
    assert "should not run" not in result.stdout
