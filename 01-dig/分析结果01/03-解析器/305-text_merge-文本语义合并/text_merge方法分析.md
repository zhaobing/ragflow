# _text_merge 方法完整解析

## 一、概要：方法签名/调用链路/整体结构

### A. 方法签名

```python
def _text_merge(self, zoomin=3):
    """
    水平方向合并相邻的文本框

    参数:
        zoomin (int): 缩放倍数，默认为3
                     用于传递给 _assign_column 方法

    作用:
        1. 为文本框分配列ID（col_id）
        2. 在同一列内，将水平相邻且在同一行的文本框合并
        3. 合并条件：同一页、同一列、同一layout、Y轴距离相近
    """
```

### B. 调用链路

```python
# 在解析流程中的位置
pdf_parser.py#__call__ ->
    __images__(fnm, zoomin)         # 1. OCR识别
    _layouts_rec(zoomin)            # 2. 版面识别
    _table_transformer_job(zoomin)  # 3. 表格识别
    _text_merge()                   # 4. 文本合并（当前方法）
    _concat_downward()              # 5. 跨页合并
    _filter_forpages()              # 6. 过滤

# 或在parse_into_bboxes中
pdf_parser.py#parse_into_bboxes ->
    __images__(fnm, zoomin)         # 1. OCR识别
    _layouts_rec(zoomin)            # 2. 版面识别
    _table_transformer_job(zoomin)  # 3. 表格识别
    _text_merge()                   # 4. 文本合并（当前方法）
    _concat_downward()              # 5. 跨页合并
    _naive_vertical_merge(zoomin)   # 6. 垂直合并
```

### C. 整体逻辑流程

```
┌─────────────────────────────────────────────────────┐
│ 1. 列识别与分配 (_assign_column)                     │
│    - 使用KMeans聚类识别文档列数                       │
│    - 为每个文本框分配col_id（列索引）                 │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│ 2. 定义辅助函数                                       │
│    - end_with: 判断文本框是否以指定字符串结尾         │
│    - start_with: 判断文本框是否以指定字符串开头       │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│ 3. 遍历相邻文本框对                                   │
│    - 检查是否满足合并条件：                           │
│      ✓ 同一页 (page_number)                         │
│      ✓ 同一列 (col_id)                              │
│      ✓ 同一layout (layoutno)                        │
│      ✓ 非特殊类型（非table/figure/equation）         │
│      ✓ Y轴距离 < mean_height / 3（同一行）           │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│ 4. 执行合并操作                                       │
│    - 扩展右边界: x1 = b_["x1"]                        │
│    - 平均垂直位置: top = (b["top"] + b_["top"]) / 2   │
│    - 平均垂直位置: bottom = (b["bottom"] + b_["bottom"]) / 2 │
│    - 拼接文本: text += b_["text"]                     │
│    - 删除被合并的框: bxs.pop(i + 1)                   │
└─────────────────────────────────────────────────────┘
```

---

## 二、业务逻辑

### A. 核心目标

**水平方向合并同一行内的相邻文本框**

在OCR识别和版面分析后，经常会出现以下情况：
- 一个完整的句子被OCR识别为多个文本框
- 例如："Hello World" 可能被识别为两个框："Hello" 和 "World"

`_text_merge` 的作用是将这些**相邻且在同一行**的文本框合并为一个。

### B. 与其他合并方法的区别

| 方法 | 合并方向 | 合并维度 | 使用场景 |
|------|---------|---------|----------|
| **_text_merge** | **水平** | 同一行内相邻框 | 将单词合并为句子 |
| **_naive_vertical_merge** | 垂直 | 上下相邻框 | 将句子合并为段落 |
| **_concat_downward** | 垂直 | 跨行跨页 | 使用XGBoost智能合并 |
| **_final_reading_order_merge** | 重排 | 调整阅读顺序 | 确保正确的阅读顺序 |

### C. 输入依赖

| 依赖项 | 来源 | 用途 |
|--------|------|------|
| `self.boxes` | `__images__()` 和 `_layouts_rec()` | OCR文本框列表 |
| `self.mean_height` | `__images__()` | 平均字符高度，用于判断是否同一行 |

### D. 输出结果

增强的 `self.boxes`，其中：
- 每个文本框添加了 `col_id` 字段（列索引）
- 同一行的相邻文本框被合并
- 文本更完整、连贯

---

## 三、执行流程详解

### 步骤1: 列识别与分配（[pdf_parser.py:535](deepdoc/parser/pdf_parser.py#L535)）

```python
def _text_merge(self, zoomin=3):
    # merge adjusted boxes
    bxs = self._assign_column(self.boxes, zoomin)
```

**`_assign_column` 方法详解**：

这是一个**基于KMeans聚类的列识别算法**，用于检测文档的列数（如单栏、双栏、三栏）。

#### 1.1 数据准备

```python
by_page = defaultdict(list)
for b in boxes:
    by_page[b["page_number"]].append(b)

for pg, bxs in by_page.items():
    x0s_raw = np.array([b["x0"] for b in bxs], dtype=float)
    min_x0 = np.min(x0s_raw)
    max_x1 = np.max([b["x1"] for b in bxs])
    width = max_x1 - min_x0
```

#### 1.2 缩进容错处理

```python
INDENT_TOL = width * 0.12  # 缩进容差为页面宽度的12%
x0s = []
for x in x0s_raw:
    if abs(x - min_x0) < INDENT_TOL:
        x0s.append([min_x0])  # 接近左边界的视为同一列
    else:
        x0s.append([x])
x0s = np.array(x0s, dtype=float)
```

**为什么需要缩进容错？**

```
示例：双栏文档
┌───────────────────────────────────────┐
│ 第1列文本                       第2列文本  │
│ 这是一段较长的文本          另一列文本  │
│ 可能会有缩进               这里也缩进  │
└───────────────────────────────────────┘

如果不处理缩进：
- "这是一段较长的文本" → x0 = 100
- "可能会有缩进"   → x0 = 120  (因为缩进)
- 会误识别为3列

处理缩进后：
- "这是一段较长的文本" → x0 = 100 → 归一化到100
- "可能会有缩进"   → x0 = 120 → 归一化到100 (因为 |120-100| < INDENT_TOL)
- 正确识别为1列
```

#### 1.3 最佳列数选择

```python
max_try = min(4, len(bxs))  # 最多尝试4列
if max_try < 2:
    max_try = 1
best_k = 1
best_score = -1

for k in range(1, max_try + 1):
    km = KMeans(n_clusters=k, n_init="auto")
    labels = km.fit_predict(x0s)

    centers = np.sort(km.cluster_centers_.flatten())
    if len(centers) > 1:
        score = silhouette_score(x0s, labels)  # 轮廓系数
    else:
        score = 0

    if score > best_score:
        best_score = best_score
        best_k = k

page_cols[pg] = best_k
```

**轮廓系数（Silhouette Score）**：
- 范围：[-1, 1]
- 接近1：聚类效果好（列之间分离明显）
- 接近0：聚类边界模糊
- 接近-1：聚类错误

#### 1.4 全局列数投票

```python
global_cols = Counter(page_cols.values()).most_common(1)[0][0]
```

**投票机制**：
- 每页独立判断列数
- 取众数作为全局列数
- 避免：第1页是双栏，第2页误判为单栏

#### 1.5 最终分配列ID

```python
for pg, bxs in by_page.items():
    k = page_cols[pg]
    if len(bxs) < k:
        k = 1  # 如果文本框数量 < 列数，强制为1列

    x0s = np.array([[b["x0"]] for b in bxs], dtype=float)
    km = KMeans(n_clusters=k, n_init="auto")
    labels = km.fit_predict(x0s)

    centers = km.cluster_centers_.flatten()
    order = np.argsort(centers)  # 按X轴排序

    remap = {orig: new for new, orig in enumerate(order)}

    for b, lb in zip(bxs, labels):
        b["col_id"] = remap[lb]  # 分配列ID（0, 1, 2, ...）
```

**示例**：

```python
# 原始文本框
boxes = [
    {"text": "第1列内容", "x0": 100},
    {"text": "第2列内容", "x0": 400},
    {"text": "第1列内容", "x0": 120},
    {"text": "第2列内容", "x0": 420},
]

# KMeans聚类（k=2）
centers = [110, 410]  # 两列的中心位置
labels = [0, 1, 0, 1]  # 每个框的列标签

# 分配col_id
boxes = [
    {"text": "第1列内容", "x0": 100, "col_id": 0},
    {"text": "第2列内容", "x0": 400, "col_id": 1},
    {"text": "第1列内容", "x0": 120, "col_id": 0},
    {"text": "第2列内容", "x0": 420, "col_id": 1},
]
```

---

### 步骤2: 定义辅助函数（[pdf_parser.py:537-544](deepdoc/parser/pdf_parser.py#L537-L544)）

```python
def end_with(b, txt):
    """
    判断文本框是否以指定字符串结尾

    参数:
        b: 文本框字典
        txt: 目标字符串

    返回:
        bool: 是否以txt结尾
    """
    txt = txt.strip()
    tt = b.get("text", "").strip()
    return tt and tt.find(txt) == len(tt) - len(txt)

def start_with(b, txts):
    """
    判断文本框是否以指定字符串列表中的任意一个开头

    参数:
        b: 文本框字典
        txts: 目标字符串列表

    返回:
        bool: 是否以txts中的任意一个开头
    """
    tt = b.get("text", "").strip()
    return tt and any([tt.find(t.strip()) == 0 for t in txts])
```

**注意**：这两个函数在 `_text_merge` 中定义但**未使用**，可能是：
1. 历史遗留代码
2. 为未来扩展预留

---

### 步骤3: 遍历并合并相邻文本框（[pdf_parser.py:546-568](deepdoc/parser/pdf_parser.py#L546-L568)）

```python
# horizontally merge adjacent box with the same layout
i = 0
while i < len(bxs) - 1:
    b = bxs[i]       # 当前文本框
    b_ = bxs[i + 1]  # 下一个文本框

    # 检查条件1: 同一页且同一列
    if b["page_number"] != b_["page_number"] or b.get("col_id") != b_.get("col_id"):
        i += 1
        continue

    # 检查条件2: 同一layout且非特殊类型
    if b.get("layoutno", "0") != b_.get("layoutno", "1") or b.get("layout_type", "") in ["table", "figure", "equation"]:
        i += 1
        continue

    # 检查条件3: Y轴距离相近（同一行）
    if abs(self._y_dis(b, b_)) < self.mean_height[bxs[i]["page_number"] - 1] / 3:
        # merge
        bxs[i]["x1"] = b_["x1"]
        bxs[i]["top"] = (b["top"] + b_["top"]) / 2
        bxs[i]["bottom"] = (b["bottom"] + b_["bottom"]) / 2
        bxs[i]["text"] += b_["text"]
        bxs.pop(i + 1)
        continue

    i += 1

self.boxes = bxs
```

#### 3.1 条件详解

**条件1: 同一页且同一列**

```python
if b["page_number"] != b_["page_number"] or b.get("col_id") != b_.get("col_id"):
    i += 1
    continue
```

- **page_number**: 必须在同一页
- **col_id**: 必须在同一列（由 `_assign_column` 分配）

**原因**：
- 不同页的文本框不能合并
- 不同列的文本框属于不同的阅读流

---

**条件2: 同一layout且非特殊类型**

```python
if b.get("layoutno", "0") != b_.get("layoutno", "1") or b.get("layout_type", "") in ["table", "figure", "equation"]:
    i += 1
    continue
```

- **layoutno**: 必须在同一个layout区域（由版面分析分配）
- **layout_type**: 排除表格、图片、公式

**原因**：
- 不同layout区域的文本框可能属于不同的内容块
- 表格、图片、公式应该保持独立，不应与文本合并

---

**条件3: Y轴距离相近（同一行）**

```python
if abs(self._y_dis(b, b_)) < self.mean_height[bxs[i]["page_number"] - 1] / 3:
    # merge
```

**`_y_dis` 方法计算**：

```python
def _y_dis(self, a, b):
    return (b["top"] + b["bottom"] - a["top"] - a["bottom"]) / 2
```

**几何意义**：

```
框a: top=100, bottom=120  → 中心Y = (100+120)/2 = 110
框b: top=115, bottom=135  → 中心Y = (115+135)/2 = 125

_y_dis(a, b) = (115 + 135 - 100 - 120) / 2
             = (250 - 220) / 2
             = 15
```

**阈值: mean_height / 3**

```python
# 示例
mean_height = 12  # 平均字符高度
threshold = 12 / 3 = 4  # Y轴距离阈值

# 如果 _y_dis(b, b_) < 4，则认为在同一行
```

**为什么是 mean_height / 3？**

- **太小（如 mean_height / 10）**: 无法合并稍微有高低差的文本框
- **太大（如 mean_height）**: 可能合并不同行的文本框
- **1/3 是经验值**: 既能容忍OCR的微小误差，又不会误合并

---

#### 3.2 合并操作详解

```python
# merge
bxs[i]["x1"] = b_["x1"]
bxs[i]["top"] = (b["top"] + b_["top"]) / 2
bxs[i]["bottom"] = (b["bottom"] + b_["bottom"]) / 2
bxs[i]["text"] += b_["text"]
bxs.pop(i + 1)
```

| 字段 | 合并前 | 合并后 | 说明 |
|------|--------|--------|------|
| **x1** | b["x1"] | b_["x1"] | 扩展右边界到第二个框的右边界 |
| **top** | b["top"] | (b["top"] + b_["top"]) / 2 | 取两者的平均，代表合并后的上边界 |
| **bottom** | b["bottom"] | (b["bottom"] + b_["bottom"]) / 2 | 取两者的平均，代表合并后的下边界 |
| **text** | b["text"] | b["text"] + b_["text"] | 直接拼接文本 |
| **列表操作** | - | bxs.pop(i + 1) | 删除第二个框（已被合并） |

**可视化示例**：

```
合并前:
┌──────────┐  ┌─────────┐
│  Hello   │  │  World! │
│  x1=200  │  │  x1=300 │
└──────────┘  └─────────┘

合并后:
┌──────────────────┐
│  Hello World!    │
│  x1=300          │
└──────────────────┘
```

---

## 四、技术要点

### A. Y轴距离计算

```python
def _y_dis(self, a, b):
    return (b["top"] + b["bottom"] - a["top"] - a["bottom"]) / 2
```

**几何解释**：

```
框a: ┌────────┐
    │        │ height_a = bottom_a - top_a
    └────────┘

框b:      ┌────────┐
          │        │ height_b = bottom_b - top_b
          └────────┘

_y_dis(a, b) = (中心Y_b - 中心Y_a)
             = ((top_b + bottom_b) / 2 - (top_a + bottom_a) / 2)
             = (top_b + bottom_b - top_a - bottom_a) / 2
```

**特点**：
- **正值**: b 在 a 下方
- **负值**: b 在 a 上方
- **0**: 完全水平对齐

---

### B. 使用while而非for循环

```python
i = 0
while i < len(bxs) - 1:
    # ...
    if 合并条件满足:
        bxs.pop(i + 1)
        continue  # 不增加i，继续检查新的bxs[i+1]
    i += 1
```

**为什么使用 while？**

1. **列表长度动态变化**：
   - 合并后会 `pop(i + 1)`，列表长度减少
   - for循环无法处理动态变化的列表

2. **链式合并**：
   ```python
   # 示例：3个框在同一行
   bxs = [box1, box2, box3]

   # 第1次循环: i=0
   # 合并 box1 和 box2
   bxs = [box1_合并, box3]

   # continue，i仍为0
   # 第2次循环: i=0
   # 检查 box1_合并 和 box3
   # 可能继续合并
   ```

---

### C. 阈值设计的合理性

| 阈值 | 值 | 作用 | 理由 |
|------|-----|------|------|
| **INDENT_TOL** | width * 0.12 | 缩进容错 | 12%的页面宽度可以容忍段落首行缩进 |
| **mean_height / 3** | ~4pt | 同一行判断 | 既能容忍OCR误差，又不会误合并 |
| **max_try** | min(4, len(bxs)) | 最大列数 | 大多数文档不超过4列 |

**实验验证**：

```python
# 场景1: 双栏论文
width = 500  # A4纸张宽度（约500pt）
INDENT_TOL = 500 * 0.12 = 60pt
# 可以容忍约2个汉字的缩进

# 场景2: 单行文本
mean_height = 12pt
threshold = 12 / 3 = 4pt
# 约为1/3个字符高度，可以容忍OCR的Y轴检测误差
```

---

### D. KMeans聚类参数选择

```python
km = KMeans(n_clusters=k, n_init="auto")
```

**参数说明**：
- **n_clusters=k**: 聚类数量（1到4）
- **n_init="auto"**: 自动选择初始化次数（默认为10）

**为什么使用KMeans？**

1. **简单高效**：O(nkt)，n为样本数，k为聚类数，t为迭代次数
2. **无监督**：不需要标注数据
3. **适合1D数据**：文本框的x0坐标是1维数据

**其他算法对比**：

| 算法 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **KMeans** | 简单、快速 | 需要预先指定k | 列数已知的文档 |
| **DBSCAN** | 自动发现聚类 | 对参数敏感 | 列数未知的文档 |
| **GMM** | 软聚类 | 计算复杂度高 | 需要概率的场景 |

---

### E. 边界情况处理

| 情况 | 处理方式 | 代码 |
|------|---------|------|
| **空列表** | `_assign_column` 直接返回 | `if not boxes: return boxes` |
| **只有1个框** | 无法合并，循环不执行 | `while i < len(bxs) - 1` |
| **col_id不存在** | 使用 `.get()` 避免KeyError | `b.get("col_id") != b_.get("col_id")` |
| **layoutno不存在** | 使用默认值 "0" 或 "1" | `b.get("layoutno", "0")` |
| **文本框数量 < 列数** | 强制为1列 | `if len(bxs) < k: k = 1` |

---

## 五、数据流示例

### A. 输入数据

```python
# 合并前
self.boxes = [
    {"text": "Hello", "x0": 100, "x1": 150, "top": 100, "bottom": 115, "page_number": 1, "layoutno": "0", "layout_type": "text"},
    {"text": "World!", "x0": 155, "x1": 200, "top": 102, "bottom": 117, "page_number": 1, "layoutno": "0", "layout_type": "text"},
    {"text": "This", "x0": 100, "x1": 130, "top": 150, "bottom": 165, "page_number": 1, "layoutno": "0", "layout_type": "text"},
    {"text": "is", "x0": 135, "x1": 155, "top": 152, "bottom": 167, "page_number": 1, "layoutno": "0", "layout_type": "text"},
    {"text": "a test.", "x0": 160, "x1": 220, "top": 151, "bottom": 166, "page_number": 1, "layoutno": "0", "layout_type": "text"},
]

self.mean_height[0] = 12  # 第1页的平均字符高度
```

### B. 执行过程

```python
# 步骤1: 列识别（假设单栏）
bxs = self._assign_column(self.boxes, zoomin)
# 所有框的 col_id = 0

# 步骤2: 遍历合并
i = 0
b = {"text": "Hello", ...}
b_ = {"text": "World!", ...}

# 检查条件1: 同一页且同一列 ✅
b["page_number"] == b_["page_number"]  # 1 == 1
b["col_id"] == b_["col_id"]            # 0 == 0

# 检查条件2: 同一layout且非特殊类型 ✅
b["layoutno"] == b_["layoutno"]        # "0" == "0"
b["layout_type"] != "table"            # "text" != "table"

# 检查条件3: Y轴距离
_y_dis(b, b_) = (102 + 117 - 100 - 115) / 2 = 2
threshold = 12 / 3 = 4
abs(2) < 4  # ✅ 满足条件

# 合并
bxs[0]["x1"] = 200
bxs[0]["top"] = (100 + 102) / 2 = 101
bxs[0]["bottom"] = (115 + 117) / 2 = 116
bxs[0]["text"] = "HelloWorld!"
bxs.pop(1)

# 列表变为:
bxs = [
    {"text": "HelloWorld!", "x0": 100, "x1": 200, "top": 101, "bottom": 116, ...},
    {"text": "This", ...},
    {"text": "is", ...},
    {"text": "a test.", ...},
]

# 继续循环...
```

### C. 输出数据

```python
# 合并后
self.boxes = [
    {"text": "HelloWorld!", "x0": 100, "x1": 200, "top": 101, "bottom": 116, "page_number": 1, "layoutno": "0", "layout_type": "text", "col_id": 0},
    {"text": "Thisis a test.", "x0": 100, "x1": 220, "top": 151, "bottom": 166, "page_number": 1, "layoutno": "0", "layout_type": "text", "col_id": 0},
]
```

---

## 六、应用场景

### A. 单栏文档

```python
# 输入: 单栏论文的OCR结果
boxes = [
    {"text": "This", "x0": 100},
    {"text": "is", "x0": 135},
    {"text": "a", "x0": 155},
    {"text": "sentence.", "x0": 170},
]

# 输出: 合并后的文本
boxes = [
    {"text": "Thisis a sentence.", "x0": 100, "x1": 250},
]
```

### B. 双栏文档

```python
# 输入: 双栏论文
boxes = [
    {"text": "第1列文本1", "x0": 100, "col_id": 0},
    {"text": "第1列文本2", "x0": 200, "col_id": 0},
    {"text": "第2列文本1", "x0": 400, "col_id": 1},
    {"text": "第2列文本2", "x0": 500, "col_id": 1},
]

# 输出: 按列合并
boxes = [
    {"text": "第1列文本1第1列文本2", "x0": 100, "x1": 250, "col_id": 0},
    {"text": "第2列文本1第2列文本2", "x0": 400, "x1": 550, "col_id": 1},
]
```

### C. 多栏文档（三栏）

```python
# 输入: 三栏文档（如小册子）
boxes = [
    {"text": "第1列", "x0": 50, "col_id": 0},
    {"text": "第2列", "x0": 250, "col_id": 1},
    {"text": "第3列", "x0": 450, "col_id": 2},
]

# 输出: 保持三列独立
boxes = [
    {"text": "第1列", "col_id": 0},
    {"text": "第2列", "col_id": 1},
    {"text": "第3列", "col_id": 2},
]
```

---

## 七、与其他模块的协作

### A. 与 `_layouts_rec` 的协作

```python
# _layouts_rec 提供 layoutno
self.boxes = [
    {"text": "...", "layoutno": "0", "layout_type": "text"},  # 第1个layout区域
    {"text": "...", "layoutno": "0", "layout_type": "text"},  # 第1个layout区域
    {"text": "...", "layoutno": "1", "layout_type": "text"},  # 第2个layout区域
]

# _text_merge 使用 layoutno
# 只有 layoutno 相同的文本框才能合并
# 例如：layoutno="0" 的框可以合并，但不能与 layoutno="1" 的框合并
```

### B. 与 `_table_transformer_job` 的协作

```python
# _table_transformer_job 标注表格结构
self.boxes = [
    {"text": "Name", "layout_type": "table", "R": 0, "C": 0},
    {"text": "Price", "layout_type": "table", "R": 0, "C": 1},
]

# _text_merge 排除表格
if b.get("layout_type", "") in ["table", "figure", "equation"]:
    i += 1
    continue  # 不合并表格内的文本框
```

### C. 与 `_naive_vertical_merge` 的协作

```python
# _text_merge 先执行水平合并
self.boxes = _text_merge()
# → "Hello" + "World!" = "HelloWorld!"

# _naive_vertical_merge 后执行垂直合并
self.boxes = _naive_vertical_merge()
# → "HelloWorld!" + "\n" + "This is a test." = "HelloWorld!\nThis is a test."
```

---

## 八、常见问题与调试

### A. 文本框未合并

**可能原因**：
1. Y轴距离超过阈值
2. 不在同一列
3. 不在同一layout
4. 是特殊类型（表格/图片/公式）

**调试方法**：

```python
# 检查1: 查看Y轴距离
for i in range(len(bxs) - 1):
    b, b_ = bxs[i], bxs[i + 1]
    y_dis = abs(self._y_dis(b, b_))
    threshold = self.mean_height[b["page_number"] - 1] / 3
    print(f"Y距离: {y_dis}, 阈值: {threshold}, 是否合并: {y_dis < threshold}")

# 检查2: 查看列ID
for b in bxs:
    print(f"文本: {b['text']}, 列ID: {b.get('col_id', None)}")

# 检查3: 查看layout信息
for b in bxs:
    print(f"文本: {b['text']}, layoutno: {b.get('layoutno', None)}, type: {b.get('layout_type', None)}")
```

### B. 错误合并

**可能原因**：
1. 阈值太大
2. 列识别错误
3. layout分配错误

**调试方法**：

```python
# 降低阈值，减少误合并
if abs(self._y_dis(b, b_)) < self.mean_height[bxs[i]["page_number"] - 1] / 5:  # 从3改为5
    # merge
```

### C. 性能问题

**优化方向**：

1. **减少KMeans调用次数**：
   ```python
   # 如果所有框都有col_id，跳过分配
   if all("col_id" in b for b in boxes):
       return boxes
   ```

2. **限制合并范围**：
   ```python
   # 只检查相邻的几个框，而不是整个列表
   for i in range(len(bxs) - 1):
       if i > 0 and bxs[i]["top"] - bxs[i-1]["top"] > threshold * 2:
           break  # 超过阈值，停止合并
   ```

---

## 九、总结

### 核心功能

`_text_merge` 是PDF解析流程中**水平文本合并**的关键步骤：

1. ✅ **列识别**: 使用KMeans聚类识别文档列数
2. ✅ **列分配**: 为每个文本框分配 `col_id`
3. ✅ **水平合并**: 在同一列内，合并同一行的相邻文本框
4. ✅ **智能过滤**: 排除表格、图片、公式等特殊类型

### 技术亮点

| 特性 | 说明 |
|------|------|
| **无监督列识别** | 使用KMeans + 轮廓系数自动识别列数 |
| **缩进容错** | 12%页面宽度的容差，处理段落首行缩进 |
| **多条件合并** | 页、列、layout、Y轴距离四重条件 |
| **链式合并** | while循环支持连续合并多个框 |
| **鲁棒性** | 完善的边界情况处理 |

### 在解析流程中的位置

```
PDF文档
    ↓
__images__ (OCR识别)
    ↓
_layouts_rec (版面识别)
    ↓
_table_transformer_job (表格识别)
    ↓
_text_merge (水平文本合并) ← 当前方法
    ↓
_concat_downward (跨页合并)
    ↓
_filter_forpages (过滤)
```

### 与其他合并方法的对比

| 方法 | 方向 | 触发条件 | 算法 | 复杂度 |
|------|------|----------|------|--------|
| **_text_merge** | 水平 | Y轴距离 < mean_height/3 | 规则 | O(n) |
| **_naive_vertical_merge** | 垂直 | 多种特征（标点、距离、重叠） | 规则 | O(n) |
| **_concat_downward** | 垂直 | XGBoost模型预测 | 机器学习 | O(n²) |

---

**文档版本**: v1.0
**创建日期**: 2025-12-28
**相关文件**:
- [源码位置](../../../../deepdoc/parser/pdf_parser.py#L533-L569)
- [_assign_column方法](../../../../deepdoc/parser/pdf_parser.py#L447-L531)
- [KMeans聚类](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.KMeans.html)
- [轮廓系数](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.silhouette_score.html)
