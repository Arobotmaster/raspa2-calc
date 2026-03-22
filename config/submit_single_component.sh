#!/bin/bash
# 批量提交 24 套单组分 423K 验证任务
# 用法: cd ~/raspa2-calc && bash .raspa_tools/config/submit_single_component.sh

CONFIG_DIR="$HOME/raspa2-calc/.raspa_tools/config/single-component"

CONFIGS=(
  xylene-trappe-cbmc-swap-o-xylene-423K.yaml
  xylene-trappe-cbmc-swap-m-xylene-423K.yaml
  xylene-trappe-cbmc-swap-p-xylene-423K.yaml
  xylene-trappe-cfcmc-o-xylene-423K.yaml
  xylene-trappe-cfcmc-m-xylene-423K.yaml
  xylene-trappe-cfcmc-p-xylene-423K.yaml
  xylene-trappe-cfcmc-cbmc-o-xylene-423K.yaml
  xylene-trappe-cfcmc-cbmc-m-xylene-423K.yaml
  xylene-trappe-cfcmc-cbmc-p-xylene-423K.yaml
  xylene-trappe-conventional-o-xylene-423K.yaml
  xylene-trappe-conventional-m-xylene-423K.yaml
  xylene-trappe-conventional-p-xylene-423K.yaml
  xylene-opls-cbmc-swap-o-xylene-423K.yaml
  xylene-opls-cbmc-swap-m-xylene-423K.yaml
  xylene-opls-cbmc-swap-p-xylene-423K.yaml
  xylene-opls-cfcmc-o-xylene-423K.yaml
  xylene-opls-cfcmc-m-xylene-423K.yaml
  xylene-opls-cfcmc-p-xylene-423K.yaml
  xylene-opls-cfcmc-cbmc-o-xylene-423K.yaml
  xylene-opls-cfcmc-cbmc-m-xylene-423K.yaml
  xylene-opls-cfcmc-cbmc-p-xylene-423K.yaml
  xylene-opls-conventional-o-xylene-423K.yaml
  xylene-opls-conventional-m-xylene-423K.yaml
  xylene-opls-conventional-p-xylene-423K.yaml
)

TOTAL=${#CONFIGS[@]}
echo "共 $TOTAL 套单组分任务待提交"
echo "========================================"

for i in "${!CONFIGS[@]}"; do
  cfg="${CONFIGS[$i]}"
  cfg_path="$CONFIG_DIR/$cfg"
  num=$((i + 1))

  if [ ! -f "$cfg_path" ]; then
    echo "[$num/$TOTAL] 跳过（文件不存在）: $cfg"
    continue
  fi

  echo ""
  echo "[$num/$TOTAL] 提交: $cfg"
  echo "----------------------------------------"

  # 输入序列: 1(参数筛选模式) -> 2(指定配置文件) -> 路径 -> 24(核心数) -> y(确认)
  printf "1\n2\n%s\n24\ny\n" "$cfg_path" | raspa-calc

  if [ $? -eq 0 ]; then
    echo "✅ [$num/$TOTAL] $cfg 提交成功"
  else
    echo "❌ [$num/$TOTAL] $cfg 提交失败"
  fi

  sleep 2
done

echo ""
echo "========================================"
echo "全部 $TOTAL 套任务提交完成"
