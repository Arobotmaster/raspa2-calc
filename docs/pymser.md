# pyMSER（pymser）自动平衡使用说明

本项目支持在 RASPA2 / RASPA3 模拟结束后，使用 `pymser`（pyMSER）自动判定平衡截断点 `t0`，并在“平衡后生产样本不足”时自动续跑补足。

## 1) 前置准备

1. 安装依赖（在 `.raspa_tools` 目录）：
   - `pip install -r requirements.txt`
2. 准备 `pymser` conda 环境（示例）：
   - `conda env create -f environment.yml`
   - 默认环境名为 `pymser`（可在配置里改）
3. 建议先自检：
   - `RASPA_WORK_DIR=/path/to/work raspa-diagnose`

## 2) 启用方式（config.yaml）

在 `config.yaml` 中开启 `calculation.mser`（参数筛选模式可用 `parameter_screening.mser` 覆盖）：

```yaml
calculation:
  mser:
    enable: true
    target_cycles: 2500
    add_cycles: 400
    max_iter: 20
    uncertainty: uSD
    conda_env: pymser
    llm: true
    batch_size: 5
```

字段含义：
- `enable`: 是否启用自动平衡
- `target_cycles`: “平衡后生产样本数”目标（`len(series) - t0`）
- `add_cycles`: 每次续跑追加的循环数
- `max_iter`: 最多续跑次数
- `uncertainty`: `SD/SE/uSD/uSE`（传给 pyMSER 的平均值不确定度计算）
- `conda_env`: 包含 `pymser` 的 conda 环境名
- `llm` / `batch_size`: 仅 RASPA3 脚本使用（传给 `pymser.equilibrate`）

说明：
- 平衡截断点使用 pyMSER 自带的 `t0`（默认判据）。
- `tail_rel_std` / `tail_window` / `min_t0_frac` 已弃用并会被忽略（避免因额外阈值导致任务被误判为失败）。

## 3) 运行流程（自动）

- RASPA2 高通量：`job_templates/runjobs.sh` 在模拟成功后调用 `raspa_calc.algorithms.auto_mser_raspa2`
- RASPA3 高通量：`job_templates/runjobs_raspa3.sh` 在检测到 `output/` 输出后调用 `raspa_calc.algorithms.auto_mser_raspa3`

脚本会在任务目录下写出：
- `auto_mser.log`: 每次迭代的 `t0`、样本数与续跑信息
- `mser_timeseries.csv`: 累积时间序列（用于调试/复算）
- RASPA2：`stats_<T>_<P>.json`；RASPA3：`stats.json`（平衡后均值与不确定度）

## 4) 手动复跑/排查

若想对某个 `mc*` 目录单独复跑（以 RASPA3 为例）：
- `PYTHONPATH=$HOME/raspa2-calc/.raspa_tools/scripts/python conda run -n pymser python -m raspa_calc.algorithms.auto_mser_raspa3 --workdir /path/to/mcXXX`

常见排查点：
- 看 `auto_mser.log`：是否一直是 “平衡后样本不足”，需要提高 `NumberOfCycles` 或调大 `add_cycles/max_iter/target_cycles`
- 看 `auto_mser_raspa.log`（RASPA3）：续跑时 `raspa3` 是否真的执行成功
- 若启用 pyMSER，`failed_mser`/`__failed` 通常表示自动平衡脚本退出码非 0（先看日志再决定是否重跑）
