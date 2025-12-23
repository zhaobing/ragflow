# RAGFlowPdfParser 数据结构完整解析

## 1. 输入数据结构

### A. 主要输入参数

```python
def __call__(self, fnm, need_image=True, zoomin=3, return_html=False):
    # fnm: PDF文件路径或二进制数据
    # need_image: 是否提取图像
    # zoomin: 缩放倍数 (默认3)
    # return_html: 是否返回HTML格式表格
```

### B. 页面范围控制

```python
def parse_into_bboxes(self, fnm, callback=None, zoomin=3, from_page=0, to_page=100000):
    # from_page: 起始页码 (从0开始)
    # to_page: 结束页码 (最大100000，表示全部)
```

## 2. 核心数据结构

### A. 页面级数据结构

#### 页面图像数据

```python
self.page_images: List[PIL.Image] = []
# 每个元素: PIL.Image对象
# 分辨率: 72 * zoomin
# 格式: RGB图像，带注释信息

# 示例
page_images[0] = <PIL.Image.Image image mode=RGB size=2480x3508 at 0x...>
```

#### 页面字符数据

```python
self.page_chars: List[List[Dict]] = []
# 每个页面包含字符列表

# 单个字符数据结构
char_dict = {
    "text": "A",           # 字符内容
    "x0": 100.5,          # 左边界
    "x1": 108.2,          # 右边界
    "top": 50.0,          # 上边界
    "bottom": 60.0,       # 下边界
    "height": 10.0,       # 字符高度
    "width": 7.7,         # 字符宽度
    "ncs": "DeviceRGB",   # 颜色空间
    "stroking_color": [0, 0, 0],  # 描边颜色
    "non_stroking_color": [0, 0, 0],  # 填充颜色
}
```

#### 页面布局数据

```python
self.page_layout: List[List[Dict]] = []
# 布局识别结果，每页一个布局元素列表

# 单个布局元素
layout_element = {
    "type": "text",                    # 布局类型
    "score": 0.95,                     # 置信度
    "x0": 100.0,                      # 左边界
    "x1": 500.0,                      # 右边界
    "top": 50.0,                       # 上边界
    "bottom": 200.0,                  # 下边界
    "bbox": [100, 50, 500, 200],       # 边界框 [x0, y0, x1, y1]
    "page_number": 1,                  # 页码
}
```

### B. 文本框数据结构

#### 主要文本框容器

```python
self.boxes: List[List[Dict]] = []
# 按页面组织的文本框列表

# 单个文本框数据结构
text_box = {
    # 位置信息
    "x0": 100.0,                      # 左边界
    "x1": 500.0,                      # 右边界
    "top": 150.0,                      # 上边界
    "bottom": 180.0,                  # 下边界
    "page_number": 1,                  # 页码

    # 文本内容
    "text": "这是一段文本内容",           # 合并后的完整文本
    "txt": "原始OCR文本",               # OCR原始识别文本(处理中被删除)

    # 布局信息
    "layout_type": "text",             # 布局类型: text, title, table, figure, etc.
    "layoutno": "1",                   # 布局编号(同类型布局的序号)
    "col_id": 0,                        # 列编号(多栏文档中的列索引)

    # 表格相关(如果是表格文本框)
    "R": 1,                            # 表格行号
    "R_top": 200.0,                    # 表格行顶部位置
    "R_bott": 220.0,                   # 表格行底部位置
    "H": 2,                            # 表格表头编号
    "C": 1,                            # 表格列号
    "SP": 0,                          # 跨行跨列标记

    # 位置标签(用于精确定位)
    "position_tag": "@@1\t100.0\t500.0\t50.0\t180.0##",

    # 图像相关(如果包含图片)
    "image": <PIL.Image.Image>,       # 裁剪的图像
    "positions": [[1, 100, 500, 50, 180]],  # 精确位置列表
}
```

### C. 表格组件数据结构

#### 表格识别结果

```python
self.tb_cpns: List[Dict] = []
# 表格组件列表

# 单个表格组件
table_component = {
    "label": "table row",              # 组件标签: table row, table column, header等
    "x0": 100.0,                      # 左边界
    "x1": 500.0,                      # 右边界
    "top": 50.0,                       # 上边界
    "bottom": 80.0,                    # 下边界
    "pn": 1,                           # 页码
    "layoutno": 0,                     # 布局编号
}
```

## 3. 统计和辅助数据

### A. 页面统计信息

```python
# 累积高度(跨页坐标转换)
self.page_cum_height: List[float] = [0.0, 792.0, 1584.0, ...]
# page_cum_height[i] = 前 i 页的总高度

# 平均尺寸(用于合并判断)
self.mean_height: List[float] = []      # 每页平均字符高度
self.mean_width: List[float] = []       # 每页平均字符宽度
```

### B. 元数据信息

```python
# 文档基本信息
self.total_page: int = 10             # 总页数
self.page_from: int = 0               # 处理起始页
self.column_num: int = 1              # 文档列数

# 大纲信息
self.outlines: List[Tuple[str, int]] = []
# 元组格式: ("章节标题", 层级深度)
# 示例: [("1. 介绍", 1), ("1.1 背景", 2), ("2. 方法", 1)]

# 语言检测
self.is_english: bool = False         # 是否为英文文档
```

### C. 临时处理数据

```python
# 未匹配字符
self.lefted_chars: List[Dict] = []     # 未匹配到OCR框的PDF字符

# 垃圾文本块
self.garbages: Dict = {}               # 被过滤的垃圾文本块

# 并行处理相关
self.parallel_limiter: List[asyncio.Semaphore] = None  # 并行控制器
```

## 4. 输出数据结构

### A. parse_into_bboxes 输出

```python
# 返回值: List[Dict] - 结构化文本框列表
structured_boxes = [
    {
        # 基础信息
        "page_number": 1,
        "x0": 100.0, "x1": 500.0, "top": 50.0, "bottom": 80.0,

        # 文本内容
        "text": "这是标题内容",
        "layout_type": "title",

        # 位置标签(用于精确定位和裁剪)
        "position_tag": "@@1\t100.0\t500.0\t50.0\t80.0##",

        # 图像数据(如果启用need_image)
        "image": <PIL.Image.Image>,
        "positions": [[1, 100, 500, 50, 80]],

        # 表格信息(如果是表格相关)
        "R": 1, "H": 0, "C": 1,  # 行号、表头号、列号
    },
    # ... 更多文本框
]
```

### B. __call__ 输出

```python
# 返回值: Tuple[List[Tuple[str, str]], List[Tuple]]
# (文本内容列表, 表格数据列表)

# 文本内容
text_content = [
    ("这是第一段文本", "@@1\t100.0\t500.0\t50.0\t80.0##"),
    ("这是第二段文本", "@@1\t100.0\t500.0\t85.0\t105.0##"),
    # ...
]

# 表格数据
tables = [
    (
        <PIL.Image.Image>,            # 表格图像
        "<table>...</table>"         # HTML格式表格内容
    ),
    # ... 更多表格
]
```

## 5. 数据转换流程

### A. 坐标系统转换

```python
# 1. PDF坐标系 → 图像坐标系 (OCR处理)
img_coords = pdf_coords * zoomin

# 2. 图像坐标系 → PDF坐标系 (结果输出)
pdf_coords = img_coords / zoomin

# 3. 单页坐标 → 跨页统一坐标
global_top = local_top + page_cum_height[page_num - 1]
```

### B. 数据聚合流程

```python
# 字符级 → 文本框级 → 布局级 → 文档级
PDF字符 + OCR结果 → 文本框 → 布局识别 → 文档结构
```

## 6. 数据结构特点

### A. 层次化设计

```
文档级
├── 页面级 (page_images, page_chars, page_layout)
│   ├── 文本框级 (boxes)
│   │   ├── 字符级 (page_chars中的char_dict)
│   │   └── 布局级 (layout_type, layoutno)
│   └── 表格级 (tb_cpns)
└── 元数据级 (outlines, statistics)
```

### B. 坐标系统

- **本地坐标**: 页面内相对坐标
- **全局坐标**: 跨文档统一坐标
- **缩放坐标**: 适应不同分辨率的坐标

### C. 数据一致性

- **页面对应**: 所有数据都包含页码信息
- **坐标转换**: 多种坐标系统间的无缝转换
- **索引关联**: 通过位置标签建立文本-图像关联

## 7. 位置标签格式详解

### A. 标签格式

```python
position_tag = "@@{pages}\t{x0}\t{x1}\t{top}\t{bottom}##"

# 示例
"@@1\t100.0\t500.0\t50.0\t80.0##"
# 解析:
# @@1     - 第1页 (支持跨页如@@1-2)
# 100.0   - 左边界
# 500.0   - 右边界
# 50.0    - 上边界
# 80.0    - 下边界
```

### B. 跨页处理

```python
# 跨页面文本框
"@@1-2\t100.0\t500.0\t750.0\t50.0##"
# 表示文本框从第1页底部延续到第2页顶部
```

## 8. 类型定义总结

### A. 布局类型

```python
LAYOUT_TYPES = {
    "text": "正文文本",
    "title": "标题",
    "Figure": "图片",
    "Figure caption": "图片说明",
    "Table": "表格",
    "Table caption": "表格标题",
    "Header": "页眉",
    "Footer": "页脚",
    "Reference": "参考文献",
    "Equation": "公式"
}
```

### B. 组件标签

```python
TABLE_COMPONENTS = {
    "table row": "表格行",
    "table column": "表格列",
    "table header": "表头行",
    "table spanning": "跨行跨列"
}
```

## 总结

`RAGFlowPdfParser` 的数据结构体现了完整的PDF解析流程：

1. **输入层**: PDF文件 → 页面图像 + 字符数据
2. **处理层**: OCR识别 + 布局分析 + 表格检测 + 智能合并
3. **输出层**: 结构化文本框 + 表格数据 + 位置信息

### 数据结构特点

- **层次清晰**: 从字符到文本框到完整文档的层次化组织
- **坐标统一**: 多种坐标系统的无缝转换
- **类型丰富**: 支持文本、表格、图片等多种内容类型
- **位置精确**: 位置标签支持精确定位和裁剪
- **可扩展性**: 支持新增布局类型和属性

这种设计使得RAGFlow能够准确理解和处理复杂的PDF文档结构，为后续的知识构建提供高质量的输入数据。