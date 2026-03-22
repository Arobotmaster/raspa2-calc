#!/bin/bash
# 批量提交所有 xylene 力场验证任务
# 用法: bash submit_all_xylene.sh
# 每套任务使用 24 核，自动确认提交

RASPA_CALC=$(which raspa-calc 2>/dev/null || echo "$HOME/raspa2-calc/.raspa_tools/bin/raspa-calc")
CONFIG_DIR="$HOME/raspa2-calc/.raspa_tools/config"

# 要提交的配置文件列表（跳过已提交的 opls-cbmc-swap-323K）
CONFIGS=(
  xylene-opls-cbmc-swap-343K.yaml
  xylene-opls-cbmc-swap-383K.yaml
  xylene-opls-cbmc-swap-423K.yaml
  xylene-opls-cfcmc-323K.yaml
  xylene-opls-cfcmc-343K.yaml
  xylene-opls-cfcmc-383K.yaml
  xylene-opls-cfcmc-423K.yaml
  xylene-opls-cfcmc-cbmc-323K.yaml
  xylene-opls-cfcmc-cbmc-343K.yaml
  xylene-opls-cfcmc-cbmc-383K.yaml
  xylene-opls-cfcmc-cbmc-423K.yaml
  xylene-opls-conventional-323K.yaml
  xylene-opls-conventional-343K.yaml
  xylene-opls-conventional-383K.yaml
  xylene-opls-conventional-423K.yaml
  xylene-trappe-cbmc-swap-323K.yaml
  xylene-trappe-cbmc-swap-343K.yaml
  xylene-trappe-cbmc-swap-383K.yaml
  xylene-trappe-cbmc-swap-423K.yaml
  xylene-trappe-cfcmc-323K.yaml
  xylene-trappe-cfcmc-343K.yaml
  xylene-trappe-cfcmc-383K.yaml
  xylene-trappe-cfcmc-423K.yaml
  xylene-trappe-cfcmc-cbmc-323K.yaml
  xylene-trappe-cfcmc-cbmc-343K.yaml
  xylene-trappe-cfcmc-cbmc-383K.yaml
  xylene-trappe-cfcmc-cbmc-423K.yaml
  xylene-trappe-conventional-323K.yaml
  xylene-trappe-conventional-343K.yaml
  xylene-trappe-conventional-383K.yaml
  xylene-trappe-conventional-423K.yaml
)

TOTAL=${#CONFIGS[@]}
echo "共 $TOTAL 套任务待提交"
echo "========================================"

for i in "${!CONFIGS[@]}"; do
  cfg="${CONFIGS[$i]}"
  cfg_path="$CONFIG_DIR/$cfg"
  num=$((i + 1))
  echo ""
  echo "[$num/$TOTAL] 提交: $cfg"
  echo "----------------------------------------"

  # 输入序列: 1(模式) -> 2(指定配置) -> 路径 -> 24(核心数) -> y(确认)
  printf "1\n2\n%s\n24\ny\n" "$cfg_path" | raspa-calc

  if [ $? -eq 0 ]; then
    echo "✅ [$num/$TOTAL] $cfg 提交成功"
  else
    echo "❌ [$num/$TOTAL] $cfg 提交失败"
  fi

  # 短暂等待避免并发写入冲突
  sleep 2
done

echo ""
echo "========================================"
echo "全部 $TOTAL 套任务提交完成"
