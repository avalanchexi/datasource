import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional


VALID_ENV = (
    "TUSHARE_TOKEN=xxxxxxxxxxxxxxxxxxxx\n"
    "TAVILY_API_KEY=yyyyyyyyyyyyyyyyyyyy\n"
    "DEEPSEEK_API_KEY=zzzzzzzzzzzzzzzzzzzz\n"
)


def _copy_preflight(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    scripts = root / "scripts"
    scripts.mkdir()
    preflight = Path("run_preflight.sh").read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    runtime = Path("scripts/runtime_env.sh").read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    (root / "run_preflight.sh").write_bytes(preflight.encode("utf-8"))
    (scripts / "runtime_env.sh").write_bytes(runtime.encode("utf-8"))
    return root


def _write_fake_command(root: Path, name: str, body: str) -> Path:
    fake_bin = root / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    path = fake_bin / name
    path.write_bytes(("#!/usr/bin/env bash\n" + body).encode("utf-8"))
    path.chmod(0o755)
    return fake_bin


def _bash_path(path: Path, *, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
        return f"./{relative.as_posix()}"
    except ValueError:
        pass
    text = str(path)
    if len(text) > 2 and text[1] == ":":
        return f"/mnt/{text[0].lower()}{text[2:].replace(chr(92), '/')}"
    return text


def _run_preflight(
    root: Path,
    *,
    env: Optional[dict] = None,
    path_prefix: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    inline_env = {"ALLOW_SYSTEM_PYTHON": "1"}
    inline_env.update(env or {})
    merged.update(inline_env)
    env_prefix = " ".join(
        f"{key}={shlex.quote(str(value))}" for key, value in inline_env.items()
    )
    command = f"{env_prefix} bash run_preflight.sh"
    if path_prefix is not None:
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


def test_preflight_missing_env_fails(tmp_path: Path) -> None:
    root = _copy_preflight(tmp_path)

    result = _run_preflight(root)

    assert result.returncode != 0
    assert "Missing .env" in result.stdout


def test_preflight_short_key_fails(tmp_path: Path) -> None:
    root = _copy_preflight(tmp_path)
    (root / ".env").write_text(
        "TUSHARE_TOKEN=short\n"
        "TAVILY_API_KEY=yyyyyyyyyyyyyyyyyyyy\n"
        "DEEPSEEK_API_KEY=zzzzzzzzzzzzzzzzzzzz\n",
        encoding="utf-8",
    )

    result = _run_preflight(root)

    assert result.returncode != 0
    assert "Missing/short TUSHARE_TOKEN" in result.stdout


def test_preflight_dns_failure_is_hard_fail(tmp_path: Path) -> None:
    root = _copy_preflight(tmp_path)
    (root / ".env").write_text(VALID_ENV, encoding="utf-8")
    fake_bin = _write_fake_command(
        root,
        "getent",
        "printf 'dns failed for %s\\n' \"$*\" >&2\nexit 2\n",
    )

    result = _run_preflight(root, path_prefix=fake_bin)

    assert result.returncode != 0
    assert "DNS check failed" in result.stdout
    assert "api.tavily.com" in result.stdout


def test_preflight_https_failure_is_hard_fail(tmp_path: Path) -> None:
    root = _copy_preflight(tmp_path)
    (root / ".env").write_text(VALID_ENV, encoding="utf-8")
    fake_bin = _write_fake_command(
        root,
        "getent",
        "printf '127.0.0.1 %s\\n' \"${@: -1}\"\n",
    )
    _write_fake_command(root, "curl", "printf '000'\nexit 0\n")

    result = _run_preflight(root, path_prefix=fake_bin)

    assert result.returncode != 0
    assert "HTTPS check failed" in result.stdout
    assert "https://api.tavily.com" in result.stdout


def test_preflight_accepts_non_2xx_http_response(tmp_path: Path) -> None:
    root = _copy_preflight(tmp_path)
    (root / ".env").write_text(VALID_ENV, encoding="utf-8")
    fake_bin = _write_fake_command(
        root,
        "getent",
        "printf '127.0.0.1 %s\\n' \"${@: -1}\"\n",
    )
    _write_fake_command(root, "curl", "printf '405'\nexit 0\n")

    result = _run_preflight(root, path_prefix=fake_bin)

    assert result.returncode == 0, result.stdout
    assert "[OK] DNS api.tavily.com" in result.stdout
    assert "[OK] HTTPS https://api.tavily.com" in result.stdout
    assert "Proxy cleared" in result.stdout


def test_preflight_curl_timeout_defaults_are_configurable() -> None:
    script = Path("run_preflight.sh").read_text(encoding="utf-8")

    assert 'PREFLIGHT_CONNECT_TIMEOUT="${PREFLIGHT_CONNECT_TIMEOUT:-10}"' in script
    assert 'PREFLIGHT_MAX_TIME="${PREFLIGHT_MAX_TIME:-15}"' in script
    assert '--connect-timeout "$PREFLIGHT_CONNECT_TIMEOUT" --max-time "$PREFLIGHT_MAX_TIME"' in script


def test_preflight_curl_transport_failure_with_000_output_fails(
    tmp_path: Path,
) -> None:
    root = _copy_preflight(tmp_path)
    (root / ".env").write_text(VALID_ENV, encoding="utf-8")
    fake_bin = _write_fake_command(
        root,
        "getent",
        "printf '127.0.0.1 %s\\n' \"${@: -1}\"\n",
    )
    _write_fake_command(root, "curl", "printf '000'\nexit 7\n")

    result = _run_preflight(root, path_prefix=fake_bin)

    assert result.returncode != 0
    assert "HTTPS check failed" in result.stdout
    assert "HTTP 000000" not in result.stdout


def test_preflight_dns_uses_hostname_without_port(tmp_path: Path) -> None:
    root = _copy_preflight(tmp_path)
    (root / ".env").write_text(VALID_ENV, encoding="utf-8")
    fake_bin = _write_fake_command(
        root,
        "getent",
        "printf '%s\\n' \"$*\" >> getent-args.txt\n"
        "case \"$*\" in *api.deepseek.com:443*) exit 9 ;; esac\n"
        "printf '127.0.0.1 %s\\n' \"${@: -1}\"\n",
    )
    _write_fake_command(root, "curl", "printf '405'\nexit 0\n")

    result = _run_preflight(
        root,
        env={"DEEPSEEK_BASE_URL": "https://api.deepseek.com:443/v1"},
        path_prefix=fake_bin,
    )

    assert result.returncode == 0, result.stdout
    dns_calls = (root / "getent-args.txt").read_text(encoding="utf-8")
    assert "hosts api.deepseek.com\n" in dns_calls
    assert "api.deepseek.com:443" not in dns_calls
