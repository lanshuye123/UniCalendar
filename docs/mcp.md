# MCP Server 使用指南

UniCalendar MCP Server 将日程管理功能暴露为 MCP 工具，供 AI 客户端（Claude Desktop、Copilot、Continue 等）调用。

## 安装依赖

```bash
pip install -e .
# MCP 库已包含在依赖中
```

## 启动方式

### 模式 1：stdio（本地，用于 Claude Desktop）

```bash
python mcp_server.py --token <JWT_ACCESS_TOKEN>
```

或通过环境变量：

```bash
MCP_USER_TOKEN=<JWT_ACCESS_TOKEN> python mcp_server.py
```

### 模式 2：HTTP（远程，用于 Copilot 等）

```bash
# 带认证（推荐）
python mcp_server.py --http --port 8100

# 开发模式（无认证，固定用户）
MCP_USER_TOKEN=<JWT_ACCESS_TOKEN> python mcp_server.py --http --port 8100 --no-auth
```

## Claude Desktop 配置

编辑 `~/.config/claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "unicalendar": {
      "command": "python",
      "args": [
        "/path/to/UniCalendar/mcp_server.py",
        "--token",
        "<YOUR_JWT_ACCESS_TOKEN>"
      ]
    }
  }
}
```

获取 JWT Token：

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"login": "your_username", "password": "your_password"}'
```

## 工具列表

### search_items

搜索日程、待办、提醒。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `item_type` | string | `"all"` | `"event"`, `"todo"`, `"reminder"`, `"all"` |
| `keyword` | string | — | 标题/描述关键词搜索 |
| `time_range` | string | — | `"today"`, `"this_week"`, `"next_week"`, `"this_month"` / `"今天"`, `"本周"`, `"下周"`, `"本月"` / 自定义 `"2024-01-01 ~ 2024-01-31"` |
| `status` | string | — | 状态过滤 |
| `event_group` | string | — | 事件分组名称或 UUID |
| `limit` | int | 20 | 返回上限 |

### create_item

创建日程/待办/提醒。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `item_type` | string | 必填 | `"event"`, `"todo"`, `"reminder"` |
| `title` | string | 必填 | 标题 |
| `description` | string | — | 描述 |
| `start` | string | — | 日程开始时间 `"2024-01-15T09:00"` |
| `end` | string | — | 日程结束时间 |
| `event_group` | string | — | 事件分组名称 |
| `importance` | string | — | `"high"`, `"medium"`, `"low"` |
| `urgency` | string | — | `"high"`, `"medium"`, `"low"` |
| `due_date` | string | — | 待办截止 `"2024-01-15"` |
| `priority` | string | — | 优先级 |
| `trigger_time` | string | — | 提醒时间 `"2024-01-15T09:00"` |
| `repeat` | string | — | 重复规则 `"daily"`, `"每周"`, `"工作日"`, `"FREQ=WEEKLY;BYDAY=MO,WE,FR"` |

### update_item

更新日程/待办/提醒。只传需要修改的字段。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `identifier` | string | 必填 | UUID 或标题 |
| `item_type` | string | — | 可选类型指定 |
| `edit_scope` | string | `"single"` | `"single"`, `"all"`, `"future"` |
| `clear_repeat` | bool | false | 设为 true 清除重复规则 |

其他参数与 `create_item` 相同。

### delete_item

删除日程/待办/提醒。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `identifier` | string | 必填 | UUID 或标题 |
| `item_type` | string | — | 可选类型指定 |
| `delete_scope` | string | `"single"` | `"single"`, `"all"`, `"future"` |

### complete_todo

标记待办为完成。

| 参数 | 类型 | 说明 |
|------|------|------|
| `identifier` | string | 待办 UUID 或标题 |

### get_event_groups

获取用户所有事件分组（用于选择事件分组时参考）。

### get_share_groups

获取用户所在的所有分享组。

### check_schedule_conflicts

检查日程冲突。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `time_range` | string | `"this_week"` | 时间范围 |
| `include_share_groups` | bool | true | 是否包含分享组日程 |

## Copilot 配置

```json
{
  "mcpServers": {
    "unicalendar": {
      "url": "http://your-server.com:8100/mcp",
      "headers": {
        "Authorization": "Bearer <YOUR_JWT_TOKEN>"
      }
    }
  }
}
```

## 安全注意事项

1. **Token 安全**：JWT Token 有完整 API 权限。stdio 模式下 Token 仅本地可见。
2. **HTTP 模式**：生产环境务必保持认证开启（不使用 `--no-auth`），建议配合 HTTPS。
3. **Token 过期**：默认 30 分钟过期。需要定期刷新。
4. **用户隔离**：每个用户只能操作自己的数据，MCP Server 通过 Token 识别用户身份。
