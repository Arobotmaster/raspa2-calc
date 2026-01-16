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
- `raspa-calc`/`raspa-scale`/`job_templates`/脚本执行所需的读写都在 NVMe 上完成。
- `work/` 是高通量任务最密集的读写目录，**必须**在 NVMe 上。

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

已在 `raspa-calc`、`raspa-scale`、`job_templates/tasksrun.sh` 中加入剩余空间检查。

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

