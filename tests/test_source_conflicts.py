from datasource.utils.source_conflicts import resolve_websearch_results


def test_resolve_by_source_weight():
    results = [
        {
            "task": {"indicator_key": "dxy", "task_id": "1"},
            "extraction": {"value": 100, "source_url": "https://investing.com/x"},
        },
        {
            "task": {"indicator_key": "dxy", "task_id": "2"},
            "extraction": {"value": 101, "source_url": "https://stats.gov.cn/x"},
        },
    ]
    deduped, conflicts = resolve_websearch_results(results)
    assert len(deduped) == 1
    chosen = deduped[0]
    assert chosen["task"]["task_id"] == "2"
    assert conflicts["conflicts"]
