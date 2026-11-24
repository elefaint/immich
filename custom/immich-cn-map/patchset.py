#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Immich Web 地图定制：补丁定义。

每条 Patch 都是一组「原文 -> 替换」，锚定在 Immich 3.4.x 的前端构建产物上。
为什么不改源码：线上跑的是预编译包（www/_app/immutable 下的 hash chunk），
改源码要整套 Node 构建链 + 重新打 spk；而这里所有改动都在展示层，
不涉及后端 API / 数据库结构，打在产物上是成本最低、回滚最快的方式。

产物文件名带内容 hash（随版本变化），所以定位靠代码特征串而不是文件名，
见 apply.resolve_targets()。
"""

from dataclasses import dataclass, field

# ---------------------------------------------------------------- 坐标转换
# WGS-84 -> GCJ-02（国内地图底图使用的火星坐标）。标准 eviltransform 实现。
WGS2GCJ = (
    "function __wb_wgs2gcj(e,t){"
    "function a(e,t){return e<72.004||e>137.8347||t<0.8293||t>55.8271}"
    "function n(e,t){let n=-100+2*e+3*t+.2*t*t+.1*e*t+.2*Math.sqrt(Math.abs(e));"
    "n+=(20*Math.sin(6*e*Math.PI)+20*Math.sin(2*e*Math.PI))*2/3,"
    "n+=(20*Math.sin(t*Math.PI)+40*Math.sin(t/3*Math.PI))*2/3,"
    "n+=(160*Math.sin(t/12*Math.PI)+320*Math.sin(t*Math.PI/30))*2/3;return n}"
    "function r(e,t){let n=300+e+2*t+.1*e*e+.1*e*t+.1*Math.sqrt(Math.abs(e));"
    "n+=(20*Math.sin(6*e*Math.PI)+20*Math.sin(2*e*Math.PI))*2/3,"
    "n+=(20*Math.sin(e*Math.PI)+40*Math.sin(e/3*Math.PI))*2/3,"
    "n+=(150*Math.sin(e/12*Math.PI)+300*Math.sin(e/30*Math.PI))*2/3;return n}"
    "if(a(e,t))return[e,t];"
    "let i=n(e-105,t-35),o=r(e-105,t-35),s=t/180*Math.PI,l=Math.sin(s);"
    "l=1-.00669342162296594323*l*l;let u=Math.sqrt(l);"
    "return i=i*180/((6378245*(1-.00669342162296594323))/(l*u)*Math.PI),"
    "o=o*180/(6378245/u*Math.cos(s)*Math.PI),[e+o,t+i]} "
)

# GCJ-02 -> WGS-84：迭代反解，供「地图点选址」把高德坐标还原成相册要存的 WGS-84，
# 避免同一张照片被反复 +500 米漂移。
GCJ2WGS = (
    "function __wb_gcj2wgs(e,t){"
    "if(e<72.004||e>137.8347||t<0.8293||t>55.8271)return[e,t];"
    "let n=e,r=t;for(let i=0;i<4;i++){let o=__wb_wgs2gcj(n,r);n+=e-o[0],r+=t-o[1]}"
    "return[n,r]} "
)

# ------------------------------------------------------- timeline 相关常量
# 点圈选择：拖动地图会连续触发 onClusterSelect，与点圈叠在一起时面板会叠加。
# 拖动走 180ms trailing 防抖，点圈立即执行并取消待执行的拖动任务。
SEL_HELPERS = (
    "window.__wbSelT=0;"
    "const __wbSelLazy=(a,b)=>{clearTimeout(window.__wbSelT);"
    "window.__wbSelT=setTimeout(()=>{window.__wbSelT=0;r.onClusterSelect(a,b)},180)};"
    "const __wbSelNow=(a,b)=>{clearTimeout(window.__wbSelT);window.__wbSelT=0;"
    "r.onClusterSelect(a,b)};"
)


@dataclass
class Patch:
    """一条补丁：对单个文件按顺序做若干次精确替换。"""

    id: str
    title: str
    file: str            # "map" | "timeline" | 相对 www 的路径
    edits: list = field(default_factory=list)   # [(old, new), ...]
    why: str = ""
    optional: bool = False
    # 判定“已打”的特征串。注入型补丁的 new 里包含 old，而且后续补丁可能插到
    # new 中间，所以默认用“所有 new 完整命中”，必要时用更短的稳定标记覆盖。
    detect: tuple = ()

    def applied(self, text: str) -> bool:
        if self.detect:
            return all(d in text for d in self.detect)
        return all(new in text for _, new in self.edits)

    def partial(self, text: str) -> bool:
        if self.detect:
            return any(d in text for d in self.detect)
        return any(new in text for _, new in self.edits)


MAP_PATCHES = [
    Patch(
        id="map.cluster",
        title="聚合半径放大、保留到更深层级",
        file="map",
        edits=[
            ("cluster:{radius:35,maxZoom:18}", "cluster:{radius:80,maxZoom:20}"),
            ("getClusterLeaves(e,1e4,0)", "getClusterLeaves(e,1e6,0)"),
        ],
        why="默认 radius 35 会在城市尺度上炸出密密麻麻的小圈，看不清区域分布；"
            "放大到 80px 并按区域合并，maxZoom 20 让密集区在高倍下才拆开。"
            "另把单次取叶子数从 1 万提到 100 万，避免大圈只统计到前 1 万张。",
    ),
    Patch(
        id="map.coord",
        title="WGS-84 <-> GCJ-02 坐标纠偏",
        file="map",
        edits=[
            (
                "let Ge=e=>({type:`Feature`,geometry:{type:`Point`,coordinates:[e.lon,e.lat]},properties:",
                GCJ2WGS
                + WGS2GCJ
                + "let Ge=e=>({type:`Feature`,geometry:{type:`Point`,"
                  "coordinates:(()=>{let c=__wb_wgs2gcj(+e.lon,+e.lat);return[c[0],c[1]]})()},"
                  "properties:",
            ),
            (
                "for(let t of v())e.extend([t.lon,t.lat]);return e",
                "for(let t of v())e.extend(__wb_wgs2gcj(+t.lon,+t.lat));return e",
            ),
            (
                "function We(e){if(!A())return;let{lng:t,lat:n}=e.lngLat;le()({lng:t,lat:n}),",
                "function We(e){if(!A())return;let{lng:t,lat:n}=e.lngLat,c=__wb_gcj2wgs(t,n);"
                "le()({lng:c[0],lat:c[1]}),",
            ),
            (
                "Ke=e=>{let t=e,n=$.convert(t.geometry.coordinates);return{lat:n.lat,lon:n.lng,",
                "Ke=e=>{let t=e,n=$.convert(t.geometry.coordinates),c=__wb_gcj2wgs(n.lng,n.lat);"
                "return{lat:c[1],lon:c[0],",
            ),
            (
                "o={west:i?-180:t,south:i?-90:e.getSouth(),east:i?180:n,north:i?90:e.getNorth()};",
                "o=i?{west:-180,south:-90,east:180,north:90}:(()=>{"
                "let[a,b]=__wb_gcj2wgs(t,e.getSouth()),[c,d]=__wb_gcj2wgs(n,e.getNorth());"
                "return{west:a,south:b,east:c,north:d}})();",
            ),
            (
                "({lon:t,lat:n})=>e.contains([t,n])",
                "({lon:t,lat:n})=>{let s=__wb_wgs2gcj(+t,+n);return e.contains([s[0],s[1]])}",
            ),
        ],
        detect=("__wb_wgs2gcj", "__wb_gcj2wgs"),
        why="相册里存的是 GPS 的 WGS-84，高德底图是 GCJ-02，直接画会整体偏 400~600 米。"
            "打点前 wgs->gcj，反过来「在地图上选位置」时 gcj->wgs 再交给 Immich，"
            "否则保存的位置会被二次偏移。",
    ),
    Patch(
        id="map.sel_debounce",
        title="拖动与点圈的选择竞态（面板叠加的根因之一）",
        file="map",
        edits=[
            ("let Ze=()=>{", SEL_HELPERS + "let Ze=()=>{"),
            (
                "r.onClusterSelect(a,o)},Qe=()=>{ie()&&!nt.isViewing&&Ze()}",
                "__wbSelLazy(a,o)},Qe=()=>{"
                "if(Date.now()-(window.__wb_clusterTs||0)<1200)return;"
                "ie()&&!nt.isViewing&&Ze()}",
            ),
            (
                "let l={west:a,south:o,east:s,north:c};r.onClusterSelect(i,l)}else ne()(i)}",
                "let[lw,ls]=__wb_gcj2wgs(a,o),[le_,ln_]=__wb_gcj2wgs(s,c);"
                "let l={west:lw,south:ls,east:le_,north:ln_};"
                "window.__wb_clusterTs=Date.now();__wbSelNow(i,l)}"
                "else{clearTimeout(window.__wbSelT);window.__wbSelT=0;ne()(i)}}",
            ),
        ],
        why="moveend 与 click 可能只差几十毫秒，两个请求各写一次 timeline，旧的一份没被清掉就叠住了。",
    ),
    Patch(
        id="map.default_view",
        title="地图默认视野（打开就落在自己的区域）",
        file="map",
        edits=[
            (
                "get zoom(){return b()},get center(){return x()},get bounds(){return De}",
                "get zoom(){var _d=window.__wbMapDefault;if(!_d||_d.enabled===!1)return b();"
                "var _th=_d.zoomReplaceBelow==null?5:_d.zoomReplaceBelow,_z=b();"
                "return(_z===void 0||_z<_th)?(_d.zoom==null?11:_d.zoom):_z},"
                "get center(){var _d=window.__wbMapDefault;if(!_d||_d.enabled===!1)return x();"
                "var _th=_d.zoomReplaceBelow==null?5:_d.zoomReplaceBelow,_c=x(),_z=b();"
                "if(_c===void 0||_z===void 0||_z<_th){var _p=_d.center||{lng:104.0658,lat:30.6572},"
                "_l=+_p.lng,_a=+_p.lat,_o=window.__wbMapCenterObj;"
                "return(_o&&_o.lng===_l&&_o.lat===_a)?_o:(window.__wbMapCenterObj={lng:_l,lat:_a})}"
                "return _c},get bounds(){return De}",
            ),
        ],
        why="MapLibre 实例创建时读的是组件传下来的 zoom/center，无 hash 时上游给的是全球视野。"
            "这里在 getter 层兜底：只有“没有有效视野”时才替换，用户带 hash 或缩放过后不干扰。",
    ),
]

TIMELINE_PATCHES = [
    Patch(
        id="tl.force_options",
        title="timeline 不再因为 options 相等而跳过重载",
        file="timeline",
        edits=[
            (
                "async updateOptions(t){if(!t.deferInit&&!(this.#u!==e.#c&&Le(this.#u,t))){",
                "async updateOptions(t){if(!t.deferInit){",
            )
        ],
        why="从“全库”切到“圈内”时，只有 bbox/assetFilter 变了，上游判定 options 没变就直接 return，"
            "面板里留着上一批照片。",
    ),
    Patch(
        id="tl.nodefer",
        title="布局不再 defer，避免多个 day 落到同一 top",
        file="timeline",
        edits=[
            (
                "for(let t of this.months)J(this,t,{invalidateHeight:e});this.updateViewportProximities()",
                "for(let t of this.months)J(this,t,{invalidateHeight:e,noDefer:!0});"
                "this.updateViewportProximities()",
            )
        ],
        why="day 不在视口内时 layout 直接 return，旧 height 被沿用，累加 top 后两组照片落在同一位置。",
    ),
    Patch(
        id="tl.viewid",
        title="month 的 key 加代数，强制全量重建",
        file="timeline",
        edits=[
            (
                "get viewId(){let{year:e,month:t}=this.yearMonth;return e+`-`+t}",
                "get viewId(){let{year:e,month:t}=this.yearMonth;"
                "return (this.__wbGen||0)+`-`+e+`-`+t}",
            ),
            (
                "async#g(){let e=await f({...P.params,...this.#u});this.months=e.map(e=>{"
                "let t=new we(e.timeBucket);return new bi(this,{year:t.getUTCFullYear(),"
                "month:t.getUTCMonth()+1},e.count,!1,this.#u.order,this.#u.orderBy)}),",
                "async#g(){let u=this.#u,e=await f({...P.params,...u});if(this.#u!==u)return;"
                "window.__wbGen=(window.__wbGen||0)+1;let __g=window.__wbGen;"
                "this.months=e.map(e=>{let t=new we(e.timeBucket);let __m=new bi(this,"
                "{year:t.getUTCFullYear(),month:t.getUTCMonth()+1},e.count,!1,u.order,u.orderBy);"
                "__m.__wbGen=__g;return __m}),",
            ),
            (
                "this.updateViewportGeometry(!1),this.#v()}finally{this.suspendTransitions=!1}}}",
                "this.updateViewportGeometry(!1),this.#v()}finally{this.suspendTransitions=!0}}}",
            ),
        ],
        why="key 只用 year-month，两次加载的 2026-11 是同一个 key，Svelte keyed each 直接复用旧 DOM 节点，"
            "旧 top/transform 残留就叠住了。加代数让每次重建 key 全变；同时禁掉 150ms 过渡，"
            "避免旧位置动画与新位置同时存在。",
    ),
]


# ------------------------------------------------------------ 可选：百度底图
# 当前线上用的是高德，百度这段默认不启用（--with-baidu 才打）。
# 百度瓦片不吃标准 XYZ 编号，要用 BD-09MC（原点左下、y 轴向上）的整数行列号，
# 所以必须把 MapLibre 请求的 XYZ 反算成经纬度 -> GCJ 加偏 -> BD 加偏 -> 墨卡托行列号。
# 直接把 style 的 tiles 写成 standard XYZ 会拿到空白图。
BAIDU_TR = (
    'window.__wbBaiduTR=function(e,t){let u=typeof e==="string"?e:(e&&e.url||"");'
    'let mi=u.indexOf("__wb_baidu__/");if(mi>=0){'
    'let m=u.slice(mi+13).replace(/\\.png.*$/,"").split("/");'
    "let z=+m[0],x=+m[1],y=+m[2];let n=Math.pow(2,z);"
    "let lng=x/n*360-180;"
    "let lat=180/Math.PI*Math.atan(Math.sinh(Math.PI*(1-2*y/n)));"
    "let blng=lng,blat=lat;"
    "if(lng>=72.004&&lng<=137.8347&&lat>=0.8293&&lat<=55.8271){"
    "let xx=lng,yy=lat,"
    "zz=Math.sqrt(xx*xx+yy*yy)+0.00002*Math.sin(yy*Math.PI*3000/180),"
    "th=Math.atan2(yy,xx)+0.000003*Math.cos(xx*Math.PI*3000/180);"
    "blng=zz*Math.cos(th)+0.0065;blat=zz*Math.sin(th)+0.006}"
    "let R=6378137;"
    "let xmc=R*blng*Math.PI/180,ymc=R*Math.log(Math.tan(Math.PI/4+blat*Math.PI/360));"
    "let k=Math.pow(2,z-18)/256;"
    "let bdx=Math.floor(xmc*k),bdy=Math.floor(ymc*k);"
    "let srv=((x+y+z)%4+4)%4;"
    'let url="https://maponline"+srv+".bdimg.com/tile/?qt=tile&x="+bdx+"&y="+bdy'
    '+"&z="+z+"&styles=pl&scaler=1&udt=20240101";return{url:url}}return void 0};'
)

OPTIONAL_PATCHES = [
    Patch(
        id="map.baidu_tiles",
        title="可选：百度底图（BD-09MC 瓦片编号 + GCJ->BD 加偏）",
        file="map",
        optional=True,
        edits=[
            ("let Ge=e=>({type:`Feature`", BAIDU_TR + "let Ge=e=>({type:`Feature`"),
            (
                "attributionControl:!1,diffStyleUpdates:!0,",
                "attributionControl:!1,diffStyleUpdates:!0,transformRequest:window.__wbBaiduTR,",
            ),
        ],
        why="百度瓦片编号不是标准 XYZ，不换算会拿到空白图；同时需要把 GCJ-02 再偏到 BD-09。"
            "启用方式：apply --with-baidu 后把系统配置里的 map.lightStyle 指向 /baidu-style.json。",
    ),
]
