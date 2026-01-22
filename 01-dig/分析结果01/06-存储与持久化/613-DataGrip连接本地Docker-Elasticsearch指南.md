# DataGrip连接本地Docker Elasticsearch完整指南

> **基于**: RAGFlow本地Docker环境
> **Elasticsearch版本**: 8.11.3
> **创建时间**: 2026-01-21

---

## 目录

1. [环境配置分析](#1-环境配置分析)
2. [DataGrip连接步骤](#2-datagrip连接步骤)
3. [验证连接](#3-验证连接)
4. [常见问题](#4-常见问题)

---

## 1. 环境配置分析

### 1.1 从启动脚本分析

**文件**: `docker/launch_backend_debug.sh`

**关键发现**:
```bash
# 第7-22行：加载环境变量
load_env_file() {
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local env_file="$script_dir/.env"
    source "$env_file"
}

# 第25行：加载.env文件
load_env_file
```

**结论**: 启动脚本从 `docker/.env` 加载配置

### 1.2 从.env文件分析Elasticsearch配置

**文件**: `docker/.env`

**Elasticsearch相关配置**:

```bash
# 第22-23行：Elasticsearch版本
STACK_VERSION=8.11.3

# 第25-26行：主机名和端口
ES_HOST=es01
ES_PORT=1200

# 第32-33行：用户密码
ELASTIC_PASSWORD=infini_rag_flow
```

### 1.3 从docker-compose-base.yml分析

**文件**: `docker/docker-compose-base.yml`

**Elasticsearch服务配置** (第2-34行):

```yaml
es01:
  image: elasticsearch:${STACK_VERSION}  # elasticsearch:8.11.3
  ports:
    - ${ES_PORT}:9200  # 1200:9200
  environment:
    - ELASTIC_PASSWORD=${ELASTIC_PASSWORD}  # infini_rag_flow
    - xpack.security.enabled=true
    - xpack.security.http.ssl.enabled=false  # HTTP非SSL
    - xpack.security.transport.ssl.enabled=false
```

### 1.4 关键配置汇总

| 配置项 | 值 | 说明 |
|--------|-----|------|
| **Host** | `localhost` | 本地访问 |
| **Port** | `1200` | 宿主机映射端口（Docker内部是9200） |
| **Username** | `elastic` | ES默认用户名 |
| **Password** | `infini_rag_flow` | 从.env文件 |
| **Version** | `8.11.3` | ES版本 |
| **Protocol** | `http` | 非SSL（xpack.security.http.ssl.enabled=false） |

---

## 2. DataGrip连接步骤

### 2.1 打开DataGrip并创建新连接

1. 启动DataGrip
2. 点击左侧 `Database` 面板的 `+` 按钮
3. 选择 `Data Source` → `Elasticsearch`

### 2.2 配置连接信息

#### 基本配置

在连接配置面板中填写：

```
Host: localhost
Port: 1200
Authentication: Basic Auth
Username: elastic
Password: infini_rag_flow
```

#### 详细配置界面

**选项卡: General**

| 字段 | 值 | 说明 |
|------|-----|------|
| **Host** | `localhost` | 或使用 `127.0.0.1` |
| **Port** | `1200` | 宿主机端口（不是9200） |
| **User** | `elastic` | ES默认超级用户 |
| **Password** | `infini_rag_flow` | 来自.env配置 |

**选项卡: SSH/SSL**

- ❌ 不需要配置SSH（本地直接访问）
- ❌ 不需要配置SSL（已禁用SSL）

**选项卡: Advanced**

```properties
# 连接超时设置
Connection Timeout: 60000 (60秒)

# 读取超时设置
Socket Timeout: 60000 (60秒)
```

### 2.3 完整配置截图说明

```
┌─────────────────────────────────────────────────────────┐
│ Data Source: Elasticsearch - Local Docker             │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Host:       [localhost                    ]            │
│ Port:       [1200                          ]            │
│                                                         │
│ Authentication:  [Basic Auth ▼]                        │
│ User:       [elastic                      ]            │
│ Password:   [************                  ]            │
│                                                         │
│ ☐ HTTP Proxy                                           │
│                                                         │
│          [Test Connection]  [Download Driver]          │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 2.4 下载驱动

1. 首次连接时，DataGrip会提示下载驱动
2. 点击 `Download Driver` 或 `Download missing driver files`
3. 等待下载完成

**需要的驱动**: Elasticsearch Rest Client

---

## 3. 验证连接

### 3.1 测试连接

1. 点击 `Test Connection` 按钮
2. 如果成功，会显示类似信息：

```
Connection successful
Elasticsearch version: 8.11.3
Cluster name: docker-cluster
```

3. 如果失败，查看错误信息并参考[常见问题](#4-常见问题)

### 3.2 测试基础查询

连接成功后，在Console中执行：

```sql
-- 查看所有索引
SHOW TABLES
```

**期望结果**:
```
rag_table_tenant_001
...
```

```sql
-- 查看ES版本
SELECT VERSION()
```

**期望结果**```
8.11.3
```

### 3.3 验证实际数据

```sql
-- 查询RAGFlow的chunk数据
SELECT COUNT(*)
FROM rag_table_tenant_001
```

```sql
-- 查看索引结构
DESCRIBE rag_table_tenant_001
```

---

## 4. 常见问题

### Q1: 连接超时 "Connection refused"

**错误信息**:
```
Connection refused: connect
```

**原因**: Elasticsearch容器未启动

**解决方案**:

```bash
# 1. 检查容器状态
docker ps | grep elasticsearch

# 2. 如果未启动，启动服务
cd docker
docker compose -f docker-compose-base.yml up -d

# 3. 查看容器日志
docker logs es01
```

### Q2: 认证失败 "Authentication failed"

**错误信息**:
```
authentication failed for user elastic
```

**原因**: 用户名或密码错误

**解决方案**:

1. 确认密码：
```bash
# 查看.env文件
cat docker/.env | grep ELASTIC_PASSWORD
```

2. 重置密码：
```bash
# 进入ES容器
docker exec -it es01 bash

# 重置密码
bin/elasticsearch-reset-password -u elastic
```

### Q3: 端口错误 "Port 9200 not reachable"

**错误信息**:
```
Failed to connect to localhost:9200
```

**原因**: 端口配置错误，应该使用 `1200` 而不是 `9200`

**解决方案**:

在DataGrip中使用：
```
Port: 1200  # 正确（宿主机端口）
```

而不是：
```
Port: 9200  # 错误（Docker内部端口）
```

**端口映射说明**:
```
宿主机:1200  →  Docker容器:9200
     ↓
DataGrip连接localhost:1200
```

### Q4: SSL错误 "SSL handshake failed"

**错误信息**:
```
SSL handshake failed
```

**原因**: ES配置中已禁用SSL，但DataGrip尝试使用HTTPS

**解决方案**:

确保DataGrip使用HTTP而非HTTPS：

1. 检查连接URL：`http://localhost:1200`
2. 不要勾选 "Use SSL" 选项

### Q5: 驱动问题 "Driver not found"

**解决方案**:

1. 点击 `Download Driver` 按钮
2. 或手动添加驱动：
   - 打开 `File` → `Data Sources` → `Drivers` → `Elasticsearch`
   - 点击 `+` 添加驱动文件
   - 下载地址: https://jdbc.postgresql.org/download/

### Q6: 查询报错 "Index not found"

**错误信息**:
```
IndexNotFoundException: no such index [rag_table_tenant_001]
```

**原因**: 索引名称不正确

**解决方案**:

1. 查看所有索引：
```sql
SHOW TABLES
```

2. 使用正确的索引名称（注意tenant ID）

---

## 5. 完整配置示例

### 5.1 DataGrip连接配置文件

DataGrip支持导出连接配置，格式如下：

```xml
<!-- DataGrip连接配置 -->
<data-source>
  <name>Elasticsearch - Local Docker</name>
  <driver-ref>elasticsearch</driver-ref>
  <synchronize>true</synchronize>
  <configured-url>false</configured-url>
  <url>http://localhost:1200</url>
  <driver-properties>
    <property name="user" value="elastic"/>
    <property name="password" value="infini_rag_flow"/>
  </driver-properties>
</data-source>
```

### 5.2 使用cURL测试连接

在连接DataGrip之前，先用cURL测试：

```bash
# 测试ES是否可访问
curl http://localhost:1200

# 期望输出
{
  "name" : "es01",
  "cluster_name" : "docker-cluster",
  "version" : {
    "number" : "8.11.3",
    ...
  }
}

# 测试认证
curl -u elastic:infini_rag_flow http://localhost:1200/_cluster/health

# 查看所有索引
curl -u elastic:infini_rag_flow http://localhost:1200/_cat/indices?v
```

### 5.3 使用Python脚本测试

```python
from elasticsearch import Elasticsearch

# 连接配置
es = Elasticsearch(
    "http://localhost:1200",
    basic_auth=("elastic", "infini_rag_flow")
)

# 测试连接
info = es.info()
print(f"Elasticsearch version: {info['version']['number']}")

# 查看所有索引
indices = es.indices.get_alias(index="*")
print(f"Indices: {list(indices.keys())}")
```

---

## 6. 快速参考

### 6.1 连接信息速查卡

```
┌────────────────────────────────────────────┐
│  Elasticsearch连接信息                      │
├────────────────────────────────────────────┤
│  Host:     localhost                       │
│  Port:     1200                            │
│  URL:      http://localhost:1200           │
│  User:     elastic                         │
│  Password: infini_rag_flow                 │
│  Version:  8.11.3                          │
├────────────────────────────────────────────┤
│  配置文件: docker/.env                      │
│  容器名:  es01                              │
│  网络:    ragflow                          │
└────────────────────────────────────────────┘
```

### 6.2 常用Docker命令

```bash
# 查看ES容器状态
docker ps | grep es01

# 查看ES日志
docker logs -f es01

# 重启ES容器
docker restart es01

# 进入ES容器
docker exec -it es01 bash

# 查看ES配置
cat docker/docker-compose-base.yml | grep -A 30 "es01:"

# 查看环境变量
cat docker/.env | grep ES
```

### 6.3 检查ES健康状态

```sql
-- 在DataGrip中执行
SELECT * FROM _cluster_health

-- 或使用REST API（在Console中）
GET /_cluster/health
```

---

## 7. 后续使用

### 7.1 查看RAGFlow数据

连接成功后，可以：

1. **查看所有索引**:
```sql
SHOW TABLES
```

2. **查询chunk数据**:
```sql
SELECT
    id,
    kb_id,
    doc_id,
    docnm_kwd,
    SUBSTRING(content_with_weight, 1, 100) as preview
FROM rag_table_tenant_001
LIMIT 10
```

3. **统计查询**:
```sql
SELECT
    kb_id,
    COUNT(*) as chunk_count
FROM rag_table_tenant_001
GROUP BY kb_id
```

### 7.2 导出数据

1. 执行查询后，在结果面板右键
2. 选择 `Export Data to File`
3. 选择格式（CSV、Excel、JSON等）

### 7.3 保存常用查询

1. 编写查询后，按 `Ctrl+S` (Mac: `Cmd+S`)
2. 保存为 `.sql` 文件
3. 下次直接打开使用

---

## 8. 故障排查清单

✅ **检查项**:

- [ ] Docker容器是否运行？`docker ps | grep es01`
- [ ] 端口是否正确？使用 `1200` 而不是 `9200`
- [ ] 密码是否正确？检查 `docker/.env` 中的 `ELASTIC_PASSWORD`
- [ ] 防火墙是否阻止端口？
- [ ] DataGrip驱动是否已下载？
- [ ] ES容器是否健康？`docker logs es01`
- [ ] 使用cURL能否连接？`curl http://localhost:1200`

---

## 9. 相关文档

- [612-Elasticsearch查询指导-DataGrip篇.md](612-Elasticsearch查询指导-DataGrip篇.md) - 完整查询指南
- [docker/.env](../../../docker/.env) - 环境变量配置
- [docker/docker-compose-base.yml](../../../docker/docker-compose-base.yml) - Docker服务配置
- [Elasticsearch官方文档](https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html)
