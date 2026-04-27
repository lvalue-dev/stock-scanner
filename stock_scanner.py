"""
주식 스캐너 — 한국투자 Open API
RSI / MACD / 3봉 패턴 분석 후 Discord 알림
"""

import os
import json
import time
import math
import datetime
import requests

APP_KEY    = os.environ["KI_APP_KEY"]
APP_SECRET = os.environ["KI_APP_SECRET"]
DISCORD_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

API_BASE = "https://openapi.koreainvestment.com:9443"

STOCKS = [
    ("005930", "삼성전자"),   ("000660", "SK하이닉스"),  ("373220", "LG에너지솔루션"),
    ("207940", "삼성바이오로직스"), ("005380", "현대차"),  ("005490", "POSCO홀딩스"),
    ("051910", "LG화학"),     ("068270", "셀트리온"),    ("035720", "카카오"),
    ("035420", "NAVER"),      ("012330", "현대모비스"),  ("000270", "기아"),
    ("006400", "삼성SDI"),    ("105560", "KB금융"),      ("055550", "신한지주"),
    ("086790", "하나금융지주"), ("316140", "우리금융지주"), ("028260", "삼성물산"),
    ("015760", "한국전력"),   ("066570", "LG전자"),      ("034730", "SK"),
    ("017670", "SK텔레콤"),   ("030200", "KT"),          ("032830", "삼성생명"),
    ("009150", "삼성전기"),   ("003670", "포스코퓨처엠"), ("010130", "고려아연"),
    ("000810", "삼성화재"),   ("011070", "LG이노텍"),    ("033780", "KT&G"),
    ("096770", "SK이노베이션"), ("267250", "HD현대"),    ("329180", "HD현대중공업"),
    ("042700", "한미반도체"), ("000100", "유한양행"),    ("090430", "아모레퍼시픽"),
    ("047050", "포스코인터내셔널"), ("003550", "LG"),    ("086280", "현대글로비스"),
    ("024110", "기업은행"),   ("139480", "이마트"),      ("004020", "현대제철"),
    ("000720", "현대건설"),   ("011200", "HMM"),         ("014680", "한화솔루션"),
    ("009540", "HD한국조선해양"), ("010950", "S-Oil"),   ("018260", "삼성SDS"),
    ("161390", "한국타이어앤테크놀로지"), ("180640", "한진칼"),
]


# ── Technical Analysis ──────────────────────────────────────────────────────

def calc_ema(prices: list[float], period: int) -> float:
    if len(prices) < period:
        return prices[-1]
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def calc_rsi(prices: list[float], period: int = 14) -> float | None:
    if len(prices) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = prices[i] - prices[i - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(prices)):
        d = prices[i] - prices[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0)) / period
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def calc_macd(prices: list[float]) -> dict | None:
    if len(prices) < 35:
        return None
    macd_line = [
        calc_ema(prices[: i + 1], 12) - calc_ema(prices[: i + 1], 26)
        for i in range(25, len(prices))
    ]
    if len(macd_line) < 9:
        return None
    sig_line = [
        calc_ema(macd_line[: i + 1], 9) for i in range(8, len(macd_line))
    ]
    if len(sig_line) < 2:
        return None
    cm, pm = macd_line[-1], macd_line[-2]
    cs, ps = sig_line[-1], sig_line[-2]
    return {"golden_cross": pm <= ps and cm > cs, "macd": cm, "signal": cs}


def check_3_candle_rise(candles: list[dict]) -> bool:
    if len(candles) < 3:
        return False
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    return (
        c1["close"] > c1["open"]
        and c2["close"] > c2["open"]
        and c3["close"] > c3["open"]
        and c2["close"] > c1["close"]
        and c3["close"] > c2["close"]
    )


RSI_THRESHOLD = 40  # 30 → 40으로 완화 (극단적 과매도 → 약세 구간)

def analyze(price_data: dict) -> tuple[dict | None, str]:
    """(신호결과 | None, RSI 디버그 문자열) 반환"""
    raw = price_data.get("output2", [])
    if len(raw) < 15:
        return None, f"데이터 부족({len(raw)}일)"
    candles = [
        {
            "open": float(d["stck_oprc"]),
            "close": float(d["stck_clpr"]),
            "high": float(d["stck_hgpr"]),
            "low": float(d["stck_lwpr"]),
        }
        for d in reversed(raw)
    ]
    closes = [c["close"] for c in candles]
    rsi = calc_rsi(closes)
    macd_res = calc_macd(closes)
    rise3 = check_3_candle_rise(candles)
    rsi_tag = f"RSI={rsi:.1f}" if rsi is not None else "RSI=N/A"

    signals = []
    if rsi is not None and rsi <= RSI_THRESHOLD:
        signals.append(f"RSI과매도({rsi:.1f})")
    if macd_res and macd_res["golden_cross"]:
        signals.append("MACD골든크로스")
    if rise3:
        signals.append("3봉상승")
    if not signals:
        return None, rsi_tag

    confidence = min(99, len(signals) * 25 + (max(0, RSI_THRESHOLD - rsi) if rsi else 0))
    return {
        "price": closes[-1],
        "rsi": f"{rsi:.1f}" if rsi is not None else "N/A",
        "signals": signals,
        "confidence": int(confidence),
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
    start = today - datetime.timedelta(days=180)  # 6개월치 → MACD 계산 충분
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
        raise RuntimeError(f"API 오류 [{rt_cd}] {data.get('msg1', '')} / {data.get('msg_cd', '')}")
    return data


def send_discord(stock_code: str, stock_name: str, a: dict) -> None:
    if not DISCORD_URL:
        print("  ⚠️  DISCORD_WEBHOOK_URL 미설정 — 전송 건너뜀")
        return
    payload = {
        "embeds": [
            {
                "title": f"📊 {stock_name} ({stock_code})",
                "color": 0x00CC66,
                "fields": [
                    {"name": "가격", "value": f"{a['price']:,.0f}원", "inline": True},
                    {"name": "RSI", "value": a["rsi"], "inline": True},
                    {"name": "신뢰도", "value": f"{a['confidence']}%", "inline": True},
                    {"name": "신호", "value": ", ".join(a["signals"]), "inline": False},
                ],
                "timestamp": datetime.datetime.utcnow().isoformat(),
            }
        ]
    }
    res = requests.post(DISCORD_URL, json=payload, timeout=10)
    if not res.ok:
        print(f"  ⚠️  Discord 전송 실패 [{res.status_code}]: {res.text[:200]}")


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M}] 스캔 시작 — {len(STOCKS)}종목")
    print(f"Discord URL: {'설정됨' if DISCORD_URL else '미설정 (알림 없음)'}")
    token = get_token()
    print("토큰 발급 완료")

    hits = []
    for i, (code, name) in enumerate(STOCKS, 1):
        print(f"[{i:2d}/{len(STOCKS)}] {name} 분석 중...", end=" ")
        try:
            data = fetch_daily_price(token, code)
            result, debug = analyze(data)
            if result:
                print(f"🎯 신호: {', '.join(result['signals'])} ({debug})")
                hits.append((code, name, result))
                send_discord(code, name, result)
            else:
                print(f"신호 없음 ({debug})")
            time.sleep(0.25)
        except Exception as e:
            print(f"⚠️  오류: {e}")

    print(f"\n완료 — 신호 {len(hits)}개")
    for code, name, r in hits:
        print(f"  {name}({code}): {r['price']:,.0f}원 | {', '.join(r['signals'])} | 신뢰도 {r['confidence']}%")


if __name__ == "__main__":
    main()
