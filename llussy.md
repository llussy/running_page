# llussy 的 fork 说明

本仓库 fork 自 [yihong0618/running_page](https://github.com/yihong0618/running_page)。
这份文档记录**本 fork 相对上游的所有改动**，以及同步上游时哪些地方会冲突、该怎么处理。

数据源：**咕咚（Codoon）**，只同步跑步。最后更新：2026-09-21。

---

## 一、同步上游前先看这里

```bash
git remote add upstream https://github.com/yihong0618/running_page.git   # 只需一次
git fetch upstream
git merge upstream/master
```

按冲突风险从高到低：

| 文件 | 本 fork 的改动 | 合并策略 |
| --- | --- | --- |
| `src/static/activities.json` | 自己的跑步数据 | **永远保留本地**（`git checkout --ours`），上游那份是原作者的数据 |
| `run_page/data.db` | 自己的数据库 | 同上。未被 git 跟踪时不会冲突，但别被上游的 `.gitignore` 改动带偏 |
| `GPX_OUT/` | 自己的轨迹 | 同上 |
| `config.yml` | avatar / goals | 手动合并，保留本地这两项，上游新增的配置项照收 |
| `src/static/site-metadata.ts` | siteUrl | 手动合并，保留本地 siteUrl |
| `run_page/codoon_sync.py` | `IS_ONLY_RUN = True` | 手动合并，**改完后确认这一行还在** |
| `run_page/fix_run_location.py` | 本 fork 新增，上游没有 | 不会冲突 |
| `llussy.md` | 本文件 | 不会冲突 |

合并完跑一遍自查（见第五节）。

---

## 二、改动清单

### 1. `config.yml`

```yaml
mapbox_token: ''   # 保持为空，token 不入库，见下方说明
avatar: '...githubusercontent.com/u/18432966...'   # GitHub uid 18432966 = llussy
goals:
  all:  { yearly: 1000, monthly: 100, weekly: 35 }   # 上游是 2000/150/35
  Run:  { yearly: 1000, monthly: 100, weekly: 25 }
theme_preset: dashboard   # 与上游一致
```

**Mapbox token 不要写进 config.yml。** 取值顺序见 `src/core/config.ts:40`：

```ts
import.meta.env.VITE_MAPBOX_TOKEN || config.mapbox_token || ''
```

- **本地开发**：写在 `.env.local` 里的 `VITE_MAPBOX_TOKEN=pk.xxx`（已被 `.gitignore:29` 的 `.env*.local` 忽略）
- **GitHub Actions**：在仓库 Settings → Secrets 里配 `MAPBOX_TOKEN`，
  `gh-pages.yml:99` 和 `ci.yml:73` 会自动注入成 `VITE_MAPBOX_TOKEN`

config.yml 里的 `mapbox_token` 只是兜底，**保持空值**即可。

### 2. `src/static/site-metadata.ts`

`siteUrl` 改为 `https://llussy.github.io/running_page/`。

> GitHub Pages 的子路径**不需要手动配**：`vite.config.ts:84` 读 `PATH_PREFIX` 环境变量，
> `.github/workflows/gh-pages.yml:100` 已经是 `PATH_PREFIX=/$REPO_NAME pnpm build`，会自动注入。
> 本地 `pnpm develop` 时 base 仍是 `/`，不受影响。

**未改（待办）**：`navLinks` 里 Blog / About 两条仍指向 `yihong0618` 的仓库。
这两条只在 **classic** 主题的导航栏渲染，dashboard 下看不到，所以一直没动。

### 3. `run_page/codoon_sync.py:75`

```python
IS_ONLY_RUN = True   # 上游默认 False
```

作用点在 `codoon_sync.py:486`（过滤活动列表）和 `:603`（跳过写入）。
设为 `True` 后连非跑步活动的详情接口都不会请求，同步更快。

**注意它只管新增，不管存量**——已经入库的非跑步数据不会被它删掉。

### 4. `run_page/fix_run_location.py`（新增）

补位置的工具脚本，见第四节。

---

## 三、日常同步

```bash
python3.13 run_page/codoon_sync.py <手机号> <密码> --with-gpx
pnpm develop
```

同步是**增量**的（`codoon_sync.py:645` 拿 db 里已有的 run_id 做差集），重复执行不会重复拉取。
脚本结尾会自动 `generator.load()` 重写 `activities.json`。

---

## 四、地理位置（足迹地图）

### 为什么需要单独处理

咕咚接口不返回地理位置（`codoon_sync.py:600` 直接写 `location_country = None`）。
`generator/db.py:105-128` 本来有兜底反查，但那段代码**没有任何限速**，
首次全量同步几百上千条会被 Nominatim 限流，而且失败是静默的：

```python
except Exception:  # noqa: S110, BLE001
    pass           # ← 失败就放弃，location_country 留 None，不报错
```

结果就是首次同步后 2844 条全是 NULL。前端 `useActivities.ts:6` 的 `extractProvince()`
第一行（`:7`）是 `if (!loc || loc === 'None') return null`，于是全部返回 null，
足迹地图显示 **0 / 35 省份**。

### 修复

```bash
python3.13 run_page/fix_run_location.py              # 补齐所有缺位置的活动
python3.13 run_page/fix_run_location.py --dry-run    # 先看要处理哪些
python3.13 run_page/fix_run_location.py --type Run   # 只处理跑步
```

按 1 次/秒限速，可断点续跑（已有位置的自动跳过），结尾自动重生成 `activities.json`。

### 以后还需要跑吗

**一般不需要。** 每周同步只新增几条，请求量远低于限速阈值，`db.py` 的兜底反查会自动填上。
但有两种情况要留意：

1. 失败是静默的，不会报错，只会表现为足迹地图数字不涨
2. 攒了很久（上百条）一次性入库时，又会撞限速

所以自动同步后建议跑一下第五节的自查。

> 已知精度问题：咕咚的坐标很可能是 **GCJ-02**，Nominatim 按 WGS-84 解析，有几百米偏移。
> 省份级别不受影响。如果哪天发现路线地图轨迹整体偏移，根因在这里
> （`codoon_sync.py:78` 有 `TRANS_GCJ02_TO_WGS84` 开关，前端也有 `gcoord` 依赖）。

---

## 五、自查

```bash
python3.13 -c "
import sqlite3, json, collections
c = sqlite3.connect('run_page/data.db')
print('db 各类型:', c.execute('select type, count(*) from activities group by type').fetchall())
print('db 缺位置:', c.execute('select count(*) from activities where location_country is null').fetchone()[0])
d = json.load(open('src/static/activities.json'))
print('json 条数:', len(d), collections.Counter(a['type'] for a in d))
"
grep -n 'IS_ONLY_RUN' run_page/codoon_sync.py | head -1
grep -n 'VITE_MAPBOX_TOKEN' .env.local   # 本地 token 是否还在
```

2026-09-21 的基线：

```text
db 各类型: [('Run', 858)]
db 缺位置: 2          # 这 2 条本来就没有 polyline，无法反查
json 条数: 858 Counter({'Run': 858})
足迹地图: 北京市 650 / 河北省 205 / 天津市 1 → 3 个省
GPX_OUT: 846 个文件（另有 12 条 Run 是室内跑，没轨迹）
```

---

## 六、历史操作记录

2026-09-21 首次搭建，做过的一次性操作（**不要重复执行**）：

1. 首次全量同步咕咚，得到 2844 条（Run 858 / Hike 1842 / Ride 144）
2. 对 856 条 Run 反查位置，856/856 成功
3. `DELETE FROM activities WHERE type != 'Run'` 删除 1986 条非跑步数据 + `VACUUM`
4. 删除 `GPX_OUT/` 里 1441 个非跑步轨迹，剩 846 个
5. `IS_ONLY_RUN` 改 `True`，防止后续同步再进非跑步数据

> 咕咚里 Hike 占了 65%（1842/2844），比例偏高，**可能混着 App 里运动类型选错的跑步记录**。
> 这批数据已删且未保留备份。如果哪天想找回，只能 `pnpm data:clean` 后重新全量同步
> （需先把 `IS_ONLY_RUN` 改回 `False`）。

---

## 七、遗留问题

- [ ] `assets/` 目录状态混乱：部分 svg 被删（`year_*.svg`、`github_*.svg`、`grid.svg` 等），
      部分是原作者的旧图。这些**只有 classic 主题用**（`SVGStat`、`YearStat`、`YearSummaryModal`），
      当前 dashboard 主题下完全不读，所以没影响。若要切 classic，需按
      `.github/workflows/run_data_sync.yml:247-250` 的命令重新生成全套。
- [ ] `assets/index.tsx` 相对上游有改动，但这是个**退化**：丢了 prettier 格式化，
      且 `mol*.svg` 被改成 `mol.svg`（少 glob 到 `mol_running.svg`/`mol_walking.svg`）。
      建议直接 `git checkout upstream/master -- assets/index.tsx` 还原。
- [ ] 仓库根目录有两个误生成的文件：`2026.svg`、`poster.svg`。
      成因是 `gen_svg.py` 的 `--output` 默认值是 `poster.svg`，不传就落在根目录；
      正确路径应是 `assets/github.svg` / `assets/github_2026.svg`。可直接删。
- [ ] `site-metadata.ts` 的 navLinks 仍指向原作者（见第二节第 2 条）。
- [ ] 定时同步未配置。若要配，`codoon_sync.py:675` 支持 `--from-auth-token`，
      用 token + user_id 比命令行明文手机号密码安全。
