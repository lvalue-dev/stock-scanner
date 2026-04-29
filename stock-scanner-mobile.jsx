import { useState, useRef, useCallback, useEffect } from "react";

const API_BASE = "https://openapi.koreainvestment.com:9443";
const RT_INTERVAL = 30000; // 30초마다 현재가 갱신

const STOCKS = [
  { code: "005930", name: "삼성전자" },
  { code: "000660", name: "SK하이닉스" },
  { code: "373220", name: "LG에너지솔루션" },
  { code: "207940", name: "삼성바이오로직스" },
  { code: "005380", name: "현대차" },
  { code: "005490", name: "POSCO홀딩스" },
  { code: "051910", name: "LG화학" },
  { code: "068270", name: "셀트리온" },
  { code: "035720", name: "카카오" },
  { code: "035420", name: "NAVER" },
  { code: "012330", name: "현대모비스" },
  { code: "000270", name: "기아" },
  { code: "006400", name: "삼성SDI" },
  { code: "105560", name: "KB금융" },
  { code: "055550", name: "신한지주" },
  { code: "086790", name: "하나금융지주" },
  { code: "316140", name: "우리금융지주" },
  { code: "028260", name: "삼성물산" },
  { code: "015760", name: "한국전력" },
  { code: "066570", name: "LG전자" },
  { code: "034730", name: "SK" },
  { code: "017670", name: "SK텔레콤" },
  { code: "030200", name: "KT" },
  { code: "032830", name: "삼성생명" },
  { code: "009150", name: "삼성전기" },
  { code: "003670", name: "포스코퓨처엠" },
  { code: "010130", name: "고려아연" },
  { code: "000810", name: "삼성화재" },
  { code: "011070", name: "LG이노텍" },
  { code: "033780", name: "KT&G" },
  { code: "096770", name: "SK이노베이션" },
  { code: "267250", name: "HD현대" },
  { code: "329180", name: "HD현대중공업" },
  { code: "042700", name: "한미반도체" },
  { code: "000100", name: "유한양행" },
  { code: "090430", name: "아모레퍼시픽" },
  { code: "047050", name: "포스코인터내셔널" },
  { code: "003550", name: "LG" },
  { code: "086280", name: "현대글로비스" },
  { code: "024110", name: "기업은행" },
  { code: "139480", name: "이마트" },
  { code: "004020", name: "현대제철" },
  { code: "000720", name: "현대건설" },
  { code: "011200", name: "HMM" },
  { code: "014680", name: "한화솔루션" },
  { code: "009540", name: "HD한국조선해양" },
  { code: "010950", name: "S-Oil" },
  { code: "018260", name: "삼성SDS" },
  { code: "161390", name: "한국타이어앤테크놀로지" },
  { code: "180640", name: "한진칼" },
];

// ── Technical Analysis ─────────────────────────────────────────────────────

function calcEMA(prices, period) {
  if (prices.length < period) return prices[prices.length - 1];
  const k = 2 / (period + 1);
  let ema = prices.slice(0, period).reduce((a, b) => a + b) / period;
  for (let i = period; i < prices.length; i++) {
    ema = prices[i] * k + ema * (1 - k);
  }
  return ema;
}

function calcRSI(prices, period = 14) {
  if (prices.length < period + 1) return null;
  let gains = 0, losses = 0;
  for (let i = 1; i <= period; i++) {
    const d = prices[i] - prices[i - 1];
    if (d > 0) gains += d;
    else losses -= d;
  }
  let avgGain = gains / period;
  let avgLoss = losses / period;
  for (let i = period + 1; i < prices.length; i++) {
    const d = prices[i] - prices[i - 1];
    avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
  }
  if (avgLoss === 0) return 100;
  return 100 - 100 / (1 + avgGain / avgLoss);
}

function calcMACD(prices) {
  if (prices.length < 35) return null;
  const macdLine = [];
  for (let i = 25; i < prices.length; i++) {
    const s = prices.slice(0, i + 1);
    macdLine.push(calcEMA(s, 12) - calcEMA(s, 26));
  }
  if (macdLine.length < 9) return null;
  const signalLine = [];
  for (let i = 8; i < macdLine.length; i++) {
    signalLine.push(calcEMA(macdLine.slice(0, i + 1), 9));
  }
  if (signalLine.length < 2) return null;
  const curMACD = macdLine[macdLine.length - 1];
  const prevMACD = macdLine[macdLine.length - 2];
  const curSig = signalLine[signalLine.length - 1];
  const prevSig = signalLine[signalLine.length - 2];
  return {
    goldenCross: prevMACD <= prevSig && curMACD > curSig,
    macd: curMACD,
    signal: curSig,
  };
}

function check3CandleRise(candles) {
  if (candles.length < 3) return false;
  const [c1, c2, c3] = candles.slice(-3);
  return (
    c1.close > c1.open &&
    c2.close > c2.open &&
    c3.close > c3.open &&
    c2.close > c1.close &&
    c3.close > c2.close
  );
}

const RSI_THRESHOLD = 40;

function isMarketOpen() {
  const now = new Date();
  const kst = new Date(now.getTime() + 9 * 3600 * 1000);
  const day = kst.getUTCDay();
  const t = kst.getUTCHours() * 100 + kst.getUTCMinutes();
  return day >= 1 && day <= 5 && t >= 900 && t < 1531;
}

function analyzeStock(priceData) {
  const raw = priceData?.output2;
  if (!raw || raw.length < 15) return null;

  const candles = [...raw].reverse().map((d) => ({
    open: parseFloat(d.stck_oprc),
    close: parseFloat(d.stck_clpr),
    high: parseFloat(d.stck_hgpr),
    low: parseFloat(d.stck_lwpr),
  }));

  const closes = candles.map((c) => c.close);
  const rsi = calcRSI(closes);
  const macdResult = calcMACD(closes);
  const threeCandle = check3CandleRise(candles);

  const signals = [];
  if (rsi !== null && rsi <= RSI_THRESHOLD) signals.push(`RSI과매도(${rsi.toFixed(1)})`);
  if (macdResult?.goldenCross) signals.push("MACD골든크로스");
  if (threeCandle) signals.push("3봉상승");
  if (signals.length === 0) return null;

  const confidence = Math.min(
    99,
    signals.length * 25 + (rsi !== null ? Math.max(0, RSI_THRESHOLD - rsi) : 0)
  );

  return {
    price: closes[closes.length - 1],
    rsi: rsi?.toFixed(1) ?? "N/A",
    signals,
    confidence: confidence.toFixed(0),
  };
}

async function sendDiscord(webhookUrl, stock, analysis) {
  await fetch(webhookUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      embeds: [
        {
          title: `📊 ${stock.name} (${stock.code})`,
          color: 0x00cc66,
          fields: [
            {
              name: "가격",
              value: `${analysis.price.toLocaleString()}원`,
              inline: true,
            },
            { name: "RSI", value: analysis.rsi, inline: true },
            { name: "신뢰도", value: `${analysis.confidence}%`, inline: true },
            {
              name: "신호",
              value: analysis.signals.join(", "),
              inline: false,
            },
          ],
          timestamp: new Date().toISOString(),
        },
      ],
    }),
  });
}

// ── Component ──────────────────────────────────────────────────────────────

const S = {
  wrap: {
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    maxWidth: 480,
    margin: "0 auto",
    background: "#0d0d1f",
    minHeight: "100vh",
    color: "#dde1f0",
  },
  header: {
    background: "linear-gradient(135deg,#1a1a40,#2a2a60)",
    padding: "18px 16px 14px",
    borderBottom: "1px solid #2a2a4a",
  },
  title: { fontSize: 20, fontWeight: 700, color: "#8080ff", margin: 0 },
  sub: { fontSize: 12, color: "#6668aa", marginTop: 4 },
  tabs: {
    display: "flex",
    background: "#12122a",
    borderBottom: "1px solid #2a2a4a",
  },
  tab: (a) => ({
    flex: 1,
    padding: "12px 4px",
    fontSize: 13,
    fontWeight: a ? 700 : 400,
    color: a ? "#8080ff" : "#666",
    background: "none",
    border: "none",
    borderBottom: a ? "2px solid #8080ff" : "2px solid transparent",
    cursor: "pointer",
  }),
  body: { padding: 16 },
  label: { display: "block", fontSize: 12, color: "#6668aa", marginBottom: 4 },
  input: {
    width: "100%",
    padding: "11px 12px",
    background: "#1a1a38",
    border: "1px solid #2a2a50",
    borderRadius: 8,
    color: "#dde1f0",
    fontSize: 14,
    boxSizing: "border-box",
    marginBottom: 14,
  },
  btn: (v) => ({
    width: "100%",
    padding: "14px",
    borderRadius: 10,
    border: "none",
    fontSize: 16,
    fontWeight: 700,
    cursor: "pointer",
    background:
      v === "stop"
        ? "#cc3333"
        : v === "save"
        ? "#2255cc"
        : "#1a7a44",
    color: "#fff",
    marginTop: 6,
  }),
  pbar: {
    background: "#1a1a38",
    borderRadius: 4,
    height: 8,
    marginBottom: 4,
    overflow: "hidden",
  },
  pfill: (p) => ({
    width: `${p}%`,
    height: "100%",
    background: "linear-gradient(90deg,#4444cc,#8080ff)",
    borderRadius: 4,
    transition: "width 0.4s ease",
  }),
  card: {
    background: "#14143a",
    borderRadius: 10,
    padding: "14px 14px 10px",
    marginBottom: 12,
    borderLeft: "3px solid #00cc66",
  },
  cardName: { fontSize: 15, fontWeight: 700, marginBottom: 6 },
  price: { fontSize: 22, fontWeight: 700, color: "#00ff88" },
  rsi: { fontSize: 12, color: "#888", marginLeft: 10 },
  badge: (c) => ({
    display: "inline-block",
    padding: "3px 9px",
    borderRadius: 20,
    fontSize: 11,
    background: c + "22",
    color: c,
    marginRight: 4,
    marginTop: 6,
  }),
  logBox: {
    background: "#080818",
    borderRadius: 8,
    padding: "10px 12px",
    height: 320,
    overflowY: "auto",
    fontFamily: "monospace",
    fontSize: 12,
  },
  logLine: { padding: "3px 0", borderBottom: "1px solid #12122a", color: "#99a" },
  err: {
    background: "#330a0a",
    border: "1px solid #cc3333",
    borderRadius: 8,
    padding: "12px 14px",
    color: "#ff8888",
    fontSize: 13,
    marginBottom: 14,
  },
  empty: { textAlign: "center", color: "#555", padding: "48px 20px", fontSize: 14 },
  info: { fontSize: 12, color: "#555", lineHeight: 1.9, marginTop: 20 },
};

export default function StockScanner() {
  const ls = (k, d = "") => {
    try {
      return localStorage.getItem(k) ?? d;
    } catch {
      return d;
    }
  };

  const [tab, setTab] = useState("scanner");
  const [appKey, setAppKey] = useState(() => ls("ki_appkey"));
  const [appSecret, setAppSecret] = useState(() => ls("ki_secret"));
  const [discordUrl, setDiscordUrl] = useState(() => ls("ki_discord"));
  const [scanning, setScanning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [results, setResults] = useState([]);
  const [logs, setLogs] = useState([]);
  const [errMsg, setErrMsg] = useState("");

  // 실시간 시세 상태
  const [rtPrices, setRtPrices] = useState({});   // { code: { price, change, changePct, sign } }
  const [rtRunning, setRtRunning] = useState(false);
  const [rtLoading, setRtLoading] = useState(false);
  const [rtLastUpdate, setRtLastUpdate] = useState(null);
  const [rtErr, setRtErr] = useState("");
  const stopRef = useRef(false);
  const tokenCache = useRef({ value: null, expiry: 0 });
  const rtIntervalRef = useRef(null);
  const rtStopRef = useRef(false);

  const addLog = useCallback((msg) => {
    const t = new Date().toLocaleTimeString("ko-KR");
    setLogs((prev) => [`[${t}] ${msg}`, ...prev].slice(0, 200));
  }, []);

  const saveSettings = () => {
    try {
      localStorage.setItem("ki_appkey", appKey);
      localStorage.setItem("ki_secret", appSecret);
      localStorage.setItem("ki_discord", discordUrl);
    } catch {}
  };

  const getToken = async () => {
    const now = Date.now();
    if (tokenCache.current.value && now < tokenCache.current.expiry) {
      return tokenCache.current.value;
    }
    const res = await fetch(`${API_BASE}/oauth2/tokenP`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        grant_type: "client_credentials",
        appkey: appKey,
        appsecret: appSecret,
      }),
    });
    if (!res.ok) throw new Error(`토큰 HTTP ${res.status}`);
    const d = await res.json();
    if (!d.access_token) throw new Error("토큰 없음: " + JSON.stringify(d));
    tokenCache.current = { value: d.access_token, expiry: now + 23 * 3600 * 1000 };
    return d.access_token;
  };

  const fetchCurrentPrice = async (token, code) => {
    const p = new URLSearchParams({
      fid_cond_mrkt_div_code: "J",
      fid_input_iscd: code,
    });
    const res = await fetch(
      `${API_BASE}/uapi/domestic-stock/v1/quotations/inquire-price?${p}`,
      {
        headers: {
          authorization: `Bearer ${token}`,
          appkey: appKey,
          appsecret: appSecret,
          tr_id: "FHKST01010100",
          custtype: "P",
        },
      }
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.rt_cd !== "0") throw new Error(data.msg1 || data.msg_cd || "오류");
    return data.output;
  };

  const fetchDailyPrice = async (token, code) => {
    const today = new Date();
    const start = new Date(today);
    start.setDate(start.getDate() - 180);
    const fmt = (d) => d.toISOString().slice(0, 10).replace(/-/g, "");
    const p = new URLSearchParams({
      fid_cond_mrkt_div_code: "J",
      fid_input_iscd: code,
      fid_input_date_1: fmt(start),
      fid_input_date_2: fmt(today),
      fid_period_div_code: "D",
      fid_org_adj_prc: "0",
    });
    const res = await fetch(
      `${API_BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice?${p}`,
      {
        headers: {
          authorization: `Bearer ${token}`,
          appkey: appKey,
          appsecret: appSecret,
          tr_id: "FHKST03010100",
          custtype: "P",
        },
      }
    );
    if (!res.ok) throw new Error(`조회 HTTP ${res.status}`);
    const data = await res.json();
    if (data.rt_cd !== "0") {
      throw new Error(`API [${data.rt_cd}] ${data.msg1 ?? data.msg_cd ?? "오류"}`);
    }
    return data;
  };

  const startScan = async () => {
    if (!appKey || !appSecret) {
      setErrMsg("설정 탭에서 App Key와 Secret을 입력하세요.");
      setTab("settings");
      return;
    }
    saveSettings();
    setScanning(true);
    stopRef.current = false;
    setResults([]);
    setLogs([]);
    setErrMsg("");
    setProgress(0);

    try {
      addLog("토큰 발급 중...");
      const token = await getToken();
      addLog("✅ 토큰 발급 완료");

      for (let i = 0; i < STOCKS.length; i++) {
        if (stopRef.current) {
          addLog("⏹ 스캔 중단");
          break;
        }
        const stock = STOCKS[i];
        setProgress(Math.round(((i + 1) / STOCKS.length) * 100));
        addLog(`🔍 ${stock.name} 분석 중...`);

        try {
          const data = await fetchDailyPrice(token, stock.code);
          const raw = data?.output2 ?? [];
          const analysis = analyzeStock(data);
          if (analysis) {
            addLog(`🎯 ${stock.name} — ${analysis.signals.join(", ")} RSI=${analysis.rsi}`);
            setResults((prev) => [...prev, { stock, analysis }]);
            if (discordUrl) {
              try {
                await sendDiscord(discordUrl, stock, analysis);
                addLog(`📨 Discord 전송 완료: ${stock.name}`);
              } catch (e) {
                addLog(`⚠️ Discord 오류: ${e.message}`);
              }
            }
          } else {
            const closes = [...raw].reverse().map((d) => parseFloat(d.stck_clpr));
            const rsi = calcRSI(closes);
            addLog(`— ${stock.name} 신호 없음 RSI=${rsi ? rsi.toFixed(1) : "N/A"} (${raw.length}일)`);
          }
          await new Promise((r) => setTimeout(r, 250));
        } catch (e) {
          addLog(`⚠️ ${stock.name}: ${e.message}`);
        }
      }

      if (!stopRef.current) {
        addLog(`✅ 완료 — 신호 ${results.length}개 발견`);
        setProgress(100);
      }
    } catch (e) {
      setErrMsg(e.message);
      addLog(`❌ ${e.message}`);
    } finally {
      setScanning(false);
    }
  };

  // ── 실시간 시세 ────────────────────────────────────────────────────────────

  const startRealtime = async () => {
    if (!appKey || !appSecret) {
      setErrMsg("설정 탭에서 App Key와 Secret을 입력하세요.");
      setTab("settings");
      return;
    }
    saveSettings();
    rtStopRef.current = false;
    setRtRunning(true);
    setRtPrices({});
    setRtErr("");

    const poll = async () => {
      if (rtStopRef.current) return;
      setRtLoading(true);
      try {
        const token = await getToken();
        const updates = {};
        for (const stock of STOCKS) {
          if (rtStopRef.current) break;
          try {
            const out = await fetchCurrentPrice(token, stock.code);
            updates[stock.code] = {
              price: parseInt(out.stck_prpr),
              change: parseInt(out.prdy_vrss),
              changePct: parseFloat(out.prdy_ctrt),
              sign: out.prdy_vrss_sign, // 1:상한 2:상승 3:보합 4:하한 5:하락
            };
          } catch { /* 개별 종목 실패 시 건너뜀 */ }
          await new Promise((r) => setTimeout(r, 100));
        }
        if (!rtStopRef.current) {
          setRtPrices(updates);
          setRtLastUpdate(new Date().toLocaleTimeString("ko-KR"));
          setRtErr("");
        }
      } catch (e) {
        setRtErr(e.message);
      } finally {
        setRtLoading(false);
      }
    };

    await poll();
    if (!rtStopRef.current) {
      rtIntervalRef.current = setInterval(poll, RT_INTERVAL);
    }
  };

  const stopRealtime = () => {
    rtStopRef.current = true;
    setRtRunning(false);
    if (rtIntervalRef.current) {
      clearInterval(rtIntervalRef.current);
      rtIntervalRef.current = null;
    }
    setRtLoading(false);
  };

  // 탭 이탈 또는 언마운트 시 인터벌 정리
  useEffect(() => {
    return () => {
      if (rtIntervalRef.current) clearInterval(rtIntervalRef.current);
    };
  }, []);

  return (
    <div style={S.wrap}>
      {/* Header */}
      <div style={S.header}>
        <div style={S.title}>📈 주식 스캐너</div>
        <div style={S.sub}>한국투자 Open API · RSI / MACD / 3봉 패턴</div>
      </div>

      {/* Tabs */}
      <div style={S.tabs}>
        {[
          ["scanner", "스캔"],
          ["results", `결과(${results.length})`],
          ["realtime", rtRunning ? "실시간●" : "실시간"],
          ["settings", "설정"],
          ["log", "로그"],
        ].map(([id, label]) => (
          <button key={id} style={{
            ...S.tab(tab === id),
            ...(id === "realtime" && rtRunning ? { color: "#00cc66", borderBottomColor: "#00cc66" } : {}),
          }} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>

      <div style={S.body}>
        {errMsg && <div style={S.err}>⚠️ {errMsg}</div>}

        {/* ── 스캔 탭 ── */}
        {tab === "scanner" && (
          <div>
            <div style={S.pbar}>
              <div style={S.pfill(progress)} />
            </div>
            <div style={{ textAlign: "right", fontSize: 11, color: "#555", marginBottom: 16 }}>
              {progress}% · {STOCKS.length}종목
            </div>

            {scanning ? (
              <button style={S.btn("stop")} onClick={() => (stopRef.current = true)}>
                ⏹ 스캔 중단
              </button>
            ) : (
              <button style={S.btn("start")} onClick={startScan}>
                🚀 스캔 시작
              </button>
            )}

            <div style={S.info}>
              분석 조건<br />
              • RSI(14) ≤ 30 — 과매도 구간<br />
              • MACD 골든크로스 — 추세 전환<br />
              • 3봉 연속 양봉 상승<br />
              • 대상: KOSPI 주요 50 종목
            </div>

            {logs[0] && (
              <div style={{ marginTop: 12, fontSize: 12, color: "#666" }}>{logs[0]}</div>
            )}
          </div>
        )}

        {/* ── 결과 탭 ── */}
        {tab === "results" && (
          <div>
            {results.length === 0 ? (
              <div style={S.empty}>
                {scanning ? "🔍 스캔 중..." : "신호 없음\n스캔 탭에서 시작하세요."}
              </div>
            ) : (
              results.map((r, i) => (
                <div key={i} style={S.card}>
                  <div style={S.cardName}>
                    {r.stock.name}{" "}
                    <span style={{ fontWeight: 400, color: "#666", fontSize: 12 }}>
                      {r.stock.code}
                    </span>
                  </div>
                  <div>
                    <span style={S.price}>{r.analysis.price.toLocaleString()}원</span>
                    <span style={S.rsi}>RSI {r.analysis.rsi}</span>
                  </div>
                  <div>
                    {r.analysis.signals.map((s, j) => (
                      <span key={j} style={S.badge("#8080ff")}>{s}</span>
                    ))}
                    <span style={S.badge("#00cc66")}>신뢰도 {r.analysis.confidence}%</span>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* ── 실시간 탭 ── */}
        {tab === "realtime" && (
          <div>
            {/* 상태 바 */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: isMarketOpen() ? "#00cc66" : "#666" }}>
                {isMarketOpen() ? "🟢 장중" : "⚫ 장외"}
              </div>
              <div style={{ fontSize: 11, color: "#555" }}>
                {rtLoading ? "⏳ 조회 중..." : rtLastUpdate ? `⏱ ${rtLastUpdate} 업데이트` : ""}
              </div>
            </div>

            {rtErr && <div style={S.err}>⚠️ {rtErr}</div>}

            {/* 시작/중단 버튼 */}
            {rtRunning ? (
              <button style={S.btn("stop")} onClick={stopRealtime}>⏹ 실시간 중단</button>
            ) : (
              <button style={S.btn("start")} onClick={startRealtime}>▶ 실시간 시작</button>
            )}

            {!rtRunning && Object.keys(rtPrices).length === 0 && (
              <div style={{ ...S.info, textAlign: "center", marginTop: 32 }}>
                실시간 시작을 누르면<br />
                50종목 현재가를 {RT_INTERVAL / 1000}초마다 자동 갱신합니다
              </div>
            )}

            {/* 가격 목록 — 등락률 내림차순 */}
            {Object.keys(rtPrices).length > 0 && (
              <div style={{ marginTop: 14 }}>
                {[...STOCKS]
                  .sort((a, b) => (rtPrices[b.code]?.changePct ?? 0) - (rtPrices[a.code]?.changePct ?? 0))
                  .map((stock) => {
                    const rt = rtPrices[stock.code];
                    if (!rt) return null;
                    const up = rt.changePct > 0;
                    const dn = rt.changePct < 0;
                    const clr = up ? "#cc4444" : dn ? "#4488ff" : "#888";
                    const arrow = up ? "▲" : dn ? "▼" : "—";
                    return (
                      <div key={stock.code} style={{
                        display: "flex", justifyContent: "space-between", alignItems: "center",
                        padding: "9px 12px", marginBottom: 4, borderRadius: 8,
                        background: "#14143a", borderLeft: `3px solid ${clr}`,
                      }}>
                        <div>
                          <div style={{ fontWeight: 600, fontSize: 13 }}>{stock.name}</div>
                          <div style={{ color: "#555", fontSize: 10 }}>{stock.code}</div>
                        </div>
                        <div style={{ textAlign: "right" }}>
                          <div style={{ fontSize: 15, fontWeight: 700, color: "#00ff88" }}>
                            {rt.price.toLocaleString()}원
                          </div>
                          <div style={{ fontSize: 11, color: clr }}>
                            {arrow}{Math.abs(rt.changePct).toFixed(2)}%
                            <span style={{ color: "#555", marginLeft: 4 }}>
                              ({rt.change >= 0 ? "+" : ""}{rt.change.toLocaleString()})
                            </span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
              </div>
            )}
          </div>
        )}

        {/* ── 설정 탭 ── */}
        {tab === "settings" && (
          <div>
            <label style={S.label}>App Key</label>
            <input
              style={S.input}
              type="password"
              value={appKey}
              onChange={(e) => setAppKey(e.target.value)}
              placeholder="한국투자 App Key"
            />

            <label style={S.label}>App Secret</label>
            <input
              style={S.input}
              type="password"
              value={appSecret}
              onChange={(e) => setAppSecret(e.target.value)}
              placeholder="한국투자 App Secret"
            />

            <label style={S.label}>Discord Webhook URL (선택)</label>
            <input
              style={S.input}
              type="password"
              value={discordUrl}
              onChange={(e) => setDiscordUrl(e.target.value)}
              placeholder="https://discord.com/api/webhooks/..."
            />

            <button
              style={S.btn("save")}
              onClick={() => {
                saveSettings();
                setErrMsg("");
                addLog("✅ 설정 저장됨");
                setTab("scanner");
              }}
            >
              💾 저장하고 스캔으로 이동
            </button>

            <div style={S.info}>
              • API Key는 기기 로컬에만 저장됩니다.<br />
              • 한국투자 Open API: securities.koreainvestment.com<br />
              • 모의투자 계좌로도 동일하게 사용 가능합니다.<br />
              • CORS 오류 시 PC 환경(GitHub Actions)을 이용하세요.
            </div>
          </div>
        )}

        {/* ── 로그 탭 ── */}
        {tab === "log" && (
          <div>
            <div style={S.logBox}>
              {logs.length === 0 ? (
                <div style={{ color: "#444", padding: 8 }}>로그 없음</div>
              ) : (
                logs.map((l, i) => (
                  <div key={i} style={S.logLine}>{l}</div>
                ))
              )}
            </div>
            {logs.length > 0 && (
              <button
                style={{ ...S.btn("stop"), marginTop: 10, padding: "10px", fontSize: 13 }}
                onClick={() => setLogs([])}
              >
                🗑 로그 지우기
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
