#!/bin/bash

# 脚本用法说明
show_usage() {
    echo "用法: $0 [选项]"
    echo "选项:"
    echo "  -u <用户名>    删除指定用户的所有任务"
    echo "  -r <开始-结束> 删除指定范围的作业ID (例如: -r 12894-13421)"
    echo "  -l <作业ID列表> 删除指定的作业ID列表 (例如: -l 12894,12895,13421)"
    echo "  -h             显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0 -u zjp                    # 删除用户zjp的所有任务"
    echo "  $0 -r 12894-13421            # 删除作业ID从12894到13421的所有任务"
    echo "  $0 -l 12894,12895,13421      # 删除指定的作业ID"
}

# 删除指定用户的所有任务
kill_user_jobs() {
    local username=$1
    echo "正在获取用户 $username 的所有任务..."
    
    # 获取用户的所有任务ID
    local job_ids=$(squeue -u $username -h -o "%i" 2>/dev/null)
    
    if [ -z "$job_ids" ]; then
        echo "用户 $username 没有正在运行或排队的任务"
        return 0
    fi
    
    echo "找到以下任务ID:"
    echo "$job_ids"
    echo ""
    
    # 确认删除
    read -p "确认删除用户 $username 的所有任务? [y/N]: " confirm
    if [[ $confirm =~ ^[Yy]$ ]]; then
        echo "正在删除任务..."
        for job_id in $job_ids; do
            echo "删除任务 $job_id"
            scancel $job_id
        done
        echo "完成删除用户 $username 的所有任务"
    else
        echo "操作已取消"
    fi
}

# 删除指定范围的任务
kill_range_jobs() {
    local range=$1
    local start=$(echo $range | cut -d'-' -f1)
    local end=$(echo $range | cut -d'-' -f2)
    
    if [[ ! $start =~ ^[0-9]+$ ]] || [[ ! $end =~ ^[0-9]+$ ]]; then
        echo "错误: 范围格式不正确，应为 开始-结束 (例如: 12894-13421)"
        exit 1
    fi
    
    echo "正在删除作业ID从 $start 到 $end 的任务..."
    for i in $(seq $start $end); do
        echo "删除任务 $i"
        scancel $i
    done
    echo "完成删除范围任务"
}

# 删除指定列表的任务
kill_list_jobs() {
    local job_list=$1
    echo "正在删除指定的任务列表..."
    
    # 将逗号分隔的列表转换为数组
    IFS=',' read -ra job_array <<< "$job_list"
    
    for job_id in "${job_array[@]}"; do
        # 去除空格
        job_id=$(echo $job_id | tr -d ' ')
        if [[ $job_id =~ ^[0-9]+$ ]]; then
            echo "删除任务 $job_id"
            scancel $job_id
        else
            echo "警告: 跳过无效的作业ID '$job_id'"
        fi
    done
    echo "完成删除列表任务"
}

# 主程序逻辑
if [ $# -eq 0 ]; then
    # 如果没有参数，保持原有行为
    echo "执行原有删除范围任务..."
    for i in {12894..13421}; do
        echo "删除任务 $i"
        scancel $i
    done
else
    # 解析命令行参数
    while getopts "u:r:l:h" opt; do
        case $opt in
            u)
                kill_user_jobs "$OPTARG"
                ;;
            r)
                kill_range_jobs "$OPTARG"
                ;;
            l)
                kill_list_jobs "$OPTARG"
                ;;
            h)
                show_usage
                exit 0
                ;;
            \?)
                echo "无效选项: -$OPTARG" >&2
                show_usage
                exit 1
                ;;
        esac
    done
fi