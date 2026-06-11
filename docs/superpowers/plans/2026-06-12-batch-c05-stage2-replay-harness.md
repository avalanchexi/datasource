# 批次 C-0.5:Stage2 replay harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立确定性离线回放 harness(夹具 + 两层测试 + golden),把 Stage2 现行为锁死,作为批次 C 全部拆分 PR 的回归底座。

**Architecture:** 纯新增文件(`tests/fixtures/stage2_replay/` + `tests/test_stage2_replay_harness.py`),不改任何现有代码。Level 1 直调 `_execute_tasks`(全注入);Level 2 monkeypatch 三锚点跑完整 `main()`。录制数据(`websearch_results/*.json` 含 `raw_results/extraction/result_type`)既是供数源也是断言 oracle。

**Tech Stack:** pytest、monkeypatch、现有 fake 契约(`tests/test_stage2_unified.py` L4082+ 范例)。无新依赖。

**Spec:** `docs/superpowers/specs/2026-06-12-batch-c05-stage2-replay-harness-design.md`

---

## 环境头(必读)

- WSL/Linux shell、worktree 根执行;`$MAIN=/mnt/d/cursor/datasource` 只读取材。Python 一律 `bash run_clean.sh python ...`。
- **零网络**(Task 0 pip bootstrap 除外);**不修改任何现有源码与测试文件**——本计划只允许新增文件。若发现必须改现有代码才能回放,停止回报(那是设计问题,不是执行问题)。
- 接口契约以现有代码/测试为准:写 fake 前先读锚点(`tests/test_stage2_unified.py` 中 L4082 附近的 search/extract fake、`tests/test_stage2_structured_integration.py` 的 registry fake 与 `_execute_tasks` 调用),**fake 的方法签名与返回 shape 照抄锚点**,不自创。
- 若批次 B(`codex/batch-b-script-naming`)先合入 main:开工前 `git rebase main`(零文件交叠,预期无冲突;有冲突即停止回报)。

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

Expected: bootstrap OK + baseline 全绿(失败→停止回报)。注意本批 worktree **不需要** `data/` 夹具——夹具进 `tests/fixtures/`(git 跟踪)。

### Task 1: 构建夹具包 `tests/fixtures/stage2_replay/`

**Files:** Create: `tests/fixtures/stage2_replay/{market_data_input.json, tasks.jsonl, recorded/*.json, structured_responses.json}`

- [ ] **Step 1: 从主 checkout 拷录制源(只读)**

```bash
mkdir -p tests/fixtures/stage2_replay/recorded tests/fixtures/stage2_replay/golden
cp "$MAIN/data/runs/20260522/market_data.json" tests/fixtures/stage2_replay/market_data_input.json
cp "$MAIN"/data/runs/20260522/websearch_results/*.json tests/fixtures/stage2_replay/recorded/
ls tests/fixtures/stage2_replay/recorded | wc -l
```

Expected: 4 个录制文件。

- [ ] **Step 2: 生成 tasks.jsonl(4 个录制搜索任务 + 4 个手工结构化任务)**

写一次性构建脚本 `tests/fixtures/stage2_replay/_build_tasks.py`(保留入库,golden 重建时复用):

```python
"""Build the replay task set: 4 recorded search tasks + 4 synthetic structured tasks."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
tasks = []
for rec in sorted(HERE.glob("recorded/*.json")):
    tasks.append(json.loads(rec.read_text(encoding="utf-8"))["task"])

# 结构化链路任务:命中 / fund_flow gate / 解析失败回退 / 无源转 manual。
# 字段结构照抄录制任务,indicator 选 structured_responses.json 中定义的键。
base = {k: tasks[0][k] for k in ("stage_phase", "search_backend") if k in tasks[0]}
synthetic = [
    {**base, "task_id": "replay-structured-gold", "indicator_key": "GC=F",
     "category": "commodities", "query": "COMEX gold close", "unit": "$/oz",
     "extraction_backend": "deepseek", "preferred_domains": [], "created_at": 1700000000},
    {**base, "task_id": "replay-structured-etf", "indicator_key": "etf",
     "category": "fund_flow", "query": "全市场ETF净流入", "unit": "亿元",
     "extraction_backend": "deepseek", "preferred_domains": [], "created_at": 1700000000},
    {**base, "task_id": "replay-structured-parse-error", "indicator_key": "DXY",
     "category": "forex", "query": "US dollar index close", "unit": "index",
     "extraction_backend": "deepseek", "preferred_domains": [], "created_at": 1700000000},
    {**base, "task_id": "replay-manual-required", "indicator_key": "mlf",
     "category": "monetary_policy", "query": "MLF操作利率", "unit": "%",
     "extraction_backend": "deepseek", "preferred_domains": [], "created_at": 1700000000},
]
tasks.extend(synthetic)
out = HERE / "tasks.jsonl"
out.write_text("\n".join(json.dumps(t, ensure_ascii=False) for t in tasks) + "\n", encoding="utf-8")
print(f"wrote {len(tasks)} tasks")
```

```bash
bash run_clean.sh python tests/fixtures/stage2_replay/_build_tasks.py
```

Expected: `wrote 8 tasks`。(若录制任务缺 `stage_phase` 等字段,以录制文件实际结构为准调整 `base`,并在回报中记录。)

- [ ] **Step 3: 写 `structured_responses.json`**(fake registry 的供数,shape 照抄 `tests/test_stage2_structured_integration.py` 的 `StructuredResult(...)` 构造参数)

```json
{
  "GC=F": {"behavior": "success", "payload": {"value": 2410.5, "unit": "$/oz"},
           "source": "Structured gold fixture", "source_url": "https://finance.yahoo.com/quote/GC=F",
           "source_tier": "tier2", "confidence": 0.98},
  "etf": {"behavior": "success", "payload": {"value": 85.0, "recent_5d": 85.0, "total_120d": 1200.0,
          "trend": "inflow", "unit": "亿元", "metric_basis": "news_net_flow",
          "window_evidence": "unknown", "is_estimated": false},
          "source": "ETF news fixture", "source_url": "https://finance.example.com/etf-news",
          "source_tier": "tier3", "confidence": 0.9},
  "DXY": {"behavior": "parse_error"}
}
```

(`mlf` 不在表内 → registry 无 provider → 走搜索;recorded 中也无 mlf → fake search 返回空 → 落 manual_required,覆盖第四条链路。)

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/stage2_replay/ && git commit -m "test: add stage2 replay fixture pack"
```

### Task 2: harness 模块(fake 层 + 归一化)

**Files:** Create: `tests/test_stage2_replay_harness.py`(本 Task 先写 fake/归一化与加载器;测试函数在 Task 3/4 追加)

- [ ] **Step 1: 先读锚点再写 fake**

```bash
sed -n '4070,4120p' tests/test_stage2_unified.py
sed -n '4240,4270p' tests/test_stage2_unified.py
```

记录:Tavily fake 的 `search` 返回 shape、`extract` 签名;DeepSeek fake 的 `extract(snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None)` 返回 shape。**下一步代码中的返回结构必须与锚点一致**;如与本计划骨架不符,以锚点为准修改骨架并在回报记录。

- [ ] **Step 2: 写 harness 骨架**

```python
"""Deterministic offline replay harness for stage2_unified_enhancer (batch C-0.5).

Fixtures: tests/fixtures/stage2_replay/. Recorded files double as oracle
(result_type/extraction captured from a real run). Golden refresh:
STAGE2_REPLAY_UPDATE_GOLDEN=1 pytest tests/test_stage2_replay_harness.py
"""

import json
import os
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "stage2_replay"


def load_recordings():
    """query string -> recorded payload(含 raw_results/extraction/result_type)."""
    by_query = {}
    for path in sorted(FIXTURES.glob("recorded/*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        task = rec["task"]
        for q in [task.get("query")] + list(task.get("queries") or []):
            if q:
                by_query[q] = rec
    return by_query


class ReplayTavilyClient:
    """以录制 raw_results 应答;无录制的 query 返回空(锚点 shape)。"""

    def __init__(self):
        self._by_query = load_recordings()
        self.search_calls = 0

    async def search(self, *args, **kwargs):
        self.search_calls += 1
        query = kwargs.get("query") or (args[0] if args else "")
        rec = self._by_query.get(query)
        raw = rec["raw_results"] if rec else []
        return {"results": raw}  # ← 与 Task 2 Step 1 锚点核对后定稿

    async def extract(self, *args, **kwargs):
        return {"results": []}  # 回放不做 Tavily extract;锚点核对 shape


class ReplayDeepSeek:
    """对录制任务回放其 extraction;其余返回 no_value。"""

    def __init__(self):
        self._by_query = load_recordings()

    async def extract(self, snippets, indicator, unit_hint=None, issuer_hint=None, request_timeout=None):
        for rec in self._by_query.values():
            if rec["task"]["indicator_key"] == indicator and rec.get("extraction"):
                return dict(rec["extraction"])
        return {"value": None, "note": "deepseek_no_value"}


class ReplayRegistry:
    """structured_responses.json 驱动;behavior=parse_error 时抛 StructuredProviderError。"""

    def __init__(self):
        self._spec = json.loads((FIXTURES / "structured_responses.json").read_text(encoding="utf-8"))
        self.calls = 0

    def provider_for(self, indicator_key):
        return object() if indicator_key in self._spec else None

    async def fetch(self, task, market_payload, reference_date):
        from datasource.providers.stage2_structured import StructuredProviderError, StructuredResult

        self.calls += 1
        spec = self._spec[task["indicator_key"]]
        if spec["behavior"] == "parse_error":
            raise StructuredProviderError(provider="replay-fixture", indicator_key=task["indicator_key"],
                                          reason="parse_error", message="replay fixture parse error")
        return StructuredResult(provider="replay-fixture", indicator_key=task["indicator_key"],
                                category=task["category"], payload=dict(spec["payload"]),
                                source=spec["source"], source_url=spec["source_url"],
                                source_tier=spec["source_tier"], as_of_date=reference_date,
                                confidence=spec["confidence"])


# 每项必须有实证来由(连跑两次 capture 的 diff),不许凭感觉加。
VOLATILE_FIELDS = set()  # Task 5 Step 1 实证后填充,如 {"created_at", "elapsed_ms", ...}


def normalize(obj):
    """递归剔除 VOLATILE_FIELDS、按键排序,产出可比对结构。"""
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in sorted(obj.items()) if k not in VOLATILE_FIELDS}
    if isinstance(obj, list):
        return [normalize(v) for v in obj]
    return obj


def assert_or_update_golden(payload, name):
    golden = FIXTURES / "golden" / name
    text = json.dumps(normalize(payload), ensure_ascii=False, indent=2, sort_keys=True)
    if os.environ.get("STAGE2_REPLAY_UPDATE_GOLDEN") == "1":
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

- [ ] **Step 1: 追加测试**(调用方式照抄 `tests/test_stage2_structured_integration.py` L278 附近的 `_execute_tasks(...)` 实参写法,缺省参数不写)

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
    outcome = {
        r.get("indicator_key") or r.get("task", {}).get("indicator_key"): r.get("result_type")
        for r in websearch
    }
    # 四条链路都必须出现(具体值由 golden 锁定)
    assert_or_update_golden(
        {"outcome": outcome, "completed": len(completed), "failures": len(failures),
         "websearch": websearch},
        "level1_outcome.json",
    )
```

- [ ] **Step 2: 首跑 capture + 复跑断言**

```bash
STAGE2_REPLAY_UPDATE_GOLDEN=1 bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py -q
bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py -q
```

Expected: 两次都 PASS;第二次为真实断言。若 `_execute_tasks` 调用因签名/返回 shape 报错:对照锚点修 harness(fake 侧),**不许改 `scripts/stage2_unified_enhancer.py`**。

- [ ] **Step 3: Commit**(`git add -A && git commit -m "test: add level-1 stage2 replay chain test with golden"`)

### Task 4: Level-2 端到端回放(main() 级)

**Files:** Modify: `tests/test_stage2_replay_harness.py`(追加)

- [ ] **Step 1: 追加测试**

```python
def test_replay_full_main(tmp_path, monkeypatch):
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
        "--no-cache",
    ]
    monkeypatch.setattr(stage2.sys, "argv", argv)
    import asyncio
    rc = asyncio.run(stage2.main())
    assert rc in (0, None)

    produced = json.loads(out.read_text(encoding="utf-8"))
    assert_or_update_golden(produced, "level2_market_data_stage2.json")

    ws_payload = json.loads(ws.read_text(encoding="utf-8"))
    assert_or_update_golden(ws_payload, "level2_websearch_results.json")

    # oracle:4 个录制任务的 result_type/extraction 与真实 run 一致
    recorded = {r["task"]["indicator_key"]: r for r in load_recordings().values()}
    produced_by_key = {}
    items = ws_payload.get("results") if isinstance(ws_payload, dict) else ws_payload
    for item in items:
        key = item.get("indicator_key") or item.get("task", {}).get("indicator_key")
        produced_by_key[key] = item
    for key, rec in recorded.items():
        got = produced_by_key.get(key)
        assert got is not None, f"recorded task {key} missing from replay output"
        assert got.get("result_type") == rec.get("result_type"), key
        if rec.get("extraction"):
            assert got.get("extraction", {}).get("value") == rec["extraction"].get("value"), key
            assert got.get("extraction", {}).get("source_url") == rec["extraction"].get("source_url"), key
```

(若 `main()` 不是 async 或入口名不同,以 L7066 实际定义为准调整调用;`--gap-monitor` 等参数名以 `--help` 实际输出为准,首跑前 `bash run_clean.sh python scripts/stage2_unified_enhancer.py --help | grep -E "gap|resume|websearch"` 核对。)

- [ ] **Step 2: capture + 断言**(同 Task 3 Step 2 两连跑)

Expected: 两次 PASS;oracle 四项全中。oracle 不中 → 不许改断言阈值,停止回报(说明 fake 供数或参数与真实 run 偏差,需规划方裁定)。

- [ ] **Step 3: Commit**

### Task 5: 确定性收口 + 终验 + 回报

- [ ] **Step 1: VOLATILE_FIELDS 实证**

```bash
STAGE2_REPLAY_UPDATE_GOLDEN=1 bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py -q
cp -r tests/fixtures/stage2_replay/golden /tmp/golden_run1
STAGE2_REPLAY_UPDATE_GOLDEN=1 bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py -q
diff -r /tmp/golden_run1 tests/fixtures/stage2_replay/golden
```

Expected: diff 为空 → `VOLATILE_FIELDS` 留空即可。**diff 不为空** → 把每个不稳定字段加入 `VOLATILE_FIELDS` 并逐项注释来由(如 `created_at:任务时间戳`),重新 capture 直至连跑 diff 为空;全部字段及来由写入回报。

- [ ] **Step 2: 终验**

```bash
bash run_clean.sh python -m pytest -q 2>&1 | tail -3
bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py -q 2>&1 | tail -2
git status --short
```

Expected: 全量绿(新增 2 个用例);status 干净。

- [ ] **Step 3: 回报**(留在分支,不合并)

回报:各 Task SHA、Task 2 Step 1 锚点核对结论(fake shape 是否照计划骨架/有何修正)、oracle 四项结果、VOLATILE_FIELDS 最终清单及来由、终验输出、偏差清单。

**后续(评审方):** 评审(重点:VOLATILE_FIELDS 是否过宽、oracle 覆盖)→ squash 合入 → C1 拆分计划生成。
