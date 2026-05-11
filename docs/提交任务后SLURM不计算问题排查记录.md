# 提交任务后 SLURM 不计算问题排查记录

## 1. 现象

本次问题出现在 `lxq-CO2` 任务。

用户侧看到的现象是：

- `raspa-calc` 输出“提交完成”，例如：
  - `✅ Job array 87724 提交完成（1-2）`
- 但任务目录内仍然是：
  - `待处理 2`
  - `运行中 0`
  - `已完成 0`
- `raspa-status -d /home/zjp/raspa2-calc/work/lxq-CO2` 显示没有任何任务真正开始
- `squeue` 里很快看不到对应作业，容易误判成“已经算完了”

需要特别注意：

- `submit.sh` 在 `sbatch` 成功返回后就会退出
- 因此“提交脚本结束”只代表“提交动作完成”，**不代表模拟已经开始**

## 2. 排查过程中的关键结论

### 2.1 不是 `raspa3` 本身坏了

在任务目录内手动执行：

```bash
cd /home/zjp/raspa2-calc/work/lxq-CO2/mc1
conda activate raspa3
raspa3
```

可以正常启动模拟，并生成：

- `output/`
- `restart_data.bin`
- `bias_factors/`

说明：

- `simulation.json`
- `force_field.json`
- 分子 JSON
- `raspa3` conda 环境

本身是可用的。

### 2.2 不是 SLURM 基础功能坏了

使用最小 `sbatch` 单作业和最小 `sbatch --array` 测试时，作业都能正常 `COMPLETED`。

说明：

- SLURM 调度器正常
- `sbatch --array` 机制本身正常
- 日志路径本身也不是根因

### 2.3 出问题的作业其实是启动后很快失败

用 `scontrol show job 87727` 检查后可以看到：

- `JobState=FAILED`
- `Reason=NonZeroExitCode`
- `ExitCode=1:0`
- 作业实际落在 `worker-node-02`

这说明它不是“没提交上”，而是：

1. 已经被 SLURM 接收
2. 已经被调度到计算节点
3. 在节点上很快失败退出

### 2.4 关键异常在 `worker-node-02`

登录 `10.10.14.11`（即 `worker-node-02`）后发现：

```bash
grep raspa2-calc /proc/mounts
```

没有任何输出。

但这台机器本应看到两层 NFS 挂载：

- `10.10.14.12:/srv/raspa2-calc -> /home/zjp/raspa2-calc`
- `10.10.14.12:/srv/raspa2-calc-work -> /home/zjp/raspa2-calc/work`

实际却是：

- `/home/zjp/raspa2-calc` 指向本地旧目录
- `.raspa_tools`、`docs/`、脚本版本与当前主节点不一致
- `work/` 也不是共享工作区

因此 `worker-node-02` 上运行的作业，看到的并不是当前共享代码树和共享任务目录。

## 3. 根因

根因是：

- `worker-node-02` 的 NFS 挂载失效
- 但本地仍然残留了一个旧的 `/home/zjp/raspa2-calc` 目录
- 导致作业在该节点上使用了**错误的本地旧目录**

这会造成一系列问题：

- 提交脚本版本不一致
- `.raspa_tools` 下的脚本/文档/配置不一致
- `work/` 不是共享目录，任务状态和其他节点不一致
- 作业虽然被调度了，但实际执行环境错误，最终很快 `FAILED`

这也是为什么：

- `lxq-CO2` 提交后不计算
- `raspa-scale` 行为看起来异常
- 但在任务目录里手动跑 `raspa3` 又是正常的

## 4. 修复步骤

在 `worker-node-02` 上执行：

```bash
sudo umount -fl /home/zjp/raspa2-calc/work || true
sudo umount -fl /home/zjp/raspa2-calc || true
sudo systemctl daemon-reload
sudo mount /home/zjp/raspa2-calc
sudo mount /home/zjp/raspa2-calc/work
```

修复后验证：

```bash
grep raspa2-calc /proc/mounts
ls -l /home/zjp/raspa2-calc/.raspa_tools/docs/存储架构说明_NVMe_NFS_分层存储.md
```

期望看到：

- `/home/zjp/raspa2-calc` 已来自 `10.10.14.12:/srv/raspa2-calc`
- `/home/zjp/raspa2-calc/work` 已来自 `10.10.14.12:/srv/raspa2-calc-work`
- 关键文件时间戳与主节点一致

## 5. 修复后的结果

用户在修复 NFS 后重新提交 `lxq-CO2`，任务已能正常运行，例如：

```text
87740_1    normal raspa_ar      zjp  R       0:25      1 worker-node-02
```

这说明：

- `worker-node-02` 已经能看到正确的共享目录
- 作业可以在该节点上正常启动计算

## 6. 本次顺手做的提交策略调整

为了让 `squeue` 中的作业名更接近日常使用习惯，已将：

- `submit.sh` 的默认提交模式从 `auto`
- 改为 `loop`

效果是：

- 默认情况下优先逐个提交
- `NAME` 更容易保持为数字 worker 名，而不是统一显示为 `raspa_array`

如需恢复数组提交，可显式设置：

```bash
export RASPA_SUBMIT_MODE=array
```

## 7. 以后遇到“提交成功但不计算”时的最短排查顺序

按下面顺序查最快：

1. 先确认是否只是“提交脚本退出”，而不是真正完成计算

```bash
raspa-status -d /home/zjp/raspa2-calc/work/任务目录
```

2. 查看作业是否真实失败

```bash
scontrol show job <jobid>
```

重点看：

- `JobState`
- `Reason`
- `ExitCode`
- `NodeList`

3. 到实际运行节点检查 NFS 挂载

```bash
grep raspa2-calc /proc/mounts
```

4. 确认该节点看到的是共享目录，不是本地旧目录

```bash
ls -ld /home/zjp/raspa2-calc /home/zjp/raspa2-calc/work
ls -l /home/zjp/raspa2-calc/.raspa_tools/docs/存储架构说明_NVMe_NFS_分层存储.md
```

5. 如果缺挂载，按第 4 节重新挂载

## 8. 相关文档

- [存储架构说明_NVMe_NFS_分层存储.md](/home/zjp/raspa2-calc/.raspa_tools/docs/存储架构说明_NVMe_NFS_分层存储.md)
- [SLURM集群基础构建与维护.md](/home/zjp/raspa2-calc/.raspa_tools/docs/SLURM集群基础构建与维护.md)
- [高通量计算模式使用说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/高通量计算模式使用说明.md)
- [raspa-scale使用说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/raspa-scale使用说明.md)
