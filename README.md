# CLIProxyAPI Utils

CLIProxyAPI 账号清理工具，自动检测并处理异常账号：

- **删除** 401 认证失败的账号（备份后删除）
- **禁用** 配额耗尽的账号（402/403/429/usage_limit_reached）
- **保留** 已禁用、不可用的账号不做操作

## 快速开始

### 本地运行

1. 创建 `config.ini`：

```ini
[cliproxyapi]
base-url = http://your-host:8317
management-key = your-key
```

2. 运行：

```bash
# 模拟运行（不实际操作）
python cliproxyapi_cleanup_401.py --dry-run --once

# 单次执行
python cliproxyapi_cleanup_401.py --once

# 循环检测（默认 60 秒间隔）
python cliproxyapi_cleanup_401.py --interval 120
```

### Docker 运行

```bash
docker pull ghcr.io/yiranxiaohui/cliproxyapi_utils:main

# 挂载配置文件运行
docker run -v ./config.ini:/app/config.ini:ro ghcr.io/yiranxiaohui/cliproxyapi_utils:main --once

# 或通过命令行参数
docker run ghcr.io/yiranxiaohui/cliproxyapi_utils:main \
  --base-url http://your-host:8317 \
  --management-key your-key \
  --once
```

### Docker Compose

```bash
# 确保 config.ini 在同目录下
docker compose run cleanup --once
docker compose run cleanup --dry-run --once
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--base-url` | API 地址 | config.ini 中的值 |
| `--management-key` | 管理密钥 | config.ini 中的值 |
| `--dry-run` | 模拟运行，不实际操作 | 关闭 |
| `--once` | 只执行一次，不循环 | 关闭 |
| `--interval` | 循环检测间隔（秒） | 60 |
| `--timeout` | API 请求超时（秒） | 20 |

## 账号分类逻辑

| 分类 | 匹配条件 | 操作 |
|------|---------|------|
| `delete_401` | 401/unauthorized/token expired | 备份后删除 |
| `quota_exhausted` | 402/403/429/usage_limit_reached | 禁用 |
| `disabled` | 已禁用状态 | 不操作 |
| `unavailable` | 错误/不可用状态 | 不操作 |
| `available` | 正常 | 不操作 |

## 输出文件

- `backups/` — 删除前的账号备份文件
- `reports/` — 每次运行的 JSON 报告
