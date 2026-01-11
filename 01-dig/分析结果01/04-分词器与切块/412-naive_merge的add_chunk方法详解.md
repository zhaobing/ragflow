# naive_merge 的 add_chunk 方法详解

> 文件位置: [rag/nlp/__init__.py:881-903](../../../rag/nlp/__init__.py#L881-L903)
> 相关方法: `naive_merge()` (line 846-930), `naive_merge_with_images()` (line 933-980)

---

## 目录

1. [方法概述](#1-方法概述)
2. [核心参数与变量](#2-核心参数与变量)
3. [代码逻辑详解](#3-代码逻辑详解)
4. [重叠机制深度解析](#4-重叠机制深度解析)
5. [执行流程示例](#5-执行流程示例)
6. [边界情况处理](#6-边界情况处理)
7. [与 naive_merge_with_images 的对比](#7-与-naive_merge_with_images-的对比)

---

## 1. 方法概述

### 1.1 方法签名与位置

**位置**: [rag/nlp/__init__.py:881-903](../../../rag/nlp/__init__.py#L881-L903)

```python
def add_chunk(t, pos):
    """
    将文本段落添加到chunk列表中，自动处理token限制和重叠

    参数:
        t: 待添加的文本内容
        pos: 位置标签（格式: @@页码\tx0\tx1\ttop\tbottom##）
    """
    nonlocal cks, tk_nums, delimiter
    # 获取当前文本的token数量（使用tiktoken编码器）
    tnum = num_tokens_from_string(t)

    if not pos:
        pos = ""
    if tnum < 8:
        pos = ""

    # 核心逻辑：判断是否需要新建chunk
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

### 1.2 核心功能

1. **智能分块**: 根据token限制自动将文本分割为多个chunk
2. **重叠处理**: 在相邻chunk之间添加重叠内容，保持上下文连贯性
3. **位置标签管理**: 自动附加和去重位置标签
4. **token计数**: 实时跟踪每个chunk的token数量

---

## 2. 核心参数与变量

### 2.1 外部变量 (nonlocal)

```python
cks       # list[str]: 已生成的chunk列表
tk_nums   # list[int]: 每个chunk的token数量
delimiter # str: 分隔符（虽声明但未在本函数中使用）
```

**初始化**（在 `naive_merge` 中）:
```python
cks = [""]      # 初始为空字符串
tk_nums = [0]   # 初始token数为0
```

### 2.2 输入参数

| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `t` | str | 待添加的文本内容 | `"这是第一段文本"` |
| `pos` | str | 位置标签 | `"@@1\t100\t500\t200\t300##"` |

### 2.3 外部配置参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `chunk_token_num` | int | 128 | 单个chunk的最大token数 |
| `overlapped_percent` | int | 0 | 重叠百分比（0-90） |

---

## 3. 代码逻辑详解

### 3.1 第一部分：初始化与验证

```python
# 获取当前文本的token数量（使用tiktoken编码器）
tnum = num_tokens_from_string(t)

if not pos:
    pos = ""
if tnum < 8:
    pos = ""
```

**逻辑说明**:

1. **token计数**: 使用 tiktoken 编码器计算文本的token数量
2. **空标签处理**: 如果 `pos` 为空，设为空字符串
3. **短文本过滤**: 如果token数 < 8，丢弃位置标签
   - **原因**: 短文本通常是标题、页码等，不需要位置信息

**示例**:
```python
t = "机器学习是人工智能的一个分支"
pos = "@@1\t100\t500\t200\t300##"

tnum = num_tokens_from_string(t)
# tnum = 15 (假设)

# tnum >= 8，保留 pos
```

---

### 3.2 第二部分：核心判断逻辑

```python
if cks[-1] == "" or tk_nums[-1] > chunk_token_num * (100 - overlapped_percent)/100.:
    # 分支A：创建新chunk
    ...
else:
    # 分支B：追加到当前chunk
    ...
```

#### 判断条件解析

**条件1**: `cks[-1] == ""`
- **含义**: 当前chunk列表为空（只有初始空字符串）
- **目的**: 第一次添加文本时，创建第一个chunk

**条件2**: `tk_nums[-1] > chunk_token_num * (100 - overlapped_percent)/100.`
- **含义**: 当前chunk的token数超过阈值
- **阈值公式**: `chunk_token_num * (100 - overlapped_percent) / 100`

**阈值计算示例**:

| `chunk_token_num` | `overlapped_percent` | 阈值计算 | 阈值 |
|-------------------|---------------------|----------|------|
| 128 | 0 | `128 * 100 / 100` | 128 |
| 128 | 10 | `128 * 90 / 100` | 115.2 |
| 128 | 20 | `128 * 80 / 100` | 102.4 |
| 512 | 15 | `512 * 85 / 100` | 435.2 |

**为什么减去重叠百分比？**

```
假设 chunk_token_num = 128, overlapped_percent = 10

如果不减:
  - chunk1 可达 128 tokens
  - 添加 10% 重叠 (12.8 tokens)
  - chunk1 总共 140.8 tokens > 128 ✗ 超限！

如果减去:
  - chunk1 只能到 115.2 tokens
  - 添加 10% 重叠 (11.52 tokens)
  - chunk1 总共 126.72 tokens ≈ 128 ✓ 符合限制
```

---

### 3.3 分支A：创建新chunk

```python
if cks:
    overlapped = RAGFlowPdfParser.remove_tag(cks[-1])
    t = overlapped[int(len(overlapped)*(100-overlapped_percent)/100.):] + t
if t.find(pos) < 0:
    t += pos
cks.append(t)
tk_nums.append(tnum)
```

#### 步骤详解

**步骤1**: 提取上一个chunk的内容
```python
if cks:
    overlapped = RAGFlowPdfParser.remove_tag(cks[-1])
```
- **条件**: `cks` 非空（不是第一次添加）
- **作用**: 移除位置标签，获取纯文本
- **示例**:
  ```python
  cks[-1] = "这是第一段文本@@1\t100\t500\t200\t300##"
  overlapped = "这是第一段文本"
  ```

**步骤2**: 计算重叠部分
```python
t = overlapped[int(len(overlapped)*(100-overlapped_percent)/100.):] + t
```
- **逻辑**: 从上一个chunk的末尾提取指定百分比的内容
- **计算**:
  - 起始位置: `len(overlapped) * (100 - overlapped_percent) / 100`
  - 示例: `len=100, percent=10` → 起始位置 = `100 * 90 / 100` = `90`
  - 提取: `overlapped[90:]` → 最后10个字符

**示例**:
```python
overlapped = "这是一段很长的文本内容，包含了多个句子和段落"
len(overlapped) = 30
overlapped_percent = 20

start = 30 * (100 - 20) / 100 = 24
overlapped_part = overlapped[24:]  # "句子和段落"
t = overlapped_part + " " + t
```

**步骤3**: 添加位置标签
```python
if t.find(pos) < 0:
    t += pos
```
- **条件**: 当前文本中不包含 `pos`
- **作用**: 避免重复添加位置标签

**步骤4**: 创建新chunk
```python
cks.append(t)
tk_nums.append(tnum)
```
- 将新文本添加到chunk列表
- 记录token数量

---

### 3.4 分支B：追加到当前chunk

```python
else:
    if cks[-1].find(pos) < 0:
        t += pos
    cks[-1] += t
    tk_nums[-1] += tnum
```

#### 步骤详解

**步骤1**: 添加位置标签
```python
if cks[-1].find(pos) < 0:
    t += pos
```
- **条件**: 当前chunk中不包含 `pos`
- **作用**: 确保位置标签被添加

**步骤2**: 追加文本
```python
cks[-1] += t
tk_nums[-1] += tnum
```
- 将新文本追加到当前chunk末尾
- 累加token数量

---

## 4. 重叠机制深度解析

### 4.1 为什么需要重叠？

**场景**: 文本被分割为多个chunk

```
Chunk 1: "机器学习是人工智能的一个分支，它使计算机能够从数据中学习。"
Chunk 2: "深度学习是机器学习的一个子领域，它使用神经网络进行学习。"
```

**问题**:
- "它" 指代不明
- Chunk 2 的上下文不完整

**解决方案**: 添加重叠

```
Chunk 1: "机器学习是人工智能的一个分支，它使计算机能够从数据中学习。"
Chunk 2: "数据中学习。深度学习是机器学习的一个子领域，它使用神经网络进行学习。"
          ^^^^^^^^^^^^^^
          重叠部分 (来自 Chunk 1)
```

**效果**:
- Chunk 2 现在有完整的上下文
- "它" 的指代清晰

---

### 4.2 重叠计算公式

```python
overlapped = RAGFlowPdfParser.remove_tag(cks[-1])
t = overlapped[int(len(overlapped)*(100-overlapped_percent)/100.):] + t
```

**公式拆解**:

```
起始位置 = len(overlapped) * (100 - overlapped_percent) / 100
重叠内容 = overlapped[起始位置:]
新chunk = 重叠内容 + 新文本
```

**参数关系**:

| `overlapped_percent` | 重叠内容占比 | 起始位置 |
|---------------------|-------------|----------|
| 0% | 0% | `100%` |
| 10% | 10% | `90%` |
| 20% | 20% | `80%` |
| 50% | 50% | `50%` |

---

### 4.3 重叠示例

#### 示例1: overlapped_percent = 20

**上一个chunk**:
```python
cks[-1] = "机器学习是人工智能的一个分支，它使计算机能够从数据中学习。@@1\t100\t500\t200\t300##"
```

**提取重叠**:
```python
# 1. 移除标签
overlapped = "机器学习是人工智能的一个分支，它使计算机能够从数据中学习。"
len(overlapped) = 34

# 2. 计算起始位置
start = 34 * (100 - 20) / 100 = 34 * 0.8 = 27.2 ≈ 27

# 3. 提取重叠部分
overlap_part = overlapped[27:]  # "从数据中学习。"

# 4. 添加新文本
new_text = "深度学习是机器学习的子领域。"
t = overlap_part + new_text
# t = "从数据中学习。深度学习是机器学习的子领域。"
```

**最终chunk**:
```python
cks.append("从数据中学习。深度学习是机器学习的子领域。")
```

---

#### 示例2: overlapped_percent = 0

```python
cks[-1] = "第一段内容。"
overlapped = "第一段内容。"
len(overlapped) = 6

start = 6 * (100 - 0) / 100 = 6
overlap_part = overlapped[6:]  # "" (空字符串)

# 无重叠
t = "" + "第二段内容。"
```

---

## 5. 执行流程示例

### 5.1 完整示例

**输入**:
```python
sections = [
    ("这是第一段文本，包含了一些基本概念。", "@@1\t0\t100\t0\t50##"),
    ("这是第二段文本，介绍了更深入的内容。", "@@1\t0\t100\t50\t100##"),
    ("这是第三段文本，总结了前面的要点。", "@@1\t0\t100\t100\t150##"),
]

chunk_token_num = 50
overlapped_percent = 20
```

**执行流程**:

#### 初始化
```python
cks = [""]
tk_nums = [0]
```

#### 处理第一段
```python
add_chunk("\n这是第一段文本，包含了一些基本概念。", "@@1\t0\t100\t0\t50##")

tnum = num_tokens_from_string(t)  # 假设 = 20

# 判断: cks[-1] == "" → True
# → 进入分支A (创建新chunk)

if cks:  # cks = [""]，条件为True（列表非空，但第一个元素为空）
    # 但 cks[0] == ""，所以实际上不会提取重叠
    # overlapped = ""

t = "\n这是第一段文本，包含了一些基本概念。"
t += "@@1\t0\t100\t0\t50##"

cks = ["", "\n这是第一段文本，包含了一些基本概念。@@1\t0\t100\t0\t50##"]
tk_nums = [0, 20]
```

**注意**: 第一次添加时，`cks` 非空（有初始空字符串），但 `cks[0] == ""`，所以不会提取重叠。

---

#### 处理第二段
```python
add_chunk("\n这是第二段文本，介绍了更深入的内容。", "@@1\t0\t100\t50\t100##")

tnum = 20

# 判断: tk_nums[-1] > 50 * 80 / 100
#        20 > 40 → False

# → 进入分支B (追加到当前chunk)

cks[-1] += "\n这是第二段文本，介绍了更深入的内容。"
tk_nums[-1] += 20

cks = ["", "\n这是第一段文本...@@1\t0\t100\t0\t50##\n这是第二段文本...@@1\t0\t100\t50\t100##"]
tk_nums = [0, 40]
```

---

#### 处理第三段（假设第二段后token数超限）

```python
# 假设处理后第二段token数 = 45

add_chunk("\n这是第三段文本，总结了前面的要点。", "@@1\t0\t100\t100\t150##")

tnum = 20

# 判断: tk_nums[-1] > 50 * 80 / 100
#        45 > 40 → True

# → 进入分支A (创建新chunk)

if cks:
    # 提取重叠
    overlapped = RAGFlowPdfParser.remove_tag(cks[-1])
    # overlapped = "这是第一段文本...这是第二段文本..." (无标签)

    # 计算重叠部分
    start = len(overlapped) * 80 / 100  # 假设 len = 100, start = 80
    overlap_part = overlapped[80:]  # 最后20%的内容

    t = overlap_part + "\n这是第三段文本，总结了前面的要点。"

cks.append(t)
tk_nums.append(20)
```

---

### 5.2 状态变化表

| 步骤 | 当前chunk | tk_nums[-1] | 判断结果 | 操作 |
|------|-----------|-------------|----------|------|
| 初始 | `""` | 0 | - | - |
| 添加第1段 | `""` | 0 | `cks[-1]==""` → True | 创建chunk1 |
| 添加第2段 | `"第一段..."` | 20 | `20 > 40` → False | 追加到chunk1 |
| 添加第3段 | `"第一段...第二段..."` | 45 | `45 > 40` → True | 创建chunk2 (带重叠) |
| 添加第4段 | `"第三段...（重叠）"` | 25 | `25 > 40` → False | 追加到chunk2 |

---

## 6. 边界情况处理

### 6.1 短文本处理

```python
if tnum < 8:
    pos = ""
```

**原因**:
- 短文本（token < 8）通常是页码、标题等
- 不需要位置标签
- 避免干扰检索

**示例**:
```python
t = "第1页"
pos = "@@1\t0\t100\t0\t10##"

tnum = 3  # 假设
# tnum < 8 → pos = ""
```

---

### 6.2 空chunk列表

```python
if cks:
    overlapped = RAGFlowPdfParser.remove_tag(cks[-1])
    t = overlapped[int(len(overlapped)*(100-overlapped_percent)/100.):] + t
```

**第一次添加时**:
```python
cks = [""]  # 初始状态
if cks:  # True (列表非空)
    # 但 cks[0] == ""
    # overlapped = ""
    # 重叠部分为空字符串
```

---

### 6.3 位置标签重复

```python
if t.find(pos) < 0:
    t += pos
```

**场景**:
```python
# 如果文本中已经包含位置标签
t = "内容@@1\t0\t100\t0\t50##"
pos = "@@1\t0\t100\t0\t50##"

t.find(pos)  # 返回位置索引，不是 -1
# 不会重复添加
```

---

### 6.4 overlapped_percent = 0

```python
overlapped_percent = 0

start = len(overlapped) * (100 - 0) / 100 = len(overlapped)
overlap_part = overlapped[len(overlapped):]  # "" (空)
```

**结果**: 无重叠

---

### 6.5 overlapped_percent = 100

```python
overlapped_percent = 100

start = len(overlapped) * (100 - 100) / 100 = 0
overlap_part = overlapped[0:]  # 整个上一个chunk
```

**结果**: 完全重复（实际中不推荐）

---

## 7. 与 naive_merge_with_images 的对比

### 7.1 代码对比

#### naive_merge (纯文本)

```python
def add_chunk(t, pos):
    nonlocal cks, tk_nums, delimiter
    tnum = num_tokens_from_string(t)

    if not pos:
        pos = ""
    if tnum < 8:
        pos = ""

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

#### naive_merge_with_images (带图像)

```python
def add_chunk(t, image, pos=""):
    nonlocal cks, result_images, tk_nums, delimiter

    tnum = num_tokens_from_string(t)
    if not pos:
        pos = ""
    if tnum < 8:
        pos = ""

    if cks[-1] == "" or tk_nums[-1] > chunk_token_num * (100 - overlapped_percent)/100.:
        if cks:
            overlapped = RAGFlowPdfParser.remove_tag(cks[-1])
            t = overlapped[int(len(overlapped)*(100-overlapped_percent)/100.):] + t
        if t.find(pos) < 0:
            t += pos
        cks.append(t)
        result_images.append(image)
        tk_nums.append(tnum)
    else:
        if cks[-1].find(pos) < 0:
            t += pos
        cks[-1] += t
        result_images[-1] = concat_img(result_images[-1], image) if result_images[-1] else image
        tk_nums[-1] += tnum
```

### 7.2 关键差异

| 特性 | naive_merge | naive_merge_with_images |
|------|-------------|-------------------------|
| **输入** | `(t, pos)` | `(t, image, pos)` |
| **图像处理** | 无 | `concat_img()` 合并图像 |
| **图像列表** | 无 | `result_images` 与 `cks` 同步 |
| **追加逻辑** | `cks[-1] += t` | `cks[-1] += t` + 图像合并 |

---

## 8. 总结

### 8.1 核心功能

1. **智能分块**: 根据token限制自动分割
2. **重叠机制**: 保持上下文连贯性
3. **位置管理**: 自动附加和去重标签
4. **token跟踪**: 实时监控chunk大小

### 8.2 关键公式

```
阈值 = chunk_token_num * (100 - overlapped_percent) / 100

判断: tk_nums[-1] > 阈值
  - True → 创建新chunk
  - False → 追加到当前chunk

重叠 = overlapped[len * (100 - percent) / 100:]
```

### 8.3 设计亮点

1. **动态调整**: 根据重叠百分比动态调整阈值
2. **避免超限**: 减去重叠百分比，确保最终chunk不超限
3. **位置去重**: 检查并避免重复添加位置标签
4. **短文本优化**: 过滤短文本的位置标签

### 8.4 应用场景

- ✅ PDF文档分块
- ✅ 长文本切分
- ✅ 保持上下文的检索
- ✅ 图文混合文档处理

---

## 相关文档

- [406-文本合并与切块流程.md](406-文本合并与切块流程.md) - 完整的合并流程
- [407-切块向量化流程.md](407-切块向量化流程.md) - 切块后的处理
- [412-naive_merge_with_images详解](412-naive_merge_with_images详解.md) - 带图像的版本
