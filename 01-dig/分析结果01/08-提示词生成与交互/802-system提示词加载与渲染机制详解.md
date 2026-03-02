# 801-system提示词加载与渲染机制详解

## 概述

`prompt_config` 中的 `system` 字段是 RAG 系统的核心系统提示词，负责定义 LLM 的角色、行为规范和知识使用方式。本文档详细分析 `system` 提示词的加载、存储、渲染流程。

**源码位置**: [api/db/db_models.py:853-856](../../api/db/db_models.py#L853-L856)

---

## 一、system 字段定义与默认值

### 1.1 数据库模型定义

```python
# api/db/db_models.py:842-856
class Dialog(DataBaseModel):
    # ... 其他字段 ...
    llm_setting = JSONField(null=False, default={...})
    prompt_type = CharField(max_length=16, null=False, default="simple", ...)
    prompt_config = JSONField(
        null=False,
        default={
            "system": "",
            "prologue": "Hi! I'm your assistant. What can I do for you?",
            "parameters": [],
            "empty_response": "Sorry! No relevant content was found in the knowledge base!"
        },
    )
```

**设计特点**:
- **JSONField 类型**: 使用 `JSONField` 存储，支持复杂嵌套结构
- **默认空字符串**: `"system": ""` - 允许空提示词，由前端填充默认值
- **完整性**: 包含 `prologue`（开场白）、`parameters`（变量定义）、`empty_response`（空响应）

### 1.2 前端默认值定义

```typescript
// web/src/locales/zh.ts:561-564
systemInitialValue: `你是一个智能助手，请总结知识库的内容来回答问题，请列举知识库中的数据详细回答。当所有知识库内容都与问题无关时，你的回答必须包括"知识库中未找到您要的答案！"这句话。回答需要考虑聊天历史。
        以下是知识库：
        {knowledge}
        以上是知识库。`
```

**多语言支持**:
- 中文: `web/src/locales/zh.ts`
- 英文: `web/src/locales/en.ts`
- 其他: `de.ts`, `es.ts`, `fr.ts`, `ja.ts`, `pt-br.ts`, `ru.ts`, `vi.ts`, `zh-traditional.ts`

---

## 二、system 提示词加载流程

### 2.1 完整加载链路

```
┌─────────────────────────────────────────────────────────────────┐
│              system 提示词加载流程                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐          │
│  │  创建对话   │ -> │  初始化前端  │ -> │  设置默认值   │          │
│  └─────────────┘    └─────────────┘    └─────────────┘          │
│           │                      │                      │            │
│           v                      v                      v            │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐          │
│  │ 初始数据结构 │ -> │  国际化加载  │ -> │  用户编辑     │          │
│  └─────────────┘    └─────────────┘    └─────────────┘          │
│           │                      │                      │            │
│           v                      v                      v            │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐          │
│  │ 提交到API   │ -> │  数据库存储  │ -> │  运行时加载   │          │
│  └─────────────┘    └─────────────┘    └─────────────┘          │
│                                                                     │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 前端初始化流程

```typescript
// web/src/pages/next-chats/hooks/use-rename-chat.ts:20-46
const InitialData = useMemo(
  () => ({
    name: '',
    icon: '',
    language: 'English',
    description: '',
    prompt_config: {
      empty_response: '',
      prologue: t('chat.setAnOpenerInitial'),
      quote: true,
      keyword: false,
      tts: false,
      system: t('chat.systemInitialValue'),  // ← 从多语言文件加载默认 system 提示词
      refine_multiturn: false,
      use_kg: false,
      reasoning: false,
      parameters: [{ key: 'knowledge', optional: false }],
      toc_enhance: false,
    },
    llm_id: tenantInfo.data.llm_id,
    llm_setting: {},
    similarity_threshold: 0.2,
    vector_similarity_weight: 0.3,
    top_n: 8,
  }),
  [t, tenantInfo.data.llm_id],
);
```

**关键点**:
1. **动态加载**: `t('chat.systemInitialValue')` 通过 i18n 动态获取对应语言的默认值
2. **依赖缓存**: 依赖项 `[t, tenantInfo.data.llm_id]` 确保语言和 LLM 配置变化时重新计算
3. **完整结构**: 包含所有 `prompt_config` 必需字段

### 2.3 API 接收与存储

```python
# api/apps/dialog_app.py:64, 97-98
prompt_config = req["prompt_config"]  # 从请求中提取

# 新建对话
dia = {
    # ... 其他字段 ...
    "prompt_config": prompt_config,  # ← 完整存储到数据库
    # ...
}
DialogService.save(**dia)
```

**验证逻辑**:

```python
# api/apps/dialog_app.py:66-75
if not is_create:
    # 检查 {knowledge} 变量是否必需
    if not req.get("kb_ids", []) and "{knowledge}" in prompt_config['system']:
        return get_data_error_result(
            message="Please remove `{knowledge}` in system prompt since no knowledge base / Tavily used here."
        )

    # 检查所有必需参数是否使用
    for p in prompt_config["parameters"]:
        if p["optional"]:
            continue
        if prompt_config["system"].find("{%s}" % p["key"]) < 0:
            return get_data_error_result(
                message="Parameter '{}' is not used".format(p["key"])
            )
```

**验证规则**:
1. **知识库检查**: 无知识库时不允许 `{knowledge}` 变量
2. **参数使用检查**: 所有 `optional=false` 的参数必须在 `system` 中使用

---

## 三、运行时渲染流程

### 3.1 渲染入口

```python
# api/db/services/dialog_service.py:493-494
# 组装系统提示词
msg = [{"role": "system", "content": prompt_config["system"].format(**kwargs)+attachments_}]
```

**渲染时机**: 阶段5 - 提示词组装 [dialog_service.py:461-514](../dialog_service.py#L461-L514)

### 3.2 变量传递链路

```
┌─────────────────────────────────────────────────────────────┐
│                        变量传递链路                            │
├─────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────┐    ┌─────────────────┐                      │
│  │ kwargs 构建      │ -> │  模板渲染       │                      │
│  └─────────────────┘    └─────────────────┘                      │
│           │                      │                                │
│           v                      v                                │
│  ┌─────────────────┐    ┌─────────────────┐                      │
│  │ 知识注入         │ -> │  模板变量替换   │                      │
│  └─────────────────┘    └─────────────────┘                      │
│           │                      │                                │
│           v                      v                                │
│  ┌─────────────────┐    ┌─────────────────┐                      │
│  │ 最终提示词       │ <- │  附件追加       │                      │
│  └─────────────────┘    └─────────────────┘                      │
│                                                                      │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 变量构建详解

```python
# api/db/services/dialog_service.py:456-494
# 步骤1: 知识组装
knowledges = kb_prompt(kbinfos, max_tokens)

# 步骤2: 格式化为字符串
kwargs["knowledge"] = "\n------\n" + "\n\n------\n\n".join(knowledges)

# 步骤3: 获取附件内容（如果有）
if "files" in messages[-1]:
    attachments_ = "\n\n".join(FileService.get_files(messages[-1]["files"]))

# 步骤4: 渲染系统提示词
system_prompt = prompt_config["system"].format(**kwargs) + attachments_
msg = [{"role": "system", "content": system_prompt}]
```

**kwargs 常见变量**:

| 变量名 | 来源 | 格式 | 示例 |
|--------|------|------|------|
| `knowledge` | 检索结果 | 格式化知识块列表 | `"\n------\n\nID: 0\n├── ..."` |
| `question` | 用户输入 | 纯文本 | `"如何使用产品？"` |
| `quote` | 配置参数 | 布尔值或字符串 | `True` 或 `"Please cite sources"` |
| 自定义变量 | 用户定义 | 任意类型 | 由 `prompt_config["parameters"]` 定义 |

---

## 四、模板变量机制

### 4.1 variables 参数定义

```python
# 示例 prompt_config
prompt_config = {
    "system": "你是一个{role}，请根据{knowledge}回答问题。",
    "parameters": [
        {"key": "role", "optional": False},
        {"key": "knowledge", "optional": False}
    ]
}
```

**parameters 结构**:

```typescript
interface PromptParameter {
    key: string;        // 变量名，对应模板中的 {key}
    optional: boolean;   // 是否可选
    // 可能还有其他字段（根据前端实现）
}
```

### 4.2 变量验证机制

```python
# api/apps/dialog_app.py:69-75
for p in prompt_config["parameters"]:
    if p["optional"]:
        continue
    if prompt_config["system"].find("{%s}" % p["key"]) < 0:
        return get_data_error_result(
            message="Parameter '{}' is not used".format(p["key"])
        )
```

**验证逻辑**:
1. 遍历所有 `optional=false` 的参数
2. 检查 `system` 中是否包含 `{key}` 占位符
3. 未找到则返回错误

**示例**:

```python
# 场景1: 通过验证
prompt_config = {
    "system": "请根据{knowledge}回答",  # 包含 {knowledge}
    "parameters": [{"key": "knowledge", "optional": False}]
}
# ✓ 通过

# 场景2: 验证失败
prompt_config = {
    "system": "你是一个助手",  # 不包含 {knowledge}
    "parameters": [{"key": "knowledge", "optional": False}]
}
# ✗ 错误: "Parameter 'knowledge' is not used"
```

---

## 五、调试时的 prompt_config 解析

### 5.1 实际值分析

```python
{
    'quote': True,
    'keyword': False,
    'tts': False,
    'empty_response': '',
    'prologue': '你好！ 我是你的助理，有什么可以帮到你的吗？',
    'system': '''你是一个智能助手，请总结知识库的内容来回答问题，请列举知识库中的数据详细回答。当所有知识库内容都与问题无关时，你的回答必须包括"知识库中未找到您要的答案！"这句话。回答需要考虑聊天历史。
        以下是知识库：
        {knowledge}
        以上是知识库。''',
    'refine_multiturn': False,
    'use_kg': False,
    'parameters': [{...}],
    'reasoning': False,
    'cross_languages': [],
    'toc_enhance': False
}
```

### 5.2 字段功能说明

| 字段 | 类型 | 作用 | 默认值 |
|------|------|------|--------|
| `system` | str | LLM 系统提示词 | 多语言默认值 |
| `prologue` | str | 对话开场白 | "Hi! I'm your assistant..." |
| `quote` | bool | 是否启用引用标注 | `True` |
| `keyword` | bool | 是否提取关键词 | `False` |
| `tts` | bool | 是否启用文字转语音 | `False` |
| `empty_response` | str | 空响应时的回复 | "Sorry! No relevant content..." |
| `refine_multiturn` | bool | 是否多轮对话精炼 | `False` |
| `use_kg` | bool | 是否使用知识图谱 | `False` |
| `reasoning` | bool | 是否使用 Agentic RAG | `False` |
| `cross_languages` | list | 跨语言配置 | `[]` |
| `toc_enhance` | bool | 是否启用 TOC 增强检索 | `False` |
| `parameters` | list | 模板变量定义 | `[{"key": "knowledge", "optional": false}]` |

---

## 六、多语言支持机制

### 6.1 国际化目录结构

```
web/src/locales/
├── en.ts              # 英文
├── zh.ts              # 简体中文
├── zh-traditional.ts  # 繁体中文
├── ja.ts              # 日文
├── de.ts              # 德文
├── es.ts              # 西班牙文
├── fr.ts              # 法文
├── pt-br.ts           # 巴西葡萄牙语
├── ru.ts              # 俄文
├── vi.ts              # 越南语
└── id.ts              # 印尼语
```

### 6.2 默认值对比

**中文版本** (zh.ts):
```
你是一个智能助手，请总结知识库的内容来回答问题，请列举知识库中的数据详细回答。当所有知识库内容都与问题无关时，你的回答必须包括"知识库中未找到您要的答案！"这句话。回答需要考虑聊天历史。
以下是知识库：
{knowledge}
以上是知识库。
```

**英文版本** (en.ts):
```
You are an intelligent assistant. Please summarize the content of the knowledge base to answer the question, and list the data in the knowledge base in detail. When all knowledge base content is irrelevant to the question, your answer must include the sentence "The answer was not found in the knowledge base!" Answer the question considering the chat history.
Below is the knowledge base:
{knowledge}
Above is the knowledge base.
```

---

## 七、最佳实践与注意事项

### 7.1 变量命名规范

| 变量 | 用途 | 注意事项 |
|------|------|----------|
| `{knowledge}` | 检索到的知识内容 | 最常用，建议保留 |
| `{question}` | 用户问题 | 用于明确上下文 |
| 自定义变量 | 特定场景参数 | 需在 `parameters` 中定义 |

### 7.2 提示词设计建议

1. **明确角色定位**:
   ```
   你是一个专业的技术支持助手...
   ```

2. **指定输出格式**:
   ```
   请按以下格式回答：
   ## 答案
   ...

   ## 参考资料
   [ID:X] 文档名称
   ```

3. **约束引用行为**:
   ```
   回答时必须使用 [ID:X] 格式引用知识来源。
   不要编造未提供的信息。
   ```

4. **处理无结果场景**:
   ```
   当所有知识库内容都与问题无关时，
   你的回答必须包括"知识库中未找到您要的答案！"这句话。
   ```

### 7.3 常见错误

**错误1: 未使用必需变量**
```python
# 错误示例
prompt_config = {
    "system": "你是一个助手",  # 缺少 {knowledge}
    "parameters": [{"key": "knowledge", "optional": False}]
}

# API 返回错误
# "Parameter 'knowledge' is not used"
```

**解决方案**:
```python
# 正确示例
prompt_config = {
    "system": "你是知识库助手，根据以下知识回答：\n{knowledge}",
    "parameters": [{"key": "knowledge", "optional": False}]
}
```

**错误2: 无知识库时使用 {knowledge}**
```python
# 错误场景
kb_ids = []  # 空知识库
prompt_config["system"] = "请根据{knowledge}回答"  # 包含 {knowledge}

# API 返回错误
# "Please remove `{knowledge}` in system prompt since no knowledge base / Tavily used here."
```

---

## 八、扩展机制

### 8.1 Jinja2 模板系统

虽然当前使用 Python 内置的 `.format()` 方法，但系统已集成 Jinja2：

```python
# rag/prompts/generator.py:181
PROMPT_JINJA_ENV = jinja2.Environment(
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True
)
```

**Jinja2 支持的高级特性** (当前未在 system 提示词中使用):
- 条件判断: `{% if knowledge %}...{% endif %}`
- 循环: `{% for chunk in knowledges %}...{% endfor %}`
- 过滤器: `{{ knowledge|truncate(1000) }}`

### 8.2 动态提示词生成

其他模块已使用 Jinja2：

```python
# rag/prompts/generator.py:264-270
template = PROMPT_JINJA_ENV.from_string(FULL_QUESTION_PROMPT_TEMPLATE)
rendered_prompt = template.render(
    today=today,
    yesterday=yesterday,
    tomorrow=tomorrow,
    conversation=conversation,
    language=language,
)
```

---

## 九、总结

`system` 提示词的加载与渲染是 RAG 系统提示词工程的核心环节，其流程可概括为：

| 阶段 | 位置 | 关键操作 |
|------|------|----------|
| **默认值定义** | 前端 locales 文件 | 多语言支持 |
| **初始化** | use-rename-chat.ts | i18n 动态加载 |
| **用户编辑** | 对话设置界面 | 支持变量插入 |
| **API 验证** | dialog_app.py | 参数使用检查 |
| **数据库存储** | Dialog.prompt_config | JSONField 存储 |
| **运行时加载** | dialog_service.py | 从数据库读取 |
| **变量注入** | kwargs 构建 | 知识、问题等 |
| **模板渲染** | .format() 或 Jinja2 | 变量替换 |
| **LLM 调用** | async_chat_streamly | 最终提示词 |

**设计亮点**:
1. **国际化默认值**: 支持多语言开箱即用
2. **灵活变量系统**: parameters + 验证机制
3. **存储与渲染分离**: 模板存储，运行时渲染
4. **扩展性**: 集成 Jinja2，支持高级模板特性

---

## 十、相关文档索引

- [723-提示词组装逻辑业务流程详解](../07-查询与检索流程/723-提示词组装逻辑业务流程详解.md)
- [703-对话服务主流程详解](../07-查询与检索流程/703-对话服务主流程详解.md)
- [720-kb_prompt知识组装流程业务逻辑详解](../07-查询与检索流程/720-kb_prompt知识组装流程业务逻辑详解.md)

---

**文档版本**: v1.0
**最后更新**: 2025-02-11
**作者**: Claude Code Analysis
