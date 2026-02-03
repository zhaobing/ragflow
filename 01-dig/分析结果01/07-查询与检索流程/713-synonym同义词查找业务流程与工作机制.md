# synonym.py 同义词查找业务流程与工作机制

## 文件位置

[rag/nlp/synonym.py](../../rag/nlp/synonym.py)

---

## 概述

`synonym.py` 实现了一个双层同义词查找系统，用于查询扩展（Query Expansion），提升检索系统的召回率。系统结合了**自定义领域词典**和**WordNet 通用词库**，支持动态更新和多实例同步。

---

## 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                    同义词查找系统架构                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────┐  │
│  │ 本地词典     │───→│ Redis 缓存   │───→│ 动态更新     │  │
│  │ synonym.json│    │ kevin_synonyms│    │ (可选)      │  │
│  └─────────────┘    └──────────────┘    └─────────────┘  │
│         ↓                                                │
│  ┌─────────────┐                                          │
│  │ WordNet     │                                          │
│  │ (英文回退)   │                                          │
│  └─────────────┘                                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 类结构与初始化

### Dealer 类 (synonym.py:26-47)

```python
class Dealer:
    def __init__(self, redis=None):
        # 计数器：用于触发 Redis 重新加载
        self.lookup_num = 100000000

        # 时间戳：上次从 Redis 加载的时间
        self.load_tm = time.time() - 1000000

        # 词典数据结构: {词: [同义词列表]} 或 {词: 同义词}
        self.dictionary = None

        # Redis 连接（可选）
        self.redis = redis
```

### 初始化流程

```python
# 步骤 1: 加载本地词典 (32-38行)
path = os.path.join(get_project_base_directory(), "rag/res", "synonym.json")
self.dictionary = json.load(open(path, 'r'))

# 步骤 2: 统一转换为小写 (35行)
self.dictionary = {
    (k.lower() if isinstance(k, str) else k): v
    for k, v in self.dictionary.items()
}

# 步骤 3: 初始加载 Redis (47行)
self.load()
```

**词典格式示例**:
```json
{
  "ai": ["人工智能", "artificial intelligence", "机器智能"],
  "ml": "machine learning",  // 支持字符串
  "nlp": ["natural language processing", "自然语言处理"],
  "llm": ["large language model", "大语言模型"]
}
```

---

## 核心方法详解

### 1. load() - 动态加载方法 (synonym.py:49-68)

#### 工作机制

```
┌──────────────────────────────────────────────┐
│  load() 调用时机判断                         │
├──────────────────────────────────────────────┤
│  1. Redis 连接存在？                         │
│     NO → 跳过                                │
│     YES → 继续                               │
│                                              │
│  2. 查询次数 >= 100？                        │
│     NO → 跳过（避免频繁更新）                 │
│     YES → 继续                               │
│                                              │
│  3. 距上次更新 >= 1小时？                    │
│     NO → 跳过                                │
│     YES → 继续                               │
│                                              │
│  4. 从 Redis 加载                            │
│     - 获取 "kevin_synonyms" 键                │
│     - 解析 JSON                              │
│     - 更新 self.dictionary                   │
└──────────────────────────────────────────────┘
```

#### 代码实现

```python
def load(self):
    # 条件 1: 必须有 Redis 连接
    if not self.redis:
        return

    # 条件 2: 累积查询次数 >= 100
    if self.lookup_num < 100:
        return

    # 条件 3: 距上次更新 >= 3600秒 (1小时)
    tm = time.time()
    if tm - self.load_tm < 3600:
        return

    # 执行加载
    self.load_tm = time.time()
    self.lookup_num = 0
    d = self.redis.get("kevin_synonyms")
    if not d:
        return

    try:
        d = json.loads(d)
        self.dictionary = d  # 更新词典
    except Exception as e:
        logging.error("Fail to load synonym!" + str(e))
```

#### 设计优势

| 特性 | 说明 |
|-----|------|
| **热更新** | 无需重启服务即可更新词典 |
| **限流保护** | 100次查询或1小时内最多更新一次 |
| **多实例同步** | 多个服务实例从同一 Redis 读取，保持一致 |
| **容错机制** | Redis 失败时降级到本地词典 |

---

### 2. lookup() - 同义词查找方法 (synonym.py:71-96)

#### 三层查找策略

```
输入: "ai"
    ↓
┌─────────────────────────────────────────────┐
│  第1层: 自定义词典查找                       │
│  dictionary.get("ai")                       │
│  → ["人工智能", "artificial intelligence"]   │
└─────────────────────────────────────────────┘
    ↓ 未找到
┌─────────────────────────────────────────────┐
│  第2层: WordNet 通用同义词库 (仅英文)        │
│  wordnet.synsets("ai")                      │
│  → ["artificial intelligence", ...]         │
└─────────────────────────────────────────────┘
    ↓ 仍未找到
┌─────────────────────────────────────────────┐
│  第3层: 返回空列表                           │
│  → []                                       │
└─────────────────────────────────────────────┘
```

#### 代码实现

```python
def lookup(self, tk, topn=8):
    # === 步骤 0: 输入验证 ===
    if not tk or not isinstance(tk, str):
        return []

    # === 步骤 1: 自定义词典查找 ===
    self.lookup_num += 1  # 计数，触发 Redis 更新
    self.load()           # 检查是否需要从 Redis 加载

    # 规范化输入：清理空白符
    key = re.sub(r"[ \t]+", " ", tk.strip())

    # 查询词典
    res = self.dictionary.get(key, [])

    # 兼容字符串和列表格式
    if isinstance(res, str):
        res = [res]

    # 找到则直接返回
    if res:
        return res[:topn]

    # === 步骤 2: WordNet 回退 (仅纯英文) ===
    if re.fullmatch(r"[a-z]+", tk):
        # 获取所有同义词集
        wn_set = {
            re.sub("_", " ", syn.name().split(".")[0])
            for syn in wordnet.synsets(tk)
        }

        # 排除原词本身
        wn_set.discard(tk)

        # 过滤空字符串
        wn_res = [t for t in wn_set if t]

        return wn_res[:topn]

    # === 步骤 3: 未找到 ===
    return []
```

---

## WordNet 处理详解

### WordNet 数据结构

```python
wordnet.synsets("ai")
# 返回:
# [
#   Synset('artificial_intelligence.n.01'),
#   Synset('ai.n.02'),
#   ...
# ]

# 处理流程:
syn.name() = "artificial_intelligence.n.01"
    ↓
split(".")[0] = "artificial_intelligence"
    ↓
sub("_", " ") = "artificial intelligence"
```

### 为什么只处理纯英文？

```python
if re.fullmatch(r"[a-z]+", tk):
    # 只对纯英文单词查询 WordNet
```

**原因**:
| 因素 | 说明 |
|-----|------|
| **WordNet 特性** | 主要针对英语设计 |
| **中文处理** | 中文同义词依赖自定义词典 |
| **性能优化** | 避免对中文词进行无效查询 |
| **混合词** | "ai模型" 这类混合词会跳过 WordNet |

---

## 业务应用场景

### 1. 查询扩展 (query.py:173-174)

```python
twts = self.tw.weights([tt])
syns = self.syn.lookup(tt)  # ← 调用 lookup
if syns and len(keywords) < 32:
    keywords.extend(syns)   # 扩展查询词
```

**示例**:
```
用户查询: "RAGFlow 支持 LLM 吗？"

原始分词: ["ragflow", "支持", "llm", "吗"]

同义词扩展:
  "llm" → ["large language model", "大语言模型"]

扩展查询:
  ["ragflow", "支持", "llm", "large language model", "大语言模型"]

→ 召回更多相关文档，提升检索效果
```

---

### 2. 多语言支持

```python
# 场景：中英文混合检索
"ai" (英文)  → ["人工智能", "artificial intelligence"]
"人工智能" (中文) → [] (依赖自定义词典配置)
```

---

## 数据流转图

```
┌──────────────┐
│ 用户查询词    │
│ "llm"        │
└──────┬───────┘
       ↓
┌──────────────────────────────────────┐
│ lookup("llm")                       │
├──────────────────────────────────────┤
│ 1. lookup_num += 1                   │
│ 2. 调用 load() 检查更新条件          │
│ 3. 规范化输入 → "llm"                │
└──────┬───────────────────────────────┘
       ↓
┌──────────────────────────────────────┐
│ 查询自定义词典                        │
│ dictionary.get("llm")                │
└──────┬───────────────────────────────┘
       ↓
┌──────────────────────────────────────┐
│ 找到?                                │
│ YES → ["large language model", ...]  │
│ NO  → 继续                           │
└──────┬───────────────────────────────┘
       ↓ (未找到)
┌──────────────────────────────────────┐
│ 是纯英文?                            │
│ YES → 查询 WordNet                   │
│ NO  → 返回 []                        │
└──────┬───────────────────────────────┘
       ↓
┌──────────────┐
│ 返回同义词列表 │
└──────────────┘
```

---

## Redis 更新策略

### 更新触发条件

```python
# 三个条件同时满足才更新:
1. self.redis 存在
2. self.lookup_num >= 100
3. time.time() - self.load_tm >= 3600
```

### 更新流程

```
┌────────────────────────────────────┐
│ 服务启动                            │
├────────────────────────────────────┤
│ • 加载 synonym.json                 │
│ • 初始化 lookup_num = 100000000    │
│ • 初始化 load_tm = now - 1000000   │
└──────────┬─────────────────────────┘
           ↓
┌────────────────────────────────────┐
│ 查询 1: lookup("ai")               │
│ lookup_num: 100000000 → 100000001  │
│ 条件检查:                          │
│   ✓ redis 存在                     │
│   ✓ lookup_num >= 100              │
│   ✗ load_tm < 3600 (首次立即加载)  │
│ → 从 Redis 加载                    │
└──────────┬─────────────────────────┘
           ↓
┌────────────────────────────────────┐
│ 查询 2-100:                        │
│ lookup_num 累加                    │
│ load_tm 未超过 3600秒              │
│ → 跳过 Redis 加载                  │
└──────────┬─────────────────────────┘
           ↓
┌────────────────────────────────────┐
│ 查询 101 或 1小时后:               │
│ → 再次从 Redis 加载                │
└────────────────────────────────────┘
```

---

## 设计优势总结

| 特性 | 实现方式 | 优势 |
|-----|---------|------|
| **双层策略** | 自定义词典 + WordNet | 领域定制 + 通用知识 |
| **动态更新** | Redis 定时加载 | 无需重启，支持热更新 |
| **性能优化** | 限流保护 (100次/1小时) | 避免频繁 Redis 查询 |
| **多实例同步** | 共享 Redis 键 | 所有实例保持一致 |
| **容错降级** | Redis 失败时使用本地词典 | 高可用性 |
| **格式兼容** | 支持字符串/列表格式 | 灵活的数据结构 |
| **中英文支持** | 分层处理策略 | 适配不同语言 |

---

## 配置建议

### synonym.json 示例

```json
{
  "ai": ["人工智能", "artificial intelligence", "机器智能"],
  "llm": ["large language model", "大语言模型", "大模型"],
  "rag": ["retrieval augmented generation", "检索增强生成"],
  "vector": ["向量", "embedding"],
  "embedding": ["嵌入", "词嵌入", "向量化"]
}
```

### Redis 配置示例

```python
# Redis 中的数据结构
redis.set("kevin_synonyms", json.dumps({
    "ai": ["人工智能", "artificial intelligence"],
    "llm": ["large language model", "大语言模型"],
    ...
}))
```

---

## 总结

`synonym.py` 实现了一个**高效、灵活、可扩展**的同义词查找系统：

```
核心设计思想:
├─ 双层查找: 领域词典 (优先) + WordNet (回退)
├─ 动态更新: Redis 热更新 + 本地兜底
├─ 性能优化: 智能限流 + 条件触发
└─ 高可用: 容错降级 + 多实例同步

应用价值:
└─ 提升检索召回率，支持查询扩展和多语言检索
```

这种设计在保持**领域定制性**的同时，利用了**通用知识库**（WordNet），并通过 Redis 实现了动态更新，是检索系统中查询扩展模块的经典实现。
