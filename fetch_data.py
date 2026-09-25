"""
BLACK SWAN 데이터 수집 스크립트
- 뉴스: 무료 RSS + 무료 번역(MyMemory)
- 가격: Binance(크립토) + Yahoo Finance(주가지수/금/달러인덱스/원유/VIX/선물)
  -> 이 스크립트는 "서버"에서 실행되므로 브라우저의 CORS 제약이 아예 적용되지 않음.
     그래서 여기서는 야후 파이낸스든 어디든 그냥 다 받아올 수 있음.
- CME 선물은 CME 공식 데이터 대신, 같은 값을 추적하는 Yahoo Finance 선물 티커(ES=F, NQ=F 등)로 대체 (무료, 지연 있음)
- 롱/숏 유리 지표: NDX/ES 추세(20일선), RSI, VIX 방향, 달러인덱스 방향을 조합한 간단 합성 스코어
표준 라이브러리만 사용 (pip install 불필요)
"""
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HEADERS = {"User-Agent": "Mozilla/5.0 (BlackSwanBot)"}

NEWS_FEEDS = {
    "ndx": ("https://www.cnbc.com/id/10000664/device/rss/rss.html", "ndx"),
    "btc": ("https://www.coindesk.com/arc/outboundfeeds/rss/", "btc"),
    "general1": ("https://finance.yahoo.com/news/rssindex", "general"),
    "general2": ("https://feeds.marketwatch.com/marketwatch/topstories/", "general"),
}

CRYPTO = {"btc": "BTCUSDT", "eth": "ETHUSDT", "sol": "SOLUSDT"}
YAHOO = {
    "ndx": "%5ENDX",     # 나스닥100 지수
    "es":  "ES%3DF",     # S&P500 선물 (CME E-mini 대체)
    "nq":  "NQ%3DF",     # 나스닥 선물 (CME E-mini 대체)
    "gold": "GC%3DF",    # 금 선물 (CME 대체)
    "wti": "CL%3DF",     # WTI 원유 선물 (CME 대체)
    "zn":  "ZN%3DF",     # 10년물 국채 선물 (CME 대체)
    "dxy": "DX-Y.NYB",   # 달러인덱스
    "vix": "%5EVIX",     # 변동성지수
    "hsi": "%5EHSI",     # 항셍지수
    "n225": "%5EN225",   # 니케이225
    "kospi": "%5EKS11",  # 코스피
    "sse": "000001.SS",  # 상해종합
    "dax": "%5EGDAXI",   # 독일 DAX
    "ftse": "%5EFTSE",   # 영국 FTSE100
    "krw": "KRW%3DX",    # 원/달러
    "jpy": "JPY%3DX",    # 엔/달러
    "copper": "HG%3DF",  # 구리 선물
    "natgas": "NG%3DF",  # 천연가스 선물
    "silver": "SI%3DF",  # 은 선물
    "qqq": "QQQ",         # 나스닥100 추종 ETF
    "irx": "%5EIRX",     # 3개월 국채수익률 (x10 표기)
    "fvx": "%5EFVX",     # 5년물 국채수익률 (x10 표기)
    "tnx": "%5ETNX",     # 10년물 국채수익률 (x10 표기)
    "tyx": "%5ETYX",     # 30년물 국채수익률 (x10 표기)
}

# ---------- 뉴스 ----------
def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"'))
    return re.sub(r"\s+", " ", text).strip()

def fetch_rss(url, limit=15):
    req = urllib.request.Request(url, headers=HEADERS)
    xml = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")
    items = re.findall(r"<item>(.*?)</item>", xml, re.S)
    out = []
    for it in items[:limit]:
        title = re.search(r"<title>(.*?)</title>", it, re.S)
        link = re.search(r"<link>(.*?)</link>", it, re.S)
        pub = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
        desc = re.search(r"<description>(.*?)</description>", it, re.S)
        if title and link:
            clean_title = re.sub(r"<!\[CDATA\[|\]\]>", "", title.group(1)).strip()
            clean_desc = ""
            if desc:
                raw_desc = re.sub(r"<!\[CDATA\[|\]\]>", "", desc.group(1))
                clean_desc = strip_html(raw_desc)[:400]
                # 설명이 제목과 사실상 같거나(중복) 너무 짧으면 의미 없는 요약이므로 버림
                if not clean_desc or clean_desc.lower().startswith(clean_title.lower()[:20]) or len(clean_desc) < 20:
                    clean_desc = ""
            out.append({
                "title": clean_title,
                "description": clean_desc,
                "link": link.group(1).strip(),
                "pubDate": pub.group(1).strip() if pub else "",
            })
    return out

def translate(text):
    try:
        q = urllib.parse.quote(text[:450])
        url = f"https://api.mymemory.translated.net/get?q={q}&langpair=en|ko"
        req = urllib.request.Request(url, headers=HEADERS)
        j = json.loads(urllib.request.urlopen(req, timeout=10).read())
        t = j.get("responseData", {}).get("translatedText")
        if t and t.strip().lower() != text.strip().lower():
            return t
        return None
    except Exception:
        return None

def collect_news():
    news = []
    for feed_key, (url, tag) in NEWS_FEEDS.items():
        try:
            for n in fetch_rss(url):
                n["tag"] = tag
                n["title_ko"] = translate(n["title"])
                n["desc_ko"] = translate(n["description"]) if n.get("description") else None
                news.append(n)
        except Exception as e:
            print(f"[경고] 뉴스({feed_key}) 수집 실패: {e}")
    return news

# ---------- 가격 ----------
def fetch_binance_closes(symbol, limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit={limit}"
    req = urllib.request.Request(url, headers=HEADERS)
    raw = json.loads(urllib.request.urlopen(req, timeout=15).read())
    return [float(k[4]) for k in raw]

def fetch_yahoo_closes(symbol, rng="6mo"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval=1d"
    req = urllib.request.Request(url, headers=HEADERS)
    j = json.loads(urllib.request.urlopen(req, timeout=15).read())
    closes = j["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    return [c for c in closes if c is not None]

def fetch_stooq_closes(us_ticker, limit=100):
    """Yahoo가 막혔을 때의 2차 소스. 미국 개별 종목(.us)만 신뢰성 있게 지원함.
    지수/선물/외환은 Stooq 코드 체계가 달라 여기서는 다루지 않음."""
    url = f"https://stooq.com/q/d/l/?s={us_ticker.lower()}.us&i=d"
    req = urllib.request.Request(url, headers=HEADERS)
    text = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")
    lines = [l for l in text.strip().split("\n") if l]
    if len(lines) < 2 or "Date" not in lines[0]:
        raise ValueError("stooq: no data")
    closes = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) >= 5:
            try:
                closes.append(float(parts[4]))
            except ValueError:
                pass
    if not closes:
        raise ValueError("stooq: empty")
    return closes[-limit:]

def fetch_equity_closes_with_fallback(us_ticker, rng="6mo"):
    """미국 개별 종목 전용: Yahoo 1차 시도 -> 실패시 Stooq 2차 시도."""
    try:
        return fetch_yahoo_closes(us_ticker, rng=rng), "yahoo"
    except Exception as e:
        print(f"[정보] {us_ticker} Yahoo 실패, Stooq로 재시도: {e}")
        return fetch_stooq_closes(us_ticker), "stooq"

def rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0); losses += max(-d, 0)
    avg_gain, avg_loss = gains / period, losses / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        g, l = max(d, 0), max(-d, 0)
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def ma(closes, n=20):
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n

def collect_assets():
    assets = {}
    for aid, sym in CRYPTO.items():
        try:
            closes = fetch_binance_closes(sym)
            assets[aid] = build_asset(closes, live=True)
        except Exception as e:
            print(f"[경고] 크립토({aid}) 수집 실패: {e}")
            assets[aid] = {"live": False}
    for aid, sym in YAHOO.items():
        try:
            # 일반 미국 티커(alpha 문자만, 예: QQQ)는 Stooq 이중화까지 적용
            if sym.isalpha() and sym.isupper():
                closes, _src = fetch_equity_closes_with_fallback(sym)
            else:
                closes = fetch_yahoo_closes(sym)
            assets[aid] = build_asset(closes, live=True)
        except Exception as e:
            print(f"[경고] 야후({aid}) 수집 실패: {e}")
            assets[aid] = {"live": False}
    return assets

def build_asset(closes, live):
    last, prev = closes[-1], closes[-2]
    return {
        "live": live,
        "closes": closes[-100:],
        "last": last,
        "chg_pct": (last - prev) / prev * 100,
        "rsi14": rsi(closes),
        "ma20": ma(closes),
    }

# ---------- 롱/숏 유리 지표 ----------
def compute_bias(assets):
    """
    간단 합성 스코어 (-1 ~ +1). 각 요소를 -1/0/+1로 점수화해 평균.
    - 나스닥100·S&P선물: 20일선 위 + RSI>55 => 롱 유리
    - VIX: RSI>55(변동성 상승) => 숏 유리(리스크오프)
    - 달러인덱스: 20일선 위(강달러) => 숏 유리(리스크오프) 경향
    """
    scores = []
    used = []

    for eq in ["ndx", "es"]:
        a = assets.get(eq)
        if a and a.get("live") and a.get("ma20") and a.get("rsi14") is not None:
            s = 0
            s += 1 if a["last"] > a["ma20"] else -1
            s += 1 if a["rsi14"] > 55 else (-1 if a["rsi14"] < 45 else 0)
            scores.append(s / 2)
            used.append(eq)

    v = assets.get("vix")
    if v and v.get("live") and v.get("rsi14") is not None:
        scores.append(-1 if v["rsi14"] > 55 else (1 if v["rsi14"] < 45 else 0))
        used.append("vix")

    d = assets.get("dxy")
    if d and d.get("live") and d.get("ma20"):
        scores.append(-1 if d["last"] > d["ma20"] else 1)
        used.append("dxy")

    if not scores:
        return {"score": None, "label": "산출불가", "used": []}

    avg = sum(scores) / len(scores)
    if avg > 0.3:
        label = "롱 유리"
    elif avg < -0.3:
        label = "숏 유리"
    else:
        label = "중립/혼조"
    return {"score": round(avg, 3), "label": label, "used": used}

SECTOR_ETFS = {
    "xlk": ("XLK", "기술"), "xlf": ("XLF", "금융"), "xle": ("XLE", "에너지"),
    "xlv": ("XLV", "헬스케어"), "xly": ("XLY", "임의소비재"), "xlp": ("XLP", "필수소비재"),
    "xli": ("XLI", "산업재"), "xlb": ("XLB", "소재"), "xlu": ("XLU", "유틸리티"),
    "xlre": ("XLRE", "부동산"), "xlc": ("XLC", "커뮤니케이션"),
}

def collect_sectors():
    out = {}
    for key, (ticker, name) in SECTOR_ETFS.items():
        try:
            closes, source = fetch_equity_closes_with_fallback(ticker, rng="5d")
            last, prev = closes[-1], closes[-2]
            out[key] = {"name": name, "chg_pct": (last - prev) / prev * 100, "source": source}
        except Exception as e:
            print(f"[경고] 섹터({key}) 수집 실패(Yahoo+Stooq 둘 다): {e}")
    return out

HEATMAP_TICKERS = {
    "AAPL":"AAPL","MSFT":"MSFT","NVDA":"NVDA","GOOGL":"GOOGL","AMZN":"AMZN","META":"META",
    "TSLA":"TSLA","AVGO":"AVGO","COST":"COST","NFLX":"NFLX","AMD":"AMD","ADBE":"ADBE",
    "PEP":"PEP","CSCO":"CSCO","INTC":"INTC","QCOM":"QCOM","TXN":"TXN","AMAT":"AMAT",
    "INTU":"INTU","BKNG":"BKNG",
}

def collect_heatmap():
    out = {}
    for key, ticker in HEATMAP_TICKERS.items():
        try:
            closes, source = fetch_equity_closes_with_fallback(ticker, rng="5d")
            last, prev = closes[-1], closes[-2]
            out[key] = {"name": key, "chg_pct": (last - prev) / prev * 100, "source": source}
        except Exception as e:
            print(f"[경고] 히트맵({key}) 수집 실패(Yahoo+Stooq 둘 다): {e}")
    return out

def collect_insider(tickers):
    """SEC EDGAR Form 4(내부자 거래 신고) 최근 30일 건수 집계.
    SEC는 신원이 명시된 User-Agent를 요구함 -> 아래 이메일을 본인 것으로 바꿔서 사용 권장."""
    SEC_HEADERS = {"User-Agent": "BlackSwanTerminal contact@example.com"}
    out = {}
    try:
        req = urllib.request.Request("https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS)
        raw = json.loads(urllib.request.urlopen(req, timeout=20).read())
        cik_map = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in raw.values()}
    except Exception as e:
        print(f"[경고] SEC 티커맵 로드 실패: {e}")
        return out

    cutoff = datetime.now(timezone.utc).date()
    for t in tickers:
        cik = cik_map.get(t.upper())
        if not cik:
            continue
        try:
            req = urllib.request.Request(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=SEC_HEADERS)
            j = json.loads(urllib.request.urlopen(req, timeout=15).read())
            recent = j["filings"]["recent"]
            count = 0
            for form, fdate in zip(recent["form"], recent["filingDate"]):
                if form == "4":
                    d = datetime.strptime(fdate, "%Y-%m-%d").date()
                    if (cutoff - d).days <= 30:
                        count += 1
            out[t] = {"form4_count_30d": count}
        except Exception as e:
            print(f"[경고] 내부자거래({t}) 수집 실패: {e}")
    return out

# ---------- 매크로 지표 (FRED, API키 불필요한 무료 CSV 엔드포인트) ----------
FRED_SERIES = {
    "cpi_yoy": ("CPIAUCSL", "미국 CPI(전월비 지수)"),
    "unemployment": ("UNRATE", "실업률(%)"),
    "fedfunds": ("FEDFUNDS", "연방기금금리(%)"),
    "core_pce": ("PCEPILFE", "근원 PCE 물가지수"),
    "retail_sales": ("RSXFS", "소매판매(십억$)"),
    "industrial_prod": ("INDPRO", "산업생산지수"),
    "housing_starts": ("HOUST", "신규주택착공(천호)"),
    "nonfarm_payrolls": ("PAYEMS", "비농업고용(천명)"),
    "initial_claims": ("ICSA", "신규실업수당청구(명)"),
    "consumer_sentiment": ("UMCSENT", "미시간대 소비자심리지수"),
    "ppi": ("PPIACO", "생산자물가지수(PPI)"),
    "yield_2s10s": ("T10Y2Y", "장단기금리차(10Y-2Y,%p)"),
}

def fetch_fred_latest(series_id):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    req = urllib.request.Request(url, headers=HEADERS)
    text = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")
    lines = [l for l in text.strip().split("\n") if l]
    rows = [l.split(",") for l in lines[1:] if "," in l]
    valid = [(d, v) for d, v in rows if v not in (".", "")]
    if not valid:
        raise ValueError("fred: no data")
    date, value = valid[-1]
    prev_value = valid[-2][1] if len(valid) >= 2 else None
    return {
        "date": date,
        "value": float(value),
        "prev": float(prev_value) if prev_value else None,
    }

def collect_macro():
    out = {}
    for key, (series_id, label) in FRED_SERIES.items():
        try:
            r = fetch_fred_latest(series_id)
            r["label"] = label
            out[key] = r
        except Exception as e:
            print(f"[경고] 매크로({key}) 수집 실패: {e}")
    return out

# ---------- 공매도 거래량 비중 (FINRA 일별 short volume, 무료 공개) ----------
def fetch_finra_short_volume(date_str):
    """date_str: YYYYMMDD. FINRA가 당일 파일을 아직 안 올렸으면 예외 발생 -> 호출부에서 전일로 재시도."""
    url = f"https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date_str}.txt"
    req = urllib.request.Request(url, headers=HEADERS)
    text = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", errors="ignore")
    lines = [l for l in text.strip().split("\n") if l]
    out = {}
    for line in lines[1:]:
        parts = line.split("|")
        if len(parts) >= 5:
            ticker = parts[1].strip().upper()
            try:
                short_vol = float(parts[2])
                total_vol = float(parts[4])
                if total_vol > 0:
                    out[ticker] = short_vol / total_vol * 100
            except ValueError:
                continue
    if not out:
        raise ValueError("finra: empty file")
    return out

def collect_short_volume(tickers):
    """오늘부터 최대 5일 전까지 거슬러 올라가며 가장 최근 영업일 파일을 찾음(주말/공휴일 대비)."""
    from datetime import timedelta
    today = datetime.now(timezone.utc).date()
    for back in range(0, 6):
        d = today - timedelta(days=back)
        try:
            all_data = fetch_finra_short_volume(d.strftime("%Y%m%d"))
            return {t: {"short_vol_pct": round(all_data[t], 1), "date": d.isoformat()}
                    for t in tickers if t in all_data}
        except Exception:
            continue
    print("[경고] FINRA 공매도 거래량 데이터: 최근 6일 내 파일을 찾지 못함")
    return {}

KR_TICKERS = {
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "373220.KS": "LG에너지솔루션",
    "207940.KS": "삼성바이오로직스", "005380.KS": "현대차", "000270.KS": "기아",
    "035420.KS": "NAVER", "035720.KS": "카카오", "068270.KS": "셀트리온",
    "005490.KS": "POSCO홀딩스", "051910.KS": "LG화학", "006400.KS": "삼성SDI",
    "028260.KS": "삼성물산", "105560.KS": "KB금융", "055550.KS": "신한지주",
}

def fetch_yahoo_chart_full(symbol, rng="1mo"):
    """종가+거래량을 함께 반환 (거래량 급증 계산용)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval=1d"
    req = urllib.request.Request(url, headers=HEADERS)
    j = json.loads(urllib.request.urlopen(req, timeout=15).read())
    quote = j["chart"]["result"][0]["indicators"]["quote"][0]
    pairs = [(c, v) for c, v in zip(quote["close"], quote["volume"]) if c is not None and v is not None]
    if len(pairs) < 5:
        raise ValueError("not enough data")
    return [p[0] for p in pairs], [p[1] for p in pairs]

def collect_volume_surge():
    """오늘 거래량이 평소(최근 20일 평균) 대비 급증한 종목 — 미국 대형주 + 한국 대형주."""
    out = {}
    combined = [(t, t, "US") for t in HEATMAP_TICKERS.values()] + \
               [(t, n, "KR") for t, n in KR_TICKERS.items()]
    for ticker, name, market in combined:
        try:
            closes, volumes = fetch_yahoo_chart_full(ticker, rng="1mo")
            today_vol = volumes[-1]
            hist_vol = volumes[:-1]
            avg_vol = sum(hist_vol) / len(hist_vol) if hist_vol else 0
            ratio = (today_vol / avg_vol) if avg_vol > 0 else 0
            chg = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 else 0
            out[ticker] = {"name": name, "market": market, "chg_pct": chg, "vol_ratio": ratio, "volume": today_vol}
        except Exception as e:
            print(f"[경고] 거래량급증({market}:{ticker}) 수집 실패: {e}")
    return out

# ---------- 텔레그램 알림 (등락률 신규 진입 시) ----------
CRYPTO_IDS = {"btc", "eth", "sol"}
THRESH_CRYPTO = 6.0    # 크립토는 변동성이 커서 기준을 높게
THRESH_OTHER = 3.0     # 지수·개별주·원자재·외환 등
ALERT_STATE_FILE = "alert_state.json"

ASSET_DISPLAY_NAMES = {
    "btc": "BTC", "eth": "ETH", "sol": "SOL",
    "ndx": "나스닥100", "es": "S&P500 선물", "nq": "나스닥 선물",
    "gold": "금", "wti": "WTI 원유", "zn": "10년물 국채",
    "dxy": "달러인덱스", "vix": "VIX",
    "hsi": "항셍지수", "n225": "니케이225", "kospi": "코스피", "sse": "상해종합",
    "dax": "DAX", "ftse": "FTSE100", "krw": "원/달러", "jpy": "엔/달러",
    "copper": "구리", "natgas": "천연가스", "silver": "은", "qqq": "QQQ",
}

def build_alert_candidates(assets, volume_surge):
    """알림 발송과 사이트 표시가 공유하는 후보 목록: (key, name, chg_pct, threshold, category)"""
    candidates = []
    for aid, a in (assets or {}).items():
        if a.get("live") and a.get("chg_pct") is not None:
            name = ASSET_DISPLAY_NAMES.get(aid, aid.upper())
            is_crypto = aid in CRYPTO_IDS
            threshold = THRESH_CRYPTO if is_crypto else THRESH_OTHER
            candidates.append((aid, name, a["chg_pct"], threshold, "crypto" if is_crypto else "other"))
    for ticker, v in (volume_surge or {}).items():
        candidates.append((ticker, v["name"], v["chg_pct"], THRESH_OTHER, "stock"))
    return candidates

def build_price_alerts(assets, volume_surge):
    """현재 기준선(지수·개별주 3%, 크립토 6%)을 넘고 있는 종목 목록 — 사이트 표시용."""
    out = {}
    for key, name, chg, threshold, category in build_alert_candidates(assets, volume_surge):
        if abs(chg) >= threshold:
            out[key] = {"name": name, "chg_pct": chg, "category": category, "threshold": threshold}
    return out

def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data)
    urllib.request.urlopen(req, timeout=10)

def load_alert_state():
    try:
        with open(ALERT_STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_alert_state(state):
    with open(ALERT_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(state), f)

def check_and_send_alerts(assets, volume_surge):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[정보] 텔레그램 알림 비활성화 (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정)")
        return

    candidates = build_alert_candidates(assets, volume_surge)

    prev_state = load_alert_state()
    new_state = set()
    for key, name, chg, threshold, category in candidates:
        if abs(chg) >= threshold:
            new_state.add(key)
            if key not in prev_state:
                direction = "상승" if chg >= 0 else "하락"
                sign = "+" if chg >= 0 else ""
                text = f"{name} {sign}{chg:.2f}% {direction}!"
                try:
                    send_telegram(token, chat_id, text)
                    print(f"[알림 발송] {text}")
                except Exception as e:
                    print(f"[경고] 텔레그램 발송 실패({name}): {e}")
    save_alert_state(new_state)

def main():
    assets = collect_assets()
    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "news": collect_news(),
        "assets": assets,
        "bias": compute_bias(assets),
        "sectors": collect_sectors(),
        "volume_surge": collect_volume_surge(),
        "heatmap": collect_heatmap(),
        "insider": collect_insider(list(HEATMAP_TICKERS.keys())),
        "macro": collect_macro(),
        "short_vol": collect_short_volume(list(HEATMAP_TICKERS.keys())),
    }
    data["price_alerts"] = build_price_alerts(assets, data["volume_surge"])
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"완료: 뉴스 {len(data['news'])}건, 자산 {len(assets)}개, bias={data['bias']}")
    check_and_send_alerts(assets, data["volume_surge"])

if __name__ == "__main__":
    main()
