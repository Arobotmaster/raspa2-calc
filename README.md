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
| **实时任务监控** | `raspa-status` / `raspa-scale status` 基于当前目录统计 | 精确进度报告 |

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
- *参数筛选* (`python -m raspa_calc.entrypoints.parameter_screening`)：快速测试参数组合，高通量调度提交，可用 `raspa-scale` 动态扩缩容
- *高通量计算* (`python -m raspa_calc.entrypoints.task_runner`)：批量处理框架结构，支持960+核心并行
- *数据提取* (`python -m raspa_calc.entrypoints.data_extractor`)：解析RASPA输出，生成Excel/CSV报表，自动检测版本
- *警告处理* (`python -m raspa_calc.entrypoints.warning_processor`)：提取失败任务、CSV数据替换
- *等温线绘制* (`python -m raspa_calc.entrypoints.isotherm_plotter`)：可视化吸附数据
- *CSV/CIF 筛选* (`python -m raspa_calc.entrypoints.ciffilter`)：交互式按条件/refcode筛选CSV，可复制匹配的CIF
####
 **详细指南** 参考`docs/`（各个功能使用说明）

### 执行优化
- *SLURM作业数组*：`sbatch --array=1-N` 一次提交N个子任务，提交速度快50倍
- *共享任务队列*：`.raspa_task_queue` 原子弹出机制，减少90% NFS扫描
- *动态并发缩放*：`raspa-scale` 支持交互(-i)与自动(-y)选择并发
- *并发安全*：原子文件锁 + 三级任务队列，支持NFS和高并发

### 系统特性
- *多节点集群*：SLURM + NFS 共享存储，支持异构节点和960+ CPU核心
- *零配置检测*: /PBS/LOCAL，环境适配即插即用
- *实时监控*：`raspa-status` / `raspa-scale status` 精确统计任务状态，支持按子目录查看
- *配置灵活*：YAML配置 + 交互式参数设置，支持多种气体分子
- *完整诊断*：`raspa-diagnose` 检查环境、依赖、工具链
- *智能恢复*：失败任务自动检查、标记和重试

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
### Python 模块入口（可直接运行）

```bash
python -m raspa_calc                      # 主交互入口（同 raspa-calc）
python -m raspa_calc.entrypoints.task_runner      # 高通量 runner
python -m raspa_calc.entrypoints.data_extractor # 数据提取
python -m raspa_calc.entrypoints.parameter_screening
python -m raspa_calc.entrypoints.warning_processor
python -m raspa_calc.entrypoints.isotherm_plotter
python -m raspa_calc.entrypoints.ciffilter
```
## 命令行工具参考-**详细指南看docs**

### 主入口：raspa-calc
```bash
raspa-calc
```
**功能**：主程序入口，支持6种计算模式，自动检测 RASPA 版本

### 任务监控：raspa-status / raspa-scale status
```bash
raspa-status           # 查看任务状态统计
raspa-status -d output # 显示详细任务列表
raspa-status -r        # 重置失败任务状态
raspa-status -m        # 实时监控任务进度
raspa-scale status -d output
```

### 动态缩放：raspa-scale
```bash
raspa-scale           # 默认进入交互菜单（含状态查看）
raspa-scale -i 核心数    # 交互式
raspa-scale -y 核心数    # 自动采用建议并发
raspa-scale kill -n worker-node-01:10,worker-node-02:5  # 按节点终止指定数量作业
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
