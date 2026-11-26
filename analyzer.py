# -*- coding: utf-8 -*-
"""
分析与告警模块：基于 K 线计算技术指标，按 config.ALERT 规则生成结构化信号。
只输出"信号/提醒"，不输出买卖建议——决策权在用户。
"""
import config


def ma(rows, n):
    if len(rows) < n:
        return None
    return round(sum(r["close"] for r in rows[-n:]) / n, 3)


def analyze(secid, name, quote, kline):
    """返回单个标的的分析结果 + 告警信号列表。"""
    signals = []
    rows = kline.get("rows", []) if kline.get("ok") else []

    ma5, ma10, ma20 = ma(rows, 5), ma(rows, 10), ma(rows, 20)
    vol5 = sum(r["volume"] for r in rows[-6:-1]) / 5 if len(rows) >= 6 else None
    today_vol = rows[-1]["volume"] if rows else None
    vol_ratio = round(today_vol / vol5, 2) if vol5 and today_vol else None

    pct = quote.get("pct") if quote.get("ok") else None

    # 规则1：单日涨跌幅异动
    if pct is not None and abs(pct) >= config.ALERT["pct_change"]:
        direction = "大涨" if pct > 0 else "大跌"
        signals.append({
            "level": "warn", "type": "涨跌幅异动",
            "text": f"{name} {direction} {abs(pct):.2f}%（阈值±{config.ALERT['pct_change']}%）",
        })

    # 规则2：量能异动
    if vol_ratio is not None and vol_ratio >= config.ALERT["vol_ratio"]:
        signals.append({
            "level": "warn", "type": "放量",
            "text": f"{name} 量比 {vol_ratio}（今日量/过去5日均量，阈值{config.ALERT['vol_ratio']}）",
        })

    # 规则3：均线金叉/死叉（用最近两日 MA5 与 MA20 关系判断）
    if config.ALERT["ma_cross"] and len(rows) >= 21:
        prev = rows[-2]
        prev_rows = rows[:-1]
        ma5_prev = ma(prev_rows, 5)
        ma20_prev = ma(prev_rows, 20)
        if ma5 and ma20 and ma5_prev and ma20_prev:
            if ma5_prev <= ma20_prev and ma5 > ma20:
                signals.append({"level": "info", "type": "均线金叉", "text": f"{name} MA5 上穿 MA20"})
            if ma5_prev >= ma20_prev and ma5 < ma20:
                signals.append({"level": "info", "type": "均线死叉", "text": f"{name} MA5 下穿 MA20"})

    # 规则4：资金流（净占比口径，规避原始值单位歧义）
    flow_pct = None
    return {
        "secid": secid, "name": name,
        "code": quote.get("code") or kline.get("code"),
        "price": quote.get("price"), "pct": pct,
        "ma5": ma5, "ma10": ma10, "ma20": ma20,
        "vol_ratio": vol_ratio,
        "quote_ok": quote.get("ok", False),
        "kline_ok": kline.get("ok", False),
        "as_of": quote.get("as_of") or kline.get("as_of"),
        "signals": signals,
    }


def analyze_flow(secid, name, flow):
    """资金流信号（基于净占比，单位口径清晰）。"""
    sig = []
    if flow.get("ok") and flow.get("main_pct") is not None:
        p = flow["main_pct"]
        if abs(p) >= 3:
            level = "warn" if abs(p) >= 5 else "info"
            sig.append({
                "level": level, "type": "资金流",
                "text": f"{name} 主力净占比 {p:+.2f}%",
            })
    return sig
