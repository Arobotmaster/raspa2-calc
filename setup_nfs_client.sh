#!/bin/bash
# NFS客户端配置脚本

echo "=== 配置NFS客户端 ==="

# 检查nfs-utils是否已安装
if ! rpm -qa | grep -q nfs-utils; then
    echo "安装NFS客户端工具..."
    sudo yum install -y nfs-utils --disablerepo=epel,docker-ce-stable
fi

# 创建挂载点
echo "创建挂载点..."
sudo mkdir -p /home/zjp/raspa2-calc

# 测试NFS连接
echo "测试NFS服务器连接..."
showmount -e 10.10.14.12

# 挂载NFS共享
echo "挂载NFS共享..."
sudo mount -t nfs 10.10.14.12:/shared/raspa2-calc /home/zjp/raspa2-calc

# 添加到/etc/fstab以便开机自动挂载
if ! grep -q "10.10.14.12:/shared/raspa2-calc" /etc/fstab; then
    echo "添加到自动挂载..."
    echo "10.10.14.12:/shared/raspa2-calc /home/zjp/raspa2-calc nfs defaults 0 0" | sudo tee -a /etc/fstab
fi

# 设置环境变量
if ! grep -q "RASPA_WORK_DIR.*shared" ~/.bashrc; then
    echo "设置环境变量..."
    echo 'export RASPA_WORK_DIR=/home/zjp/raspa2-calc' >> ~/.bashrc
    echo 'export RASPA_DIR=/home/zjp/anaconda3/pkgs/raspa2-2.0.50-h678ec8c_0' >> ~/.bashrc
fi

# 验证挂载
echo "验证挂载状态..."
df -h | grep raspa2-calc
ls -la /home/zjp/raspa2-calc/

echo "NFS客户端配置完成！"
