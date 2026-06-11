# Archived Scripts

Scripts in this directory are preserved for historical and manual analysis
only. They are not run by the normal Stage1 -> Stage4 daily pipeline.

Archived categories:

- Charts: `cn10y_chart.py`, `cn10y_interactive_chart.py`, and
  `generate_index_charts.py` are retained for older chart-generation workflows.
- Snapshots: `fetch_csi_indices_snapshot.py` is retained for historical index
  snapshot collection experiments.
- Auto executor: `ai_auto_executor.py` is retained as an old automation
  experiment and is not a daily pipeline launcher.

For production daily runs, use the active Stage1 -> Stage4 pipeline documented
in the repository playbook instead of these archived utilities.
