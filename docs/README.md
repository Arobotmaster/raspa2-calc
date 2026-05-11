# RASPA Tools 文档导航

这个目录下的文档已经覆盖了：

- Slurm 集群基础构建与维护
- NFS / 存储架构
- 基于 Anaconda 的 RASPA2 / RASPA3 部署
- 高通量、参数筛选、数据提取、绘图等功能使用

如果你是第一次接手这套环境，不要从某一篇功能文档直接开始。推荐按下面的顺序读。

## 1. 首次部署推荐阅读顺序

### 第一步：先把 Slurm 集群地基看明白

- [SLURM集群基础构建与维护.md](/home/zjp/raspa2-calc/.raspa_tools/docs/SLURM集群基础构建与维护.md)

这篇解决的是“RASPA 跑在什么基础设施上”。

重点包括：

- Slurm 集群最小构建步骤
- `slurm.conf` / `munge.key` / systemd 的作用
- 新增节点、用户一致性、日常维护
- 为什么 RASPA 问题经常其实是 Slurm / UID/GID / NFS 问题

### 第二步：再看整体 RASPA 集群部署

- [CLUSTER_DEPLOYMENT_GUIDE.md](/home/zjp/raspa2-calc/.raspa_tools/docs/CLUSTER_DEPLOYMENT_GUIDE.md)

这篇解决的是“在现成 Slurm 集群上，怎么把 RASPA2 / RASPA3 跑起来”。

重点包括：

- NFS 共享工作区
- Anaconda / RASPA2 / RASPA3 环境
- 作业脚本和环境变量
- 基本验证方法

### 第三步：先了解这套工具到底有哪些功能

- [高通量计算模式使用说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/高通量计算模式使用说明.md)
- [参数筛选模式使用说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/参数筛选模式使用说明.md)
- [数据提取模式使用说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/数据提取模式使用说明.md)
- [等温线绘制模式使用说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/等温线绘制模式使用说明.md)
- [CSV_CIF筛选模式使用说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/CSV_CIF筛选模式使用说明.md)
- [raspa-scale使用说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/raspa-scale使用说明.md)

这一步解决的是“这套工具能做什么，以及你应该先看哪种模式”。

建议理解：

- 六大主要功能分别解决什么问题
- 高通量主流程和参数筛选的区别
- 数据提取、绘图、CSV/CIF 筛选分别在什么阶段使用
- `raspa-scale` 是运行中调并发，不是前置部署文档

### 第四步：再理解当前 Slurm 资源模型和调度逻辑

- [SLURM_CR_CORE_高通量&多线程说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/SLURM_CR_CORE_高通量&多线程说明.md)

这篇解决的是“为什么当前集群这样调度 RASPA 单线程任务”，属于理解性能与调度策略的进阶文档，不是首次上手必读的第三步。

重点包括：

- `CR_Core` 的含义
- 超线程节点为什么要做 worker 打包
- 节点计划、worker、job 的对应关系

## 2. 日常维护入口

### Slurm / 集群基础维护

- [SLURM集群基础构建与维护.md](/home/zjp/raspa2-calc/.raspa_tools/docs/SLURM集群基础构建与维护.md)

适合处理：

- 新增 Slurm 节点
- Slurm 基础排障
- 节点重启后恢复
- 用户 / UID/GID / NFS 这类基础设施问题

### 存储与 NFS

- [存储架构说明_NVMe_NFS_分层存储.md](/home/zjp/raspa2-calc/.raspa_tools/docs/存储架构说明_NVMe_NFS_分层存储.md)
- [CLUSTER_DEPLOYMENT_GUIDE.md](/home/zjp/raspa2-calc/.raspa_tools/docs/CLUSTER_DEPLOYMENT_GUIDE.md)
- [提交任务后SLURM不计算问题排查记录.md](/home/zjp/raspa2-calc/.raspa_tools/docs/提交任务后SLURM不计算问题排查记录.md)

适合处理：

- NFS 挂载
- 在线区 / 归档区布局
- `Stale file handle`
- 工作目录读写异常
- 提交成功但任务没有真正开始计算

### RASPA 版本与运行环境

- [CLUSTER_DEPLOYMENT_GUIDE.md](/home/zjp/raspa2-calc/.raspa_tools/docs/CLUSTER_DEPLOYMENT_GUIDE.md)
- [RASPA3_Examples_Guide.md](/home/zjp/raspa2-calc/.raspa_tools/docs/RASPA3_Examples_Guide.md)

适合处理：

- RASPA2 与 RASPA3 切换
- conda 环境
- RASPA3 JSON 资源目录
- 作业脚本环境变量

## 3. 功能使用文档

### 高通量主流程

- [高通量计算模式使用说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/高通量计算模式使用说明.md)
- [raspa-scale使用说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/raspa-scale使用说明.md)

适合处理：

- 批量任务生成与提交
- 动态扩缩容
- 节点优先级与 worker 数控制

### 参数筛选与数据处理

- [参数筛选模式使用说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/参数筛选模式使用说明.md)
- [数据提取模式使用说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/数据提取模式使用说明.md)
- [CSV_CIF筛选模式使用说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/CSV_CIF筛选模式使用说明.md)
- [等温线绘制模式使用说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/等温线绘制模式使用说明.md)

### 其他专题

- [pymser.md](/home/zjp/raspa2-calc/.raspa_tools/docs/pymser.md)
- [WARNING_PROCESSOR_SIMPLIFIED_FINAL_REPORT.md](/home/zjp/raspa2-calc/.raspa_tools/docs/WARNING_PROCESSOR_SIMPLIFIED_FINAL_REPORT.md)

## 4. 代码结构与维护参考

- [CODE_STRUCTURE.md](/home/zjp/raspa2-calc/.raspa_tools/docs/CODE_STRUCTURE.md)

适合处理：

- 想改代码，但不清楚入口在哪
- 想知道 shell 脚本、Python CLI、模板路径之间如何连接

## 5. 最短判断路径

如果以后遇到问题，可以先按这个顺序判断：

1. 先看 Slurm 集群是不是正常
2. 再看 UID/GID 和共享存储是不是正常
3. 再看 RASPA2 / RASPA3 环境和你当前使用的功能模式
4. 最后再看调度逻辑和性能细节

对应入口：

1. [SLURM集群基础构建与维护.md](/home/zjp/raspa2-calc/.raspa_tools/docs/SLURM集群基础构建与维护.md)
2. [CLUSTER_DEPLOYMENT_GUIDE.md](/home/zjp/raspa2-calc/.raspa_tools/docs/CLUSTER_DEPLOYMENT_GUIDE.md)
3. 各模式使用说明
4. [SLURM_CR_CORE_高通量&多线程说明.md](/home/zjp/raspa2-calc/.raspa_tools/docs/SLURM_CR_CORE_高通量&多线程说明.md)

## 6. 一句话结论

这个目录现在可以按两种方式使用：

- 想从零部署：按 “Slurm 基础 -> RASPA 集群部署 -> 功能总览 -> 调度逻辑说明” 顺序读
- 想排障或维护：先看基础设施文档，再看具体功能文档
