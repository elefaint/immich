# 从产物补丁移植到上游源码（PORTING.md）

本目录的 `patchset.py` 打在 Immich **构建产物**上（便于在 NAS 上直接部署）。
本文档列出同一批改动在**上游 TypeScript / Svelte 源码**里应该怎么写，供以后从源码构建时照搬。

> 版本说明：本仓库 `main` 是 `3.4.0-rc.0`，线上实际运行 `3.4.1`。
> 两版这两个文件的逻辑一致，但函数名/行号略有出入：
>
> | 编译产物 | 上游源码 |
> |---|---|
> | `Ge()` | `asFeature()` |
> | `$.convert()` | `LngLat.convert()` |
> | `We()` | `handleMapClick()` |
> | `Ke()` | `asMarker()` |
> | `Ze()` | `handleViewportSelect()` |
> | `Qe()` | `handleMoveEnd()` |
> | `Ue()` | `handleClusterClick()` |
> | `#g()` | `#initializeTimelineMonths()` |
> | `#_()` | `#init()` |
> | `#u` | `#options` |
> | `f()` | `getTimeBuckets()` |
> | `J()` | `updateGeometry()` |
> | `updateViewportGeometry()` | `refreshLayout()` |
>
> 定位请以代码内容为准，不要照抄行号。

---

## 0. 新增源码文件：`wgs2gcj.ts`

上游没有坐标系转换，先新增一个工具模块（例如 `web/src/lib/utils/geo-cn.ts`）：

```ts
// WGS-84 -> GCJ-02（eviltransform 标准实现）
const outOfChina = (lng: number, lat: number) =>
  lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271;

function transformLat(x: number, y: number) {
  let ret = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
  ret += ((20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2) / 3;
  ret += ((20 * Math.sin(y * Math.PI) + 40 * Math.sin((y / 3) * Math.PI)) * 2) / 3;
  ret += ((160 * Math.sin((y / 12) * Math.PI) + 320 * Math.sin((y * Math.PI) / 30)) * 2) / 3;
  return ret;
}
function transformLon(x: number, y: number) {
  let ret = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
  ret += ((20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2) / 3;
  ret += ((20 * Math.sin(x * Math.PI) + 40 * Math.sin((x / 3) * Math.PI)) * 2) / 3;
  ret += ((150 * Math.sin((x / 12) * Math.PI) + 300 * Math.sin((x / 30) * Math.PI)) * 2) / 3;
  return ret;
}

export function wgs2gcj(lng: number, lat: number): [number, number] {
  if (outOfChina(lng, lat)) return [lng, lat];
  let dLat = transformLat(lng - 105, lat - 35);
  let dLng = transformLon(lng - 105, lat - 35);
  const radLat = (lat / 180) * Math.PI;
  let magic = Math.sin(radLat);
  magic = 1 - 0.00669342162296594323 * magic * magic;
  const sqrtMagic = Math.sqrt(magic);
  dLat = (dLat * 180) / (((6378245 * (1 - 0.00669342162296594323)) / (magic * sqrtMagic)) * Math.PI);
  dLng = (dLng * 180) / ((6378245 / sqrtMagic) * Math.cos(radLat) * Math.PI);
  return [lng + dLng, lat + dLat];
}

// GCJ-02 -> WGS-84：4 次迭代反解，避免反复保存时累积 +500m 漂移
export function gcj2wgs(lng: number, lat: number): [number, number] {
  if (outOfChina(lng, lat)) return [lng, lat];
  let x = lng;
  let y = lat;
  for (let i = 0; i < 4; i++) {
    const [gx, gy] = wgs2gcj(x, y);
    x += lng - gx;
    y += lat - gy;
  }
  return [x, y];
}
```

---

## 1. `Map.svelte`：聚合参数

文件：`web/src/lib/components/shared-components/map/Map.svelte`

```diff
- const leaves = await mapSource.getClusterLeaves(clusterId, 10_000, 0);
+ const leaves = await mapSource.getClusterLeaves(clusterId, 1_000_000, 0);
```

```diff
- cluster={{ radius: 35, maxZoom: 18 }}
+ cluster={{ radius: 80, maxZoom: 20 }}
```

原因：默认 radius 35 会在城市尺度炸出大量小圈；改为 80 后按区域合并。
叶子上限 1 万会在大圈时被截断（面板照片不全）。

## 2. `Map.svelte`：坐标纠偏

同一文件，先加 import：

```diff
+ import { gcj2wgs, wgs2gcj } from '#lib/utils/geo-cn';
```

**a) 初始包围盒**（`initialBounds`）

```diff
- bounds.extend([marker.lon, marker.lat]);
+ bounds.extend(wgs2gcj(marker.lon, marker.lat));
```

**b) 打点（`asFeature`）**

```diff
- geometry: { type: 'Point', coordinates: [marker.lon, marker.lat] },
+ geometry: { type: 'Point', coordinates: wgs2gcj(marker.lon, marker.lat) },
```

**c) 点弹窗还原（`asMarker`）**

```diff
  const coords = LngLat.convert(featurePoint.geometry.coordinates as [number, number]);
+ const [lon, lat] = gcj2wgs(coords.lng, coords.lat);
  return {
-   lat: coords.lat,
-   lon: coords.lng,
+   lat,
+   lon,
```

**d) 地图点选位置（`handleMapClick`）**

```diff
- onClickPoint({ lng, lat });
+ const [wgsLng, wgsLat] = gcj2wgs(lng, lat);
+ onClickPoint({ lng: wgsLng, lat: wgsLat });
```

注意：只把交给 Immich 保存的值转回 WGS；`new Marker().setLngLat([lng, lat])` 保持 GCJ，继续贴在底图上。

**e) 聚合圈 bbox（`handleClusterClick`）**

```diff
- const bbox = { west, south, east, north };
+ const [bw, bs] = gcj2wgs(west, south);
+ const [be, bn] = gcj2wgs(east, north);
+ const bbox = { west: bw, south: bs, east: be, north: bn };
```

这里的叶子坐标来自 `asFeature`，已经是 GCJ，必须转回 WGS 才能查后端。

**f) 视口选择（`handleViewportSelect`）**

```diff
- : mapMarkers.filter(({ lon, lat }) => bounds.contains([lon, lat])).map(({ id }) => id);
+ : mapMarkers
+     .filter(({ lon, lat }) => {
+       const [x, y] = wgs2gcj(lon, lat);
+       return bounds.contains([x, y]);
+     })
+     .map(({ id }) => id);
```

```diff
- const bbox: SelectionBBox = {
-   west: showAll ? -180 : west,
-   south: showAll ? -90 : bounds.getSouth(),
-   east: showAll ? 180 : east,
-   north: showAll ? 90 : bounds.getNorth(),
- };
+ const [bw, bs] = showAll ? [-180, -90] : gcj2wgs(west, bounds.getSouth());
+ const [be, bn] = showAll ? [180, 90] : gcj2wgs(east, bounds.getNorth());
+ const bbox: SelectionBBox = { west: bw, south: bs, east: be, north: bn };
```

## 3. `Map.svelte`：拖动 / 点圈的选择竞态

在同一文件里包装 `onClusterSelect`，把「拖动地图选视口」和「点圈」两条路径分开：

```ts
let selectTimer: ReturnType<typeof setTimeout> | undefined;
let lastClusterSelectAt = 0;

const selectNow = (ids: string[], bbox: SelectionBBox) => {
  clearTimeout(selectTimer);
  selectTimer = undefined;
  lastClusterSelectAt = Date.now();
  onClusterSelect?.(ids, bbox);
};
const selectLazy = (ids: string[], bbox: SelectionBBox) => {
  clearTimeout(selectTimer);
  selectTimer = setTimeout(() => {
    selectTimer = undefined;
    onClusterSelect?.(ids, bbox);
  }, 180);
};
```

改动点：

```diff
  // handleClusterClick，多资产分支
- onClusterSelect(ids, bbox);
+ selectNow(ids, bbox);
   return;
  }
  // 单资产分支也要取消待执行的拖动任务
- onSelect(ids);
+ clearTimeout(selectTimer);
+ selectTimer = undefined;
+ onSelect(ids);
```

```diff
  // handleViewportSelect 末尾
- onClusterSelect(visibleIds, bbox);
+ selectLazy(visibleIds, bbox);
```

```diff
  const handleMoveEnd = () => {
+   if (Date.now() - lastClusterSelectAt < 1200) {
+     return; // 面板 resize 触发的 moveend 会覆盖刚点中的圈
+   }
    if (viewportGridActive && !assetViewerManager.isViewing) {
```

## 4. `Map.svelte` + `app.html`：默认视野

产物里的做法是在 `svelte-maplibre` 组件的 `get zoom()/get center()` 上兜底；
从源码构建时更干净的做法是直接改默认值。

**a) `Map.svelte` 的属性默认值**

```diff
- zoom = undefined,
- center = $bindable(undefined),
+ zoom = globalThis.__wbMapDefault?.zoom ?? 11,
+ center = $bindable(
+   globalThis.__wbMapDefault?.center ?? { lng: 104.0658, lat: 30.6572 },
+ ),
```

需要给 `globalThis` 加一句类型声明（或改成 `(globalThis as any).__wbMapDefault`）。
对象引用要固定：把默认值提到模块级常量，避免每次渲染生成新对象导致 `$effect` 反复 `jumpTo`。

> 设置了 zoom/center 会让 `initialBounds` 的自动 fit 失效（其条件里检查了这两个值），
> 这正是想要的效果：打开即落在默认区域，而不是自动 fit 到全部照片。

**b) `web/src/app.html` 的 `<head>` 里插入两段脚本**

第一段：写死兜底值，再异步用 `/map-default.json`（静态资源）覆盖。

```html
<script>
  window.__wbMapDefault = { "enabled": true, "zoom": 11, "center": { "lng": 104.0658, "lat": 30.6572 }, "zoomReplaceBelow": 5 };
  fetch('/map-default.json', { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => { if (j && typeof j === 'object') window.__wbMapDefault = j; })
    .catch(() => {});
</script>
```

第二段：URL 是 `/map` 且 hash 的 zoom 低于阈值时抹掉 hash，否则 MapLibre 的 Hash 模块会覆盖默认视野。

```html
<script>
  try {
    const p = location.pathname, s = location.search;
    const m = /#([0-9]+(?:\.[0-9]+)?)\//.exec(location.hash || '');
    if (m && /\/map\/?$/.test(p)) {
      const th = window.__wbMapDefault?.zoomReplaceBelow || 5;
      if (+m[1] < th) history.replaceState(null, '', p + s);
    }
  } catch {}
</script>
```

`map-default.json` 的 `center` 是 **GCJ-02**（和高德底图同坐标空间），不是 WGS-84。

## 5. `timeline-manager.svelte.ts`：取消 options 相等跳过

文件：`web/src/lib/managers/timeline-manager/timeline-manager.svelte.ts`

```diff
- import { clamp, isEqual } from 'lodash-es';
+ import { clamp } from 'lodash-es';
```

```diff
  async updateOptions(options: TimelineManagerOptions) {
    if (options.deferInit) {
      return;
    }
-   if (this.#options !== TimelineManager.#INIT_OPTIONS && isEqual(this.#options, options)) {
-     return;
-   }
```

原因：从「全库」切到「圈内」时，上游认为 options 深比较相等就整段跳过，面板里留着上一批照片。

## 6. `timeline-manager.svelte.ts`：布局不 defer

同文件，`refreshLayout()` 内部：

```diff
  override refreshLayout() {
    for (const month of this.months) {
-     updateGeometry(this, month, { invalidateHeight: true });
+     updateGeometry(this, month, { invalidateHeight: true, noDefer: true });
    }
    this.updateViewportProximities();
  }
```

原因：day 不在视口附近时 layout 直接 return，沿用旧的 `height=0`，`top` 累加后多个 day 落在同一位置。

## 7. `timeline-month.svelte.ts` + `timeline-manager.svelte.ts`：month key 加代数 + 禁动画

**a) `web/src/lib/managers/timeline-manager/timeline-month.svelte.ts`**

```diff
  export class TimelineMonth {
+   __wbGen: number | undefined;
```

```diff
  get viewId() {
    const { year, month } = this.yearMonth;
-   return year + '-' + month;
+   return (this.__wbGen ?? 0) + '-' + year + '-' + month;
  }
```

**b) `timeline-manager.svelte.ts` 的 `#initializeTimelineMonths()`**

```diff
  async #initializeTimelineMonths() {
-   const timebuckets = await getTimeBuckets({
-     ...authManager.params,
-     ...this.#options,
-   });
+   const options = this.#options;                 // 快照
+   const timebuckets = await getTimeBuckets({
+     ...authManager.params,
+     ...options,
+   });
+   if (this.#options !== options) return;         // 过期响应直接丢弃
+   const gen = ++__wbGeneration;                  // 模块级 let __wbGeneration = 0
    this.months = timebuckets.map((timeBucket) => {
      const date = new SvelteDate(timeBucket.timeBucket);
-     return new TimelineMonth(this, {...}, timeBucket.count, false, this.#options.order, this.#options.orderBy);
+     const month = new TimelineMonth(this, {...}, timeBucket.count, false, options.order, options.orderBy);
+     month.__wbGen = gen;
+     return month;
    });
    this.albumAssets.clear();
    this.updateViewportGeometry(false);
  }
```

**c) 同文件 `updateOptions()` 的 `finally`**

```diff
    } finally {
-     this.suspendTransitions = false;
+     this.suspendTransitions = true;
    }
```

`set suspendTransitions(true)` 会在 `VirtualScrollManager` 里触发一个 1 秒的 debounce 再置 false，
所以这里写 `true` 的实际效果是「重建后 1 秒内禁用动画」，覆盖掉 150ms 的 `transition-all` 过渡态。

**d) 为什么必须做 a+b+c**

`Timeline.svelte` 用的是 keyed each：

```svelte
{#each timelineManager.months as timelineMonth (timelineMonth.viewId)}
```

两次加载都会产生 `2026-11` 这个 key，Svelte 会复用旧 DOM，旧的 `top`/`transform` 残留导致照片组压在同一位置。
仅改 key 还不够：重建瞬间仍处于 150ms 过渡态，会短暂同时看到新旧位置。

## 8. 可选：百度底图

默认不启用。源码侧的接法是把翻译函数单独放一个模块，然后传给 Map 构造参数：

```diff
  <MapLibre
    {hash}
    style=""
+   transformRequest={globalThis.__wbBaiduTR}
```

函数体见 `OPTIONAL_PATCHES` 里的 `BAIDU_TR`。注意 MapLibre v5 的
`transformRequest(url: string, resourceType)` 第一个参数是**字符串**，不是 `{url}` 对象。
非百度 URL 返回 `undefined` 让 MapLibre 用原请求。

---

## 非源码改动（构建/部署时另外处理）

| 项 | 内容 |
|---|---|
| 静态资源 | `assets/amap-style.json` / `baidu-style.json` / `map-default.json` 放进 `www/` |
| 系统配置 | `system_config` 的 `cfg['map']['lightStyle']`、`['darkStyle']` 指向 `/amap-style.json`（嵌套字段，不是扁平 key） |
| 缓存 | 升级全部 `__wbv__` / `__wb_ver__` 版本号；删除 `_app/immutable` 下 `.br` / `.gz` |
| 服务 | `synopkg restart immich` |
