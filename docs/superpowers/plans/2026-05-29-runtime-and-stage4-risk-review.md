# Runtime Probe and Stage4 Risk Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local runtime probe, document the WSL-first startup path, and add a read-only Stage4 risk review for reportable-but-risky data items.

**Architecture:** Keep the startup probe as a standalone shell script so it can run before `run_preflight.sh` and before Python/runtime loading. Keep Stage4 risk review as a standalone Python CLI that uses existing run-path conventions and writes a derived JSON artifact without changing source data. Documentation and scoped memory make the workflow durable across future sessions.

**Tech Stack:** Bash, Python standard library, pytest, existing `datasource.utils.run_paths` helpers, existing repo scripts under `scripts/`.

---

## File Structure

- Create: `scripts/env_probe.sh`
  - Local-only shell/venv/Python compatibility probe.
  - Runs before `run_preflight.sh`.
  - Does not source `.env`, call APIs, or load project Python modules.

- Create: `scripts/stage4_risk_review.py`
  - Read-only risk-review CLI.
  - Reads `market_data_complete.json`, optional `gap_monitor.json`, optional `quality_metrics.json`.
  - Writes `stage4_risk_review.json`.
  - Exposes pure functions so tests can call rule logic directly.

- Create: `tests/test_env_probe.py`
  - Subprocess tests using temp repositories and fake `uname`.
  - Covers Linux venv success, MSYS + Linux venv `USE_WSL`, broken venv, and LF line endings.

- Create: `tests/test_stage4_risk_review.py`
  - Unit tests for BCOM, CN10Y_CDB, fund-flow, missing source evidence, and CLI output.

- Modify: `AGENTS.md`
  - Add `bash scripts/env_probe.sh` as Setup step 0 before preflight.
  - Clarify probe vs preflight responsibility.

- Modify: `CLAUDE.md`
  - Add a short cold-session reminder to validate execution channel before preflight.
  - Mention current machine's Linux/WSL venv and MSYS `dofork` fallback to WSL.

- Create: `/home/tywin/.codex/memories/datasource-wsl-runtime.md`
  - Scoped local memory for this machine and repository.

## Task 1: Add Local Runtime Probe

**Files:**
- Create: `scripts/env_probe.sh`
- Test later in Task 2: `tests/test_env_probe.py`

- [ ] **Step 1: Create the script**

Use `apply_patch` to add this file:

```bash
#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 2

status="OK"
reason=""

platform="$(uname -s 2>/dev/null || printf 'unknown')"
case "$platform" in
  MINGW*|MSYS*|CYGWIN*) is_windows_native_bash=1 ;;
  *) is_windows_native_bash=0 ;;
esac

repo_path="$(pwd -P 2>/dev/null || pwd)"
if [ -f ".venv/bin/activate" ]; then
  venv_layout="linux"
  python_path="$ROOT_DIR/.venv/bin/python"
elif [ -f ".venv/Scripts/activate" ]; then
  venv_layout="windows"
  if [ -x ".venv/Scripts/python.exe" ]; then
    python_path="$ROOT_DIR/.venv/Scripts/python.exe"
  else
    python_path="$ROOT_DIR/.venv/Scripts/python"
  fi
elif [ -d ".venv" ]; then
  venv_layout="broken"
  python_path=""
else
  venv_layout="missing"
  python_path=""
fi

if [ "$is_windows_native_bash" = "1" ] && [ "$venv_layout" = "linux" ]; then
  status="USE_WSL"
  reason="Windows native bash is active but .venv uses Linux/WSL layout"
elif [ "$is_windows_native_bash" = "1" ]; then
  case "$repo_path" in
    /mnt/*)
      status="USE_WSL"
      reason="Repository path looks like WSL but current shell is Windows native bash"
      ;;
  esac
fi

if [ "$status" = "OK" ]; then
  case "$venv_layout" in
    linux|windows)
      if [ -z "$python_path" ] || [ ! -x "$python_path" ]; then
        status="BROKEN_ENV"
        reason="Selected venv Python is not executable: $python_path"
      elif ! python_exec="$("$python_path" -c "import sys; print(sys.executable)" 2>&1)"; then
        status="BROKEN_ENV"
        reason="Selected venv Python failed: $python_exec"
      fi
      ;;
    missing)
      status="BROKEN_ENV"
      reason="Missing .venv; create it before running the pipeline"
      ;;
    broken)
      status="BROKEN_ENV"
      reason=".venv exists but no usable activate script was found"
      ;;
  esac
fi

printf '[%s] env_probe\n' "$status"
printf 'platform=%s\n' "$platform"
printf 'repo_path=%s\n' "$repo_path"
printf 'venv_layout=%s\n' "$venv_layout"
if [ -n "${python_path:-}" ]; then
  printf 'python=%s\n' "$python_path"
fi
if [ -n "$reason" ]; then
  printf 'reason=%s\n' "$reason"
fi

case "$status" in
  OK)
    printf 'next=bash run_preflight.sh\n'
    exit 0
    ;;
  USE_WSL)
    printf 'next=C:\\Windows\\System32\\bash.exe -lc "cd %s && bash run_preflight.sh"\n' "$repo_path"
    exit 3
    ;;
  *)
    printf 'next=fix local venv or execution channel, then rerun bash scripts/env_probe.sh\n'
    exit 2
    ;;
esac
```

- [ ] **Step 2: Make the script executable**

Run:

```bash
chmod +x scripts/env_probe.sh
```

Expected: no output, exit code 0.

- [ ] **Step 3: Run the probe in the current workspace**

Run:

```bash
bash scripts/env_probe.sh
```

Expected in the current WSL workspace:

```text
[OK] env_probe
platform=Linux
repo_path=/mnt/d/cursor/datasource
venv_layout=linux
python=/mnt/d/cursor/datasource/.venv/bin/python
next=bash run_preflight.sh
```

- [ ] **Step 4: Commit**

```bash
git add scripts/env_probe.sh
git commit -m "feat: add runtime environment probe"
```

## Task 2: Test Runtime Probe

**Files:**
- Create: `tests/test_env_probe.py`
- Modify: none

- [ ] **Step 1: Add failing tests**

Use `apply_patch` to add:

```python
import os
import shlex
import subprocess
from pathlib import Path


def _copy_probe(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    scripts = root / "scripts"
    scripts.mkdir()
    body = Path("scripts/env_probe.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    (scripts / "env_probe.sh").write_bytes(body.encode("utf-8"))
    (scripts / "env_probe.sh").chmod(0o755)
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


def _write_linux_venv(root: Path, *, executable: bool = True) -> None:
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "activate").write_text("export PROBE_ACTIVATE=linux\n", encoding="utf-8")
    python = bin_dir / "python"
    python.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = \"-c\" ]; then printf '%s\\n' \"$0\"; else printf 'fake-python\\n'; fi\n",
        encoding="utf-8",
    )
    python.chmod(0o755 if executable else 0o644)


def _run_probe(root: Path, *, path_prefix: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    command = "bash scripts/env_probe.sh"
    if path_prefix is not None:
        command = f"PATH={shlex.quote(str(path_prefix))}:$PATH; export PATH; {command}"
    return subprocess.run(
        ["bash", "-lc", command],
        cwd=root,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def test_env_probe_script_uses_lf_line_endings() -> None:
    body = Path("scripts/env_probe.sh").read_bytes()
    assert b"\r\n" not in body


def test_env_probe_linux_venv_ok(tmp_path: Path) -> None:
    root = _copy_probe(tmp_path)
    _write_linux_venv(root)
    fake_bin = _write_fake_uname(root, "Linux")

    result = _run_probe(root, path_prefix=fake_bin)

    assert result.returncode == 0, result.stdout
    assert "[OK] env_probe" in result.stdout
    assert "platform=Linux" in result.stdout
    assert "venv_layout=linux" in result.stdout
    assert "next=bash run_preflight.sh" in result.stdout


def test_env_probe_msys_with_linux_venv_requests_wsl(tmp_path: Path) -> None:
    root = _copy_probe(tmp_path)
    _write_linux_venv(root)
    fake_bin = _write_fake_uname(root, "MSYS_NT-10.0")

    result = _run_probe(root, path_prefix=fake_bin)

    assert result.returncode == 3, result.stdout
    assert "[USE_WSL] env_probe" in result.stdout
    assert "Windows native bash is active but .venv uses Linux/WSL layout" in result.stdout
    assert "C:\\Windows\\System32\\bash.exe" in result.stdout


def test_env_probe_missing_venv_is_broken(tmp_path: Path) -> None:
    root = _copy_probe(tmp_path)
    fake_bin = _write_fake_uname(root, "Linux")

    result = _run_probe(root, path_prefix=fake_bin)

    assert result.returncode == 2, result.stdout
    assert "[BROKEN_ENV] env_probe" in result.stdout
    assert "Missing .venv" in result.stdout


def test_env_probe_non_executable_python_is_broken(tmp_path: Path) -> None:
    root = _copy_probe(tmp_path)
    _write_linux_venv(root, executable=False)
    fake_bin = _write_fake_uname(root, "Linux")

    result = _run_probe(root, path_prefix=fake_bin)

    assert result.returncode == 2, result.stdout
    assert "[BROKEN_ENV] env_probe" in result.stdout
    assert "not executable" in result.stdout
```

- [ ] **Step 2: Run tests and verify they pass**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_env_probe.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_env_probe.py
git commit -m "test: cover runtime environment probe"
```

## Task 3: Add Stage4 Risk Review CLI

**Files:**
- Create: `scripts/stage4_risk_review.py`
- Test later in Task 4: `tests/test_stage4_risk_review.py`

- [ ] **Step 1: Add the CLI and pure review helpers**

Use `apply_patch` to create:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage4 pre-report risk review.

This script is read-only with respect to market data inputs. It writes a
derived review JSON artifact that highlights reportable-but-risky data items.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from datasource.utils.run_paths import build_run_paths, build_run_paths_from_reference


Finding = Dict[str, Any]

CRITICAL_SOURCE_KEYS = {
    "commodities.BCOM",
    "bonds.CN10Y_CDB",
    "forex.USDCNY",
    "macro_indicators.bdi",
    "monetary_policy.mlf",
    "monetary_policy.reserve_ratio",
}

BCOM_BAD_TOKENS = (
    "bcomtr",
    "total return",
    "etf",
    "exchange traded fund",
    "fund",
    "sub-index",
    "sub index",
)

WINDOW_EVIDENCE_OK = {"direct_window", "direct_daily_series", "direct_balance_delta"}
ESTIMATED_FLOW_BASIS = {"news_net_flow", "estimated_net_flow"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage4 前只读风险复核",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--date", default=None, help="运行日期，支持 YYYY-MM-DD 或 YYYYMMDD")
    parser.add_argument("--market-data", default=None, help="market_data_complete.json 路径")
    parser.add_argument("--gap-monitor", default=None, help="gap_monitor.json 路径")
    parser.add_argument("--quality-metrics", default=None, help="quality_metrics.json 路径")
    parser.add_argument("--output", default=None, help="stage4_risk_review.json 输出路径")
    parser.add_argument(
        "--allow-fund-flow-downgrade",
        action="store_true",
        help="记录 Stage4 fund_flow downgrade 路径已启用",
    )
    return parser.parse_args()


def _load_json(path: Path, *, required: bool) -> Optional[Dict[str, Any]]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"required input not found: {path}")
        return None
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _item_text(item: Dict[str, Any]) -> str:
    fields = [
        item.get("symbol"),
        item.get("name"),
        item.get("source"),
        item.get("note"),
        item.get("manual_reason"),
        item.get("source_url"),
        item.get("estimation_method"),
        item.get("metric_basis"),
        item.get("window_evidence"),
    ]
    return " ".join(str(value) for value in fields if value not in (None, "")).lower()


def _has_numeric_current(item: Dict[str, Any]) -> bool:
    for key in ("current_value", "current_price", "current_rate", "current_yield"):
        value = item.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
    return False


def _finding(severity: str, key: str, code: str, message: str, item: Dict[str, Any]) -> Finding:
    return {
        "severity": severity,
        "key": key,
        "code": code,
        "message": message,
        "source_url": item.get("source_url"),
        "is_estimated": item.get("is_estimated"),
        "metric_basis": item.get("metric_basis"),
        "window_evidence": item.get("window_evidence"),
    }


def _iter_items(payload: Dict[str, Any]) -> Iterable[tuple[str, Dict[str, Any]]]:
    for category, values in payload.items():
        if category == "metadata" or not isinstance(values, dict):
            continue
        for name, item in values.items():
            if isinstance(item, dict):
                yield f"{category}.{name}", item


def review_bcom(payload: Dict[str, Any]) -> List[Finding]:
    item = (payload.get("commodities") or {}).get("BCOM")
    if not isinstance(item, dict):
        return []
    text = _item_text(item)
    for token in BCOM_BAD_TOKENS:
        if token in text:
            return [
                _finding(
                    "blocker",
                    "commodities.BCOM",
                    "bcom_scope_mismatch",
                    f"BCOM evidence appears to reference incompatible scope: {token}",
                    item,
                )
            ]
    return [
        _finding(
            "review_required",
            "commodities.BCOM",
            "bcom_plain_index_review",
            "Confirm source represents plain Bloomberg Commodity Index, not TR, ETF, fund, or sub-index scope",
            item,
        )
    ]


def review_cn10y_cdb(payload: Dict[str, Any]) -> List[Finding]:
    item = (payload.get("bonds") or {}).get("CN10Y_CDB")
    if not isinstance(item, dict) or not item.get("is_estimated"):
        return []
    text = _item_text(item)
    has_basis = any(token in text for token in ("spread", "利差", "cn10y", "估算"))
    if has_basis:
        return [
            _finding(
                "info",
                "bonds.CN10Y_CDB",
                "cn10y_cdb_estimate_disclosed",
                "CN10Y_CDB estimate includes spread/proxy basis disclosure",
                item,
            )
        ]
    return [
        _finding(
            "review_required",
            "bonds.CN10Y_CDB",
            "cn10y_cdb_estimate_missing_basis",
            "CN10Y_CDB is estimated but lacks spread/proxy basis disclosure",
            item,
        )
    ]


def review_fund_flow(payload: Dict[str, Any], *, allow_fund_flow_downgrade: bool) -> List[Finding]:
    findings: List[Finding] = []
    fund_flow = payload.get("fund_flow") or {}
    if not isinstance(fund_flow, dict):
        return findings
    for name, item in fund_flow.items():
        if not isinstance(item, dict):
            continue
        key = f"fund_flow.{name}"
        basis = item.get("metric_basis")
        window_evidence = item.get("window_evidence")
        estimated = bool(item.get("is_estimated"))
        weak_window = window_evidence not in (None, "") and window_evidence not in WINDOW_EVIDENCE_OK
        if estimated or basis in ESTIMATED_FLOW_BASIS or weak_window:
            code = "fund_flow_downgrade_review" if allow_fund_flow_downgrade else "fund_flow_estimate_review"
            message = "fund_flow uses estimated/news/weak-window evidence and needs downgrade disclosure review"
            findings.append(_finding("review_required", key, code, message, item))
    return findings


def review_source_evidence(payload: Dict[str, Any]) -> List[Finding]:
    findings: List[Finding] = []
    for key, item in _iter_items(payload):
        if not _has_numeric_current(item):
            continue
        if item.get("source_url"):
            continue
        severity = "blocker" if key in CRITICAL_SOURCE_KEYS else "review_required"
        findings.append(
            _finding(
                severity,
                key,
                "missing_source_url",
                "Numeric report-facing value is missing source_url evidence",
                item,
            )
        )
    return findings


def build_review(
    market_payload: Dict[str, Any],
    *,
    gap_monitor: Optional[Dict[str, Any]],
    quality_metrics: Optional[Dict[str, Any]],
    allow_fund_flow_downgrade: bool,
) -> Dict[str, Any]:
    findings: List[Finding] = []
    findings.extend(review_bcom(market_payload))
    findings.extend(review_cn10y_cdb(market_payload))
    findings.extend(
        review_fund_flow(
            market_payload,
            allow_fund_flow_downgrade=allow_fund_flow_downgrade,
        )
    )
    findings.extend(review_source_evidence(market_payload))

    grouped = {"blocker": [], "review_required": [], "info": []}
    for finding in findings:
        grouped[finding["severity"]].append(finding)

    return {
        "metadata": {
            "date": (market_payload.get("metadata") or {}).get("date"),
            "allow_fund_flow_downgrade": allow_fund_flow_downgrade,
            "gap_monitor_present": gap_monitor is not None,
            "quality_metrics_present": quality_metrics is not None,
            "finding_count": len(findings),
            "blocker_count": len(grouped["blocker"]),
            "review_required_count": len(grouped["review_required"]),
            "info_count": len(grouped["info"]),
        },
        "findings": grouped,
    }


def resolve_paths(args: argparse.Namespace):
    if args.market_data:
        market_path = Path(args.market_data)
        run_paths = build_run_paths_from_reference(path=market_path, fallback_to_today=True)
    elif args.date:
        run_paths = build_run_paths(args.date)
        market_path = run_paths.market_data_complete
    else:
        run_paths = build_run_paths_from_reference(fallback_to_today=True)
        market_path = run_paths.market_data_complete

    gap_path = Path(args.gap_monitor) if args.gap_monitor else run_paths.gap_monitor
    quality_path = Path(args.quality_metrics) if args.quality_metrics else run_paths.quality_metrics
    output_path = Path(args.output) if args.output else run_paths.data_dir / "stage4_risk_review.json"
    return market_path, gap_path, quality_path, output_path


def main() -> None:
    args = parse_args()
    market_path, gap_path, quality_path, output_path = resolve_paths(args)

    market_payload = _load_json(market_path, required=True)
    assert market_payload is not None
    gap_monitor = _load_json(gap_path, required=False)
    quality_metrics = _load_json(quality_path, required=False)

    review = build_review(
        market_payload,
        gap_monitor=gap_monitor,
        quality_metrics=quality_metrics,
        allow_fund_flow_downgrade=args.allow_fund_flow_downgrade,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(review, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"[DONE] Stage4 risk review written: {output_path}")
    print(
        "[INFO] "
        f"blockers={review['metadata']['blocker_count']}, "
        f"review_required={review['metadata']['review_required_count']}, "
        f"info={review['metadata']['info_count']}"
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run module import smoke**

Run:

```bash
bash run_clean.sh python -c "import runpy; runpy.run_path('scripts/stage4_risk_review.py', run_name='stage4_risk_review_import')"
```

Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add scripts/stage4_risk_review.py
git commit -m "feat: add stage4 risk review"
```

## Task 4: Test Stage4 Risk Review

**Files:**
- Create: `tests/test_stage4_risk_review.py`
- Modify: none

- [ ] **Step 1: Add failing tests**

Use `apply_patch` to add:

```python
import json
import runpy
import subprocess
from pathlib import Path


MODULE = runpy.run_path("scripts/stage4_risk_review.py", run_name="stage4_risk_review_test")


def _build_review(payload, *, allow_fund_flow_downgrade=False):
    return MODULE["build_review"](
        payload,
        gap_monitor=None,
        quality_metrics=None,
        allow_fund_flow_downgrade=allow_fund_flow_downgrade,
    )


def test_bcom_total_return_scope_is_blocker() -> None:
    review = _build_review(
        {
            "metadata": {"date": "2026-05-29"},
            "commodities": {
                "BCOM": {
                    "current_value": 135.87,
                    "source_url": "https://example.com/bcomtr",
                    "note": "Bloomberg Commodity Total Return index",
                }
            },
        }
    )

    assert review["metadata"]["blocker_count"] == 1
    finding = review["findings"]["blocker"][0]
    assert finding["key"] == "commodities.BCOM"
    assert finding["code"] == "bcom_scope_mismatch"


def test_bcom_plain_index_still_requires_human_review() -> None:
    review = _build_review(
        {
            "metadata": {"date": "2026-05-29"},
            "commodities": {
                "BCOM": {
                    "current_value": 135.87,
                    "source_url": "https://www.investing.com/indices/bloomberg-commodity",
                    "note": "Bloomberg Commodity Index close",
                }
            },
        }
    )

    assert review["metadata"]["review_required_count"] == 1
    assert review["findings"]["review_required"][0]["code"] == "bcom_plain_index_review"


def test_cn10y_cdb_estimate_without_basis_requires_review() -> None:
    review = _build_review(
        {
            "metadata": {"date": "2026-05-29"},
            "bonds": {
                "CN10Y_CDB": {
                    "current_yield": 1.81,
                    "source_url": "https://example.com/cdb",
                    "is_estimated": True,
                }
            },
        }
    )

    assert review["metadata"]["review_required_count"] == 1
    assert review["findings"]["review_required"][0]["code"] == "cn10y_cdb_estimate_missing_basis"


def test_cn10y_cdb_estimate_with_spread_basis_is_info() -> None:
    review = _build_review(
        {
            "metadata": {"date": "2026-05-29"},
            "bonds": {
                "CN10Y_CDB": {
                    "current_yield": 1.81,
                    "source_url": "https://example.com/cdb",
                    "is_estimated": True,
                    "estimation_method": "CN10Y plus observed CDB spread",
                }
            },
        }
    )

    assert review["metadata"]["info_count"] == 1
    assert review["findings"]["info"][0]["code"] == "cn10y_cdb_estimate_disclosed"


def test_fund_flow_estimated_basis_requires_downgrade_review() -> None:
    review = _build_review(
        {
            "metadata": {"date": "2026-05-29"},
            "fund_flow": {
                "etf": {
                    "recent_5d": -225.0,
                    "total_120d": -1500.0,
                    "source_url": "https://example.com/etf-news",
                    "is_estimated": True,
                    "metric_basis": "news_net_flow",
                    "window_evidence": "news_summary",
                }
            },
        },
        allow_fund_flow_downgrade=True,
    )

    assert review["metadata"]["review_required_count"] == 1
    finding = review["findings"]["review_required"][0]
    assert finding["key"] == "fund_flow.etf"
    assert finding["code"] == "fund_flow_downgrade_review"


def test_critical_numeric_item_without_source_url_is_blocker() -> None:
    review = _build_review(
        {
            "metadata": {"date": "2026-05-29"},
            "forex": {
                "USDCNY": {
                    "current_rate": 7.18,
                }
            },
        }
    )

    assert review["metadata"]["blocker_count"] == 1
    assert review["findings"]["blocker"][0]["code"] == "missing_source_url"


def test_cli_writes_review_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "data" / "runs" / "20260529"
    run_dir.mkdir(parents=True)
    market_path = run_dir / "market_data_complete.json"
    output_path = run_dir / "stage4_risk_review.json"
    market_path.write_text(
        json.dumps(
            {
                "metadata": {"date": "2026-05-29"},
                "fund_flow": {
                    "etf": {
                        "recent_5d": -1.0,
                        "total_120d": -2.0,
                        "source_url": "https://example.com",
                        "is_estimated": True,
                        "metric_basis": "estimated_net_flow",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python",
            "scripts/stage4_risk_review.py",
            "--market-data",
            str(market_path),
            "--output",
            str(output_path),
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["finding_count"] == 1
    assert payload["findings"]["review_required"][0]["key"] == "fund_flow.etf"
```

- [ ] **Step 2: Run focused tests**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_stage4_risk_review.py -q
```

Expected:

```text
7 passed
```

- [ ] **Step 3: Run CLI against an existing run if available**

Run:

```bash
bash run_clean.sh python scripts/stage4_risk_review.py --date 2026-05-29 --allow-fund-flow-downgrade
```

Expected when `data/runs/20260529/market_data_complete.json` exists:

```text
[DONE] Stage4 risk review written: data/runs/20260529/stage4_risk_review.json
[INFO] blockers=0, review_required=1, info=0
```

If the existing run has different review findings, the three count values may differ, but the line must start with `[INFO] blockers=` and include `review_required=` and `info=` fields.

If the run file does not exist, run this instead to verify the error path:

```bash
bash run_clean.sh python scripts/stage4_risk_review.py --date 2099-01-01
```

Expected:

```text
FileNotFoundError: required input not found: data/runs/20990101/market_data_complete.json
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_stage4_risk_review.py
git commit -m "test: cover stage4 risk review"
```

## Task 5: Document Cold-Start Workflow

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update `AGENTS.md` setup section**

Use `apply_patch` to insert this text under `## 3. Setup & Health Check`, before the current environment creation step:

```markdown
0. Shell/venv 探活（任何 Stage1/Stage2 前先跑）:
   ```bash
   bash scripts/env_probe.sh
   ```
   `env_probe.sh` 只检查本地执行通道，不读取 API key、不访问外网、不替代 preflight。若输出 `OK`，继续 `bash run_preflight.sh`；若输出 `USE_WSL`，说明当前 shell 与仓库/venv 布局错配，应切到 `C:\Windows\System32\bash.exe` 进入 WSL 后再执行项目脚本；若输出同时包含 `dofork` 和 `errno 11` 的 Git/MSYS bash 错误时，不要反复重跑流水线或优先杀进程，先切 WSL。
```

Then renumber the existing setup steps so `Create env` remains step 1 and `Preflight` remains after the probe.

- [ ] **Step 2: Update `CLAUDE.md` cold-session checklist**

Use `apply_patch` to replace the checklist at `## Before You Start (cold-session checklist)` with:

```markdown
1. `bash scripts/env_probe.sh` — 先确认执行通道与 `.venv` 布局。当前本机仓库是 Linux/WSL venv；若 Git/MSYS bash 输出同时包含 `dofork` 和 `errno 11`，或探活输出 `USE_WSL`，切到 `C:\Windows\System32\bash.exe` 后再运行项目脚本，不要在坏 MSYS bash 上重试流水线。
2. `bash run_preflight.sh` — 验证三个 API key + 清代理 + DNS/HTTPS 探活。失败是 hard fail，不要继续。
3. 所有流水线脚本通过 `bash run_clean.sh python scripts/stage2_unified_enhancer.py` 这类 `run_clean.sh` 包装命令执行；不要直跑。
4. Stage1 → Stage2 → Stage2.5 → Stage3 → Stage4，每日按序一次性跑完。**Tavily 每日只能跑 1 次** — 422/quota 后改走 Stage2.5 manual，不要重跑 Stage2。
5. 排障入口看 [Operational Pitfalls](#operational-pitfalls操作陷阱) 与 [Troubleshooting](#troubleshooting) — 它们覆盖 95% 的卡点（`missing_items` 双层、Stage3 三路 gate、inject 跳过 `is_estimated`、fund_flow 估算规则）。
6. 完整命令、参数表、输出契约见 `SCRIPTS.md` 与 `AGENTS.md`；本文件只保留最小操作指引。
```

- [ ] **Step 3: Add Stage4 risk review to daily-run docs**

In `AGENTS.md` under `### 5.6 Stage4 Report`, add a short pre-step before report generation:

```bash
bash run_clean.sh python scripts/stage4_risk_review.py \
  --date "$DATE" \
  --allow-fund-flow-downgrade
```

Add this explanatory bullet:

```markdown
- Stage4 前先运行 `stage4_risk_review.py` 生成 `data/runs/${DATE_NH}/stage4_risk_review.json`。该脚本只读复核，不修改数据；`blocker` 应先处理，`review_required` 必须人工确认报告披露可接受后再生成正式报告。
```

- [ ] **Step 4: Check docs for the new commands**

Run:

```bash
rg -n "env_probe|stage4_risk_review|USE_WSL|dofork" AGENTS.md CLAUDE.md
```

Expected: matches in both `AGENTS.md` and `CLAUDE.md`, with `stage4_risk_review` present in `AGENTS.md`.

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md CLAUDE.md
git commit -m "docs: document runtime probe workflow"
```

## Task 6: Record Scoped Local Memory

**Files:**
- Create: `/home/tywin/.codex/memories/datasource-wsl-runtime.md`

- [ ] **Step 1: Write memory file**

Use `apply_patch` to add:

```markdown
# datasource WSL Runtime Memory

Scope: `/mnt/d/cursor/datasource` on the current machine.

The repository currently uses a Linux/WSL virtual environment layout (`.venv/bin/activate`, `.venv/bin/python`). If Claude Code's default Bash is Git/MSYS and emits both `dofork` and `errno 11`, or emits `Resource temporarily unavailable`, switch to `C:\Windows\System32\bash.exe` and run project scripts inside WSL.

Do not repeatedly retry the daily pipeline or kill shell processes as the primary fix for this failure mode. First verify the execution channel with `bash scripts/env_probe.sh`, then run `bash run_preflight.sh`.
```

- [ ] **Step 2: Verify memory file exists**

Run:

```bash
test -f /home/tywin/.codex/memories/datasource-wsl-runtime.md && sed -n '1,80p' /home/tywin/.codex/memories/datasource-wsl-runtime.md
```

Expected: file contents printed with the scope line and WSL runtime rule.

No git commit is needed because this file is outside the repository.

## Task 7: Final Verification

**Files:**
- Uses all files created or modified in Tasks 1-6.

- [ ] **Step 1: Run runtime probe**

Run:

```bash
bash scripts/env_probe.sh
```

Expected in current WSL workspace:

```text
[OK] env_probe
```

- [ ] **Step 2: Run focused tests**

Run:

```bash
bash run_clean.sh python -m pytest tests/test_env_probe.py tests/test_stage4_risk_review.py -q
```

Expected:

```text
12 passed
```

- [ ] **Step 3: Run syntax checks**

Run:

```bash
bash run_clean.sh python -m py_compile scripts/stage4_risk_review.py
```

Expected: no output, exit code 0.

- [ ] **Step 4: Inspect changed files**

Run:

```bash
git status --short
git log --oneline -6
```

Expected:

- Repository changes from this implementation are either committed per task or clearly limited to the current task's files.
- Unrelated pre-existing worktree changes remain untouched.

- [ ] **Step 5: Optional final consolidation commit if documentation or tests remain uncommitted**

Only run this if `git status --short` shows implementation files from this plan still uncommitted:

```bash
git add scripts/env_probe.sh scripts/stage4_risk_review.py tests/test_env_probe.py tests/test_stage4_risk_review.py AGENTS.md CLAUDE.md
git commit -m "feat: harden runtime startup and stage4 review"
```

Expected: commit succeeds. Do not add unrelated files such as pre-existing reports, unrelated config changes, or local editor settings.

## Self-Review

- Spec coverage: Task 1 covers local execution-channel probe; Task 5 covers `AGENTS.md` and `CLAUDE.md`; Task 6 covers scoped memory; Tasks 3 and 4 cover Stage4 risk review; Task 7 covers final verification.
- No network calls are introduced in `env_probe.sh` or `stage4_risk_review.py`.
- Stage1, Stage2, Stage2.5, Stage3, and Stage4 scoring behavior remains unchanged.
- Risk review writes only `stage4_risk_review.json` and does not mutate market data, gap monitor, quality metrics, or reports.
- Fund-flow estimate handling remains review/downgrade oriented and does not reclassify estimates as non-estimated.
