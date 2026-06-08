"""
A股自动化分析脚本 (增强版)
======================
盘前 (8:30) - 隔夜行情、盘前新闻、当日预判 + 板块趋势解读
盘后 (15:30) - 板块资金流向分析 + 趋势解读 + 个股推荐
数据来源: 东方财富、同花顺、百度财经
推送: Server酱
"""

import akshare as ak
import requests
import pandas as pd
import os
import sys
from datetime import datetime, date, timedelta

SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "SCT361365TNYfnOEArgCCcKesZyGnB6z2g")


def send_wechat(content, title=""):
    """Push to WeChat via ServerChan"""
    if not title:
        first_line = content.split(chr(10))[0]
        title = first_line.replace("#", "").strip()[:50]
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
    data = {"title": title, "desp": content}
    try:
        resp = requests.post(url, json=data, timeout=30)
        result = resp.json()
        if result.get("code") == 0:
            pid = result.get("data", {}).get("pushid", "")
            print(f"[OK] pushed via ServerChan (pushid: {pid})")
        else:
            print(f"[WARN] push fail: {result}")
        return result
    except Exception as e:
        print(f"[ERROR] push exception: {e}")
        return None


def safe_fetch(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as e:
        print(f"[WARN] {func.__name__} failed: {e}")
        return None


def truncate_msg(msg, max_bytes=4000):
    if len(msg.encode("utf-8")) <= max_bytes:
        return msg
    while len(msg.encode("utf-8")) > max_bytes - 50:
        msg = msg[:len(msg) - 100]
        last_nl = msg.rfind(chr(10))
        if last_nl > 0:
            msg = msg[:last_nl]
        else:
            break
    return msg + chr(10)*2 + "...content truncated"


def fmt_float(val):
    try:
        v = float(val)
        if pd.isna(v):
            return "--"
        return f"{v:.2f}"
    except (ValueError, TypeError):
        return str(val)


def fmt_pct(val):
    try:
        v = float(val)
        if pd.isna(v):
            return "--"
        return f"{v:+.2f}%"
    except (ValueError, TypeError):
        return str(val)


def trend_arrow(val):
    try:
        v = float(val)
        if pd.isna(v):
            return ""
        return "↑" if v > 0 else "↓" if v < 0 else "→"
    except:
        return ""


def flow_icon(val):
    try:
        v = float(val)
        if pd.isna(v):
            return ""
        return "🟢" if v > 0 else "🔴"
    except:
        return ""




# ======================== Recommendation Tracking & Hit Rate ========================

import json
import os

RECORDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recommendations.json")


def load_records():
    """Load recommendation history from JSON file"""
    if not os.path.exists(RECORDS_FILE):
        return {"recommendations": [], "verifications": []}
    try:
        with open(RECORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"recommendations": [], "verifications": []}


def save_records(records):
    """Save recommendation history to JSON file"""
    with open(RECORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def save_recommendation(sector_picks, stock_picks):
    """Save today""s recommendations for future verification"""
    records = load_records()
    today_str = str(date.today())
    
    # Remove any existing record for today
    records["recommendations"] = [
        r for r in records["recommendations"] if r.get("date") != today_str
    ]
    
    entry = {"date": today_str, "sectors": [], "stocks": []}
    for name, stocks in sector_picks:
        entry["sectors"].append({
            "name": name,
            "stocks": [{"code": s[0], "name": s[1], "price": s[2]} for s in stocks]
        })
    for code, name, price in stock_picks:
        entry["stocks"].append({"code": code, "name": name, "price": price})
    
    records["recommendations"].append(entry)
    # Keep only last 60 days
    records["recommendations"] = sorted(
        records["recommendations"], key=lambda x: x["date"]
    )[-60:]
    save_records(records)
    print(f"[RECORD] Saved {len(sector_picks)} sectors + {len(stock_picks)} stock picks")


def verify_yesterday_recommendations(today_spot):
    """Verify yesterday""s recommendations against today""s market data"""
    records = load_records()
    yesterday_str = str(date.today() - timedelta(days=1))
    
    yest_recs = [r for r in records["recommendations"] if r.get("date") == yesterday_str]
    if not yest_recs:
        return None
    
    # Remove old verification for yesterday
    records["verifications"] = [
        v for v in records["verifications"] if v.get("date") != str(date.today())
    ]
    
    result = {"date": str(date.today()), "rec_date": yesterday_str, "sectors": [], "stocks": []}
    
    # Build current sector lookup from today""s spot data
    sector_map = {}
    if today_spot is not None:
        for _, row in today_spot.iterrows():
            name = str(row.get("名称", ""))
            chg = row.get("涨跌幅", "")
            try:
                chg_val = float(chg.replace("%", ""))
            except:
                chg_val = 0
            sector_map[name] = chg_val
    
    sector_hits = 0
    sector_total = 0
    stock_hits = 0
    stock_total = 0
    
    for rec in yest_recs:
        for s in rec.get("sectors", []):
            sname = s["name"]
            chg = sector_map.get(sname, None)
            if chg is not None:
                hit = chg > 0
                sector_total += 1
                if hit:
                    sector_hits += 1
                result["sectors"].append({
                    "name": sname, "change_pct": chg, "hit": hit
                })
        
        for s in rec.get("stocks", []):
            stock_total += 1
            # For stocks we try to get from individual fund flow data
            result["stocks"].append({
                "code": s["code"], "name": s["name"],
                "prev_price": s.get("price", 0), "change_pct": 0, "hit": None
            })
    
    if sector_total > 0:
        result["sector_hit_rate"] = round(sector_hits / sector_total * 100, 1)
    else:
        result["sector_hit_rate"] = 0
    result["sector_hits"] = sector_hits
    result["sector_total"] = sector_total
    
    records["verifications"].append(result)
    records["verifications"] = sorted(
        records["verifications"], key=lambda x: x["date"]
    )[-60:]
    save_records(records)
    
    return result


def build_hit_rate_section(verification):
    """Build markdown section for hit rate report"""
    if verification is None:
        return ""
    
    lines = ["", "## " + chr(0x1f4ca) + " 昨日推荐验证", ""]
    
    if verification.get("sector_total", 0) > 0:
        hr = verification["sector_hit_rate"]
        icon = chr(0x1f7e2) if hr >= 60 else chr(0x1f7e1) if hr >= 40 else chr(0x1f534)
        lines.append(f"{icon} 板块命中率: **{hr}%** ({verification['sector_hits']}/{verification['sector_total']})")
        
        lines.append("")
        lines.append("| 板块 | 涨跌幅 | 结果 |")
        lines.append("|------|--------|------|")
        for s in verification.get("sectors", []):
            chg = s["change_pct"]
            arr = chr(0x2191) if chg > 0 else chr(0x2193)
            res = chr(0x2705) if s["hit"] else chr(0x274c)
            lines.append(f"| {s['name']} | {arr}{chg:+.1f}% | {res} |")
    
    # Add overall stats
    records = load_records()
    all_verifications = records.get("verifications", [])
    if len(all_verifications) >= 3:
        total_hits = sum(v.get("sector_hits", 0) for v in all_verifications)
        total_sectors = sum(v.get("sector_total", 0) for v in all_verifications)
        if total_sectors > 0:
            overall_hr = round(total_hits / total_sectors * 100, 1)
            lines.append(f"")
            lines.append(f"{chr(0x1f4c8)} 累计命中率（近{len(all_verifications)}天）: **{overall_hr}%** ({total_hits}/{total_sectors})")
    
    return chr(10).join(lines)


def get_overall_stats():
    """Get overall hit rate statistics for learning"""
    records = load_records()
    verifications = records.get("verifications", [])
    
    if not verifications:
        return None
    
    total_sector_hits = 0
    total_sector_count = 0
    
    for v in verifications:
        total_sector_hits += v.get("sector_hits", 0)
        total_sector_count += v.get("sector_total", 0)
    
    if total_sector_count == 0:
        return None
    
    return {
        "total_days": len(verifications),
        "total_recommendations": total_sector_count,
        "total_hits": total_sector_hits,
        "hit_rate": round(total_sector_hits / total_sector_count * 100, 1)
    }


# ======================== Trend Analysis ========================

def analyze_sector_momentum(sector_type):
    """
    Analyze sector capital flow momentum by comparing today vs 5-day data.
    Returns categorized sectors with trend interpretation.
    """
    today = safe_fetch(ak.stock_sector_fund_flow_rank, indicator="今日", sector_type=sector_type)
    five_day = safe_fetch(ak.stock_sector_fund_flow_rank, indicator="5日", sector_type=sector_type)
    ten_day = safe_fetch(ak.stock_sector_fund_flow_rank, indicator="10日", sector_type=sector_type)

    result = {
        "today_top": None,
        "sustained_inflow": [],
        "accelerating": [],
        "reversing": [],
        "sustained_outflow": [],
        "all_data": today
    }

    if today is None or today.empty:
        return result

    result["today_top"] = today.head(8)

    if five_day is None or today is None:
        return result

    # Build lookup by sector name
    flow_col = "主力净流入-净额"
    name_col = "名称"

    today_map = {}
    for _, row in today.iterrows():
        name = str(row.get(name_col, ""))
        if name:
            today_map[name] = row

    five_map = {}
    for _, row in five_day.iterrows():
        name = str(row.get(name_col, ""))
        if name:
            five_map[name] = row

    ten_map = {}
    if ten_day is not None and not ten_day.empty:
        for _, row in ten_day.iterrows():
            name = str(row.get(name_col, ""))
            if name:
                ten_map[name] = row

    # Analyze each sector present in today's data
    for _, row in today.iterrows():
        name = str(row.get(name_col, ""))
        if not name:
            continue
        t_val = pd.to_numeric(row.get(flow_col, 0), errors="coerce")
        if pd.isna(t_val):
            t_val = 0

        f_val = 0
        if name in five_map:
            f_val = pd.to_numeric(five_map[name].get(flow_col, 0), errors="coerce")
            if pd.isna(f_val):
                f_val = 0

        ten_val = 0
        if name in ten_map:
            ten_val = pd.to_numeric(ten_map[name].get(flow_col, 0), errors="coerce")
            if pd.isna(ten_val):
                ten_val = 0

        # Sustained inflow: today > 0 and 5-day avg > 0 and 10-day avg > 0
        f_avg = f_val  # already a total, compare today vs 5-day per day
        t_daily = t_val
        f_daily = f_val

        if t_daily > 0 and f_daily > 0 and ten_val > 0:
            result["sustained_inflow"].append((name, t_val, f_val, ten_val))
        elif t_daily > 0 and f_daily < 0:
            result["reversing"].append((name, t_val, f_val))
        elif t_daily > 0 and f_daily > 0 and t_daily > abs(f_daily) * 0.3:
            result["accelerating"].append((name, t_val, f_val))
        elif t_daily < 0 and f_daily < 0 and ten_val < 0:
            result["sustained_outflow"].append((name, t_val, f_val, ten_val))

    # Sort by today's flow
    result["sustained_inflow"].sort(key=lambda x: x[1], reverse=True)
    result["accelerating"].sort(key=lambda x: x[1], reverse=True)
    result["reversing"].sort(key=lambda x: x[1], reverse=True)
    result["sustained_outflow"].sort(key=lambda x: x[1])

    return result


def build_trend_section(momentum, section_title):
    """Build a markdown section explaining capital flow trends and why money is moving."""
    lines = []
    lines.append(f"## {section_title}")
    lines.append("")

    si = momentum.get("sustained_inflow", [])
    acc = momentum.get("accelerating", [])
    rev = momentum.get("reversing", [])
    so = momentum.get("sustained_outflow", [])

    if si:
        lines.append("**🟢 持续流入板块**（今日 + 5日 + 10日均流入）")
        for name, t, f, ten in si[:5]:
            lines.append(f"  - {name}: 今日 **{fmt_float(t)}亿**  5日 {fmt_float(f)}亿  10日 {fmt_float(ten)}亿 🟢")
        lines.append("\n→ 资金长期持续流入，表明这些板块得到市场的长期认可")
        lines.append("")

    if acc:
        lines.append("**🟡 加速流入板块**（今日流入较 5日显著增大）")
        for name, t, f in acc[:3]:
            ratio = abs(t / f * 100) if f != 0 else 0
            lines.append(f"  - {name}: 今日 {fmt_float(t)}亿  5日 {fmt_float(f)}亿  (增幅 {ratio:.0f}%)")
        lines.append("\n→ 资金加速流入，可能受政策、产业利好或市场情绪驱动")
        lines.append("")

    if rev:
        lines.append("**🔵 转向流入板块**（近期流出转今日流入）")
        for name, t, f in rev[:3]:
            lines.append(f"  - {name}: 今日 +{fmt_float(t)}亿  5日 {fmt_float(f)}亿")
        lines.append("\n→ 资金方向发生转变，需关注是否有利好催化")
        lines.append("")

    if so:
        lines.append("**🔴 持续流出板块**（今日 + 5日 + 10日均流出）")
        for name, t, f, ten in so[:3]:
            lines.append(f"  - {name}: 今日 {fmt_float(t)}亿  5日 {fmt_float(f)}亿  10日 {fmt_float(ten)}亿")
        lines.append("")

    if not si and not acc and not rev and not so:
        lines.append("（数据加载中...）")

    return chr(10).join(lines)


# ======================== Morning Analysis ========================

def morning_analysis():
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    lines = [f"# 📈 A股盘前分析 ({today_str})", ""]

    # ====== Key Summary ======
    lines.append("## 📋 数据摘要")
    lines.append("")

    # 1. Global indices
    lines.append("### 🌍 隔夜外盘")
    global_spot = safe_fetch(ak.index_global_spot_em)
    if global_spot is not None and not global_spot.empty:
        targets = ["道琼斯", "纳斯达克", "标普500", "恒生指数", "富时中国A50"]
        for _, row in global_spot.iterrows():
            name = str(row.get("名称", ""))
            for t in targets:
                if t in name:
                    latest = row.get("最新价", "")
                    chg = row.get("涨跌幅", "")
                    arr = trend_arrow(chg.replace("%", ""))
                    lines.append(f"  {arr} {name[:16]}: **{latest}** ({chg})")
                    break
    lines.append("")

    # 2. A-share indices
    lines.append("### 🏛 昨日A股收盘")
    a_spot = safe_fetch(ak.stock_zh_index_spot_em, symbol="上证系列指数")
    if a_spot is not None and not a_spot.empty:
        targets = {"上证指数", "深证成指", "创业板指", "科创50"}
        for _, row in a_spot.iterrows():
            name = str(row.get("名称", ""))
            if name in targets:
                latest = row.get("最新价", "")
                chg_pct = row.get("涨跌幅", "")
                chg_amt = row.get("涨跌额", "")
                arr = trend_arrow(chg_pct.replace("%", ""))
                lines.append(f"  {arr} {name}: **{latest}** ({chg_pct}, {chg_amt})")
    lines.append("")

    # 3. North-bound capital
    lines.append("### 💰 北向资金（昨日）")
    hsgt = safe_fetch(ak.stock_hsgt_fund_flow_summary_em)
    if hsgt is not None and not hsgt.empty:
        last = hsgt.iloc[0]
        sh = fmt_float(last.get("沪股通当日净流入(亿元)", ""))
        sz = fmt_float(last.get("深股通当日净流入(亿元)", ""))
        total = fmt_float(last.get("当日资金净流入(亿元)", ""))
        arr = trend_arrow(total)
        lines.append(f"  {arr} 沪股通: **{sh}亿** | 深股通: **{sz}亿** | 合计: **{total}亿**")
    lines.append("")

    # 4. 3-day sector flow trend analysis
    lines.append("### 🔁 8日资金流入板块 Top5")
    industry_flow = safe_fetch(ak.stock_fund_flow_industry, symbol="3日排行")
    if industry_flow is not None and not industry_flow.empty:
        for i, (_, row) in enumerate(industry_flow.head(5).iterrows(), 1):
            name = row.get("行业", "")
            net_inflow = row.get("主力净流入", "")
            col = "🟢" if "-" not in str(net_inflow) else "🔴"
            lines.append(f"  {i}. {col} {name}: **{net_inflow}**")
    lines.append("")

    # 5. News
    lines.append("### 📰 盘前重要消息")
    try:
        eco_news = safe_fetch(ak.news_economic_baidu, date=today.strftime("%Y%m%d"))
        if eco_news is not None and not eco_news.empty:
            for _, row in eco_news.head(4).iterrows():
                t = row.get("时间", "")
                content = row.get("内容", "")
                if t and content:
                    lines.append(f"  - ⏰{t} {str(content)[:40]}")
    except Exception:
        pass
    try:
        news_df = ak.stock_news_em(symbol="000001")
        if news_df is not None and not news_df.empty:
            for _, row in news_df.head(5).iterrows():
                title = str(row.get("新闻标题", ""))[:50]
                if title:
                    lines.append(f"  - {title}")
    except Exception:
        pass

    lines.append("")
    lines.append("---")
    lines.append("⚠️ *数据来源: 东方财富/同花顺/百度财经 | 仅供参考，不构成投资建议*")
    return truncate_msg(chr(10).join(lines))


# ======================== Evening Analysis ========================

def evening_analysis():
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    lines = [f"# 📊 A股盘后复盘 ({today_str})", ""]

    # ====== 1. Index Close ======
    lines.append("## 🏛 主要指数收盘")
    a_spot = safe_fetch(ak.stock_zh_index_spot_em, symbol="上证系列指数")
    if a_spot is not None and not a_spot.empty:
        targets = {"上证指数", "深证成指", "创业板指", "科创50"}
        for _, row in a_spot.iterrows():
            name = str(row.get("名称", ""))
            if name in targets:
                latest = row.get("最新价", "")
                chg_pct = row.get("涨跌幅", "")
                chg_amt = row.get("涨跌额", "")
                arr = trend_arrow(chg_pct.replace("%", ""))
                lines.append(f"  {arr} {name}: **{latest}** ({chg_pct}, {chg_amt})")
    lines.append("")

    # ====== 2. Sector Flow Trend Analysis (Today + Momentum) ======
    momentum = analyze_sector_momentum("行业资金流")
    lines.append(build_trend_section(momentum, "💰 行业板块资金流向分析"))
    lines.append("")

    # ====== 3. Today Top Inflow/Outflow ======
    today_data = momentum.get("all_data")

    # Verify yesterday recommendations against today data
    verification = verify_yesterday_recommendations(today_data)
    if verification:
        vr = build_hit_rate_section(verification)
        if vr:
            lines.append(vr)
            lines.append()

    if today_data is not None and not today_data.empty:
        lines.append("### 今日流入 Top8")
        for i, (_, row) in enumerate(today_data.head(8).iterrows(), 1):
            name = row.get("名称", "")
            net = fmt_float(row.get("主力净流入-净额", ""))
            chg = row.get("涨跌幅", "")
            arr = trend_arrow(chg)
            icon = flow_icon(net)
            lines.append(f"  {i}. {icon} {name}: **{net}亿** [{arr}{chg}]")
        lines.append("")

        lines.append("### 今日流出 Top5")
        for i, (_, row) in enumerate(today_data.tail(5).iterrows(), 1):
            name = row.get("名称", "")
            net = fmt_float(row.get("主力净流入-净额", ""))
            chg = row.get("涨跌幅", "")
            arr = trend_arrow(chg)
            lines.append(f"  {i}. 🔴 {name}: {net}亿 [{arr}{chg}]")
    lines.append("")

    # ====== 4. Concept Sector Top3 ======
    lines.append("## 🔥 概念板块资金 Top5")
    concept_flow = safe_fetch(ak.stock_sector_fund_flow_rank, indicator="今日", sector_type="概念资金流")
    if concept_flow is not None and not concept_flow.empty:
        for i, (_, row) in enumerate(concept_flow.head(5).iterrows(), 1):
            name = row.get("名称", "")
            net = fmt_float(row.get("主力净流入-净额", ""))
            chg = row.get("涨跌幅", "")
            lines.append(f"  {i}. {name}: **{net}亿** ({fmt_pct(chg)})")
    lines.append("")

    # ====== 5. Stock Picks from Top Inflow Sectors ======
    lines.append("## ⭐ 资金流入板块个股推荐")
    if today_data is not None and not today_data.empty:
        top_sectors = today_data.head(3)
        for _, sector_row in top_sectors.iterrows():
            sector_name = sector_row.get("名称", "")
            cons = safe_fetch(ak.stock_board_industry_cons_em, symbol=sector_name)
            if cons is not None and not cons.empty:
                # Sort by change descending to pick best performers
                cons_sorted = cons.sort_values(by="涨跌幅", ascending=False)
                lines.append(f"**{sector_name}**")
                cnt = 0
                for _, stock_row in cons_sorted.iterrows():
                    if cnt >= 2:
                        break
                    code = stock_row.get("代码", "")
                    sname = stock_row.get("名称", "")
                    price = stock_row.get("最新价", "")
                    chg = stock_row.get("涨跌幅", "")
                    arr = trend_arrow(chg)
                    lines.append(f"  {arr} {code} {sname}  ({price}, {chg})")
                    cnt += 1
    lines.append("")

    # ====== 6. Top Capital Inflow Stocks ======
    # Save recommendations for tomorrow verification
    try:
        _sector_picks = []
        if today_data is not None and not today_data.empty:
            for _, _sr in today_data.head(3).iterrows():
                _sn = _sr.get("名称", "")
                _cons = safe_fetch(ak.stock_board_industry_cons_em, symbol=_sn)
                _stocks = []
                if _cons is not None and not _cons.empty:
                    _sorted = _cons.sort_values(by="涨跌幅", ascending=False)
                    for _, _r in _sorted.head(2).iterrows():
                        _stocks.append((str(_r.get("代码","")), str(_r.get("名称","")), str(_r.get("最新价",""))))
                _sector_picks.append((_sn, _stocks))
        _stock_picks = []
        _mf = safe_fetch(ak.stock_main_fund_flow, symbol="全部股票")
        if _mf is not None and not _mf.empty:
            for _, _r in _mf.head(5).iterrows():
                _stock_picks.append((str(_r.get("代码","")), str(_r.get("名称","")), str(_r.get("主力净流入-净额",""))))
        save_recommendation(_sector_picks, _stock_picks)
    except Exception as _e:
        print(f"[WARN] save failed: {_e}")

    lines.append("## 🏆 主力净流入个股 Top5")
    main_flow = safe_fetch(ak.stock_main_fund_flow, symbol="全部股票")
    if main_flow is not None and not main_flow.empty:
        for i, (_, row) in enumerate(main_flow.head(5).iterrows(), 1):
            code = row.get("代码", "")
            name = row.get("名称", "")
            net = row.get("主力净流入-净额", "")
            lines.append(f"  {i}. {code} {name}: **{net}**")
    lines.append("")

    # ====== 7. Individual Stock Fund Flow ======
    lines.append("## 💸 今日个股资金净流入 Top5")
    ind_flow = safe_fetch(ak.stock_individual_fund_flow_rank, indicator="今日")
    if ind_flow is not None and not ind_flow.empty:
        for i, (_, row) in enumerate(ind_flow.head(5).iterrows(), 1):
            code = row.get("代码", "")
            name = row.get("名称", "")
            net = row.get("主力净流入-净额", "")
            chg = row.get("涨跌幅", "")
            lines.append(f"  {i}. {code} {name}: **{net}** ({fmt_pct(chg)})")
    lines.append("")

    # ====== 8. Limit-up Stocks ======
    lines.append("## 📈 昨日涨停股池")
    zt = safe_fetch(ak.stock_zt_pool_previous_em, date=today_str)
    if zt is not None and not zt.empty:
        for i, (_, row) in enumerate(zt.head(5).iterrows(), 1):
            code = row.get("代码", "")
            name = row.get("名称", "")
            lines.append(f"  {i}. {code} {name}")
    lines.append("")

    # ====== 9. News ======
    lines.append("## 📰 今日市场要闻")
    try:
        news_df = ak.stock_news_em(symbol="000001")
        if news_df is not None and not news_df.empty:
            for _, row in news_df.head(5).iterrows():
                title = str(row.get("新闻标题", ""))[:50]
                if title:
                    lines.append(f"  - {title}")
    except Exception:
        pass

    lines.append("")
    lines.append("---")
    lines.append("⚠️ *数据来源: 东方财富/同花顺 | 仅供参考，不构成投资建议*")
    return truncate_msg(chr(10).join(lines))


# ======================== Main ========================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] Mode: {mode}")

    if mode == "morning":
        msg = morning_analysis()
    elif mode == "evening":
        msg = evening_analysis()
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)

    byte_len = len(msg.encode("utf-8"))
    print(f"Message length: {byte_len} bytes")
    if byte_len > 0:
        send_wechat(msg)
    print("Done")
