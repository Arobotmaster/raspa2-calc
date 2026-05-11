import math
import os
import subprocess
from collections import OrderedDict

from raspa_calc.runtime import config as common_config
from .logging_utils import logger


def _normalize_node_list(value):
    nodes = []
    if isinstance(value, str):
        nodes = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple)):
        nodes = [str(item).strip() for item in value if str(item).strip()]
    return list(dict.fromkeys(nodes))


def parse_node_priorities(raw=None):
    """Parse node priorities from env string 'node:priority,...'."""
    text = raw if raw is not None else os.environ.get("RASPA_NODE_PRIORITIES", "")
    priorities = {}
    if not text:
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

        config, _ = common_config.load_config()
        if config:
            env = config.get("environment") or {}
            calc = config.get("calculation") or {}
            node_priorities = env.get("node_priorities") or calc.get("node_priorities") or {}
            if isinstance(node_priorities, dict):
                for key, val in node_priorities.items():
                    try:
                        priorities[str(key)] = int(val)
                    except Exception:
                        continue
        if not priorities:
            for path in common_config.resolve_config_paths():
                if not os.path.exists(path):
                    continue
                priorities = parse_simple(path) or {}
                if priorities:
                    break
        if not priorities:
            return priorities

    parts = [p for p in text.split(",") if p.strip()]
    for part in parts:
        if ":" not in part:
            continue
        name, value = part.split(":", 1)
        name = name.strip()
        try:
            prio = int(value.strip())
        except Exception:
            continue
        if name:
            priorities[name] = prio
    return priorities


def parse_allowed_nodes(raw=None):
    """Parse allowed nodes from env string or config."""
    text = raw if raw is not None else os.environ.get("RASPA_ALLOWED_NODES", "")
    allowed_nodes = _normalize_node_list(text)
    if allowed_nodes:
        return allowed_nodes

    config, _ = common_config.load_config()
    if config:
        env = config.get("environment") or {}
        calc = config.get("calculation") or {}
        allowed = (
            calc.get("allowed_nodes")
            or env.get("allowed_nodes")
            or calc.get("node_allowlist")
            or env.get("node_allowlist")
        )
        allowed_nodes = _normalize_node_list(allowed)
        if allowed_nodes:
            return allowed_nodes

    for path in common_config.resolve_config_paths():
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except Exception:
            continue

        inside = False
        indent = None
        inline_nodes = []
        list_nodes = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            cur_indent = len(line) - len(line.lstrip())
            if "allowed_nodes:" in line or "node_allowlist:" in line:
                inside = True
                indent = cur_indent
                inline_nodes = _normalize_node_list(line.split(":", 1)[1].strip())
                list_nodes = []
                if inline_nodes:
                    break
                continue
            if not inside:
                continue
            if indent is not None and cur_indent <= indent:
                break
            if stripped.startswith("- "):
                item = stripped[2:].strip()
                if item:
                    list_nodes.append(item)
            elif ":" in stripped:
                break
        allowed_nodes = _normalize_node_list(inline_nodes or list_nodes)
        if allowed_nodes:
            return allowed_nodes

    return []


def filter_cluster_info_by_allowed_nodes(cluster_info, allowed_nodes=None):
    """Return a whitelist-filtered cluster view for logging and planning."""
    if not cluster_info:
        return cluster_info

    allowed_nodes = _normalize_node_list(allowed_nodes if allowed_nodes is not None else parse_allowed_nodes())
    if not allowed_nodes:
        filtered = dict(cluster_info)
        filtered["allowed_nodes"] = []
        filtered["restricted_by_allowed_nodes"] = False
        return filtered

    nodes = cluster_info.get("nodes") or []
    allowed_set = set(allowed_nodes)
    filtered_nodes = [dict(node) for node in nodes if node.get("node") in allowed_set]

    filtered = dict(cluster_info)
    filtered["allowed_nodes"] = allowed_nodes
    filtered["restricted_by_allowed_nodes"] = True

    if not nodes:
        return filtered

    filtered["nodes"] = filtered_nodes
    filtered["total_cpus"] = int(sum(int(node.get("total_cpus", 0) or 0) for node in filtered_nodes))
    filtered["allocated_cpus"] = int(sum(int(node.get("allocated_cpus", 0) or 0) for node in filtered_nodes))
    filtered["other_cpus"] = int(sum(int(node.get("other_cpus", 0) or 0) for node in filtered_nodes))
    filtered["available_cpus"] = int(sum(int(node.get("free_cpus", 0) or 0) for node in filtered_nodes))
    return filtered


def _get_slurm_summary():
    """Fallback SLURM summary."""
    try:
        result = subprocess.run(["sinfo", "-h", "-o", "%C"], capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split("/")
            if len(parts) == 4:
                allocated = int(parts[0])
                idle = int(parts[1])
                other = int(parts[2])
                total = int(parts[3])
                return {
                    "total_cpus": total,
                    "allocated_cpus": allocated,
                    "other_cpus": other,
                    "available_cpus": idle,
                    "nodes": [],
                    "method": "sinfo_summary",
                    "available": True,
                }
        logger.warning(f"SLURM sinfo聚合命令执行失败或输出为空: {result.stderr}")
        return {"available": False}
    except subprocess.TimeoutExpired:
        logger.warning("SLURM聚合命令超时")
        return {"available": False}
    except FileNotFoundError:
        logger.warning("未找到SLURM命令，可能不在SLURM环境中")
        return {"available": False}
    except Exception as e:
        logger.warning(f"获取SLURM聚合资源信息时出错: {e}")
        return {"available": False}


def get_slurm_cluster_resources():
    """Get SLURM cluster CPU resources."""
    use_ssh_load = os.environ.get("RASPA_NODE_LOAD_SSH", "false").lower() in ("1", "true", "yes", "y", "on")
    free_policy_raw = os.environ.get("RASPA_SLURM_FREE_POLICY", "alloc_ht")
    free_policy = (free_policy_raw or "alloc").strip().lower()
    if free_policy in ("min", "load+alloc", "load_alloc"):
        free_policy = "min"
    elif free_policy in ("load", "load_only", "load-only"):
        free_policy = "load"
    elif free_policy in ("alloc_ht", "auto", "auto_ht", "alloc-ht"):
        free_policy = "alloc_ht"
    else:
        free_policy = "alloc"

    def _load_from_ssh(node: str):
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

    format_spec = "%N|%c|%C|%O|%z"
    try:
        result = subprocess.run(["sinfo", "-N", "-h", "-o", format_spec], capture_output=True, text=True, timeout=30)
        if result.returncode != 0 or not result.stdout.strip():
            logger.warning(f"SLURM节点级命令执行失败或输出为空: {result.stderr}")
            return _get_slurm_summary()

        total_cpus = allocated_cpus = other_cpus = 0
        total_free_cpus = 0
        nodes = []
        seen_nodes = set()

        for line in result.stdout.strip().splitlines():
            parts = line.strip().split("|")
            if len(parts) < 4:
                continue

            node_name = parts[0]
            # sinfo 在部分环境会为同一节点输出多行（例如多分区），避免重复计入
            if node_name in seen_nodes:
                continue
            seen_nodes.add(node_name)
            try:
                node_total = int(parts[1])
            except ValueError:
                continue

            summary = parts[2]
            summary_parts = summary.split("/")
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
            if load_str and load_str.lower() not in ("unknown", "(null)", "n/a", "-"):
                try:
                    load_value = float(str(load_str).rstrip("*"))
                except ValueError:
                    load_value = None
            load_from_ssh = _load_from_ssh(node_name)
            if load_from_ssh is not None:
                load_value = load_from_ssh

            topology = parts[4] if len(parts) > 4 else ""
            sockets = cores_per_socket = threads_per_core = None
            physical_cpus = None
            if topology:
                topo_parts = topology.split(":")
                if len(topo_parts) == 3:
                    try:
                        sockets = int(topo_parts[0])
                        cores_per_socket = int(topo_parts[1])
                        threads_per_core = int(topo_parts[2])
                        if threads_per_core > 0:
                            physical_cpus = node_total // threads_per_core
                    except ValueError:
                        threads_per_core = None

            load_effective = int(math.ceil(load_value)) if load_value is not None else 0

            free_by_alloc = max(0, node_total - node_alloc - node_other)
            free_by_load = max(0, node_total - load_effective)
            use_load = free_policy in ("load", "min")
            if free_policy == "alloc_ht" and threads_per_core and threads_per_core > 1:
                use_load = True
            if load_value is None:
                use_load = False

            if free_policy == "load" and use_load:
                node_free = free_by_load
            elif free_policy in ("min", "alloc_ht") and use_load:
                node_free = min(free_by_alloc, free_by_load)
            else:
                node_free = free_by_alloc

            nodes.append(
                {
                    "node": node_name,
                    "total_cpus": node_total,
                    "allocated_cpus": node_alloc,
                    "other_cpus": node_other,
                    "load": load_value,
                    "topology": topology,
                    "sockets": sockets,
                    "cores_per_socket": cores_per_socket,
                    "threads_per_core": threads_per_core,
                    "physical_cpus": physical_cpus,
                    "free_cpus": node_free,
                    "usable_cpus": node_total,
                }
            )

            total_cpus += node_total
            allocated_cpus += node_alloc
            other_cpus += node_other
            total_free_cpus += node_free

        if not nodes:
            logger.warning("未能解析到任何节点资源信息，回退到聚合统计")
            return _get_slurm_summary()

        return {
            "total_cpus": total_cpus,
            "allocated_cpus": allocated_cpus,
            "other_cpus": other_cpus,
            "available_cpus": int(total_free_cpus),
            "nodes": nodes,
            "method": "sinfo_per_node",
            "available": True,
        }

    except subprocess.TimeoutExpired:
        logger.warning("SLURM节点级命令超时")
        return _get_slurm_summary()
    except FileNotFoundError:
        logger.warning("未找到SLURM命令，可能不在SLURM环境中")
        return {"available": False}
    except Exception as e:
        logger.warning(f"获取SLURM节点资源信息时出错: {e}")
        return _get_slurm_summary()


def build_node_plan(cluster_info, cpu_cores):
    """Build node allocation plan based on cluster info."""
    if not cluster_info or not cluster_info.get("available"):
        return "", []

    nodes = cluster_info.get("nodes") or []
    if not nodes or cpu_cores <= 0:
        return "", []

    priority_map = parse_node_priorities()
    allowed_nodes = parse_allowed_nodes()
    if priority_map:
        ordered_items = ", ".join(f"{name}:{prio}" for name, prio in sorted(priority_map.items(), key=lambda x: -x[1]))
        logger.info(f"应用节点优先级: {ordered_items}")
    if allowed_nodes:
        logger.info(f"限制可用节点: {', '.join(allowed_nodes)}")
        allowed_set = set(allowed_nodes)
        nodes = [node for node in nodes if node.get("node") in allowed_set]
        if not nodes:
            logger.warning("限定节点列表内没有可用节点，节点分配计划为空")
            return "", []

    def node_priority(node):
        return priority_map.get(node.get("node"), 0)

    def sort_group(group):
        return sorted(
            group,
            key=lambda n: (
                -node_priority(n),
                -(n.get("free_cpus", 0) or 0),
                n.get("load") if n.get("load") is not None else 0,
            ),
        )

    free_policy_raw = os.environ.get("RASPA_SLURM_FREE_POLICY", "alloc_ht")
    free_policy = (free_policy_raw or "alloc").strip().lower()
    if free_policy in ("min", "load+alloc", "load_alloc"):
        free_policy = "min"
    elif free_policy in ("load", "load_only", "load-only"):
        free_policy = "load"
    elif free_policy in ("alloc_ht", "auto", "auto_ht", "alloc-ht"):
        free_policy = "alloc_ht"
    else:
        free_policy = "alloc"

    for n in nodes:
        total = int(n.get("total_cpus", 0) or 0)
        free = max(0, int(n.get("free_cpus", 0) or 0))
        alloc = max(0, int(n.get("allocated_cpus", 0) or 0))
        load_val_raw = n.get("load")
        try:
            load_val = float(str(load_val_raw).rstrip("*"))
        except Exception:
            load_val = None
        tpc = n.get("threads_per_core") or 1
        use_load = free_policy in ("load", "min")
        if free_policy == "alloc_ht" and tpc and int(tpc) > 1:
            use_load = True
        if load_val is None:
            use_load = False
        if not use_load:
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
        n["_effective_free"] = effective
        n["_load_ratio"] = load_ratio
        n["_total_cpus"] = total

    ordered_nodes = sorted(
        nodes,
        key=lambda n: (
            -node_priority(n),
            -(n.get("_effective_free", 0) or 0),
            -(n.get("free_cpus", 0) or 0),
            n.get("load") if n.get("load") is not None else 0,
        ),
    )
    plan_counts = OrderedDict()
    assigned_by_node = {}
    remaining = cpu_cores

    # 第一轮：按有效容量（更保守）分配
    for node in ordered_nodes:
        if remaining <= 0:
            break
        node_name = node["node"]
        cap = max(0, int(node.get("_effective_free", 0) or 0))
        if cap == 0:
            continue
        take = min(cap, remaining)
        if take > 0:
            assigned_by_node[node_name] = assigned_by_node.get(node_name, 0) + take
            plan_counts[node_name] = assigned_by_node[node_name]
        remaining -= take

    # 第二轮：若仍有剩余，按更宽松容量补分配，但必须扣除第一轮已分配
    if remaining > 0:
        for node in ordered_nodes:
            if remaining <= 0:
                break
            node_name = node["node"]
            cap = int(node.get("free_cpus", 0) or 0)
            total = int(node.get("_total_cpus", 0) or 0)
            load_ratio = float(node.get("_load_ratio", 0.0) or 0.0)
            alloc_ratio = float(node.get("allocated_cpus", 0) or 0.0) / float(total) if total > 0 else 0.0
            if load_ratio >= 0.85 or alloc_ratio >= 0.95:
                cap = 0
            elif load_ratio >= 0.70 or alloc_ratio >= 0.85:
                cap = int(cap * 0.5)
            cap = max(0, cap)
            already = assigned_by_node.get(node_name, 0)
            residual_cap = max(0, cap - already)
            take = min(residual_cap, remaining)
            if take <= 0:
                continue
            assigned_by_node[node_name] = already + take
            plan_counts[node_name] = assigned_by_node[node_name]
            remaining -= take

    plan_pairs = [(node, count) for node, count in plan_counts.items() if count > 0]
    plan_string = ",".join(f"{node}:{count}" for node, count in plan_pairs)
    return plan_string, plan_pairs
