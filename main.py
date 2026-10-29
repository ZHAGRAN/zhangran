#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GEO 行业 & 竞品早报 —— 企微群机器人(消息推送) 每日推送脚本

流程: 读取 config.yaml -> 抓取 RSS / Google News -> 按竞品关键词分类
      -> 组装 Markdown 早报 -> 推送到企业微信群机器人 Webhook

用法:
  python main.py --dry-run            # 只打印不发送
  python main.py --days 3             # 回看最近 3 天(默认 1 天)
  python main.py --config my.yaml     # 指定配置
Webhook key 来源(优先级): 环境变量 WECOM_WEBHOOK_KEY > config.yaml
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time

import feedparser
import requests
import yaml

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 20
WECOM_SEND_API = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
# 企微 markdown 单条上限 4096 字节(utf-8)，留安全余量
MAX_BYTES = 3800


# ---------- 工具 ----------
def log(msg: str):
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def strip_html(text: str, limit: int = 110) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit] + "…"
    return text


def entry_date(entry) -> dt.datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        v = getattr(entry, key, None)
        if v:
            try:
                return dt.datetime(*v[:6])
            except Exception:
                pass
    return None


def infer_type(title: str, summary: str, categories) -> str:
    """推断推文类型(粗粒度启发式, RSS 自带 categories 时优先)。"""
    cats = [c.get("term", "") for c in (categories or []) if isinstance(c, dict)]
    cats = [c for c in cats if c]
    text = f"{title} {summary}"
    rules = [
        ("产品发布", r"发布|上线|推出|launch|release|announc|新版|更新"),
        ("融资动态", r"融资|获得.*投资|轮|acquire|acquisition|并购"),
        ("行业报告", r"报告|白皮书|research|report|榜单|排名"),
        ("观点文章", r"深度|解读|分析|指南|guide|how|趋势|洞察"),
        ("活动预告", r"直播|峰会|大会|webinar|活动|报名"),
    ]
    for name, pat in rules:
        if re.search(pat, text, re.I):
            return name
    if cats:
        return strip_html("、".join(cats[:2]), 12)
    return "动态资讯"


# ---------- 抓取 ----------
def fetch_feed(url: str) -> list[dict]:
    """抓取任意 RSS/Atom 源, 返回统一结构的条目列表。"""
    items = []
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        for e in parsed.entries:
            items.append({
                "title": strip_html(getattr(e, "title", ""), 80),
                "link": getattr(e, "link", "") or "",
                "date": entry_date(e),
                "summary": strip_html(getattr(e, "summary", getattr(e, "description", ""))),
                "categories": getattr(e, "tags", None),
            })
    except Exception as exc:
        log(f"  抓取失败 {url}: {exc}")
    return items


def fetch_gnews(query: str, lang: str = "zh-CN") -> list[dict]:
    """Google News RSS 搜索(免费无 key), 覆盖媒体对竞品的报道。"""
    q = requests.utils.quote(query)
    url = (f"https://news.google.com/rss/search?q={q}"
           f"&hl={lang}&gl=CN&ceid=CN:zh-Hans")
    return fetch_feed(url)


# ---------- 分类与组稿 ----------
def in_window(item: dict, days: int) -> bool:
    d = item["date"]
    if d is None:
        return True  # 无日期的条目保守保留
    return d >= dt.datetime.now() - dt.timedelta(days=days)


def hit_keywords(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in keywords)


def collect(cfg: dict, days: int):
    """返回 (industry_items, {竞品名: [items]}, failures)"""
    industry, comp_map, failures = [], {}, []
    now = time.time()

    # 1) 行业媒体源
    for src in cfg.get("industry", {}).get("sources", []):
        raw = []
        if src.get("type") == "rss" and src.get("url"):
            log(f"抓取行业源: {src['name']}")
            raw = fetch_feed(src["url"])
            if not raw:
                failures.append(src["name"])
            industry.extend([i for i in raw if in_window(i, days)]
                            [: cfg.get("max_items_per_source", 5)])
        for kw in src.get("extra_queries", []):
            log(f"抓取聚合搜索: {kw}")
            got = [i for i in fetch_gnews(kw) if in_window(i, days)]
            industry.extend(got[:3])

    # 2) 竞品源
    for comp in cfg.get("competitors", []):
        name, kws = comp["name"], comp.get("keywords", [comp["name"]])
        bucket = comp_map.setdefault(name, [])
        for src in comp.get("sources", []):
            if src.get("type") == "gnews":
                log(f"抓取竞品源: {name} -> gnews: {src['query']}")
                raw = fetch_gnews(src["query"])
            elif src.get("type") == "rss":
                log(f"抓取竞品源: {name} -> {src.get('channel', 'RSS')}: {src['url']}")
                raw = fetch_feed(src["url"])
            else:
                continue
            if not raw:
                failures.append(f"{name}/{src.get('channel', src.get('query', '?'))}")
            for i in raw:
                if in_window(i, days) and i["title"] and i["link"]:
                    i["channel"] = src.get("channel", "媒体报道")
                    bucket.append(i)
        # 3) 从行业媒体里捞竞品提及, 避免漏掉大厂 GEO 业务新闻
        for i in list(industry):
            if hit_keywords(i["title"] + " " + i["summary"], kws):
                i["channel"] = "媒体报道"
                bucket.append(i)
        # 去重 + 截断
        seen, uniq = set(), []
        for i in bucket:
            if i["link"] not in seen:
                seen.add(i["link"])
                uniq.append(i)
        comp_map[name] = uniq[: cfg.get("max_items_per_competitor", 4)]

    # 行业部分按关键词过滤(避免早报被无关新闻刷屏)
    kws = cfg.get("industry", {}).get("keywords", [])
    if kws:
        industry = [i for i in industry
                    if hit_keywords(i["title"] + " " + i["summary"], kws)]
    # 行业去重
    seen, uniq = set(), []
    for i in industry:
        if i["link"] and i["link"] not in seen:
            seen.add(i["link"])
            uniq.append(i)
    industry = uniq[: cfg.get("max_industry_items", 8)]
    return industry, comp_map, failures


def fmt_item(i: dict, idx: int) -> str:
    date_s = i["date"].strftime("%m-%d") if i["date"] else ""
    type_s = infer_type(i["title"], i["summary"], i.get("categories"))
    line = f"{idx}. [{i['title']}]({i['link']})"
    meta = [x for x in (i.get("channel", ""), type_s, date_s) if x]
    if meta:
        line += f"\n    > {' | '.join(meta)}"
    if i["summary"]:
        line += f"\n    > {i['summary']}"
    return line


def build_report(cfg: dict, industry: list, comp_map: dict, failures: list) -> list[str]:
    """组装 markdown, 超长自动分片。"""
    today = dt.date.today().strftime("%Y-%m-%d")
    title = cfg.get("report", {}).get("title", "GEO 行业 & 竞品早报")
    chunks, buf = [], [f"**{title}** {today}\n"]

    def flush():
        if len(buf) > 1:
            chunks.append("\n".join(buf))
        buf.clear()

    def add(text: str):
        # 按字节估算分片
        if sum(len(s.encode('utf-8')) for s in buf) + len(text.encode('utf-8')) > MAX_BYTES:
            flush()
            buf.append(f"**{title}**(续)\n")
        buf.append(text)

    add(f"\n**一、行业动态**({len(industry)}条)")
    if industry:
        for n, i in enumerate(industry, 1):
            add(fmt_item(i, n))
    else:
        add("今日行业源无关键词相关新增。")

    add(f"\n**二、竞品动态**")
    any_comp = False
    for name, items in comp_map.items():
        if not items:
            continue
        any_comp = True
        add(f"\n<font color=\"info\">**{name}**</font>({len(items)}条)")
        for n, i in enumerate(items, 1):
            add(fmt_item(i, n))
    if not any_comp:
        add("今日各竞品无新增动态。")

    if failures:
        add(f"\n<font color=\"comment\">来源异常: {('、'.join(failures))}</font>")
    flush()
    return chunks


# ---------- 发送 ----------
def send(key: str, chunks: list[str]) -> bool:
    ok = True
    for n, content in enumerate(chunks, 1):
        payload = {"msgtype": "markdown", "markdown": {"content": content}}
        try:
            r = requests.post(WECOM_SEND_API, params={"key": key},
                              json=payload, timeout=TIMEOUT)
            data = r.json()
            if data.get("errcode") == 0:
                log(f"已推送第 {n}/{len(chunks)} 条")
            else:
                log(f"推送失败({n}/{len(chunks)}): {data}")
                ok = False
        except Exception as exc:
            log(f"推送异常: {exc}")
            ok = False
        if n < len(chunks):
            time.sleep(1)  # 频率限制 20条/分钟, 留间隔
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    days = args.days or cfg.get("lookback_days", 1)
    key = os.environ.get("WECOM_WEBHOOK_KEY", "") or cfg.get("webhook_key", "")

    log(f"开始抓取, 回看窗口 {days} 天")
    industry, comp_map, failures = collect(cfg, days)
    chunks = build_report(cfg, industry, comp_map, failures)

    if args.dry_run:
        for c in chunks:
            print("\n" + "=" * 46 + "\n" + c)
        print(f"\n共 {len(chunks)} 片 | 行业 {len(industry)} 条 | "
              f"竞品 {sum(len(v) for v in comp_map.values())} 条")
        return

    if not key:
        sys.exit("未配置 Webhook key: 请设置环境变量 WECOM_WEBHOOK_KEY 或填入 config.yaml")
    if not send(key, chunks):
        sys.exit(1)
    log("完成")


if __name__ == "__main__":
    main()
