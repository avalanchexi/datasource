# 批次 C-0.5:Stage2 replay harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development(recommended)or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox(`- [ ]`)syntax for tracking.

**Goal:** 建立确定性离线回放 harness(夹具 + 两层测试 + golden),把 Stage2 现行为锁死,作为批次 C 全部拆分 PR 的回归底座。

**Architecture:** 纯新增文件(`tests/fixtures/stage2_replay/` + `tests/test_stage2_replay_harness.py`),不改任何现有代码。夹具用**真实录制任务**:主供数 20260527(structured/manual/skip 全 18 指标)+ 从 20260424 借 1 条 search_success 记录补搜索链路。Level 1 直调 `_execute_tasks`(全注入、默认串行);Level 2 monkeypatch 三锚点跑完整 `main()` 并强制 `--no-use-queue`。录制文件的 `result_type/extraction` 既是 fake 供数也是断言 oracle。

**Tech Stack:** pytest、monkeypatch、现有 fake 契约(`tests/test_stage2_unified.py` L4082+、`tests/test_stage2_structured_integration.py`)。无新依赖。

**Spec:** `docs/superpowers/specs/2026-06-12-batch-c05-stage2-replay-harness-design.md`(2026-06-12 加固修订)

---

## 环境头(必读)

- WSL/Linux shell、worktree 根执行;`$MAIN=/mnt/d/cursor/datasource` 只读取材。Python 一律 `bash run_clean.sh python ...`。
- **零网络**(Task 0 pip bootstrap 除外);**不修改任何现有源码与测试文件**——本计划只允许新增文件。若发现必须改现有代码才能回放,停止回报(那是设计问题,不是执行问题)。
- 接口契约以现有代码/测试为准:写 fake 前先读锚点(`tests/test_stage2_unified.py` L4082 附近的 search/extract fake、`tests/test_stage2_structured_integration.py` 的 registry fake 与 `_execute_tasks` 调用),**fake 的方法签名与返回 shape 照抄锚点**,不自创。
- 若批次 B 已合入 main:开工前 `git rebase main`(零文件交叠,预期无冲突;有冲突即停止回报)。
- **录制文件 shape 是唯一外部不确定项**:Task 1 Step 2 先 dump 一条 `structured_success` 记录确认 payload 字段落位(`extraction` vs 顶层),构建脚本据此取数并 **fail loud**;不要假设字段一定存在。

---

### Task 0: 置备 worktree

- [ ] **Step 1: 创建并置备**(配方同批次 B Task 0,分支换名)

```bash
MAIN=/mnt/d/cursor/datasource
WT="$MAIN/.worktrees/codex-batch-c05-replay-harness"
cd "$MAIN"
git worktree add "$WT" -b codex/batch-c05-stage2-replay-harness
cp "$MAIN/.env" "$WT/.env"
mkdir -p "$WT/logs" "$WT/reports" "$WT/.venv"
cd "$WT"
DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -V
bash run_clean.sh python -m pytest -q 2>&1 | tail -3
```

Expected: bootstrap OK + baseline 全绿(失败→停止回报)。本批 worktree **不需要** `data/` 夹具——夹具进 `tests/fixtures/`(git 跟踪);但构建脚本需读 `$MAIN/data/runs/`(只读取材)。

### Task 1: 构建夹具包 `tests/fixtures/stage2_replay/`

**Files:**
- Create: `tests/fixtures/stage2_replay/_build_fixtures.py`(构建脚本,入库供 golden 重建复用)
- Create(脚本产出): `tests/fixtures/stage2_replay/{market_data_input.json, recorded/*.json, tasks.jsonl, structured_responses.json}`

- [ ] **Step 1: 确认供数 run 仍在主 checkout**

```bash
ls "$MAIN"/data/runs/20260527/websearch_results/*.json | wc -l   # 期望 18
ls "$MAIN"/data/runs/20260424/websearch_results/*.json | wc -l   # 期望 18
test -f "$MAIN"/data/runs/20260527/market_data.json && echo input-ok
```

Expected: `18` / `18` / `input-ok`。任一缺失→停止回报(供数 run 漂移,需规划方改选日期)。

- [ ] **Step 2: 先 dump 一条结构化记录确认 payload 落位**

```bash
bash run_clean.sh python - <<'PY'
import json, glob
for f in sorted(glob.glob("/mnt/d/cursor/datasource/data/runs/20260527/websearch_results/*.json")):
    d = json.load(open(f, encoding="utf-8"))
    if d.get("result_type") == "structured_success":
        ext = d.get("extraction") or {}
        print("indicator =", d["task"]["indicator_key"])
        print("top_keys  =", sorted(d.keys()))
        print("extraction.keys =", sorted(ext.keys()))
        print("value/source_url/source_tier =",
              ext.get("value"), "|", ext.get("source_url"), "|", ext.get("source_tier"))
        break
PY
```

记录:结构化记录的 value/source_url/source_tier 落在 `extraction` 下(预期)还是顶层。**下一步构建脚本的取数路径以此为准**;若两处都没有 source_url/source_tier,停止回报(说明该 run 结构化记录不可回放,需换 run)。

- [ ] **Step 3: 写构建脚本 `_build_fixtures.py`**

```python
"""Build the stage2 replay fixture pack from real recorded runs.

Donor runs (verified 2026-06-12):
  - 20260527: structured_success / manual_required / skipped_existing, 18 indicators.
  - 20260424: borrow ONE search_success record to cover the search lane
    (structured-era runs have ~0 search_success).

Idempotent: rerun to regenerate. fail loud on any coverage/shape gap.
"""

import json
import shutil
from collections import Counter
from pathlib import Path

MAIN = Path("/mnt/d/cursor/datasource")
PRIMARY = MAIN / "data/runs/20260527/websearch_results"
SEARCH_DONOR = MAIN / "data/runs/20260424/websearch_results"
INPUT = MAIN / "data/runs/20260527/market_data.json"

HERE = Path(__file__).resolve().parent
REC = HERE / "recorded"


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _structured_payload(rec):
    """Pull replayable structured payload from a record; fail loud if unusable."""
    ext = rec.get("extraction") or {}
    src_url = ext.get("source_url") or rec.get("source_url")
    src_tier = ext.get("source_tier") or rec.get("source_tier")
    key = rec["task"]["indicator_key"]
    if not src_url or not src_tier:
        raise SystemExit(f"FAIL: structured record {key} missing source_url/source_tier; pick another run")
    return {
        "behavior": "success",
        "payload": {k: ext[k] for k in ("value", "unit", "recent_5d", "total_120d",
                                        "trend", "metric_basis", "window_evidence",
                                        "is_estimated") if k in ext},
        "source": ext.get("source") or rec.get("source") or "replay-fixture",
        "source_url": src_url,
        "source_tier": src_tier,
        "confidence": ext.get("confidence", 0.9),
    }


def main():
    REC.mkdir(parents=True, exist_ok=True)
    for old in REC.glob("*.json"):
        old.unlink()

    # 1) market_data input
    shutil.copy2(INPUT, HERE / "market_data_input.json")

    # 2) primary records (20260527) keyed by indicator
    primary = {}
    for f in sorted(PRIMARY.glob("*.json")):
        rec = _load(f)
        primary[rec["task"]["indicator_key"]] = (f, rec)

    rtypes = {k: r["result_type"] for k, (_, r) in primary.items()}
    structured_keys = sorted(k for k, t in rtypes.items() if t == "structured_success")
    manual_keys = sorted(k for k, t in rtypes.items() if t == "manual_required")
    skip_keys = sorted(k for k, t in rtypes.items() if t == "skipped_existing")
    if not (structured_keys and manual_keys and skip_keys):
        raise SystemExit(f"FAIL: primary run missing a result_type: {Counter(rtypes.values())}")

    # 3) search lane: swap ONE manual indicator with a borrowed 20260424 search_success record
    donor_search = {}
    for f in sorted(SEARCH_DONOR.glob("*.json")):
        rec = _load(f)
        if rec.get("result_type") == "search_success":
            donor_search[rec["task"]["indicator_key"]] = rec
    search_key = next((k for k in manual_keys if k in donor_search), None)
    if search_key is None:
        # fallback: any donor search_success indicator not already structured
        search_key = next((k for k in sorted(donor_search) if k not in structured_keys), None)
    if search_key is None:
        raise SystemExit("FAIL: no borrowable search_success record from 20260424")

    # 4) write recorded/ : all primary except the swapped indicator, plus the borrowed search record
    written = {}
    for key, (f, rec) in primary.items():
        if key == search_key:
            continue
        (REC / f.name).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        written[key] = rec
    srec = donor_search[search_key]
    (REC / f"borrowed_search_{search_key.replace('=', '_')}.json").write_text(
        json.dumps(srec, ensure_ascii=False, indent=2), encoding="utf-8")
    written[search_key] = srec

    # 5) PARSE_ERROR lane: pick one structured indicator (the last, kept out of oracle) → fake parse_error
    parse_error_key = structured_keys[-1]

    # 6) structured_responses.json: success for structured keys (except parse_error_key), parse_error for it
    structured_responses = {}
    for key in structured_keys:
        if key == search_key:  # search_key was manual, won't be here, but guard anyway
            continue
        if key == parse_error_key:
            structured_responses[key] = {"behavior": "parse_error"}
        else:
            structured_responses[key] = _structured_payload(written[key])
    (HERE / "structured_responses.json").write_text(
        json.dumps(structured_responses, ensure_ascii=False, indent=2), encoding="utf-8")

    # 7) tasks.jsonl from real task objects (sorted by task_id for stable order)
    tasks = [rec["task"] for rec in written.values()]
    tasks.sort(key=lambda t: str(t.get("task_id")))
    (HERE / "tasks.jsonl").write_text(
        "\n".join(json.dumps(t, ensure_ascii=False) for t in tasks) + "\n", encoding="utf-8")

    # 8) coverage guard: four result_types must be reachable
    final_rtypes = {k: (r.get("result_type")) for k, r in written.items()}
    have = set(final_rtypes.values())
    needed = {"structured_success", "search_success", "manual_required", "skipped_existing"}
    missing = needed - have
    if missing:
        raise SystemExit(f"FAIL: result_type coverage gap: missing={missing} have={Counter(final_rtypes.values())}")

    meta = {"search_key": search_key, "parse_error_key": parse_error_key,
            "structured_keys": structured_keys, "manual_keys": manual_keys, "skip_keys": skip_keys}
    (HERE / "fixture_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OK", {"tasks": len(tasks), **{k: v for k, v in meta.items() if k.endswith("_key")},
                 "coverage": dict(Counter(final_rtypes.values()))})


if __name__ == "__main__":
    main()
```

```bash
mkdir -p tests/fixtures/stage2_replay
# 把上面脚本写入 tests/fixtures/stage2_replay/_build_fixtures.py 后:
bash run_clean.sh python tests/fixtures/stage2_replay/_build_fixtures.py
```

Expected: `OK {...}`,coverage 含 structured_success/search_success/manual_required/skipped_existing 各 ≥1。任一 `FAIL:` → 停止回报(供数 run 不满足,需规划方裁定)。

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/stage2_replay/ && git commit -m "test: add stage2 replay fixture pack from real recorded runs"
```

### Task 2: harness 模块(fake 层 + 归一化 + golden 助手)

**Files:** Create: `tests/test_stage2_replay_harness.py`(本 Task 写 fake/归一化/加载器;测试函数在 Task 3/4 追加)

- [ ] **Step 1: 先读锚点再写 fake**

```bash
sed -n '4070,4120p' tests/test_stage2_unified.py
sed -n '4240,4270p' tests/test_stage2_unified.py
grep -n "_execute_tasks(" tests/test_stage2_structured_integration.py | head
```

记录:Tavily fake 的 `search` 返回 shape、`extract` 签名;DeepSeek fake 的 `extract(snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None)` 返回 shape;`_execute_tasks(...)` 实参写法。**下一步代码的返回结构必须与锚点一致**;不符以锚点为准修改骨架并在回报记录。

- [ ] **Step 2: 写 harness 骨架**

```python
"""Deterministic offline replay harness for stage2_unified_enhancer (batch C-0.5).

Fixtures: tests/fixtures/stage2_replay/ (built by _build_fixtures.py from real runs).
Recorded files double as oracle (result_type/extraction from a real run).
Golden refresh: STAGE2_REPLAY_UPDATE_GOLDEN=1 pytest tests/test_stage2_replay_harness.py
"""

import json
import os
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "stage2_replay"
META = json.loads((FIXTURES / "fixture_meta.json").read_text(encoding="utf-8"))
PARSE_ERROR_KEY = META["parse_error_key"]  # 合成 parse_error,不参与 oracle


def load_recordings():
    """indicator_key -> recorded payload(含 raw_results/extraction/result_type)。"""
    by_key = {}
    for path in sorted(FIXTURES.glob("recorded/*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        by_key[rec["task"]["indicator_key"]] = rec
    return by_key


def _recordings_by_query():
    by_query = {}
    for rec in load_recordings().values():
        task = rec["task"]
        for q in [task.get("query")] + list(task.get("queries") or []):
            if q:
                by_query[q] = rec
    return by_query


class ReplayTavilyClient:
    """以录制 raw_results 应答;无录制的 query 返回空(锚点 shape)。"""

    def __init__(self):
        self._by_query = _recordings_by_query()
        self.search_calls = 0

    async def search(self, *args, **kwargs):
        self.search_calls += 1
        query = kwargs.get("query") or (args[0] if args else "")
        rec = self._by_query.get(query)
        raw = rec.get("raw_results") if rec else []
        return {"results": raw or []}  # ← 与 Task 2 Step 1 锚点核对后定稿

    async def extract(self, *args, **kwargs):
        return {"results": []}  # 回放不做 Tavily extract;锚点核对 shape


class ReplayDeepSeek:
    """对录制任务回放其 extraction;其余返回 no_value。"""

    def __init__(self):
        self._by_key = load_recordings()

    async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None):
        rec = self._by_key.get(indicator)
        if rec and rec.get("extraction"):
            return dict(rec["extraction"])
        return {"value": None, "note": "deepseek_no_value"}


class ReplayRegistry:
    """structured_responses.json 驱动;不在表内的 indicator 视为无 provider(逼走搜索链路)。"""

    def __init__(self):
        self._spec = json.loads((FIXTURES / "structured_responses.json").read_text(encoding="utf-8"))
        self.calls = 0

    def provider_for(self, indicator_key):
        return object() if indicator_key in self._spec else None

    async def fetch(self, task, market_payload, reference_date):
        from datasource.providers.stage2_structured import StructuredProviderError, StructuredResult

        self.calls += 1
        key = task["indicator_key"]
        spec = self._spec[key]
        if spec["behavior"] == "parse_error":
            raise StructuredProviderError(provider="replay-fixture", indicator_key=key,
                                          reason="parse_error", message="replay fixture parse error")
        return StructuredResult(provider="replay-fixture", indicator_key=key,
                                category=task.get("category"), payload=dict(spec["payload"]),
                                source=spec["source"], source_url=spec["source_url"],
                                source_tier=spec["source_tier"], as_of_date=reference_date,
                                confidence=spec["confidence"])


# 每项必须有实证来由(连跑两次 capture 的 diff),不许凭感觉加。
VOLATILE_FIELDS = set()  # Task 5 Step 1 实证后填充,如 {"created_at", "elapsed_ms", ...}


def _result_sort_key(item):
    if not isinstance(item, dict):
        return ("", "")
    task = item.get("task") if isinstance(item.get("task"), dict) else {}
    return (str(item.get("task_id") or task.get("task_id") or ""),
            str(item.get("indicator_key") or task.get("indicator_key") or ""))


def sort_results(items):
    """对结果列表按 task_id/indicator 规范排序,消除并发完成顺序抖动。"""
    return sorted(items, key=_result_sort_key) if isinstance(items, list) else items


def normalize(obj):
    """递归剔除 VOLATILE_FIELDS、按 dict 键排序;不重排 list(保留 market_data 语义顺序)。"""
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in sorted(obj.items()) if k not in VOLATILE_FIELDS}
    if isinstance(obj, list):
        return [normalize(v) for v in obj]
    return obj


def assert_or_update_golden(payload, name):
    golden = FIXTURES / "golden" / name
    text = json.dumps(normalize(payload), ensure_ascii=False, indent=2, sort_keys=True)
    if os.environ.get("STAGE2_REPLAY_UPDATE_GOLDEN") == "1":
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(text, encoding="utf-8")
        return
    assert golden.exists(), f"golden missing: {name}; run with STAGE2_REPLAY_UPDATE_GOLDEN=1"
    assert text == golden.read_text(encoding="utf-8"), f"golden mismatch: {name}"
```

- [ ] **Step 3: Commit**

```bash
bash run_clean.sh python -m py_compile tests/test_stage2_replay_harness.py && echo OK
git add tests/test_stage2_replay_harness.py && git commit -m "test: add stage2 replay harness scaffolding (fakes + golden helpers)"
```

### Task 3: Level-1 链路测试(`_execute_tasks` 级)

**Files:** Modify: `tests/test_stage2_replay_harness.py`(追加)

- [ ] **Step 1: 追加测试**(调用方式照抄 `tests/test_stage2_structured_integration.py` 的 `_execute_tasks(...)` 实参写法;默认 `use_queue=False` 即串行)

```python
def _load_tasks():
    lines = (FIXTURES / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(ln) for ln in lines if ln.strip()]


def test_replay_execute_tasks_chains(tmp_path):
    import asyncio

    from scripts.stage2_unified_enhancer import _execute_tasks

    market = json.loads((FIXTURES / "market_data_input.json").read_text(encoding="utf-8"))
    completed, failures, websearch = asyncio.run(_execute_tasks(
        _load_tasks(), market,
        client=ReplayTavilyClient(), exa_client=None,
        extractor=ReplayDeepSeek(), task_log_path=tmp_path / "task_log.jsonl",
        cache_ttl=None, structured_registry=ReplayRegistry(),
    ))

    websearch_sorted = sort_results(websearch)
    outcome = {item.get("indicator_key") or item.get("task", {}).get("indicator_key"):
               item.get("result_type") for item in websearch_sorted}

    # 四链路覆盖(spec 验收 #4)
    have = set(outcome.values())
    for rt in ("structured_success", "search_success", "manual_required", "skipped_existing"):
        assert rt in have, f"missing result_type {rt}; outcome={outcome}"

    # oracle:录制任务的 result_type 与录制一致(parse_error 合成项除外)
    recorded = load_recordings()
    for key, rec in recorded.items():
        if key == PARSE_ERROR_KEY:
            continue
        assert outcome.get(key) == rec.get("result_type"), f"{key}: {outcome.get(key)} != {rec.get('result_type')}"

    assert_or_update_golden(
        {"outcome": outcome, "completed": len(completed), "failures": len(failures),
         "websearch": websearch_sorted},
        "level1_outcome.json",
    )
```

- [ ] **Step 2: 首跑 capture + 复跑断言**

```bash
STAGE2_REPLAY_UPDATE_GOLDEN=1 bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py::test_replay_execute_tasks_chains -q
bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py::test_replay_execute_tasks_chains -q
```

Expected: 两次 PASS;第二次为真实断言。若 `_execute_tasks` 调用因签名/返回 shape 报错:对照锚点修 harness(fake 侧),**不许改 `scripts/stage2_unified_enhancer.py`**。若 oracle 不中:停止回报(fake 供数或 registry 路由与真实 run 偏差,需规划方裁定)。

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "test: add level-1 stage2 replay chain test with golden + oracle"
```

### Task 4: Level-2 端到端回放(main() 级)

**Files:** Modify: `tests/test_stage2_replay_harness.py`(追加)

- [ ] **Step 1: 先核对 CLI flag**

```bash
bash run_clean.sh python scripts/stage2_unified_enhancer.py --help | grep -E "no-use-queue|resume-from-task-file|websearch-results|task-file|task-log|gap-monitor|deepseek-max-concurrency|no-cache"
```

记录实际 flag 名;下一步 argv 以此为准(若某 flag 名不同,改 argv,不改源码)。

- [ ] **Step 2: 追加测试**

```python
def test_replay_full_main(tmp_path, monkeypatch):
    import asyncio

    import scripts.stage2_unified_enhancer as stage2

    monkeypatch.setattr(stage2, "AsyncTavilyClient", lambda *a, **k: ReplayTavilyClient())
    monkeypatch.setattr(stage2, "DeepSeekExtractionAgent", lambda *a, **k: ReplayDeepSeek())
    monkeypatch.setattr(stage2, "build_default_registry", lambda: ReplayRegistry())
    monkeypatch.setenv("TAVILY_API_KEY", "replay-dummy-key-0123456789")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "replay-dummy-key-0123456789")

    out = tmp_path / "market_data_stage2.json"
    ws = tmp_path / "websearch_results_auto.json"
    argv = [
        "stage2_unified_enhancer.py",
        "--market-data", str(FIXTURES / "market_data_input.json"),
        "--output", str(out),
        "--execute-search",
        "--resume-from-task-file", str(FIXTURES / "tasks.jsonl"),
        "--websearch-results", str(ws),
        "--task-file", str(tmp_path / "tasks_out.jsonl"),
        "--task-log", str(tmp_path / "task_log.jsonl"),
        "--gap-monitor", str(tmp_path / "gap_monitor.json"),
        "--no-use-queue",                       # 确定性:关并发队列(use_queue 默认 True)
        "--deepseek-max-concurrency", "1",      # 确定性:串行抽取
        "--no-cache",
    ]
    monkeypatch.setattr(stage2.sys, "argv", argv)
    rc = asyncio.run(stage2.main())
    assert rc in (0, None)

    produced = json.loads(out.read_text(encoding="utf-8"))
    assert_or_update_golden(produced, "level2_market_data_stage2.json")

    ws_payload = json.loads(ws.read_text(encoding="utf-8"))
    items = ws_payload.get("results") if isinstance(ws_payload, dict) else ws_payload
    assert_or_update_golden({"results": sort_results(items)}, "level2_websearch_results.json")

    # oracle:录制任务的 result_type/extraction 与真实 run 一致(parse_error 合成项除外)
    recorded = load_recordings()
    produced_by_key = {}
    for item in items:
        key = item.get("indicator_key") or item.get("task", {}).get("indicator_key")
        produced_by_key[key] = item
    for key, rec in recorded.items():
        if key == PARSE_ERROR_KEY:
            continue
        got = produced_by_key.get(key)
        assert got is not None, f"recorded task {key} missing from replay output"
        assert got.get("result_type") == rec.get("result_type"), key
        if rec.get("extraction") and rec["extraction"].get("value") is not None:
            assert got.get("extraction", {}).get("value") == rec["extraction"].get("value"), key
            assert got.get("extraction", {}).get("source_url") == rec["extraction"].get("source_url"), key
```

(若 `main()` 不是 async 或入口名不同,以 L7066 实际定义为准调整调用。)

- [ ] **Step 3: capture + 断言**(同 Task 3 Step 2 两连跑,目标 `::test_replay_full_main`)

Expected: 两次 PASS;oracle 全中。oracle 不中 → 不许改断言阈值,停止回报。

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "test: add level-2 stage2 full-main replay with golden + oracle"
```

### Task 5: 确定性收口 + 终验 + 回报

- [ ] **Step 1: VOLATILE_FIELDS 实证**

```bash
STAGE2_REPLAY_UPDATE_GOLDEN=1 bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py -q
cp -r tests/fixtures/stage2_replay/golden /tmp/golden_run1
STAGE2_REPLAY_UPDATE_GOLDEN=1 bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py -q
diff -r /tmp/golden_run1 tests/fixtures/stage2_replay/golden
```

Expected: diff 为空 → `VOLATILE_FIELDS` 留空。**diff 不为空** → 把每个不稳定字段加入 `VOLATILE_FIELDS` 并逐项注释来由(如 `created_at:任务时间戳`),重新 capture 直至连跑 diff 为空;全部字段及来由写入回报。注意:列表顺序抖动应已被 `sort_results` 消除——若 diff 仍是顺序问题,说明有未排序的结果列表,补 `sort_results`,不要靠 VOLATILE 掩盖。

- [ ] **Step 2: 终验**

```bash
bash run_clean.sh python -m pytest -q 2>&1 | tail -3
bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py -q 2>&1 | tail -2
git status --short
```

Expected: 全量绿(新增 2 个用例);status 干净。

- [ ] **Step 3: 回报**(留在分支,不合并)

回报:各 Task SHA、Task 1 Step 2 结构化记录 shape 结论、Task 2 Step 1 锚点核对结论、`_build_fixtures.py` 选出的 `search_key/parse_error_key` 及 coverage、oracle 全中证据、VOLATILE_FIELDS 最终清单及来由、终验输出、偏差清单。

**后续(评审方):** 评审(重点:VOLATILE_FIELDS 是否过宽、oracle 覆盖、search_key 路由是否真走搜索链路)→ squash 合入 → C1 拆分计划生成。
