## raspa-scale 使用说明与中断后恢复

`raspa-scale` 用于在不重跑前处理流程的情况下，动态调整高通量计算的并发度（扩容/缩容），并在作业被打断后自动补齐缺失的作业，保证任务最终跑完。

### 能解决什么问题
- 运行过程中临时增加/减少并发，避免手工 scancel/重提。
- 节点或队列异常导致作业被取消时，自动识别缺口并补交，继续未完成的任务。
- 确保补交作业继承原始高通量配置（`.raspa_config.yaml` 会被自动保存/读取）。
- 避免过度提交：最多提交到「目标并发」与「剩余可跑任务数」的较小值。
- 避免误杀：缩容时只裁剪编号大于目标值的作业，或按运行时间最短的作业补足裁剪数。

### 基本用法
在任务子目录（含 `mc*` 任务）下执行：
- `raspa-scale`：自动推荐并发上限并进入选择菜单（仅展示，不改动）。
- `raspa-scale -i`：交互式输入并发上限，然后选择是只写上限还是自动扩/缩容。
- `raspa-scale <并发数> -a`：直接写入上限并自动扩/缩容。
- `raspa-scale <并发数> --limit-only`：只写入 `.raspa_worker_limit`，不提交流程变更。
- `-y`：无交互自动采用推荐并发并执行自动扩/缩容（适合无终端或 CI）。

菜单含义：
- `d` 仅查看；`l` 写入上限；`a` 写入上限并执行自动扩/缩容。

### 工作原理简述
1. 在目标目录写入 `.raspa_worker_limit`，运行中的 worker 在下个任务边界会遵守上限。
2. 对 SLURM 循环提交的任务：
   - 追踪文件 `.raspa_jobs.list` 记录 JobId→worker 编号；缺失时会通过 `scontrol` 尝试重建。
   - `__running` 目录数量与 SLURM 活跃作业求并，估算当前并发。
   - 扩容：找出 1..上限 的缺口编号，且不超过剩余待处理任务数后补交。
   - 缩容：优先 scancel 编号大于上限的作业，若不足则按运行时间最短补齐。
   - 节点计划：自动按集群空闲、负载与可选的 `node_priorities` 生成/轮询分配。
3. 配置继承：`raspa-calc` 会把本次的 `config.yaml` 快照为 `.raspa_config.yaml`；`runjobs.sh`/`runjobs_raspa3.sh` 读取它，保证补交作业用同一 conda/env/cif/template/MSER 配置。

### 中断后恢复全量任务的建议流程
1. 进入任务目录：`cd /home/zjp/raspa2-calc/work/<子目录>`。
2. 查看现状：`raspa-status`（确认运行中/待处理数量）。
3. 若有残留的 `mc*__running` 但队列里已无对应作业，可先将它们改回待处理（示例：`find . -maxdepth 1 -name 'mc*__running' -exec bash -c 'mv "$0" "${0%__running}"' {} \;`，请慎用，只在确认对应作业已终止时执行）。
4. 执行恢复并设定目标并发，例如：`raspa-scale -i 140`，在菜单选 `a`。
   - 工具会重建 `.raspa_jobs.list`（若缺失）、补齐缺口编号、并沿用 `.raspa_config.yaml`。
5. 等待几秒后再跑一次 `raspa-status`，确认 Running 数接近目标；如仍不足，可重复 `raspa-scale -i <目标>`。

### 注意事项
- 请在包含 `job_templates` 的工作目录内运行；工具会自动复制合适的 `runjobs.sh` 到子目录的 `job_templates`。
- 若目标并发大于剩余可跑任务数，实际提交不会超过可用任务。
- 当初始运行数已高于目标时，本轮只做缩容，不会立即补交；待作业被调度器真正取消后再按需扩容即可。
