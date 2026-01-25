#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Isotherm Plotter for RASPA outputs

Parses completed RASPA output files, aggregates multi-pressure points per
framework (MOF) and component, and generates isotherm plots (loading vs pressure).

Inputs:
- Base directory containing mc* folders or general output files.
- Adsorption type (absolute/excess) and unit.
- Target component name (optional). If not given, plot all components found.

Outputs:
- PNG plots per framework (and per component if multiple) in the output dir.
- CSV files with the aggregated (pressure, loading) pairs alongside the plots.

Requirements:
- matplotlib for plotting

This script reuses parsing utilities from data_extractor.py.
"""

from __future__ import annotations

import os
import re
import sys
import math
import argparse
from collections import defaultdict

try:
    import matplotlib
    matplotlib.use("Agg")  # headless
    import matplotlib.pyplot as plt
except ImportError:
    print("需要安装 matplotlib 才能绘制等温线图。请运行: pip install matplotlib")
    sys.exit(1)

try:
    # Reuse existing parsing utilities
    from raspa_calc.app.data_extractor import (
        RASPA_Output_Data,
        extract_framework_name_from_filepath,
        find_all_mc_directories,
        find_output_file_in_mc_dir,
    )
except Exception as e:
    print(f"无法导入数据解析模块: {e}")
    print("请确保已正确安装 raspa_calc 包")
    print("可尝试运行: python -m raspa_calc.entrypoints.data_extractor --help")
    sys.exit(1)

try:
    # Optional: RASPA3 parser (txt output)
    from raspa_calc.domain.parsers.data_extractor_raspa3 import (
        RASPA3_Output_Data,
        extract_framework_name_from_simulation_json as extract_framework_name_from_simulation_json_raspa3,
        find_output_file_in_mc_dir as find_output_file_in_mc_dir_raspa3,
    )
except Exception:
    RASPA3_Output_Data = None
    extract_framework_name_from_simulation_json_raspa3 = None
    find_output_file_in_mc_dir_raspa3 = None


def _infer_context_dir(output_file: str) -> str | None:
    """
    Infer the simulation directory (where simulation.json/input usually lives)
    from an output file path.

    - RASPA3: <sim_dir>/output/output_*.txt  -> context = <sim_dir>
    - RASPA2: <mc_dir>/Output/System_0/output_*.data -> context = <mc_dir>
    - Fallback: parent directory of output_file
    """
    try:
        parent = os.path.dirname(output_file)
        base = os.path.basename(parent).lower()
        if base in {'output', 'outputs', 'output_files'}:
            return os.path.dirname(parent)
        if base == 'system_0':
            up1 = os.path.dirname(parent)  # Output/
            if os.path.basename(up1).lower() == 'output':
                return os.path.dirname(up1)
            return os.path.dirname(parent)
        return parent
    except Exception:
        return None


def _iter_output_files(base_dir: str):
    """
    Yield (context_dir, output_file) pairs.

    - If mc* layout exists, prefer mc* ordering and pick the most likely output per mc dir.
    - Otherwise, recursively find output files:
      - RASPA2: output*.data
      - RASPA3: output_*.txt (under output/)
    """
    mc_dirs = find_all_mc_directories(base_dir)
    yielded = False
    if mc_dirs:
        for mc_dir in sorted(mc_dirs, key=lambda p: _extract_mc_number_safe(p)):
            output = find_output_file_in_mc_dir(mc_dir)
            if (not output) and find_output_file_in_mc_dir_raspa3:
                output = find_output_file_in_mc_dir_raspa3(mc_dir)
            if output and os.path.exists(output):
                yielded = True
                yield (mc_dir, output)
        if yielded:
            return

    # General recursive search for RASPA output files
    for root, _, files in os.walk(base_dir):
        for fn in files:
            lower = fn.lower()
            full = os.path.join(root, fn)
            if fn.endswith('.data') and 'output' in lower:
                yield (_infer_context_dir(full), full)
            elif fn.endswith('.txt') and lower.startswith('output_'):
                yield (_infer_context_dir(full), full)
            elif lower == 'output' and os.path.isfile(full):
                yield (_infer_context_dir(full), full)


def _extract_mc_number_safe(mc_dir: str) -> int:
    try:
        m = re.search(r'mc(\d+)', os.path.basename(mc_dir))
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
        if math.isfinite(v):
            return v
        return None
    except Exception:
        return None


def _convert_pressure(value_pa: float, unit: str) -> float:
    if unit.lower() == 'pa':
        return value_pa
    if unit.lower() == 'bar':
        return value_pa / 1e5
    raise ValueError(f"Unsupported pressure unit: {unit}")


def _safe_framework_name(context_dir: str | None, file_path: str, content: str) -> str:
    if context_dir and extract_framework_name_from_simulation_json_raspa3:
        try:
            name = extract_framework_name_from_simulation_json_raspa3(context_dir) or ''
            if name:
                return name
        except Exception:
            pass

    name = extract_framework_name_from_filepath(file_path) or ''
    if name:
        # RASPA3 txt outputs often look like output_<T>_<P>.s0.txt; avoid treating temperature as framework name.
        if not (name.isdigit() and os.path.basename(file_path).lower().startswith('output_')):
            return name
    # Fallback: attempt very rough parse from path parts
    base = os.path.basename(file_path)
    m = re.search(r'output_([^._]+)', base)
    return m.group(1) if m else 'UnknownFramework'


def _get_adsorption(raspa, ads_type: str, unit: str):
    if ads_type == 'absolute':
        return raspa.get_absolute_adsorption(unit)
    elif ads_type == 'excess':
        return raspa.get_excess_adsorption(unit)
    else:
        raise ValueError("ads_type must be 'absolute' or 'excess'")


_STP_CM3_PER_MOL = 22414.0


def _has_numeric_adsorption(ads_map: dict) -> bool:
    if not ads_map:
        return False
    for v in ads_map.values():
        if _to_float(v) is not None:
            return True
    return False


def _convert_from_molkg(molkg_map: dict, target_unit: str, framework_density: float | None):
    if target_unit == 'cm^3/g':
        factor = _STP_CM3_PER_MOL / 1000.0
    elif target_unit == 'cm^3/cm^3':
        if framework_density is None:
            return {}
        factor = (_STP_CM3_PER_MOL / 1e6) * framework_density
    else:
        return {}

    converted = {}
    for comp, val in molkg_map.items():
        v = _to_float(val)
        converted[comp] = (v * factor) if v is not None else None
    return converted


def collect_isotherm_points(base_dir: str,
                            component: str | None,
                            ads_type: str,
                            unit: str,
                            pressure_unit: str,
                            include_unfinished: bool = False):
    """
    Collect points grouped as data[framework][component] = list of (P, loading).
    P is in requested pressure_unit; loading in requested adsorption unit.
    """
    data = defaultdict(lambda: defaultdict(list))

    for context_dir, output_file in _iter_output_files(base_dir):
        try:
            with open(output_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            use_raspa3 = False
            if RASPA3_Output_Data and (output_file.lower().endswith('.txt')):
                # Heuristic detection: RASPA3 text output usually contains these markers.
                if ('RASPA 3' in content) or ('Abs. loading average' in content) or ('Loadings' in content):
                    use_raspa3 = True

            raspa = RASPA3_Output_Data(content) if use_raspa3 else RASPA_Output_Data(content)

            if not include_unfinished and not raspa.is_finished():
                continue

            p_pa_str = raspa.get_pressure()
            p_pa = _to_float(p_pa_str)
            if p_pa is None:
                continue
            p = _convert_pressure(p_pa, pressure_unit)

            ads_map = _get_adsorption(raspa, ads_type, unit)
            if not _has_numeric_adsorption(ads_map) and unit in {'cm^3/g', 'cm^3/cm^3'}:
                molkg_map = _get_adsorption(raspa, ads_type, 'mol/kg')
                if _has_numeric_adsorption(molkg_map):
                    density = None
                    if unit == 'cm^3/cm^3' and hasattr(raspa, 'get_Framework_density'):
                        try:
                            density = _to_float(raspa.get_Framework_density())
                        except Exception:
                            density = None
                    ads_map = _convert_from_molkg(molkg_map, unit, density)
            if not ads_map:
                continue

            fw = _safe_framework_name(context_dir, output_file, content)

            # If a specific component is requested, filter to it; else add all
            if component:
                # Use exact match first, else case-insensitive fallback
                comp_key = None
                if component in ads_map:
                    comp_key = component
                else:
                    for k in ads_map.keys():
                        if k.lower() == component.lower():
                            comp_key = k
                            break
                if comp_key is None:
                    continue  # this file doesn't have that component
                val = _to_float(ads_map.get(comp_key))
                if val is None:
                    continue
                data[fw][comp_key].append((p, val))
            else:
                for k, v_str in ads_map.items():
                    v = _to_float(v_str)
                    if v is None:
                        continue
                    data[fw][k].append((p, v))
        except Exception:
            # Skip problematic files silently to keep flow robust
            continue

    # Deduplicate by pressure and sort
    for fw in list(data.keys()):
        for comp in list(data[fw].keys()):
            pts = data[fw][comp]
            if not pts:
                continue
            # group by exact pressure value; compute mean loading if duplicates
            by_p = defaultdict(list)
            for p, y in pts:
                by_p[p].append(y)
            dedup = sorted((p, sum(ys)/len(ys)) for p, ys in by_p.items())
            data[fw][comp] = dedup

    return data


def _sanitize_filename(s: str) -> str:
    return re.sub(r'[^A-Za-z0-9_.\\-]+', '_', s)


def plot_isotherms(data,
                    outdir: str,
                    component: str | None,
                    ads_type: str,
                    unit: str,
                    pressure_unit: str,
                    logx: bool,
                    combine_all: bool):
    os.makedirs(outdir, exist_ok=True)

    # If combine_all, produce one figure per component across frameworks
    if combine_all:
        comps = set()
        for fw in data:
            for comp in data[fw]:
                comps.add(comp)
        for comp in sorted(comps):
            plt.figure(figsize=(7, 5))
            any_curve = False
            for fw in sorted(data.keys()):
                pts = data[fw].get(comp, [])
                if len(pts) < 1:
                    continue
                xs = [p for p, _ in pts]
                ys = [y for _, y in pts]
                plt.plot(xs, ys, marker='o', linestyle='-', label=fw)
                any_curve = True
            if not any_curve:
                plt.close()
                continue
            plt.xlabel(f'Pressure [{pressure_unit}]')
            plt.ylabel(f'Loading ({ads_type}) [{unit}]')
            title = f'Isotherm – {comp} ({ads_type}, {unit})'
            plt.title(title)
            if logx:
                plt.xscale('log')
            plt.legend(fontsize=8)
            plt.tight_layout()
            fn = os.path.join(outdir, _sanitize_filename(f'isotherm_ALL_{comp}_{ads_type}_{unit}_{pressure_unit}.png'))
            plt.savefig(fn, dpi=200)
            plt.close()

    # One plot per framework (and per component)
    for fw in sorted(data.keys()):
        fw_data = data[fw]
        if not fw_data:
            continue

        for comp, pts in sorted(fw_data.items()):
            if len(pts) < 1:
                continue
            xs = [p for p, _ in pts]
            ys = [y for _, y in pts]
            plt.figure(figsize=(7, 5))
            plt.plot(xs, ys, marker='o', linestyle='-')
            plt.xlabel(f'Pressure [{pressure_unit}]')
            plt.ylabel(f'Loading ({ads_type}) [{unit}]')
            title = f'{fw} – {comp} ({ads_type}, {unit})'
            plt.title(title)
            if logx:
                plt.xscale('log')
            plt.tight_layout()
            png_name = _sanitize_filename(f'isotherm_{fw}_{comp}_{ads_type}_{unit}_{pressure_unit}.png')
            png_path = os.path.join(outdir, png_name)
            plt.savefig(png_path, dpi=200)
            plt.close()

            # Also dump CSV with points
            csv_name = _sanitize_filename(f'isotherm_{fw}_{comp}_{ads_type}_{unit}_{pressure_unit}.csv')
            csv_path = os.path.join(outdir, csv_name)
            with open(csv_path, 'w', encoding='utf-8') as f:
                f.write(f'Pressure[{pressure_unit}],Loading[{unit}]\n')
                for p, y in pts:
                    f.write(f'{p},{y}\n')


def parse_args(argv=None):
    p = argparse.ArgumentParser(description='Plot isotherms from RASPA outputs')
    p.add_argument('--base-dir', default=os.getcwd(), help='Base directory to scan (default: CWD)')
    p.add_argument('--component', default=None, help='Component name to plot. If omitted, plot all components found.')
    p.add_argument('--type', dest='ads_type', choices=['absolute', 'excess'], default='absolute',
                   help='Adsorption type (default:absolute)')
    p.add_argument('--unit', choices=['mol/kg', 'cm^3/g', 'mg/g', 'cm^3/cm^3'], default='mol/kg',
                   help='Loading unit (default:mol/kg)')
    p.add_argument('--pressure-unit', choices=['Pa', 'bar'], default='Pa', help='Pressure unit for x-axis (default: Pa)')
    p.add_argument('--logx', action='store_true', default=False, help='Use log scale for pressure')
    p.add_argument('--linearx', action='store_true', help='Force linear x-axis (overrides --logx, default behavior)')
    p.add_argument('--outdir', default='isotherms', help='Output directory (default: isotherms)')
    p.add_argument('--combine-all', action='store_true', help='Also produce combined plots across frameworks per component')
    p.add_argument('--include-unfinished', action='store_true', help='Include unfinished simulations (default: skip)')
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    # Resolve logx setting (default is now False/linear)
    logx = args.logx and not args.linearx

    print('=== RASPA 等温线绘制工具 ===')
    print(f'- 扫描目录: {args.base_dir}')
    print(f'- 组件: {args.component or "(全部)"}')
    print(f'- 吸附类型: {args.ads_type}')
    print(f'- 单位: {args.unit}')
    print(f'- 压力单位: {args.pressure_unit}')
    print(f'- x轴对数刻度: {"是" if logx else "否"}')
    print(f'- 输出目录: {args.outdir}')
    if args.include_unfinished:
        print('- 包含未完成的模拟: 是')

    data = collect_isotherm_points(
        base_dir=args.base_dir,
        component=args.component,
        ads_type=args.ads_type,
        unit=args.unit,
        pressure_unit=args.pressure_unit,
        include_unfinished=args.include_unfinished,
    )

    # Filter out frameworks with no points at all
    valid_fw = [fw for fw in data if any(len(pts) for pts in data[fw].values())]
    if not valid_fw:
        print('未找到可用于绘制等温线的数据点。请确认输出文件和筛选条件。')
        return 1

    plot_isotherms(
        data=data,
        outdir=args.outdir,
        component=args.component,
        ads_type=args.ads_type,
        unit=args.unit,
        pressure_unit=args.pressure_unit,
        logx=logx,
        combine_all=args.combine_all,
    )

    # 统计和显示结果
    print('\n' + '='*60)
    print('✓ 等温线绘制完成！')
    print('='*60)

    # 统计信息
    total_frameworks = len(valid_fw)
    total_plots = 0
    total_points = 0
    components_found = set()

    for fw in valid_fw:
        for comp, pts in data[fw].items():
            if len(pts) > 0:
                total_plots += 1
                total_points += len(pts)
                components_found.add(comp)

    print(f'\n📊 绘制统计:')
    print(f'   - MOF框架数量: {total_frameworks}')
    print(f'   - 组件类型: {", ".join(sorted(components_found))}')
    print(f'   - 生成图表数量: {total_plots}')
    print(f'   - 总数据点数: {total_points}')

    # 列出输出文件（显示前10个）
    try:
        output_files = sorted([f for f in os.listdir(args.outdir) if f.endswith('.png')])
        if output_files:
            print(f'\n📁 输出文件 (共 {len(output_files)} 个):')
            for i, fname in enumerate(output_files[:10], 1):
                print(f'   {i}. {fname}')
            if len(output_files) > 10:
                print(f'   ... 还有 {len(output_files) - 10} 个文件')
    except Exception:
        pass

    print(f'\n✓ 所有文件已保存到: {os.path.abspath(args.outdir)}')
    print('='*60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
