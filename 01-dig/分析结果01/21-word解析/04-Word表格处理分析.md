# Word表格处理分析

## 概述

本文档分析RAGFlow中Word文档表格提取与处理的完整机制。

---

## 1. 表格处理架构

### 1.1 两个解析器的表格处理对比

| 解析器 | 文件 | 表格处理方式 | 输出格式 |
|--------|------|-------------|----------|
| `RAGFlowDocxParser` | deepdoc/parser/docx_parser.py | 文本重组 | 列表(文本行) |
| `Docx` | rag/app/naive.py | HTML生成 | HTML字符串 |

### 1.2 调用链路

```
chunk() 函数 (rag/app/naive.py)
    │
    ├── sections, tables = Docx()(filename, binary)  ← 主要使用
    │       │
    │       ├── sections: [(text, image, style), ...]
    │       └── tables: [((None, html), position), ...]
    │
    └── tables = vision_figure_parser_docx_wrapper()  ← 视觉增强
```

---

## 2. RAGFlowDocxParser - 文本重组方式

### 2.1 单元格提取 - __extract_table_content()

**文件**: `deepdoc/parser/docx_parser.py:27-31`

```python
def __extract_table_content(self, tb):
    df = []
    for row in tb.rows:
        df.append([c.text for c in row.cells])  # 提取每行所有单元格文本
    return self.__compose_table_content(pd.DataFrame(df))
```

**处理流程**:
1. 遍历表格的所有行 (`tb.rows`)
2. 提取每行所有单元格的文本 (`c.text`)
3. 构建二维数组 `df`
4. 转换为 pandas DataFrame
5. 调用 `__compose_table_content()` 进行内容重组

**注意**: python-docx 会自动处理合并单元格，合并区域会返回相同的文本。

### 2.2 表格内容重组 - __compose_table_content()

**文件**: `deepdoc/parser/docx_parser.py:33-114`

#### 2.2.1 单元格类型识别 - blockType()

```python
def blockType(b):
    pattern = [
        # 日期类型
        ("^(20|19)[0-9]{2}[年/-][0-9]{1,2}[月/-][0-9]{1,2}日*$", "Dt"),
        (r"^(20|19)[0-9]{2}年$", "Dt"),
        (r"^(20|19)[0-9]{2}[年/-][0-9]{1,2}月*$", "Dt"),
        ("^[0-9]{1,2}[月/-][0-9]{1,2}日*$", "Dt"),
        (r"^第*[一二三四1-4]季度$", "Dt"),

        # 代码/大写字母
        (r"^(20|19)[0-9]{2}[ABCDE]$", "DT"),
        (r"^[0-9A-Z/\._~-]+$", "Ca"),

        # 纯数字
        ("^[0-9.,+%/ -]+$", "Nu"),

        # 英文
        (r"^[A-Z]*[a-z' -]+$", "En"),

        # 数字+英文混合
        (r"^[0-9.,+-]+[0-9A-Za-z/$￥%<>（）()' -]+$", "NE"),

        # 单字符
        (r"^.{1}$", "Sg")
    ]
    for p, n in pattern:
        if re.search(p, b):
            return n

    # 基于分词的类型推断
    tks = [t for t in rag_tokenizer.tokenize(b).split() if len(t) > 1]
    if len(tks) > 3:
        if len(tks) < 12:
            return "Tx"  # 中等长度文本
        else:
            return "Lx"  # 长文本

    if len(tks) == 1 and rag_tokenizer.tag(tks[0]) == "nr":
        return "Nr"  # 人名

    return "Ot"  # 其他类型
```

**类型代码表**:

| 代码 | 含义 | 判断规则 |
|------|------|----------|
| Dt | 日期 | 日期正则匹配 |
| DT | 代码 | 年份+字母 |
| Nu | 数字 | 纯数字+符号 |
| Ca | 代码 | 大写字母+符号 |
| En | 英文 | 英文字母 |
| NE | 数字英文混合 | 数字+英文 |
| Sg | 单字符 | 单个字符 |
| Tx | 中等文本 | 3-12个token |
| Lx | 长文本 | >12个token |
| Nr | 人名 | 词性为nr |
| Ot | 其他 | 其他情况 |

#### 2.2.2 表格类型统计

```python
# 统计除首行外所有单元格的类型
max_type = Counter([
    blockType(str(df.iloc[i, j]))
    for i in range(1, len(df))      # 跳过第一行（通常是标题）
    for j in range(len(df.iloc[i, :]))
])
max_type = max(max_type.items(), key=lambda x: x[1])[0]  # 取最多的类型
```

**用途**: 判断表格是"数据型"(数字为主)还是"文本型"。

#### 2.2.3 多行表头检测

```python
colnm = len(df.iloc[0, :])  # 列数
hdrows = [0]  # header rows，第一行默认为标题

# 如果主要是数字型表格，寻找其他标题行
if max_type == "Nu":
    for r in range(1, len(df)):
        tys = Counter([blockType(str(df.iloc[r, j]))
                      for j in range(len(df.iloc[r, :]))])
        tys = max(tys.items(), key=lambda x: x[1])[0]
        if tys != max_type:  # 该行类型与数据类型不同，可能是标题
            hdrows.append(r)
```

**示例**:
```
| 产品 | Q1 | Q2 | Q3 | Q4 |    ← 第0行，标题
|------|----|----|----|-----|
| 2023 | 100| 120| 130| 140|    ← 数据行
| 2024 | 150| 160| 170| 180|    ← 数据行
| 合计 | 250| 280| 300| 320|    ← 第3行，也包含数字但作为小计行

hdrows = [0]  # 第一行是标题
```

#### 2.2.4 数据行处理

```python
lines = []
for i in range(1, len(df)):
    if i in hdrows:  # 跳过标题行
        continue

    # 计算该行与各标题行的相对位置
    hr = [r - i for r in hdrows]
    hr = [r for r in hr if r < 0]  # 只保留前面的标题

    # 只保留连续的标题行
    t = len(hr) - 1
    while t > 0:
        if hr[t] - hr[t - 1] > 1:
            hr = hr[t:]
            break
        t -= 1

    # 为每列构建标题前缀
    headers = []
    for j in range(len(df.iloc[i, :])):
        t = []
        for h in hr:
            x = str(df.iloc[i + h, j]).strip()  # 标题行的单元格内容
            if x in t:
                continue
            t.append(x)
        t = ",".join(t)
        if t:
            t += ": "
        headers.append(t)

    # 提取非空单元格
    cells = []
    for j in range(len(df.iloc[i, :])):
        if not str(df.iloc[i, j]):
            continue
        cells.append(headers[j] + str(df.iloc[i, j]))

    # 组合该行的所有单元格
    lines.append(";".join(cells))

# 根据列数决定输出格式
if colnm > 3:
    return lines  # 多列：每行一个字符串
return ["\n".join(lines)]  # 少列：合并为一个字符串
```

**输出示例**:
```
原始表格:
| 姓名 | 年龄 | 职位 |
|------|------|------|
| 张三 | 25   | 工程师 |
| 李四 | 30   | 经理 |

输出:
[
    "姓名: 张三; 年龄: 25; 职位: 工程师",
    "姓名: 李四; 年龄: 30; 职位: 经理"
]
```

---

## 3. Docx类 - HTML生成方式

### 3.1 表格HTML生成

**文件**: `rag/app/naive.py:352-378`

```python
tbls = []
for i, tb in enumerate(self.doc.tables):
    # 1. 获取表格前的层级标题
    title = self.__get_nearest_title(i, filename)

    # 2. 构建HTML
    html = "<table>"
    if title:
        html += f"<caption>Table Location: {title}</caption>"

    # 3. 遍历行
    for r in tb.rows:
        html += "<tr>"
        i_col = 0
        try:
            while i_col < len(r.cells):
                span = 1
                c = r.cells[i_col]

                # 4. 检测合并单元格（通过文本相同判断）
                for j in range(i_col + 1, len(r.cells)):
                    if c.text == r.cells[j].text:
                        span += 1
                        i_col = j
                    else:
                        break
                i_col += 1

                # 5. 添加单元格
                html += f"<td>{c.text}</td>" if span == 1 else f"<td colspan='{span}'>{c.text}</td>"
        except Exception as e:
            logging.warning(f"Error parsing table, ignore: {e}")
        html += "</tr>"

    html += "</table>"
    tbls.append(((None, html), ""))
```

### 3.2 合并单元格检测逻辑

```python
# 通过比较相邻单元格文本判断是否合并
span = 1
c = r.cells[i]
for j in range(i + 1, len(r.cells)):
    if c.text == r.cells[j].text:  # 文本相同则认为是合并
        span += 1
        i = j
    else:
        break
```

**原理**: python-docx中，合并的单元格在不同索引位置会返回相同的内容。

**生成的HTML示例**:
```html
<table>
    <caption>Table Location: 文档名 > 第一章 > 数据统计</caption>
    <tr>
        <td>姓名</td>
        <td>年龄</td>
    </tr>
    <tr>
        <td>张三</td>
        <td>25</td>
    </tr>
</table>
```

### 3.3 表格数据结构

```python
tbls = [
    ((None, html), ""),  # (image, html_string), position
    # image: 图片截图（Word表格没有，所以是None）
    # html: HTML格式的表格内容
    # position: 位置信息（Word表格为空）
]
```

---

## 4. 层级标题提取 - __get_nearest_title()

**文件**: `rag/app/naive.py:207-308`

### 4.1 函数目的

获取指定表格前的层级标题结构，例如：`"文档名 > 第一章 > 数据统计"`

### 4.2 处理流程

```python
def __get_nearest_title(self, table_index, filename):
    # 1. 获取文档名（不含扩展名）
    doc_name = re.sub(r"\.[a-zA-Z]+$", "", filename)
    if not doc_name:
        doc_name = "Untitled Document"

    # 2. 按文档顺序收集所有块（段落和表格）
    blocks = []
    for i, block in enumerate(self.doc._element.body):
        if block.tag.endswith('p'):  # Paragraph
            p = Paragraph(block, self.doc)
            blocks.append(('p', i, p))
        elif block.tag.endswith('tbl'):  # Table
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

    if target_table_pos == -1:
        return ""

    # 4. 向前查找最近的标题段落
    nearest_title = None
    for i in range(len(blocks)-1, -1, -1):
        block_type, pos, block = blocks[i]
        if pos >= target_table_pos:  # 跳过表格后的块
            continue

        if block_type != 'p':
            continue

        # 检查是否为标题样式
        if block.style and block.style.name and re.search(r"Heading\s*(\d+)", block.style.name, re.I):
            level_match = re.search(r"(\d+)", block.style.name)
            if level_match:
                level = int(level_match.group(1))
                if level <= 7:  # 支持最多7级标题
                    title_text = block.text.strip()
                    if title_text:
                        nearest_title = (level, title_text)
                        break

    if nearest_title:
        # 5. 构建层级标题结构
        titles = []
        titles.append(nearest_title)
        current_level = nearest_title[0]

        # 6. 查找父级标题
        while current_level > 1:
            found = False
            for i in range(len(blocks)-1, -1, -1):
                block_type, pos, block = blocks[i]
                if pos >= target_table_pos:
                    continue

                if block_type != 'p':
                    continue

                if block.style and re.search(r"Heading\s*(\d+)", block.style.name, re.I):
                    level_match = re.search(r"(\d+)", block.style.name)
                    if level_match:
                        level = int(level_match.group(1))
                        if level < current_level:  # 父级标题级别更小
                            title_text = block.text.strip()
                            if title_text:
                                titles.append((level, title_text))
                                current_level = level
                                found = True
                                break

            if not found:
                break

        # 7. 按级别排序并组装
        titles.sort(key=lambda x: x[0])  # 升序
        hierarchy = [doc_name] + [t[1] for t in titles]
        return " > ".join(hierarchy)

    return ""
```

### 4.3 支持的标题样式

| 样式名称 | 级别 |
|----------|------|
| Heading 1 | 1 |
| Heading 2 | 2 |
| Heading 3 | 3 |
| Heading 4 | 4 |
| Heading 5 | 5 |
| Heading 6 | 6 |
| Heading 7 | 7 |

### 4.4 输出示例

```
文档结构:
文档.docx
├── Heading 1: 第一章
│   ├── Heading 2: 1.1 概述
│   └── Heading 2: 1.2 数据
│       └── [表格1]
└── Heading 1: 第二章
    └── [表格2]

表格1的title: "文档 > 第一章 > 1.2 数据"
表格2的title: "文档 > 第二章"
```

---

## 5. 表格Token化 - tokenize_table()

**文件**: `rag/nlp/__init__.py:358-416`

### 5.1 函数签名

```python
def tokenize_table(tbls, doc, eng, batch_size=10) -> List[dict]:
```

### 5.2 处理流程

```python
res = []
for (img, rows), poss in tbls:
    if not rows:
        continue

    # 情况1: rows是字符串（HTML格式）
    if isinstance(rows, str):
        d = copy.deepcopy(doc)
        tokenize(d, rows, eng)
        d["content_with_weight"] = rows
        d["doc_type_kwd"] = "table"
        if img:
            d["image"] = img
            d["doc_type_kwd"] = "image"  # 有图片时标记为image
        if poss:
            add_positions(d, poss)
        res.append(d)
        continue

    # 情况2: rows是列表（RAGFlowDocxParser的输出）
    de = "; " if eng else "； "
    for i in range(0, len(rows), batch_size):
        d = copy.deepcopy(doc)
        r = de.join(rows[i:i + batch_size])  # 分批合并
        tokenize(d, r, eng)
        d["doc_type_kwd"] = "table"
        if img:
            d["image"] = img
            d["doc_type_kwd"] = "image"
        add_positions(d, poss)
        res.append(d)

return res
```

### 5.3 batch_size参数

- **默认值**: 10
- **作用**: 控制每个chunk包含的表格行数
- **用途**: 防止单个chunk过大

### 5.4 最终Chunk结构

```python
{
    "content_with_weight": "<table>...</table>",  # HTML或文本
    "content_ltks": "...",                        # 粗粒度分词
    "content_sm_ltks": "...",                     # 细粒度分词
    "doc_type_kwd": "table" or "image",           # 类型标记
    "image": <PIL.Image> or None,                 # 图片
    "page_num_int": [0, 0, 0, 0, 0],              # 页码
    "position_int": [(0, 0, 0, 0, 0), ...],       # 位置
    "docnm_kwd": "...",                           # 文档名
    "title_tks": "...",                           # 标题分词
    "title_sm_tks": "...",                        # 标题细粒度分词
}
```

---

## 6. 完整表格处理流程图

```
Word文档 (.docx)
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Docx.__call()(filename, binary)                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 段落处理 → sections (lines合并后)                      │  │
│  └───────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 表格处理                                               │  │
│  │  for i, tb in enumerate(self.doc.tables):             │  │
│  │    1. title = __get_nearest_title(i, filename)        │  │
│  │    2. html = "<table>" + <caption> + rows + "</table>"│  │
│  │    3. tbls.append(((None, html), ""))                 │  │
│  └───────────────────────────────────────────────────────┘  │
│  返回: sections, tbls                                         │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ vision_figure_parser_docx_wrapper(sections, tbls)            │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 如果配置了视觉模型:                                     │  │
│  │  - 提取sections中的图片                                 │  │
│  │  - 视觉LLM描述                                         │  │
│  │  - 合并到tbls列表                                      │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ tokenize_table(tables, doc, is_english)                      │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ for (img, html), poss in tables:                      │  │
│  │   d["content_with_weight"] = html                     │  │
│  │   d["doc_type_kwd"] = "table" or "image"              │  │
│  │   tokenize(d, html, eng)                              │  │
│  │   res.append(d)                                       │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
Final Table Chunks
```

---

## 7. Word表格与PDF表格对比

| 维度 | Word | PDF |
|------|------|-----|
| 表格提取 | python-docx，DOM直接访问 | OCR+布局分析 |
| 单元格获取 | `row.cells[i].text` | 视觉区域识别 |
| 合并单元格 | 文本相同推断 | 坐标范围计算 |
| 标题获取 | 样式名(Heading 1-7) | 位置+字体大小推断 |
| 输出格式 | HTML | 图片+文本行 |
| 图片截图 | 无 | 有 |

---

## 8. 关键配置参数

| 参数 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `batch_size` | tokenize_table() | 10 | 每个chunk的表格行数 |
| `chunk_token_num` | parser_config | 128 | 文本切片token数 |
| `table_context_size` | parser_config | 0 | 表格上下文附加数量 |

---

## 9. 总结

Word表格处理核心流程：

1. **提取**: 使用python-docx直接访问表格DOM结构
2. **标题关联**: 通过样式名识别层级标题
3. **HTML生成**: 将表格转换为HTML格式
4. **视觉增强**: (可选) 使用视觉LLM增强表格内容
5. **Token化**: 分词处理并生成chunk结构
6. **上下文附加**: (可选) 为表格chunk附加周围文本

**关键特性**:
- 直接DOM访问，无需OCR
- 支持层级标题提取
- HTML格式保留表格结构
- 合并单元格检测
- 批量处理防止chunk过大
