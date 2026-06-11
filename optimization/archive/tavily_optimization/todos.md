# Tavily 优化待办

- [ ] 在 CI/本地新增一条“优化版” Stage2 命令别名（直连 + 低并发），写入 SCRIPTS.md/AGENTS 补充节。
- [ ] 为易失败的 4 项（BCOM,GSG,USDCNY,USDCNH）添加专用 task 组示例，存放在 `reports/search_tasks_stage2_examples.jsonl`。
- [ ] 在 `stage2_unified_enhancer.py` 帮助文本中增加直连/代理提示和 deepseek 并发/超时推荐值。
- [ ] 评估把数值类任务默认切换为 regex 抽取的影响（正确率 vs. 覆盖率），出一份对比记录。
- [ ] 将域名白名单配置化（可通过 CLI 或环境变量覆盖），默认包含 reuters/bloomberg/investing/ft。
- [ ] 若仍有 503，大幅拉长深度搜索 timeout（>25s）并观察命中率，形成结论回填 requirements。
