# Local release verification

Release0.3.1 was checked on2026-10-11 with Windows/Python3.12.10 in an isolated environment without system-site-packages.

- External-staging wheel build, pinned dependency installation, pip check and doctor: passed.
- Full regression suite against the installed wheel:188 tests passed.
- Eight installed diagnostic study runs: passed; all eight output manifests verified.
- Installed real-volume pilot:30 forecasts,270 case records,264 plans and229 completed retrospective replays. Numerical records equal the saved evidence;792 public strategy arrays match exactly.
- Installed Python source and packaged design files:54 byte-for-byte matches.
- All65 saved CSV, NPZ and PNG files retained from the existing numerical evidence are unchanged. Report attribution and documentation are maintained separately from financial calculations.

These are local checks. Hosted results are available separately in GitHub Actions. Smoke runs test installation and do not replace full research. The real-volume pilot has only five evaluation dates and does not establish live fills, complete market-volume coverage or profitability.

Byte-preserving Git attributes keep source digests, frozen inputs and result manifests stable across checkouts. Current repository checksums are recorded in provenance/repository-manifest.json. Study manifests describe distributed files; hashes embedded in prior results identify their producing revision.

## 2026-10-22 本地执行扩展验收

成本预算与双资产协同执行接入现有本地面板，未修改原冻结研究与src核心计算。完整回归291项通过，八项研究快速运行及其输出指纹核对通过；pip check和环境检查通过。浏览器实际核对预算推荐、独立验证、双资产方法切换、分钟回放及两类中文报告生成。新增脚本通过Node语法检查。

新增实验全部使用人工数据。预算规划和验证使用独立随机流；双资产逐分钟核对整数股和现金，所有未完成场景保留。代码审查发现并修复预算前沿标记未显示的问题，复核无剩余已确认重要问题。测试和审查不证明实际成交、成本校准或市场优势。
