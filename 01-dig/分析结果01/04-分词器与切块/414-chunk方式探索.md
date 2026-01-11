# Chunk方式探索：语义完整性 vs Token限制

> 相关文件: [rag/nlp/__init__.py](../../../rag/nlp/__init__.py)
> 相关方法: `naive_merge()`, `naive_merge_with_images()`
> 输出位置: [01-dig/分析结果01/04-分词器与切块/414-chunk方式探索.md](414-chunk方式探索.md)

---

## 目录

1. [问题分析：Token-based Chunk的语义缺失](#1-问题分析token-based-chunk的语义缺失)
2. [Case1: 列表场景的语义破坏](#2-case1-列表场景的语义破坏)
3. [Case2: 章节结构的语义破坏](#3-case2-章节结构的语义破坏)
4. [业界推荐的Chunk策略](#4-业界推荐的chunk策略)
5. [RAGFlow中的改进方案](#5-ragflow中的改进方案)
6. [实现方案与代码示例](#6-实现方案与代码示例)
7. [评估与对比](#7-评估与对比)

---

## 1. 问题分析：Token-based Chunk的语义缺失

### 1.1 当前机制

**RAGFlow的chunk策略**:
```python
# rag/nlp/__init__.py:881-903
def add_chunk(t, pos):
    # 基于token数量判断是否创建新chunk
    if cks[-1] == "" or tk_nums[-1] > chunk_token_num * (100 - overlapped_percent)/100.:
        # 创建新chunk
        cks.append(t)
        tk_nums.append(tnum)
    else:
        # 追加到当前chunk
        cks[-1] += t
        tk_nums[-1] += tnum
```

**核心逻辑**:
- ✅ 简单高效
- ✅ 可控的chunk大小
- ⚠️ **完全忽略语义边界**

### 1.2 语义完整性问题

**问题本质**:
```
文本的语义结构 ≠ Token数量

示例:
- 段落边界：通过\n\n或缩进识别
- 列表结构：通过项目符号或数字识别
- 章节结构：通过标题层级识别
- 代码块：通过```或缩进识别
```

**冲突点**:
```
语义单元: 一个列表项（完整语义）
Token数量: 50 tokens

Chunk限制: 128 tokens
当前行为: 可能将列表项从中间切断！

后果:
- 上半chunk: "1. 第一项内容..."
- 下半chunk: "...内容的一部分"
```

---

## 2. Case1: 列表场景的语义破坏

### 2.1 场景描述

**示例文本**:
```markdown
## 机器学习算法分类

机器学习算法可以分为以下几类：

1. 监督学习
   - 使用标记数据训练
   - 包括分类和回归问题
   - 典型算法：SVM、随机森林、神经网络

2. 无监督学习
   - 使用未标记数据发现模式
   - 包括聚类和降维
   - 典型算法：K-means、PCA、自编码器

3. 强化学习
   - 通过与环境交互学习
   - 基于奖励机制优化策略
   - 典型应用：游戏AI、机器人控制
```

### 2.2 Token-based Chunk结果

**假设**: `chunk_token_num = 100`, `overlapped_percent = 10`

**执行结果**:
```
Chunk 1 (0-100 tokens):
"## 机器学习算法分类

机器学习算法可以分为以下几类：

1. 监督学习
   - 使用标记数据训练
   - 包括分类和回"

Chunk 2 (90-190 tokens, 重叠10 tokens):
"归问题
   - 典型算法：SVM、随机森林、神经网络

2. 无监督学习
   - 使用未标记数据发现模式
   - 包括聚类和降维"
```

### 2.3 语义缺失分析

| 问题 | 描述 | 影响 |
|------|------|------|
| **列表项被切断** | "包括分类和回" 被分割到两个chunk | 检索时无法获得完整信息 |
| **上下文丢失** | Chunk 2 没有标题，不知道"归问题"是什么 | 用户困惑："什么归问题？" |
| **层级关系破坏** | 缩进关系丢失，无法判断子项归属 | 难以理解文档结构 |
| **关键信息缺失** | "典型算法：SVM"被拆分 | 检索"监督学习算法"可能漏掉SVM |

### 2.4 检索场景的影响

**用户查询**: "监督学习有哪些典型算法？"

**期望结果**: 返回包含完整列表的chunk
```
"1. 监督学习
   - 典型算法：SVM、随机森林、神经网络"
```

**实际结果**:
- Chunk 1: "1. 监督学习\n  - 包括分类和回" ← 不完整
- Chunk 2: "归问题\n  - 典型算法：SVM..." ← 缺少上下文

**召回失败**: 用户只看到"归问题"和"SVM"，不知道它们之间的关系！

---

## 3. Case2: 章节结构的语义破坏

### 3.1 场景描述

**示例文本**:
```markdown
# 第三章 深度学习基础

## 3.1 神经网络原理

神经网络是受生物大脑启发而来的计算模型。它由多层神经元组成，每层神经元与下一层全连接。

## 3.2 前向传播算法

前向传播是指数据从输入层流向输出层的过程。每一层神经元接收上一层的输出，经过激活函数处理后传递给下一层。

### 3.2.1 激活函数

激活函数引入非线性特性，常见的激活函数包括：

1. Sigmoid函数
2. Tanh函数
3. ReLU函数
4. Leaky ReLU函数

## 3.3 反向传播算法

反向传播是训练神经网络的核心算法...
```

### 3.2 Token-based Chunk结果

**假设**: `chunk_token_num = 128`

**执行结果**:
```
Chunk 1 (0-128 tokens):
"# 第三章 深度学习基础

## 3.1 神经网络原理

神经网络是受生物大脑启发而来的计算模型。它由多层神经元组成，每层神经元与下一层全连接。

## 3.2 前向传播算法

前向传播是指数据从输入层流向输出层的过程。每一层神经元接收上一层的输出，经过激活函数处理"

Chunk 2 (115-243 tokens):
"后传递给下一层。

### 3.2.1 激活函数

激活函数引入非线性特性，常见的激活函数包括：

1. Sigmoid函数
2. Tanh函数
3. ReLU函数
4. Leaky ReLU函数

## 3.3 反向传播算法

反向传播是训练神经网络的核心算法..."
```

### 3.3 语义缺失分析

| 问题 | 描述 | 影响 |
|------|------|------|
| **小节标题分离** | "## 3.2"在Chunk 1，"### 3.2.1"在Chunk 2 | 丢失层级关系 |
| **主题切换** | Chunk 1 讲"前向传播"，Chunk 2 跳到"激活函数" | 语义不连贯 |
| **上下文断裂** | "处理"和"后传递"被分割 | 无法理解完整句子 |
| **结构信息丢失** | 标题层级混乱，难以导航 | 用户不知道"激活函数"属于哪个部分 |

### 3.4 检索场景的影响

**用户查询**: "激活函数有哪些？"

**期望结果**: 返回包含完整列表和上下文的chunk
```
"### 3.2.1 激活函数

激活函数引入非线性特性，常见的激活函数包括：

1. Sigmoid函数
2. Tanh函数
3. ReLU函数
4. Leaky ReLU函数"
```

**实际结果**:
- Chunk 2: 返回列表，但缺少"激活函数引入非线性特性"的上下文
- 用户困惑: "这些函数有什么特点？什么时候用？"

---

## 4. 业界推荐的Chunk策略

### 4.1 策略分类

#### 按语义层级分类

```
Level 1: 字符级 (Character-level)
  - 简单但破坏语义
  - 很少使用

Level 2: Token级 (Token-based)
  - RAGFlow当前使用
  - ✅ 简单可控
  - ⚠️ 破坏语义边界

Level 3: 句子级 (Sentence-based)
  - 按句子切分
  - 保持句子完整性
  - 可能破坏段落完整性

Level 4: 段落级 (Paragraph-based)
  - 按段落切分
  - 保持段落完整性
  - 段落可能过长

Level 5: 语义单元级 (Semantic-unit-based)
  - 按列表项、代码块、小节切分
  - 最佳语义完整性
  - 实现复杂

Level 6: 结构感知级 (Structure-aware)
  - 理解文档结构（标题、列表、表格）
  - 智能切分
  - 最优但最复杂
```

---

### 4.2 主流方案对比

#### 方案1: Fixed-size Chunking (固定大小)

**代表**: RAGFlow, LangChain `RecursiveCharacterTextSplitter`

**原理**:
```python
chunks = []
current_chunk = ""
current_tokens = 0

for sentence in sentences:
    sentence_tokens = num_tokens(sentence)

    if current_tokens + sentence_tokens > chunk_size:
        chunks.append(current_chunk)
        current_chunk = sentence
        current_tokens = sentence_tokens
    else:
        current_chunk += sentence
        current_tokens += sentence_tokens
```

**优点**:
- ✅ 实现简单
- ✅ 可控的chunk大小
- ✅ 适合均匀分布的文本

**缺点**:
- ❌ 破坏语义边界（句子、段落、列表）
- ❌ 可能将相关内容分割到不同chunk
- ❌ 重叠可能不够（需要手动调整）

**适用场景**:
- 文档结构简单
- 段落长度均匀
- 对语义完整性要求不高

---

#### 方案2: Semantic Chunking (语义切分)

**代表**: LlamaIndex `SemanticSplitter`, Unstructured

**原理**:
```python
# 基于句子相似度切分
chunks = []
current_chunk = ""
last_similarity = 0

for sentence in sentences:
    # 计算当前句子与chunk最后一句话的相似度
    similarity = cosine_similarity(
        embed(current_chunk_last_sentence),
        embed(current_sentence)
    )

    if similarity < threshold:  # 相似度低，主题切换
        chunks.append(current_chunk)
        current_chunk = sentence
    else:
        current_chunk += sentence
```

**优点**:
- ✅ 保持主题一致性
- ✅ 在语义边界处切分
- ✅ 提高chunk质量

**缺点**:
- ❌ 需要embedding模型（增加开销）
- ❌ 相似度阈值难以调优
- ❌ 可能产生不均匀的chunk大小

**适用场景**:
- 文档有明确主题划分
- 需要高质量的chunk
- 可以容忍额外的计算开销

---

#### 方案3: Structure-aware Chunking (结构感知)

**代表**: Unstructured, Custom solutions

**原理**:
```python
# 解析文档结构
document = parse_structure(markdown_text)

chunks = []
for section in document.sections:
    for element in section.elements:
        if element.type == "paragraph":
            chunks.append(create_chunk(element))
        elif element.type == "list":
            # 按列表项分组
            list_items = group_by_semantic_unit(element.items)
            for items in list_items:
                chunks.append(create_chunk(items))
        elif element.type == "code":
            # 保持代码块完整
            chunks.append(create_chunk(element))
```

**优点**:
- ✅ 完美保持语义完整性
- ✅ 保留结构信息（标题、列表、表格）
- ✅ 最符合人类阅读习惯

**缺点**:
- ❌ 实现复杂
- ❌ 依赖文档解析器（Markdown、HTML、PDF）
- ❌ 不同格式需要不同处理逻辑

**适用场景**:
- 结构化文档（Markdown、HTML）
- 需要高质量的检索结果
- 可以接受复杂的实现

---

#### 方案4: Recursive Chunking (递归切分)

**代表**: LangChain `RecursiveCharacterTextSplitter`

**原理**:
```python
def recursive_split(text, separators, chunk_size, overlap):
    """
    递归切分文本

    separators: ["\n\n", "\n", "。", ""]
    - 先按段落切分（\n\n）
    - 如果段落太大，按句子切分（\n）
    - 如果句子太大，按字切分（。）
    - 最后按字符切分（""）
    """

    for separator in separators:
        if separator in text:
            chunks = text.split(separator)

            # 检查每个chunk大小
            for chunk in chunks:
                if num_tokens(chunk) > chunk_size:
                    # 递归调用，使用下一个分隔符
                    return recursive_split(
                        chunk,
                        next_separators,
                        chunk_size,
                        overlap
                    )

            # 所有chunk都符合大小
            return add_overlap(chunks, overlap)

    # 没有分隔符可用，强制切分
    return force_split(text, chunk_size, overlap)
```

**优点**:
- ✅ 优先使用高层级分隔符（段落、句子）
- ✅ 降级使用低层级分隔符
- ✅ 平衡语义完整性和chunk大小

**缺点**:
- ❌ 仍然可能在低层级切分（破坏语义）
- ❌ 递归逻辑复杂
- ❌ 需要精心设计分隔符优先级

**适用场景**:
- 文档有多层结构
- 需要平衡语义和大小
- LangChain用户

---

#### 方案5: Document-specific Chunking (文档特定)

**代表**: 专用PDF解析器（如 `PdfElementExtractor`）

**原理**:
```python
# 针对PDF的特殊处理
class PDFChunker:
    def chunk(self, pdf_document):
        chunks = []

        # 1. 按页分割
        for page in pdf_document.pages:
            # 2. 按版面元素分割
            for element in page.elements:
                if element.type == "text_block":
                    # 检测边界（段落、列表）
                    if self.is_paragraph_end(element):
                        chunks.append(current_chunk)
                        current_chunk = ""
                    current_chunk += element.text

                elif element.type == "list":
                    # 保持列表项完整
                    list_chunks = self.chunk_list(element)
                    chunks.extend(list_chunks)

                elif element.type == "table":
                    # 表格单独作为chunk
                    chunks.append(self.extract_table(element))

        return chunks
```

**优点**:
- ✅ 完全适配PDF格式
- ✅ 保留文档原始结构
- ✅ 高质量chunk

**缺点**:
- ❌ 仅适用于PDF
- ❌ 依赖PDF解析器质量
- ❌ 不同PDF格式需要不同处理

**适用场景**:
- PDF文档为主
- 需要高质量的结构化chunk
- 企业级应用

---

### 4.3 方案对比总结

| 方案 | 语义完整性 | 实现难度 | 计算开销 | 适用场景 |
|------|-----------|----------|----------|----------|
| **Fixed-size** | ⭐⭐ | 简单 | 低 | 简单文档 |
| **Semantic** | ⭐⭐⭐⭐ | 中等 | 中（embedding） | 主题明确的文档 |
| **Structure-aware** | ⭐⭐⭐⭐⭐ | 复杂 | 低 | 结构化文档 |
| **Recursive** | ⭐⭐⭐ | 中等 | 低 | 多层结构文档 |
| **Document-specific** | ⭐⭐⭐⭐⭐ | 很复杂 | 低 | 特定格式（PDF） |

---

## 5. RAGFlow中的改进方案

### 5.1 当前机制回顾

**RAGFlow的chunk流程**:
```python
# 1. PDF解析 → sections (文本块列表)
sections = [
    ("段落1文本", "@@1\t0\t100\t0\t50##"),
    ("段落2文本", "@@1\t0\t100\t50\t100##"),
    ...
]

# 2. naive_merge → chunks (基于token合并)
chunks = naive_merge(
    sections,
    chunk_token_num=128,
    delimiter="\n!?。；！？"
)

# 3. tokenize_chunks → 添加位置标签和分词
res = tokenize_chunks(chunks, doc, is_english, pdf_parser)
```

**问题**:
- ❌ `naive_merge` 仅基于token数量，忽略语义边界
- ❌ `delimiter` 参数未充分利用
- ❌ 没有识别列表、章节等结构

---

### 5.2 改进方案1: 增强Delimiter感知

**原理**: 利用 `delimiter` 参数进行语义切分

**实现**:
```python
def naive_merge_enhanced(sections, chunk_token_num=128,
                         delimiter="\n!?。；！？", overlapped_percent=0):
    from deepdoc.parser.pdf_parser import RAGFlowPdfParser

    if not sections:
        return []
    if isinstance(sections, str):
        sections = [sections]
    if isinstance(sections[0], str):
        sections = [(s, "") for s in sections]

    # 解析分隔符
    delimiters = list(set(delimiter))  # 去重

    cks = [""]
    tk_nums = [0]

    def add_chunk(t, pos):
        nonlocal cks, tk_nums

        tnum = num_tokens_from_string(t)

        if not pos:
            pos = ""
        if tnum < 8:
            pos = ""

        # 关键改进：按delimiter切分当前文本块
        sub_chunks = split_by_delimiters(t, delimiters)

        for i, sub_chunk in enumerate(sub_chunks):
            sub_tnum = num_tokens_from_string(sub_chunk)

            # 判断是否需要创建新chunk
            if cks[-1] == "" or tk_nums[-1] > chunk_token_num * (100 - overlapped_percent)/100.:
                if cks and i > 0:  # 不是第一个子块
                    # 添加重叠
                    overlapped = RAGFlowPdfParser.remove_tag(cks[-1])
                    overlap_part = overlapped[int(len(overlapped)*(100-overlapped_percent)/100.):]
                    sub_chunk = overlap_part + sub_chunk

                if pos and sub_chunk.find(pos) < 0:
                    sub_chunk += pos

                cks.append(sub_chunk)
                tk_nums.append(sub_tnum)
            else:
                # 追加到当前chunk
                if pos and cks[-1].find(pos) < 0:
                    sub_chunk += pos
                cks[-1] += sub_chunk
                tk_nums[-1] += sub_tnum

    for sec, pos in sections:
        add_chunk("\n"+sec, pos)

    return cks


def split_by_delimiters(text, delimiters):
    """
    按分隔符切分文本，保持完整性

    优先级：
    1. 段落分隔符 (\n\n)
    2. 句子分隔符 (。\n, ！\n, ？\n)
    3. 列表分隔符 (\n1., \n-, \n*)
    """
    chunks = []
    current_chunk = ""

    for char in text:
        current_chunk += char

        # 检查是否到达分隔符
        if char in delimiters:
            # 检查后续字符（处理连续分隔符）
            if len(current_chunk.strip()) > 0:
                chunks.append(current_chunk)
                current_chunk = ""

    if current_chunk:
        chunks.append(current_chunk)

    return chunks
```

**优点**:
- ✅ 保持句子/段落完整性
- ✅ 利用现有 `delimiter` 参数
- ✅ 改动较小

**缺点**:
- ❌ 仍然基于token数量判断
- ❌ 无法识别复杂结构（列表层级）

---

### 5.3 改进方案2: 结构感知Chunk（推荐）

**原理**: 识别文档结构（标题、列表、表格），智能切分

**实现**:
```python
def structure_aware_merge(sections, chunk_token_num=128,
                          overlapped_percent=0):
    """
    结构感知的文本合并

    识别：
    1. 标题 (# ## ###)
    2. 列表项 (1. 2. 3. 或 - *)
    3. 代码块 (```)
    4. 表格 (<table>)
    """
    from deepdoc.parser.pdf_parser import RAGFlowPdfParser

    if not sections:
        return []
    if isinstance(sections, str):
        sections = [sections]
    if isinstance(sections[0], str):
        sections = [(s, "") for s in sections]

    cks = [""]
    tk_nums = [0]

    def add_chunk(t, pos, metadata=None):
        nonlocal cks, tk_nums

        tnum = num_tokens_from_string(t)

        if not pos:
            pos = ""
        if tnum < 8:
            pos = ""

        # 检查是否包含结构元素
        structure_info = detect_structure(t)

        if structure_info["type"] == "heading":
            # 标题：通常需要新chunk
            if cks[-1] and cks[-1] != "":
                cks.append(t + (pos if t.find(pos) < 0 else ""))
                tk_nums.append(tnum)
            else:
                cks[-1] += t + (pos if t.find(pos) < 0 else "")
                tk_nums[-1] = tnum

        elif structure_info["type"] == "list":
            # 列表：按列表项分组
            list_items = structure_info["items"]
            list_chunks = group_list_items(list_items, chunk_token_num)

            for i, list_chunk in enumerate(list_chunks):
                list_text = "\n".join(list_chunk)
                list_tnum = num_tokens_from_string(list_text)

                if i > 0:
                    # 添加重叠
                    overlapped = RAGFlowPdfParser.remove_tag(cks[-1])
                    overlap_part = overlapped[int(len(overlapped)*(100-overlapped_percent)/100.):]
                    list_text = overlap_part + "\n" + list_text

                cks.append(list_text)
                tk_nums.append(list_tnum)

        elif structure_info["type"] == "code_block":
            # 代码块：保持完整
            cks.append(t + (pos if t.find(pos) < 0 else ""))
            tk_nums.append(tnum)

        else:
            # 普通段落：基于token数量
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

    for sec, pos in sections:
        add_chunk("\n"+sec, pos)

    return cks


def detect_structure(text):
    """
    检测文本结构类型

    返回:
        {
            "type": "heading" | "list" | "code_block" | "paragraph",
            "level": int (for heading),
            "items": list (for list)
        }
    """
    text = text.strip()

    # 检测标题
    if re.match(r'^#{1,6}\s', text):
        level = len(re.match(r'^#+', text).group())
        return {"type": "heading", "level": level}

    # 检测代码块
    if re.match(r'^```', text):
        return {"type": "code_block"}

    # 检测列表
    lines = text.split('\n')
    if lines and re.match(r'^\s*[\d\-\*]+\.', lines[0]):
        items = []
        for line in lines:
            if re.match(r'^\s*[\d\-\*]+\.', line):
                items.append(line)
            elif line.strip():
                items[-1] += "\n" + line

        return {"type": "list", "items": items}

    # 普通段落
    return {"type": "paragraph"}


def group_list_items(items, chunk_token_num):
    """
    将列表项分组，确保不超限

    参数:
        items: 列表项列表
        chunk_token_num: token限制

    返回:
        分组后的列表（二维列表）
    """
    groups = []
    current_group = []
    current_tokens = 0

    for item in items:
        item_tokens = num_tokens_from_string(item)

        if current_tokens + item_tokens > chunk_token_num and current_group:
            groups.append(current_group)
            current_group = [item]
            current_tokens = item_tokens
        else:
            current_group.append(item)
            current_tokens += item_tokens

    if current_group:
        groups.append(current_group)

    return groups
```

**优点**:
- ✅ 完整保持列表、章节结构
- ✅ 智能识别不同类型的内容
- ✅ 更符合语义完整性

**缺点**:
- ❌ 实现复杂
- ❌ 依赖格式识别
- ❌ 可能产生不均匀的chunk大小

---

### 5.4 改进方案3: 混合策略（最佳实践）

**原理**: 结合多种策略，自适应选择

**实现**:
```python
def hybrid_merge(sections, chunk_token_num=128,
                 delimiter="\n!?。；！？", overlapped_percent=0):
    """
    混合策略：
    1. 优先使用结构感知切分
    2. 降级到delimiter切分
    3. 最后使用token切分
    """

    # 检测文档类型
    doc_type = detect_document_type(sections)

    if doc_type == "markdown":
        # 使用Markdown解析器
        return merge_markdown(sections, chunk_token_num, overlapped_percent)

    elif doc_type == "pdf_with_layout":
        # PDF已有版面分析结果
        return merge_by_layout(sections, chunk_token_num, overlapped_percent)

    else:
        # 降级到原始方法
        return naive_merge(sections, chunk_token_num, delimiter, overlapped_percent)


def detect_document_type(sections):
    """
    检测文档类型
    """
    text = "\n".join([s[0] for s in sections[:10]])  # 取前10个section

    if re.search(r'^#{1,6}\s', text, re.MULTILINE):
        return "markdown"

    if any("@@" in s[1] for s in sections if s[1]):
        return "pdf_with_layout"

    return "plain_text"


def merge_markdown(sections, chunk_token_num, overlapped_percent):
    """
    Markdown文档专用合并策略
    """
    import re
    from markdown import Markdown
    from bs4 import BeautifulSoup

    # 转换为HTML以便解析结构
    md_text = "\n".join([s[0] for s in sections])
    html = Markdown().convert(md_text)
    soup = BeautifulSoup(html, 'html.parser')

    chunks = []
    current_chunk = ""
    current_tokens = 0

    # 按标题层级切分
    for element in soup.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'li', 'pre']):
        text = element.get_text()
        tnum = num_tokens_from_string(text)

        # 标题：通常开始新chunk
        if element.name in ['h1', 'h2', 'h3']:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = text
            current_tokens = tnum

        # 列表项：尽量保持在一起
        elif element.name == 'li':
            if current_tokens + tnum > chunk_token_num and current_chunk:
                chunks.append(current_chunk)
                current_chunk = text
                current_tokens = tnum
            else:
                current_chunk += "\n" + text
                current_tokens += tnum

        # 代码块：保持完整
        elif element.name == 'pre':
            if current_chunk:
                chunks.append(current_chunk)
            chunks.append(text)
            current_chunk = ""
            current_tokens = 0

        # 普通段落
        elif element.name == 'p':
            if current_tokens + tnum > chunk_token_num and current_chunk:
                chunks.append(current_chunk)
                current_chunk = text
                current_tokens = tnum
            else:
                current_chunk += "\n" + text
                current_tokens += tnum

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def merge_by_layout(sections, chunk_token_num, overlapped_percent):
    """
    基于版面分析的合并策略（PDF专用）
    """
    # RAGFlow的PDF解析已经提供了layout信息
    # 可以利用这些信息进行智能切分

    cks = [""]
    tk_nums = [0]

    current_layout_type = None

    def add_chunk(t, pos):
        nonlocal cks, tk_nums, current_layout_type

        tnum = num_tokens_from_string(t)

        # 检测layout类型（从pos中提取）
        new_layout_type = extract_layout_from_pos(pos)

        # layout类型切换：创建新chunk
        if new_layout_type and new_layout_type != current_layout_type:
            if cks[-1]:
                cks.append(t + (pos if t.find(pos) < 0 else ""))
                tk_nums.append(tnum)
            else:
                cks[-1] += t + (pos if t.find(pos) < 0 else "")
                tk_nums[-1] = tnum
            current_layout_type = new_layout_type

        else:
            # 同一layout类型，基于token判断
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

    for sec, pos in sections:
        add_chunk("\n"+sec, pos)

    return cks


def extract_layout_from_pos(pos):
    """
    从位置标签中提取layout类型
    """
    # pos 格式: @@页码\tx0\tx1\ttop\tbottom##
    # 可能需要额外的layout信息

    # 这里假设pos包含layout类型
    # 实际实现需要根据RAGFlow的具体格式调整

    if not pos or "@@" not in pos:
        return None

    # 示例：假设layout信息编码在pos中
    # 实际需要查看RAGFlow的具体实现

    return "text"  # 默认返回文本类型
```

**优点**:
- ✅ 自适应选择最佳策略
- ✅ 兼顾语义完整性和chunk大小
- ✅ 可扩展到更多文档类型

**缺点**:
- ❌ 实现最复杂
- ❌ 需要测试多种场景

---

## 6. 实现方案与代码示例

### 6.1 完整实现：递归语义切分

```python
import re
from typing import List, Tuple, Optional
from dataclasses import dataclass

@dataclass
class ChunkMetadata:
    """Chunk元数据"""
    chunk_id: int
    content: str
    tokens: int
    type: str  # "heading", "paragraph", "list", "code_block"
    level: Optional[int] = None
    parent_id: Optional[int] = None


class SemanticChunker:
    """语义感知的文本切分器"""

    def __init__(
        self,
        chunk_token_num: int = 128,
        overlapped_percent: int = 10,
        delimiters: List[str] = None
    ):
        self.chunk_token_num = chunk_token_num
        self.overlapped_percent = overlapped_percent
        self.delimiters = delimiters or ["\n\n", "\n", "。", "！", "？", ".", "!", "?"]

        # 结构模式
        self.patterns = {
            "heading": re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE),
            "list_item": re.compile(r'^(\s*)([\d\-\*]+)\.\s+(.+)$', re.MULTILINE),
            "code_block": re.compile(r'^```(\w*)$', re.MULTILINE),
            "table": re.compile(r'^\|(.+)\|$', re.MULTILINE),
        }

    def chunk(self, sections: List[Tuple[str, str]]) -> List[ChunkMetadata]:
        """
        切分文本sections为chunks

        参数:
            sections: [(文本内容, 位置标签), ...]

        返回:
            [ChunkMetadata, ...]
        """
        # 1. 合并sections为完整文本（保留位置映射）
        full_text, pos_map = self._merge_sections(sections)

        # 2. 识别结构元素
        structure = self._parse_structure(full_text, pos_map)

        # 3. 按结构分组
        semantic_units = self._group_by_structure(structure)

        # 4. 切分为chunks
        chunks = self._create_chunks(semantic_units)

        return chunks

    def _merge_sections(
        self,
        sections: List[Tuple[str, str]]
    ) -> Tuple[str, dict]:
        """
        合并sections，建立位置映射
        """
        full_text = ""
        pos_map = {}  # {char_index: position_tag}

        current_idx = 0
        for sec_text, pos_tag in sections:
            start_idx = current_idx
            full_text += sec_text
            end_idx = current_idx + len(sec_text)

            # 记录每个字符的位置标签
            for idx in range(start_idx, end_idx):
                pos_map[idx] = pos_tag

            current_idx = end_idx

        return full_text, pos_map

    def _parse_structure(
        self,
        text: str,
        pos_map: dict
    ) -> List[dict]:
        """
        解析文本结构

        返回:
            [
                {
                    "type": "heading",
                    "level": 1,
                    "text": "...",
                    "start": 0,
                    "end": 20,
                    "pos": "@@1\t0\t100\t0\t50##"
                },
                ...
            ]
        """
        elements = []
        lines = text.split('\n')
        current_idx = 0

        in_code_block = False
        code_block_lang = None
        code_block_start = 0

        for line in lines:
            line_start = current_idx
            line_end = current_idx + len(line)

            # 检测代码块
            if self.patterns["code_block"].match(line):
                if not in_code_block:
                    # 代码块开始
                    in_code_block = True
                    code_block_lang = self.patterns["code_block"].match(line).group(1)
                    code_block_start = line_start
                else:
                    # 代码块结束
                    elements.append({
                        "type": "code_block",
                        "lang": code_block_lang,
                        "text": text[code_block_start:line_end],
                        "start": code_block_start,
                        "end": line_end,
                        "pos": pos_map.get(code_block_start, "")
                    })
                    in_code_block = False
                    code_block_lang = None

                current_idx = line_end + 1
                continue

            if in_code_block:
                current_idx = line_end + 1
                continue

            # 检测标题
            heading_match = self.patterns["heading"].match(line)
            if heading_match:
                level = len(heading_match.group(1))
                content = heading_match.group(2)
                elements.append({
                    "type": "heading",
                    "level": level,
                    "text": line,
                    "start": line_start,
                    "end": line_end,
                    "pos": pos_map.get(line_start, "")
                })
                current_idx = line_end + 1
                continue

            # 检测列表项
            list_match = self.patterns["list_item"].match(line)
            if list_match:
                elements.append({
                    "type": "list_item",
                    "indent": len(list_match.group(1)),
                    "marker": list_match.group(2),
                    "text": line,
                    "start": line_start,
                    "end": line_end,
                    "pos": pos_map.get(line_start, "")
                })
                current_idx = line_end + 1
                continue

            # 普通段落
            elements.append({
                "type": "paragraph",
                "text": line,
                "start": line_start,
                "end": line_end,
                "pos": pos_map.get(line_start, "")
            })

            current_idx = line_end + 1

        return elements

    def _group_by_structure(self, elements: List[dict]) -> List[dict]:
        """
        按结构分组为语义单元
        """
        units = []
        current_unit = {
            "type": None,
            "elements": [],
            "tokens": 0,
            "start": 0,
            "end": 0,
            "pos": ""
        }

        for element in elements:
            element_tokens = self._count_tokens(element["text"])

            # 标题：开始新单元
            if element["type"] == "heading":
                if current_unit["elements"]:
                    units.append(current_unit)

                current_unit = {
                    "type": "section",
                    "level": element["level"],
                    "elements": [element],
                    "tokens": element_tokens,
                    "start": element["start"],
                    "end": element["end"],
                    "pos": element["pos"]
                }

            # 列表项：尽量保持在一起
            elif element["type"] == "list_item":
                if current_unit["type"] != "list":
                    if current_unit["elements"]:
                        units.append(current_unit)

                    current_unit = {
                        "type": "list",
                        "elements": [element],
                        "tokens": element_tokens,
                        "start": element["start"],
                        "end": element["end"],
                        "pos": element["pos"]
                    }
                else:
                    # 同一列表，检查是否超限
                    if current_unit["tokens"] + element_tokens > self.chunk_token_num:
                        units.append(current_unit)
                        current_unit = {
                            "type": "list",
                            "elements": [element],
                            "tokens": element_tokens,
                            "start": element["start"],
                            "end": element["end"],
                            "pos": element["pos"]
                        }
                    else:
                        current_unit["elements"].append(element)
                        current_unit["tokens"] += element_tokens
                        current_unit["end"] = element["end"]

            # 代码块：独立单元
            elif element["type"] == "code_block":
                if current_unit["elements"]:
                    units.append(current_unit)

                units.append({
                    "type": "code",
                    "elements": [element],
                    "tokens": element_tokens,
                    "start": element["start"],
                    "end": element["end"],
                    "pos": element["pos"]
                })

                current_unit = {"type": None, "elements": [], "tokens": 0, "start": 0, "end": 0, "pos": ""}

            # 普通段落
            elif element["type"] == "paragraph":
                # 检查是否需要合并到当前单元
                if current_unit["type"] in ["section", "paragraph"]:
                    # 同一语义单元，检查是否超限
                    if current_unit["tokens"] + element_tokens > self.chunk_token_num * 0.8:
                        units.append(current_unit)
                        current_unit = {
                            "type": "paragraph",
                            "elements": [element],
                            "tokens": element_tokens,
                            "start": element["start"],
                            "end": element["end"],
                            "pos": element["pos"]
                        }
                    else:
                        current_unit["elements"].append(element)
                        current_unit["tokens"] += element_tokens
                        current_unit["end"] = element["end"]
                else:
                    if current_unit["elements"]:
                        units.append(current_unit)

                    current_unit = {
                        "type": "paragraph",
                        "elements": [element],
                        "tokens": element_tokens,
                        "start": element["start"],
                        "end": element["end"],
                        "pos": element["pos"]
                    }

        if current_unit["elements"]:
            units.append(current_unit)

        return units

    def _create_chunks(self, units: List[dict]) -> List[ChunkMetadata]:
        """
        创建最终chunks，添加重叠
        """
        chunks = []
        chunk_id = 0

        for i, unit in enumerate(units):
            # 提取文本
            text = "\n".join([el["text"] for el in unit["elements"]])

            # 添加重叠（除第一个外）
            if i > 0 and self.overlapped_percent > 0:
                overlap_size = int(len(chunks[-1].content) * self.overlapped_percent / 100)
                overlap_text = chunks[-1].content[-overlap_size:]
                text = overlap_text + "\n" + text

            # 检查是否超过限制
            if unit["tokens"] > self.chunk_token_num:
                # 递归切分
                sub_chunks = self._recursive_split(text, unit["type"])
                for sub_chunk in sub_chunks:
                    chunks.append(ChunkMetadata(
                        chunk_id=chunk_id,
                        content=sub_chunk,
                        tokens=self._count_tokens(sub_chunk),
                        type=unit["type"],
                        level=unit.get("level"),
                        parent_id=chunks[-1].chunk_id if chunks else None
                    ))
                    chunk_id += 1
            else:
                chunks.append(ChunkMetadata(
                    chunk_id=chunk_id,
                    content=text,
                    tokens=unit["tokens"],
                    type=unit["type"],
                    level=unit.get("level"),
                    parent_id=chunks[-1].chunk_id if chunks else None
                ))
                chunk_id += 1

        return chunks

    def _recursive_split(self, text: str, chunk_type: str) -> List[str]:
        """
        递归切分超长文本
        """
        chunks = []

        # 按分隔符优先级切分
        for delimiter in self.delimiters:
            if delimiter in text:
                parts = text.split(delimiter)

                # 检查每个部分的大小
                all_fit = all(
                    self._count_tokens(part) <= self.chunk_token_num
                    for part in parts
                )

                if all_fit:
                    # 所有部分都符合大小
                    return parts

                # 部分超限，递归切分
                result = []
                for part in parts:
                    if self._count_tokens(part) > self.chunk_token_num:
                        result.extend(self._recursive_split(part, chunk_type))
                    else:
                        result.append(part)

                return result

        # 没有合适的分隔符，强制切分
        return self._force_split(text)

    def _force_split(self, text: str) -> List[str]:
        """
        强制按token切分
        """
        tokens = self._tokenize(text)
        chunks = []

        current_chunk = ""
        current_tokens = 0

        for token in tokens:
            token_chars = len(token)

            if current_tokens + token_chars > self.chunk_token_num:
                chunks.append(current_chunk)
                current_chunk = token
                current_tokens = token_chars
            else:
                current_chunk += token
                current_tokens += token_chars

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _count_tokens(self, text: str) -> int:
        """计算文本的token数量"""
        from common.token_utils import num_tokens_from_string
        return num_tokens_from_string(text)

    def _tokenize(self, text: str) -> List[str]:
        """简单的tokenization（按空格分割）"""
        return text.split()
```

### 6.2 使用示例

```python
from rag.nlp import naive_merge
from semantic_chunker import SemanticChunker

# 原始sections（来自PDF解析）
sections = [
    ("## 3.1 神经网络原理", "@@1\t0\t100\t0\t50##"),
    ("神经网络是受生物大脑启发而来的计算模型。", "@@1\t0\t100\t50\t100##"),
    ("## 3.2 前向传播算法", "@@1\t0\t100\t100\t150##"),
    ("前向传播是指数据从输入层流向输出层的过程。", "@@1\t0\t100\t150\t200##"),
]

# 方法1：原始naive_merge（基于token）
chunks_token = naive_merge(sections, chunk_token_num=128, delimiter="\n")
# 可能破坏标题和内容的关联

# 方法2：语义感知切分
chunker = SemanticChunker(chunk_token_num=128, overlapped_percent=10)
chunks_semantic = chunker.chunk(sections)
# 保持章节结构的完整性

# 对比
print("Token-based chunks:")
for i, chunk in enumerate(chunks_token):
    print(f"Chunk {i+1}: {chunk[:50]}...")

print("\nSemantic chunks:")
for chunk_meta in chunks_semantic:
    print(f"Chunk {chunk_meta.chunk_id} ({chunk_meta.type}):")
    print(f"  {chunk_meta.content[:50]}...")
```

---

## 7. 评估与对比

### 7.1 评估指标

| 指标 | 说明 | 重要性 |
|------|------|--------|
| **语义完整性** | Chunk是否保持完整的语义单元 | ⭐⭐⭐⭐⭐ |
| **检索召回率** | 查询是否能找到相关chunk | ⭐⭐⭐⭐⭐ |
| **检索精确率** | 返回的chunk是否准确相关 | ⭐⭐⭐⭐ |
| **Chunk大小均匀性** | Chunk大小是否相对均匀 | ⭐⭐⭐ |
| **计算效率** | Chunk处理的性能 | ⭐⭐⭐ |
| **实现复杂度** | 代码的复杂程度 | ⭐⭐ |

### 7.2 方案对比

| 方案 | 语义完整性 | 召回率 | 精确率 | 大小均匀性 | 效率 | 复杂度 | 综合评分 |
|------|-----------|--------|--------|-----------|------|--------|---------|
| **Fixed-size (RAGFlow当前)** | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐ | 13/35 |
| **Semantic** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐⭐ | 21/35 |
| **Structure-aware** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 28/35 |
| **Recursive** | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | 23/35 |
| **Hybrid** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | 30/35 |

### 7.3 推荐方案

#### 对于RAGFlow

**短期改进**（立即可用）:
1. ✅ 增强delimiter感知（利用现有参数）
2. ✅ 添加列表项检测（简单正则）
3. ✅ 优化重叠策略（针对列表、表格）

**中期改进**（需要开发）:
1. ✅ 实现递归切分（参考LangChain）
2. ✅ 添加结构检测（标题、列表、代码块）
3. ✅ 提供配置选项（让用户选择chunk策略）

**长期改进**（需要重构）:
1. ✅ 完全结构感知切分
2. ✅ 多模态支持（图像、表格、图表）
3. ✅ 自适应chunk策略

---

## 8. 社区推荐总结

### 8.1 LangChain推荐

**RecursiveCharacterTextSplitter**:
```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=128,
    chunk_overlap=12,
    separators=["\n\n", "\n", "。", "！", "？", "", ""]
)

chunks = splitter.split_text(text)
```

**优点**: 递归使用不同分隔符，优先保持高层级结构

---

### 8.2 LlamaIndex推荐

**SemanticSplitter**:
```python
from llama_index.core.node_parser import SemanticSplitter

splitter = SemanticSplitter(
    buffer_size=1,
    breakpoint_percentile_threshold=95,
)

nodes = splitter.get_nodes_from_documents(documents)
```

**优点**: 基于句子相似度切分，保持主题一致性

---

### 8.3 Unstructured推荐

**结构感知切分**:
```python
from unstructured.partition import partition_pdf

elements = partition_pdf("example.pdf")

# 按元素类型分组
for element in elements:
    if element.category == "Title":
        # 处理标题
    elif element.category == "NarrativeText":
        # 处理正文
    elif element.category == "ListItem":
        # 处理列表项
```

**优点**: 完全理解文档结构，保持语义完整性

---

### 8.4 最佳实践建议

1. **不要一刀切**: 不同文档类型使用不同策略
2. **结构优先**: 优先利用文档结构信息
3. **重叠很重要**: 特别是对于列表、表格
4. **测试验证**: 在实际数据上评估检索效果
5. **用户配置**: 提供选项让用户根据场景选择

---

## 9. 总结

### 9.1 核心问题

RAGFlow当前的token-based chunk策略存在语义完整性问题：
- ❌ 列表项可能被切断
- ❌ 章节结构可能被破坏
- ❌ 上下文信息可能丢失

### 9.2 解决方案

| 问题 | 解决方案 | 优先级 |
|------|----------|--------|
| 列表被切断 | 检测列表结构，按列表项分组 | P0 |
| 章节被破坏 | 检测标题层级，按章节分组 | P0 |
| 上下文丢失 | 优化重叠策略，针对不同内容类型 | P1 |
| 超长文本块 | 预处理sections，避免超限 | P1 |

### 9.3 实施建议

**阶段1**: 快速改进（1-2周）
- 添加列表检测和保持逻辑
- 增强delimiter感知
- 优化重叠策略

**阶段2**: 结构增强（1-2个月）
- 实现递归切分
- 添加标题层级识别
- 提供chunk策略配置选项

**阶段3**: 全面重构（3-6个月）
- 完全结构感知切分
- 多模态支持
- 自适应策略选择

### 9.4 最终建议

对于RAGFlow这样的生产级RAG系统，建议：
1. **短期**: 在现有基础上增强，添加列表和章节检测
2. **中期**: 实现结构感知的chunk策略
3. **长期**: 提供多种chunk策略，让用户根据场景选择

**关键**: 没有万能的chunk策略，最好的策略取决于具体的应用场景和数据特点！

---

## 相关文档

- [406-文本合并与切块流程.md](406-文本合并与切块流程.md) - 原始合并机制
- [412-naive_merge的add_chunk方法详解.md](412-naive_merge的add_chunk方法详解.md) - add_chunk详解
- [413-naive_merge超长文本块处理分析.md](413-naive_merge超长文本块处理分析.md) - 超长文本处理
