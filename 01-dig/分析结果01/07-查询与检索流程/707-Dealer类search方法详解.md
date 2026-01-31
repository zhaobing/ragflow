# Dealer类search方法详解

> 文件位置: [rag/nlp/search.py](../../../rag/nlp/search.py) 第74-176行
> 分析时间: 2026-01-31

## 目录

1. [函数概述](#函数概述)
2. [函数签名](#函数签名)
3. [核心数据结构](#核心数据结构)
4. [执行流程详解](#执行流程详解)
5. [关键代码分析](#关键代码分析)
6. [调用链路](#调用链路)

---

## 函数概述

`search` 方法是 `Dealer` 类的核心方法，负责在文档存储引擎（Elasticsearch/Infinity）中执行混合检索，结合了**全文检索**和**向量检索**两种方式。

### 主要功能

- 支持纯全文检索
- 支持纯向量检索
- 支持混合检索（全文+向量融合）
- 支持多维度过滤（知识库、文档、实体等）
- 支持分页查询
- 支持高亮显示

---

## 函数签名

```python
def search(self, req: dict,
           idx_names: str | list[str],
           kb_ids: list[str],
           emb_mdl=None,
           highlight: bool | list | None = None,
           rank_feature: dict | None = None) -> SearchResult
```

### 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `req` | dict | 检索请求对象，包含查询条件、分页参数等 |
| `idx_names` | str\|list[str] | 索引名称（租户ID对应的索引） |
| `kb_ids` | list[str] | 知识库ID列表 |
| `emb_mdl` | EmbeddingModel | 嵌入模型，用于向量检索（可选） |
| `highlight` | bool\|list\|None | 高亮配置，True默认高亮content/title，list自定义字段 |
| `rank_feature` | dict\|None | 排序特征（如PageRank分数） |

### req字典结构

```python
req = {
    # 查询条件
    "question": "用户查询的问题",
    "kb_ids": ["kb_id1", "kb_id2"],  # 知识库过滤
    "doc_ids": ["doc_id1"],           # 文档过滤

    # 分页参数
    "page": 1,     # 页码（从1开始）
    "size": 10,    # 每页大小
    "topk": 1024,  # 返回的最大结果数

    # 相似度参数
    "similarity": 0.1,  # 向量相似度阈值

    # 其他过滤条件
    "knowledge_graph_kwd": "...",
    "entity_kwd": "...",
    "available_int": 1,
    # ...
}
```

---

## 核心数据结构

### SearchResult（返回结果）

```python
@dataclass
class SearchResult:
    total: int                    # 命中的文档总数
    ids: list[str]               # 命中的chunk ID列表
    query_vector: list[float]    # 查询向量
    field: dict                  # 文档字段内容 {chunk_id: {field: value}}
    highlight: dict              # 高亮结果 {chunk_id: "highlighted_content"}
    aggregation: list|dict       # 聚合结果（按文档名分组）
    keywords: list[str]          # 提取的关键词
    group_docs: list[list]       # 分组文档
```

---

## 执行流程详解

### 流程图

```
┌─────────────────────────────────────────────────────────────┐
│                      search 方法流程                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  1. 初始化参数   │
                    │  - 过滤条件      │
                    │  - 分页参数      │
                    │  - 返回字段      │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  是否有问题?     │
                    └────────┬────────┘
                      │           │
                   NO │           │ YES
                      │           │
                      ▼           ▼
        ┌─────────────────┐  ┌─────────────────────┐
        │ 2A. 无问题检索   │  │ 2B. 有问题检索       │
        │ - 按页码排序     │  │ - 问题分析           │
        │ - 简单过滤       │  │ - 关键词提取         │
        └─────────────────┘  └──────────┬──────────┘
                                       │
                                       ▼
                             ┌─────────────────────┐
                             │ 是否有嵌入模型?      │
                             └──────────┬──────────┘
                                   │         │
                                NO │         │ YES
                                   │         │
                                   ▼         ▼
                     ┌─────────────────┐  ┌─────────────────────┐
                     │ 3A. 全文检索    │  │ 3B. 混合检索        │
                     │ - matchText     │  │ - matchText         │
                     │                │  │ - matchDense(向量)  │
                     │                │  │ - fusionExpr(融合)  │
                     └─────────────────┘  └──────────┬──────────┘
                                                       │
                                                       ▼
                                           ┌───────────────────────┐
                                           │  4. 结果为空重试       │
                                           │  - 降低min_match      │
                                           │  - 降低similarity    │
                                           └───────────┬───────────┘
                                                       │
                                                       ▼
                                           ┌───────────────────────┐
                                           │  5. 后处理             │
                                           │  - 提取关键词          │
                                           │  - 高亮处理           │
                                           │  - 聚合统计           │
                                           └───────────┬───────────┘
                                                       │
                                                       ▼
                                           ┌───────────────────────┐
                                           │  6. 返回SearchResult  │
                                           └───────────────────────┘
```

---

## 关键代码分析

### 1. 初始化阶段（83-98行）

```python
# 构建过滤条件
filters = self.get_filters(req)
orderBy = OrderByExpr()

# 分页计算
pg = int(req.get("page", 1)) - 1  # 转为0-based
topk = int(req.get("topk", 1024))
ps = int(req.get("size", topk))
offset, limit = pg * ps, ps

# 获取返回字段列表
src = req.get("fields", [
    "docnm_kwd",          # 文档名
    "content_ltks",       # 内容分词
    "kb_id",             # 知识库ID
    "doc_id",            # 文档ID
    "title_tks",         # 标题分词
    "important_kwd",     # 关键词
    "position_int",      # 位置
    # ...
])
kwds = set([])
```

**要点：**
- `page` 从1开始转为0-based索引
- `size` 默认等于 `topk`
- `fields` 控制返回哪些字段，减少网络传输

---

### 2. 无问题检索分支（103-110行）

当没有问题查询时，仅按照页码和创建时间排序返回结果：

```python
if not qst:
    if req.get("sort"):
        orderBy.asc("page_num_int")
        orderBy.asc("top_int")
        orderBy.desc("create_timestamp_flt")
    res = self.dataStore.search(src, [], filters, [], orderBy, offset, limit, idx_names, kb_ids)
```

**使用场景：**
- 浏览文档内容
- 按顺序查看chunk
- 不需要语义匹配的场景

---

### 3. 问题分析（117行）

```python
matchText, keywords = self.qryr.question(qst, min_match=0.3)
```

**`question` 方法的作用：**
1. **分词处理**: 对问题进行分词
2. **关键词提取**: 提取重要关键词
3. **构建查询表达式**: 生成全文检索的 `matchText` 表达式

**min_match 参数：**
- `0.3` 表示至少匹配30%的词项
- 控制召回的严格程度
- 后续会降到 `0.1` 进行宽松重试

---

### 4. 全文检索分支（120-125行）

当没有嵌入模型时，仅使用全文检索：

```python
if emb_mdl is None:
    matchExprs = [matchText]
    res = self.dataStore.search(
        src, highlightFields, filters, matchExprs,
        orderBy, offset, limit, idx_names, kb_ids,
        rank_feature=rank_feature
    )
```

**特点：**
- 只使用BM25等文本相似度算法
- 不需要向量模型
- 响应速度快
- 适合精确匹配场景

---

### 5. 混合检索分支（126-152行）

当有嵌入模型时，执行**向量+全文**的混合检索：

#### 5.1 获取查询向量（128-129行）

```python
matchDense = self.get_vector(qst, emb_mdl, topk, req.get("similarity", 0.1))
q_vec = matchDense.embedding_data
```

**`get_vector` 方法（53-61行）：**

```python
def get_vector(self, txt, emb_mdl, topk=10, similarity=0.1):
    # 使用嵌入模型编码查询
    qv, _ = emb_mdl.encode_queries(txt)

    # 转换为浮点数组
    embedding_data = [get_float(v) for v in qv]

    # 构建向量列名 (如 q_1024_vec)
    vector_column_name = f"q_{len(embedding_data)}_vec"

    # 返回密集向量匹配表达式
    return MatchDenseExpr(
        vector_column_name,
        embedding_data,
        'float',
        'cosine',        # 余弦相似度
        topk,
        {"similarity": similarity}
    )
```

**要点：**
- 支持任意维度的向量（1024/768等）
- 使用余弦相似度
- `similarity` 参数控制最低相似度阈值

---

#### 5.2 构建融合表达式（133-134行）

```python
fusionExpr = FusionExpr("weighted_sum", topk, {"weights": "0.05,0.95"})
matchExprs = [matchText, matchDense, fusionExpr]
```

**融合策略：**

| 权重 | 值 | 说明 |
|------|-----|------|
| 全文检索权重 | 0.05 (5%) | BM25分数权重 |
| 向量检索权重 | 0.95 (95%) | 余弦相似度权重 |

**设计理念：**
- 向量检索主导（95%），重视语义相似
- 全文检索辅助（5%），提升关键词匹配
- 可以通过调整权重适应不同场景

---

#### 5.3 执行混合检索（136-139行）

```python
res = self.dataStore.search(
    src, highlightFields, filters, matchExprs,
    orderBy, offset, limit, idx_names, kb_ids,
    rank_feature=rank_feature
)
```

**matchExprs 的组成：**
1. `matchText`: 全文检索表达式（BM25）
2. `matchDense`: 向量检索表达式（余弦相似度）
3. `fusionExpr`: 融合表达式（加权求和）

---

### 6. 结果为空重试机制（141-152行）

当第一次检索结果为空时，执行降级重试：

```python
if total == 0:
    if filters.get("doc_id"):
        # 如果有文档过滤，去掉检索条件直接返回
        res = self.dataStore.search(src, [], filters, [], orderBy, offset, limit, idx_names, kb_ids)
    else:
        # 降低匹配要求重试
        matchText, _ = self.qryr.question(qst, min_match=0.1)  # 从0.3降到0.1
        matchDense.extra_options["similarity"] = 0.17          # 从0.1降到0.17
        res = self.dataStore.search(src, highlightFields, filters,
                                   [matchText, matchDense, fusionExpr],
                                   orderBy, offset, limit, idx_names, kb_ids,
                                   rank_feature=rank_feature)
```

**降级策略：**

| 参数 | 初始值 | 降级值 | 说明 |
|------|--------|--------|------|
| min_match | 0.3 | 0.1 | 全文匹配比例降低 |
| similarity | 0.1 | 0.17 | 向量相似度阈值降低 |

**注意：** similarity从0.1升到0.17是**放宽限制**（因为是阈值，越低越严格）

---

### 7. 关键词提取（154-161行）

```python
for k in keywords:
    kwds.add(k)
    # 细粒度分词
    for kk in rag_tokenizer.fine_grained_tokenize(k).split():
        if len(kk) < 2:
            continue
        if kk in kwds:
            continue
        kwds.add(kk)
```

**作用：**
- 提取查询关键词用于高亮
- 细粒度分词增加匹配范围
- 去重避免重复

---

### 8. 返回结果构建（164-176行）

```python
ids = self.dataStore.get_chunk_ids(res)
keywords = list(kwds)
highlight = self.dataStore.get_highlight(res, keywords, "content_with_weight")
aggs = self.dataStore.get_aggregation(res, "docnm_kwd")

return self.SearchResult(
    total=total,
    ids=ids,
    query_vector=q_vec,
    aggregation=aggs,
    highlight=highlight,
    field=self.dataStore.get_fields(res, src + ["_score"]),
    keywords=keywords
)
```

**返回内容：**
- `total`: 命中总数
- `ids`: chunk ID列表
- `query_vector`: 查询向量（用于后续重排序）
- `aggregation`: 按文档名聚合的统计
- `highlight`: 高亮结果
- `field`: 字段内容（包括分数）
- `keywords`: 提取的关键词

---

## 调用链路

### 上游调用

```
retrieval() (search.py:366)
    └── search() (search.py:74)
            └── dataStore.search() (DocStoreConnection)
```

### 下游调用

```
search()
    ├── get_filters()          # 构建过滤条件
    ├── qryr.question()        # 问题分析
    ├── get_vector()           # 获取向量
    ├── dataStore.search()     # 执行检索
    ├── dataStore.get_chunk_ids()
    ├── dataStore.get_highlight()
    ├── dataStore.get_aggregation()
    └── dataStore.get_fields()
```

---

## 配合使用的方法

### 1. get_filters() - 构建过滤条件（63-72行）

```python
def get_filters(self, req):
    condition = dict()
    for key, field in {"kb_ids": "kb_id", "doc_ids": "doc_id"}.items():
        if key in req and req[key] is not None:
            condition[field] = req[key]

    for key in ["knowledge_graph_kwd", "available_int", "entity_kwd",
                "from_entity_kwd", "to_entity_kwd", "removed_kwd"]:
        if key in req and req[key] is not None:
            condition[key] = req[key]
    return condition
```

**支持的过滤条件：**
- `kb_id`: 知识库ID
- `doc_id`: 文档ID
- `knowledge_graph_kwd`: 知识图谱关键词
- `available_int`: 可用性标识
- `entity_kwd`: 实体关键词
- `from_entity_kwd`: 源实体
- `to_entity_kwd`: 目标实体

---

### 2. rerank() - 重排序（298-335行）

```python
def rerank(self, sres, query, tkweight=0.3, vtweight=0.7, cfield="content_ltks",
           rank_feature: dict | None = None):
    _, keywords = self.qryr.question(query)

    # 获取向量
    vector_size = len(sres.query_vector)
    vector_column = f"q_{vector_size}_vec"
    zero_vector = [0.0] * vector_size
    ins_embd = []
    for chunk_id in sres.ids:
        vector = sres.field[chunk_id].get(vector_column, zero_vector)
        ins_embd.append(vector)

    # 构建token权重
    ins_tw = []
    for i in sres.ids:
        content_ltks = list(OrderedDict.fromkeys(sres.field[i][cfield].split()))
        title_tks = [t for t in sres.field[i].get("title_tks", "").split() if t]
        question_tks = [t for t in sres.field[i].get("question_tks", "").split() if t]
        important_kwd = sres.field[i].get("important_kwd", [])
        # 标题权重2倍，问题权重6倍，关键词权重5倍
        tks = content_ltks + title_tks * 2 + important_kwd * 5 + question_tks * 6
        ins_tw.append(tks)

    # 计算排序特征分数
    rank_fea = self._rank_feature_scores(rank_feature, sres)

    # 混合相似度计算
    sim, tksim, vtsim = self.qryr.hybrid_similarity(
        sres.query_vector, ins_embd, keywords, ins_tw, tkweight, vtweight
    )

    return sim + rank_fea, tksim, vtsim
```

**重排序公式：**

```
最终分数 = 文本相似度 × token权重 + 向量相似度 × 向量权重 + 排序特征分数
```

**字段权重分配：**
- 正文: 1倍
- 标题: 2倍
- 重要关键词: 5倍
- 问题: 6倍

---

## 使用示例

### 示例1: 基本检索

```python
dealer = Dealer(data_store)

req = {
    "question": "什么是机器学习？",
    "kb_ids": ["kb_001"],
    "page": 1,
    "size": 10,
    "topk": 1024,
    "similarity": 0.1
}

result = dealer.search(
    req=req,
    idx_names="ragflow_tenant_001",
    kb_ids=["kb_001"],
    emb_mdl=embedding_model
)

print(f"命中总数: {result.total}")
print(f"chunk IDs: {result.ids}")
print(f"关键词: {result.keywords}")
```

### 示例2: 带文档过滤的检索

```python
req = {
    "question": "深度学习原理",
    "kb_ids": ["kb_001"],
    "doc_ids": ["doc_123", "doc_456"],  # 只检索特定文档
    "page": 1,
    "size": 20
}

result = dealer.search(req, idx_names, kb_ids, emb_mdl)
```

### 示例3: 纯全文检索

```python
# 不传emb_mdl，只使用全文检索
result = dealer.search(
    req=req,
    idx_names=idx_names,
    kb_ids=kb_ids,
    highlight=True  # 启用高亮
)
```

---

## 性能优化点

1. **字段过滤**: 通过 `fields` 参数只返回需要的字段
2. **分页处理**: 使用 `offset` + `limit` 避免返回过多数据
3. **过滤优先**: 通过 `filters` 在检索前过滤，减少检索范围
4. **重试机制**: 避免无谓的重试，有条件降级

---

## 总结

`search` 方法是RAGFlow检索系统的核心，实现了：

1. **灵活的检索模式**: 支持全文、向量、混合三种模式
2. **多维过滤**: 支持知识库、文档、实体等多种过滤条件
3. **智能重试**: 结果为空时自动降级重试
4. **高亮支持**: 提供查询关键词高亮
5. **聚合统计**: 按文档聚合命中结果

其设计体现了**召回**与**排序**分离的原则：
- `search` 负责大规模召回（topk=1024）
- `rerank` 负责精细重排序（返回少量高质量结果）
