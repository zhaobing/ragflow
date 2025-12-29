# _assign_column 方法完整解析

## 一、概要：方法签名/调用链路/整体结构

### A. 方法签名

```python
def _assign_column(self, boxes, zoomin=3):
    """
    为文本框分配列ID（col_id）- 基于KMeans聚类的文档列识别

    参数:
        boxes (List[dict]): 文本框列表
            每个框包含: {"x0": float, "x1": float, "top": float,
                        "bottom": float, "page_number": int, ...}
        zoomin (int): 缩放倍数（本方法中未使用，保留用于兼容性）

    返回:
        List[dict]: 添加了 col_id 字段的文本框列表
            每个框新增: {"col_id": int}  # 列索引（0, 1, 2, ...）

    作用:
        1. 识别每页的列数（单栏、双栏、三栏等）
        2. 为每个文本框分配列索引
        3. 确保列索引从左到右排列（col_id=0是最左列）
    """
```

### B. 调用链路

```python
# 在解析流程中的位置
pdf_parser.py#_text_merge ->
    _assign_column(self.boxes, zoomin)  # 列识别与分配
    ↓
    # 水平合并同列文本框

pdf_parser.py#_naive_vertical_merge ->
    _assign_column(self.boxes, zoomin)  # 列识别与分配
    ↓
    # 垂直合并同列文本框

pdf_parser.py#_final_reading_order_merge ->
    _assign_column(self.boxes, zoomin)  # 列识别与分配
    ↓
    # 调整阅读顺序
```

### C. 整体逻辑流程

```
┌─────────────────────────────────────────────────────┐
│ 1. 前置检查                                           │
│    - 空列表检查                                       │
│    - 是否已分配col_id检查                             │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│ 2. 按页分组                                           │
│    - 将文本框按page_number分组                        │
│    - 每页独立处理                                      │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│ 3. 每页列数识别（核心算法）                            │
│    3.1 提取左边界坐标（x0）                           │
│    3.2 缩进容错处理（INDENT_TOL = width * 0.12）      │
│    3.3 KMeans聚类（k=1到4）                          │
│    3.4 轮廓系数评估                                   │
│    3.5 选择最佳列数                                   │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│ 4. 全局列数投票                                       │
│    - 统计各页列数                                     │
│    - 取众数作为全局参考                               │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│ 5. 最终列ID分配                                       │
│    5.1 使用KMeans对每页文本框聚类                     │
│    5.2 按聚类中心X坐标排序                            │
│    5.3 重新映射col_id（0, 1, 2, ...）                │
└─────────────────────────────────────────────────────┘
```

---

## 二、业务逻辑

### A. 核心目标

**自动识别文档的列结构**，为每个文本框分配列ID，支持：
- 单栏文档（如小说、报告）
- 双栏文档（如学术论文）
- 三栏文档（如小册子）
- 四栏文档（如海报）

### B. 为什么需要列识别？

#### 场景1: 双栏文档的阅读顺序

```
错误处理（无列信息）:
┌─────────────────────────────────────┐
│ 第1列上    第2列上                   │
│ 文本1      文本3                     │
│ 文本2      文本4                     │
│ 第1列下    第2列下                   │
│ 文本5      文本6                     │
└─────────────────────────────────────┘

阅读顺序: 1 → 2 → 3 → 4 → 5 → 6  ❌ 错误！

正确处理（有列信息）:
col_id=0: 1 → 2 → 5
col_id=1: 3 → 4 → 6

阅读顺序: 1 → 2 → 5 → 3 → 4 → 6  ✅ 正确！
```

#### 场景2: 文本合并

```python
# 无列信息: 可能错误地合并不同列的文本
box1 = {"text": "第1列文本", "x0": 100}
box2 = {"text": "第2列文本", "x0": 400}
# 可能被错误合并（如果Y轴相近）

# 有列信息: 只合并同列的文本
box1 = {"text": "第1列文本", "x0": 100, "col_id": 0}
box2 = {"text": "第2列文本", "x0": 400, "col_id": 1}
# 不会合并（col_id不同）
```

### C. 输入输出

| 项目 | 类型 | 说明 |
|------|------|------|
| **输入** | `List[dict]` | 文本框列表，每个框包含位置信息 |
| **输出** | `List[dict]` | 同样的列表，每个框新增 `col_id` 字段 |

**输出示例**：

```python
# 输入
boxes = [
    {"text": "第1列文本1", "x0": 100, "page_number": 1},
    {"text": "第2列文本1", "x0": 400, "page_number": 1},
    {"text": "第1列文本2", "x0": 120, "page_number": 1},
    {"text": "第2列文本2", "x0": 420, "page_number": 1},
]

# 输出
boxes = [
    {"text": "第1列文本1", "x0": 100, "page_number": 1, "col_id": 0},
    {"text": "第2列文本1", "x0": 400, "page_number": 1, "col_id": 1},
    {"text": "第1列文本2", "x0": 120, "page_number": 1, "col_id": 0},
    {"text": "第2列文本2", "x0": 420, "page_number": 1, "col_id": 1},
]
```

---

## 三、执行流程详解

### 步骤1: 前置检查（[pdf_parser.py:448-451](pdf_parser.py#L448-L451)）

```python
if not boxes:
    return boxes  # 空列表，直接返回

if all("col_id" in b for b in boxes):
    return boxes  # 所有框都有col_id，跳过处理
```

**设计意图**：
- **性能优化**: 如果已经分配过列ID，直接跳过
- **幂等性**: 多次调用该方法不会产生副作用

---

### 步骤2: 按页分组（[pdf_parser.py:453-458](pdf_parser.py#L453-L458)）

```python
by_page = defaultdict(list)
for b in boxes:
    by_page[b["page_number"]].append(b)

page_cols = {}
```

**数据结构示例**：

```python
# 输入
boxes = [
    {"text": "...", "page_number": 1, "x0": 100},
    {"text": "...", "page_number": 1, "x0": 400},
    {"text": "...", "page_number": 2, "x0": 100},
    {"text": "...", "page_number": 2, "x0": 400},
    {"text": "...", "page_number": 2, "x0": 700},  # 三栏
]

# 分组结果
by_page = {
    1: [
        {"text": "...", "page_number": 1, "x0": 100},
        {"text": "...", "page_number": 1, "x0": 400},
    ],
    2: [
        {"text": "...", "page_number": 2, "x0": 100},
        {"text": "...", "page_number": 2, "x0": 400},
        {"text": "...", "page_number": 2, "x0": 700},
    ],
}
```

**为什么按页分组？**
- 不同页可能有不同的列数
- 例如：第1页是单栏（标题页），第2页是双栏（正文）

---

### 步骤3: 每页列数识别（[pdf_parser.py:460-510](pdf_parser.py#L460-L510)）

这是**核心算法**，包含5个子步骤。

#### 3.1 提取左边界坐标

```python
x0s_raw = np.array([b["x0"] for b in bxs], dtype=float)
```

**示例**：

```python
# 输入
bxs = [
    {"text": "第1列第1段", "x0": 100},
    {"text": "第1列第2段", "x0": 120},  # 有缩进
    {"text": "第2列第1段", "x0": 400},
    {"text": "第2列第2段", "x0": 420},  # 有缩进
]

# 输出
x0s_raw = [100, 120, 400, 420]
```

---

#### 3.2 计算页面边界与缩进容差

```python
min_x0 = np.min(x0s_raw)     # 最左边的文本框位置
max_x1 = np.max([b["x1"] for b in bxs])  # 最右边的文本框位置
width = max_x1 - min_x0      # 页面内容宽度

INDENT_TOL = width * 0.12    # 缩进容差
```

**可视化**：

```
页面宽度计算:

min_x0 = 100                           max_x1 = 600
        ↓                               ↓
┌────────�─────────────────────────────────┐
│ 第1列              第2列                 │
│ ┌──────────────┐  ┌──────────────┐      │
│ │这是首行，有缩进│  │正常段落       │      │
│ │ x0=100       │  │ x0=400       │      │
│ └──────────────┘  └──────────────┘      │
│ ┌──────────────┐  ┌──────────────┐      │
│ │无缩进的段落   │  │正常段落       │      │
│ │ x0=120       │  │ x0=400       │      │
│ └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────┘

width = 600 - 100 = 500
INDENT_TOL = 500 * 0.12 = 60  # 可以容忍约2个汉字的缩进
```

---

#### 3.3 缩进归一化处理

```python
x0s = []
for x in x0s_raw:
    if abs(x - min_x0) < INDENT_TOL:
        x0s.append([min_x0])  # 归一化到最左边界
    else:
        x0s.append([x])  # 保持原值
x0s = np.array(x0s, dtype=float)
```

**作用**：消除段落首行缩进对列识别的影响

**示例**：

```python
# 输入
x0s_raw = [100, 120, 400, 420]
min_x0 = 100
INDENT_TOL = 60

# 处理过程
x=100:  |100 - 100| = 0 < 60   → x0s.append([100])
x=120:  |120 - 100| = 20 < 60  → x0s.append([100])  # 归一化！
x=400:  |400 - 100| = 300 > 60 → x0s.append([400])
x=420:  |420 - 100| = 320 > 60 → x0s.append([400])  # 归一化！

# 输出
x0s = [[100], [100], [400], [400]]
```

**关键点**：
- `x0s` 是二维数组，因为 `KMeans.fit_predict()` 要求 2D 输入
- 归一化后，KMeans能正确识别为2列，而不是4列

---

#### 3.4 KMeans聚类选择最佳列数

```python
max_try = min(4, len(bxs))  # 最多尝试4列
if max_try < 2:
    max_try = 1

best_k = 1          # 最佳列数
best_score = -1     # 最佳轮廓系数

for k in range(1, max_try + 1):
    km = KMeans(n_clusters=k, n_init="auto")
    labels = km.fit_predict(x0s)

    centers = np.sort(km.cluster_centers_.flatten())
    if len(centers) > 1:
        try:
            score = silhouette_score(x0s, labels)  # 轮廓系数
        except ValueError:
            continue
    else:
        score = 0

    if score > best_score:
        best_score = score
        best_k = k

page_cols[pg] = best_k
```

**轮廓系数（Silhouette Score）**：

| 范围 | 含义 | 聚类效果 |
|------|------|----------|
| **0.7 - 1.0** | 强结构 | 优秀 |
| **0.5 - 0.7** | 中等结构 | 良好 |
| **0.25 - 0.5** | 弱结构 | 一般 |
| **< 0.25** | 无结构 | 差 |

**示例**：

```python
# 双栏文档
x0s = [[100], [100], [400], [400]]

# k=1: score = 0 (只有1个聚类，轮廓系数为0)
# k=2: score = 0.95 (两个聚类分离很好)  ← 最佳
# k=3: score = 0.60 (过度拟合)
# k=4: score = 0.40 (严重过拟合)

best_k = 2
page_cols[1] = 2  # 第1页是2列
```

---

#### 3.5 全局列数投票（[pdf_parser.py:513-514](pdf_parser.py#L513-L514)）

```python
global_cols = Counter(page_cols.values()).most_common(1)[0][0]
logging.info(f"Global column_num decided by majority: {global_cols}")
```

**作用**：避免某页误判，取众数作为全局参考

**示例**：

```python
# 输入
page_cols = {1: 2, 2: 2, 3: 1, 4: 2, 5: 2}
#            第1页2列  第2页2列  第3页1列  第4页2列  第5页2列

# 投票
Counter({2: 4, 1: 1})  # 2列出现4次，1列出现1次

global_cols = 2  # 大多数页是2列
```

**为什么需要全局投票？**
- 某些页可能因为内容特殊（如图片页）被误判
- 投票机制可以提高鲁棒性

---

### 步骤4: 最终列ID分配（[pdf_parser.py:517-539](pdf_parser.py#L517-L539)）

```python
for pg, bxs in by_page.items():
    if not bxs:
        continue

    k = page_cols[pg]  # 使用之前识别的列数
    if len(bxs) < k:    # 如果文本框数量 < 列数
        k = 1           # 强制为1列，避免聚类错误

    # 4.1 KMeans聚类
    x0s = np.array([[b["x0"]] for b in bxs], dtype=float)
    km = KMeans(n_clusters=k, n_init="auto")
    labels = km.fit_predict(x0s)

    # 4.2 按聚类中心排序
    centers = km.cluster_centers_.flatten()
    order = np.argsort(centers)  # 升序排列的索引

    # 4.3 重新映射col_id
    remap = {orig: new for new, orig in enumerate(order)}

    # 4.4 分配col_id
    for b, lb in zip(bxs, labels):
        b["col_id"] = remap[lb]

    # 4.5 按列分组（本步骤不影响结果，可能用于调试）
    grouped = defaultdict(list)
    for b in bxs:
        grouped[b["col_id"].append(b)

return boxes
```

**详细示例**：

```python
# 输入：第1页的文本框
bxs = [
    {"text": "第2列文本1", "x0": 400},
    {"text": "第1列文本1", "x0": 100},
    {"text": "第2列文本2", "x0": 420},
    {"text": "第1列文本2", "x0": 120},
]

# 步骤4.1: KMeans聚类（k=2）
x0s = [[400], [100], [420], [120]]
labels = [1, 0, 1, 0]  # KMeans的原始标签
#                    (第2列)(第1列)(第2列)(第1列)

# 步骤4.2: 按聚类中心排序
centers = [110, 410]  # 两个聚类中心
order = [0, 1]        # argsort([110, 410]) = [0, 1]

# 步骤4.3: 重新映射
remap = {0: 0, 1: 1}  # 原始标签 → 新标签

# 步骤4.4: 分配col_id
boxes = [
    {"text": "第2列文本1", "x0": 400, "col_id": 1},  # labels[0]=1 → remap[1]=1
    {"text": "第1列文本1", "x0": 100, "col_id": 0},  # labels[1]=0 → remap[0]=0
    {"text": "第2列文本2", "x0": 420, "col_id": 1},  # labels[2]=1 → remap[1]=1
    {"text": "第1列文本2", "x0": 120, "col_id": 0},  # labels[3]=0 → remap[0]=0
]
```

---

## 四、技术要点

### A. KMeans聚类参数

```python
km = KMeans(n_clusters=k, n_init="auto")
```

**参数说明**：
- `n_clusters=k`: 聚类数量（1到4）
- `n_init="auto"`: 自动选择初始化次数（默认为10）

**为什么KMeans适合列识别？**

| 特性 | 说明 |
|------|------|
| **简单高效** | 时间复杂度 O(nkt)，适合1D数据 |
| **无监督** | 不需要标注数据 |
| **1D数据友好** | 文本框的x0坐标是1维数据 |
| **可解释性强** | 聚类中心对应列的物理位置 |

---

### B. 轮廓系数（Silhouette Score）

**定义**：

```
对于每个样本i:
a(i) = 样本i到同簇其他样本的平均距离（簇内距离）
b(i) = 样本i到最近异簇样本的平均距离（簇间距离）

s(i) = (b(i) - a(i)) / max(a(i), b(i))

轮廓系数 = 所有样本s(i)的平均值
```

**范围与含义**：

| 范围 | 含义 | 说明 |
|------|------|------|
| **接近1** | 完美聚类 | 样本分配正确，簇间分离明显 |
| **接近0** | 重叠聚类 | 簇之间有重叠 |
| **接近-1** | 错误聚类 | 样本被分配到错误的簇 |

**在列识别中的应用**：

```python
# 示例1: 双栏文档（理想的聚类）
x0s = [[100], [100], [400], [400]]
score = 0.95  # 优秀

# 示例2: 单栏文档（不需要聚类）
x0s = [[100], [120], [110], [130]]
score = -0.2  # 差（说明k=2不合适，应该k=1）

# 示例3: 三栏文档
x0s = [[50], [50], [250], [250], [450], [450]]
score = 0.92  # 优秀
```

---

### C. 缩进容差设计

```python
INDENT_TOL = width * 0.12
```

**为什么是12%？**

**理论依据**：

```
中文字符宽度 ≈ 12pt
两个字符的缩进 ≈ 24pt

A4纸张宽度 ≈ 500pt
12% of 500pt = 60pt

可以容忍：
- 首行缩进2个字符（24pt）
- 段落间的小幅对齐误差（±20pt）
- OCR检测的微小偏差（±10pt）
总计容差 ≈ 60pt
```

**实验验证**：

```python
# 场景1: 双栏文档 + 首行缩进
width = 500
INDENT_TOL = 60

x0s_raw = [100, 125, 400, 425]  # 25pt的缩进
# 归一化后
x0s = [100, 100, 400, 400]  # 正确识别为2列 ✅

# 场景2: 如果容差太小（如5%）
INDENT_TOL = 25
x0s = [100, 125, 400, 425]  # 未归一化
# KMeans可能识别为3列或4列 ❌

# 场景3: 如果容差太大（如20%）
INDENT_TOL = 100
# 可能把不同列误判为同一列 ❌
```

---

### D. 列数上限设计

```python
max_try = min(4, len(bxs))
```

**为什么最大是4？**

| 文档类型 | 列数 | 示例 |
|---------|------|------|
| 单栏 | 1 | 小说、报告 |
| 双栏 | 2 | 学术论文、报纸 |
| 三栏 | 3 | 小册子、宣传单 |
| 四栏 | 4 | 海报、说明书 |
| **超过4列** | **罕见** | 报纸（5-6列，但OCR通常失败） |

**限制为4的原因**：
1. **实用考虑**：绝大多数文档≤4列
2. **性能考虑**：尝试更多列增加计算时间
3. **准确性考虑**：文本框数量有限时，过多列会导致过拟合

---

### E. 边界情况处理

| 情况 | 处理方式 | 代码 |
|------|---------|------|
| **空列表** | 直接返回 | `if not boxes: return boxes` |
| **已有col_id** | 跳过处理 | `if all("col_id" in b for b in boxes): return boxes` |
| **某页无文本框** | 列数设为1 | `if not bxs: page_cols[pg] = 1` |
| **文本框 < 列数** | 强制为1列 | `if len(bxs) < k: k = 1` |
| **轮廓系数计算失败** | 跳过该k | `except ValueError: continue` |

---

## 五、数据流示例

### A. 单栏文档

```python
# 输入
boxes = [
    {"text": "标题", "x0": 150, "page_number": 1},
    {"text": "正文1", "x0": 100, "page_number": 1},
    {"text": "正文2", "x0": 100, "page_number": 1},
    {"text": "正文3", "x0": 120, "page_number": 1},
]

# 步骤1: 提取x0
x0s_raw = [150, 100, 100, 120]

# 步骤2: 归一化
min_x0 = 100
width = 500
INDENT_TOL = 60
x0s = [[150], [100], [100], [100]]  # 120被归一化到100

# 步骤3: KMeans聚类
k=1: score = 0
k=2: score = -0.2  # 负数，说明2列不合适

best_k = 1

# 输出
boxes = [
    {"text": "标题", "x0": 150, "col_id": 0},
    {"text": "正文1", "x0": 100, "col_id": 0},
    {"text": "正文2", "x0": 100, "col_id": 0},
    {"text": "正文3", "x0": 120, "col_id": 0},
]
```

---

### B. 双栏文档

```python
# 输入
boxes = [
    {"text": "第1列第1段", "x0": 100, "page_number": 1},
    {"text": "第1列第2段", "x0": 120, "page_number": 1},
    {"text": "第2列第1段", "x0": 400, "page_number": 1},
    {"text": "第2列第2段", "x0": 420, "page_number": 1},
]

# 步骤1: 提取x0
x0s_raw = [100, 120, 400, 420]

# 步骤2: 归一化
min_x0 = 100
width = 500
INDENT_TOL = 60
x0s = [[100], [100], [400], [400]]  # 120和420被归一化

# 步骤3: KMeans聚类
k=1: score = 0
k=2: score = 0.95  # 高分，说明2列合适
k=3: score = 0.60
k=4: score = 0.40

best_k = 2

# 步骤4: 分配col_id
# KMeans: labels = [0, 0, 1, 1]
# centers = [100, 400]
# order = [0, 1]
# remap = {0: 0, 1: 1}

# 输出
boxes = [
    {"text": "第1列第1段", "x0": 100, "col_id": 0},
    {"text": "第1列第2段", "x0": 120, "col_id": 0},
    {"text": "第2列第1段", "x0": 400, "col_id": 1},
    {"text": "第2列第2段", "x0": 420, "col_id": 1},
]
```

---

### C. 混合列数文档

```python
# 输入：第1页单栏（标题页），第2页双栏（正文）
boxes = [
    {"text": "标题", "x0": 250, "page_number": 1},
    {"text": "第1列文本", "x0": 100, "page_number": 2},
    {"text": "第2列文本", "x0": 400, "page_number": 2},
]

# 第1页处理
x0s_raw = [250]
max_try = min(4, 1) = 1
best_k = 1
page_cols[1] = 1

# 第2页处理
x0s_raw = [100, 400]
k=1: score = 0
k=2: score = 0.95
best_k = 2
page_cols[2] = 2

# 全局投票
page_cols = {1: 1, 2: 2}
global_cols = 2  # 众数

# 输出
boxes = [
    {"text": "标题", "x0": 250, "page_number": 1, "col_id": 0},
    {"text": "第1列文本", "x0": 100, "page_number": 2, "col_id": 0},
    {"text": "第2列文本", "x0": 400, "page_number": 2, "col_id": 1},
]
```

---

## 六、应用场景

### A. 学术论文解析

```
┌──────────────────────────────────────┐
│ 摘要                                   │
│ xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx        │
└──────────────────────────────────────┘
┌────────────────┬─────────────────────┤
│ 第1列          │ 第2列               │
│ Introduction   │ Related Work        │
│ xxxxxxxxx      │ xxxxxxxxxxx         │
└────────────────┴─────────────────────┘

# 输出
第1页: col_id=0 (单栏)
第2页: col_id=0, col_id=1 (双栏)
```

---

### B. 报纸解析

```
┌──────┬──────┬──────┬──────┐
│ 第1列 │ 第2列 │ 第3列 │ 第4列 │
│ 新闻1 │ 新闻2 │ 新闻3 │ 新闻4 │
└──────┴──────┴──────┴──────┘

# 输出
boxes = [
    {"text": "新闻1", "col_id": 0},
    {"text": "新闻2", "col_id": 1},
    {"text": "新闻3", "col_id": 2},
    {"text": "新闻4", "col_id": 3},
]
```

---

### C. 多语言文档

```
┌─────────────────────────────────────┐
│ 英文部分（左对齐）                   │
│ xxxxxxxxxxxxxxxxxxxxxxxxxxx         │
│ 中文部分（首行缩进）                 │
│ 　　xxxxxxxxxxxxxxxxxxxxxxxxxx       │
└─────────────────────────────────────┘

# 缩进归一化后
x0s = [100, 100]  # 归一化为1列
```

---

## 七、与其他模块的协作

### A. 与 `_text_merge` 的协作

```python
def _text_merge(self, zoomin=3):
    bxs = self._assign_column(self.boxes, zoomin)  # 先分配col_id

    # 只合并同列的文本框
    while i < len(bxs) - 1:
        b = bxs[i]
        b_ = bxs[i + 1]

        if b.get("col_id") != b_.get("col_id"):  # 不同列
            i += 1
            continue

        # 合并同列的文本框
        if abs(self._y_dis(b, b_)) < self.mean_height[...] / 3:
            bxs[i]["text"] += b_["text"]
```

---

### B. 与 `_naive_vertical_merge` 的协作

```python
def _naive_vertical_merge(self, zoomin=3):
    bxs = self._assign_column(self.boxes, zoomin)

    # 按列分组
    grouped = defaultdict(list)
    for b in bxs:
        grouped[(b["page_number"], b.get("col_id", 0))].append(b)

    # 每列独立合并
    for (pg, col), bxs in grouped.items():
        # 垂直合并当前列的文本框
```

---

## 八、常见问题与调试

### A. 判数错误

**可能原因**：
1. 缩进容差不合适
2. 文本框数量太少
3. 特殊布局（如图片页）

**调试方法**：

```python
# 查看每页的识别结果
for pg, k in page_cols.items():
    print(f"Page {pg}: {k} columns")

# 查看轮廓系数
for k in range(1, max_try + 1):
    print(f"k={k}, score={score}")
```

---

### B. col_id顺序错误

**可能原因**：
- KMeans聚类中心的顺序不是从左到右

**解决方法**：

```python
# 代码中已实现：按聚类中心排序
centers = km.cluster_centers_.flatten()
order = np.argsort(centers)  # 升序排列

remap = {orig: new for new, orig in enumerate(order)}
```

---

### C. 性能问题

**优化方向**：

1. **缓存结果**：
   ```python
   if all("col_id" in b for b in boxes):
       return boxes  # 直接返回
   ```

2. **限制max_try**：
   ```python
   max_try = min(4, len(bxs))  # 最多尝试4列
   ```

3. **使用n_init="auto"**：
   ```python
   km = KMeans(n_clusters=k, n_init="auto")  # 自动选择最优初始化次数
   ```

---

## 九、总结

### 核心功能

`_assign_column` 是**文档列识别**的核心方法：

1. ✅ **按页分组**：每页独立处理，支持混合列数
2. ✅ **缩进容错**：12%页面宽度的容差，处理首行缩进
3. ✅ **KMeans聚类**：无监督学习，自动识别列数
4. ✅ **轮廓系数评估**：选择最佳列数（1-4列）
5. ✅ **全局投票**：取众数提高鲁棒性
6. ✅ **从左到右排序**：确保col_id=0是最左列

### 技术亮点

| 特性 | 说明 |
|------|------|
| **无监督学习** | KMeans + 轮廓系数 |
| **缩进归一化** | 消除首行缩进影响 |
| **按页处理** | 支持混合列数文档 |
| **全局投票** | 提高鲁棒性 |
| **可解释性** | 聚类中心对应物理位置 |

### 在解析流程中的位置

```
PDF文档
    ↓
OCR识别 (__images__)
    ↓
版面识别 (_layouts_rec)
    ↓
列识别 (_assign_column) ← 当前方法
    ↓
文本合并 (_text_merge / _naive_vertical_merge)
```

### 关键参数总结

| 参数 | 公式/值 | 作用 | 经验依据 |
|------|---------|------|----------|
| **INDENT_TOL** | width * 0.12 | 缩进容差 | 约2个中文字符宽度 |
| **max_try** | min(4, len(bxs)) | 最大尝试列数 | 大多数文档≤4列 |
| **best_k** | argmax(silhouette_score) | 最佳列数 | 轮廓系数最大 |
| **global_cols** | Counter(page_cols).most_common(1)[0][0] | 全局列数 | 众数投票 |

---

**文档版本**: v1.0
**创建日期**: 2025-12-28
**相关文件**:
- [源码位置](../../../../deepdoc/parser/pdf_parser.py#L447-L539)
- [KMeans聚类](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.KMeans.html)
- [轮廓系数](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.silhouette_score.html)
