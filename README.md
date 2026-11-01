# BroadLink Capture（macOS）

为 IC.IHG2 网关、微信「全屋智控」小程序抓取博联云请求，并在本地导出 Home Assistant 集成需要的 `session.json` 与 `devices.json`。

这不是自动续期工具。会话过期后，按本说明重新抓取。它不登录微信、不重放设备控制请求、不连接 HA，也不上传凭证。实际抓包、证书信任和小程序操作由你手动完成。

## 依赖与适用条件

- macOS、电脑版微信，能正常打开并控制你自己的「全屋智控」。
- 网关标签为 `IC.IHG2`。其他型号需要核实实际协议，不能保证兼容。
- Python **3.9 或以上**、Homebrew、mitmproxy。无需 `pip install`，离线解析使用 mitmdump 自带的 Python 运行时。
- 本流程按普通网络环境编写；开始前关闭会影响系统代理的 VPN/代理软件。
- HA 可以稍后再访问。准备数据不需要打开 HA、网关后台或关闭防火墙。

如已安装 Homebrew：

```bash
brew install python mitmproxy
python3 --version
mitmdump --version
```

获取工具：

```bash
git clone https://github.com/skcary/broadlink-capture.git
cd broadlink-capture
```

没有 Homebrew 时，先按 [Homebrew 官方说明](https://brew.sh/)安装。本工具优先从 PATH 查找 `mitmdump`，兼容 Apple Silicon 与 Intel 的 Homebrew 路径。

## 完整操作步骤

### 1. 进入工具目录，新建抓包

```bash
cd /你的路径/broadlink-capture
./capture start
```

终端会显示本次目录和证书路径，例如：

```text
本次目录：.../broadlink-capture/.private/runs/20261101-120000-xxxxxxxx
本次证书：.../ca/mitmproxy-ca-cert.cer
PROXY_READY：代理已就绪……
```

看到 `PROXY_READY` 才表示代理完成启动。**保持这个终端运行**，不要关闭窗口或先按 Ctrl+C。每次 `start` 新建一轮，不覆盖旧数据，也不自动开启系统代理。

默认仅监听本机 `127.0.0.1:8080`，仅解密及保存 `ibroadlink.com` 域名范围内的流量。其他 HTTPS 域名走透传。这并不意味着抓包文件可以公开：博联域名内仍可能包含账号和设备凭证。

### 2. 手动导入并信任本次证书

1. 打开 macOS「钥匙串访问」，选择左侧「登录」。
2. 选择「文件 → 导入项目」（通常快捷键为 ⌘⇧I）。
3. 在文件对话框按 ⌘⇧G，粘贴启动终端显示的**本次证书完整路径**，导入。
4. 双击刚导入的 `mitmproxy` 证书，展开「信任」，将「使用此证书时」设为「始终信任」。
5. 关闭证书详情窗口，输入 Mac 密码保存。密码只输入系统窗口。

每轮使用新证书；旧的同名证书不能代替新证书。可自行验证当前证书（把路径换为实际路径）：

```bash
security verify-cert -c '/实际本次目录/ca/mitmproxy-ca-cert.cer' -p ssl -L
```

成功应显示 `certificate verification successful`。`CSSMERR_TP_NOT_TRUSTED` 表示尚未信任。不要导入或分享带私钥的 `mitmproxy-ca.pem`。

### 3. 在另一个终端开启临时代理

```bash
cd /你的路径/broadlink-capture
./capture proxy on
./capture status
```

默认网络服务名是 `Wi-Fi`。如果使用有线网络或改过名称：

```bash
networksetup -listallnetworkservices
./capture proxy on --service '你的网络服务名'
```

工具先检查本轮 mitmdump 进程和监听端口，只有确认正在运行才开代理。若检测到已有代理或代理认证配置，会拒绝覆盖。如果 macOS 拒绝修改，请手动操作，不必用 sudo 启动整个工具。

手动方式：系统设置 → 网络 → 当前网络 → 详细信息 → 代理；开启网页代理 HTTP 与安全网页代理 HTTPS，均填 `127.0.0.1`、`8080`（自定义端口时填实际端口），不启用认证，保存。手动设置的代理也必须手动关闭，脚本只恢复由 `proxy on` 管理的开关。

### 4. 重新打开微信，产生有效请求

1. 完全退出电脑版微信（⌘Q），重新打开，避免沿用旧的直连连接。
2. 打开「全屋智控」，选择目标家庭，刷新全屋设备列表，再进入各房间查看状态。
3. 如需确认控制请求，选一盏方便测试的灯，开、关各一次，间隔约 2 秒，并恢复原状态。不需要解绑设备或退出账号。
4. 查看抓包终端：

```text
COUNT local_connections=1
COUNT vendor_connect=1
COUNT vendor_http_requests=1
COUNT vendor_http_responses=1
```

`vendor_http_responses` 增长说明捕获到了博联 HTTP 响应，但不保证已经包含设备发现响应。导出时还会检查完整性。脚本只打印计数，不打印请求头、请求体或真实凭证。

一次只操作一个家庭。如果会话已经过期，需要按正常流程重新登录，再刷新设备列表。微信授权、验证码等自行操作，不发给别人。

### 5. 先关代理，再停止抓包

在第二个终端执行：

```bash
./capture proxy off
```

再回到第一个终端按 **Ctrl+C**，等待返回提示符、文件写入结束。工具在正常中断时也会尝试关闭自己开启的代理，但仍建议按上述顺序操作。强制结束进程或断电时无法保证自动恢复。

应急恢复（把 Wi-Fi 替换为你实际使用的网络服务名）：

```bash
networksetup -setwebproxystate 'Wi-Fi' off
networksetup -setsecurewebproxystate 'Wi-Fi' off
```

代理关闭后，地址字段可能仍保留 `127.0.0.1:8080`，开关关闭即不生效。工具不更改 SOCKS、自动代理、代理例外和路由。

### 6. 离线导出两个 JSON

```bash
./capture export
```

默认输出到 `exports/本次抓包名称/`。也可以指定一个尚不存在的目录：

```bash
./capture export --output "$HOME/Desktop/broadlink-export"
```

导出过程不监听代理、不联网、不回放请求。它从成功请求中提取会话，从 `DiscoverAppliancesRequest` 对应响应的 `payload.discoveredAppliances` 提取原始设备数组；设备 ID 与 `additionalApplianceDetails` 保持原样。

- 文件夹权限 `700`，两份文件权限 `600`。
- 已有导出目录不会被覆盖，避免破坏可用备份。
- 不混用多个家庭或账号；多次登录时要求最新观察到的有效会话也有设备发现响应。
- 不会凭空生成缺失字段。文件为空、会话不完整或没有设备发现响应时，返回非零退出码并说明原因。
- 若最新会话最后返回 HTTP 401，会拒绝用更早的成功记录导出。离线导出不会主动验证云端实时有效性，未知的厂商鉴权错误仍需根据实际协议补充。
- 设备清单本身也包含敏感信息，不要分享这两个文件、原始抓包、证书私钥或任何鉴权值。

### 7. 自行复制到 HA

将 `session.json`、`devices.json` 放入 **HA 配置目录下**的：

```text
config/cloudthink_broadlink/session.json
config/cloudthink_broadlink/devices.json
```

这里的 `config` 是 HA 的配置目录，不是本工具目录，也不是 `custom_components/cloudthink_broadlink/`。HAOS 通常对应 `/config/cloudthink_broadlink/`。

集成代码已安装并重启过时，换 `session.json` 无需再重启；换 `devices.json` 需重新加载对应配置条目。新增用户按原集成文档安装，再按房间添加条目。

### 8. 清理临时抓包与证书

先确认导出文件保留在安全位置，然后：

1. 确认系统 HTTP/HTTPS 代理已关闭，抓包已停止。
2. 在钥匙串访问中删除**本轮导入的** mitmproxy 证书，避免删到其他用途的同名证书。
3. 执行下面命令，按提示确认。它删除本轮原始抓包、CA 私钥与元数据，不删除 `exports/` 中的文件：

```bash
./capture cleanup
```

历史轮次可显式指定：`./capture cleanup --run '/实际/.private/runs/轮次目录'`。清理后默认轮次指针可能被移除；继续使用历史轮次时同样传 `--run`。不要把整个工具目录连同 `.private/` 或 `exports/` 打包分享；分享时仅复制源代码文件。

## 常见问题

| 现象 | 处理 |
|---|---|
| 只有 `PROXY_READY`，没有 `COUNT` | 用 `./capture status` 确认两个开关为 Yes；完全退出微信后重开；确认设置的是当前联网的网络服务 |
| 开代理后小程序没设备 | 先关两个代理恢复网络，再检查本次证书是否信任、抓包终端是否仍在运行 |
| `client_tls_failures` 增长 | 核对本次证书路径和信任，避免用了上轮同名证书 |
| `upstream_connect_failures` / `server_tls_failures` 增长 | 检查正常网络、DNS、系统时间；不使用关闭 TLS 校验的方式绕过 |
| 端口被占用 | 先停止旧抓包，或 `./capture start --port 8081`；配套代理命令自动读取本轮端口 |
| 文件为空 | 小程序正常并不代表走了代理；先看到博联 HTTP 请求/响应计数，再结束抓包 |
| 没有设备发现响应 | 重新打开小程序、切到家庭首页并刷新完整设备列表，再新建一轮抓包；不要手工拼设备数据 |
| 接口或字段改变 | 本工具只实现已知 houseproxy 结构；保留数据在本地，按实际协议调整，不能假设未知接口可用 |
| 会话再次过期 | 重新抓取并导出；当前没有经过验证的独立自动续期机制 |

## 文件与维护

```text
capture              命令入口
cli.py               启停流程、代理管理、离线导出入口、清理
capture_core.py      协议校验、会话配对、安全写入
live_addon.py        就绪提示与连接计数
export_addon.py      mitmdump 内的离线读取适配
tests/               仅使用合成数据的测试
.private/            运行时抓包、CA、当前轮次（禁止分享）
exports/             导出的敏感 JSON（禁止分享）
```

运行测试无需 mitmproxy Python 包，且不会连接任何真实设备：

```bash
python3 -m unittest discover -s tests -v
```

实现依据：`broadlink-ihg2-to-homekit` 项目的 `docs/02-capture.md`、`docs/03-protocol.md` 及集成读取格式；参考 [mitmproxy 选项](https://docs.mitmproxy.org/stable/concepts/options/)、[过滤表达式](https://docs.mitmproxy.org/stable/concepts/filters/)和[证书说明](https://docs.mitmproxy.org/stable/concepts/certificates/)。这里没有包含任何真实抓包或凭证。暂未在其他型号、其他 macOS 版本上完成实机验证。

原 HA 集成与协议说明：[SUNBinzhi/broadlink-ihg2-to-homekit](https://github.com/SUNBinzhi/broadlink-ihg2-to-homekit)。本项目专注于本地抓包与导出；房间配置、实体控制、HomeKit 桥接由原集成负责。开源许可为 [MIT](LICENSE)，涉及敏感数据的反馈请先阅读 [SECURITY.md](SECURITY.md)。
