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
        # 兼容二进制重启文件
        bin_file = os.path.join(outdir, "restart_data.bin")
        if os.path.exists(bin_file):
            return bin_file
        raise FileNotFoundError("未找到 restart 文件，请确认已开启重启输出（如 WriteBinaryRestartEvery 或 writeRestartEvery）。")
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


def _update_sim_json(workdir: str, add_cycles: int, restart_file: str) -> None:
    sim_path = os.path.join(workdir, "simulation.json")
    if not os.path.exists(sim_path):
        raise FileNotFoundError(f"未找到 simulation.json: {sim_path}")
    with open(sim_path, "r", encoding="utf-8") as f:
        sim = json.load(f)

    sim["NumberOfCycles"] = add_cycles
    sim["NumberOfInitializationCycles"] = 0
    sim["NumberOfEquilibrationCycles"] = 0
    sim["RestartFromBinaryFile"] = True
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
    ap.add_argument("--target-cycles", type=int, default=1000)
    ap.add_argument("--add-cycles", type=int, default=200)
    ap.add_argument("--max-iter", type=int, default=10)
    ap.add_argument("--uncertainty", default="uSD", choices=["SD", "SE", "uSD", "uSE"])
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
            series = df["N_ads"].to_numpy() if "N_ads" in df else df.iloc[:, 0].to_numpy()
            basis = "N_ads"
        else:
            series = df[molkg_cols].sum(axis=1).to_numpy()
            basis = "sum_molkg"

        eq = pymser.equilibrate(series, print_results=False)
        t0 = int(eq.get("t0", 0))
        ac_time = float(eq.get("ac_time", 1))
        prod = len(series) - t0
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

    print("[auto-mser3] 达到最大迭代次数仍未达标，已停止。")
    sys.exit(0)


if __name__ == "__main__":
    main()
