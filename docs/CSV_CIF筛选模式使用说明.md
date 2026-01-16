# CSV/CIF 筛选模式使用说明（模式 6）

交互式筛选 MOF CSV 数据，并可按筛选结果批量复制对应的 CIF 文件。入口已集成在 `raspa-calc` 主菜单。

## 前置条件
- 已运行 `install.sh`，可直接执行 `raspa-calc`
- 依赖 `pandas`（默认随工具安装）
- CSV 中含要筛选的列；如需复制 CIF，CSV 中需有文件名列（如 `refcode`）

## 快速操作
```bash
raspa-calc
# 选择模式 6: CSV/CIF 筛选模式
```

### 表达式输入（推荐，支持 AND/OR、区间、多值）
- 语法示例：
  - 比较：`PLD > 5`，`Density (g/cm3) <= 1.2`，`Metal Types = Co`
  - 区间：`4 <= LCD  <= 8`
  - 多值：`Metal Types in [Co,Ni,Zn]`，`KH_Classes in [weak,none]`
  - 组合：`PLD>5 AND (LCD >=4 OR Metal Types in [Co,Ni])`
- 入口：在 “第三步：设置筛选条件” 选择使用表达式输入（y），粘贴完整表达式即可一次筛完。

### 交互流程
1. **选择模式**：  
   - `1` 条件筛选：支持数值/文本条件，可叠加多个条件  
   - `2` refcode 提取：根据另一个 CSV 的 `refcode` 列提取匹配行
2. **加载 CSV**：输入主 CSV 路径（支持相对/绝对，自动尝试多种编码），程序会展示列名和前 5 行预览。
3. **设置条件 / 提取 refcode**：  
   - 数值列：`>`、`<`、`=`、`between`  
   - 文本列：等于/包含/前缀/后缀/列表  
   - refcode 提取：输入参考 CSV 路径，自动读取 `refcode` 列并匹配
4. **保存结果**：输入输出文件名，生成筛选后的 CSV（UTF-8 BOM）。
5. **可选复制 CIF**：输入文件名列、源目录、目标目录，工具会扫描源目录，复制匹配的 `.cif`（大小写不敏感，缺失会统计）。

### 示例（条件筛选 + 复制 CIF）
```text
请选择运行模式 (1/2/3/4/5/6): 6
... 选择工作模式 ...
请选择模式 (1 或 2): 1
请输入CSV文件路径: /home/zjp/raspa2-calc/filter/All-property.csv
请输入要筛选的列名: PLD
请选择筛选方式 (1-4): 1
请输入数值: 5
✅ 筛选后 2706 行
请输入输出CSV文件名: pld.csv
是否需要复制筛选后的CIF文件? (y/n): y
请输入包含文件名的列名: refcode
源文件夹路径: /home/zjp/raspa2-calc/filter/8804
目标文件夹路径: /home/zjp/raspa2-calc/filter/2705
... 复制完成，统计成功/缺失 ...
```

### 提示与注意
- CSV 编码自动尝试 `utf-8/utf-8-sig/gbk/gb2312/latin1`；失败时请检查文件编码或格式。
- 若文件名列无后缀，工具会自动补 `.cif`；按不区分大小写匹配。
- 大目录复制时会显示进度；缺失文件会统计并列出前 10 个。
- 若仅需筛选 CSV，可在复制环节选择 `n` 直接结束。 
