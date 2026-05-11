# pyMSER（pymser）自动平衡使用说明

本项目支持在 RASPA2 / RASPA3 模拟结束后，使用 `pymser`（pyMSER）自动判定平衡截断点 `t0`，并输出平衡段平均值与不确定度。

默认策略是：只要 pyMSER 成功给出 `t0` 并完成统计，就写出 `stats.json` 并将任务视为成功。`target_cycles` 只作为日志中的参考目标，不再因为 `len(series) - t0 < target_cycles` 直接判定为 failed。若确实需要自动续跑补足目标样本数，可显式开启 `extend_until_target: true`。

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
    extend_until_target: false
```

字段含义：
- `enable`: 是否启用自动平衡
- `target_cycles`: “平衡后生产样本数”参考目标（`len(series) - t0`）；默认不作为 failed 判据
- `add_cycles`: `extend_until_target: true` 时，每次续跑追加的循环数
- `max_iter`: `extend_until_target: true` 时，最多续跑次数
- `uncertainty`: `SD/SE/uSD/uSE`（传给 pyMSER 的平均值不确定度计算）
- `conda_env`: 包含 `pymser` 的 conda 环境名
- `llm` / `batch_size`: 仅 RASPA3 脚本使用（传给 `pymser.equilibrate`）
- `extend_until_target`: 是否把 `target_cycles` 当作强制续跑目标；默认 `false`

说明：
- 平衡截断点使用 pyMSER 自带的 `t0`（默认判据）。
- pyMSER 成功时会写 `stats.json`；若平衡后样本数低于 `target_cycles`，会在 `mser_status.txt` / `status.txt` 中记录类似 `mser_stats_below_target:990/1000` 的说明，但不标记为 failed。
- worker 调用 pyMSER 时默认禁用 CUDA（`CUDA_VISIBLE_DEVICES=""`），避免 PyTorch 自动选择不兼容 GPU 导致 pyMSER 异常失败。
- `tail_rel_std` / `tail_window` / `min_t0_frac` 已弃用并会被忽略（避免因额外阈值导致任务被误判为失败）。

## 3) 运行流程（自动）

- RASPA2 高通量：`RASPA_TOOL_DIR/scripts/shell/workers/runjobs.sh` 在模拟成功后调用 `raspa_calc.domain.algorithms.auto_mser_raspa2`
- RASPA3 高通量：`RASPA_TOOL_DIR/scripts/shell/workers/runjobs_raspa3.sh` 在检测到 `output/` 输出后调用 `raspa_calc.domain.algorithms.auto_mser_raspa3`

脚本会在任务目录下写出：
- `auto_mser.log`: 每次迭代的 `t0`、样本数与续跑信息
- `mser_timeseries.csv`: 累积时间序列（用于调试/复算）
- RASPA2：`stats_<T>_<P>.json`；RASPA3：`stats.json`（平衡后均值与不确定度）

## 4) 手动复跑/排查

若想对某个 `mc*` 目录单独复跑（以 RASPA3 为例）：
- `PYTHONPATH=$HOME/raspa2-calc/.raspa_tools/src conda run -n pymser python -m raspa_calc.domain.algorithms.auto_mser_raspa3 --workdir /path/to/mcXXX`

常见排查点：
- 看 `auto_mser.log`：确认 pyMSER 的 `t0`、平衡后样本数、是否写出 `stats.json`
- 如果看到 `mser_stats_below_target:当前/目标`：表示 pyMSER 已成功统计，只是平衡后样本数低于参考目标；默认不会判 failed
- 如果确实需要“必须补足生产样本数”，设置 `extend_until_target: true`，再调大 `add_cycles/max_iter/target_cycles`
- 看 `auto_mser_raspa.log`（RASPA3）：续跑时 `raspa3` 是否真的执行成功
- 若启用 pyMSER，`failed_mser`/`__failed` 通常表示 pyMSER 解析/统计异常或显式续跑失败（先看 `auto_mser.log` 的 traceback/状态说明）
