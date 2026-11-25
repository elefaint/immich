# 变更说明：Immich 中国地图定制（V1）

> 交付日期：2026-11-24
> 线上 Immich 版本：3.4.1（仓库 main 为 3.4.0-rc.0）
> 最终线上前端版本号：`v20261124_181000`
> 仓库位置：`custom/immich-cn-map/`（提交 `595177a` / `e65e361`）

---

## 1. 一句话摘要

针对群晖上部署的 Immich，把地图底图换成高德、把照片坐标从 WGS-84 纠偏到 GCJ-02、把聚合改为按区域合并、修复点聚合圈后右侧照片面板叠加/错乱，并让地图打开时直接落在默认区域（成都 z11）。所有改动都在**前端构建产物**上，未改动后端 API、数据库结构和服务端配置逻辑（仅修改了系统配置中的一个样式 URL 字段）。

---

## 2. 背景与问题清单

| # | 现象 | 根因 | 本次处理 |
|---|---|---|---|
| 1 | 地图底图在国内不可用/偏移 | 默认 OSM 底图不符合国内使用习惯 | 换高德栅格底图，样式通过系统配置下发 |
| 2 | 照片标记整体偏 400~600 米 | 相册 GPS 存的是 WGS-84，高德底图是 GCJ-02，MapLibre 不做坐标转换 | 新增双向纠偏函数，打点前 WGS→GCJ，保存位置/查后端时 GCJ→WGS |
| 3 | 地图上市内出现密密麻麻的小数字圈 | 上游默认 `radius:35, maxZoom:18`，在城市尺度聚合过细 | `radius:80, maxZoom:20`，并把单次取叶子上限从 1 万提到 100 万 |
| 4 | 点圈后右侧面板为空/重复照片/多批数据交错 | 多个原因叠加：坐标系不一致、moveend 二次覆盖、options 深比较跳过、请求竞态、keyed-each 复用 DOM + 150ms 过渡态 | 6 处修复，最终以「viewId 加代数 + 重建期禁动画」根治 |
| 5 | 打开地图先看到全球视图 | MapLibre 的 hash/默认视野逻辑，上游无默认区域配置 | 新增 `map-default.json` + 入口脚本兜底 + 组件 getter 兜底 |

---

## 3. 变更范围

### 3.1 修改的文件

| 目标 | 说明 | 变更点数 |
|---|---|---|
| `www/_app/immutable/chunks/<map chunk>` | 地图组件（上游 `Map.svelte` 编译产物） | 4 组补丁 / 12 处替换 / 3 段注入 |
| `www/_app/immutable/chunks/<timeline chunk>` | 时间线管理器（上游 `timeline-manager.svelte.ts` 等） | 3 组补丁 / 5 处替换 |
| `www/index.html` | 入口页 | 头部插入 2 段内联脚本 |
| 系统配置 `system_config` | `cfg['map']['lightStyle']`、`['darkStyle']` | 指向 `/amap-style.json`（嵌套字段，非扁平 key） |

### 3.2 新增的静态资源（`www/`）

- `amap-style.json`：高德栅格瓦片样式（当前启用）
- `baidu-style.json`：百度样式占位（备用，默认不启用）
- `map-default.json`：默认视野配置，内容是：
  ```json
  { "enabled": true, "zoom": 11, "center": { "lng": 104.0658, "lat": 30.6572 }, "zoomReplaceBelow": 5 }
  ```
  注意 `center` 是 **GCJ-02**，和高德底图同坐标系，不是 WGS-84。

### 3.3 仓库中交付的工具

| 文件 | 用途 |
|---|---|
| `apply.py` | `status` / `apply` / `restore` / `bump-version` / `clean-precompressed` |
| `patchset.py` | 7 条必打补丁 + 1 条可选百度补丁，每条带改动原因 |
| `set_map_style.py` | 写 `system-config.map.lightStyle/darkStyle` |
| `assets/*` | 三个 JSON 的唯一真源 |
| `PORTING.md` | 产物补丁 → 上游源码的逐处 diff（给要从源码构建的开发者） |
| `README.md` | 用法、补丁清单、回滚、升级后如何重新对齐锚点 |

---

## 4. 详细变更

### 4.1 地图：底图与坐标

- 注入 `__wb_wgs2gcj()` / `__wb_gcj2wgs()`（eviltransform 标准实现 + 4 次迭代反解）。
- 六处调用点：打点 `asFeature`、初始包围盒 `initialBounds`、点弹窗 `asMarker`、地图点选位置 `handleMapClick`、聚合圈 bbox、视口 `contains` 判断。
- 关键约定：**地图上的点用 GCJ，交给后端/数据库的值必须是 WGS**。点选位置时只把回调参数转回 WGS，marker 本身继续留在 GCJ 坐标上贴底图。
- 百度（可选，未启用）：`transformRequest` 把标准 XYZ 反算成 BD-09MC 私有瓦片编号。MapLibre v5 的 `transformRequest(url, resourceType)` 首参是**字符串**，不是 `{url}`；非百度 URL 必须返回 `undefined`。

### 4.2 地图：聚合与选择

- `cluster:{radius:35,maxZoom:18}` → `cluster:{radius:80,maxZoom:20}`；`getClusterLeaves(e,1e4,0)` → `1e6`。
- 注入 `selectNow` / `selectLazy` 包装 `onClusterSelect`：拖动地图走 180ms trailing 防抖，点圈立即执行并取消 pending 任务；单资产圈分支也补了 `clearTimeout`。
- `handleMoveEnd` 加 1200ms 抑制窗，挡住面板 resize 触发的 `moveend` 覆盖刚点中的圈。

### 4.3 时间线面板叠加（重点）

历史上定位过多轮，最终确认的真因有两个，都在**渲染层**：

1. `Timeline.svelte` 用 `{#each months as month (month.viewId)}`，而上游 `viewId` 只有 `year-month`。拖动刷新（全库）与点圈（圈内）常含相同的月份 → key 不变 → Svelte 复用旧 DOM，旧的 `top`/`transform` 残留。
2. day 组有 `transition-all`，时长由 `suspendTransitions?0:150` 决定；原 `updateOptions` 的 `finally` 同步把 `suspendTransitions` 置 false，导致重建后 150ms 内新旧位置同时可见。

修复：

- `viewId` 加代数前缀（`#g()` 每次加载递增 `window.__wbGen` 并挂到新建 month 上），强制 keyed each 全量重建。
- `updateOptions` 的 `finally` 改为 `suspendTransitions=true`；上游 setter 带 1s debounce，实际效果是重建后 1 秒内无动画。
- 同时保留三项数据层修复：`updateOptions` 不再因 `isEqual` 跳过、`#g()` 加 options 快照校验丢弃过期响应、`refreshLayout` 布局加 `noDefer:true`。

> 结论：仅靠 bbox/时序补丁无法根治面板叠加；必须处理 key 稳定性 + CSS 过渡态。

### 4.4 默认视野

- `map-default.json` 是唯一真源，`apply` 时同步写入入口页的兜底脚本。
- 入口页脚本一：先写死默认值，再异步 `fetch('/map-default.json')` 覆盖，保证用户改 JSON 无需重新打补丁。
- 入口页脚本二：路径为 `/map` 且 hash 里的 zoom 小于 `zoomReplaceBelow` 时，用 `history.replaceState` 抹掉 hash。用户带 `#15/39.9087/116.3975`（北京）这类正常链接不受影响。
- 组件 getter 层兜底 `zoom`/`center`；`center` 缓存为同一对象引用，避免 props 同步 effect 反复 `easeTo`。

> 踩过的坑：不要在 `onload` 里 `jumpTo`（事件有时不触发），也不要靠 `getZoom()` 判断（它返回组件 props 默认值 11，与画面实际 zoom 不符）。

---

## 5. 部署与验证

### 5.1 部署顺序（tools 不会代劳最后两步，避免误重启线上服务）

```bash
python3 apply.py status  <www>
python3 apply.py apply   <www>     # 建议先 --dry-run
python3 apply.py bump-version <www> v20261124_181000
find <www>/_app/immutable \( -name '*.br' -o -name '*.gz' \) -delete
sudo /usr/syno/bin/synopkg restart immich
python3 set_map_style.py ...       # 指向 amap-style.json
```

三个**必须**做的配套动作，漏一个都会表现为「改了没生效」：

1. 升级**两套**版本号（`__wbv__` 用于 chunk 内部 import，`__wb_ver__` 用于 index.html 入口引用）。
2. 删除 `.br` / `.gz` 预压缩文件 —— express 静态服务会优先返回它们，浏览器拿到的还是旧 chunk；验证时不能用裸 `curl`，要用 `curl --compressed -H 'Accept-Encoding: br'`。
3. `synopkg restart immich` —— 服务进程启动后持有旧资源快照，不重启不生效。

### 5.2 已完成的验证

- **反向重建**：从未打补丁的原始 chunk 重放补丁集，与线上文件逐字节一致（差异仅版本号 query 与一段已废弃的百度函数）。
- **幂等性**：连续 3 次 `apply`，`index.html` 的 md5 不变。
- **语法**：`node --check` 全部通过；预压缩残留 0；HTTPS 200。
- **浏览器实测**：高德瓦片正常、照片与聚合圈对齐；无 hash → 成都 z11，全球级 hash 被抹除，北京 z15 被尊重，SPA 从 `/photos` 进入也落在默认视野。
- **面板**：用户确认 v154500 后「彻底解决了」，后续 v181000 回归验证补丁全部在位。

---

## 6. 回滚

```bash
python3 apply.py restore <www>     # 用 *.wbcn-orig 备份还原
python3 apply.py bump-version <www> <新版本号>
find <www>/_app/immutable \( -name '*.br' -o -name '*.gz' \) -delete
sudo /usr/syno/bin/synopkg restart immich
```

需同时把 `map.lightStyle/darkStyle` 改回原始值；回滚后同样要走完版本号 + 预压缩 + 重启三步。

---

## 7. 风险与注意事项

| 风险 | 说明 |
|---|---|
| 锚点绑定版本 | 补丁按代码特征串定位 chunk（不硬编码 hash 文件名）。**Immich 升级后必须重新对齐锚点**，按 README 的「升级 Immich 之后」章节操作 |
| 两套版本号 | 只升 `__wbv__` 或只升 `__wb_ver__` 都会导致浏览器命中旧 chunk，表现为「有时新有时旧的玄学问题」 |
| 预压缩文件 | 任何静态改动后都要删 `.br`/`.gz`，否则浏览器永远拿旧代码 |
| 百度接口 | 使用非公开瓦片接口（`udt` 时间戳），未来可能失效；当前只是死代码，未启用。失效时切回 `amap-style.json` 即可 |
| 默认视野配置 | `center` 是 GCJ-02；如果改成 WGS 坐标会出现约 500m 偏移 |
| 坐标库兼容 | GCJ/WGS 转换只对国内范围生效；境外的经纬度原样返回 |

---

## 8. 后续建议

1. 若要从源码构建而不是打产物补丁，按 `PORTING.md` 逐处移植；其中 `geo-cn.ts` 是新增模块，其余都是对现有文件的局部修改。
2. 上游修掉 keyed-each 复用 / 异步竞态后，可考虑移除对应的产物补丁，减少维护面。
3. 把 `apply.py` 纳入发布流程时，建议把「升版本号 + 删预压缩 + 重启」做成显式确认步骤，而不是自动执行。

---

## 9. 附：变更涉及的源码位置（速查）

| 变更 | 上游源码 |
|---|---|
| 聚合 / 坐标 / 默认视野 | `web/src/lib/components/shared-components/map/Map.svelte` |
| 选择防抖 | 同上（`handleClusterClick` / `handleViewportSelect` / `handleMoveEnd`） |
| options 重载 / 请求快照 / 布局 / 动画 | `web/src/lib/managers/timeline-manager/timeline-manager.svelte.ts` |
| viewId | `web/src/lib/managers/timeline-manager/timeline-month.svelte.ts` |
| keyed each / transition | `web/src/lib/components/timeline/Timeline.svelte`、`Month.svelte` |
| 入口脚本 | `web/src/app.html` |

完整逐处 diff 见 `PORTING.md`。
