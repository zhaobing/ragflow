# kb_prompt() 知识组装流程业务逻辑详解

> **文件位置**: [rag/prompts/generator.py:111-149](../../../../rag/prompts/generator.py#L111-L149)
> **分析日期**: 2026-02-10
> **功能类型**: 知识组装与提示词构建

---

## 📋 概述

`kb_prompt()` 是 RAGFlow 系统中的**知识组装核心函数**，负责将检索到的知识块（chunks）转换为适合大语言模型（LLM）理解的格式化文本。该函数在 RAG 流程中处于**检索阶段与生成阶段的桥梁位置**，将原始检索结果转化为高质量的上下文信息。

### 在 RAG 流程中的位置

```
完整的 RAG 流程：

┌─────────────────────────────────────────────────────────┐
│ 1. 检索阶段 (Retrieval)                                  │
│    - 用户查询 → Elasticsearch/Infinity                  │
│    - 返回相关的知识块 (chunks)                           │
│    - 包含：content, doc_id, similarity等字段            │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ 2. 知识组装阶段 (Knowledge Assembly) 【本文档重点】     │
│    - kb_prompt() 函数                                   │
│    - Token计数与截断控制                                 │
│    - 文档元数据提取                                      │
│    - 树状结构格式化                                      │
│    - 返回格式化的知识列表                                │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ 3. 提示词构建阶段 (Prompt Construction)                 │
│    - 系统提示词 + 知识内容                               │
│    - 用户问题                                           │
│    - 组装完整的 LLM 输入                                 │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ 4. 生成阶段 (Generation)                                │
│    - LLM 处理并生成回答                                  │
│    - 基于提供的知识内容                                  │
└─────────────────────────────────────────────────────────┘
```

---

## 🎯 核心业务价值

### 为什么需要知识组装？

1. **原始检索结果的局限性**
   - 检索返回的 chunks 是结构化数据（字典格式）
   - 缺少人类可读的结构化表示
   - Token 数量可能超过 LLM 的上下文限制
   - 缺少文档级别的元数据信息

2. **LLM 的理解需求**
   - 需要清晰、结构化的文本格式
   - 需要了解知识的来源和上下文
   - 需要控制输入长度以避免超出限制
   - 需要一致的数据格式以提升理解准确性

3. **用户体验优化**
   - 提供知识来源的可追溯性
   - 支持引用和验证
   - 便于调试和问题定位
   - 提升答案的可信度

### 树状结构设计的优势

```
传统平铺格式：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Chunk 1: 深度学习是机器学习的分支...
Chunk 2: 神经网络由多个层组成...
Chunk 3: 反向传播用于训练神经网络...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

树状结构格式（kb_prompt 输出）：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ID: 0
├── Title: 深度学习入门指南.pdf
├── URL: https://example.com/doc1
├── Author: 张三
├── Publish Date: 2024-01-15
└── Content:
   深度学习是机器学习的分支...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ID: 1
├── Title: 神经网络架构详解.pdf
├── URL: https://example.com/doc2
├── Author: 李四
└── Content:
   神经网络由多个层组成...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**优势对比**：

| 特性 | 平铺格式 | 树状结构 |
|------|---------|---------|
| **可读性** | 低 | 高 |
| **信息层级** | 不清晰 | 清晰 |
| **元数据展示** | 困难 | 自然 |
| **LLM理解** | 困难 | 容易 |
| **调试友好** | 否 | 是 |

---

## 🔧 详细业务流程

### 流程图

```
输入：kbinfos = {"chunks": [chunk1, chunk2, ...]}
        max_tokens = 4000
        hash_id = False
        ↓
┌─────────────────────────────────────────┐
│ 步骤1: 提取知识块内容                    │
│   - 从 chunks 中提取 content 字段       │
│   - 支持 content 和 content_with_weight │
└─────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────┐
│ 步骤2: Token计数与截断控制               │
│   - 累加每个chunk的token数              │
│   - 当超过 max_tokens * 0.97 时停止     │
│   - 记录实际包含的chunk数量              │
└─────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────┐
│ 步骤3: 获取文档元数据                    │
│   - 根据 doc_id 批量查询文档            │
│   - 提取 meta_fields 字段               │
│   - 构建 doc_id → meta_fields 的映射    │
└─────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────┐
│ 步骤4: 定义树状节点渲染函数              │
│   - draw_node()                         │
│   - 格式化键值对为树状分支               │
│   - 处理换行和空值                       │
└─────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────┐
│ 步骤5: 格式化知识条目                    │
│   - 为每个chunk生成树状结构             │
│   - 添加 ID、Title、URL等节点           │
│   - 添加文档元数据节点                   │
│   - 添加 Content 根节点                  │
└─────────────────────────────────────────┘
        ↓
输出：knowledges = ["ID: 0\n├── Title: ...\n...", ...]
```

---

## 📝 逐行代码详解

### 步骤1: 提取知识块内容 (114行)

```python
knowledges = [get_value(ck, "content", "content_with_weight") for ck in kbinfos["chunks"]]
```

**功能说明**：
- 从 `kbinfos["chunks"]` 中提取每个 chunk 的内容字段
- 优先使用 `content` 字段，如果不存在则使用 `content_with_weight`
- `get_value()` 函数处理字段名的兼容性（详见第36-37行）

**get_value() 函数实现**：
```python
def get_value(d, k1, k2):
    return d.get(k1, d.get(k2))
```

**详细示例**：
```python
# 输入：kbinfos
kbinfos = {
    "chunks": [
        {
            "content": "深度学习是机器学习的分支",
            "content_with_weight": "深度学习是机器学习的分支",
            "doc_id": "doc_001",
            "docnm_kwd": "深度学习入门.pdf"
        },
        {
            # 没有 content 字段，使用 content_with_weight
            "content_with_weight": "神经网络由多层组成",
            "doc_id": "doc_002",
            "docnm_kwd": "神经网络详解.pdf"
        }
    ]
}

# 提取后：knowledges
knowledges = [
    "深度学习是机器学习的分支",  # 使用 content
    "神经网络由多层组成"          # 使用 content_with_weight
]
```

**字段命名规则**：

| 字段名 | 含义 | 优先级 |
|--------|------|--------|
| `content` | chunk的纯文本内容 | 1（优先） |
| `content_with_weight` | 带权重的内容（用于展示） | 2（备选） |

---

### 步骤2: Token计数与截断控制 (116-126行)

这是**核心的流量控制机制**，确保最终的知识内容不会超过 LLM 的 token 限制。

#### 2.1 初始化计数器 (116-117行)

```python
kwlg_len = len(knowledges)
used_token_count = 0
chunks_num = 0
```

**变量说明**：

| 变量 | 类型 | 说明 | 示例值 |
|------|------|------|--------|
| `kwlg_len` | int | 原始知识块总数 | 10 |
| `used_token_count` | int | 已使用的token数 | 0 → 1500 → 3500 |
| `chunks_num` | int | 实际包含的chunk数 | 0 → 3 → 5 |

#### 2.2 遍历并累加Token (118-122行)

```python
for i, c in enumerate(knowledges):
    if not c:
        continue
    used_token_count += num_tokens_from_string(c)
    chunks_num += 1
```

**功能说明**：
- 遍历所有知识块
- 跳过空内容（`if not c: continue`）
- 使用 `num_tokens_from_string()` 计算每个chunk的token数
- 累加到 `used_token_count`
- 计数 `chunks_num`

**token计算原理**：

```python
# num_tokens_from_string() 使用 tiktoken 或类似库
# 原理：将文本转换为 token IDs，然后计数

def num_tokens_from_string(text):
    tokens = encoder.encode(text)  # 编码为 token IDs
    return len(tokens)              # 返回 token 数量

# 示例
text = "深度学习是机器学习的分支"
tokens = encoder.encode(text)
# tokens 可能是: [38571, 235, 4526, 312, 5234, 311, 9285]
# token 数: 7
```

**详细示例**：
```python
# 假设
knowledges = [
    "深度学习是机器学习的分支",      # 7 tokens
    "神经网络由多个层组成",          # 8 tokens
    "反向传播用于训练神经网络",      # 9 tokens
    "卷积神经网络用于图像处理",      # 10 tokens
    "循环神经网络用于序列数据"       # 9 tokens
]
max_tokens = 30

# 处理过程
i=0: c="深度学习是机器学习的分支"
     used_token_count = 0 + 7 = 7
     chunks_num = 1

i=1: c="神经网络由多个层组成"
     used_token_count = 7 + 8 = 15
     chunks_num = 2

i=2: c="反向传播用于训练神经网络"
     used_token_count = 15 + 9 = 24
     chunks_num = 3

i=3: c="卷积神经网络用于图像处理"
     used_token_count = 24 + 10 = 34
     # 34 > 30 * 0.97 = 29.1，触发截断！
```

#### 2.3 截断控制 (123-126行)

```python
if max_tokens * 0.97 < used_token_count:
    knowledges = knowledges[:i]
    logging.warning(f"Not all the retrieval into prompt: {len(knowledges)}/{kwlg_len}")
    break
```

**关键设计**：为什么是 `0.97` 而不是 `1.0`？

1. **预留buffer空间**
   - 为后续的格式化字符串（ID、Title等）预留空间
   - 避免因为格式化导致超出限制
   - 约3%的安全边距

2. **数值示例**：
```python
max_tokens = 4000
threshold = 4000 * 0.97 = 3880

# 场景1: 不使用0.97（危险）
# 累加内容: 3990 tokens
# 格式化后: 3990 + 200 (ID、Title等) = 4190 tokens
# 结果: 超出限制！

# 场景2: 使用0.97（安全）
# 累加内容: 3880 tokens（触发截断）
# 格式化后: 3880 + 150 = 4030 tokens
# 结果: 仍然可能超出，但风险更低
```

**截断逻辑流程图**：

```
输入: max_tokens=4000, knowledges=[c1, c2, c3, c4, c5]
                    ↓
        ┌───────────────────────┐
        │ 遍历 knowledges        │
        └───────────────────────┘
                    ↓
    ┌───────────────────────────────────┐
    │ c1: 500 tokens                   │
    │ used_token_count = 500            │
    │ 500 < 3880 ✓ 继续                │
    └───────────────────────────────────┘
                    ↓
    ┌───────────────────────────────────┐
    │ c2: 800 tokens                   │
    │ used_token_count = 1300           │
    │ 1300 < 3880 ✓ 继续               │
    └───────────────────────────────────┘
                    ↓
    ┌───────────────────────────────────┐
    │ c3: 1500 tokens                  │
    │ used_token_count = 2800           │
    │ 2800 < 3880 ✓ 继续               │
    └───────────────────────────────────┘
                    ↓
    ┌───────────────────────────────────┐
    │ c4: 1200 tokens                  │
    │ used_token_count = 4000           │
    │ 4000 >= 3880 ✗ 触发截断          │
    │ knowledges = [c1, c2, c3]         │
    │ 记录日志: "3/5"                  │
    │ break                            │
    └───────────────────────────────────┘
                    ↓
输出: knowledges = [c1, c2, c3]
```

**日志输出示例**：
```python
# 原始有10个chunk，但因为token限制只能包含7个
logging.warning(f"Not all the retrieval into prompt: {len(knowledges)}/{kwlg_len}")
# 输出: WARNING - Not all the retrieval into prompt: 7/10
```

---

### 步骤3: 获取文档元数据 (128-129行)

```python
docs = DocumentService.get_by_ids([get_value(ck, "doc_id", "document_id") for ck in kbinfos["chunks"][:chunks_num]])
docs = {d.id: d.meta_fields for d in docs}
```

**功能说明**：
- 根据 `doc_id` 批量查询文档信息
- 只查询截断后的chunk数量（`chunks_num`）
- 提取每个文档的 `meta_fields` 字段
- 构建 `doc_id → meta_fields` 的映射字典

**为什么要获取文档元数据？**

1. **补充上下文信息**
   - 作者、发布日期、来源等
   - 帮助LLM理解知识的背景

2. **提供引用信息**
   - 支持答案中的引用
   - 提升可信度

3. **支持筛选和过滤**
   - 基于元数据的条件过滤
   - 提升检索精度

**详细示例**：
```python
# 假设 chunks_num = 3
# kbinfos["chunks"][:3] 包含3个chunk

# 提取 doc_id 列表
doc_ids = [
    get_value(kbinfos["chunks"][0], "doc_id", "document_id"),  # "doc_001"
    get_value(kbinfos["chunks"][1], "doc_id", "document_id"),  # "doc_002"
    get_value(kbinfos["chunks"][2], "doc_id", "document_id")   # "doc_001" (重复)
]
# 结果: ["doc_001", "doc_002", "doc_001"]

# 批量查询（去重）
docs = DocumentService.get_by_ids(["doc_001", "doc_002", "doc_001"])
# 返回文档对象列表

# 构建映射
docs = {
    "doc_001": {
        "author": "张三",
        "publish_date": "2024-01-15",
        "source": "学术期刊",
        "category": "人工智能"
    },
    "doc_002": {
        "author": "李四",
        "publish_date": "2024-02-20",
        "source": "技术博客",
        "category": "深度学习"
    }
}
```

**DocumentService.get_by_ids() 方法**：

```python
# 位于: api/db/services/document_service.py
class DocumentService:
    @staticmethod
    def get_by_ids(ids):
        # 批量查询文档
        # 参数: ids - 文档ID列表（可能重复）
        # 返回: 文档对象列表
        return db.session.query(Document).filter(Document.id.in_(set(ids))).all()
```

**性能优化**：
- 使用批量查询而非单个查询
- 数据库层面的 `IN` 查询
- 减少数据库往返次数

```python
# 低效方式（N+1查询）
for chunk in chunks:
    doc = DocumentService.get_by_id(chunk["doc_id"])  # N次查询

# 高效方式（批量查询）
doc_ids = [chunk["doc_id"] for chunk in chunks]
docs = DocumentService.get_by_ids(doc_ids)  # 1次查询
```

---

### 步骤4: 定义树状节点渲染函数 (131-136行)

```python
def draw_node(k, line):
    if line is not None and not isinstance(line, str):
        line = str(line)
    if not line:
        return ""
    return f"\n├── {k}: " + re.sub(r"\n+", " ", line, flags=re.DOTALL)
```

**功能说明**：
- 将键值对格式化为树状结构的分支
- 处理非字符串类型（转换为字符串）
- 处理空值（返回空字符串）
- 处理多行文本（压缩为单行）

**函数名称解析**：
- `draw_node`: 绘制节点，树状结构的可视化术语

**参数说明**：

| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `k` | str | 节点的键（字段名） | "Title", "Author" |
| `line` | any | 节点的值（字段值） | "深度学习.pdf", "张三" |

**返回值**：
- 成功: `"\n├── {k}: {line}"`
- 失败（空值）: `""`

**详细示例**：

```python
# 示例1: 基本用法
draw_node("Title", "深度学习入门.pdf")
# 返回: "\n├── Title: 深度学习入门.pdf"

# 示例2: 处理非字符串类型
draw_node("Publish Date", datetime.date(2024, 1, 15))
# line 转换为字符串: "2024-01-15"
# 返回: "\n├── Publish Date: 2024-01-15"

# 示例3: 处理空值
draw_node("URL", "")
# 返回: ""

# 示例4: 处理多行文本
draw_node("Content", "第一行\n\n第二行\n第三行")
# re.sub(r"\n+", " ", line) 压缩换行符
# 返回: "\n├── Content: 第一行 第二行 第三行"
```

**正则表达式解析**：

```python
re.sub(r"\n+", " ", line, flags=re.DOTALL)
```

| 组成部分 | 说明 |
|---------|------|
| `\n+` | 匹配一个或多个连续的换行符 |
| ` ` | 替换为单个空格 |
| `flags=re.DOTALL` | `.` 匹配包括换行符在内的所有字符 |

**为什么压缩换行符？**

1. **保持树状结构的整洁**
   - 多行文本会破坏树状结构
   - 导致视觉混乱

2. **LLM理解优化**
   - 单行文本更易于解析
   - 减少token浪费

**可视化示例**：

```python
# 不压缩换行符（混乱）
ID: 0
├── Title: 深度学习入门
├── Content: 深度学习是
机器学习的分支。
它基于神经网络。
                    ↑
              破坏了树状结构

# 压缩换行符（整洁）
ID: 0
├── Title: 深度学习入门
├── Content: 深度学习是 机器学习的分支。 它基于神经网络。
              ↑
        保持树状结构
```

---

### 步骤5: 格式化知识条目 (138-148行)

这是**核心的格式化逻辑**，将原始chunk数据转换为树状结构的文本。

#### 5.1 重新初始化 knowledges (138行)

```python
knowledges = []
```

**为什么重新初始化？**

```python
# 之前的 knowledges 是纯文本列表
knowledges = ["深度学习是机器学习的分支", "神经网络由多层组成"]

# 现在需要的是格式化后的字符串列表
knowledges = [
    "ID: 0\n├── Title: 深度学习入门.pdf\n├── Content:\n深度学习是机器学习的分支",
    "ID: 1\n├── Title: 神经网络详解.pdf\n├── Content:\n神经网络由多层组成"
]
```

#### 5.2 遍历chunks并格式化 (139-148行)

```python
for i, ck in enumerate(kbinfos["chunks"][:chunks_num]):
    cnt = "\nID: {}".format(i if not hash_id else hash_str2int(get_value(ck, "id", "chunk_id"), 500))
    cnt += draw_node("Title", get_value(ck, "docnm_kwd", "document_name"))
    cnt += draw_node("URL", ck['url'])  if "url" in ck else ""
    for k, v in docs.get(get_value(ck, "doc_id", "document_id"), {}).items():
        cnt += draw_node(k, v)
    cnt += "\n└── Content:\n"
    cnt += get_value(ck, "content", "content_with_weight")
    knowledges.append(cnt)
```

**逐行解析**：

**第140行: 添加ID节点**
```python
cnt = "\nID: {}".format(i if not hash_id else hash_str2int(get_value(ck, "id", "chunk_id"), 500))
```

**功能说明**：
- 生成chunk的唯一标识符
- 支持两种模式：
  - `hash_id=False`: 使用序号（0, 1, 2, ...）
  - `hash_id=True`: 使用哈希值（避免暴露真实ID）

**详细示例**：
```python
# 模式1: hash_id=False（默认）
i = 0
cnt = "\nID: {}".format(0)
# 结果: "\nID: 0"

i = 1
cnt = "\nID: {}".format(1)
# 结果: "\nID: 1"

# 模式2: hash_id=True
chunk_id = "chunk_abc123xyz"
hash_id = hash_str2int("chunk_abc123xyz", 500)
# 结果: 12345 (假设哈希值为12345)
cnt = "\nID: {}".format(12345)
# 结果: "\nID: 12345"
```

**为什么要哈希？**

1. **隐私保护**
   - 不暴露内部chunk ID
   - 避免用户推断系统结构

2. **ID简化**
   - 将长ID转换为短数字
   - 便于引用和展示

**hash_str2int() 函数**：
```python
# 位于: common/misc_utils.py
def hash_str2int(s, modulo):
    # 将字符串哈希为整数
    # 参数: s - 输入字符串, modulo - 模数
    # 返回: 0 到 modulo-1 之间的整数
    return hash(s) % modulo
```

**第141行: 添加Title节点**
```python
cnt += draw_node("Title", get_value(ck, "docnm_kwd", "document_name"))
```

**示例**：
```python
# 输入
docnm_kwd = "深度学习入门指南.pdf"

# 处理
cnt += draw_node("Title", "深度学习入门指南.pdf")
# cnt += "\n├── Title: 深度学习入门指南.pdf"
```

**第142行: 添加URL节点（可选）**
```python
cnt += draw_node("URL", ck['url'])  if "url" in ck else ""
```

**功能说明**：
- 只在chunk包含 `url` 字段时添加
- 用于在线文档或网页chunk

**示例**：
```python
# 场景1: 有URL
ck = {"url": "https://example.com/doc1"}
cnt += draw_node("URL", "https://example.com/doc1")
# cnt += "\n├── URL: https://example.com/doc1"

# 场景2: 没有URL
ck = {}
# cnt 不变
```

**第143-144行: 添加文档元数据节点**
```python
for k, v in docs.get(get_value(ck, "doc_id", "document_id"), {}).items():
    cnt += draw_node(k, v)
```

**功能说明**：
- 遍历文档的所有元数据字段
- 动态添加为树状节点
- 支持任意自定义字段

**详细示例**：
```python
# 假设 docs 映射为
docs = {
    "doc_001": {
        "author": "张三",
        "publish_date": "2024-01-15",
        "source": "学术期刊",
        "category": "人工智能"
    }
}

# chunk的doc_id
doc_id = "doc_001"

# 处理
meta_fields = docs.get("doc_001", {})
# meta_fields = {"author": "张三", "publish_date": "2024-01-15", ...}

for k, v in meta_fields.items():
    cnt += draw_node(k, v)

# 第1次循环: k="author", v="张三"
# cnt += "\n├── author: 张三"

# 第2次循环: k="publish_date", v="2024-01-15"
# cnt += "\n├── publish_date: 2024-01-15"

# 第3次循环: k="source", v="学术期刊"
# cnt += "\n├── source: 学术期刊"

# 第4次循环: k="category", v="人工智能"
# cnt += "\n├── category: 人工智能"
```

**第145行: 添加Content根节点**
```python
cnt += "\n└── Content:\n"
```

**功能说明**：
- 使用 `└──` 表示最后一个子节点
- 后面跟换行符，content内容另起一行
- 标志着元数据结束，正文开始

**第146行: 添加content内容**
```python
cnt += get_value(ck, "content", "content_with_weight")
```

**第147行: 添加到knowledges列表**
```python
knowledges.append(cnt)
```

---

### 完整示例演示

#### 输入数据

```python
kbinfos = {
    "chunks": [
        {
            "id": "chunk_001",
            "doc_id": "doc_001",
            "docnm_kwd": "深度学习入门指南.pdf",
            "url": "https://example.com/deep-learning",
            "content": "深度学习是机器学习的一个子领域，它基于人工神经网络。深度学习的核心是多层神经网络，能够学习数据的层次表示。",
            "content_with_weight": "深度学习是机器学习的一个子领域，它基于人工神经网络。"
        },
        {
            "id": "chunk_002",
            "doc_id": "doc_002",
            "docnm_kwd": "神经网络架构详解.pdf",
            "content": "神经网络由输入层、隐藏层和输出层组成。每一层包含多个神经元，神经元之间通过权重连接。",
            "content_with_weight": "神经网络由输入层、隐藏层和输出层组成。"
        },
        {
            "id": "chunk_003",
            "doc_id": "doc_001",
            "docnm_kwd": "深度学习入门指南.pdf",
            "content": "反向传播算法是训练神经网络的核心方法。它通过计算损失函数的梯度，调整网络参数以最小化损失。",
            "content_with_weight": "反向传播算法是训练神经网络的核心方法。"
        }
    ]
}

max_tokens = 200
hash_id = False

# 假设查询到的文档元数据
# docs = {
#     "doc_001": {"author": "张三", "publish_date": "2024-01-15"},
#     "doc_002": {"author": "李四", "publish_date": "2024-02-20"}
# }
```

#### 执行流程

**步骤1: 提取知识块内容**
```python
knowledges = [
    "深度学习是机器学习的一个子领域，它基于人工神经网络。深度学习的核心是多层神经网络，能够学习数据的层次表示。",  # 假设50 tokens
    "神经网络由输入层、隐藏层和输出层组成。每一层包含多个神经元，神经元之间通过权重连接。",  # 假设40 tokens
    "反向传播算法是训练神经网络的核心方法。它通过计算损失函数的梯度，调整网络参数以最小化损失。"   # 假设45 tokens
]
```

**步骤2: Token计数与截断**
```python
max_tokens = 200
threshold = 200 * 0.97 = 194

i=0: used_token_count = 50 < 194 ✓
i=1: used_token_count = 50 + 40 = 90 < 194 ✓
i=2: used_token_count = 90 + 45 = 135 < 194 ✓

# 所有chunks都在限制内，无需截断
chunks_num = 3
```

**步骤3: 获取文档元数据**
```python
docs = {
    "doc_001": {"author": "张三", "publish_date": "2024-01-15"},
    "doc_002": {"author": "李四", "publish_date": "2024-02-20"}
}
```

**步骤5: 格式化知识条目**

**Chunk 0**:
```python
i = 0
ck = kbinfos["chunks"][0]

# ID
cnt = "\nID: 0"

# Title
cnt += "\n├── Title: 深度学习入门指南.pdf"

# URL
cnt += "\n├── URL: https://example.com/deep-learning"

# 元数据
doc_id = "doc_001"
meta = {"author": "张三", "publish_date": "2024-01-15"}
cnt += "\n├── author: 张三"
cnt += "\n├── publish_date: 2024-01-15"

# Content
cnt += "\n└── Content:\n"
cnt += "深度学习是机器学习的一个子领域，它基于人工神经网络。深度学习的核心是多层神经网络，能够学习数据的层次表示。"

# 最终结果
cnt = """
ID: 0
├── Title: 深度学习入门指南.pdf
├── URL: https://example.com/deep-learning
├── author: 张三
├── publish_date: 2024-01-15
└── Content:
深度学习是机器学习的一个子领域，它基于人工神经网络。深度学习的核心是多层神经网络，能够学习数据的层次表示。
"""
```

**Chunk 1**:
```python
i = 1
ck = kbinfos["chunks"][1]

cnt = """
ID: 1
├── Title: 神经网络架构详解.pdf
├── author: 李四
├── publish_date: 2024-02-20
└── Content:
神经网络由输入层、隐藏层和输出层组成。每一层包含多个神经元，神经元之间通过权重连接。
"""
```

**Chunk 2**:
```python
i = 2
ck = kbinfos["chunks"][2]

cnt = """
ID: 2
├── Title: 深度学习入门指南.pdf
├── author: 张三
├── publish_date: 2024-01-15
└── Content:
反向传播算法是训练神经网络的核心方法。它通过计算损失函数的梯度，调整网络参数以最小化损失。
"""
```

#### 最终输出

```python
knowledges = [
    """
ID: 0
├── Title: 深度学习入门指南.pdf
├── URL: https://example.com/deep-learning
├── author: 张三
├── publish_date: 2024-01-15
└── Content:
深度学习是机器学习的一个子领域，它基于人工神经网络。深度学习的核心是多层神经网络，能够学习数据的层次表示。
""",

    """
ID: 1
├── Title: 神经网络架构详解.pdf
├── author: 李四
├── publish_date: 2024-02-20
└── Content:
神经网络由输入层、隐藏层和输出层组成。每一层包含多个神经元，神经元之间通过权重连接。
""",

    """
ID: 2
├── Title: 深度学习入门指南.pdf
├── author: 张三
├── publish_date: 2024-01-15
└── Content:
反向传播算法是训练神经网络的核心方法。它通过计算损失函数的梯度，调整网络参数以最小化损失。
"""
]
```

---

## 📊 输出格式在LLM提示词中的应用

### 如何使用 kb_prompt 的输出

`kb_prompt()` 的输出通常被组装到 LLM 的系统提示词或用户提示词中。

**示例提示词模板**：

```python
# 假设在其他地方使用 kb_prompt()
from rag.prompts.generator import kb_prompt

# 获取检索结果
kbinfos = retrieval_result  # 从检索系统获取

# 组装知识
formatted_knowledges = kb_prompt(kbinfos, max_tokens=4000, hash_id=False)

# 构建完整的LLM提示词
system_prompt = """你是一个专业的问答助手。请基于以下知识内容回答用户的问题。

知识内容：
{}

请根据上述知识内容，准确、全面地回答用户问题。如果知识内容不足以回答问题，请明确说明。
""".format("\n".join(formatted_knowledges))

user_prompt = "什么是深度学习？"

# 调用LLM
response = llm.chat(system_prompt, user_prompt)
```

**完整的提示词示例**：

```
你是一个专业的问答助手。请基于以下知识内容回答用户的问题。

知识内容：

ID: 0
├── Title: 深度学习入门指南.pdf
├── URL: https://example.com/deep-learning
├── author: 张三
├── publish_date: 2024-01-15
└── Content:
深度学习是机器学习的一个子领域，它基于人工神经网络。深度学习的核心是多层神经网络，能够学习数据的层次表示。

ID: 1
├── Title: 神经网络架构详解.pdf
├── author: 李四
├── publish_date: 2024-02-20
└── Content:
神经网络由输入层、隐藏层和输出层组成。每一层包含多个神经元，神经元之间通过权重连接。

请根据上述知识内容，准确、全面地回答用户问题。如果知识内容不足以回答问题，请明确说明。
```

**LLM的回答示例**：

```
根据提供的知识内容，我来回答您的问题：

深度学习是机器学习的一个子领域，它基于人工神经网络（来源：深度学习入门指南.pdf）。

深度学习的核心特点是：
1. 使用多层神经网络架构
2. 能够学习数据的层次表示

神经网络的基本组成包括：
- 输入层：接收原始数据
- 隐藏层：进行特征提取和转换
- 输出层：产生最终结果
- 每层包含多个神经元，神经元之间通过权重连接（来源：神经网络架构详解.pdf）

参考文献：
- 深度学习入门指南.pdf（张三，2024-01-15）
- 神经网络架构详解.pdf（李四，2024-02-20）
```

---

## 🎯 关键设计决策

### 1. 为什么使用树状结构而不是JSON？

| 特性 | 树状结构（当前） | JSON格式 | 平铺文本 |
|------|----------------|---------|---------|
| **LLM理解** | 优秀 | 中等 | 差 |
| **可读性** | 高 | 中等 | 中等 |
| **Token效率** | 中等 | 低 | 高 |
| **扩展性** | 好 | 好 | 差 |
| **调试友好** | 是 | 否 | 否 |

**选择树状结构的原因**：
1. LLM对树状结构的理解能力强
2. 人类可读，便于调试
3. 支持任意元数据字段
4. 提供清晰的层级关系

### 2. 为什么token阈值是0.97而不是1.0？

**原因分析**：

```python
# 格式化开销估算
# 假设原始内容: 1000 tokens

# 格式化后的开销（每个chunk）
ID: 0\n                      # ~3 tokens
├── Title: 深度学习入门.pdf\n # ~10 tokens
├── author: 张三\n            # ~5 tokens
├── publish_date: 2024-01-15\n # ~8 tokens
└── Content:\n               # ~3 tokens

# 总开销: ~30 tokens/chunk
# 对于10个chunks: ~300 tokens

# 如果使用1.0阈值
max_tokens = 4000
content_tokens = 4000  # 全部用于内容
formatting_tokens = 300
total = 4300  # 超出限制！

# 如果使用0.97阈值
max_tokens = 4000
threshold = 4000 * 0.97 = 3880
content_tokens = 3880
formatting_tokens = 300
total = 4180  # 仍然可能超出，但更接近

# 更安全的方案
threshold = 0.95  # 或更低
content_tokens = 4000 * 0.95 = 3800
formatting_tokens = 300
total = 4100  # 更安全
```

**建议**：
- 当前使用 `0.97` 是一个经验值
- 可以根据实际格式化开销调整
- 建议设置为 `0.90-0.95` 以确保安全

### 3. 为什么最后重新初始化knowledges？

```python
# 步骤1: 提取纯文本（用于token计数）
knowledges = ["content1", "content2", "content3"]

# 步骤2: token计数和截断
# knowledges = knowledges[:2]  # 截断到前2个

# 步骤5: 重新初始化（为什么？）
knowledges = []  # 清空
for ck in chunks:
    cnt = format_chunk(ck)  # 格式化
    knowledges.append(cnt)  # 添加格式化后的内容
```

**为什么不直接修改原列表？**

```python
# 方案1: 修改原列表（不推荐）
knowledges = ["content1", "content2"]
for i, ck in enumerate(chunks):
    knowledges[i] = format_chunk(ck)  # 替换
# 问题:
# 1. 需要跟踪索引
# 2. 可能的索引错误
# 3. 代码不清晰

# 方案2: 重新初始化（当前实现）
knowledges = []
for ck in chunks:
    cnt = format_chunk(ck)
    knowledges.append(cnt)
# 优点:
# 1. 代码清晰
# 2. 避免索引错误
# 3. 逻辑分离
```

### 4. hash_id参数的使用场景

| 场景 | hash_id设置 | 原因 |
|------|-----------|------|
| **内部测试** | `False` | 使用序号，便于调试 |
| **生产环境** | `True` | 隐藏内部ID，提升安全性 |
| **公开API** | `True` | 避免暴露系统结构 |
| **数据分析** | `False` | 保持ID一致性，便于追踪 |

---

## 🚨 注意事项与最佳实践

### 1. Token限制配置

```python
# 场景1: 小模型（4K上下文）
max_tokens = 4000
kb_prompt(kbinfos, max_tokens, hash_id=True)

# 场景2: 中等模型（8K上下文）
max_tokens = 8000
kb_prompt(kbinfos, max_tokens, hash_id=True)

# 场景3: 大模型（32K上下文）
max_tokens = 32000
kb_prompt(kbinfos, max_tokens, hash_id=True)
```

**建议**：
- 为系统提示词和用户问题预留空间
- 一般 `max_tokens = 模型上下文长度 - 1000`
- 保留buffer以应对格式化开销

### 2. 元数据字段配置

```python
# 在文档入库时配置元数据
doc.meta_fields = {
    "author": "张三",
    "publish_date": "2024-01-15",
    "source": "学术期刊",
    "category": "人工智能",
    "tags": ["深度学习", "神经网络"],
    "language": "zh",
    "page_range": "10-15"
}

# 这些字段会自动出现在kb_prompt的输出中
```

**最佳实践**：
- 只包含有价值的元数据
- 避免过多的元数据字段（token浪费）
- 使用清晰的字段名

### 3. URL字段的使用

```python
# 场景1: 在线文档（有URL）
chunk = {
    "url": "https://example.com/doc1",
    "content": "..."
}
# 输出会包含:
# ├── URL: https://example.com/doc1

# 场景2: 本地文档（无URL）
chunk = {
    "content": "..."
}
# 输出不包含URL节点
```

### 4. 错误处理

```python
# 空内容处理
if not c:
    continue  # 跳过空chunk

# 缺失字段处理
get_value(ck, "doc_id", "document_id")  # 使用备选字段名

# 元数据缺失处理
docs.get(doc_id, {})  # 返回空字典，避免KeyError
```

---

## 🔗 相关文档

### 相关函数

- [get_value()](../../../../rag/prompts/generator.py#L36-L37): 字段值提取
- [chunks_format()](../../../../rag/prompts/generator.py#L40-L58): Chunk格式化（用于API响应）
- [num_tokens_from_string()](../../../../common/token_utils.py): Token计数
- [DocumentService.get_by_ids()](../../../../api/db/services/document_service.py): 批量查询文档

### 相关分析

- [718-rerank_by_model方法业务逻辑详解](./718-rerank_by_model方法业务逻辑详解.md): 检索重排序
- [719-retrieval方法结果后处理逻辑详解](./719-retrieval方法结果后处理逻辑详解.md): 检索结果处理
- [714-全文检索与向量检索的协同机制详解](./714-全文检索与向量检索的协同机制详解.md): 检索机制

---

## 📈 总结

`kb_prompt()` 函数是 RAGFlow 系统中**知识组装的核心组件**，负责将检索到的知识块转换为适合 LLM 理解的格式化文本。

### 核心功能

1. **智能截断**: 基于token计数，确保不超出模型限制
2. **结构化表示**: 树状格式，提升LLM理解能力
3. **元数据集成**: 动态包含文档元数据，提供上下文
4. **批量查询**: 优化数据库查询性能

### 关键设计

- **0.97阈值**: 为格式化开销预留buffer
- **树状结构**: 平衡可读性和LLM理解
- **hash_id**: 支持隐私保护
- **动态元数据**: 灵活支持各种字段

### 业务价值

- **提升答案质量**: 结构化知识帮助LLM更好理解
- **增强可追溯性**: 元数据支持引用和验证
- **优化性能**: 智能截断避免资源浪费
- **便于调试**: 清晰的格式便于问题定位

---

**分析完成** ✅
