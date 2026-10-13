import time, requests, io, pytz, json, os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
import numpy as np
import pandas as pd

# ===== CONFIGURATION NTFY =====
NTFY_XAU = os.getenv("NTFY_XAU", "https://ntfy.sh/rick-xau-sr2-secret-2026")
NTFY_EUR = os.getenv("NTFY_EUR", "https://ntfy.sh/rick-eur-sr2-secret-2026")
NTFY_GBP = os.getenv("NTFY_GBP", "https://ntfy.sh/rick-gbp-sr2-secret-2026")
NTFY_V75 = os.getenv("NTFY_V75", "https://ntfy.sh/rick-v75-sr2-secret-2026")

PAIRS = {
    "XAUUSD": {"symbol": "GC=F", "ntfy": NTFY_XAU, "dec": 2, "name": "XAUUSD (Or)"},
    "EURUSD": {"symbol": "EURUSD=X", "ntfy": NTFY_EUR, "dec": 5, "name": "EURUSD"},
    "GBPUSD": {"symbol": "GBPUSD=X", "ntfy": NTFY_GBP, "dec": 5, "name": "GBPUSD"},
    "V75": {"symbol": "R_75", "ntfy": NTFY_V75, "dec": 2, "name": "Volatility 75", "source": "deriv"},
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def send(url, title, msg, img=None):
    for i in range(5):
        try:
            h = {"Title": title}
            if img:
                h["Filename"] = "chart.png"
                h["X-Message"] = msg
                r = requests.post(url, data=img, headers={k: v.encode('utf-8') for k, v in h.items()}, timeout=30)
            else:
                r = requests.post(url, data=msg.encode('utf-8'), headers=h, timeout=15)
            if r.status_code == 200:
                log(f"✅ {title}")
                return True
            log(f"⚠️ Tentative {i+1}: status {r.status_code}")
            time.sleep(2**i)
        except Exception as e:
            log(f"❌ Erreur: {e}")
            time.sleep(2**i)
    return False

def get_candles_deriv(sym, granularity=60):
    try:
        import websocket as ws_client
        log(f"🔌 Connexion Deriv pour {sym}...")
        ws = ws_client.create_connection('wss://ws.binaryws.com/websockets/v3?app_id=1089', timeout=10)
        ws.send(json.dumps({"ticks_history": sym, "count": 100, "end": "latest", "start": 1, "style": "candles", "granularity": granularity}))
        r = json.loads(ws.recv())
        ws.close()
        if "candles" in r:
            candles = [{"t": c["epoch"], "o": float(c["open"]), "h": float(c["high"]), "l": float(c["low"]), "c": float(c["close"])} for c in r["candles"]]
            log(f"✅ Deriv: {len(candles)} bougies pour {sym}")
            return candles
        else:
            log(f"⚠️ Deriv: pas de bougies pour {sym}")
            return []
    except Exception as e:
        log(f"❌ Deriv {sym}: {e}")
        return []

def get_candles(sym, interval="1h", range_days="60d"):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval={interval}&range={range_days}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json()["chart"]["result"][0]
        closes = data["indicators"]["quote"][0]["close"]
        opens = data["indicators"]["quote"][0]["open"]
        highs = data["indicators"]["quote"][0]["high"]
        lows = data["indicators"]["quote"][0]["low"]
        timestamps = data["timestamp"]
        candles = []
        for i in range(len(closes)):
            if closes[i] and opens[i] and highs[i] and lows[i]:
                candles.append({"t": timestamps[i], "o": opens[i], "h": highs[i], "l": lows[i], "c": closes[i]})
        candles = candles[-100:] if len(candles) > 100 else candles
        log(f"✅ Yahoo: {len(candles)} bougies pour {sym} en {interval}")
        return candles
    except Exception as e:
        log(f"❌ Yahoo {sym}: {e}")
        return []

def calc_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0
    tr_list = []
    for i in range(1, len(candles)):
        h = candles[i]["h"]
        l = candles[i]["l"]
        c_prev = candles[i-1]["c"]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        tr_list.append(tr)
    atr = sum(tr_list[-period:]) / period
    return atr

def sr(cd, mx=3, tol=0.002):
    n = len(cd)
    rr, rs = [], []
    for i in range(5, n-5):
        if all(cd[j]["h"] <= cd[i]["h"] for j in range(max(0,i-5), min(n,i+6)) if j != i):
            rr.append(cd[i]["h"])
        if all(cd[j]["l"] >= cd[i]["l"] for j in range(max(0,i-5), min(n,i+6)) if j != i):
            rs.append(cd[i]["l"])
    def clust(lst):
        if not lst: return []
        lst = sorted(lst)
        zones, grp = [], [lst[0]]
        for v in lst[1:]:
            if (v-grp[0])/grp[0] <= tol:
                grp.append(v)
            else:
                zones.append((np.mean(grp), len(grp)))
                grp = [v]
        zones.append((np.mean(grp), len(grp)))
        return [z[0] for z in sorted(zones, key=lambda z: z[1], reverse=True)[:mx]]
    return sorted(clust(rr), reverse=True), sorted(clust(rs))

def channel(cd, lb=40):
    if len(cd) < 20:
        return None
    rc = cd[-lb:] if len(cd) >= lb else cd
    nr, off = len(rc), len(cd)-len(rc)
    ph, pl = [], []
    for i in range(2, nr-2):
        if all(rc[j]["h"] <= rc[i]["h"] for j in range(max(0,i-2), min(nr,i+3)) if j != i):
            ph.append((i, rc[i]["h"]))
        if all(rc[j]["l"] >= rc[i]["l"] for j in range(max(0,i-2), min(nr,i+3)) if j != i):
            pl.append((i, rc[i]["l"]))
    cls = [c["c"] for c in rc]
    sg = np.polyfit(np.arange(nr), cls, 1)[0]
    if sg >= 0:
        if len(pl) < 2: return None
        xs, ys = np.array([p[0] for p in pl]), np.array([p[1] for p in pl])
    else:
        if len(ph) < 2: return None
        xs, ys = np.array([p[0] for p in ph]), np.array([p[1] for p in ph])
    sl, ic = np.polyfit(xs, ys, 1)
    xa = np.arange(nr)
    base = sl*xa + ic
    hi = np.array([c["h"] for c in rc])
    lo = np.array([c["l"] for c in rc])
    return {"x": np.arange(off, len(cd)), "upper": base+np.max(hi-base), "lower": base+np.min(lo-base), "slope": sl}

def chart_sr(cd, cp, info, title_suffix="", sl_price=None):
    if len(cd) < 5:
        return None
    rz, sz = sr(cd)
    ch = channel(cd)
    name, dec = info["name"], info["dec"]
    fig, ax = plt.subplots(figsize=(18,10))
    fig.patch.set_facecolor('#0a0a0a')
    ax.set_facecolor('#0d1117')
    for i, c in enumerate(cd):
        col = '#26a69a' if c["c"]>=c["o"] else '#ef5350'
        ax.plot([i,i], [c["l"],c["h"]], color=col, lw=1.2)
        ax.add_patch(plt.Rectangle((i-0.35, min(c["o"],c["c"])), 0.7, abs(c["c"]-c["o"]) or 0.0001, facecolor=col, edgecolor=col))
    if ch:
        cc = '#a371f7' if ch["slope"]>0 else '#f0883e'
        ax.plot(ch["x"], ch["upper"], color=cc, lw=2.5, ls='--', alpha=0.9)
        ax.plot(ch["x"], ch["lower"], color=cc, lw=2.5, ls='--', alpha=0.9)
        ax.fill_between(ch["x"], ch["lower"], ch["upper"], color=cc, alpha=0.06)
    for r in rz:
        ax.axhline(r, color='#f85149', ls=':', lw=2.5)
        ax.text(len(cd)-1, r, f'  R {r:.{dec}f}', color='#f85149', fontsize=13, va='bottom', ha='right', fontweight='bold', bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a0a0a', alpha=0.8))
    for s in sz:
        ax.axhline(s, color='#3fb950', ls=':', lw=2.5)
        ax.text(len(cd)-1, s, f'  S {s:.{dec}f}', color='#3fb950', fontsize=13, va='top', ha='right', fontweight='bold', bbox=dict(boxstyle='round,pad=0.3', facecolor='#0a1a0a', alpha=0.8))
    
    ax.axhline(cp, color='#f59e0b', ls='-.', lw=3)
    ax.text(2, cp, f' Entrée: {cp:.{dec}f}', color='#f59e0b', fontsize=14, va='bottom', fontweight='bold', bbox=dict(boxstyle='round,pad=0.4', facecolor='#1a1400', alpha=0.85))

    if sl_price:
        ax.axhline(sl_price, color='#ef5350', ls='--', lw=2.5)
        ax.text(2, sl_price, f' Stop-Loss: {sl_price:.{dec}f}', color='#ef5350', fontsize=14, va='top', fontweight='bold', bbox=dict(boxstyle='round,pad=0.4', facecolor='#0a1a0a', alpha=0.85))

    n = len(cd)
    step = max(1, n//8)
    ax.set_xticks(range(0, n, step))
    ax.set_xticklabels([datetime.fromtimestamp(cd[i]["t"]).strftime('%d/%m\n%Hh') for i in range(0,n,step)], color='white', fontsize=11)
    ax.set_title(f"  {name} {title_suffix} — SR+Canal | Prix: {cp:.{dec}f}", color='white', fontsize=16, fontweight='bold', pad=15)
    ax.set_ylabel("Prix", color='white', fontsize=13)
    ax.tick_params(colors='white', labelsize=11)
    ax.grid(True, alpha=0.12, color='gray')
    for sp in ax.spines.values():
        sp.set_color('#333333')
    from matplotlib.patches import Patch
    leg = [Patch(color='#26a69a', label='Haussière'), Patch(color='#ef5350', label='Baissière'), Patch(color='#f85149', label='Résistance'), Patch(color='#3fb950', label='Support')]
    if ch:
        leg.append(Patch(color='#a371f7' if ch["slope"]>0 else '#f0883e', label=f'Canal {"↑" if ch["slope"]>0 else "↓"}'))
    ax.legend(handles=leg, loc='upper left', facecolor='#1a1a2e', edgecolor='#555', labelcolor='white', fontsize=12, framealpha=0.9)
    plt.tight_layout(pad=1.5)
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=130, facecolor='#0a0a0a')
    buf.seek(0)
    plt.close()
    return buf.getvalue()

def analyze_sr2(key, info):
    log(f"🔍 Analyse SR2 {key}...")
    src = info.get("source", "yahoo")

    if src == "deriv":
        candles_h3 = get_candles_deriv(info["symbol"], granularity=10800)
        candles_h1 = get_candles_deriv(info["symbol"], granularity=3600)
    else:
        candles_h3 = get_candles(info["symbol"], interval="1h", range_days="60d")
        if len(candles_h3) >= 3:
            df = pd.DataFrame(candles_h3)
            df['t'] = pd.to_datetime(df['t'], unit='s')
            df.set_index('t', inplace=True)
            resampled = df.resample('3H').agg({'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last'}).dropna()
            candles_h3 = [{"t": int(ts.timestamp()), "o": row['o'], "h": row['h'], "l": row['l'], "c": row['c']} for ts, row in resampled.iterrows()]
            candles_h3 = candles_h3[-50:]
        candles_h1 = get_candles(info["symbol"], interval="1h", range_days="7d")

    if not candles_h3 or not candles_h1:
        log(f"⚠️ Pas de données pour {key}")
        return

    ch_h3 = channel(candles_h3)
    ch_h1 = channel(candles_h1)

    cp = candles_h1[-1]["c"]
    dec = info["dec"]
    rz, sz = sr(candles_h1)

    atr_h1 = calc_atr(candles_h1, 14)
    seuil_atr_min = 0.00010 if key in ["EURUSD", "GBPUSD"] else (0.5 if key == "XAUUSD" else 5.0)
    tolerance = 0.0005 if key in ["EURUSD", "GBPUSD"] else (1.5 if key == "XAUUSD" else 15.0)

    tendance_h3 = "HAUSSIERE" if ch_h3 and ch_h3["slope"] > 0.0001 else ("BAISSIERE" if ch_h3 and ch_h3["slope"] < -0.0001 else "LATERALE")
    tendance_h1 = "HAUSSIERE" if ch_h1 and ch_h1["slope"] > 0.0001 else ("BAISSIERE" if ch_h1 and ch_h1["slope"] < -0.0001 else "LATERALE")

    conseil = ""
    msg = ""
    condition_remplie = False
    sl_price = 0.0

    if rz and cp > rz[0] and tendance_h3 == "HAUSSIERE" and tendance_h1 == "HAUSSIERE":
        condition_remplie = True
        recent_low = min([c["l"] for c in candles_h1[-5:]])
        sl_price = recent_low - tolerance
        conseil = "ACHAT (H3+H1 Haussier + Cassure Resistance)"
        msg = f"SIGNAL ACHAT SR2 Pro\nCassure de la resistance {rz[0]:.{dec}f}\nEntree approx: {cp:.{dec}f}\n🛑 Stop-Loss Tolérable: {sl_price:.{dec}f}"

    elif sz and cp < sz[0] and tendance_h3 == "BAISSIERE" and tendance_h1 == "BAISSIERE":
        condition_remplie = True
        recent_high = max([c["h"] for c in candles_h1[-5:]])
        sl_price = recent_high + tolerance
        conseil = "VENTE (H3+H1 Baissier + Cassure Support)"
        msg = f"SIGNAL VENTE SR2 Pro\nCassure du support {sz[0]:.{dec}f}\nEntree approx: {cp:.{dec}f}\n🛑 Stop-Loss Tolérable: {sl_price:.{dec}f}"

    if condition_remplie:
        if atr_h1 < seuil_atr_min:
            log(f"⏭️ SILENCE {key} - ATR H1 trop faible ({atr_h1:.5f}) [Risque de fakeout]")
            return

        full_msg = f"{msg}\n\nPrix: {cp:.{dec}f}\nATR H1: {atr_h1:.{dec}f}\n{datetime.now(pytz.timezone('Africa/Porto-Novo')).strftime('%H:%M')}H Benin\nSR2 Bot Pro"

        log(f"📤 SIGNAL {key} - {conseil}")
        send(info["ntfy"], f"ALERTE {key} - {conseil}", full_msg)

        img_h3 = chart_sr(candles_h3, cp, info, "H3", sl_price)
        if img_h3:
            time.sleep(1)
            send(info["ntfy"], f"{key} H3 - {conseil}", "SR2 H3", img_h3)

        img_h1 = chart_sr(candles_h1, cp, info, "H1 & SL", sl_price)
        if img_h1:
            time.sleep(1)
            send(info["ntfy"], f"{key} H1 - Trigger & SL", "SR2 H1", img_h1)
    else:
        log(f"⏭️ SILENCE {key} - Pas de signal SR2 valide")

if __name__ == "__main__":
    log("🚀 SR2 BOT PRO - H3 + H1 + ATR + SL Tolérable")
    now = datetime.now(pytz.timezone('Africa/Porto-Novo'))
    h, j = now.hour, now.weekday()

    log("→ V75 (7j/7)")
    analyze_sr2("V75", PAIRS["V75"])

    if j < 5:
        log(f"📊 Analyse Forex {h}H")
        for key in ["XAUUSD", "EURUSD", "GBPUSD"]:
            log(f"→ {key}")
            analyze_sr2(key, PAIRS[key])
    else:
        log(f"💤 Forex ferme week-end")

    log("✅ Termine")
