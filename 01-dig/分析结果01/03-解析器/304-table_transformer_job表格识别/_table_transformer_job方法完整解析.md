# _table_transformer_job 方法完整解析

## 一、概要：方法签名/调用链路/整体结构

### A. 方法签名

```python
def _table_transformer_job(self, ZM):
    """
    表格结构识别与标注

    参数:
        ZM (int): 缩放倍数（zoomin），默认为3
                  用于将PDF坐标转换为高分辨率图像像素坐标

    作用:
        1. 裁剪表格区域的图像
        2. 调用TableStructureRecognizer识别表格内部结构
        3. 将识别结果映射到OCR文本框
        4. 为表格内的文本框标注行列、表头、跨行等结构信息
    """
```

### B. 调用链路

```python
# 在解析流程中的位置
pdf_parser.py#__call__ ->
    _layouts_rec(zoomin)           # 先进行版面识别
    _table_transformer_job(zoomin) # 再进行表格结构识别
    _text_merge()                   # 最后合并文本

# 或在parse_into_bboxes中
pdf_parser.py#parse_into_bboxes ->
    __images__(fnm, zoomin)         # 1. OCR识别
    _layouts_rec(zoomin)            # 2. 版面识别
    _table_transformer_job(zoomin)  # 3. 表格识别
    _text_merge()                   # 4. 文本合并
```

### C. 整体逻辑流程

```
┌─────────────────────────────────────────────────────┐
│ 1. 准备表格图像                                       │
│    - 从page_layout提取所有table类型的layout          │
│    - 裁剪表格区域（带MARGIN=10像素边距）              │
│    - 坐标缩放：PDF坐标 × ZM → 图像像素坐标            │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│ 2. 批量表格结构识别                                   │
│    - 调用self.tbl_det(imgs)                         │
│    - 输入：表格区域图像列表                           │
│    - 输出：表格组件（行、列、表头、跨行单元格等）     │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│ 3. 坐标映射与累积                                      │
│    - 坐标恢复：图像像素坐标 + 裁剪位置                 │
│    - 坐标归一化：像素坐标 / ZM → PDF坐标              │
│    - 跨页累积：top += page_cum_height[page_no]       │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│ 4. 提取表格组件                                        │
│    - headers: 表头区域（.*header$）                   │
│    - rows: 行区域（.* (row|header)）                  │
│    - spans: 跨行单元格（.*spanning）                  │
│    - clmns: 列区域（table column$）                  │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│ 5. 为OCR文本框标注结构信息                            │
│    - R: 所属行的索引                                  │
│    - R_top, R_bott: 行的顶部和底部边界                │
│    - H: 表头的索引                                    │
│    - H_top, H_bott: 表头的顶部和底部边界              │
│    - H_left, H_right: 表头的左右边界                  │
│    - C: 列的索引                                      │
│    - C_left, C_right: 列的左右边界                   │
│    - SP: 跨行单元格的索引                             │
└─────────────────────────────────────────────────────┘
```

---

## 二、业务逻辑

### A. 核心目标

在已经完成OCR文本识别和版面分析的基础上，对检测到的表格区域进行**细粒度结构识别**，并将结构信息标注到OCR文本框上，为后续的表格理解和重建提供基础。

### B. 输入依赖

该方法依赖于以下前置步骤的完成：

| 依赖项 | 来源 | 用途 |
|--------|------|------|
| `self.page_layout` | `_layouts_rec()` | 提供表格区域的位置信息 |
| `self.page_images` | `__images__()` | 提供页面图像用于裁剪表格 |
| `self.page_cum_height` | `__images__()` | 用于跨页坐标累积 |
| `self.boxes` | `__images__()` | OCR文本框，将被标注结构信息 |

### C. 输出结果

1. **self.tb_cpns**: 表格组件列表
   - 包含所有识别出的行、列、表头、跨行单元格等
   - 每个组件有：`x0, x1, top, bottom, pn, layoutno, label`

2. **self.boxes 的增强**: 为`layout_type="table"`的文本框添加结构标注
   - `R`: 行索引
   - `H`: 表头索引
   - `C`: 列索引
   - `SP`: 跨行单元格索引
   - 以及对应的边界坐标

---

## 三、执行流程详解

### 步骤1: 准备表格图像（[pdf_parser.py:202-221](../../../../../deepdoc/parser/pdf_parser.py#L202-L221)）

```python
def _table_transformer_job(self, ZM):
    logging.debug("Table processing...")
    imgs, pos = [], []
    tbcnt = [0]
    MARGIN = 10
    self.tb_cpns = []
    assert len(self.page_layout) == len(self.page_images)

    # 遍历每一页的版面布局
    for p, tbls in enumerate(self.page_layout):  # for page
        # 1.1 筛选出table类型的layout
        tbls = [f for f in tbls if f["type"] == "table"]
        tbcnt.append(len(tbls))

        if not tbls:
            continue

        # 1.2 遍历当前页的每个表格
        for tb in tbls:  # for table
            # 计算裁剪区域（带10像素边距）
            left, top, right, bott = tb["x0"] - MARGIN, tb["top"] - MARGIN, tb["x1"] + MARGIN, tb["bottom"] + MARGIN

            # 1.3 坐标缩放：PDF坐标 → 图像像素坐标
            left *= ZM
            top *= ZM
            right *= ZM
            bott *= ZM

            # 1.4 记录裁剪位置和裁剪图像
            pos.append((left, top))
            imgs.append(self.page_images[p].crop((left, top, right, bott)))
```

**关键点说明**：

1. **MARGIN=10的作用**:
   - 确保表格边框完整包含在裁剪区域内
   - 防止边框被裁切导致结构识别失败

2. **坐标缩放（×ZM）**:
   ```python
   # PDF坐标系: 72 DPI (points)
   # 图像坐标系: 216 DPI (pixels, zoomin=3时)
   # 转换公式: pixel = point × ZM

   # 示例：
   # PDF坐标: (100, 200, 400, 500)
   # 缩放后:   (300, 600, 1200, 1500)  # ZM=3
   ```

3. **tbcnt数组的作用**:
   ```python
   # 记录每页的表格数量，用于后续分页
   # 例如: [0, 2, 3, 1, 0, 4]
   # 含义: 第0页0个表，第1页2个表，第2页3个表...

   # 后续通过cumsum转为累积索引
   # [0, 2, 5, 6, 6, 10]
   # 用于切片: recos[tbcnt[i]:tbcnt[i+1]]
   ```

---

### 步骤2: 批量表格结构识别（[pdf_parser.py:223-226](../../../../../deepdoc/parser/pdf_parser.py#L223-L226)）

```python
assert len(self.page_images) == len(tbcnt) - 1
if not imgs:
    return

# 调用TableStructureRecognizer批量识别表格结构
recos = self.tbl_det(imgs)
```

**TableStructureRecognizer**：

| 特性 | 说明 |
|------|------|
| **模型** | Table Structure Recognition (TSR) |
| **模型文件** | tsr.onnx |
| **输入** | 表格区域图像（带边距） |
| **输出** | 表格组件列表，每个组件包含： |
| | - `label`: 组件类型（table row header, table column, spanning cell等） |
| | - `bbox`: 边界框 [x0, y0, x1, y1] |
| | - `score`: 置信度 |

**输出示例**：
```python
recos = [
    [  # 第1个表格的组件
        {"label": "table row header", "bbox": [10, 10, 390, 30], "score": 0.95},
        {"label": "table row", "bbox": [10, 30, 390, 50], "score": 0.92},
        {"label": "table row", "bbox": [10, 50, 390, 70], "score": 0.89},
        {"label": "table column", "bbox": [10, 10, 100, 70], "score": 0.88},
        {"label": "table column", "bbox": [100, 10, 200, 70], "score": 0.86},
        # ...
    ],
    [  # 第2个表格的组件
        # ...
    ],
]
```

---

### 步骤3: 坐标映射与累积（[pdf_parser.py:227-244](../../../../../deepdoc/parser/pdf_parser.py#L227-L244)）

```python
# 转换为累积索引
tbcnt = np.cumsum(tbcnt)
# 例如: [0, 2, 5, 6, 6, 10]
#       ↑  ↑  ↑  ↑  ↑   ↑
#       第 第 第 第 第   第
#       0  1  2  3  4   5
#       页 页 页 页 页   页
#       的 的 的 的 的   的
#       累 累 累 累 累   累
#       积 积 积 积 积   积
#       索 索 索 索 索   索
#       引 引 引 引 引   引

# 遍历每一页
for i in range(len(tbcnt) - 1):  # for page
    pg = []

    # 3.1 提取当前页的表格识别结果
    for j, tb_items in enumerate(recos[tbcnt[i] : tbcnt[i + 1]]):  # for table
        # 提取当前页的裁剪位置
        poss = pos[tbcnt[i] : tbcnt[i + 1]]

        # 3.2 遍历表格的每个组件
        for it in tb_items:  # for table components
            # 3.3 坐标恢复：加上裁剪偏移
            it["x0"] = it["x0"] + poss[j][0]  # 加上left
            it["x1"] = it["x1"] + poss[j][0]
            it["top"] = it["top"] + poss[j][1]  # 加上top
            it["bottom"] = it["bottom"] + poss[j][1]

            # 3.4 坐标归一化：像素坐标 / ZM → PDF坐标
            for n in ["x0", "x1", "top", "bottom"]:
                it[n] /= ZM

            # 3.5 跨页累积：加上之前页面的累积高度
            it["top"] += self.page_cum_height[i]
            it["bottom"] += self.page_cum_height[i]

            # 3.6 添加元信息
            it["pn"] = i           # 页码
            it["layoutno"] = j     # 表格索引（当前页第j个表）
            pg.append(it)

    # 3.7 将当前页的组件添加到全局列表
    self.tb_cpns.extend(pg)
```

**坐标转换示例**：

```python
# 假设识别结果（裁剪区域内的相对坐标）
it = {"bbox": [10, 20, 390, 70]}  # 在裁剪图像内
poss[j] = (300, 600)              # 裁剪位置 (left, top)，像素坐标
ZM = 3
page_cum_height[i] = 1000         # 前i页的累积高度，PDF坐标

# 步骤3.3: 加上裁剪偏移
it["x0"] = 10 + 300 = 310
it["top"] = 20 + 600 = 620
# → 在页面图像中的绝对坐标: [310, 620, 690, 770]

# 步骤3.4: 除以ZM归一化
it["x0"] = 310 / 3 = 103.33
it["top"] = 620 / 3 = 206.67
# → 在当前页的PDF坐标: [103.33, 206.67, 230, 256.67]

# 步骤3.5: 加上累积高度
it["top"] = 206.67 + 1000 = 1206.67
it["bottom"] = 256.67 + 1000 = 1256.67
# → 在整个PDF文档的绝对坐标: [103.33, 1206.67, 230, 1256.67]
```

---

### 步骤4: 提取表格组件（[pdf_parser.py:246-256](../../../../../deepdoc/parser/pdf_parser.py#L246-L256)）

```python
def gather(kwd, fzy=10, ption=0.6):
    """
    辅助函数：收集特定类型的表格组件

    参数:
        kwd: 正则表达式，匹配组件的label
        fzy: Y轴排序的模糊阈值（默认10）
        ption: layout_cleanup的重叠阈值（默认0.6）

    返回:
        排序并清理后的组件列表
    """
    # 4.1 筛选匹配的组件
    eles = Recognizer.sort_Y_firstly(
        [r for r in self.tb_cpns if re.match(kwd, r["label"])],
        fzy
    )
    # 4.2 清理与OCR文本框重叠的组件
    eles = Recognizer.layouts_cleanup(self.boxes, eles, 5, ption)
    # 4.3 再次按Y轴排序
    return Recognizer.sort_Y_firstly(eles, 0)

# 4.4 提取各类组件
headers = gather(r".*header$")           # 表头: "table row header"
rows = gather(r".* (row|header)")        # 行和表头
spans = gather(r".*spanning")            # 跨行单元格: "table spanning cell"
clmns = sorted([                         # 列
    r for r in self.tb_cpns if re.match(r"table column$", r["label"])
], key=lambda x: (x["pn"], x["layoutno"], x["x0"]))

# 4.5 列组件需要特殊处理（X轴排序）
clmns = Recognizer.layouts_cleanup(self.boxes, clmns, 5, 0.5)
```

**组件类型说明**：

| Label | 含义 | 示例 |
|-------|------|------|
| `table row header` | 表头行 | 包含列名的那一行 |
| `table row` | 数据行 | 表格的普通行 |
| `table column` | 列区域 | 垂直方向的列 |
| `table spanning cell` | 跨行单元格 | 合并的单元格（跨多行） |

**gather函数的优化**：

1. **sort_Y_firstly**: 按Y轴排序，同时考虑行内顺序
2. **layouts_cleanup**: 移除与OCR文本框重叠的组件（避免冲突）
3. **再次排序**: 确保最终顺序正确

---

### 步骤5: 为OCR文本框标注结构信息（[pdf_parser.py:257-286](../../../../../deepdoc/parser/pdf_parser.py#L257-L286)）

```python
# add R,H,C,SP tag to boxes within table layout
# 为表格内的OCR文本框添加行列、表头、跨行等标签

# 遍历所有OCR文本框
for b in self.boxes:
    # 5.1 只处理表格内的文本框
    if b.get("layout_type", "") != "table":
        continue

    # 5.2 标注行信息 (R = Row)
    ii = Recognizer.find_overlapped_with_threshold(b, rows, thr=0.3)
    if ii is not None:
        b["R"] = ii               # 行索引（在rows列表中的位置）
        b["R_top"] = rows[ii]["top"]       # 行的顶部边界
        b["R_bott"] = rows[ii]["bottom"]   # 行的底部边界

    # 5.3 标注表头信息 (H = Header)
    ii = Recognizer.find_overlapped_with_threshold(b, headers, thr=0.3)
    if ii is not None:
        b["H_top"] = headers[ii]["top"]
        b["H_bott"] = headers[ii]["bottom"]
        b["H_left"] = headers[ii]["x0"]
        b["H_right"] = headers[ii]["x1"]
        b["H"] = ii               # 表头索引

    # 5.4 标注列信息 (C = Column)
    # 使用find_horizontally_tightest_fit找到最紧密的列
    ii = Recognizer.find_horizontally_tightest_fit(b, clmns)
    if ii is not None:
        b["C"] = ii               # 列索引
        b["C_left"] = clmns[ii]["x0"]
        b["C_right"] = clmns[ii]["x1"]

    # 5.5 标注跨行单元格信息 (SP = Spanning)
    ii = Recognizer.find_overlapped_with_threshold(b, spans, thr=0.3)
    if ii is not None:
        b["H_top"] = spans[ii]["top"]
        b["H_bott"] = spans[ii]["bottom"]
        b["H_left"] = spans[ii]["x0"]
        b["H_right"] = spans[ii]["x1"]
        b["SP"] = ii              # 跨行单元格索引
```

**标注示例**：

```python
# 原始OCR文本框
{
    "text": "Product Name",
    "x0": 110, "x1": 200,
    "top": 1210, "bottom": 1230,
    "layout_type": "table",
    "page_number": 2
}

# 标注后的文本框
{
    "text": "Product Name",
    "x0": 110, "x1": 200,
    "top": 1210, "bottom": 1230,
    "layout_type": "table",
    "page_number": 2,
    # 新增标注
    "R": 0,                    # 第0行（表头行）
    "R_top": 1206.67,          # 行的顶部
    "R_bott": 1256.67,         # 行的底部
    "H": 0,                    # 第0个表头
    "H_top": 1206.67,          # 表头的顶部
    "H_bott": 1256.67,         # 表头的底部
    "H_left": 103.33,          # 表头的左边界
    "H_right": 396.67,         # 表头的右边界
    "C": 0,                    # 第0列
    "C_left": 103.33,          # 列的左边界
    "C_right": 200.0           # 列的右边界
}
```

**关键方法说明**：

1. **find_overlapped_with_threshold**:
   - 找到与文本框重叠度最大的组件
   - 阈值0.3：至少30%的重叠才认为关联

2. **find_horizontally_tightest_fit**:
   - 专用于列的匹配
   - 找到水平方向最紧密包围文本框的列

---

## 四、技术要点

### A. 坐标系统转换

**三重坐标系转换**：

```python
# 1. 裁剪区域内的相对坐标
it["bbox"] = [10, 20, 390, 70]  # 在裁剪图像内
#           ↓ 加上裁剪偏移 (poss[j])
# 2. 页面图像的绝对坐标
it["bbox"] = [310, 620, 690, 770]  # 在页面图像内
#           ↓ 除以ZM
# 3. 当前页的PDF坐标
it["bbox"] = [103.33, 206.67, 230, 256.67]  # 在当前页
#           ↓ 加上page_cum_height
# 4. 整个PDF文档的绝对坐标
it["bbox"] = [103.33, 1206.67, 230, 1256.67]  # 在整个文档
```

**为什么需要跨页累积**？

```python
# 示例：3页的PDF
page_cum_height = [0, 1000, 2000, 3000]
#                  ↑   ↑     ↑     ↑
#                  第   第1    第2    第3
#                  0   页末    页末    页末
#                  页   尾      尾      尾
#                  起

# 第1页的表格行
it["top"] = 100
it["bottom"] = 150
# 加上page_cum_height[1] = 1000
# → it["top"] = 1100, it["bottom"] = 1150

# 第2页的表格行
it["top"] = 50
it["bottom"] = 100
# 加上page_cum_height[2] = 2000
# → it["top"] = 2050, it["bottom"] = 2100
```

### B. 边距处理（MARGIN=10）

```python
MARGIN = 10  # 像素（缩放前）

# 缩放后
MARGIN_zoomed = MARGIN * ZM  # 30像素（ZM=3时）

# 为什么需要边距？
# 1. 表格边框可能在检测边界外
# 2. TSR模型需要完整的表格上下文
# 3. 防止重要信息被裁切
```

### C. 组件筛选与排序

**gather函数的三步处理**：

```python
# 步骤1: 按Y轴排序（考虑行内顺序）
eles = Recognizer.sort_Y_firstly(filtered_components, fzy=10)
# sort_Y_firstly的逻辑：
# - 主要按Y轴（top）排序
# - 如果Y轴差异 < fzy，则按X轴排序
# - 这样可以保持从左到右、从上到下的阅读顺序

# 步骤2: 清理重叠组件
eles = Recognizer.layouts_cleanup(self.boxes, eles, 5, 0.6)
# layouts_cleanup的逻辑：
# - 移除与OCR文本框重叠 > 60% 的组件
# - 避免表格组件与OCR文本框冲突

# 步骤3: 再次排序（确保顺序）
eles = Recognizer.sort_Y_firstly(eles, fzy=0)
# fzy=0: 严格按Y轴排序，不考虑行内顺序
```

### D. 多种匹配策略

| 组件类型 | 匹配方法 | 阈值 | 原因 |
|---------|---------|------|------|
| **rows** | `find_overlapped_with_threshold` | 0.3 | 允许部分重叠（行可能不完全覆盖） |
| **headers** | `find_overlapped_with_threshold` | 0.3 | 表头通常较大，部分重叠即可 |
| **spans** | `find_overlapped_with_threshold` | 0.3 | 跨行单元格可能只覆盖部分文本 |
| **clmns** | `find_horizontally_tightest_fit` | - | 列需要水平方向紧密匹配 |

**find_horizontally_tightest_fit的优势**：

```python
# 假设有两列：
clmn1 = {"x0": 100, "x1": 200}  # 第1列
clmn2 = {"x0": 200, "x1": 300}  # 第2列

# 文本框
box = {"x0": 150, "x1": 180}  # 在第1列内

# find_overlapped_with_threshold可能匹配到两列（都重叠）
# find_horizontally_tightest_fit会选择最紧密的第1列
```

### E. 错误处理

```python
# 1. 空表格检查
if not imgs:
    return

# 2. 断言检查
assert len(self.page_layout) == len(self.page_images)
assert len(self.page_images) == len(tbcnt) - 1

# 3. 索引安全
for i in range(len(tbcnt) - 1):  # 不越界
    for j, tb_items in enumerate(recos[tbcnt[i] : tbcnt[i + 1]]):
        # 使用enumerate确保j在合法范围内
```

---

## 五、数据结构示例

### A. 输入数据

```python
# self.page_layout (来自_layouts_rec)
[
    [  # 第0页
        {"type": "title", "x0": 100, "x1": 500, "top": 50, "bottom": 80},
        {"type": "table", "x0": 100, "x1": 500, "top": 100, "bottom": 300},
        {"type": "text", "x0": 100, "x1": 500, "top": 350, "bottom": 500},
    ],
    [  # 第1页
        {"type": "table", "x0": 100, "x1": 500, "top": 50, "bottom": 250},
        # ...
    ],
]

# self.page_images (来自__images__)
[
    <PIL.Image size=(2480, 3508)>,  # 第0页图像 (216 DPI)
    <PIL.Image size=(2480, 3508)>,  # 第1页图像
]

# self.page_cum_height (来自__images__)
[0, 1169.33, 2338.67]  # 每页高度的累积值

# self.boxes (来自__images__)
[
    [  # 第0页的OCR文本框
        {"text": "Title", "x0": 100, "x1": 200, "top": 50, "bottom": 80, "layout_type": "title"},
        {"text": "Name", "x0": 110, "x1": 200, "top": 110, "bottom": 130, "layout_type": "table"},
        {"text": "Price", "x0": 210, "x1": 300, "top": 110, "bottom": 130, "layout_type": "table"},
        # ...
    ],
    # ...
]
```

### B. 中间数据

```python
# imgs - 裁剪的表格图像
[
    <PIL.Image size=(1200, 600)>,  # 第1个表格 (left=300, top=300)
    <PIL.Image size=(1200, 600)>,  # 第2个表格
]

# pos - 裁剪位置
[
    (300, 300),  # 第1个表格的(left, top)
    (300, 150),  # 第2个表格的(left, top)
]

# tbcnt - 每页表格数量
[0, 1, 3, 3, 3]  # 第0页0个，第1页1个，第2页2个，...

# tbcnt (cumsum) - 累积索引
[0, 1, 4, 7, 10]  # 用于切片
```

### C. TSR输出（recos）

```python
recos = [
    [  # 第1个表格的组件
        {"label": "table row header", "bbox": [10, 10, 1190, 40], "score": 0.95},
        {"label": "table row", "bbox": [10, 40, 1190, 70], "score": 0.92},
        {"label": "table row", "bbox": [10, 70, 1190, 100], "score": 0.89},
        {"label": "table column", "bbox": [10, 10, 400, 100], "score": 0.88},
        {"label": "table column", "bbox": [400, 10, 800, 100], "score": 0.86},
        {"label": "table column", "bbox": [800, 10, 1190, 100], "score": 0.84},
    ],
    [  # 第2个表格的组件
        # ...
    ],
]
```

### D. 最终输出（self.tb_cpns）

```python
self.tb_cpns = [
    {
        "label": "table row header",
        "x0": 110.0,  # (10+300)/3 + 0
        "x1": 496.67, # (1190+300)/3
        "top": 110.0, # (10+300)/3 + 0
        "bottom": 123.33,  # (40+300)/3
        "pn": 1,  # 第1页
        "layoutno": 0,  # 该页第0个表
    },
    {
        "label": "table row",
        "x0": 110.0,
        "x1": 496.67,
        "top": 123.33,
        "bottom": 136.67,
        "pn": 1,
        "layoutno": 0,
    },
    # ...
]
```

### E. 增强后的self.boxes

```python
self.boxes = [
    # ...
    {
        "text": "Name",
        "x0": 110,
        "x1": 200,
        "top": 110,  # 相对坐标
        "bottom": 130,
        "layout_type": "table",
        "page_number": 1,
        # 新增标注
        "R": 0,  # 第0行（表头）
        "R_top": 110.0,
        "R_bott": 123.33,
        "H": 0,  # 第0个表头
        "H_top": 110.0,
        "H_bott": 123.33,
        "H_left": 110.0,
        "H_right": 496.67,
        "C": 0,  # 第0列
        "C_left": 110.0,
        "C_right": 400.0,
    },
    {
        "text": "Price",
        "x0": 410,
        "x1": 500,
        "top": 110,
        "bottom": 130,
        "layout_type": "table",
        "page_number": 1,
        # 新增标注
        "R": 0,  # 同样在第0行
        "R_top": 110.0,
        "R_bott": 123.33,
        "H": 0,
        "H_top": 110.0,
        "H_bott": 123.33,
        "H_left": 110.0,
        "H_right": 496.67,
        "C": 1,  # 第1列
        "C_left": 400.0,
        "C_right": 800.0,
    },
    {
        "text": "Apple",
        "x0": 110,
        "x1": 200,
        "top": 123.33,
        "bottom": 143.33,
        "layout_type": "table",
        "page_number": 1,
        # 新增标注
        "R": 1,  # 第1行（数据行）
        "R_top": 123.33,
        "R_bott": 136.67,
        "C": 0,
        "C_left": 110.0,
        "C_right": 400.0,
        # 没有H（不在表头内）
    },
    # ...
]
```

---

## 六、性能优化要点

### A. 批量处理

```python
# 不推荐：逐个表格识别
for tb_img in imgs:
    result = self.tbl_det([tb_img])  # 每次只处理1个

# 推荐：批量识别
recos = self.tbl_det(imgs)  # 一次处理所有表格
# 优势：
# - GPU利用率更高
# - 减少模型加载开销
# - 批处理加速（通常2-5倍）
```

### B. 索引优化

```python
# 使用累积索引避免嵌套循环
tbcnt = np.cumsum(tbcnt)  # [0, 1, 4, 7, 10]

# 快速切片
for i in range(len(tbcnt) - 1):
    page_tables = recos[tbcnt[i]:tbcnt[i+1]]  # O(1)切片

# 而不是
for i in range(len(tbcnt) - 1):
    # 需要遍历前面的所有页才知道当前页的表格
    start_idx = sum(tbcnt[:i+1])  # O(n)求和
```

### C. 列表推导式

```python
# 推荐：使用列表推导式筛选
tbls = [f for f in tbls if f["type"] == "table"]
headers = [r for r in self.tb_cpns if re.match(r".*header$", r["label"])]

# 而不是
tbls = []
for f in tbls:
    if f["type"] == "table":
        tbls.append(f)
```

### D. 避免重复计算

```python
# 推荐：预先计算并缓存
poss = pos[tbcnt[i] : tbcnt[i + 1]]  # 提取一次
for j, tb_items in enumerate(recos[tbcnt[i] : tbcnt[i + 1]]):
    # 使用poss[j]而不是重复查询pos[tbcnt[i] + j]

# 而不是
for j, tb_items in enumerate(recos[tbcnt[i] : tbcnt[i + 1]]):
    left_top = pos[tbcnt[i] + j]  # 每次都计算索引
```

---

## 七、应用场景

### A. 表格理解

```python
# 识别表格结构后，可以进行：
for b in self.boxes:
    if b.get("layout_type") == "table":
        if "H" in b:  # 表头
            print(f"表头: {b['text']}")
        elif "R" in b and "C" in b:  # 单元格
            print(f"单元格({b['R']}, {b['C']}): {b['text']}")
```

### B. 表格重建

```python
# 根据标注信息重建表格结构
def build_table(boxes):
    table = {}
    headers = {}
    cells = {}

    for b in boxes:
        if b.get("layout_type") != "table":
            continue

        if "H" in b:  # 表头
            h_idx = b["H"]
            c_idx = b["C"]
            headers[(h_idx, c_idx)] = b["text"]

        if "R" in b and "C" in b:  # 单元格
            r_idx = b["R"]
            c_idx = b["C"]
            cells[(r_idx, c_idx)] = b["text"]

    return {"headers": headers, "cells": cells}
```

### C. 跨行单元格处理

```python
# 检测跨行单元格
for b in self.boxes:
    if "SP" in b:  # 跨行单元格
        print(f"跨行单元格: {b['text']}")
        print(f"  范围: top={b['H_top']}, bottom={b['H_bott']}")
        print(f"  边界: left={b['H_left']}, right={b['H_right']}")
```

---

## 八、与其他模块的协作

### A. 与_layouts_rec的协作

```python
# _layouts_rec提供表格区域
self.page_layout = [
    [  # 每页的layout
        {"type": "table", "x0": 100, "x1": 500, "top": 100, "bottom": 300},
        # ...
    ]
]

# _table_transformer_job使用这些区域裁剪图像
for p, tbls in enumerate(self.page_layout):
    tbls = [f for f in tbls if f["type"] == "table"]
    for tb in tbls:
        imgs.append(self.page_images[p].crop((left, top, right, bott)))
```

### B. 与__images__的协作

```python
# __images__提供
# 1. page_images - 页面图像
self.page_images = [<PIL.Image>, ...]

# 2. page_cum_height - 跨页累积高度
self.page_cum_height = [0, 1169.33, 2338.67]

# 3. boxes - OCR文本框
self.boxes = [
    {"text": "...", "layout_type": "table", ...},
    # ...
]

# _table_transformer_job使用这些数据进行：
# 1. 裁剪表格图像（page_images）
# 2. 坐标累积（page_cum_height）
# 3. 标注文本框（boxes）
```

### C. 与后续模块的协作

```python
# _table_transformer_job的输出被后续模块使用
# 1. _text_merge - 使用R, C信息合并同行的文本
# 2. _extract_table_figure - 使用H, SP信息提取表格
# 3. 表格HTML生成 - 使用完整的结构信息生成表格HTML
```

---

## 九、常见问题与调试

### A. 表格未被识别

**可能原因**：
1. `page_layout`中没有`type="table"`的layout
2. TSR模型识别失败
3. 坐标转换错误

**调试方法**：
```python
# 检查1: 是否有表格layout
print(f"表格数量: {sum(len([f for f in p if f['type']=='table']) for p in self.page_layout)}")

# 检查2: imgs是否为空
print(f"裁剪的表格图像数量: {len(imgs)}")

# 检查3: TSR输出
print(f"识别的表格组件数量: {len(self.tb_cpns)}")
```

### B. 文本框未被标注

**可能原因**：
1. `layout_type`不是"table"
2. 与表格组件的重叠度 < 0.3
3. 列匹配失败

**调试方法**：
```python
# 检查1: 文本框的layout_type
table_boxes = [b for b in self.boxes if b.get("layout_type") == "table"]
print(f"表格内的文本框数量: {len(table_boxes)}")

# 检查2: 标注情况
tagged_boxes = [b for b in table_boxes if "R" in b or "C" in b]
print(f"已标注的文本框数量: {len(tagged_boxes)}")

# 检查3: 重叠度
from deepdoc.vision import Recognizer
overlaps = [Recognizer.overlapped_area(b, rows[0]) for b in table_boxes]
print(f"重叠度: {overlaps}")
```

### C. 坐标偏移错误

**可能原因**：
1. MARGIN未正确处理
2. 坐标缩放顺序错误
3. page_cum_height未正确累积

**调试方法**：
```python
# 可视化检查
import matplotlib.pyplot as plt
from PIL import ImageDraw

# 绘制表格组件
img = self.page_images[0].copy()
draw = ImageDraw.Draw(img)

for cp in self.tb_cpns:
    if cp["pn"] == 0:  # 第0页
        x0, y0 = cp["x0"] * ZM, cp["top"] * ZM
        x1, y1 = cp["x1"] * ZM, cp["bottom"] * ZM
        draw.rectangle([x0, y0, x1, y1], outline="red")

plt.imshow(img)
plt.show()
```

---

## 十、总结

### 核心功能

`_table_transformer_job` 方法是PDF解析流程中**表格结构识别**的核心环节，它：

1. **裁剪表格图像**：从版面布局中提取表格区域
2. **识别表格结构**：调用TSR模型识别行、列、表头、跨行单元格
3. **坐标映射**：将识别结果映射回PDF坐标系统
4. **标注文本框**：为OCR文本框添加结构信息（R, H, C, SP）

### 技术亮点

| 特性 | 说明 |
|------|------|
| **批量处理** | 一次性识别所有表格，提升性能 |
| **坐标转换** | 三重坐标系转换（裁剪→页面→PDF→文档） |
| **跨页累积** | 支持跨页表格的统一坐标系统 |
| **精确标注** | 使用多种匹配策略确保准确性 |
| **鲁棒性** | 边距处理、错误检查、索引安全 |

### 在解析流程中的位置

```
PDF文档
    ↓
__images__ (OCR识别)
    ↓
_layouts_rec (版面识别)
    ↓
_table_transformer_job (表格结构识别) ← 当前方法
    ↓
_text_merge (文本合并)
    ↓
_concat_downward (跨页合并)
    ↓
_extract_table_figure (提取表格)
```

---

**文档版本**: v1.0
**创建日期**: 2025-12-27
**相关文件**:
- [源码位置](../../../../../deepdoc/parser/pdf_parser.py#L202-L286)
- [TableStructureRecognizer](../../../../../deepdoc/vision/table_structure_recognizer.py)
- [Recognizer工具方法](../../../../../deepdoc/vision/recognizer.py)
