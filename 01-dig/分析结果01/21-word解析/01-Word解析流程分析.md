# 01-Word解析流程分析

## 一、核心类概览

### 1.1 类关系图

```
RAGFlowDocxParser (deepdoc/parser/docx_parser.py)
    ↑ 继承
    │
Docx (rag/app/naive.py)
    │
    └── 被 chunk() 函数调用
```

### 1.2 两个解析器的区别

| 特性 | RAGFlowDocxParser | Docx (naive.py) |
|------|-------------------|-----------------|
| 图片提取 | ❌ 不支持 | ✅ 支持 (get_picture) |
| 表格标题 | ❌ 不支持 | ✅ 支持 (__get_nearest_title) |
| Markdown转换 | ❌ 不支持 | ✅ 支持 (to_markdown) |
| 段落样式 | 简单存储 | 详细处理(Caption等) |

---

## 二、RAGFlowDocxParser 解析流程

### 2.1 类结构

```python
class RAGFlowDocxParser:
    def __extract_table_content(self, tb):
        """提取表格内容并转换"""

    def __compose_table_content(self, df):
        """组合表格内容，包含类型识别"""

    def __call__(self, fnm, from_page=0, to_page=100000000):
        """主解析方法"""
```

### 2.2 __call__ 方法流程

```python
def __call__(self, fnm, from_page=0, to_page=100000000):
    # 1. 创建Document对象
    self.doc = Document(fnm) if isinstance(fnm, str) else Document(BytesIO(fnm))

    pn = 0          # 已解析页数
    secs = []       # 解析的内容 [(文本, 样式名), ...]

    # 2. 遍历所有段落
    for p in self.doc.paragraphs:
        if pn > to_page:
            break

        runs_within_single_paragraph = []

        # 3. 遍历段落中的所有run
        for run in p.runs:
            if pn > to_page:
                break

            # 4. 收集指定页面范围内的文本
            if from_page <= pn < to_page and p.text.strip():
                runs_within_single_paragraph.append(run.text)

            # 5. 检测分页符
            if 'lastRenderedPageBreak' in run._element.xml:
                pn += 1

        # 6. 保存段落内容
        secs.append(("".join(runs_within_single_paragraph),
                     p.style.name if hasattr(p.style, 'name') else ''))

    # 7. 处理表格
    tbls = [self.__extract_table_content(tb) for tb in self.doc.tables]

    return secs, tbls
```

### 2.3 页面分页检测机制

Word文档没有原生"页"的概念，使用以下方式检测分页:

```python
# 方法1: lastRenderedPageBreak 标记
if 'lastRenderedPageBreak' in run._element.xml:
    pn += 1

# 方法2: 分页符样式
if 'w:br' in run._element.xml and 'type="page"' in run._element.xml:
    pn += 1
```

---

## 三、Docx 类 (naive.py) 解析流程

### 3.1 类结构

```python
class Docx(DocxParser):
    def get_picture(self, document, paragraph):
        """从段落中提取图片"""

    def __clean(self, line):
        """清理文本"""

    def __get_nearest_title(self, table_index, filename):
        """获取表格的层级标题"""

    def __call__(self, filename, binary=None, from_page=0, to_page=100000):
        """主解析方法"""

    def to_markdown(self, filename=None, binary=None, inline_images: bool = True):
        """转换为Markdown格式"""
```

### 3.2 __call__ 方法完整流程

```python
def __call__(self, filename, binary=None, from_page=0, to_page=100000):
    # 1. 加载文档
    self.doc = Document(filename) if not binary else Document(BytesIO(binary))

    pn = 0
    lines = []
    last_image = None

    # 2. 遍历段落
    for p in self.doc.paragraphs:
        if pn > to_page:
            break

        if from_page <= pn < to_page:
            if p.text.strip():
                # 3. Caption样式特殊处理
                if p.style and p.style.name == 'Caption':
                    former_image = None
                    if lines and lines[-1][1] and lines[-1][2] != 'Caption':
                        former_image = lines[-1][1].pop()
                    elif last_image:
                        former_image = last_image
                        last_image = None
                    lines.append((self.__clean(p.text), [former_image], p.style.name))
                else:
                    # 4. 提取当前段落的图片
                    current_image = self.get_picture(self.doc, p)
                    image_list = [current_image]
                    if last_image:
                        image_list.insert(0, last_image)
                        last_image = None
                    lines.append((self.__clean(p.text), image_list,
                                 p.style.name if p.style else ""))
            else:
                # 5. 空段落检查图片
                if current_image := self.get_picture(self.doc, p):
                    if lines:
                        lines[-1][1].append(current_image)
                    else:
                        last_image = current_image

        # 6. 分页符检测
        for run in p.runs:
            if 'lastRenderedPageBreak' in run._element.xml:
                pn += 1
                continue
            if 'w:br' in run._element.xml and 'type="page"' in run._element.xml:
                pn += 1

    # 7. 合并同一行的多个图片
    new_line = [(line[0], reduce(concat_img, line[1]) if line[1] else None)
                for line in lines]

    # 8. 处理表格
    tbls = []
    for i, tb in enumerate(self.doc.tables):
        # 8.1 获取表格层级标题
        title = self.__get_nearest_title(i, filename)

        # 8.2 构建HTML表格
        html = "<table>"
        if title:
            html += f"<caption>Table Location: {title}</caption>"
        for r in tb.rows:
            html += "<tr>"
            i = 0
            try:
                # 8.3 处理合并单元格
                while i < len(r.cells):
                    span = 1
                    c = r.cells[i]
                    for j in range(i + 1, len(r.cells)):
                        if c.text == r.cells[j].text:
                            span += 1
                            i = j
                        else:
                            break
                    i += 1
                    html += f"<td>{c.text}</td>" if span == 1 else \
                            f"<td colspan='{span}'>{c.text}</td>"
            except Exception as e:
                logging.warning(f"Error parsing table, ignore: {e}")
            html += "</tr>"
        html += "</table>"
        tbls.append(((None, html), ""))

    return new_line, tbls
```

---

## 四、表格内容处理流程

### 4.1 __extract_table_content 方法

```python
def __extract_table_content(self, tb):
    """从表格对象提取内容"""
    df = []
    # 1. 转换为DataFrame
    for row in tb.rows:
        df.append([c.text for c in row.cells])
    return self.__compose_table_content(pd.DataFrame(df))
```

### 4.2 __compose_table_content 方法

```python
def __compose_table_content(self, df):
    """组合表格内容，包含智能类型识别"""

    # 1. 定义单元格类型识别规则
    def blockType(b):
        pattern = [
            ("^(20|19)[0-9]{2}[年/-][0-9]{1,2}[月/-][0-9]{1,2}日*$", "Dt"),  # 日期
            ("^[0-9.,+%/ -]+$", "Nu"),  # 数字
            ("^[0-9A-Z/\._~-]+$", "Ca"),  # 代码
            ("^[A-Z]*[a-z' -]+$", "En"),  # 英文
            (r"^.{1}$", "Sg")  # 单字符
        ]
        for p, n in pattern:
            if re.search(p, b):
                return n

        # 2. 中文分词判断
        tks = [t for t in rag_tokenizer.tokenize(b).split() if len(t) > 1]
        if len(tks) > 3:
            return "Lx" if len(tks) >= 12 else "Tx"

        # 3. 人名识别
        if len(tks) == 1 and rag_tokenizer.tag(tks[0]) == "nr":
            return "Nr"

        return "Ot"  # 其他

    # 3. 判断表格类型
    max_type = Counter([blockType(str(df.iloc[i, j]))
                        for i in range(1, len(df))
                        for j in range(len(df.iloc[i, :]))])
    max_type = max(max_type.items(), key=lambda x: x[1])[0]

    # 4. 确定表头行
    colnm = len(df.iloc[0, :])
    hdrows = [0]
    if max_type == "Nu":
        for r in range(1, len(df)):
            tys = Counter([blockType(str(df.iloc[r, j]))
                          for j in range(len(df.iloc[r, :]))])
            tys = max(tys.items(), key=lambda x: x[1])[0]
            if tys != max_type:
                hdrows.append(r)

    # 5. 生成表格行
    lines = []
    for i in range(1, len(df)):
        if i in hdrows:
            continue
        # ... 组合表头和单元格内容

    if colnm > 3:
        return lines
    return ["\n".join(lines)]
```

---

## 五、流程图

```
┌─────────────────┐
│  DOCX文件输入    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ python-docx加载 │
│ Document对象    │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌─────────┐ ┌──────────┐
│ 段落处理 │ │ 表格处理  │
└────┬────┘ └─────┬────┘
     │            │
     ▼            ▼
┌─────────┐ ┌──────────────────┐
│ 提取文本 │ │ 表格内容→DataFrame│
│ 提取图片 │ │ 类型识别→组合     │
│ 样式处理 │ │ 层级标题→HTML     │
└────┬────┘ └────────┬─────────┘
     │               │
     └───────┬───────┘
             │
             ▼
     ┌───────────────┐
     │ sections列表   │
     │ tbls列表       │
     └───────────────┘
```

---

## 六、关键数据结构

### 6.1 sections 结构

```python
sections = [
    ("文本内容", "样式名"),
    ("另一段文本", "Heading1"),
    ...
]
```

### 6.2 tbls 结构

```python
tbls = [
    ((图片, "HTML表格内容"), "额外信息"),
    ...
]
```

---

## 七、参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| fnm | str/path | 必填 | 文件路径或BytesIO对象 |
| from_page | int | 0 | 起始页码 |
| to_page | int | 100000000 | 结束页码 |

---

## 八、调用示例

```python
# 基础解析器
parser = RAGFlowDocxParser()
sections, tables = parser("document.docx")

# 增强解析器
docx = Docx()
sections, tables = docx("document.docx")

# Markdown转换
markdown_text = docx.to_markdown("document.docx", binary=file_bytes)
```
