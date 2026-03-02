# 02-Word切片流程分析

## 一、切片函数概览

Word文档的切片处理涉及以下核心函数:

```
chunk() (rag/app/naive.py)
    │
    ├──> sections, tbls = Docx()(filename, binary)  # 解析
    │
    ├──> tbls = vision_figure_parser_docx_wrapper()  # 视觉增强
    │
    ├──> res = tokenize_table(tbls, doc, is_english)  # 表格token化
    │
    ├──> chunks, images = naive_merge_docx(...)  # 文本切片
    │
    └──> res.extend(tokenize_chunks_with_images(...))  # token化
```

---

## 二、naive_merge_docx 函数详解

### 2.1 函数签名

```python
def naive_merge_docx(sections, chunk_token_num=128, delimiter="\n。；！？"):
    """
    将Word解析的sections切片成指定token大小的chunks

    Args:
        sections: List[(文本, 图片)] 或 List[(文本, 图片, 样式)]
        chunk_token_num: 每个chunk的最大token数
        delimiter: 自定义分隔符 (格式: `分隔符1` `分隔符2`)

    Returns:
        chunks: List[str] - 切片后的文本列表
        images: List[Image] - 对应的图片列表
    """
```

### 2.2 完整流程

```python
def naive_merge_docx(sections, chunk_token_num=128, delimiter="\n。；！？"):
    if not sections:
        return [], []

    cks = []          # chunk列表
    images = []       # 图片列表
    tk_nums = []      # token计数列表

    # ===== 核心合并函数 =====
    def add_chunk(t, image, pos=""):
        nonlocal cks, images, tk_nums

        # 1. 计算token数
        tnum = num_tokens_from_string(t)

        # 2. 短文本过滤
        if tnum < 8:
            pos = ""

        # 3. 判断是否需要创建新chunk
        if not cks or tk_nums[-1] > chunk_token_num:
            # 创建新chunk
            if pos and t.find(pos) < 0:
                t += pos
            cks.append(t)
            images.append(image)
            tk_nums.append(tnum)
        else:
            # 追加到当前chunk
            if pos and cks[-1].find(pos) < 0:
                t += pos
            cks[-1] += t
            images[-1] = concat_img(images[-1], image)
            tk_nums[-1] += tnum

    # ===== 自定义分隔符处理 =====
    custom_delimiters = [m.group(1) for m in re.finditer(r"`([^`]+)`", delimiter)]
    has_custom = bool(custom_delimiters)

    if has_custom:
        # 强制分割模式
        custom_pattern = "|".join(re.escape(t) for t in
                                  sorted(set(custom_delimiters), key=len, reverse=True))
        cks, images, tk_nums = [], [], []
        pattern = r"(%s)" % custom_pattern

        for sec, image in sections:
            split_sec = re.split(pattern, sec)
            for sub_sec in split_sec:
                if not sub_sec or re.fullmatch(custom_pattern, sub_sec):
                    continue
                text_seg = "\n" + sub_sec
                cks.append(text_seg)
                images.append(image)
                tk_nums.append(num_tokens_from_string(text_seg))
        return cks, images

    # ===== 正常合并模式 =====
    for sec, image in sections:
        add_chunk("\n" + sec, image, "")

    return cks, images
```

### 2.3 切片策略

| 情况 | 处理方式 |
|------|----------|
| 当前chunk为空 | 创建新chunk |
| 当前token数 > chunk_token_num | 创建新chunk |
| 当前token数 ≤ chunk_token_num | 追加到当前chunk |
| 文本token < 8 | 过滤位置标签 |
| 有自定义分隔符 | 强制按分隔符切片 |

---

## 三、tokenize_chunks_with_images 函数详解

### 3.1 函数签名

```python
def tokenize_chunks_with_images(chunks, doc, eng, images, child_delimiters_pattern=None):
    """
    对切片后的文本进行分词处理，支持图片关联

    Args:
        chunks: List[str] - 切片后的文本
        doc: dict - 文档元数据 (docnm_kwd, title_tks等)
        eng: bool - 是否英文
        images: List[Image] - 对应的图片
        child_delimiters_pattern: str - 子分隔符正则

    Returns:
        List[dict] - token化后的chunk列表
    """
```

### 3.2 完整流程

```python
def tokenize_chunks_with_images(chunks, doc, eng, images, child_delimiters_pattern=None):
    res = []

    for ii, (ck, image) in enumerate(zip(chunks, images)):
        # 1. 过滤空白chunk
        if len(ck.strip()) == 0:
            continue

        # 2. 复制文档元数据
        d = copy.deepcopy(doc)

        # 3. 关联图片
        d["image"] = image

        # 4. 添加位置信息 (使用虚拟位置)
        add_positions(d, [[ii]*5])

        # 5. 子分隔符处理
        if child_delimiters_pattern:
            d["mom_with_weight"] = ck
            for txt in re.split(r"(%s)" % child_delimiters_pattern, ck, flags=re.DOTALL):
                dd = copy.deepcopy(d)
                tokenize(dd, txt, eng)
                res.append(dd)
            continue

        # 6. 正常分词
        tokenize(d, ck, eng)
        res.append(d)

    return res
```

### 3.3 tokenize 函数

```python
def tokenize(d, txt, eng):
    """
    对文本进行分词处理

    生成的字段:
    - content_with_weight: 原始文本
    - content_ltks: 粗粒度分词
    - content_sm_ltks: 细粒度分词
    """
    from . import rag_tokenizer

    d["content_with_weight"] = txt

    # 移除表格标签
    t = re.sub(r"</?(table|td|caption|tr|th)( [^<>]{0,12})?>", " ", txt)

    # 粗粒度分词
    d["content_ltks"] = rag_tokenizer.tokenize(t)

    # 细粒度分词
    d["content_sm_ltks"] = rag_tokenizer.fine_grained_tokenize(d["content_ltks"])
```

---

## 四、chunk() 函数中的Word处理流程

### 4.1 完整调用链

```python
def chunk(filename, binary=None, from_page=0, to_page=100000, lang="Chinese", callback=None, **kwargs):
    # 1. 配置解析
    parser_config = kwargs.get("parser_config", {
        "chunk_token_num": 512,
        "delimiter": "\n!?。；！？",
        "layout_recognize": "DeepDOC",
        "analyze_hyperlink": True
    })

    # 2. 子分隔符配置
    child_deli = re.findall(r"`([^`]+)`", parser_config.get("children_delimiter", ""))
    child_deli = sorted(set(child_deli), key=lambda x: -len(x))
    child_deli = "|".join(re.escape(t) for t in child_deli if t)

    # 3. Word文件检测
    if re.search(r"\.docx$", filename, re.IGNORECASE):
        callback(0.1, "Start to parse.")

        # 4. 超链接提取
        if parser_config.get("analyze_hyperlink", False) and is_root:
            urls = extract_links_from_docx(binary)
            # ... 递归处理超链接

        # 5. Word解析
        _SerializedRelationships.load_from_xml = load_from_xml_v2
        sections, tables = Docx()(filename, binary)

        # 6. 视觉增强处理
        tables = vision_figure_parser_docx_wrapper(
            sections=sections, tbls=tables, callback=callback, **kwargs
        )

        # 7. 表格token化
        res = tokenize_table(tables, doc, is_english)

        callback(0.8, "Finish parsing.")

        # 8. 文本切片
        chunks, images = naive_merge_docx(
            sections,
            int(parser_config.get("chunk_token_num", 128)),
            parser_config.get("delimiter", "\n!?。；！？")
        )

        # 9. 文本token化
        res.extend(tokenize_chunks_with_images(
            chunks, doc, is_english, images, child_delimiters_pattern=child_deli
        ))

        # 10. 媒体上下文附加
        if table_context_size or image_context_size:
            attach_media_context(res, table_context_size, image_context_size)

        return res
```

---

## 五、切片流程图

```
┌─────────────────┐
│  sections输入    │
│ [(文本, 图片),]  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 自定义分隔符检测 │
│ `分隔符` 格式    │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌─────────┐ ┌──────────┐
│ 强制分割 │ │ 正常合并  │
│ 按分隔符 │ │ Token控制│
└────┬────┘ └─────┬────┘
     │            │
     └─────┬──────┘
           │
           ▼
     ┌──────────────┐
     │ chunks列表   │
     │ images列表   │
     └──────┬───────┘
            │
            ▼
     ┌──────────────────┐
     │ 子分隔符处理?     │
     │ children_delimiter│
     └────┬────────┬────┘
          │ Yes    │ No
          ▼        ▼
     ┌────────┐ ┌──────────┐
     │ 细分切片│ │ 直接分词 │
     │ 多个chunk│ │ 单个chunk│
     └────┬───┘ └─────┬────┘
          │           │
          └─────┬─────┘
                │
                ▼
         ┌──────────────┐
         │ tokenize()   │
         │ 粗粒度分词    │
         │ 细粒度分词    │
         └──────────────┘
```

---

## 六、数据结构演变

### 6.1 输入: sections

```python
sections = [
    ("第一段文本", <Image对象>),
    ("第二段文本", None),
    ("表格说明", <Image对象>),
]
```

### 6.2 中间: chunks + images

```python
chunks = [
    "第一段文本\n第二段文本",  # 合并后
    "表格说明",
]

images = [
    <Image对象>,  # concat_img合并
    <Image对象>,
]
```

### 6.3 输出: token化结果

```python
[
    {
        "content_with_weight": "第一段文本\n第二段文本",
        "content_ltks": "第一 段 文本 第二 段 文本",
        "content_sm_ltks": "第一 段 文 本 第二 段 文 本",
        "docnm_kwd": "document.docx",
        "title_tks": ["document"],
        "image": <Image对象>,
        "page_num_int": [0, 0, 0, 0, 0],
        "position_int": [(0, 0, 0, 0, 0), ...],
        "top_int": [0, 0, 0, 0, 0],
    },
    {
        "content_with_weight": "表格说明",
        "content_ltks": "表格 说明",
        "content_sm_ltks": "表 格 说 明",
        "docnm_kwd": "document.docx",
        "title_tks": ["document"],
        "image": <Image对象>,
        "page_num_int": [1, 1, 1, 1, 1],
        "position_int": [(1, 0, 0, 0, 0), ...],
        "top_int": [0, 0, 0, 0, 0],
    },
]
```

---

## 七、关键参数配置

### 7.1 parser_config 配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| chunk_token_num | 512 | 每个chunk的最大token数 |
| delimiter | "\n!?。；！？" | 自定义分隔符 |
| children_delimiter | "" | 子分隔符 |
| analyze_hyperlink | True | 是否解析超链接 |
| table_context_size | 0 | 表格上下文token数 |
| image_context_size | 0 | 图片上下文token数 |

### 7.2 分隔符格式

```python
# 主分隔符 (用于合并时控制)
delimiter = "`#` `##` `---`"  # 按标题、分隔线强制分割

# 子分隔符 (用于tokenize时细分)
children_delimiter = "`\n\n`"
```

---

## 八、特殊处理

### 8.1 短文本过滤

```python
# token数 < 8 的文本会被过滤位置标签
if tnum < 8:
    pos = ""  # 移除位置信息
```

### 8.2 图片合并

```python
def concat_img(img1, img2):
    """垂直拼接两张图片"""
    if not img1 or not img2:
        return img1 or img2

    width = max(img1.size[0], img2.size[0])
    height = img1.size[1] + img2.size[1]
    new_image = Image.new('RGB', (width, height))

    new_image.paste(img1, (0, 0))
    new_image.paste(img2, (0, img1.size[1]))
    return new_image
```

### 8.3 媒体上下文附加

```python
def attach_media_context(chunks, table_context_size=0, image_context_size=0):
    """
    为表格/图片chunk附加前后文本上下文

    例如: table_context_size=100
    - 图片chunk前100 tokens的文本会被附加
    - 图片chunk后100 tokens的文本会被附加
    """
```
