# RASPA 多节点集群部署指南 (支持 RASPA2/RASPA3)

## 目录
- [1. 部署概述](#1-部署概述)
- [2. 环境准备](#2-环境准备)
- [2.3 UID/GID 一致性（强制）](#23-uidgid-一致性强制)
- [3. NFS共享存储配置](#3-nfs共享存储配置)
- [4. RASPA 版本配置](#4-raspa-版本配置)
- [5. 作业脚本优化](#5-作业脚本优化)
- [6. 环境变量配置](#6-环境变量配置)
- [7. 部署验证](#7-部署验证)
- [8. 使用指南](#8-使用指南)
- [9. 故障排除](#9-故障排除)
- [10. 部署检查清单](#10-部署检查清单)

---

## 1. 部署概述

### 1.1 项目背景
本部署指南用于配置 RASPA 高通量计算工具在 SLURM/PBS 集群上的多节点任务调度能力。支持 RASPA2 和 RASPA3 双版本，通过配置 NFS 共享存储和优化作业脚本，实现大规模 CPU 核心的充分利用。

### 1.2 版本支持

| 特性 | RASPA2 | RASPA3 |
|------|--------|--------|
| 输入文件 | `simulation.input` (文本) | `simulation.json` (JSON) |
| 额外文件 | 无 | `force_field.json`, 分子定义 `.json` |
| 执行命令 | `$RASPA_DIR/bin/simulate` | `raspa3` (conda 环境) |
| 输出目录 | `Output/System_0/*.data` | `output/*.txt` |
| 吸附量格式 | `Average loading absolute [mol/kg framework]` | `Abs. loading average [mol/kg-framework]` |

### 1.3 集群环境示例
- **操作系统**: Linux 8.10
- **调度器**: SLURM / PBS
- **节点配置**:
  - master-node: 控制节点
  - worker-node-01: 计算节点 (192核)
  - worker-node-02: 计算节点 (192核)
  - worker-node-03: 计算节点 (192核) + NFS服务器
  - worker-node-04: 计算节点 (384核)
- **总CPU核心数**: 960核

### 1.4 部署目标
- ✅ 支持 RASPA2/RASPA3 双版本切换
- ✅ 配置跨节点共享存储
- ✅ 实现多节点任务调度
- ✅ 充分利用集群计算资源

---

## 2. 环境准备

### 2.1 系统要求
```bash
# 检查操作系统版本
cat /etc/os-release

# 检查SLURM状态
sinfo -N

# 检查网络连通性
ping worker-node-01
ping worker-node-02
ping worker-node-03
```

### 2.2 依赖软件安装

#### 所有节点
```bash
# 安装NFS工具
sudo yum install -y nfs-utils --disablerepo=epel,docker-ce-stable

# 启动相关服务
sudo systemctl enable rpcbind nfs-client.target
sudo systemctl start rpcbind
```

#### RASPA3 专用 (所有计算节点)
```bash
# 创建 RASPA3 conda 环境
conda create -n raspa3 python=3.10
conda activate raspa3

# 安装 RASPA3 (根据官方文档)
pip install raspa3
# 或从源码编译安装
```

---

## 2.3 UID/GID 一致性（强制）

在 **Slurm + NFS（共享工作目录）** 的集群里，同一用户名必须在 **所有可能运行作业的节点** 上存在，并且 **UID/GID 完全一致**。否则常见问题包括：

- `scontrol show job <id>` 里作业 **0 秒失败**（例如 `RaisedSignal:53`），且工作目录下没有 `.out/.err` 或输出文件。
- 节点上 `ls -la` 显示目录/文件的 group 变成数字（例如 `1004`），或登录提示 `id: cannot find name for group ID ...`。
- Slurm 在启动作业时无法正确 setuid/setgid，作业会 `requeue` 或直接失败。

**快速检查（示例以 zjp 为例）：**

```bash
for n in master-node worker-node-01 worker-node-02 worker-node-03; do
  ssh "$n" 'hostname; id zjp; getent passwd zjp; getent group zjp'
done
```

**推荐做法：**

- 使用 LDAP/SSSD 统一账号；或
- 使用 Ansible 同步本地用户/组（本项目提供模板与说明：`/home/zjp/docs/ansible-user-sync/README.md`）。

---

## 3. NFS共享存储配置

### 3.0 推荐：用脚本自动配置/修复（更省心）

本项目提供 NFS 配置/修复脚本（支持修复 `Stale file handle`）：

```bash
# 单节点（在需要挂载的客户端节点执行）
bash /home/zjp/raspa2-calc/.raspa_tools/nfs/nfs_client_setup.sh

# 单节点修复（出现 Stale file handle / Slurm 作业 0 秒失败时）
bash /home/zjp/raspa2-calc/.raspa_tools/nfs/nfs_client_setup.sh --recover

# 批量分发/批量修复（在 NFS 服务器 10.10.14.12 上执行）
bash /home/zjp/raspa2-calc/.raspa_tools/nfs/nfs_setup_all_nodes.sh setup
bash /home/zjp/raspa2-calc/.raspa_tools/nfs/nfs_setup_all_nodes.sh recover --run
```

### 3.1 NFS服务器配置 (worker-node-03)

#### 3.1.1 创建共享目录
```bash
# 在worker-node-03上执行
sudo mkdir -p /shared/raspa2-calc
sudo mkdir -p /shared/raspa2-calc/{work,.raspa_tools}

# 重要：共享目录建议用固定的用户/组（UID/GID 必须在所有节点一致）
sudo chown -R zjp:zjp /shared/raspa2-calc

# 推荐开启 setgid：让新文件继承目录 group（避免跨节点出现 “数字 gid”/权限混乱）
sudo chmod 2775 /shared/raspa2-calc /shared/raspa2-calc/work /shared/raspa2-calc/.raspa_tools
```

> 💡 建议：避免把 `/shared` 的真实数据放在根分区（容易写满）。可以把真实数据放到大盘（如 `/home/shared/raspa2-calc`），再 bind-mount 回 `/shared/raspa2-calc`。
>
> ```bash
> sudo mkdir -p /home/shared/raspa2-calc
> sudo mount --bind /home/shared/raspa2-calc /shared/raspa2-calc
> echo "/home/shared/raspa2-calc /shared/raspa2-calc none bind 0 0" | sudo tee -a /etc/fstab
> sudo mount -a
> ```

#### 3.1.2 配置NFS导出
```bash
# 编辑/etc/exports文件
sudo vim /etc/exports

# 添加以下内容：
/shared/raspa2-calc 10.10.14.0/24(rw,sync,no_root_squash,no_subtree_check)
```

#### 3.1.3 启动NFS服务
```bash
# 启动并启用NFS服务
sudo systemctl enable nfs-server rpcbind
sudo systemctl start nfs-server rpcbind

# 重新加载导出配置
sudo exportfs -ra

# 验证导出状态
sudo exportfs -v
showmount -e localhost
```

### 3.2 NFS客户端配置 (所有其他节点)

#### 3.2.1 创建挂载点
```bash
# 在每个客户端节点执行
sudo mkdir -p /home/zjp/raspa2-calc
sudo chown zjp:zjp /home/zjp/raspa2-calc
```

#### 3.2.2 手动挂载测试
```bash
# 测试挂载
sudo mount -t nfs4 10.10.14.12:/shared/raspa2-calc /home/zjp/raspa2-calc

# 验证挂载
df -h | grep raspa
ls -la /home/zjp/raspa2-calc
```

#### 3.2.3 配置自动挂载
```bash
# 编辑/etc/fstab文件
sudo vim /etc/fstab

# 添加以下行：
10.10.14.12:/shared/raspa2-calc /home/zjp/raspa2-calc nfs4 defaults,_netdev,hard,timeo=600,retrans=2 0 0

# 测试fstab配置
sudo umount /home/zjp/raspa2-calc
sudo mount -a
```

---

## 4. RASPA 版本配置

### 4.1 配置文件设置

编辑 `.raspa_tools/config.yaml`：

```yaml
environment:
  # 工作目录
  work_dir: "/home/zjp/raspa2-calc/work"

  # ============ RASPA 版本选择 ============
  # 选择使用的 RASPA 版本: "raspa2" 或 "raspa3"
  raspa_version: "raspa3"

  # ============ RASPA2 专用配置 ============
  raspa_dir: "/home/zjp/anaconda3/pkgs/raspa2-2.0.50-h678ec8c_0"
  raspa2_cif_dir: "/path/to/raspa2/structures/cif"
  template_path: "/path/to/your/simulation.input"  # 留空使用默认模板

  # ============ RASPA3 专用配置 ============
  # RASPA3 conda 环境名称 (所有节点必须一致)
  raspa3_conda_env: "raspa3"

  # RASPA3 JSON 文件目录 (包含 force_field.json 和分子定义文件)
  raspa3_json_dir: "/home/zjp/raspa2-calc/.raspa_tools/raspa3json/CO2"

  # RASPA3 CIF 文件基础路径
  raspa3_cif_base_path: "/path/to/cif/files"

  # RASPA3 simulation.json 模板路径
  raspa3_template_path: "/home/zjp/raspa2-calc/.raspa_tools/raspa3json/CO2/simulation.json"
```

### 4.2 RASPA3 JSON 文件目录结构

```
raspa3_json_dir/
├── force_field.json    # 力场定义 (必须)
├── simulation.json     # 模拟配置模板
├── CO2.json            # CO2 分子定义
├── CH4.json            # CH4 分子定义
├── N2.json             # N2 分子定义
├── o-xylene.json       # 邻二甲苯分子定义
├── m-xylene.json       # 间二甲苯分子定义
├── p-xylene.json       # 对二甲苯分子定义
└── ...                 # 其他分子定义
```

### 4.3 RASPA3 Conda 环境配置

确保所有计算节点的 conda 环境名称一致：

```bash
# 检查所有节点的 raspa3 环境
for node in worker-node-01 worker-node-02 worker-node-03 worker-node-04; do
    echo "=== $node ==="
    ssh $node "conda activate raspa3 && which raspa3"
done
```

### 4.4 版本自动检测

程序会自动检测 RASPA 版本：
- 检测到 `simulation.json` → RASPA3
- 检测到 `simulation.input` → RASPA2

也可以在运行时手动选择版本覆盖配置。

---

## 5. 作业脚本优化

### 5.1 RASPA3 作业脚本

RASPA3 使用 conda 环境执行，作业脚本会自动：

1. 激活 raspa3 conda 环境
2. 检测 `simulation.json` 而非 `simulation.input`
3. 执行命令改为 `raspa3`

### 5.2 SLURM 作业模板示例

```bash
#!/bin/bash
#SBATCH --job-name=raspa3_htc
#SBATCH --output=1log/raspa_%A_%a.out
#SBATCH --error=1log/raspa_%A_%a.err
#SBATCH --array=1-100%50

# 激活 RASPA3 conda 环境
source ~/anaconda3/etc/profile.d/conda.sh
conda activate raspa3

# 执行任务
cd $WORK_DIR
./runjobs.sh $SLURM_ARRAY_TASK_ID $SLURM_ARRAY_TASK_COUNT
```

### 5.3 PBS 作业模板示例

```bash
#!/bin/bash
#PBS -N raspa3_htc
#PBS -o 1log/raspa_$PBS_JOBID.out
#PBS -e 1log/raspa_$PBS_JOBID.err

# 激活 RASPA3 conda 环境
source ~/anaconda3/etc/profile.d/conda.sh
conda activate raspa3

# 执行任务
cd $PBS_O_WORKDIR
./runjobs.sh $CPU $TOTAL_CPUS
```

---

## 6. 环境变量配置

### 6.1 统一环境变量

在所有节点的 `~/.bashrc` 文件中添加：

```bash
# RASPA 通用环境变量
export RASPA_WORK_DIR="/home/zjp/raspa2-calc/work"

# RASPA2 专用环境变量
export RASPA_DIR="/home/zjp/anaconda3/pkgs/raspa2-2.0.50-h678ec8c_0"

# RASPA3 conda 环境初始化
source ~/anaconda3/etc/profile.d/conda.sh

# 防止数学库线程冲突
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
```

### 6.2 重新加载环境
```bash
# 在所有节点执行
source ~/.bashrc

# 验证环境变量
echo $RASPA_WORK_DIR
echo $RASPA_DIR

# 验证 RASPA3 环境
conda activate raspa3
which raspa3
```

---

## 7. 部署验证

### 7.1 集群状态检查
```bash
# 检查所有节点状态
sinfo -N

# 期望输出：所有节点状态为idle
NODELIST        NODES PARTITION STATE
master-node         1   normal* idle
worker-node-01      1   normal* idle
worker-node-02      1   normal* idle
worker-node-03      1   normal* idle
```

### 7.2 NFS挂载验证
```bash
# 在任意节点检查挂载状态
mount | grep raspa

# 验证文件访问
ls -la /home/zjp/raspa2-calc
ls -la /home/zjp/raspa2-calc/work | head

# （可选）简单写入测试：所有节点都应能创建/读取文件
touch /home/zjp/raspa2-calc/work/.nfs_check_"$(hostname)"
```

### 7.3 RASPA 版本验证

```bash
# 验证 RASPA2
$RASPA_DIR/bin/simulate --help

# 验证 RASPA3
conda activate raspa3
raspa3 --help
```

### 7.4 版本检测验证

```bash
cd /home/zjp/raspa2-calc/work
python3 -c "
import sys
sys.path.insert(0, '/home/zjp/raspa2-calc/.raspa_tools/scripts/python')
from data_extractor import detect_raspa_version

# 测试 RASPA3 目录
print('RASPA3 目录检测:', detect_raspa_version('/home/zjp/raspa2-calc/work/10'))
"
```

---

## 8. 使用指南

### 8.1 基本使用流程

#### 8.1.1 进入工作目录
```bash
# 必须在NFS挂载目录下工作
cd /home/zjp/raspa2-calc
```

#### 8.1.2 准备输入文件

**RASPA2 模式**：
- CIF 结构文件
- simulation.input 模板
- config.yaml 配置

**RASPA3 模式**：
- CIF 结构文件
- simulation.json 模板
- force_field.json 力场文件
- 分子定义 JSON 文件 (CO2.json 等)
- config.yaml 配置

#### 8.1.3 提交任务
```bash
# 使用 raspa-calc 命令
raspa-calc

# 程序会自动：
# 1. 检测或让用户选择 RASPA 版本
# 2. 根据版本选择对应的处理流程
# 3. 生成相应的输入文件
# 4. 提交作业到调度系统
```

### 8.2 数据提取

数据提取器支持自动版本检测：

```bash
# 运行数据提取
raspa-calc
# 选择模式 3: 数据提取

# 程序会自动检测：
# - simulation.json → 使用 RASPA3 提取器
# - simulation.input → 使用 RASPA2 提取器
```

更详细的交互顺序、高通量/普通模式差异、以及 Henry/Rosenbluth 等字段说明，见：

- `docs/数据提取模式使用说明.md`

### 8.3 RASPA3 输出格式

RASPA3 输出文件位于 `output/*.txt`，吸附量格式：

```
Loadings
===============================================================================
Component 0 (CO2)
    Abs. loading average   1.234567e+00 +/-  1.234567e-02 [molecules/cell]
    Abs. loading average   5.678901e-01 +/-  5.678901e-03 [mol/kg-framework]
    Abs. loading average   2.500000e+01 +/-  2.500000e-01 [mg/g-framework]
    Excess loading average   5.000000e-01 +/-  5.000000e-03 [mol/kg-framework]
```

---

## 9. 故障排除

### 9.1 RASPA3 常见问题

#### 9.1.1 Conda 环境未激活
**问题**: `raspa3: command not found`
**解决方案**:
```bash
# 确保 conda 初始化
source ~/anaconda3/etc/profile.d/conda.sh
conda activate raspa3

# 验证
which raspa3
```

#### 9.1.2 JSON 文件缺失
**问题**: RASPA3 报错找不到力场或分子定义文件
**解决方案**:
```bash
# 检查 JSON 文件目录
ls -la /home/zjp/raspa2-calc/.raspa_tools/raspa3json/

# 确保包含：
# - force_field.json
# - simulation.json
# - 所有需要的分子定义文件 (CO2.json, CH4.json 等)
```

#### 9.1.3 数据提取为空
**问题**: RASPA3 数据提取结果为空
**解决方案**:
```bash
# 检查输出文件是否存在
ls output/*.txt

# 检查输出文件内容是否包含 Loadings 部分
grep -A 20 "^Loadings" output/*.txt
```

### 9.2 NFS 相关问题

#### 9.2.1 NFS挂载问题
**问题**: NFS挂载失败
**解决方案**:
```bash
# 检查NFS服务状态
sudo systemctl status nfs-server
sudo systemctl status rpcbind

# 检查网络连通性
ping 10.10.14.12

# 重新挂载
sudo umount /home/zjp/raspa2-calc
sudo mount -a
```

#### 9.2.2 Stale file handle（最常见）/ Slurm 作业 0 秒失败

**典型症状**（任意满足即可高度怀疑）：

- `ls` 报 `Stale file handle`
- `scontrol show job <id>`：`RunTime=00:00:00`、`JobState=FAILED`，`Reason=RaisedSignal:53`，且 `.out/.err` 没生成
- 作业被分配到某节点，但该节点上的 NFS 挂载已“失效”

**解决方案（在出问题的节点执行）：**

```bash
sudo umount -fl /home/zjp/raspa2-calc || sudo umount -l /home/zjp/raspa2-calc || true
sudo mount -a

# 也可以使用脚本（推荐）：
bash /home/zjp/raspa2-calc/.raspa_tools/nfs/nfs_client_setup.sh --recover
```

> 💡 如果问题发生在控制节点/节点上 slurmd 状态异常：在确认没有关键作业运行的情况下可重启 slurmd。

### 9.3 日志和调试

```bash
# 查看作业日志
tail -f 1log/raspa_*.out
tail -f 1log/raspa_*.err

# 查看 RASPA3 特定日志
ls output/*.txt
cat output/*.txt | head -100
```

---

## 10. 部署检查清单

### 10.1 通用检查
- [ ] 所有节点网络连通正常
- [ ] SLURM/PBS 服务运行正常
- [ ] NFS 共享存储配置正确
- [ ] 所有可能运行作业的节点 UID/GID 一致（尤其是提交作业的账号）
- [ ] 用户权限配置正确

### 10.2 RASPA2 检查
- [ ] RASPA_DIR 环境变量设置正确
- [ ] simulate 可执行文件存在
- [ ] simulation.input 模板可用

### 10.3 RASPA3 检查
- [ ] raspa3 conda 环境在所有节点存在
- [ ] raspa3 命令可执行
- [ ] force_field.json 文件存在
- [ ] 分子定义 JSON 文件完整
- [ ] simulation.json 模板配置正确
- [ ] raspa3_cif_base_path 路径正确

### 10.4 数据提取检查
- [ ] data_extractor.py 版本检测正常
- [ ] RASPA3 输出格式解析正确
- [ ] CSV/Excel 导出功能正常

---

**文档版本**: v2.5.0
**更新日期**: 2026-01-14
**维护人员**: zjp
**状态**: 支持 RASPA2/RASPA3 双版本
