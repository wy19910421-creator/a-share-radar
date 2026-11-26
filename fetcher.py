# -*- coding: utf-8 -*-
"""
数据抓取模块：东方财富公开行情接口，纯标准库实现。
每个返回都带 source（来源）与 as_of（数据时点），符合溯源要求。
"""
import json
import urllib.parse
import subprocess
import time
from datetime import datetime

import config


def _get(url, params):
    """
    带重试的 GET，返回解析后的 dict。
    用 curl 子进程而非 urllib：实测本机 urllib 的 TLS 握手会被东方财富断开，
    curl 正常。curl 为系统自带，零第三方依赖。
    """
    full = url + "?" + urllib.parse.urlencode(params)
    cmd = ["curl", "-s", "-m", str(config.TIMEOUT), "-A", config.HEADERS["User-Agent"], full]
    last_err = None
    for i in range(config.RETRY + 1):
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=config.TIMEOUT + 3)
            text = out.stdout.decode("utf-8", "ignore").strip()
            if text:
                return json.loads(text)
            last_err = RuntimeError("empty response")
        except Exception as e:  # noqa: BLE001
            last_err = e
        if i < config.RETRY:
            time.sleep(0.6)
    return {"rc": -1, "error": f"{type(last_err).__name__}: {last_err}"}


def _f(num, default=0.0, scale=100.0):
    """东方财富价格字段按 scale 缩放，无效值返回 default。"""
    try:
        if num in (None, "-", ""):
            return default
        return round(float(num) / scale, 2)
    except (ValueError, TypeError):
        return default


def fetch_quote(secid):
    """实时行情快照。"""
    fields = "f43,f44,f45,f46,f47,f48,f57,f58,f60,f86,f168,f169,f170,f116,f117,f162,f167"
    raw = _get(config.API_QUOTE, {"secid": secid, "fields": fields})
    data = raw.get("data")
    if not data:
        return {"ok": False, "error": raw.get("error", "no data"), "secid": secid}
    ts = data.get("f86")
    def fmt_ts(v):
        try:
            v = int(v)
            if v > 1e12:      # 毫秒
                v = v / 1000
            return datetime.fromtimestamp(v).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError, OSError):
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    as_of = fmt_ts(ts) if ts else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "ok": True,
        "secid": secid,
        "code": data.get("f57"),
        "name": data.get("f58"),
        "price": _f(data.get("f43")),
        "high": _f(data.get("f44")),
        "low": _f(data.get("f45")),
        "open": _f(data.get("f46")),
        "prev_close": _f(data.get("f60")),
        "change": _f(data.get("f169")),
        "pct": _f(data.get("f170")),
        "turnover_rate": _f(data.get("f168")),
        "volume_hand": data.get("f47"),          # 手
        "amount": data.get("f48"),               # 元
        "mkt_cap": data.get("f116"),             # 总市值
        "float_cap": data.get("f117"),           # 流通市值
        "pe_ttm": _f(data.get("f162")),
        "pb": _f(data.get("f167")),
        "source": "东方财富 push2 实时行情",
        "as_of": as_of,
    }


def fetch_kline(secid, days=None):
    """日 K 线（前复权），返回按日期升序的列表。"""
    days = days or config.KLINE_DAYS
    params = {
        "secid": secid,
        "klt": "101",
        "fqt": "1",
        "beg": "0",
        "end": "20500101",
        "lmt": str(days),
        "_": str(int(time.time() * 1000)),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    raw = _get(config.API_KLINE, params)
    data = raw.get("data")
    if not data or not data.get("klines"):
        return {"ok": False, "error": raw.get("error", "no kline"), "secid": secid}
    rows = []
    for line in data["klines"]:
        p = line.split(",")
        try:
            rows.append({
                "date": p[0], "open": float(p[1]), "close": float(p[2]),
                "high": float(p[3]), "low": float(p[4]),
                "volume": float(p[5]), "amount": float(p[6]),
                "amplitude": float(p[7]), "pct": float(p[8]),
                "change": float(p[9]), "turnover": float(p[10]),
            })
        except (ValueError, IndexError):
            continue
    rows = rows[-days:]  # lmt 未必生效，显式截取最近 N 条
    return {
        "ok": True, "secid": secid, "code": data.get("code"), "name": data.get("name"),
        "rows": rows, "source": "东方财富 push2his 日K(前复权)",
        "as_of": rows[-1]["date"] if rows else datetime.now().strftime("%Y-%m-%d"),
    }


def fetch_fundflow(secid):
    """主力资金流向（当日，单位：元）。字段：f62 主力净流入, f184 主力净占比。"""
    fields = "f62,f184,f66,f69,f72,f75,f78,f81,f84,f87"
    raw = _get(config.API_QUOTE, {"secid": secid, "fields": fields})
    data = raw.get("data")
    if not data:
        return {"ok": False, "error": raw.get("error", "no data"), "secid": secid}
    def yuan(v):
        try:
            return None if v in (None, "-", "") else float(v)
        except (ValueError, TypeError):
            return None
    return {
        "ok": True, "secid": secid,
        "main_net_raw": yuan(data.get("f62")),      # 接口原值（口径以东方财富为准，单位可能为万元）
        "main_pct": yuan(data.get("f184")),         # 主力净占比（%）
        "source": "东方财富 push2 资金流（原始值，单位口径以数据源为准）",
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    print(json.dumps(fetch_quote("1.000001"), ensure_ascii=False, indent=2))
    k = fetch_kline("1.600519", 10)
    print("kline rows:", len(k.get("rows", [])), "last:", k.get("rows", [{}])[-1] if k.get("ok") else k.get("error"))
    print(json.dumps(fetch_fundflow("1.600519"), ensure_ascii=False, indent=2))
