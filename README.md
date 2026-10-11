# Global Integration Challenge · 复刻修复版

原站：<https://yan-shipeng.github.io/integration/>

## 问题

**胜利结算页的底部按钮被截断，看不到也点不到。**

实测（视口 375×667，即 iPhone SE / 多数小屏安卓）：

| 元素 | top | bottom | 结果 |
|---|---|---|---|
| View Action Log | 645 | 693 | 溢出 26px |
| Export PDF | 703 | 751 | 溢出 84px |
| **Restart** | 758 | **806** | **溢出 139px** |

即按钮条整体落在视口之外 139px。更糟的是**页面无法滚动到底**，
用户没有任何办法把按钮滚进视野，只能卡在结算页出不去。

### 根本原因

原站是**两层 iframe 嵌套**：

```
yan-shipeng.github.io/integration/          ← 外层 index.html，只放一个 iframe
  └─ iframe → china-game-mzbua6le.manus.space/en   ← React 外壳
       └─ srcdoc iframe → 游戏本体（375KB 单文件）
```

游戏本体内层滚动容器的**高度未被约束**，导致 `clientHeight === scrollHeight`（都是 846px）。
既然 `scrollHeight` 不超过 `clientHeight`，就**不产生可滚动区域**，
内容因此直接溢出到视口之外 —— 这就是"滚也滚不到"的原因。

雪上加霜的是移动端还有一条 **56px 高的固定底部导航栏**（Network / Decide / Log），
`z-index:200`，而 `.app` 只给了 72px 的 `padding-bottom`，余量在长内容页上不够。

## 修复

三层修复，全部通过**追加覆盖式 CSS/JS** 实现，**未改动任何一行原有游戏逻辑**：

1. **约束滚动容器并开启滚动** — `html,body { height:100% }` + `overflow-y:auto`，
   让页面真正产生可滚动区域，内容不再溢出。
2. **结算页隐藏底部导航栏** — 结算页本身已自带 View Log / Export PDF / Restart，
   功能与导航栏重复；隐藏后从根上消除遮挡（`body.screen-ending #mobileBottomNav`）。
3. **补齐安全间距** — `env(safe-area-inset-bottom)` 兜住 iOS 小横条；
   矮屏（≤700px 高）额外收紧内边距，保证按钮首屏可见。
   另加运行时 JS 兜底：结算页渲染后主动测量并滚动，防止个别浏览器高度计算差异。
4. **决策页悬浮执行条**同步抬高到导航栏之上（`bottom: calc(57px + safe-area)`）。

## 验证结果

Playwright 实测 5 种视口，结算页三个按钮**全部完整可见且可命中点击**，JS 零报错：

| 设备 | 视口 | View Action Log | Export PDF | Restart |
|---|---|---|---|---|
| iPhone SE | 375×667 | ✅ 421–469 | ✅ 480–528 | ✅ 538–577 |
| iPhone 12 | 390×844 | ✅ 600–649 | ✅ 659–707 | ✅ 717–756 |
| Pixel 5 | 393×851 | ✅ 607–655 | ✅ 665–714 | ✅ 724–763 |
| 小屏安卓 | 360×640 | ✅ 395–443 | ✅ 453–501 | ✅ 511–550 |
| iPad | 768×1024 | ✅ 827–875 | ✅ 827–875 | ✅ 885–924 |

同时回归测试通过：开局 → 简报 → 社交网络 → 决策页（12 位关键人物、6 类动作）→
执行决策（回合 1→2、影响弹窗）→ 结算页，全流程正常，无 JS 错误。

## 文件说明

| 文件 | 说明 |
|---|---|
| `index.html` | 入口：一层 iframe 包住游戏本体 + 排行榜抽屉 |
| `integration-fixed.html` | 游戏本体（自包含单文件，约 380KB），已包含全部修复 |
| `data/leaderboard.json` | **在线排行榜数据**（与页面同源，直接可读） |
| `collect.py` | 采集器：把提交通道的成绩汇总进 `leaderboard.json` |
| `.github/workflows/collect-leaderboard.yml` | 每 15 分钟自动跑一次采集 |

游戏本体完全自包含，无外部依赖，离线可用（仅字体走 Google Fonts，
断网时自动回退到系统字体）。

## 在线排行榜 · 架构

排行榜需要「任意设备可读 + 任意设备可写」，而这里是纯静态站（无自建后端），
所以采用**读写分离**的两段式设计：

```
写入  ─── 浏览器 POST ──→  ntfy.sh 主题（提交通道，保留约 12h）
                                    │
                                    │  采集器每 15 分钟拉取
                                    ▼
读取  ←── 同源 fetch ────  data/leaderboard.json（GitHub Pages 托管，永久）
```

**为什么这么设计**

- **读**走页面**同源**的 `data/leaderboard.json`。同源 = 完全不存在 CORS 问题，
  而且 GitHub Pages 在国内可直连（`raw.githubusercontent.com` 被墙，但
  `*.github.io` 正常）。
- **写**走 `ntfy.sh`。它是少数**免注册、CORS 全开
  （`Access-Control-Allow-Origin: *`）、且国内可达**的可写入服务，
  浏览器可以直接 POST，不需要任何密钥。
- 因为 ntfy 消息只保留约 12 小时，采集器把它当作**临时信箱**：
  定期把成绩落到 `leaderboard.json`，形成持久榜单。
  15 分钟一轮，留有充足余量。

**数据流**

1. 玩家结算 → 游戏 `postMessage` 一条 `GAME_ENDED`（含完整战绩）
2. `index.html` 校验并裁剪字段，POST 到 ntfy 主题
3. 前端**乐观插入**本地缓存 → 玩家立刻能看到自己的成绩
4. GitHub Actions 每 15 分钟跑 `collect.py`：拉 ntfy → 去重 → 合并 → 按分排序 → 提交 JSON
5. 下次打开排行榜，读到的就是更新后的持久榜单

**字段与校验**：`collect.py` 对每条提交做白名单取值 + 范围钳制
（分数 0–100、回合 ≥1 等），并按 `(昵称, 时间戳, 总分)` 去重，防止重复轮询产生重复行。
榜单上限 500 条。

**排序**：总分降序，同分按提交时间升序（先到先得）。

## 部署

把仓库内容推到 GitHub Pages 即可，无需构建步骤：

- `index.html`、`integration-fixed.html`、`data/leaderboard.json` 直接静态托管
- `.github/workflows/collect-leaderboard.yml` 由 GitHub Actions 自动执行
  （需在仓库 Settings → Actions → General 里确认 Workflow permissions 为
  **Read and write**，否则无法提交榜单更新）

手动跑一次采集：`python3 collect.py`（加 `--dry-run` 只看不写）。

## 已知限制

- 写通道 `ntfy.sh` **无鉴权**，理论上可被刷分。对教学演示场景够用；
  若需防刷需引入签名或自建后端。
- 榜单**不是实时**的，最长有约 15 分钟采集延迟（玩家本人因乐观更新可立即看到）。
- ntfy.sh 为境外服务（实测国内可直连），若某天不可用，需更换提交通道；
  读取路径不受影响，已落盘的成绩始终可看。

## 追加修复（replica v2）· 结算弹窗的操作按钮看不见

第一轮修复（replica v1）只覆盖了**结算页 `#screen-ending`**。用真实终局回合复测后发现
另一处漏网：**局终结果弹窗 `#impactModal`** 的「📊 View Final Score / View Action Log」
按钮同样看不到，用户会卡在弹窗里**进不去结算页**——从用户视角看，症状就是「结算页最下面的按钮显示不出来」。

### 复现与根因

真实终局回合实测（修复前）：

| 视口 | 弹窗卡片可视高 | 内容高 | 按钮 top→bottom | 结果 |
|---|---|---|---|---|
| 375×667 | 600 | 831 | 787→857 | 视口外，看不到 |
| 390×844 | 760 | 956 | 930→1000 | 视口外，看不到 |
| 360×640 | 576 | 877 | 830→901 | 视口外，看不到 |

根因是**双重**的：

1. `.modal-card` 是内部滚动容器（`overflow:auto`），操作行排在 `#impactBody` 之后；
   内容一长，操作行就被推到卡片可视区之外，而手机上**没有可见滚动条**，看不出「还能往下滚」。
2. `showModal()` 每次渲染后执行 `card.scrollTop = 0`，并用
   `nextBtn.focus({preventScroll:true})` **刻意阻止**自动滚动到按钮——
   等于主动把按钮藏起来。

### 修复方式

把卡片改为**纵向 flex**，让中间内容区自己滚动、两条操作行**固定在卡片底部**（叠加式 CSS，未改动游戏逻辑）：

```css
.modal-card { display:flex !important; flex-direction:column !important;
              overflow:hidden !important; padding:0 !important; }
.modal-card > #impactBody { flex:1 1 auto; min-height:0; overflow-y:auto;
                            -webkit-overflow-scrolling:touch; }
.modal-card > #modalActions,
.modal-card > #modalFinalActions { flex:0 0 auto;
  padding:14px 28px calc(14px + env(safe-area-inset-bottom, 0px));
  background:var(--surface); border-top:1px solid var(--border);
  box-shadow:0 -10px 24px rgba(0,0,0,.35); position:relative; z-index:6; }
```

### 验证结果

Playwright 跑**真实终局回合**（选动作 → 执行 → 资源耗尽 → `checkEnding()` 触发），
8 种视口下弹窗与结算页的**全部按钮都完整可见且命中点击**，8/8 通过：

| 视口 | 弹窗按钮 | 结算页按钮 |
|---|---|---|
| 375×667 / 390×844 / 360×640 / 393×851 / 430×932 / 768×1024 / 1280×720 / 1280×620 | 2/2 可见可点 | 4/4 可见可点 |

> 注意：弹窗在动作执行后约 **4.8 秒**才出现（引擎内还有异步结算），自动化测试需等待足够时长。
