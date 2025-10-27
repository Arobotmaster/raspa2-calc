#!/bin/bash
#SBATCH --job-name=raspa_job
#SBATCH --nodes=1
## 单作业=1个进程（RASPA为单线程），每进程仅用1个CPU
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=1
## 偏好使用超线程（若节点支持会利用，否则自动退化）
#SBATCH --hint=multithread
## 输出与时限
#SBATCH --output=raspa_job.out
#SBATCH --error=raspa_job.err
# #SBATCH --nodelist=worker-node-03  # 注释掉节点限制，允许调度器自动分配
#SBATCH --time=99999:00:00       ##设置作业的最大运行时间

# 设置环境变量，防止数学库线程冲突
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1

## 通过 srun 运行任务处理器，保证单任务步骤与绑核策略，simulate 在其中直接调用
srun --ntasks=1 --cpus-per-task=1 --hint=multithread --cpu-bind=threads \
  bash job_templates/runjobs.sh "$1" "$2"
