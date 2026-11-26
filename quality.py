# -*- coding: utf-8 -*-
"""
数据质检模块（改进版模板第 0 节）：先质检再出数。
每项输出 status: ok / warn / missing，warn 的模块不产生异动信号。
质检结果置顶展示，写明原因。
"""
from datetime import datetime


def _check(name, ok, reason, level="warn"):
    return {"name": name, "status": "ok" if ok else level, "reason": reason if not ok else ""}


def check(data):
    """返回质检清单 + 不通过模块集合。"""
    items = []

    # 1. 成交额口径（今日必须有；昨日可缺失）
    tv = data.get("turnover") or {}
    items.append(_check("两市成交额", bool(tv.get("ok") and tv.get("amount")),
                        "成交额接口未返回数据"))
    items.append(_check("昨日成交额对比", bool(tv.get("prev_amount")),
                        "日K历史接口未返回昨日值，放量/缩量标注为未知（不编造）", level="missing"))

    # 2. 涨停家数一致：概览数 vs 涨停池条数
    b = data.get("breadth") or {}
    ld = data.get("limit_up_detail") or {}
    b_up = b.get("limit_up")
    p_total = ld.get("total")
    if isinstance(b_up, (int, float)) and isinstance(p_total, (int, float)):
        same = abs(b_up - p_total) <= max(2, b_up * 0.1)
        items.append(_check("涨停家数一致", same,
                            f"概览 {b_up} vs 涨停池 {p_total}，口径可能不同"))
    else:
        items.append(_check("涨停家数一致", False, "缺少概览或涨停池条数", level="missing"))

    # 3. 价格量级校验：涨停池 vs 龙虎榜同名股票价格相差 5 倍以上
    lu_rows = (ld.get("ladder", {}).get(">=4", []) +
               ld.get("ladder", {}).get("3", [])) if ld.get("ok") else []
    dg_rows = (data.get("dragon") or {}).get("rows") or []
    lu_price = {r.get("name"): r.get("price") for r in lu_rows if r.get("price")}
    bad = []
    for d in dg_rows:
        nm, px = d.get("name"), d.get("close")
        if nm in lu_price and isinstance(px, (int, float)) and px > 0:
            if lu_price[nm] / px > 5 or px / lu_price[nm] > 5:
                bad.append(nm)
    items.append(_check("价格量级一致", not bad,
                        f"价格相差5倍以上：{'、'.join(bad)}" if bad else ""))

    # 4. K线完整：近 60 日不足则技术指标整块标缺失
    fc = data.get("focus") or {}
    kl = (fc.get("kline") or {}).get("rows") or []
    kline_ok = len(kl) >= 60
    items.append(_check("K线完整(≥60根)", kline_ok,
                        f"仅 {len(kl)} 根，技术指标整块标缺失、不显示空列", level="missing"))

    # 5. 北向量级：成交额低于 100 亿标口径存疑
    nb = data.get("northbound") or {}
    deal = nb.get("deal_amt")
    if isinstance(deal, (int, float)):
        items.append(_check("北向量级", deal >= 1000000,  # 万元口径，100亿=1,000,000万元
                            f"北向成交额 {deal:,.0f} 万元，量级存疑（仅成交额无方向，已降为备查）",
                            level="missing"))
    else:
        items.append(_check("北向量级", False, "北向数据不可用，已降为备查", level="missing"))

    # 6. 时点统一：各模块取数时间差超过 30 分钟
    times = []
    for key in ("breadth", "limit_up", "limit_up_detail", "limit_down",
                "sector_industry", "sector_industry_down", "turnover"):
        mod = data.get(key) or {}
        t = mod.get("as_of")
        if t:
            try:
                times.append(datetime.strptime(t, "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                pass
    if times:
        spread = (max(times) - min(times)).total_seconds() / 60
        items.append(_check("时点统一", spread <= 30,
                            f"各模块取数时间相差 {spread:.0f} 分钟", level="warn"))
    else:
        items.append(_check("时点统一", False, "无法校验取数时点", level="missing"))

    # 7. 财务期次一致（若有 focus）
    fin = fc.get("fin") or {}
    fhist = fc.get("fin_hist") or {}
    fr = fin.get("report_date")
    hr = (fhist.get("rows") or [{}])[0].get("report")
    if fr and hr:
        items.append(_check("财务期次一致", fr == hr, f"快照 {fr} vs 多期最新 {hr}"))

    # 不通过模块（warn 级别不产生信号；missing 同理）
    blocked = set()
    if not kline_ok:
        blocked.add("technical")
    if any(i["name"] == "涨停家数一致" and i["status"] != "ok" for i in items):
        blocked.add("limit_up")
    return {"items": items, "blocked": sorted(blocked),
            "n_warn": sum(1 for i in items if i["status"] == "warn"),
            "n_missing": sum(1 for i in items if i["status"] == "missing")}


def filter_signals(signals, qc):
    """质检未通过的模块不产生信号。"""
    blocked = set(qc.get("blocked", []))
    out = []
    for s in signals or []:
        stype = str(s.get("type", ""))
        if "technical" in blocked and any(k in stype for k in
                ("RSI", "MACD", "布林", "KDJ", "均线", "金叉", "死叉")):
            continue
        if "limit_up" in blocked and "涨停" in stype:
            continue
        out.append(s)
    return out
