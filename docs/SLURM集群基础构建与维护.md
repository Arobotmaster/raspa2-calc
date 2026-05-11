# SLURM 集群基础构建与维护

这份文档补的是 RASPA 部署之前的“基础地基”。

如果你要在一组 Linux 节点上部署基于 Anaconda 的 RASPA2 / RASPA3 高通量计算环境，前提不是先装 RASPA，而是先把 Slurm 集群本身构建稳定。RASPA 只是跑在这个集群上的作业负载。

适用对象：

- 还没有现成 Slurm 集群，需要先把集群搭起来
- 已有 Slurm 集群，但需要明确哪些配置是 RASPA 高通量真正依赖的
- 后续要新增节点、同步用户、排查调度问题

相关文档：

- `/home/zjp/raspa2-calc/.raspa_tools/docs/CLUSTER_DEPLOYMENT_GUIDE.md`
- `/home/zjp/raspa2-calc/.raspa_tools/docs/SLURM_CR_CORE_高通量&多线程说明.md`
- `/home/zjp/Slurm-manage/slurm-cluster-summary.md`
- `/home/zjp/Slurm-manage/slurm-add-node-checklist.md`
- `/home/zjp/Slurm-manage/ansible-user-sync/README.md`

## 1. Slurm 集群在这套 RASPA 体系中的角色

RASPA2 / RASPA3 本身不负责集群调度。当前这套体系中：

- Slurm 负责节点注册、资源分配、队列调度
- NFS 负责共享工作目录
- 统一 UID/GID 负责跨节点权限一致
- RASPA2 / RASPA3 作为被调度的计算程序运行

所以顺序应该是：

1. 先把 Slurm 集群构建好
2. 再把共享存储、用户一致性、Anaconda/RASPA 环境配好
3. 最后再跑高通量计算

## 2. 最小架构

一套最小可用的 Slurm 集群通常至少包含：

- 1 台控制节点：运行 `slurmctld`
- 1 台或多台计算节点：运行 `slurmd`
- 全部节点共享同一份 `munge.key`
- 全部节点可以互相解析主机名和通信

当前这套集群的落地示例：

- 控制节点：`master-node`
- 计算节点：`worker-node-01`、`worker-node-02`、`worker-node-03`
- 分区：`normal`
- 认证：`munge`

共享存储不是 Slurm 的硬性要求，但对当前 RASPA 高通量体系来说基本是必需的，因为任务目录、脚本和输出都依赖共享工作区。

## 3. 构建 Slurm 集群的四个核心要素

### 3.1 slurm.conf

真正定义“这是一套集群”的文件是：

- `/etc/slurm/slurm.conf`

它至少要定义这些内容：

- `ClusterName`
- `ControlMachine` / `ControlAddr`
- `NodeName=...`
- `PartitionName=...`

当前这套集群的关键思路是：

- `SelectType=select/cons_tres`
- `SelectTypeParameters=CR_Core`
- `ProctrackType=proctrack/linuxproc`
- `TaskPlugin=task/none`
- `SlurmctldParameters=enable_configless`
- `ReturnToService=2`

其中最重要的和 RASPA 直接相关的点有两个：

- `CR_Core`
  这决定 Slurm 以 core 为基本资源单位；结合超线程节点时，需要额外理解“单线程 RASPA 如何吃满逻辑线程”，详见 `SLURM_CR_CORE_高通量&多线程说明.md`
- `ReturnToService=2`
  这让节点在“unexpected reboot”后重新注册成功时自动恢复到可调度状态，避免每次重启后手工 `RESUME`

### 3.2 munge.key

Slurm 节点之间的认证依赖：

- `/etc/munge/munge.key`

规则很简单：

- 所有节点必须是同一份密钥
- 权限必须严格
- `munge` 服务必须正常启动

如果这一步不对，节点即使装好了 Slurm，也无法真正加入集群。

### 3.3 systemd 服务

最少需要两个服务：

- 控制节点：`slurmctld`
- 计算节点：`slurmd`

当前现网的 `slurmd` 还额外使用了：

- `/etc/systemd/system/slurmd.service.d/selinux.conf`

用途是规避 Rocky/CentOS 8 环境下的 Slurm SELinux 兼容问题。

### 3.4 主机名、网络、时间同步

这三个基础条件如果不稳，后面所有排障都会很痛苦：

- `NodeName` 必须和节点主机名对得上
- 所有计算节点必须能访问 `ControlAddr`
- 节点间时间不能漂移太大

## 4. 从零构建一套基础 Slurm 集群

下面是最小可用流程。

### 4.1 规划节点信息

先明确每台机器的：

- 主机名
- IP
- CPU 拓扑
- 可分配内存（MB）
- 是控制节点还是计算节点

建议先记录：

```bash
hostname
hostname -I
nproc --all
lscpu | egrep 'Socket|Core|Thread'
free -m
```

### 4.2 安装 Slurm 和 Munge

每台机器都需要安装：

- `slurm`
- `slurm-slurmd`
- `slurm-slurmctld`（仅控制节点）
- `munge`

安装完成后至少确认：

```bash
systemctl status munge
systemctl status slurmd
```

控制节点还要确认：

```bash
systemctl status slurmctld
```

### 4.3 分发 munge.key

在控制节点准备好标准密钥后，把同一份文件分发到所有计算节点：

```bash
sudo install -o munge -g munge -m 0400 /path/to/munge.key /etc/munge/munge.key
sudo systemctl enable --now munge
munge -n | unmunge
```

### 4.4 编写 slurm.conf

控制节点上写 `/etc/slurm/slurm.conf`，至少包含：

```ini
ClusterName=cluster
ControlMachine=master-node
ControlAddr=10.10.14.6

AuthType=auth/munge
CryptoType=crypto/munge

SchedulerType=sched/backfill
SelectType=select/cons_tres
SelectTypeParameters=CR_Core

SlurmctldParameters=enable_configless

NodeName=master-node CPUs=256 Boards=1 SocketsPerBoard=2 CoresPerSocket=64 ThreadsPerCore=2 RealMemory=251000 State=UNKNOWN
NodeName=worker-node-01 CPUs=128 Boards=1 SocketsPerBoard=2 CoresPerSocket=64 ThreadsPerCore=1 RealMemory=251000 State=UNKNOWN
NodeName=worker-node-02 CPUs=384 Boards=1 SocketsPerBoard=2 CoresPerSocket=96 ThreadsPerCore=2 RealMemory=376000 State=UNKNOWN
NodeName=worker-node-03 CPUs=192 Boards=1 SocketsPerBoard=2 CoresPerSocket=96 ThreadsPerCore=1 RealMemory=377000 State=UNKNOWN

PartitionName=normal Nodes=master-node,worker-node-01,worker-node-02,worker-node-03 Default=YES MaxTime=INFINITE State=UP
```

要点：

- `CPUs / SocketsPerBoard / CoresPerSocket / ThreadsPerCore / RealMemory` 必须与真实硬件一致
- `State=UNKNOWN` 比手工写 `UP` 更稳妥，让 Slurm 自己判断节点状态
- 如果节点硬件信息填错，节点会注册异常，后续 RASPA 调度也会一起出问题

### 4.5 启动服务

控制节点：

```bash
sudo systemctl enable --now munge slurmctld
```

计算节点：

```bash
sudo systemctl enable --now munge slurmd
```

如果计算节点采用和现网相同的 SELinux 兼容方式，还应同步：

- `/etc/systemd/system/slurmd.service.d/selinux.conf`

### 4.6 验证集群

在控制节点执行：

```bash
scontrol ping
sinfo -N -l
scontrol show node
```

判断标准：

- `scontrol ping` 显示 `slurmctld ... is UP`
- `sinfo -N -l` 能看到所有节点
- 计算节点状态应逐步变成 `idle`、`mix` 或 `alloc`

## 5. RASPA 部署为什么还需要额外做两件事

Slurm 能跑起来，不代表 RASPA 高通量就能稳定跑。

当前体系至少还依赖两个基础条件：

### 5.1 UID/GID 一致性

如果控制节点和计算节点上用户 UID/GID 不一致，常见结果是：

- 作业 0 秒失败
- 无法 `setuid/setgid`
- 共享目录属主变成数字
- `slurm_cred_create failure`

当前推荐维护入口：

- `/home/zjp/Slurm-manage/ansible-user-sync/README.md`

### 5.2 共享工作目录

当前 RASPA 工具链默认依赖共享工作区，例如：

- `/home/zjp/raspa2-calc`
- `/home/zjp/raspa2-calc/work`

如果 NFS 异常或挂载出现 `Stale file handle`，作业通常会表现为：

- 0 秒失败
- 没有 stdout / stderr
- 进不去 `WorkDir`

这部分看：

- `/home/zjp/raspa2-calc/.raspa_tools/docs/CLUSTER_DEPLOYMENT_GUIDE.md`
- `/home/zjp/raspa2-calc/.raspa_tools/docs/存储架构说明_NVMe_NFS_分层存储.md`

## 6. 新增节点

新增节点时，不是“把机器装好就算加入集群”，而是必须完成这几步：

1. 新节点安装 Slurm 和 Munge
2. 新节点使用同一份 `munge.key`
3. 控制节点 `slurm.conf` 里增加新的 `NodeName=...`
4. 把新节点加入 `PartitionName=...`
5. 启动新节点 `munge` 和 `slurmd`
6. 控制节点执行 `scontrol reconfigure`
7. 把新节点纳入后续用户同步和运维 inventory

当前已经有自动化入口：

- `/home/zjp/Slurm-manage/ansible-user-sync/playbooks/slurm_add_node.yml`
- `/home/zjp/Slurm-manage/ansible-user-sync/vars/slurm_add_node.example.yml`

更细的手工说明见：

- `/home/zjp/Slurm-manage/slurm-add-node-checklist.md`

## 7. 日常维护

### 7.1 每天先看三件事

```bash
scontrol ping
sinfo -N -l
squeue
```

这三条基本能覆盖：

- 控制器是否在线
- 节点是否正常注册
- 队列里是否有异常积压

### 7.2 节点重启后状态恢复

当前现网配置使用：

- `ReturnToService=2`

所以节点因为重启掉线后，只要重新按有效配置注册，通常会自动恢复，不需要人工 `RESUME`。

对应自动化入口：

- `/home/zjp/Slurm-manage/ansible-user-sync/playbooks/slurm_return_to_service.yml`

### 7.3 用户新增/删除

不要在多节点上手工逐台 `useradd`。

统一入口是：

- `/home/zjp/Slurm-manage/ansible-user-sync/README.md`

里面已经包含：

- 固定 UID/GID 的用户/组清单
- 新增用户流程
- 删除用户流程
- 全节点一致性检查

## 8. 和当前 RASPA 高通量最相关的 Slurm 设计点

### 8.1 为什么是 CR_Core

当前集群配置：

- `SelectTypeParameters=CR_Core`

这意味着 Slurm 以物理 core 为资源调度单位。

但 RASPA 通常是单线程程序，所以在超线程节点上会出现一个额外问题：

- Slurm 分到 1 个 core
- 实际硬件可能是 2 个逻辑线程
- 如果每个 job 只跑 1 个 RASPA 进程，就会有一半线程空转

所以当前工具链又额外实现了：

- 同一 job 内多 worker 打包

详细解释在：

- `/home/zjp/raspa2-calc/.raspa_tools/docs/SLURM_CR_CORE_高通量&多线程说明.md`

### 8.2 为什么 RASPA3 用 Anaconda

当前 RASPA3 通过 conda 环境运行，核心原因是：

- 依赖更容易收敛
- 所有节点统一环境更容易复制
- 便于在作业脚本里固定激活同名环境

典型作业前置命令：

```bash
source ~/anaconda3/etc/profile.d/conda.sh
conda activate raspa3
raspa3 --help
```

这要求：

- 每个会跑作业的节点都存在相同的 conda 环境名
- 所有节点上的 RASPA3 执行路径一致

## 9. 推荐的维护顺序

以后遇到问题，按这个顺序排：

1. 先看 Slurm 控制器和节点状态
2. 再看用户 UID/GID 是否一致
3. 再看共享存储是否正常
4. 最后再看 RASPA2 / RASPA3 本身输入、模板和环境

这个顺序很重要。

很多表面上像“RASPA 坏了”的问题，本质其实是：

- Slurm 节点没注册
- 用户映射错了
- NFS 挂载坏了

## 10. 一句话结论

对于这套基于 Anaconda 的 RASPA2 / RASPA3 高通量体系，Slurm 集群不是附属配置，而是运行地基。

地基是否稳定，取决于：

- `slurm.conf` 是否正确
- `munge.key` 是否统一
- 节点是否正常注册
- 用户/组是否一致
- 共享工作目录是否稳定

先把这些做好，再谈 RASPA 高通量，整体故障率会低很多。
