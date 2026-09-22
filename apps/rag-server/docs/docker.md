# Docker 核心知识详解

---

## 目录

1. [docker compose 命令详解](#1-docker-compose-命令详解)
2. [host.docker.internal 底层实现原理](#2-hostdockerinternal-底层实现原理)
3. [为什么 GPU 程序必须运行在宿主机上？](#3-为什么-gpu-程序必须运行在宿主机上)
4. [docker-compose.yml 语法逐行详解](#4-docker-composeyml-语法逐行详解)
5. [Docker 容器内的目录组织结构](#5-docker-容器内的目录组织结构)
6. [healthcheck 语法与 Shell 命令基础](#6-healthcheck-语法与-shell-命令基础)
7. [.dockerignore 的作用](#7-dockerignore-的作用)
8. [两个 Dockerfile 全部语法详解](#8-两个-dockerfile-全部语法详解)
9. [Compose 与 Dockerfile 的关系 + Docker 整体运行机制](#9-compose-与-dockerfile-的关系--docker-整体运行机制)
10. [外部环境变量如何进入 Docker 容器](#10-外部环境变量如何进入-docker-容器)

---

## 1. docker compose 命令详解

### 原始命令

```bash
docker compose --env-file .env.docker up -d
```

### 逐词拆解

```
docker compose --env-file .env.docker up -d
│      │        │           │          │  │
│      │        │           │          │  └── -d：detached，后台运行（不占用终端）
│      │        │           │          └── up：创建并启动所有服务
│      │        │           └── .env.docker：环境变量文件的路径
│      │        └── --env-file：指定从哪个文件读取环境变量
│      └── compose：Docker Compose 子命令（管理多容器应用）
└── docker：Docker CLI 主命令
```

### 每个部分的详细说明

#### `compose`

Docker Compose 是 Docker 的一个子系统，专门用于**定义和管理多容器应用**。

| `docker-compose.yml` | `package.json`（声明项目组成） |

> **历史说明**：旧版本是独立命令 `docker-compose`（带横杠），新版本已集成为 `docker compose`（空格）。两者功能相同。

#### `--env-file .env.docker`

告诉 Compose："从 `.env.docker` 文件中读取变量，用于替换 `docker-compose.yml` 中的 `${VARIABLE}` 占位符。"

```
.env.docker 文件内容          docker-compose.yml 中的引用
────────────────────          ──────────────────────────
MYSQL_PORT=3306        →      ports: - "${MYSQL_PORT:-3306}:3306"
                                       ↑ 被替换为 3306
```

如果不指定 `--env-file`，Compose 默认读取当前目录下的 `.env` 文件。我们使用 `.env.docker` 是为了和 Node 项目的 `.env` 区分开。

#### `up`

执行以下操作（按顺序）：

1. 读取 `docker-compose.yml` 解析所有服务定义
2. 对有 `build:` 的服务执行 `docker build` 构建镜像
3. 创建 Docker 网络（让容器之间能互相通信）
4. 按照 `depends_on` 的依赖关系确定启动顺序
5. 创建并启动所有容器

#### `-d`（detached mode）

让所有容器在后台运行。如果不加 `-d`，所有容器的日志会输出到当前终端，关掉终端容器也会停止。

**类比**：
```bash
node server.js        # 前台运行，Ctrl+C 停止
node server.js &      # 后台运行（Linux），类似 -d 的效果
```

### 其他常用命令组合

```bash
docker compose --env-file .env.docker logs -f          # 实时查看日志（-f = follow）
docker compose --env-file .env.docker logs java-server  # 只看某个服务的日志
docker compose --env-file .env.docker ps                # 查看所有容器状态
docker compose --env-file .env.docker stop              # 停止（不删除容器）
docker compose --env-file .env.docker down              # 停止 + 删除容器 + 删除网络
docker compose --env-file .env.docker down -v           # 停止 + 删除容器 + 删除网络 + 删除数据卷
docker compose --env-file .env.docker restart java-server  # 重启某个服务
docker compose --env-file .env.docker build              # 重新构建镜像（代码修改后）
docker compose --env-file .env.docker up -d --build      # 重新构建并启动
```

---

## 2. host.docker.internal 底层实现原理

### 问题背景

Docker 容器是一个**隔离的网络环境**，有自己独立的 IP 地址和网络栈。容器内的 `localhost` 指向容器自己，**不是**宿主机。

```
宿主机（你的 Windows/Mac）
├── IP: 192.168.1.100
├── Ollama 运行在 localhost:11434
│
└── Docker 容器（node-server）
    ├── IP: 172.17.0.5（Docker 内部 IP）
    ├── localhost = 172.17.0.5（指向容器自己！）
    └── 问题：如何访问宿主机的 Ollama？
```

如果容器内代码写 `http://localhost:11434`，它访问的是容器自己的 11434 端口——那里什么也没有。

### host.docker.internal 的作用

`host.docker.internal` 是一个特殊的 DNS 域名，在 Docker 容器内部它会被解析为**宿主机的 IP 地址**。


### 底层实现原理（分平台）

#### Docker Desktop（Windows / macOS）

在 Windows 和 macOS 上，Docker 并不是直接运行在操作系统上的——它运行在一个轻量级虚拟机（LinuxKit VM）里：

```
┌─────────────────────────────────────────────┐
│ Windows / macOS 宿主机                       │
│  IP: 192.168.1.100                           │
│  Ollama: localhost:11434                     │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │ LinuxKit VM（Docker 的底层 Linux）      │  │
│  │                                         │  │
│  │  ┌─────────────┐  ┌─────────────┐     │  │
│  │  │ container A │  │ container B │     │  │
│  │  │ 172.17.0.2  │  │ 172.17.0.3  │     │  │
│  │  └─────────────┘  └─────────────┘     │  │
│  │                                         │  │
│  │  DNS 内置规则：                          │  │
│  │  host.docker.internal → 192.168.65.254  │  │
│  │  （VM 网关 IP = 宿主机）                 │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  192.168.65.254 = VM 的默认网关              │
│  指向宿主机的网络栈                           │
└─────────────────────────────────────────────┘
```

**Docker Desktop 在启动虚拟机时，自动将 `host.docker.internal` 写入 VM 的 DNS 解析配置**，指向 VM 的默认网关 IP（即宿主机）。这是 Docker Desktop 内置的功能，不需要你做任何配置。

#### Docker Engine（Linux）

Linux 上 Docker 直接运行在宿主机上（没有虚拟机），所以 **`host.docker.internal` 默认不存在**。需要你手动配置：

```yaml
# docker-compose.yml 中的配置
extra_hosts:
  - "host.docker.internal:host-gateway"
```

这行配置的作用等价于在容器的 `/etc/hosts` 文件中添加一行：

```
172.17.0.1  host.docker.internal
```

其中 `host-gateway` 是 Docker 20.10+ 提供的特殊关键字，会自动解析为宿主机在 Docker 网桥上的 IP（通常是 `172.17.0.1`）。

### 为什么我们的 compose 文件里加了 extra_hosts？

```yaml
node-server:
  extra_hosts:
    - "host.docker.internal:host-gateway"
```

**兼容性考虑**：虽然 Docker Desktop（Windows/Mac）不需要这行配置，但为了确保在 Linux 服务器上部署时也能正常工作，我们统一加上。在 Docker Desktop 上它不会覆盖内置的解析，在 Linux 上它提供了必要的 DNS 映射。

---

## 3. 为什么 GPU 程序必须运行在宿主机上？

### 核心原因：Docker 容器默认无法访问 GPU 硬件

Docker 容器的核心原理是**操作系统级别的隔离**——每个容器有独立的文件系统、进程树、网络栈。但这种隔离也意味着：**容器内看不到宿主机的硬件设备**（除非显式挂载）。

```
宿主机操作系统
├── CPU        → 容器天然共享（因为 Linux 内核共享）
├── 内存        → 容器天然共享（通过 cgroups 限制用量）
├── 磁盘        → 容器通过 volumes 挂载
├── 网络        → 容器通过虚拟网桥
│
└── GPU（NVIDIA/AMD） → ❌ 容器默认完全看不到！
    ├── 物理硬件（PCIe 设备）
    ├── GPU 驱动程序（内核模块）
    └── CUDA / ROCm 运行时
```

### GPU 在容器中的挑战

GPU 不像 CPU 那样简单——它需要：

1. **硬件设备文件**：Linux 下 GPU 通过 `/dev/nvidia0`、`/dev/nvidiactl` 等设备文件暴露，容器默认无法访问这些文件
2. **内核驱动**：GPU 驱动是一个内核模块（`nvidia.ko`），需要在宿主机内核中加载
3. **用户态运行时**：CUDA Toolkit / cuDNN 等库需要安装在可见的文件系统中
4. **版本严格匹配**：驱动版本、CUDA 版本、应用框架版本之间有严格的兼容性要求

### Docker 中使用 GPU 的方案

#### 方案一：NVIDIA Container Toolkit（可行但复杂）

```bash
# 宿主机安装 NVIDIA Container Toolkit
# 然后在 docker-compose.yml 中：
services:
  ollama:
    image: ollama/ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

**但这需要**：
- 宿主机安装 NVIDIA 驱动 + NVIDIA Container Toolkit
- Docker runtime 切换为 `nvidia-docker2`
- GPU 驱动版本与容器内 CUDA 版本兼容
- 只支持 Linux 宿主机（Windows/Mac 上的 Docker Desktop 的 GPU 透传支持有限且不稳定）

#### 方案二：Ollama 直接跑在宿主机上（我们的选择）

```
宿主机
├── Ollama（直接访问 GPU，性能最佳）
│     └── 监听 localhost:11434
│
└── Docker 容器
      └── node-server
            └── 通过 host.docker.internal:11434 调用 Ollama
```

**选择这个方案的原因**：

| 维度 | 容器内 GPU | 宿主机 Ollama |
|------|----------|-------------|
| 配置复杂度 | 高（驱动匹配、runtime 配置） | 低（安装即用） |
| 跨平台兼容 | 差（Linux only 且不稳定） | 好（Win/Mac/Linux 都支持） |
| GPU 性能 | 有少量虚拟化开销 | 原生性能，无损失 |
| 适用场景 | 大规模生产集群（K8s + GPU） | 本地开发、小团队部署 |

### Ollama 为什么特别需要 GPU？

大语言模型（LLM），模型推理是**大量的矩阵运算**：

```
CPU 推理 qwen2.5:7b  → 约 2-5 tokens/秒（痛苦地慢）
GPU 推理 qwen2.5:7b  → 约 30-80 tokens/秒（流畅对话）
```

GPU 有数千个小核心，天然适合大规模并行矩阵运算，这就是为什么 AI 推理几乎离不开 GPU。

---

## 4. docker-compose.yml 语法逐行详解

### `ports`（端口映射）

```yaml
ports:
  - "${MYSQL_PORT:-3306}:3306"
```

**语法**：`"宿主机端口:容器端口"`

```
"${MYSQL_PORT:-3306}:3306"
      │          │     │
      │          │     └── 容器内部端口（MySQL 在容器里监听的端口）
      │          └── 默认值（如果环境变量不存在，用 3306）
      └── 从 .env.docker 读取的环境变量
```

**底层原理**：Docker 通过 **iptables 规则（Linux）或端口转发（Windows/Mac）** 把宿主机端口的流量转发到容器端口。

```
外部请求 → 宿主机:3306 → Docker 网络转发 → 容器:3306 → MySQL 进程
```

**`${VARIABLE:-default}` 语法**：这是 Shell 的"变量默认值"语法——
- 如果 `VARIABLE` 已定义且非空 → 使用 `VARIABLE` 的值
- 如果 `VARIABLE` 未定义或为空 → 使用 `default`

### `environment`（环境变量注入）

```yaml
environment:
  MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:-root}
  MYSQL_DATABASE: ${MYSQL_DATABASE:-agent_server}
```

**作用**：设置容器内的环境变量。这些变量会出现在容器进程的环境中（等价于在 Shell 中 `export MYSQL_ROOT_PASSWORD=root`）。

MySQL 官方镜像在启动时会读取这些特定变量来初始化：

| 变量 | 含义 |
|------|------|
| `MYSQL_ROOT_PASSWORD` | root 用户的密码 |
| `MYSQL_DATABASE` | 自动创建的数据库名 |
| `MYSQL_CHARACTER_SET_SERVER` | 服务器字符集 |
| `MYSQL_COLLATION_SERVER` | 排序规则 |

### `command`（覆盖默认启动命令）

```yaml
command: >
  redis-server
  --requirepass "${REDIS_PASSWORD:-}"
  --appendonly yes
```

**`>` 是 YAML 的"折叠块"语法**：把多行文本折叠为一行（换行变空格）。实际等价于：

```
redis-server --requirepass "" --appendonly yes
```

**作用**：覆盖 Docker 镜像默认的启动命令（CMD），用自定义参数启动 Redis：
- `--requirepass`：设置访问密码
- `--appendonly yes`：开启 AOF 持久化（Redis 数据写入磁盘，重启不丢失）

### `build`（构建配置）

```yaml
node-server:
  build:
    context: ./apps/node-server
    dockerfile: Dockerfile
```

| 字段 | 含义 |
|------|------|
| `context` | 构建上下文目录——Docker 会把这个目录的所有文件发送给 Docker 引擎 |
| `dockerfile` | Dockerfile 的文件名（相对于 context 目录） |

**类比**：`context` 就像告诉 Docker "项目根目录在哪里"，`dockerfile` 就像告诉它 "构建脚本叫什么名字"。

### `healthcheck`（健康检查）

```yaml
healthcheck:
  test: ["CMD-SHELL", "wget -qO- http://localhost:3101/api || exit 1"]
  interval: 15s
  timeout: 5s
  retries: 5
  start_period: 10s
```

详见[第 6 节](#6-healthcheck-语法与-shell-命令基础)。

### `extra_hosts`（自定义 DNS）

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

**作用**：在容器的 `/etc/hosts` 文件中添加一条 DNS 记录。

等价于在容器内手动编辑：

```
# /etc/hosts
172.17.0.1    host.docker.internal
```

### `volumes`（顶层卷声明）

```yaml
volumes:
  mysql-data:
  redis-data:
  rabbitmq-data:
  node-storage:
  java-storage:
```

**这是 Docker 命名卷（Named Volumes）的声明**。类似于 JavaScript 中的"变量声明"——你先声明有这些卷，然后在各个 service 中引用它们。

```yaml
# 声明（顶层）
volumes:
  mysql-data:     # 声明一个叫 mysql-data 的卷

# 使用（服务中）
services:
  mysql:
    volumes:
      - mysql-data:/var/lib/mysql   # 把 mysql-data 卷挂载到容器的 /var/lib/mysql
```

**命名卷的生命周期**：
- `docker compose up` → 卷不存在就创建，存在就复用
- `docker compose down` → 卷保留（数据不丢）
- `docker compose down -v` → 卷被删除（数据清空）

### `depends_on`（启动依赖顺序）

```yaml
depends_on:
  mysql:
    condition: service_healthy
  redis:
    condition: service_healthy
  rabbitmq:
    condition: service_healthy
  node-server:
    condition: service_healthy
```

**作用**：声明 `java-server` 依赖于 `mysql`、`redis`、`rabbitmq`、`node-server` 四个服务。

**`condition: service_healthy`** 的含义：不仅要求依赖服务的容器已启动（`service_started`），还要求它的 `healthcheck` 已通过（`service_healthy`）。这是关键——MySQL 容器启动了不代表 MySQL 进程已经就绪，可能还在初始化表结构。

```
启动顺序（自动计算）：
1. mysql + redis + rabbitmq    ← 并行启动，无依赖
2. 等待三者的 healthcheck 全部通过
3. node-server 启动
4. 等待 node-server 的 healthcheck 通过
5. java-server 启动
```

---

## 5. Docker 容器内的目录组织结构

### 容器的文件系统本质

每个 Docker 容器都有一个**完整的 Linux 文件系统**，就像一台独立的 Linux 虚拟机。但它不是虚拟机——它是通过**分层文件系统（UnionFS）** 实现的。

```
容器文件系统 = 镜像层（只读） + 容器层（可写）
```

### MySQL 容器的目录结构

```
/ (根目录)
├── bin/           ← 系统命令（ls、cat、sh...）
├── etc/           ← 配置文件
│   ├── mysql/     ← MySQL 配置
│   └── hosts      ← DNS 映射（extra_hosts 写入这里）
├── usr/
│   ├── bin/       ← 用户命令（mysql、mysqld...）
│   └── lib/       ← 库文件
├── var/
│   └── lib/
│       └── mysql/ ← ⭐ MySQL 数据目录（我们挂载卷的位置）
├── tmp/           ← 临时文件
└── root/          ← root 用户的 home 目录
```

### volumes 挂载的原理

```yaml
volumes:
  - mysql-data:/var/lib/mysql
```

```
宿主机                              容器内
──────                              ──────
Docker 管理的存储区域                /var/lib/mysql/
/var/lib/docker/volumes/             │
  mysql-data/                        ├── agent_server/  (数据库文件)
    _data/  ←────── 双向同步 ──────→ ├── ibdata1        (InnoDB 数据)
      ├── agent_server/              ├── ib_logfile0    (事务日志)
      ├── ibdata1                    └── ...
      └── ...
```

**原理**：Docker 使用 **bind mount** 机制，把宿主机上的一个目录"挂载"到容器内的指定路径。容器内对 `/var/lib/mysql` 的任何读写操作，实际上直接作用在宿主机的 `mysql-data` 卷上。

### 我们的 Java 应用容器结构

```
/app (WORKDIR)
├── app.jar          ← Spring Boot 可执行 JAR（从 builder 阶段复制）
└── storage/
    └── agent-runs/  ← 挂载到 java-storage 卷（Agent 产物输出目录）
```

### 我们的 Node 应用容器结构

```
/app (WORKDIR)
├── package.json
├── node_modules/     ← 生产依赖
├── dist/
│   └── main.js       ← NestJS 编译产物（从 builder 阶段复制）
└── storage/
    └── agent-runs/   ← 挂载到 node-storage 卷
```

### 命名卷 vs 绑定挂载

```yaml
# 命名卷（Named Volume）— 由 Docker 管理存储位置
volumes:
  - mysql-data:/var/lib/mysql

# 绑定挂载（Bind Mount）— 你指定宿主机的具体路径
volumes:
  - ./local-data:/var/lib/mysql
  - D:\my-data:/var/lib/mysql
```

| 特性 | 命名卷 | 绑定挂载 |
|------|--------|---------|
| 存储位置 | Docker 自动管理 | 你手动指定 |
| 跨平台 | 一致（Docker 抽象了路径） | 路径格式不同（Win vs Linux） |
| 备份 | `docker volume` 命令管理 | 直接操作文件系统 |
| 推荐场景 | 数据库等有状态服务 | 开发时需要实时同步代码 |

---

## 6. healthcheck 语法与 Shell 命令基础

### healthcheck 完整语法

```yaml
healthcheck:
  test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "root", "-p${MYSQL_ROOT_PASSWORD:-root}"]
  interval: 10s
  timeout: 5s
  retries: 10
```
| `test` | 健康检查要执行的命令 |
| `interval` | 每隔多久检查一次（10 秒） |
| `timeout` | 单次检查的超时时间（5 秒内没响应就算失败） |
| `retries` | 连续失败多少次才判定为 unhealthy（10 次） |
| `start_period` | 容器启动后的宽限期，这段时间内的失败不计入 retries |

### test 字段的两种格式

#### 格式一：`["CMD", ...]`（数组格式，直接执行）

```yaml
test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "root", "-proot"]
```

等价于在容器内直接执行：
```bash
mysqladmin ping -h localhost -u root -proot
```

`"CMD"` 前缀表示"直接执行后面的命令"，不经过 Shell。每个参数是数组中的一个独立元素。

#### 格式二：`["CMD-SHELL", "..."]`（Shell 格式，通过 /bin/sh 执行）

```yaml
test: ["CMD-SHELL", "wget -qO- http://localhost:3101/api || exit 1"]
```

等价于在容器内执行：
```bash
/bin/sh -c "wget -qO- http://localhost:3101/api || exit 1"
```

`"CMD-SHELL"` 前缀表示"通过 Shell 执行"，支持管道 `|`、逻辑运算 `||` `&&`、重定向 `>` 等 Shell 语法。

### Shell 命令基础知识

#### `wget -qO- URL`

```bash
wget -qO- http://localhost:3101/api
│     ││
│     │└── O-：输出到标准输出（stdout），而不是保存为文件
│     │        O 是大写字母 O（Output），- 是标准输出的代号
│     └── q：quiet 安静模式，不显示下载进度
└── wget：Linux 下的命令行下载工具
```

**这个命令的作用**：发一个 HTTP GET 请求到指定 URL，把响应体输出到终端。如果能正常访问就返回退出码 0（成功），连不上就返回非 0（失败）。

#### `||` 运算符

```bash
wget -qO- http://localhost:3101/api || exit 1
│                                     │    │
│                                     │    └── exit 1：以退出码 1（失败）结束
│                                     └── ||：如果左边命令失败（退出码非 0），则执行右边
└── 如果 wget 成功（退出码 0），则 || 后面的 exit 1 不会执行
```

**Shell 中的逻辑运算符**：

| 运算符 | 含义 | 例子 |
|--------|------|------|
| `&&` | 左边成功才执行右边 | `npm install && npm run build`（安装成功才构建） |
| `\|\|` | 左边失败才执行右边 | `wget URL \|\| exit 1`（下载失败就退出） |
| `;` | 无论左边成功失败都执行右边 | `echo hello; echo world` |

#### `mysqladmin ping`

```bash
mysqladmin ping -h localhost -u root -p${MYSQL_ROOT_PASSWORD:-root}
│          │    │             │       │
│          │    │             │       └── -p：密码（注意 -p 后面紧跟密码，没有空格！）
│          │    │             └── -u root：用 root 用户
│          │    └── -h localhost：连接到 localhost
│          └── ping：发送一个 ping 请求，检查 MySQL 是否存活
└── mysqladmin：MySQL 管理工具
```

如果 MySQL 进程正常运行，返回 `mysqld is alive`（退出码 0）；否则返回错误（退出码非 0）。

#### `redis-cli ping`

```bash
redis-cli ping
```

如果 Redis 运行正常，返回 `PONG`（退出码 0）。

#### 退出码约定

| 退出码 | 含义 | Docker healthcheck 判定 |
|--------|------|------------------------|
| 0 | 成功 | healthy |
| 非 0（1, 2, ...） | 失败 | unhealthy（累积到 retries 次后） |

---

## 7. .dockerignore 的作用

### 问题背景

当你执行 `docker build` 时，Docker 会把 `context` 目录下的**所有文件**打包发送给 Docker 引擎（daemon）。

```
docker build -f Dockerfile ./apps/java-server
                            │
                            └── 这整个目录会被打包发送
```

如果目录里有 `target/`（几百 MB 的编译产物）、`node_modules/`（几百 MB 的依赖）、`.git/`（可能几个 GB 的历史）等大目录，发送过程会非常慢，构建也会变慢。

### .dockerignore 的作用

**.dockerignore 告诉 Docker "这些文件不要发送给 Docker 引擎"**，就像 `.gitignore` 告诉 Git "这些文件不要追踪"。

### 我们项目的 .dockerignore

#### Java 项目的 .dockerignore

```
target          ← 编译产物（会在容器内重新编译）
.git            ← Git 历史（构建不需要）
.github         ← GitHub 配置
.idea           ← IntelliJ 配置
.settings       ← Eclipse 配置
.classpath      ← IDE 配置
.project        ← IDE 配置
*.iml           ← IDE 配置
.localdb        ← 本地 H2 数据库文件
storage         ← 运行时生成的文件
.cursor         ← Cursor IDE 配置
*.local         ← 本地环境文件
.env            ← 环境变量（包含敏感信息！）
docs            ← 文档（构建不需要）
```

#### Node 项目的 .dockerignore

```
node_modules    ← 依赖（会在容器内重新 install）
dist            ← 编译产物（会在容器内重新 build）
.git            ← Git 历史
.github         ← GitHub 配置
coverage        ← 测试覆盖率报告
.cursor         ← Cursor IDE 配置
*.local         ← 本地环境文件
.env            ← 环境变量（包含敏感信息！）
```

### 安全风险

**`.env` 必须在 .dockerignore 中！** 否则构建时你的密码、密钥等敏感信息会被打包进镜像，任何拿到镜像的人都能看到。

---

## 8. Dockerfile 全部语法详解

### Dockerfile 是什么？

Dockerfile 是一个**构建脚本**，告诉 Docker 如何一步步构建一个镜像（image）。你可以把它理解为一个"安装说明书"——从一个基础操作系统开始，逐步安装软件、复制文件、配置环境。

**类比**：如果 `docker-compose.yml` 是"怎么部署"，那 Dockerfile 就是"怎么打包"。

### Java Dockerfile 逐行详解

```dockerfile
# ========== 阶段一：构建 ==========
FROM eclipse-temurin:17-jdk AS builder
```

**`FROM`**：指定基础镜像——你的镜像"从哪个操作系统/环境开始"。

- `eclipse-temurin:17-jdk`：Adoptium 提供的 Java 17 JDK 镜像（基于 Ubuntu Linux），包含完整的 Java 开发工具（编译器 javac、打包工具等）
- **镜像命名规则**：`仓库名:标签`，标签通常是版本号

**`AS builder`**：给这个阶段起一个别名 `builder`，后续阶段可以引用它。这是**多阶段构建（Multi-stage Build）** 的语法。

```dockerfile
WORKDIR /build
```

**`WORKDIR`**：设置工作目录——后续所有 `RUN`、`COPY`、`CMD` 等命令都在这个目录下执行。如果目录不存在会自动创建。

**类比**：等价于 `cd /build`，但更安全（WORKDIR 是 Dockerfile 专用指令，不是 Shell 命令）。

```dockerfile
COPY .mvn/ .mvn/
COPY mvnw pom.xml ./
```

**`COPY`**：把宿主机文件复制到镜像中。

```
COPY  源路径（相对于 context）  目标路径（相对于 WORKDIR）
COPY  .mvn/                     .mvn/
      │                         │
      └── 宿主机的 .mvn/ 目录   └── 镜像内的 /build/.mvn/ 目录
```

**为什么先复制 pom.xml，再复制源码？** 这是 **Docker 缓存优化**的关键技巧：

```
Docker 构建每一层都有缓存。如果某一层的输入（COPY 的文件）没变，这一层直接用缓存。

步骤1: COPY pom.xml       → pom.xml 没变 → 缓存命中 ✅
步骤2: RUN mvnw dependency → 依赖没变   → 缓存命中 ✅（省掉几分钟下载）
步骤3: COPY src/           → 源码改了   → 重新执行 ❌
步骤4: RUN mvnw package    → 重新编译   → 重新执行 ❌
```

```dockerfile
RUN chmod +x mvnw && ./mvnw dependency:go-offline -B
```

**`RUN`**：在镜像构建过程中执行一条 Shell 命令。

- `chmod +x mvnw`：给 mvnw 文件添加"可执行"权限（Linux 下脚本需要执行权限）
- `&&`：第一个命令成功后才执行第二个
- `./mvnw dependency:go-offline`：下载所有 Maven 依赖到本地缓存
- `-B`：batch mode（批处理模式），不显示交互式进度条

```dockerfile
COPY src/ src/
RUN ./mvnw package -DskipTests -B
```

复制源码，然后执行 Maven 打包：
- `package`：编译 + 测试 + 打包为 JAR 文件
- `-DskipTests`：跳过测试（Docker 构建阶段不跑测试，测试在 CI/CD 中做）

```dockerfile
# ========== 阶段二：运行 ==========
FROM eclipse-temurin:17-jre
```

**第二个 `FROM`**：开始一个全新的阶段。`17-jre` 是 Java Runtime Environment（运行时），比 JDK 小很多（没有编译器等开发工具）。

**多阶段构建的意义**：

```
阶段一（builder）           阶段二（最终镜像）
┌─────────────────┐        ┌─────────────────┐
│ JDK (大，~400MB) │        │ JRE (小，~200MB) │
│ Maven           │        │                 │
│ 源码             │   →    │ app.jar（只复制这个）│
│ 依赖缓存         │        │                 │
│ target/         │        │                 │
│ ├── app.jar ────│────────│── app.jar        │
│ └── 其他编译产物  │        └─────────────────┘
└─────────────────┘
```

最终镜像只包含 JRE + JAR 文件，不包含源码、编译工具、依赖缓存等。镜像从 ~800MB 缩小到 ~250MB。

```dockerfile
WORKDIR /app

COPY --from=builder /build/target/*.jar app.jar
```

**`COPY --from=builder`**：从前面定义的 `builder` 阶段复制文件。这是多阶段构建的核心——"只从上一个阶段拿走你需要的东西"。

- `/build/target/*.jar`：builder 阶段编译出的 JAR 文件
- `app.jar`：在最终镜像中重命名为 app.jar

```dockerfile
RUN mkdir -p /app/storage/agent-runs
```

- `mkdir`：创建目录
- `-p`：递归创建（如果父目录不存在也一并创建，且目录已存在时不报错）

```dockerfile
EXPOSE 3000
```

**`EXPOSE`**：声明容器监听的端口。**纯文档性质**，不实际开放端口——实际端口映射由 `docker-compose.yml` 的 `ports` 或 `docker run -p` 决定。

**类比**：就像 `package.json` 中写 `"port": 3000`，只是告诉别人"这个应用用 3000 端口"，不会自动打开端口。

```dockerfile
ENTRYPOINT ["java", \
  "-XX:+UseContainerSupport", \
  "-XX:MaxRAMPercentage=75.0", \
  "-jar", "app.jar"]
```

**`ENTRYPOINT`**：容器启动时执行的命令（不可被 `docker run` 的参数覆盖，只能追加参数）。

- `java -jar app.jar`：运行 Spring Boot 应用
- `-XX:+UseContainerSupport`：告诉 JVM "你运行在容器中，请根据容器分配的内存来调整堆大小"（而不是读取宿主机的物理内存）
- `-XX:MaxRAMPercentage=75.0`：JVM 堆内存最多使用容器分配内存的 75%（留 25% 给堆外内存、线程栈等）

**`\` 反斜杠**：Dockerfile 中的行续接符，把一条很长的命令拆成多行写。

```dockerfile
WORKDIR /build

COPY package.json package-lock.json* pnpm-lock.yaml* ./
```

- `*` 通配符在 COPY 中的作用：文件存在就复制，不存在也不报错。这样不论项目用 npm（`package-lock.json`）还是 pnpm（`pnpm-lock.yaml`），Dockerfile 都能工作

```dockerfile
RUN corepack enable pnpm && pnpm install --frozen-lockfile
```

- `corepack enable pnpm`：Node.js 内置的 corepack 工具，启用 pnpm 包管理器
- `pnpm install --frozen-lockfile`：根据 lockfile 安装依赖（不允许修改 lockfile，保证依赖确定性）
- 这里安装的是**全部依赖**（含 devDependencies），因为构建需要 TypeScript、NestJS CLI

```dockerfile
COPY . .
RUN pnpm run build
```

复制全部源码，执行 `nest build` 编译 TypeScript 为 JavaScript。

```dockerfile
CMD ["node", "dist/main"]
```

**`CMD`** vs **`ENTRYPOINT`** 的区别：

| 指令 | 被覆盖方式 | 用途 |
|------|-----------|------|
| `CMD` | `docker run <image> <其他命令>` 直接覆盖 | 提供默认命令，可被替换 |
| `ENTRYPOINT` | 不会被覆盖，`docker run` 的参数是追加的 | 固定入口，参数可变 |

Java 用 `ENTRYPOINT` 是因为 JVM 参数是固定的；Node 用 `CMD` 是因为更灵活（调试时可以替换成 `node --inspect dist/main`）。

---

## 9. Compose 与 Dockerfile 的关系 + Docker 整体运行机制

### Compose 和 Dockerfile 的关系

```
┌─────────────────────────────────────────────────────────────┐
│                    docker-compose.yml                         │
│    "编排文件"——定义有哪些服务、如何组网、如何启动               │
│                                                              │
│    services:                                                  │
│      mysql:                                                   │
│        image: mysql:8.0          ← 直接用现成镜像             │
│                                                              │
│      java-server:                                             │
│        build:                                                 │
│          context: ./apps/java-server                          │
│          dockerfile: Dockerfile  ← 指向 Dockerfile 去构建     │
│                                                              │
│      node-server:                                             │
│        build:                                                 │
│          context: ./apps/node-server                          │
│          dockerfile: Dockerfile  ← 指向 Dockerfile 去构建     │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │  "Compose 负责编排，Dockerfile 负责打包"
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │Dockerfile│  │Dockerfile│  │ 现成镜像  │
  │(Java)    │  │(Node)    │  │ (MySQL)  │
  │          │  │          │  │          │
  │ 如何打包  │  │ 如何打包  │  │ 已打包好  │
  │ Java 应用 │  │ Node 应用│  │ 直接使用  │
  └──────────┘  └──────────┘  └──────────┘
```

**一句话总结**：
- **Dockerfile** = 如何把一个应用打包成镜像（"包装盒的制作说明"）
- **docker-compose.yml** = 如何把多个镜像组合起来运行（"多个包装盒如何摆放和连接"）

### Docker 完整运行机制

```
┌──────────────────────────────────────────────────────────────────┐
│                     Docker 完整架构                               │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Docker CLI（你输入命令的地方）                                │  │
│  │   docker compose up -d                                     │  │
│  │   docker build ...                                          │  │
│  │   docker run ...                                            │  │
│  └────────────────────┬───────────────────────────────────────┘  │
│                       │ REST API（CLI 和 Daemon 通过 API 通信）   │
│  ┌────────────────────▼───────────────────────────────────────┐  │
│  │ Docker Daemon（dockerd，后台守护进程）                       │  │
│  │                                                             │  │
│  │  接收 CLI 的请求，执行实际操作：                               │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐  │  │
│  │  │ 镜像管理     │  │ 容器管理      │  │ 网络/卷管理       │  │  │
│  │  │ build/pull   │  │ create/start │  │ network/volume   │  │  │
│  │  └──────┬──────┘  └──────┬───────┘  └──────────────────┘  │  │
│  │         │                │                                  │  │
│  │  ┌──────▼──────┐  ┌─────▼────────────────────────────┐    │  │
│  │  │ containerd  │  │ runc（OCI 标准容器运行时）          │    │  │
│  │  │ 镜像存储管理 │  │                                    │    │  │
│  │  └─────────────┘  │ 创建真正的容器进程：                │    │  │
│  │                    │  ┌─────────────────────────────┐  │    │  │
│  │                    │  │ Linux Namespace（隔离）       │  │    │  │
│  │                    │  │  PID namespace → 独立进程树   │  │    │  │
│  │                    │  │  NET namespace → 独立网络栈   │  │    │  │
│  │                    │  │  MNT namespace → 独立文件系统 │  │    │  │
│  │                    │  │  UTS namespace → 独立主机名   │  │    │  │
│  │                    │  └─────────────────────────────┘  │    │  │
│  │                    │  ┌─────────────────────────────┐  │    │  │
│  │                    │  │ Linux cgroups（资源限制）     │  │    │  │
│  │                    │  │  CPU 限制                    │  │    │  │
│  │                    │  │  内存限制                     │  │    │  │
│  │                    │  │  IO 限制                     │  │    │  │
│  │                    │  └─────────────────────────────┘  │    │  │
│  │                    │  ┌─────────────────────────────┐  │    │  │
│  │                    │  │ UnionFS（分层文件系统）       │  │    │  │
│  │                    │  │  镜像层1（只读）             │  │    │  │
│  │                    │  │  镜像层2（只读）             │  │    │  │
│  │                    │  │  ...                        │  │    │  │
│  │                    │  │  容器层（可写）              │  │    │  │
│  │                    │  └─────────────────────────────┘  │    │  │
│  │                    └────────────────────────────────────┘    │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ Docker Registry（镜像仓库，如 Docker Hub）                    │  │
│  │   存储和分发镜像：mysql:8.0, node:22-alpine, redis:7 ...     │  │
│  └─────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────┘
```

### Docker 不是虚拟机

这是最重要的概念区别：

```
虚拟机（VMware / VirtualBox）              Docker 容器
┌──────────────────────┐                  ┌──────────────────────┐
│ App A     App B      │                  │ App A     App B      │
├──────────────────────┤                  ├──────────┬───────────┤
│ Guest OS  Guest OS   │  ← 每个 VM      │ 容器 A    │ 容器 B    │
│ (Ubuntu)  (CentOS)   │    一个完整 OS    │ (隔离的进程)│(隔离的进程)│
├──────────────────────┤                  ├──────────┴───────────┤
│ Hypervisor (VMM)     │  ← 虚拟化层      │ Docker Engine        │
├──────────────────────┤                  ├──────────────────────┤
│ Host OS (Windows)    │                  │ Host OS (Windows)    │
├──────────────────────┤                  ├──────────────────────┤
│ Hardware             │                  │ Hardware             │
└──────────────────────┘                  └──────────────────────┘

启动速度：分钟级                           启动速度：秒级
资源开销：GB 级（每个 VM 运行完整 OS）      资源开销：MB 级（共享宿主机内核）
隔离级别：强（硬件级虚拟化）               隔离级别：中（进程级隔离）
```

**Docker 容器的本质是"被隔离的普通 Linux 进程"**，通过 Linux 内核的 Namespace 和 cgroups 机制实现隔离和资源限制。容器不需要自己的操作系统内核，直接共享宿主机的内核。

### 从 `docker compose up` 到容器运行的完整流程

```
1. docker compose up -d
   │
2. │ 读取 docker-compose.yml
   │ 读取 --env-file 中的环境变量
   │ 解析所有 ${VARIABLE:-default}
   │
3. │ 对每个有 build: 的服务
   ├──── 读取 Dockerfile
   ├──── 发送 context 目录到 Docker Daemon（排除 .dockerignore 中的文件）
   ├──── 逐行执行 Dockerfile 指令
   │     ├── FROM → 拉取基础镜像（如果本地没有）
   │     ├── COPY → 复制文件到镜像层
   │     ├── RUN  → 执行命令，结果保存为新的镜像层
   │     └── 每一步都检查缓存，未变化则直接复用
   └──── 生成最终镜像（image）
   │
4. │ 对每个用 image: 的服务
   └──── 检查本地是否有该镜像，没有就从 Docker Hub 拉取
   │
5. │ 创建 Docker 网络（所有服务共享一个虚拟网络）
   │ 注册 DNS：每个服务名 → 容器 IP（如 mysql → 172.18.0.2）
   │
6. │ 按 depends_on 排序，依次启动容器
   │ 每个容器：
   │   ├── 创建 Namespace（PID/NET/MNT）
   │   ├── 设置 cgroups（CPU/内存限制）
   │   ├── 挂载文件系统（镜像层 + 可写层 + volumes）
   │   ├── 配置网络（分配 IP、加入网桥）
   │   ├── 注入环境变量
   │   └── 执行 ENTRYPOINT/CMD 启动应用进程
   │
7. │ 容器进入运行状态
   │ healthcheck 开始定期检查
   │ depends_on 等待 service_healthy 后再启动下一个
   │
8. └─ 所有服务启动完毕，打印容器状态
```

### Docker 镜像的分层结构

```
镜像层（Image Layers）—— 只读，共享，可缓存

┌──────────────────────────────────────┐
│ Layer 7: ENTRYPOINT java -jar app.jar│  ← Dockerfile 最后一条指令
├──────────────────────────────────────┤
│ Layer 6: RUN mkdir -p /app/storage   │  ← 创建目录
├──────────────────────────────────────┤
│ Layer 5: COPY --from=builder app.jar │  ← 复制 JAR
├──────────────────────────────────────┤
│ Layer 4: WORKDIR /app                │  ← 设置工作目录
├──────────────────────────────────────┤
│ Layer 3: eclipse-temurin:17-jre      │  ← JRE 运行时
├──────────────────────────────────────┤
│ Layer 2: Ubuntu 基础文件系统          │  ← 基础 OS
├──────────────────────────────────────┤
│ Layer 1: 内核引导文件                │  ← 最底层
└──────────────────────────────────────┘

每一层都是上一层的"增量"——只存储变化的部分。
多个镜像如果共享基础层（如都基于 Ubuntu），磁盘上只存一份。
```

---

## 10. 外部环境变量如何进入 Docker 容器

### 环境变量的三层传递链

```
第一层：.env.docker 文件                  第二层：docker-compose.yml              第三层：容器内部
─────────────────────                    ──────────────────────                 ──────────────
MYSQL_ROOT_PASSWORD=root           →     environment:                      →   容器进程的环境变量
                                           MYSQL_PASSWORD: ${MYSQL_ROOT_PASSWORD:-root}
                                                                               echo $MYSQL_PASSWORD
                                                                               → root
```

### 详细流程

#### 第一层：从 .env.docker 文件读取

```bash
docker compose --env-file .env.docker up -d
```

Docker Compose 读取 `.env.docker` 文件，把里面的键值对加载到 Compose 的**替换上下文**中。

#### 第二层：替换 docker-compose.yml 中的变量

Compose 扫描 `docker-compose.yml` 中所有 `${...}` 占位符，用第一层加载的变量替换：

#### 第三层：注入容器环境变量

Compose 把替换后的 `environment` 字段中的每一对键值，通过 Docker API 注入到容器进程的环境中。

**底层原理**：Docker 创建容器时，通过 Linux 的 `execve` 系统调用启动应用进程，并在调用参数中传入环境变量列表。

```c
// 简化版 Linux 进程创建
execve("/usr/bin/java",
       ["java", "-jar", "app.jar"],        // 命令行参数
       ["MYSQL_PASSWORD=root",             // 环境变量列表
        "REDIS_HOST=redis",
        "JWT_SECRET=my-secret",
        ...]);
```

容器内的应用代码通过各语言标准 API 读取：

```java
// Java
String password = System.getenv("MYSQL_PASSWORD");  // → "root"
```

```javascript
// Node.js
const token = process.env.INTERNAL_TOKEN;  // → "my-secret-token"
```

```properties
# Spring Boot application.properties 自动读取环境变量
spring.datasource.password=${MYSQL_PASSWORD:root}
# MYSQL_PASSWORD 环境变量存在 → 使用环境变量的值
# 不存在 → 使用 : 后面的默认值 root
```

### 环境变量注入的三种方式对比

```yaml
services:
  java-server:
    # 方式一：在 environment 中直接定义
    environment:
      REDIS_HOST: redis                    # 固定值
      MYSQL_PASSWORD: ${MYSQL_ROOT_PASSWORD:-root}  # 从 .env 文件读取

    # 方式二：从文件批量导入（会导入文件中所有变量）
    env_file:
      - .env.docker

    # 方式三：继承宿主机的环境变量
    environment:
      HOME:    # 只写 key 不写 value → 继承宿主机的 $HOME
```

| 方式 | 适用场景 |
|------|---------|
| `environment` + `${VAR}` | 需要精确控制每个变量的名称和默认值（我们的项目用的方式） |
| `env_file` | 变量很多且容器内外变量名一致时，批量导入最方便 |
| 继承宿主机变量 | 少见，偶尔用于传递 CI/CD 变量 |

**注意变量名可以在传递过程中改变**：

```yaml
# .env.docker 中叫 INTERNAL_TOKEN
# 传给 Java 容器时重命名为 AI_GATEWAY_API_KEY
AI_GATEWAY_API_KEY: ${INTERNAL_TOKEN:-change-me}
```

这让同一个密钥（INTERNAL_TOKEN）在不同服务中可以有不同的变量名，符合各自应用的配置规范。

---

## 11. 补充问答

### Q1：logs、ps、restart 这些命令又不是启动命令，为什么还要带 `--env-file .env.docker`？

这是一个非常好的观察。答案是：**`--env-file` 不是给容器用的，是给 Compose 自己用的——它需要环境变量来"认出"是哪组服务。**

`docker-compose.yml` 中大量使用了 `${VARIABLE:-default}` 占位符（如端口号、容器名等）。Compose 在执行**任何命令**时都需要先**解析**这个 YAML 文件，把占位符替换为实际值，才能知道：

- `logs java-server` → 要看哪个容器的日志？容器名是什么？
- `ps` → 哪些容器属于这个 compose 项目？
- `restart java-server` → 要重启的容器端口配置是什么？

```
docker compose --env-file .env.docker logs java-server

步骤一：读取 .env.docker → 获得变量值
步骤二：解析 docker-compose.yml → 替换所有 ${...} → 得到完整的服务定义
步骤三：根据解析结果找到 java-server 对应的容器
步骤四：执行 docker logs <容器ID>
```

**如果不带 `--env-file` 会怎样？**

Compose 默认会找当前目录的 `.env` 文件。如果 `.env` 不存在且 yml 中有必填的 `${VARIABLE}`（没有 `:-default` 默认值），Compose 会报错或使用空字符串，可能导致找不到对应的容器。

**实际上**，我们的 compose 文件中所有变量都带了 `:-default` 默认值，所以不带 `--env-file` 大多数情况下也能用——只是会使用默认值而不是你自定义的值。但养成好习惯，始终带上 `--env-file` 最安全。

**简化方案**：如果觉得每次都带 `--env-file` 太啰嗦，可以直接把 `.env.docker` 改名为 `.env`，这样 Compose 会自动读取，所有命令都不需要加 `--env-file` 了。

---

### Q2：什么是 IP 地址和网络栈？

#### IP 地址

IP 地址是网络中设备的"门牌号"——数据包要从 A 发送到 B，必须知道 B 的 IP 地址。

两种 IP 地址类型：

| 类型 | 格式 | 范围 | 用途 |
|------|------|------|------|
| IPv4 | `192.168.1.100` | 4 组 0-255 的数字 | 目前最常用 |
| IPv6 | `2001:db8::1` | 更长的地址 | 解决 IPv4 地址耗尽问题 |

**私有 IP vs 公网 IP**：

```
互联网（公网）
│
├── 你家路由器：公网 IP 114.80.x.x（运营商分配，全球唯一）
│   │
│   ├── 你的电脑：192.168.1.100（私有 IP，仅局域网内可见）
│   ├── 你的手机：192.168.1.101
│   └── Docker 容器：172.17.0.2（Docker 内部私有 IP，仅 Docker 网络内可见）
```

#### 网络栈（Network Stack）

网络栈是操作系统中处理网络通信的**一整套软件层**，从底层到高层依次是：

```
┌────────────────────────────────────┐
│ 应用层（你的代码）                   │
│ HTTP 请求 GET /api                 │  ← 你写的 fetch("http://...")
├────────────────────────────────────┤
│ 传输层（TCP / UDP）                 │
│ 建立连接、保证数据可靠到达           │  ← 操作系统内核处理
│ 端口号（如 :3000、:3101）在这一层   │
├────────────────────────────────────┤
│ 网络层（IP 协议）                   │
│ 寻址、路由（数据走哪条路到目的地）    │  ← 路由表、IP 地址在这一层
├────────────────────────────────────┤
│ 数据链路层 + 物理层                  │
│ 实际的电信号 / 无线信号传输          │  ← 网卡、网线、WiFi
└────────────────────────────────────┘
```

**"独立的网络栈"意味着什么？**

每个 Docker 容器拥有自己的：
- **自己的 IP 地址**：172.17.0.2（不是宿主机的 192.168.1.100）
- **自己的端口空间**：容器 A 和容器 B 都可以监听 3000 端口，互不冲突
- **自己的路由表**：决定数据包怎么转发
- **自己的 localhost**：`127.0.0.1` 指向容器自己，不是宿主机

```
宿主机网络栈                    容器 A 网络栈                 容器 B 网络栈
├── IP: 192.168.1.100          ├── IP: 172.17.0.2           ├── IP: 172.17.0.3
├── localhost → 自己            ├── localhost → 容器A自己      ├── localhost → 容器B自己
├── 端口 3000 → Java            ├── 端口 3000 → Java          ├── 端口 3101 → Node
└── 路由表 → 互联网             └── 路由表 → Docker 网桥      └── 路由表 → Docker 网桥
```

**类比**：每个容器就像一栋独立的公寓楼，有自己的门牌号（IP）、自己的楼层编号（端口）、自己的信箱（localhost）。它们通过公共道路（Docker 网桥）互相通信。

---

### Q3：VM 的默认网关 IP 为什么就是宿主机？

#### 什么是网关（Gateway）？

网关是"网络的出口"——当一个设备要访问**不在自己网络内**的地址时，数据包会被发送到网关，由网关负责转发。

```
你家的网络：
├── 电脑 192.168.1.100
├── 手机 192.168.1.101
│
└── 路由器 192.168.1.1 ← 这就是"默认网关"
    │
    └── 连接到互联网
```

当你的电脑要访问 `google.com`（不在 192.168.1.x 网段），数据包会发给网关（路由器 192.168.1.1），路由器再转发到互联网。

#### Docker Desktop 的虚拟机网络

在 Windows/Mac 上，Docker 运行在一个 LinuxKit 虚拟机中：

```
宿主机（Windows/Mac）
├── IP: 192.168.65.254（在 VM 看来这就是"网关"）
│
└── LinuxKit VM（Docker 的底层 Linux）
    ├── VM 自己的 IP: 192.168.65.3
    ├── VM 的默认网关: 192.168.65.254 ← 指向宿主机
    │
    └── 容器
        ├── 容器 IP: 172.17.0.2
        └── 要访问宿主机的 Ollama → 发给谁？
```

**VM 被创建时，Docker Desktop 设置了一个虚拟网络**，这个网络有两端：
- 一端在 VM 内部（192.168.65.3）
- 另一端在宿主机上（192.168.65.254）

对 VM 来说，要访问"外面的世界"（包括宿主机），唯一的出口就是这个虚拟网络的另一端——宿主机。所以**宿主机天然就是 VM 的网关**。
```
---

### Q4：核心名词和概念详解

#### Docker 网桥（Docker Bridge）

网桥是一种**虚拟的网络交换机**，让多个容器像连接在同一个局域网中一样互相通信。

```
┌──────────────────────────────────────────────────┐
│ 宿主机                                            │
│                                                    │
│  ┌──────────────────────────────────────────────┐ │
│  │ docker0 网桥（虚拟交换机）                      │ │
│  │ IP: 172.17.0.1  ← 宿主机在网桥上的 IP          │ │
│  │                                                │ │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐       │ │
│  │  │容器 A    │  │容器 B    │  │容器 C    │       │ │
│  │  │172.17.0.2│  │172.17.0.3│  │172.17.0.4│       │ │
│  │  └─────────┘  └─────────┘  └─────────┘       │ │
│  └──────────────────────────────────────────────┘ │
│                                                    │
│  网桥的 IP 172.17.0.1 就是"宿主机在 Docker 网桥上的 IP"  │
│  容器访问 172.17.0.1 就是在访问宿主机                │
└──────────────────────────────────────────────────┘
```

**类比**：网桥就像一个交换机/路由器，把所有容器连在一个虚拟局域网中。容器 A 要和容器 B 通信，数据包通过网桥转发。

#### 虚拟网桥（Virtual Bridge）

和上面的 Docker 网桥是同一个东西，"虚拟"强调的是它不是物理硬件设备（不是你买的路由器），而是操作系统内核用软件模拟出来的。Linux 内核原生支持创建虚拟网桥（`brctl` 命令或 `ip link add type bridge`）。

#### Linux 内核（Kernel）

操作系统的核心，是**硬件和软件之间的桥梁**。

```
┌──────────────────────────────┐
│ 应用程序                      │
│ (Java, Node, MySQL, 浏览器)   │
├──────────────────────────────┤  ← 系统调用接口（应用和内核的边界）
│ Linux 内核（Kernel）          │
│                              │
│ ├── 进程管理   （创建/调度进程）│
│ ├── 内存管理   （分配/回收内存）│
│ ├── 文件系统   （读写磁盘文件）│
│ ├── 网络栈     （处理网络通信）│
│ ├── 设备驱动   （控制硬件设备）│  ← GPU 驱动就在这一层
│ └── 安全模块   （权限控制）    │
├──────────────────────────────┤
│ 硬件                          │
│ (CPU, 内存, 硬盘, 网卡, GPU)  │
└──────────────────────────────┘
```

**关键理解**：应用程序不能直接操作硬件，必须通过内核。比如你写 `fs.readFile()` 读文件，底层是 Node 调用了内核的 `read()` 系统调用，内核再操作磁盘硬件。

**Docker 容器共享宿主机的内核**——这就是容器比虚拟机快的核心原因：不需要启动一个新的内核。

#### GPU 驱动是内核模块

**驱动程序（Driver）** 是内核的扩展模块，教内核如何与特定硬件设备通信。

```
应用程序调用 CUDA API
    │
    ▼
CUDA 运行时库（用户态）
    │
    ▼ 系统调用
内核中的 NVIDIA 驱动模块（nvidia.ko）
    │
    ▼ PCIe 总线通信
GPU 硬件（NVIDIA RTX 4090 等）
```

- **内核模块（.ko 文件）**：可以动态加载到内核中的代码。`nvidia.ko` 就是 NVIDIA GPU 的内核驱动
- **为什么容器访问 GPU 困难**：驱动在宿主机内核中运行，容器虽然共享内核，但默认看不到 `/dev/nvidia*` 设备文件

#### CUDA Toolkit / cuDNN

```
┌─────────────────────────────────┐
│ 你的 AI 应用（Ollama、PyTorch）  │  ← 最上层
├─────────────────────────────────┤
│ cuDNN（深度神经网络加速库）       │  ← NVIDIA 提供的高级 AI 库
├─────────────────────────────────┤
│ CUDA Toolkit（GPU 编程工具包）    │  ← NVIDIA 提供的 GPU 编程框架
│ 包含：编译器(nvcc)、运行时、数学库 │
├─────────────────────────────────┤
│ NVIDIA 驱动（内核模块）           │  ← 控制 GPU 硬件
├─────────────────────────────────┤
│ GPU 硬件                         │  ← 物理设备
└─────────────────────────────────┘
```

- **CUDA**：NVIDIA 创造的 GPU 编程平台，让程序员可以用 GPU 做通用计算（不仅仅是显示图像）
- **cuDNN**：基于 CUDA 的深度学习加速库，为卷积、RNN 等神经网络运算提供高度优化的实现
- **"安装在可见的文件系统中"**：CUDA/cuDNN 是一堆 `.so` 动态链接库文件（如 `libcudart.so`），应用程序在运行时需要加载它们。如果在容器中运行 AI 应用，容器的文件系统中必须有这些库文件

#### AOF 持久化（Redis）

Redis 是内存数据库——数据存在内存中，速度快但断电丢失。AOF 是 Redis 的一种数据持久化策略：

```
AOF = Append-Only File（只追加文件）

Redis 工作流程（开启 AOF 后）：
1. 客户端发送命令：SET user:1 "Tom"
2. Redis 在内存中执行命令
3. Redis 把这条命令追加写入 AOF 文件（appendonly.aof）
4. 下次 Redis 重启时，重放 AOF 文件中的所有命令，恢复数据

┌─────────────────────────────┐
│ appendonly.aof（磁盘文件）    │
│                             │
│ SET user:1 "Tom"            │  ← 第 1 条命令
│ SET user:2 "Jerry"          │  ← 第 2 条命令
│ DEL user:1                  │  ← 第 3 条命令
│ ...                         │
└─────────────────────────────┘
```

Redis 还有另一种持久化方式 RDB（定期快照），两者可以同时使用。`--appendonly yes` 就是开启 AOF。

#### 操作系统内核（OS Kernel）

操作系统分为两部分：

```
┌──────────────────────────┐
│ 用户空间（User Space）    │  ← 你的应用程序运行在这里
│ Shell、浏览器、Java、Node │
├──────────────────────────┤  ← 系统调用边界
│ 内核空间（Kernel Space）  │  ← 操作系统核心运行在这里
│ 进程调度、内存管理、驱动  │
├──────────────────────────┤
│ 硬件                      │
└──────────────────────────┘
```

- **内核（Kernel）**：操作系统最核心的部分，拥有对硬件的完全控制权
- **用户空间**：普通应用程序运行的地方，不能直接操作硬件，必须通过"系统调用"请求内核代劳
- **Windows 的内核**叫 NT Kernel，**macOS 的内核**叫 XNU（Darwin），**Linux 的内核**叫 Linux

Docker 容器共享的就是 Linux 内核（Windows/Mac 上 Docker 通过虚拟机运行一个 Linux 内核）。

---

### Q5：宿主机性能全面优于容器，为什么大规模生产还选容器？

**因为大规模集群需要的不是"单机极致性能"，而是"大规模自动化管理"。**

#### 100 台服务器的视角（大厂生产环境）

假设你有 100 台 GPU 服务器，要跑 200 个不同的 AI 模型服务：

**不用容器（宿主机部署）**：
```
服务器 1：手动安装驱动 → 手动装 CUDA → 手动装 Ollama → 手动配置端口 → 手动配置监控
服务器 2：重复上述步骤（但驱动版本可能不一致…）
服务器 3：重复……
...
服务器 100：已经过去三天了，第 37 台机器的驱动和 CUDA 版本不兼容
```

**用容器（K8s + GPU）**：
```yaml
# 写一个配置文件，K8s 自动在 100 台机器上部署
apiVersion: apps/v1
kind: Deployment
spec:
  replicas: 200                          # 200 个实例
  template:
    spec:
      containers:
      - image: ollama/ollama:latest       # 包含了 CUDA + 依赖
        resources:
          limits:
            nvidia.com/gpu: 1             # 每个容器分配 1 个 GPU
```

**执行一条命令 → K8s 自动在 100 台机器上调度部署 200 个实例 → 某台机器挂了自动迁移到其他机器 → 流量自动负载均衡**

| 需求 | 宿主机部署 | 容器化部署（K8s） |
|------|----------|----------------|
| 环境一致性 | 每台手动装，容易不一致 | 镜像保证 100% 一致 |
| 扩缩容 | 手动加机器、手动装环境 | `kubectl scale --replicas=300` 一条命令 |
| 故障恢复 | 人工排查、重新部署 | 自动检测异常、自动重启、自动迁移 |
| 资源利用率 | 一台机器跑一个服务，资源浪费 | K8s 动态调度，GPU 利用率最大化 |
| 版本更新 | 逐台登录更新 | 滚动更新，一条命令，自动金丝雀发布 |
| 监控告警 | 逐台配置 | 统一 Prometheus/Grafana 监控 |

### Q7：healthcheck 的 test 只支持 CMD 和 CMD-SHELL 两种吗？CMD 是什么？

#### 支持的格式

Docker healthcheck 的 `test` 字段支持**三种格式**：

```yaml
# 格式一：CMD — 直接执行，不经过 Shell
test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]

# 格式二：CMD-SHELL — 通过 /bin/sh -c 执行
test: ["CMD-SHELL", "wget -qO- http://localhost:3101/api || exit 1"]

# 格式三：NONE — 禁用健康检查
test: ["NONE"]
```
#### CMD 是什么？

这里的 `CMD` 不是 Dockerfile 中的 `CMD` 指令，也不是 Windows 的 `cmd.exe`。它是 Docker healthcheck 的**执行模式标记**：

| 标记 | 含义 | 底层行为 |
|------|------|---------|
| `CMD` | 直接执行 | Docker 直接调用 `exec` 系统调用运行指定的可执行文件，参数逐个传递 |
| `CMD-SHELL` | 通过 Shell 执行 | Docker 先启动 `/bin/sh`，然后让 Shell 来执行后面的字符串 |

#### CMD 和 Shell 的关系

```
CMD 模式：
Docker → exec("mysqladmin", ["ping", "-h", "localhost"])
         直接启动 mysqladmin 进程，不经过任何中间环节

CMD-SHELL 模式：
Docker → exec("/bin/sh", ["-c", "wget -qO- http://... || exit 1"])
         先启动 Shell（/bin/sh），Shell 再解析并执行命令字符串
         Shell 负责处理 ||、&&、|、>、$变量 等特殊语法
```

**什么时候用哪个？**

- **CMD**：命令简单，不需要管道、逻辑运算等 Shell 语法时用。性能稍好（少一层 Shell）
- **CMD-SHELL**：需要 `||`、`&&`、`|`、`$变量`、重定向等 Shell 功能时必须用

#### Shell 是什么？

Shell 是"命令行解释器"——你在终端（PowerShell、Terminal）中输入命令，是 Shell 在帮你解析和执行。

```
你输入：ls -la | grep ".txt" && echo "found"
         │        │             │
         Shell 解析：
         ├── ls -la           → 执行 ls 命令
         ├── | grep ".txt"    → 把 ls 的输出通过管道传给 grep
         └── && echo "found"  → 如果 grep 成功，执行 echo
```

Linux 常见的 Shell 有 `bash`（功能丰富）、`sh`（最基础）、`zsh`、`fish` 等。Docker 容器中通常是 `/bin/sh`（Alpine 镜像中实际是 `busybox ash`）。

---

### Q8：`-XX:+UseContainerSupport` 这些是 Java 内置的命令吗？

**是的，它们是 JVM（Java Virtual Machine）的内置启动参数。**

```bash
java -XX:+UseContainerSupport -XX:MaxRAMPercentage=75.0 -jar app.jar
│    │                        │                          │
│    │                        │                          └── -jar：标准参数，指定运行哪个 JAR
│    │                        └── -XX:MaxRAMPercentage：非标准参数，设置最大堆内存百分比
│    └── -XX:+UseContainerSupport：非标准参数，启用容器感知
└── java：JDK 提供的启动命令
```

#### Java 启动参数分三类

| 前缀 | 类型 | 稳定性 | 例子 |
|------|------|--------|------|
| `-`（无前缀） | 标准参数 | 所有 JVM 实现都支持 | `-jar`、`-version`、`-classpath` |
| `-X` | 非标准参数 | 大多数 JVM 支持但不保证 | `-Xmx512m`（最大堆内存 512MB） |
| `-XX:` | 高级参数 | 仅 HotSpot JVM 支持，可能随版本变化 | `-XX:+UseG1GC`（使用 G1 垃圾回收器） |

#### `-XX:+UseContainerSupport` 为什么需要？

**问题**：JVM 默认根据**物理机的总内存**来决定堆内存大小。如果宿主机有 32GB 内存，但容器只分配了 1GB，JVM 会以为自己有 32GB 可用，分配过多内存后被操作系统直接 kill（OOM Killed）。

```
宿主机 32GB 内存
└── 容器限制 1GB
    └── JVM 以为有 32GB → 分配 8GB 堆 → 超过 1GB 限制 → 被杀

加了 UseContainerSupport：
└── 容器限制 1GB
    └── JVM 检测到容器限制 → 只按 1GB 来计算 → 分配 750MB 堆 → 正常运行
```

**`-XX:MaxRAMPercentage=75.0`**：堆内存最多占容器可用内存的 75%。剩余 25% 留给：
- JVM 的非堆内存（Metaspace、Code Cache）
- 线程栈
- NIO Direct Buffer
- 操作系统开销

---

### Q9：`COPY . .` 为什么是复制全部？

```dockerfile
COPY . .
     │ │
     │ └── 目标路径：. = 当前 WORKDIR（即 /build）
     └── 源路径：. = context 目录的根（即 docker-compose.yml 中指定的 context）
```

**`.`（点）在文件系统中表示"当前目录"**，所以 `COPY . .` 的含义是"把 context 目录中的**所有文件和子目录**复制到容器的 WORKDIR 中"。

### Q10：CMD 和 ENTRYPOINT 的"覆盖"具体是什么操作？

#### 场景一：正常使用（不覆盖）

```bash
docker run my-java-server
```

容器启动时执行 Dockerfile 中定义的 `ENTRYPOINT` 或 `CMD`。

#### 场景二：覆盖 CMD

**Node 的 Dockerfile 用的是 CMD**：

```dockerfile
CMD ["node", "dist/main"]
```

当你手动运行容器时，可以替换这个命令：

```bash
# 正常启动（使用默认 CMD）
docker run my-node-server
# → 执行 node dist/main

# 覆盖 CMD — 在 docker run 后面直接写新命令
docker run my-node-server node --inspect dist/main
# → 执行 node --inspect dist/main（加了调试模式）

docker run my-node-server sh
# → 进入容器的 Shell（不启动 Node 应用，用于调试容器环境）

docker run my-node-server ls -la
# → 列出容器内的文件（查看目录结构）
```

**`docker run <镜像> <命令>` 中 `<命令>` 部分会完全替换 Dockerfile 的 CMD。**

#### 场景三：ENTRYPOINT 不被覆盖

**Java 的 Dockerfile 用的是 ENTRYPOINT**：

```dockerfile
ENTRYPOINT ["java", "-XX:+UseContainerSupport", "-XX:MaxRAMPercentage=75.0", "-jar", "app.jar"]
```

```bash
# 正常启动
docker run my-java-server
# → 执行 java -XX:+UseContainerSupport -XX:MaxRAMPercentage=75.0 -jar app.jar

# 尝试"覆盖" — 你传的参数会被追加，不是替换！
docker run my-java-server --spring.profiles.active=local
# → 执行 java ... -jar app.jar --spring.profiles.active=local
#   你的参数被追加到 ENTRYPOINT 的末尾

# 如果你真的要覆盖 ENTRYPOINT（很少需要），必须用 --entrypoint
docker run --entrypoint sh my-java-server
# → 进入 Shell（绕过了 ENTRYPOINT）
```

#### 什么时候会遇到这些操作？

| 场景 | 操作 | 说明 |
|------|------|------|
| 调试容器 | `docker run my-node sh` | 进入容器 Shell 查看文件 |
| 临时加启动参数 | `docker run my-java -- --spring.profiles.active=test` | 追加 Spring 参数 |
| CI/CD 中跑测试 | `docker run my-node pnpm test` | 在容器环境中执行测试 |
| docker compose exec | `docker compose exec java-server sh` | 进入运行中的容器排查问题 |

### Q11：Docker 容器的本质——Namespace 和 cgroups 详解

#### 一句话总结

**Docker 容器 = 一组被 Linux Namespace 隔离、被 cgroups 限制资源的普通进程。** 没有虚拟机，没有新内核，只是同一个 Linux 内核上的进程隔离。

#### Namespace（命名空间）—— 隔离

Namespace 让一组进程"看到"一个独立的系统视图，以为自己运行在一台独立的机器上。

Linux 提供了 8 种 Namespace，Docker 主要使用其中 6 种：

| Namespace | 隔离的内容 | 容器内的感受 |
|-----------|-----------|-------------|
| **PID** | 进程 ID | 容器内看到的进程从 PID 1 开始，看不到宿主机的其他进程 |
| **NET** | 网络 | 容器有独立的 IP、端口、路由表、`localhost` |
| **MNT** | 文件系统挂载 | 容器有独立的根文件系统（`/`），看不到宿主机的文件 |
| **UTS** | 主机名 | 容器有自己的 hostname（`agent-java-server`） |
| **IPC** | 进程间通信 | 容器内的共享内存、消息队列等与宿主机隔离 |
| **USER** | 用户 ID | 容器内的 root (UID 0) 可以映射为宿主机的普通用户 |

**PID Namespace 示例**：

```
宿主机进程列表（宿主机看到的）：
PID 1     → systemd（系统初始化进程）
PID 1234  → dockerd（Docker 守护进程）
PID 5678  → java -jar app.jar（容器内的 Java 进程）
PID 5679  → node dist/main（容器内的 Node 进程）
PID 5680  → mysqld（容器内的 MySQL 进程）

Java 容器内看到的（被 PID Namespace 隔离后）：
PID 1     → java -jar app.jar（在容器内它是"1号进程"）
                               （看不到其他任何进程）

Node 容器内看到的：
PID 1     → node dist/main（在容器内它是"1号进程"）
                            （看不到其他任何进程）
```

**NET Namespace 示例**：

```
宿主机网络：
IP: 192.168.1.100
端口 3000: 被占用（映射到 Java 容器）
端口 3101: 被占用（映射到 Node 容器）

Java 容器的网络（独立）：
IP: 172.17.0.5
端口 3000: Java 监听（在容器内的 3000 端口）
localhost = 172.17.0.5

Node 容器的网络（独立）：
IP: 172.17.0.6
端口 3101: Node 监听
localhost = 172.17.0.6
```

#### cgroups（Control Groups）—— 资源限制

Namespace 解决了"隔离"（看不到别人），cgroups 解决了"限制"（不能用太多资源）。

没有 cgroups 的话，一个容器可能吃光宿主机所有内存，导致其他容器和宿主机本身崩溃。

```
宿主机总资源：16GB 内存, 8 核 CPU

cgroups 限制：
├── Java 容器：最多 4GB 内存, 2 核 CPU
├── Node 容器：最多 2GB 内存, 1 核 CPU
├── MySQL 容器：最多 4GB 内存, 2 核 CPU
└── 剩余给宿主机和其他容器

如果 Java 容器尝试分配 5GB 内存 → cgroups 拒绝 → OOM Killer 终止进程
```

cgroups 可以限制的资源：

| 资源 | 说明 | docker compose 配置 |
|------|------|-------------------|
| 内存 | 最大可用内存 | `deploy.resources.limits.memory: 4g` |
| CPU | 可用 CPU 份额/核数 | `deploy.resources.limits.cpus: '2.0'` |
| 磁盘 IO | 读写速度限制 | `device_write_bps` 等 |
| 网络带宽 | 网络流量限制 | 通过 tc (traffic control) |

#### UnionFS（联合文件系统）—— 分层镜像

这是 Docker 镜像分层存储的底层实现：

```
镜像层（只读）                              容器层（可写）
┌──────────────────────┐                 ┌─────────────────────┐
│ Layer 1: Ubuntu 基础  │ ← 所有基于       │ 容器运行时写入的文件  │
│ Layer 2: JRE 17      │   Ubuntu 的镜像   │ - 日志文件           │
│ Layer 3: app.jar     │   共享 Layer 1    │ - 临时文件           │
└──────────────────────┘                 └─────────────────────┘
        │                                          │
        └─────────── UnionFS 合并为一个视图 ────────┘
                            │
                 ┌──────────▼──────────┐
                 │ 容器看到的文件系统    │
                 │ / (根目录)           │
                 │ ├── usr/lib/jre/    │ ← 来自 Layer 2
                 │ ├── app/app.jar     │ ← 来自 Layer 3
                 │ └── tmp/debug.log   │ ← 来自容器层（运行时生成）
                 └─────────────────────┘
```

**UnionFS 把多个只读层和一个可写层"叠"在一起**，对容器来说就像一个完整的文件系统。修改文件时使用 **Copy-on-Write（写时复制）**——先把要修改的文件从只读层复制到可写层，然后修改可写层的副本。

#### 为什么说"不是虚拟机"？

```
虚拟机方式：
宿主机内核 → Hypervisor → Guest OS 内核 → 应用进程
                          （一个完整的操作系统！）

Docker 方式：
宿主机内核 → 应用进程（被 Namespace/cgroups 隔离）
             （没有 Guest OS，直接用宿主机内核！）
```

- 虚拟机：每个 VM 运行一个完整的操作系统（包括自己的内核），开销大，启动慢（分钟级）
- 容器：所有容器共享宿主机的一个内核，只是用 Namespace 让彼此"看不到对方"，开销极小，启动快（秒级）

这就是为什么一台机器能跑几十个容器但只能跑几个虚拟机——容器没有重复运行操作系统的开销。

---

### Q12：容器内默认只有一个 `/app` 根目录吗？怎么自定义？

**不是的。`/app` 不是容器的根目录，也不是默认存在的——它是我们通过 `WORKDIR` 指令自己创建的。**

#### 容器内的真实目录结构

容器拥有一个**完整的 Linux 文件系统**，根目录是 `/`，和一台普通 Linux 机器一样：

```
/                        ← 容器的真正根目录（和宿主机的 / 完全隔离）
├── bin/                 ← 基础命令（ls、cat、sh 等）
├── etc/                 ← 配置文件
├── home/                ← 用户目录
├── lib/                 ← 系统库
├── tmp/                 ← 临时文件
├── usr/                 ← 用户安装的程序
│   ├── bin/
│   ├── lib/
│   └── local/
├── var/                 ← 运行时数据（日志等）
│
└── app/                 ← ❗ 这个目录不是自带的，是 WORKDIR /app 创建的
    ├── app.jar          ← COPY 进来的文件
    └── storage/         ← RUN mkdir 创建的目录
```

这些目录来自**基础镜像**（如 `eclipse-temurin:17-jre`、`node:22-alpine`），基础镜像本身就包含一个精简的 Linux 文件系统。

#### `WORKDIR` 的真正含义

`WORKDIR` 做了两件事：

1. **如果目录不存在，自动创建它**（等于隐式 `mkdir -p`）
2. **把后续所有指令的"当前目录"设为这个路径**

```dockerfile
WORKDIR /app
# 等价于：
# RUN mkdir -p /app
# cd /app（对后续所有指令生效）
```