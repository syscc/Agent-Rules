# Agent-Rules

自用分流规则。`*.list` 是 Clash 格式的纯文本规则，`*.srs` 是自动编译出的 sing-box 二进制规则集。

## 为什么需要转换

sing-box 的 `route.rule_set` 只接受 source JSON 或 binary `.srs`，不能直接解析 Clash 的行式 `.list`。
因此本仓库用 GitHub Actions 在每次修改 `.list` 后自动编译出 `.srs`，客户端直接远程引用 `.srs`。

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `MyDirect.list` | 直连规则（Clash 格式，手工维护） |
| `MyProxy.list` | 代理规则（Clash 格式，手工维护） |
| `MyDirect.srs` / `MyProxy.srs` | 由 Actions 自动生成的 sing-box 二进制规则集，**不要手工编辑** |
| `scripts/clash2srs.py` | 转换脚本：Clash `.list` → sing-box source JSON → `.srs` |

## 工作流

`.github/workflows/build-ruleset.yml`：

1. 触发条件：推送修改 `*.list` / 脚本 / 工作流本身（`main` 分支），或手动 `workflow_dispatch`；PR 只构建不提交。
2. 下载固定版本 sing-box（当前 `1.14.4`，见工作流 `SING_BOX_VERSION`）。
3. 运行 `scripts/clash2srs.py`，把每个 `*.list` 编译成同名 `.srs`。
4. 用 `sing-box rule-set decompile` 校验产物可被解析。
5. 若 `.srs` 有变化，以 `github-actions[bot]` 身份自动提交回仓库。

只监听 `*.list` 变化、提交只涉及 `*.srs`，因此不会产生循环触发。

## sing-box 客户端引用

编译产物已提交到 `main`，可直接作为远程规则集使用（`format` 可省略，`.srs` 后缀会被自动识别为 binary）：

```json
{
  "route": {
    "rule_set": [
      {
        "type": "remote",
        "tag": "my-direct",
        "format": "binary",
        "url": "https://raw.githubusercontent.com/syscc/Agent-Rules/main/MyDirect.srs",
        "download_detour": "proxy"
      },
      {
        "type": "remote",
        "tag": "my-proxy",
        "format": "binary",
        "url": "https://raw.githubusercontent.com/syscc/Agent-Rules/main/MyProxy.srs",
        "download_detour": "proxy"
      }
    ],
    "rules": [
      { "rule_set": ["my-direct"], "outbound": "direct" },
      { "rule_set": ["my-proxy"], "outbound": "proxy" }
    ],
    "final": "proxy"
  }
}
```

> **sing-box 1.14+**：`download_detour` 已废弃，改用 `http_client`：
>
> ```json
> {
>   "type": "remote",
>   "tag": "my-proxy",
>   "format": "binary",
>   "url": "https://raw.githubusercontent.com/syscc/Agent-Rules/main/MyProxy.srs",
>   "http_client": "proxy-client"
> }
> ```
>
> 未配置 `http_clients` 时仍会回退到默认出站下载，但该隐式行为将在 1.16.0 移除。

本仓库生成的规则集 `version` 为 `1`，sing-box `1.8.0` 及以上均可读取。

## 本地手动编译

```bash
# 需要 sing-box >= 1.8 在 PATH 中，或 --singbox 指定路径
python3 scripts/clash2srs.py MyDirect.list MyProxy.list

# 只转换其中一个，并保留中间 source JSON 便于查看
python3 scripts/clash2srs.py --keep-json MyProxy.list

# 指定 sing-box 可执行文件
python3 scripts/clash2srs.py --singbox /usr/local/bin/sing-box MyProxy.list
```

脚本会打印每个字段的条目数，并对跳过/无法识别的规则输出警告到 stderr。

## 支持的 Clash 规则类型

| Clash | sing-box 字段 |
| --- | --- |
| `DOMAIN` | `domain` |
| `DOMAIN-SUFFIX` | `domain_suffix` |
| `DOMAIN-KEYWORD` | `domain_keyword` |
| `DOMAIN-REGEX` | `domain_regex` |
| `IP-CIDR` / `IP-CIDR6` | `ip_cidr` |
| `SRC-IP-CIDR` | `source_ip_cidr` |
| `DST-PORT` / `SRC-PORT` | `port` / `source_port` |
| `PROCESS-NAME` / `PROCESS-PATH` | `process_name` / `process_path` |

补充说明：

- 行尾的策略名（`Proxy` / `DIRECT`）与 `no-resolve` 会被忽略——规则集只描述“匹配什么”，“走哪个出站”由客户端 `route.rules` 决定。
- 以 `#` 或 `//` 开头的行、空行被忽略，所以 `##DOMAIN,...` 这类注释示例不会生效。
- `GEOIP` / `GEOSITE` / `MATCH` / `RULE-SET` / `IP-ASN` 等规则集不支持的项会被警告并跳过；这些应在 sing-box 配置的 `route.rules` 层处理。
- 同一文件内的重复条目自动去重，输出顺序固定，重复构建结果稳定（便于 diff）。
