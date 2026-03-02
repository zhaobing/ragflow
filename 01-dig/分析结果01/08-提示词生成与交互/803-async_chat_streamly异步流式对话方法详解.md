# async_chat_streamly 异步流式对话方法详解

## 一、方法概述

`async_chat_streamly` 是 `LLMBundle` 类中的核心方法之一，位于 `api/db/services/llm_service.py:402-443`。该方法用于实现**异步流式对话**功能，是 RAGFlow 系统中处理大语言模型流式响应的关键接口。

### 方法签名
```python
async def async_chat_streamly(self, system: str, history: list, gen_conf: dict = {}, **kwargs)
```

## 二、方法参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `system` | str | 系统提示词，用于设置模型的角色和行为准则 |
| `history` | list | 对话历史记录，包含用户和助手的历史消息 |
| `gen_conf` | dict | 生成配置参数，如 temperature、max_tokens 等 |
| `**kwargs` | dict | 额外的模型特定参数 |

## 三、核心业务流程

### 3.1 流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                    async_chat_streamly                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────────┐   │
│  │  1. 初始化  │ -> │ 2. 选择流式   │ -> │ 3. Langfuse追踪  │   │
│  │    变量     │    │    函数      │    │    (可选)        │   │
│  └─────────────┘    └──────────────┘    └──────────────────┘   │
│                            │                                     │
│                            v                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 4. 异步流式处理循环                                        │  │
│  │   ┌─────────────────────────────────────────────────┐    │  │
│  │   │ a) 调用底层模型的流式生成方法                     │    │  │
│  │   │ b) 处理流式返回的文本片段                         │    │  │
│  │   │ c) 处理推理标签 (<think>)                         │    │  │
│  │   │ d) 过滤工具调用内容 (非详细模式)                  │    │  │
│  │   │ e) 累积完整响应并 yield                          │    │  │
│  │   └─────────────────────────────────────────────────┘    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                            │                                     │
│                            v                                     │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────────┐   │
│  │ 5. 记录Token │ -> │ 6. 更新追踪   │ -> │ 7. 返回结果      │   │
│  │    使用量   │    │    数据       │    │                 │   │
│  └─────────────┘    └──────────────┘    └──────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 四、详细代码分析

### 4.1 初始化阶段 (402-404行)

```python
total_tokens = 0
ans = ""
```

- **total_tokens**: 记录本次对话消耗的总 token 数
- **ans**: 累积完整的响应文本

### 4.2 流式函数选择 (405-410行)

```python
if self.is_tools and getattr(self.mdl, "is_tools", False) and hasattr(self.mdl, "async_chat_streamly_with_tools"):
    stream_fn = getattr(self.mdl, "async_chat_streamly_with_tools", None)
elif hasattr(self.mdl, "async_chat_streamly"):
    stream_fn = getattr(self.mdl, "async_chat_streamly", None)
else:
    raise RuntimeError(f"Model {self.mdl} does not implement async_chat or async_chat_with_tools")
```

**选择逻辑:**

| 条件 | 选择的函数 |
|------|-----------|
| 支持工具调用且有 `async_chat_streamly_with_tools` | `async_chat_streamly_with_tools` |
| 有 `async_chat_streamly` | `async_chat_streamly` |
| 都不具备 | 抛出 RuntimeError |

这是一个**策略选择模式**，优先选择支持工具调用的流式方法。

### 4.3 Langfuse 追踪初始化 (412-414行)

```python
generation = None
if self.langfuse:
    generation = self.langfuse.start_generation(
        trace_context=self.trace_context,
        name="chat_streamly",
        model=self.llm_name,
        input={"system": system, "history": history}
    )
```

Langfuse 是一个 LLM 可观测性平台，用于追踪和监控 LLM 调用。

### 4.4 核心流式处理循环 (416-442行)

```python
if stream_fn:
    chat_partial = partial(stream_fn, system, history, gen_conf)
    use_kwargs = self._clean_param(chat_partial, **kwargs)
    try:
        async for txt in chat_partial(**use_kwargs):
            # ... 处理每个文本块
```

#### 4.4.1 Token 计数处理 (421-423行)

```python
if isinstance(txt, int):
    total_tokens = txt
    break
```

当流式返回整数时，表示 token 总数，记录后跳出循环。

#### 4.4.2 推理标签处理 (425-426行)

```python
if txt.endswith(""):
    ans = ans[: -len("")]
```

处理 o1 等模型的 `<think>` 推理标签。当文本以 `` 结尾时，移除这个标签，避免向用户展示推理过程。

#### 4.4.3 工具调用内容过滤 (428-429行)

```python
if not self.verbose_tool_use:
    txt = re.sub(r"<tool_call>.*?</tool_call>", "", txt, flags=re.DOTALL)
```

在非详细模式下，使用正则表达式移除 `<tool_call>` 标签内的工具调用内容，使输出更简洁。

#### 4.4.4 文本累积与输出 (431-432行)

```python
ans += txt
yield ans
```

将新文本累积到 `ans` 中，并 yield 当前完整响应。这是一个**增量输出**模式，每次 yield 都是完整的累积结果。

### 4.5 异常处理与资源清理 (433-437行)

```python
except Exception as e:
    if generation:
        generation.update(output={"error": str(e)})
        generation.end()
    raise
```

捕获异常并：
1. 更新 Langfuse 追踪记录
2. 结束追踪
3. 重新抛出异常

### 4.6 Token 使用记录 (438-439行)

```python
if total_tokens and not TenantLLMService.increase_usage(self.tenant_id, self.llm_type, total_tokens, self.llm_name):
    logging.error("LLMBundle.async_chat_streamly can't update token usage for {}/CHAT llm_name: {}, used_tokens: {}".format(self.tenant_id, self.llm_name, total_tokens))
```

记录租户的 token 使用量，用于计费和配额管理。

### 4.7 追踪记录更新 (440-442行)

```python
if generation:
    generation.update(output={"output": ans}, usage_details={"total_tokens": total_tokens})
    generation.end()
```

更新 Langfuse 追踪记录，保存最终输出和 token 使用情况。

## 五、关键技术点

### 5.1 异步生成器 (Async Generator)

该方法是一个**异步生成器函数**，使用 `async for` 迭代和 `yield` 返回值：

```python
async def async_chat_streamly(...):
    async for txt in chat_partial(**use_kwargs):
        yield ans
```

### 5.2 增量输出模式

每次 yield 返回的是**累积的完整结果**，而非仅增量部分：

```
Token流:  "你" -> "好" -> "世" -> "界"
Yield输出: "你" -> "你好" -> "你好世" -> "你好世界"
```

### 5.3 参数清理机制

通过 `_clean_param` 方法过滤掉底层模型不支持的参数：

```python
use_kwargs = self._clean_param(chat_partial, **kwargs)
```

这是通过 `inspect` 模块检查函数签名实现的 (282-296行)。

### 5.4 推理内容隐藏

对于 o1 等带推理过程的模型，自动隐藏 `<think>` 标签内的推理过程：

```python
if txt.endswith(""):
    ans = ans[: -len("")]
```

### 5.5 工具调用内容可选显示

通过 `verbose_tool_use` 标志控制是否显示工具调用详情：

```python
if not self.verbose_tool_use:
    txt = re.sub(r"<tool_call>.*?</tool_call>", "", txt, flags=re.DOTALL)
```

## 六、与其他方法的对比

| 方法 | 类型 | 返回方式 | 使用场景 |
|------|------|----------|----------|
| `async_chat` | async | 完整响应 | 非流式对话 |
| `async_chat_streamly` | async generator | 流式增量 | 实时流式对话 |
| `chat` | sync | 完整响应 | 同步非流式 |
| `chat_streamly` | sync generator | 流式增量 | 同步流式 |

## 七、调用链路

```
LLMBundle.async_chat_streamly
    ↓
底层模型 async_chat_streamly / async_chat_streamly_with_tools
    ↓
LLM Provider API (OpenAI / Anthropic / etc.)
    ↓
流式响应返回
    ↓
后处理 (推理标签过滤、工具调用过滤)
    ↓
Yield 增量结果
```

## 八、使用示例

```python
# 创建 LLMBundle
bundle = LLMBundle(
    tenant_id="tenant123",
    llm_type=LLMType.CHAT,
    llm_name="gpt-4"
)

# 异步流式对话
async for response in bundle.async_chat_streamly(
    system="你是一个 helpful assistant",
    history=[
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！有什么可以帮助你的？"}
    ],
    gen_conf={"temperature": 0.7}
):
    print(response, end="", flush=True)
```

## 九、注意事项

1. **异步上下文**: 必须在异步上下文中调用此方法
2. **模型支持**: 底层模型必须实现 `async_chat_streamly` 或 `async_chat_streamly_with_tools`
3. **Token 计算**: 依赖底层模型正确返回 token 计数
4. **状态管理**: 每次调用都创建新的生成上下文，不保留状态

## 十、相关文件

- `api/db/services/llm_service.py:402-443` - 方法定义
- `api/db/services/tenant_llm_service.py` - Token 使用记录服务
- `rag/llm/` - 底层模型实现
- `common/constants.py` - LLMType 常量定义
