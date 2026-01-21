# SLURM (CR_CORE) + 超线程节点满载说明（RASPA 单线程高通量）

## 1. 背景与问题现象

- **RASPA 是单线程模拟程序**：每个模拟任务只能使用 **1 个 CPU 线程**。
- 本集群节点混合：
  - **单线程节点**（`ThreadsPerCore=1`）：1 个物理核 = 1 个线程 → 同时跑 1 个 RASPA 任务
  - **超线程节点**（`ThreadsPerCore=2`，例如 `master-node` / `worker-node-02`）：1 个物理核 = 2 个线程 → 同时可跑 2 个 RASPA 任务
- 现象（修复前）：
  - `pe` 显示 `Use/Tot` 似乎已满，但 `top` 看到 CPU 仍有大量 `id`（空闲），**实际吞吐只有 ~50%**
  - 提交更多任务后出现 `ReqNodeNotAvail` / `Resources` 等等待原因

## 2. 根因：SLURM 的 `CR_CORE` 资源口径导致“每个作业占 2 线程但只跑 1 任务”

本集群 SLURM 配置为 `SelectTypeParameters=CR_CORE`（按 **物理核 core** 做为可消耗资源）。

在 **超线程节点**（`ThreadsPerCore=2`）上：

- 你提交作业时写 `--cpus-per-task=1`（看起来是 1 个 CPU）
- 但 **SLURM 实际分配的是 1 个 core**，而 1 个 core 对应 **2 个 CPU(thread)**  
  因此会出现：
  - `ReqTRES=cpu=1`
  - `AllocTRES=cpu=2` / `NumCPUs=2`

如果 1 个 sbatch 作业里只启动 1 个 `raspa3`/`simulate` 进程，那么：

- SLURM 以为你用了 2 个线程（所以 `pe Use` 会快速“满”）
- 但 RASPA 只吃掉其中 1 个线程 → **另一条超线程空转** → `top` 看到 ~50% idle

> 这也解释了为什么你会看到 “`pe` 的 `Use=256` 但感觉只有 ~128 个任务在跑”：在 HT 节点上 **每个作业按 2 个 CPU(thread) 计费**，`Use` 统计的是 **分配的 CPU(thread)**，不是 job 数量。

## 3. 解决方案：在超线程节点上把多个 worker “打包”到同一个 sbatch 作业里

核心策略：

- **sbatch 仍然只申请 1 core**（保持 `--ntasks-per-node=1`、`--cpus-per-task=1` 不变）
- 但在 **同一个作业内部** 同时启动 `ThreadsPerCore` 个 worker（每个 worker 跑 1 个 RASPA 单线程任务）
  - 单线程节点：`ThreadsPerCore=1` → 1 个作业跑 1 个 worker（行为不变）
  - 超线程节点：`ThreadsPerCore=2` → 1 个作业跑 2 个 worker → **把 SLURM 分配到的 2 个线程吃满**

这样在 `CR_CORE` 下：

- `master-node` 仍然最多只能调度 **128 个“作业”(core)**（SLURM 的口径）
- 但每个作业里跑 2 个 RASPA worker → **并发任务数 = 128 * 2 = 256（满载全部线程）**

## 4. 代码实现要点（关键文件）

### 4.1 `job_templates/tasksrun.sh`

脚本位置约定（新版）：

- 提交脚本默认在 `RASPA_TOOL_DIR/job_templates`（未设置时为 `~/raspa2-calc/.raspa_tools/job_templates`）。
- 不再复制 `job_templates` 到工作目录；任务目录仅保存队列与 `mc*` 任务目录。
- `tasksrun.sh` 会把 `RASPA_TOOL_DIR` 传入作业环境，供提交脚本/worker 定位 `runjobs*.sh`。

主要做了三件事：

1) **检测调度器是否为 `CR_CORE`**
- 通过 `scontrol show config` 解析 `SelectTypeParameters`，只有检测到 `CR_CORE` 才启用打包逻辑（避免在其它集群配置下误伤）。

2) **检测每个节点的 `ThreadsPerCore`**
- 通过 `sinfo -N -h -o '%N|%z'` 获取拓扑（`%z` 为 `S:C:T`，其中 `T` 即 `ThreadsPerCore`）。

3) **把“worker 计划数”转换为“需要提交的 job 数”，并把多个 worker ID 写入同一个 job**
- 节点计划（`RASPA_NODE_PLAN` / `.raspa_node_plan`）里的数字按“线程/worker 数”理解。
- 在 `CR_CORE` 且 `ThreadsPerCore>1` 的节点上：  
  `jobs = ceil(workers / ThreadsPerCore)`
- 每个提交脚本会额外注入：
  - `RASPA_WORKER_ID`（该 job 的第一个 worker id，用于兼容旧逻辑）
  - `RASPA_WORKER_IDS`（CSV，例如 `130,131`，表示同一 job 内要跑的多个 worker）
- 日志会显示类似：`节点分配计划(线程->作业): master-node:130 -> master-node:65`

### 4.2 `job_templates/job_submit.sh`（以及运行时生成的 `job_submit_ht.sh`）

新增对 `RASPA_WORKER_IDS` 的解析：

- **脚本来源**：优先从 `RASPA_TOOL_DIR/job_templates` 读取 `runjobs.sh` / `runjobs_raspa3.sh`，仅在工具目录不可用时回退到工作目录同名脚本。
- **单 worker**：沿用 `srun --ntasks=1 --cpus-per-task=1` 启动 1 个 `runjobs.sh`
- **多 worker**：在同一个 batch step 里后台启动多个 `runjobs.sh` 并 `wait`
  - 这里刻意 **不使用多个 `srun` step**，因为在 `CR_CORE` 下多个 step 可能会按 core 串行分配资源，导致同一作业内无法并发跑满超线程

## 5. 达到的效果

- 超线程节点（`master-node`/`worker-node-02`）从“只能用一半算力”变为“**两条超线程都能被 RASPA 任务吃满**”
- 单线程节点行为不变
- `pe` 的 `Use` 会更符合实际“分配的 CPU(thread)”；在 HT 节点上看到 `Use` 增长更快是正常现象
- 整体可把集群并发拉到接近 **所有节点逻辑线程总数**（例如约 960 个并发任务）

## 6. 如何验证（建议命令）

### 6.1 确认 SLURM 是否为 CR_CORE
```bash
scontrol show config | egrep -i 'SelectTypeParameters|TaskPlugin'
```

### 6.2 查看节点 ThreadsPerCore
```bash
sinfo -N -h -o '%N %z'
```

### 6.3 验证某个作业在超线程节点上的 CPU 分配
```bash
scontrol show job <jobid> | egrep 'ReqTRES|AllocTRES|NumCPUs|NodeList'
```
期望看到：`ReqTRES=cpu=1` 但 `AllocTRES=cpu=2`（在 `ThreadsPerCore=2` 的节点上）。

### 6.4 用 top 观察真实负载
当任务数量足够时，超线程节点的 `top` 应该出现 **`id` 接近 0**（或显著低于修复前）。

---

## 7. 高通量模式任务分配逻辑（raspa-calc 高通量）

这一部分解释“高通量模式到底如何给每个节点分配任务”，以及日志里“节点计划/worker/job”的含义。

### 7.0 提交/分配/排队流程图（通用）

```
raspa-calc / parameter_screening
  -> RASPA_TOOL_DIR/job_templates/tasksrun.sh
     - 检测调度系统: SLURM / PBS / LOCAL
     - 选择提交模式:
         * SLURM array (无节点计划)
         * loop (有节点计划或 PBS/LOCAL)
     - 提交 job_submit.sh / pbs.sh / local.sh
        (注入 RASPA_WORK_DIR / RASPA_SUBDIR / RASPA_WORKER_IDS ...)
          -> RASPA_TOOL_DIR/job_templates/runjobs*.sh
             - 读取 .raspa_queue/ (next_id/last_id/next.lock/retry.list/tasks.list)
             - 认领任务: mcX -> mcX__running -> __done/__failed
             - 并发上限: .raspa_worker_limit
```

### 7.1 核心概念（非常重要）

- **任务（task）**：一个 `mcXXXX` 目录（一个结构/一个压力点/一个模拟）。
- **worker**：一个长期运行的取任务进程（最终会执行 `raspa3` 或 `simulate`，但一次只跑单线程）。
- **sbatch 作业（job）**：提交给 SLURM 的一个作业分配单元。
- 在本工具里：**“并发数/CPU核心数”本质上是想启动多少个 worker**，而不是一次性列出 `mc*` 并硬分配到某个节点。

### 7.2 节点层：如何决定每个节点放多少个 worker

高通量模式会先收集集群资源，然后生成一个节点分配计划（写到 `RASPA_NODE_PLAN` 和输出目录下的 `.raspa_node_plan`）：

1) **采集每节点资源（线程总数/已分配/负载）**
- 通过 `sinfo -N -h -o '%N|%c|%C|%O|%z'` 获取：
  - `total_cpus`（逻辑线程数）
  - `allocated_cpus` / `other_cpus`
  - `CPULoad`
  - `ThreadsPerCore`（来自拓扑 `%z = S:C:T`）
- 可选：设置 `RASPA_NODE_LOAD_SSH=true` 时，会用 `ssh <node> cat /proc/loadavg` 把“非 SLURM 提交的负载”也纳入 `CPULoad`（避免 `pe` 监控不到的情况）。

2) **计算每个节点的“可用线程数”**
- 基础空闲：`free_by_alloc = total - allocated - other`
- 负载修正：`free_by_load = total - ceil(load)`
- 取最保守：`free_cpus = min(free_by_alloc, free_by_load)`  
  这样能避免某节点存在非 SLURM 负载时被误判为空闲。

3) **应用节点优先级（可选）**
- 从 `config.yaml` 的 `environment.node_priorities` 或 `calculation.node_priorities` 读取权重。
- 排序规则大致为：优先级高 → 有效空闲多 → 空闲多 → 负载低。

4) **按两轮分配生成计划**
- 第 1 轮：使用“有效可用核（考虑负载/分配比例的降权）”分配。
- 第 2 轮：若并发还没分满，再用剩余 `free_cpus` 继续分配，确保低优先级但空闲的节点也会被用上。

最终得到类似：
`master-node:130,worker-node-01:37,...`

> 注意：这里的数字表示“要在该节点上放多少个 worker（线程/任务并发）”，不是 job 数。

### 7.3 提交层：节点计划如何变成实际的 sbatch 提交

提交由 `RASPA_TOOL_DIR/job_templates/tasksrun.sh` 完成（不再复制 `job_templates` 到工作目录）：

- **如果存在节点计划**：必须逐个提交（loop），因为需要对每个 job 写 `#SBATCH --nodelist=<node>`；这时会自动禁用 job array。
- **如果不存在节点计划**：可用 job array（由 SLURM 自己调度到各节点）。

在本集群 `CR_CORE` + 超线程节点的前提下，提交层还会做“worker 打包”：

- 节点计划的 `count` 仍按“worker 数/线程数”理解。
- 对于 `ThreadsPerCore=T>1` 的节点：  
  - 需要提交的 job 数：`jobs = ceil(count / T)`
  - 每个 job 内会注入 `RASPA_WORKER_IDS=w1,w2,...`（最多 T 个），同一 job 同时启动多个 worker 吃满 T 条超线程。

所以你会看到日志：
`节点分配计划(线程->作业): master-node:130 -> master-node:65`

它的意思是：
- 目标是在 `master-node` 上跑 **130 个 worker（130 个并发任务）**
- 但由于 `CR_CORE` 的“1 core = 2 threads”，需要提交 **65 个 job**，每个 job 内跑 2 个 worker

这也解释了为什么 `pe` 会显示 `Use=130/256`（而不是 65）：`pe Use` 统计的是 **已分配的 CPU(thread)**，65 个 job * 2 threads/job = 130 threads。

### 7.4 任务层：mc* 目录到底怎么分给 worker（不是按节点硬分配）

每个 worker 运行 `RASPA_TOOL_DIR/job_templates/runjobs.sh`（RASPA3 则用 `runjobs_raspa3.sh`），它们不会提前拿到“属于本节点的任务列表”，而是通过共享队列动态领取：

- 输出目录下有一个共享队列：`<output_dir>/.raspa_queue/`
  - `next_id` / `last_id`：指针队列（全局递增领取）
  - `retry.list`：失败或中断回滚的重试列表
  - `next.lock`：文件锁，保证多 worker 并发领取不冲突
  - `tasks.list`：list-mode 任务清单（参数筛选/批量任务会生成）
- worker 领取到一个 `mcX` 后，会把目录原子地重命名为 `mcX__running`，运行结束再改为 `__done` 或 `__failed`。

因此：
- “给节点分配任务”在实现上是 **给节点分配 worker 数量**；
- 真正的 `mc*` 任务分配是 **worker 之间抢队列**，天然实现负载均衡。

### 7.5 队列与提交文件速查

- `<output_dir>/.raspa_queue/next_id`：下一个可领取的任务编号
- `<output_dir>/.raspa_queue/last_id`：当前队列的最大编号
- `<output_dir>/.raspa_queue/next.lock`：指针锁（避免并发冲突）
- `<output_dir>/.raspa_queue/retry.list`：回滚/失败任务的重试队列
- `<output_dir>/.raspa_queue/tasks.list`：list-mode 任务清单（按相对路径）
- `<output_dir>/.raspa_worker_limit`：并发上限（raspa-scale 动态调整）
- `<output_dir>/.raspa_jobs.list`：JobId 与 worker 编号映射（供扩缩容追踪）
- `<output_dir>/mcX__running`：已被 worker 领取的任务目录（完成后变为 `__done`/`__failed`）
