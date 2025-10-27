# RASPA2多节点集群部署指南

## 目录
- [1. 部署概述](#1-部署概述)
- [2. 环境准备](#2-环境准备)
- [3. NFS共享存储配置](#3-nfs共享存储配置)
- [4. 作业脚本优化](#4-作业脚本优化)
- [5. 环境变量配置](#5-环境变量配置)
- [6. 部署验证](#6-部署验证)
- [7. 使用指南](#7-使用指南)
- [8. 故障排除](#8-故障排除)

---

## 1. 部署概述

### 1.1 项目背景
本部署指南用于配置RASPA2高通量计算工具在SLURM集群上的多节点任务调度能力。通过配置NFS共享存储和优化作业脚本，实现960个CPU核心的充分利用。

### 1.2 集群环境
- **操作系统**: Linux 8.10
- **调度器**: SLURM
- **节点配置**:
  - master-node: 控制节点
  - worker-node-01: 计算节点 (192核)
  - worker-node-02: 计算节点 (192核)
  - worker-node-03: 计算节点 (192核) + NFS服务器
  - worker-node-04: 计算节点 (384核)
- **总CPU核心数**: 960核

### 1.3 部署目标
- ✅ 解决硬编码节点限制问题
- ✅ 配置跨节点共享存储
- ✅ 实现多节点任务调度
- ✅ 充分利用集群计算资源

---

## 2. 环境准备

### 2.1 系统要求
```bash
# 检查操作系统版本
cat /etc/os-release

# 检查SLURM状态
sinfo -N

# 检查网络连通性
ping worker-node-01
ping worker-node-02
ping worker-node-03
```

### 2.2 依赖软件安装
在所有节点上安装必要软件：
```bash
# 安装NFS工具（跳过有问题的软件源）
sudo yum install -y nfs-utils --disablerepo=epel,docker-ce-stable

# 启动相关服务
sudo systemctl enable rpcbind nfs-client.target
sudo systemctl start rpcbind
```

---

## 3. NFS共享存储配置

### 3.1 NFS服务器配置 (worker-node-03)

#### 3.1.1 创建共享目录
```bash
# 在worker-node-03上执行
sudo mkdir -p /shared/raspa2-calc
sudo chown -R zjp:zjp /shared/raspa2-calc
sudo chmod 755 /shared/raspa2-calc
```

#### 3.1.2 配置NFS导出
```bash
# 编辑/etc/exports文件
sudo vim /etc/exports

# 添加以下内容：
/shared/raspa2-calc 10.10.14.0/24(rw,sync,no_root_squash,no_subtree_check)
```

#### 3.1.3 启动NFS服务
```bash
# 启动并启用NFS服务
sudo systemctl enable nfs-server rpcbind
sudo systemctl start nfs-server rpcbind

# 重新加载导出配置
sudo exportfs -ra

# 验证导出状态
sudo exportfs -v
showmount -e localhost
```

### 3.2 NFS客户端配置 (所有其他节点)

#### 3.2.1 创建挂载点
```bash
# 在每个客户端节点执行
sudo mkdir -p /home/zjp/raspa2-calc
sudo chown zjp:zjp /home/zjp/raspa2-calc
```

#### 3.2.2 手动挂载测试
```bash
# 测试挂载
sudo mount -t nfs4 10.10.14.12:/shared/raspa2-calc /home/zjp/raspa2-calc

# 验证挂载
df -h | grep raspa
ls -la /home/zjp/raspa2-calc
```

#### 3.2.3 配置自动挂载
```bash
# 编辑/etc/fstab文件
sudo vim /etc/fstab

# 添加以下行：
10.10.14.12:/shared/raspa2-calc /home/zjp/raspa2-calc nfs4 rw,hard,intr,timeo=600,retrans=2 0 0

# 测试fstab配置
sudo umount /home/zjp/raspa2-calc
sudo mount -a
```

### 3.3 数据迁移
```bash
# 在worker-node-03上将项目文件复制到共享目录
cp -r /home/zjp/raspa2-calc/* /shared/raspa2-calc/

# 重新挂载确保数据同步
sudo umount /home/zjp/raspa2-calc
sudo mount /home/zjp/raspa2-calc
```

---

## 4. 作业脚本优化

### 4.1 问题分析
原始作业脚本存在硬编码节点限制：
```bash
#SBATCH --nodelist=worker-node-03  # 硬编码限制
```

这导致所有任务只能在worker-node-03上运行，其他节点资源浪费。

### 4.2 优化措施

#### 4.2.1 移除硬编码节点限制
修改以下文件：
- `/home/zjp/raspa2-calc/job_templates/job_sub.sh`
- `/home/zjp/raspa2-calc/job_templates/job_sub144.sh`
- `/home/zjp/raspa2-calc/job_templates/sbatch.sh`

```bash
# 将硬编码行注释掉
# #SBATCH --nodelist=worker-node-03  # 注释掉节点限制，允许调度器自动分配
```

#### 4.2.2 创建优化提交脚本
创建了 `optimized_submit.sh` 脚本，具备以下功能：
- 自动检测集群可用资源
- 智能分配作业数量
- 支持动态节点选择
- 提供详细的作业统计信息

### 4.3 模板文件更新
确保 `.raspa_tools/job_templates/` 目录下的模板文件也同步更新：
```bash
# 运行安装脚本更新模板
cd /home/zjp/raspa2-calc
./install.sh
```

---

## 5. 环境变量配置

### 5.1 统一环境变量
在所有节点的 `~/.bashrc` 文件中添加：
```bash
# RASPA2环境变量
export RASPA_DIR="/home/zjp/anaconda3/pkgs/raspa2-2.0.50-h678ec8c_0"
export RASPA_WORK_DIR="/home/zjp/raspa2-calc"

# 防止数学库线程冲突
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
```

### 5.2 重新加载环境
```bash
# 在所有节点执行
source ~/.bashrc

# 验证环境变量
echo $RASPA_WORK_DIR
echo $RASPA_DIR
```

### 5.3 配置文件更新
更新 `config.yaml` 中的工作目录配置：
```yaml
environment:
  work_dir: "/home/zjp/raspa2-calc"  # 指向NFS挂载目录
```

---

## 6. 部署验证

### 6.1 集群状态检查
```bash
# 检查所有节点状态
sinfo -N

# 期望输出：所有节点状态为idle
NODELIST        NODES PARTITION STATE 
master-node         1   normal* idle  
worker-node-01      1   normal* idle  
worker-node-02      1   normal* idle  
worker-node-03      1   normal* idle  
```

### 6.2 NFS挂载验证
```bash
# 在任意节点检查挂载状态
mount | grep raspa

# 期望输出：
10.10.14.12:/shared/raspa2-calc on /home/zjp/raspa2-calc type nfs4 (rw,relatime,...)

# 验证文件访问
ls -la /home/zjp/raspa2-calc
```

### 6.3 功能测试
```bash
# 使用集群检查脚本
cd /home/zjp/raspa2-calc
./job_templates/cluster_check.sh

# 提交测试作业
./job_templates/optimized_submit.sh 4
```

### 6.4 任务调度验证
```bash
# 查看作业分布
squeue -u $USER

# 验证作业在不同节点上运行
squeue -u $USER -o "%.10i %.9P %.20j %.8u %.8T %.10M %.6D %R"
```

---

## 7. 使用指南

### 7.1 基本使用流程

#### 7.1.1 进入工作目录
```bash
# 必须在NFS挂载目录下工作
cd /home/zjp/raspa2-calc
```

#### 7.1.2 准备输入文件
确保以下文件在共享目录中：
- CIF结构文件
- simulation.input模板
- 配置文件 (config.yaml)

#### 7.1.3 提交任务
```bash
# 方法1：使用优化脚本
./job_templates/optimized_submit.sh 192

# 方法2：使用raspa-calc命令
raspa-calc <参数>

# 方法3：手动提交
sbatch job_templates/sbatch.sh
```

### 7.2 监控和管理

#### 7.2.1 查看任务状态
```bash
# 查看作业队列
squeue -u $USER

# 查看集群资源
sinfo -N

# 实时监控
watch squeue -u $USER
```

#### 7.2.2 任务管理
```bash
# 取消所有作业
scancel -u $USER

# 取消特定作业
scancel <job_id>

# 查看作业详情
scontrol show job <job_id>
```

### 7.3 性能优化建议

#### 7.3.1 合理设置并行度
```bash
# 根据任务数量调整并行作业数
# 任务数 < 960: 使用任务数作为并行度
# 任务数 >= 960: 使用最大CPU数960
```

#### 7.3.2 监控资源使用
```bash
# 查看节点负载
sinfo -Nel

# 查看CPU使用率
top -u zjp
```

---

## 8. 故障排除

### 8.1 常见问题

#### 8.1.1 NFS挂载问题
**问题**: NFS挂载失败
**解决方案**:
```bash
# 检查NFS服务状态
sudo systemctl status nfs-server
sudo systemctl status rpcbind

# 检查网络连通性
ping 10.10.14.12

# 重新挂载
sudo umount /home/zjp/raspa2-calc
sudo mount -a
```

#### 8.1.2 任务调度问题
**问题**: 任务仍然挂起在特定节点
**解决方案**:
```bash
# 检查节点状态
scontrol show node worker-node-03

# 恢复排空节点
sudo scontrol update NodeName=worker-node-03 State=RESUME

# 检查作业脚本是否还有硬编码限制
grep -r "nodelist" job_templates/
```

#### 8.1.3 环境变量问题
**问题**: 环境变量未生效
**解决方案**:
```bash
# 检查环境变量
echo $RASPA_WORK_DIR
echo $RASPA_DIR

# 重新加载配置
source ~/.bashrc

# 在作业脚本中显式设置
export RASPA_WORK_DIR="/home/zjp/raspa2-calc"
```

### 8.2 日志和调试

#### 8.2.1 查看作业日志
```bash
# 查看作业输出
tail -f raspa_*.out
tail -f raspa_*.err

# 查看SLURM日志
sudo journalctl -u slurmd -f
```

#### 8.2.2 调试模式
```bash
# 使用调试模式提交作业
sbatch --test-only job_templates/sbatch.sh

# 检查作业脚本语法
bash -n job_templates/sbatch.sh
```

### 8.3 性能问题

#### 8.3.1 NFS性能优化
```bash
# 调整NFS挂载参数
mount -t nfs4 -o rsize=1048576,wsize=1048576,hard,intr,timeo=600 \
  10.10.14.12:/shared/raspa2-calc /home/zjp/raspa2-calc
```

#### 8.3.2 作业调度优化
```bash
# 分批提交避免调度器过载
for i in {1..10}; do
    sbatch job_templates/sbatch.sh
    sleep 1
done
```

---

## 9. 部署检查清单

### 9.1 部署前检查
- [ ] 所有节点网络连通正常
- [ ] SLURM服务运行正常
- [ ] 用户权限配置正确
- [ ] 必要软件包已安装

### 9.2 NFS配置检查
- [ ] NFS服务器正常启动
- [ ] 导出配置正确
- [ ] 所有客户端挂载成功
- [ ] 文件权限设置正确
- [ ] 自动挂载配置生效

### 9.3 作业脚本检查
- [ ] 硬编码节点限制已移除
- [ ] 模板文件已更新
- [ ] 环境变量配置正确
- [ ] 脚本权限设置正确

### 9.4 功能验证检查
- [ ] 集群状态正常
- [ ] 测试作业提交成功
- [ ] 作业能分布到不同节点
- [ ] 输出文件正确生成

---

## 10. 总结

### 10.1 关键成功因素
1. **NFS共享存储**: 确保所有节点访问相同数据
2. **移除硬编码限制**: 允许调度器自由分配节点
3. **统一环境配置**: 保证所有节点环境一致
4. **正确的工作目录**: 必须在NFS挂载目录下提交任务

### 10.2 最佳实践
1. 定期监控集群状态和资源使用
2. 合理设置并行作业数量
3. 及时清理完成的作业文件
4. 保持NFS服务的高可用性

### 10.3 预期效果
- CPU利用率从单节点192核提升到集群960核
- 作业调度灵活性大幅提升
- 高通量计算效率显著提高
- 系统资源充分利用

---

**文档版本**: v1.0  
**更新日期**: 2025-09-06  
**维护人员**: zjp  
**状态**: 部署成功验证