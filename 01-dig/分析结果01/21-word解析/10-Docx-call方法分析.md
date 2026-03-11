# Docx.__call__() 方法分析

## 概述

`Docx` 类是RAGFlow中用于解析Word文档(.docx)的核心类，`__call__()` 方法是其主入口，负责提取文档中的段落、图片和表格，并将其转换为结构化数据。

**文件位置**: `rag/app/naive.py:160-378`

**类继承关系**:
```
Docx(DocxParser)
    └── 继承自 RAGFlowDocxParser
        └── 位置: deepdoc/parser/docx_parser.py
```

---

## 一、业务逻辑

### 1.1 核心功能

`__call__()` 方法实现以下核心功能：

1. **文档加载**: 使用python-docx库加载Word文档
2. **段落解析**: 提取文档中的所有段落文本
3. **图片提取**: 从段落中提取关联图片
4. **Caption处理**: 处理Caption样式，关联图片与标题
5. **分页检测**: 识别文档中的分页符
6. **表格解析**: 提取表格并生成HTML格式
7. **层级标题关联**: 为表格附加层级标题路径

### 1.2 输入输出

**输入参数**:
```python
def __call__(self, filename, binary=None, from_page=0, to_page=100000):
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| filename | str | - | 文件名或文件路径 |
| binary | bytes | None | 文件二进制内容 |
| from_page | int | 0 | 起始页码 |
| to_page | int | 100000 | 结束页码 |

**返回值**:
```python
return new_line, tbls
# new_line: [(text, image, style), ...]
# tbls: [((None, html), position), ...]
```

---

## 二、执行流程详解

### 2.1 完整流程图

```
__call__(filename, binary, from_page, to_page)
    │
    ├─→ 1. 文档加载
    │     self.doc = Document(BytesIO(binary))
    │
    ├─→ 2. 段落遍历与处理
    │     for p in self.doc.paragraphs:
    │       │
    │       ├─→ 分页检测
    │       │   if 'lastRenderedPageBreak' in run._element.xml:
    │       │       pn += 1
    │       │
    │       ├─→ 非空段落处理
    │       │   if p.text.strip():
    │       │     │
    │       │     ├─→ Caption样式处理
    │       │     │   if p.style.name == 'Caption':
    │       │     │     ├─ 提取前一个段落的图片
    │       │     │     └─ 关联图片与标题
    │       │     │
    │       │     └─→ 普通段落处理
    │       │         ├─ get_picture() 提取图片
    │       │         ├─ 处理缓存的last_image
    │       │         └─ 添加到lines列表
    │       │
    │       └─→ 空段落处理
    │           if current_image := get_picture():
    │             ├─ 附加到前一个段落
    │             └─ 或缓存为last_image
    │
    ├─→ 3. 图片合并
    │     new_line = [(text, reduce(concat_img, images)), ...]
    │
    ├─→ 4. 表格处理
    │     for i, tb in enumerate(self.doc.tables):
    │       │
    │       ├─→ 获取层级标题
    │       │   title = __get_nearest_title(i, filename)
    │       │
    │       ├─→ 构建HTML表格
    │       │   for row in tb.rows:
    │       │     ├─ 检测合并单元格
    │       │     └─ 生成 <tr><td> 结构
    │       │
    │       └─→ 添加到tbls列表
    │
    └─→ 5. 返回结果
          return new_line, tbls
```

### 2.2 段落处理详细流程

#### 2.2.1 文档初始化

```python
self.doc = Document(filename) if not binary else Document(BytesIO(binary))
pn = 0          # 当前页码计数器
lines = []      # 段落列表: [(text, [images], style), ...]
last_image = None  # 缓存的图片(用于空段落的图片关联)
```

#### 2.2.2 段落遍历

```python
for p in self.doc.paragraphs:
    # 页码范围检查
    if pn > to_page:
        break

    if from_page <= pn < to_page:
        # 处理段落...

    # 分页符检测
    for run in p.runs:
        if 'lastRenderedPageBreak' in run._element.xml:
            pn += 1
        if 'w:br' in run._element.xml and 'type="page"' in run._element.xml:
            pn += 1
```

**分页检测机制**:
- `lastRenderedPageBreak`: Word自动分页标记
- `w:br type="page"`: 手动分页符标记

#### 2.2.3 Caption样式处理

```python
if p.style and p.style.name == 'Caption':
    former_image = None

    # 方式1: 从前一个段落提取图片
    if lines and lines[-1][1] and lines[-1][2] != 'Caption':
        former_image = lines[-1][1].pop()

    # 方式2: 使用缓存的图片
    elif last_image:
        former_image = last_image
        last_image = None

    # 添加Caption段落(带关联图片)
    lines.append((self.__clean(p.text), [former_image], p.style.name))
```

**Caption关联规则**:
| 条件 | 行为 |
|------|------|
| 前一个段落有图片且非Caption | 提取该图片 |
| 前一个段落是Caption | 使用 `last_image` 缓存 |
| 都不满足 | 使用None（无图片） |

#### 2.2.4 普通段落处理

```python
else:
    # 1. 提取当前段落的图片
    current_image = self.get_picture(self.doc, p)

    # 2. 构建图片列表(包含缓存的图片)
    image_list = [current_image]
    if last_image:
        image_list.insert(0, last_image)  # 缓存图片放在前面
        last_image = None

    # 3. 添加到lines列表
    lines.append((
        self.__clean(p.text),  # 清理后的文本
        image_list,            # 图片列表
        p.style.name if p.style else ""  # 样式名
    ))
```

#### 2.2.5 空段落处理

```python
else:
    # 空段落但包含图片的情况
    if current_image := self.get_picture(self.doc, p):
        if lines:
            # 附加到前一个段落的图片列表
            lines[-1][1].append(current_image)
        else:
            # 文档开头的图片，缓存起来
            last_image = current_image
```

**处理场景**:
```
[图片] + [空行] + [文本] → 图片与文本关联
```

#### 2.2.6 图片合并

```python
# 使用reduce垂直合并多张图片
new_line = [
    (line[0], reduce(concat_img, line[1]) if line[1] else None)
    for line in lines
]
```

### 2.3 表格处理详细流程

#### 2.3.1 表格遍历

```python
tbls = []
for i, tb in enumerate(self.doc.tables):
    # i: 表格索引
    # tb: Table对象
```

#### 2.3.2 层级标题获取

```python
title = self.__get_nearest_title(i, filename)
# 返回格式: "文档名 > 第一章 > 1.1 小节"
```

**标题获取逻辑**:
1. 向前查找最近的标题段落(Heading 1-7)
2. 查找所有父级标题
3. 按级别排序(从高到低)
4. 用 " > " 连接

#### 2.3.3 HTML表格构建

```python
html = "<table>"

# 添加标题
if title:
    html += f"<caption>Table Location: {title}</caption>"

# 遍历行
for r in tb.rows:
    html += "<tr>"

    # 遍历单元格
    i_col = 0
    while i_col < len(r.cells):
        span = 1
        c = r.cells[i_col]

        # 检测合并单元格(通过文本相同判断)
        for j in range(i_col + 1, len(r.cells)):
            if c.text == r.cells[j].text:
                span += 1
                i_col = j
            else:
                break

        i_col += 1

        # 生成单元格HTML
        if span == 1:
            html += f"<td>{c.text}</td>"
        else:
            html += f"<td colspan='{span}'>{c.text}</td>"

    html += "</tr>"

html += "</table>"
tbls.append(((None, html), ""))
```

**合并单元格检测原理**:
python-docx中，合并的单元格在不同索引位置返回相同内容，通过比较文本判断colspan。

---

## 三、辅助方法分析

### 3.1 get_picture() - 图片提取

**文件位置**: `rag/app/naive.py:164-201`

```python
def get_picture(self, document, paragraph):
    # 1. XPath定位图片
    imgs = paragraph._element.xpath('.//pic:pic')
    if not imgs:
        return None

    res_img = None
    for img in imgs:
        # 2. 获取嵌入ID
        embed = img.xpath('.//a:blip/@r:embed')
        if not embed:
            continue
        embed = embed[0]

        # 3. 从relationships获取图片二进制
        try:
            related_part = document.part.related_parts[embed]
            image_blob = related_part.image.blob
        except (UnrecognizedImageError, UnexpectedEndOfFileError,
                InvalidImageStreamError, UnicodeDecodeError) as e:
            logging.info(f"Skipping image: {e}")
            continue

        # 4. 转换为PIL Image
        try:
            image = Image.open(BytesIO(image_blob)).convert('RGB')
            if res_img is None:
                res_img = image
            else:
                res_img = concat_img(res_img, image)  # 垂直合并
        except Exception:
            continue

    return res_img
```

**异常处理**:
| 异常类型 | 说明 |
|----------|------|
| UnrecognizedImageError | 不识别的图片格式 |
| UnexpectedEndOfFileError | 图片流意外结束 |
| InvalidImageStreamError | 图片流损坏 |
| UnicodeDecodeError | 编码错误 |

### 3.2 __clean() - 文本清理

**文件位置**: `rag/app/naive.py:203-205`

```python
def __clean(self, line):
    # 将全角空格替换为半角空格，并去除首尾空白
    line = re.sub(r"\u3000", " ", line).strip()
    return line
```

### 3.3 __get_nearest_title() - 层级标题提取

**文件位置**: `rag/app/naive.py:207-310`

```python
def __get_nearest_title(self, table_index, filename):
    # 1. 获取文档名
    doc_name = re.sub(r"\.[a-zA-Z]+$", "", filename)

    # 2. 收集所有文档块(段落+表格)，保持原始顺序
    blocks = []
    for i, block in enumerate(self.doc._element.body):
        if block.tag.endswith('p'):  # 段落
            p = Paragraph(block, self.doc)
            blocks.append(('p', i, p))
        elif block.tag.endswith('tbl'):  # 表格
            blocks.append(('t', i, None))

    # 3. 找到目标表格的位置
    target_table_pos = -1
    table_count = 0
    for i, (block_type, pos, _) in enumerate(blocks):
        if block_type == 't':
            if table_count == table_index:
                target_table_pos = pos
                break
            table_count += 1

    # 4. 向后查找最近的标题
    nearest_title = None
    for i in range(len(blocks)-1, -1, -1):
        block_type, pos, block = blocks[i]
        if pos >= target_table_pos:  # 跳过表格后的块
            continue

        if block_type != 'p':
            continue

        # 检查是否为标题样式
        if block.style and re.search(r"Heading\s*(\d+)", block.style.name, re.I):
            level = int(re.search(r"(\d+)", block.style.name).group(1))
            if level <= 7:  # 支持最多7级标题
                nearest_title = (level, block.text.strip())
                break

    # 5. 查找所有父级标题
    if nearest_title:
        titles = [nearest_title]
        current_level = nearest_title[0]

        while current_level > 1:
            found = False
            for i in range(len(blocks)-1, -1, -1):
                # ... 查找更高级别的标题
                if level < current_level:
                    titles.append((level, block.text.strip()))
                    current_level = level
                    found = True
                    break

            if not found:
                break

        # 6. 按级别排序并组装
        titles.sort(key=lambda x: x[0])  # 升序: 1, 2, 3...
        hierarchy = [doc_name] + [t[1] for t in titles]
        return " > ".join(hierarchy)

    return ""
```

**支持的标题样式**:
- Heading 1
- Heading 2
- Heading 3
- Heading 4
- Heading 5
- Heading 6
- Heading 7

**输出示例**:
```
文档名 > 第一章 > 1.1 小节 > 1.1.1 子小节
```

---

## 四、数据结构

### 4.1 中间数据结构 - lines

```python
lines = [
    (text, [images], style),
    # text: str - 段落文本
    # [images]: List[PIL.Image] - 图片列表
    # style: str - 样式名称
    ...
]
```

**示例**:
```python
[
    ("文档标题", [None], "Heading 1"),
    ("这是一段文字", [img1, img2], "Normal"),
    ("图1说明", [img1], "Caption"),
]
```

### 4.2 输出数据结构 - new_line

```python
new_line = [
    (text, merged_image),
    # text: str - 清理后的文本
    # merged_image: PIL.Image or None - 合并后的图片
    ...
]
```

### 4.3 表格数据结构 - tbls

```python
tbls = [
    ((None, html), position),
    # None: 无图片截图
    # html: str - HTML格式的表格
    # position: str - 位置信息(Word中为空)
    ...
]
```

**HTML示例**:
```html
<table>
    <caption>Table Location: 文档名 > 第一章</caption>
    <tr>
        <td>单元格1</td>
        <td colspan='2'>合并单元格</td>
    </tr>
</table>
```

---

## 五、技术要点

### 5.1 python-docx库使用

```python
from docx import Document

# 加载文档
doc = Document(BytesIO(binary))

# 访问段落
for p in doc.paragraphs:
    text = p.text
    style = p.style.name

# 访问表格
for tb in doc.tables:
    for row in tb.rows:
        for cell in row.cells:
            text = cell.text
```

### 5.2 XPath图片定位

```python
# Word文档XML结构
paragraph._element.xpath('.//pic:pic')
# .//pic:pic - 递归查找所有pic命名空间的pic元素

# 获取嵌入ID
img.xpath('.//a:blip/@r:embed')
# @r:embed - 获取r:embed属性的值

# 通过relationships获取图片
document.part.related_parts[embed]
```

### 5.3 合并单元格检测

**原理**: python-docx中，合并的单元格在不同索引返回相同内容

```python
span = 1
c = r.cells[i]
for j in range(i + 1, len(r.cells)):
    if c.text == r.cells[j].text:  # 文本相同 → 合并
        span += 1
        i = j
    else:
        break
```

### 5.4 图片垂直合并

```python
from functools import reduce

# 将多张图片垂直拼接
merged_image = reduce(concat_img, image_list)
# 等价于: concat_img(concat_img(img1, img2), img3)
```

### 5.5 Caption关联算法

```
规则:
1. Caption段落优先从"前一个非Caption段落"提取图片
2. 如果前一个也是Caption，使用缓存的last_image
3. last_image来自"空段落中的图片"

场景示例:
[段落A + 图片1] + [Caption: 图1说明] → 图片1关联到Caption
[空段落 + 图片2] + [文本段落] → 图片2关联到文本段落
```

---

## 六、总结

### 6.1 Docx.__call__() 核心价值

1. **结构化提取**: 将Word文档的复杂结构转换为简单的(文本,图片)对
2. **图片关联**: 智能关联图片与文本/Caption
3. **表格HTML化**: 保留表格结构和层级信息
4. **分页支持**: 支持按页码范围提取内容
5. **容错处理**: 多层异常处理确保解析稳定性

### 6.2 与PDF解析对比

| 维度 | Word | PDF |
|------|------|-----|
| 解析方式 | python-docx DOM | OCR + 布局分析 |
| 准确率 | 100% | 90-99% |
| 速度 | 快 | 慢 |
| 图片提取 | 直接读取 | 视觉检测 |
| 表格输出 | HTML | 图片 + 文本 |
| 位置信息 | 无 | 精确坐标 |

### 6.3 调用链路

```
chunk() 函数
    └── Docx()(filename, binary)
            ├── __call__()
            │   ├── 段落处理
            │   │   ├── get_picture()
            │   │   ├── Caption处理
            │   │   └── 空段落处理
            │   ├── 图片合并
            │   └── 表格处理
            │       └── __get_nearest_title()
            └── 返回 (new_line, tbls)
```
