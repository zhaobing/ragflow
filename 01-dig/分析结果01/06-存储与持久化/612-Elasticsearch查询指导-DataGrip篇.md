# Elasticsearch 查询指导 - DataGrip 篇

> **目标受众**: 使用DataGrip查询Elasticsearch数据的开发者
> **数据源**: RAGFlow存储在Elasticsearch中的chunk数据
> **创建时间**: 2026-01-21

---

## 目录

1. [DataGrip连接配置](#1-datagrip连接配置)
2. [基础查询](#2-基础查询)
3. [常见查询场景](#3-常见查询场景)
4. [聚合查询](#4-聚合查询)
5. [向量搜索](#5-向量搜索)
6. [全文检索](#6-全文检索)
7. [性能优化](#7-性能优化)
8. [数据结构说明](#8-数据结构说明)

---

## 1. DataGrip连接配置

### 1.1 添加Elasticsearch数据源

**步骤**:
1. 打开DataGrip
2. 点击 `Database` → `+` → `Data Source` → `Elasticsearch`

**连接配置**:
```
Host: localhost (或你的ES主机地址)
Port: 9200
Authentication: Basic Auth
Username: elastic (根据你的配置)
Password: your_password (根据你的配置)
```

**测试连接**:
- 点击 `Test Connection`
- 如果成功，会显示ES版本信息

### 1.2 使用SQL查询ES

DataGrip支持使用**SQL-like语法**查询Elasticsearch：

```sql
-- 基础查询
SELECT * FROM rag_table_tenant_001 LIMIT 10

-- 条件查询
SELECT id, kb_id, doc_id, docnm_kwd
FROM rag_table_tenant_001
WHERE kb_id = 'kb_123'
LIMIT 10
```

**底层转换**:
DataGrip会将SQL转换为Elasticsearch DSL查询。

---

## 2. 基础查询

### 2.1 查看所有索引

```sql
-- 查看所有索引
SHOW TABLES
```

**结果示例**:
```
rag_table_tenant_001
rag_table_tenant_002
...
```

### 2.2 查看索引结构

```sql
-- 查看索引的mapping（相当于表结构）
DESCRIBE rag_table_tenant_001
```

**或使用**:
```sql
-- 查看完整的mapping
SHOW COLUMNS FROM rag_table_tenant_001
```

### 2.3 基础SELECT查询

```sql
-- 查询指定字段
SELECT
    id,
    kb_id,
    doc_id,
    docnm_kwd,
    content_with_weight
FROM rag_table_tenant_001
LIMIT 10
```

### 2.4 WHERE条件过滤

```sql
-- 单条件
SELECT * FROM rag_table_tenant_001
WHERE kb_id = 'kb_123'

-- 多条件 AND
SELECT * FROM rag_table_tenant_001
WHERE kb_id = 'kb_123'
  AND available_int = 1

-- 多条件 OR
SELECT * FROM rag_table_tenant_001
WHERE kb_id = 'kb_123'
   OR kb_id = 'kb_456'

-- IN 查询
SELECT * FROM rag_table_tenant_001
WHERE kb_id IN ('kb_123', 'kb_456', 'kb_789')
```

---

## 3. 常见查询场景

### 3.1 查询指定知识库的所有chunk

```sql
SELECT
    id,
    doc_id,
    docnm_kwd,
    SUBSTRING(content_with_weight, 1, 100) as content_preview
FROM rag_table_tenant_001
WHERE kb_id = 'your_kb_id'
ORDER BY id
LIMIT 100
```

### 3.2 查询指定文档的所有chunk

```sql
SELECT
    id,
    important_kwd,
    question_kwd,
    content_with_weight
FROM rag_table_tenant_001
WHERE doc_id = 'your_doc_id'
ORDER BY id
```

### 3.3 查询可用的chunk

```sql
-- available_int = 1 表示可用
-- available_int = 0 表示不可用（如mother chunk）
SELECT
    COUNT(*) as total_chunks,
    available_int
FROM rag_table_tenant_001
GROUP BY available_int
```

### 3.4 查询包含关键词的chunk

```sql
-- 全文检索
SELECT
    id,
    docnm_kwd,
    content_with_weight
FROM rag_table_tenant_001
WHERE content_ltks LIKE '%关键词%'
   OR important_tks LIKE '%关键词%'
LIMIT 20
```

### 3.5 查询带图片的chunk

```sql
SELECT
    id,
    doc_id,
    img_id,
    position_int
FROM rag_table_tenant_001
WHERE img_id IS NOT NULL
  AND available_int = 1
LIMIT 50
```

### 3.6 查询Mother Chunk

```sql
-- Mother Chunk: available_int = 0
SELECT
    id,
    doc_id,
    LENGTH(content_with_weight) as content_length,
    content_with_weight
FROM rag_table_tenant_001
WHERE available_int = 0
ORDER BY id
LIMIT 10
```

### 3.7 查询带标签的chunk

```sql
SELECT
    id,
    docnm_kwd,
    tag_kwd,
    tag_feas
FROM rag_table_tenant_001
WHERE tag_kwd IS NOT NULL
  AND available_int = 1
LIMIT 50
```

### 3.8 查询知识图谱相关的chunk

```sql
-- 知识图谱chunk: knowledge_graph_kwd 不为空
SELECT
    id,
    knowledge_graph_kwd,
    entity_kwd,
    entity_type_kwd,
    from_entity_kwd,
    to_entity_kwd
FROM rag_table_tenant_001
WHERE knowledge_graph_kwd IS NOT NULL
```

---

## 4. 聚合查询

### 4.1 统计每个文档的chunk数量

```sql
SELECT
    doc_id,
    docnm_kwd,
    COUNT(*) as chunk_count
FROM rag_table_tenant_001
WHERE available_int = 1
GROUP BY doc_id, docnm_kwd
ORDER BY chunk_count DESC
LIMIT 20
```

### 4.2 统计每个知识库的chunk数量

```sql
SELECT
    kb_id,
    COUNT(*) as total_chunks,
    SUM(CASE WHEN available_int = 1 THEN 1 ELSE 0 END) as available_chunks,
    SUM(CASE WHEN available_int = 0 THEN 1 ELSE 0 END) as mother_chunks
FROM rag_table_tenant_001
GROUP BY kb_id
```

### 4.3 统计chunk的长度分布

```sql
SELECT
    CASE
        WHEN LENGTH(content_with_weight) < 500 THEN '0-500'
        WHEN LENGTH(content_with_weight) < 1000 THEN '500-1000'
        WHEN LENGTH(content_with_weight) < 2000 THEN '1000-2000'
        WHEN LENGTH(content_with_weight) < 5000 THEN '2000-5000'
        ELSE '5000+'
    END as length_range,
    COUNT(*) as chunk_count
FROM rag_table_tenant_001
WHERE available_int = 1
GROUP BY length_range
ORDER BY
    CASE
        WHEN length_range = '0-500' THEN 1
        WHEN length_range = '500-1000' THEN 2
        WHEN length_range = '1000-2000' THEN 3
        WHEN length_range = '2000-5000' THEN 4
        ELSE 5
    END
```

### 4.4 统计标签使用频率

```sql
-- 注意：数组字段的聚合在ES SQL中有限制
-- 可能需要使用原生聚合查询
SELECT
    tag_kwd,
    COUNT(*) as count
FROM rag_table_tenant_001
WHERE tag_kwd IS NOT NULL
GROUP BY tag_kwd
ORDER BY count DESC
LIMIT 20
```

---

## 5. 向量搜索

### 5.1 使用KNN向量搜索

**注意**: DataGrip的SQL不支持直接的向量搜索，需要使用**原生ES DSL查询**。

**在DataGrip中执行原生查询**:

```json
// 使用Console或Script执行
POST /rag_table_tenant_001/_search
{
  "size": 10,
  "query": {
    "knn": {
      "field": "q_1024_vec",
      "query_vector": [0.1, 0.2, 0.3, ...],  // 你的查询向量
      "k": 10,
      "num_candidates": 100
    }
  }
}
```

### 5.2 混合搜索（向量+全文）

```json
POST /rag_table_tenant_001/_search
{
  "size": 10,
  "query": {
    "bool": {
      "must": [
        {
          "query_string": {
            "fields": ["content_ltks^2", "title_tks^10", "important_tks^20"],
            "query": "你的查询关键词",
            "minimum_should_match": "30%"
          }
        }
      ]
    }
  },
  "knn": {
    "field": "q_1024_vec",
    "query_vector": [0.1, 0.2, 0.3, ...],
    "k": 10,
    "num_candidates": 50
  }
}
```

---

## 6. 全文检索

### 6.1 基础全文检索

```sql
-- 使用LIKE进行简单搜索
SELECT
    id,
    docnm_kwd,
    content_with_weight
FROM rag_table_tenant_001
WHERE content_ltks LIKE '%搜索内容%'
   OR important_tks LIKE '%搜索内容%'
LIMIT 20
```

### 6.2 使用query_string进行高级搜索

**使用原生DSL**:

```json
POST /rag_table_tenant_001/_search
{
  "query": {
    "query_string": {
      "fields": [
        "docnm_kwd^10",
        "content_ltks^2",
        "important_tks^20",
        "question_tks^20"
      ],
      "query": "搜索内容",
      "minimum_should_match": "30%"
    }
  },
  "size": 20
}
```

**字段权重说明**:
- `docnm_kwd^10`: 文档标题权重10
- `important_tks^20`: 关键词权重20
- `question_tks^20`: 问题权重20
- `content_ltks^2`: 内容权重2

### 6.3 多字段搜索

```json
POST /rag_table_tenant_001/_search
{
  "query": {
    "multi_match": {
      "query": "搜索内容",
      "fields": ["docnm_kwd", "content_ltks", "important_tks"],
      "type": "best_fields"
    }
  }
}
```

---

## 7. 性能优化

### 7.1 限制返回字段

```sql
-- 只查询需要的字段，减少网络传输
SELECT
    id,
    doc_id,
    docnm_kwd
FROM rag_table_tenant_001
WHERE kb_id = 'kb_123'
LIMIT 100
```

### 7.2 使用分页

```sql
-- 分页查询
SELECT id, docnm_kwd
FROM rag_table_tenant_001
LIMIT 50 OFFSET 0   -- 第一页

SELECT id, docnm_kwd
FROM rag_table_tenant_001
LIMIT 50 OFFSET 50  -- 第二页
```

### 7.3 合理使用filter

```sql
-- filter不计算得分，性能更好
SELECT * FROM rag_table_tenant_001
WHERE available_int = 1
  AND kb_id = 'kb_123'
```

### 7.4 避免全表扫描

```sql
-- ❌ 避免这样的查询
SELECT * FROM rag_table_tenant_001
WHERE SUBSTRING(content_with_weight, 1, 10) = '某个值'

-- ✅ 使用全文索引
SELECT * FROM rag_table_tenant_001
WHERE content_ltks LIKE '%某个值%'
```

---

## 8. 数据结构说明

### 8.1 核心字段

| 字段名 | 类型 | 说明 | 示例 |
|--------|------|------|------|
| `id` | string | Chunk唯一标识 | `"chunk_123"` |
| `kb_id` | string | 知识库ID | `"kb_456"` |
| `doc_id` | string | 文档ID | `"doc_789"` |
| `docnm_kwd` | string | 文档名称 | `"示例文档.pdf"` |
| `content_with_weight` | text | 原始内容 | `"这是文档内容..."` |
| `content_ltks` | text | 分词后的内容 | `"this is document"` |
| `content_sm_ltks` | text | 精细分词内容 | `"this doc"` |
| `available_int` | int | 可用性标志 | `1` (可用) / `0` (mother chunk) |

### 8.2 向量字段

| 字段名 | 维度 | 说明 |
|--------|------|------|
| `q_1024_vec` | 1024 | 1024维向量（OpenAI text-embedding-ada-002） |
| `q_768_vec` | 768 | 768维向量（BERT系列） |
| `q_1536_vec` | 1536 | 1536维向量（OpenAI text-embedding-3-large） |

### 8.3 数组字段

| 字段名 | 元素类型 | 说明 | 示例 |
|--------|---------|------|------|
| `important_kwd` | string | 关键词列表 | `["关键词1", "关键词2"]` |
| `question_kwd` | string | 问题列表 | `["问题1", "问题2"]` |
| `tag_kwd` | string | 标签列表 | `["标签1", "标签2"]` |
| `position_int` | array | PDF位置信息 | `[[x0, y0, x1, y1], ...]` |

### 8.4 特殊字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `pagerank_fea` | int | PageRank权重（用于排序） |
| `tag_feas` | object | 标签特征（用于rank_feature） |
| `metadata` | object | 元数据（JSON格式） |
| `img_id` | string | 关联图片ID |
| `mom_id` | string | Mother Chunk ID |

### 8.5 知识图谱字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `knowledge_graph_kwd` | string | 图谱chunk类型 |
| `entity_kwd` | string | 实体名称 |
| `entity_type_kwd` | string | 实体类型 |
| `from_entity_kwd` | string | 边的起始实体 |
| `to_entity_kwd` | string | 边的结束实体 |
| `weight_int` | int | 边的权重 |
| `rank_flt` | float | 实体排名 |

---

## 9. 实用查询模板

### 9.1 查询模板1: 检查chunk完整性

```sql
-- 检查是否有缺失必要字段的chunk
SELECT
    COUNT(*) as missing_content
FROM rag_table_tenant_001
WHERE content_with_weight IS NULL
   OR content_ltks IS NULL
   OR kb_id IS NULL
```

### 9.2 查询模板2: 查找重复chunk

```sql
-- 根据content_ltks查找重复chunk
SELECT
    content_ltks,
    COUNT(*) as count,
    GROUP_CONCAT(id) as chunk_ids
FROM rag_table_tenant_001
GROUP BY content_ltks
HAVING COUNT(*) > 1
```

### 9.3 查询模板3: 数据质量检查

```sql
-- 检查数据质量
SELECT
    'Total chunks' as metric,
    COUNT(*) as value
FROM rag_table_tenant_001
UNION ALL
SELECT
    'Chunks with content',
    COUNT(*)
FROM rag_table_tenant_001
WHERE LENGTH(content_with_weight) > 0
UNION ALL
SELECT
    'Chunks with keywords',
    COUNT(*)
FROM rag_table_tenant_001
WHERE important_kwd IS NOT NULL
  AND ARRAY_LENGTH(important_kwd) > 0
UNION ALL
SELECT
    'Chunks with images',
    COUNT(*)
FROM rag_table_tenant_001
WHERE img_id IS NOT NULL
```

### 9.4 查询模板4: 查找大chunk

```sql
-- 查找内容过长的chunk
SELECT
    id,
    docnm_kwd,
    LENGTH(content_with_weight) as content_length,
    SUBSTRING(content_with_weight, 1, 200) as content_preview
FROM rag_table_tenant_001
WHERE LENGTH(content_with_weight) > 5000
ORDER BY content_length DESC
LIMIT 20
```

### 9.5 查询模板5: 导出数据

```sql
-- 导出指定知识库的所有chunk
SELECT
    id,
    kb_id,
    doc_id,
    docnm_kwd,
    content_with_weight,
    important_kwd,
    img_id
FROM rag_table_tenant_001
WHERE kb_id = 'your_kb_id'
  AND available_int = 1
-- 在DataGrip中可以导出为CSV/Excel
```

---

## 10. 常见问题

### Q1: 如何查看完整的chunk内容？

**A**: DataGrip默认会截断长文本，需要设置：

1. 打开 `File` → `Settings` → `Editor` → `General` → `Appearance`
2. 勾选 `Show data in editor as`
3. 或者直接在结果面板右键 → `Fetch all rows`

### Q2: SQL查询报错怎么办？

**A**: 检查以下几点：

1. 索引名称是否正确
2. 字段名称是否正确（使用`DESCRIBE`查看）
3. SQL语法是否符合ES SQL规范

### Q3: 如何执行复杂的向量搜索？

**A**: 使用原生DSL查询：

1. 在DataGrip中打开 `Console`
2. 直接执行JSON格式的DSL查询
3. 或使用 `Script` 模式

### Q4: 如何分析查询性能？

**A**: 在DSL查询中启用`profile`：

```json
POST /rag_table_tenant_001/_search
{
  "profile": true,
  "query": {
    "match_all": {}
  }
}
```

返回结果会包含详细的性能分析。

---

## 11. 快速参考

### 11.1 常用SQL语句

```sql
-- 查看所有索引
SHOW TABLES

-- 查看索引结构
DESCRIBE rag_table_tenant_001

-- 查询前N条
SELECT * FROM rag_table_tenant_001 LIMIT 10

-- 条件查询
SELECT * FROM rag_table_tenant_001 WHERE kb_id = 'kb_123'

-- 统计
SELECT COUNT(*) FROM rag_table_tenant_001

-- 分组统计
SELECT kb_id, COUNT(*) FROM rag_table_tenant_001 GROUP BY kb_id
```

### 11.2 常用DSL查询

```json
// 基础查询
GET /rag_table_tenant_001/_search
{
  "query": {
    "match_all": {}
  },
  "size": 10
}

// 词条查询
GET /rag_table_tenant_001/_search
{
  "query": {
    "term": {
      "kb_id": "kb_123"
    }
  }
}

// 范围查询
GET /rag_table_tenant_001/_search
{
  "query": {
    "range": {
      "pagerank_fea": {
        "gte": 10
      }
    }
  }
}
```

---

## 12. 相关文档

- [Elasticsearch SQL官方文档](https://www.elastic.co/guide/en/elasticsearch/reference/current/xpack-sql.html)
- [Elasticsearch Query DSL](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl.html)
- [601-持久化流程总结.md](601-持久化流程总结.md)
- [611-Elasticsearch插入流程分析.md](611-Elasticsearch插入流程分析.md)
