import os
import math
import json
import re
import pandas as pd
import logging
import sys
import traceback
import subprocess
import multiprocessing
import shutil
import copy
from contextlib import contextmanager, nullcontext
from collections import OrderedDict
from calculate_params import process_structure_file, load_cache, save_cache
from force_field_utils import write_filtered_force_field


# ============ RASPA 版本检测 ============

def get_raspa_version_from_env():
    """从环境变量获取 RASPA 版本"""
    return os.environ.get('RASPA_VERSION', 'raspa2').lower()


def load_raspa3_config():
    """加载 RASPA3 专用配置"""
    return {
        'conda_env': os.environ.get('RASPA3_CONDA_ENV', 'raspa3'),
        'json_dir': os.environ.get('RASPA3_JSON_DIR', ''),
        'cif_base_path': os.environ.get('RASPA3_CIF_BASE_PATH', ''),
        'template_path': os.environ.get('RASPA3_TEMPLATE_PATH', ''),
    }

# 配置日志系统
CONSOLE_HANDLER = None

def setup_logging(log_file="raspa_calculation.log"):
    """设置日志系统"""
    # 获取根日志记录器
    root_logger = logging.getLogger()

    # 如果已经有处理器，先清除它们以避免重复
    if root_logger.handlers:
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

    # 设置日志级别
    root_logger.setLevel(logging.INFO)

    # 创建格式化器
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # 文件处理器
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

    global CONSOLE_HANDLER
    CONSOLE_HANDLER = console_handler

    return root_logger

# 初始化日志系统
logger = setup_logging()
CURRENT_SUBDIR = None
CURRENT_TOPDIR = None

@contextmanager
def quiet_console(level=logging.WARNING):
    """临时降低控制台日志级别，避免批量处理刷屏。"""
    if CONSOLE_HANDLER is None:
        yield
        return
    previous_level = CONSOLE_HANDLER.level
    CONSOLE_HANDLER.setLevel(level)
    try:
        yield
    finally:
        CONSOLE_HANDLER.setLevel(previous_level)

def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")

def _positive_int(raw, default):
    try:
        value = int(raw)
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default

def _parse_submit_index(line):
    match = re.search(r"正在提交(?:作业\s*|第)(\d+)", line)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None

def _should_print_submit_line(line):
    important_markers = (
        "错误",
        "失败",
        "⚠️",
        "❌",
        "警告",
        "WARNING",
        "Error",
        "ERROR",
        "开始提交计算任务",
        "使用CPU核心数",
        "提交模式",
        "开始逐个提交作业",
        "job array",
        "Job array",
        "节点分配计划",
        "所有作业已提交完成",
        "提示",
        "检测到",
    )
    return any(marker in line for marker in important_markers)


def locate_cif_file(framework_name, cif_dir):
    """Locate CIF file for a given framework name within a directory."""
    clean_name = framework_name
    if isinstance(clean_name, str) and clean_name.lower().endswith('.cif'):
        clean_name = clean_name[:-4]

    candidates = [
        os.path.join(cif_dir, f"{clean_name}.cif"),
        os.path.join(cif_dir, f"{clean_name}"),
        os.path.join(cif_dir, f"{str(clean_name).upper()}.cif"),
        os.path.join(cif_dir, f"{str(clean_name).lower()}.cif"),
    ]

    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def count_numbered_labels(cif_path):
    """Count labels that contain numeric suffixes in a CIF file."""
    try:
        with open(cif_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as exc:
        logger.warning(f"读取 CIF 失败，跳过标签检查: {cif_path} ({exc})")
        return 0

    count = 0
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('loop_'):
            headers = []
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith('_'):
                headers.append(lines[j].strip())
                j += 1

            if '_atom_site_label' in headers:
                label_idx = headers.index('_atom_site_label')
                k = j
                while k < len(lines):
                    row = lines[k].strip()
                    if not row or row.startswith('_') or row.startswith('loop_') or row.startswith('data_'):
                        break

                    parts = row.split()
                    if len(parts) > label_idx:
                        label = parts[label_idx].strip().strip("'\"")
                        if any(ch.isdigit() for ch in label):
                            count += 1
                    k += 1
                i = k
                continue
        i += 1

    return count


def parse_node_priorities(raw=None):
    """Parse node priorities from env string 'node:priority,...'."""
    text = raw if raw is not None else os.environ.get('RASPA_NODE_PRIORITIES', '')
    priorities = {}
    if not text:
        # 尝试从配置文件读取（兼容未显式导出环境变量）
        search_paths = [
            os.path.join(os.getcwd(), "config.yaml"),
            os.path.join(os.getcwd(), ".raspa_tools", "config.yaml"),
            os.path.expanduser("~/raspa2-calc/.raspa_tools/config.yaml"),
        ]
        def parse_simple(path: str):
            pr = {}
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    lines = fh.readlines()
            except Exception:
                return pr
            inside = False
            indent = None
            for line in lines:
                if "node_priorities:" in line and not line.lstrip().startswith("#"):
                    inside = True
                    indent = len(line) - len(line.lstrip())
                    continue
                if not inside:
                    continue
                cur_indent = len(line) - len(line.lstrip())
                if indent is not None and cur_indent <= indent:
                    break
                if ":" not in line:
                    continue
                try:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if key and val:
                        pr[key] = int(val)
                except Exception:
                    continue
            return pr

        def parse_yaml(path: str):
            try:
                import yaml  # type: ignore
            except Exception:
                return {}
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                env = data.get("environment") or {}
                calc = data.get("calculation") or {}
                np = env.get("node_priorities") or calc.get("node_priorities") or {}
                if isinstance(np, dict):
                    return {str(k): int(v) for k, v in np.items() if str(k)}
            except Exception:
                return {}
            return {}

        for p in search_paths:
            if not os.path.exists(p):
                continue
            priorities = parse_yaml(p) or parse_simple(p) or {}
            if priorities:
                break
        if not priorities:
            return priorities

    parts = [p for p in text.split(',') if p.strip()]
    for part in parts:
        if ':' not in part:
            continue
        name, value = part.split(':', 1)
        name = name.strip()
        try:
            prio = int(value.strip())
        except Exception:
            continue
        if name:
            priorities[name] = prio
    return priorities


def _get_slurm_summary():
    """备用：获取SLURM聚合CPU统计信息"""
    try:
        result = subprocess.run(['sinfo', '-h', '-o', '%C'],
                                capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split('/')
            if len(parts) == 4:
                allocated = int(parts[0])
                idle = int(parts[1])
                other = int(parts[2])
                total = int(parts[3])
                return {
                    'total_cpus': total,
                    'allocated_cpus': allocated,
                    'other_cpus': other,
                    'available_cpus': idle,
                    'nodes': [],
                    'method': 'sinfo_summary',
                    'available': True
                }
        logger.warning(f"SLURM sinfo聚合命令执行失败或输出为空: {result.stderr}")
        return {'available': False}
    except subprocess.TimeoutExpired:
        logger.warning("SLURM聚合命令超时")
        return {'available': False}
    except FileNotFoundError:
        logger.warning("未找到SLURM命令，可能不在SLURM环境中")
        return {'available': False}
    except Exception as e:
        logger.warning(f"获取SLURM聚合资源信息时出错: {e}")
        return {'available': False}


def get_slurm_cluster_resources():
    """获取SLURM集群的CPU资源信息（考虑节点负载与超线程）"""
    use_ssh_load = os.environ.get("RASPA_NODE_LOAD_SSH", "false").lower() in ("1", "true", "yes", "y", "on")

    def _load_from_ssh(node: str):
        """Optional: read 1-min loadavg via SSH to capture非SLURM负载"""
        if not use_ssh_load:
            return None
        try:
            out = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", node, "cat /proc/loadavg"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if out.returncode != 0:
                return None
            first = out.stdout.strip().split()
            if not first:
                return None
            return float(first[0])
        except Exception:
            return None

    format_spec = '%N|%c|%C|%O|%z'
    try:
        result = subprocess.run(['sinfo', '-N', '-h', '-o', format_spec],
                                capture_output=True, text=True, timeout=30)
        if result.returncode != 0 or not result.stdout.strip():
            logger.warning(f"SLURM节点级命令执行失败或输出为空: {result.stderr}")
            return _get_slurm_summary()

        total_cpus = allocated_cpus = other_cpus = 0
        total_free_cpus = 0
        nodes = []

        for line in result.stdout.strip().splitlines():
            parts = line.strip().split('|')
            if len(parts) < 4:
                continue

            node_name = parts[0]
            try:
                node_total = int(parts[1])
            except ValueError:
                continue

            summary = parts[2]
            summary_parts = summary.split('/')
            if len(summary_parts) != 4:
                continue

            try:
                node_alloc = int(summary_parts[0])
                node_other = int(summary_parts[2])
                node_total_from_summary = int(summary_parts[3])
            except ValueError:
                continue

            node_total = node_total_from_summary or node_total

            load_str = parts[3]
            load_value = None
            if load_str and load_str.lower() not in ('unknown', '(null)', 'n/a', '-'):
                try:
                    load_value = float(str(load_str).rstrip("*"))
                except ValueError:
                    load_value = None
            load_from_ssh = _load_from_ssh(node_name)
            if load_from_ssh is not None:
                load_value = load_from_ssh

            topology = parts[4] if len(parts) > 4 else ''
            sockets = cores_per_socket = threads_per_core = None
            physical_cpus = None
            if topology:
                topo_parts = topology.split(':')
                if len(topo_parts) == 3:
                    try:
                        sockets = int(topo_parts[0])
                        cores_per_socket = int(topo_parts[1])
                        threads_per_core = int(topo_parts[2])
                        if threads_per_core > 0:
                            physical_cpus = (node_total // threads_per_core)
                    except ValueError:
                        threads_per_core = None

            load_effective = int(math.ceil(load_value)) if load_value is not None else 0

            free_by_alloc = max(0, node_total - node_alloc - node_other)
            free_by_load = max(0, node_total - load_effective)
            node_free = min(free_by_alloc, free_by_load)

            nodes.append({
                'node': node_name,
                'total_cpus': node_total,
                'allocated_cpus': node_alloc,
                'other_cpus': node_other,
                'load': load_value,
                'topology': topology,
                'sockets': sockets,
                'cores_per_socket': cores_per_socket,
                'threads_per_core': threads_per_core,
                'physical_cpus': physical_cpus,
                'free_cpus': node_free,
                'usable_cpus': node_total,
            })

            total_cpus += node_total
            allocated_cpus += node_alloc
            other_cpus += node_other
            total_free_cpus += node_free

        if not nodes:
            logger.warning("未能解析到任何节点资源信息，回退到聚合统计")
            return _get_slurm_summary()

        return {
            'total_cpus': total_cpus,
            'allocated_cpus': allocated_cpus,
            'other_cpus': other_cpus,
            'available_cpus': int(total_free_cpus),
            'nodes': nodes,
            'method': 'sinfo_per_node',
            'available': True
        }

    except subprocess.TimeoutExpired:
        logger.warning("SLURM节点级命令超时")
        return _get_slurm_summary()
    except FileNotFoundError:
        logger.warning("未找到SLURM命令，可能不在SLURM环境中")
        return {'available': False}
    except Exception as e:
        logger.warning(f"获取SLURM节点资源信息时出错: {e}")
        return _get_slurm_summary()


def build_node_plan(cluster_info, cpu_cores):
    """根据集群资源信息生成节点分配计划"""
    if not cluster_info or not cluster_info.get('available'):
        return "", []

    nodes = cluster_info.get('nodes') or []
    if not nodes or cpu_cores <= 0:
        return "", []

    priority_map = parse_node_priorities()
    if priority_map:
        ordered_items = ", ".join(
            f"{name}:{prio}" for name, prio in sorted(priority_map.items(), key=lambda x: -x[1])
        )
        logger.info(f"应用节点优先级: {ordered_items}")

    def node_priority(node):
        return priority_map.get(node.get('node'), 0)

    def sort_group(group):
        return sorted(
            group,
            key=lambda n: (
                -node_priority(n),
                -(n.get('free_cpus', 0) or 0),
                n.get('load') if n.get('load') is not None else 0
            )
        )

    # 计算有效可用核：考虑 CPULoad，避免高负载节点被误判为空闲
    for n in nodes:
        total = int(n.get('total_cpus', 0) or 0)
        free = max(0, int(n.get('free_cpus', 0) or 0))
        alloc = max(0, int(n.get('allocated_cpus', 0) or 0))
        load_val_raw = n.get('load')
        try:
            load_val = float(str(load_val_raw).rstrip("*"))
        except Exception:
            load_val = None
        busy = max(alloc, load_val if load_val is not None else 0)
        headroom = max(0, total - math.ceil(busy))
        effective = max(0, min(free, headroom))
        load_ratio = 0.0
        if total > 0 and load_val is not None:
            load_ratio = max(0.0, float(load_val) / float(total))
        alloc_ratio = float(alloc) / float(total) if total > 0 else 0.0
        if load_ratio >= 0.85 or alloc_ratio >= 0.95:
            effective = 0
        elif load_ratio >= 0.70 or alloc_ratio >= 0.85:
            effective = int(effective * 0.5)
        n['_effective_free'] = effective
        n['_load_ratio'] = load_ratio
        n['_total_cpus'] = total

    ordered_nodes = sorted(
        nodes,
        key=lambda n: (
            -node_priority(n),
            -(n.get('_effective_free', 0) or 0),
            -(n.get('free_cpus', 0) or 0),
            n.get('load') if n.get('load') is not None else 0
        )
    )
    plan_counts = OrderedDict()
    plan_queue = []
    remaining = cpu_cores

    # 第一轮：按有效可用核分配（考虑负载）
    for node in ordered_nodes:
        if remaining <= 0:
            break
        cap = int(node.get('_effective_free', 0) or 0)
        if cap < 0:
            cap = 0
        if cap <= 0:
            continue
        take = min(cap, remaining)
        plan_queue.extend([node['node']] * take)
        remaining -= take

    # 第二轮：若仍有余量，按剩余 free_cpus 继续分配，确保低优先级空闲节点也被使用
    if remaining > 0:
        for node in ordered_nodes:
            if remaining <= 0:
                break
            cap = int(node.get('free_cpus', 0) or 0)
            total = int(node.get('_total_cpus', 0) or 0)
            load_ratio = float(node.get('_load_ratio', 0.0) or 0.0)
            alloc_ratio = float(node.get('allocated_cpus', 0) or 0.0) / float(total) if total > 0 else 0.0
            if load_ratio >= 0.85 or alloc_ratio >= 0.95:
                cap = 0
            elif load_ratio >= 0.70 or alloc_ratio >= 0.85:
                cap = int(cap * 0.5)
            if cap < 0:
                cap = 0
            take = min(cap, remaining)
            if take <= 0:
                continue
            plan_queue.extend([node['node']] * take)
            remaining -= take

    for node_name in plan_queue:
        plan_counts[node_name] = plan_counts.get(node_name, 0) + 1

    plan_pairs = [(node, count) for node, count in plan_counts.items() if count > 0]
    plan_string = ",".join(f"{node}:{count}" for node, count in plan_pairs)
    return plan_string, plan_pairs

def get_directory_setup():
    """获取输出目录设置"""
    logger.info("=== 步骤1：设置输出目录 ===")

    # 尝试从环境变量读取
    output_dir_env = os.environ.get('RASPA_OUTPUT_DIR')
    if output_dir_env:
        logger.info(f"从配置文件读取输出目录: {output_dir_env}")
        return output_dir_env

    while True:
        try:
            subdir = input("请输入用于存放输出文件的目录名 (e.g., '302'): ").strip()
            if subdir:
                # 验证目录名格式
                if not all(c.isalnum() or c in '-_' for c in subdir):
                    logger.warning("目录名包含非法字符，请使用字母、数字、下划线或连字符")
                    continue

                # 检查目录是否已存在
                if os.path.exists(subdir):
                    overwrite = input(f"目录 '{subdir}' 已存在。覆盖? (y/n): ").strip().lower()
                    if overwrite != 'y':
                        continue

                return subdir
            logger.warning("目录名不能为空，请重新输入")
        except KeyboardInterrupt:
            logger.info("用户取消操作")
            sys.exit(130)  # 使用SIGINT的标准退出码
        except Exception as e:
            logger.error(f"获取目录名时出错: {str(e)}")

def get_framework_data():
    """获取并处理CSV文件数据"""
    logger.info("=== 步骤2：选择框架结构 ===")

    # 尝试从环境变量读取CSV文件路径
    csv_path_env = os.environ.get('RASPA_CSV_FILE')
    if csv_path_env:
        csv_path = csv_path_env
        logger.info(f"从配置文件读取CSV文件路径: {csv_path}")
    else:
        while True:
            try:
                csv_path = input("请输入CSV文件路径: ").strip()
                if not os.path.exists(csv_path):
                    logger.warning(f"文件不存在: {csv_path}")
                    continue
                break
            except KeyboardInterrupt:
                logger.info("用户取消操作")
                sys.exit(130)

    # 验证CSV文件
    if not os.path.exists(csv_path):
        logger.error(f"CSV文件不存在: {csv_path}")
        return None, None

    try:
        # 读取CSV文件，处理BOM编码问题
        try:
            df = pd.read_csv(csv_path, encoding='utf-8-sig')  # utf-8-sig可以自动处理BOM
        except UnicodeDecodeError:
            try:
                df = pd.read_csv(csv_path, encoding='utf-8')
            except UnicodeDecodeError:
                df = pd.read_csv(csv_path, encoding='gbk')
    except Exception as e:
        logger.error(f"无法读取CSV文件: {str(e)}")
        return None, None

    df = df.dropna(subset=[df.columns[0]])
    columns = df.columns.tolist()

    logger.info("可用的列名:")
    for i, col in enumerate(columns):
        print(f"{i+1}. {col}")

    # 尝试从环境变量读取框架列名
    framework_column_env = os.environ.get('RASPA_FRAMEWORK_COLUMN')
    if framework_column_env:
        if framework_column_env in columns:
            framework_column = framework_column_env
            logger.info(f"从配置文件读取框架列名: {framework_column}")
        else:
            logger.warning(f"配置文件中的框架列名 '{framework_column_env}' 不存在，使用默认列")
            framework_column = columns[0]  # 使用第一列作为默认
    else:
        # 选择列名
        while True:
            try:
                choice = input("\n请选择包含框架名称的列名 (输入序号或列名): ")
                if choice.isdigit() and 1 <= int(choice) <= len(columns):
                    framework_column = columns[int(choice)-1]
                    break
                elif choice in columns:
                    framework_column = choice
                    break
                else:
                    logger.warning("无效的选择，请重新输入")
            except KeyboardInterrupt:
                logger.info("用户取消操作")
                sys.exit(130)  # 使用SIGINT的标准退出码

    logger.info(f"已选择列名: {framework_column}")

    # 获取框架名称列表
    framework_names = df[framework_column].dropna().tolist()
    framework_names = [name for name in framework_names if str(name).strip()]
    total_structures = len(framework_names)

    if total_structures == 0:
        logger.warning("没有找到有效的框架结构，请检查CSV文件")
        return None, None

    logger.info(f"从CSV文件中读取到总共 {total_structures} 个有效框架结构")

    # 选择处理数量 (支持从环境变量读取)
    # 从现在起不再从配置读取 max_structures；交互式让用户选择数量
    while True:
        try:
            x = int(input(f"\n请输入要处理的结构数量 (1-{total_structures}): "))
            if 1 <= x <= total_structures:
                framework_names = framework_names[:x]
                break
            logger.warning(f"请输入1到{total_structures}之间的数字")
        except ValueError:
            logger.warning("请输入有效的数字")
        except KeyboardInterrupt:
            logger.info("用户取消操作")
            sys.exit(130)  # 使用SIGINT的标准退出码

    return framework_names, x

def get_computation_setup(total_tasks, cif_dir=None):
    """获取计算设置"""
    logger.info("=== 步骤3：设置计算参数 ===")

    # 获取系统可用总核心数
    system_cores = multiprocessing.cpu_count()
    logger.info(f"当前节点CPU核心数: {system_cores}")
    
    # 获取SLURM集群资源信息
    cluster_info = get_slurm_cluster_resources()
    globals()['LAST_CLUSTER_INFO'] = cluster_info
    if cluster_info['available']:
        logger.info(f"SLURM集群总 CPU核心数: {cluster_info['total_cpus']}")
        logger.info(f"SLURM集群已分配 CPU核心数: {cluster_info['allocated_cpus']}")
        logger.info(f"SLURM集群当前可用 CPU核心数: {cluster_info['available_cpus']}")

        if cluster_info.get('nodes'):
            logger.info("节点资源详情（线程总数/负载/建议可用线程）：")
            for node in cluster_info['nodes']:
                load_txt = f"{node['load']:.2f}" if node['load'] is not None else "未知"
                topo_txt = node.get('topology') or "?"
                free_cpus = node.get('free_cpus', 0)
                physical = node.get('physical_cpus')
                if physical:
                    logger.info(
                        f"  {node['node']}: 总{node['total_cpus']}线程 (物理{physical}, 拓扑{topo_txt}), "
                        f"已分配{node['allocated_cpus']}, CPULoad={load_txt}, 估计可用={free_cpus}"
                    )
                else:
                    logger.info(
                        f"  {node['node']}: 总{node['total_cpus']}线程, 已分配{node['allocated_cpus']}, "
                        f"CPULoad={load_txt}, 估计可用={free_cpus}"
                    )
        
        recommended_cores = min(cluster_info['available_cpus'], total_tasks)
        if recommended_cores > 0:
            logger.info(f"建议使用CPU核心数: {recommended_cores} (基于集群空闲资源)")
        else:
            logger.info("集群当前无空闲CPU资源，请谨慎选择使用数量")
    else:
        logger.info("未检测到SLURM集群环境，使用当前节点信息")

    # 获取CPU核心数
    # 不再从配置读取 cpu_cores；交互式让用户输入并发
    while True:
        try:
            cpu_cores = int(input(f"\n请输入需要运行的CPU核心数 (1-{total_tasks}): "))
            if 1 <= cpu_cores <= total_tasks:
                break
            logger.warning(f"CPU核心数必须在1到{total_tasks}之间")
        except ValueError:
            logger.warning("请输入有效的数字")
        except KeyboardInterrupt:
            logger.info("用户取消操作")
            sys.exit(130)  # 使用SIGINT的标准退出码

    # 构建节点分配计划，便于后续提交阶段指定 nodelist
    if cluster_info.get('available'):
        plan_string, plan_pairs = build_node_plan(cluster_info, cpu_cores)
        if plan_string:
            os.environ['RASPA_NODE_PLAN'] = plan_string
            logger.info(f"节点分配计划: {plan_string}")
            if plan_pairs:
                summary = ", ".join(f"{n}:{c}" for n, c in plan_pairs)
                logger.info(f"节点任务分配总览: {summary}")
            plan_path = None
            if CURRENT_TOPDIR and CURRENT_SUBDIR:
                plan_path = os.path.join(CURRENT_TOPDIR, CURRENT_SUBDIR, ".raspa_node_plan")
                try:
                    with open(plan_path, 'w', encoding='utf-8') as pf:
                        pf.write(plan_string + "\n")
                    logger.info(f"节点分配计划已写入: {plan_path}")
                except Exception as exc:
                    logger.warning(f"写入节点分配计划失败: {exc}")
        else:
            os.environ.pop('RASPA_NODE_PLAN', None)
            if CURRENT_TOPDIR and CURRENT_SUBDIR:
                plan_path = os.path.join(CURRENT_TOPDIR, CURRENT_SUBDIR, ".raspa_node_plan")
                if os.path.exists(plan_path):
                    try:
                        os.remove(plan_path)
                        logger.info(f"已清理旧的节点分配计划: {plan_path}")
                    except Exception as exc:
                        logger.warning(f"删除节点分配计划失败: {exc}")
    else:
        os.environ.pop('RASPA_NODE_PLAN', None)
        if CURRENT_TOPDIR and CURRENT_SUBDIR:
            plan_path = os.path.join(CURRENT_TOPDIR, CURRENT_SUBDIR, ".raspa_node_plan")
            if os.path.exists(plan_path):
                try:
                    os.remove(plan_path)
                    logger.info(f"已清理旧的节点分配计划: {plan_path}")
                except Exception as exc:
                    logger.warning(f"删除节点分配计划失败: {exc}")

    # 获取截断半径
    while True:
        try:
            # 尝试从环境变量读取
            cutoff_env = os.environ.get('RASPA_CUTOFF_RADIUS')
            if cutoff_env:
                cutoff = float(cutoff_env)
                logger.info(f"从配置文件读取截断半径: {cutoff}")
            else:
                cutoff = float(input("请输入截断半径 (e.g., '12'): "))

            if cutoff <= 0:
                logger.warning("截断半径必须大于0")
                continue
            if cutoff > 100:  # 合理性检查
                if cutoff_env:
                    logger.warning(f"警告: 截断半径 {cutoff} 非常大")
                else:
                    confirm = input("警告: 截断半径非常大，确认使用此值? (y/n): ").strip().lower()
                    if confirm != 'y':
                        continue
            break
        except ValueError:
            logger.warning("请输入有效的数字")
        except KeyboardInterrupt:
            logger.info("用户取消操作")
            sys.exit(130)  # 使用SIGINT的标准退出码

    # CIF文件目录已在前面的步骤中设置
    cif_dir = cif_dir  # 使用已经设置的CIF目录

    # 获取分子名称
    molecules_env = os.environ.get('RASPA_DEFAULT_MOLECULES')
    if molecules_env:
        molecule_name = molecules_env
        logger.info(f"从配置文件读取分子: {molecule_name}")
    else:
        molecule_name = input("请输入分子名称 (默认为'I2', 支持多种分子用空格分隔): ").strip()
        if not molecule_name:
            molecule_name = "I2"

    logger.info(f"将使用分子: {molecule_name}")

    # 支持多种气体分子
    molecule_list = molecule_name.split()
    if len(molecule_list) > 1:
        logger.info(f"检测到多种气体分子: {', '.join(molecule_list)}")

    # 读取/输入 simulation.input 模板路径（留空使用默认模板）
    template_path_env = os.environ.get('RASPA_TEMPLATE_PATH')
    template_path = None
    if template_path_env:
        if os.path.exists(template_path_env):
            template_path = template_path_env
            logger.info(f"从配置文件读取模板路径: {template_path}")
        else:
            logger.warning(f"配置文件中的模板文件不存在: {template_path_env}")

    if template_path is None and raspa_version == 'raspa2':
        user_input = input("请输入simulation.input模板文件路径 (留空使用默认模板): ").strip()
        if user_input:
            if os.path.exists(user_input):
                template_path = user_input
                logger.info(f"将使用自定义模板: {template_path}")
            else:
                logger.warning(f"模板文件不存在，继续使用默认模板: {user_input}")

    # 询问是否使用CSV文件获取孔隙率
    use_void_csv_env = os.environ.get('RASPA_USE_VOID_CSV')
    void_csv_file_env = os.environ.get('RASPA_VOID_CSV_FILE')
    void_column_env = os.environ.get('RASPA_VOID_COLUMN')

    if use_void_csv_env:
        use_void_csv = use_void_csv_env.lower() == 'true'
        logger.info(f"从配置文件读取孔隙率设置: {'使用' if use_void_csv else '不使用'}CSV文件")
    else:
        use_void_csv = input("是否使用CSV文件获取孔隙率? (y/n): ").strip().lower() == 'y'

    void_csv_file = None
    void_fraction_column = None

    if use_void_csv:
        if void_csv_file_env:
            void_csv_file = void_csv_file_env
            if os.path.exists(void_csv_file):
                logger.info(f"从配置文件读取孔隙率CSV文件: {void_csv_file}")
            else:
                logger.warning(f"配置文件中的孔隙率CSV文件不存在: {void_csv_file}")
                void_csv_file = None
        else:
            while True:
                void_csv_file = input("请输入包含孔隙率的CSV文件路径: ").strip()
                if not void_csv_file:
                    logger.warning("文件路径不能为空")
                    continue
                if not os.path.exists(void_csv_file):
                    logger.warning(f"文件不存在: {void_csv_file}")
                    continue
                break

        # 读取CSV文件并显示列名
        try:
            df = pd.read_csv(void_csv_file)
            columns = df.columns.tolist()

            logger.info("可用的列名:")
            for i, col in enumerate(columns):
                print(f"{i+1}. {col}")

            # 尝试从环境变量读取孔隙率列名
            if void_column_env:
                if void_column_env in columns:
                    void_fraction_column = void_column_env
                    logger.info(f"从配置文件读取孔隙率列名: {void_fraction_column}")
                else:
                    logger.warning(f"配置文件中的孔隙率列名 '{void_column_env}' 不存在，使用默认列")
                    void_fraction_column = columns[0]  # 使用第一列作为默认
            else:
                # 选择列名
                while True:
                    try:
                        choice = input("\n请选择包含孔隙率的列名 (输入序号或列名): ")
                        if choice.isdigit() and 1 <= int(choice) <= len(columns):
                            void_fraction_column = columns[int(choice)-1]
                            break
                        elif choice in columns:
                            void_fraction_column = choice
                            break
                        else:
                            logger.warning("无效的选择，请重新输入")
                    except KeyboardInterrupt:
                        logger.info("用户取消操作")
                        sys.exit(130)  # 使用SIGINT的标准退出码

            logger.info(f"已选择孔隙率列: {void_fraction_column}")

        except Exception as e:
            logger.error(f"读取CSV文件时出错: {e}")
            void_csv_file = None
            void_fraction_column = None

    return cpu_cores, cutoff, void_csv_file, void_fraction_column, template_path, molecule_name, cif_dir

def update_all_files(topdir, total_tasks, subdir, cpu_cores):
    """更新所有配置文件"""
    try:
        # 获取 RASPA 版本
        raspa_version = get_raspa_version_from_env()

        # 获取安装目录
        tool_dir = os.path.join(os.environ.get('HOME', ''), 'raspa2-calc/.raspa_tools')
        logger.info(f"工具目录: {tool_dir}")
        logger.info(f"工作目录: {topdir}")
        logger.info(f"RASPA 版本: {raspa_version.upper()}")

        # 注：作业日志的目录与开关通过环境变量传递（由 raspa_calc.py 读取 config 并设置），
        # 此处不直接读取配置对象，避免在本模块中依赖全局 config。
        # 创建job_templates目录（如果不存在）
        job_templates_dir = os.path.join(topdir, "job_templates")
        os.makedirs(job_templates_dir, exist_ok=True)

        # 根据 RASPA 版本选择模板文件
        template_files = ['job_submit_ht.sh', 'job_submit.sh', 'tasksrun.sh', 'pbs.sh', 'sbatch.sh', 'local.sh']

        # 根据版本添加 runjobs 脚本
        if raspa_version == 'raspa3':
            template_files.append('runjobs_raspa3.sh')
        else:
            template_files.append('runjobs.sh')

        logger.info(f"准备复制 {len(template_files)} 个模板文件到 {job_templates_dir}")
        for file in template_files:
            src = os.path.join(tool_dir, 'job_templates', file)
            dst = os.path.join(job_templates_dir, file)

            # RASPA3 的 runjobs_raspa3.sh 复制为 runjobs.sh
            if file == 'runjobs_raspa3.sh':
                dst = os.path.join(job_templates_dir, 'runjobs.sh')
                logger.info(f"复制 {file} -> runjobs.sh (RASPA3模式)")
            else:
                logger.info(f"复制 {file}: {src} -> {dst}")

            if os.path.exists(src):
                shutil.copy2(src, dst)
                # 设置执行权限
                os.chmod(dst, 0o755)
                logger.info(f"已复制并设置权限: {os.path.basename(dst)}")
            else:
                logger.warning(f"Warning: Template file {file} not found in installation directory")

        logger.info("模板脚本已复制到工作目录，运行时将通过环境变量注入参数，无需额外重写。")

        # 提交前清理旧任务队列与指针，避免使用陈旧列表
        try:
            queue_path = os.path.join(topdir, subdir, ".raspa_task_queue")
            lock_path = queue_path + ".lock"
            for p in (queue_path, lock_path):
                if os.path.exists(p):
                    os.remove(p)
            logger.info("已清理旧的 .raspa_task_queue 队列文件")
        except Exception as _e:
            logger.warning(f"清理队列文件失败: {_e}")

        try:
            pointer_dir = os.path.join(topdir, subdir, ".raspa_queue")
            if os.path.isdir(pointer_dir):
                shutil.rmtree(pointer_dir)
                logger.info("已重置 .raspa_queue 指针目录")
        except Exception as _e:
            logger.warning(f"重置 .raspa_queue 失败: {_e}")

        return True

    except Exception as e:
        logger.error(f"更新配置文件时出错: {e}")
        return False

def check_structure_files(framework_name, custom_cif_dir=None):
    """检查CIF结构文件是否存在

    Args:
        framework_name (str): 框架名称
        custom_cif_dir (str, optional): 自定义CIF文件目录. 默认为None.

    Returns:
        str: CIF结构文件路径，如果找不到则返回None
    """
    # 处理框架名称，确保它没有.cif后缀
    if framework_name.lower().endswith('.cif'):
        framework_name = framework_name[:-4]  # 移除.cif后缀

    # 使用自定义CIF目录或默认目录
    if custom_cif_dir:
        cif_dir = custom_cif_dir
    else:
        # 从环境变量读取CIF目录，如果没有则使用默认值
        cif_dir = os.environ.get('RASPA_CIF_DIR')
        if not cif_dir:
            current_dir = os.getcwd()
            cif_dir = os.path.join(current_dir, "data", "cif")

    # 检查标准CIF文件名
    cif_file = os.path.join(cif_dir, f"{framework_name}.cif")
    if os.path.exists(cif_file):
        return cif_file

    # 尝试其他可能的文件名形式
    alternative_files = [
        os.path.join(cif_dir, f"{framework_name.upper()}.cif"),  # 全大写
        os.path.join(cif_dir, f"{framework_name.lower()}.cif"),  # 全小写
        os.path.join(cif_dir, f"{framework_name}")  # 无后缀
    ]

    for alt_file in alternative_files:
        if os.path.exists(alt_file):
            logger.info(f"找到框架 {framework_name} 的替代CIF文件: {alt_file}")
            return alt_file

    # 尝试使用新的检查函数查找文件
    from calculate_params import check_structure_files as check_cif_files
    cif_file = check_cif_files(framework_name, cif_dir)
    if cif_file:
        return cif_file

    # 列出目录中的所有文件，便于调试
    if os.path.exists(cif_dir):
        logger.debug(f"CIF目录 {cif_dir} 中的文件:")
        for file in os.listdir(cif_dir):
            logger.debug(f"  - {file}")

    logger.error(f"找不到框架 {framework_name} 的CIF结构文件")
    return None

def process_framework(topdir, subdir, counter, framework_name, cutoff, void_csv_file=None, void_fraction_column=None, template_path=None, molecule_name="I2", cif_dir=None, framework_column=None, result_cache=None):
    """处理单个框架结构

    Args:
        topdir (str): 主目录路径
        subdir (str): 子目录路径
        counter (int): 结构计数器
        framework_name (str): 框架名称
        cutoff (float): 截断半径
        void_csv_file (str, optional): 包含孔隙率的CSV文件路径. 默认为None.
        void_fraction_column (str, optional): 孔隙率列的列名. 默认为None.
        framework_column (str, optional): 框架名称列的列名. 默认为None.
        template_path (str, optional): 自定义simulation.input模板路径. 默认为None.
        molecule_name (str, optional): 分子名称. 默认为"I2".
        cif_dir (str, optional): 自定义CIF文件目录. 默认为None.
        result_cache (dict, optional): 计算结果缓存字典. 默认为None.

    Returns:
        bool: 处理成功返回True，失败返回False
    """
    # 提前创建目录以便存放日志
    md_dir = os.path.join(topdir, subdir, f"mc{counter}")
    os.makedirs(md_dir, exist_ok=True)

    # 设置任务级日志
    task_log_file = os.path.join(md_dir, "raspa_calculation.log")
    task_handler = logging.FileHandler(task_log_file, mode='w')
    task_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    task_handler.setLevel(logging.INFO)
    
    current_logger = logging.getLogger()
    current_logger.addHandler(task_handler)

    try:
        try:
            # 检查wei文件
            structure_file = check_structure_files(framework_name, cif_dir)
            if structure_file is None:
                logger.error(f"找不到框架 {framework_name} 的结构文件")
                return False

            # 使用calculate_params.py处理结构文件
            success, unit_cells, void_fraction = process_structure_file(
                structure_file,
                cutoff,
                csv_file=void_csv_file,
                void_fraction_column=void_fraction_column,
                framework_column=framework_column,
                result_cache=result_cache
            )
            if not success:
                return False

            # 目录已创建，这里无需再次创建
            # md_dir = os.path.join(topdir, subdir, f"mc{counter}")
            # os.makedirs(md_dir, exist_ok=True)

            # 确定使用哪个simulation.input模板
            if template_path and os.path.isfile(template_path):
                # 使用自定义模板
                sim_input_file = template_path
                logger.info(f"使用自定义模板: {template_path}")
            else:
                logger.error("缺少 RASPA2 模板，请在 config.yaml 中设置 template_path 指向可用的 simulation.input")
                return False

            # 复制simulation.input文件
            import subprocess
            try:
                subprocess.run(f"cp -rf {sim_input_file} {md_dir}/", shell=True, check=True, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError:
                return False

            # 更新模拟输入文件
            sim_input_path = os.path.join(md_dir, "simulation.input")
            if not os.path.exists(sim_input_path):
                return False

            with open(sim_input_path, "r") as f:
                lines = f.readlines()

            updated_lines = []
            # 处理多组分分子名称
            molecule_list = molecule_name.split() if isinstance(molecule_name, str) else [molecule_name]
            # MSER 控制参数（仅 RASPA2）
            mser_enable = os.environ.get('RASPA_MSER_ENABLE', 'false').lower() == 'true'
            mser_add_cycles = int(os.environ.get('RASPA_MSER_ADD_CYCLES', '500')) if mser_enable else None
            seen_number_cycles = seen_init_cycles = seen_equil_cycles = False
            seen_continue = seen_restart = seen_print = False
            
            for line in lines:
                if line.startswith("FrameworkName"):
                    updated_lines.append(f"FrameworkName {framework_name}\n")
                elif line.startswith("UnitCells"):
                    updated_lines.append(f"UnitCells {unit_cells[0]} {unit_cells[1]} {unit_cells[2]}\n")
                elif line.startswith("HeliumVoidFraction"):
                    updated_lines.append(f"HeliumVoidFraction {void_fraction}\n")
                elif mser_enable and line.lower().startswith("numberofcycles"):
                    seen_number_cycles = True
                    updated_lines.append(f"NumberOfCycles {mser_add_cycles}\n")
                elif mser_enable and line.lower().startswith("numberofinitializationcycles"):
                    seen_init_cycles = True
                    updated_lines.append("NumberOfInitializationCycles 0\n")
                elif mser_enable and line.lower().startswith("numberofequilibrationcycles"):
                    seen_equil_cycles = True
                    updated_lines.append("NumberOfEquilibrationCycles 0\n")
                elif mser_enable and line.lower().startswith("restartfile"):
                    seen_restart = True
                    updated_lines.append("RestartFile no\n")
                elif mser_enable and line.lower().startswith("printevery"):
                    seen_print = True
                    updated_lines.append("PrintEvery 1\n")
                elif line.startswith("Component ") and "MoleculeName" in line:
                    # 提取Component编号
                    parts = line.split()
                    if len(parts) >= 3 and parts[0] == "Component" and parts[2] == "MoleculeName":
                        try:
                            component_idx = int(parts[1])
                            if component_idx < len(molecule_list):
                                # 使用对应的分子名称
                                molecule = molecule_list[component_idx]
                                # 保持原有的格式和空格
                                prefix = line[:line.find("MoleculeName") + len("MoleculeName")]
                                updated_lines.append(f"{prefix}   {molecule}\n")
                            else:
                                # 如果组分编号超出分子列表范围，使用第一个分子
                                molecule = molecule_list[0]
                                prefix = line[:line.find("MoleculeName") + len("MoleculeName")]
                                updated_lines.append(f"{prefix}   {molecule}\n")
                        except (ValueError, IndexError):
                            # 如果解析失败，使用原有行
                            updated_lines.append(line)
                    else:
                        updated_lines.append(line)
                else:
                    updated_lines.append(line)

            # 如果模板缺少相关字段且启用 MSER，追加默认值
            if mser_enable:
                if not seen_number_cycles:
                    updated_lines.append(f"NumberOfCycles {mser_add_cycles}\n")
                if not seen_init_cycles:
                    updated_lines.append("NumberOfInitializationCycles 0\n")
                if not seen_equil_cycles:
                    updated_lines.append("NumberOfEquilibrationCycles 0\n")
                if not seen_restart:
                    updated_lines.append("RestartFile no\n")
                if not seen_print:
                    updated_lines.append("PrintEvery 1\n")

            with open(sim_input_path, "w") as f:
                f.writelines(updated_lines)

            return True

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.debug(f"Error processing structure {framework_name}: {e}")
            return False
    finally:
        current_logger.removeHandler(task_handler)
        task_handler.close()


def process_framework_raspa3(topdir, subdir, counter, framework_name, cutoff, void_csv_file=None,
                              void_fraction_column=None, template_path=None, molecule_name="CO2",
                              cif_base_path=None, json_dir=None, framework_column=None, result_cache=None):
    """处理单个框架结构 (RASPA3 版本)

    Args:
        topdir (str): 主目录路径
        subdir (str): 子目录路径
        counter (int): 结构计数器
        framework_name (str): 框架名称
        cutoff (float): 截断半径
        void_csv_file (str, optional): 包含孔隙率的CSV文件路径
        void_fraction_column (str, optional): 孔隙率列的列名
        framework_column (str, optional): 框架名称列的列名
        template_path (str, optional): 自定义 simulation.json 模板路径
        molecule_name (str, optional): 分子名称 (支持多分子空格分隔)
        cif_base_path (str, optional): CIF 文件基础路径
        json_dir (str, optional): JSON 文件目录 (force_field.json, 分子定义文件)
        result_cache (dict, optional): 计算结果缓存字典

    Returns:
        bool: 处理成功返回True，失败返回False
    """
    # 提前创建目录以便存放日志
    md_dir = os.path.join(topdir, subdir, f"mc{counter}")
    os.makedirs(md_dir, exist_ok=True)

    # 设置任务级日志
    task_log_file = os.path.join(md_dir, "raspa_calculation.log")
    task_handler = logging.FileHandler(task_log_file, mode='w')
    task_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    task_handler.setLevel(logging.INFO)
    
    current_logger = logging.getLogger()
    current_logger.addHandler(task_handler)

    try:
        try:
            # 查找 CIF 文件
            cif_path = None
            clean_name = framework_name
            if clean_name.lower().endswith('.cif'):
                clean_name = clean_name[:-4]

            if cif_base_path:
                # RASPA3 风格：使用 cif_base_path
                candidates = [
                    os.path.join(cif_base_path, f"{clean_name}.cif"),
                    os.path.join(cif_base_path, f"{clean_name}"),
                    os.path.join(cif_base_path, f"{clean_name.upper()}.cif"),
                    os.path.join(cif_base_path, f"{clean_name.lower()}.cif"),
                ]
                for path in candidates:
                    if os.path.exists(path):
                        cif_path = path
                        break

            if cif_path is None:
                logger.error(f"找不到框架 {framework_name} 的 CIF 文件")
                return False

            # 使用 calculate_params.py 处理结构文件
            success, unit_cells, void_fraction = process_structure_file(
                cif_path,
                cutoff,
                csv_file=void_csv_file,
                void_fraction_column=void_fraction_column,
                framework_column=framework_column,
                result_cache=result_cache
            )
            if not success:
                # 后备方案：简单计算
                try:
                    cell_params = {}
                    with open(cif_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith('_cell_length_a'):
                                cell_params['a'] = float(line.split()[1].split('(')[0])
                            elif line.startswith('_cell_length_b'):
                                cell_params['b'] = float(line.split()[1].split('(')[0])
                            elif line.startswith('_cell_length_c'):
                                cell_params['c'] = float(line.split()[1].split('(')[0])

                    if 'a' in cell_params and 'b' in cell_params and 'c' in cell_params:
                        unit_a = max(1, math.ceil(2 * cutoff / cell_params['a']))
                        unit_b = max(1, math.ceil(2 * cutoff / cell_params['b']))
                        unit_c = max(1, math.ceil(2 * cutoff / cell_params['c']))
                        unit_cells = [unit_a, unit_b, unit_c]
                        void_fraction = 0.5  # 默认孔隙率
                    else:
                        unit_cells = [1, 1, 1]
                        void_fraction = 0.5
                except Exception:
                    unit_cells = [1, 1, 1]
                    void_fraction = 0.5

            # 目录已创建，这里无需再次创建
            # md_dir = os.path.join(topdir, subdir, f"mc{counter}")
            # os.makedirs(md_dir, exist_ok=True)

            # 确定使用哪个 simulation.json 模板
            if template_path and os.path.isfile(template_path):
                sim_template_file = template_path
            else:
                tool_dir = os.environ.get('HOME', '') + '/raspa2-calc/.raspa_tools'
                sim_template_file = os.path.join(tool_dir, "raspa3json", "CO2", "simulation.json")
                if not os.path.isfile(sim_template_file):
                    logger.error("找不到 RASPA3 模板文件，请在 config.yaml 设置 raspa3_template_path 指向可用的 simulation.json")
                    return False

            # 加载模板
            with open(sim_template_file, 'r', encoding='utf-8') as f:
                sim_config = json.load(f)

            # 深拷贝并更新配置
            sim_config = copy.deepcopy(sim_config)

            # 更新 Systems 配置
            if "Systems" in sim_config and len(sim_config["Systems"]) > 0:
                # 设置 CIF 文件绝对路径 (RASPA3 需要绝对路径)
                sim_config["Systems"][0]["Name"] = cif_path
                # 设置 NumberOfUnitCells
                sim_config["Systems"][0]["NumberOfUnitCells"] = unit_cells
                # 设置孔隙率
                sim_config["Systems"][0]["HeliumVoidFraction"] = void_fraction

            # 更新 Components (分子名称)
            molecule_list = molecule_name.split() if isinstance(molecule_name, str) else [molecule_name]
            if "Components" in sim_config:
                for i, component in enumerate(sim_config["Components"]):
                    if i < len(molecule_list):
                        component["Name"] = molecule_list[i]
                    elif molecule_list:
                        component["Name"] = molecule_list[0]

            # pyMSER: 生成阶段即按追加步数和最小输出频率配置
            mser_enable = os.environ.get('RASPA_MSER_ENABLE', 'false').lower() == 'true'
            if mser_enable:
                try:
                    mser_add_cycles = int(os.environ.get('RASPA_MSER_ADD_CYCLES', '500'))
                except ValueError:
                    mser_add_cycles = 500
                sim_config["NumberOfCycles"] = mser_add_cycles
                sim_config["NumberOfInitializationCycles"] = 0
                sim_config["NumberOfEquilibrationCycles"] = 0
                sim_config["PrintEvery"] = 1

            # 移除二进制重启相关字段，统一走 JSON RestartFileName
            sim_config.pop("WriteBinaryRestartEvery", None)
            sim_config.pop("RestartFromBinaryFile", None)

            # 保存 simulation.json
            sim_path = os.path.join(md_dir, "simulation.json")
            with open(sim_path, 'w', encoding='utf-8') as f:
                json.dump(sim_config, f, indent=2)

            # 复制 JSON 文件到任务目录
            if json_dir and os.path.isdir(json_dir):
                # 复制力场文件
                force_field_src = os.path.join(json_dir, "force_field.json")
                if os.path.exists(force_field_src):
                    dest = os.path.join(md_dir, "force_field.json")
                    write_filtered_force_field(
                        force_field_src,
                        dest,
                        cif_path=cif_path,
                        json_dir=json_dir,
                        component_names=molecule_list,
                        log=logger,
                    )

                # 复制分子定义文件
                for mol_name in molecule_list:
                    mol_src = os.path.join(json_dir, f"{mol_name}.json")
                    if os.path.exists(mol_src):
                        shutil.copy2(mol_src, os.path.join(md_dir, f"{mol_name}.json"))

            return True

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.debug(f"RASPA3 处理框架 {framework_name} 时出错: {e}")
            return False
    finally:
        current_logger.removeHandler(task_handler)
        task_handler.close()


from concurrent.futures import ProcessPoolExecutor, as_completed

def _process_framework_wrapper(args):
    """Wrapper for parallel processing of frameworks"""
    func_name, kwargs = args
    result_cache = kwargs.get('result_cache')
    
    # Snapshot cache keys to detect new entries
    initial_keys = set(result_cache.keys()) if result_cache else set()
    
    success = False
    try:
        if func_name == 'raspa3':
            success = process_framework_raspa3(**kwargs)
        else:
            success = process_framework(**kwargs)
    except Exception as e:
        logger.error(f"Error in worker for {kwargs.get('framework_name')}: {e}")
        return False, {}

    # Identify new cache entries
    new_entries = {}
    if result_cache:
        current_keys = set(result_cache.keys())
        new_keys = current_keys - initial_keys
        for k in new_keys:
            new_entries[k] = result_cache[k]
            
    return success, new_entries

def main():
    try:
        # 检测 RASPA 版本
        raspa_version = get_raspa_version_from_env()
        raspa3_config = load_raspa3_config() if raspa_version == 'raspa3' else {}

        logger.info(f"=== RASPA高通量计算设置 ({raspa_version.upper()}) ===")

        # 步骤1：检查命令行参数和初始化
        print(f"\n步骤1：初始化设置 (RASPA版本: {raspa_version.upper()})")

        # 尝试从环境变量或命令行参数获取信息
        framework_column = 'refcode'  # 默认值
        if len(sys.argv) == 3:
            # 从命令行参数获取（向后兼容）
            csv_file = sys.argv[1]
            column_number = sys.argv[2]
            # 使用默认的framework_column或从环境变量获取
            framework_column = os.environ.get('RASPA_FRAMEWORK_COLUMN', 'refcode')
            logger.info("从命令行参数获取CSV文件信息")
        else:
            # 从环境变量获取（配置文件模式）
            csv_file = os.environ.get('RASPA_CSV_FILE')
            framework_column = os.environ.get('RASPA_FRAMEWORK_COLUMN', 'refcode')

            if not csv_file:
                logger.error("错误：未找到CSV文件路径，请在配置文件中设置csv_file_path")
                sys.exit(1)

            # 将列名转换为列号（简化处理，假设列名就是我们要找的）
            column_number = framework_column
            logger.info("从环境变量获取CSV文件信息")

        if not os.path.exists(csv_file):
            logger.error(f"错误：找不到CSV文件 {csv_file}")
            sys.exit(1)

        topdir = os.path.abspath(os.getcwd())
        subdir = get_directory_setup()
        global CURRENT_TOPDIR, CURRENT_SUBDIR
        CURRENT_TOPDIR = topdir
        CURRENT_SUBDIR = subdir

        if not os.path.exists(os.path.join(topdir, subdir)):
            try:
                os.makedirs(os.path.join(topdir, subdir))
            except Exception as e:
                logger.error(f"无法创建目录: {e}")
                sys.exit(1)

        # 步骤2：读取和处理CSV文件
        print("\n步骤2：处理CSV文件")
        try:
            # 读取CSV文件，处理BOM编码问题
            try:
                df = pd.read_csv(csv_file, encoding='utf-8-sig')
            except UnicodeDecodeError:
                try:
                    df = pd.read_csv(csv_file, encoding='utf-8')
                except UnicodeDecodeError:
                    df = pd.read_csv(csv_file, encoding='gbk')
            df = df.dropna(subset=[df.columns[0]])

            # 处理列名或列号
            if column_number.isdigit():
                # 如果是数字，当作列号处理
                col_index = int(column_number) - 1
                if 0 <= col_index < len(df.columns):
                    framework_names = df[df.columns[col_index]].dropna().tolist()
                else:
                    logger.error(f"列号 {column_number} 超出范围")
                    sys.exit(1)
            else:
                # 如果是字符串，当作列名处理
                if column_number in df.columns:
                    framework_names = df[column_number].dropna().tolist()
                else:
                    logger.error(f"列名 '{column_number}' 不存在于CSV文件中")
                    logger.info(f"可用的列名: {list(df.columns)}")
                    sys.exit(1)

            framework_names = [name for name in framework_names if str(name).strip()]
            total_tasks = len(framework_names)
            initial_total_tasks = total_tasks

            if total_tasks == 0:
                logger.error("没有找到有效的框架结构，请检查CSV文件")
                sys.exit(1)

            logger.info(f"找到 {total_tasks} 个有效框架结构")

            # 获取CIF文件目录（根据RASPA版本使用不同的配置）
            if raspa_version == 'raspa3':
                # RASPA3: 使用 cif_base_path
                cif_dir = raspa3_config.get('cif_base_path', '')
                if not cif_dir:
                    cif_dir = os.environ.get('RASPA_CIF_DIR', '')
                if not cif_dir:
                    default_cif_dir = "/home/zjp/anaconda3/envs/raspa3/share/raspa3/framework"
                    cif_dir = input(f"\n请输入CIF文件基础路径 (默认为'{default_cif_dir}'): ").strip()
                    if not cif_dir:
                        cif_dir = default_cif_dir
                else:
                    logger.info(f"使用配置文件中的CIF基础路径 (RASPA3): {cif_dir}")
            else:
                # RASPA2: 使用传统 cif_dir
                cif_dir = os.environ.get('RASPA_CIF_DIR')
                if not cif_dir:
                    current_dir = os.getcwd()
                    default_cif_dir = os.path.join(current_dir, "data", "cif")
                    cif_dir = input(f"\n请输入CIF文件目录 (默认为'{default_cif_dir}'): ").strip()
                    if not cif_dir:
                        cif_dir = default_cif_dir
                else:
                    logger.info(f"使用配置文件中的CIF目录: {cif_dir}")

            if not os.path.exists(cif_dir):
                logger.warning(f"CIF目录不存在: {cif_dir}")
                create_dir = input("是否创建该目录? (y/n): ").strip().lower()
                if create_dir == 'y':
                    try:
                        os.makedirs(cif_dir, exist_ok=True)
                        logger.info(f"已创建目录: {cif_dir}")
                    except Exception as e:
                        logger.error(f"创建目录失败: {e}")

            logger.info(f"将使用CIF目录: {cif_dir}")

            # 检查每个框架是否有对应的CIF文件
            logger.info("检查框架对应的CIF文件...")
            missing_cifs = []
            skipped_missing_cifs = 0
            found_cifs = []
            framework_cif_paths = {}

            for framework in framework_names:
                cif_file = locate_cif_file(framework, cif_dir)
                if cif_file:
                    found_cifs.append(framework)
                    framework_cif_paths[framework] = cif_file
                else:
                    missing_cifs.append(framework)

            # 显示结果
            if missing_cifs:
                logger.warning(f"以下 {len(missing_cifs)} 个框架没有对应的CIF文件:")
                for i, missing in enumerate(missing_cifs[:10], 1):
                    logger.warning(f"  {i}. {missing}")
                if len(missing_cifs) > 10:
                    logger.warning(f"  ... 及其他 {len(missing_cifs) - 10} 个")

                skipped_missing_cifs = len(missing_cifs)
                logger.warning("上述框架将被自动跳过，程序继续处理其余结构。")

            # 仅保留存在CIF文件的框架以继续后续步骤
            framework_names = found_cifs
            total_tasks = len(framework_names)

            if total_tasks == 0:
                logger.error("所有框架均缺少CIF文件，无法继续计算。")
                sys.exit(1)

            logger.info(f"共找到 {len(found_cifs)} 个框架对应的CIF文件")

            # 检查 CIF 标签是否包含编号
            label_issues = []
            total_label_issues = 0
            
            # 使用并行处理加速标签检查
            logger.info("正在检查 CIF 文件标签格式...")
            
            # 准备检查任务
            check_tasks = []
            for framework in framework_names:
                cif_path = framework_cif_paths.get(framework)
                if not cif_path:
                    continue
                # 如果路径包含 cleaned_cif，直接跳过（认为已清理）
                if "cleaned_cif" in os.path.normpath(cif_path).split(os.sep):
                    continue
                check_tasks.append((framework, cif_path))
            
            if check_tasks:
                try:
                    cpu_count = multiprocessing.cpu_count()
                except Exception:
                    cpu_count = 2
                max_workers = min(16, cpu_count)  # IO密集型，不需要太多进程
                
                with ProcessPoolExecutor(max_workers=max_workers) as executor:
                    # 提交任务：只传递 cif_path 给 count_numbered_labels
                    # 我们需要包装一下以便返回 framework 名称
                    future_to_fw = {
                        executor.submit(count_numbered_labels, cif_path): (framework, cif_path)
                        for framework, cif_path in check_tasks
                    }
                    
                    for future in as_completed(future_to_fw):
                        framework, cif_path = future_to_fw[future]
                        try:
                            issue_count = future.result()
                            if issue_count > 0:
                                label_issues.append((framework, cif_path, issue_count))
                                total_label_issues += issue_count
                        except Exception:
                            pass

            if label_issues:
                preview_limit = 10
                logger.warning(f"检测到 {len(label_issues)} 个 CIF 文件的 _atom_site_label 含编号，共 {total_label_issues} 条标签存在编号。")
                for fw, path, cnt in label_issues[:preview_limit]:
                    logger.warning(f"  - {fw}: {cnt} 个编号标签 ({path})")
                if len(label_issues) > preview_limit:
                    logger.warning(f"  ... 仅展示前 {preview_limit} 个框架，另有 {len(label_issues) - preview_limit} 个未列出")

                user_choice = input("是否使用 clean_cif_labels.py 自动去除编号? (y/n): ").strip().lower()
                if user_choice != 'y':
                    logger.error("用户拒绝自动清理 CIF 标签，程序终止。请先处理标签后重新运行。")
                    sys.exit(1)

                script_path = os.path.join(os.path.dirname(__file__), "clean_cif_labels.py")
                target_files = [os.path.basename(path) for _, path, _ in label_issues]
                logger.info(f"运行标签清理脚本（就地处理有编号的文件）: {script_path} {cif_dir} --in-place --files {', '.join(target_files)}")
                cmd = [sys.executable, script_path, cif_dir, "--in-place", "--files", *target_files]
                result = subprocess.run(cmd)
                if result.returncode != 0:
                    logger.error("标签清理脚本执行失败，程序终止。")
                    sys.exit(1)

                missing_cleaned = [f for f in target_files if not os.path.exists(os.path.join(cif_dir, f))]
                if missing_cleaned:
                    logger.error(f"以下文件未成功完成就地清理: {', '.join(missing_cleaned)}")
                    sys.exit(1)

                logger.info(f"已完成 {len(target_files)} 个 CIF 的就地清理。")

        except Exception as e:
            logger.error(f"处理CSV文件时出错: {e}")
            logger.debug(traceback.format_exc())
            sys.exit(1)

        cpu_cores, cutoff, void_csv_file, void_fraction_column, template_path, molecule_name, _ = get_computation_setup(total_tasks, cif_dir)

        # 步骤3：显示配置摘要
        print("\n步骤3：配置摘要")
        logger.info("计算参数:")
        logger.info(f"- 输出目录: {subdir}")
        logger.info(f"- 处理框架数: {total_tasks}")
        logger.info(f"- CPU核心数: {cpu_cores}")
        logger.info(f"- 截断半径: {cutoff}")
        logger.info(f"- 分子名称: {molecule_name}")
        logger.info(f"- CIF文件目录: {cif_dir}")
        if template_path:
            logger.info(f"- 自定义模板路径: {template_path}")
        if void_csv_file and void_fraction_column:
            logger.info(f"- 孔隙率CSV文件: {void_csv_file}")
            logger.info(f"- 孔隙率列名: {void_fraction_column}")
        
        # 显示完整的模拟输入文件示例 (根据RASPA版本显示不同格式)
        if raspa_version == 'raspa3':
            print("\n=== 生成的 simulation.json 示例 (RASPA3) ===\n")
        else:
            print("\n=== 生成的 simulation.input 示例 (RASPA2) ===\n")

        # 使用第一个框架作为示例
        if framework_names:
            first_framework = framework_names[0]

            # 获取第一个框架的参数
            try:
                structure_file = check_structure_files(first_framework, cif_dir)
                if structure_file:
                    success, unit_cells, void_fraction = process_structure_file(
                        structure_file,
                        cutoff,
                        csv_file=void_csv_file,
                        void_fraction_column=void_fraction_column,
                        framework_column=framework_column
                    )

                    if success:
                        molecule_list = molecule_name.split() if isinstance(molecule_name, str) else [molecule_name]

                        if raspa_version == 'raspa3':
                            # RASPA3: 显示 simulation.json 预览
                            template_file = template_path if template_path and os.path.isfile(template_path) else None
                            if not template_file:
                                tool_dir = os.environ.get('HOME', '') + '/raspa2-calc/.raspa_tools'
                                template_file = os.path.join(tool_dir, "raspa3json", "CO2", "simulation.json")

                            if os.path.exists(template_file):
                                with open(template_file, 'r') as f:
                                    sim_config = json.load(f)

                                # 深拷贝并更新配置
                                sim_config = copy.deepcopy(sim_config)

                                # 更新 Systems 配置
                                if "Systems" in sim_config and len(sim_config["Systems"]) > 0:
                                    sim_config["Systems"][0]["Name"] = structure_file
                                    sim_config["Systems"][0]["NumberOfUnitCells"] = list(unit_cells)
                                    sim_config["Systems"][0]["HeliumVoidFraction"] = void_fraction

                                # 更新 Components (分子名称)
                                if "Components" in sim_config:
                                    for i, component in enumerate(sim_config["Components"]):
                                        if i < len(molecule_list):
                                            component["Name"] = molecule_list[i]
                                        elif molecule_list:
                                            component["Name"] = molecule_list[0]

                                mser_enable = os.environ.get('RASPA_MSER_ENABLE', 'false').lower() == 'true'
                                if mser_enable:
                                    try:
                                        mser_add_cycles = int(os.environ.get('RASPA_MSER_ADD_CYCLES', '500'))
                                    except ValueError:
                                        mser_add_cycles = 500
                                    sim_config["NumberOfCycles"] = mser_add_cycles
                                    sim_config["NumberOfInitializationCycles"] = 0
                                    sim_config["NumberOfEquilibrationCycles"] = 0
                                    sim_config["PrintEvery"] = 1

                                # 移除二进制重启相关字段，统一走 JSON RestartFileName
                                sim_config.pop("WriteBinaryRestartEvery", None)
                                sim_config.pop("RestartFromBinaryFile", None)

                                # 显示 JSON 内容（限制行数避免刷屏）
                                sim_text = json.dumps(sim_config, indent=2)
                                sim_lines = sim_text.splitlines()
                                preview_lines = 60
                                print("\n".join(sim_lines[:preview_lines]))
                                if len(sim_lines) > preview_lines:
                                    print(f"... (共{len(sim_lines)}行，仅显示前{preview_lines}行)")

                            print("\n" + "="*50)
                            print(f"📦 此示例使用框架: {first_framework}")
                            print(f"📦 CIF 文件路径: {structure_file}")
                            print(f"📦 NumberOfUnitCells: {list(unit_cells)}")
                            print(f"📦 孔隙率: {void_fraction}")
                            if len(molecule_list) > 1:
                                print(f"📦 多组分分子: {', '.join(molecule_list)}")
                            else:
                                print(f"📦 分子名称: {molecule_list[0]}")

                            # 显示 JSON 目录信息
                            json_dir = raspa3_config.get('json_dir', '')
                            if json_dir:
                                print(f"📦 JSON 文件目录: {json_dir}")
                            print("="*50)
                        else:
                            # RASPA2: 显示 simulation.input 预览
                            template_file = template_path if template_path and os.path.isfile(template_path) else None
                            if os.path.exists(template_file):
                                with open(template_file, 'r') as f:
                                    template_content = f.read()

                                # 执行替换逻辑
                                lines = template_content.split('\n')

                                # 替换参数
                                for i, line in enumerate(lines):
                                    if line.startswith("FrameworkName"):
                                        lines[i] = f"FrameworkName {first_framework}"
                                    elif line.startswith("UnitCells"):
                                        lines[i] = f"UnitCells {unit_cells[0]} {unit_cells[1]} {unit_cells[2]}"
                                    elif line.startswith("HeliumVoidFraction"):
                                        lines[i] = f"HeliumVoidFraction {void_fraction}"
                                    elif line.startswith("Component ") and "MoleculeName" in line:
                                        # 提取Component编号
                                        parts = line.split()
                                        if len(parts) >= 3 and parts[0] == "Component" and parts[2] == "MoleculeName":
                                            try:
                                                component_idx = int(parts[1])
                                                if component_idx < len(molecule_list):
                                                    molecule = molecule_list[component_idx]
                                                    prefix = line[:line.find("MoleculeName") + len("MoleculeName")]
                                                    lines[i] = f"{prefix}   {molecule}"
                                                else:
                                                    molecule = molecule_list[0]
                                                    prefix = line[:line.find("MoleculeName") + len("MoleculeName")]
                                                    lines[i] = f"{prefix}   {molecule}"
                                            except (ValueError, IndexError):
                                                pass

                                # 显示替换后的内容
                                print('\n'.join(lines[:50]))  # 只显示前50行避免输出过长
                                if len(lines) > 50:
                                    print(f"... (共{len(lines)}行，仅显示前50行)")

                            print("\n" + "="*50)
                            print(f"📦 此示例使用框架: {first_framework}")
                            print(f"📦 UnitCells: {unit_cells[0]} {unit_cells[1]} {unit_cells[2]}")
                            print(f"📦 孔隙率: {void_fraction}")
                            if len(molecule_list) > 1:
                                print(f"📦 多组分分子: {', '.join(molecule_list)}")
                            else:
                                print(f"📦 分子名称: {molecule_list[0]}")
                            print("="*50)

            except Exception as e:
                logger.warning(f"无法生成示例: {e}")

        if input("\n确认这些设置正确吗？(y/n): ").lower() != 'y':
            logger.info("程序已终止")
            sys.exit(0)

        # 步骤3.5：加载缓存（如果启用）
        use_cache = _env_flag('RASPA_USE_CIF_CACHE', False)
        result_cache = None
        cache_file = os.environ.get('RASPA_CIF_CACHE_PATH') or os.path.join(topdir, "params_cache.json")
        
        if use_cache:
            result_cache = load_cache(cache_file)
            if result_cache:
                logger.info(f"启用 CIF 参数缓存 (已加载 {len(result_cache)} 条记录) | 路径: {cache_file}")
            else:
                logger.info(f"启用 CIF 参数缓存 (无现有缓存) | 路径: {cache_file}")

        # 步骤4：处理结构文件
        print(f"\n步骤4：处理结构文件 ({raspa_version.upper()})")
        successful_structures = 0
        from tqdm import tqdm

        # 获取 RASPA3 专用配置
        json_dir = raspa3_config.get('json_dir', '') if raspa_version == 'raspa3' else None

        quiet_mode = not _env_flag("RASPA_HT_VERBOSE", False)
        console_ctx = quiet_console(logging.WARNING) if quiet_mode else nullcontext()
        
        # 准备任务列表
        tasks = []
        for counter, framework_name in enumerate(framework_names, 1):
            if raspa_version == 'raspa3':
                kwargs = {
                    'topdir': topdir,
                    'subdir': subdir,
                    'counter': counter,
                    'framework_name': framework_name,
                    'cutoff': cutoff,
                    'void_csv_file': void_csv_file,
                    'void_fraction_column': void_fraction_column,
                    'template_path': template_path,
                    'molecule_name': molecule_name,
                    'cif_base_path': cif_dir,
                    'json_dir': json_dir,
                    'framework_column': framework_column,
                    'result_cache': result_cache if result_cache is not None else {}
                }
                tasks.append(('raspa3', kwargs))
            else:
                kwargs = {
                    'topdir': topdir,
                    'subdir': subdir,
                    'counter': counter,
                    'framework_name': framework_name,
                    'cutoff': cutoff,
                    'void_csv_file': void_csv_file,
                    'void_fraction_column': void_fraction_column,
                    'template_path': template_path,
                    'molecule_name': molecule_name,
                    'cif_dir': cif_dir,
                    'framework_column': framework_column,
                    'result_cache': result_cache if result_cache is not None else {}
                }
                tasks.append(('raspa2', kwargs))

        # 并行处理
        with console_ctx:
            # 确定并行 worker 数量
            try:
                cpu_count = multiprocessing.cpu_count()
            except Exception:
                cpu_count = 2
            # 限制最大 worker 数，避免过多进程竞争磁盘IO
            max_workers = min(32, cpu_count)
            logger.info(f"启用并行处理结构文件，使用 {max_workers} 个进程")

            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有任务
                futures = [executor.submit(_process_framework_wrapper, task) for task in tasks]
                
                # 使用 tqdm 显示进度
                with tqdm(total=len(tasks), desc="处理进度", unit="结构") as pbar:
                    for future in as_completed(futures):
                        try:
                            success, new_cache = future.result()
                            if success:
                                successful_structures += 1
                            
                            # 合并缓存更新
                            if result_cache is not None and new_cache:
                                result_cache.update(new_cache)
                        except Exception as e:
                            logger.error(f"任务执行异常: {e}")
                        
                        pbar.update(1)

        # 保存缓存
        if use_cache and result_cache is not None:
            save_cache(result_cache, cache_file)

        # 步骤5：检查处理结果
        print("\n步骤5：处理结果")
        if successful_structures == 0:
            logger.error("没有成功处理任何结构文件，无法继续计算")
            logger.error("请确保wei目录或cif目录中存在所需的结构文件")
            logger.error("计算被取消")
            sys.exit(1)

        # 更新配置文件
        actual_cores = min(cpu_cores, successful_structures) if successful_structures != total_tasks else cpu_cores
        logger.info(f"准备更新配置文件: topdir={topdir}, total_tasks={successful_structures}, subdir={subdir}, actual_cores={actual_cores}")
        if not update_all_files(topdir, successful_structures, subdir, actual_cores):
            logger.error("更新配置文件失败，程序终止")
            sys.exit(1)
        logger.info("配置文件更新完成")

        # 步骤6：最终总结
        print("\n步骤6：执行总结")
        logger.info("计算任务设置完成:")
        logger.info(f"- 原始结构数: {initial_total_tasks}")
        logger.info(f"- 成功处理: {successful_structures} 个结构")
        if skipped_missing_cifs:
            logger.info(f"- 缺失CIF跳过: {skipped_missing_cifs} 个结构")
        logger.info(f"- 失败处理: {total_tasks - successful_structures} 个结构")
        logger.info(f"- 实际使用CPU核心数: {actual_cores}")
        logger.info("所有配置文件已更新，开始提交计算任务...")

        # 步骤7：提交计算任务
        print("\n步骤7：提交计算任务")
        try:
            # 获取工具目录
            tool_dir = os.path.expanduser("~/raspa2-calc/.raspa_tools")
            tasksrun_script = os.path.join(tool_dir, "job_templates", "tasksrun.sh")

            if not os.path.exists(tasksrun_script):
                logger.error(f"找不到任务提交脚本: {tasksrun_script}")
                logger.info("请手动运行以下命令提交任务:")
                logger.info(f"bash {tasksrun_script} {actual_cores}")
                return

            # 设置环境变量供tasksrun.sh使用
            os.environ['RASPA_WORK_DIR'] = topdir
            
            # 确保CIF目录环境变量传递给子进程
            if 'RASPA_CIF_DIR' in os.environ:
                logger.info(f"传递CIF目录环境变量: {os.environ['RASPA_CIF_DIR']}")
            else:
                logger.warning("RASPA_CIF_DIR环境变量未设置")

            # 实时回显：正在提交第X个任务…
            env = os.environ.copy()
            print(f"将提交 {actual_cores} 个并行作业")
            # 直接调用 tasksrun.sh，它内部会循环提交 each job；我们解析其输出并实时提示
            with subprocess.Popen([tasksrun_script, str(actual_cores)],
                                  cwd=topdir,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT,
                                  text=True,
                                  bufsize=1,
                                  env=env) as proc:
                submit_verbose = _env_flag("RASPA_SUBMIT_VERBOSE", False)
                submit_every = _positive_int(os.environ.get("RASPA_SUBMIT_LOG_EVERY"), 10)
                submit_every = min(submit_every, max(1, actual_cores))
                if not submit_verbose and submit_every > 1:
                    print(f"提交中... 每 {submit_every} 个任务提示一次 (完整输出可设 RASPA_SUBMIT_VERBOSE=1)")

                submitted = 0
                for line in proc.stdout:
                    line_strip = line.strip()
                    if not line_strip:
                        continue
                    if submit_verbose:
                        print(line_strip)
                        continue

                    # 捕获“正在提交第N个任务/正在提交作业 N ...”格式，按间隔打印
                    idx = _parse_submit_index(line_strip)
                    if idx is not None:
                        submitted = max(submitted, idx)
                        if submitted == 1 or submitted == actual_cores or submitted % submit_every == 0:
                            print(f"正在提交第{submitted}个任务…")
                        continue

                    # 其他关键信息按需透传（避免刷屏）
                    if _should_print_submit_line(line_strip):
                        print(line_strip)
                ret = proc.wait()

            if ret == 0:
                logger.info(f"✅ 任务提交完成，共提交 {actual_cores} 个任务")
                print(f"总计提交 {actual_cores} 个任务")
            else:
                logger.error("任务提交失败")
                logger.info("请手动运行以下命令提交任务:")
                logger.info(f"bash {tasksrun_script} {actual_cores}")

        except Exception as e:
            logger.error(f"提交任务时出错: {e}")
            logger.info("请手动运行以下命令提交任务:")
            logger.info(f"bash {tasksrun_script} {actual_cores}")

    except KeyboardInterrupt:
        logger.info("\n用户取消操作，程序已终止")
        sys.exit(130)
    except Exception as e:
        logger.error(f"程序执行时出错: {e}")
        logger.debug(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
