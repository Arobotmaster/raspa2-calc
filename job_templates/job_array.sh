#!/bin/bash
#SBATCH --job-name=raspa-calc
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=1
#SBATCH --hint=multithread
#SBATCH --array=1-200%200
#SBATCH --time=99999:00:00
#SBATCH --output=/home/zjp/raspa2-calc/work/test/1log/raspa_%A_%a.out
#SBATCH --error=/home/zjp/raspa2-calc/work/test/1log/raspa_%A_%a.err

WORK_DIR=/home/zjp/raspa2-calc/work
cd "$WORK_DIR" || exit 1
echo "SLURM 数组任务启动: JobID=${SLURM_ARRAY_JOB_ID:-$SLURM_JOB_ID} TaskID=${SLURM_ARRAY_TASK_ID}"

if [ "${RASPA_SIMPLE_LAUNCH:-false}" = "true" ]; then
  # 直接启动（更快启动，靠 cgroups/配额控制CPU；不使用 srun 绑核）
  exec bash job_templates/runjobs.sh "${SLURM_ARRAY_TASK_ID}" "200"
else
  srun --ntasks=1 --cpus-per-task=1 --hint=multithread --cpu-bind=threads \
    bash job_templates/runjobs.sh "${SLURM_ARRAY_TASK_ID}" "200"
fi
