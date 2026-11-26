# -*- coding: utf-8 -*-
"""
A股投研日报（改进版模板）看板渲染。
三层结构：必看（第一屏）/ 选看 / 备查（默认折叠）。
结论先行、涨跌对称、质检前置标灰、所有数据标注时点、红涨绿跌。
纯 HTML/CSS + 内联 SVG，离线可看。
"""
import config
import quality


# ---------- 通用辅助 ----------

def h(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def color(pct):
    if pct is None:
        return "#5f6368"
    try:
        pct = float(pct)
    except (ValueError, TypeError):
        return "#5f6368"
    return "#d93025" if pct > 0 else ("#137333" if pct < 0 else "#5f6368")


def sign(pct, suffix="%"):
    if pct is None:
        return "—"
    try:
        return f"{float(pct):+.2f}{suffix}"
    except (ValueError, TypeError):
        return "—"


def fmt_num(v, unit=""):
    if v is None:
        return "—"
    try:
        v = float(v)
    except (ValueError, TypeError):
        return h(v)
    if abs(v) >= 1e12:
        return f"{v/1e12:.2f}万亿{unit}"
    if abs(v) >= 1e8:
        return f"{v/1e8:.2f}亿{unit}"
    if abs(v) >= 1e4:
        return f"{v/1e4:.2f}万{unit}"
    return f"{v:.2f}{unit}" if v % 1 else f"{int(v)}{unit}"


def yi(v):
    """元 -> 万亿元（用于两市成交额展示）。"""
    try:
        return f"{float(v)/1e12:.2f}"
    except (ValueError, TypeError):
        return "—"


def badge(text, cls="info"):
    return f'<span class="badge {cls}">{h(text)}</span>'


def empty(msg):
    return f'<div class="empty">{h(msg)}</div>'


def src(text):
    return f'<p class="src">{h(text)}</p>'


# ---------- SVG K线 ----------

def candlestick_svg(rows, w=1000, hgt=260):
    if not rows or len(rows) < 5:
        return empty("K线数据不足（少于5根）")
    rows = rows[-60:]
    n = len(rows)
    vol_h = 50
    price_h = hgt - vol_h - 24
    pad_t, pad_b = 8, 4
    lo = min(r["low"] for r in rows)
    hi = max(r["high"] for r in rows)
    rng = (hi - lo) or 1
    vmax = max(r["volume"] for r in rows) or 1
    cw = w / n
    body_w = max(cw * 0.62, 1.5)

    def x(i):
        return i * cw + cw / 2

    def y(p):
        return pad_t + (hi - p) / rng * (price_h - pad_t - pad_b)

    parts = [f'<svg viewBox="0 0 {w} {hgt}" width="100%" height="{hgt}" preserveAspectRatio="xMidYMid meet" style="background:#fff">']
    for g in range(5):
        gy = pad_t + g * (price_h - pad_t - pad_b) / 4
        gv = hi - g * rng / 4
        parts.append(f'<line x1="0" y1="{gy:.1f}" x2="{w}" y2="{gy:.1f}" stroke="#eceff1" stroke-width="1"/>')
        parts.append(f'<text x="{w-2}" y="{gy-3:.1f}" font-size="10" fill="#9aa0a6" text-anchor="end">{gv:.2f}</text>')
    for i, r in enumerate(rows):
        up = r["close"] >= r["open"]
        col = "#d93025" if up else "#137333"
        cx = x(i)
        parts.append(f'<line x1="{cx:.1f}" y1="{y(r["high"]):.1f}" x2="{cx:.1f}" y2="{y(r["low"]):.1f}" stroke="{col}" stroke-width="1"/>')
        yo, yc = y(r["open"]), y(r["close"])
        top, bot = min(yo, yc), max(yo, yc)
        bh = max(bot - top, 1.5)
        parts.append(f'<rect x="{cx-body_w/2:.1f}" y="{top:.1f}" width="{body_w:.1f}" height="{bh:.1f}" fill="{col}"/>')
        vh = r["volume"] / vmax * (vol_h - 6)
        parts.append(f'<rect x="{cx-body_w/2:.1f}" y="{price_h+2:.1f}" width="{body_w:.1f}" height="{vh:.1f}" fill="{col}" opacity="0.55"/>')
    parts.append(f'<line x1="0" y1="{price_h}" x2="{w}" y2="{price_h}" stroke="#dadce0" stroke-width="1"/>')
    for idx in (0, n // 2, n - 1):
        parts.append(f'<text x="{x(idx):.1f}" y="{hgt-4}" font-size="9" fill="#9aa0a6" text-anchor="middle">{h(rows[idx]["date"])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def breadth_bar(b):
    if not b or not b.get("ok"):
        return empty("涨跌分布数据不可用")
    up, down, flat = b.get("up", 0), b.get("down", 0), b.get("flat", 0)
    total = up + down + flat or 1
    uw, fw, dw = up / total * 100, flat / total * 100, down / total * 100
    return (f'<div class="breadth-bar">'
            f'<div class="seg up" style="width:{uw:.1f}%" title="上涨 {up}"></div>'
            f'<div class="seg flat" style="width:{fw:.1f}%" title="平盘 {flat}"></div>'
            f'<div class="seg down" style="width:{dw:.1f}%" title="下跌 {down}"></div>'
            f'</div>')


# ---------- 0. 质检 ----------

def qc_block(data):
    qc = data.get("qc") or {}
    items = qc.get("items") or []
    if not items:
        return ""
    parts = ['<div class="qc"><div class="qc-title">数据质检（先质检再出数）</div><div class="qc-items">']
    for it in items:
        st = it.get("status")
        mark = "✅" if st == "ok" else ("⚠️" if st == "warn" else "⬜")
        cls = "qc-ok" if st == "ok" else ("qc-warn" if st == "warn" else "qc-miss")
        reason = (" · " + h(it.get("reason"))) if it.get("reason") else ""
        parts.append(f'<span class="{cls}">{mark} {h(it.get("name"))}{reason}</span>')
    parts.append("</div></div>")
    return "".join(parts)


# ---------- 1. 一句话结论 ----------

def _tone(data):
    """按模板档位判定行情性质。"""
    b = data.get("breadth") or {}
    if not b.get("ok"):
        return "中性", "#5f6368"
    up, down = b.get("up") or 0, b.get("down") or 0
    ld = b.get("limit_down") or 0
    total = up + down or 1
    down_ratio = down / total
    up_ratio = up / total
    if down_ratio > 0.8 and ld > 100:
        return "急跌", "#c5221f"
    if up_ratio > 0.65:
        return "强", "#d93025"
    if down_ratio > 0.65:
        return "弱", "#137333"
    return "中性", "#5f6368"


def tldr(data):
    idx = {a.get("name"): a.get("pct") for a in data.get("indices", [])}
    sh = idx.get("上证指数")
    cy = idx.get("创业板指")
    kc = None
    allrows = (data.get("indices_all") or {}).get("rows") or []
    for r in allrows:
        if r.get("name") == "科创50":
            kc = r.get("pct")
    if kc is None:
        for r in allrows:
            if r.get("code") == "000688":
                kc = r.get("pct")
    b = data.get("breadth") or {}
    tv = data.get("turnover") or {}
    ld = data.get("limit_down") or {}
    tone, tcol = _tone(data)
    amt_txt = f"{yi(tv.get('amount'))}万亿" if tv.get("ok") else "待补"
    if tv.get("chg_pct") is not None:
        amt_txt += f"（较昨日 {sign(tv.get('chg_pct'))}，{tv.get('state')}）"
    else:
        amt_txt += "（昨日值待补）"
    lu_n = (data.get("limit_up_detail") or {}).get("total")
    if lu_n is None:
        lu_n = b.get("limit_up")
    ld_n = ld.get("total") if ld.get("ok") else b.get("limit_down")

    # 最大特征（客观描述）
    feats = []
    if isinstance(sh, (int, float)) and isinstance(cy, (int, float)) and cy < sh - 1:
        feats.append("小盘成长跌幅明显大于大盘权重")
    if isinstance(kc, (int, float)) and kc < -3:
        feats.append("科创50显著走弱")
    top_up = ((data.get("sector_industry") or {}).get("rows") or [])[:2]
    if top_up:
        feats.append("防御型板块（" + "、".join(h(r.get("name")) for r in top_up) + "）逆势居前")
    if ld.get("ok") and ld.get("total", 0) > 30:
        feats.append(f"跌停 {ld.get('total')} 家，小市值个股承压")
    feature = "；".join(feats) if feats else "板块涨跌分化，个股涨少跌多"

    line = (f"今日【{tone}】：上证 {sign(sh)}，创业板 {sign(cy)}，科创50 {sign(kc)}；"
            f"上涨 {b.get('up','—')} 家 / 下跌 {b.get('down','—')} 家；"
            f"两市成交额 {amt_txt}；涨停 {lu_n if lu_n is not None else '—'} / "
            f"跌停 {ld_n if ld_n is not None else '—'}；最大特征：{feature}。")
    return f"""
    <div class="tldr">
      <h2>一句话结论 · 必看</h2>
      <div class="tone" style="color:{tcol}">今日行情性质：{tone}</div>
      <p class="concl">{line}</p>
      {breadth_bar(b) if b.get('ok') else ''}
      <p class="disc">客观描述、不预测方向；所有数据标注时点，T-1 数据单独注明。</p>
    </div>"""


# ---------- 2. 市场温度（今日/昨日/变化） ----------

def temperature_block(data):
    b = data.get("breadth") or {}
    tv = data.get("turnover") or {}
    mg = data.get("margin") or {}
    lu = data.get("limit_up_detail") or {}
    ld = data.get("limit_down") or {}
    zb = data.get("broken_board") or {}
    yst = data.get("yesterday_perf") or {}

    lu_n = lu.get("total") if lu.get("ok") else b.get("limit_up")
    ld_n = ld.get("total") if ld.get("ok") else b.get("limit_down")
    lu_total = lu_n if isinstance(lu_n, (int, float)) else 0
    zb_n = zb.get("total") if zb.get("ok") else 0
    burst = round(zb_n / (lu_total + zb_n) * 100, 1) if (lu_total + zb_n) else None
    max_h = lu.get("max_height") if lu.get("ok") else None
    yavg = yst.get("avg_pct") if yst.get("ok") else None

    # 昨日列：多数接口无历史，按模板标注 T-1 或待补
    def row(name, today, yesterday, note=""):
        nt = h(note)
        return f'<tr><td class="metric">{h(name)}{f"<div class=\"sub\">{nt}</div>" if nt else ""}</td>' \
               f'<td>{today}</td><td>{yesterday}</td><td>{h("—")}</td></tr>'

    rows = []
    rows.append(row("上涨 / 下跌家数",
                    f'{b.get("up","—")} / {b.get("down","—")}' if b.get("ok") else "—",
                    "待补"))
    rows.append(row("涨停 / 跌停家数",
                    f'{lu_n if lu_n is not None else "—"} / {ld_n if ld_n is not None else "—"}',
                    "待补"))
    rows.append(row("炸板率", f"{burst}%" if burst is not None else "—", "待补",
                    f"炸板 {zb_n} / 涨停+炸板 {lu_total+zb_n}"))
    rows.append(row("连板最高高度", f"{max_h}板" if max_h else "—", "待补"))
    rows.append(row("昨日涨停股今日平均涨幅",
                    sign(yavg) if yavg is not None else '<span class="miss-tag">数据缺失</span>',
                    "—",
                    "接口未返回昨日涨停池" if yst.get("ok") is False else ""))
    amt = f"{yi(tv.get('amount'))}万亿" if tv.get("ok") else "—"
    if tv.get("chg_pct") is not None:
        amt += f' <span style="color:{color(tv.get("chg_pct"))}">({sign(tv.get("chg_pct"))})</span>'
    rows.append(row("两市成交额", amt,
                    f'{yi(tv.get("prev_amount"))}万亿' if tv.get("prev_amount") else '<span class="miss-tag">待补</span>',
                    tv.get("state", "")))
    rz = f'{fmt_num(mg.get("rz_ye"),"元")} / {sign(mg.get("rz_jme"))}' if mg.get("ok") else "—"
    rows.append(row("融资余额及净买入", rz, "待补", f'T-1 · {mg.get("date","")}'))

    head = ('<table><thead><tr><th>指标</th><th>今日</th><th>昨日（T-1）</th>'
            '<th>变化</th></tr></thead><tbody>')
    return head + "".join(rows) + "</tbody></table>" + \
        src("来源：东方财富 push2 / push2ex / 数据中心 · 取数 " + h(data.get("generated_at", "")) +
            " · 昨日列多数接口无历史值，标待补，不编造")


# ---------- 3. 指数与风格 ----------

def index_style_block(data):
    rows = (data.get("indices_all") or {}).get("rows") or []
    if not rows:
        rows = [{"name": a.get("name"), "price": a.get("price"), "pct": a.get("pct")}
                for a in data.get("indices", [])]
    tv = data.get("turnover") or {}
    out = ['<table><thead><tr><th>指数</th><th>点位</th><th>涨跌幅</th><th>成交额</th></tr></thead><tbody>']
    for r in rows:
        c = color(r.get("pct"))
        amt = fmt_num(r.get("amount"), "元") if r.get("amount") else "—"
        out.append(f'<tr><td class="nm">{h(r.get("name"))} <span class="code">{h(r.get("code") or "")}</span></td>'
                   f'<td style="color:{c}">{r.get("price") if r.get("price") is not None else "—"}</td>'
                   f'<td style="color:{c};font-weight:600">{sign(r.get("pct"))}</td>'
                   f'<td>{amt}</td></tr>')
    out.append("</tbody></table>")

    # 风格对比（纯数据）
    pmap = {r.get("name"): r.get("pct") for r in rows}

    def avg(names):
        vals = [pmap[n] for n in names if isinstance(pmap.get(n), (int, float))]
        return sum(vals) / len(vals) if vals else None

    big = avg(["上证50", "沪深300"])
    small = avg(["中证500", "中小100"])
    growth = avg(["创业板指", "科创50"])
    gap = (growth - big) if (growth is not None and big is not None) else None
    sty = (f'<div class="style-grid">'
           f'<div class="mini"><div class="ml">大盘（上证50/沪深300）</div><div class="mv" style="color:{color(big)}">{sign(big)}</div></div>'
           f'<div class="mini"><div class="ml">小盘（中证500/中小100）</div><div class="mv" style="color:{color(small)}">{sign(small)}</div></div>'
           f'<div class="mini"><div class="ml">成长（创业板/科创50）</div><div class="mv" style="color:{color(growth)}">{sign(growth)}</div></div>'
           f'<div class="mini"><div class="ml">成长 − 大盘</div><div class="mv" style="color:{color(gap)}">{sign(gap)} 个百分点</div></div>'
           f'</div>')
    return "".join(out) + '<h3 style="margin-top:16px">风格对比（纯数据）</h3>' + sty + \
        src("指数点位与涨跌幅为收盘值；成交额口径以东方财富为准 · 时点 " + h(data.get("generated_at", "")))


# ---------- 4. 板块四表（涨跌对称 + 资金双向） ----------

def _sector_table(rows, kind="pct", limit=5):
    if not rows:
        return empty("无数据")
    out = ['<table class="compact"><thead><tr><th>板块</th><th>涨跌</th><th>主力净额</th><th>成交额</th><th>领涨股</th></tr></thead><tbody>']
    for r in rows[:limit]:
        c = color(r.get("pct"))
        dv = ""
        if r.get("diverge"):
            dv = f' <span class="diverge" title="{h(r["diverge"])}">⚠️</span>'
        out.append(f'<tr><td class="nm">{h(r.get("name"))}{dv}</td>'
                   f'<td style="color:{c}">{sign(r.get("pct"))}</td>'
                   f'<td style="color:{color(r.get("main_net"))}">{fmt_num(r.get("main_net"),"元")}</td>'
                   f'<td>{fmt_num(r.get("amount"),"元")}</td>'
                   f'<td>{h(r.get("leader") or "—")}</td></tr>')
    out.append("</tbody></table>")
    return "".join(out)


def sector_block(data):
    ind_up = (data.get("sector_industry") or {}).get("rows") or []
    ind_dn = (data.get("sector_industry_down") or {}).get("rows") or []
    con_up = (data.get("sector_concept") or {}).get("rows") or []
    con_dn = (data.get("sector_concept_down") or {}).get("rows") or []
    fin = data.get("sector_flow") or {}
    fin_in = (fin.get("industry_in") or {}).get("rows") or []
    fin_out = (fin.get("industry_out") or {}).get("rows") or []

    def panel(title, rows, badge_cls=""):
        return (f'<div class="sector-panel"><h3>{h(title)}</h3>{_sector_table(rows)}</div>')

    html = ('<div class="sector-grid">'
            + panel("行业 · 涨幅前5", ind_up)
            + panel("行业 · 跌幅前5", ind_dn)
            + panel("行业 · 资金净流入前5", fin_in)
            + panel("行业 · 资金净流出前5", fin_out)
            + panel("概念 · 涨幅前5", con_up)
            + panel("概念 · 跌幅前5", con_dn)
            + '</div>')
    return html + src("⚠️ 表示涨跌与资金背离（涨但资金流出 / 跌但资金流入）· 成交额低于1亿的板块不上榜 · 时点 " +
                      h(data.get("generated_at", "")))


# ---------- 5. 涨停与跌停（对称） ----------

def limit_blocks(data):
    lu = data.get("limit_up_detail") or {}
    ld = data.get("limit_down") or {}
    zb = data.get("broken_board") or {}

    ladder = lu.get("ladder") or {}
    by_ind = lu.get("by_industry") or []
    high = ladder.get(">=4", []) + ladder.get("3", [])
    n4 = len(ladder.get(">=4", []))
    n3 = len(ladder.get("3", []))
    n2 = len(ladder.get("2", []))

    lu_html = ['<div class="limit-col"><h3>涨停 <span class="pill-red">按行业聚合 · 连板梯队</span></h3>']
    if lu.get("ok"):
        lu_html.append(f'<p class="metric-line">最高 <b style="color:#d93025">{lu.get("max_height")}板</b> · '
                       f'≥4板 {n4} 只 · 3板 {n3} 只 · 2板 {n2} 只 · 涨停合计 {lu.get("total")} 只</p>')
        if by_ind:
            lu_html.append('<table class="compact"><thead><tr><th>行业</th><th>家数</th></tr></thead><tbody>')
            for r in by_ind[:6]:
                lu_html.append(f'<tr><td>{h(r.get("name"))}</td><td>{r.get("count")}</td></tr>')
            lu_html.append("</tbody></table>")
        if high:
            lu_html.append('<h3 style="margin-top:12px">连板个股（≥3板）</h3>'
                           '<table class="compact"><thead><tr><th>名称</th><th>连板</th><th>行业</th><th>封单</th></tr></thead><tbody>')
            for r in high[:12]:
                lu_html.append(f'<tr><td class="nm">{h(r.get("name"))}</td>'
                               f'<td><span class="pill-red">{r.get("limit_count")}板</span></td>'
                               f'<td>{h(r.get("industry") or "—")}</td>'
                               f'<td>{fmt_num(r.get("fund"),"元")}</td></tr>')
            lu_html.append("</tbody></table>")
    else:
        lu_html.append(empty("涨停池数据不可用"))
    lu_html.append('</div>')

    ld_html = ['<div class="limit-col"><h3>跌停 <span class="pill-green">按行业聚合 · 流动性明细</span></h3>']
    if ld.get("ok"):
        ld_html.append(f'<p class="metric-line">跌停合计 <b style="color:#137333">{ld.get("total")}</b> 家 · '
                       f'非ST {ld.get("nonst_count")} / ST {ld.get("st_count")}</p>')
        by = ld.get("by_industry") or []
        if by:
            ld_html.append('<table class="compact"><thead><tr><th>行业</th><th>家数</th><th>非ST/ST</th></tr></thead><tbody>')
            for r in by[:6]:
                ld_html.append(f'<tr><td>{h(r.get("name"))}</td><td>{r.get("count")}</td>'
                               f'<td>{r.get("nonst")}/{r.get("st")}</td></tr>')
            ld_html.append("</tbody></table>")
        rows = ld.get("rows") or []
        if rows:
            ld_html.append('<h3 style="margin-top:12px">跌停个股（成交额前5）</h3>'
                           '<table class="compact"><thead><tr><th>名称</th><th>价格</th><th>成交额</th><th>行业</th></tr></thead><tbody>')
            for r in rows[:5]:
                ld_html.append(f'<tr><td class="nm">{h(r.get("name"))}{" <span class=\"code\">ST</span>" if r.get("is_st") else ""}</td>'
                               f'<td>{r.get("price")}</td><td>{fmt_num(r.get("amount"),"元")}</td>'
                               f'<td>{h(r.get("industry") or "—")}</td></tr>')
            ld_html.append("</tbody></table>")
    else:
        ld_html.append(empty("跌停池数据不可用"))
    ld_html.append('</div>')

    burst_line = ""
    if zb.get("ok"):
        zb_rows = zb.get("rows") or []
        burst_line = (f'<p class="metric-line">炸板池 <b>{zb.get("total")}</b> 家 · '
                      f'代表：{h("、".join(r.get("name") or "" for r in zb_rows[:5]))}</p>')
    return ('<div class="two-col">' + "".join(lu_html) + "".join(ld_html) + '</div>' + burst_line +
            src("涨停/跌停按行业聚合，明细仅列连板≥3或成交额靠前者 · 价格统一为元 · 时点 " +
                h(data.get("generated_at", ""))))


# ---------- 6. 龙虎榜（选看） ----------

def dragon_block(data):
    dg = data.get("dragon") or {}
    if not dg.get("ok") or not dg.get("rows"):
        return empty("龙虎榜数据不可用")
    rows = dg["rows"]
    # 净买前5 / 净卖前5
    buys = sorted([r for r in rows if (r.get("net_amt") or 0) > 0], key=lambda x: -(x.get("net_amt") or 0))[:5]
    sells = sorted([r for r in rows if (r.get("net_amt") or 0) < 0], key=lambda x: (x.get("net_amt") or 0))[:5]

    def table(rs, title):
        if not rs:
            return empty(title + "无数据")
        out = [f'<h3>{h(title)}</h3><table class="compact"><thead><tr>'
               '<th>名称</th><th>涨幅</th><th>榜单净额</th><th>上榜原因</th></tr></thead><tbody>']
        for r in rs:
            c = color(r.get("pct"))
            out.append(f'<tr><td class="nm">{h(r.get("name"))}</td>'
                       f'<td style="color:{c}">{sign(r.get("pct"))}</td>'
                       f'<td style="color:{color(r.get("net_amt"))}">{fmt_num(r.get("net_amt"),"元")}</td>'
                       f'<td class="explain">{h(r.get("explain") or "—")}</td></tr>')
        out.append("</tbody></table>")
        return "".join(out)

    return ('<div class="two-col"><div>' + table(buys, "净买额前5") + '</div><div>' +
            table(sells, "净卖额前5") + '</div></div>' +
            src(f'交易日 {h(dg.get("trade_date"))} · 买方席位类型数据暂不可得，未展示 · 来源：{h(dg.get("source"))}'))


# ---------- 7. 全球与外部（简版 + 联动） ----------

def global_block(data):
    g = data.get("global_markets") or {}
    cf = data.get("commodities_fx") or {}
    fu = data.get("futures_basis") or {}
    by = data.get("bond_yield") or {}
    parts = ['<div class="two-col">']
    # 全球市场 + 联动
    if g.get("ok") and g.get("rows"):
        parts.append('<div><h3>全球市场</h3><table class="compact"><thead><tr><th>指数</th><th>点位</th><th>涨跌</th></tr></thead><tbody>')
        pmap = {r.get("name"): r.get("pct") for r in ((data.get("indices_all") or {}).get("rows") or [])}
        kc = pmap.get("科创50")
        for r in g["rows"]:
            nm = r.get("name") or ""
            link = ""
            if kc is not None and isinstance(r.get("pct"), (int, float)):
                same = (r.get("pct") > 0 and kc > 0) or (r.get("pct") < 0 and kc < 0)
                if any(k in nm for k in ("纳指", "纳斯达克", "恒生科技", "日经")):
                    link = f' <span class="link-tag">与科创50{"同向" if same else "背离"}</span>'
            parts.append(f'<tr><td>{h(nm)}{link}</td><td>{r.get("price")}</td>'
                         f'<td style="color:{color(r.get("pct"))}">{sign(r.get("pct"))}</td></tr>')
        parts.append('</tbody></table></div>')
    # 商品汇率 + 国债
    if cf.get("ok") and cf.get("rows") or by.get("ok"):
        parts.append('<div><h3>商品 / 汇率 / 利率</h3><table class="compact"><thead><tr><th>品种</th><th>价格</th><th>涨跌</th></tr></thead><tbody>')
        for r in (cf.get("rows") or []):
            parts.append(f'<tr><td>{h(r.get("name"))}</td><td>{r.get("price")}</td>'
                         f'<td style="color:{color(r.get("pct"))}">{sign(r.get("pct"))}</td></tr>')
        if by.get("ok"):
            parts.append(f'<tr><td>{h(by.get("name"))}</td><td>{by.get("value")}</td>'
                         f'<td style="color:{color(by.get("pct"))}">{sign(by.get("pct"))}</td></tr>')
        else:
            parts.append(f'<tr><td>10年期国债收益率</td><td colspan="2"><span class="miss-tag">数据缺失</span></td></tr>')
        parts.append('</tbody></table></div>')
    parts.append('</div>')

    # 期指基差（托底资金线索）
    if fu.get("ok") and fu.get("rows"):
        parts.append('<h3 style="margin-top:16px">股指期货基差（现货 − 期货，正=贴水）</h3>'
                     '<table class="compact"><thead><tr><th>品种</th><th>期货</th><th>现货</th><th>基差</th><th>状态</th></tr></thead><tbody>')
        for r in fu["rows"]:
            parts.append(f'<tr><td class="nm">{h(r.get("name"))} <span class="code">{h(r.get("spot_name"))}</span></td>'
                         f'<td>{r.get("future")}</td><td>{r.get("spot")}</td>'
                         f'<td style="color:{color(-(r.get("basis") or 0))}">{r.get("basis")}</td>'
                         f'<td>{h(r.get("state"))}</td></tr>')
        parts.append('</tbody></table>')
        parts.append('<p class="note-inline">四大期指全线贴水，反映避险/对冲需求；'
                     '宽基ETF份额变动接口暂未返回，按模板标注数据缺失、不编造。</p>')
    return "".join(parts) + src("全球指数为隔夜/实时值，已注明联动关系 · 来源：东方财富 push2")


# ---------- 8. 我的持仓与自选 ----------

def watch_block(data):
    wl = data.get("watchlist") or []
    if not wl:
        return empty("自选股数据不可用")
    idx = {a.get("name"): a.get("pct") for a in data.get("indices", [])}
    bench = idx.get("上证指数")
    ann_by_code = {}
    for r in ((data.get("announcements") or {}).get("rows") or []):
        ann_by_code.setdefault(r.get("code"), []).append(r.get("category"))

    out = ['<table><thead><tr><th>标的</th><th>现价</th><th>涨跌</th><th>相对大盘</th>'
           '<th>距MA20</th><th>量比</th><th>主力净占比</th><th>今日事件</th><th>信号</th></tr></thead><tbody>']
    for a in wl:
        c = color(a.get("pct"))
        is_etf = str(a.get("code", "")).startswith(("51", "15", "56", "58"))
        ind = a.get("ind") or {}
        rel = (a.get("pct") - bench) if (isinstance(a.get("pct"), (int, float)) and isinstance(bench, (int, float))) else None
        ma20 = ind.get("ma20")
        dma = ((a.get("price") / ma20 - 1) * 100) if (isinstance(a.get("price"), (int, float)) and isinstance(ma20, (int, float)) and ma20) else None
        # ETF 不显示主力净占比；K线不全显示数据缺失
        kline_ok = len(((data.get("focus") or {}).get("kline") or {}).get("rows") or []) >= 60
        if is_etf:
            flow_txt = '<span class="muted">—</span>'  # ETF 不显示主力净占比
        else:
            flow_txt = sign(a.get("flow_pct")) if a.get("flow_pct") is not None else "—"
        ma_txt = sign(dma) if dma is not None else "—"
        vr = a.get("vol_ratio")
        vr_txt = f"{vr:.2f}" if isinstance(vr, (int, float)) else "—"
        ev = ann_by_code.get(a.get("code"), [])
        ev_txt = "、".join(ev[:2]) if ev else '<span class="muted">—</span>'
        sigs = "".join(badge(s.get("type"), "warn" if s.get("level") == "warn" else "info")
                       for s in a.get("signals", [])) or '<span class="muted">—</span>'
        out.append(f'<tr><td class="nm">{h(a.get("name"))}<div class="sub">{h(a.get("code") or "")} · {h(a.get("note") or "")}</div></td>'
                   f'<td style="color:{c};font-weight:600">{a.get("price") if a.get("price") is not None else "—"}</td>'
                   f'<td style="color:{c}">{sign(a.get("pct"))}</td>'
                   f'<td style="color:{color(rel)}">{sign(rel)}</td>'
                   f'<td style="color:{color(dma)}">{ma_txt}</td>'
                   f'<td>{vr_txt}</td><td>{flow_txt}</td><td>{ev_txt}</td><td>{sigs}</td></tr>')
    out.append("</tbody></table>")
    note = ('ETF 不显示主力净占比 · 技术指标数据不全时整行显示缺失、不产生信号 · '
            '相对大盘以上证指数为基准 · 时点 ' + h(data.get("generated_at", "")))
    return "".join(out) + src(note)


def focus_block(data):
    """个股深度面板：仅对触发信号的非ETF标的展开。"""
    wl = data.get("watchlist") or []
    triggered = [a for a in wl if a.get("signals") and
                 not str(a.get("code", "")).startswith(("51", "15", "56", "58"))]
    if not triggered:
        return empty("今日自选股未触发信号，个股深度面板不展开（按模板规则）")
    a = triggered[0]
    fc = data.get("focus") or {}
    # 只有 focus 就是该标的时才展示（避免张冠李戴）
    if fc.get("code") != a.get("code"):
        return (f'<p class="note-inline">触发信号标的：{h(a.get("name"))}（{h(a.get("code"))}）· '
                f'{h("、".join(s.get("type") or "" for s in a.get("signals", [])))}。'
                f'详细K线面板仅对当前焦点标的提供，此处不展开以避免错配。</p>')
    kline_ok = len((fc.get("kline") or {}).get("rows") or []) >= 60
    if not kline_ok:
        return empty(f'{a.get("name")} K线不足60根，技术指标整块标缺失，不显示空列')
    q = fc.get("quote") or {}
    ind = fc.get("ind") or {}
    kline = candlestick_svg((fc.get("kline") or {}).get("rows", []))
    return (f'<h3>{h(fc.get("name"))} <span class="code">{h(fc.get("code"))}</span> · 今日触发信号，展开深度面板</h3>'
            f'<div class="kline-wrap">{kline}</div>'
            f'<div class="mini-grid" style="margin-top:12px">'
            f'<div class="mini"><div class="ml">现价</div><div class="mv" style="color:{color(q.get("pct"))}">{q.get("price") or "—"}</div></div>'
            f'<div class="mini"><div class="ml">MA5/MA20</div><div class="mv">{ind.get("ma5","—")} / {ind.get("ma20","—")}</div></div>'
            f'<div class="mini"><div class="ml">MACD</div><div class="mv" style="color:{color(ind.get("macd"))}">{ind.get("macd") if ind.get("macd") is not None else "—"}</div></div>'
            f'<div class="mini"><div class="ml">RSI(14)</div><div class="mv">{ind.get("rsi14") if ind.get("rsi14") is not None else "—"}</div></div>'
            f'</div>' + src("K线为前复权日线 · 技术指标基于历史数据统计，不预测方向"))


# ---------- 9. 公告与要闻（精选） ----------

def announcement_block(data):
    ann = data.get("announcements") or {}
    macro = data.get("macro_news") or {}
    rows = ann.get("rows") or []
    out = ['<h3>公告精选（并购 / 回购 / 减持 / 业绩 / 监管，上限10条）</h3>']
    if rows:
        out.append('<table class="compact"><thead><tr><th>时间</th><th>公司</th><th>类型</th><th>标题</th></tr></thead><tbody>')
        for r in rows[:10]:
            out.append(f'<tr><td>{h(r.get("date"))}</td><td class="nm">{h(r.get("name") or "—")}</td>'
                       f'<td>{badge(r.get("category"))}</td>'
                       f'<td class="explain"><a href="{h(r.get("url") or "#")}" target="_blank" rel="noopener">{h(r.get("title"))}</a></td></tr>')
        out.append("</tbody></table>")
    else:
        out.append(empty("未检索到符合条件的精选公告"))

    out.append('<h3 style="margin-top:16px">可能相关的消息（政策 / 监管 / 宏观）</h3>')
    mrows = macro.get("rows") or []
    if mrows:
        out.append('<ul class="newslist">')
        for r in mrows[:6]:
            out.append(f'<li><span class="ntime">{h(r.get("time"))}</span>'
                       f'<a href="{h(r.get("url") or "#")}" target="_blank" rel="noopener">{h(r.get("title"))}</a></li>')
        out.append("</ul>")
    else:
        out.append('<p class="note-inline">今日未检索到明确催化事件（政策/监管/宏观关键词筛选为空），不留白、不编造。</p>')
    return "".join(out) + src("公告按关键词精选并剔除程序性噪音 · 宏观消息来自快讯关键词筛选 · 时点 " +
                              h(data.get("generated_at", "")))


# ---------- 10. 明日关注 ----------

def tomorrow_block(data):
    ul = data.get("unlock") or {}
    rows = ul.get("rows") or []
    out = ['<div class="two-col"><div><h3>限售解禁（未来3天，按市值）</h3>']
    if rows:
        out.append('<table class="compact"><thead><tr><th>日期</th><th>标的</th><th>解禁市值</th><th>占总股本</th></tr></thead><tbody>')
        for r in rows[:8]:
            ratio = r.get("ratio")
            cap = r.get("cap")
            cap_yuan = cap * 1e4 if isinstance(cap, (int, float)) else None  # 接口单位为万元
            out.append(f'<tr><td>{h(r.get("date"))}</td><td class="nm">{h(r.get("name"))} <span class="code">{h(r.get("code"))}</span></td>'
                       f'<td>{fmt_num(cap_yuan,"元")}</td>'
                       f'<td>{f"{float(ratio)*100:.2f}%" if isinstance(ratio,(int,float)) else "—"}</td></tr>')
        out.append("</tbody></table>")
    else:
        out.append(empty("未检索到未来3天解禁数据"))
    out.append('</div><div><h3>数据 / 会议 / 交割</h3>')
    out.append('<ul class="plain-list">'
               '<li>重要经济数据发布：统计算法未提供日历接口，标注待补，不编造。</li>'
               '<li>重要会议：无公开接口，标注待补。</li>'
               '<li>期权、期指交割日：每月第三个周五，临近时以交易所公告为准。</li>'
               '<li>自选股公告预披露与财报日期：见「公告精选」及 F10 财务快照。</li>'
               '</ul></div></div>')
    out.append('<p class="note-inline">明日关注中无公开接口的项目一律标注待补，避免编造具体日期与事件。</p>')
    return "".join(out)


# ---------- 11. 异动信号 ----------

def signal_block(sig):
    if not sig:
        return empty("未触发任何异动信号（质检未通过的模块不产生信号）")
    out = ['<table class="compact"><thead><tr><th>标的</th><th>触发条件</th><th>当前数值</th><th>阈值</th></tr></thead><tbody>']
    for s in sig[:20]:
        out.append(f'<tr><td class="nm">{h(s.get("name") or "—")}</td>'
                   f'<td>{badge(s.get("type"), "warn" if s.get("level")=="warn" else "info")}</td>'
                   f'<td>{h(s.get("text") or "—")}</td>'
                   f'<td>{h(s.get("threshold") or "见 config.py")}</td></tr>')
    out.append("</tbody></table>")
    return "".join(out) + src("阈值：涨跌幅 ±" + str(config.ALERT.get("pct_change")) +
                              "% · 量比 " + str(config.ALERT.get("vol_ratio")) +
                              "x · RSI≥70/≤30 · MACD/布林/KDJ 状态 · 均线金叉死叉")


# ---------- 12. 备查（折叠） ----------

def appendix_block(data):
    nb = data.get("northbound") or {}
    parts = []
    if nb.get("ok"):
        parts.append(f'<p>北向成交（{h(nb.get("date"))}）：{(nb.get("deal_amt") or 0):,.0f} 万元。'
                     f'沪深港通改革后仅披露成交额、无买卖方向，参考价值低，降为备查。</p>')
    else:
        parts.append('<p>北向成交：接口未返回有效数据（量级存疑），已降为备查，不输出信号。</p>')
    parts.append('<p>完整涨停/跌停名单、完整龙虎榜：见结构化 JSON 数据文件（本页仅展示聚合与重点个股）。</p>')
    parts.append('<div class="note" style="margin-top:10px">'
                 '<b>口径与风险提示</b>：本系统为客观数据监测工具，不预测涨跌方向、不构成买卖建议。'
                 '资金流字段单位口径以东方财富数据源为准；技术指标为历史数据统计，过往表现不预示未来。'
                 '财经快讯与公告为第三方信息，未经独立核实。市场有风险，投资决策请独立判断。</div>')
    parts.append(src("数据来源：东方财富公开接口（push2 / push2ex / 数据中心 / F10 / 公告 / 快讯）· 生成时点 " +
                     h(data.get("generated_at", ""))))
    return "".join(parts)


# ---------- 主渲染 ----------

CSS = """
  * { box-sizing:border-box; }
  body { margin:0; background:#f5f6f8; color:#202124; font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; line-height:1.6; }
  .wrap { max-width:1200px; margin:0 auto; padding:28px 20px 60px; }
  .hd { border-bottom:3px solid #1a73e8; padding-bottom:14px; margin-bottom:20px; }
  .hd h1 { margin:0; font-size:27px; letter-spacing:.5px; }
  .hd .meta { color:#5f6368; font-size:13px; margin-top:6px; }
  .pill { display:inline-block; padding:3px 10px; border-radius:12px; background:#e8f0fe; color:#1967d2; font-size:12px; font-weight:600; }
  .pill-red { display:inline-block; padding:1px 7px; border-radius:10px; background:#fce8e6; color:#c5221f; font-size:11px; font-weight:600; }
  .pill-green { display:inline-block; padding:1px 7px; border-radius:10px; background:#e6f4ea; color:#137333; font-size:11px; font-weight:600; }
  .tldr { background:#fff; border:1px solid #e0e3e8; border-left:5px solid #1a73e8; border-radius:8px; padding:18px 22px; margin-bottom:16px; box-shadow:0 1px 3px rgba(0,0,0,.04); }
  .tldr h2 { margin:0 0 8px; font-size:15px; color:#1a73e8; }
  .tldr .tone { font-size:18px; font-weight:700; }
  .tldr .concl { margin:8px 0; color:#202124; font-size:14px; font-weight:500; }
  .tldr .disc { margin:8px 0 0; color:#5f6368; font-size:12px; }
  .qc { background:#fff; border:1px solid #e0e3e8; border-radius:8px; padding:12px 18px; margin-bottom:20px; }
  .qc-title { font-size:13px; font-weight:700; color:#5f6368; margin-bottom:6px; }
  .qc-items { display:flex; flex-wrap:wrap; gap:8px 16px; font-size:12px; }
  .qc-ok { color:#137333; } .qc-warn { color:#c5221f; } .qc-miss { color:#9aa0a6; }
  .level-tag { display:inline-block; padding:2px 8px; border-radius:10px; font-size:11px; font-weight:600; margin-left:8px; }
  .level-must { background:#fce8e6; color:#c5221f; } .level-opt { background:#e8f0fe; color:#1967d2; } .level-ref { background:#f1f3f4; color:#5f6368; }
  .sec { background:#fff; border:1px solid #e0e3e8; border-radius:8px; padding:20px 22px; margin-bottom:18px; box-shadow:0 1px 3px rgba(0,0,0,.04); }
  .sec > h2 { margin:0 0 16px; font-size:17px; border-left:4px solid #1a73e8; padding-left:10px; }
  h3 { font-size:14px; color:#3c4043; margin:0 0 10px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th { background:#f1f3f4; color:#5f6368; font-weight:600; text-align:left; padding:8px 10px; font-size:12px; white-space:nowrap; }
  td { padding:8px 10px; border-bottom:1px solid #eceff1; }
  tr:last-child td { border-bottom:none; }
  .compact { font-size:12px; } .compact th,.compact td { padding:6px 8px; }
  .nm { font-weight:600; white-space:nowrap; }
  .sub { font-size:11px; color:#9aa0a6; font-weight:400; }
  .code { color:#9aa0a6; font-weight:400; font-size:11px; }
  .explain { color:#5f6368; font-size:12px; max-width:320px; }
  .metric { font-weight:600; }
  .badge { display:inline-block; padding:2px 7px; border-radius:10px; font-size:11px; margin:1px; white-space:nowrap; }
  .badge.warn { background:#fce8e6; color:#c5221f; } .badge.info { background:#e8f0fe; color:#1967d2; }
  .muted { color:#9aa0a6; }
  .miss-tag { color:#9aa0a6; background:#f1f3f4; padding:1px 6px; border-radius:4px; font-size:11px; }
  .diverge { color:#f9ab00; }
  .two-col { display:grid; grid-template-columns:1fr 1fr; gap:24px; }
  .sector-grid { display:grid; grid-template-columns:1fr 1fr; gap:18px 24px; }
  .mini-grid,.style-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; }
  .mini { background:#f8f9fa; border:1px solid #eceff1; border-radius:6px; padding:9px 12px; }
  .ml { color:#5f6368; font-size:11px; } .mv { font-size:15px; font-weight:600; margin-top:3px; }
  .breadth-bar { display:flex; height:14px; border-radius:7px; overflow:hidden; margin-top:14px; }
  .breadth-bar .seg.up { background:#d93025; } .breadth-bar .seg.flat { background:#9aa0a6; } .breadth-bar .seg.down { background:#137333; }
  .metric-line { font-size:13px; color:#3c4043; margin:4px 0 10px; }
  .newslist { list-style:none; padding:0; margin:0; }
  .newslist li { padding:8px 0; border-bottom:1px solid #eceff1; font-size:13px; }
  .newslist li:last-child { border-bottom:none; }
  .newslist a { color:#202124; text-decoration:none; } .newslist a:hover { color:#1a73e8; }
  .ntime { display:inline-block; min-width:74px; color:#9aa0a6; font-size:11px; }
  .plain-list { margin:0; padding-left:18px; font-size:13px; color:#3c4043; }
  .plain-list li { padding:4px 0; }
  .note-inline { font-size:12px; color:#5f6368; background:#f8f9fa; border-radius:6px; padding:8px 12px; margin:10px 0 0; }
  .kline-wrap { border:1px solid #eceff1; border-radius:6px; overflow:hidden; }
  .empty { color:#5f6368; background:#f8f9fa; padding:14px; border-radius:6px; text-align:center; }
  .src { color:#9aa0a6; font-size:11px; margin:10px 0 0; }
  .note { font-size:12px; color:#5f6368; background:#fff8e1; border:1px solid #fde293; border-radius:6px; padding:12px 16px; }
  details.ref { margin-bottom:18px; background:#fff; border:1px solid #e0e3e8; border-radius:8px; padding:14px 22px; }
  details.ref summary { cursor:pointer; font-size:15px; font-weight:600; color:#5f6368; }
  .ft { color:#9aa0a6; font-size:12px; text-align:center; margin-top:30px; line-height:1.8; }
  @media(max-width:760px){ .two-col,.sector-grid{grid-template-columns:1fr;} }
"""


def render(data):
    date_str = data["generated_at"][:10].replace("-", "")
    mode = data.get("mode", "post")
    mode_label = "盘前简报" if mode == "pre" else "盘后简报"
    out = config.OUTPUT_DIR / f"投研看板_{date_str}_{mode}.html"

    def sec(num, title, level, body):
        tag = {"必看": "level-must", "选看": "level-opt", "备查": "level-ref"}[level]
        return (f'<div class="sec"><h2>{num}、{h(title)}'
                f'<span class="level-tag {tag}">{level}</span></h2>{body}</div>')

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股投研日报（改进版）{mode_label} {data['generated_at'][:10]}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="hd">
    <h1>A股投研日报（改进版） <span class="pill">{mode_label}</span></h1>
    <div class="meta">生成时间：{data['generated_at']} · 市场状态：{h(data['market_status'])} · 数据源：东方财富公开接口 · 三层分级：必看 / 选看 / 备查</div>
  </div>

  {qc_block(data)}
  {tldr(data)}

  {sec('二', '市场温度（今日 / 昨日 / 变化）', '必看', temperature_block(data))}
  {sec('三', '指数与风格', '必看', index_style_block(data))}
  {sec('四', '板块：涨、跌、资金（涨跌对称）', '必看', sector_block(data))}
  {sec('五', '涨停与跌停（涨跌对称）', '必看', limit_blocks(data))}
  {sec('六', '全球与外部（简版）', '必看', global_block(data))}
  {sec('七', '我的持仓与自选', '必看', watch_block(data) + '<h3 style="margin-top:18px">个股深度面板（仅触发信号展开）</h3>' + focus_block(data))}
  {sec('八', '公告与要闻（精选）', '必看', announcement_block(data))}
  {sec('九', '明日关注', '选看', tomorrow_block(data))}
  {sec('十', '龙虎榜', '选看', dragon_block(data))}
  {sec('十一', '异动信号汇总', '选看', signal_block(data.get('signals', [])))}

  <details class="ref">
    <summary>十二、备查（点击展开）：北向成交 / 完整口径与风险提示 / 数据来源</summary>
    <div style="margin-top:12px">{appendix_block(data)}</div>
  </details>

  <div class="ft">
    A股投研日报（改进版）· 自动生成<br>
    客观数据监测，不预测方向、不构成投资建议 · 红涨绿跌<br>
    数据来源：东方财富公开接口 · 生成时点 {data['generated_at']}
  </div>
</div>
</body>
</html>"""
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    demo = {
        "generated_at": "2026-11-25 16:00:00", "market_status": "盘后",
        "indices": [], "indices_all": {"rows": []}, "breadth": {"ok": False},
        "watchlist": [], "signals": [],
    }
    print(render(demo))
