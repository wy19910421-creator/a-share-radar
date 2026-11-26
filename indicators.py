# -*- coding: utf-8 -*-
"""
技术指标计算：MA / EMA / MACD / RSI / 布林带 / ATR / KDJ。
纯标准库，输入为 fetcher.fetch_kline 的 rows（按日期升序）。
"""

def _ema(vals, n):
    if not vals:
        return []
    k = 2 / (n + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def compute(rows):
    """返回完整技术指标 dict，数据不足时对应字段为 None。"""
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    vols = [r["volume"] for r in rows]
    n = len(closes)
    res = {}

    def avg(seq, w):
        return round(sum(seq[-w:]) / w, 3) if len(seq) >= w else None

    res["ma5"], res["ma10"], res["ma20"], res["ma60"] = (
        avg(closes, 5), avg(closes, 10), avg(closes, 20), avg(closes, 60))
    res["vol_ma5"] = avg(vols, 5)

    # MACD (12,26,9)
    if n >= 26:
        ema12, ema26 = _ema(closes, 12), _ema(closes, 26)
        dif = [a - b for a, b in zip(ema12, ema26)]
        dea = _ema(dif, 9)
        macd_bar = [(a - b) * 2 for a, b in zip(dif, dea)]
        res["dif"] = round(dif[-1], 3)
        res["dea"] = round(dea[-1], 3)
        res["macd"] = round(macd_bar[-1], 3)
        res["macd_prev"] = round(macd_bar[-2], 3) if n >= 27 else None
    else:
        res["dif"] = res["dea"] = res["macd"] = res["macd_prev"] = None

    # RSI(14)
    if n >= 15:
        gains, losses = [], []
        for i in range(1, n):
            ch = closes[i] - closes[i - 1]
            gains.append(max(ch, 0))
            losses.append(max(-ch, 0))
        ag, al = sum(gains[:14]) / 14, sum(losses[:14]) / 14
        for i in range(14, len(gains)):
            ag = (ag * 13 + gains[i]) / 14
            al = (al * 13 + losses[i]) / 14
        res["rsi14"] = round(100 if al == 0 else 100 - 100 / (1 + ag / al), 2)
    else:
        res["rsi14"] = None

    # 布林带(20,2)
    if n >= 20:
        mid = sum(closes[-20:]) / 20
        var = sum((c - mid) ** 2 for c in closes[-20:]) / 20
        sd = var ** 0.5
        res["boll_mid"] = round(mid, 3)
        res["boll_up"] = round(mid + 2 * sd, 3)
        res["boll_low"] = round(mid - 2 * sd, 3)
        price = closes[-1]
        res["boll_pos"] = round((price - res["boll_low"]) / ((res["boll_up"] - res["boll_low"]) or 1), 3)
    else:
        res["boll_mid"] = res["boll_up"] = res["boll_low"] = res["boll_pos"] = None

    # ATR(14)
    if n >= 15:
        trs = []
        for i in range(1, n):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            trs.append(tr)
        res["atr14"] = round(sum(trs[-14:]) / 14, 3)
        res["atr_pct"] = round(res["atr14"] / closes[-1] * 100, 2) if closes[-1] else None
    else:
        res["atr14"] = res["atr_pct"] = None

    # KDJ(9,3,3)
    if n >= 9:
        rsv = []
        for i in range(8, n):
            hh, ll = max(highs[i - 8:i + 1]), min(lows[i - 8:i + 1])
            rsv.append((closes[i] - ll) / ((hh - ll) or 1) * 100)
        k, d = 50.0, 50.0
        for v in rsv:
            k = (2 * k + v) / 3
            d = (2 * d + k) / 3
        res["k"], res["d"], res["j"] = round(k, 2), round(d, 2), round(3 * k - 2 * d, 2)
    else:
        res["k"] = res["d"] = res["j"] = None

    res["last_close"] = closes[-1] if closes else None
    return res


def signals(ind, name):
    """把指标转成客观信号文本（不预测方向，只描述状态）。"""
    out = []
    if ind.get("rsi14") is not None:
        r = ind["rsi14"]
        if r >= 70:
            out.append({"level": "warn", "type": "RSI", "text": f"{name} RSI(14)={r}，处于超买区(≥70)"})
        elif r <= 30:
            out.append({"level": "warn", "type": "RSI", "text": f"{name} RSI(14)={r}，处于超卖区(≤30)"})
    if ind.get("macd") is not None and ind.get("macd_prev") is not None:
        if ind["macd_prev"] <= 0 < ind["macd"]:
            out.append({"level": "info", "type": "MACD", "text": f"{name} MACD 柱状由负转正（DIF={ind['dif']}, DEA={ind['dea']}）"})
        elif ind["macd_prev"] >= 0 > ind["macd"]:
            out.append({"level": "info", "type": "MACD", "text": f"{name} MACD 柱状由正转负（DIF={ind['dif']}, DEA={ind['dea']}）"})
    if ind.get("boll_pos") is not None:
        p = ind["boll_pos"]
        if p >= 1:
            out.append({"level": "warn", "type": "布林带", "text": f"{name} 收盘触及布林上轨({ind['boll_up']})"})
        elif p <= 0:
            out.append({"level": "warn", "type": "布林带", "text": f"{name} 收盘触及布林下轨({ind['boll_low']})"})
    if ind.get("j") is not None:
        if ind["j"] >= 100:
            out.append({"level": "info", "type": "KDJ", "text": f"{name} J值={ind['j']}，高位"})
        elif ind["j"] <= 0:
            out.append({"level": "info", "type": "KDJ", "text": f"{name} J值={ind['j']}，低位"})
    return out


if __name__ == "__main__":
    import fetcher
    k = fetcher.fetch_kline("1.600519", 60)
    ind = compute(k["rows"])
    for key in ("ma5", "ma20", "dif", "dea", "macd", "rsi14", "boll_up", "boll_low", "atr14", "k", "d", "j"):
        print(f"{key}: {ind.get(key)}")
    print("signals:", signals(ind, "贵州茅台"))
