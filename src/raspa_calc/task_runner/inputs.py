import multiprocessing
import os
import sys

import pandas as pd

from .csv_utils import read_csv_with_fallbacks
from .logging_utils import logger
from .scheduler import build_node_plan, get_slurm_cluster_resources
from . import state


def get_directory_setup():
    """Get output directory setup."""
    logger.info("=== 步骤1：设置输出目录 ===")

    output_dir_env = os.environ.get("RASPA_OUTPUT_DIR")
    if output_dir_env:
        logger.info(f"从配置文件读取输出目录: {output_dir_env}")
        return output_dir_env

    while True:
        try:
            subdir = input("请输入用于存放输出文件的目录名 (e.g., '302'): ").strip()
            if subdir:
                if not all(c.isalnum() or c in "-_" for c in subdir):
                    logger.warning("目录名包含非法字符，请使用字母、数字、下划线或连字符")
                    continue

                if os.path.exists(subdir):
                    overwrite = input(f"目录 '{subdir}' 已存在。覆盖? (y/n): ").strip().lower()
                    if overwrite != "y":
                        continue

                return subdir
            logger.warning("目录名不能为空，请重新输入")
        except KeyboardInterrupt:
            logger.info("用户取消操作")
            sys.exit(130)
        except Exception as e:
            logger.error(f"获取目录名时出错: {str(e)}")


def get_framework_data():
    """Get CSV data for frameworks."""
    logger.info("=== 步骤2：选择框架结构 ===")

    csv_path_env = os.environ.get("RASPA_CSV_FILE")
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

    if not os.path.exists(csv_path):
        logger.error(f"CSV文件不存在: {csv_path}")
        return None, None

    try:
        df = read_csv_with_fallbacks(csv_path)
    except Exception as e:
        logger.error(f"无法读取CSV文件: {str(e)}")
        return None, None

    df = df.dropna(subset=[df.columns[0]])
    columns = df.columns.tolist()

    logger.info("可用的列名:")
    for i, col in enumerate(columns):
        print(f"{i+1}. {col}")

    framework_column_env = os.environ.get("RASPA_FRAMEWORK_COLUMN")
    if framework_column_env:
        if framework_column_env in columns:
            framework_column = framework_column_env
            logger.info(f"从配置文件读取框架列名: {framework_column}")
        else:
            logger.warning(f"配置文件中的框架列名 '{framework_column_env}' 不存在，使用默认列")
            framework_column = columns[0]
    else:
        while True:
            try:
                choice = input("\n请选择包含框架名称的列名 (输入序号或列名): ")
                if choice.isdigit() and 1 <= int(choice) <= len(columns):
                    framework_column = columns[int(choice) - 1]
                    break
                if choice in columns:
                    framework_column = choice
                    break
                logger.warning("无效的选择，请重新输入")
            except KeyboardInterrupt:
                logger.info("用户取消操作")
                sys.exit(130)

    logger.info(f"已选择列名: {framework_column}")

    framework_names = df[framework_column].dropna().tolist()
    framework_names = [name for name in framework_names if str(name).strip()]
    total_structures = len(framework_names)

    if total_structures == 0:
        logger.warning("没有找到有效的框架结构，请检查CSV文件")
        return None, None

    logger.info(f"从CSV文件中读取到总共 {total_structures} 个有效框架结构")

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
            sys.exit(130)

    return framework_names, x


def _write_node_plan(plan_path, plan_string):
    try:
        with open(plan_path, "w", encoding="utf-8") as pf:
            pf.write(plan_string + "\n")
        logger.info(f"节点分配计划已写入: {plan_path}")
    except Exception as exc:
        logger.warning(f"写入节点分配计划失败: {exc}")


def _clear_node_plan(plan_path):
    if plan_path and os.path.exists(plan_path):
        try:
            os.remove(plan_path)
            logger.info(f"已清理旧的节点分配计划: {plan_path}")
        except Exception as exc:
            logger.warning(f"删除节点分配计划失败: {exc}")


def _apply_node_plan(cluster_info, cpu_cores, plan_path=None):
    if cluster_info.get("available"):
        plan_string, plan_pairs = build_node_plan(cluster_info, cpu_cores)
        if plan_string:
            os.environ["RASPA_NODE_PLAN"] = plan_string
            logger.info(f"节点分配计划: {plan_string}")
            if plan_pairs:
                summary = ", ".join(f"{n}:{c}" for n, c in plan_pairs)
                logger.info(f"节点任务分配总览: {summary}")
            if plan_path:
                _write_node_plan(plan_path, plan_string)
        else:
            os.environ.pop("RASPA_NODE_PLAN", None)
            _clear_node_plan(plan_path)
    else:
        os.environ.pop("RASPA_NODE_PLAN", None)
        _clear_node_plan(plan_path)


def get_cpu_cores_with_plan(total_tasks, cluster_info=None, plan_path=None):
    """Prompt for CPU cores and configure node plan."""
    if total_tasks <= 0:
        return 0

    system_cores = multiprocessing.cpu_count()
    logger.info(f"当前节点CPU核心数: {system_cores}")

    if cluster_info is None:
        cluster_info = get_slurm_cluster_resources()

    if cluster_info.get("available"):
        logger.info(f"SLURM集群总 CPU核心数: {cluster_info.get('total_cpus')}")
        logger.info(f"SLURM集群已分配 CPU核心数: {cluster_info.get('allocated_cpus')}")
        logger.info(f"SLURM集群当前可用 CPU核心数: {cluster_info.get('available_cpus')}")

        if cluster_info.get("nodes"):
            logger.info("节点资源详情（线程总数/负载/建议可用线程）：")
            for node in cluster_info["nodes"]:
                load_txt = f"{node['load']:.2f}" if node.get("load") is not None else "未知"
                topo_txt = node.get("topology") or "?"
                free_cpus = node.get("free_cpus", 0)
                physical = node.get("physical_cpus")
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

        recommended_cores = min(int(cluster_info.get("available_cpus") or 0), total_tasks)
        if recommended_cores > 0:
            logger.info(f"建议使用CPU核心数: {recommended_cores} (基于集群空闲资源)")
        else:
            logger.info("集群当前无空闲CPU资源，请谨慎选择使用数量")
    else:
        logger.info("未检测到SLURM集群环境，使用当前节点信息")

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
            sys.exit(130)

    _apply_node_plan(cluster_info, cpu_cores, plan_path)
    return cpu_cores


def get_computation_setup(total_tasks, cif_dir=None):
    """Get computation settings."""
    logger.info("=== 步骤3：设置计算参数 ===")

    cluster_info = get_slurm_cluster_resources()
    globals()["LAST_CLUSTER_INFO"] = cluster_info
    plan_path = None
    if state.CURRENT_TOPDIR and state.CURRENT_SUBDIR:
        plan_path = os.path.join(state.CURRENT_TOPDIR, state.CURRENT_SUBDIR, ".raspa_node_plan")
    cpu_cores = get_cpu_cores_with_plan(
        total_tasks,
        cluster_info=cluster_info,
        plan_path=plan_path,
    )

    while True:
        try:
            cutoff_env = os.environ.get("RASPA_CUTOFF_RADIUS")
            if cutoff_env:
                cutoff = float(cutoff_env)
                logger.info(f"从配置文件读取截断半径: {cutoff}")
            else:
                cutoff = float(input("请输入截断半径 (e.g., '12'): "))

            if cutoff <= 0:
                logger.warning("截断半径必须大于0")
                continue
            if cutoff > 100:
                if cutoff_env:
                    logger.warning(f"警告: 截断半径 {cutoff} 非常大")
                else:
                    confirm = input("警告: 截断半径非常大，确认使用此值? (y/n): ").strip().lower()
                    if confirm != "y":
                        continue
            break
        except ValueError:
            logger.warning("请输入有效的数字")
        except KeyboardInterrupt:
            logger.info("用户取消操作")
            sys.exit(130)

    cif_dir = cif_dir

    molecules_env = os.environ.get("RASPA_DEFAULT_MOLECULES")
    if molecules_env:
        molecule_name = molecules_env
        logger.info(f"从配置文件读取分子: {molecule_name}")
    else:
        molecule_name = input("请输入分子名称 (默认为'I2', 支持多种分子用空格分隔): ").strip()
        if not molecule_name:
            molecule_name = "I2"

    logger.info(f"将使用分子: {molecule_name}")

    molecule_list = molecule_name.split()
    if len(molecule_list) > 1:
        logger.info(f"检测到多种气体分子: {', '.join(molecule_list)}")

    template_path_env = os.environ.get("RASPA_TEMPLATE_PATH")
    template_path = None
    if template_path_env:
        if os.path.exists(template_path_env):
            template_path = template_path_env
            logger.info(f"从配置文件读取模板路径: {template_path}")
        else:
            logger.warning(f"配置文件中的模板文件不存在: {template_path_env}")

    if template_path is None and raspa_version == "raspa2":
        user_input = input("请输入simulation.input模板文件路径 (留空使用默认模板): ").strip()
        if user_input:
            if os.path.exists(user_input):
                template_path = user_input
                logger.info(f"将使用自定义模板: {template_path}")
            else:
                logger.warning(f"模板文件不存在，继续使用默认模板: {user_input}")

    use_void_csv_env = os.environ.get("RASPA_USE_VOID_CSV")
    void_csv_file_env = os.environ.get("RASPA_VOID_CSV_FILE")
    void_column_env = os.environ.get("RASPA_VOID_COLUMN")

    if use_void_csv_env:
        use_void_csv = use_void_csv_env.lower() == "true"
        logger.info(f"从配置文件读取孔隙率设置: {'使用' if use_void_csv else '不使用'}CSV文件")
    else:
        use_void_csv = input("是否使用CSV文件获取孔隙率? (y/n): ").strip().lower() == "y"

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

        try:
            df = read_csv_with_fallbacks(void_csv_file)
            columns = df.columns.tolist()

            logger.info("可用的列名:")
            for i, col in enumerate(columns):
                print(f"{i+1}. {col}")

            if void_column_env:
                if void_column_env in columns:
                    void_fraction_column = void_column_env
                    logger.info(f"从配置文件读取孔隙率列名: {void_fraction_column}")
                else:
                    logger.warning(f"配置文件中的孔隙率列名 '{void_column_env}' 不存在，使用默认列")
                    void_fraction_column = columns[0]
            else:
                while True:
                    try:
                        choice = input("\n请选择包含孔隙率的列名 (输入序号或列名): ")
                        if choice.isdigit() and 1 <= int(choice) <= len(columns):
                            void_fraction_column = columns[int(choice) - 1]
                            break
                        if choice in columns:
                            void_fraction_column = choice
                            break
                        logger.warning("无效的选择，请重新输入")
                    except KeyboardInterrupt:
                        logger.info("用户取消操作")
                        sys.exit(130)

            logger.info(f"已选择孔隙率列: {void_fraction_column}")

        except Exception as e:
            logger.error(f"读取CSV文件时出错: {e}")
            void_csv_file = None
            void_fraction_column = None

    return cpu_cores, cutoff, void_csv_file, void_fraction_column, template_path, molecule_name, cif_dir
