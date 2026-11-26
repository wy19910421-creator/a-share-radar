# -*- coding: utf-8 -*-
"""
A 股投研辅助系统 - 配置文件
所有自选股、指数、告警阈值都在这里维护。
注意：这里只是"观察清单"，不是投资建议；请按自己的判断增删。
"""
import os
import time as _time
from pathlib import Path

# Linux（GitHub Actions）上设置 TZ 后需 tzset() 才对 datetime.now() 生效；Windows 无此函数
if _time.__dict__.get("tzset") and os.environ.get("TZ"):
    _time.tzset()

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"


def _load_dotenv():
    """本地开发用：从 .env 读取环境变量（该文件不上传仓库）。

    云端（GitHub Actions）通过 Secrets 注入同名环境变量，无需 .env。
    """
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

# 数据源：东方财富公开行情接口（无需 key）
API_QUOTE = "https://push2.eastmoney.com/api/qt/stock/get"
API_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
API_FLOW = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "close",
}
TIMEOUT = 15
RETRY = 3

# 大盘指数观察（secid 前缀：1=沪市, 0=深市/创业板）
INDICES = [
    {"secid": "1.000001", "name": "上证指数", "code": "000001"},
    {"secid": "0.399001", "name": "深证成指", "code": "399001"},
    {"secid": "0.399006", "name": "创业板指", "code": "399006"},
]

# 自选股观察清单（示例为宽基 ETF 与常见大盘股，仅为演示抓取，非推荐）
# 你可以随意改成自己关注的股票：沪市用 1.xxxxxx，深市用 0.xxxxxx
WATCHLIST = [
    {"secid": "1.510300", "name": "沪深300ETF", "code": "510300", "note": "宽基观察"},
    {"secid": "1.510050", "name": "上证50ETF",  "code": "510050", "note": "宽基观察"},
    {"secid": "0.159915", "name": "创业板ETF",  "code": "159915", "note": "宽基观察"},
    {"secid": "1.600519", "name": "贵州茅台",    "code": "600519", "note": "示例"},
    {"secid": "0.000858", "name": "五粮液",      "code": "000858", "note": "示例"},
]

# 告警阈值
ALERT = {
    "pct_change": 5.0,       # 单日涨跌幅绝对值超过 5% 触发
    "vol_ratio": 2.0,        # 量比（今日量/过去5日均量）超过 2 倍触发
    "ma_cross": True,        # 是否检测均线金叉/死叉（MA5 上穿/下穿 MA20）
    "flow_in_wan": 5000,     # 主力净流入超过 5000 万触发（单位：万元）
}

KLINE_DAYS = 60             # 抓取最近 60 个交易日用于技术指标计算

# 微信推送配置
# 渠道三选一：pushplus(PushPlus) / serverchan(Server酱) / wecom(企业微信群机器人)
# 凭证获取方式见 README。未填凭证前 enabled 请保持 False。
def _env_bool(name, default=False):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


PUSH = {
    # 本地读 .env，云端读 GitHub Actions Secrets（注入同名环境变量）
    "enabled": _env_bool("PUSH_ENABLED", False),
    "channel": os.environ.get("PUSH_CHANNEL", "pushplus"),
    "pushplus_token": os.environ.get("PUSHPLUS_TOKEN", ""),
    "serverchan_key": os.environ.get("SERVERCHAN_KEY", ""),
    "wecom_webhook": os.environ.get("WECOM_WEBHOOK", ""),
}
