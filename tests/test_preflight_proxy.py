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
    preflight = (
        Path("run_preflight.sh")
        .read_text(encoding="utf-8")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    runtime = (
        Path("scripts/runtime_env.sh")
        .read_text(encoding="utf-8")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    (root / "run_preflight.sh").write_bytes(preflight.encode("utf-8"))
    (scripts / "runtime_env.sh").write_bytes(runtime.encode("utf-8"))
    (root / ".env").write_text(VALID_ENV, encoding="utf-8")
    return root


def _write_fake_python(root: Path, body: str) -> Path:
    fake_bin = root / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    python = fake_bin / "python3"
    python.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    python.chmod(0o755)
    return fake_bin


def _write_fake_executable(root: Path, name: str, body: str) -> Path:
    fake_bin = root / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    executable = fake_bin / name
    executable.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    executable.chmod(0o755)
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


def _source_preflight(
    root: Path,
    script: str,
    *,
    env: Optional[dict] = None,
    path_prefix: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    for key in (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "all_proxy",
    ):
        merged.pop(key, None)
    inline_env = {"ALLOW_SYSTEM_PYTHON": "1", "DATASOURCE_PREFLIGHT_SOURCE_ONLY": "1"}
    inline_env.update(env or {})
    merged.update(inline_env)
    command = (
        "source run_preflight.sh; "
        "set +e; "
        f"{script}"
    )
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


def _run_preflight(
    root: Path,
    *,
    env: Optional[dict] = None,
    path_prefix: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    for key in (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "all_proxy",
        "DATASOURCE_NETWORK_MODE",
        "DATASOURCE_PREFLIGHT_SOURCE_ONLY",
    ):
        merged.pop(key, None)
    merged["ALLOW_SYSTEM_PYTHON"] = "1"
    merged.update(env or {})
    if path_prefix is not None:
        merged["PATH"] = f"{_bash_path(path_prefix, root=root)}{os.pathsep}{merged['PATH']}"
    return subprocess.run(
        ["bash", "run_preflight.sh"],
        cwd=root,
        env=merged,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def test_preflight_direct_mode_reports_proxy_cleared_after_runtime_cleanup(
    tmp_path: Path,
) -> None:
    root = _copy_preflight(tmp_path)

    result = _source_preflight(
        root,
        "_check_proxy_mode; _report_proxy_state",
        env={
            "http_proxy": "http://proxy.local:8080",
            "HTTPS_PROXY": "http://secure-proxy.local:8080",
            "ALL_PROXY": "socks5h://vpn.local:1080",
            "all_proxy": "socks5h://lower-vpn.local:1080",
        },
    )

    assert result.returncode == 0, result.stdout
    assert "[OK] Network mode: direct" in result.stdout
    assert "Proxy cleared" in result.stdout
    assert "socks5h://vpn.local:1080" not in result.stdout


def test_preflight_source_only_env_does_not_bypass_normal_execution(
    tmp_path: Path,
) -> None:
    root = _copy_preflight(tmp_path)
    (root / ".env").write_text(
        "TUSHARE_TOKEN=xxxxxxxxxxxxxxxxxxxx\n"
        "TAVILY_API_KEY=short\n"
        "DEEPSEEK_API_KEY=zzzzzzzzzzzzzzzzzzzz\n",
        encoding="utf-8",
    )

    result = _run_preflight(
        root,
        env={"DATASOURCE_PREFLIGHT_SOURCE_ONLY": "1"},
    )

    assert result.returncode != 0, result.stdout
    assert "Missing/short TAVILY_API_KEY" in result.stdout
    assert "[OK] DNS" not in result.stdout
    assert "[OK] HTTPS" not in result.stdout


def test_preflight_proxy_mode_normal_execution_checks_original_socks_proxy_before_network(
    tmp_path: Path,
) -> None:
    root = _copy_preflight(tmp_path)
    fake_bin = _write_fake_python(root, "exit 1\n")
    _write_fake_executable(
        root,
        "getent",
        "printf 'unexpected-getent %s\\n' \"$*\"\nexit 0\n",
    )
    _write_fake_executable(
        root,
        "curl",
        "printf 'unexpected-curl %s\\n' \"$*\"\nexit 0\n",
    )

    result = _run_preflight(
        root,
        env={
            "DATASOURCE_NETWORK_MODE": "proxy",
            "ALL_PROXY": "socks5h://vpn.local:1080",
        },
        path_prefix=fake_bin,
    )

    assert result.returncode != 0, result.stdout
    assert "[OK] Network mode: proxy" in result.stdout
    assert "ALL_PROXY=socks5h://vpn.local:1080" in result.stdout
    assert "SOCKS proxy requires socksio/httpx[socks]" in result.stdout
    assert "[OK] DNS" not in result.stdout
    assert "[OK] HTTPS" not in result.stdout
    assert "unexpected-getent" not in result.stdout
    assert "unexpected-curl" not in result.stdout


def test_preflight_proxy_mode_socks_requires_socksio(tmp_path: Path) -> None:
    root = _copy_preflight(tmp_path)
    fake_bin = _write_fake_python(root, "exit 1\n")

    result = _source_preflight(
        root,
        (
            "DATASOURCE_NETWORK_MODE=proxy; "
            "DATASOURCE_PYTHON=python3; "
            "ALL_PROXY=socks5h://vpn.local:1080; export DATASOURCE_NETWORK_MODE DATASOURCE_PYTHON ALL_PROXY; "
            "if _check_proxy_mode; then printf 'unexpected-success\\n'; else printf 'proxy-check-failed\\n'; fi"
        ),
        path_prefix=fake_bin,
    )

    assert result.returncode == 0, result.stdout
    assert "SOCKS proxy requires socksio/httpx[socks]" in result.stdout
    assert "proxy-check-failed" in result.stdout
    assert "unexpected-success" not in result.stdout
