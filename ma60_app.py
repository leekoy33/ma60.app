import os
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import twstock
import yfinance as yf

# ==================== 1. 頁面基本配置 (手機友善) ====================
st.set_page_config(
    page_title="台股 60m 糾結突破高勝率儀表板",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",  # 手機打開預設收合側邊欄
)

# 雲端伺服器/本機跨平台暫存路徑
WATCHLIST_FILE = (
    "/tmp/watch_list.csv" if os.path.exists("/tmp") else "watch_list.csv"
)

# ==================== 2. 工具與指標計算函數 ====================


@st.cache_data(ttl=86400)
def get_stock_info_map() -> dict[str, str]:
    """自動取得台灣上市/上櫃普通股代碼與名稱對照表 (快取 1 天)"""
    stock_map = {}
    for code, info in twstock.codes.items():
        if info.type == "股票" and len(code) == 4:
            if info.market == "上市":
                stock_map[f"{code}.TW"] = info.name
            elif info.market == "上櫃":
                stock_map[f"{code}.TWO"] = info.name
    return stock_map


@st.cache_data(ttl=86400)
def get_all_taiwan_stock_symbols() -> list[str]:
    """取得股票代碼清單"""
    stock_map = get_stock_info_map()
    return sorted(list(stock_map.keys()))


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """計算 60m 所需的均線、布林通道、MACD 與 KD 指標"""
    df = df.copy()

    # 均線
    df["MA35"] = df["Close"].rolling(35).mean()
    df["MA200"] = df["Close"].rolling(200).mean()
    df["Vol_MA20"] = df["Volume"].rolling(20).mean()

    # 布林通道
    df["BB_Mid"] = df["Close"].rolling(20).mean()
    std = df["Close"].rolling(20).std()
    df["BB_Upper"] = df["BB_Mid"] + 2 * std
    df["BB_Lower"] = df["BB_Mid"] - 2 * std
    df["BB_BW"] = (
        (df["BB_Upper"] - df["BB_Lower"]) / df["BB_Mid"] * 100.0
    )  # 布林頻寬%

    # MACD (12, 26, 9)
    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD_DIF"] = ema12 - ema26
    df["MACD_DEM"] = df["MACD_DIF"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD_DIF"] - df["MACD_DEM"]

    # KD (9, 3, 3)
    low_min = df["Low"].rolling(9).min()
    high_max = df["High"].rolling(9).max()
    rsv = (df["Close"] - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50)

    k_list, d_list = [50.0], [50.0]
    for r in rsv.iloc[1:]:
        k = (2 / 3) * k_list[-1] + (1 / 3) * r
        d = (2 / 3) * d_list[-1] + (1 / 3) * k
        k_list.append(k)
        d_list.append(d)

    df["K"] = k_list
    df["D"] = d_list

    return df


def plot_stock_chart(symbol: str, stock_name: str = ""):
    """繪製 60 分鐘 K 線 + 布林通道 + 35/200MA 圖表"""
    try:
        df = yf.Ticker(symbol).history(period="15d", interval="60m")
        if df.empty or len(df) < 35:
            st.warning(f"無法載入 {symbol} {stock_name} 的圖表資料。")
            return

        df = calculate_indicators(df)

        fig = go.Figure()

        # K線
        fig.add_trace(
            go.Candlestick(
                x=df.index,
                open=df["Open"],
                high=df["High"],
                low=df["Low"],
                close=df["Close"],
                name="K線",
            )
        )

        # 布林通道
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["BB_Upper"],
                line=dict(color="rgba(250, 0, 0, 0.4)", width=1),
                name="布林上軌",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["BB_Lower"],
                line=dict(color="rgba(0, 250, 0, 0.4)", width=1),
                name="布林下軌",
                fill="tonexty",
                fillcolor="rgba(200, 200, 200, 0.1)",
            )
        )

        # 均線
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["MA35"],
                line=dict(color="orange", width=1.5),
                name="35MA",
            )
        )
        if not df["MA200"].isna().all():
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df["MA200"],
                    line=dict(color="purple", width=1.5),
                    name="200MA",
                )
            )

        title_text = f"{symbol} {stock_name} 60m 走勢圖".strip()
        fig.update_layout(
            title=title_text,
            xaxis_rangeslider_visible=False,
            height=420,
            margin=dict(l=10, r=10, t=35, b=10),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
            ),
        )
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"繪製圖表時發生錯誤: {e}")


# ==================== 3. 側邊欄控制項 ====================
st.sidebar.title("⚙️ 策略參數與濾網設定")

st.sidebar.subheader("📊 流動性門檻")
min_volume_threshold = st.sidebar.number_input(
    "近5日平均成交量下限 (張)",
    min_value=100,
    max_value=10000,
    value=500,
    step=100,
    help="低於此成交量的冷門股將會被過濾掉。選不出股票時可調低（例如 300 張）",
)

st.sidebar.subheader("🎯 糾結壓縮條件")
threshold_pct = st.sidebar.slider(
    "均線糾結門檻 (%)",
    min_value=1.0,
    max_value=8.0,
    value=3.0,
    step=0.1,
    help="35MA 與 200MA 的最大差距%",
)
max_bb_bw = st.sidebar.slider(
    "布林頻寬上限 (%)",
    min_value=3.0,
    max_value=20.0,
    value=10.0,
    step=0.5,
    help="布林通道極致壓縮程度",
)

st.sidebar.subheader("⚡ 盤中突破條件")
vol_multiplier = st.sidebar.slider(
    "爆量倍數",
    min_value=1.1,
    max_value=3.0,
    value=1.3,
    step=0.1,
    help="當前 60m 成交量相對 20 週期均量的倍數",
)

st.sidebar.subheader("🛡️ 高勝率濾網設定")
use_macd_filter = st.sidebar.checkbox(
    "啟用 MACD 濾網 (柱狀圖翻紅 & DIF>0)", value=True
)
use_kd_filter = st.sidebar.checkbox(
    "啟用 KD 濾網 (中低檔金叉且 K < 80)", value=False
)

# 取得股票名稱對照表
stock_map = get_stock_info_map()

# ==================== 4. 主頁面內容 ====================
st.title("📈 台股 60m 糾結突破監控")

tab1, tab2 = st.tabs(["📌 盤前觀察名單", "🚨 盤中帶量突破"])

# ----------------- TAB 1: 盤前選股 -----------------
with tab1:
    st.caption(
        "篩選條件：日線 20MA/60MA 雙多頭 + 60m 35/200MA 糾結 + 布林通道極致壓縮"
    )

    if st.button(
        "🚀 開始盤前全台股掃描", key="btn_premarket", use_container_width=True
    ):
        all_stocks = get_all_taiwan_stock_symbols()
        progress_bar = st.progress(0)
        status_text = st.empty()

        # 第一階段：日線過濾
        status_text.text(
            f"階段 1/2：檢測日線雙多頭 (成交量 > {min_volume_threshold} 張)..."
        )
        qualified_stocks = []
        batch_size = 100

        for i in range(0, len(all_stocks), batch_size):
            batch = all_stocks[i : i + batch_size]
            progress_bar.progress((i + batch_size) / len(all_stocks) * 0.5)

            try:
                df_batch = yf.download(
                    tickers=batch,
                    period="120d",
                    interval="1d",
                    group_by="ticker",
                    progress=False,
                    threads=True,
                )
                for sym in batch:
                    try:
                        df_s = (
                            df_batch.dropna(subset=["Close", "Volume"])
                            if len(batch) == 1
                            else df_batch[sym].dropna(
                                subset=["Close", "Volume"]
                            )
                        )

                        avg_vol_5d = (
                            df_s["Volume"].tail(5).mean() / 1000.0
                        )  # 股數轉張數
                        if len(df_s) < 65 or avg_vol_5d < min_volume_threshold:
                            continue

                        df_s["MA20"] = df_s["Close"].rolling(20).mean()
                        df_s["MA60"] = df_s["Close"].rolling(60).mean()
                        latest = df_s.iloc[-1]

                        if (
                            latest["Close"]
                            > latest["MA20"]
                            > df_s["MA20"].iloc[-4]
                        ) and (
                            latest["Close"]
                            > latest["MA60"]
                            > df_s["MA60"].iloc[-6]
                        ):
                            qualified_stocks.append(sym)
                    except Exception:
                        continue
            except Exception:
                pass

        # 第二階段：60m 糾結壓縮過濾
        status_text.text(
            f"階段 1 符合 {len(qualified_stocks)} 檔。階段 2/2：檢測 60m 糾結壓縮..."
        )
        watchlist_results = []

        for idx, sym in enumerate(qualified_stocks):
            progress_bar.progress(
                0.5 + (idx + 1) / len(qualified_stocks) * 0.5
            )
            try:
                df_60m = yf.Ticker(sym).history(period="60d", interval="60m")
                if df_60m.empty or len(df_60m) < 200:
                    continue

                df_60m = calculate_indicators(df_60m)
                latest = df_60m.iloc[-1]

                diff_pct = (
                    abs(latest["MA35"] - latest["MA200"])
                    / latest["MA200"]
                    * 100.0
                )

                if diff_pct <= threshold_pct and latest["BB_BW"] <= max_bb_bw:
                    watchlist_results.append(
                        {
                            "股票代碼": sym,
                            "股票名稱": stock_map.get(sym, ""),
                            "最新收盤價": round(latest["Close"], 2),
                            "均線差距(%)": round(diff_pct, 2),
                            "布林頻寬(%)": round(latest["BB_BW"], 2),
                        }
                    )
            except Exception:
                pass

        progress_bar.progress(1.0)
        status_text.empty()

        df_watch = pd.DataFrame(watchlist_results)
        if not df_watch.empty:
            df_watch.to_csv(WATCHLIST_FILE, index=False)
            st.success(
                f"✅ 選股完成！找到 {len(df_watch)} 檔蓄勢標的並已儲存觀察名單。"
            )
            st.dataframe(df_watch, use_container_width=True)
        else:
            st.warning(
                "❌ 今日未篩選出符合條件之個股。建議調高糾結門檻或降低成交量張數後重新掃描。"
            )

    # 展示當前觀察名單
    if os.path.exists(WATCHLIST_FILE):
        st.subheader("📋 當前觀察名單")
        df_current = pd.read_csv(WATCHLIST_FILE)
        st.dataframe(df_current, use_container_width=True)
    else:
        st.info("尚無觀察名單，請先點選上方按鈕執行盤前選股。")

# ----------------- TAB 2: 盤中監控 -----------------
with tab2:
    st.caption("針對觀察名單檢測：紅棒 + 帶量 + 突破布林 + MACD/KD 進階濾網")

    if st.button(
        "🔍 立即掃描盤中突破訊號", key="btn_intraday", use_container_width=True
    ):
        if not os.path.exists(WATCHLIST_FILE):
            st.error("❌ 請先在【盤前觀察名單】頁籤執行選股以建立清單！")
        else:
            df_watch = pd.read_csv(WATCHLIST_FILE)
            symbols = df_watch["股票代碼"].tolist()

            breakout_results = []
            monitor_bar = st.progress(0)

            for idx, sym in enumerate(symbols):
                monitor_bar.progress((idx + 1) / len(symbols))
                try:
                    df = yf.Ticker(sym).history(period="10d", interval="60m")
                    if df.empty or len(df) < 35:
                        continue

                    df = calculate_indicators(df)
                    latest = df.iloc[-1]
                    prev = df.iloc[-2]

                    close_price = latest["Close"]
                    open_price = latest["Open"]
                    volume = latest["Volume"]
                    vol_ma20 = latest["Vol_MA20"]
                    bb_upper = latest["BB_Upper"]

                    # 1. 基礎突破條件
                    cond_red = close_price > open_price
                    cond_vol = volume > (vol_ma20 * vol_multiplier)
                    cond_break = (close_price >= bb_upper) or (
                        prev["Close"] < prev["MA35"]
                        and close_price > latest["MA35"]
                    )

                    # 2. MACD 濾網
                    cond_macd = True
                    if use_macd_filter:
                        cond_macd = (latest["MACD_Hist"] > 0) and (
                            latest["MACD_DIF"] > 0
                        )

                    # 3. KD 濾網
                    cond_kd = True
                    if use_kd_filter:
                        cond_kd = (
                            (prev["K"] <= prev["D"])
                            and (latest["K"] > latest["D"])
                            and (latest["K"] < 80)
                        )

                    # 綜合判定
                    if (
                        cond_red
                        and cond_vol
                        and cond_break
                        and cond_macd
                        and cond_kd
                    ):
                        breakout_results.append(
                            {
                                "股票代碼": sym,
                                "股票名稱": stock_map.get(sym, ""),
                                "現價": round(close_price, 2),
                                "爆量倍數": round(volume / vol_ma20, 2),
                                "突破布林上軌": (
                                    "是" if close_price >= bb_upper else "否"
                                ),
                                "MACD狀態": (
                                    "0軸上多頭"
                                    if latest["MACD_DIF"] > 0
                                    else "多頭"
                                ),
                                "K值": round(latest["K"], 1),
                            }
                        )
                except Exception:
                    pass

            monitor_bar.empty()

            if breakout_results:
                st.balloons()
                st.success(
                    f"🚨 發現 {len(breakout_results)} 檔股票觸發高勝率帶量突破訊號！"
                )
                df_breakout = pd.DataFrame(breakout_results)
                st.dataframe(df_breakout, use_container_width=True)

                st.markdown("---")
                st.subheader("📊 突破股票走勢圖檢視")
                
                # 選項結合代碼與名稱，增強可讀性
                options_map = {
                    f"{item['股票代碼']} {item['股票名稱']}": (
                        item["股票代碼"],
                        item["股票名稱"],
                    )
                    for item in breakout_results
                }
                
                selected_label = st.selectbox(
                    "選擇要查看 K 線圖的股票：",
                    list(options_map.keys()),
                )
                if selected_label:
                    sel_code, sel_name = options_map[selected_label]
                    plot_stock_chart(sel_code, sel_name)
            else:
                st.info("⌛ 目前無股票觸發帶量突破訊號。")
