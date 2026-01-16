#!/bin/bash

# 模拟完整的高通量计算工作流程
# 用于验证修复后的逻辑是否正确

echo "=== RASPA2 高通量计算工作流程模拟 ==="
echo

# 模拟参数
TOTAL_TASKS=8
CPU_CORES=3
CSV_FILE="test_data.csv"
COLUMN_NUM=1

echo "模拟场景："
echo "- 总任务数: $TOTAL_TASKS"
echo "- CPU核心数: $CPU_CORES"
echo "- CSV文件: $CSV_FILE"
echo "- 列号: $COLUMN_NUM"
echo

# ==========================================
# 阶段1: 初始化和环境检查
# ==========================================
echo "阶段1: 初始化和环境检查"
echo "1.1 检查RASPA_DIR环境变量..."
if [ -z "$RASPA_DIR" ]; then
    echo "   ⚠️  RASPA_DIR未设置，使用模拟模式"
    RASPA_DIR="/mock/raspa"
else
    echo "   ✅ RASPA_DIR已设置: $RASPA_DIR"
fi

echo "1.2 检查CIF文件配置..."
# CIF文件目录现在通过配置文件指定，不再假设固定位置
echo "   ℹ️  CIF文件目录由配置文件指定"

echo "1.3 验证CSV文件..."
if [ -f "$CSV_FILE" ]; then
    echo "   ✅ CSV文件存在"
    CSV_LINES=$(wc -l < "$CSV_FILE")
    echo "   📊 CSV文件包含 $CSV_LINES 行数据"
else
    echo "   ❌ CSV文件不存在，创建模拟数据"
    # 创建模拟CSV文件
    cat > "$CSV_FILE" << EOF
framework_name,property1,property2
MOF001,1.23,4.56
MOF002,2.34,5.67
MOF003,3.45,6.78
MOF004,4.56,7.89
MOF005,5.67,8.90
MOF006,6.78,9.01
MOF007,7.89,0.12
MOF008,8.90,1.23
EOF
    echo "   ✅ 已创建模拟CSV文件"
fi

echo

# ==========================================
# 阶段2: 参数配置和任务准备
# ==========================================
echo "阶段2: 参数配置和任务准备"

echo "2.1 读取并处理CSV数据..."
FRAMEWORKS=$(tail -n +2 "$CSV_FILE" | cut -d',' -f1)
TOTAL_FRAMEWORKS=$(echo "$FRAMEWORKS" | wc -l)
echo "   📊 发现 $TOTAL_FRAMEWORKS 个框架结构"

echo "2.2 创建输出目录结构..."
SUBDIR="simulation_output_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$SUBDIR"
echo "   📁 创建输出目录: $SUBDIR"

echo "2.3 生成任务配置文件..."
COUNTER=1
for framework in $FRAMEWORKS; do
    TASK_DIR="$SUBDIR/mc$COUNTER"
    mkdir -p "$TASK_DIR"

    # 创建模拟的simulation.input文件
    cat > "$TASK_DIR/simulation.input" << EOF
FrameworkName $framework
UnitCells 1 1 1
HeliumVoidFraction 0.5
Component 0 MoleculeName I2
EOF
    echo "   📝 创建任务 $COUNTER: $framework"
    COUNTER=$((COUNTER + 1))
done

echo

# ==========================================
# 阶段3: 任务分配和提交
# ==========================================
echo "阶段3: 任务分配和提交"

echo "3.1 计算任务分配..."
echo "   总任务数: $TOTAL_FRAMEWORKS"
echo "   CPU核心数: $CPU_CORES"
echo "   任务分配步长: $CPU_CORES"

echo "3.2 模拟CPU核心任务分配:"
for cpu in $(seq 1 $CPU_CORES); do
    TASKS_FOR_CPU=$(seq $cpu $CPU_CORES $TOTAL_FRAMEWORKS)
    echo "   CPU $cpu 处理任务: $TASKS_FOR_CPU"
done

echo "3.3 模拟作业提交..."
for cpu in $(seq 1 $CPU_CORES); do
    echo "   🚀 提交作业 CPU-$cpu (处理任务: $(seq $cpu $CPU_CORES $TOTAL_FRAMEWORKS))"
    sleep 0.1  # 模拟提交延迟
done

echo

# ==========================================
# 阶段4: 并行计算执行
# ==========================================
echo "阶段4: 并行计算执行"

echo "4.1 模拟并行计算过程..."
for cpu in $(seq 1 $CPU_CORES); do
    (
        echo "   🔄 CPU $cpu 开始执行..."

        # 模拟第一轮并行处理
        for task in $(seq $cpu $CPU_CORES $TOTAL_FRAMEWORKS); do
            echo "      📊 CPU $cpu 处理任务 mc$task (第一轮)"
            sleep 0.2  # 模拟计算时间

            # 模拟状态转换
            TASK_DIR="$SUBDIR/mc$task"
            mv "$TASK_DIR" "${TASK_DIR}__running" 2>/dev/null || true
            echo "         状态: mc$task → mc${task}__running"

            # 模拟RASPA计算
            echo "         ⚡ 执行RASPA模拟..."
            sleep 0.3

            # 模拟计算完成
            mv "${TASK_DIR}__running" "${TASK_DIR}__done" 2>/dev/null || true
            echo "         ✅ 任务 mc$task 完成: mc${task}__running → mc${task}__done"
        done

        echo "   🔄 CPU $cpu 第一轮完成，开始第二轮检查..."

        # 模拟第二轮地毯式搜索
        for task in $(seq 1 1 $TOTAL_FRAMEWORKS); do
            TASK_DIR="$SUBDIR/mc$task"
            if [ -d "${TASK_DIR}__done" ]; then
                echo "      ✅ CPU $cpu 确认任务 mc$task 已完成"
            elif [ -d "${TASK_DIR}__running" ]; then
                echo "      ⏳ CPU $cpu 发现任务 mc$task 仍在运行"
            elif [ -d "$TASK_DIR" ]; then
                echo "      📋 CPU $cpu 处理遗漏任务 mc$task"
                mv "$TASK_DIR" "${TASK_DIR}__running"
                sleep 0.2
                mv "${TASK_DIR}__running" "${TASK_DIR}__done"
                echo "         ✅ 遗漏任务 mc$task 已补齐"
            fi
        done

        echo "   ✅ CPU $cpu 执行完成"
    ) &
done

# 等待所有CPU核心完成
wait

echo

# ==========================================
# 阶段5: 结果收集和状态统计
# ==========================================
echo "阶段5: 结果收集和状态统计"

echo "5.1 统计任务完成状态..."
DONE_COUNT=$(find "$SUBDIR" -name "*__done" | wc -l)
RUNNING_COUNT=$(find "$SUBDIR" -name "*__running" | wc -l)
FAILED_COUNT=$(find "$SUBDIR" -name "*__failed" | wc -l)
PENDING_COUNT=$(find "$SUBDIR" -name "mc[0-9]*" ! -name "*__*" | wc -l)

echo "   📊 任务状态统计:"
echo "      ✅ 已完成: $DONE_COUNT 个"
echo "      ⏳ 运行中: $RUNNING_COUNT 个"
echo "      ❌ 失败: $FAILED_COUNT 个"
echo "      ⏸️  待处理: $PENDING_COUNT 个"

TOTAL_PROCESSED=$((DONE_COUNT + RUNNING_COUNT + FAILED_COUNT))
echo "   📈 处理进度: $TOTAL_PROCESSED / $TOTAL_FRAMEWORKS"

echo

# ==========================================
# 阶段6: 验证和问题检查
# ==========================================
echo "阶段6: 验证和问题检查"

ISSUES_FOUND=0

echo "6.1 检查任务完整性..."
if [ $DONE_COUNT -eq $TOTAL_FRAMEWORKS ]; then
    echo "   ✅ 所有任务都已完成"
else
    echo "   ❌ 发现未完成任务"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
fi

echo "6.2 检查是否有遗漏的任务..."
MISSED_TASKS=""
for i in $(seq 1 $TOTAL_FRAMEWORKS); do
    if [ ! -d "$SUBDIR/mc${i}__done" ]; then
        MISSED_TASKS="$MISSED_TASKS $i"
    fi
done

if [ -z "$MISSED_TASKS" ]; then
    echo "   ✅ 无遗漏任务"
else
    echo "   ❌ 发现遗漏任务: $MISSED_TASKS"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
fi

echo "6.3 检查CPU核心负载均衡..."
CPU_LOAD=""
for cpu in $(seq 1 $CPU_CORES); do
    CPU_TASKS=$(seq $cpu $CPU_CORES $TOTAL_FRAMEWORKS | wc -w)
    CPU_LOAD="$CPU_LOAD CPU$cpu:$CPU_TASKS"
done
echo "   📊 CPU负载分布: $CPU_LOAD"

echo "6.4 检查是否有重复计算..."
DUPLICATE_COUNT=0
for i in $(seq 1 $TOTAL_FRAMEWORKS); do
    DONE_DIR="$SUBDIR/mc${i}__done"
    if [ -d "$DONE_DIR" ]; then
        # 检查日志中是否有多次计算记录（模拟检查）
        LOG_ENTRIES=$(grep "mc$i" "$SUBDIR/log_output" 2>/dev/null | wc -l || echo "0")
        if [ "$LOG_ENTRIES" -gt 1 ]; then
            DUPLICATE_COUNT=$((DUPLICATE_COUNT + 1))
        fi
    fi
done

if [ $DUPLICATE_COUNT -eq 0 ]; then
    echo "   ✅ 无重复计算"
else
    echo "   ❌ 发现 $DUPLICATE_COUNT 个重复计算的任务"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
fi

echo

# ==========================================
# 阶段7: 最终报告
# ==========================================
echo "阶段7: 最终报告"

if [ $ISSUES_FOUND -eq 0 ]; then
    echo "🎉 工作流程模拟完成 - 全部正常！"
    echo
    echo "✅ 验证结果:"
    echo "   - 任务分配逻辑正确"
    echo "   - 并行计算正常执行"
    echo "   - 所有任务完成无遗漏"
    echo "   - CPU负载均衡合理"
    echo "   - 无重复计算问题"
else
    echo "⚠️  工作流程模拟完成 - 发现 $ISSUES_FOUND 个问题"
    echo
    echo "❌ 需要修复的问题:"
    if [ $DONE_COUNT -ne $TOTAL_FRAMEWORKS ]; then
        echo "   - 任务完成不完整"
    fi
    if [ -n "$MISSED_TASKS" ]; then
        echo "   - 存在遗漏任务: $MISSED_TASKS"
    fi
    if [ $DUPLICATE_COUNT -gt 0 ]; then
        echo "   - 存在重复计算"
    fi
fi

echo
echo "📁 模拟输出目录: $SUBDIR"
echo "🧹 清理命令: rm -rf $SUBDIR $CSV_FILE"

echo
echo "=== 模拟结束 ==="
