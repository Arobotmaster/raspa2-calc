import logging
import os
import subprocess
import traceback


logger = logging.getLogger("parameter_screening")


def create_job_script_raspa3(param_dir, job_name, scheduler_type="slurm", conda_env="raspa3", mser_config=None):
    """创建 RASPA3 作业提交脚本

    Args:
        param_dir: 参数目录
        job_name: 作业名称
        scheduler_type: 调度系统类型 ('slurm', 'pbs', 或 'local')
        conda_env: RASPA3 conda 环境名称
        mser_config: pyMSER 配置

    Returns:
        str: 脚本文件路径
    """
    script_path = os.path.join(param_dir, "job.sh")

    mser_settings = mser_config or {}
    mser_enable = bool(mser_settings.get('enable', False))
    mser_target_cycles = int(mser_settings.get('target_cycles', 1000)) if mser_enable else None
    mser_add_cycles = int(mser_settings.get('add_cycles', 500)) if mser_enable else None
    mser_max_iter = int(mser_settings.get('max_iter', 20)) if mser_enable else None
    mser_uncertainty = mser_settings.get('uncertainty', 'uSD') if mser_enable else 'uSD'
    mser_conda_env = mser_settings.get('conda_env', 'pymser') if mser_enable else 'pymser'

    status_file = "status.txt"
    orig_dir = param_dir

    mser_env_block = ""
    mser_run_block = ""
    if mser_enable:
        mser_env_block = f"""
# pyMSER 设置
MSER_MODULE="raspa_calc.domain.algorithms.auto_mser_raspa3"
MSER_PYTHONPATH="${{RASPA_TOOL_DIR:-$HOME/raspa2-calc/.raspa_tools}}/src"
export PYTHONPATH="${{MSER_PYTHONPATH}}${{PYTHONPATH:+:$PYTHONPATH}}"
export RASPA_MSER_ENABLE=true
export RASPA_MSER_TARGET_CYCLES={mser_target_cycles}
export RASPA_MSER_ADD_CYCLES={mser_add_cycles}
export RASPA_MSER_MAX_ITER={mser_max_iter}
export RASPA_MSER_UNCERTAINTY={mser_uncertainty}
export RASPA_MSER_CONDA_ENV={mser_conda_env}
export RASPA3_CONDA_ENV={conda_env}
"""

        mser_run_block = f"""
if [ $raspa3_exit_code -eq 0 ] && [ -d "output" ]; then
    output_count=$(find output -maxdepth 1 -type f \\( -name "output_*.txt" -o -name "output_*.json" \\) 2>/dev/null | wc -l)
else
    output_count=0
fi
if [ $output_count -gt 0 ] && [ -d "$MSER_PYTHONPATH/raspa_calc/domain/algorithms" ]; then
    echo " ==> 运行 pyMSER 自动平衡"
    if command -v conda >/dev/null 2>&1; then
        conda run -n "{mser_conda_env}" python -m "$MSER_MODULE" \\
          --workdir "$(pwd)" \\
          --target-cycles "{mser_target_cycles}" \\
          --add-cycles "{mser_add_cycles}" \\
          --max-iter "{mser_max_iter}" \\
          --uncertainty "{mser_uncertainty}" \\
          --conda-env "{mser_conda_env}" \\
          --raspa3-conda-env "{conda_env}"
    else
        python -m "$MSER_MODULE" \\
          --workdir "$(pwd)" \\
          --target-cycles "{mser_target_cycles}" \\
          --add-cycles "{mser_add_cycles}" \\
          --max-iter "{mser_max_iter}" \\
          --uncertainty "{mser_uncertainty}" \\
          --conda-env "{mser_conda_env}" \\
          --raspa3-conda-env "{conda_env}"
    fi
    mser_status=$?
fi
"""

    # conda 初始化脚本
    conda_init = '''
# 初始化 conda
if [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/anaconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
fi
'''

    if scheduler_type == "slurm":
        script_content = f'''#!/bin/bash
#SBATCH --job-name={job_name}
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=1
#SBATCH --hint=multithread
#SBATCH --output=%x.%j.out
#SBATCH --error=%x.%j.err

# 设置资源限制
ulimit -u 20480
ulimit -s 16384

# 设置环境变量
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
MSER_ENABLED={"1" if mser_enable else "0"}
{mser_env_block}
{conda_init}
# 激活 RASPA3 环境
conda activate {conda_env}

ORIG_DIR="{orig_dir}"
PARENT_DIR="$(dirname "$ORIG_DIR")"
BASE_DIR="$(basename "$ORIG_DIR")"
RUN_DIR="$ORIG_DIR"
if [ -d "${{ORIG_DIR}}__running" ]; then RUN_DIR="${{ORIG_DIR}}__running"; fi
if [ -d "${{ORIG_DIR}}__done" ]; then RUN_DIR="${{ORIG_DIR}}__done"; fi
if [ -d "${{ORIG_DIR}}__failed" ]; then RUN_DIR="${{ORIG_DIR}}__failed"; fi
if [ "$RUN_DIR" = "$ORIG_DIR" ] && [ -d "$ORIG_DIR" ]; then
  (cd "$PARENT_DIR" && mv "$BASE_DIR" "${{BASE_DIR}}__running") && RUN_DIR="${{ORIG_DIR}}__running"
fi
cd "$RUN_DIR" || exit 1

echo "running" > "{status_file}"
echo $SLURM_JOB_ID > jobid

# 运行 RASPA3
raspa3_exit_code=0
mser_status=0
raspa3
raspa3_exit_code=$?
{mser_run_block}
if [ $raspa3_exit_code -ne 0 ]; then
    echo "failed_simulate" > "{status_file}"
    mv "$RUN_DIR" "${{ORIG_DIR}}__failed" 2>/dev/null || true
elif [ $MSER_ENABLED -eq 1 ] && [ $mser_status -ne 0 ]; then
    echo "failed_mser" > "{status_file}"
    mv "$RUN_DIR" "${{ORIG_DIR}}__failed" 2>/dev/null || true
else
    echo "done" > "{status_file}"
    mv "$RUN_DIR" "${{ORIG_DIR}}__done" 2>/dev/null || true
fi
'''
    elif scheduler_type == "pbs":
        script_content = f'''#!/bin/bash
#PBS -N {job_name}
#PBS -l nodes=1:ppn=1
#PBS -o pbs.out
#PBS -e pbs.err
#PBS -j oe

# 设置资源限制
ulimit -u 20480
ulimit -s 16384

# 设置环境变量
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
MSER_ENABLED={"1" if mser_enable else "0"}
{mser_env_block}
{conda_init}
# 激活 RASPA3 环境
conda activate {conda_env}

# 切换到作业目录
cd $PBS_O_WORKDIR

ORIG_DIR="{orig_dir}"
PARENT_DIR="$(dirname "$ORIG_DIR")"
BASE_DIR="$(basename "$ORIG_DIR")"
RUN_DIR="$ORIG_DIR"
if [ -d "${{ORIG_DIR}}__running" ]; then RUN_DIR="${{ORIG_DIR}}__running"; fi
if [ -d "${{ORIG_DIR}}__done" ]; then RUN_DIR="${{ORIG_DIR}}__done"; fi
if [ -d "${{ORIG_DIR}}__failed" ]; then RUN_DIR="${{ORIG_DIR}}__failed"; fi
if [ "$RUN_DIR" = "$ORIG_DIR" ] && [ -d "$ORIG_DIR" ]; then
  (cd "$PARENT_DIR" && mv "$BASE_DIR" "${{BASE_DIR}}__running") && RUN_DIR="${{ORIG_DIR}}__running"
fi
cd "$RUN_DIR" || exit 1

echo $PBS_JOBID > jobid
echo "running" > "{status_file}"

# 运行 RASPA3
raspa3_exit_code=0
mser_status=0
raspa3
raspa3_exit_code=$?
{mser_run_block}
if [ $raspa3_exit_code -ne 0 ]; then
    echo "failed_simulate" > "{status_file}"
    mv "$RUN_DIR" "${{ORIG_DIR}}__failed" 2>/dev/null || true
elif [ $MSER_ENABLED -eq 1 ] && [ $mser_status -ne 0 ]; then
    echo "failed_mser" > "{status_file}"
    mv "$RUN_DIR" "${{ORIG_DIR}}__failed" 2>/dev/null || true
else
    echo "done" > "{status_file}"
    mv "$RUN_DIR" "${{ORIG_DIR}}__done" 2>/dev/null || true
fi
'''
    else:
        script_content = f'''#!/bin/bash

# 设置环境变量
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
MSER_ENABLED={"1" if mser_enable else "0"}
{mser_env_block}
{conda_init}
# 激活 RASPA3 环境
conda activate {conda_env}

# 切换到作业目录
ORIG_DIR="{orig_dir}"
PARENT_DIR="$(dirname "$ORIG_DIR")"
BASE_DIR="$(basename "$ORIG_DIR")"
RUN_DIR="$ORIG_DIR"
if [ -d "${{ORIG_DIR}}__running" ]; then RUN_DIR="${{ORIG_DIR}}__running"; fi
if [ -d "${{ORIG_DIR}}__done" ]; then RUN_DIR="${{ORIG_DIR}}__done"; fi
if [ -d "${{ORIG_DIR}}__failed" ]; then RUN_DIR="${{ORIG_DIR}}__failed"; fi
if [ "$RUN_DIR" = "$ORIG_DIR" ] && [ -d "$ORIG_DIR" ]; then
  (cd "$PARENT_DIR" && mv "$BASE_DIR" "${{BASE_DIR}}__running") && RUN_DIR="${{ORIG_DIR}}__running"
fi
cd "$RUN_DIR" || exit 1

echo $$ > jobid
echo "running" > "{status_file}"

# 运行 RASPA3
raspa3_exit_code=0
mser_status=0
raspa3
raspa3_exit_code=$?
{mser_run_block}
if [ $raspa3_exit_code -ne 0 ]; then
    echo "failed_simulate" > "{status_file}"
    mv "$RUN_DIR" "${{ORIG_DIR}}__failed" 2>/dev/null || true
elif [ $MSER_ENABLED -eq 1 ] && [ $mser_status -ne 0 ]; then
    echo "failed_mser" > "{status_file}"
    mv "$RUN_DIR" "${{ORIG_DIR}}__failed" 2>/dev/null || true
else
    echo "done" > "{status_file}"
    mv "$RUN_DIR" "${{ORIG_DIR}}__done" 2>/dev/null || true
fi
'''

    with open(script_path, "w") as f:
        f.write(script_content)

    os.chmod(script_path, 0o755)
    logger.info(f"创建 RASPA3 作业脚本: {script_path}")

    return script_path


def create_job_script(param_dir, job_name, scheduler_type="pbs", mser_config=None):
    """创建作业提交脚本

    Args:
        param_dir: 参数目录
        job_name: 作业名称
        scheduler_type: 调度系统类型 ('slurm', 'pbs', 或 'local')
        mser_config: pyMSER 配置

    Returns:
        str: 脚本文件路径
    """
    # 创建脚本文件路径
    script_path = os.path.join(param_dir, "job.sh")

    # 获取RASPA目录
    raspa_dir = os.environ.get('RASPA_DIR', '')
    raspa_cmd = os.path.join(raspa_dir, "bin", "simulate")

    mser_settings = mser_config or {}
    mser_enable = bool(mser_settings.get('enable', False))
    mser_target_cycles = int(mser_settings.get('target_cycles', 1000)) if mser_enable else None
    mser_add_cycles = int(mser_settings.get('add_cycles', 500)) if mser_enable else None
    mser_max_iter = int(mser_settings.get('max_iter', 20)) if mser_enable else None
    mser_uncertainty = mser_settings.get('uncertainty', 'uSD') if mser_enable else 'uSD'
    mser_conda_env = mser_settings.get('conda_env', 'pymser') if mser_enable else 'pymser'

    status_file = "status.txt"
    orig_dir = param_dir

    mser_env_block = ""
    mser_run_block = ""
    if mser_enable:
        mser_env_block = f"""
# pyMSER 设置
MSER_MODULE="raspa_calc.domain.algorithms.auto_mser_raspa2"
MSER_PYTHONPATH="${{RASPA_TOOL_DIR:-$HOME/raspa2-calc/.raspa_tools}}/src"
export PYTHONPATH="${{MSER_PYTHONPATH}}${{PYTHONPATH:+:$PYTHONPATH}}"
export RASPA_MSER_ENABLE=true
export RASPA_MSER_TARGET_CYCLES={mser_target_cycles}
export RASPA_MSER_ADD_CYCLES={mser_add_cycles}
export RASPA_MSER_MAX_ITER={mser_max_iter}
export RASPA_MSER_UNCERTAINTY={mser_uncertainty}
export RASPA_MSER_CONDA_ENV={mser_conda_env}
"""
        mser_run_block = f"""
if [ $sim_exit_code -eq 0 ] && [ -d "$MSER_PYTHONPATH/raspa_calc/domain/algorithms" ]; then
  echo " ==> 运行 pyMSER 自动平衡"
  mser_status=0
  if command -v conda >/dev/null 2>&1; then
    conda run -n "{mser_conda_env}" python -m "$MSER_MODULE" \\
      --workdir "$(pwd)" \\
      --target-cycles "{mser_target_cycles}" \\
      --add-cycles "{mser_add_cycles}" \\
      --max-iter "{mser_max_iter}" \\
      --uncertainty "{mser_uncertainty}" \\
      --conda-env "{mser_conda_env}"
  else
    python -m "$MSER_MODULE" \\
      --workdir "$(pwd)" \\
      --target-cycles "{mser_target_cycles}" \\
      --add-cycles "{mser_add_cycles}" \\
      --max-iter "{mser_max_iter}" \\
      --uncertainty "{mser_uncertainty}" \\
      --conda-env "{mser_conda_env}"
  fi
  mser_status=$?
fi
"""

    # 根据调度系统类型生成不同的脚本内容
    if scheduler_type == "slurm":
        # SLURM脚本
        script_content = f"""#!/bin/bash
#SBATCH --job-name={job_name}
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=1
#SBATCH --hint=multithread
#SBATCH --output=%x.%j.out
#SBATCH --error=%x.%j.err

# 设置资源限制和线程数
ulimit -u 20480
ulimit -s 16384

# 设置环境变量，防止数学库线程冲突
export OPENBLAS_NUM_THREADS=1 
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
MSER_ENABLED={"1" if mser_enable else "0"}
{mser_env_block}

# 设置工作目录并重命名状态
ORIG_DIR="{orig_dir}"
PARENT_DIR="$(dirname "$ORIG_DIR")"
BASE_DIR="$(basename "$ORIG_DIR")"
RUN_DIR="$ORIG_DIR"
if [ -d "${{ORIG_DIR}}__running" ]; then RUN_DIR="${{ORIG_DIR}}__running"; fi
if [ -d "${{ORIG_DIR}}__done" ]; then RUN_DIR="${{ORIG_DIR}}__done"; fi
if [ -d "${{ORIG_DIR}}__failed" ]; then RUN_DIR="${{ORIG_DIR}}__failed"; fi
if [ "$RUN_DIR" = "$ORIG_DIR" ] && [ -d "$ORIG_DIR" ]; then
  (cd "$PARENT_DIR" && mv "$BASE_DIR" "${{BASE_DIR}}__running") && RUN_DIR="${{ORIG_DIR}}__running"
fi
cd "$RUN_DIR" || exit 1

echo "running" > "{status_file}"
echo $SLURM_JOB_ID > jobid

# 运行RASPA
sim_exit_code=0
mser_status=0
{raspa_cmd}
sim_exit_code=$?
{mser_run_block}
if [ $sim_exit_code -ne 0 ]; then
  echo "failed_simulate" > "{status_file}"
  mv "$RUN_DIR" "${{ORIG_DIR}}__failed" 2>/dev/null || true
elif [ $MSER_ENABLED -eq 1 ] && [ $mser_status -ne 0 ]; then
  echo "failed_mser" > "{status_file}"
  mv "$RUN_DIR" "${{ORIG_DIR}}__failed" 2>/dev/null || true
else
  echo "done" > "{status_file}"
  mv "$RUN_DIR" "${{ORIG_DIR}}__done" 2>/dev/null || true
fi
"""
    elif scheduler_type == "pbs":
        # PBS脚本
        script_content = f"""#!/bin/bash
#PBS -N {job_name}
#PBS -l nodes=1:ppn=1
#PBS -o pbs.out
#PBS -e pbs.err
#PBS -j oe

# 设置资源限制和线程数
ulimit -u 20480
ulimit -s 16384

# 设置环境变量，防止数学库线程冲突
export OPENBLAS_NUM_THREADS=1 
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
MSER_ENABLED={"1" if mser_enable else "0"}
{mser_env_block}

# 切换到作业提交的目录
cd $PBS_O_WORKDIR

ORIG_DIR="{orig_dir}"
RUN_DIR="$ORIG_DIR"
if [ -d "${{ORIG_DIR}}__running" ]; then RUN_DIR="${{ORIG_DIR}}__running"; fi
if [ -d "${{ORIG_DIR}}__done" ]; then RUN_DIR="${{ORIG_DIR}}__done"; fi
if [ -d "${{ORIG_DIR}}__failed" ]; then RUN_DIR="${{ORIG_DIR}}__failed"; fi
if [ "$RUN_DIR" = "$ORIG_DIR" ] && [ -d "$ORIG_DIR" ]; then
  (cd "$PARENT_DIR" && mv "$BASE_DIR" "${{BASE_DIR}}__running") && RUN_DIR="${{ORIG_DIR}}__running"
fi
cd "$RUN_DIR" || exit 1

echo $PBS_JOBID > jobid
echo "running" > "{status_file}"

# 运行RASPA
sim_exit_code=0
mser_status=0
{raspa_cmd}
sim_exit_code=$?
{mser_run_block}
if [ $sim_exit_code -ne 0 ]; then
  echo "failed_simulate" > "{status_file}"
  mv "$RUN_DIR" "${{ORIG_DIR}}__failed" 2>/dev/null || true
elif [ $MSER_ENABLED -eq 1 ] && [ $mser_status -ne 0 ]; then
  echo "failed_mser" > "{status_file}"
  mv "$RUN_DIR" "${{ORIG_DIR}}__failed" 2>/dev/null || true
else
  echo "done" > "{status_file}"
  mv "$RUN_DIR" "${{ORIG_DIR}}__done" 2>/dev/null || true
fi
"""
    else:
        # 本地脚本
        script_content = f"""#!/bin/bash

# 设置环境变量，防止数学库线程冲突
export OPENBLAS_NUM_THREADS=1 
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
MSER_ENABLED={"1" if mser_enable else "0"}
{mser_env_block}

# 切换到作业目录
ORIG_DIR="{orig_dir}"
PARENT_DIR="$(dirname "$ORIG_DIR")"
BASE_DIR="$(basename "$ORIG_DIR")"
RUN_DIR="$ORIG_DIR"
if [ -d "${{ORIG_DIR}}__running" ]; then RUN_DIR="${{ORIG_DIR}}__running"; fi
if [ -d "${{ORIG_DIR}}__done" ]; then RUN_DIR="${{ORIG_DIR}}__done"; fi
if [ -d "${{ORIG_DIR}}__failed" ]; then RUN_DIR="${{ORIG_DIR}}__failed"; fi
if [ "$RUN_DIR" = "$ORIG_DIR" ] && [ -d "$ORIG_DIR" ]; then
  (cd "$PARENT_DIR" && mv "$BASE_DIR" "${{BASE_DIR}}__running") && RUN_DIR="${{ORIG_DIR}}__running"
fi
cd "$RUN_DIR" || exit 1

echo $$ > jobid
echo "running" > "{status_file}"

# 运行RASPA
sim_exit_code=0
mser_status=0
{raspa_cmd}
sim_exit_code=$?
{mser_run_block}
if [ $sim_exit_code -ne 0 ]; then
  echo "failed_simulate" > "{status_file}"
  mv "$RUN_DIR" "${{ORIG_DIR}}__failed" 2>/dev/null || true
elif [ $MSER_ENABLED -eq 1 ] && [ $mser_status -ne 0 ]; then
  echo "failed_mser" > "{status_file}"
  mv "$RUN_DIR" "${{ORIG_DIR}}__failed" 2>/dev/null || true
else
  echo "done" > "{status_file}"
  mv "$RUN_DIR" "${{ORIG_DIR}}__done" 2>/dev/null || true
fi
"""

    # 写入脚本文件
    with open(script_path, "w") as f:
        f.write(script_content)

    # 设置执行权限
    os.chmod(script_path, 0o755)
    logger.info(f"创建作业脚本: {script_path}")

    return script_path


def submit_job(script_path, scheduler_type="pbs"):
    """提交作业

    Args:
        script_path: 脚本文件路径
        scheduler_type: 调度系统类型 ('slurm', 'pbs', 或 'local')

    Returns:
        str: 作业ID或None（如果提交失败）
    """
    try:
        # 保存当前目录
        original_dir = os.getcwd()

        # 切换到脚本所在目录
        script_dir = os.path.dirname(script_path)
        os.chdir(script_dir)
        script_name = os.path.basename(script_path)

        # 根据调度系统类型提交作业
        if scheduler_type == "slurm":
            # 使用SLURM提交作业
            result = subprocess.run(["sbatch", script_name],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  check=False)

            # 处理结果
            if result.returncode == 0:
                # 从输出中提取作业ID
                output = result.stdout.decode('utf-8').strip()
                # SLURM输出格式通常是 "Submitted batch job 123456"
                job_id = output.split()[-1] if output else "unknown"
                logger.info(f"作业提交成功，ID: {job_id}")
                # 将作业ID写入文件
                with open(os.path.join(script_dir, "jobid"), 'w') as f:
                    f.write(job_id)
                return job_id
            else:
                error = result.stderr.decode('utf-8').strip()
                logger.error(f"作业提交失败: {error}")
                return None

        elif scheduler_type == "pbs":
            # 使用PBS提交作业
            result = subprocess.run(["qsub", script_name],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  check=False)

            # 处理结果
            if result.returncode == 0:
                job_id = result.stdout.decode('utf-8').strip()
                logger.info(f"作业提交成功，ID: {job_id}")
                # 将作业ID写入文件
                with open(os.path.join(script_dir, "jobid"), 'w') as f:
                    f.write(job_id)
                return job_id
            else:
                error = result.stderr.decode('utf-8').strip()
                logger.error(f"作业提交失败: {error}")
                return None
        else:
            # 本地模式，直接在后台运行
            process = subprocess.Popen(["bash", script_name],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)

            # 将进程ID写入文件
            job_id = str(process.pid)
            with open(os.path.join(script_dir, "jobid"), 'w') as f:
                f.write(job_id)

            logger.info(f"本地作业已启动，进程ID: {job_id}")
            return job_id

    except Exception as e:
        logger.error(f"提交作业时出错: {e}")
        logger.debug(traceback.format_exc())
        return None
    finally:
        # 返回原始目录
        os.chdir(original_dir)
