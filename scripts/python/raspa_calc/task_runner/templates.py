import os
import shutil

from .env import get_raspa_version_from_env
from .logging_utils import logger


def update_all_files(topdir, total_tasks, subdir, cpu_cores):
    """Update template scripts and reset queue pointers."""
    try:
        raspa_version = get_raspa_version_from_env()

        tool_dir = os.path.join(os.environ.get("HOME", ""), "raspa2-calc/.raspa_tools")
        logger.info(f"工具目录: {tool_dir}")
        logger.info(f"工作目录: {topdir}")
        logger.info(f"RASPA 版本: {raspa_version.upper()}")

        logger.info("模板脚本将直接从工具目录使用，不再复制到工作目录。")

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
