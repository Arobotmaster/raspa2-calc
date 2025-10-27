#!/bin/bash
# 批量配置所有节点的NFS客户端

NODES=("10.10.14.6" "10.10.14.7" "10.10.14.11")
NODE_NAMES=("master-node" "worker-node-01" "worker-node-02")

echo "=== 批量配置NFS客户端 ==="
echo "时间: $(date)"
echo ""

for i in "${!NODES[@]}"; do
    NODE_IP="${NODES[i]}"
    NODE_NAME="${NODE_NAMES[i]}"
    
    echo "【${NODE_NAME} (${NODE_IP})】"
    echo "正在配置..."
    
    # 检查节点连通性
    if ! ping -c 1 "$NODE_IP" >/dev/null 2>&1; then
        echo "❌ 节点 $NODE_IP 不可达，跳过"
        continue
    fi
    
    # 复制配置脚本到节点
    echo "正在复制配置脚本..."
    scp -q /shared/raspa2-calc/setup_nfs_client.sh zjp@$NODE_IP:~/
    
    if [ $? -eq 0 ]; then
        echo "✅ 脚本复制成功"
        echo "请手动登录到 $NODE_NAME 执行以下命令："
        echo "   ssh zjp@$NODE_IP"
        echo "   ./setup_nfs_client.sh"
        echo ""
    else
        echo "❌ 脚本复制失败"
        echo ""
    fi
done

echo "=== 配置指南 ==="
echo "请按顺序登录到每个节点并执行配置脚本："
echo ""
echo "1. master-node:"
echo "   ssh zjp@10.10.14.6"
echo "   ./setup_nfs_client.sh"
echo ""
echo "2. worker-node-01:"
echo "   ssh zjp@10.10.14.7"
echo "   ./setup_nfs_client.sh"
echo ""
echo "3. worker-node-02:"
echo "   ssh zjp@10.10.14.11"
echo "   ./setup_nfs_client.sh"
echo ""
echo "配置完成后，所有节点都将共享同一个工作目录："
echo "   /home/zjp/raspa2-calc -> /shared/raspa2-calc"
