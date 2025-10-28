# RASPA2 高通量计算工具 v2.3.0

**⚡ 高性能RASPA2分子模拟计算平台** - 支持参数筛选、高通量计算、数据处理、警告恢复、等温线绘制

## 🎯 v2.3.0 核心特性（2025-10）

| 特性 | 说明 | 性能提升 |
|------|------|--------|
| **SLURM作业数组** | `sbatch --array=1-N%M` 一次提交 | ⚡ 提交速度快 50 倍 |
| **共享任务队列** | `.raspa_task_queue` 原子竞争机制 | 🚀 减少 90% I/O 扫描 |
| **动态并发缩放** | `raspa-scale` 交互/自动选择并发 | 📊 平滑升降，无需重启 |
| **统一资源探测** | 与 raspa-calc 一致的集群资源视图 | 📡 一处实现，脚本一致 |
| **多节点集群** | NFS 共享存储 + 异构节点支持 | 🌐 支持 960+ 核心 |
| **五大计算模式** | 参数筛选、高通量、数据提取、警告处理、等温线绘制 | 🔄 覆盖全周期 |
| **原子文件锁** | 基于 POSIX `noclobber` 的并发安全 | 🔒 NFS友好，无race condition |
| **智能环境检测** | 自动检测 SLURM/PBS/LOCAL 并适配 | ✅ 零配置部署 |
| **实时任务监控** | `raspa-status` 基于当前目录统计 | 📈 精确进度报告 |

> **💡 推荐配置**：SLURM 集群（多节点）+ NFS 共享存储 + 960+ CPU 核心

## 项目概览

一个企业级RASPA2分子模拟高通量计算系统，集成参数筛选、数据处理、性能监控为一体。

## 📋 核心功能

### 五大计算模式
- **🎯 参数筛选** (`parameter_screening.py`)：快速测试参数组合，生成等温线
- **⚙️ 高通量计算** (`calculate_params.py`)：批量处理框架结构，支持960+核心并行
- **📊 数据提取** (`data_extractor.py`)：解析RASPA输出，生成Excel/CSV报表
- **⚠️ 警告处理** (`warning_processor.py`)：提取失败任务、CSV数据替换
- **📈 等温线绘制** (`isotherm_plotter.py`)：可视化吸附数据

### 执行优化
- **⚡ SLURM作业数组**：`sbatch --array=1-N` 一次提交N个子任务，提交速度快50倍
- **🚀 共享任务队列**：`.raspa_task_queue` 原子弹出机制，减少90% NFS扫描
- **📊 动态并发缩放**：`raspa-scale` 支持交互(-i)与自动(-y)选择并发；按“可用任务数 + 集群空闲CPU”给出建议值，避免过度补交
- **🔒 并发安全**：原子文件锁 + 三级任务队列，支持NFS和高并发

### 系统特性
- **🌐 多节点集群**：SLURM + NFS 共享存储，支持异构节点和960+ CPU核心
- **🔧 零配置检测**：自动识别SLURM/PBS/LOCAL，环境适配即插即用
- **📈 实时监控**：`raspa-status` 精确统计任务状态，支持按子目录查看
- **🎨 配置灵活**：YAML配置 + 交互式参数设置，支持多种气体分子
- **📋 完整诊断**：`raspa-diagnose` 检查环境、依赖、工具链
- **🔍 智能恢复**：失败任务自动检查、标记和重试

## 🚀 5分钟快速开始

### 前置要求
```bash
# 1. Python 3.8+ 和系统工具
python3 --version
which bash find grep sed

# 2. RASPA2 安装路径
export RASPA_DIR=/path/to/raspa2  # 需要包含 share/raspa/forcefield
```

### 安装步骤

```bash
# 1. 克隆或进入项目目录
cd raspa2-calc/.raspa_tools

# 2. 运行安装脚本
chmod +x install.sh
./install.sh

# 3. 重新加载shell配置
source ~/.bashrc  # 或 source ~/.zshrc

# 4. 验证安装
raspa-diagnose
```

### 依赖包

```
numpy>=1.21.0          # 科学计算
pandas>=1.3.0          # 数据处理
gemmi>=0.5.0           # CIF文件处理和晶体学计算
openpyxl>=3.0.0        # Excel支持（可选）
tqdm>=4.60.0           # 进度条
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 集群部署

### 多节点集群配置

v2.3.0支持在SLURM集群上进行多节点高通量计算：

#### 1. NFS共享存储配置

**服务器端配置**：
```bash
# 创建共享目录
sudo mkdir -p /shared/raspa2-calc
sudo chown -R zjp:zjp /shared/raspa2-calc

# 配置NFS导出
echo "/shared/raspa2-calc 10.10.14.0/24(rw,sync,no_root_squash)" | sudo tee -a /etc/exports
sudo systemctl enable --now nfs-server rpcbind
sudo exportfs -ra
```

**客户端配置**：
```bash
# 安装NFS客户端
sudo yum install -y nfs-utils

# 配置自动挂载
echo "10.10.14.12:/shared/raspa2-calc /home/zjp/raspa2-calc nfs4 rw,hard,intr 0 0" | sudo tee -a /etc/fstab
sudo mount -a
```

#### 2. 使用方法

⚠️ **重要**：多节点任务调度必须在NFS挂载目录下提交任务：

```bash
# 进入NFS共享目录
cd /home/zjp/raspa2-calc

# 启动高通量计算
raspa-calc
```

### 任务提交与并发优化

默认启用以下优化，显著降低大规模并发下的开销：
- **SLURM 作业数组（默认）**：一次 `sbatch --array=1-N%N` 提交 N 个子任务；提交更快、队列管理更轻
- **单步 srun**：每个子任务仅启动一次 job step，`runjobs.sh` 在该步骤内持续消费任务
- **共享任务队列**：`.raspa_task_queue` 保存待处理 mc* 清单；原子弹出避免抢占冲突，并自动清理 `.raspa_task_queue.*` 临时文件
- **兼容模式延迟**：PBS/LOCAL 或 `SUBMIT_MODE=LOOP` 时，保留轻量延迟（SLURM/PBS 0.2s、LOCAL 1s）
- **作业日志输出**：默认写入 `<输出目录>/1log/raspa_%A_%a.(out|err)`；可通过配置关闭或自定义目录

```bash
# 进入你的工作目录
cd /path/to/your/project

# 启动主程序（会自动进行环境检测）
raspa-calc
```

#### 动态并发与 Job Array（SLURM）

- 提交时选择“并发核心数”N，默认使用“作业数组”提交：`--array=1-N%N`
- 运行期间可随时缩放并发：
  - 交互式：`raspa-scale -i <子目录>`（展示集群资源与可用任务，输入期望并发）
  - 自动采纳建议：`raspa-scale -y <子目录>`（非交互/CI环境推荐）
  - 指定数值：`raspa-scale 700 <子目录>`
- 兼容模式：若需逐个 `sbatch` 提交，设置 `export SUBMIT_MODE=LOOP` 后再运行；仍可用 `raspa-scale`（生效于限额文件）

说明：`raspa-scale` 写入 `<子目录>/.raspa_worker_limit` 控制“工人”在任务边界自觉退出/继续；对于逐个 `sbatch` 的 loop 模式，还会“有意义补交”（不超过“可跑任务总数与集群空闲的建议上限”）。作业数组限流可按需手动 `scontrol update ... ArrayTaskThrottle=<N>`。

#### PBS 并发控制（立即生效）

- 即时扩/缩容命令：
  - 扩容/缩容：` .raspa_tools/bin/raspa-scale-pbs <并发上限> [子目录] `
  - 示例：
    - 立刻扩到 20：`.raspa_tools/bin/raspa-scale-pbs 20 test`
    - 立刻缩到 8：`.raspa_tools/bin/raspa-scale-pbs 8 test`
- 行为与安全性：
  - 写入 `<子目录>/.raspa_worker_limit`，保证 worker 在任务边界平滑退出/继续。
  - 立刻补交缺口编号（只补 1..N 中缺失的编号，避免重复）。
  - 立刻回收超额作业：按“最短 walltime 优先”裁剪；若同一编号存在多个作业，仅保留 walltime 最大者，其余回收（duplicate）。
  - 安全过滤：仅回收日志路径属于当前子目录 `<子目录>/1log/` 的数字命名作业，避免误删他处作业。
  - 输出可见：打印每条 `qdel <jobid> (name=<编号>)` 和 `提交 worker 编号: <编号>`。
- 诊断与兜底：
  - 若 PBS 队列清理为异步，作业会先进入 E 状态，队列中短时仍可见；这是正常现象。
  - 若日志路径不匹配导致无法安全回收，脚本会给出一键兜底命令，手动回收：
    - `qstat -u "$USER" | awk 'NR>2 {print $1,$2}' | awk '$2~/^[0-9]+$/ && $2>目标 {print $1}' | xargs -r qdel`
  - 活跃估计优先基于 PBS 队列过滤结果；当队列信息异常时，回退使用目录中的 `__running` 计数。

提示：PBS 的 `qdel` 通常为异步清理，相比 `scancel` 更慢；本工具已按“最短 walltime 优先 + 去重”尽量减少损失并尽快回到目标并发。

#### 作业日志配置

- `logging.output_dir`：作业数组/逐个提交产生的 `.out/.err` 输出目录（相对输出目录，默认 `1log`）
- `logging.enable_job_logs`：`true/false` 控制是否写入 `.out/.err`（为 `false`/`0`/`no` 时，统一写入 `/dev/null`）
- 支持运行时修改：更新配置后重新提交即可；已有作业可用 `raspa-scale` 结合 `ArrayTaskThrottle` 调整并发

#### 环境检测功能

程序启动时会自动进行全面的环境检测，包括：

- ✅ **Python依赖包**：gemmi、numpy、pandas等
- ✅ **系统工具**：bash、find、grep、sed、chmod
- ✅ **环境变量**：RASPA_DIR、RASPA_WORK_DIR
- ✅ **RASPA可执行文件**：检查simulate程序是否存在
- ✅ **工具目录**：检查.raspa_tools目录

如果检测到问题，程序会：
1. 列出所有不符合要求的项目
2. 提供具体的解决方案建议
3. 阻止程序继续运行，避免后续错误

#### 环境变量设置

确保以下环境变量已正确设置：

```bash
export RASPA_DIR=/path/to/raspa/installation
export RASPA_WORK_DIR=/path/to/your/work/directory
```

可以将这些变量添加到你的shell配置文件中：

```bash
echo 'export RASPA_DIR=/path/to/raspa' >> ~/.bashrc
echo 'export RASPA_WORK_DIR=/path/to/work' >> ~/.bashrc
source ~/.bashrc
```

#### 配置文件支持

工具支持YAML格式的配置文件 (`config.yaml`)，用于自定义各种参数：

```yaml
# 环境配置
environment:
  work_dir: "/path/to/work"
  raspa_dir: "/path/to/raspa"
  cif_dir: "data/cif"

# 计算参数
calculation:
  cutoff_radius: 12.0
  default_molecules: "12c CH4"  # 支持多种气体分子
  # 并发核心数与结构数量：提交时交互选择，不再在配置中设置
  output_directory: "calc_output"
  use_custom_template: false   # 使用自定义模板
  use_void_csv: false          # 使用空隙率CSV

# 性能优化
performance:
  enable_cache: true
  cache_timeout: 3600
  show_progress: true
```

#### 配置参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| `cutoff_radius` | 截断半径 | `12.0` |
| `default_molecules` | 默认分子(空格分隔) | `"12c CH4 CO2"` |
| `并发核心数` | 提交时交互设置 | 例如 `960` |
| `处理结构数量` | 提交时交互设置 | 例如 `1000` |
| `output_directory` | 输出目录名 | `"calc_output"` |
| `use_custom_template` | 使用自定义模板 | `false` |
| `csv_file_path` | CSV文件路径 | `"data/structures.csv"` |
| `framework_column` | 框架名称列 | `"refcode"` |

#### 气体分子配置

配置文件支持多种气体分子输入：

```yaml
calculation:
  # 单个分子
  default_molecules: "12c"

  # 多种气体分子 (用空格分隔)
  default_molecules: "12c CH4 CO2 N2 O2"
```

程序会自动解析空格分隔的分子列表，支持同时计算多种气体。

#### 完整配置示例

复制 `config.example.yaml` 为 `config.yaml` 并根据需要修改：

```yaml
# 计算参数配置
calculation:
  cutoff_radius: 12.0                    # 截断半径
  default_molecules: "12c CH4 CO2"       # 多种气体分子
  # 并发核心数、处理结构数量：提交时交互输入
  output_directory: "multi_gas_calc"    # 输出目录
  csv_file_path: "data/structures.csv"  # CSV文件路径
  framework_column: "refcode"           # 框架列名
  use_void_csv: true                    # 使用空隙率CSV
  void_csv_file: "data/properties.csv"  # 空隙率文件
  void_column: "VF"                     # 空隙率列名

logging:
  level: "INFO"              # 主日志级别
  file: "raspa_calc.log"     # 主日志文件
  output_dir: "1log"         # 作业 .out/.err 相对目录（默认写入 <输出目录>/1log/）
  enable_job_logs: true       # 是否生成 .out/.err（false/0/no 时写入 /dev/null）
  # 其他字段（max_size / backup_count 等）可按需保留
```

配置文件优势：
- 🔧 **灵活配置**：无需修改代码即可调整参数
- 👥 **团队协作**：共享标准配置，避免冲突
- 🚀 **环境适配**：为不同环境提供定制设置
- 📝 **版本控制**：配置文件可纳入版本控制系统
- 🌟 **多分子支持**：轻松配置多种气体分子计算
- ⚠️ **警告处理**：支持警告任务的提取和数据替换

## 警告处理系统

v2.3.0引入了强大的警告处理系统，支持两种模式：

### 模式1：提取警告数据

传统的警告处理流程，用于从原始CSV中提取包含警告的任务：

```bash
# 运行警告处理器
python scripts/python/warning_processor.py

# 选择模式1：提取警告数据
# 选择CSV文件（包含警告信息）
# 选择警告类型（如：INAPPROPRIATE NUMBER OF UNIT CELLS）
# 生成warning_tasks.csv文件
```

**流程步骤**：
1. 分析original.csv中的警告
2. 用户选择警告类型
3. 生成warning_tasks.csv
4. 显示手动配置指导

### 模式2：CSV数据替换

新增的智能数据替换功能，用于将重新计算的结果替换回原始数据：

```bash
# 运行警告处理器
python scripts/python/warning_processor.py

# 选择模式2：CSV数据替换
# 选择原始CSV文件
# 选择重新计算CSV文件
# 手动选择匹配列（如coreid、refcode等）
# 自动执行数据替换
```

**流程步骤**：
1. 选择原始和重新计算的CSV文件
2. 系统显示所有可用的匹配列
3. 用户手动选择匹配列
4. 预览数据样本并确认
5. 执行精准数据替换
6. 生成更新后的CSV文件

### 手动列选择特性

根据用户偏好，系统不会自动选择匹配列，而是让用户完全控制：

- 🔍 **智能检测**：自动检测两个CSV文件的共同列
- 🎯 **优先排序**：将常见的框架列名（coreid、refcode等）放在前面
- 📄 **数据预览**：显示选择列的数据样本供用户确认
- ✅ **确认机制**：用户必须确认选择才会执行替换
- ⚙️ **灵活配置**：支持任意列名匹配，不限于特定格式

**使用例子**：
```
🎯 请选择用于匹配的列名:
  1. coreid
  2. refcode  
  3. Framework Name
  4. name
  5. structure

请输入列号 (1-5): 1

🔍 预览列 'coreid' 的数据样本:
📄 原始CSV中的 'coreid': ['core001', 'core002', 'core003']
📄 重计算CSV中的 'coreid': ['core001', 'core003']

确认使用该列进行匹配吗? (y/n): y
```

## 📚 命令行工具参考

### 主入口：raspa-calc
```bash
raspa-calc
```
**功能**：主程序入口，支持5种计算模式

**交互流程**：
1. 选择计算模式（参数筛选 / 高通量 / 数据提取 / 警告处理 / 等温线绘制）
2. 输入CSV文件路径和框架列名
3. 交互式选择参数（CPU核心数、处理结构数、截断半径等）
4. 预览示例configuration，确认后提交

**示例**：
```bash
# 高通量计算模式
$ raspa-calc
=== RASPA 高通量计算工具 ===
1. 参数筛选（快速测试）
2. 高通量计算（批量处理）
3. 数据提取（解析结果）
4. 警告处理（失败恢复）
5. 等温线绘制（可视化）
> 选择模式: 2
> 请输入CSV文件路径: structures.csv
> 请输入框架列名: refcode
> 请输入处理结构数: 100
> 请输入CPU核心数: 480
```

### 任务监控：raspa-status
```bash
# 查看任务状态统计
raspa-status

# 显示详细任务列表
raspa-status -d output

# 重置失败任务状态
raspa-status -r

# 实时监控任务进度
raspa-status -m

# 监控特定子目录
raspa-status -d <subdir>
```

**输出示例**：
```
📊 RASPA 任务状态统计
├─ 已完成:   520 个 ✅
├─ 运行中:    95 个 ⏳
├─ 待处理:    45 个 ⏸️
└─ 失败:       0 个 ❌
```

### 动态缩放：raspa-scale
```bash
# 交互式：展示资源与可用任务，输入并发上限
raspa-scale -i work/301adsorption

# 自动采用建议并发（非交互/CI推荐）
raspa-scale -y work/301adsorption

# 直接指定并发（非交互）
raspa-scale 700 work/301adsorption
```

**说明**：
- 修改 `<子目录>/.raspa_worker_limit` 文件，worker 在任务边界检查并动态退出
- SLURM loop 模式下按“有意义目标并发”补交/缩容；当可用任务为 0 时不会补交
- 建议并发 = min(子目录中“运行中+待处理(含simulation.input)”数量, 集群空闲CPU)

### 环境诊断：raspa-diagnose
```bash
raspa-diagnose           # 诊断当前目录
raspa-diagnose -h        # 查看使用说明
raspa-diagnose <路径>    # 诊断指定路径（相对路径优先，回退到 RASPA_WORK_DIR）
```

**检查项**：
- ✅ Python 版本 & 依赖包（numpy, pandas, gemmi等）
- ✅ 系统工具（bash, find, grep, sed, chmod）
- ✅ 环境变量（RASPA_DIR, RASPA_WORK_DIR）
- ✅ RASPA 可执行文件
- ✅ 调度系统（SLURM/PBS 节点状态）
- ✅ 工具链版本

说明：诊断会额外检查 `<子目录>/.raspa_worker_limit`、`.raspa_jobs.list` 与 squeue 活跃作业的一致性，并提示是否存在“__running 但无活跃作业”的卡死情形。

### 等温线绘制：raspa-plot-isotherm
```bash
raspa-plot-isotherm
```

**功能**：
- 解析RASPA输出文件
- 绘制吸附等温线图（PNG）
- 导出数据为CSV

## 技术细节

### 共享任务队列机制

- 队列文件：`<子目录>/.raspa_task_queue`，保存待处理 mc* 清单；提交前会清理旧队列并重建
- 领取算法：原子弹出一条 mcN，原子改名 `mcN→mcN__running`，计算成功后改为 `__done`，失败改为 `__failed`
- 并发安全：优先使用 `flock`；在NFS下使用原子文件锁兜底，避免抢占冲突

### v2.1 增强特性

1. **智能子目录检测**
   - 自动检测包含mc*目录的子目录
   - 支持常见的目录结构（如output、3等）
   - 避免硬编码目录名称

2. **动态参数配置**
   - 自动统计总任务数量
   - 支持用户指定CPU核心数
   - 动态调整工作目录路径

3. **多调度系统支持**
   - SLURM：使用sbatch提交作业
   - PBS：使用qsub提交作业
   - 本地模式：直接执行bash脚本

4. **模拟模式**
   - 在没有RASPA程序时自动启用
   - 用于测试脚本逻辑和任务流程
   - 模拟真实的计算过程

5. **错误处理增强**
   - 更好的文件存在性检查
   - 优雅的错误信息输出
   - 自动跳过无效目录

6. **权限问题修复**
   - 增强的权限设置逻辑
   - 自动修复脚本执行权限
   - 安装时确保所有脚本权限正确

### 任务状态管理

任务目录状态说明：
- `mc*`：待处理任务
- `mc*__running`：正在运行的任务
- `mc*__done`：已完成的任务
- `mc*__failed`：失败的任务

### 脚本文件说明

- `tasksrun.sh`：主任务提交脚本
- `runjobs.sh`：单个任务执行脚本
- `job_submit.sh`：作业提交模板（raspa-scale 在提交时会基于此生成临时脚本）
- `local.sh`、`pbs.sh`、`sbatch.sh`：不同调度系统的模板

其他：
- `scripts/python/cluster_info.py`：统一的 SLURM 集群资源探测 CLI，供 raspa-scale/raspa-calc 共享使用
- `raspa-status`：默认子目录为 `.`；若当前/工作目录下仅有一个包含 mc* 的子目录，会自动选择该子目录

## 常见问题

### Q: 如何确认我使用的是哪个版本？

A: 运行诊断工具查看版本信息：
```bash
raspa-diagnose
```

### Q: 任务显示"所有任务已完成，无需提交新作业"但实际没有运行？

A: v2.1版本已修复此问题。脚本现在会：
- 智能检测实际的任务目录
- 动态统计待处理任务数量
- 正确识别任务状态

### Q: 如何指定使用的CPU核心数？

A: 在高通量计算模式中，程序会提示你输入CPU核心数：
```
请输入要使用的CPU核心数 (建议值: 520): 520
```

### Q: 如何在多节点集群上运行？

A: 确保满足以下条件：
1. 配置NFS共享存储
2. 所有节点环境变量一致
3. 在NFS挂载目录下提交任务
4. 使用`sinfo -Nel`检查节点状态

### Q: 为什么任务排队但有空闲CPU？

A: 可能原因：
1. 节点处于DRAIN状态：使用`sudo scontrol update NodeName=<node> State=RESUME`恢复
2. 调度器过载：v2.3.0已添加任务提交延迟解决
3. NFS挂载问题：检查所有节点的NFS挂载状态

### Q: 如何配置框架列名？

A: 在config.yaml中设置：
```yaml
calculation:
  framework_column: "your_column_name"  # 替换为实际列名
```

### Q: 支持哪些作业调度系统？

A: v2.3.0支持：
- SLURM (sbatch) - 完整的多节点集群支持
- PBS (qsub)  
- 本地模式 (bash)

### Q: 如何在没有RASPA程序的环境中测试？

A: v2.3.0自动检测RASPA程序，如果不存在会启用模拟模式，可以用于测试脚本逻辑。

### Q: 如何使用警告处理系统？

A: v2.3.0新增强大的警告处理系统：
```bash
# 运行警告处理器
python scripts/python/warning_processor.py

# 选择模式1：提取警告数据（生成warning_tasks.csv）
# 选择模式2：CSV数据替换（用重新计算结果替换原始数据）
```

### Q: 如何选择正确的匹配列进行CSV替换？

A: 系统会显示所有可用的共同列供您选择：
- 优先显示常见框架列名（coreid、refcode等）
- 显示每列的数据样本供确认
- 支持手动选择任意列名匹配
- 确认机制确保数据准确替换

### Q: CSV数据替换安全吗？

A: 非常安全：
- 只替换精确匹配的行，其他数据保持不变
- 生成带`_updated`后缀的新文件，不覆盖原文件
- 提供详细的替换过程报告
- 支持替换前的数据预览和确认

## v2.2 修复详情

### 🔧 修复的问题

1. **第二轮状态检查逻辑修复**
   - **问题**：第二轮循环无法正确识别已完成/失败/运行中的任务
   - **影响**：可能重复处理已完成任务或遗漏待处理任务
   - **修复**：添加完整的状态检查逻辑，使用`if/elif`结构正确处理各种状态

2. **并发安全机制**
   - **问题**：多进程环境下可能出现竞态条件
   - **影响**：任务状态转换可能出现冲突
   - **修复**：实现文件锁机制(`set -o noclobber`)确保原子性操作

3. **STEP变量逻辑错误**
   - **问题**：`STEP=${CPU:-2}`错误地将当前CPU ID赋值给步长
   - **影响**：任务分配不均匀，第一轮循环可能跳过任务
   - **修复**：正确设置`STEP=$TOTAL_CPUS`，步长等于总CPU数

4. **硬编码路径问题**
   - **问题**：模板文件包含硬编码的绝对路径
   - **影响**：系统不可移植，部署到不同环境需要修改
   - **修复**：使用`$RASPA_WORK_DIR`环境变量替换硬编码路径

5. **模板语法错误**
   - **问题**：`sbatch.sh`使用非bash语法`{{$VAR}}`
   - **影响**：SLURM作业提交失败
   - **修复**：改为标准bash变量语法`${VAR}`或`$VAR`

6. **参数传递问题**
   - **问题**：作业模板调用`runjobs.sh 0`传递错误参数
   - **影响**：任务分配逻辑无法获取正确CPU信息
   - **修复**：传递正确的参数`$1 $2`（CPU ID和总CPU数）

### ✅ 验证结果

通过完整测试验证所有修复：

```bash
📊 任务统计:
   ✅ 已完成: 3 个
   ❌ 已失败: 0 个
   ⏳ 运行中: 1 个
   ⏸️ 待处理: 0 个

🎉 第二轮状态检查修复成功！
```

- ✅ 第二轮状态检查逻辑工作正常
- ✅ 并发安全机制有效防止竞态条件
- ✅ 任务分配均匀，无遗漏任务
- ✅ 文件锁机制正确清理，无残留
- ✅ 所有修复都通过实际测试验证

### 🧪 测试方法

```bash
# 创建测试场景
mkdir -p test_output/mc1 test_output/mc2 test_output/mc3
mv test_output/mc1 test_output/mc1__done    # 已完成
mv test_output/mc3 test_output/mc3__running # 运行中
# mc2 保持原始状态（模拟遗漏）

# 执行第二轮状态检查
for i in {1..3}; do
  if [ -d "mc${i}__done" ]; then echo "✅ 已完成，跳过"
  elif [ -d "mc${i}__failed" ]; then echo "❌ 已失败，跳过"
  elif [ -d "mc${i}__running" ]; then echo "⏳ 运行中，跳过"
  elif [ -d "mc$i" ]; then echo "📋 补齐遗漏任务"; fi
done
```

## 版本历史

### v2.3.0 - 集群优化版本（里程碑，2025-10）

**核心优化**：
- ✅ **SLURM作业数组** - `sbatch --array=1-N` 一次提交N个子任务，提交速度快50倍
- ✅ **共享任务队列** - `.raspa_task_queue` 原子竞争机制，减少90% NFS扫描
- ✅ **单步srun模式** - 每个子任务仅启动一次job step，显著降低系统开销
- ✅ **动态并发缩放** - `raspa-scale N` 实时调整，配合 `ArrayTaskThrottle` 平滑升降

**功能增强**：
- ✅ **五大计算模式** - 参数筛选、高通量、数据提取、警告处理、等温线绘制
- ✅ **多节点集群** - NFS共享存储 + 异构节点兼容，支持960+ CPU核心
- ✅ **原子文件锁** - 基于POSIX noclobber的并发安全，NFS友好
- ✅ **三级任务队列** - retry.list + next_id/last_id + 自动扫描，容错恢复
- ✅ **CSV数据集成** - 支持从CSV读取空隙率、框架名等元数据
- ✅ **警告处理系统** - 双模式：失败任务提取 + CSV数据替换

**代码质量**：
- ✅ **资源检测重构** - 使用 `available_cpus`（总可用）和 `free_cpus`（节点级）替代 `idle_cpus`
- ✅ **配置参数化** - 框架列名、模板路径、空隙率CSV等完全可配置
- ✅ **性能改进** - BOM编码处理、gemmi库集成、精确UnitCells算法
- ✅ **向后兼容** - 保留 `idle_cpus` 后备值 (`.get('idle_cpus', 0)`)，确保数据兼容

### v2.2 - 修复验证版本
- ✅ **并发安全修复** - 实现文件锁机制 (`set -o noclobber`) 防止竞态条件
- ✅ **状态检查逻辑** - 修复第二轮循环的任务识别（if/elif结构）
- ✅ **参数传递修复** - 正确传递CPU ID和总数给job step

### v2.1 - 功能增强版本
- ✅ **智能子目录检测** - 自动识别包含mc*的工作目录结构
- ✅ **动态参数配置** - 自动统计任务数、支持用户指定CPU核心数
- ✅ **多调度系统适配** - SLURM/PBS/本地执行自动检测
- ✅ **模拟模式** - 无RASPA程序时自动启用，便于脚本验证
- ✅ **错误处理增强** - 改进的文件存在性检查和权限管理

### v2.0 - 核心重写版本
- ✅ **任务提交逻辑** - 从全局循环改为每任务独立作业
- ✅ **集成raspa-calc** - 统一的命令行入口
- ✅ **智能任务管理** - 引入任务状态转换（mc* → mc*__running → mc*__done）
- ✅ **CPU动态分配** - 支持用户指定使用的CPU核心数

### v1.x - 初始版本
- 基础功能实现
- 小批量和高通量计算模式
- 简单的任务状态监控

## 贡献

欢迎提交Issue和Pull Request来改进这个工具。

## 许可证

[请添加适当的许可证信息]
