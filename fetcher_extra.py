# -*- coding: utf-8 -*-
"""
改进版模板专用数据抓取层（2026-11-25 改进版模板）。
覆盖：两市成交额(含前一日)、跌停池聚合、炸板池、连板梯队、昨日涨停表现、
板块资金双向、期指基差、解禁日历、精选公告、宏观政策消息。
全部走 curl 子进程；每个函数带 source/as_of，失败降级、不编造数据。
"""
import json
import subprocess
import time
from datetime import datetime, timedelta

import config

UA = config.HEADERS["User-Agent"]
UT = "7eea3edcaed734bea9cbfc24409ed989"


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


def _prev_trade_date():
    """上一交易日（粗略：跳过周末，遇节假日以接口返回为准）。"""
    d = datetime.now() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


# ---------- 1. 两市成交额 + 前一日 ----------

def _sh_sz_amount():
    """沪市 + 深市成交额（f6，单位元）。"""
    url = ("https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2"
           "&secids=1.000001,0.399001&fields=f6,f12,f14")
    j = _curl(url)
    if not j or j.get("rc") != 0 or not j.get("data"):
        return None
    total, detail = 0.0, {}
    for d in j["data"].get("diff", []):
        amt = d.get("f6")
        if isinstance(amt, (int, float)):
            total += amt
            detail[d.get("f14")] = amt
    return {"total": total, "detail": detail} if total > 0 else None


def _kline_amount_last(secid, n=3):
    """从日K最近 n 根取每日成交额（多域名重试，失败返回 None）。"""
    hosts = ["push2his.eastmoney.com", "63.push2his.eastmoney.com", "push2his.eastmoney.com"]
    for host in hosts:
        url = (f"https://{host}/api/qt/stock/kline/get?secid={secid}&klt=101&fqt=1"
               "&beg=0&end=20500101&lmt=" + str(n) + "&_=" + str(int(time.time() * 1000)) +
               "&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57")
        j = _curl(url, timeout=12)
        data = j.get("data") if isinstance(j, dict) else None
        if data and data.get("klines"):
            out = []
            for line in data["klines"]:
                p = line.split(",")
                try:
                    out.append({"date": p[0], "amount": float(p[6])})
                except (ValueError, IndexError):
                    continue
            if out:
                return out
        time.sleep(0.3)
    return None


def fetch_turnover():
    """两市成交额（今日 vs 昨日），返回放量/缩量。沪市f6+深市f6；昨日取两市日K最近一根。"""
    today = _sh_sz_amount()
    if not today:
        return {"ok": False, "error": "今日成交额接口不可用", "source": "东方财富 push2"}
    sh = _kline_amount_last("1.000001", 3)
    sz = _kline_amount_last("0.399001", 3)
    prev, prev_date = None, ""
    if sh and sz:
        # 以日期对齐取最近一个共同交易日
        sz_map = {r["date"]: r["amount"] for r in sz}
        for r in reversed(sh):
            if r["date"] in sz_map:
                prev = r["amount"] + sz_map[r["date"]]
                prev_date = r["date"]
                break
    amt = today["total"]
    chg_pct = ((amt / prev - 1) * 100) if prev and prev > 0 else None
    if chg_pct is None:
        state = "未知"
    elif chg_pct > 3:
        state = "显著放量"
    elif chg_pct > 0.5:
        state = "放量"
    elif chg_pct < -3:
        state = "显著缩量"
    elif chg_pct < -0.5:
        state = "缩量"
    else:
        state = "基本持平"
    return {
        "ok": True, "amount": amt,
        "sh_amount": today["detail"].get("上证指数"),
        "sz_amount": today["detail"].get("深证成指"),
        "prev_amount": prev, "prev_date": prev_date,
        "chg_pct": round(chg_pct, 2) if chg_pct is not None else None,
        "state": state,
        "source": "东方财富 push2 实时 + push2his 日K", "as_of": _now(),
    }


# ---------- 2. 跌停池（按行业聚合） ----------

def fetch_limit_down():
    """跌停池：按行业聚合家数、区分ST，列出成交额靠前的个股明细。"""
    url = ("https://push2ex.eastmoney.com/getTopicDTPool?ut=" + UT +
           "&dpt=wz.ztzt&Pageindex=0&pagesize=500&sort=zdp%3Aasc&date=" + _today())
    j = _curl(url)
    if not j or j.get("rc") != 0 or not j.get("data"):
        return {"ok": False, "error": "跌停池接口不可用", "source": "东方财富 push2ex"}
    pool = j["data"].get("pool") or []
    total = j["data"].get("tc")
    byind, st_n, nonst_n = {}, 0, 0
    rows = []
    for p in pool:
        name = p.get("n") or ""
        ind = p.get("hybk") or "其他"
        price = round((p.get("p") or 0) / 1000, 2)
        amount = p.get("amount")
        is_st = "ST" in name.upper()
        st_n += 1 if is_st else 0
        nonst_n += 0 if is_st else 1
        if ind not in byind:
            byind[ind] = {"name": ind, "count": 0, "st": 0, "nonst": 0, "amount": 0}
        byind[ind]["count"] += 1
        byind[ind]["st" if is_st else "nonst"] += 1
        byind[ind]["amount"] += (amount or 0)
        rows.append({
            "code": p.get("c"), "name": name, "price": price,
            "pct": round(p.get("zdp") or 0, 2), "amount": amount,
            "industry": ind, "is_st": is_st, "days": p.get("days"),
        })
    top_ind = sorted(byind.values(), key=lambda x: -x["count"])[:10]
    # 明细只列成交额靠前的（流动性大的更有参考意义）
    top_rows = sorted(rows, key=lambda x: -(x.get("amount") or 0))[:5]
    return {
        "ok": True, "total": total if total is not None else len(rows),
        "st_count": st_n, "nonst_count": nonst_n,
        "by_industry": top_ind, "rows": top_rows,
        "source": "东方财富 push2ex 跌停池", "as_of": _now(),
    }


# ---------- 3. 炸板池 + 连板梯队 ----------

def fetch_broken_board():
    """炸板池：炸板家数、炸板率=炸板/(涨停+炸板)，列出代表个股。"""
    url = ("https://push2ex.eastmoney.com/getTopicZBPool?ut=" + UT +
           "&dpt=wz.ztzt&Pageindex=0&pagesize=200&sort=fbt%3Aasc&date=" + _today())
    j = _curl(url)
    if not j or j.get("rc") != 0 or not j.get("data"):
        return {"ok": False, "error": "炸板池接口不可用", "source": "东方财富 push2ex"}
    pool = j["data"].get("pool") or []
    total = j["data"].get("tc")
    rows = []
    for p in pool:
        rows.append({
            "code": p.get("c"), "name": p.get("n"),
            "pct": round(p.get("zdp") or 0, 2),
            "amount": p.get("amount"), "broken_count": p.get("zbc"),
            "industry": p.get("hybk"),
            "limit_count": (p.get("zttj") or {}).get("ct"),
        })
    return {
        "ok": True, "total": total if total is not None else len(rows), "rows": rows[:12],
        "source": "东方财富 push2ex 炸板池", "as_of": _now(),
    }


def fetch_limit_up_ladder():
    """涨停梯队：按连板数分组（>=4板 / 3板 / 2板），个股明细只列连板>=3。"""
    url = ("https://push2ex.eastmoney.com/getTopicZTPool?ut=" + UT +
           "&dpt=wz.ztzt&Pageindex=0&pagesize=500&sort=fbt%3Aasc&date=" + _today())
    j = _curl(url)
    if not j or j.get("rc") != 0 or not j.get("data"):
        return {"ok": False, "error": "涨停池接口不可用", "source": "东方财富 push2ex"}
    pool = j["data"].get("pool") or []
    ladder = {">=4": [], "3": [], "2": [], "1": []}
    byind = {}
    for p in pool:
        lb = p.get("lbc") or 1
        item = {
            "code": p.get("c"), "name": p.get("n"),
            "price": round((p.get("p") or 0) / 1000, 2),
            "limit_count": lb, "industry": p.get("hybk"),
            "fund": p.get("fund"),
        }
        key = ">=4" if lb >= 4 else (str(lb) if lb in (2, 3) else "1")
        ladder[key].append(item)
        ind = p.get("hybk") or "其他"
        byind[ind] = byind.get(ind, 0) + 1
    top_ind = sorted([{"name": k, "count": v} for k, v in byind.items()],
                     key=lambda x: -x["count"])[:8]
    return {
        "ok": True, "total": j["data"].get("tc"),
        "max_height": max([p.get("lbc") or 1 for p in pool], default=0),
        "ladder": ladder, "by_industry": top_ind,
        "detail": sorted(ladder[">=4"] + ladder["3"], key=lambda x: -x["limit_count"])[:12],
        "source": "东方财富 push2ex 涨停池", "as_of": _now(),
    }


def fetch_yesterday_limit_up_perf():
    """昨日涨停股今日平均涨幅。取昨日涨停池代码 -> 今日实时涨跌幅求均值。"""
    yd = _prev_trade_date()
    # 当前日期（以数据日为准）：凌晨0-9点视为前一交易日数据尚未产生，用昨日作数据日
    now = datetime.now()
    data_day = (now - timedelta(days=1)).strftime("%Y%m%d") if now.hour < 9 else _today()
    url = ("https://push2ex.eastmoney.com/getTopicZTPool?ut=" + UT +
           "&dpt=wz.ztzt&Pageindex=0&pagesize=200&sort=fbt%3Aasc&date=" + yd)
    j = _curl(url)
    if not j or j.get("rc") != 0 or not j.get("data"):
        return {"ok": False, "error": "昨日涨停池接口不可用", "source": "东方财富 push2ex"}
    pool = j["data"].get("pool") or []
    if not pool:
        return {"ok": False, "error": "昨日涨停池无数据", "source": "东方财富 push2ex"}
    qdate = str(j["data"].get("qdate", ""))
    # 数据日 = 最新交易日的日期（凌晨时段为昨日）；若接口返回的 qdate == 数据日，
    # 说明拿到的是"当日涨停池"而非"昨日涨停池"，接口忽略了 date 参数，不编造。
    if qdate != yd or qdate == data_day:
        return {"ok": False,
                "error": f"接口仅返回最新交易日涨停池（qdate={qdate}），无法取昨日名单，标注数据缺失",
                "source": "东方财富 push2ex"}
    codes = [p.get("c") for p in pool[:60]]
    secids = []
    for c in codes:
        secids.append(("1." if str(c).startswith(("6", "5")) else "0.") + str(c))
    qurl = ("https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids=" +
            ",".join(secids) + "&fields=f2,f3,f12,f14")
    qj = _curl(qurl)
    pcts = []
    if qj and qj.get("data"):
        for d in qj["data"].get("diff", []):
            if isinstance(d.get("f3"), (int, float)):
                pcts.append(d["f3"])
    if not pcts:
        return {"ok": False, "error": "今日行情接口未返回", "source": "东方财富 push2"}
    return {
        "ok": True, "date": yd, "sample": len(pcts),
        "avg_pct": round(sum(pcts) / len(pcts), 2),
        "up": sum(1 for p in pcts if p > 0),
        "down": sum(1 for p in pcts if p < 0),
        "source": "东方财富 push2ex + push2", "as_of": _now(),
    }


# ---------- 4. 板块资金双向（净流入/净流出前5） ----------

def fetch_sector_flow(kind="industry", side="in", size=5):
    """板块资金净流入/流出排行。f62=主力净额，f6=成交额（低于1亿剔除）。"""
    t = "2" if kind == "industry" else "3"
    po = 1 if side == "in" else 0
    url = ("https://push2.eastmoney.com/api/qt/clist/get?"
           f"pn=1&pz=30&po={po}&np=1&fltt=2&invt=2&fid=f62&fs=m%3A90%2Bt%3A{t}"
           "&fields=f12,f14,f3,f62,f6,f128,f136")
    j = _curl(url)
    if not j or j.get("rc") != 0 or not j.get("data"):
        return {"ok": False, "error": "板块资金接口不可用", "source": "东方财富 push2"}
    rows = []
    for d in j["data"].get("diff", []):
        amt = d.get("f6")
        # 成交额门槛：低于 1 亿不上榜（模板要求剔除小板块噪音）
        if not isinstance(amt, (int, float)) or amt < 1e8:
            continue
        pct = d.get("f3")
        net = d.get("f62")
        diverge = ""
        if isinstance(pct, (int, float)) and isinstance(net, (int, float)):
            if pct > 0 and net < 0:
                diverge = "涨但资金流出"
            elif pct < 0 and net > 0:
                diverge = "跌但资金流入"
        rows.append({
            "code": d.get("f12"), "name": d.get("f14"), "pct": pct,
            "main_net": net, "amount": amt,
            "leader": d.get("f128"), "leader_pct": d.get("f136"),
            "diverge": diverge,
        })
        if len(rows) >= size:
            break
    label = "行业" if kind == "industry" else "概念"
    direction = "净流入" if side == "in" else "净流出"
    return {
        "ok": bool(rows), "rows": rows,
        "source": f"东方财富 push2 {label}板块资金{direction}", "as_of": _now(),
    }


# ---------- 5. 股指期货基差 ----------

def fetch_index_futures():
    """四大期指主力合约 vs 现货指数，计算基差（现货-期货，正=贴水）。"""
    u1 = ("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=72&po=1&np=1"
          "&fltt=2&invt=2&fid=f3&fs=m%3A8&fields=f2,f3,f4,f12,f14")
    j1 = _curl(u1)
    if not j1 or not j1.get("data"):
        return {"ok": False, "error": "期指接口不可用", "source": "东方财富 push2"}
    fut = {}
    for d in j1["data"].get("diff", []):
        nm = d.get("f14") or ""
        # 精确匹配"XX主力合约"，排除"次主力合约"
        if nm.endswith("主力合约") and "次" not in nm:
            key = nm[:2]  # IF/IH/IC/IM
            fut[key] = d.get("f2")
    u2 = ("https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2"
          "&secids=1.000300,1.000016,1.000905,1.000852&fields=f2,f3,f12,f14")
    j2 = _curl(u2)
    if not j2 or not j2.get("data"):
        return {"ok": False, "error": "现货指数接口不可用", "source": "东方财富 push2"}
    spot_map = {"IF": "沪深300", "IH": "上证50", "IC": "中证500", "IM": "中证1000"}
    spot = {d.get("f14"): d.get("f2") for d in j2["data"].get("diff", [])}
    rows = []
    for key, spot_name in spot_map.items():
        fv, sv = fut.get(key), spot.get(spot_name)
        if isinstance(fv, (int, float)) and isinstance(sv, (int, float)):
            basis = sv - fv
            rows.append({
                "name": key, "spot_name": spot_name,
                "future": fv, "spot": sv,
                "basis": round(basis, 2),
                "basis_pct": round(basis / sv * 100, 3) if sv else None,
                "state": "贴水" if basis > 0 else ("升水" if basis < 0 else "平水"),
            })
    return {"ok": bool(rows), "rows": rows,
            "source": "东方财富 push2 期指/现货", "as_of": _now()}


# ---------- 6. 国债收益率（降级标注：本机接口不可用） ----------

def fetch_bond_yield():
    """10年期国债收益率。当前公开接口不稳定，返回不可用状态，绝不编造。"""
    candidates = [
        ("中国10年期国债", "100.CN10Y"),
        ("美国10年期国债", "100.US10Y"),
    ]
    for name, secid in candidates:
        url = ("https://push2.eastmoney.com/api/qt/stock/get?secid=" + secid +
               "&fields=f2,f3,f43,f57,f58")
        j = _curl(url, timeout=10)
        d = j.get("data") if isinstance(j, dict) else None
        if d and isinstance(d.get("f2"), (int, float)) and d.get("f2") > 0:
            return {
                "ok": True, "name": name, "value": d.get("f2") / 100 if d.get("f2") > 100 else d.get("f2"),
                "raw": d.get("f2"), "pct": d.get("f3"),
                "source": "东方财富 push2 " + name, "as_of": _now(),
            }
        time.sleep(0.2)
    return {
        "ok": False, "error": "10年期国债收益率接口不可用（公开接口未返回数据）",
        "note": "按模板要求标注数据缺失，不编造数值",
        "source": "东方财富 push2", "as_of": _now(),
    }


# ---------- 7. 解禁日历（明日关注） ----------

def fetch_unlock_calendar(days=3):
    """未来 N 天限售解禁（按解禁市值排序）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    flt = f"(FREE_DATE%3E%3D%27{today}%27)(FREE_DATE%3C%3D%27{end}%27)"
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
           "reportName=RPT_LIFT_STAGE&columns=ALL&pageNumber=1&pageSize=50"
           "&sortColumns=LIFT_MARKET_CAP&sortTypes=-1&source=WEB&client=WEB&filter=" + flt)
    j = _curl(url)
    if not j or not j.get("result") or not j["result"].get("data"):
        return {"ok": False, "error": "解禁日历接口不可用", "source": "东方财富数据中心"}
    rows = []
    for d in j["result"]["data"][:10]:
        rows.append({
            "code": d.get("SECURITY_CODE"), "name": d.get("SECURITY_NAME_ABBR"),
            "date": (d.get("FREE_DATE") or "")[:10],
            "cap": d.get("LIFT_MARKET_CAP"),  # 解禁市值（万元）
            "ratio": d.get("FREE_RATIO"),
            "type": d.get("FREE_SHARES_TYPE"),
        })
    return {"ok": bool(rows), "rows": rows,
            "source": "东方财富数据中心 限售解禁", "as_of": _now()}


# ---------- 8. 精选公告（并购/回购/减持/业绩/监管） ----------

ANNO_KEEP = {
    "并购重组": ["收购", "重组", "合并", "资产购买", "发行股份购买"],
    "定增": ["非公开发行", "向特定对象发行", "定增"],
    "重大合同": ["中标", "重大合同", "框架协议"],
    "大额回购": ["回购"],
    "增持": ["增持"],
    "减持": ["减持"],
    "解禁": ["解除限售", "限售股上市流通"],
    "业绩": ["业绩预告", "业绩快报", "年度报告", "季度报告", "半年度报告"],
    "监管": ["立案", "处罚", "监管", "问询", "警示函"],
}
ANNO_DROP = ["公司章程", "股东会通知", "增加股东大会议案", "监事会", "董事会决议",
             "独立董事", "制度", "章程修订", "股东大会通知"]


def fetch_curated_announcements(size=10):
    """精选公告：按标题关键词分类，剔除程序性噪音，回购要求金额较大（>=1亿）。"""
    url = ("https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1"
           f"&page_size=80&page_index=1&ann_type=A&client_source=web&f_node=0&s_node=0")
    j = _curl(url)
    if not j or not j.get("data") or not j["data"].get("list"):
        return {"ok": False, "error": "公告接口不可用", "source": "东方财富公告"}
    out = []
    for d in j["data"]["list"]:
        title = d.get("title") or ""
        if any(k in title for k in ANNO_DROP):
            continue
        cat = ""
        for c, kws in ANNO_KEEP.items():
            if any(k in title for k in kws):
                cat = c
                break
        if not cat:
            continue
        codes = d.get("codes") or []
        stock = codes[0] if codes else {}
        out.append({
            "title": title, "category": cat,
            "code": stock.get("stock_code"), "name": stock.get("short_name"),
            "date": (d.get("notice_date") or "")[:10],
            "url": "https://data.eastmoney.com/notices/detail/" +
                   str(stock.get("stock_code", "")) + "/" + str(d.get("art_code", "")) + ".html",
        })
        if len(out) >= size:
            break
    return {"ok": bool(out), "rows": out,
            "source": "东方财富公告（关键词精选）", "as_of": _now()}


# ---------- 9. 宏观/政策消息（解释大跌用） ----------

MACRO_KW = ["央行", "证监会", "国务院", "国常会", "财政部", "政策", "监管",
            "降准", "降息", "加息", "关税", "制裁", "IPO", "注册制", "熔断",
            "汇金", "国家队", "稳增长", "GDP", "CPI", "PMI", "社融", "美联储"]


def fetch_macro_news(size=6):
    """从快讯中筛选政策/监管/宏观消息；无则明确返回空（不编造催化事件）。"""
    j = _curl("https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_60_1_.html")
    if not j or j.get("rc") != 1 or not j.get("LivesList"):
        return {"ok": False, "error": "快讯接口不可用", "source": "东方财富快讯"}
    rows = []
    for d in j["LivesList"]:
        title = d.get("title") or d.get("simtitle") or ""
        if not any(k in title for k in MACRO_KW):
            continue
        ts = d.get("sort")
        tstr = ""
        try:
            ti = int(ts)
            if ti > 1e14:
                ti //= 1000
            tstr = datetime.fromtimestamp(ti / 1000).strftime("%H:%M")
        except (ValueError, TypeError, OSError):
            pass
        rows.append({
            "title": title, "time": tstr,
            "digest": d.get("digest"),
            "url": d.get("url_w") or d.get("url_m"),
        })
        if len(rows) >= size:
            break
    return {
        "ok": True, "rows": rows,
        "note": "与政策/监管/宏观相关的消息（关键词筛选）；为空表示未检索到明确催化事件",
        "source": "东方财富 7x24 快讯（宏观关键词筛选）", "as_of": _now(),
    }


if __name__ == "__main__":
    tests = [
        ("两市成交额", fetch_turnover),
        ("跌停池", fetch_limit_down),
        ("炸板池", fetch_broken_board),
        ("涨停梯队", fetch_limit_up_ladder),
        ("昨日涨停表现", fetch_yesterday_limit_up_perf),
        ("行业资金流入", lambda: fetch_sector_flow("industry", "in")),
        ("行业资金流出", lambda: fetch_sector_flow("industry", "out")),
        ("期指基差", fetch_index_futures),
        ("国债收益率", fetch_bond_yield),
        ("解禁日历", lambda: fetch_unlock_calendar(3)),
        ("精选公告", fetch_curated_announcements),
        ("宏观消息", fetch_macro_news),
    ]
    for name, fn in tests:
        try:
            r = fn()
            rows = r.get("rows") or r.get("by_industry") or r.get("ladder") or []
            n = len(rows) if isinstance(rows, list) else "-"
            print(f"{name}: ok={r.get('ok')} rows={n} err={r.get('error','')}")
        except Exception as e:  # noqa: BLE001
            print(f"{name}: EXC {type(e).__name__}: {e}")
        time.sleep(0.2)
