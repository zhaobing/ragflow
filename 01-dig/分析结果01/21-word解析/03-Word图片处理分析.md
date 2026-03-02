# Word图片处理分析

## 概述

本文档分析RAGFlow中Word文档图片提取与处理的完整机制。

---

## 1. 图片提取机制 - get_picture()

### 1.1 函数签名与位置

**文件**: `rag/app/naive.py:164-201`

```python
def get_picture(self, document, paragraph) -> Optional[Image.Image]:
```

### 1.2 XPath定位机制

```python
imgs = paragraph._element.xpath('.//pic:pic')
```

使用XPath表达式 `'.//pic:pic'` 在段落元素中查找所有图片：
- `.` - 从当前元素（段落）开始
- `//pic:pic` - 递归查找所有 `pic:pic` 命名空间的元素
- 返回图片元素列表

### 1.3 图片提取流程

```python
for img in imgs:
    # 1. 获取图片嵌入ID
    embed = img.xpath('.//a:blip/@r:embed')
    if not embed:
        continue
    embed = embed[0]

    # 2. 通过关系ID获取图片二进制数据
    related_part = document.part.related_parts[embed]
    image_blob = related_part.image.blob

    # 3. 异常处理
    except UnrecognizedImageError: ...
    except UnexpectedEndOfFileError: ...
    except InvalidImageStreamError: ...
    except UnicodeDecodeError: ...
    except Exception: ...

    # 4. 转换为PIL Image对象
    image = Image.open(BytesIO(image_blob)).convert('RGB')

    # 5. 图片合并
    if res_img is None:
        res_img = image
    else:
        res_img = concat_img(res_img, image)
```

### 1.4 异常处理机制

| 异常类型 | 说明 | 处理方式 |
|----------|------|----------|
| `UnrecognizedImageError` | 不识别的图片格式 | 跳过该图片 |
| `UnexpectedEndOfFileError` | 图片流意外结束 | 跳过该图片 |
| `InvalidImageStreamError` | 图片流损坏 | 跳过该图片 |
| `UnicodeDecodeError` | 编码错误 | 跳过该图片 |
| `Exception` | 其他异常 | 跳过该图片 |

**容错设计**: 任何图片提取失败都不会中断整个解析流程，只是记录日志并跳过。

### 1.5 图片格式转换

```python
image = Image.open(BytesIO(image_blob)).convert('RGB')
```

- `Image.open()` - 支持多种格式：PNG, JPEG, GIF, BMP等
- `.convert('RGB')` - 统一转换为RGB格式
  - 消除格式差异（RGBA → RGB, 灰度 → RGB）
  - 确保后续处理的一致性
  - 便于视觉模型处理

---

## 2. 图片合并机制 - concat_img()

### 2.1 函数签名与位置

**文件**: `rag/nlp/__init__.py:1029-1055`

```python
def concat_img(img1, img2) -> Optional[Image.Image]:
```

### 2.2 合并逻辑

```python
# 边界条件处理
if img1 and not img2:
    return img1
if not img1 and img2:
    return img2
if not img1 and not img2:
    return None

# 重复检测
if img1 is img2:
    return img1

# 内容相同检测
if isinstance(img1, Image.Image) and isinstance(img2, Image.Image):
    pixel_data1 = img1.tobytes()
    pixel_data2 = img2.tobytes()
    if pixel_data1 == pixel_data2:
        return img1
```

### 2.3 垂直拼接策略

```python
width1, height1 = img1.size
width2, height2 = img2.size

new_width = max(width1, width2)  # 取最大宽度
new_height = height1 + height2   # 高度累加
new_image = Image.new('RGB', (new_width, new_height))

new_image.paste(img1, (0, 0))       # 第一张图在顶部
new_image.paste(img2, (0, height1)) # 第二张图在下方
```

**示意图**:
```
┌─────────────────────┐
│      img1          │ ← y=0
│   (width1, h1)     │
├─────────────────────┤ ← y=height1
│      img2          │
│   (width2, h2)     │
└─────────────────────┘
```

**对齐方式**: 左对齐 (x=0)

---

## 3. Caption样式与图片关联

### 3.1 Caption识别逻辑

**文件**: `rag/app/naive.py:323-330`

```python
if p.style and p.style.name == 'Caption':
    former_image = None
    if lines and lines[-1][1] and lines[-1][2] != 'Caption':
        # 从前一个段落提取图片
        former_image = lines[-1][1].pop()
    elif last_image:
        # 使用缓存的图片
        former_image = last_image
        last_image = None
    # Caption段落关联前一个图片
    lines.append((self.__clean(p.text), [former_image], p.style.name))
```

### 3.2 关联规则

| 条件 | 行为 |
|------|------|
| 前一个段落有图片且不是Caption | 提取该图片 |
| 前一个段落是Caption | 使用 `last_image` 缓存 |
| 都不满足 | 使用None（无图片） |

### 3.3 数据结构

```python
lines = [
    (text, [image_list], style_name),
    # text: 段落文本
    # image_list: 图片列表（合并后的单一图片）
    # style_name: 样式名称，如 "Caption", "Normal", "Heading 1"
]
```

### 3.4 last_image缓存机制

```python
# 空段落中的图片被缓存
if not p.text.strip():
    if current_image := self.get_picture(self.doc, p):
        if lines:
            # 附加到前一个段落
            lines[-1][1].append(current_image)
        else:
            # 缓存等待后续关联
            last_image = current_image
```

---

## 4. 图片与Chunk关联

### 4.1 切片阶段 - naive_merge_docx()

**文件**: `rag/nlp/__init__.py:1058-1121`

```python
def naive_merge_docx(sections, chunk_token_num=128, delimiter="\n。；！？"):
    # sections: [(text, image, style), ...]
    # 返回: (chunks, images) - 两个列表长度相同
    cks = []
    images = []

    def add_chunk(t, image, pos=""):
        cks.append(t)
        images.append(image)
        tk_nums.append(num_tokens_from_string(t))

    # 切片逻辑...
    # 每个chunk与对应的图片一一关联

    return cks, images
```

**关键特性**: chunks 和 images 列表长度相同，一一对应。

### 4.2 Token化阶段 - tokenize_chunks_with_images()

**文件**: `rag/nlp/__init__.py:336-355`

```python
def tokenize_chunks_with_images(chunks, doc, eng, images, child_delimiters_pattern=None):
    res = []
    for ii, (ck, image) in enumerate(zip(chunks, images)):
        if len(ck.strip()) == 0:
            continue
        d = copy.deepcopy(doc)
        d["image"] = image  # 关联图片到chunk
        add_positions(d, [[ii]*5])  # 添加位置信息

        if child_delimiters_pattern:
            # 子分隔符处理：每个子chunk都关联同一张图片
            d["mom_with_weight"] = ck
            for txt in re.split(r"(%s)" % child_delimiters_pattern, ck, flags=re.DOTALL):
                dd = copy.deepcopy(d)
                tokenize(dd, txt, eng)
                res.append(dd)
            continue

        tokenize(d, ck, eng)
        res.append(d)
    return res
```

### 4.3 图片在最终Chunk中的存储

```python
chunk = {
    "content_with_weight": "...",
    "content_ltks": "...",
    "content_sm_ltks": "...",
    "docnm_kwd": "...",
    "title_tks": "...",
    "title_sm_tks": "...",
    "page_num_int": [ii, ii, ii, ii, ii],
    "position_int": [(ii, 0, 0, 0, 0), ...],
    "top_int": [0, ...],
    "doc_type_kwd": "image",  # 如果有图片
    "image": <PIL.Image.Image>,  # RGB格式图片
}
```

---

## 5. 视觉模型增强 - vision_figure_parser_docx_wrapper()

### 5.1 函数签名与位置

**文件**: `deepdoc/parser/figure_parser.py:40-56`

```python
def vision_figure_parser_docx_wrapper(sections, tbls, callback=None, **kwargs) -> List:
```

### 5.2 视觉模型初始化

```python
try:
    vision_model = LLMBundle(kwargs["tenant_id"], LLMType.IMAGE2TEXT)
    callback(0.7, "Visual model detected. Attempting to enhance figure extraction...")
except Exception:
    vision_model = None  # 没有配置视觉模型时跳过
```

### 5.3 视觉增强流程

```python
if vision_model:
    # 1. 准备图片数据
    figures_data = vision_figure_parser_figure_data_wrapper(sections)

    # 2. 创建视觉解析器
    docx_vision_parser = VisionFigureParser(
        vision_model=vision_model,
        figures_data=figures_data,
        **kwargs
    )

    # 3. 执行视觉分析
    boosted_figures = docx_vision_parser(callback=callback)

    # 4. 合并到表格列表
    tbls.extend(boosted_figures)

return tbls
```

### 5.4 VisionFigureParser类

**文件**: `deepdoc/parser/figure_parser.py:87-153`

```python
class VisionFigureParser:
    def __init__(self, vision_model, figures_data, *args, **kwargs):
        self.vision_model = vision_model
        self._extract_figures_info(figures_data)

    def _extract_figures_info(self, figures_data):
        self.figures = []       # PIL.Image列表
        self.descriptions = []  # 文字描述列表
        self.positions = []     # 位置信息列表

        for item in figures_data:
            # item格式: ((image, [description]), [(pn, left, right, top, bottom), ...])
            self.figures.append(item[0][0])
            self.descriptions.append(item[0][1])
            self.positions.append(item[1])

    def __call__(self, **kwargs):
        # 并发处理所有图片
        futures = []
        for idx, img_binary in enumerate(self.figures):
            futures.append(shared_executor.submit(process, idx, img_binary))

        # 等待所有结果
        for future in as_completed(futures):
            figure_num, txt = future.result()
            if txt:
                # 将视觉模型生成的描述添加到原描述前
                self.descriptions[figure_num] = txt + "\n".join(self.descriptions[figure_num])

        return self._assemble()
```

### 5.5 视觉分析提示词

```python
def vision_llm_figure_describe_prompt():
    return """
    Describe the image precisely with at most 5 sentences. Do not generate overall title.
    Focus on the text content, data, and structure visible in the image.
    """
```

### 5.6 多线程并发处理

```python
shared_executor = ThreadPoolExecutor(max_workers=10)

@timeout(30, 3)  # 单个图片30秒超时，最多重试3次
def process(figure_idx, figure_binary):
    description_text = picture_vision_llm_chunk(
        binary=figure_binary,
        vision_model=self.vision_model,
        prompt=vision_llm_figure_describe_prompt(),
        callback=callback,
    )
    return figure_idx, description_text
```

---

## 6. 图片上下文附加 - attach_media_context()

### 6.1 函数签名与位置

**文件**: `rag/nlp/__init__.py:419-450`

```python
def attach_media_context(chunks, table_context_size=0, image_context_size=0):
```

### 6.2 功能说明

为图片/表格类型的chunk附加周围的文本上下文，提高检索效果。

```python
# 配置参数
table_context_size = int(parser_config.get("table_context_size", 0) or 0)
image_context_size = int(parser_config.get("image_context_size", 0) or 0)

# 调用
if table_context_size or image_context_size:
    attach_media_context(res, table_context_size, image_context_size)
```

### 6.3 图片chunk识别

```python
def is_image_chunk(ck):
    # 方式1: 通过doc_type_kwd标记
    if ck.get("doc_type_kwd") == "image":
        return True

    # 方式2: 有图片但没有文本
    text_val = ck.get("content_with_weight") if isinstance(ck.get("content_with_weight"), str) else ck.get("text")
    has_text = isinstance(text_val, str) and text_val.strip()
    return bool(ck.get("image")) and not has_text
```

---

## 7. 完整图片处理流程图

```
Word文档 (.docx)
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Docx.__call__()                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 段落遍历                                               │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │ get_picture(document, paragraph)                │  │  │
│  │  │  ┌────────────────────────────────────────────┐ │  │  │
│  │  │  │ 1. XPath定位: .//pic:pic                   │ │  │  │
│  │  │  │ 2. 提取embed ID: a:blip/@r:embed           │ │  │  │
│  │  │  │ 3. 获取图片blob: related_parts[embed]      │ │  │  │
│  │  │  │ 4. PIL.Image: Image.open(blob).convert(RGB)│ │  │  │
│  │  │  │ 5. 合并: concat_img(res_img, image)        │ │  │  │
│  │  │  └────────────────────────────────────────────┘ │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  │                                                        │  │
│  │  Caption处理: 关联前一个段落的图片                    │  │
│  │                                                        │  │
│  └───────────────────────────────────────────────────────┘  │
│  返回: sections=[(text, image, style), ...]                 │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ vision_figure_parser_docx_wrapper()                          │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 如果配置了视觉模型 (IMAGE2TEXT):                       │  │
│  │  - 提取所有图片                                        │  │
│  │  - 并发调用视觉LLM描述图片                             │  │
│  │  - 增强图片描述信息                                    │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ naive_merge_docx(sections, chunk_token_num, delimiter)       │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 按token数切片                                          │  │
│  │ chunks = ["text1", "text2", ...]                      │  │
│  │ images = [img1, img2, ...]  ← 一一对应                │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ tokenize_chunks_with_images(chunks, doc, eng, images)        │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ for chunk, image in zip(chunks, images):              │  │
│  │   d["image"] = image  ← 关联图片                      │  │
│  │   tokenize(d, chunk, eng)                              │  │
│  │   res.append(d)                                        │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ attach_media_context(chunks, table_context_size, image_context_size) │
│  为图片chunk附加周围文本上下文                                 │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
Final Chunks (with images)
```

---

## 8. 关键参数配置

| 参数 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `chunk_token_num` | parser_config | 128 | 切片token数限制 |
| `delimiter` | parser_config | "\n!?。；！？" | 切片分隔符 |
| `children_delimiter` | parser_config | None | 子分隔符 |
| `image_context_size` | parser_config | 0 | 图片上下文附加数量 |
| `vision_model` | tenant配置 | - | 视觉LLM模型 |

---

## 9. 与PDF图片处理的对比

| 维度 | Word | PDF |
|------|------|-----|
| 图片提取 | python-docx库，DOM直接访问 | OCR视觉检测 |
| 图片定位 | XPath: `.//pic:pic` | 布局分析 + 目标检测 |
| 图片格式 | 直接从docx结构获取 | 从页面图像裁剪 |
| Caption识别 | style.name == 'Caption' | 文本位置推断 |
| 图片合并 | concat_img垂直拼接 | 视觉区域合并 |

---

## 10. 总结

Word图片处理核心流程：

1. **提取**: 通过XPath从docx的DOM结构中直接提取图片
2. **转换**: 统一转换为RGB格式
3. **合并**: 使用concat_img垂直拼接多张图片
4. **关联**: 通过Caption样式和位置关联图片与文本
5. **增强**: (可选) 使用视觉LLM生成图片描述
6. **切片**: 图片与文本chunk一一对应
7. **附加**: (可选) 为图片chunk附加文本上下文

**关键特性**:
- 高容错性：图片提取失败不中断解析
- 一对一关联：chunk与图片一一对应
- 视觉增强：可选的视觉模型支持
- 上下文附加：提高图片chunk的检索效果
