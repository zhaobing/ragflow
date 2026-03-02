# Word与PDF解析对比分析

## 概述

本文档对比RAGFlow中Word(.docx)和PDF文档解析的异同。

---

## 1. 解析方式对比

### 1.1 Word解析 - python-docx库

**特点**: 基于DOM结构的直接访问

```python
# rag/app/naive.py - Docx类
class Docx(DocxParser):
    def __call__(self, filename, binary=None, from_page=0, to_page=100000):
        self.doc = Document(BytesIO(binary))  # python-docx

        # 直接访问段落和表格
        for p in self.doc.paragraphs:
            text = p.text
            style = p.style.name

        for tb in self.doc.tables:
            for row in tb.rows:
                for cell in row.cells:
                    text = cell.text
```

**优势**:
- 结构准确，无识别错误
- 速度快，无需OCR
- 格式信息完整保留

**限制**:
- 仅支持.docx格式
- 不支持.doc等旧格式

### 1.2 PDF解析 - OCR + 布局分析

**特点**: 基于视觉的深度学习模型

```python
# rag/app/naive.py - Pdf类
class Pdf(PdfParser):
    def __call__(self, filename, binary=None, from_page=0, to_page=100000):
        # 1. PDF转图像
        self.__images__(binary, zoomin, from_page, to_page)

        # 2. OCR文字识别
        # 3. 版面布局分析
        self._layouts_rec(zoomin)

        # 4. 表格结构识别
        self._table_transformer_job(zoomin)

        # 5. 文本合并
        self._text_merge(zoomin=zoomin)

        # 6. 提取表格和图片
        tbls = self._extract_table_figure(True, zoomin, True, True)
```

**优势**:
- 支持扫描版PDF
- 支持各种PDF版本
- 可处理复杂版面

**限制**:
- 依赖OCR准确率
- 处理速度较慢
- 可能产生识别错误

---

## 2. 切片方式对比

### 2.1 Word切片 - naive_merge_docx()

**文件**: `rag/nlp/__init__.py:1058-1107`

```python
def naive_merge_docx(sections, chunk_token_num=128, delimiter="\n。；！？"):
    """
    Word专用切片函数

    特点:
    - 无重叠合并
    - 图片与文本一一对应
    - 位置标记简单
    """
    cks, images, tk_nums = [], [], []

    def add_chunk(t, image, pos=""):
        if not cks or tk_nums[-1] > chunk_token_num:
            cks.append(t)
            images.append(image)
            tk_nums.append(tnum)
        else:
            cks[-1] += t
            images[-1] = concat_img(images[-1], image)  # 图片垂直合并
            tk_nums[-1] += tnum

    return cks, images
```

### 2.2 PDF切片 - naive_merge()

**文件**: `rag/nlp/__init__.py:845-937`

```python
def naive_merge(sections, chunk_token_num=128, delimiter="\n。；！？", overlapped_percent=0):
    """
    PDF通用切片函数

    特点:
    - 支持重叠合并 (overlapped_percent)
    - 保留位置标签 (@@页码 x0 x1 top bottom##)
    - 从上一个chunk末尾提取重叠内容
    """
    cks, tk_nums = [""], [0]

    def add_chunk(t, pos):
        if cks[-1] == "" or tk_nums[-1] > chunk_token_num * (100 - overlapped_percent)/100.:
            # 从上一个chunk提取重叠部分
            overlapped = RAGFlowPdfParser.remove_tag(cks[-1])
            t = overlapped[int(len(overlapped)*(100-overlapped_percent)/100.):] + t
            cks.append(t)

    return cks
```

### 2.3 切片功能对比

| 功能 | Word | PDF |
|------|------|-----|
| 重叠合并 | ❌ 不支持 | ✅ 支持 |
| 位置标签 | ❌ 无 | ✅ @@...##格式 |
| 图片关联 | ✅ 一一对应 | ✅ 支持合并 |
| 自定义分隔符 | ✅ 支持 | ✅ 支持 |
| 子分隔符 | ✅ 支持 | ✅ 支持 |

---

## 3. 图片处理对比

### 3.1 Word图片提取

**方式**: 直接从docx DOM提取

```python
def get_picture(document, paragraph):
    # XPath定位
    imgs = paragraph._element.xpath('.//pic:pic')

    for img in imgs:
        # 获取图片嵌入ID
        embed = img.xpath('.//a:blip/@r:embed')[0]

        # 从relationships获取图片
        related_part = document.part.related_parts[embed]
        image_blob = related_part.image.blob

        # 转换为PIL Image
        image = Image.open(BytesIO(image_blob)).convert('RGB')

        # 合并多张图片
        res_img = concat_img(res_img, image)
```

**特点**:
- 100%准确
- 原始分辨率
- 格式统一为RGB

### 3.2 PDF图片提取

**方式**: 布局分析 + 区域裁剪

```python
# 版面分析识别图片区域
self._layouts_rec(zoomin)

# 提取图片区域
tbls, figures = self._extract_table_figure(True, zoomin, True, True, True)

# figures格式: [(image, [description])]
```

**特点**:
- 依赖版面识别准确率
- 可能误识别图表
- 需要人工校正

---

## 4. 表格处理对比

### 4.1 Word表格

**提取方式**: DOM遍历

```python
for tb in self.doc.tables:
    for row in tb.rows:
        for cell in row.cells:
            text = cell.text
```

**输出格式**: HTML字符串

```html
<table>
    <caption>Table Location: 文档名 > 标题</caption>
    <tr>
        <td>单元格1</td>
        <td colspan='2'>合并单元格</td>
    </tr>
</table>
```

**特点**:
- 结构完整
- 单元格内容准确
- 合并单元格检测通过文本相同实现
- 保留层级标题信息

### 4.2 PDF表格

**提取方式**: 表格识别模型

```python
# 1. 表格结构识别
self._table_transformer_job(zoomin)

# 2. 表格区域提取
tbls = self._extract_table_figure(True, zoomin, True, True)

# 输出: (image, rows) 或 (image, text)
```

**输出格式**: 图片 + 文本行

```python
[
    ((<PIL.Image>, ["行1内容", "行2内容", ...]), [(pn, left, right, top, bottom)]),
    ...
]
```

**特点**:
- 需要表格识别模型
- 保留表格截图
- 可能识别错误

---

## 5. 分页处理对比

### 5.1 Word分页

**检测方式**: 分页符标记

```python
for run in p.runs:
    # 方法1: lastRenderedPageBreak
    if 'lastRenderedPageBreak' in run._element.xml:
        pn += 1

    # 方法2: type="page"
    if 'w:br' in run._element.xml and 'type="page"' in run._element.xml:
        pn += 1
```

**特点**:
- 逻辑分页
- 准确度高
- 依赖文档创建时的分页设置

### 5.2 PDF分页

**检测方式**: 物理页面

```python
# 每个PDF页面独立处理
for page in pdf.pages:
    # 转换为图像
    page_image = convert_to_image(page)

    # OCR识别
    o_results = ocr.ocr(page_image)
```

**特点**:
- 物理分页
- 每页独立图像
- 页面边界清晰

---

## 6. 位置信息对比

### 6.1 Word位置信息

**特点**: 无精确位置信息

```python
# Word解析不保留位置坐标
sections = [
    (text, image, style),
    ...
]
```

**原因**: Word文档是流式排版，位置由渲染引擎动态计算。

### 6.2 PDF位置信息

**特点**: 精确的页面坐标

```python
# 位置标签格式: @@页码1-页码2-...	x0	y0	x1	y1##
sections = [
    (text, "@@1-2	100	200	500	300##"),
    ...
]
```

**用途**:
- 高亮显示
- 引用定位
- 可视化调试

---

## 7. 性能对比

| 指标 | Word | PDF |
|------|------|-----|
| 解析速度 | 快 (~1秒/文档) | 慢 (~5-30秒/文档) |
| 内存占用 | 低 | 高 (需加载页面图像) |
| CPU占用 | 低 | 高 (OCR+模型推理) |
| 准确率 | 100% | 90-99% (依赖质量) |

---

## 8. 总结

| 维度 | Word | PDF |
|------|------|-----|
| 解析库 | python-docx | OCR + Layout Analysis |
| 数据来源 | DOM结构 | 视觉识别 |
| 切片函数 | naive_merge_docx | naive_merge |
| 图片提取 | 直接读取 | 视觉检测 |
| 表格输出 | HTML字符串 | 图片 + 文本 |
| 分页检测 | 分页符标记 | 物理页面 |
| 位置信息 | 无 | 精确坐标 |
| 速度 | 快 | 慢 |
| 准确率 | 100% | 90-99% |

**选择建议**:
- **Word**: 原始文档是docx格式时优先使用
- **PDF**: 扫描文档或PDF格式时使用
- **混合**: 同一批次可同时处理两种格式
