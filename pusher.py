# -*- coding: utf-8 -*-
"""
微信推送（改进版模板）：结论先行、涨跌对称、精选去噪。
盘前 = 隔夜全球 + 今日关注；盘后 = 收盘复盘 + 涨跌停 + 板块资金 + 精选公告。
渠道：pushplus / serverchan / wecom。curl 子进程 POST。
"""
import json
import subprocess
import sys

import config
import reporter as rp


def _mode_name(data):
    return "盘前简报" if data.get("mode") == "pre" else "盘后简报"


def _cut(s, n=40):
    s = str(s or "")
    return s if len(s) <= n else s[:n] + "…"


def _money(v):
    if v is None or v == "-":
        return ""
    try:
        return rp.fmt_num(float(v), "元")
    except (ValueError, TypeError):
        return ""


def _conclusion(data):
    """一句话结论（与看板一致）。"""
    idx = {a.get("name"): a.get("pct") for a in data.get("indices", [])}
    sh, cy = idx.get("上证指数"), idx.get("创业板指")
    b = data.get("breadth") or {}
    tv = data.get("turnover") or {}
    ld = data.get("limit_down") or {}
    lu = data.get("limit_up_detail") or {}
    tone = "中性"
    if b.get("ok"):
        up, down = b.get("up") or 0, b.get("down") or 0
        ratio = down / (up + down or 1)
        if ratio > 0.8 and (ld.get("total") or 0) > 100:
            tone = "急跌"
        elif up / (up + down or 1) > 0.65:
            tone = "强"
        elif ratio > 0.65:
            tone = "弱"
    amt = f"{rp.yi(tv.get('amount'))}万亿" if tv.get("ok") else "待补"
    if tv.get("chg_pct") is not None:
        amt += f"（{tv['state']} {rp.sign(tv['chg_pct'])}）"
    else:
        amt += "（昨日待补）"
    lu_n = lu.get("total") if lu.get("ok") else b.get("limit_up")
    ld_n = ld.get("total") if ld.get("ok") else b.get("limit_down")
    q = data.get("qc") or {}
    qtxt = f"质检 {q['n_warn']}警{q['n_missing']}缺。" if q else ""
    return (f"今日【{tone}】：上证 {rp.sign(sh)}，创业板 {rp.sign(cy)}；"
            f"涨 {b.get('up','—')}/跌 {b.get('down','—')}；成交 {amt}；"
            f"涨停 {lu_n if lu_n is not None else '—'}/跌停 {ld_n if ld_n is not None else '—'}。" + qtxt)


def _md_table(rows, cols, n=5):
    """rows: list of dict; cols: [(key,label)]"""
    if not rows:
        return "- 无数据"
    head = "| " + " | ".join(label for _, label in cols) + " |"
    sep = "|" + "|".join(["---"] * len(cols)) + "|"
    lines = [head, sep]
    for r in rows[:n]:
        cells = []
        for key, _ in cols:
            v = r.get(key)
            if key in ("pct", "change", "avg_pct"):
                cells.append(rp.sign(v))
            elif key in ("main_net", "amount", "cap", "net_amt", "fund"):
                cells.append(_money(v) or "—")
            else:
                cells.append(str(v) if v is not None else "—")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ---------- Markdown ----------

def build_markdown(data):
    mode = data.get("mode", "post")
    date = data["generated_at"][:10]
    L = [f"## A股投研{_mode_name(data)} {date}", f"> {_conclusion(data)}"]

    # 盘前：隔夜全球 + 商品汇率
    if mode == "pre":
        g = data.get("global_markets") or {}
        if g.get("ok") and g.get("rows"):
            L.append("\n**隔夜全球市场**")
            L.append(_md_table(g["rows"], [("name", "指数"), ("price", "点位"), ("pct", "涨跌")], 6))
        cf = data.get("commodities_fx") or {}
        if cf.get("ok") and cf.get("rows"):
            L.append("\n**商品/汇率**")
            L.append(_md_table(cf["rows"], [("name", "品种"), ("price", "价格"), ("pct", "涨跌")], 4))

    # 市场温度（涨跌对称核心）
    b = data.get("breadth") or {}
    tv = data.get("turnover") or {}
    lu = data.get("limit_up_detail") or {}
    ld = data.get("limit_down") or {}
    zb = data.get("broken_board") or {}
    ys = data.get("yesterday_perf") or {}
    mg = data.get("margin") or {}
    temp = []
    if b.get("ok"):
        temp.append(f"涨/跌 {b.get('up')}/{b.get('down')}")
    if tv.get("ok"):
        t = f"成交 {rp.yi(tv.get('amount'))}万亿"
        t += f"（昨日 {'待补' if not tv.get('prev_amount') else rp.yi(tv['prev_amount'])+'万亿'}，{tv.get('state')}）"
        temp.append(t)
    lu_n = lu.get("total") if lu.get("ok") else b.get("limit_up")
    ld_n = ld.get("total") if ld.get("ok") else b.get("limit_down")
    temp.append(f"涨停 {lu_n if lu_n is not None else '—'}/跌停 {ld_n if ld_n is not None else '—'}")
    if lu.get("ok"):
        temp.append(f"最高 {lu.get('max_height')}板")
    if zb.get("ok") and isinstance(lu_n, (int, float)):
        zb_n = zb.get("total") or 0
        temp.append(f"炸板率 {round(zb_n/(lu_n+zb_n)*100,1) if (lu_n+zb_n) else '—'}%")
    if ys.get("ok"):
        temp.append(f"昨涨停今均 {rp.sign(ys.get('avg_pct'))}")
    if mg.get("ok"):
        temp.append(f"融资余额 {rp.fmt_num(mg.get('rz_ye'),'元')}(T-1)")
    if temp:
        L.append("\n**市场温度（今日）**\n" + " · ".join(temp))

    # 板块：涨跌对称 + 资金双向
    iu = (data.get("sector_industry") or {}).get("rows") or []
    idn = (data.get("sector_industry_down") or {}).get("rows") or []
    sf = data.get("sector_flow") or {}
    fin = (sf.get("industry_in") or {}).get("rows") or []
    fout = (sf.get("industry_out") or {}).get("rows") or []
    if iu or idn:
        L.append("\n**行业板块（涨跌对称）**")
        if iu:
            L.append("领涨：" + "、".join(f"{r.get('name')} {rp.sign(r.get('pct'))}" for r in iu[:5]))
        if idn:
            L.append("领跌：" + "、".join(f"{r.get('name')} {rp.sign(r.get('pct'))}" for r in idn[:5]))
        if fin:
            L.append("资金流入：" + "、".join(f"{r.get('name')} {_money(r.get('main_net'))}" for r in fin[:5]))
        if fout:
            L.append("资金流出：" + "、".join(f"{r.get('name')} {_money(r.get('main_net'))}" for r in fout[:5]))

    # 涨停与跌停（对称）
    if lu.get("ok") or ld.get("ok"):
        L.append("\n**涨停 / 跌停**")
        if lu.get("ok"):
            ladder = lu.get("ladder") or {}
            hi = (ladder.get(">=4") or []) + (ladder.get("3") or [])
            L.append(f"涨停 {lu.get('total')} 只，最高 {lu.get('max_height')}板；"
                     f"≥4板 {len(ladder.get('>=4',[]))}、3板 {len(ladder.get('3',[]))}、2板 {len(ladder.get('2',[]))}")
            if hi:
                L.append("连板梯队：" + "、".join(f"{r.get('name')}({r.get('limit_count')}板)" for r in hi[:6]))
            by = lu.get("by_industry") or []
            if by:
                L.append("涨停行业：" + "、".join(f"{r.get('name')}{r.get('count')}家" for r in by[:5]))
        if ld.get("ok"):
            byd = ld.get("by_industry") or []
            tail = ("；集中行业：" + "、".join(f"{r.get('name')}{r.get('count')}家" for r in byd[:5])) if byd else ""
            L.append(f"跌停 {ld.get('total')} 家（非ST {ld.get('nonst_count')}/ST {ld.get('st_count')}）" + tail)

    # 期指基差（托底资金线索）
    fu = data.get("futures_basis") or {}
    if fu.get("ok") and fu.get("rows"):
        L.append("\n**股指期货基差（现货−期货）**")
        L.append("、".join(f"{r.get('name')} {r.get('state')}{r.get('basis')}点" for r in fu["rows"]))
        L.append("宽基ETF份额变动：接口未返回，数据缺失（不编造）")
    byield = data.get("bond_yield") or {}
    if not byield.get("ok"):
        L.append("10年期国债收益率：数据缺失（公开接口未返回）")

    # 盘后龙虎榜
    if mode == "post":
        dg = data.get("dragon") or {}
        if dg.get("ok") and dg.get("rows"):
            buys = sorted([r for r in dg["rows"] if (r.get("net_amt") or 0) > 0],
                          key=lambda x: -(x.get("net_amt") or 0))[:5]
            L.append("\n**龙虎榜净买前5**")
            L.append("、".join(f"{r.get('name')} {_money(r.get('net_amt'))}" for r in buys) if buys else "- 无净买入上榜")

    # 自选股（ETF 不显示主力净占比）
    wl = data.get("watchlist") or []
    if wl:
        L.append("\n**自选股**")
        bench = next((a.get("pct") for a in data.get("indices", []) if a.get("name") == "上证指数"), None)
        for a in wl:
            is_etf = str(a.get("code", "")).startswith(("51", "15", "56", "58"))
            rel = (a.get("pct") - bench) if (isinstance(a.get("pct"), (int, float)) and isinstance(bench, (int, float))) else None
            line = f"- {a.get('name')} {rp.sign(a.get('pct'))} 相对大盘 {rp.sign(rel)}"
            if not is_etf and a.get("flow_pct") is not None:
                line += f" 主力净占比 {rp.sign(a.get('flow_pct'))}"
            sigs = "、".join(s.get("type") or "" for s in a.get("signals", []))
            if sigs:
                line += f"｜信号：{sigs}"
            L.append(line)

    # 异动信号
    sig = data.get("signals") or []
    L.append(f"\n**异动信号（{len(sig)}）**")
    if sig:
        for s in sig[:10]:
            L.append(f"- [{s.get('type')}] {s.get('text')}")
    else:
        L.append("- 无（质检未通过的模块不产生信号）")

    # 精选公告 + 宏观消息
    ann = data.get("announcements") or {}
    if ann.get("ok") and ann.get("rows"):
        L.append("\n**公告精选**")
        for r in ann["rows"][:6]:
            L.append(f"- [{r.get('category')}] {r.get('name') or ''} {_cut(r.get('title'))}")
    macro = data.get("macro_news") or {}
    L.append("\n**可能相关的消息（政策/监管/宏观）**")
    if macro.get("ok") and macro.get("rows"):
        for r in macro["rows"][:5]:
            L.append(f"- {r.get('time','')} {_cut(r.get('title'))}")
    else:
        L.append("- 今日未检索到明确催化事件（不编造）")

    # 明日关注（解禁）
    ul = data.get("unlock") or {}
    if ul.get("ok") and ul.get("rows"):
        L.append("\n**明日关注 · 解禁**")
        def cap_txt(r):
            cap = r.get("cap")
            return rp.fmt_num(cap * 1e4 if isinstance(cap, (int, float)) else None, "元")
        L.append("、".join(f"{r.get('date')} {r.get('name')} {cap_txt(r)}" for r in ul["rows"][:4]))

    L.append("\n---\n客观数据监测，不预测方向、不构成投资建议。北向成交降为备查（仅成交额无方向）。市场有风险。")
    return "\n".join(L)


# ---------- HTML ----------

def _md_to_html(md):
    """把 markdown 简报转成微信 HTML（轻量转换）。"""
    out, in_ul = [], False
    for line in md.split("\n"):
        if line.startswith("## "):
            out.append(f'<h2 style="color:#1a73e8;font-size:19px">{rp.h(line[3:])}</h2>')
        elif line.startswith("> "):
            out.append(f'<p style="background:#f1f3f4;padding:8px 10px;border-radius:6px;font-size:13px;margin:6px 0">{rp.h(line[2:])}</p>')
        elif line.startswith("**") and line.endswith("**"):
            out.append(f'<h3 style="margin:14px 0 4px;font-size:15px;color:#1a73e8">{rp.h(line[2:-2])}</h3>')
        elif line.startswith("| "):
            if set(line.replace("|", "").replace("-", "").strip()) == set():
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            out.append('<div style="font-size:12px;color:#3c4043">' + " · ".join(rp.h(c) for c in cells) + '</div>')
        elif line.startswith("- "):
            if not in_ul:
                out.append("<ul style='margin:4px 0;padding-left:18px'>")
                in_ul = True
            out.append(f"<li style='font-size:13px'>{rp.h(line[2:])}</li>")
        elif line.strip() == "---":
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append('<hr style="border:none;border-top:1px solid #eceff1">')
        elif line.strip():
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f'<p style="font-size:13px;margin:4px 0">{rp.h(line)}</p>')
    if in_ul:
        out.append("</ul>")
    return "".join(out)


def build_html(data):
    md = build_markdown(data)
    return ('<div style="font-family:-apple-system,\'Microsoft YaHei\',sans-serif;'
            'color:#202124;line-height:1.65">' + _md_to_html(md) +
            '<p style="color:#9aa0a6;font-size:11px;margin-top:12px">'
            '数据来源：东方财富公开接口 · 红涨绿跌 · 市场有风险，投资需谨慎</p></div>')


# ---------- 发送 ----------

def _post(url, payload):
    body = json.dumps(payload, ensure_ascii=False)
    cmd = ["curl", "-s", "-m", "15", "-X", "POST",
           "-H", "Content-Type: application/json", "-d", body, url]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=18)
        out = r.stdout.decode("utf-8", "ignore").strip()
        return out[:500] if out else "(empty response)"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"


def send_pushplus(title, html, token):
    return _post("http://www.pushplus.plus/send",
                 {"token": token, "title": title, "content": html, "template": "html"})


def send_serverchan(title, markdown, key):
    return _post(f"https://sctapi.ftqq.com/{key}.send", {"title": title, "desp": markdown})


def send_wecom(markdown, webhook):
    return _post(webhook, {"msgtype": "markdown", "markdown": {"content": markdown}})


def push(data, mode=None, dry_run=False):
    cfg = config.PUSH
    if mode is None:
        mode = data.get("mode", "post")
    title = f"A股投研{_mode_name({'mode': mode})} {data['generated_at'][:10]}"
    d = {**data, "mode": mode}

    if dry_run:
        print(f"\n[DRY-RUN · {'盘前' if mode=='pre' else '盘后'}] 将推送以下内容（不实际发送）：")
        print("-" * 60)
        print(build_markdown(d))
        print("-" * 60)
        return {"ok": True, "dry_run": True}

    if not cfg.get("enabled"):
        print("[推送] 未启用（config.PUSH.enabled=False），跳过。")
        return {"ok": False, "reason": "disabled"}

    channel = cfg.get("channel", "pushplus")
    try:
        if channel == "pushplus":
            token = cfg.get("pushplus_token", "")
            if not token:
                return {"ok": False, "reason": "未配置 pushplus_token"}
            res = send_pushplus(title, build_html(d), token)
        elif channel == "serverchan":
            key = cfg.get("serverchan_key", "")
            if not key:
                return {"ok": False, "reason": "未配置 serverchan_key"}
            res = send_serverchan(title, build_markdown(d), key)
        elif channel == "wecom":
            webhook = cfg.get("wecom_webhook", "")
            if not webhook:
                return {"ok": False, "reason": "未配置 wecom_webhook"}
            res = send_wecom(build_markdown(d), webhook)
        else:
            return {"ok": False, "reason": f"未知渠道 {channel}"}
        print(f"[推送] 渠道={channel} 模式={'盘前' if mode=='pre' else '盘后'} 返回：{res}")
        return {"ok": True, "channel": channel, "mode": mode, "response": res}
    except Exception as e:  # noqa: BLE001
        print(f"[推送] 失败：{type(e).__name__}: {e}")
        return {"ok": False, "reason": str(e)}


if __name__ == "__main__":
    from pathlib import Path
    files = sorted(config.OUTPUT_DIR.glob("data_*.json"))
    if not files:
        print("没有找到 data_*.json，请先运行 python main.py")
        sys.exit(1)
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    send = "--send" in sys.argv
    mode = "pre" if "--pre" in sys.argv else ("post" if "--post" in sys.argv else data.get("mode", "post"))
    result = push(data, mode=mode, dry_run=not send)
    print("结果：", result)
