# RASPA 高通量计算工具 v2.5.0

<div align="center">
  <img src="figure/RASPA高性能分子模拟计算平台信息图.png" alt="RASPA高性能分子模拟计算平台信息图" width="50%">
</div>

**高性能 RASPA 分子模拟计算平台** - 支持 RASPA2/RASPA3 双版本、参数筛选、高通量计算、数据处理、警告恢复、等温线绘制

## v2.5.0 核心特性（2025-12）

| 特性 | 说明 | 性能提升 |
|------|------|--------|
| **RASPA2/RASPA3 双版本** | 自动检测版本，支持配置切换 | 兼容新旧版本 |
| **SLURM作业数组** | `sbatch --array=1-N%M` 一次提交 | 提交速度快 50 倍 |
| **共享任务队列** | `.raspa_task_queue` 原子竞争机制 | 减少 90% I/O 扫描 |
| **动态并发缩放** | `raspa-scale` 交互/自动选择并发 | 平滑升降，无需重启 |
| **统一资源探测** | 与 raspa-calc 一致的集群资源视图 | 一处实现，脚本一致 |
| **多节点集群** | NFS 共享存储 + 异构节点支持 | 支持 960+ 核心 |
| **六大计算模式** | 参数筛选、高通量、数据提取、警告处理、等温线、CSV/CIF筛选 | 覆盖全周期 |
| **原子文件锁** | 基于 POSIX `noclobber` 的并发安全 | NFS友好，无race condition |
| **智能环境检测** | 自动检测 SLURM/PBS/LOCAL 并适配 | 零配置部署 |
| **实时任务监控** | `raspa-status` 基于当前目录统计 | 精确进度报告 |

> **推荐配置**：SLURM 集群（多节点）+ NFS 共享存储 + 960+ CPU 核心

## 项目概览

一个企业级 RASPA 分子模拟高通量计算系统，支持 RASPA2 和 RASPA3 双版本，集成参数筛选、数据处理、性能监控为一体。

## RASPA 版本支持

### 版本对比

| 特性 | RASPA2 | RASPA3 |
|------|--------|--------|
| 输入文件 | `simulation.input` (文本) | `simulation.json` (JSON) |
| 额外文件 | 无 | `force_field.json`, 分子定义 `.json` |
| 执行命令 | `$RASPA_DIR/bin/simulate` | `raspa3` (conda 环境) |
| 输出目录 | `Output/System_0/*.data` | `output/*.txt` |
| 吸附量格式 | `Average loading absolute [mol/kg framework]` | `Abs. loading average [mol/kg-framework]` |

### 版本检测

程序会自动检测 RASPA 版本：
- 检测到 `simulation.json` → RASPA3
- 检测到 `simulation.input` → RASPA2
- 可在运行时手动选择版本覆盖配置

## 核心功能

### 六大计算模式
- *参数筛选* (`parameter_screening.py`)：快速测试参数组合，生成等温线
- *高通量计算* (`calculate_params.py`)：批量处理框架结构，支持960+核心并行
- *数据提取* (`data_extractor.py`)：解析RASPA输出，生成Excel/CSV报表，自动检测版本
- *警告处理* (`warning_processor.py`)：提取失败任务、CSV数据替换
- *等温线绘制* (`isotherm_plotter.py`)：可视化吸附数据
- *CSV/CIF 筛选* (`ciffilter.py`)：交互式按条件/refcode筛选CSV，可复制匹配的CIF

### 执行优化
- *SLURM作业数组*：`sbatch --array=1-N` 一次提交N个子任务，提交速度快50倍
- *共享任务队列*：`.raspa_task_queue` 原子弹出机制，减少90% NFS扫描
- *动态并发缩放*：`raspa-scale` 支持交互(-i)与自动(-y)选择并发
- *并发安全*：原子文件锁 + 三级任务队列，支持NFS和高并发

### 系统特性
- *多节点集群*：SLURM + NFS 共享存储，支持异构节点和960+ CPU核心
- *零配置检测*: /PBS/LOCAL，环境适配即插即用
- *实时监控*：`raspa-status` 精确统计任务状态，支持按子目录查看
- *配置灵活*：YAML配置 + 交互式参数设置，支持多种气体分子
- *完整诊断*：`raspa-diagnose` 检查环境、依赖、工具链
- *智能恢复*：失败任务自动检查、标记和重试
- **详细指南移至** `docs/` 目录（集群部署、RASPA3 示例、警告处理等）

## 5分钟快速开始

### 前置要求（base 环境 + 按需准备 raspa3/pymser）
```bash
# 基础检查（在 base 环境）：准备 raspa2和其他脚本所需环境
conda install -c conda-forge raspa2
pip install -r requirements.txt

# 若跑 RASPA3：准备 raspa3 环境
conda create --name raspa3
conda activate raspa3
conda install -c conda-forge raspa3

# 如需 pyMSER：创建 pymser 环境
conda env create -f environment.yml  # 生成名为 pymser 的环境
```

### 安装步骤

```bash
# 1. 克隆或进入项目目录
cd raspa2-calc

# 2. 运行安装脚本
chmod +x install.sh
./install.sh

# 3. 重新加载shell配置
source ~/.bashrc  # 或 source ~/.zshrc

# 4. 验证安装
raspa-diagnose

```
## 命令行工具参考

### 主入口：raspa-calc
```bash
raspa-calc
```
**功能**：主程序入口，支持5种计算模式，自动检测 RASPA 版本

### 任务监控：raspa-status
```bash
raspa-status           # 查看任务状态统计
raspa-status -d output # 显示详细任务列表
raspa-status -r        # 重置失败任务状态
raspa-status -m        # 实时监控任务进度
```

### 动态缩放：raspa-scale
```bash
raspa-scale -i work/output    # 交互式
raspa-scale -y work/output    # 自动采用建议并发
raspa-scale 700 work/output   # 直接指定并发
```

### 环境诊断：raspa-diagnose
```bash
raspa-diagnose           # 诊断当前目录
raspa-diagnose <路径>    # 诊断指定路径
```

### 等温线绘制：raspa-plot-isotherm
```bash
raspa-plot-isotherm
```

## 数据提取

### 自动版本检测

数据提取器会自动检测 RASPA 版本并使用对应的解析器：

```bash
raspa-calc
# 选择模式 3: 数据提取
# 程序自动检测：
# - simulation.json → RASPA3 提取器
# - simulation.input → RASPA2 提取器
```

### RASPA3 输出格式

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

### RASPA3 支持的数据项

- `pressure` - 压力 [Pa]
- `temperature` - 温度 [K]
- `He_void_fraction` - 氦空隙率
- `Framework_density` - 框架密度 [kg/m^3]
- `absolute_adsorption` - 绝对吸附量 (mol/kg, mg/g, cm^3/g, cm^3/cm^3, molecules/cell)
- `excess_adsorption` - 超额吸附量 (同上单位)
- `adsorption_heat` - 吸附热 [kJ/mol]
- `henry_coefficient` - 亨利系数 [mol/kg/Pa]
- `rosenbluth_weight` - Rosenbluth 权重

## 警告处理系统

### 模式1：提取警告数据

```bash
python scripts/python/warning_processor.py
# 选择模式1：提取警告数据
```

### 模式2：CSV数据替换

```bash
python scripts/python/warning_processor.py
# 选择模式2：CSV数据替换
```

## 高通量计算配置文件

### 完整配置示例

```yaml
# 环境配置
environment:
  work_dir: "/path/to/work"

  # ============ RASPA 版本选择 ============
  raspa_version: "raspa3"  # 或 "raspa2"

  # ============ RASPA2 配置 ============
  raspa_dir: "/path/to/raspa2"
  raspa2_cif_dir: "/path/to/cif"

  # ============ RASPA3 配置 ============
  raspa3_conda_env: "raspa3"
  raspa3_json_dir: "/path/to/raspa3json"
  raspa3_cif_base_path: "/path/to/cif"
  raspa3_template_path: "/path/to/simulation.json"

# 配置片段（含 pyMSER）
environment:
  work_dir: "/path/to/work"
  raspa_version: "raspa2"           # 或 raspa3
  raspa_dir: "/path/to/raspa2"      # RASPA2 路径
  raspa2_cif_dir: "/path/to/cif"
  template_path: "/path/to/simulation.input"
  raspa3_conda_env: "raspa3"
  raspa3_json_dir: "/path/to/raspa3json"
  raspa3_cif_base_path: "/path/to/cif/files"
  raspa3_template_path: "/path/to/simulation.json"

calculation:
  cutoff_radius: 12.8
  default_molecules: "CO2 CH4"
  csv_file_path: "data/structures.csv"
  framework_column: "refcode"
  output_directory: "calc_output"
  # pyMSER 自动平衡（RASPA2/3 通用，多组分按 mol/kg 总和判定）
  mser:
    enable: true          # 开启后 pyMSER 自动续跑
    target_cycles: 2000   # 期望平衡后样本数
    add_cycles: 400       # 每次追加的循环数
    max_iter: 20          # 最多追加次数
    uncertainty: "uSD"    # SD/SE/uSD/uSE
    conda_env: "pymser"   # 含 pymser+raspa3 的 conda 环境，R2/R3 共享
    llm: true             # 使用 MSER-LLM 截断（更靠前、平滑）
    batch_size: 5         # MSER 批大小（默认 5，平滑序列）
    tail_rel_std: 0.0     # 尾部相对波动阈值（<=0 不检查；>0 时超阈续跑）
    tail_window: 2000     # 尾部波动检测窗口（实际取 min(window, 产线样本数)）
    min_t0_frac: 0.0      # 最小 t0 占比（<=0 不限制；>0 时强制跳过前置占比）

logging:
  level: "INFO"
  file: "raspa_calc.log"
  output_dir: "1log"
  enable_job_logs: true

performance:
  enable_cache: true
  show_progress: true
```

### pyMSER 使用示例

- RASPA2：在 `config.yaml` 里设 `environment.raspa_version: "raspa2"` 与 `calculation.mser.enable: true`，准备好 `RASPA_DIR` 指向 raspa2 安装；运行 `raspa-calc`，提交的任务会在模拟结束后自动用 `pymser` 环境做平衡判定、按 `add_cycles` 续跑直至达标或达到 `max_iter`。输出包含 `mser_timeseries.csv` 和 `stats_<T>_<P>.json`。
- RASPA3：在 `config.yaml` 里设 `environment.raspa_version: "raspa3"`，并指定 `raspa3_conda_env`（运行 raspa3 的环境，如上创建的 raspa3）以及 `calculation.mser.conda_env`（运行 pyMSER 的环境，默认 pymser）。运行 `raspa-calc` 后的 RASPA3 任务由 `runjobs_raspa3.sh` 调度：模拟阶段用 `raspa3_conda_env` 执行 `raspa3`，平衡判定与续跑用 `pymser` 环境解析输出并追加 `add_cycles`，多组分以 mol/kg 总和作为判据。
- 参数筛选：共用 `calculation.mser`，也可在 `parameter_screening.mser` 覆盖；生成的参数筛选作业会在模拟完成后自动运行 pyMSER，并基于 JSON 重启（`RestartFileName`）续跑，不再使用二进制重启。

#### 节点优先级配置

在 `config.yaml` 设置节点权重，数字越大优先级越高。支持 `environment.node_priorities` 与 `calculation.node_priorities` 两处配置。例如：

```yaml
environment:
  node_priorities:
    worker-node-01: 4
    worker-node-02: 3
    worker-node-03: 2
    master-node: 1
```

- `raspa-calc` 高通量模式：会按优先级和实时空闲核数生成 `.raspa_node_plan`，日志显示“节点任务分配总览”。每个 sbatch 显式带 `--nodelist`。
- `raspa-scale` 扩缩容：自动读取优先级（即使无 PyYAML 也能解析），重建 `.raspa_node_plan` 后补交缺口，sbatch 同样带 `--nodelist`。
- 负载感知：当节点 CPU 负载或已分配比例 ≥85% 时跳过，≥70% 时仅按可用核的一半分配，优先把任务洒向空闲且高权重的节点。

## 集群部署

### 多节点集群配置

v2.5.0 支持在SLURM/PBS集群上进行多节点高通量计算。详见 [CLUSTER_DEPLOYMENT_GUIDE.md](CLUSTER_DEPLOYMENT_GUIDE.md)。

#### NFS共享存储配置

> v2.5.0+ 推荐使用 `/.raspa_tools/nfs/` 目录下的脚本来配置 NFS（已整合并重命名）。

**服务器端**：
```bash
sudo mkdir -p /shared/raspa2-calc
sudo chown -R zjp:zjp /shared/raspa2-calc
echo "/shared/raspa2-calc 10.10.14.0/24(rw,sync,no_root_squash)" | sudo tee -a /etc/exports
sudo systemctl enable --now nfs-server rpcbind
sudo exportfs -ra
```

**客户端**：
```bash
sudo yum install -y nfs-utils
echo "10.10.14.12:/shared/raspa2-calc /home/zjp/raspa2-calc nfs4 rw,hard,intr 0 0" | sudo tee -a /etc/fstab
sudo mount -a
```

**脚本方式（推荐）**：
```bash
# 单节点客户端配置（在客户端执行）
bash .raspa_tools/nfs/nfs_client_setup.sh

# 批量把客户端脚本拷贝到各节点（在 NFS 服务器上执行）
bash .raspa_tools/nfs/nfs_setup_all_nodes.sh
```

#### 使用方法

**重要**：多节点任务调度必须在NFS挂载目录下提交任务：

```bash
cd /home/zjp/raspa2-calc
raspa-calc
```

### 环境变量设置

```bash
# RASPA 通用
export RASPA_WORK_DIR=/path/to/work

# RASPA2 专用
export RASPA_DIR=/path/to/raspa2

# RASPA3 conda 初始化
source ~/anaconda3/etc/profile.d/conda.sh

# 防止线程冲突
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
```

## 常见问题

### Q: 如何切换 RASPA2/RASPA3 版本？

A: 在 `config.yaml` 中设置：
```yaml
environment:
  raspa_version: "raspa3"  # 或 "raspa2"
```

或在运行时选择版本覆盖配置。

### Q: RASPA3 数据提取为空？

A: 检查以下几点：
1. 确认输出文件存在：`ls output/*.txt`
2. 确认包含 Loadings 部分：`grep -A 20 "^Loadings" output/*.txt`
3. 确认模拟已完成：`grep "Simulation finished" output/*.txt`

### Q: RASPA3 conda 环境找不到？

A: 确保：
1. 所有计算节点有相同的 conda 环境名称
2. 在作业脚本中正确激活环境：
```bash
source ~/anaconda3/etc/profile.d/conda.sh
conda activate raspa3
```

### Q: 如何配置 RASPA3 的分子定义？

A: 在 `raspa3_json_dir` 目录下放置所有需要的 JSON 文件：
- `force_field.json` (必须)
- `simulation.json` (模板)
- 分子定义文件 (`CO2.json`, `CH4.json` 等)

程序会自动复制 these 文件到每个任务目录。

### Q: 支持哪些作业调度系统？

A: v2.5.0 支持：
- SLURM (sbatch) - 完整的多节点集群支持 + RASPA3
- PBS (qsub) - RASPA2/RASPA3
- 本地模式 (bash)

## 版本历史

### v2.4.0 - RASPA3 支持版本（2025-12）

**新增功能**：
- 支持 RASPA2/RASPA3 双版本切换
- 自动版本检测（simulation.json vs simulation.input）
- RASPA3 数据提取器（科学计数法格式解析）
- RASPA3 专用配置项（conda环境、JSON目录等）
- Loadings 段落精确定位（避免与组件定义混淆）

**修复**：
- 修复 RASPA3 温度/压力提取（避免匹配 "Unit of temperature"）
- 修复 RASPA3 组件块提取（从 Loadings 部分提取）

### v2.3.0 - 集群优化版本（2025-10）

**核心优化**：
- SLURM作业数组 - 一次提交N个子任务
- 共享任务队列 - 原子竞争机制
- 动态并发缩放 - raspa-scale 实时调整

**功能增强**：
- 六大计算模式
- 多节点集群支持
- 原子文件锁
- CSV数据集成
- 警告处理系统

### v2.2 - 修复验证版本
- 并发安全修复
- 状态检查逻辑修复
- 参数传递修复

### v2.1 - 功能增强版本
- 智能子目录检测
- 动态参数配置
- 多调度系统适配
- 模拟模式
- 错误处理增强

### v2.0 - 核心重写版本
- 任务提交逻辑重写
- 集成raspa-calc
- 智能任务管理
- CPU动态分配

## 贡献

欢迎提交Issue和Pull Request来改进这个工具。

## 许可证

MIT License
