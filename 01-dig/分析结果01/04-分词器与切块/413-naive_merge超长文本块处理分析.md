# naive_merge 中超长文本块的处理机制分析

> 文件位置: [rag/nlp/__init__.py:881-910](../../../rag/nlp/__init__.py#L881-L910)
> 关键问题: **单个文本块本身超过chunk_token_num限制时的处理方式**

---

## 目录

1. [问题分析](#1-问题分析)
2. [当前代码的处理逻辑](#2-当前代码的处理逻辑)
3. [存在的问题](#3-存在的问题)
4. [实际测试案例](#4-实际测试案例)
5. [与其它方法的对比](#5-与其它方法的对比)
6. [解决方案建议](#6-解决方案建议)

---

## 1. 问题分析

### 1.1 场景描述

**问题**: 当传入的文本块 `t` 本身超过 `chunk_token_num` 限制时，`add_chunk` 如何处理？

**示例**:
```python
chunk_token_num = 128  # 单个chunk限制
overlapped_percent = 10  # 重叠百分比

# 场景1: 短文本块（正常）
t1 = "这是一段较短的文本，大约20个token。"  # tnum = 20

# 场景2: 中等长度文本块（临界）
t2 = "这是一段中等长度的文本..."  # tnum = 115

# 场景3: 超长文本块（问题）
t3 = "这是一段非常长的文本，包含200个token..."  # tnum = 200
```

### 1.2 关键疑问

❓ **当 `tnum = 200 > chunk_token_num = 128` 时，会发生什么？**

---

## 2. 当前代码的处理逻辑

### 2.1 add_chunk 方法核心逻辑

```python
def add_chunk(t, pos):
    nonlocal cks, tk_nums, delimiter
    # 计算当前文本块的token数量
    tnum = num_tokens_from_string(t)

    if not pos:
        pos = ""
    if tnum < 8:
        pos = ""

    # 关键判断：是否需要创建新chunk
    if cks[-1] == "" or tk_nums[-1] > chunk_token_num * (100 - overlapped_percent)/100.:
        # 分支A：创建新chunk
        if cks:
            overlapped = RAGFlowPdfParser.remove_tag(cks[-1])
            t = overlapped[int(len(overlapped)*(100-overlapped_percent)/100.):] + t

        if t.find(pos) < 0:
            t += pos
        cks.append(t)
        tk_nums.append(tnum)  # ← 直接使用 tnum
    else:
        # 分支B：追加到当前chunk
        if cks[-1].find(pos) < 0:
            t += pos
        cks[-1] += t
        tk_nums[-1] += tnum  # ← 累加 tnum
```

### 2.2 关键发现

**重要**: `add_chunk` 方法**不会对单个文本块 `t` 进行切分**！

```python
# 计算token数
tnum = num_tokens_from_string(t)  # t 是整个传入的文本块

# 直接使用 tnum，无论多大
cks.append(t)
tk_nums.append(tnum)
```

**结论**:
- ✅ 如果 `t` 很短（如20 tokens），正常添加
- ⚠️ 如果 `t` 很长（如200 tokens），**整个文本块作为一个chunk被添加**，超出限制！

---

## 3. 存在的问题

### 3.1 问题演示

**假设场景**:
```python
sections = [
    ("这是一个超长的段落，包含了200个token的内容..." * 10, "@@1\t0\t100\t0\t500##"),
]

chunk_token_num = 128
overlapped_percent = 10

# 初始化
cks = [""]
tk_nums = [0]
```

**执行流程**:
```python
# 第一次调用 add_chunk
add_chunk("\n这是一个超长的段落...", "@@1\t0\t100\t0\t500##")

tnum = 200  # 超过限制！

# 判断
cks[-1] == ""  # True（初始状态）

# 进入分支A（创建新chunk）
if cks:
    # cks[0] == ""，所以不会提取重叠
    # overlapped = ""

cks.append("\n这是一个超长的段落...")  # 整个200 tokens的文本
tk_nums.append(200)  # 记录为200！

# 结果
cks = ["", "\n这是一个超长的段落..."]  # chunk有200 tokens！
tk_nums = [0, 200]  # 超过128的限制！
```

### 3.2 问题总结

| 问题 | 描述 | 影响 |
|------|------|------|
| **不切分长文本** | 单个 `t` 无论多长，都作为一个整体 | 可能产生超大的chunk |
| **token计数不准确** | `tk_nums` 记录的是 `tnum`，不是实际chunk的token数 | 影响后续判断 |
| **阈值失效** | 判断条件 `tk_nums[-1] > threshold` 可能永远不触发 | 导致无限追加 |

---

## 4. 实际测试案例

### 4.1 测试用例1: 超长单个文本块

**输入**:
```python
sections = [
    ("这是一段非常长的文本。" * 50, "@@1\t0\t100\t0\t500##"),  # 假设200 tokens
]

chunk_token_num = 128
```

**执行**:
```python
cks = [""]
tk_nums = [0]

add_chunk("\n这是一段非常长的文本..." * 50, "@@1\t0\t100\t0\t500##")

tnum = 200

# cks[-1] == "" → True
# 创建新chunk
cks.append(t)  # 整个200 tokens
tk_nums.append(200)
```

**结果**:
```python
cks = ["", "\n这是一段非常长的文本..." * 50]
tk_nums = [0, 200]

# 问题：chunk有200 tokens，远超128的限制！
```

---

### 4.2 测试用例2: 多个文本块，其中之一超长

**输入**:
```python
sections = [
    ("第一段，50个token。", "@@1\t0\t100\t0\t100##"),
    ("第二段，200个token。" * 10, "@@1\t0\t100\t100\t300##"),  # 超长！
    ("第三段，50个token。", "@@1\t0\t100\t300\t400##"),
]

chunk_token_num = 128
overlapped_percent = 10
```

**执行流程**:

#### Step 1: 添加第一段
```python
add_chunk("\n第一段，50个token。", "@@1\t0\t100\t0\t100##")
tnum = 50

cks[-1] == "" → True
cks.append("\n第一段，50个token。@@@1\t0\t100\t0\t100##")
tk_nums.append(50)

# cks = ["", "\n第一段..."]
# tk_nums = [0, 50]
```

#### Step 2: 添加第二段（超长）
```python
add_chunk("\n第二段，200个token..." * 10, "@@1\t0\t100\t100\t300##")
tnum = 200

# 判断
cks[-1] == "" → False
tk_nums[-1] > threshold?
  50 > 128 * 0.9 = 115.2
  50 > 115.2 → False

# 进入分支B（追加到当前chunk）
cks[-1] += "\n第二段，200个token..." * 10
tk_nums[-1] += 200

# cks = ["", "\n第一段...\n第二段..."]
# tk_nums = [0, 250]  # 50 + 200 = 250！
```

**结果**: 第二个chunk有 **250 tokens**，几乎达到限制的两倍！

---

### 4.3 测试用例3: 连续多个超长文本块

**输入**:
```python
sections = [
    ("超长段落1，200个token。" * 10, pos1),
    ("超长段落2，200个token。" * 10, pos2),
    ("超长段落3，200个token。" * 10, pos3),
]

chunk_token_num = 128
```

**执行**:
```python
# 第一个段落
add_chunk(t1, pos1)  # tnum = 200
cks[-1] == "" → True
cks = [t1]
tk_nums = [200]

# 第二个段落
add_chunk(t2, pos2)  # tnum = 200
cks[-1] == "" → False
tk_nums[-1] > threshold?
  200 > 115.2 → True
# 创建新chunk
cks = [t1, t2]  # 每个200 tokens！
tk_nums = [200, 200]

# 第三个段落
add_chunk(t3, pos3)  # tnum = 200
cks[-1] == "" → False
tk_nums[-1] > threshold?
  200 > 115.2 → True
# 创建新chunk
cks = [t1, t2, t3]  # 每个200 tokens！
tk_nums = [200, 200, 200]
```

**结果**: 所有chunk都是200 tokens，全部超限！

---

## 5. 与其它方法的对比

### 5.1 naive_merge_with_images

**代码对比**:
```python
def add_chunk(t, image, pos=""):
    # ...
    if cks[-1] == "" or tk_nums[-1] > chunk_token_num * (100 - overlapped_percent)/100.:
        if cks:
            overlapped = RAGFlowPdfParser.remove_tag(cks[-1])
            t = overlapped[int(len(overlapped)*(100-overlapped_percent)/100.):] + t
        if t.find(pos) < 0:
            t += pos
        cks.append(t)
        result_images.append(image)
        tk_nums.append(tnum)  # ← 同样的问题！
    else:
        if cks[-1].find(pos) < 0:
            t += pos
        cks[-1] += t
        result_images[-1] = concat_img(result_images[-1], image)
        tk_nums[-1] += tnum
```

**结论**: `naive_merge_with_images` **同样存在这个问题**！

---

### 5.2 实际调用场景

在 `chunk()` 方法中的调用：

```python
# rag/app/naive.py:956-961
chunks = naive_merge(
    sections, int(parser_config.get("chunk_token_num", 128)),
    parser_config.get("delimiter", "\n!?。；！？")
)
res.extend(tokenize_chunks(chunks, doc, is_english, pdf_parser, child_delimiters_pattern=child_deli))
```

**关键**: `sections` 来自哪里？

```python
# sections 是 PDF 解析后的文本块列表
# 每个元素是 (文本内容, 位置标签)
sections, tables = pdf_parser(...)
# sections = [
#   ("这是第一段文本", "@@1\t0\t100\t0\t50##"),
#   ("这是第二段文本", "@@1\t0\t100\t50\t100##"),
#   ...
# ]
```

**实际情况**:
- PDF 解析器（如 `PdfParser`）通常**不会产生单个超长的文本块**
- 文本已经被分割成较小的段落
- 但在某些情况下（如无边框的长段落），可能会产生较长的文本块

---

## 6. 解决方案建议

### 6.1 问题根源

`add_chunk` 方法假设:
✅ 传入的 `t` 是一个**较小的文本块**
✅ 通过累加多个小文本块来达到token限制

实际情况:
⚠️ 如果 `t` 本身就超过限制，会产生超大的chunk

### 6.2 解决方案

#### 方案1: 在 add_chunk 内部切分（推荐）

```python
def add_chunk(t, pos):
    nonlocal cks, tk_nums, delimiter
    tnum = num_tokens_from_string(t)

    if not pos:
        pos = ""
    if tnum < 8:
        pos = ""

    # ===== 新增：切分超长文本 =====
    if tnum > chunk_token_num:
        # 将超长文本切分为多个小块
        chunks = split_long_text(t, chunk_token_num)

        for i, chunk in enumerate(chunks):
            chunk_tnum = num_tokens_from_string(chunk)

            if i == 0:
                # 第一个块：追加到当前chunk（如果空间足够）
                if tk_nums[-1] <= chunk_token_num * (100 - overlapped_percent)/100.:
                    if cks[-1].find(pos) < 0:
                        chunk += pos
                    cks[-1] += chunk
                    tk_nums[-1] += chunk_tnum
                else:
                    # 创建新chunk
                    if cks:
                        overlapped = RAGFlowPdfParser.remove_tag(cks[-1])
                        chunk = overlapped[int(len(overlapped)*(100-overlapped_percent)/100.):] + chunk
                    if chunk.find(pos) < 0:
                        chunk += pos
                    cks.append(chunk)
                    tk_nums.append(chunk_tnum)
            else:
                # 后续块：创建新chunk
                if cks:
                    overlapped = RAGFlowPdfParser.remove_tag(cks[-1])
                    chunk = overlapped[int(len(overlapped)*(100-overlapped_percent)/100.):] + chunk
                if chunk.find(pos) < 0:
                    chunk += pos
                cks.append(chunk)
                tk_nums.append(chunk_tnum)

        return  # 提前返回

    # ===== 原有逻辑 =====
    if cks[-1] == "" or tk_nums[-1] > chunk_token_num * (100 - overlapped_percent)/100.:
        if cks:
            overlapped = RAGFlowPdfParser.remove_tag(cks[-1])
            t = overlapped[int(len(overlapped)*(100-overlapped_percent)/100.):] + t
        if t.find(pos) < 0:
            t += pos
        cks.append(t)
        tk_nums.append(tnum)
    else:
        if cks[-1].find(pos) < 0:
            t += pos
        cks[-1] += t
        tk_nums[-1] += tnum
```

**辅助函数**:
```python
def split_long_text(text, max_tokens):
    """
    将超长文本切分为多个小块

    参数:
        text: 待切分的文本
        max_tokens: 每个块的最大token数

    返回:
        切分后的文本列表
    """
    # 按句子切分（优先保持句子完整性）
    sentences = re.split(r'([。！？.!?])', text)

    chunks = []
    current_chunk = ""
    current_tokens = 0

    for i in range(0, len(sentences), 2):
        if i + 1 < len(sentences):
            sentence = sentences[i] + sentences[i + 1]  # 句子 + 标点
        else:
            sentence = sentences[i]

        sentence_tokens = num_tokens_from_string(sentence)

        if current_tokens + sentence_tokens > max_tokens:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = sentence
            current_tokens = sentence_tokens
        else:
            current_chunk += sentence
            current_tokens += sentence_tokens

    if current_chunk:
        chunks.append(current_chunk)

    return chunks
```

---

#### 方案2: 在调用前预处理（推荐，改动小）

**在 `naive_merge` 方法中**:

```python
def naive_merge(sections, chunk_token_num=128, delimiter="\n。；！？", overlapped_percent=0):
    # ...

    # 新增：预处理超长文本块
    processed_sections = []
    for sec, pos in sections:
        tnum = num_tokens_from_string(sec)

        if tnum > chunk_token_num * 0.8:  # 超过80%阈值
            # 切分超长文本
            sub_chunks = split_long_text(sec, chunk_token_num * 0.8)
            for i, sub_chunk in enumerate(sub_chunks):
                if i == 0:
                    processed_sections.append((sub_chunk, pos))
                else:
                    # 后续chunk不添加位置标签（因为属于同一个section）
                    processed_sections.append((sub_chunk, ""))
        else:
            processed_sections.append((sec, pos))

    # 使用处理后的sections
    cks = [""]
    tk_nums = [0]

    def add_chunk(t, pos):
        # 原有逻辑...

    for sec, pos in processed_sections:
        add_chunk("\n"+sec, pos)

    return cks
```

---

#### 方案3: 在 PDF 解析阶段控制（最佳）

**在 `PdfParser.__call__` 中**:

```python
# deepdoc/parser/pdf_parser.py
def __call__(self, filename, binary=None, from_page=0, to_page=100000, zoomin=3, callback=None):
    # ...

    # 垂直相邻文本块合并
    self._naive_vertical_merge(zoomin)

    # 新增：检查并切分超长文本块
    MAX_TOKENS = 512  # 根据需求调整
    for i in range(len(self.boxes)):
        text = self.boxes[i]["text"]
        tnum = num_tokens_from_string(text)

        if tnum > MAX_TOKENS:
            # 切分超长文本框
            # 这里需要实现按token切分的逻辑
            # 可能需要重新计算边界框（较复杂）
            pass

    # 最终阅读顺序重排
    self._final_reading_order_merge(zoomin)
```

**优点**: 在源头控制，避免后续处理复杂化

---

### 6.3 推荐方案

**综合考虑**:

1. **短期方案**: 在 `naive_merge` 中预处理（方案2）
   - ✅ 改动小
   - ✅ 不影响PDF解析逻辑
   - ✅ 易于测试和回滚

2. **长期方案**: 在 PDF 解析阶段控制（方案3）
   - ✅ 从源头解决问题
   - ✅ 保持语义完整性（基于段落结构切分）
   - ⚠️ 需要深入了解PDF解析逻辑

3. **不推荐方案**: 在 `add_chunk` 内部切分（方案1）
   - ❌ 逻辑复杂，容易出错
   - ❌ 可能影响现有功能
   - ❌ 难以维护

---

## 7. 总结

### 7.1 问题总结

| 问题 | 描述 | 严重程度 |
|------|------|----------|
| **不切分长文本** | 单个 `t` 超过限制时，整个作为一个chunk | 🔴 高 |
| **token计数失效** | `tk_nums` 可能记录超大值 | 🟡 中 |
| **阈值判断失效** | 判断条件可能不准确 | 🟡 中 |
| **累积效应** | 多个超长文本块累积，导致更大的chunk | 🔴 高 |

### 7.2 实际影响

**场景**: PDF 中有一个300字的长段落（约150 tokens）

```python
# 当前行为
chunks = [150_tokens_chunk]  # 超过128的限制

# 期望行为
chunks = [
    70_tokens_chunk,
    80_tokens_chunk  # 总计150，被切分为两个
]
```

**影响**:
- ❌ 检索时可能返回过长的上下文
- ❌ 向量化时可能超过模型限制
- ❌ 用户体验差（返回过多无关内容）

### 7.3 关键结论

**`add_chunk` 方法的假设**:
> 传入的 `t` 是较小的文本块，通过累加达到token限制

**实际情况**:
> 如果 `t` 本身超过限制，会产生超大的chunk

**建议**:
> 在调用 `naive_merge` 之前，对 `sections` 进行预处理，切分超长文本块

---

## 8. 相关代码位置

| 文件 | 行号 | 方法 | 说明 |
|------|------|------|------|
| [rag/nlp/__init__.py](../../../rag/nlp/__init__.py) | 881-910 | `add_chunk` | 存在问题的方法 |
| [rag/nlp/__init__.py](../../../rag/nlp/__init__.py) | 846-937 | `naive_merge` | 调用 `add_chunk` 的方法 |
| [rag/nlp/__init__.py](../../../rag/nlp/__init__.py) | 940-980 | `naive_merge_with_images` | 同样存在此问题 |
| [rag/app/naive.py](../../../rag/app/naive.py) | 956-961 | `chunk()` | 调用 `naive_merge` 的入口 |

---

## 相关文档

- [406-文本合并与切块流程.md](406-文本合并与切块流程.md) - 完整的合并流程
- [412-naive_merge的add_chunk方法详解.md](412-naive_merge的add_chunk方法详解.md) - add_chunk详解
