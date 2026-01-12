# build_chunks 方法全流程分析

> 生成时间: 2025-01-11
> 文件位置: `rag/svr/task_executor.py`
> 方法位置: 第225-433行

## 一、方法签名与配置

```python
@timeout(60*80, 1)
async def build_chunks(task, progress_callback):
    """
    文档切块核心方法

    Args:
        task: 任务字典，包含文档信息、解析配置等
        progress_callback: 进度回调函数

    Returns:
        list[dict]: chunk列表，每个chunk包含文档片段及其元数据

    Raises:
        TaskCanceledException: 任务被取消时抛出
        Exception: 处理失败时抛出
    """
```

**关键配置**:
- **超时时间**: 80分钟（4800秒）
- **最大文件大小**: `settings.DOC_MAXIMUM_SIZE`
- **并发控制**: `chunk_limiter` (默认Semaphore=1)

---

## 二、业务逻辑概览

`build_chunks` 是文档切块的核心方法，负责将原始文档转换为结构化的chunk列表。整体流程如下：

```
build_chunks
│
├── 阶段1: 文件获取 (从MinIO)
├── 阶段2: 文档切块 (调用Parser)
├── 阶段3: 图片处理 (上传到MinIO)
├── 阶段4: 关键词提取 (可选)
├── 阶段5: 问题生成 (可选)
└── 阶段6: 内容标签 (可选)
```

---

## 三、执行流程详解

### 3.1 阶段1: 文件大小验证

```python
# 第227-230行
if task["size"] > settings.DOC_MAXIMUM_SIZE:
    set_progress(task["id"], prog=-1, msg="File size exceeds( <= %dMb )"
                 % (int(settings.DOC_MAXIMUM_SIZE / 1024 / 1024)))
    return []
```

**逻辑**:
- 检查文件大小是否超过限制
- 超过则标记任务失败并返回空列表
- 默认限制通常为128MB或更大（取决于配置）

### 3.2 阶段2: 从MinIO获取文件

```python
# 第232-250行
chunker = FACTORY[task["parser_id"].lower()]
try:
    st = timer()
    bucket, name = File2DocumentService.get_storage_address(doc_id=task["doc_id"])
    binary = await get_storage_binary(bucket, name)
    logging.info("From minio({}) {}/{}".format(timer() - st, task["location"], task["name"]))
except TimeoutError:
    progress_callback(-1, "Internal server error: Fetch file from minio timeout. Could you try it again.")
    logging.exception("Minio {}/{} got timeout: Fetch file from minio timeout.".format(task["location"], task["name"]))
    raise
except Exception as e:
    if re.search("(No such file|not found)", str(e)):
        progress_callback(-1, "Can not find file <%s> from minio. Could you try it again?" % task["name"])
    else:
        progress_callback(-1, "Get file from minio: %s" % str(e).replace("'", ""))
    logging.exception("Chunking {}/{} got exception".format(task["location"], task["name"]))
    raise
```

**关键点**:
1. **获取存储地址**: 通过 `File2DocumentService.get_storage_address()` 获取bucket和文件名
2. **异步获取**: `await get_storage_binary(bucket, name)` 异步从MinIO获取二进制内容
3. **超时处理**: 60秒超时（`@timeout(60)` 装饰器在 `get_storage_binary` 上）
4. **错误分类**:
   - `TimeoutError`: 文件获取超时
   - `No such file/not found`: 文件不存在
   - 其他异常: 通用错误处理

**MinIO存储结构**:
```
bucket (知识库ID)
└── name (文件路径，如: docs/abc123.pdf)
```

### 3.3 阶段3: 文档切块

```python
# 第252-272行
try:
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
    logging.info("Chunking({}) {}/{} done".format(timer() - st, task["location"], task["name"]))
except TaskCanceledException:
    raise
except Exception as e:
    progress_callback(-1, "Internal server error while chunking: %s" % str(e).replace("'", ""))
    logging.exception("Chunking {}/{} got exception".format(task["location"], task["name"]))
    raise
```

**关键点**:
1. **并发控制**: `async with chunk_limiter` 限制并发切块数量（默认1）
2. **线程池执行**: `asyncio.to_thread()` 将阻塞的切块操作放到线程池执行
3. **Parser选择**: `chunker = FACTORY[task["parser_id"].lower()]`

**Parser Factory 映射**:
```python
FACTORY = {
    "general": naive,      # 通用解析器
    "naive": naive,        # 简单解析
    "paper": paper,        # 论文解析
    "book": book,          # 书籍解析
    "presentation": presentation,  # PPT解析
    "manual": manual,      # 手册解析
    "laws": laws,          # 法律文档解析
    "qa": qa,              # 问答对解析
    "table": table,        # 表格解析
    "resume": resume,      # 简历解析
    "picture": picture,    # 图片解析
    "one": one,            # 单文档解析
    "audio": audio,        # 音频解析
    "email": email,        # 邮件解析
    "kg": naive,           # 知识图谱
    "tag": tag             # 标签解析
}
```

**chunk() 方法参数说明**:
| 参数 | 说明 |
|------|------|
| `name` | 文件名 |
| `binary` | 文件二进制内容 |
| `from_page` | 起始页码 |
| `to_page` | 结束页码 |
| `lang` | 文档语言 |
| `callback` | 进度回调函数 |
| `kb_id` | 知识库ID |
| `parser_config` | 解析器配置 |
| `tenant_id` | 租户ID |

**返回的 chunk 结构** (示例):
```python
{
    "content_with_weight": "文档内容...",
    "page_num_int": [1, 2, 3],
    "top_int": [100, 200, 300],
    "position_int": "位置信息",
    "image": "base64编码的图片",
    "table": "表格数据",
    # ... 其他元数据
}
```

### 3.4 阶段4: 图片处理

```python
# 第274-316行
docs = []
doc = {
    "doc_id": task["doc_id"],
    "kb_id": str(task["kb_id"])
}
if task["pagerank"]:
    doc[PAGERANK_FLD] = int(task["pagerank"])
st = timer()

@timeout(60)
async def upload_to_minio(document, chunk):
    try:
        d = copy.deepcopy(document)
        d.update(chunk)
        d["id"] = xxhash.xxh64(
            (chunk["content_with_weight"] + str(d["doc_id"])).encode("utf-8", "surrogatepass")
        ).hexdigest()
        d["create_time"] = str(datetime.now()).replace("T", " ")[:19]
        d["create_timestamp_flt"] = datetime.now().timestamp()
        if not d.get("image"):
            _ = d.pop("image", None)
            d["img_id"] = ""
            docs.append(d)
            return
        await image2id(d, partial(settings.STORAGE_IMPL.put, tenant_id=task["tenant_id"]),
                      d["id"], task["kb_id"])
        docs.append(d)
    except Exception:
        logging.exception("Saving image of chunk {}/{}/{} got exception".format(
            task["location"], task["name"], d["id"]))
        raise

tasks = []
for ck in cks:
    tasks.append(asyncio.create_task(upload_to_minio(doc, ck)))
try:
    await asyncio.gather(*tasks, return_exceptions=False)
except Exception as e:
    logging.error(f"MINIO PUT({task['name']}) got exception: {e}")
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    raise

el = timer() - st
logging.info("MINIO PUT({}) cost {:.3f} s".format(task["name"], el))
```

**关键点**:
1. **Chunk ID生成**: 使用 xxhash 哈希算法
   ```python
   d["id"] = xxhash.xxh64(
       (chunk["content_with_weight"] + str(d["doc_id"])).encode("utf-8", "surrogatepass")
   ).hexdigest()
   ```
   - 基于内容 + doc_id 生成唯一ID
   - 相同内容会生成相同ID（去重基础）

2. **图片处理流程**:
   - 如果chunk没有image字段，直接添加到docs
   - 如果有image，调用 `image2id()` 上传到MinIO
   - `image2id()` 会:
     - 解码base64图片
     - 上传到MinIO
     - 将返回的图片ID存入 `d["img_id"]`
     - 从chunk中移除原始图片数据

3. **并发上传**: 使用 `asyncio.gather()` 并发上传所有chunk
4. **超时控制**: 每个上传任务60秒超时
5. **错误回滚**: 失败时取消所有任务并抛出异常

### 3.5 阶段5: 自动关键词提取 (可选)

```python
# 第318-344行
if task["parser_config"].get("auto_keywords", 0):
    st = timer()
    progress_callback(msg="Start to generate keywords for every chunk ...")
    chat_mdl = LLMBundle(task["tenant_id"], LLMType.CHAT,
                        llm_name=task["llm_id"], lang=task["language"])

    async def doc_keyword_extraction(chat_mdl, d, topn):
        cached = get_llm_cache(chat_mdl.llm_name, d["content_with_weight"],
                              "keywords", {"topn": topn})
        if not cached:
            async with chat_limiter:
                cached = await keyword_extraction(chat_mdl, d["content_with_weight"], topn)
            set_llm_cache(chat_mdl.llm_name, d["content_with_weight"],
                         cached, "keywords", {"topn": topn})
        if cached:
            d["important_kwd"] = cached.split(",")
            d["important_tks"] = rag_tokenizer.tokenize(" ".join(d["important_kwd"]))
        return

    tasks = []
    for d in docs:
        tasks.append(asyncio.create_task(
            doc_keyword_extraction(chat_mdl, d, task["parser_config"]["auto_keywords"])
        ))
    try:
        await asyncio.gather(*tasks, return_exceptions=False)
    except Exception as e:
        logging.error("Error in doc_keyword_extraction: {}".format(e))
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    progress_callback(msg="Keywords generation {} chunks completed in {:.2f}s".format(
        len(docs), timer() - st))
```

**关键点**:
1. **触发条件**: `task["parser_config"]["auto_keywords"] > 0`
2. **LLM调用**: 使用Chat模型提取关键词
3. **缓存机制**:
   - 先从缓存读取: `get_llm_cache()`
   - 缓存未命中时调用LLM
   - 结果写入缓存: `set_llm_cache()`
4. **并发控制**: `chat_limiter` 限制并发LLM调用
5. **输出字段**:
   - `important_kwd`: 关键词列表 (数组)
   - `important_tks`: 关键词token列表 (分词结果)

**缓存Key结构**:
```
llm_name + content + "keywords" + {topn: N}
```

### 3.6 阶段6: 自动问题生成 (可选)

```python
# 第346-371行
if task["parser_config"].get("auto_questions", 0):
    st = timer()
    progress_callback(msg="Start to generate questions for every chunk ...")
    chat_mdl = LLMBundle(task["tenant_id"], LLMType.CHAT,
                        llm_name=task["llm_id"], lang=task["language"])

    async def doc_question_proposal(chat_mdl, d, topn):
        cached = get_llm_cache(chat_mdl.llm_name, d["content_with_weight"],
                              "question", {"topn": topn})
        if not cached:
            async with chat_limiter:
                cached = await question_proposal(chat_mdl, d["content_with_weight"], topn)
            set_llm_cache(chat_mdl.llm_name, d["content_with_weight"],
                         cached, "question", {"topn": topn})
        if cached:
            d["question_kwd"] = cached.split("\n")
            d["question_tks"] = rag_tokenizer.tokenize("\n".join(d["question_kwd"]))

    tasks = []
    for d in docs:
        tasks.append(asyncio.create_task(
            doc_question_proposal(chat_mdl, d, task["parser_config"]["auto_questions"])
        ))
    try:
        await asyncio.gather(*tasks, return_exceptions=False)
    except Exception as e:
        logging.error("Error in doc_question_proposal", exc_info=e)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    progress_callback(msg="Question generation {} chunks completed in {:.2f}s".format(
        len(docs), timer() - st))
```

**关键点**:
1. **触发条件**: `task["parser_config"]["auto_questions"] > 0`
2. **功能**: 为每个chunk生成相关问题
3. **缓存机制**: 同关键词提取
4. **输出字段**:
   - `question_kwd`: 问题列表 (按\n分割)
   - `question_tks`: 问题token列表 (分词结果)

### 3.7 阶段7: 内容标签 (可选)

```python
# 第373-431行
if task["kb_parser_config"].get("tag_kb_ids", []):
    progress_callback(msg="Start to tag for every chunk ...")
    kb_ids = task["kb_parser_config"]["tag_kb_ids"]
    tenant_id = task["tenant_id"]
    topn_tags = task["kb_parser_config"].get("topn_tags", 3)
    S = 1000
    st = timer()
    examples = []
    all_tags = get_tags_from_cache(kb_ids)
    if not all_tags:
        all_tags = settings.retriever.all_tags_in_portion(tenant_id, kb_ids, S)
        set_tags_to_cache(kb_ids, all_tags)
    else:
        all_tags = json.loads(all_tags)

    chat_mdl = LLMBundle(task["tenant_id"], LLMType.CHAT,
                        llm_name=task["llm_id"], lang=task["language"])

    docs_to_tag = []
    for d in docs:
        task_canceled = has_canceled(task["id"])
        if task_canceled:
            progress_callback(-1, msg="Task has been canceled.")
            return None
        if settings.retriever.tag_content(tenant_id, kb_ids, d, all_tags,
                                         topn_tags=topn_tags, S=S) \
           and len(d[TAG_FLD]) > 0:
            examples.append({"content": d["content_with_weight"], TAG_FLD: d[TAG_FLD]})
        else:
            docs_to_tag.append(d)

    async def doc_content_tagging(chat_mdl, d, topn_tags):
        cached = get_llm_cache(chat_mdl.llm_name, d["content_with_weight"],
                              all_tags, {"topn": topn_tags})
        if not cached:
            picked_examples = random.choices(examples, k=2) if len(examples) > 2 else examples
            if not picked_examples:
                picked_examples.append({"content": "This is an example",
                                       TAG_FLD: {'example': 1}})
            async with chat_limiter:
                cached = await content_tagging(
                    chat_mdl,
                    d["content_with_weight"],
                    all_tags,
                    picked_examples,
                    topn_tags,
                )
            if cached:
                cached = json.dumps(cached)
        if cached:
            set_llm_cache(chat_mdl.llm_name, d["content_with_weight"],
                         cached, all_tags, {"topn": topn_tags})
            d[TAG_FLD] = json.loads(cached)

    tasks = []
    for d in docs_to_tag:
        tasks.append(asyncio.create_task(doc_content_tagging(chat_mdl, d, topn_tags)))
    try:
        await asyncio.gather(*tasks, return_exceptions=False)
    except Exception as e:
        logging.error("Error tagging docs: {}".format(e))
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    progress_callback(msg="Tagging {} chunks completed in {:.2f}s".format(
        len(docs), timer() - st))
```

**关键点**:
1. **触发条件**: `task["kb_parser_config"]["tag_kb_ids"]` 非空
2. **功能**: 为chunk打标签（基于参考知识库的标签体系）
3. **两阶段处理**:
   - **阶段1**: 基于检索的自动标签
     - 从参考知识库获取所有标签: `all_tags_in_portion()`
     - 尝试自动匹配: `tag_content()`
     - 成功的作为示例

   - **阶段2**: LLM生成标签
     - 对于无法自动匹配的chunk
     - 使用few-shot prompting
     - 随机选择2个示例

4. **输出字段**: `TAG_FLD` (值为标签字典)

**tag_content() 逻辑**:
```python
# 基于向量检索的标签匹配
# 如果chunk与某个标签向量相似度高，自动打标签
if settings.retriever.tag_content(tenant_id, kb_ids, d, all_tags,
                                  topn_tags=topn_tags, S=S) \
   and len(d[TAG_FLD]) > 0:
    examples.append({"content": d["content_with_weight"], TAG_FLD: d[TAG_FLD]})
else:
    docs_to_tag.append(d)
```

---

## 四、数据结构详解

### 4.1 输入: task 参数结构

```python
{
    "id": "task_id",
    "doc_id": "document_id",
    "kb_id": "knowledge_base_id",
    "name": "document.pdf",
    "location": "storage_location",
    "size": 1024000,
    "from_page": 0,
    "to_page": -1,
    "language": "Chinese",
    "llm_id": "model_name",
    "parser_id": "naive",
    "parser_config": {
        "auto_keywords": 5,      # 提取关键词数量
        "auto_questions": 3,     # 生成问题数量
        "chunk_token_num": 512,  # chunk大小
        "delimiter": "\\n!?。"   # 分隔符
    },
    "kb_parser_config": {
        "tag_kb_ids": ["kb1", "kb2"],  # 参考知识库ID列表
        "topn_tags": 3                 # 标签数量
    },
    "tenant_id": "tenant_id",
    "pagerank": 1
}
```

### 4.2 输出: docs 结构

```python
[
    {
        "id": "chunk_id",                    # xxhash生成的唯一ID
        "doc_id": "document_id",
        "kb_id": "knowledge_base_id",
        "content_with_weight": "文本内容",
        "page_num_int": [1, 2],              # 页码列表
        "top_int": [100, 200],               # 位置列表
        "position_int": "位置信息",
        "create_time": "2025-01-11 10:00:00",
        "create_timestamp_flt": 1704950400.0,
        "img_id": "image_id",                # MinIO图片ID

        # 以下字段可选:
        "important_kwd": ["关键词1", "关键词2"],  # auto_keywords生成
        "important_tks": ["token1", "token2"],   # 关键词分词
        "question_kwd": ["问题1", "问题2"],       # auto_questions生成
        "question_tks": ["token1", "token2"],    # 问题分词
        "tags": {"tag1": 0.9, "tag2": 0.8},      # content_tagging生成
        "_position_int": [{"page_num": 1, ...}]  # 位置信息(如果有)
    },
    # ... 更多chunks
]
```

---

## 五、关键技术点

### 5.1 异步并发控制

```python
# 全局定义
MAX_CONCURRENT_CHUNK_BUILDERS = int(os.environ.get('MAX_CONCURRENT_CHUNK_BUILDERS', "1"))
chunk_limiter = asyncio.Semaphore(MAX_CONCURRENT_CHUNK_BUILDERS)

# 使用
async with chunk_limiter:
    cks = await asyncio.to_thread(chunker.chunk, ...)
```

**作用**: 限制同时执行的切块操作数量，防止资源耗尽

### 5.2 异步转同步执行

```python
# 将同步的chunk方法放到线程池执行
cks = await asyncio.to_thread(
    chunker.chunk,
    task["name"],
    binary=binary,
    ...
)
```

**原因**: 各种parser的chunk()方法是同步的，放到线程池避免阻塞事件循环

### 5.3 哈希去重

```python
import xxhash

d["id"] = xxhash.xxh64(
    (chunk["content_with_weight"] + str(d["doc_id"])).encode("utf-8", "surrogatepass")
).hexdigest()
```

**特点**:
- xxhash: 快速非加密哈希算法
- 基于内容生成ID: 相同内容生成相同ID
- 支持去重: 相同chunk只存储一次

### 5.4 LLM缓存机制

```python
# 读取缓存
cached = get_llm_cache(llm_name, content, cache_type, params)

# 写入缓存
set_llm_cache(llm_name, content, result, cache_type, params)
```

**缓存结构** (Redis):
```
Key: llm_cache:{llm_name}:{xxhash(content)}:{cache_type}:{params}
Value: result
TTL: 通常7天或更长
```

**优势**:
- 减少LLM调用成本
- 提升响应速度
- 相同输入返回相同结果

### 5.5 Few-Shot Learning

```python
# 内容标签中使用
picked_examples = random.choices(examples, k=2) if len(examples) > 2 else examples
if not picked_examples:
    picked_examples.append({"content": "This is an example", TAG_FLD: {'example': 1}})

cached = await content_tagging(
    chat_mdl,
    d["content_with_weight"],
    all_tags,
    picked_examples,  # 示例
    topn_tags,
)
```

**作用**: 提供示例提升LLM输出质量

### 5.6 超时控制

```python
@timeout(60*80, 1)  # 方法级别: 80分钟
async def build_chunks(task, progress_callback):
    ...

@timeout(60)  # 函数级别: 60秒
async def upload_to_minio(document, chunk):
    ...
```

**多层保护**:
- 方法级别: 防止整体超时
- 函数级别: 防止单个操作超时

### 5.7 错误处理与回滚

```python
try:
    await asyncio.gather(*tasks, return_exceptions=False)
except Exception as e:
    # 取消所有任务
    for t in tasks:
        t.cancel()
    # 等待所有任务完成/取消
    await asyncio.gather(*tasks, return_exceptions=True)
    # 抛出异常
    raise
```

**模式**: 全部成功或全部失败 (All-or-Nothing)

---

## 六、调用关系图

```
build_chunks (入口)
│
├── File2DocumentService.get_storage_address() ──────> 获取MinIO存储地址
│
├── get_storage_binary() ─────────────────────────────> 从MinIO下载文件
│
├── FACTORY[parser_id].chunk() ───────────────────────> 执行切块
│   ├── naive.chunk()
│   ├── paper.chunk()
│   ├── book.chunk()
│   ├── presentation.chunk()
│   ├── laws.chunk()
│   ├── qa.chunk()
│   ├── table.chunk()
│   └── ... (其他parser)
│
├── upload_to_minio() [并发] ─────────────────────────> 处理图片
│   └── image2id() ───────────────────────────────────> 上传图片到MinIO
│
├── doc_keyword_extraction() [并发] ──────────────────> 提取关键词
│   ├── get_llm_cache() ──────────────────────────────> 读取缓存
│   ├── keyword_extraction() ─────────────────────────> LLM调用
│   │   └── chat_limiter (并发控制)
│   ├── set_llm_cache() ──────────────────────────────> 写入缓存
│   └── rag_tokenizer.tokenize() ─────────────────────> 分词
│
├── doc_question_proposal() [并发] ────────────────────> 生成问题
│   ├── get_llm_cache()
│   ├── question_proposal() ──────────────────────────> LLM调用
│   │   └── chat_limiter
│   ├── set_llm_cache()
│   └── rag_tokenizer.tokenize()
│
└── doc_content_tagging() [并发] ─────────────────────> 内容标签
    ├── get_tags_from_cache() ────────────────────────> 获取标签缓存
    ├── retriever.all_tags_in_portion() ──────────────> 获取所有标签
    ├── retriever.tag_content() ──────────────────────> 自动标签匹配
    ├── content_tagging() ────────────────────────────> LLM打标签
    │   └── chat_limiter
    └── set_llm_cache()
```

---

## 七、性能优化策略

### 7.1 并发处理

```python
# 关键词提取 - 并发
tasks = []
for d in docs:
    tasks.append(asyncio.create_task(doc_keyword_extraction(chat_mdl, d, topn)))
await asyncio.gather(*tasks, return_exceptions=False)
```

**效果**: N个chunk并发处理，时间从 O(N) 降至 O(1)

### 7.2 缓存策略

| 缓存类型 | Key | Value | 使用场景 |
|---------|-----|-------|---------|
| LLM缓存 | `{llm}:{content}:{type}:{params}` | LLM输出 | 关键词、问题、标签 |
| 标签缓存 | `tags:{kb_ids}` | 标签字典 | 知识库标签体系 |

### 7.3 资源限制

```python
MAX_CONCURRENT_CHUNK_BUILDERS = 1  # 切块并发数
chat_limiter = asyncio.Semaphore(N)  # LLM调用并发数
```

**目的**: 防止资源耗尽，保证系统稳定性

### 7.4 批处理建议

当前实现中，MinIO上传和LLM调用都已实现并发，但在parser层面可以进一步优化：

```python
# 建议增加批量embedding接口
async def batch_embed_texts(texts, batch_size=32):
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        yield await embed_model.encode(batch)
```

---

## 八、常见问题与解决方案

### 8.1 文件过大问题

**问题**: 文件超过 `DOC_MAXIMUM_SIZE` 限制

**解决方案**:
```python
# 配置调整
export DOC_MAXIMUM_SIZE=209715200  # 200MB

# 或分片处理
task["from_page"] = 0
task["to_page"] = 50  # 先处理前50页
```

### 8.2 切块超时问题

**问题**: 复杂文档切块超过80分钟

**解决方案**:
1. 调整超时时间: `@timeout(60*120, 1)`
2. 简化parser配置: 减少 `chunk_token_num`
3. 分页处理: 分多次处理不同页面范围

### 8.3 LLM调用失败

**问题**: 关键词/问题提取时LLM调用失败

**解决方案**:
```python
# 已有重试机制: 缓存未命中时重新调用
# 可以增加重试次数
if not cached:
    for attempt in range(3):
        try:
            cached = await keyword_extraction(...)
            break
        except Exception as e:
            if attempt == 2:
                raise
```

### 8.4 图片处理失败

**问题**: 图片上传MinIO失败

**解决方案**:
```python
# 当前已有: All-or-Nothing模式
# 可以增加容错: 跳过失败的图片
if not d.get("image"):
    d["img_id"] = ""
else:
    try:
        await image2id(...)
    except Exception:
        d["img_id"] = ""  # 失败时设为空
```

---

## 九、配置参数总览

| 参数 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `DOC_MAXIMUM_SIZE` | settings | 128MB | 最大文件大小 |
| `MAX_CONCURRENT_CHUNK_BUILDERS` | 环境变量 | 1 | 切块并发数 |
| `auto_keywords` | parser_config | 0 | 关键词数量 |
| `auto_questions` | parser_config | 0 | 问题数量 |
| `tag_kb_ids` | kb_parser_config | [] | 参考知识库ID |
| `topn_tags` | kb_parser_config | 3 | 标签数量 |

---

## 十、总结

`build_chunks` 方法是 RAGFlow 文档处理的核心，具有以下特点：

1. **模块化设计**: 通过 Factory 模式支持多种解析器
2. **异步并发**: 全流程异步化，关键步骤并发执行
3. **容错机制**: 超时控制、错误回滚、任务取消检测
4. **智能增强**: LLM驱动的关键词、问题、标签提取
5. **性能优化**: 缓存机制、资源限制、批量处理
6. **可扩展性**: 易于添加新的parser和处理步骤

**核心流程**: 文件获取 → Parser切块 → 图片处理 → 可选增强(keywords/questions/tags) → 返回chunks

**关键依赖**:
- 存储: MinIO (`settings.STORAGE_IMPL`)
- 模型: LLM (`LLMBundle`)
- 缓存: Redis (`get_llm_cache`, `set_llm_cache`)
- 检索: Elasticsearch/Infinity (`settings.retriever`)
- 分词: `rag_tokenizer`
