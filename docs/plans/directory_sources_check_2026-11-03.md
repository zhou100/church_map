# 目录站能不能自动扫：robots.txt 和使用条款的检查

**检查时间：** 2026-11-03（UTC 当天）· **方式：** 用爬虫的 UA（`ChurchMapBot/1.0`）获取 robots.txt 和条款页面，只读，没有抓任何列表页
**结论先说：** robots.txt 允许，但**两家的使用条款都限制复制和再利用它们的数据**。没有书面许可，不建议做自动扫描。这不是法律意见，最终由业主判断。

---

## 1. ChurchFinder（churchfinder.com）

**robots.txt**（`https://www.churchfinder.com/robots.txt`，HTTP 200）

- 对所有爬虫（`User-agent: *`）禁止访问的路径：`/search/`、`/admin/`、`/user/*`、`/node/*/claim`、`/church/*/reviews`，以及一些静态资源目录。
- 城市列表页和教会页面**没有被禁止**。
- 对 AhrefsBot、SemrushBot、GPTBot 等整站禁止，并注明这些爬虫在服务器层面也被拒绝。
- 2026-09-12 加了一条注释：说每天有约 22.5 万次请求在爬 claim 和 reviews 链接，所以禁止了这两类路径。说明这个站在意抓取带来的负载。

**使用条款**（`https://www.churchfinder.com/terms-and-conditions`）

- "USE OF CHURCH DATA. PERSONAL AND NON-COMMERCIAL USE LIMITATION … all church data on the CF Web Sites are for your personal and noncommercial use."
- "You may not modify, copy, distribute, transmit, display, perform, reproduce, publish, license, create derivative works from, transfer, or sell any information … obtained from the CF Web Sites."
- 网站内容"including … the selection and arrangements thereof"受合集作品版权保护。

## 2. oursweb 华人教会名录（church.oursweb.net，CCNDA 运营）

**robots.txt**

- `https://church.oursweb.net/robots.txt`：只有 `Disallow: /html/`。
- `https://oursweb.net/robots.txt`：只有 content-signal 的说明注释，没有具体规则。

**使用条款**：名录页脚的"服務條款"链接到 `https://www.ccnda.org/rules`。

- 禁止"未經本協會同意擅自摘錄、轉載、複製或使用本網站內任何會員服務資料庫之內容"。
- 网站上的所有内容（著作、資訊、資料、網站架構等）"任何人不得逕自使用、修改、重製……若您欲引用或轉載……必須依法取得 CCNDA 或其他權利人的事前書面同意"。

## 3. 这对我们意味着什么

1. **自动扫描（计划 F）**：把列表页批量抓下来生成线索库，就属于"复制、使用资料库内容"或"创作衍生作品"。没有书面许可就不做。
2. **Muse 现在的 D12 扫描**也在用这两个站（brief v3.4 起），已经通过目录站发现了 628 个新教会。
   - 我们发布的事实都引自教会自己的网站，目录站只用来"找"（S5 规则），没有复制目录站的内容。
   - 但"系统地用目录站列表决定研究哪些教会"是否在条款允许的范围内，同样存在疑问。
   - 要不要继续让 Muse 扫这两个站，需要业主决定。这份检查没有改动 Muse 的任何规则。
3. **可以考虑的替代来源**（都需要逐个检查）：
   - **IRS EO BMF**：公有领域，加州 16,880 条线索，见记忆记录 `project_irs_bmf_measurement`；
   - **OSM**：ODbL 许可，就是现在的目录来源；
   - **各宗派官方的教会查找页**：天主教教区、LDS、Kingdom Hall 等，每家条款不同；
   - **直接写信给 ChurchFinder 或 CCNDA 申请许可**：ChurchFinder 条款里提到的 "authorized, written permission" 有这个渠道。

## 4. 需要业主决定

1. 计划 F（自动扫目录站）：搁置，还是先写信申请许可？
2. Muse 的 D12 目录扫描：照常，还是暂停改用其他来源找线索？
