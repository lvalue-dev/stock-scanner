"""
주식 스캐너 — 한국투자 Open API
종합 기술적 분석: RSI, MACD, 볼린저밴드, 이평선, 스토캐스틱, 거래량, 지지/저항
매수·매도 구간, 목표가, 손절가, 종합점수(0-100) 산출 후 Discord 알림
"""

import os
import json
import time
import datetime
import requests

APP_KEY    = os.environ["KI_APP_KEY"]
APP_SECRET = os.environ["KI_APP_SECRET"]
DISCORD_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

API_BASE = "https://openapi.koreainvestment.com:9443"

STOCKS = [
    ("005930", "삼성전자"),    ("000660", "SK하이닉스"),   ("373220", "LG에너지솔루션"),
    ("207940", "삼성바이오로직스"), ("005380", "현대차"),   ("005490", "POSCO홀딩스"),
    ("051910", "LG화학"),      ("068270", "셀트리온"),     ("035720", "카카오"),
    ("035420", "NAVER"),       ("012330", "현대모비스"),   ("000270", "기아"),
    ("006400", "삼성SDI"),     ("105560", "KB금융"),       ("055550", "신한지주"),
    ("086790", "하나금융지주"), ("316140", "우리금융지주"), ("028260", "삼성물산"),
    ("015760", "한국전력"),    ("066570", "LG전자"),       ("034730", "SK"),
    ("017670", "SK텔레콤"),    ("030200", "KT"),           ("032830", "삼성생명"),
    ("009150", "삼성전기"),    ("003670", "포스코퓨처엠"),  ("010130", "고려아연"),
    ("000810", "삼성화재"),    ("011070", "LG이노텍"),     ("033780", "KT&G"),
    ("096770", "SK이노베이션"), ("267250", "HD현대"),      ("329180", "HD현대중공업"),
    ("042700", "한미반도체"),  ("000100", "유한양행"),     ("090430", "아모레퍼시픽"),
    ("047050", "포스코인터내셔널"), ("003550", "LG"),      ("086280", "현대글로비스"),
    ("024110", "기업은행"),    ("139480", "이마트"),       ("004020", "현대제철"),
    ("000720", "현대건설"),    ("011200", "HMM"),          ("014680", "한화솔루션"),
    ("009540", "HD한국조선해양"), ("010950", "S-Oil"),    ("018260", "삼성SDS"),
    ("161390", "한국타이어앤테크놀로지"), ("180640", "한진칼"),
]

# ── Technical Analysis ──────────────────────────────────────────────────────

def calc_ema(prices: list, period: int) -> float:
    if len(prices) < period:
        return prices[-1]
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def calc_rsi(prices: list, period: int = 14) -> float | None:
    if len(prices) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = prices[i] - prices[i - 1]
        if d > 0: gains += d
        else: losses -= d
    avg_g, avg_l = gains / period, losses / period
    for i in range(period + 1, len(prices)):
        d = prices[i] - prices[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0)) / period
    return 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)


def calc_macd(prices: list) -> dict | None:
    if len(prices) < 35:
        return None
    macd_line = [calc_ema(prices[:i+1], 12) - calc_ema(prices[:i+1], 26)
                 for i in range(25, len(prices))]
    if len(macd_line) < 9:
        return None
    sig_line = [calc_ema(macd_line[:i+1], 9) for i in range(8, len(macd_line))]
    if len(sig_line) < 2:
        return None
    cm, pm = macd_line[-1], macd_line[-2]
    cs, ps = sig_line[-1], sig_line[-2]
    return {"golden_cross": pm <= ps and cm > cs, "macd": cm, "signal": cs,
            "histogram": cm - cs}


def calc_bollinger(prices: list, period: int = 20, mult: float = 2.0) -> dict | None:
    if len(prices) < period:
        return None
    sma = sum(prices[-period:]) / period
    std = (sum((p - sma) ** 2 for p in prices[-period:]) / period) ** 0.5
    upper, lower = sma + mult * std, sma - mult * std
    cur = prices[-1]
    pos = (cur - lower) / (upper - lower) if upper != lower else 0.5
    return {"upper": round(upper), "middle": round(sma), "lower": round(lower),
            "position": pos, "width": round((upper - lower) / sma * 100, 1)}


def calc_moving_averages(prices: list) -> dict:
    result = {}
    for p in [5, 20, 60, 120]:
        if len(prices) >= p:
            result[f"ma{p}"] = round(sum(prices[-p:]) / p)
    if all(f"ma{p}" in result for p in [5, 20, 60]):
        m5, m20, m60 = result["ma5"], result["ma20"], result["ma60"]
        if m5 > m20 > m60:
            result["alignment"] = "정배열"
        elif m5 < m20 < m60:
            result["alignment"] = "역배열"
        else:
            result["alignment"] = "혼조"
    else:
        result["alignment"] = "N/A"
    return result


def calc_stochastic(candles: list, k_period: int = 14, d_period: int = 3) -> dict | None:
    if len(candles) < k_period + d_period:
        return None
    k_vals = []
    for i in range(len(candles) - k_period - d_period + 1, len(candles) - k_period + 1):
        if i < 0:
            continue
        sub = candles[i:i + k_period]
        lo, hi = min(c["low"] for c in sub), max(c["high"] for c in sub)
        k_vals.append(50.0 if hi == lo else 100 * (sub[-1]["close"] - lo) / (hi - lo))
    if not k_vals:
        return None
    k = k_vals[-1]
    d = sum(k_vals[-d_period:]) / min(d_period, len(k_vals))
    return {"k": round(k, 1), "d": round(d, 1),
            "oversold": k < 20, "overbought": k > 80}


def find_support_resistance(closes: list, window: int = 5) -> dict:
    supports, resistances = [], []
    for i in range(window, len(closes) - window):
        lo = min(closes[i - window:i + window + 1])
        hi = max(closes[i - window:i + window + 1])
        if closes[i] == lo:
            supports.append(closes[i])
        if closes[i] == hi:
            resistances.append(closes[i])
    cur = closes[-1]
    below = sorted(set(round(s) for s in supports if s < cur), reverse=True)[:3]
    above = sorted(set(round(r) for r in resistances if r > cur))[:3]
    return {"support": below, "resistance": above}


def analyze_volume(candles: list, period: int = 20) -> dict | None:
    if len(candles) < period:
        return None
    vols = [c["volume"] for c in candles]
    avg = sum(vols[-period:]) / period
    if avg == 0:
        return None
    cur = vols[-1]
    ratio = cur / avg
    return {"avg": int(avg), "current": int(cur),
            "ratio": round(ratio, 2), "surge": ratio > 1.5}


def check_3_candle_rise(candles: list) -> bool:
    if len(candles) < 3:
        return False
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    return (c1["close"] > c1["open"] and c2["close"] > c2["open"] and
            c3["close"] > c3["open"] and c2["close"] > c1["close"] and
            c3["close"] > c2["close"])


# ── Comprehensive Analysis ──────────────────────────────────────────────────

def analyze(price_data: dict) -> tuple[dict | None, str]:
    raw = price_data.get("output2", [])
    if len(raw) < 20:
        return None, f"데이터 부족({len(raw)}일)"

    candles = [
        {"open": float(d["stck_oprc"]), "close": float(d["stck_clpr"]),
         "high": float(d["stck_hgpr"]), "low": float(d["stck_lwpr"]),
         "volume": int(d.get("acml_vol", 0))}
        for d in reversed(raw)
    ]
    closes = [c["close"] for c in candles]
    cur = closes[-1]
    prev_close = closes[-2] if len(closes) > 1 else cur
    change_pct = (cur - prev_close) / prev_close * 100

    rsi       = calc_rsi(closes)
    macd_res  = calc_macd(closes)
    boll      = calc_bollinger(closes)
    mas       = calc_moving_averages(closes)
    stoch     = calc_stochastic(candles)
    sr        = find_support_resistance(closes)
    vol       = analyze_volume(candles)
    rise3     = check_3_candle_rise(candles)

    # ── Scoring (기준: 50 = 중립) ──
    score = 50
    signals = []

    # RSI (최대 ±20)
    if rsi is not None:
        if   rsi <= 25: score += 20; signals.append(f"RSI극과매도({rsi:.0f})")
        elif rsi <= 35: score += 14; signals.append(f"RSI강과매도({rsi:.0f})")
        elif rsi <= 40: score +=  8; signals.append(f"RSI과매도({rsi:.0f})")
        elif rsi >= 75: score -= 18; signals.append(f"RSI과매수({rsi:.0f})")
        elif rsi >= 65: score -=  8

    # MACD (최대 ±15)
    if macd_res:
        if macd_res["golden_cross"]:
            score += 15; signals.append("MACD골든크로스")
        elif macd_res["histogram"] > 0:
            score += 5
        elif macd_res["macd"] < 0 and macd_res["histogram"] < 0:
            score -= 10; signals.append("MACD데드크로스")

    # Bollinger Band (최대 ±15)
    if boll:
        pos = boll["position"]
        if   pos < 0.05: score += 15; signals.append("볼린저하단돌파")
        elif pos < 0.15: score += 10; signals.append("볼린저하단근접")
        elif pos < 0.25: score +=  4
        elif pos > 0.95: score -= 12; signals.append("볼린저상단돌파")
        elif pos > 0.85: score -=  5

    # MA 배열 (최대 ±12)
    alignment = mas.get("alignment", "N/A")
    if alignment == "정배열":
        score += 12; signals.append("이평선정배열")
    elif alignment == "역배열":
        score -= 10; signals.append("이평선역배열")

    # MA5 vs MA20 단기 크로스 (최대 ±6)
    ma5, ma20 = mas.get("ma5"), mas.get("ma20")
    if ma5 and ma20:
        if   ma5 > ma20 * 1.005: score += 6; signals.append("단기MA상향돌파")
        elif ma5 < ma20 * 0.995: score -= 5

    # Stochastic (최대 ±10)
    if stoch:
        if   stoch["oversold"]:   score += 10; signals.append(f"스토캐스틱과매도({stoch['k']:.0f})")
        elif stoch["overbought"]: score -=  8; signals.append(f"스토캐스틱과매수({stoch['k']:.0f})")

    # 3봉 연속 상승 (+8)
    if rise3:
        score += 8; signals.append("3봉연속상승")

    # 거래량 급증 (+5)
    if vol and vol["surge"]:
        score += 5; signals.append(f"거래량급증({vol['ratio']:.1f}배)")

    score = max(0, min(100, score))
    rsi_tag = f"RSI={rsi:.1f}" if rsi is not None else "RSI=N/A"

    if not signals:
        return None, rsi_tag

    # ── 매수·매도 구간 계산 ──
    support    = sr.get("support", [])
    resistance = sr.get("resistance", [])

    buy_low  = round((support[0] * 0.99) if support else cur * 0.97)
    buy_high = round((boll["middle"] * 1.005 if boll else cur * 1.02))
    sell_low  = round((resistance[0] * 0.99) if resistance else cur * 1.04)
    sell_high = round(boll["upper"] if boll else (resistance[0] * 1.02 if resistance else cur * 1.08))
    stop_loss = round((support[1] * 0.98) if len(support) > 1 else
                      (support[0] * 0.96 if support else cur * 0.94))
    target    = sell_high
    upside    = round((target - cur) / cur * 100, 1)
    downside  = round((cur - stop_loss) / cur * 100, 1)

    # ── 예측 텍스트 ──
    if   score >= 78: pred = "강한 매수 신호 🟢"
    elif score >= 65: pred = "매수 고려 📈"
    elif score >= 58: pred = "상승 가능성 (관망) 👀"
    elif score <= 35: pred = "매도 신호 🔴"
    elif score <= 45: pred = "매도 고려 📉"
    else:             pred = "중립 ➡️"

    return {
        "price":        cur,
        "change_pct":   round(change_pct, 2),
        "rsi":          f"{rsi:.1f}" if rsi else "N/A",
        "score":        score,
        "prediction":   pred,
        "signals":      signals,
        # MACD
        "macd_value":   round(macd_res["macd"]) if macd_res else None,
        "macd_hist":    round(macd_res["histogram"]) if macd_res else None,
        "macd_golden":  macd_res["golden_cross"] if macd_res else False,
        # Bollinger
        "boll_upper":   boll["upper"]  if boll else None,
        "boll_lower":   boll["lower"]  if boll else None,
        "boll_pos_pct": round(boll["position"] * 100) if boll else None,
        "boll_width":   boll["width"]  if boll else None,
        # Moving Averages
        "ma5":    mas.get("ma5"),
        "ma20":   mas.get("ma20"),
        "ma60":   mas.get("ma60"),
        "ma120":  mas.get("ma120"),
        "alignment": alignment,
        # Stochastic
        "stoch_k": stoch["k"] if stoch else None,
        "stoch_d": stoch["d"] if stoch else None,
        # Volume
        "vol_ratio": vol["ratio"] if vol else None,
        "vol_surge": vol["surge"] if vol else False,
        # Support / Resistance
        "support":    support[:2],
        "resistance": resistance[:2],
        # Zones
        "buy_zone_min":  buy_low,
        "buy_zone_max":  buy_high,
        "sell_zone_min": sell_low,
        "sell_zone_max": sell_high,
        "stop_loss":     stop_loss,
        "target_price":  target,
        "upside_pct":    upside,
        "downside_pct":  downside,
    }, rsi_tag


# ── API Calls ───────────────────────────────────────────────────────────────

def get_token() -> str:
    res = requests.post(
        f"{API_BASE}/oauth2/tokenP",
        json={"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET},
        timeout=10,
    )
    res.raise_for_status()
    data = res.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"토큰 없음: {data}")
    return token


def fetch_daily_price(token: str, code: str) -> dict:
    today = datetime.date.today()
    start = today - datetime.timedelta(days=180)
    res = requests.get(
        f"{API_BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
        params={
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": code,
            "fid_input_date_1": start.strftime("%Y%m%d"),
            "fid_input_date_2": today.strftime("%Y%m%d"),
            "fid_period_div_code": "D",
            "fid_org_adj_prc": "0",
        },
        headers={
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY,
            "appsecret": APP_SECRET,
            "tr_id": "FHKST03010100",
            "custtype": "P",
        },
        timeout=15,
    )
    res.raise_for_status()
    data = res.json()
    rt_cd = data.get("rt_cd", "?")
    if rt_cd != "0":
        raise RuntimeError(f"API [{rt_cd}] {data.get('msg1', '')} / {data.get('msg_cd', '')}")
    return data


def send_discord(code: str, name: str, a: dict) -> None:
    if not DISCORD_URL:
        print("  ⚠️  DISCORD_WEBHOOK_URL 미설정")
        return

    score = a["score"]
    color = (0x00CC66 if score >= 65 else 0xFFAA00 if score >= 55 else 0xFF4444)

    def pf(v): return f"{int(v):,}원" if v else "N/A"

    fields = [
        {"name": "💰 현재가",   "value": f"{pf(a['price'])} ({a['change_pct']:+.1f}%)", "inline": True},
        {"name": "🏆 종합점수", "value": f"**{score}/100**",         "inline": True},
        {"name": "🔮 예측",     "value": a["prediction"],             "inline": True},
        {"name": "📊 RSI",      "value": a["rsi"],                    "inline": True},
        {"name": "📉 MACD",     "value": f"{a['macd_value']:+,}" if a["macd_value"] else "N/A", "inline": True},
        {"name": "⚡ 스토캐스틱","value": f"K={a['stoch_k']} D={a['stoch_d']}" if a["stoch_k"] else "N/A", "inline": True},
        {"name": "🟢 매수구간", "value": f"{pf(a['buy_zone_min'])} ~ {pf(a['buy_zone_max'])}", "inline": True},
        {"name": "🔴 매도구간", "value": f"{pf(a['sell_zone_min'])} ~ {pf(a['sell_zone_max'])}", "inline": True},
        {"name": "🛡️ 손절가",  "value": f"{pf(a['stop_loss'])} (-{a['downside_pct']}%)", "inline": True},
        {"name": "🎯 목표가",   "value": f"{pf(a['target_price'])} (+{a['upside_pct']}%)", "inline": True},
        {"name": "📈 이평선",   "value": (
            f"MA5={pf(a['ma5'])} MA20={pf(a['ma20'])} MA60={pf(a['ma60'])} [{a['alignment']}]"
            if a.get("ma5") else "N/A"
        ), "inline": False},
        {"name": "🔔 신호",     "value": "\n".join(f"• {s}" for s in a["signals"]) or "없음", "inline": False},
    ]
    if a.get("support"):
        fields.append({"name": "🔵 지지구간", "value": " / ".join(pf(s) for s in a["support"]), "inline": True})
    if a.get("resistance"):
        fields.append({"name": "🔶 저항구간", "value": " / ".join(pf(r) for r in a["resistance"]), "inline": True})

    payload = {"embeds": [{"title": f"📊 {name} ({code})", "color": color,
                           "fields": fields, "timestamp": datetime.datetime.utcnow().isoformat()}]}
    res = requests.post(DISCORD_URL, json=payload, timeout=10)
    if not res.ok:
        print(f"  ⚠️  Discord 실패 [{res.status_code}]: {res.text[:150]}")


# ── JSON Output ─────────────────────────────────────────────────────────────

def save_results_json(hits: list, now: datetime.datetime) -> None:
    os.makedirs("docs/data", exist_ok=True)
    payload = {
        "scan_time": now.strftime("%Y-%m-%d %H:%M"),
        "total_scanned": len(STOCKS),
        "signal_count": len(hits),
        "signals": [{"code": c, "name": n, **r} for c, n, r in hits],
    }
    with open("docs/data/results.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("📄 docs/data/results.json 저장됨")


def append_signals_log(hits: list, now: datetime.datetime) -> None:
    os.makedirs("docs/data", exist_ok=True)
    path = "docs/data/signals_log.json"
    try:
        with open(path, encoding="utf-8") as f:
            log = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    for code, name, r in hits:
        log.append({
            "date":       now.strftime("%Y-%m-%d"),
            "time":       now.strftime("%H:%M"),
            "code":       code,
            "name":       name,
            "score":      r["score"],
            "prediction": r["prediction"],
            "signals":    r["signals"],
            "price":      r["price"],
            "change_pct": r.get("change_pct", 0),
            "target_price": r.get("target_price"),
            "upside_pct":   r.get("upside_pct"),
        })

    log = log[-1000:]  # 최대 1000건 유지
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print("📄 docs/data/signals_log.json 업데이트됨")


def fetch_market_ranking(token: str, market: str, rank_type: str) -> list:
    """등락률 순위 조회 (rank_type: 'up'=상승, 'dn'=하락)
    market: 'J'=KOSPI, 'Q'=KOSDAQ
    """
    # KOSDAQ은 별도 스크린 코드 사용
    scr_code = "261" if market == "Q" else "211"
    headers = {
        "Authorization": f"Bearer {token}",
        "appkey": APP_KEY, "appsecret": APP_SECRET,
        "tr_id": "FHPST01710000", "custtype": "P",
    }
    params = {
        "fid_rsfl_rate2": "", "fid_cond_mrkt_div_code": market,
        "fid_cond_scr_div_code": scr_code, "fid_input_iscd": "0000",
        "fid_rank_sort_cls_code": "0" if rank_type == "up" else "1",
        "fid_input_cnt_1": "0", "fid_prc_cls_code": "1",
        "fid_input_price_1": "", "fid_input_price_2": "",
        "fid_vol_cnt": "", "fid_trgt_cls_code": "0",
        "fid_trgt_exls_cls_code": "0", "fid_div_cls_code": "0",
        "fid_rsfl_rate1": "",
    }
    try:
        r = requests.get(f"{API_BASE}/uapi/domestic-stock/v1/ranking/fluctuation",
                         headers=headers, params=params, timeout=10)
        d = r.json()
        if d.get("rt_cd") != "0":
            print(f"  ⚠️  등락률순위({market}/{rank_type}) rt_cd={d.get('rt_cd')} msg={d.get('msg1')}")
            return []
        result = d.get("output", [])[:30]
        print(f"  ✅  등락률순위({market}/{rank_type}) {len(result)}개")
        return result
    except Exception as e:
        print(f"  ⚠️  등락률순위({market}/{rank_type}) 오류: {e}")
        return []


def fetch_volume_ranking(token: str, market: str) -> list:
    """거래량 순위 조회"""
    # KOSDAQ은 별도 스크린 코드 사용
    scr_code = "20172" if market == "Q" else "20171"
    headers = {
        "Authorization": f"Bearer {token}",
        "appkey": APP_KEY, "appsecret": APP_SECRET,
        "tr_id": "FHPST01710000", "custtype": "P",
    }
    params = {
        "fid_cond_mrkt_div_code": market, "fid_cond_scr_div_code": scr_code,
        "fid_input_iscd": "0000", "fid_rank_sort_cls_code": "0",
        "fid_input_cnt_1": "0", "fid_prc_cls_code": "0",
        "fid_input_price_1": "", "fid_input_price_2": "",
        "fid_vol_cnt": "150000", "fid_trgt_cls_code": "111111111",
        "fid_trgt_exls_cls_code": "000000", "fid_div_cls_code": "0",
        "fid_input_date_1": "",
    }
    try:
        r = requests.get(f"{API_BASE}/uapi/domestic-stock/v1/ranking/volume",
                         headers=headers, params=params, timeout=10)
        d = r.json()
        if d.get("rt_cd") != "0":
            print(f"  ⚠️  거래량순위({market}) rt_cd={d.get('rt_cd')} msg={d.get('msg1')}")
            return []
        result = d.get("output", [])[:30]
        print(f"  ✅  거래량순위({market}) {len(result)}개")
        return result
    except Exception as e:
        print(f"  ⚠️  거래량순위({market}) 오류: {e}")
        return []


def save_market_ranking_json(token: str, now: datetime.datetime) -> None:
    """KOSPI/KOSDAQ 상승·하락·거래량 순위 저장"""
    print("📊 시장 랭킹 조회 중...")
    ranking = {
        "update_time": now.strftime("%Y-%m-%d %H:%M"),
        "kospi": {
            "up":  fetch_market_ranking(token, "J", "up"),
            "dn":  fetch_market_ranking(token, "J", "dn"),
            "vol": fetch_volume_ranking(token, "J"),
        },
        "kosdaq": {
            "up":  fetch_market_ranking(token, "Q", "up"),
            "dn":  fetch_market_ranking(token, "Q", "dn"),
            "vol": fetch_volume_ranking(token, "Q"),
        },
    }
    with open("docs/data/market_ranking.json", "w", encoding="utf-8") as f:
        json.dump(ranking, f, ensure_ascii=False, indent=2)
    print("📄 docs/data/market_ranking.json 저장됨")


def save_portfolio_json(price_map: dict, now: datetime.datetime) -> None:
    os.makedirs("docs/data", exist_ok=True)
    try:
        with open("portfolio_config.json", encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        return

    holdings, total_inv, total_cur = [], 0, 0
    for h in cfg.get("holdings", []):
        code, qty, avg = h["code"], h["qty"], h["avg_price"]
        cur = price_map.get(code, h.get("last_price", avg))
        inv = qty * avg
        pnl = qty * cur - inv
        holdings.append({**h, "current_price": cur,
                         "pnl": round(pnl), "pnl_pct": round(pnl / inv * 100, 2) if inv else 0})
        total_inv += inv
        total_cur += qty * cur

    total_pnl = total_cur - total_inv
    payload = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "total_invested": round(total_inv),
        "total_current":  round(total_cur),
        "total_pnl":      round(total_pnl),
        "total_pnl_pct":  round(total_pnl / total_inv * 100, 2) if total_inv else 0,
        "holdings": holdings,
    }
    with open("docs/data/portfolio.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("📄 docs/data/portfolio.json 저장됨")


def send_discord_summary(hits: list, now: datetime.datetime) -> None:
    if not DISCORD_URL or not hits:
        return
    lines = [f"• {n} ({c})  점수 {r['score']}  {r['prediction'].split()[0]}  목표 {r.get('target_price',0):,}원"
             for c, n, r in hits[:10]]
    payload = {"embeds": [{"title": f"📊 [{now:%m/%d %H:%M}] 스캔 완료 — 신호 {len(hits)}개",
                           "color": 0x8080FF,
                           "description": "\n".join(lines)}]}
    res = requests.post(DISCORD_URL, json=payload, timeout=10)
    if not res.ok:
        print(f"  ⚠️  요약 Discord 실패 [{res.status_code}]")


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    now = datetime.datetime.now()
    print(f"[{now:%Y-%m-%d %H:%M}] 스캔 시작 — {len(STOCKS)}종목")
    print(f"Discord URL: {'설정됨' if DISCORD_URL else '미설정 (알림 없음)'}")
    token = get_token()
    print("토큰 발급 완료\n")

    hits, price_map = [], {}
    for i, (code, name) in enumerate(STOCKS, 1):
        print(f"[{i:2d}/{len(STOCKS)}] {name:20s}", end=" ")
        try:
            data = fetch_daily_price(token, code)
            result, debug = analyze(data)
            if result:
                stars = "★" * (1 + result["score"] // 25)
                print(f"🎯 점수={result['score']:3d} {stars}  {debug}  {', '.join(result['signals'][:3])}")
                hits.append((code, name, result))
                price_map[code] = result["price"]
                send_discord(code, name, result)
            else:
                # 가격은 기록 (포트폴리오 현재가 업데이트용)
                raw = data.get("output2", [])
                if raw:
                    price_map[code] = float(raw[0].get("stck_clpr") or 0)
                print(f"신호 없음  ({debug})")
            time.sleep(0.25)
        except Exception as e:
            print(f"⚠️  오류: {e}")

    hits.sort(key=lambda x: x[2]["score"], reverse=True)
    print(f"\n{'─'*60}")
    print(f"완료 — 신호 {len(hits)}개 발견")
    if hits:
        print(f"\n{'순위':4} {'종목':12} {'점수':6} {'현재가':10} {'목표가':10} {'상승여력':8} 예측")
        print("─" * 70)
        for rank, (code, name, r) in enumerate(hits, 1):
            print(f"{rank:4d} {name:12s} {r['score']:6d} {r['price']:10,.0f} "
                  f"{r['target_price']:10,.0f} {r['upside_pct']:+6.1f}%  {r['prediction']}")

    # JSON 저장 (GitHub Pages 대시보드용)
    save_results_json(hits, now)
    append_signals_log(hits, now)
    save_portfolio_json(price_map, now)
    save_market_ranking_json(token, now)
    send_discord_summary(hits, now)


if __name__ == "__main__":
    main()
