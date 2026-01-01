# RASPA3 综合参考手册与使用指南

> **版本**：2025-12-22
> **适用版本**：RASPA 3.0+
> **来源**：基于官方文档、J. Chem. Phys. 2024 论文及源码分析整理

---

## 1. 🎯 模拟方法决策指南 (Simulation Method Decision Matrix)

在开始模拟前，请根据您的**研究目标**选择合适的方法：

| 研究目标                  | 推荐方法                                | 典型应用                                       | 关键参数/示例                  |
| :------------------------ | :-------------------------------------- | :--------------------------------------------- | :----------------------------- |
| **吸附等温线**      | **GCMC** (Grand Canonical MC)     | 计算 MOF/Zeolite 在不同压力下的吸附量          | `basic/8`, `basic/10`      |
| **混合物吸附**      | **GCMC** (Multi-component)        | 气体分离选择性 (Selectivity)、共吸附           | `nonbasic/1` (Fugacity)      |
| **高密度/低温吸附** | **CFCMC** (Continuous Fractional) | 传统 GCMC 插入困难的体系（如水、大分子、高压） | `advanced/2`                 |
| **气体密度/力场验证** | **NPT-MC** (Isobaric-Isothermal)  | 给定 P,T 预测体相气体的密度、验证 $U_{gg}$ | `nonbasic/2`, `nonbasic/3` |
| **扩散系数**        | **MD** (Molecular Dynamics)       | 计算自扩散系数 (Self-diffusivity)、MSD         | `basic/5`, `basic/13`      |
| **气液平衡 (VLE)**  | **Gibbs-Ensemble**                | 计算纯组分或混合物的蒸气压、密谋               | `advanced/1`                 |
| **相变与亚稳态**    | **TMMC** (Transition Matrix)      | 识别毛细凝聚、吸附滞后环、精确自由能           | `advanced/5`                 |
| **复杂构型/能垒**   | **HMC** (Hybrid MC)               | MC 与 MD 结合，跨越复杂势能面能垒              | `advanced/4`                 |
| **大体系加速**      | **Grid Interpolation**            | 预计算势能网格，加速 >3x3x3 晶胞的模拟         | `auxiliary/5`                |
| **吸附位点分析**    | **Density Grids**                 | 可视化分子在孔道中的分布热图                   | `density_grids/*`            |

---

## 2. 🧪 吸附与热力学模拟 (Adsorption & Thermodynamics)

此板块主要关注**蒙特卡洛 (MC)** 模拟，用于计算平衡态性质。

### 2.1 基础吸附 (Basic GCMC)

适用于简单分子的单组分吸附。

- **核心参数**：`TranslationProbability`, `RotationProbability`, `SwapProbability` (必须 > 0)
- **示例**：
  - `basic/8_mc_adsorption_of_methane_in_mfi`: 最标准的甲烷吸附等温线。
  - `basic/10_mc_adorption_co2_in_mfi`: CO₂ 吸附（需开启 `ChargeMethod: "Ewald"`）。

### 2.2 混合物分离 (Mixtures)

适用于计算吸附选择性 `S = (x1/y1) / (x2/y2)`。

- **关键概念**：
  - **Fugacity (逸度)**：混合物模拟建议指定各组分的逸度而非分压。
  - 公式：$f_i = \phi_i \cdot y_i \cdot P_{total}$ ($\phi_i$ 为逸度系数)。
- **示例**：`nonbasic/1_mc_adsorption_binary_mixture`
  - 定义两个 `Components`，分别指定 `MolFraction` 或 `FugacityCoefficient`。

### 2.3 NPT 系综 (Isobaric-Isothermal)

用于预测在特定温度和压力下，纯流体或混合物的**体相密度**。通常用于验证力场或作为 GCMC 的输入条件。

- **核心参数**：`VolumeMoveProbability` (允许盒子体积变化)
- **示例**：`nonbasic/2_mc_npt_co2`

> [!TIP]
> **验证逻辑**：如果 NPT 模拟出的密度与实验值（如 NIST）不符，说明分子的 L-J 参数或电荷模型本身存在问题。这是验证客体-客体 ($U_{gg}$) 相互作用的基础。详见 [2.5 节](#25-力场验证工作流-force-field-validation-workflow)。

### 2.4 亨利系数 (Henry Coefficients)

用于表征无限稀释下的吸附强度，预测低压吸附行为。

- **方法**：使用 Widom 插入法或 NVT 模拟计数。
- **示例**：`basic/12_mc_henry_coefficient`

> [!TIP]
> **验证逻辑**：亨利系数对客体-框架 ($U_{gh}$) 相互作用极其敏感。如果分子的体相密度（NPT）正确但亨利系数错误，通常说明框架电荷或框架原子的 L-J 参数需要调整。

### 2.5 力场验证工作流 (Force Field Validation Workflow)

在进行大规模筛选前，必须确保所选力场（如 TraPPE, UFF, DREIDING）能够准确描述物理过程。推荐的验证逻辑分为 **“单元测试 (Unit Test)”** 与 **“终期考核 (Final Test)”**：

#### 阶段 0：客体-客体 ($U_{gg}$) 验证（NPT）
- **指标**：纯流体密度、蒸发焓。
- **作用**：基本功测试。确保分子的尺寸和极性模型是正确的。

#### 阶段 1：客体-框架 ($U_{gh}$) **诊断**（Henry Coeff / Isotherm 初期）
- **指标**：亨利系数、吸附热 ($Q_{st}$)、极低压吸附量。
- **作用**：**诊断工具**。由于低压下分子间几乎不碰撞，结果偏差可直接定位到“框架电荷”或“骨架参数”问题。

#### 阶段 2：综合性 **终检**（Full Isotherm）
- **指标**：全压力范围等温线。
- **作用**：**最终验证**。这是与实验数据对标的标准方式。如果阶段 0 和 1 都过了但阶段 2 失败，说明是高压下分子堆积或极性相互作用描述有误（GG 作用）。

> [!IMPORTANT]
> 虽然大多数研究直接对比等温线，但当模拟与实验不符时，**亨利系数和 NPT 是唯一的“排雷”手段**，用于区分是分子模型错了，还是框架弄错了。

---

## 3. 🚀 动力学与输运性质 (Dynamics & Transport)

此板块主要关注**分子动力学 (MD)** 模拟，用于计算随时间演化的性质。

### 3.1 自扩散系数 (Self-Diffusivity)

通过均方位移 (MSD) 计算扩散系数 $D_s = \lim_{t \to \infty} \frac{1}{6t} \text{MSD}(t)$。

- **设置**：
  - `SimulationType: "MolecularDynamics"`
  - `Ensemble: "NVT"` 或 `"NVE"`
  - `ComputeMSD: true`
  - `SampleMSDEvery`: 采样频率
- **示例**：
  - `basic/5_md_methane_in_box_nve`: 基础 NVE 扩散。
  - `basic/13_md_diffusion_co2_in_mfi`: 骨架中的扩散（需注意恒温器设置）。

### 3.2 结构与光谱分析 (Structure & Spectra)

RASPA3 支持在 MD 中实时计算多种关联函数：

- **RDF (径向分布函数)**：`ComputeRDF: true`，用于分析分子间或分子-骨架距离。
  - 示例：`basic/14_md_rdf_co2_in_mfi`
- **VACF (速度自相关函数)**：`ComputeVACF: true`，用于计算扩散谱或声子谱。
- **Order-N MSD**: 优化的 MSD 算法，适合长时间模拟。

---

## 4. ⚖️ 相平衡与相变 (Phase Equilibria)

### 4.1 Gibbs 系综 (VLE)

直接模拟气液两相共存，无需显式界面。需要两个模拟盒子。

- **应用**：计算纯物质或混合物的饱和蒸气压、液体密度、气体密度。
- **配置**：
  - `Systems`: 定义两个 Box。
  - `GibbsVolumeMoveProbability`: 允许两个盒子交换体积。
  - `GibbsSwapProbability`: 允许两个盒子交换粒子。
- **示例**：
  - `advanced/1_mc_gibbs_co2`: CO₂ 气液平衡。

### 4.2 Transition Matrix MC (TMMC)

通过计算粒子数概率分布 (PNPD) 来连接微观状态与宏观性质。

- **应用**：精确测定相变点、研究亚稳态（如过冷蒸气）、计算自由能垒。
- **工作流**：
  1. 在同一温度/压力下进行多个模拟（覆盖不同 N 范围）。
  2. 使用 `combine-tmmc-data.py` 拼接分布。
  3. 使用直方图重加权 (Histogram Reweighting) 获得完整等温线。
- **示例**：`advanced/5_tmmc_methane_in_tobacco_667`

---

## 5. 🛠️ 高级功能与性能优化 (Advanced Features)

### 5.1 Blocking Pockets (阻塞口袋)

用于人为“关闭”多孔材料中的某些区域（如不通孔道、死体积），防止分子进入。

- **原理**：定义一系列球形或矩形区域，若分子试图进入则被拒绝。
- **配置** (在 `Components` 中)：
  ```json
  "blockingPockets": [
     [cx, cy, cz, radius],  // 定义球形阻塞区
     ...
  ]
  ```
- **示例**：`nonbasic/6_mc_adsorption_co2_in_lta_4a_sodium`

### 5.2 Grid Interpolation (网格插值加速)

对于大体系（>3x3x3 晶胞），实时计算主客体相互作用非常耗时。网格法预先计算势能场，将模拟速度提升 5-20 倍。

- **流程**：
  1. 在 `force_field.json` 中定义网格参数 (`UseInterpolationGrids`).
  2. RASPA 启动时自动生成网格（VDW 和 Coulomb）。
  3. 模拟过程中查表插值。
- **参数** (在 `force_field.json` 中):
  ```json
  "UseInterpolationGrids": ["C_co2", "O_co2"],
  "SpacingVDWGrid": 0.15,
  "InterpolationScheme": 3
  ```
- **示例**：`auxiliary/5_make_grids`

### 5.3 Density Grids (密度网格可视化)

生成分子在空间中的概率分布热图，用于识别强吸附位点。

- **功能**：
  - **Site-Resolved**：可针对特定原子生成网格（如只看 CO2 的 C 原子）。
  - **Equitable Binning**：平滑化处理，减少离散化伪影。
- **配置参数**：
  ```json
  "ComputeDensityGrid": true,
  "DensityGridSize": [128, 128, 128],
  "DensityGridPseudoAtomsList": ["C_co2"]
  ```
- **示例**：`examples/density_grids/*`

### 5.4 结果可视化与输出

RASPA3 支持多种输出格式用于后处理：

- **PDB Movies**: `output/Movies` 目录，可用 VMD / iRASPA 打开观看轨迹。
- **Histograms**:
  - `EnergyHistogram`: 能量分布，用于 TMMC 分析。
  - `NumberOfMoleculeHistogram`: 分子数分布，用于计算 PNPD。
- **Tail Corrections**: 对于 CFCMC，支持长程尾部校正 (Tail-corrections)，提高能量计算精度。

---

## 6. ⚠️ 实验性功能 (Experimental)

以下功能在 RASPA3 中已实现但仍在完善中，使用需谨慎：

- **Flexible Molecules (CBMC)**: 柔性分子的蒙特卡洛生长。目前支持基本的 Rosenbluth 权重计算，但全功能的柔性 MC 模拟仍在优化中。
- **Partial Insertion Move**: 部分插入移动，用于提高稠密体系的接受率。
- **Flexible Frameworks**: 柔性骨架支持（目前主要作为刚性处理，完全的柔性骨架模拟建议仍参考 RASPA2 或等待后续更新）。

---

---

## 7. ⚙️ 输入文件配置详解

### 7.1 关键模拟参数

| 参数                             | 说明                                                                    | 推荐值                                   |
| :------------------------------- | :---------------------------------------------------------------------- | :--------------------------------------- |
| `SimulationType`               | `MonteCarlo` / `MolecularDynamics` / `MonteCarloTransitionMatrix` | -                                        |
| `NumberOfCycles`               | 总模拟步数                                                              | MC:$10^5 \sim 10^6$; MD: 根据 TimeStep |
| `NumberOfInitializationCycles` | 初始化步数（不采样）                                                    | 总步数的 10%                             |
| `PrintEvery`                   | 屏幕输出频率                                                            | 1000 - 5000                              |
| `ForceField`                   | 力场名称                                                                | "Local"建议放在执行任务的目录            |

### 7.2 MC 移动概率推荐 (Weights)

总和不必为 1，程序会自动归一化。建议根据分子类型调整：

| 移动类型 (`Probability`) | 小分子 (CH₄, N₂) | 极性/长链 (CO₂, Alkanes) |  高密/难插入  | 说明                 |
| :------------------------- | :----------------: | :-----------------------: | :-----------: | :------------------- |
| `Translation`            |        0.5        |            1.0            |      1.0      | 平移                 |
| `Rotation`               |        0.5        |            1.0            |      1.0      | 旋转                 |
| `Swap`                   |        1.0        |            0.0            |      0.0      | 粒子交换 (GCMC)      |
| `Reinsertion`            |        0.5        |            1.0            |      1.0      | 重新生长 (CBMC)      |
| `CFCMC_CBMC_Swap`        |         -         |             -             | **1.0** | 分数分子交换 (CFCMC) |
| `IdentityChange`         |         -         |             -             |      1.0      | 混合物组分互换       |

---

## 8. ⏱️ 工业级筛选流水线架构 (Industrial-Grade Screening Pipeline)

针对大规模材料筛选（>1000 MOFs），建议采用以下优化策略以平衡**计算效率**与**物理保真度**。

### 8.1 计算效率优化

#### A. 能量网格 (MakeGrid) 路由策略
对于大晶胞体系，预计算势能网格可大幅加速模拟。
- **适用条件**：骨架原子数 > 500-1000，且骨架电中性且不含移动离子。
- **禁忌场景**：若骨架带电或含可移动离子（如 $Na^+$），**严禁使用 MakeGrid**，必须强制使用 `ChargeMethod: "Ewald"`。
- **配置**：在 `force_field.json` 中设置 `"UseInterpolationGrids": ["C_co2", ...]`。

#### B. 自适应最小扩胞策略 (Adaptive Unit Cells)
$XYZ$ 轴独立计算扩胞倍数：$k_i = \lceil 2 \times \text{Cutoff} / L_i \rceil$，避免不必要的原子重复。

### 8.2 物理显式性优化

#### A. 基于几何探测的死区屏蔽 (Blocking Pockets)
- **工作流**：结合 **Zeo++** (`-vol`) 探测非连通空腔，自动生成 `blockingPockets` 列表填入 `simulation.json`。
- **意义**：确保物理可及空间与实验有效孔隙一致，防止吸附量虚高。

#### B. 热力学逸度修正 (Fugacity Correction)
在高压下，务必通过外部 Python 库（如 PR-EOS）计算**偏逸度系数**并填入 `FugacityCoefficient` 字段，理想气体假设（=1.0）在高压下误差显著。

---

## 9. 🚀 安装与运行

### 两种安装方式

| 包名               | 安装命令                                | 用途                                                             |
| ------------------ | --------------------------------------- | ---------------------------------------------------------------- |
| **raspa3**   | `conda install -c conda-forge raspa3` | **推荐**：命令行程序，读取 `simulation.json`，适合高通量 |
| **raspalib** | `conda install conda-forge::raspalib` | Python 库，用于交互式开发                                        |

### 快速开始 (Command Line)

```bash
# 1. 准备目录
mkdir my_simulation && cd my_simulation
# 2. 准备文件：simulation.json, force_field.json, molecule.json, framework.cif
# 3. 运行
raspa3
# 4. 查看结果
cat output/*.txt
```

---

## 10. 🔄 Restart 文件详解

### Restart 机制对比

| 特性           | Binary Restart (`restart_data.bin`)   | JSON Restart (`restart_*.json`)  |
| -------------- | --------------------------------------- | ---------------------------------- |
| **用途** | **崩溃自动恢复** (Crash Recovery) | **手动续算** / 修改条件续跑  |
| **配置** | `WriteBinaryRestartEvery`             | `writeRestartEvery`              |
| **恢复** | `ContinueAfterCrash: true`            | 在 JSON 中指定 `RestartFileName` |

### 如何使用 JSON Restart 续算？

1. 复制 `output/restart_*.json` 到当前目录。
2. 修改 `simulation.json`：
   - 系统部分添加：`"RestartFileName": "restart_240_0.s0"` (不要加 .json 后缀)
   - 组件部分设置：`"CreateNumberOfMolecules": 0` (**必须设为0**)

---

## 11. 📚 常见问题 (FAQ)

### Q: RASPA2 与 RASPA3 主要区别？

- **输入格式**：RASPA2 使用 `simulation.input` (文本)，RASPA3 使用 `simulation.json`。
- **力场定义**：RASPA3 将力场完全参数化在 `force_field.json` 中，不再依赖 `force_field_mixing_rules.def`。
- **性能**：RASPA3 对现代硬件进行了优化，特别是对大体系的 Ewald 求和与 CFCMC。

### Q: 什么时候使用 Fugacity 还是 Pressure？

- 单组分：两者均可，Pressure 更直观。
- **混合物**：**强烈推荐使用 Fugacity**。因为在混合物中，如果指定总压和摩尔分数，RASPA 内部还是会用状态方程算出逸度。直接指定逸度能避免状态方程带来的误差，且定义更符合热力学平衡条件 ($f_i^{gas} = f_i^{ads}$)。

### Q: 能否计算柔性骨架 (Flexible Frameworks)？

- **RASPA3 目前主要支持刚性骨架**。
- 虽然代码中有部分柔性支持的基础，但正式的柔性骨架 MD/MC 仍在 Experimental/Todo 阶段 (参考 README)。建议暂时视为刚性骨架模拟器。

---

## 12. 🔄 RASPA2 vs RASPA3 深度对比 (Migration Guide)

从 RASPA2 迁移到 RASPA3 不仅仅是格式的变化，更是从“分散式文本”向“结构化 JSON 驱动”的演进。

### 12.1 核心文件映射关系

| 功能模块 | RASPA2 (Legacy) | RASPA3 (Modern JSON) | 关键变化 |
| :--- | :--- | :--- | :--- |
| **模拟参数** | `simulation.input` | `simulation.json` | 层次化结构，支持更复杂的组件定义 |
| **力场混合** | `force_field_mixing_rules.def` | `force_field.json` (SelfInteractions) | L-J 参数与混合规则整合 |
| **原子属性** | `pseudo_atoms.def` | `force_field.json` (PseudoAtoms) | **大幅简化**：质量、电荷不再分散 |
| **分子定义** | `molecules/SO2.def` | `SO2.json` | 包含坐标、键、临界常数的独立对象 |
| **骨架处理** | 隐式 (根据 CIF 原子名) | 显式 (`"framework": true`) | JSON 中需明确标记哪些原子属骨架 |

### 12.2 参数级转换逻辑 (Conversion Logic)

基于高通量转换脚本（如 `convert_forcefield.py`）的逻辑：

#### A. 力场合并 (Force Field Consolidation)
RASPA3 将旧版的两个 `.def` 文件合二为一。
- **质量与电荷**：从 `pseudo_atoms.def` 的第 6-7 列提取，填入 JSON 的 `PseudoAtoms` 数组。
- **L-J 参数**：从 `mixing_rules.def` 提取 $\epsilon, \sigma$，填入 JSON 的 `SelfInteractions`。
- **截断与修正**：`shifted/truncated` 和 `TailCorrections` 变为 JSON 的顶层布尔/字符串。

#### B. 分子定义 (Molecule Definitions)
- **临界常数**：旧版 `.def` 顶部的三行（$T_c, P_c, \alpha$）变为 JSON 顶层字段。
- **坐标映射**：`pseudoAtoms` 数组存储 `[类型, [x, y, z]]`，极易通过 NumPy 处理。
- **键信息**：旧版 `Bond stretch:` 后的列表变为 JSON 的 `Bonds` 索引对（如 `[0, 1]`）。

#### C. 模拟控制 (Simulation Input)
- **组件权重**：RASPA2 的 `TranslationProbability` 等变为 `Components` 下的 `Weights` 字典。
- **运行设置**：`NumberOfCycles` 和 `PrintEvery` 依然保留，但位置移入顶层 JSON 对象。

---

## 13. 🏗️ 高通量计算实践 (High-Throughput with `raspa2-calc`)

在大规模筛选任务中，推荐使用类似 `raspa2-calc` 的自动化管理架构。其核心逻辑如下：

### 13.1 自动化工作流架构
1.  **模板化配置**：
    -   维护一个基础 `simulation.json` 模板。
    -   使用 Python 脚本解析 CIF 晶胞参数，动态调整 `UnitCells`。
2.  **文件分发**：
    -   每个任务建立独立文件夹。
    -   从中心库（`raspa3_json_dir`）拷贝 `force_field.json` 和对应的 `Molecule.json`。
3.  **环境管理**：
    -   在提交脚本（如 SLURM/PBS）中自动 `conda activate raspa3`。
4.  **数据提取**：
    -   利用 RASPA3 统一的 `output/*.txt` 命名规则。
    -   通过 Python 解析输出文件中的 `Average density`, `Average loading [mg/g]` 等关键字段。

### 13.2 典型任务目录结构
```text
project/
├── force_fields/          # 存储各种力场的 JSON
├── molecules/             # 存储分子的 JSON
├── structures/            # 存储各材料的 CIF
└── tasks/
    └── task_MOF_001/      # 自动生成的任务目录
        ├── simulation.json  # 针对该材料定制
        ├── force_field.json # 拷贝自 force_fields/
        ├── CO2.json        # 拷贝自 molecules/
        └── framework.cif   # 拷贝自 structures/
```

---

*文档维护：基于 RASPA3 v3.0.18*
