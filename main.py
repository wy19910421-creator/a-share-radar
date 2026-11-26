# -*- coding: utf-8 -*-
"""
A 股投研辅助系统（全方位版） - 主入口
用法：python main.py [--mode pre|post]
  pre  = 盘前简报（隔夜全球市场 + 今日关注）
  post = 盘后简报（收盘复盘 + 资金面）
生成 output/投研看板_YYYYMMDD.html + 结构化 JSON
"""
import json
import sys
import time
from datetime import datetime

import config
import fetcher
import fetcher_ext as ext
import fetcher_deep as deep
import fetcher_extra as extra
import analyzer
import indicators
import reporter
import pusher
import quality


def _log(msg):
    print(msg, flush=True)


def collect(mode="post"):
    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "market_status": _market_status(),
        "mode": mode,
    }

    # 0. 深度数据（全球市场/商品汇率/两融/北向）
    _log(">> [0/13] 深度数据（全球市场/商品汇率/两融/北向）")
    data["global_markets"] = deep.fetch_global_markets()
    data["commodities_fx"] = deep.fetch_commodities_fx()
    data["margin"] = deep.fetch_margin()
    data["northbound"] = deep.fetch_northbound()
    time.sleep(0.2)

    # 1. 市场全景
    _log(">> [1/13] 市场全景（涨跌分布/涨停/多指数）")
    data["breadth"] = ext.fetch_market_breadth()
    data["limit_up"] = ext.fetch_limit_up_pool(8)
    data["indices_all"] = ext.fetch_more_indices()
    time.sleep(0.2)

    # 1b. 改进版模板新增维度
    _log(">> [1b/13] 成交额/跌停/炸板/梯队/昨日涨停/期指/国债/解禁/公告/宏观")
    data["turnover"] = extra.fetch_turnover()
    data["limit_down"] = extra.fetch_limit_down()
    data["broken_board"] = extra.fetch_broken_board()
    data["limit_up_detail"] = extra.fetch_limit_up_ladder()
    data["yesterday_perf"] = extra.fetch_yesterday_limit_up_perf()
    data["futures_basis"] = extra.fetch_index_futures()
    data["bond_yield"] = extra.fetch_bond_yield()
    data["unlock"] = extra.fetch_unlock_calendar(3)
    data["announcements"] = extra.fetch_curated_announcements(10)
    data["macro_news"] = extra.fetch_macro_news(6)
    data["sector_flow"] = {
        "industry_in": extra.fetch_sector_flow("industry", "in"),
        "industry_out": extra.fetch_sector_flow("industry", "out"),
    }
    time.sleep(0.2)

    # 2. 核心指数（结论卡用）
    _log(">> [2/13] 核心指数行情")
    indices = []
    for it in config.INDICES:
        q = fetcher.fetch_quote(it["secid"])
        k = fetcher.fetch_kline(it["secid"], 25)
        a = analyzer.analyze(it["secid"], it["name"], q, k)
        indices.append(a)
        time.sleep(0.2)
    data["indices"] = indices

    # 3. 板块轮动（涨/跌）
    _log(">> [3/13] 板块轮动（行业/概念，涨/跌）")
    data["sector_industry"] = ext.fetch_sectors("industry", 10)
    data["sector_industry_down"] = ext.fetch_sectors("industry", 8, po=0)
    data["sector_concept"] = ext.fetch_sectors("concept", 10)
    data["sector_concept_down"] = ext.fetch_sectors("concept", 8, po=0)
    time.sleep(0.3)

    # 4. 个股涨跌榜
    _log(">> [4/13] 个股涨跌榜")
    data["movers_up"] = ext.fetch_stock_movers("up", 8)
    data["movers_down"] = ext.fetch_stock_movers("down", 8)
    time.sleep(0.2)

    # 5. 龙虎榜
    _log(">> [5/13] 龙虎榜")
    data["dragon"] = ext.fetch_dragon_tiger(8)
    time.sleep(0.2)

    # 6. 行业重点新闻（券商研报 + 热点行业资讯）
    _log(">> [6/13] 行业重点新闻（券商研报 + 热点行业资讯）")
    data["industry_research"] = ext.fetch_industry_research(6)
    hot_names = [r.get("name") for r in (data["sector_industry"].get("rows") or [])[:2]]
    hot_names += [r.get("name") for r in (data["sector_industry_down"].get("rows") or [])[:1]]
    data["industry_news"] = ext.fetch_industry_news(hot_names, 2)
    time.sleep(0.2)

    # 7. 财经要闻
    _log(">> [7/13] 财经要闻")
    data["news"] = ext.fetch_news(8)
    time.sleep(0.2)

    # 8. 自选股深度
    _log(">> [8/13] 自选股深度（行情/技术/资金/财务）")
    watchlist, all_signals = [], []
    for a in indices:
        all_signals += a["signals"]
    for it in config.WATCHLIST:
        q = fetcher.fetch_quote(it["secid"])
        k = fetcher.fetch_kline(it["secid"], config.KLINE_DAYS)
        f = fetcher.fetch_fundflow(it["secid"])
        a = analyzer.analyze(it["secid"], it["name"], q, k)
        a["note"] = it.get("note", "")
        a["flow_pct"] = f.get("main_pct") if f.get("ok") else None
        a["flow_raw"] = f.get("main_net_raw") if f.get("ok") else None
        all_signals += a["signals"]
        all_signals += analyzer.analyze_flow(it["secid"], it["name"], f)

        # 技术指标
        if k.get("ok") and k.get("rows"):
            ind = indicators.compute(k["rows"])
            a["ind"] = ind
            ind_signals = indicators.signals(ind, it["name"])
            a["signals"] += ind_signals
            all_signals += ind_signals

        # 资金流细分 + 财务多期（ETF 跳过财务）
        code = it["code"]
        fd = deep.fetch_flow_detail(it["secid"])
        a["flow_detail"] = fd if fd.get("ok") else None
        if not code.startswith(("51", "15", "56", "58")):
            fin = ext.fetch_financials(code)
            a["fin"] = fin if fin.get("ok") else None
            fin_hist = deep.fetch_financials_history(code, 3)
            a["fin_hist"] = fin_hist if fin_hist.get("ok") else None
            time.sleep(0.15)

        watchlist.append(a)
        _log(f"   {it['name']}: {'OK' if q.get('ok') else 'FAIL'} pct={a['pct']} signals={len(a['signals'])}")
        time.sleep(0.2)
    data["watchlist"] = watchlist
    data["signals"] = all_signals

    # 9. 个股深度面板
    _log(">> [9/13] 个股深度面板")
    focus = None
    for it in config.WATCHLIST:
        if not it["code"].startswith(("51", "15", "56", "58")):
            focus = it
            break
    if focus:
        q = fetcher.fetch_quote(focus["secid"])
        k = fetcher.fetch_kline(focus["secid"], config.KLINE_DAYS)
        data["focus"] = {
            "name": focus["name"], "code": focus["code"],
            "quote": q, "kline": k,
            "ind": indicators.compute(k["rows"]) if k.get("ok") else {},
            "fin": ext.fetch_financials(focus["code"]),
            "fin_hist": deep.fetch_financials_history(focus["code"], 3),
            "flow": fetcher.fetch_fundflow(focus["secid"]),
            "flow_detail": deep.fetch_flow_detail(focus["secid"]),
        }

    # 10. 数据质检 + 信号过滤（先质检再出数）
    _log(">> [10/13] 数据质检 + 信号过滤")
    qc = quality.check(data)
    data["qc"] = qc
    data["signals"] = quality.filter_signals(data["signals"], qc)
    _log(f"   质检：{qc['n_warn']} 项警告 / {qc['n_missing']} 项缺失 · 信号 {len(data['signals'])} 条")
    return data


def _market_status():
    now = datetime.now()
    t = now.time()
    if now.weekday() >= 5:
        return "休市（周末）"
    from datetime import time as T
    if T(9, 30) <= t <= T(11, 30) or T(13, 0) <= t <= T(15, 0):
        return "盘中"
    if T(11, 30) < t < T(13, 0):
        return "午间休市"
    if t < T(9, 30):
        return "盘前"
    return "盘后"


def _parse_mode():
    """从命令行解析 --mode pre|post，默认按当前时间推断。"""
    if "--mode" in sys.argv:
        i = sys.argv.index("--mode")
        if i + 1 < len(sys.argv):
            m = sys.argv[i + 1].lower()
            if m in ("pre", "post"):
                return m
    # 默认：12 点前视为盘前，否则盘后
    return "pre" if datetime.now().hour < 12 else "post"


def main():
    mode = _parse_mode()
    label = "盘前简报" if mode == "pre" else "盘后简报"
    _log("=" * 64)
    _log(f"A 股投研辅助系统（全方位版） - {label}")
    _log("=" * 64)
    data = collect(mode)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = reporter.render(data)
    _log("=" * 64)
    _log(f"[完成] 看板已生成：{path}")
    _log(f"   指数 {len(data['indices'])} / 自选股 {len(data['watchlist'])} / 信号 {len(data['signals'])}")

    suffix = "盘前" if mode == "pre" else "盘后"
    jpath = config.OUTPUT_DIR / f"data_{datetime.now().strftime('%Y%m%d')}_{suffix}.json"
    jpath.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _log(f"   结构化数据：{jpath}")

    # 微信推送（盘前/盘后双模式简报）
    pusher.push(data, mode=mode)
    return path


if __name__ == "__main__":
    main()
