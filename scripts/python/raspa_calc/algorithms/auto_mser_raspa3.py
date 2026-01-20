#!/usr/bin/env python3
"""
Auto-extend a RASPA3 run until pyMSER reports enough equilibrated samples.

Logic:
- Parse RASPA3 output/*.txt (Abs. loading average ... [mol/kg-framework]) and
  build a time series per component. Sum all mol/kg columns as the MSER series.
- Run pyMSER; if not enough equilibrated samples, update simulation.json to
  restart from the latest restart_*.json:
    * Systems[0].RestartFileName = "<restart_xxx_0.s0>" (no .json suffix)
    * Components[*].CreateNumberOfMolecules = 0
    * NumberOfCycles += add_cycles; NumberOfInitializationCycles/EquilibrationCycles = 0
- Repeat until target_cycles reached or max_iter exhausted.

Outputs:
- mser_timeseries.csv (cumulative)
- stats_<T>_<P>.json (t0, ac_time, basis, per-component averages/uncertainties)
- auto_mser.log (pyMSER iterations) and auto_mser_raspa.log (raspa3 stdout/err)
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Dict, List

import pandas as pd
import pymser


def _find_latest_restart(workdir: str) -> str:
    outdir = os.path.join(workdir, "output")
    candidates = glob.glob(os.path.join(outdir, "restart_*.json"))
    if not candidates:
        raise FileNotFoundError("未找到 restart_*.json，请确认 RASPA 已输出 JSON 重启文件（output/restart_*.json）。")
    return max(candidates, key=os.path.getmtime)


def _parse_output_to_timeseries(workdir: str) -> pd.DataFrame:
    """Parse RASPA3 output/*.txt into a time series DataFrame with mol/kg columns."""
    txt_files = glob.glob(os.path.join(workdir, "output", "*.txt"))
    if not txt_files:
        raise FileNotFoundError("未找到 output/*.txt")

    data: List[Dict[str, float]] = []
    iter_re = re.compile(r"Current\s+cycle:\s+(\d+)\s+out\s+of\s+(\d+)", re.IGNORECASE)
    comp_re = re.compile(r"component\s+\d+\s*\(([^)]+)\)", re.IGNORECASE)
    molkg_re = re.compile(r"([-\d.eE+]+)\s+mol/kg", re.IGNORECASE)

    for txt in sorted(txt_files):
        with open(txt, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        iter_matches = list(iter_re.finditer(content))
        if not iter_matches:
            continue

        for idx, m in enumerate(iter_matches):
            start = m.end()
            end = iter_matches[idx + 1].start() if idx + 1 < len(iter_matches) else len(content)
            segment = content[start:end]
            record: Dict[str, float] = {"cycle": int(m.group(1))}

            comps = list(comp_re.finditer(segment))
            for j, cm in enumerate(comps):
                name = cm.group(1).strip()
                search_start = cm.end()
                search_end = comps[j + 1].start() if j + 1 < len(comps) else len(segment)
                sub = segment[search_start:search_end]
                val = molkg_re.search(sub)
                if val:
                    try:
                        record[f"{name}_[mol/kg]"] = float(val.group(1))
                    except ValueError:
                        continue
            data.append(record)

    if not data:
        raise RuntimeError("解析 output/*.txt 未获取到吸附数据")

    df = pd.DataFrame(data)
    df["cycle"] = df["cycle"].astype(int)
    df = df.drop_duplicates(subset=["cycle"], keep="first").sort_values("cycle").reset_index(drop=True)
    for col in [c for c in df.columns if c.endswith("_[mol/kg]")]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


def _find_constant_tail_t0(series: pd.Series) -> int:
    values = series.to_numpy()
    if len(values) == 0:
        return 0
    last = values[-1]
    idx = len(values) - 1
    while idx >= 0 and values[idx] == last:
        idx -= 1
    return idx + 1


def _write_status_note(workdir: str, note: str) -> None:
    status_path = os.path.join(workdir, "status.txt")
    note_line = f"note: {note}"
    try:
        with open(status_path, "r", encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f]
    except FileNotFoundError:
        lines = []
    if note_line not in lines:
        lines.append(note_line)
        with open(status_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def _write_mser_status_flag(workdir: str, note: str) -> None:
    status_path = os.path.join(workdir, "mser_status.txt")
    with open(status_path, "w", encoding="utf-8") as f:
        f.write(note + "\n")


def _update_sim_json(workdir: str, add_cycles: int, restart_file: str) -> None:
    sim_path = os.path.join(workdir, "simulation.json")
    if not os.path.exists(sim_path):
        raise FileNotFoundError(f"未找到 simulation.json: {sim_path}")
    with open(sim_path, "r", encoding="utf-8") as f:
        sim = json.load(f)

    sim["NumberOfCycles"] = add_cycles
    sim["NumberOfInitializationCycles"] = 0
    sim["NumberOfEquilibrationCycles"] = 0
    # 仅使用 JSON 重启，不使用二进制
    sim.pop("RestartFromBinaryFile", None)
    sim.pop("WriteBinaryRestartEvery", None)
    restart_name = os.path.splitext(os.path.abspath(restart_file))[0]
    # RASPA3: 将 RestartFileName 放在 Systems 标签
    if sim.get("Systems"):
        sim["Systems"][0]["RestartFileName"] = restart_name
    # 顶层不要带 RestartFileName，避免未知字段
    sim.pop("RestartFileName", None)
    if sim.get("Components"):
        for comp in sim["Components"]:
            comp["CreateNumberOfMolecules"] = 0

    with open(sim_path, "w", encoding="utf-8") as f:
        json.dump(sim, f, indent=2)


def _run_raspa3(workdir: str, raspa_env: str, log_path: str) -> int:
    cmd = f"""
    source ~/.bashrc >/dev/null 2>&1 || true
    if [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/anaconda3/etc/profile.d/conda.sh"
    elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/miniconda3/etc/profile.d/conda.sh"
    fi
    conda activate {raspa_env}
    cd "{workdir}"
    raspa3 >> "{log_path}" 2>&1
    """
    return subprocess.call(cmd, shell=True, executable="/bin/bash")


def main():
    ap = argparse.ArgumentParser(description="Auto-extend RASPA3 until pyMSER equilibrates.")
    ap.add_argument("--workdir", required=True, help="任务目录（包含 simulation.json, output/）")
    def env_bool(name: str, default: bool) -> bool:
        v = os.environ.get(name)
        if v is None:
            return default
        return str(v).strip().lower() not in ("false", "0", "no", "n")

    def env_int(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, default))
        except Exception:
            return default

    def env_float(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, default))
        except Exception:
            return default

    ap.add_argument("--target-cycles", type=int, default=int(os.environ.get("RASPA_MSER_TARGET_CYCLES", 1000)))
    ap.add_argument("--add-cycles", type=int, default=int(os.environ.get("RASPA_MSER_ADD_CYCLES", 200)))
    ap.add_argument("--max-iter", type=int, default=int(os.environ.get("RASPA_MSER_MAX_ITER", 10)))
    ap.add_argument("--uncertainty", default=os.environ.get("RASPA_MSER_UNCERTAINTY", "uSD"), choices=["SD", "SE", "uSD", "uSE"])
    ap.add_argument("--llm", action="store_true", default=env_bool("RASPA_MSER_LLM", True), help="使用 MSER-LLM（默认开启）")
    ap.add_argument("--no-llm", dest="llm", action="store_false", help="关闭 MSER-LLM")
    ap.add_argument("--batch-size", type=int, default=env_int("RASPA_MSER_BATCH_SIZE", 5), help="MSER 批大小，默认 5（更平滑）")
    ap.add_argument(
        "--tail-rel-std",
        type=float,
        default=env_float("RASPA_MSER_TAIL_REL_STD", 0.0),
        help="(已弃用/忽略) 尾部相对波动阈值",
    )
    ap.add_argument(
        "--tail-window",
        type=int,
        default=env_int("RASPA_MSER_TAIL_WINDOW", 2000),
        help="(已弃用/忽略) 尾部波动检查窗口大小",
    )
    ap.add_argument(
        "--min-t0-frac",
        type=float,
        default=env_float("RASPA_MSER_MIN_T0_FRAC", 0.0),
        help="(已弃用/忽略) 最小 t0 占比",
    )
    ap.add_argument(
        "--conda-env",
        default=os.environ.get("RASPA_MSER_CONDA_ENV", "pymser"),
        help="包含 raspa3+pymser 的 conda 环境名",
    )
    ap.add_argument(
        "--raspa3-conda-env",
        default=os.environ.get("RASPA3_CONDA_ENV", "raspa3"),
        help="运行 raspa3 的 conda 环境名",
    )
    args = ap.parse_args()

    workdir = os.path.abspath(args.workdir)
    log_path = os.path.join(workdir, "auto_mser_raspa.log")
    mser_log = os.path.join(workdir, "auto_mser.log")
    combined_csv = os.path.join(workdir, "mser_timeseries.csv")

    if (args.tail_rel_std and args.tail_rel_std > 0) or (args.min_t0_frac and args.min_t0_frac > 0) or os.environ.get("RASPA_MSER_TAIL_WINDOW"):
        msg = "[auto-mser3] 已忽略 tail_rel_std/tail_window/min_t0_frac（已弃用），仅使用 pyMSER 默认平衡截断点 t0。"
        print(msg)
        with open(mser_log, "a", encoding="utf-8") as lf:
            lf.write(msg + "\n")

    for it in range(1, args.max_iter + 1):
        msg = f"[auto-mser3] 迭代 {it}/{args.max_iter}，解析输出并判定平衡..."
        print(msg)
        with open(mser_log, "a", encoding="utf-8") as lf:
            lf.write(msg + "\n")

        try:
            df_new = _parse_output_to_timeseries(workdir)
        except Exception as exc:  # noqa: BLE001
            print(f"[auto-mser3] 解析输出失败: {exc}")
            sys.exit(1)

        if os.path.exists(combined_csv):
            df_old = pd.read_csv(combined_csv)
            try:
                offset = int(df_old["cycle"].max())
            except Exception:
                offset = 0
            df_new["cycle"] = df_new["cycle"].astype(int) + offset
            df = pd.concat([df_old, df_new], ignore_index=True)
        else:
            df = df_new
        # 去重并排序，保证 cycle 连续增长
        df = df.drop_duplicates(subset=["cycle"], keep="first").sort_values("cycle").reset_index(drop=True)
        df.to_csv(combined_csv, index=False)

        molkg_cols = [c for c in df.columns if c.endswith("_[mol/kg]")]
        if not molkg_cols:
            series_np = df["N_ads"].to_numpy() if "N_ads" in df else df.iloc[:, 0].to_numpy()
            basis = "N_ads"
        else:
            series_np = df[molkg_cols].sum(axis=1).to_numpy()
            basis = "sum_molkg"

        # 统一使用 pandas Series 便于后续 iloc/tail 处理，同时传 numpy 给 pymser
        series = pd.Series(series_np)

        mser_note = None
        try:
            eq = pymser.equilibrate(
                series.to_numpy(),
                LLM=bool(args.llm),
                batch_size=max(1, int(args.batch_size)),
                print_results=False,
                uncertainty=args.uncertainty,
            )
            t0 = int(eq.get("t0", 0))
            ac_time = float(eq.get("ac_time", 1))
        except ValueError as exc:
            if "constant" not in str(exc).lower():
                raise
            t0 = _find_constant_tail_t0(series)
            ac_time = 1.0
            mser_note = "mser_constant_series_fallback"
            msg = f"[auto-mser3] pyMSER ADF 检测到常数序列，改用尾部常数区间作为平衡区: t0={t0}"
            print(msg)
            with open(mser_log, "a", encoding="utf-8") as lf:
                lf.write(msg + "\n")
            try:
                _write_mser_status_flag(workdir, mser_note)
                _write_status_note(workdir, mser_note)
            except Exception as note_exc:  # noqa: BLE001
                warn = f"[auto-mser3] 写入状态说明失败: {note_exc}"
                print(warn)
                with open(mser_log, "a", encoding="utf-8") as lf:
                    lf.write(warn + "\n")
        n_samples = len(series)

        # 合法化 t0 范围
        t0 = min(max(t0, 0), max(0, n_samples - 1))

        prod = n_samples - t0
        # 如果产线样本不足，不再强制提前 t0；保留 pyMSER 给出的平衡点，追加循环来补足样本
        if prod < args.target_cycles:
            with open(mser_log, "a", encoding="utf-8") as lf:
                lf.write(
                    f"[auto-mser3] t0={t0} 产线样本 {prod}/{args.target_cycles} 不足，保留原 t0，继续续跑以补足样本\n"
                )
        msg = f"[auto-mser3] t0={t0} 基于 {basis}，平衡后样本={prod}/{args.target_cycles}"
        print(msg)
        with open(mser_log, "a", encoding="utf-8") as lf:
            lf.write(msg + "\n")

        if prod >= args.target_cycles:
            stats = {}
            for col in molkg_cols:
                avg, unc = pymser.calc_equilibrated_average(
                    data=df[col].to_numpy(),
                    eq_index=t0,
                    uncertainty=args.uncertainty,
                    ac_time=ac_time,
                )
                stats[col] = {"average": float(avg), "uncertainty": float(unc)}
            stats_path = os.path.join(workdir, "stats.json")
            with open(stats_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"t0": t0, "ac_time": ac_time, "basis": basis, "stats": stats},
                    f,
                    indent=2,
                )
            print(f"[auto-mser3] 达标，已保存统计: {stats_path}")
            return

        # 未达标：更新 simulation.json 并续跑
        try:
            restart_file = _find_latest_restart(workdir)
        except Exception as exc:  # noqa: BLE001
            print(f"[auto-mser3] 找不到 restart 文件: {exc}")
            sys.exit(1)

        try:
            _update_sim_json(workdir, args.add_cycles, restart_file)
        except Exception as exc:  # noqa: BLE001
            print(f"[auto-mser3] 更新 simulation.json 失败: {exc}")
            sys.exit(1)

        ret = _run_raspa3(workdir, args.raspa3_conda_env, log_path)
        if ret != 0:
            print(f"[auto-mser3] raspa3 运行失败，返回码 {ret}，详见 {log_path}")
            sys.exit(ret)

    msg = "[auto-mser3] 达到最大迭代次数仍未达标，标记失败（未满足 target_cycles）。"
    print(msg)
    with open(mser_log, "a", encoding="utf-8") as lf:
        lf.write(msg + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
