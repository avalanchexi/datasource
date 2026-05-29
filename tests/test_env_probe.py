import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[1]


def _copy_probe(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    body = (REPO_ROOT / "scripts/env_probe.sh").read_text(
        encoding="utf-8"
    ).replace("\r\n", "\n")
    probe = scripts / "env_probe.sh"
    probe.write_bytes(body.encode("utf-8"))
    probe.chmod(0o755)
    return root


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


def _write_linux_venv(root: Path, *, executable: bool = True) -> Path:
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "activate").write_text("export FAKE_VENV=linux\n", encoding="utf-8")
    python_path = bin_dir / "python"
    python_path.write_bytes(
        b"#!/usr/bin/env bash\nprintf '%s\\n' '/fake/linux/python'\n"
    )
    python_path.chmod(0o755 if executable else 0o644)
    return python_path


def _write_windows_venv(root: Path, *, executable: bool = True) -> Path:
    scripts_dir = root / ".venv" / "Scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "activate").write_text(
        "export FAKE_VENV=windows\n", encoding="utf-8"
    )
    python_path = scripts_dir / "python.exe"
    python_path.write_bytes(
        b"#!/usr/bin/env bash\nprintf '%s\\n' 'C:/fake/windows/python.exe'\n"
    )
    python_path.chmod(0o755 if executable else 0o644)
    return python_path


def _run_probe(
    root: Path,
    *,
    path_prefix: Optional[Path] = None,
    fake_pwd: Optional[str] = None,
) -> subprocess.CompletedProcess:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(root)),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    command = "bash scripts/env_probe.sh"
    if fake_pwd is not None:
        command = (
            "cd() { "
            "if [ \"${1:-}\" = \"$ENV_PROBE_FAKE_PWD\" ]; then return 0; fi; "
            "builtin cd \"$@\"; "
            "}; "
            "pwd() { printf '%s\\n' \"$ENV_PROBE_FAKE_PWD\"; }; "
            "export -f cd; "
            "export -f pwd; "
            f"{command}"
        )
        env["ENV_PROBE_FAKE_PWD"] = fake_pwd
    if path_prefix is not None:
        command = (
            f"PATH={shlex.quote(path_prefix.as_posix())}:\"$PATH\"; "
            f"export PATH; {command}"
        )
    return subprocess.run(
        ["bash", "-c", command],
        cwd=root,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _env_probe_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def test_env_probe_script_uses_lf_line_endings() -> None:
    body = (REPO_ROOT / "scripts/env_probe.sh").read_bytes()

    assert b"\r\n" not in body


def test_linux_venv_returns_ok(tmp_path: Path) -> None:
    root = _copy_probe(tmp_path)
    fake_bin = _write_fake_uname(root, "Linux")
    python_path = _write_linux_venv(root)

    result = _run_probe(root, path_prefix=fake_bin)

    assert result.returncode == 0, result.stdout
    assert "[OK] env_probe" in result.stdout
    assert "platform=Linux" in result.stdout
    assert "venv_layout=linux" in result.stdout
    assert f"python={python_path}" in result.stdout
    assert "next=bash run_preflight.sh" in result.stdout


def test_msys_with_linux_venv_returns_use_wsl(tmp_path: Path) -> None:
    root = _copy_probe(tmp_path)
    fake_bin = _write_fake_uname(root, "MSYS_NT-10.0")
    _write_linux_venv(root)

    result = _run_probe(root, path_prefix=fake_bin)

    assert result.returncode == 3
    assert "[USE_WSL] env_probe" in result.stdout
    assert "Windows native bash is active but .venv uses Linux/WSL layout" in result.stdout
    assert "C:\\Windows\\System32\\bash.exe" in result.stdout


def test_missing_venv_returns_broken_env(tmp_path: Path) -> None:
    root = _copy_probe(tmp_path)
    fake_bin = _write_fake_uname(root, "Linux")

    result = _run_probe(root, path_prefix=fake_bin)

    assert result.returncode == 2
    assert "[BROKEN_ENV] env_probe" in result.stdout
    assert "venv_layout=missing" in result.stdout
    assert "Missing .venv; create it before running the pipeline" in result.stdout


def test_venv_directory_without_activate_returns_broken_env(tmp_path: Path) -> None:
    root = _copy_probe(tmp_path)
    fake_bin = _write_fake_uname(root, "Linux")
    (root / ".venv").mkdir()

    result = _run_probe(root, path_prefix=fake_bin)

    assert result.returncode == 2
    assert "[BROKEN_ENV] env_probe" in result.stdout
    assert "venv_layout=broken" in result.stdout
    assert ".venv exists but no usable activate script was found" in result.stdout


def test_non_executable_venv_python_returns_broken_env(tmp_path: Path) -> None:
    root = _copy_probe(tmp_path)
    fake_bin = _write_fake_uname(root, "Linux")
    python_path = _write_linux_venv(root, executable=False)

    result = _run_probe(root, path_prefix=fake_bin)

    assert result.returncode == 2
    assert "[BROKEN_ENV] env_probe" in result.stdout
    assert f"Selected venv Python is not executable: {python_path}" in result.stdout


def test_linux_shell_with_windows_venv_returns_broken_env(tmp_path: Path) -> None:
    root = _copy_probe(tmp_path)
    fake_bin = _write_fake_uname(root, "Linux")
    _write_windows_venv(root)

    result = _run_probe(root, path_prefix=fake_bin)

    assert result.returncode == 2
    assert "[BROKEN_ENV] env_probe" in result.stdout
    assert "venv_layout=windows" in result.stdout
    assert "Windows venv layout is not usable under Linux/WSL" in result.stdout


def test_msys_drive_path_next_command_is_wsl_converted_and_shell_quoted(
    tmp_path: Path,
) -> None:
    root = _copy_probe(tmp_path)
    fake_bin = _write_fake_uname(root, "MSYS_NT-10.0")
    _write_linux_venv(root)
    fake_repo_path = "/d/Repo With Spaces/quote's/repo"

    result = _run_probe(root, path_prefix=fake_bin, fake_pwd=fake_repo_path)

    assert result.returncode == 3
    expected_path = "/mnt/d/Repo With Spaces/quote's/repo"
    expected_next = (
        "next=C:\\Windows\\System32\\bash.exe -lc "
        f"\"cd {_env_probe_single_quote(expected_path)} && bash run_preflight.sh\""
    )
    assert f"repo_path={fake_repo_path}" in result.stdout
    assert expected_next in result.stdout
