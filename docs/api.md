# API 参考

所有 API 需要在 `Authorization` header 中携带 Bearer Token（JWT 或 OAuth access_token）。

```
Authorization: Bearer <token>
```

## 通用响应格式

```json
{
  "event": { ... },    // 单条数据
  "message": "..."     // 操作结果
}
```

列表接口：

```json
{
  "events": [ ... ],   // 数据列表
  "count": 42          // 总数
}
```

错误响应（非 OAuth）：

```json
{
  "detail": "Error description"
}
```

## 日程数据结构

```json
{
  "id": "uuid",
  "title": "标题",
  "start": "2026-01-15T09:00:00",
  "end": "2026-01-15T10:00:00",
  "description": "描述",
  "importance": "high",
  "urgency": "high",
  "groupID": "event-group-uuid",
  "ddl": "2026-01-15T23:59:00",
  "rrule": "FREQ=WEEKLY;BYDAY=MO,WE,FR",
  "is_recurring": true,
  "is_main_event": true,
  "series_id": "series-uuid",
  "is_detached": false,
  "shared_to_groups": ["share-group-id-1"],
  "status": "confirmed",
  "location": "",
  "tags": [],
  "linked_reminders": [],
  "last_modified": "2026-01-15 09:00:00"
}
```

### RRULE 格式

标准 iCalendar RRULE 字符串，支持的属性：

```
FREQ=DAILY|WEEKLY|MONTHLY|YEARLY
INTERVAL=N
COUNT=N
UNTIL=YYYYMMDDTHHMMSS
BYDAY=MO,TU,WE,TH,FR,SA,SU
BYDAY=+1MO  (每月第一个周一)
BYDAY=-1FR  (每月最后一个周五)
BYMONTHDAY=N
BYSETPOS=N
```

## 待办数据结构

```json
{
  "id": "uuid",
  "title": "标题",
  "description": "描述",
  "due_date": "2026-01-15",
  "estimated_duration": "2h",
  "importance": "high",
  "urgency": "high",
  "groupID": "event-group-uuid",
  "status": "pending",
  "created_at": "2026-01-15 09:00:00",
  "last_modified": "2026-01-15 09:00:00"
}
```

待办状态：

| 状态 | 说明 |
|------|------|
| `pending` | 待处理 |
| `in_progress` | 进行中 |
| `completed` | 已完成 |
| `cancelled` | 已取消 |

## 提醒数据结构

```json
{
  "id": "uuid",
  "title": "标题",
  "content": "提醒内容",
  "trigger_time": "2026-01-15T09:00:00",
  "priority": "high",
  "status": "active",
  "snooze_until": "",
  "rrule": "FREQ=DAILY",
  "series_id": "series-uuid",
  "is_recurring": true,
  "is_main_reminder": true,
  "is_detached": false,
  "created_at": "2026-01-15 09:00:00",
  "last_modified": "2026-01-15 09:00:00"
}
```

提醒状态：

| 状态 | 说明 |
|------|------|
| `active` | 活跃 |
| `snoozed` | 已延后 |
| `dismissed` | 已忽略 |
| `completed` | 已完成 |

## 事件分组

```json
{
  "id": "uuid",
  "name": "工作",
  "description": "工作相关日程",
  "color": "#3b82f6",
  "type": "default",
  "working_hours_start": "09:00",
  "working_hours_end": "18:00"
}
```

## 分享组

```json
{
  "id": "uuid",
  "name": "团队 Cal",
  "description": "团队共享日历",
  "join_code": "A1B2C3D4",
  "is_active": true,
  "owner_id": 1,
  "role": "owner",
  "created_at": "2026-01-15T00:00:00"
}
```

分享组角色：

| 角色 | 权限 |
|------|------|
| `owner` | 完全控制（转让除外） |
| `admin` | 管理成员、修改角色 |
| `member` | 查看和添加日程 |

## 认证

所有认证端点返回用户对象：

```json
{
  "id": 1,
  "username": "john",
  "email": "john@example.com",
  "is_active": true,
  "is_verified": false,
  "created_at": "2026-01-15T00:00:00"
}
```

登录返回 JWT Token：

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "dGhpcyBpcyBhIHJlZnJl...",
  "token_type": "Bearer"
}
```
