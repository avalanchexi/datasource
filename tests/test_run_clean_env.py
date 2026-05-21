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
    (root / ".env").write_text(
        "TUSHARE_TOKEN=xxxxxxxxxxxxxxxxxxxx\n"
        "TAVILY_API_KEY=yyyyyyyyyyyyyyyyyyyy\n"
        "DEEPSEEK_API_KEY=zzzzzzzzzzzzzzzzzzzz\n",
        encoding="utf-8",
    )
    return root


def _run_clean(
    root: Path,
    *args: str,
    env: Optional[dict] = None,
) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    for key in (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        merged.pop(key, None)
    merged.update(env or {})
    env_args = ["-u", "ALLOW_SYSTEM_PYTHON"]
    env_args.extend(f"{key}={shlex.quote(str(value))}" for key, value in (env or {}).items())
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


def test_run_clean_removes_active_proxy_vars_and_keeps_no_proxy(tmp_path: Path) -> None:
    root = _copy_runner(tmp_path)

    result = _run_clean(
        root,
        "bash",
        "-c",
        (
            "printf '%s|%s|%s|%s|%s|%s|%s\\n' "
            "\"${http_proxy:-}\" \"${https_proxy:-}\" "
            "\"${HTTP_PROXY:-}\" \"${HTTPS_PROXY:-}\" "
            "\"${ALL_PROXY:-}\" \"${all_proxy:-}\" \"${NO_PROXY:-}\""
        ),
        env={
            "ALLOW_SYSTEM_PYTHON": "1",
            "http_proxy": "http://proxy.local:8080",
            "https_proxy": "http://lower-secure-proxy.local:8080",
            "HTTP_PROXY": "http://upper-proxy.local:8080",
            "HTTPS_PROXY": "http://secure-proxy.local:8080",
            "ALL_PROXY": "socks5h://vpn.local:1080",
            "all_proxy": "socks5h://lower-vpn.local:1080",
            "NO_PROXY": "localhost,127.0.0.1",
        },
    )

    assert result.returncode == 0, result.stdout
    assert result.stdout.strip().splitlines()[-1] == "||||||localhost,127.0.0.1"
