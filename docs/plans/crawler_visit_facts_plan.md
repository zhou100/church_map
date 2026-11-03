# ChurchMap 实施计划：爬虫接手、流水线上云、Muse 交接

**日期：** 2026-11-03（PT）· **目标：** 加州先上线，业主参与降到最少
**依据：** [workflow_review_2026-11-03.md](../workflow_review_2026-11-03.md)、[crawler_vs_muse_2026-11-03.md](../crawler_vs_muse_2026-11-03.md)、[directory_sources_check_2026-11-03.md](directory_sources_check_2026-11-03.md)
**状态：** 业主起草，Claude 审阅后合并（2026-11-03）。标【改】的是审阅时改的地方，改动理由写在同一处。接手的 agent 先读 [AGENTS.md](../../AGENTS.md)，它对所有 agent 都适用。

> 业主只在三种时候出手：一次性授权（secrets、服务账号）、批准第 0 节的决定、处理标成"待审"的发布 diff。其余都由 agent 实现，DOT 负责盯状态。

### 代码进度（2026-11-03 23:24 UTC）

| PR | 内容 | 状态 |
|---|---|---|
| [#67](https://github.com/zhou100/church_map/pull/67) | 宽松解析 run log 里的目录扫描记录。格式不对不再退回；只有 Muse 自己写明还有 U 条没研究、且没到上限时，**整个包**退回，不是按行退回【改】 | 已合并 `2697b52` |
| [#68](https://github.com/zhou100/church_map/pull/68) | trafilatura 和 R2 调用移出事件循环 | 已合并 `4d86c9c` |
| [#69](https://github.com/zhou100/church_map/pull/69) | 修复 fetch 一直 partial（robots.txt 里有 NUL 字节） | 已合并 `8a76ea5` |
| [#70](https://github.com/zhou100/church_map/pull/70) | 多抓儿童、青少年、托育、联系、活动页面。website_v3 不受影响；每个教会要抓的页面约增加到 1.85 倍 | 已合并 `8cbc0c7`（2026-11-03 23:16 UTC） |
| #71 | 本执行计划和三份背景文档 | 已合并 `6d14f95` |
| PR 2 草稿（`codex/website-identity-checks`） | 离线身份比对核心、私有 JSONL 报告及反例测试 | 进行中；只支持单一、同名同站的 Church JSON-LD；未接入线上拦截，未评估 2,543 个候选 |

**部署观察（2026-11-03 23:18–23:24 UTC）：** GitHub deployment
`7533216349`（Vercel Production）和 `7533208637`（Render `main - churchmap-api`）
均报告 `8cbc0c7d4268eeca0be6c88a820b83aca3e791b8` 部署成功。
`/api/stats` 的 `generated_at=2026-11-03T23:18:38.790694+00:00`，
`fetch.last_success` 仍是 10/25。最近一次自然 fetch 是部署前的
[Actions run 41703909895](https://github.com/zhou100/church_map/actions/runs/41703909895)
（19:30 UTC；服务端 run 1402）：`partial`，50 processed / 48 ok / 2 error，
旧响应没有 `errors` 明细或 `deferred`。尚不能判定 #69/#70 的生产效果；未手动触发。
部署记录不等于完成浏览器上线 QA。

---

## 0. 需要业主拍板的事（一次性）

| # | 决定 | 建议 |
|---|---|---|
| D-A | "到访信息提取"的 LLM 预算 | 批准试跑：只跑有 Muse 结果的 2,543 个候选。跑完前 200 个先报告实测成本，再跑剩下的 |
| D-B | 自动发布规则（§2） | **已批准（2026-11-03 PT，本次接手对话）：§2 八项条件全部满足才自动 apply，否则待审。** 判定器尚未实现；不表示现在可直接调用现有 `--apply`。 |
| D-C | brief v3.7（§4） | 批准 |
| D-D | USPS 地址核验服务 | 先确认 USPS 现在的 API 能不能提供 DPV/RDI/CMRA、免费额度多少、结果能不能存下来；确认后再试用，只用在没有教会自己来源的地址上【改】 |
| D-E | 停止按网页语言推断聚会语言 | 批准，但要先看 §3 PR 4 写的代价【改】 |
| **D-F**【新】 | 自动扫目录站（churchfinder、oursweb） | 两家的使用条款都限制复制和再利用它们的数据（见目录站检查文档）。建议搁置，或者先写信申请许可 |
| **D-G**【新】 | Muse 现在的目录扫描（D12）是否继续 | 同样的条款问题。它已经通过目录站找到了 628 个教会 |
| **D-H**【新】 | 流水线在哪里跑（§1.1） | **已批准（2026-11-03 PT，本次接手对话）：继续使用公开 repo 的 GitHub Actions，即 §1.1(c)。** 必须先完成仅计数日志和泄漏回归测试。 |

D-A、D-C、D-D、D-E、D-F、D-G 仍是建议，未获批准。业主询问私有报告能否存 R2；技术上可行，建议专用私有 bucket。尚未创建资源、获得访问凭据或迁移状态；analytics Postgres 的云端落点仍未配置。

已经做过的决定（11/03）：
- 儿童项目分 3 类 × 3 段（附录 A）；
- 偏好设置改成按年龄段选（附录 C）；
- 试点跑全部 Muse 候选；
- 格式问题由我们自己修。

---

## 1. 流水线搬离个人电脑（PR 1）

现在的每小时拉取依赖 Windows 计划任务、WSL、G: 盘挂载，而且跑的是当前检出的分支（P11）。

### 1.1 改动

1. `drive_sync.py` / `drive_pull_hourly.sh` 改用 **Google Drive API**（服务账号），不再读 `/mnt/g`。
2. **在哪里跑（D-H）【改】：**
   - `zhou100/church_map` 是公开 repo，Actions 日志对所有人可见。而 `validate_returns.py`、`recheck_sources.py`、`build_seeds.py` 会打印候选名称、URL、摘录片段，原始返回文件里还有 D-2 要求不公开的个人电话。所以 raw returns 才一直是 gitignore 的。
   - 可选做法：
     - (a) 一个**私有** repo，专门放这个 workflow；
     - (b) Render cron job，和 API 同一个平台；
     - (c) 留在公开 repo，但所有步骤都改成只输出计数、不打印内容，还要有一个测试来保证这一点。
   - **业主已选 (c)**（2026-11-03 PT）：继续使用公开 repo；原推荐 (a)/(b) 不再作为执行方案。
   - 不管放在哪里：每小时触发，再加手动触发；`concurrency: { group: muse-pull, cancel-in-progress: false }` 取代原来的锁文件；固定在 `main` 上运行。
   - 步骤：`validate_returns.py` → `recheck_sources.py` → `repair_excerpts.py`（按需）→ `build_seeds.py` → `geocode_incremental` → `dbt build` → `publish_verified.py`（dry run，按 §2 的规则判定是否 apply）→ 生成状态摘要（§1.3）。
3. **持久状态要搬走【改】。** 下面这些现在只存在这台电脑上，而且都是 gitignore 的，CI 每次运行都是全新环境，用完就丢：

   | 状态 | 现在的位置 | 作用 |
   |---|---|---|
   | 地理编码台账 | `analytics/exports/geocode_ledger.csv`、`geocode_history/`、`geocode_reconciliation.json` | 同一个地址不重复提交 Census；`build_seeds` 只用和台账绑定过的坐标 |
   | 复核历史 | `muse_handoff/returns/recheck/history/` | 一次网络失败不推翻 30 天内的 `verified` 结论（carry-over 规则） |
   | 批次状态 | `muse_handoff/outbox/status.csv`（主副本） | 各个包的状态 |
   | 收货记录 | `muse_handoff/returns/received.csv` | 每个文件的接收时间 |
   | Muse 返回的文件 | `muse_handoff/returns/*.csv` | 种子数据的来源 |
   | 目录快照 | `holyhub.db` | 来自 2026-05-08 的 SQLite，比生产环境少约 500 个网站 |

   - 前四项搬进云上的 analytics 库，或者一个私有 R2 bucket；
   - Muse 返回的文件每次从 Drive 拉；
   - 目录快照改成用一个**只读角色**从生产库读，`load_snapshot.py` 要跟着改。
4. **analytics 库上云。** 本地 Postgres（5433）换成一个小的托管 Postgres（另开一个 Supabase 项目或 Neon），连接串放进 secrets；dbt 顺便接上 CI。
5. `dbt build` 传入 `--vars '{as_of_date: <当天>}'`，修掉 `mart_coverage_snapshot` 停在 10/19 的问题。D-3 的 12 个月新鲜度依赖这个日期。
6. **复核会被挡【改】。** 云上的机器是数据中心 IP，有些教会网站会对它返回 403。上云后要比较 `recheck_sources` 的 `fetch_failed` 和 `robots_blocked` 比例，比本地明显升高就要处理。被挡的不能绕过（AGENTS）。

### 1.2 业主一次性要做的（约 15 分钟）

- 在 Google Cloud 建一个服务账号，把 Muse 的共享文件夹分享给它（编辑权限）。
- 在 secrets 里填：`GDRIVE_SA_JSON`、`ANALYTICS_DATABASE_URL`、`PUBLISH_DATABASE_URL`（§2）、`PROD_READONLY_DATABASE_URL`【新】，以及 `CENSUS_*`（如有）。
- 新流水线连续 24 小时正常运行**之后**，再关掉 Windows 计划任务 `ChurchMapMusePull`【改：先确认新的能跑再关旧的】。

### 1.3 状态摘要文件

每次运行结束，覆盖写 Drive 上的 `status/status_digest.md` 和 `status/status_digest.json`，内容：

- 各 WP 的状态、进入该状态的时间；
- 最近 24 小时入库行数、拒收行数（按原因分）；
- 最近一次 fetch / extract / tag 的结果，`deferred` 数（#70 新增），`errors` 列表（#69 新增）；
- 发布：自动 apply 的批次号和行数，或者"待审" diff 的链接；
- 失败的步骤和日志最后 20 行。

【改】Muse 也能读这个 Drive 文件夹，所以摘要里**不写摘录原文、不写电话、不写 Muse 的笔记**，只写计数、编号、URL 和步骤名。日志尾部要先过滤再写。

**完成标准：** 业主电脑关机 24 小时，`received.csv` 和 `status_digest.md` 照常更新；而且上云后第一次 `dbt build` 的 map_ready 数和本地最后一次一致。

---

## 2. 发布自动化（并入 PR 1）

`publish_verified.py` 已有分批事务、`publish_log` 和 `--revert`。

**自动 apply 的条件（全部满足）：**

1. diff 里只有新增，或者只填补原来为空的字段；不覆盖、不删除已有值。【改】**坐标修正**（pin 移动超过 50 米）属于覆盖，一律待审。
2. 本次不超过 200 行。
3. D-1、D-2 过滤命中为零。
4. `as_of_date` 等于当天。
5. 上一次发布之后，没有被 `--revert` 过的批次。
6. 【新】本次运行的 `dbt build` 全部通过，包括 identity、grain、pin 相关的测试（AGENTS：身份错误、粒度膨胀、坐标不匹配会挡住相关的发布）。
7. 【新】**新增教会**这一类，还要求：没有 `possible_match_church_id` / `possible_match_candidate_id`；`match_confidence` 不是 `low`；同一批里没有地址相同、名字不同的两条（见 §3 的去重规则）。不满足的那几条单独列成待审，其余照常自动发布。
8. 【新】生产环境不在 `READ_ONLY=1` 状态。

不满足的只生成 diff，标成**待审**，写进状态摘要。业主批准后，由 agent 用 `--apply` 执行。

**这是一项长期授权【改】。** AGENTS.md 现在要求"apply 之前检查具体改了哪些字段"。业主批准 D-B 后，要把这条自动发布规则写进 AGENTS.md 的"Change invariants"，指向这一节，否则下一个 agent 会认为自动 apply 违反项目规则。

**数据库权限：** `PUBLISH_DATABASE_URL` 用一个新的 Postgres 角色，不用 owner 账号。发布脚本要写的表有：
- `churches`：插入新教会，更新 `COLUMNS` 列出的那些列，包括 `latitude`、`longitude`，可以用列级授权；
- `church_fact_sources`；
- `publish_log`。

**回滚：** 不自动回滚。出问题时由业主或 agent 执行 `--revert <批次号>`。注意发布是分批提交的，revert 之后如果又有新的编辑，不一定安全（AGENTS）。

---

## 3. 爬虫接手"到访信息"

### 已完成：PR #70 多抓页面

儿童、青少年、托育、联系、活动、新闻、讲道这几类页面，每个教会最多多抓 4 个，存进 R2。website_v3 不会读它们。

部署后看状态摘要里的 `deferred`。如果顺延太多，二选一：
- 同时抓 2–3 个教会，每个网站加锁保证一次只有一个请求（需要 #68 先合并）；
- 把 fetch 的定时从每 4 小时一次改成每 2 小时一次。

### PR 2：网站身份比对（不花钱，先做）

- 用目录、Muse 或 IRS 给的地址和电话，和网站原始 HTML 里的地址、电话做确定性比对，输出 `address_matches` / `phone_matches`，口径和 `url_evidence` 一样。
- 【改】**明确矛盾才挡住，没得比的不挡。** 原来写的是"不匹配的网站不进入后面的提取"。但目录里只有 0.4% 的地址有门牌号、6.9% 有电话，大部分教会根本没有可比的数据，照原来的写法几乎会挡掉所有目录教会。改成三种结果：
  - `match`（一致）：照常提取；
  - `conflict`（不一致）：不提取，列为身份难题，派给 Muse（§4.3）；
  - `no_comparable`（没有可比数据）：照常提取，但标成"身份未核实"。显示规则在 PR 5 里定。

### PR 3：存原始响应 + 结构化解析器（不花钱）

1. **存原始响应。【改】**
   - R2 里已经存的就是原始 HTML 字节（`put_html(raw_bytes)`），只是没存 HTTP 头。
   - **`content_hash` 不能改成按原始字节计算。** AGENTS 规定 R2 的 key 是 `raw_html/{church_id}/{YYYY-MM-DD}/{content_hash}.html`，`content_hash` 是 trafilatura 清洗后正文的哈希，并且要保留 `UNIQUE(church_id, url, content_hash)` 这个去重约束。原始字节里常有时间戳和随机 nonce，每次抓都不一样；如果按原始字节算哈希，"内容没变就只刷新抓取时间"的规则会失效，每次重抓都会生成新的待提取任务，提取费用会成倍增加。
   - 正确做法：新增一列 `raw_sha256`；HTTP 头存成 JSON 附带文件，或者用 `warcio` 写 WARC（新依赖，理由是要完整保留证据）。key 和去重规则都不动。
   - 要加两个测试：内容没变时重抓不产生新任务；正文变了时产生新任务（AGENTS 的要求）。
2. **结构化解析器**（按优先级）：
   1. schema.org JSON-LD / microdata（`extruct`）：地址、电话、`Event`；
   2. 讲道播客 RSS：最近一集的发布日期，作为活动证据；
   3. `.ics` 日历（`icalendar` + `dateutil.rrule`）：聚会和活动；
   4. WordPress The Events Calendar 的 REST 接口（`/wp-json/tribe/events/v1/events`），请求之前同样要过 robots 检查；
   5. Church Center、YouTube 先不做。
3. **活动证据的规则：** 有实际内容的条目才算，比如讲道、活动、周报。CMS 的 `lastmod`、sitemap 时间戳、页脚版权年份**不算**（P5）。
   - 【改】RSS 的 `pubDate` 是元数据时间戳，只有同时满足下面两条才算数：这一集是这个教会自己的讲道（feed 的作者或链接指回这个教会的网站，不是宗派或其他堂会的 feed）；显示时写明"最近一次讲道发布于某日（播客）"。
4. 每个提取值记录：URL、抓取时间、存档记录 ID（WARC 记录或 R2 key）、在原始文本里的字符起止位置、解析器名称。

### PR 4：LLM 到访信息提取（需要 D-A）

- 只对结构化解析器没填上的字段调用 LLM：
  - 聚会时间（星期、时间、类型、语言）；
  - 儿童与青少年项目，**按附录 A 的 3 类 × 3 段**【改：原稿没写分类】；
  - 地址是不是聚会地点；
  - 电话是教会电话还是个人电话（D-2）。
- 读的是**原始 HTML 转出的全文**（含页脚），不是 trafilatura 正文。新的提取阶段要读这个教会存档的**所有**页面，包括 v3 的那几类，因为导航里排在前面的 `/kids` 链接会被 `ministries` 这一类先占走（#70）。
- 页面顺序：先主页（Muse 的数据里 68–74% 的地址和聚会时间在主页上），再联系、到访、聚会时间页，周报 PDF 最后。
- **原文位置怎么定【改】。** 不让 LLM 自己报字符起止位置，LLM 数位置很不准。改成：
  1. LLM 返回每个值的**逐字原文**；
  2. 代码在存档的原始文本里精确查找，自己算出起止位置；
  3. 找不到或者出现多处、无法区分的，直接丢弃。

  这样效果和原来想要的一样（按位置精确比对存档），但位置是确定性算出来的。
- 聚会时间多存两个字段：`observed_at`，以及 `seasonal_flag`（原文出现夏季、圣诞、复活节、"从某日起"等字样）。带 `seasonal_flag` 的时间先不显示为常规时间。
- 证据来源单独标注 `crawler_verified`，和 `muse_verified` 分开显示、分开统计。
- 新写一个 prompt（`visit_v1.py`），有自己的 `PROMPT_VERSION` 和 eval 基线。**不改** `website_v3`，所以 v3 现有的基线和缓存不受影响。
- **D-E：停掉按网页语言推断聚会语言。** 语言只用页面原文里的证据，存 ISO 639-3 代码。【改】要先认清代价：
  - v3.1 这样推断是为了让"语言"字段有数据，eval 里它的分数是 0.588，在所有字段里最低。停掉以后，语言偏好能匹配到的教会会**大幅减少**，访客能明显感觉到；
  - 这个改动发生在 `website_v3`，要升 `PROMPT_VERSION`、重新生成 baseline 和 cache、过 eval gate；
  - 已经提取过的约 6,500 个教会要重新排队提取，这是付费的，而且只能走有上限、先 dry run 的重新排队流程；
  - 在重新提取完成之前，现有的推断值要么不再参与"为你推荐"，要么标成"推断"，二选一，在这个 PR 里决定；
  - 前后端现在用的是语言名称（`'Mandarin;English'`），换成 ISO 代码以后，API、`fit_sql`、`fitScore` 和 `fitParityCases.json` 都要一起改。

### 【新】PR 5：API、详情页、卡片、按年龄段的偏好

原稿漏了这一步：数据提取出来，访客还看不到。

- **API：** 详情接口返回到访事实和儿童项目，带来源类别（`crawler_verified` / `muse_verified`）、URL 和检查日期。
- **详情页：** 按年龄段列出项目，每一条写明"来自教会网站 · 检查于某日"，附原页面链接。遵守 DESIGN.md：教会名用 Fraunces 字体，配色是赭石色和金色。
- **卡片：** 加一行，比如"学龄前：聚会期间看护 · 儿童：主日学 · 青少年：周五团契"。
- **偏好（附录 C）：** 改成按年龄段选，外加"需要工作日托育"。服务器端的 `fit_sql` 和前端的 `fitScore` 一起改，`fitParityCases.json` 加新用例。要测一个排在第一页之后的匹配结果，还要测没有坐标的教会（AGENTS 的要求）。
- 跑 `npm test` 和 `npm run build`，再在浏览器里检查：手机和电脑、键盘焦点、空状态。

### 评估（PR 4 合并之前）

1. **试跑：** 2,543 个有 Muse 结果的候选。【改】两边一致的可以**发布**，但**不计入准确率**。爬虫和 Muse 读的常常是同一个主页，会一起读错，"两边一致"不能证明是对的（AGENTS：不能用同一来源自己给自己打分）。
2. **有分歧的：** 拿存档页面判定。【改】**不能交给 Muse 判**，因为分歧的一方就是 Muse。改成：
   - 先用确定性规则过一遍：原文找得到吗？日期过期了吗？是不是另一个堂点？
   - 剩下的由业主抽查；或者换一个模型先分类，再由业主确认。
3. **独立样本：** 从没用过的教会里分层抽约 100 个（地区、语言、网站类型），必须包含走错堂点、活动过期、页面上没写这几类反例。这是业主唯一需要亲自标注的部分，只做一次。100 个样本时，准确率大约在 90% 附近的字段，95% 置信区间大约是 ±6 个百分点；要更窄就得多标。
4. **报告：** 每个字段的准确率给出 Wilson 95% 置信区间。不需要为此加 `statsmodels`，公式几行就能写。按错误类型分别计数：走错堂点、过期、证据不支持、该填没填。不拿 Muse 当标准答案。容忍度在看结果**之前**写下来。

### 地址筛选（需要 D-D）

- 对 IRS 线索和没有教会自己来源的地址，跑 DPV/RDI/CMRA。住宅地址或商业信箱地址不作为聚会地点显示。

### 去重规则修正

- brief 的 D4 原来是"按名称和地址去重"，改成：**地址相同但名称不同，不合并**。比如共用一栋楼的华人堂、西语堂。这和 AGENTS 的"同一个地址不能证明是同一个教会"一致。
- 同一个网站有多个堂点（campus）时，聚会时间必须绑定到具体堂点；绑定不了的不显示。

---

## 4. Muse 交接（brief v3.7）

### 4.1 Muse 以后只做这些

1. **给没有网站的教会找网站**，先限加州。
2. **按城市找目录里没有的教会**：网络搜索、宗派名录。目录站能不能用，看 D-G。
3. **爬虫读不了的网站**：JS 渲染、我们的爬虫被挡的。只用正常浏览，不绕过封锁。
4. **身份难题**：多堂点、共用场地、搬家、地址是办公室还是聚会地点、来源冲突，以及 PR 2 标成 `conflict` 的网站。

有网站、而且爬虫能读的教会，**不再派给 Muse**。复查和重新引用类批次（类似 WP-0031–0040、0051、0052、S 系列）**停开**，由爬虫重抓加复核接手。

### 4.2 brief v3.7 的改动

- 删掉"必须查 Facebook"（A2）；校验脚本的 `activity checked:` 那一行不再要求 `facebook=`。
- 已有的 Facebook 数据保留，按 D-3 显示，12 个月后自然过期。
- 保留"看完活动、新闻、讲道、周报页面才能标 unresolved"（防止 P7）。
- 网站上找不到 12 个月内日期的，标 `unresolved`，显示"活跃状态未知"。
- 目录站只用来"找"，不能当证据引用（S5）。是否继续用，看 D-G。
- 格式问题由我们自动修正（#67）。【改】退回的单位是**整个包**：只有 Muse 自己写明某城市还有 U 条没研究、而且没到上限时才退回。行级的问题仍由 `validate_returns.py` 报错。如果要改成"按行退回、其余行照收"，需要另外开 PR。
- `README_FOR_MUSE.md` 和 `reference/BRIEF_v3.md` 一起更新。

### 4.3 派活自动化

- 每次拉取结束后，如果 Muse 手上 `queued` + `started` 的包少于 2 个，脚本自动从任务池生成下一个 WP 并发布到 Drive。
- 【新】每天最多自动生成 N 个包（建议 3 个），而且同一批教会不会被重复派出。
- 任务池的优先级：
  1. 加州、目录里没有网站的教会，按城市分组，每包约 50 条；
  2. 爬虫标成 `js_rendered` 或 `blocked` 的教会；
  3. 爬虫和身份比对标成"难题"的教会。
- 【改】WP-0044–0048 已经在 11/03 入库（通过 `sweep_accepted.csv`），需要按新规则检查的只有 **WP-0049、WP-0050**。它们的 TASK.md 要注明不用再查 Facebook。

---

## 5. 盯状态和催 Muse（交给 DOT）

DOT 只读 `status/status_digest.md`，不需要 GitHub 或 Drive 的其他权限。设定如下：

```
你只负责一件事：每天早上 9 点（太平洋时间）读 Drive 上的
status/status_digest.md，有问题才报告。

检查：
1. 有没有步骤失败，或者 fetch 连续 partial / pipeline_ok=false。
2. 哪些 WP 处于 needs_fix 超过 48 小时，哪些 queued 超过 72 小时没人领。
3. 有没有标成「待审」的发布 diff。
4. fetch 的 errors 列表或 deferred 数有没有明显增加。

动作：
- needs_fix 超过 48 小时：起草一条给 Muse 的提醒，写清 WP 编号和
  feedback 里的具体问题（逐条引用，不要概括），附 feedback 链接。
  草稿给我看，不要自己发。
- 步骤失败：贴出失败步骤名和日志最后 20 行，不要自己修。
- 有待审 diff：一句话总结新增几行、改了哪些字段，附链接。

规则：
- 一切正常就什么都不说，不要发「今天一切正常」。
- 不改代码，不触发发布，不修改 Drive 上的任何文件，不直接联系 Muse。
- 数字只引用文件里的原文，读不到就说读不到。
- status_digest.md 超过 26 小时没更新，本身就是一个问题，要报告。
```

---

## 6. 顺序和完成标准

| 顺序 | 内容 | 依赖 | 完成标准 |
|---|---|---|---|
| **0**【新】 | #67–#71 已合并；Render/Vercel deployment 均报告 `8cbc0c7` 成功 | 等待部署后的自然 fetch | **未完成**：部署后 `ok`、`errors`、`deferred` 待核对；上线浏览器 QA 未做 |
| 1 | §1 + §2 流水线上云 + 自动发布 | D-B、D-H 已批准；Drive、私有状态存储和云 analytics 接入待提供 | 业主电脑关机 24 小时照常运行；云上 map_ready 和本地一致；至少一次自动 apply |
| 2 | §4 brief v3.7 + 派活自动化 | D-C、D-G | WP-0049、0050 按新规则校验；新 WP 自动生成 |
| 3 | §5 DOT 上岗 | §1.3 | DOT 连续 3 天正常（没事不说话） |
| 4 | §3 PR 2 身份比对 | 私有候选和存档输入；线上消费端尚需接入 | 离线核心已有 21 个合成测试；**未完成** 2,543 个候选报告、普通 HTML 比对和线上拦截；不声称覆盖率或身份准确率 |
| 5 | §3 PR 3 存原始响应 + 结构化解析器 | — | 新抓的页面都有 `raw_sha256` 和 HTTP 头；`content_hash` 的去重测试通过；JSON-LD / RSS / .ics 有产出 |
| 6 | §3 PR 4 LLM 到访信息 + 评估 | D-A、D-E、5 | 评估报告完成（含 Wilson 区间和各类错误计数）；业主决定是否全量 |
| **7**【新】 | §3 PR 5 API、详情页、卡片、偏好 | 6 | `npm test`、`npm run build` 通过，浏览器里检查过；fit 两边用例一致 |
| 8 | 上线前：dry run，发布约 450 个新教会，上线 QA，核对 Render/Vercel 部署 SHA | 1 | 生产环境的 map_ready 数和 analytics 库一致 |

---

## 7. 交给其他 agent（Codex）之前要知道的【新】

接手的 agent 在云端或者另一台机器上，**拿不到**下面这些：

| 拿不到的 | 在哪里 | 影响 |
|---|---|---|
| 本地 analytics 库 | 5433 端口的 Postgres | §1 之前，所有 analytics 数字都没法复现 |
| Muse 返回的文件 | `muse_handoff/returns/`（gitignore） | 跑不了 `build_seeds` 和 `dbt build` |
| 目录快照 | `holyhub.db`（gitignore） | 同上 |
| Drive 共享文件夹 | 需要 §1.2 的服务账号 | 读不到 Muse 的交付 |
| 复现脚本 | 会话 scratchpad（不在 repo 里） | 文档里有方法说明，需要的话可以重写 |
| 本地测试库 | `churchmap_test`（5433）：`0002_pgvector` 只是标记成已执行、没有真跑 | 跑数据库测试要自己准备一个装了 pgvector 的 Postgres |

所以 §1 应该排在最前面：它把这些状态搬到 agent 能访问的地方。在那之前，只依赖代码的工作可以先做：§3 的 PR 2、PR 3，以及 PR 4 的代码部分。四份文档要先提交进 repo，接手的 agent 才能看到。

---

## 附录 A：儿童与青少年项目分类（11/03 业主选了"粗一些"）

每个项目从两个维度标注：**它在什么时候**，以及**面向哪个年龄段**。一个项目可以对应多个年龄段。

| 类型 | 含义 | 例子 |
|---|---|---|
| `during_service` | **聚会期间**：看护、托管、主日学、儿童崇拜 | "Nursery (0-36 months)"、"Sunday School for children in grades K-6" |
| `weekday_care` | **工作日托育和教育**：日托、幼儿园、学前班、Mother's Day Out、课后托管、教会办的学校 | preschool、early learning center、MDO、堂区学校 |
| `other` | 平日晚间的儿童俱乐部和青少年团契、宗教教育、VBS 和营会、特殊需要事工 | "AWANA ages 2 to 18, weekly meetings Thursdays"、"VBS 2026" |

| 年龄段 | 范围 | 能归到这一段的依据 |
|---|---|---|
| `preschool` 学龄前 | 0–5 岁，上 K 之前 | 写了月龄或岁数，或者写了 nursery、infants、toddlers、preschool、Pre-K、TK |
| `children` 儿童 | K–5 年级 | 写了年级或岁数，或者写了 elementary |
| `youth` 青少年 | 6–12 年级 | 写了年级，或者写了 middle school、junior high、high school、youth group、students |

- **只按网页上写明的内容归类，不推断。** 只写了"Kids"、没写年龄的，`age_bands` 为空，显示"儿童项目（年龄未写明）"。
- `during_service` 和 `weekday_care` 必须分开记，两者对家长的意义完全不同。
- 每个项目记录的字段：`type`、`age_bands[]`、`ages_stated`（原文）、`name_stated`、`schedule_stated`、`source_url`、逐字原文和起止位置、`page_fetched_at`、`content_hash`、`raw_sha256`、`evidence_class`、`extractor_version`。

## 附录 B：数据模型（新增 migration `0007`，只增不改）

- `church_programs`：每个项目一行，字段见附录 A。
- `church_visit_facts`：每个事实一行。
  - `field` 取值：`address`、`service_time`、`phone`、`last_activity`；
  - 再加原文值、结构化值、`is_worship_location`、`campus`、`seasonal_flag`、`observed_at`、URL、原文位置、核对结论、`evidence_class`、`parser`、`extractor_version`。
- 现有的 `churches.kids_program` 和 `church_fact_sources` 保持不变，Muse 发布的数据照旧可读。
- 同一个事实两边都有时，显示核对时间更新的那一条，另一条作为第二出处。
- 迁移要在数据库上按真实顺序跑一遍，从 0001 一直跑到 0007。

## 附录 C：偏好和排序

- `preferences.js` 里的 `kids: boolean` 改成 `kids: { bands: ['preschool'|'children'|'youth'], weekday_care: bool }`。已存的旧值 `kids: true` 迁移为"任意年龄段"。
- 打分规则：
  - 有写明年龄段、并且和访客选的一致的项目，算强证据；
  - "年龄未写明"的儿童或青少年项目，算弱证据；
  - 没有任何信息，算 0，**不扣分**。
- 服务器端的 `fit_sql` 和前端的 `fitScore` 一起改，`fitParityCases.json` 同步加用例。


## 接手验证记录（2026-11-03 UTC）

- 代码基线：`8cbc0c7`；工作分支 `codex/website-identity-checks`，隔离 worktree，原 checkout 未切换。
- 离线核心：`backend/scrapers_v2/identity.py`。仅单一 Church JSON-LD、同名同站的实体可比较；完整街道/城市/州及规范化电话同时矛盾才返回 `conflict`。单项矛盾、多堂点、其他实体、缺数据均不拦截。这是保守的初始实现，不是对全部 HTML 的覆盖声明；也不验证活跃状态或聚会地址。
- 离线入口：`python -m scripts.check_website_identity --input <private.jsonl> --output <new-private-report.jsonl>`。每行包含 `subject_id`、`html_path`（相对 manifest）、`source_url`、`fetched_at`、`reference`；reference 包含 `name`、`website`、`phone`、schema.org 格式 `address`。报告绑定原始字节 SHA-256、reference SHA-256 和版本，包含 `allow_extraction`；目前没有线上消费者或自动派 Muse。
- 输入/输出文件保持私有，报告文件不覆盖已有文件；stdout 仅计数，错误不回显内容。未读写 Drive、R2 或生产库。
- **通过**：Python 3.11.15；新建专用测试库 `churchmap_identity_test`，`127.0.0.1:55472`；pgvector 0.8.1；真实执行 `python -m backend.db.migrate`（0001–0006 全部执行），`python -m pytest -q`：590 passed、5 skipped、10 subtests passed。
- **跳过**：3 个 parity 测试缺 San Francisco 真实数据；2 个旧测试已被 parity 测试替代。没有删掉或放宽测试。
- **早期失败及纠正**：现有 `venv` 实为 Python 3.10，首次无 DB 测试 6 failed / 507 passed / 82 skipped，失败源于 `asyncio.timeout` 不存在；改用已有 Python 3.11 环境，不修改生产代码兼容错误测试环境。随后真实 DB 全套结果见上。
- **未运行**：私有候选评估、dbt（缺输入及 sidecar）、生产发布、付费调用、前端测试/浏览器（无 UI 改动）。本地通过不代表生产验证。
