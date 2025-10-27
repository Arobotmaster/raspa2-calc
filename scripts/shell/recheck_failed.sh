#!/bin/bash

# RASPA失败任务重新检查脚本
# 此脚本用于重新检查被标记为__failed的目录，将实际成功的目录重新标记为__done

echo "=== RASPA失败任务重新检查工具 ==="
echo "此工具将检查所有__failed目录，并将实际成功的任务重新标记为__done"

# 获取当前工作目录
topdir=$(pwd)

# 改进的失败检测函数（与runjobs.sh中的函数相同）
check_simulation_success() {
    local work_dir="$1"
    local simulation_failed=true
    
    echo "检查目录: $work_dir"
    
    # 检查1：是否存在output文件
    if ls "${work_dir}/Output/System_0/output_"*"_1.1.1_"*".data" >/dev/null 2>&1 || \
       ls "${work_dir}/output_"*"_1.1.1_"*".data" >/dev/null 2>&1 || \
       [ -f "${work_dir}/output.data" ]; then
        echo "  ✓ 检测到输出文件存在"
        simulation_failed=false
    fi
    
    # 检查2：检查是否有电影文件或重启文件（另一种成功指标）
    if ls "${work_dir}/Movies/System_0/"*.pdb >/dev/null 2>&1 || \
       ls "${work_dir}/RestartInitial/System_0/"* >/dev/null 2>&1 || \
       ls "${work_dir}/"*.pdb >/dev/null 2>&1; then
        echo "  ✓ 检测到电影或重启文件存在"
        simulation_failed=false
    fi
    
    # 检查3：如果有output文件，检查是否包含"Simulation finished"或其他完成标志
    for output_file in "${work_dir}/Output/System_0/output_"*".data" "${work_dir}/output_"*".data" "${work_dir}/output.data"; do
        if [ -f "$output_file" ]; then
            if grep -q "Simulation finished\|simulation finished\|Average loading\|Final results" "$output_file" 2>/dev/null; then
                echo "  ✓ 在输出文件中发现模拟完成标志"
                simulation_failed=false
                break
            fi
        fi
    done
    
    # 检查4：检查是否有合理的输出文件大小（不为空）
    for output_file in "${work_dir}/Output/System_0/output_"*".data" "${work_dir}/output_"*".data" "${work_dir}/output.data"; do
        if [ -f "$output_file" ] && [ -s "$output_file" ]; then
            local file_size=$(wc -c < "$output_file" 2>/dev/null || echo 0)
            if [ "$file_size" -gt 1000 ]; then  # 文件大小大于1KB认为是有效输出
                echo "  ✓ 检测到有效的输出文件（大小: ${file_size} bytes）"
                simulation_failed=false
                break
            fi
        fi
    done
    
    # 返回结果：0表示成功，1表示失败
    if [ "$simulation_failed" = true ]; then
        echo "  ✗ 未检测到成功的模拟证据"
        return 1
    else
        echo "  ✓ 模拟已成功完成"
        return 0
    fi
}

# 查找所有子目录中的__failed目录
failed_count=0
success_count=0
recovered_count=0

echo ""
echo "开始搜索__failed目录..."

# 搜索所有包含__failed的目录
for failed_dir in $(find "$topdir" -type d -name "*__failed" 2>/dev/null); do
    failed_count=$((failed_count + 1))
    echo ""
    echo "[$failed_count] 处理目录: $failed_dir"
    
    # 检查这个目录是否实际成功
    if check_simulation_success "$failed_dir"; then
        # 获取基础名称（去掉__failed后缀）
        base_name=$(echo "$failed_dir" | sed 's/__failed$//')
        done_dir="${base_name}__done"
        
        echo "  → 准备将目录重命名为: $done_dir"
        
        # 检查目标目录是否已存在
        if [ -d "$done_dir" ]; then
            echo "  ⚠ 警告: 目标目录 $done_dir 已存在"
            echo "  → 请手动处理此冲突"
        else
            # 重命名目录
            if mv "$failed_dir" "$done_dir"; then
                echo "  ✓ 成功重命名为: $done_dir"
                recovered_count=$((recovered_count + 1))
                
                # 从原始文件名中提取框架名称
                if [ -f "$done_dir/simulation.input" ]; then
                    framework_name=$(grep "FrameworkName" "$done_dir/simulation.input" | awk '{print $2}' 2>/dev/null || echo "未知框架")
                    echo "  ✓ 框架名称: $framework_name"
                fi
            else
                echo "  ✗ 重命名失败"
            fi
        fi
        success_count=$((success_count + 1))
    else
        echo "  → 确实失败，保持__failed状态"
    fi
done

echo ""
echo "=== 重新检查完成 ==="
echo "总共检查的__failed目录数: $failed_count"
echo "实际成功的目录数: $success_count"
echo "成功恢复的目录数: $recovered_count"
echo "确实失败的目录数: $((failed_count - success_count))"

if [ $recovered_count -gt 0 ]; then
    echo ""
    echo "✓ 已成功恢复 $recovered_count 个被错误标记为失败的计算任务！"
    echo "这些任务现在被标记为__done状态。"
else
    echo ""
    echo "未发现被错误标记为失败的任务。"
fi

if [ $failed_count -eq 0 ]; then
    echo ""
    echo "未找到任何__failed目录。"
fi

echo ""
echo "检查完成。" 