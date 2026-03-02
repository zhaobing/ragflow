# chunk() 方法综合分析

## 概述

`chunk()` 方法是RAGFlow中文件解析和切片的核心入口函数，负责将各种格式的文件解析并切分为可检索的文本块(chunks)。

**文件位置**: `rag/app/naive.py:630-984`

**函数签名**:
```python
def chunk(filename, binary=None, from_page=0, to_page=100000,
          lang="Chinese", callback=None, **kwargs):
```

---

## 一、业务逻辑

### 1.1 核心功能

`chunk()` 方法是RAGFlow文档处理的**统一入口**，实现以下核心功能：

1. **多格式支持**: 支持 docx, pdf, excel, txt, markdown, html, json等多种文件格式
2. **解析提取**: 根据文件类型调用相应的解析器提取内容
3. **智能切片**: 按token数限制和分隔符将文本切分为chunks
4. **分词处理**: 生成粗粒度和细粒度分词
5. **递归处理**: 支持嵌入文件和超链接的递归解析
6. **视觉增强**: 使用视觉模型增强图片/表格理解

### 1.2 处理流程概览

```
文件输入
    │
    ├─→ 格式识别
    │
    ├─→ 提取嵌入文件 (仅根调用)
    │
    ├─→ 分发到对应解析器
    │   ├─ Word(.docx) → Docx
    │   ├─ PDF → PdfParser
    │   ├─ Excel → ExcelParser
    │   ├─ 文本 → TxtParser
    │   ├─ Markdown → Markdown
    │   ├─ HTML → HtmlParser
    │   └─ JSON → JsonParser
    │
    ├─→ 表格处理 → tokenize_table()
    │
    ├─→ 文本合并切片
    │   ├─ 有图片 → naive_merge_with_images()
    │   ├─ Word → naive_merge_docx()
    │   └─ 其他 → naive_merge()
    │
    ├─→ 分词处理
    │   ├─ 有图片 → tokenize_chunks_with_images()
    │   └─ 无图片 → tokenize_chunks()
    │
    ├─→ 超链接递归处理
    │
    ├─→ 上下文附加
    │
    └─→ 返回chunks列表
```

---

## 二、执行流程详解

### 2.1 初始化阶段

```python
# 语言识别
is_english = lang.lower() == "english"

# 解析器配置
parser_config = kwargs.get("parser_config", {
    "chunk_token_num": 512,
    "delimiter": "\n!?。；！？",
    "layout_recognize": "DeepDOC",
    "analyze_hyperlink": True
})

# 子分隔符解析 (格式: `分隔符1`分隔符2`)
child_deli = re.findall(r"`([^`]+)`", parser_config.get("children_delimiter", ""))
child_deli = sorted(set(child_deli), key=lambda x: -len(x))
child_deli = "|".join(re.escape(t) for t in child_deli if t)

# 上下文附加配置
table_context_size = max(0, int(parser_config.get("table_context_size", 0) or 0))
image_context_size = max(0, int(parser_config.get("image_context_size", 0) or 0))

# 构建文档元数据
doc = {
    "docnm_kwd": filename,
    "title_tks": rag_tokenizer.tokenize(re.sub(r"\.[a-zA-Z]+$", "", filename))
}
doc["title_sm_tks"] = rag_tokenizer.fine_grained_tokenize(doc["title_tks"])
```

### 2.2 嵌入文件提取

```python
is_root = kwargs.get("is_root", True)
embed_res = []

if is_root:
    # 仅在根调用时提取嵌入文件
    embeds = extract_embed_file(binary)

    # 递归处理每个嵌入文件
    for embed_filename, embed_bytes in embeds:
        sub_res = chunk(embed_filename, binary=embed_bytes,
                       lang=lang, is_root=False, **kwargs)
        embed_res.extend(sub_res)
```

**支持的嵌入文件类型**:
- OOXML容器: docx, xlsx, pptx中的 `word/embeddings/`, `xl/embeddings/`
- OLE容器: doc, ppt, xls中的 `Ole10Native`流

### 2.3 Word文档处理 (.docx)

```python
if re.search(r"\.docx$", filename, re.IGNORECASE):
    # 1. 超链接提取与递归处理
    if parser_config.get("analyze_hyperlink", False) and is_root:
        urls = extract_links_from_docx(binary)
        for url in urls:
            html_bytes, metadata = extract_html(url)
            sub_url_res = chunk(url, html_bytes, is_root=False, **kwargs)
            url_res.extend(sub_url_res)

    # 2. Word解析
    _SerializedRelationships.load_from_xml = load_from_xml_v2
    sections, tables = Docx()(filename, binary)

    # 3. 视觉增强 (可选)
    tables = vision_figure_parser_docx_wrapper(sections, tables, callback, **kwargs)

    # 4. 表格token化
    res = tokenize_table(tables, doc, is_english)

    # 5. 文本切片
    chunks, images = naive_merge_docx(sections, chunk_token_num, delimiter)

    # 6. 分词处理
    res.extend(tokenize_chunks_with_images(chunks, doc, is_english, images, child_deli))

    # 7. 合并结果
    res.extend(embed_res)
    res.extend(url_res)

    # 8. 上下文附加
    if table_context_size or image_context_size:
        attach_media_context(res, table_context_size, image_context_size)

    return res
```

**Word处理特点**:
- 基于python-docx库的DOM解析
- 图片与文本一一对应
- 支持Caption样式关联图片
- 表格转为HTML格式

### 2.4 PDF文档处理

```python
elif re.search(r"\.pdf$", filename, re.IGNORECASE):
    # 1. 解析器选择
    layout_recognizer = parser_config.get("layout_recognize", "DeepDOC")
    if layout_recognizer.endswith("@mineru"):
        parser_model_name = layout_recognizer.split("@", 1)[0]
        layout_recognizer = "MinerU"

    # 2. 超链接提取
    if parser_config.get("analyze_hyperlink", False) and is_root:
        urls = extract_links_from_pdf(binary)

    # 3. PDF解析 (OCR + 布局分析)
    parser = PARSERS.get(layout_recognizer.lower(), by_plaintext)
    sections, tables, pdf_parser = parser(
        filename, binary, from_page, to_page, lang,
        callback, layout_recognizer, mineru_llm_name=parser_model_name
    )

    # 4. 表格token化
    res = tokenize_table(tables, doc, is_english)
```

**PDF处理特点**:
- 支持多种解析器: DeepDOC, MinerU, Docling, TCADP
- OCR文字识别
- 版面布局分析
- 表格结构识别

### 2.5 Excel文档处理

```python
elif re.search(r"\.(csv|xlsx?)$", filename, re.IGNORECASE):
    # 方式1: TCADP Parser (腾讯云表格解析)
    if layout_recognizer == "TCADP Parser":
        tcadp_parser = TCADPParser(table_result_type, markdown_image_response_type)
        sections, tables = tcadp_parser.parse_pdf(filepath, binary, ...)
        parser_config["chunk_token_num"] = 0

    # 方式2: DeepDOC Parser
    else:
        excel_parser = ExcelParser()
        if parser_config.get("html4excel"):
            sections = [(_, "") for _ in excel_parser.html(binary, 12) if _]
            parser_config["chunk_token_num"] = 0
        else:
            sections = [(_, "") for _ in excel_parser(binary) if _]
```

### 2.6 文本文件处理

```python
elif re.search(r"\.(txt|py|js|java|c|cpp|h|php|go|ts|sh|cs|kt|sql)$", filename, re.IGNORECASE):
    sections = TxtParser()(filename, binary,
                          parser_config.get("chunk_token_num", 128),
                          parser_config.get("delimiter", "\n!?;。；！？"))
```

### 2.7 Markdown处理

```python
elif re.search(r"\.(md|markdown)$", filename, re.IGNORECASE):
    # 1. Markdown解析
    markdown_parser = Markdown(chunk_token_num)
    sections, tables, section_images = markdown_parser(
        filename, binary, separate_tables=False,
        delimiter=delimiter, return_section_images=True
    )

    # 2. 视觉增强 (可选)
    if vision_model:
        for idx, (section_text, _) in enumerate(sections):
            if section_images[idx]:
                combined_image = section_images[idx]
                vision_parser = VisionFigureParser(vision_model, ...)
                boosted_figures = vision_parser(callback=callback)
                sections[idx] = (section_text + "\n\n" + boosted_figures, ...)

    # 3. 超链接提取
    if parser_config.get("hyperlink_urls", False) and is_root:
        for section_text in sections:
            soup = markdown_parser.md_to_html(section_text)
            urls.update(markdown_parser.get_hyperlink_urls(soup))
```

### 2.8 HTML处理

```python
elif re.search(r"\.(htm|html)$", filename, re.IGNORECASE):
    chunk_token_num = int(parser_config.get("chunk_token_num", 128))
    sections = HtmlParser()(filename, binary, chunk_token_num)
    sections = [(_, "") for _ in sections if _]
```

### 2.9 JSON处理

```python
elif re.search(r"\.(json|jsonl|ldjson)$", filename, re.IGNORECASE):
    chunk_token_num = int(parser_config.get("chunk_token_num", 128))
    sections = JsonParser(chunk_token_num)(binary)
    sections = [(_, "") for _ in sections if _]
```

### 2.10 旧版Word处理 (.doc)

```python
elif re.search(r"\.doc$", filename, re.IGNORECASE):
    from tika import parser as tika_parser
    doc_parsed = tika_parser.from_buffer(BytesIO(binary))
    if doc_parsed.get('content'):
        sections = doc_parsed['content'].split('\n')
        sections = [(_, "") for _ in sections if _]
```

### 2.11 通用切片处理

```python
# Markdown特殊处理
if is_markdown:
    # 自定义合并逻辑支持重叠
    merged_chunks = []
    merged_images = []
    overlapped_percent = int(parser_config.get("overlapped_percent", 0))

    for sec in sections:
        if current_tokens + sec_tokens > chunk_limit:
            merged_chunks.append(current_text)
            # 提取重叠部分
            if overlapped_percent > 0:
                overlap_len = int(len(current_text) * overlapped_percent / 100)
                overlap_part = current_text[-overlap_len:]
            current_text = overlap_part
        current_text += "\n" + text

    chunks = merged_chunks

# 有图片的切片
elif section_images:
    chunks, images = naive_merge_with_images(sections, section_images,
                                            chunk_token_num, delimiter)
    res.extend(tokenize_chunks_with_images(chunks, doc, is_english, images, child_deli))

# 无图片的切片
else:
    chunks = naive_merge(sections, chunk_token_num, delimiter)
    res.extend(tokenize_chunks(chunks, doc, is_english, pdf_parser, child_deli))
```

### 2.12 超链接递归处理

```python
if urls and parser_config.get("analyze_hyperlink", False) and is_root:
    for index, url in enumerate(urls):
        html_bytes, metadata = extract_html(url)
        if html_bytes:
            sub_url_res = chunk(url, html_bytes, is_root=False, **kwargs)
            url_res.extend(sub_url_res)
```

### 2.13 结果合并与上下文附加

```python
# 合并所有结果
if embed_res:
    res.extend(embed_res)
if url_res:
    res.extend(url_res)

# 为表格和图片附加上下文
if table_context_size or image_context_size:
    attach_media_context(res, table_context_size, image_context_size)

return res
```

---

## 三、技术要点

### 3.1 文件格式识别

使用正则表达式匹配文件扩展名：

| 格式 | 正则表达式 |
|------|-----------|
| Word | `\.docx$` |
| PDF | `\.pdf$` |
| Excel | `\.(csv\|xlsx?)$` |
| 文本 | `\.(txt\|py\|js\|java\|c\|cpp\|h\|php\|go\|ts\|sh\|cs\|kt\|sql)$` |
| Markdown | `\.(md\|markdown)$` |
| HTML | `\.(htm\|html)$` |
| JSON | `\.(json\|jsonl\|ldjson)$` |
| 旧Word | `\.doc$` |

### 3.2 解析器映射

```python
PARSERS = {
    "deepdoc": DeepDOCPdfParser,
    "mineru": MinerUParser,
    "tcadp": TCADPParser,
    "docling": DoclingParser,
    "plaintext": by_plaintext,
    ...
}
```

### 3.3 切片算法对比

| 函数 | 用途 | 特点 |
|------|------|------|
| naive_merge | PDF通用切片 | 支持重叠，保留位置标签 |
| naive_merge_docx | Word专用切片 | 图片一一对应 |
| naive_merge_with_images | 带图片切片 | 图片合并 |
| Markdown自定义 | Markdown切片 | 支持重叠百分比 |

### 3.4 分词处理流程

```python
tokenize_chunks_with_images(chunks, doc, is_english, images, child_delimiters_pattern):
    for ck, image in zip(chunks, images):
        d = copy.deepcopy(doc)
        d["image"] = image
        add_positions(d, [[ii]*5])

        if child_delimiters_pattern:
            # 子分隔符处理
            d["mom_with_weight"] = ck
            for txt in re.split(child_delimiters_pattern, ck):
                dd = copy.deepcopy(d)
                tokenize(dd, txt, eng)
                res.append(dd)
        else:
            tokenize(d, ck, eng)
            res.append(d)
```

### 3.5 递归调用保护

```python
is_root = kwargs.get("is_root", True)

# 防止无限递归
if is_root:
    # 提取嵌入文件
    # 提取超链接
else:
    # 递归调用，不再处理嵌入文件和超链接
```

### 3.6 进度回调机制

```python
callback(prog, msg)
# 示例:
callback(0.1, "Start to parse.")
callback(0.8, "Finish parsing.")
callback(1.0, "Task done.")
```

### 3.7 错误处理

```python
try:
    sub_res = chunk(url, html_bytes, is_root=False, **kwargs)
except Exception as e:
    # 降级处理
    sub_res = chunk(f"{index}.html", html_bytes, is_root=False, **kwargs)
```

---

## 四、数据流转

### 4.1 输入数据

```python
{
    "filename": str,          # 文件名
    "binary": bytes,          # 文件二进制
    "from_page": int,         # 起始页
    "to_page": int,           # 结束页
    "lang": str,              # 语言
    "parser_config": dict,    # 解析器配置
    "tenant_id": str,         # 租户ID
    "kb_id": str,             # 知识库ID
}
```

### 4.2 中间数据

```python
# 解析结果
sections: [(text, position), ...]
tables: [((image, rows), positions), ...]
section_images: [PIL.Image, ...]

# 切片结果
chunks: [str, ...]
images: [PIL.Image, ...]
```

### 4.3 输出数据

```python
[
    {
        "id": str,                    # Chunk唯一ID
        "doc_id": str,                # 文档ID
        "kb_id": str,                 # 知识库ID
        "content_with_weight": str,   # 原始内容
        "content_ltks": str,          # 粗粒度分词
        "content_sm_ltks": str,       # 细粒度分词
        "docnm_kwd": str,             # 文档名
        "title_tks": str,             # 标题分词
        "title_sm_tks": str,          # 标题细粒度分词
        "page_num_int": List[int],    # 页码
        "position_int": List[tuple],  # 位置坐标
        "top_int": List[int],         # 顶部坐标
        "doc_type_kwd": str,          # 文档类型
        "image": PIL.Image,           # 关联图片
        "img_id": str,                # 图片ID(MinIO)
        "mom_with_weight": str,       # Mother chunk内容
        "mom_id": str,                # Mother chunk ID
        ...
    },
    ...
]
```

---

## 五、配置参数详解

### 5.1 核心参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| chunk_token_num | int | 512 | 每个chunk的最大token数 |
| delimiter | str | "\n!?。；！？" | 切片分隔符 |
| children_delimiter | str | None | 子分隔符(格式: `分隔符1`分隔符2`) |
| layout_recognize | str | "DeepDOC" | PDF布局识别器 |
| analyze_hyperlink | bool | True | 是否分析超链接 |
| table_context_size | int | 0 | 表格上下文附加数量 |
| image_context_size | int | 0 | 图片上下文附加数量 |
| overlapped_percent | int | 0 | 重叠百分比(0-90) |

### 5.2 分隔符格式

```python
# 主分隔符: 直接分隔
delimiter = "\n!?。；！？"

# 子分隔符: 格式需要用反引号包裹
children_delimiter = "`##`###`###`"
# 解析后: ["##", "###", "###"]
```

---

## 六、总结

### 6.1 chunk()方法的核心价值

1. **统一接口**: 为所有文件格式提供统一的处理入口
2. **格式适配**: 根据文件类型自动选择最佳解析策略
3. **智能切片**: 按语义和token数进行智能分块
4. **扩展性强**: 易于添加新的文件格式支持
5. **递归处理**: 支持嵌入文件和超链接的深度解析

### 6.2 技术亮点

- **多解析器支持**: DeepDOC, MinerU, Docling, TCADP等
- **视觉增强**: 集成多模态大模型提升理解能力
- **递归保护**: 防止无限递归的设计
- **容错机制**: 多层降级处理保证稳定性
- **进度反馈**: 实时回调处理进度

### 6.3 调用链路总结

```
chunk()
    ├── 嵌入文件提取 → chunk(is_root=False)
    ├── Word解析 → Docx() → naive_merge_docx()
    ├── PDF解析 → PdfParser → naive_merge()
    ├── Excel解析 → ExcelParser
    ├── Markdown解析 → Markdown → 自定义合并
    ├── 其他格式解析
    ├── 表格处理 → tokenize_table()
    ├── 文本切片 → naive_merge*()
    ├── 分词处理 → tokenize_chunks*()
    ├── 超链接处理 → chunk(is_root=False)
    └── 上下文附加 → attach_media_context()
```
