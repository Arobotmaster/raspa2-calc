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

        job_templates_dir = os.path.join(topdir, "job_templates")
        os.makedirs(job_templates_dir, exist_ok=True)

        template_files = ["job_submit_ht.sh", "job_submit.sh", "tasksrun.sh", "pbs.sh", "sbatch.sh", "local.sh"]

        if raspa_version == "raspa3":
            template_files.append("runjobs_raspa3.sh")
        else:
            template_files.append("runjobs.sh")

        logger.info(f"准备复制 {len(template_files)} 个模板文件到 {job_templates_dir}")
        for file in template_files:
            src = os.path.join(tool_dir, "job_templates", file)
            dst = os.path.join(job_templates_dir, file)

            if file == "runjobs_raspa3.sh":
                dst = os.path.join(job_templates_dir, "runjobs.sh")
                logger.info(f"复制 {file} -> runjobs.sh (RASPA3模式)")
            else:
                logger.info(f"复制 {file}: {src} -> {dst}")

            if os.path.exists(src):
                shutil.copy2(src, dst)
                os.chmod(dst, 0o755)
                logger.info(f"已复制并设置权限: {os.path.basename(dst)}")
            else:
                logger.warning(f"Warning: Template file {file} not found in installation directory")

        logger.info("模板脚本已复制到工作目录，运行时将通过环境变量注入参数，无需额外重写。")

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
