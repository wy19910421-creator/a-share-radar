# -*- coding: utf-8 -*-
"""
深度数据抓取层：全球市场、商品汇率、两融、北向、资金流细分、财务多期。
curl 后端，每个返回带 source/as_of，失败降级。
"""
import json
import subprocess
from datetime import datetime

import config

UA = config.HEADERS["User-Agent"]


def _curl(url, timeout=15):
    try:
        r = subprocess.run(["curl", "-s", "-m", str(timeout), "-A", UA, url],
                           capture_output=True, timeout=timeout + 3)
        text = r.stdout.decode("utf-8", "ignore").strip()
        return json.loads(text) if text else None
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {e}"}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _batch_quotes(secids, fields="f1,f2,f3,f4,f12,f13,f14"):
    url = ("https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids=" + secids +
           "&fields=" + fields)
    j = _curl(url)
    if not j or j.get("rc") != 0 or not j.get("data"):
        return None
    rows = []
    for d in j["data"].get("diff", []):
        rows.append({
            "code": d.get("f12"), "name": d.get("f14"),
            "price": d.get("f2"), "pct": d.get("f3"), "change": d.get("f4"),
        })
    return rows


# ---------- 1. 全球市场 ----------

def fetch_global_markets():
    """隔夜/盘中全球股指。"""
    rows = _batch_quotes("100.DJIA,100.NDX,100.SPX,100.HSI,124.HSTECH,100.N225")
    if not rows:
        return {"ok": False, "error": "全球指数接口不可用", "source": "东方财富 push2"}
    return {"ok": True, "rows": rows, "source": "东方财富 push2 全球指数", "as_of": _now()}


def fetch_commodities_fx():
    """商品与汇率：美元指数、COMEX黄金、NYMEX原油、离岸人民币。"""
    rows = _batch_quotes("100.UDI,101.GC00Y,102.CL00Y,133.USDCNH")
    if not rows:
        return {"ok": False, "error": "商品汇率接口不可用", "source": "东方财富 push2"}
    return {"ok": True, "rows": rows, "source": "东方财富 push2 商品汇率", "as_of": _now()}


# ---------- 2. 两融 ----------

def fetch_margin():
    """两融余额（融资余额/融券余额/融资净买入）。"""
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
           "reportName=RPTA_RZRQ_LSHJ&columns=ALL&pageNumber=1&pageSize=1"
           "&sortColumns=dim_date&sortTypes=-1&source=WEB&client=WEB")
    j = _curl(url)
    if not j or not j.get("result") or not j["result"].get("data"):
        return {"ok": False, "error": "两融接口不可用", "source": "东方财富数据中心"}
    d = j["result"]["data"][0]
    return {
        "ok": True,
        "date": (d.get("DIM_DATE") or "")[:10],
        "rz_ye": d.get("RZYE"),          # 融资余额
        "rq_ye": d.get("RQYE"),          # 融券余额
        "rz_jme": d.get("RZJME"),        # 融资净买入
        "rz_ye_zb": d.get("RZYEZB"),     # 融资余额占流通市值比
        "source": "东方财富数据中心 两融", "as_of": _now(),
    }


# ---------- 3. 北向资金（改革后仅成交额口径） ----------

def fetch_northbound():
    """北向成交额（沪深港通改革后不再披露实时净买入，仅成交额）。"""
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
           "reportName=RPT_MUTUAL_DEAL_HISTORY&columns=ALL&pageNumber=1&pageSize=1"
           "&sortColumns=TRADE_DATE&sortTypes=-1&source=WEB&client=WEB"
           "&filter=(MUTUAL_TYPE%3D%22001%22)")
    j = _curl(url)
    if not j or not j.get("result") or not j["result"].get("data"):
        return {"ok": False, "error": "北向接口不可用", "source": "东方财富数据中心"}
    d = j["result"]["data"][0]
    return {
        "ok": True,
        "date": (d.get("TRADE_DATE") or "")[:10],
        "deal_amt": d.get("DEAL_AMT"),        # 成交额（万元）
        "index_close": d.get("INDEX_CLOSE_PRICE"),
        "index_pct": d.get("INDEX_CHANGE_RATE"),
        "note": "沪深港通改革后不再披露实时净买入，仅展示成交额",
        "source": "东方财富数据中心 沪深港通", "as_of": _now(),
    }


# ---------- 4. 个股资金流细分 ----------

def fetch_flow_detail(secid):
    """个股资金流细分（超大单/大单/中单/小单）。盘中可能不全，盘后完整。"""
    url = ("https://push2.eastmoney.com/api/qt/stock/get?secid=" + secid +
           "&fields=f57,f58,f62,f66,f69,f72,f75,f78,f81,f84,f87")
    j = _curl(url)
    if not j or not j.get("data"):
        return {"ok": False, "error": "资金细分接口不可用", "source": "东方财富 push2"}
    d = j["data"]
    def v(k):
        x = d.get(k)
        return None if x in (None, "-", "") else float(x)
    return {
        "ok": True, "code": d.get("f57"), "name": d.get("f58"),
        "main_net": v("f62"),
        "super_net": v("f66"), "super_pct": v("f69"),
        "big_net": v("f72"), "big_pct": v("f75"),
        "mid_net": v("f78"), "mid_pct": v("f81"),
        "small_net": v("f84"), "small_pct": v("f87"),
        "source": "东方财富 push2 资金流细分", "as_of": _now(),
    }


# ---------- 5. 财务多期 ----------

def fetch_financials_history(code, periods=3):
    """财务多期趋势（营收/净利/ROE/EPS）。"""
    url = ("https://datacenter.eastmoney.com/securities/api/data/v1/get?"
           "reportName=RPT_LICO_FN_CPD&columns=ALL&filter=(SECURITY_CODE%3D%22" + code +
           "%22)&pageNumber=1&pageSize=" + str(periods) +
           "&sortColumns=REPORTDATE&sortTypes=-1&source=HSF10&client=PC")
    j = _curl(url)
    if not j or not j.get("result") or not j["result"].get("data"):
        return {"ok": False, "error": "财务多期接口不可用", "source": "东方财富 F10"}
    rows = []
    for d in j["result"]["data"]:
        rows.append({
            "report": (d.get("REPORTDATE") or "")[:10],
            "eps": d.get("BASIC_EPS"), "roe": d.get("WEIGHTAVG_ROE"),
            "revenue": d.get("TOTAL_OPERATE_INCOME"), "net_profit": d.get("PARENT_NETPROFIT"),
            "revenue_yoy": round(d.get("YSTZ") or 0, 2),
            "profit_yoy": round(d.get("SJLTZ") or 0, 2),
            "bps": d.get("BPS"),
        })
    return {"ok": True, "rows": rows, "source": "东方财富 F10 多期", "as_of": _now()}


if __name__ == "__main__":
    for name, fn in [
        ("全球市场", fetch_global_markets), ("商品汇率", fetch_commodities_fx),
        ("两融", fetch_margin), ("北向", fetch_northbound),
        ("资金细分", lambda: fetch_flow_detail("1.600519")),
        ("财务多期", lambda: fetch_financials_history("600519")),
    ]:
        r = fn()
        rows = r.get("rows")
        print(f"{name}: ok={r.get('ok')} rows={len(rows) if rows else '-'} err={r.get('error','')}")
        if rows:
            print("   sample:", rows[0] if isinstance(rows[0], dict) else rows[:2])
