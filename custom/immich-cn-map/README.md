# Immich 中国地图定制

把 Immich 自带的 MapLibre 地图改造成国内可用的形态：高德底图、坐标纠偏、按区域聚合、打开即落在自己的城市，并修掉了时间线（timeline）面板反复叠加的老问题。

线上环境：Synology DS1621+ / SynoCommunity 预编译包 **immich-web 3.4.1**。

## 解决的是什么问题

| # | 现象 | 原因 | 处理 |
|---|------|------|------|
| 1 | 地图加载不出来 / 英文底图 | Immich 默认用 MapLibre 官方样式（境外源） | 换成高德栅格瓦片，样式走 system-config |
| 2 | 照片点位整体偏 400~600 米 | 相册里存 WGS-84，国内底图是 GCJ-02 | 打点前 wgs→gcj；「在地图上选位置」时 gcj→wgs |
| 3 | 聚合圈密密麻麻，看不出区域 | 默认 `radius:35 / maxZoom:18` | `radius:80 / maxZoom:20`，叶子上限 1 万→100 万 |
| 4 | 点右边照片面板时出现两套图层叠加、重复照片 | 拖动与点圈并发写 timeline + keyed each 复用旧 DOM + 150ms 过渡残留 | 选择防抖、viewId 加代数、禁过渡、布局不 defer |
| 5 | 打开地图是撒哈拉以南的全球视野 | 无 hash 时组件没拿到有效视野 | `map-default.json` + getter 兜底 |

## 为什么不直接改源码

线上跑的是打包好的 `www/_app/immutable/*.js`。改源码要装整套 Node/pnpm 构建链、重新打 spk，为了几个纯前端的展示层改动不划算；而且每次上游发版都要重新编译。

所以这里选择**在构建产物上打补丁**：按代码特征串定位 chunk（文件名带内容 hash，版本一变就换名），幂等替换，备份可回滚。

代价是锚点与上游产物绑定。**要把这些改动移植回源码，见 [PORTING.md](PORTING.md)**，里面逐处给出了上游 `.svelte` / `.ts` 的 diff。

## 目录

```
custom/immich-cn-map/
├── apply.py            # 入口：status / apply / restore / bump-version / clean-precompressed
├── patchset.py         # 补丁定义（每条都带“为什么”）
├── set_map_style.py    # 把样式写进 Immich system-config（换底图用）
├── PORTING.md          # 产物补丁 -> 上游源码的逐处 diff
├── CHANGELOG.md        # 变更说明（背景、改动清单、部署/验证/回滚）
└── assets/
    ├── amap-style.json     # 高德栅格样式（当前使用）
    ├── baidu-style.json    # 百度样式（可选，需 --with-baidu）
    └── map-default.json    # 默认视野（唯一真源，改这里再 apply）
```

## 用法

在 NAS 上（`www` 目录属主是 `sc-immich`，需要 sudo）：

```bash
cd /volume1/docker/immich-cn-map          # 把本目录放到别处也行

# 1) 看现状
sudo python3 apply.py status  /volume1/@appstore/immich/share/immich/www

# 2) 打补丁（幂等，已打过会 SKIP；先 --dry-run 可只看不改）
sudo python3 apply.py apply   /volume1/@appstore/immich/share/immich/www --dry-run
sudo python3 apply.py apply   /volume1/@appstore/immich/share/immich/www

# 3) 换版本号，让浏览器重新拉 chunk
sudo python3 apply.py bump-version /volume1/@appstore/immich/share/immich/www v20261124_181000

# 4) 删掉打包时留下的预压缩文件（旧的 .br/.gz 会让浏览器拿到旧 chunk）
sudo python3 apply.py clean-precompressed /volume1/@appstore/immich/share/immich/www

# 5) 重启生效
sudo /usr/syno/bin/synopkg restart immich
```

`apply` 做的事：备份原始产物为 `*.wbcn-orig` → 按内容定位 chunk → 逐条替换并 `node --check` 校验 → 安装 `assets/*.json` → 重写 `index.html` 头部的默认视野脚本。

## 补丁清单

### 地图 chunk（`Map.svelte` 编译产物）

| id | 改动 | 说明 |
|----|------|------|
| `map.cluster` | `radius 35→80`、`maxZoom 18→20`、`getClusterLeaves 1e4→1e6` | 按区域合并；大圈不再只统计前 1 万张 |
| `map.coord` | 注入 `__wb_wgs2gcj` / `__wb_gcj2wgs`，并改 5 处 | 打点 wgs→gcj；包围盒、点圈、选位置反向 gcj→wgs |
| `map.sel_debounce` | 拖动 180ms 防抖、点圈立即执行并取消拖动任务、1.2s 冷却 | 消除两次请求各写一份 timeline |
| `map.default_view` | `zoom` / `center` getter 兜底 | 只在“没有有效视野”时替换，带 hash 不干扰 |

### 时间线 chunk（`timeline-manager` 编译产物）

| id | 改动 | 说明 |
|----|------|------|
| `tl.force_options` | 去掉 `options` 相等的短路 | 「全库」→「圈内」只变 bbox，上游会直接 return |
| `tl.nodefer` | `updateGeometry(..., noDefer:true)` | day 不在视口时 layout 直接 return，旧 height 让多组照片落到同一 top |
| `tl.viewid` | viewId 加 `__wbGen` 代数、`#g` 加快照校验、`suspendTransitions` 收尾设为 `true` | keyed each 按 year-month 复用旧节点是叠加的根因 |

### 可选

`map.baidu_tiles`（`--with-baidu` 才打）：百度瓦片不吃标准 XYZ 编号，必须换算成 BD-09MC 行列号，同时把 GCJ-02 再偏到 BD-09。当前线上用高德，默认不打。

## 默认视野

`assets/map-default.json`：

```json
{
  "enabled": true,
  "zoom": 11,
  "center": { "lng": 104.0658, "lat": 30.6572 },
  "zoomReplaceBelow": 5
}
```

- `center` 用 **GCJ-02**（和高德底图同一坐标空间），不是 GPS 的 WGS-84。
- `zoomReplaceBelow`：缩放级别低于该值时判定“没有有效视野”（全球视图约 z2），强制回到默认视野；显式 hash（如 `#15/39.9/116.4`）不受影响。
- 改完这个 JSON 重跑 `apply` 即可，会同时更新 `www/map-default.json` 和 `index.html` 里的内联兜底值（避免首帧闪一下全球地图）。

## 换底图

样式是**运行时配置**，不用重新打包：

```bash
# 高德（当前）
python3 set_map_style.py --base-url http://127.0.0.1:2283 --api-key <KEY>
# 百度（需先 apply --with-baidu）
python3 set_map_style.py ... --style assets/baidu-style.json --as-url /baidu-style.json
python3 set_map_style.py ... --show        # 只看当前 map 配置
```

默认写 `data:` URL（自包含，重启不丢）；`--as-url /amap-style.json` 则写相对路径，改样式文件即可生效、无需再 PUT。原配置会备份到 `system-config-before-map-style.json`。

注意：样式只决定“底图长什么样”，坐标纠偏在 `map.coord` 里，换底图不会自动换坐标系——百度还需要 `--with-baidu` 的编号换算。

## 回滚

```bash
sudo python3 apply.py restore /volume1/@appstore/immich/share/immich/www
sudo python3 apply.py clean-precompressed /volume1/@appstore/immich/share/immich/www
sudo /usr/syno/bin/synopkg restart immich
```

`restore` 用 `*.wbcn-orig`（首次 apply 时备份的原始产物）覆盖回去。

## 验证

```bash
# 语法（apply 内部已做，也可手动）
node --check /tmp/x.mjs

# 页面可达
curl -sk -o /dev/null -w '%{http_code}\n' https://<你的域名>/map

# 瓦片请求（应看到 autonavi）
# 浏览器 F12 -> Network 过滤 webrd
```

本次改动在 immich-web 3.4.1 上做过往返验证：把补丁集应用回**未打补丁的原始 chunk**，结果与线上文件逐字节一致（只差版本号 query 参数和一段已废弃的百度函数）。

## 升级 Immich 之后

上游发版后 chunk hash 会变，`status` 会出现 `FAIL 锚点命中异常` 或 `PENDING`。这时的处理顺序：

1. 先跑 `status`，看哪几条失配；
2. 对照源码改 `patchset.py` 的锚点（改动位置在下面）；
3. 重新 `apply` + `bump-version` + `clean-precompressed` + 重启。

对应源码位置（供移植/提 PR）：

| 补丁 | 源码 |
|------|------|
| `map.cluster` `map.coord` `map.sel_debounce` `map.default_view` | `web/src/lib/components/shared-components/map/Map.svelte` |
| `tl.viewid` | `web/src/lib/managers/timeline-manager/timeline-month.svelte.ts:267`（`get viewId`） |
| `tl.force_options` | `web/src/lib/managers/timeline-manager/timeline-manager.svelte.ts:323`（`updateOptions`） |
| `tl.nodefer` | 同上 `timeline-manager.svelte.ts:295`（`updateGeometry`）；`timeline-day.svelte.ts:165`（`layout` 的 `noDefer`） |

## 已知遗留

- `index.html` 里还留着一句一次性清缓存脚本（`__wb_final_clear_20261124b`，靠 sessionStorage 只跑一次）。它是当初排查强缓存时加的临时手段，不属于定制逻辑，未纳入补丁集；不想要可以手动删掉。
- 线上地图 chunk 里还有 `window.__wbBaiduTR` 的死代码（切回高德后不再挂载到 `transformRequest`），保留无副作用；本补丁集默认不生成它。
- `www/amap-test.json` 是调试残留，可删。
