# Word持久化流程分析

## 概述

本文档分析RAGFlow中Word文档处理后的数据持久化机制，包括Chunk生成、向量化处理和存储引擎插入。

---

## 1. 持久化入口 - do_handle_task()

### 1.1 函数签名与位置

**文件**: `rag/svr/task_executor.py:862-1080`

```python
@timeout(60*60*3, 1)
async def do_handle_task(task):
```

### 1.2 任务类型处理

```python
task_type = task.get("task_type", "")

if task_type == "raptor":
    # RAPTOR层次聚类
    await run_raptor_for_kb(...)
elif task_type == "graphrag":
    # 知识图谱
    await run_graphrag_for_kb(...)
elif task_type == "dataflow":
    # 工作流
    await run_dataflow(task)
else:
    # 标准切片处理 (包括Word)
    chunks = await build_chunks(task, progress_callback)
    token_count, vector_size = await embedding(chunks, embedding_model, ...)
    await insert_es(task_id, task_tenant_id, task_dataset_id, chunks, ...)
```

### 1.3 Word文档处理流程

```
do_handle_task()
    │
    ├── 1. 绑定嵌入模型
    ├── 2. 初始化知识库索引
    ├── 3. build_chunks()    ← 解析与切片
    ├── 4. embedding()       ← 向量化
    └── 5. insert_es()       ← 持久化
```

---

## 2. Chunk生成 - build_chunks()

### 2.1 函数签名与位置

**文件**: `rag/svr/task_executor.py:226-330`

```python
@timeout(60*80, 1)
async def build_chunks(task, progress_callback):
```

### 2.2 处理流程

```python
# 1. 文件大小检查
if task["size"] > settings.DOC_MAXIMUM_SIZE:
    return []

# 2. 从MinIO获取文件
bucket, name = File2DocumentService.get_storage_address(doc_id=task["doc_id"])
binary = await get_storage_binary(bucket, name)

# 3. 调用chunker进行切片
chunker = FACTORY[task["parser_id"].lower()]  # "naive" → NaiveChunker
async with chunk_limiter:
    cks = await asyncio.to_thread(
        chunker.chunk,
        task["name"],
        binary=binary,
        from_page=task["from_page"],
        to_page=task["to_page"],
        lang=task["language"],
        callback=progress_callback,
        kb_id=task["kb_id"],
        parser_config=task["parser_config"],
        tenant_id=task["tenant_id"],
    )

# 4. 构建文档元数据
docs = []
doc = {
    "doc_id": task["doc_id"],
    "kb_id": str(task["kb_id"])
}

# 5. 处理每个chunk
for ck in cks:
    d = copy.deepcopy(doc)
    d.update(ck)
    # 上传图片到MinIO
    if ck.get("image"):
        img_id = await upload_to_minio(doc, ck)
        d["img_id"] = img_id
    docs.append(d)

return docs
```

### 2.3 图片上传 - upload_to_minio()

```python
@timeout(60)
async def upload_to_minio(document, chunk):
    img_id = generate_hash_id()
    buf = BytesIO()
    chunk["image"].save(buf, format="JPEG")
    buf.seek(0)
    settings.STORAGE_IMPL.put(buf.getvalue(), folder="image", name=img_id)
    return img_id
```

---

## 3. 向量化处理 - embedding()

### 3.1 函数签名与位置

**文件**: `rag/svr/task_executor.py:475-543`

```python
async def embedding(docs, mdl, parser_config=None, callback=None):
```

### 3.2 内容提取

```python
tts, cnts = [], []
for d in docs:
    # 标题
    tts.append(d.get("docnm_kwd", "Title"))

    # 内容: 优先使用question_kwd，否则使用content_with_weight
    c = "\n".join(d.get("question_kwd", []))
    if not c:
        c = d["content_with_weight"]

    # HTML标签清理
    c = re.sub(r"</?(table|td|caption|tr|th)( [^<>]{0,12})?>", " ", c)
    if not c:
        c = "None"
    cnts.append(c)
```

### 3.3 标题向量化

```python
# 只编码第一个标题，然后广播
vts, c = await asyncio.to_thread(mdl.encode, tts[0:1])
tts = np.tile(vts[0], (len(cnts), 1))  # 复制n份
tk_count += c
```

**优化**: 避免重复编码相同标题，提升性能。

### 3.4 内容批量向量化

```python
@timeout(60)
def batch_encode(txts):
    return mdl.encode([truncate(c, mdl.max_length-10) for c in txts])

cnts_ = np.array([])
for i in range(0, len(cnts), settings.EMBEDDING_BATCH_SIZE):
    async with embed_limiter:
        vts, c = await asyncio.to_thread(batch_encode, cnts[i : i + settings.EMBEDDING_BATCH_SIZE])

    if len(cnts_) == 0:
        cnts_ = vts
    else:
        cnts_ = np.concatenate((cnts_, vts), axis=0)
    tk_count += c
```

**批量大小**: `settings.EMBEDDING_BATCH_SIZE` (默认32)

### 3.5 向量融合

```python
filename_embd_weight = parser_config.get("filename_embd_weight", 0.1)
title_w = float(filename_embd_weight)

# 融合公式: vect = title_w * title_vec + (1-title_w) * content_vec
if tts.ndim == 2 and cnts.ndim == 2 and tts.shape == cnts.shape:
    vects = title_w * tts + (1 - title_w) * cnts
else:
    vects = cnts
```

**融合目的**: 结合标题(全局信息)和内容(局部信息)的向量。

### 3.6 向量挂载

```python
assert len(vects) == len(docs)
vector_size = 0
for i, d in enumerate(docs):
    v = vects[i].tolist()
    vector_size = len(v)
    d["q_%d_vec" % len(v)] = v  # 动态字段名，如 q_768_vec

return tk_count, vector_size
```

**动态字段名**: `q_{维度}_vec`，如 `q_1024_vec`、`q_768_vec`

---

## 4. 存储引擎插入 - insert_es()

### 4.1 函数签名与位置

**文件**: `rag/svr/task_executor.py:787-848`

```python
async def insert_es(task_id, task_tenant_id, task_dataset_id, chunks, progress_callback):
```

### 4.2 Mother Chunk处理

```python
mothers = []
mother_ids = set([])

# 提取Mother Chunks (使用了子分隔符的chunk)
for ck in chunks:
    mom = ck.get("mom") or ck.get("mom_with_weight") or ""
    if not mom:
        continue

    # 生成Mother Chunk ID
    id = xxhash.xxhash64(mom.encode("utf-8")).hexdigest()
    ck["mom_id"] = id

    # 避免重复
    if id in mother_ids:
        continue
    mother_ids.add(id)

    # 构建Mother Chunk
    mom_ck = copy.deepcopy(ck)
    mom_ck["id"] = id
    mom_ck["content_with_weight"] = mom
    mom_ck["available_int"] = 0  # 不直接用于检索
    flds = list(mom_ck.keys())
    for fld in flds:
        if fld not in ["id", "content_with_weight", "doc_id", "docnm_kwd", "kb_id", "available_int", "position_int"]:
            del mom_ck[fld]
    mothers.append(mom_ck)
```

**Mother Chunk**: 使用子分隔符的原始完整文本，不参与检索，仅用于引用。

### 4.3 批量插入Mother Chunks

```python
for b in range(0, len(mothers), settings.DOC_BULK_SIZE):
    await asyncio.to_thread(
        settings.docStoreConn.insert,
        mothers[b:b + settings.DOC_BULK_SIZE],
        search.index_name(task_tenant_id),
        task_dataset_id,
    )
    task_canceled = has_canceled(task_id)
    if task_canceled:
        progress_callback(-1, msg="Task has been canceled.")
        return False
```

**批量大小**: `settings.DOC_BULK_SIZE` (默认64)

### 4.4 批量插入普通Chunks

```python
for b in range(0, len(chunks), settings.DOC_BULK_SIZE):
    doc_store_result = await asyncio.to_thread(
        settings.docStoreConn.insert,
        chunks[b:b + settings.DOC_BULK_SIZE],
        search.index_name(task_tenant_id),
        task_dataset_id,
    )

    # 检查取消
    task_canceled = has_canceled(task_id)
    if task_canceled:
        progress_callback(-1, msg="Task has been canceled.")
        return False

    # 更新进度
    if b % 128 == 0:
        progress_callback(prog=0.8 + 0.1 * (b + 1) / len(chunks), msg="")

    # 检查错误
    if doc_store_result:
        error_message = f"Insert chunk error: {doc_store_result}..."
        progress_callback(-1, msg=error_message)
        raise Exception(error_message)

    # 更新任务chunk_ids
    chunk_ids = [chunk["id"] for chunk in chunks[:b + settings.DOC_BULK_SIZE]]
    chunk_ids_str = " ".join(chunk_ids)
    TaskService.update_chunk_ids(task_id, chunk_ids_str)
```

### 4.5 存储引擎抽象

```python
settings.docStoreConn.insert
# 根据配置实际是:
# - Elasticsearch: rag.utils.es_conn.EsConnection.insert()
# - Infinity: rag.utils.infinity_conn.InfinityConnection.insert()
```

---

## 5. 完整Chunk数据结构

### 5.1 基础字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | str | Chunk唯一ID (xxhash) |
| `doc_id` | str | 文档ID |
| `kb_id` | str | 知识库ID |

### 5.2 内容字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `content_with_weight` | str | 原始文本内容 |
| `content_ltks` | str | 粗粒度分词(空格分隔) |
| `content_sm_ltks` | str | 细粒度分词 |
| `mom_with_weight` | str | Mother chunk内容(有子分隔符时) |

### 5.3 元数据字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `docnm_kwd` | str | 文档名称 |
| `title_tks` | str | 标题分词 |
| `title_sm_tks` | str | 标题细粒度分词 |

### 5.4 位置字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `page_num_int` | List[int] | 页码列表 [pn, pn, pn, pn, pn] |
| `position_int` | List[tuple] | 位置坐标 [(pn, left, right, top, bottom), ...] |
| `top_int` | List[int] | 顶部坐标 [top, ...] |

### 5.5 类型字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `doc_type_kwd` | str | 文档类型: "table"/"image"/"" |

### 5.6 图片字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `image` | PIL.Image | 图片对象(处理时) |
| `img_id` | str | 图片ID(MinIO存储后) |

### 5.7 向量字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `q_{n}_vec` | List[float] | n维向量，如 q_768_vec |

### 5.8 Mother Chunk字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `mom_id` | str | Mother chunk ID |
| `available_int` | int | 可用标记(0=不参与检索) |

### 5.9 完整示例

```python
{
    # ===== 基础 =====
    "id": "a1b2c3d4e5f6...",
    "doc_id": "doc_123",
    "kb_id": "kb_456",

    # ===== 内容 =====
    "content_with_weight": "这是文档内容...",
    "content_ltks": "这 文档 内容",
    "content_sm_ltks": "这  文  案  内  容",
    "mom_with_weight": "完整的原始内容...",

    # ===== 元数据 =====
    "docnm_kwd": "报告.docx",
    "title_tks": "报告 标题",
    "title_sm_tks": "报  告  标  题",

    # ===== 位置 =====
    "page_num_int": [1, 1, 1, 1, 1],
    "position_int": [(1, 100, 500, 200, 300)],
    "top_int": [200],

    # ===== 类型 =====
    "doc_type_kwd": "",

    # ===== 图片 =====
    "img_id": "img_xyz...",

    # ===== 向量 =====
    "q_768_vec": [0.1, 0.2, ..., 0.9],  # 768维

    # ===== Mother Chunk =====
    "mom_id": "mom_abc...",
}
```

---

## 6. 完整持久化流程图

```
do_handle_task()
    │
    ├── 1. 绑定嵌入模型
    │   embedding_model = LLMBundle(tenant_id, LLMType.EMBEDDING, ...)
    │
    ├── 2. 初始化知识库索引
    │   init_kb(task, vector_size)
    │   └── settings.docStoreConn.createIdx(idxnm, kb_id, vector_size)
    │
    ├── 3. build_chunks()
    │   ├── 从MinIO获取文件
    │   ├── 调用chunker.chunk()
    │   │   └── 内部调用 Docx().__call__()
    │   │       └── 返回 sections, tables
    │   │   └── naive_merge_docx()
    │   │   └── tokenize_chunks_with_images()
    │   │   └── tokenize_table()
    │   ├── 上传图片到MinIO
    │   └── 返回 chunks列表
    │
    ├── 4. embedding()
    │   ├── 提取标题和内容
    │   ├── 标题向量化 (编码第一个，广播)
    │   ├── 内容批量向量化
    │   ├── 向量融合
    │   └── 挂载向量到chunk: d["q_768_vec"] = [...]
    │
    └── 5. insert_es()
        ├── 提取Mother Chunks
        ├── 批量插入Mother Chunks
        │   └── docStoreConn.insert(mothers, index_name, kb_id)
        ├── 批量插入普通Chunks
        │   └── docStoreConn.insert(chunks, index_name, kb_id)
        ├── 更新任务chunk_ids
        └── DocumentService.increment_chunk_num()
```

---

## 7. 关键配置参数

| 参数 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `DOC_MAXIMUM_SIZE` | settings | - | 最大文件大小 |
| `EMBEDDING_BATCH_SIZE` | settings | 32 | 向量化批量大小 |
| `DOC_BULK_SIZE` | settings | 64 | 存储插入批量大小 |
| `filename_embd_weight` | parser_config | 0.1 | 标题向量权重 |
| `chunk_token_num` | parser_config | 128 | 切片token数 |

---

## 8. 总结

Word持久化核心流程：

1. **文件获取**: 从MinIO获取Word文档二进制
2. **解析切片**: 调用chunk函数生成sections和tables
3. **Token化**: 对文本和表格进行分词处理
4. **图片上传**: 将图片上传到MinIO并获取img_id
5. **向量化**: 标题+内容融合向量
6. **存储插入**: 批量插入Elasticsearch/Infinity
7. **元数据更新**: 更新任务状态和文档统计

**关键特性**:
- 异步处理，支持并发控制
- 批量操作优化性能
- 向量融合结合标题和内容
- Mother Chunk机制支持子分隔符
- 支持任务取消和错误恢复
