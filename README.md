# UniCalendar API

后端日历服务 — RESTful API + OAuth 2.0 Provider + CalDAV + MCP Server

## 功能

- **日历核心**：日程（支持 RRULE 递归规则）、待办、提醒的完整 CRUD
- **协作**：事件分组（颜色标签）、分享组（多人共享日历）
- **日历订阅**：iCalendar Feed (.ics) 兼容 Apple/Google/Outlook 日历
- **OAuth 2.0 Provider**：作为认证中心，第三方应用可通过 OAuth Token 调用后端服务
- **CalDAV**：完整 RFC 4791/5545 实现，支持 iOS/macOS/Thunderbird/DAVx5 原生同步
- **MCP Server**：暴露日程管理工具给 Claude Desktop、Copilot 等 AI 客户端

## 技术栈

| 层级 | 技术 |
|------|------|
| 框架 | FastAPI + Starlette |
| ORM | SQLAlchemy 2.0 (async) |
| 数据库 | SQLite (WAL 模式) |
| 认证 | JWT + OAuth 2.0 (authorization_code / refresh_token) |
| 密码 | bcrypt |
| 递归规则 | python-dateutil (RRULE) |
| iCalendar | icalendar |
| MCP | mcp.server.fastmcp |

## 快速开始

```bash
# 安装
pip install -e .

# 启动（API + CalDAV 合并运行，单端口）
uvicorn app.main:app --reload --port 8000

# 访问 API 文档
open http://localhost:8000/docs
```

## 项目结构

```
├── app/
│   ├── main.py              # FastAPI 入口，CalDAV 中间件
│   ├── config.py            # 全局配置（密钥、过期时间等）
│   ├── database.py          # SQLAlchemy async engine + session
│   ├── dependencies.py      # 认证依赖注入（Bearer / OAuth Token）
│   │
│   ├── core/
│   │   ├── security.py      # bcrypt 密码哈希、JWT 签发/校验
│   │   ├── rrule_engine.py  # 递归规则引擎（RRuleSegment / RRuleSeries）
│   │   └── reminder_manager.py  # 提醒递归生命周期管理
│   │
│   ├── models/
│   │   ├── __init__.py      # User, UserData, EventGroup, ShareGroup 等
│   │   └── oauth.py         # OAuthClient, OAuthToken, AuthorizationCode
│   │
│   ├── schemas/__init__.py  # 全部 Pydantic 请求/响应模型
│   │
│   ├── services/            # 业务逻辑层
│   │   ├── event_service.py         # 日程 CRUD + RRule 生成
│   │   ├── todo_service.py          # 待办 CRUD + 转日程
│   │   ├── reminder_service.py      # 提醒 CRUD + 递归
│   │   ├── group_service.py         # 事件分组管理
│   │   ├── share_group_service.py   # 分享组管理
│   │   ├── calendar_feed_service.py # iCalendar Feed 生成
│   │   └── oauth_service.py         # OAuth 令牌管理
│   │
│   ├── api/                 # RESTful API 路由
│   │   ├── auth.py          # 注册、登录、密码重置
│   │   ├── events.py        # 日程 CRUD + 批量编辑
│   │   ├── todos.py         # 待办 CRUD + 转日程
│   │   ├── reminders.py     # 提醒 CRUD + 批量编辑
│   │   ├── event_groups.py  # 事件分组管理
│   │   ├── share_groups.py  # 分享组管理
│   │   ├── calendar_feed.py # iCalendar 订阅
│   │   └── oauth.py         # OAuth 授权/令牌端点
│   │
│   └── caldav/              # CalDAV 协议实现
│       ├── xml_utils.py     # WebDAV XML 构建
│       ├── ical_builder.py  # iCalendar 对象构建
│       ├── ical_parser.py   # iCalendar 文本解析
│       ├── etag.py          # ETag / CTag 计算
│       └── router.py        # PROPFIND / REPORT / GET / PUT / DELETE
│
├── mcp_server.py            # MCP Server 独立进程
├── pyproject.toml
├── requirements.txt
└── tests/
```

## REST API

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 注册账号 |
| POST | `/api/auth/login` | 登录获取 JWT |
| GET | `/api/auth/me` | 当前用户信息 |
| POST | `/api/auth/change-password` | 修改密码 |
| POST | `/api/auth/change-username` | 修改用户名 |
| POST | `/api/auth/password-reset/request` | 请求重置密码 |
| POST | `/api/auth/password-reset/verify` | 验证并重置密码 |
| POST | `/api/auth/email/verify-request` | 请求邮箱验证 |
| POST | `/api/auth/email/verify` | 验证邮箱 |

### 日程

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/events/` | 获取所有日程 |
| POST | `/api/events/` | 创建日程（支持 RRULE） |
| GET | `/api/events/{id}` | 获取单个日程 |
| PUT | `/api/events/{id}` | 更新日程 |
| DELETE | `/api/events/{id}` | 删除日程（?delete_scope=single\|all\|future） |
| POST | `/api/events/bulk-edit` | 批量编辑（支持 single/all/future 范围） |

### 待办

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/todos/` | 获取所有待办（?status=pending 筛选） |
| POST | `/api/todos/` | 创建待办 |
| GET | `/api/todos/{id}` | 获取单个待办 |
| PUT | `/api/todos/{id}` | 更新待办 |
| DELETE | `/api/todos/{id}` | 删除待办 |
| POST | `/api/todos/convert` | 将待办转换为日程 |

### 提醒

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/reminders/` | 获取所有提醒 |
| POST | `/api/reminders/` | 创建提醒（支持 RRULE） |
| GET | `/api/reminders/{id}` | 获取单个提醒 |
| PUT | `/api/reminders/{id}` | 更新提醒 |
| DELETE | `/api/reminders/{id}` | 删除提醒 |
| POST | `/api/reminders/update-status` | 更新状态（snooze/dismiss/complete） |
| POST | `/api/reminders/bulk-edit` | 批量编辑 |

### 事件分组

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/event-groups/` | 获取所有分组 |
| POST | `/api/event-groups/` | 创建分组 |
| PUT | `/api/event-groups/{id}` | 更新分组 |
| DELETE | `/api/event-groups/{id}` | 删除分组 |
| POST | `/api/event-groups/bulk-delete` | 批量删除 |

### 分享组

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/share-groups/` | 创建分享组 |
| GET | `/api/share-groups/` | 获取我的分享组 |
| POST | `/api/share-groups/join` | 通过邀请码加入 |
| POST | `/api/share-groups/{id}/leave` | 退出分享组 |
| GET | `/api/share-groups/{id}/members` | 获取成员列表 |
| PUT | `/api/share-groups/{id}/members` | 修改成员角色/颜色 |
| GET | `/api/share-groups/{id}/events` | 获取分享组日程 |

### 日历订阅

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/calendar/feed?token=xxx` | iCalendar Feed（Apple 日历订阅） |

### OAuth 2.0 Provider

| 方法 | 路径 | RFC | 说明 |
|------|------|-----|------|
| GET | `/api/oauth/authorize` | 6749 | 授权端点（支持 PKCE S256） |
| POST | `/api/oauth/token` | 6749 | 令牌端点（authorization_code / refresh_token） |
| POST | `/api/oauth/introspect` | 7662 | 令牌内省 |
| POST | `/api/oauth/revoke` | 7009 | 令牌吊销 |
| GET | `/api/oauth/userinfo` | OIDC | 用户信息 |
| POST | `/api/oauth/clients` | — | 注册 OAuth 客户端 |
| GET | `/api/oauth/clients` | — | 列出注册的客户端 |
| DELETE | `/api/oauth/clients/{id}` | — | 删除客户端 |

#### OAuth Scopes

| Scope | 说明 |
|-------|------|
| `read:events` | 读取日程 |
| `write:events` | 创建/修改/删除日程 |
| `read:todos` | 读取待办 |
| `write:todos` | 创建/修改/删除待办 |
| `read:reminders` | 读取提醒 |
| `write:reminders` | 创建/修改/删除提醒 |
| `read:groups` | 读取分组和分享组 |
| `write:groups` | 管理分组和分享组 |
| `read:calendar` | 访问日历订阅源 |
| `offline_access` | 发放 refresh_token |

#### OAuth 使用流程

```
# 1. 用户注册 OAuth 客户端
POST /api/oauth/clients
{
  "client_name": "My App",
  "redirect_uris": ["https://myapp.example.com/callback"],
  "default_scopes": ["read:events", "read:todos"]
}
→ { "client_id": "...", "client_secret": "..." }

# 2. 引导用户授权（浏览器跳转）
GET /api/oauth/authorize
  ?response_type=code
  &client_id={client_id}
  &redirect_uri=https://myapp.example.com/callback
  &scope=read:events%20read:todos
  &state=random_state

# 3. 用户授权后，回调返回 code
→ https://myapp.example.com/callback?code=AUTH_CODE&state=...

# 4. 用 code 换取 access_token
POST /api/oauth/token
  grant_type=authorization_code
  &code=AUTH_CODE
  &redirect_uri=https://myapp.example.com/callback
  &client_id={client_id}
  &client_secret={client_secret}
→ { "access_token": "...", "refresh_token": "...", "token_type": "Bearer", "expires_in": 1800 }

# 5. 调用 API
GET /api/events/
Authorization: Bearer {access_token}

# 6. 刷新令牌
POST /api/oauth/token
  grant_type=refresh_token
  &refresh_token={refresh_token}
  &client_id={client_id}
  &client_secret={client_secret}
```

## CalDAV

CalDAV 支持通过标准协议同步日历，兼容以下客户端：

- iOS / macOS 原生日历
- Thunderbird + Lightning
- DAVx5（Android）
- Evolution（Linux）

### CalDAV 端点

| 路径 | 方法 | 说明 |
|------|------|------|
| `/.well-known/caldav` | PROPFIND | 服务发现 |
| `/caldav/` | PROPFIND | 服务根（current-user-principal） |
| `/caldav/principals/{user}/` | PROPFIND | 用户主体（calendar-home-set） |
| `/caldav/{user}/` | PROPFIND | 日历主目录（枚举所有日历集合） |
| `/caldav/{user}/{calendar}/` | PROPFIND | 日历集合属性 + 枚举事件 |
| `/caldav/{user}/{calendar}/` | REPORT | calendar-query / calendar-multiget |
| `/caldav/{user}/{calendar}/{uid}.ics` | GET | 获取单个事件 iCalendar |
| `/caldav/{user}/{calendar}/{uid}.ics` | PUT | 创建/更新事件（含 iOS "仅此" 编辑） |
| `/caldav/{user}/{calendar}/{uid}.ics` | DELETE | 删除事件（重复系列全部删除） |

### 认证方式

CalDAV 支持三种认证：
1. **HTTP Basic Auth**：用户名 + JWT Token 作为密码（推荐）
2. **HTTP Basic Auth**：用户名 + 明文密码
3. **Bearer Token**：`Authorization: Bearer <JWT>`

### iOS/macOS 配置

```
服务器: https://your-server.com
用户名: your-username
密码:   your-jwt-access-token  (从 /api/auth/login 获取)
```

### 日历映射

每个 CalDAV 日历集合对应一组事件：

| Calendar ID | 内容 |
|-------------|------|
| `default` | 未分组的日程 |
| `{group-uuid}` | 对应事件分组下的日程 |
| `reminders` | 提醒（转为 VEVENT + VALARM，只读） |

## MCP Server

MCP Server 将日程管理工具暴露给 AI 客户端（Claude Desktop、Copilot 等）。

### 启动

```bash
# stdio 模式（Claude Desktop 本地）
python mcp_server.py --token <JWT_TOKEN>

# HTTP 模式（远程客户端）
python mcp_server.py --http --port 8100 --token <JWT_TOKEN>

# HTTP 模式（无认证，仅开发）
MCP_USER_TOKEN=<JWT_TOKEN> python mcp_server.py --http --port 8100 --no-auth
```

### 提供的工具

| 工具 | 说明 |
|------|------|
| `search_items` | 搜索日程/待办/提醒 |
| `create_item` | 创建日程/待办/提醒 |
| `update_item` | 更新日程/待办/提醒 |
| `delete_item` | 删除日程/待办/提醒 |
| `complete_todo` | 标记待办为完成 |
| `get_event_groups` | 获取事件分组列表 |
| `get_share_groups` | 获取分享组列表 |
| `check_schedule_conflicts` | 检查日程冲突 |

### Claude Desktop 配置

`~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "unicalendar": {
      "command": "python",
      "args": ["/path/to/UniCalendar/mcp_server.py", "--token", "<YOUR_JWT_TOKEN>"]
    }
  }
}
```

## 运行测试

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SECRET_KEY` | `change-me...` | JWT 签名密钥 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./uni_calendar.db` | 数据库 URL |
| `DEBUG` | `false` | 调试模式 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | JWT 过期时间（分钟） |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `30` | 刷新令牌过期（天） |
| `AUTH_CODE_EXPIRE_MINUTES` | `10` | OAuth 授权码过期（分钟） |
| `OAUTH_ISSUER` | `https://localhost:8000` | JWT issuer |
| `MCP_USER_TOKEN` | — | MCP Server 认证 Token |

## 架构设计

```
┌────────────────────────────────────────────────────────────┐
│  HTTP Clients                                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │CalDAV App│  │REST App  │  │OAuth App │  │MCP Client│  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
└───────┼──────────────┼──────────────┼──────────────┼───────┘
        │              │              │              │
   ┌────▼──────────────▼──────────────▼──────────────▼───────┐
   │                   FastAPI (Single Port)                  │
   │  ┌───────────────────────────────────────────────────┐  │
   │  │ CalDAV Middleware (PROPFIND/REPORT/GET/PUT/DELETE) │  │
   │  └───────────────────────────────────────────────────┘  │
   │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐  │
   │  │Auth API │ │REST API │ │OAuth API│ │Calendar Feed│  │
   │  └────┬────┘ └────┬────┘ └────┬────┘ └──────┬──────┘  │
   └───────┼───────────┼───────────┼──────────────┼─────────┘
           │           │           │              │
   ┌───────▼───────────▼───────────▼──────────────▼─────────┐
   │                  Service Layer                           │
   │  event_service / todo_service / reminder_service         │
   │  group_service / share_group_service / oauth_service     │
   └───────────────────────┬─────────────────────────────────┘
                           │
   ┌───────────────────────▼─────────────────────────────────┐
   │              Data Layer (SQLAlchemy)                      │
   │  User / UserData / EventGroup / ShareGroup / OAuth*      │
   └───────────────────────┬─────────────────────────────────┘
                           │
   ┌───────────────────────▼─────────────────────────────────┐
   │                  SQLite (WAL Mode)                        │
   └─────────────────────────────────────────────────────────┘
```

## License

MIT
