# OAuth 2.0 Provider 使用指南

UniCalendar 作为 OAuth 2.0 Provider，第三方应用可通过 OAuth Token 访问用户日历数据。

## 支持的授权流

| 授权流 | RFC | 适用场景 |
|--------|-----|----------|
| Authorization Code + PKCE | RFC 6749 + 7636 | Web 应用、移动应用 |
| Refresh Token | RFC 6749 | 令牌续期 |

## 可用 Scopes

| Scope | 权限 |
|-------|------|
| `read:events` | 读取日程 |
| `write:events` | 创建/修改/删除日程 |
| `read:todos` | 读取待办 |
| `write:todos` | 创建/修改/删除待办 |
| `read:reminders` | 读取提醒 |
| `write:reminders` | 创建/修改/删除提醒 |
| `read:groups` | 读取分组与分享组信息 |
| `write:groups` | 管理分组与分享组 |
| `read:calendar` | 访问 iCalendar Feed |
| `offline_access` | 发放 refresh_token 用于离线访问 |

## 1. 注册 OAuth 客户端

作为开发者，首先需要在 UniCalendar 上注册你的应用：

```
POST /api/oauth/clients
Authorization: Bearer <user_jwt>

{
  "client_name": "我的日程 App",
  "redirect_uris": [
    "https://myapp.example.com/oauth/callback"
  ],
  "grant_types": ["authorization_code", "refresh_token"],
  "default_scopes": ["read:events", "read:todos"],
  "is_confidential": true
}
```

响应（`client_secret` **仅在注册时返回一次**）：

```json
{
  "client_id": "abc123...",
  "client_secret": "xyz789...",
  "client_name": "我的日程 App",
  "redirect_uris": ["https://myapp.example.com/oauth/callback"],
  "grant_types": ["authorization_code", "refresh_token"],
  "default_scopes": ["read:events", "read:todos"],
  "is_confidential": true,
  "is_active": true
}
```

## 2. 用户授权（Authorization Code Flow）

### 步骤 1：引导用户授权

用户点击"使用 UniCalendar 登录"，浏览器跳转到：

```
GET /api/oauth/authorize
  ?response_type=code
  &client_id={client_id}
  &redirect_uri=https://myapp.example.com/oauth/callback
  &scope=read:events%20read:todos%20read:reminders
  &state=random_csrf_state
```

可选参数：

| 参数 | 说明 |
|------|------|
| `code_challenge` | PKCE code_challenge（推荐使用 S256） |
| `code_challenge_method` | `S256` |
| `nonce` | OIDC nonce |

### 步骤 2：处理回调

用户授权后，浏览器被重定向到你的 `redirect_uri`：

```
GET https://myapp.example.com/oauth/callback
  ?code=AUTHORIZATION_CODE
  &state=random_csrf_state
```

验证 `state` 匹配后，使用 `code` 换取令牌。

### 步骤 3：换取 Token

```
POST /api/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code=AUTHORIZATION_CODE
&redirect_uri=https://myapp.example.com/oauth/callback
&client_id={client_id}
&client_secret={client_secret}
&code_verifier={pkce_verifier}
```

响应：

```json
{
  "access_token": "eyJ...",
  "refresh_token": "abc...",
  "token_type": "Bearer",
  "expires_in": 1800,
  "scope": "read:events read:todos read:reminders"
}
```

## 3. 调用 API

使用 `access_token` 调用受保护的 API：

```bash
curl -H "Authorization: Bearer <access_token>" \
  https://your-server.com/api/events/
```

## 4. 刷新 Token

`access_token` 有效期 30 分钟。过期后使用 `refresh_token` 换取新令牌：

```
POST /api/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token
&refresh_token={refresh_token}
&client_id={client_id}
&client_secret={client_secret}
```

响应包含新的 `access_token` 和 `refresh_token`。旧令牌自动吊销。

## 5. 令牌内省

验证令牌是否有效（资源服务器调用）：

```
POST /api/oauth/introspect
Content-Type: application/json

{
  "token": "access_or_refresh_token"
}
```

响应：

```json
{
  "active": true,
  "client_id": "abc123...",
  "username": "john",
  "scope": "read:events read:todos",
  "token_type": "Bearer",
  "exp": 1716000000,
  "iat": 1715998200
}
```

## 6. 令牌吊销

```
POST /api/oauth/revoke
Content-Type: application/json

{
  "token": "access_or_refresh_token"
}
```

## Python 示例

```python
import requests

# 配置
BASE = "https://your-server.com"
CLIENT_ID = "your_client_id"
CLIENT_SECRET = "your_client_secret"
REDIRECT_URI = "https://myapp.example.com/oauth/callback"

# 1. 换取 token（用户授权后获得 code）
resp = requests.post(f"{BASE}/api/oauth/token", data={
    "grant_type": "authorization_code",
    "code": "AUTHORIZATION_CODE",
    "redirect_uri": REDIRECT_URI,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
})
tokens = resp.json()
access_token = tokens["access_token"]

# 2. 调用 API
events = requests.get(
    f"{BASE}/api/events/",
    headers={"Authorization": f"Bearer {access_token}"}
).json()

# 3. 刷新令牌
new_tokens = requests.post(f"{BASE}/api/oauth/token", data={
    "grant_type": "refresh_token",
    "refresh_token": tokens["refresh_token"],
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
}).json()
```

## PKCE 示例

对于无法安全存储 `client_secret` 的客户端（SPA、移动应用），使用 PKCE：

```python
import hashlib
import base64
import secrets
import urllib.parse

# 生成 code_verifier 和 code_challenge
code_verifier = secrets.token_urlsafe(48)
digest = hashlib.sha256(code_verifier.encode()).digest()
code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

# 授权请求
params = {
    "response_type": "code",
    "client_id": CLIENT_ID,
    "redirect_uri": REDIRECT_URI,
    "scope": "read:events",
    "state": secrets.token_urlsafe(16),
    "code_challenge": code_challenge,
    "code_challenge_method": "S256",
}
auth_url = f"{BASE}/api/oauth/authorize?{urllib.parse.urlencode(params)}"
# 引导用户访问 auth_url...

# 换取 token 时提供 code_verifier
resp = requests.post(f"{BASE}/api/oauth/token", data={
    "grant_type": "authorization_code",
    "code": "AUTHORIZATION_CODE",
    "redirect_uri": REDIRECT_URI,
    "client_id": CLIENT_ID,
    "code_verifier": code_verifier,  # 无需 client_secret
})
```

## 错误响应

所有 OAuth 端点遵循 RFC 6749 错误格式：

| 端点 | 状态码 | 位置 |
|------|--------|------|
| `/authorize` | 302 | URL query `?error=...&error_description=...` |
| `/token` | 400/401 | JSON body `{"error": "...", "error_description": "..."}` |

常见错误：

| 错误码 | 说明 |
|--------|------|
| `invalid_client` | client_id 或 client_secret 不正确 |
| `invalid_grant` | 授权码/刷新令牌已过期或已使用 |
| `invalid_scope` | 请求了不支持的 scope |
| `unsupported_grant_type` | 不支持的 grant_type |
| `unauthorized_client` | 客户端未授权或禁用 |
