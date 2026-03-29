# 存储架构说明：NVMe NFS（在线）+ HDD NFS（归档）

本项目的最终目标是：**运行 `raspa-calc` 时所有脚本/队列/任务目录的文件读写都很快，且在所有节点体验一致**。因此将高频读写放到 NVMe，HDD 仅用于归档/历史保留。

## 1. 设计原则

- **在线计算（快）**：所有节点共享同一份目录树，用于脚本运行、任务提交、队列锁文件、任务目录读写。
- **归档存储（大）**：把已完成或不常用的目录迁移到 HDD，避免占满 NVMe。
- **路径一致**：所有节点都通过同一路径访问，避免修改大量脚本和配置。

## 2. 当前目录与导出（NFS 服务器：`10.10.14.12`）

### 2.1 NVMe（在线计算区）

NFS 导出：
- `10.10.14.12:/srv/raspa2-calc` → 客户端挂载到 `/home/zjp/raspa2-calc`
- `10.10.14.12:/srv/raspa2-calc-work` → 客户端挂载到 `/home/zjp/raspa2-calc/work`

说明：
- `raspa-calc`/`raspa-scale`/`.raspa_tools` 脚本位于代码区（NVMe），`scripts/shell` 下脚本不再复制到 `work/`。
- 高频读写集中在 `work/`（队列锁文件与任务目录），**必须**在 NVMe 上。

### 2.1.1 为什么 work 目录要单独挂载？（Mount Overlay 机制）

你可能会疑惑：`/srv/raspa2-calc` 里明明也有 `work` 子目录，为什么还要再挂载一次 `/srv/raspa2-calc-work`？

这是有意设计的**挂载覆盖（Mount Overlay）**：

1.  **服务器端物理分离**：
    - `/srv/raspa2-calc`（代码层）：存放脚本、配置。其下的 `work/` 只是一个空目录（挂载点）。
    - `/srv/raspa2-calc-work`（数据层）：存放真实的计算数据。
2.  **客户端统一视图**：
    - 客户端先挂载代码层到 `/home/zjp/raspa2-calc`。
    - 再把数据层挂载到 `/home/zjp/raspa2-calc/work`，**覆盖**原本的空目录。
3.  **优势**：
    - **灵活扩容**：如果未来数据量暴涨，管理员可以把 `/srv/raspa2-calc-work` 迁移到另一块更大的硬盘，而**无需修改任何客户端脚本或路径**。
    - **性能调优**：可以针对数据目录单独设置 NFS 参数（如更激进的缓存策略），而不影响代码目录的安全性。

### 2.2 HDD（归档区，仅保留历史）

NFS 导出：
- `10.10.14.12:/shared/raspa2-calc/work_hdd_backup_20260115_224850`
  → 客户端挂载到 `/home/zjp/raspa2-calc/work_hdd_backup_20260115_224850`

说明：
- 该目录用于保存旧项目/历史结果/不再需要频繁读写的数据。
- HDD 上大量小文件的 `rm -rf` 仍可能很慢，这是硬件特性决定的；建议在 NVMe `work/` 下清理，或在服务器本机处理归档目录。

## 3. 客户端验证（任一节点）

```bash
mount | grep '/home/zjp/raspa2-calc'
showmount -e 10.10.14.12
```

期望看到：
- `/home/zjp/raspa2-calc` 来自 `/srv/raspa2-calc`
- `/home/zjp/raspa2-calc/work` 来自 `/srv/raspa2-calc-work`
- `/home/zjp/raspa2-calc/work_hdd_backup_20260115_224850` 来自 `/shared/.../work_hdd_backup_20260115_224850`

## 4. 归档与清理建议

### 4.1 把计算完成的目录迁移到 HDD

注意：NVMe 与 HDD 是不同文件系统（不同 NFS export），直接 `mv` 可能失败（跨设备）。推荐用 `rsync`：

```bash
src="/home/zjp/raspa2-calc/work/你的任务目录"
dst="/home/zjp/raspa2-calc/work_hdd_backup_20260115_224850/你的任务目录"

rsync -aHAX --numeric-ids "$src/" "$dst/"
rm -rf "$src"
```

### 4.2 无需保留的目录：优先在 NVMe work 下删除

```bash
rm -rf /home/zjp/raspa2-calc/work/不需要的目录
```

若目录极大且删除很慢，建议“先改名、后台删”：

```bash
cd /home/zjp/raspa2-calc/work
mv bigdir .trash_bigdir_$(date +%Y%m%d_%H%M%S)
nohup rm -rf .trash_bigdir_* >/tmp/rm_bigdir.log 2>&1 &
```

## 5. 空间保护（防止 NVMe 被写满）

已在 `raspa-calc`、`raspa-scale`、`RASPA_TOOL_DIR/scripts/shell/entrypoints/submit.sh` 中加入剩余空间检查。

默认：
- 阈值 50GB
- 空间不足仅提醒（不阻断）

强制阻断（推荐用于生产环境）：

```bash
export RASPA_MIN_FREE_ACTION=abort
export RASPA_MIN_FREE_GB=50
```

也可写入 `.raspa_tools/config.yaml`：

```yaml
environment:
  work_dir_min_free_gb: 50
  work_dir_min_free_action: "abort"
```

## 6. 常见故障：Stale file handle

现象：
- `df`/`ls`/脚本执行卡住或提示 `Stale file handle`

处理（在该节点执行）：

```bash
sudo umount -fl /home/zjp/raspa2-calc/work || true
sudo umount -fl /home/zjp/raspa2-calc || true
sudo mount -a
```

或使用项目脚本（需保证脚本文件可访问）：

```bash
bash /home/zjp/raspa2-calc/.raspa_tools/nfs/nfs_client_setup.sh --recover
```

## 7. 常见故障：NFS 服务端无响应（完整排查与恢复流程）

### 7.1 典型症状

- 客户端所有 NFS 目录下的命令（`ls`、`stat`、`df` 等）全部卡死
- `dmesg | grep nfs` 显示大量 `server X not responding, still trying`
- Slurm 任务状态卡在 RUNNING 但 CPU idle 高、任务不前进
- `slurmstepd` 会因 NFS I/O 超时而自动取消任务（`CANCELLED`），此时需重新提交
- NFS 服务端正常（`nfsiostat` 有 ops/s），但客户端完全无法访问

### 7.2 诊断顺序

**Step 1：确认是哪台 NFS 服务端出了问题**

```bash
# 查看当前节点的 NFS mount 来源（每个节点都要查）
cat /proc/mounts | grep raspa2-calc

# 确认 NFS server IP（如 10.10.14.12）
# 所有客户端看到的 server IP 是一致的
```

**Step 2：检查 NFS 服务端状态（server 节点执行）**

```bash
# 查看 NFS 服务端内核日志
dmesg | grep -i nfs | tail -20

# 查看 NFS ops 是否有积压
nfsiostat 2>/dev/null | head -20

# 确认 NFS 进程是否存活
ps aux | grep -E 'nfsd|rpc|mountd' | grep -v grep

# 检查服务端 export 是否正常
showmount -e localhost
```

**Step 3：检查客户端 mount overlay 是否正确**

这是**最容易被忽视的故障点**。每个客户端节点都必须有两层挂载：

```bash
# 正确情况（应该看到两条）：
# /home/zjp/raspa2-calc  来自  /srv/raspa2-calc
# /home/zjp/raspa2-calc/work  来自  /srv/raspa2-calc-work

cat /proc/mounts | grep raspa2-calc
```

**常见错误**：只有 `/home/zjp/raspa2-calc` 挂载了，但 `/home/zjp/raspa2-calc/work` 没有单独挂载，导致只能看到 `/srv/raspa2-calc` 下的空目录，而不是真实数据。

### 7.3 恢复流程

#### 阶段 A：修复 NFS 服务端（server 节点执行，如 worker-node-03）

```bash
# 如果 dmesg 显示 "server not responding" 且持续超过几分钟，
# 重启 NFS 服务是最有效的办法（不会中断已有连接）

sudo systemctl restart nfs-server rpcbind

# 验证
dmesg | grep -i nfs | tail -10
# 应该看到 "NFSD: all clients done reclaiming" 表示所有客户端已重连
```

#### 阶段 B：修复客户端挂载（每个出问题的节点执行）

```bash
# 1. 检查 /proc/mounts 确认当前挂载状态
cat /proc/mounts | grep raspa2-calc

# 2. 如果 work 目录缺失挂载（只有第一层挂载正常）
#    先卸载可能损坏的挂载（即使没显示 mounted 也执行，|| true）
sudo umount -fl /home/zjp/raspa2-calc/work || true
sudo umount -fl /home/zjp/raspa2-calc || true

# 3. 重新挂载（必须先挂载代码层，再挂载数据层）
sudo mount -a
# 或手动分别挂载：
# sudo mount -t nfs4 -o rw,noatime,nodiratime,vers=4.2 10.10.14.12:/srv/raspa2-calc /home/zjp/raspa2-calc
# sudo mount -t nfs4 -o rw,noatime,nodiratime,vers=4.2 10.10.14.12:/srv/raspa2-calc-work /home/zjp/raspa2-calc/work

# 4. 如果 fstab 有残留旧配置导致 systemd 用旧版本
sudo systemctl daemon-reload

# 5. 验证两层挂载都正确
cat /proc/mounts | grep raspa2-calc
# 期望：
# 10.10.14.12:/srv/raspa2-calc   /home/zjp/raspa2-calc  nfs4 ...
# 10.10.14.12:/srv/raspa2-calc-work  /home/zjp/raspa2-calc/work  nfs4 ...

# 6. 验证数据可访问
ls /home/zjp/raspa2-calc/work/xyleneLCD-trappe-conventional-lt1000/
# 应该能看到 mc*__done 目录，而不只是 1log
```

#### 阶段 C：恢复 Slurm 节点调度

```bash
# master-node 如果处于 drain 状态，需要恢复
sudo scontrol update nodename=master-node state=resume

# 确认节点状态
sinfo -n master-node
```

### 7.4 快速验证脚本（任一客户端节点）

```bash
#!/bin/bash
# 放在 ~/.bashrc 或 alias 里方便调试
nfs_check() {
    echo "=== /proc/mounts ==="
    grep raspa2-calc /proc/mounts
    echo ""
    echo "=== dmesg NFS errors ==="
    dmesg | grep -i nfs | tail -5
    echo ""
    echo "=== 验证数据可访问 ==="
    timeout 3 ls /home/zjp/raspa2-calc/work/ 2>/dev/null | head -5 || echo "NFS 挂载可能有问题！"
}
alias nfs-check='nfs_check'
```

### 7.5 使用项目脚本恢复（推荐）

项目已内置恢复脚本，自动处理以上步骤：

```bash
# 客户端恢复（自动处理 umount + remount）
bash /home/zjp/raspa2-calc/.raspa_tools/nfs/nfs_client_setup.sh --recover

# 恢复后重启 slurmd（仅 master-node/控制节点，且无运行中任务时）
bash /home/zjp/raspa2-calc/.raspa_tools/nfs/nfs_client_setup.sh --recover --restart-slurmd
```

> **注意**：`--restart-slurmd` 会中断正在调度的任务，只有在确认无重要任务运行时才使用。
