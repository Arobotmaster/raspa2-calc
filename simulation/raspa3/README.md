# RASPA3 simulation.json 模板库

整理自 `/home/zjp/RASPA3/examples`，按用途分类。

## 文件列表

| 文件 | 用途 | 插入方法 | 系综 |
|------|------|----------|------|
| `mc_adsorption_cbmc.json` | 单组分吸附等温线 | CBMC (SwapProbability) | μVT |
| `mc_adsorption_conventional.json` | 单组分吸附等温线 | Conventional (SwapConventionalProbability) | μVT |
| `mc_adsorption_cfcmc.json` | 单组分吸附等温线 | CFCMC (CFCMC_SwapProbability) | μVT |
| `mc_adsorption_cfcmc_cbmc.json` | 单组分吸附等温线 | CB-CFCMC (CFCMC_CBMC_SwapProbability) | μVT |
| `mc_adsorption_binary_cbmc.json` | 二元混合物吸附等温线 | CBMC | μVT |
| `mc_henry_coefficient.json` | Henry 系数 / 零载荷吸附 | Widom 插入 | NVT |
| `mc_enthalpy_zero_loading.json` | 零载荷吸附焓 | 单分子 NVT | NVT |
| `mc_npt_fluid.json` | 纯流体 NPT 性质 | 体积移动 | NPT |
| `mc_gibbs_vle.json` | 气液平衡 (VLE) | Gibbs CFCMC | Gibbs |
| `mc_rosenbluth_weight.json` | 理想气体 Rosenbluth 权重 | Widom | NVT |
| `md_diffusion_nvt.json` | 分子动力学扩散系数 (MSD) | — | NVT-MD |

## 插入方法选择指南

- **CBMC** (`SwapProbability`): 适合链状/柔性分子，标准选择
- **Conventional** (`SwapConventionalProbability`): 适合小球形分子（甲烷、惰性气体）
- **CFCMC** (`CFCMC_SwapProbability`): 适合高密度/强相互作用体系，收敛更稳定，需要 `ThermodynamicIntegration: true`
- **CB-CFCMC** (`CFCMC_CBMC_SwapProbability`): 结合 CFCMC 和 CBMC 优点，适合链状分子在高密度体系，需要 `ThermodynamicIntegration: true`

## 占位符说明

模板中的占位符在使用时替换：

- `FRAMEWORK_NAME` → CIF 文件路径（RASPA3 需要绝对路径）或框架名称
- `MOLECULE_NAME` → 分子名称（对应 `.json` 分子定义文件名）
- `FORCE_FIELD_DIR` → 力场目录路径（包含 `force_field.json` 的目录）

## 在 raspa-calc 中使用

在 `config.yaml` 的 `parameter_screening.parameters` 中指定模板路径：

```yaml
parameter_screening:
  parameters:
    raspa3_template_path:
      - "/home/zjp/raspa2-calc/.raspa_tools/simulation/raspa3/mc_adsorption_cbmc.json"
      - "/home/zjp/raspa2-calc/.raspa_tools/simulation/raspa3/mc_adsorption_cfcmc_cbmc.json"
    raspa3_json_dir:
      - "/path/to/force_field_A"
      - "/path/to/force_field_B"
    ExternalTemperature: [300, 350]
    ExternalPressure: [1e4, 1e5, 1e6]
```

## ChargeMethod 选择

- `"None"`: 无电荷，适合 TraPPE-UA 等联合原子力场
- `"Ewald"`: Ewald 求和，适合带电荷的分子（CO₂、H₂O、OPLS 等）
