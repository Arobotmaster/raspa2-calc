#!/usr/bin/env python3
"""
Auto-extend a RASPA2 GCMC run until pyMSER reports enough equilibrated samples.

Usage:
    python auto_mser_raspa2.py --workdir <task_dir> --target-cycles 1000 --add-cycles 500

Assumptions:
    - workdir contains a valid RASPA2 run (simulation.input, Output/, Restart/ as produced by simulate).
    - CSV time series already exist (raspa_*.csv or raspa_csv.tgz with those files). If not found, the
      script aborts and asks you to enable CSV generation first.
    - A conda environment with pymser + raspa2 is available; set via --conda-env (default: pymser).
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from typing import Optional, Tuple

import pandas as pd
import pymser


def _find_csv(workdir: str, temp: float, pressure: float) -> Optional[str]:
    """Locate raspa_<T>_<P>.csv without unpacking."""
    pattern = os.path.join(workdir, "Output", "System_0", f"raspa_{temp:.6f}_{pressure}.csv")
    if os.path.exists(pattern):
        return pattern
    candidates = glob.glob(os.path.join(workdir, "Output", "System_0", "raspa_*.csv"))
    return candidates[0] if candidates else None


def _parse_output_data_to_df(workdir: str, temp: float, pressure: float) -> pd.DataFrame:
    """Parse RASPA2 output_*.data into a minimal DataFrame (cycle, step, N_ads, per-component counts)."""
    pattern = os.path.join(workdir, "Output", "System_0", f"output_*_{temp:.6f}_{pressure:g}.data")
    matches = glob.glob(pattern)
    if not matches:
        raise FileNotFoundError(f"未找到输出数据文件匹配 {pattern}")
    data_path = matches[0]

    records = []
    current_cycle = None
    total_cycles = None
    components = {}
    step_counter = 0
    conv_mol_kg = None

    with open(data_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue

            if conv_mol_kg is None and "Conversion factor molecules/unit cell -> mol/kg" in line:
                try:
                    conv_mol_kg = float(line.split(":")[1].split()[0])
                except Exception:
                    conv_mol_kg = None

            if line.startswith("Current cycle:"):
                # 遇到新循环时，如果已有上一循环数据则先保存
                if current_cycle is not None and "N_ads" in components:
                    step_counter += 1
                    record = {"cycle": current_cycle, "step": step_counter, "N_ads": components["N_ads"]}
                    for k, v in components.items():
                        if k != "N_ads":
                            record[k] = v
                    records.append(record)
                components = {}
                try:
                    parts = line.split()
                    current_cycle = int(parts[2])
                    total_cycles = int(parts[5])
                except Exception:
                    current_cycle = None
                continue

            if current_cycle is None:
                continue

            if line.startswith("Number of Adsorbates:"):
                try:
                    val = int(line.split()[3])
                    components["N_ads"] = val
                except Exception:
                    pass
                continue

            if line.startswith("Component "):
                # e.g., "Component 0 (CO2), current number of integer/fractional/reaction molecules: 0/0/0 ..."
                try:
                    # Extract name between parentheses
                    if "(" in line and ")" in line:
                        name = line.split("(", 1)[1].split(")", 1)[0]
                    else:
                        name = f"Comp{len(components)}"
                    after_colon = line.split(":", 1)[1]
                    count_str = after_colon.strip().split("/")[0]
                    count_val = int(count_str)
                    components[f"{name}_[molecules/uc]"] = count_val
                except Exception:
                    pass
                continue

    # Append last cycle
    if current_cycle is not None and "N_ads" in components:
        step_counter += 1
        record = {"cycle": current_cycle, "step": step_counter, "N_ads": components["N_ads"]}
        for k, v in components.items():
            if k != "N_ads":
                record[k] = v
        records.append(record)

    if not records:
        raise RuntimeError("解析 .data 时未提取到任何循环数据，请检查输出格式。")

    df = pd.DataFrame.from_records(records)

    # 如果有转换因子，添加 mol/kg 列
    if conv_mol_kg is not None:
        for col in list(df.columns):
            if col.endswith("_[molecules/uc]"):
                base = col.replace("_[molecules/uc]", "")
                df[f"{base}_[mol/kg]"] = df[col] * conv_mol_kg

    return df


def _parse_simulation_input(path: str) -> Tuple[float, float, list[str]]:
    """Extract ExternalTemperature, ExternalPressure, molecule list from simulation.input."""
    temp = None
    pressure = None
    molecules = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("externaltemperature"):
                parts = line.split()
                if len(parts) >= 2:
                    temp = float(parts[1])
            elif line.lower().startswith("externalpressure"):
                parts = line.split()
                if len(parts) >= 2:
                    pressure = float(parts[1])
            elif line.lower().startswith("component") and "MoleculeName" in line:
                parts = line.split()
                if len(parts) >= 3:
                    molecules.append(parts[-1])
    if temp is None or pressure is None:
        raise ValueError("simulation.input 缺少 ExternalTemperature 或 ExternalPressure")
    if not molecules:
        molecules = ["CO2"]
    return temp, pressure, molecules


def _update_simulation_input(path: str, add_cycles: int, restart: bool) -> None:
    """Increase NumberOfCycles by add_cycles, set restart flags, zero init/equil cycles."""
    lines = []
    number_cycles = None
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.lower().startswith("numberofcycles"):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        number_cycles = int(parts[1])
                        number_cycles += add_cycles
                        line = f"NumberOfCycles {number_cycles}\n"
                    except ValueError:
                        pass
            elif line.lower().startswith("numberofinitializationcycles"):
                line = "NumberOfInitializationCycles 0\n"
            elif line.lower().startswith("numberofequilibrationcycles"):
                line = "NumberOfEquilibrationCycles 0\n"
            elif line.lower().startswith("writebinaryrestartevery"):
                # keep user value; if absent we won't add here
                pass
            elif line.lower().startswith("restartfile"):
                line = f"RestartFile {'yes' if restart else 'no'}\n"
            lines.append(line)

    # Ensure restart flag exists
    if restart and not any(l.lower().startswith("restartfile") for l in lines):
        lines.append("RestartFile yes\n")
    if not restart and not any(l.lower().startswith("restartfile") for l in lines):
        lines.append("RestartFile no\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"[auto-mser] 更新 NumberOfCycles -> {number_cycles}, 追加 {add_cycles} 步；RestartFile {'yes' if restart else 'no'}")


def _run_simulate(workdir: str, conda_env: str, simulate_cmd: str, log_path: str) -> int:
    """Run simulate in a conda env with raspa2+pymser installed."""
    cmd = f"""
    source ~/.bashrc >/dev/null 2>&1 || true
    if [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/anaconda3/etc/profile.d/conda.sh"
    elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/miniconda3/etc/profile.d/conda.sh"
    fi
    conda activate {conda_env}
    export PATH="{os.path.dirname(simulate_cmd)}:$PATH"
    cd "{workdir}"
    "{simulate_cmd}" simulation.input >> "{log_path}" 2>&1
    """
    return subprocess.call(cmd, shell=True, executable="/bin/bash")


def main():
    parser = argparse.ArgumentParser(description="Auto-extend RASPA2 until pyMSER equilibrates.")
    parser.add_argument("--workdir", required=True, help="任务目录（包含 simulation.input 和 Output/）")
    parser.add_argument("--target-cycles", type=int, default=1000, help="期望的平衡后生产步数")
    parser.add_argument("--add-cycles", type=int, default=500, help="每次追加的生产步数")
    parser.add_argument("--max-iter", type=int, default=20, help="最多追加次数")
    parser.add_argument("--uncertainty", default="uSD", choices=["SD", "SE", "uSD", "uSE"])
    parser.add_argument("--conda-env", default="pymser", help="包含 pymser+raspa2 的 conda 环境名")
    args = parser.parse_args()

    workdir = os.path.abspath(args.workdir)
    sim_path = os.path.join(workdir, "simulation.input")
    if not os.path.exists(sim_path):
        print(f"[auto-mser] 未找到 simulation.input: {sim_path}")
        sys.exit(1)

    log_path = os.path.join(workdir, "auto_mser.log")
    temp, pressure, molecules = _parse_simulation_input(sim_path)
    gas_comp = {m: 1.0 / len(molecules) for m in molecules}
    combined_csv = os.path.join(workdir, "mser_timeseries.csv")
    simulate_cmd = os.path.join(os.environ.get("RASPA_DIR", ""), "bin", "simulate")
    if not os.path.exists(simulate_cmd):
        simulate_cmd = "simulate"
    print(f"[auto-mser] 使用 simulate 命令: {simulate_cmd}")

    for iteration in range(1, args.max_iter + 1):
        msg = f"[auto-mser] 迭代 {iteration}/{args.max_iter}，检查平衡..."
        print(msg)
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(msg + "\n")

        # 若缺少 CSV，则从 .data 解析时间序列；否则直接读取已有 CSV
        csv_path = _find_csv(workdir, temp, pressure)
        if not csv_path:
            try:
                df_new = _parse_output_data_to_df(workdir, temp, pressure)
            except Exception as exc:  # noqa: BLE001
                print(f"[auto-mser] 解析 RASPA 输出生成时间序列失败: {exc}")
                sys.exit(1)

            if os.path.exists(combined_csv):
                df_old = pd.read_csv(combined_csv)
                offset = len(df_old)
                df_new["cycle"] = df_new["cycle"] + offset
                df_new["step"] = range(offset + 1, offset + len(df_new) + 1)
                df = pd.concat([df_old, df_new], ignore_index=True)
            else:
                df_new["step"] = range(1, len(df_new) + 1)
                df = df_new

            df.to_csv(combined_csv, index=False)
        else:
            df = pd.read_csv(csv_path)
            # 如有累计文件，也合并以保证迭代间连续
            if os.path.exists(combined_csv) and combined_csv != csv_path:
                df_old = pd.read_csv(combined_csv)
                df = pd.concat([df_old, df], ignore_index=True)

        # 使用总吸附量（所有 mol/kg 列求和；若无则退回 N_ads）作为判据
        target_cols = [c for c in df.columns if c.endswith("_[mol/kg]")]
        if target_cols:
            combined_series = df[target_cols].sum(axis=1).to_numpy()
            combined_label = "sum_molkg"
        else:
            combined_series = df["N_ads"].to_numpy()
            combined_label = "N_ads"

        eq = pymser.equilibrate(combined_series, print_results=False)
        t0 = int(eq["t0"]) if "t0" in eq else 0
        ac_time = float(eq.get("ac_time", 1))
        prod_samples = len(combined_series) - t0
        msg = f"[auto-mser] t0={t0} 基于总吸附量 ({combined_label}), 平衡后样本数={prod_samples}/{args.target_cycles}"
        print(msg)
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(msg + "\n")

        if prod_samples >= args.target_cycles:
            print("[auto-mser] 达到目标生产步数，输出统计...")
            stats = {}
            for gas in gas_comp:
                col = f"{gas}_[mol/kg]"
                if col in df.columns:
                    avg, unc = pymser.calc_equilibrated_average(
                        data=df[col].to_numpy(),
                        eq_index=t0,
                        uncertainty=args.uncertainty,
                        ac_time=ac_time,
                    )
                    stats[col] = {"average": float(avg), "uncertainty": float(unc)}
            stats_path = os.path.join(workdir, f"stats_{temp:.6f}_{pressure:.0f}.json")
            with open(stats_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "t0": int(t0),
                        "ac_time": ac_time,
                        "basis": combined_label,
                        "stats": stats,
                    },
                    f,
                    indent=2,
                )
            print(f"[auto-mser] 已保存统计: {stats_path}")
            return

        msg = f"[auto-mser] 未达标，将追加 {args.add_cycles} 周期并重启模拟..."
        print(msg)
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(msg + "\n")
        _update_simulation_input(sim_path, args.add_cycles, restart=True)

        # 准备重启文件夹
        restart_src = os.path.join(workdir, "Restart", "System_0")
        restart_dst = os.path.join(workdir, "RestartInitial", "System_0")
        if os.path.exists(restart_src):
            os.makedirs(restart_dst, exist_ok=True)
            for fname in os.listdir(restart_src):
                shutil.copy2(os.path.join(restart_src, fname), os.path.join(restart_dst, fname))

        ret = _run_simulate(workdir, args.conda_env, simulate_cmd, log_path)
        if ret != 0:
            print(f"[auto-mser] simulate 失败，返回码 {ret}，详见 {os.path.join(workdir, 'auto_mser_raspa.log')}")
            sys.exit(ret)

    msg = "[auto-mser] 达到最大迭代次数，仍未满足生产步数要求。"
    print(msg)
    with open(log_path, "a", encoding="utf-8") as lf:
        lf.write(msg + "\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
