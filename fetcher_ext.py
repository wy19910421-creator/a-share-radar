# -*- coding: utf-8 -*-
"""
扩展数据抓取层：市场全景、板块轮动、涨停池、龙虎榜、个股财务、财经要闻。
全部走 curl 子进程（本机 urllib TLS 会被断连），每个返回带 source/as_of，失败降级。
"""
import json
import subprocess
import time
from datetime import datetime

import config

UA = config.HEADERS["User-Agent"]


def _curl(url, timeout=15):
    try:
        r = subprocess.run(["curl", "-s", "-m", str(timeout), "-A", UA, url],
                           capture_output=True, timeout=timeout + 3)
        text = r.stdout.decode("utf-8", "ignore").strip()
        if text.startswith("var ajaxResult="):
            text = text[len("var ajaxResult="):]
        if text.startswith("jQuery(") and text.endswith(")"):
            text = text[len("jQuery("):-1]
        return json.loads(text) if text else None
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {e}"}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today():
    return datetime.now().strftime("%Y%m%d")


# ---------- 1. 市场全景 ----------

def fetch_market_breadth():
    """涨跌分布 + 涨停/跌停家数。"""
    j = _curl("https://push2ex.eastmoney.com/getTopicZDFenBu?"
              "ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt")
    if not j or j.get("rc") != 0 or not j.get("data"):
        return {"ok": False, "error": "涨跌分布接口不可用", "source": "东方财富 push2ex"}
    data = j["data"]
    dist = {}
    for item in data.get("fenbu", []):
        for k, v in item.items():
            dist[k] = v
    up = sum(v for k, v in dist.items() if k.isdigit() and int(k) > 0)
    down = sum(v for k, v in dist.items() if k.lstrip("-").isdigit() and k.startswith("-"))
    flat = dist.get("0", 0)
    limit_up = dist.get("11", 0) + dist.get("10", 0)
    limit_down = dist.get("-11", 0) + dist.get("-10", 0)
    return {
        "ok": True, "up": up, "down": down, "flat": flat,
        "limit_up": limit_up, "limit_down": limit_down,
        "qdate": str(data.get("qdate", "")),
        "source": "东方财富 push2ex 涨跌分布", "as_of": _now(),
    }


def fetch_limit_up_pool(size=8):
    """涨停池（连板数、封单、行业）。"""
    url = ("https://push2ex.eastmoney.com/getTopicZTPool?"
           f"ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt&Pageindex=0&pagesize={size}"
           "&sort=fbt%3Aasc&date=" + _today())
    j = _curl(url)
    if not j or j.get("rc") != 0 or not j.get("data"):
        return {"ok": False, "error": "涨停池接口不可用", "source": "东方财富 push2ex"}
    d = j["data"]
    rows = []
    for p in d.get("pool", []):
        rows.append({
            "code": p.get("c"), "name": p.get("n"),
            "price": round((p.get("p") or 0) / 1000, 2),
            "pct": round(p.get("zdp") or 0, 2),
            "amount": p.get("amount"),
            "limit_count": p.get("lbc"),          # 连板数
            "industry": p.get("hybk"),
            "fund": p.get("fund"),                # 封单资金
        })
    return {
        "ok": True, "total": d.get("tc"), "rows": rows,
        "qdate": str(d.get("qdate", "")),
        "source": "东方财富 push2ex 涨停池", "as_of": _now(),
    }


def fetch_more_indices():
    """批量指数（含科创50、中证500、上证50）。"""
    secids = "1.000001,0.399001,0.399006,1.000688,1.000905,1.000016,1.000300,0.399005"
    url = ("https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids=" + secids +
           "&fields=f1,f2,f3,f4,f12,f13,f14")
    j = _curl(url)
    if not j or j.get("rc") != 0 or not j.get("data"):
        return {"ok": False, "error": "指数批量接口不可用", "source": "东方财富 push2"}
    rows = []
    for d in j["data"].get("diff", []):
        rows.append({
            "code": d.get("f12"), "name": d.get("f14"),
            "price": d.get("f2"), "pct": d.get("f3"), "change": d.get("f4"),
        })
    return {"ok": True, "rows": rows, "source": "东方财富 push2 指数批量", "as_of": _now()}


# ---------- 2. 板块轮动 ----------

def fetch_sectors(kind="industry", size=10, po=1):
    """板块涨跌排行。kind: industry(行业) / concept(概念)；po=1 涨幅榜，po=0 跌幅榜。"""
    t = "2" if kind == "industry" else "3"
    url = ("https://push2.eastmoney.com/api/qt/clist/get?"
           f"pn=1&pz={size}&po={po}&np=1&fltt=2&invt=2&fid=f3&fs=m%3A90%2Bt%3A{t}"
           "&fields=f12,f14,f3,f62,f104,f105,f128,f136")
    j = _curl(url)
    if not j or j.get("rc") != 0 or not j.get("data"):
        return {"ok": False, "error": "板块接口不可用", "source": "东方财富 push2"}
    rows = []
    for d in j["data"].get("diff", []):
        rows.append({
            "code": d.get("f12"), "name": d.get("f14"),
            "pct": d.get("f3"), "main_net": d.get("f62"),
            "up_count": d.get("f104"), "down_count": d.get("f105"),
            "leader": d.get("f128"), "leader_pct": d.get("f136"),
        })
    label = "行业板块" if kind == "industry" else "概念板块"
    return {
        "ok": True, "total": j["data"].get("total"), "rows": rows,
        "source": f"东方财富 push2 {label}", "as_of": _now(),
    }


# ---------- 3. 龙虎榜 ----------

def fetch_dragon_tiger(size=8):
    """龙虎榜（最新交易日，按净买额排序）。"""
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
           "reportName=RPT_DAILYBILLBOARD_DETAILSNEW&columns=ALL&pageNumber=1&pageSize=20"
           "&sortColumns=TRADE_DATE,BILLBOARD_NET_AMT&sortTypes=-1,-1&source=WEB&client=WEB")
    j = _curl(url)
    if not j or not j.get("result") or not j["result"].get("data"):
        return {"ok": False, "error": "龙虎榜接口不可用", "source": "东方财富数据中心"}
    all_rows = j["result"]["data"]
    # 取最新交易日
    if all_rows:
        latest = all_rows[0].get("TRADE_DATE", "")[:10]
        rows = [d for d in all_rows if d.get("TRADE_DATE", "")[:10] == latest]
    else:
        latest, rows = "", []
    out = []
    for d in rows[:size]:
        out.append({
            "code": d.get("SECURITY_CODE"), "name": d.get("SECURITY_NAME_ABBR"),
            "close": d.get("CLOSE_PRICE"), "pct": round(d.get("CHANGE_RATE") or 0, 2),
            "net_amt": d.get("BILLBOARD_NET_AMT"),
            "explain": d.get("EXPLANATION") or d.get("EXPLAIN"),
            "trade_date": (d.get("TRADE_DATE") or "")[:10],
        })
    return {
        "ok": True, "rows": out, "trade_date": latest,
        "source": "东方财富数据中心 龙虎榜", "as_of": _now(),
    }


# ---------- 4. 个股财务 ----------

def fetch_financials(code):
    """F10 核心财务：营收/净利/增速/ROE/EPS。"""
    url = ("https://datacenter.eastmoney.com/securities/api/data/v1/get?"
           "reportName=RPT_LICO_FN_CPD&columns=ALL&filter=(SECURITY_CODE%3D%22" + code +
           "%22)&pageNumber=1&pageSize=1&source=HSF10&client=PC")
    j = _curl(url)
    if not j or not j.get("result") or not j["result"].get("data"):
        return {"ok": False, "error": "财务接口不可用", "source": "东方财富 F10"}
    d = j["result"]["data"][0]
    return {
        "ok": True, "code": code,
        "report_date": (d.get("REPORTDATE") or "")[:10],
        "eps": d.get("BASIC_EPS"), "roe": d.get("WEIGHTAVG_ROE"),
        "revenue": d.get("TOTAL_OPERATE_INCOME"), "net_profit": d.get("PARENT_NETPROFIT"),
        "revenue_yoy": round(d.get("YSTZ") or 0, 2),
        "profit_yoy": round(d.get("SJLTZ") or 0, 2),
        "bps": d.get("BPS"),
        "source": "东方财富 F10 主要指标", "as_of": _now(),
    }


# ---------- 5. 财经要闻 ----------

def fetch_news(size=8):
    """财经 7x24 快讯。"""
    j = _curl(f"https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_{size}_1_.html")
    if not j or j.get("rc") != 1 or not j.get("LivesList"):
        return {"ok": False, "error": "快讯接口不可用", "source": "东方财富快讯"}
    rows = []
    for d in j["LivesList"][:size]:
        # 快讯接口无 showTime，用 sort（16位毫秒时间戳，取前13位）还原时间
        ts = d.get("sort")
        tstr = ""
        try:
            ts_int = int(ts)
            if ts_int > 1e14:      # 16 位微秒级
                ts_int = ts_int // 1000
            tstr = datetime.fromtimestamp(ts_int / 1000).strftime("%H:%M")
        except (ValueError, TypeError, OSError):
            tstr = ""
        rows.append({
            "title": d.get("title") or d.get("simtitle"),
            "digest": d.get("digest"), "time": tstr,
            "url": d.get("url_w") or d.get("url_m"),
        })
    return {"ok": True, "rows": rows, "source": "东方财富 7x24 快讯", "as_of": _now()}


# ---------- 6. 个股涨跌榜 ----------

def fetch_stock_movers(side="up", size=8):
    """个股涨幅榜/跌幅榜。side: up(涨幅) / down(跌幅)。含代码、名称、价格、涨跌幅、主力净额、行业。"""
    po = 1 if side == "up" else 0
    # 沪深主板 + 创业板 + 科创板
    fs = "m%3A0%2Bt%3A6%2Cm%3A0%2Bt%3A80%2Cm%3A1%2Bt%3A2%2Cm%3A1%2Bt%3A23"
    url = ("https://push2.eastmoney.com/api/qt/clist/get?"
           f"pn=1&pz={size}&po={po}&np=1&fltt=2&invt=2&fid=f3&fs={fs}"
           "&fields=f12,f14,f2,f3,f62,f100")
    j = _curl(url)
    if not j or j.get("rc") != 0 or not j.get("data"):
        return {"ok": False, "error": "个股涨跌榜接口不可用", "source": "东方财富 push2"}
    rows = []
    for d in j["data"].get("diff", []):
        rows.append({
            "code": d.get("f12"), "name": d.get("f14"),
            "price": d.get("f2"), "pct": d.get("f3"),
            "main_net": d.get("f62"), "industry": d.get("f100"),
        })
    label = "涨幅榜" if side == "up" else "跌幅榜"
    return {
        "ok": True, "side": side, "total": j["data"].get("total"), "rows": rows,
        "source": f"东方财富 push2 个股{label}", "as_of": _now(),
    }


# ---------- 7. 行业重点新闻（券商研报 + 热点行业资讯） ----------

def fetch_industry_research(size=6):
    """券商行业研报（近 7 天），作为行业重点观点来源。"""
    from datetime import timedelta
    end = datetime.now().strftime("%Y-%m-%d")
    beg = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    url = ("https://reportapi.eastmoney.com/report/list?"
           "cb=&industryCode=*&pageSize=" + str(size) +
           "&industry=*&rating=&ratingchange=&beginTime=" + beg +
           "&endTime=" + end +
           "&pageNo=1&fields=&qType=1&orgCode=&rcode=&p=1&pageNumber=1&_=1")
    j = _curl(url)
    if not j or not j.get("data"):
        return {"ok": False, "error": "行业研报接口不可用", "source": "东方财富研报中心"}
    rows = []
    for d in j["data"][:size]:
        title = d.get("title") or ""
        rows.append({
            "title": title,
            "industry": d.get("industryName") or "",
            "org": d.get("orgSName") or "",
            "rating": d.get("emRatingName") or "",
            "date": (d.get("publishDate") or "")[:10],
            "url": "https://data.eastmoney.com/report/zw_industry.jshtml?infocode=" + str(d.get("infoCode") or ""),
        })
    return {
        "ok": True, "rows": rows,
        "source": "东方财富研报中心 行业研报", "as_of": _now(),
    }


def fetch_industry_news(names, per=2):
    """按给定行业名搜索相关资讯（东方财富资讯搜索），去重后返回热点行业新闻。"""
    import urllib.parse
    if not names:
        return {"ok": False, "error": "未指定行业", "source": "东方财富资讯搜索"}
    rows, seen = [], set()
    for name in names[:4]:
        param = {
            "uid": "", "keyword": name,
            "type": ["cmsArticleWebOld"], "client": "web",
            "clientType": "web", "clientVersion": "curr",
            "param": {"cmsArticleWebOld": {
                "searchScope": "default", "sort": "default",
                "pageIndex": 1, "pageSize": per,
                "preTag": "", "postTag": "",
            }},
        }
        url = ("https://search-api-web.eastmoney.com/search/jsonp?cb=jQuery&param="
               + urllib.parse.quote(json.dumps(param, ensure_ascii=False)))
        j = _curl(url)
        if not j or j.get("code") != 0:
            continue
        items = (j.get("result") or {}).get("cmsArticleWebOld") or []
        for d in items:
            title = (d.get("title") or "").strip()
            key = title[:30]
            if not title or key in seen:
                continue
            seen.add(key)
            rows.append({
                "title": title,
                "digest": (d.get("content") or "")[:120],
                "industry": name,
                "media": d.get("mediaName") or "",
                "date": (d.get("date") or "")[:16],
                "url": d.get("url") or "",
            })
        time.sleep(0.15)
    if not rows:
        return {"ok": False, "error": "行业资讯搜索无结果", "source": "东方财富资讯搜索"}
    return {
        "ok": True, "rows": rows[:10],
        "source": "东方财富资讯搜索（按热点行业）", "as_of": _now(),
    }


if __name__ == "__main__":
    for name, fn in [
        ("涨跌分布", fetch_market_breadth), ("涨停池", fetch_limit_up_pool),
        ("多指数", fetch_more_indices), ("行业板块", lambda: fetch_sectors("industry")),
        ("概念板块", lambda: fetch_sectors("concept")), ("龙虎榜", fetch_dragon_tiger),
        ("财务", lambda: fetch_financials("600519")), ("快讯", fetch_news),
        ("个股涨幅榜", lambda: fetch_stock_movers("up", 5)),
        ("个股跌幅榜", lambda: fetch_stock_movers("down", 5)),
        ("行业跌幅榜", lambda: fetch_sectors("industry", 5, po=0)),
        ("行业研报", fetch_industry_research),
        ("行业新闻", lambda: fetch_industry_news(["半导体", "医药"], 2)),
    ]:
        r = fn()
        rows = r.get("rows")
        print(f"{name}: ok={r.get('ok')} rows={len(rows) if rows else '-'} err={r.get('error','')}")
        time.sleep(0.2)
