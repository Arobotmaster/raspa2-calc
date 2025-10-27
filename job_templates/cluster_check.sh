#!/bin/bash
# 集群状态检查脚本

echo "=== SLURM集群状态报告 ==="
echo "时间: $(date)"
echo ""

echo "1. 节点状态概览:"
sinfo -N
echo ""

echo "2. 详细节点信息:"
sinfo -Nel
echo ""

echo "3. CPU资源统计:"
echo "节点名称          状态     CPU总数  已分配  空闲"
echo "=================================================="
sinfo -h -o "%n %t %c %C" | while read node state total alloc; do
    idle=$((total - alloc))
    printf "%-15s %-8s %-8s %-8s %-8s\n" "$node" "$state" "$total" "$alloc" "$idle"
done
echo ""

echo "4. 总CPU资源统计:"
TOTAL_CPUS=$(sinfo -h -o "%c" | awk '{sum+=$1} END {print sum}')
IDLE_CPUS=$(sinfo -h -o "%c %T" | awk '$2 ~ /idle/ {sum+=$1} END {print sum+0}')
MIXED_CPUS=$(sinfo -h -o "%c %T" | awk '$2 ~ /mixed/ {sum+=$1} END {print sum+0}')
DRAIN_CPUS=$(sinfo -h -o "%c %T" | awk '$2 ~ /drain/ {sum+=$1} END {print sum+0}')
AVAILABLE_CPUS=$((IDLE_CPUS + MIXED_CPUS))

echo "总CPU数: $TOTAL_CPUS"
echo "空闲CPU: $IDLE_CPUS"
echo "混合CPU: $MIXED_CPUS" 
echo "排空CPU: $DRAIN_CPUS"
echo "可用CPU: $AVAILABLE_CPUS"
echo ""

echo "5. 当前作业队列:"
squeue -u $USER 2>/dev/null | head -10
echo ""

echo "6. 建议操作:"
echo "   - 使用优化脚本: ./optimized_submit.sh <cpu_count>"
echo "   - 检查排空节点: scontrol show node worker-node-03"
echo "   - 恢复节点: sudo scontrol update NodeName=worker-node-03 State=RESUME"
echo "   - 查看作业详情: scontrol show job <job_id>"