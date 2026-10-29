# GEO 行业 & 竞品早报（企微机器人推送）

每天早上 **9:00**（北京时间）自动抓取 GEO 行业动态和 14 个竞品的最新消息，
整理成一条 Markdown 早报，通过**企业微信群机器人（消息推送）Webhook** 免费推送到群里。
运行在 **GitHub Actions** 云端定时任务上，不依赖本机开机，全程免费。

## 推送内容

- **一、行业动态**：钛媒体、量子位、爱范儿、极客公园、199IT 等 RSS 源 +
  Google News 聚合搜索（关键词：GEO / 生成式引擎 / AI搜索 / AI营销…）
- **二、竞品动态**：每个竞品两路信息
  - Google News 关键词搜索（媒体报道 + 被收录的官网动态）
  - 行业媒体中提及该竞品的新闻自动归类
- 每条包含：**标题（可点链接）、来源渠道、推文类型（产品发布/融资/报告/观点…）、内容摘要**

已配置竞品：Profound、Otterly.ai、Semrush、Peec AI、透镜GEO、爱搜GEO、智推时代、
迈富时、百分点科技、泓动数据、增长超人、微盟、腾讯GEO、360 GEO、其他大厂GEO

## 部署步骤（一次性，约 5 分钟）

### 1. 建企微机器人，拿 Webhook key

企微群 → 右上角「…」→ **消息推送** → **添加** → 新建 → 复制 **Webhook 地址**，
取 `?key=` 后面那一串，例如 `693a91f6-xxxx-xxxx-xxxx-xxxxxxxxxxxx`。

> ⚠️ key 等同密码，不要提交到仓库、不要外泄。机器人可「发布到企业」后拉进多个群。

### 2. 建 GitHub 私有仓库并推送代码

```bash
# 把本目录 wecom-daily-brief 里的所有文件（含 .github/）推到一个【私有】空仓库
git init && git add -A && git commit -m "init: GEO daily brief"
git remote add origin git@github.com:你的用户名/你的仓库名.git
git push -u origin main
```

### 3. 配置 Secret

仓库 **Settings → Secrets and variables → Actions → New repository secret**
- Name: `WECOM_WEBHOOK_KEY`
- Secret: 你的机器人 key

### 4. 测试并上线

仓库 **Actions** 页签 → 「GEO 早报推送」→ **Run workflow** 手动跑一次，
群里有消息即成功。之后每天北京时间 9:00（UTC 1:00）自动执行。
（GitHub 定时任务在高峰期可能延迟几分钟~半小时，属正常。）

## 本地测试

```bash
pip install -r requirements.txt
python main.py --dry-run --days 3   # 只打印不发送
WECOM_WEBHOOK_KEY=你的key python main.py --days 1   # 真实发送
```

> 注意：Google News 源在国内网络直连不通，本地测试会显示这些来源"异常"，
> 属预期；部署到 GitHub Actions（海外节点）后正常。行业 RSS 源本地即可验证。

## 自定义

全部在 `config.yaml`：

| 想改什么 | 怎么改 |
|---|---|
| 增删竞品 | `competitors:` 列表，`keywords` 建议写具体词避免误抓 |
| 调整行业关键词过滤 | `industry.keywords` |
| 换推送时间 | `.github/workflows/daily.yml` 里的 `cron`（UTC，北京时间-8h） |
| 回看天数 | `lookback_days`（每日跑保持 1） |
| 早报标题 | `report.title` |

## 公众号接入（可选增强）

公众号没有官方免费 RSS，两种方案，接入后往对应竞品 `sources` 里加一条
`{type: rss, url: feed地址, channel: 公众号}` 即可：

1. **自建 wechat2rss**（推荐，开源免费）：`github.com/ttttmr/wechat2rss`
2. **自部署 RSSHub** 微信公众号路由（公共实例基本不可用）

> 内部提示：新榜自家数据能力天然覆盖公众号监测，如后续想接内部接口，
> 在 `main.py` 的 `collect()` 里加一路自定义抓取即可，架构已预留。

## 常见问题

- **36氪/虎嗅为什么不在源里**：官方 RSS 已加反爬（36氪返回验证页、虎嗅超时），
  其 GEO 相关文章由 Google News 聚合查询覆盖；如需直接订阅可自建 RSSHub。
- **消息没收到**：检查 Actions 运行日志（来源异常会列在早报末尾）、
  key 是否失效（机器人被移出群）、手动 Run workflow 验证。
- **频率限制**：单机器人 20 条/分钟，脚本已自动分片+限速，无需处理。
