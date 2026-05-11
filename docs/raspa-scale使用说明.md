## raspa-scale 使用说明与中断后恢复

`raspa-scale` 用于在不重跑前处理流程的情况下，动态调整高通量计算的并发度（扩容/缩容），并在作业被打断后自动补齐缺失的作业，保证任务最终跑完。

### 能解决什么问题
- **动态扩缩容**：运行过程中临时增加/减少并发，避免手工 scancel/重提。
- **自动补救**：节点或队列异常导致作业被取消时，自动识别缺口并补交。
- **配置继承**：确保补交作业继承原始高通量配置；恢复时优先读取任务目录下的 `.raspa_config.yaml`。
- **资源优化**：在超线程节点上，自动将多个 Worker 打包进单个 SLURM Job，充分利用 ThreadsPerCore 资源。
- **死锁自愈**：自动清理因强制中断（如 scancel）导致的陈旧锁文件和卡死的队列指针。

### 基本用法
在任务子目录（含 `mc*` 任务）下执行：
- `raspa-scale`：默认先展示资源与任务概览，然后进入模式选择（含查看任务状态入口）。
- `raspa-scale -i`：强制进入交互模式（与默认行为一致，适合脚本显式说明）。
- `raspa-scale -a <并发数>`：直接写入上限并自动扩/缩容。
- `raspa-scale --limit-only <并发数>`：只写入 `.raspa_worker_limit`，不提交流程变更。
- `raspa-scale -y`：无交互自动采用推荐并发并执行自动扩/缩容（适合无终端或 CI）；默认会把“当前目录运行中 + 集群估计空闲线程数”写入 `.raspa_worker_limit`。
- `RASPA_SCALE_RECOMMEND=auto|run_idle|idle|full`：控制“推荐并发”策略；默认 auto（按“当前目录运行中 + 集群空闲”推荐，且不超过任务总数）。
- `RASPA_SCALE_SCAN_JOBS=<N>`：并行扫描任务目录的线程数（默认自动使用最多 32 线程；设为 1 可禁用并行）。
- `RASPA_SCALE_SCAN_MODE=auto|fast|verify`：任务统计模式；auto 在任务很多时自动切换到 fast（不逐目录检查 simulation.*）。
- `RASPA_SCALE_SCAN_FAST_THRESHOLD=<N>`：auto 模式触发 fast 的阈值（默认 2000）。
- `RASPA_SCALE_SCAN_CACHE_SEC=<N>`：任务统计缓存秒数（默认 15，避免脚本内多次重复扫描）。
- `RASPA_SLURM_FREE_POLICY=alloc_ht|alloc|min|load`：控制“可用线程数”的估算策略（SLURM）。  
  - `alloc_ht`（默认）：在 **超线程节点(T>1)** 取 `min(alloc, load)`，其余节点按 `alloc`。  
  - `alloc`：仅按分配量估算，等价于 `free = total - allocated - other`。  
  - `min`：所有节点取 `alloc` 与 `load` 的保守最小值，避免非 SLURM 负载干扰。  
  - `load`：所有节点仅按负载估算，适合想严格避开系统负载时使用。
- `raspa-scale kill`：进入终止任务的交互菜单（按用户/范围/列表）。
- `raspa-scale kill -u <用户名>`：终止指定用户的全部 SLURM 任务。
- `raspa-scale kill -n <node[:count],...> [-c <count>]`：按节点终止运行中的任务（支持多个节点与数量）。
- `raspa-scale kill -r <开始-结束>`：按作业ID范围终止。
- `raspa-scale kill -l <id1,id2,...>`：按作业ID列表终止。

示例：
- `raspa-scale -a 256`
- `raspa-scale --limit-only 128`
- `raspa-scale -y`
- `raspa-scale kill -n worker-node-01:10,worker-node-02:5`
- `raspa-scale kill -n worker-node-01,worker-node-02 -c 3`

菜单含义：
- **模式菜单**：`1` 自动扩缩容（写入并执行）；`2` 终止任务（按用户/范围/列表）；`3` 查看任务状态；`q` 退出。
- **终止任务菜单**：`u` 按用户；`r` 按范围；`l` 按列表；`q` 退出。

### 脚本与模板位置
- 提交脚本默认使用 `RASPA_TOOL_DIR/scripts/shell/entrypoints/submit.sh`，不再复制 `scripts/shell` 下脚本到工作目录。
- Worker 执行脚本优先来自 `RASPA_TOOL_DIR/scripts/shell/workers/runjobs*.sh`，可通过 `RASPA_TOOL_DIR` 覆盖工具目录。
- 工作目录主要保留队列与任务数据：`.raspa_queue`、`.raspa_worker_limit`、`.raspa_jobs.list`、`mc*` 等。

### 节点优先级配置（node_priorities）

`raspa-scale` 在生成节点分配计划时，**只读取任务目录下的 `.raspa_config.yaml`**，不再回退到其他路径。

配置示例（`.raspa_config.yaml`）：
```yaml
calculation:
  node_priorities:
    master-node: 1
    worker-node-01: 3
    worker-node-02: 2
    worker-node-03: 4
```
数值越大优先级越高。若 `.raspa_config.yaml` 不存在或未配置 `node_priorities`，工具会在终端输出提示，并按集群可用线程数自动分配。

### 限定节点范围（allowed_nodes）

如果你不是想“优先用某些节点”，而是想“只能在某些节点上跑”，请在任务目录下的 `.raspa_config.yaml` 增加 `allowed_nodes`。

配置示例（只允许一个节点）：
```yaml
calculation:
  allowed_nodes:
    - worker-node-01
```

配置示例（允许多个节点，并在允许范围内继续按优先级排序）：
```yaml
calculation:
  allowed_nodes:
    - worker-node-01
    - worker-node-03
  node_priorities:
    worker-node-03: 4
    worker-node-01: 2
```

说明：
- `allowed_nodes` 是白名单，未列出的节点不会进入 `raspa-scale` 的节点分配计划。
- `node_priorities` 只在白名单内部生效；它不能代替白名单。
- 若白名单节点当前都没有可用资源，`raspa-scale` 不会回退到其他节点补交。
- 也可用环境变量临时覆盖：`export RASPA_ALLOWED_NODES=\"worker-node-01,worker-node-03\"`。
- 该白名单同时作用于高通量模式和参数筛选模式的小批量初始提交。
- 当 `raspa-scale` 发现你设置的目标并发低于当前 `__running`，且配置了 `allowed_nodes` 时，会先优先终止白名单外节点上的当前项目作业，再决定是否继续缩容或回补到白名单节点。
- 当目标并发高于当前 `__running` 时，`raspa-scale` 只会把新增作业补到白名单节点上，用这些节点的空闲核补足并发。

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
3. **配置读取优先级**：
   - Worker 恢复任务时，优先读取当前任务根目录下的 `.raspa_config.yaml`。
   - 若不存在，再尝试当前目录 `config.yaml`，最后才回退到 `~/.raspa_tools/config.yaml`。
   - 因此恢复历史任务时，应该修改工作目录中的配置快照，而不是只改工具目录里的原始配置。
4. **打包策略 (Packing)**：
   - 在支持超线程的节点（如 ThreadsPerCore=2），`raspa-scale` 会自动生成 `pack_size=2` 的作业。
   - 例如：提交 1 个 SLURM Job，申请 2 个 CPU 线程，内部启动 2 个 Worker 并发计算。
   - 日志会显示：`节点分配计划(线程->作业): nodeA:20 -> nodeA:10`。
5. **线程 vs 物理核显示**：
   - 资源与推荐并发默认以 **CPU线程数=worker并发数** 统计。
   - 若节点为超线程（ThreadsPerCore>1），日志会显示 `线程/核` 形式，例如：  
     `总256线程/128核, 已分配144线程/72核, 估计可用112线程/56核`。
6. **死锁处理**：
   - **锁超时**：默认 30秒。若作业被杀导致 `mcX.lock` 残留，新 Worker 会在 30s 后自动接管。
   - **指针重置**：若队列指针（`next_id`）已耗尽但仍有大量回滚任务（Pending），`raspa-scale` 会自动删除指针，触发 Worker 全量重新扫描。

### 任务标记为 __failed 后续算（pyMSER / 模拟异常）

当前默认策略下，pyMSER 成功写出统计后会返回成功；即使平衡后样本数低于 `target_cycles`，也只会记录 `mser_stats_below_target:当前/目标`，不会因此标记为 `__failed`。

只有以下情况通常会产生 `__failed`：
- RASPA 模拟本身失败或没有输出文件。
- pyMSER 解析/统计异常（查看 `auto_mser.log` 中的 traceback）。
- 显式设置 `extend_until_target: true` 后，自动续跑过程失败。

如果已启用 `extend_until_target: true`，任务目录内已有 `restart_*.json` 和 `mser_timeseries.csv` 时，可以直接从断点续算，无需重新生成输入。

**操作步骤：**

1. **确认是否真的需要强制补足 target_cycles**：多数筛选任务只需要 pyMSER 的 `t0`、平均值和不确定度，不需要强制补足生产样本数。此时保持：
   ```yaml
   mser:
     extend_until_target: false
   ```

2. **如果需要续跑补足 target_cycles**：找到任务目录下的配置快照 `.raspa_config.yaml`，设置 `extend_until_target: true`，并将 `mser.max_iter` 改大（如 200）：
   ```bash
   # 注意：要改的是任务目录下的快照，不是 .raspa_tools/config/ 下的原始配置
   # 快照路径示例：
   /home/zjp/raspa2-calc/work/<output_directory>/.raspa_config.yaml
   ```
   修改内容：
   ```yaml
   mser:
     extend_until_target: true
     max_iter: 200   # 原来是 50
   ```
   Worker 每次迭代都会重新读取此文件，**正在运行的 worker 无需重启**即可生效。

   如果还要同时调整 `target_cycles`、`add_cycles`、`uncertainty` 等参数，也应当改这一份快照，例如：
   ```yaml
   mser:
     extend_until_target: true
     target_cycles: 1000
     add_cycles: 600
     max_iter: 200
   ```

3. **去掉 `__failed` 后缀**，让 worker 重新认领：
   ```bash
   # 单个任务
   mv mc123__failed mc123

   # 批量（所有 failed 任务）
   for d in mc*__failed; do mv "$d" "${d%__failed}"; done

   # 只 reset 特定压力点（list-mode，COV_* 命名）
   for p in 1000 3000 5000; do
     mv COV_12_T_423_P_${p}__failed COV_12_T_423_P_${p}
   done
   ```

4. **如需按 `mser_timeseries.csv` 的最大 `cycle` 直接判定完成，先统一筛一遍所有非 `__done` 目录**：
   - 适用于你已经接受“达到某个 cycle 阈值即可视为完成”的场景。
   - 建议先把 `__running` / `__failed` 恢复为无后缀目录，再统一处理，避免漏掉已经回滚成 `mcX` 的目录。
   - 下例会把所有“非 `__done` 且 `mser_timeseries.csv` 中最大 `cycle > THRESHOLD`”的目录改成 `__done`：
   ```bash
   THRESHOLD=12000
   python - <<'PY'
   import csv, glob, os

   threshold = float(os.environ.get("THRESHOLD", "12000"))
   for d in sorted(glob.glob("mc[0-9]*")):
       if d.endswith("__done"):
           continue
       csv_path = os.path.join(d, "mser_timeseries.csv")
       if not os.path.isfile(csv_path):
           continue

       mx = None
       with open(csv_path, newline="", encoding="utf-8") as fh:
           reader = csv.reader(fh)
           header = next(reader, None)
           idx = None
           if header:
               for i, key in enumerate(header):
                   if str(key).strip().lower() == "cycle":
                       idx = i
                       break
           if idx is None:
               continue

           for row in reader:
               if idx >= len(row):
                   continue
               value = str(row[idx]).strip()
               if not value:
                   continue
               try:
                   val = float(value)
               except Exception:
                   continue
               if mx is None or val > mx:
                   mx = val

       if mx is not None and mx > threshold:
           dst = d + "__done"
           if not os.path.exists(dst):
               os.rename(d, dst)
               print(f"{d} -> {dst} (max_cycle={mx})")
   PY
   ```

4. **从正确目录运行 raspa-scale**：必须在包含 `.raspa_queue/` 和 `.raspa_worker_limit` 的那一层目录下运行，而不是子目录：
   ```bash
   cd /home/zjp/raspa2-calc/work/<output_directory>
   raspa-scale -y
   ```
   - `raspa-scale -y`：按当前集群剩余可用线程数自动写入 `.raspa_worker_limit` 并补交。
   - `raspa-scale -a <并发数>`：手工指定并发上限。
   - 交互模式也可以：`raspa-scale` 或 `raspa-scale -i`。

**注意事项：**
- Worker 会从 `output/restart_*.json` 接续上次的模拟，不会从头重跑。
- 如果 `mser.enable` 在快照里是 `false`，需要同时改为 `true`，否则 worker 不会调用 pyMSER。
- list-mode（`COV_*` 命名）的任务队列在 `output_directory` 这一层，不在 `MIL-47_ASR_pacman/` 等子目录下，raspa-scale 要在正确层级运行。
- 文档示例统一使用“选项在前”的形式，例如 `raspa-scale -a 256`。


1. 进入任务目录：`cd /home/zjp/raspa2-calc/work/<子目录>`。
2. 查看现状：`raspa-status`。
   - 关注 `运行中` 和 `待处理` 数量。
   - 确认 `SLURM活跃` 是否符合预期。
3. 如需修改恢复参数，先编辑 `./.raspa_config.yaml`，不要只改 `.raspa_tools/config/` 下的原始配置。
4. 如需按 `cycle` 阈值直接收敛为完成态，先执行上面的 `mser_timeseries.csv` 筛选脚本。
5. 执行恢复并设定目标并发：`raspa-scale -y`、`raspa-scale -a <并发数>` 或 `raspa-scale -i`。
   - 工具会自动检测环境、清理死锁指针、重建 `.raspa_jobs.list`、补齐缺口编号。
   - 如果之前有大量任务被 `scancel`，工具会提示 `自动重置指针以加速认领`。
   - 也可直接运行 `raspa-scale` 后选择模式 `1` 进入扩缩容流程。
6. 验证效果：
   - 等待约 10-30 秒。
   - 再次运行 `raspa-status`，确认 `运行中` 数量开始上升并接近 `SLURM活跃` 数。

### 常见问题
- **Q: 为什么 raspa-status 显示的运行数远小于提交数？**
  A: 作业正在排队，或正在争抢任务锁。新版脚本已优化锁竞争，通常在 1 分钟内会同步。如果长时间不涨，请重新运行 `raspa-scale -a` 触发指针重置。
- **Q: 为什么 mc50 之后的任务一直不跑？**
  A: 可能是旧的锁文件导致。`raspa-scale` 现已内置自动重置逻辑，重新运行一次扩容即可解决。
- **Q: 缩容后目录变回 mcX 了，但新作业不认领？**
  A: 同上，这是因为队列指针已扫过这些 ID。重新运行 `raspa-scale` 会自动删除 `next_id`，强制 Worker 回头扫描。
