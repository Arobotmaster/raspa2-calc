## raspa-scale 使用说明与中断后恢复

`raspa-scale` 用于在不重跑前处理流程的情况下，动态调整高通量计算的并发度（扩容/缩容），并在作业被打断后自动补齐缺失的作业，保证任务最终跑完。

### 能解决什么问题
- **动态扩缩容**：运行过程中临时增加/减少并发，避免手工 scancel/重提。
- **自动补救**：节点或队列异常导致作业被取消时，自动识别缺口并补交。
- **配置继承**：确保补交作业继承原始高通量配置（`.raspa_config.yaml` 会被自动保存/读取）。
- **资源优化**：在超线程节点上，自动将多个 Worker 打包进单个 SLURM Job，充分利用 ThreadsPerCore 资源。
- **死锁自愈**：自动清理因强制中断（如 scancel）导致的陈旧锁文件和卡死的队列指针。

### 基本用法
在任务子目录（含 `mc*` 任务）下执行：
- `raspa-scale`：默认先展示资源与任务概览，然后进入模式选择（含查看任务状态入口）。
- `raspa-scale -i`：强制进入交互模式（与默认行为一致，适合脚本显式说明）。
- `raspa-scale <并发数> -a`：直接写入上限并自动扩/缩容。
- `raspa-scale <并发数> --limit-only`：只写入 `.raspa_worker_limit`，不提交流程变更。
- `-y`：无交互自动采用推荐并发并执行自动扩/缩容（适合无终端或 CI）。
- `RASPA_SCALE_RECOMMEND=auto|run_idle|idle|full`：控制“推荐并发”策略；默认 auto（按“当前目录运行中 + 集群空闲”推荐，且不超过任务总数）。
- `RASPA_SCALE_SCAN_JOBS=<N>`：并行扫描任务目录的线程数（默认自动使用最多 32 线程；设为 1 可禁用并行）。
- `RASPA_SCALE_SCAN_MODE=auto|fast|verify`：任务统计模式；auto 在任务很多时自动切换到 fast（不逐目录检查 simulation.*）。
- `RASPA_SCALE_SCAN_FAST_THRESHOLD=<N>`：auto 模式触发 fast 的阈值（默认 2000）。
- `RASPA_SCALE_SCAN_CACHE_SEC=<N>`：任务统计缓存秒数（默认 15，避免脚本内多次重复扫描）。
- `raspa-scale kill`：进入终止任务的交互菜单（按用户/范围/列表）。
- `raspa-scale kill -u <用户名>`：终止指定用户的全部 SLURM 任务。
- `raspa-scale kill -n <node[:count],...> [-c <count>]`：按节点终止运行中的任务（支持多个节点与数量）。
- `raspa-scale kill -r <开始-结束>`：按作业ID范围终止。
- `raspa-scale kill -l <id1,id2,...>`：按作业ID列表终止。

示例：
- `raspa-scale kill -n worker-node-01:10,worker-node-02:5`
- `raspa-scale kill -n worker-node-01,worker-node-02 -c 3`

菜单含义：
- **模式菜单**：`1` 自动扩缩容（写入并执行）；`2` 终止任务（按用户/范围/列表）；`3` 查看任务状态；`q` 退出。
- **终止任务菜单**：`u` 按用户；`r` 按范围；`l` 按列表；`q` 退出。

### 脚本与模板位置
- 提交脚本默认使用 `RASPA_TOOL_DIR/job_templates/tasksrun.sh`，不再复制 `job_templates` 到工作目录。
- Worker 执行脚本优先来自 `RASPA_TOOL_DIR/job_templates/runjobs*.sh`，可通过 `RASPA_TOOL_DIR` 覆盖工具目录。
- 工作目录主要保留队列与任务数据：`.raspa_queue`、`.raspa_worker_limit`、`.raspa_jobs.list`、`mc*` 等。

### 状态监控与排查 (raspa-status)
`raspa-status` 现已升级，能区分“实际运行”与“SLURM调度”状态：
- **运行中(__running)**：实际已成功抢到任务锁并开始计算的目录数。
- **SLURM活跃/估算**：SLURM 队列中处于 Pending/Running 状态的作业对应的 Worker 总数。
- **常见现象解释**：
  - `运行中 10 (SLURM活跃: 50)`：说明有 40 个作业刚提交，正在排队或正在初始化（抢锁中）。
  - `运行中 0 (SLURM活跃: 0)` 但有大量 `待处理`：说明作业已全部结束或意外终止，需用 `raspa-scale` 补交。

### 工作原理简述
1. **并发控制**：在目标目录写入 `.raspa_worker_limit`，运行中的 worker 在下个任务边界会遵守上限。
2. **作业追踪**：
   - 追踪文件 `.raspa_jobs.list` 记录 JobId→Worker编号（支持 1:N 打包映射）。
   - 自动识别“孤儿目录”（有 `__running` 但无对应 SLURM 作业），并将其回滚为待处理。
3. **打包策略 (Packing)**：
   - 在支持超线程的节点（如 ThreadsPerCore=2），`raspa-scale` 会自动生成 `pack_size=2` 的作业。
   - 例如：提交 1 个 SLURM Job，申请 2 个 CPU 线程，内部启动 2 个 Worker 并发计算。
   - 日志会显示：`节点分配计划(线程->作业): nodeA:20 -> nodeA:10`。
4. **死锁处理**：
   - **锁超时**：默认 30秒。若作业被杀导致 `mcX.lock` 残留，新 Worker 会在 30s 后自动接管。
   - **指针重置**：若队列指针（`next_id`）已耗尽但仍有大量回滚任务（Pending），`raspa-scale` 会自动删除指针，触发 Worker 全量重新扫描。

### 中断后恢复全量任务的建议流程
1. 进入任务目录：`cd /home/zjp/raspa2-calc/work/<子目录>`。
2. 查看现状：`raspa-status`。
   - 关注 `运行中` 和 `待处理` 数量。
   - 确认 `SLURM活跃` 是否符合预期。
3. 执行恢复并设定目标并发：`raspa-scale -i -a`。
   - 工具会自动检测环境、清理死锁指针、重建 `.raspa_jobs.list`、补齐缺口编号。
   - 如果之前有大量任务被 `scancel`，工具会提示 `自动重置指针以加速认领`。
   - 也可直接运行 `raspa-scale` 后选择模式 `1` 进入扩缩容流程。
4. 验证效果：
   - 等待约 10-30 秒。
   - 再次运行 `raspa-status`，确认 `运行中` 数量开始上升并接近 `SLURM活跃` 数。

### 常见问题
- **Q: 为什么 raspa-status 显示的运行数远小于提交数？**
  A: 作业正在排队，或正在争抢任务锁。新版脚本已优化锁竞争，通常在 1 分钟内会同步。如果长时间不涨，请重新运行 `raspa-scale -a` 触发指针重置。
- **Q: 为什么 mc50 之后的任务一直不跑？**
  A: 可能是旧的锁文件导致。`raspa-scale` 现已内置自动重置逻辑，重新运行一次扩容即可解决。
- **Q: 缩容后目录变回 mcX 了，但新作业不认领？**
  A: 同上，这是因为队列指针已扫过这些 ID。重新运行 `raspa-scale` 会自动删除 `next_id`，强制 Worker 回头扫描。
