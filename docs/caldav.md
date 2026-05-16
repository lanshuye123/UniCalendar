# CalDAV 使用指南

UniCalendar 实现完整的 CalDAV 协议（RFC 4791 / RFC 5545），支持与原生日历客户端同步。

## 支持的客户端

| 平台 | 客户端 | 说明 |
|------|--------|------|
| iOS | 原生日历 | 设置 → 日历 → 账户 → 添加账户 → 其他 → 添加 CalDAV 账户 |
| macOS | 原生日历 | 系统偏好 → 互联网账户 → 添加其他账户 → CalDAV |
| Android | DAVx5 | 从 F-Droid/Google Play 安装，添加 CalDAV 账户 |
| Linux | Evolution / Thunderbird | 直接配置 CalDAV URL |
| Web | Thunderbird Lightning | 新日历 → 远程 → CalDAV |

## 服务发现

客户端通过 `.well-known` 自动发现：

```
GET /.well-known/caldav → 301 重定向至 /caldav/
```

## 凭据

| 字段 | 值 |
|------|-----|
| **服务器地址** | `https://your-server.com` |
| **用户名** | UniCalendar 用户名 |
| **密码** | JWT Token（从 `/api/auth/login` 获取）|

密码支持三种格式：

1. **JWT Token**（推荐）：通过 `/api/auth/login` 登录获取的 `access_token`
2. **明文密码**：注册时使用的密码
3. **Bearer Token**：在 Authorization header 中使用 `Bearer <token>`

## 端点

| 路径 | 方法 | 说明 |
|------|------|------|
| `/.well-known/caldav` | PROPFIND | 服务发现（RFC 6764） |
| `/caldav/` | PROPFIND | 服务根 |
| `/caldav/principals/{user}/` | PROPFIND | 用户主体资源 |
| `/caldav/{user}/` | PROPFIND Depth:1 | 日历主目录 |
| `/caldav/{user}/{cal}/` | PROPFIND | 日历集合 |
| `/caldav/{user}/{cal}/` | REPORT | 日历查询/批量获取 |
| `/caldav/{user}/{cal}/{uid}.ics` | GET | 获取事件 |
| `/caldav/{user}/{cal}/{uid}.ics` | PUT | 创建/更新事件 |
| `/caldav/{user}/{cal}/{uid}.ics` | DELETE | 删除事件 |

## 日历映射

UniCalendar 的事件分组自动映射为 CalDAV 日历集合：

| Calendar ID | 显示名称 | 内容 |
|-------------|----------|------|
| `default` | UniScheduler | 未分组的日程 |
| `{group-uuid}` | 事件分组名称 | 该分组下的所有日程 |
| `reminders` | 提醒 | 活跃/延后的提醒（转为 VEVENT，只读） |

每个日历集合的颜色继承自事件分组的颜色设置。

## 重复事件处理

### 创建重复事件

通过 PUT 上传带 RRULE 的 VEVENT 即创建重复系列：

```ical
BEGIN:VEVENT
UID:my-event-123
SUMMARY:每周例会
DTSTART;TZID=Asia/Shanghai:20260101T090000
DTEND;TZID=Asia/Shanghai:20260101T100000
RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR
END:VEVENT
```

### iOS "仅此" 编辑

iOS 的"仅此"编辑通过 PUT 多 VEVENT 实现。主 VEVENT 保持 RRULE，修改的实例以独立的 VEVENT 带 `RECURRENCE-ID` 上传。

### iOS "此及以后" 编辑

iOS 通过在 RRULE 上添加 `UNTIL` 限制 + 创建新系列来实现分拆编辑。

### RRULE 支持范围

| RRULE 属性 | 支持 |
|-----------|------|
| FREQ | DAILY, WEEKLY, MONTHLY, YEARLY |
| INTERVAL | 完全支持 |
| COUNT | 完全支持 |
| UNTIL | 完全支持（UTC 和本地时间） |
| BYDAY | 完全支持 |
| BYMONTHDAY | 完全支持 |
| BYSETPOS | 支持 |
| EXDATE | 通过 rrule_engine 支持 |

## ETag / CTag 同步机制

| 属性 | 作用 |
|------|------|
| `getetag` | 每个事件的 ETag，PUT 时通过 `If-Match` header 做冲突检测 |
| `getctag` | 日历集合的 CTag，客户端通过对比判断是否有变化 |

CTag 基于 `max(last_modified) + 事件数量` 的哈希，任何增删改都会改变 CTag。

## iOS 配置示例

1. 打开 **设置** → **日历** → **账户**
2. 点击 **添加账户** → **其他**
3. 选择 **添加 CalDAV 账户**
4. 填写：

```
服务器:   your-server.com
用户名:   your-username
密码:     your-jwt-token
描述:     UniCalendar
```

5. 使用 SSL：如果使用 HTTPS，保持开启
6. 点击 **下一步**，等待校验完成

## 故障排查

### 401 Unauthorized
- 确认用户名和密码（JWT Token）正确
- Token 是否过期（默认 30 分钟）
- 可以重新 `POST /api/auth/login` 获取新 Token

### 403 Calendar creation managed by server
- 不支持通过 CalDAV MKCALENDAR 创建新日历
- 日历通过 Web API 的事件分组自动管理

### 提醒日历只读
- `/caldav/{user}/reminders/` 只支持 GET 和 PROPFIND
- 提醒需要通过 REST API `/api/reminders/` 管理

### 事件未同步
- 检查事件是否在正确的分组中
- 重新打开日历客户端的同步开关
- 查看服务器日志确认 DAV 请求是否到达
