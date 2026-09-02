import os
import time
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import twstock
import yfinance as yf

# 1. 頁面配置 (設定適合手機顯示)
st.set_page_config(
    page_title="台股 60m 糾結突破監控 (MA60)",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",  # 手機開啟時預設收合側邊欄
)

# 雲端伺服器暫存路徑
WATCHLIST_FILE = "/tmp/watch_list.csv"

# ==================== 工具函數 ====================


@st.cache_data(ttl=86400)
def get_all_taiwan_stock_symbols() -> list[str]:
    """自動取得台灣上市/上櫃普通股代碼清單 (快取 1 天)"""
    watch_list = []
    for code, info in twstock.codes.items():
        if info.type == "股票" and len(code) == 4:
            if info.market == "上市":
                watch_list.append(f"{code}.TW")
            elif info.market == "上櫃":
                watch_list.append(f"{code}.TWO")
    return sorted(watch_list)


def plot_stock_chart(symbol: str):
    """繪製適合手機顯示的 60 分鐘 K 線圖"""
    try:
        df = yf.Ticker(symbol).history(period="10d", interval="60m")
        if df.empty or len(df) < 35:
            st.warning(f"無法載入 {symbol} 的圖表資料。")
            return

        # 計算指標
        df["MA35"] = df["Close"].rolling(35).mean()
        df["MA200"] = df["Close"].rolling(200).mean()
        df["BB_Mid"] = df["Close"].rolling(20).mean()
        std = df["Close"].rolling(20).std()
        df["BB_Upper"] = df["BB_Mid"] + 2 * std
        df["BB_Lower"] = df["BB_Mid"] - 2 * std

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
                line=dict(color="rgba(250, 0, 0, 0.5)", width=1),
                name="布林上軌",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["BB_Lower"],
                line=dict(color="rgba(0, 250, 0, 0.5)", width=1),
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

        # 手機版縮小邊距與調高度
        fig.update_layout(
            title=f"{symbol} 60m 走勢圖",
            xaxis_rangeslider_visible=False,
            height=400,
            margin=dict(l=10, r=10, t=30, b=10),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
            ),
        )
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"繪圖時發生錯誤: {e}")


# ==================== 側邊欄控制項 ====================
st.sidebar.title("⚙️ 策略參數設定")

threshold_pct = st.sidebar.slider(
    "均線糾結門檻 (%)",
    min_value=1.0,
    max_value=5.0,
    value=2.5,
    step=0.1,
)
max_bb_bw = st.sidebar.slider(
    "布林頻寬上限 (%)", min_value=3.0, max_value=15.0, value=8.0, step=0.5
)
vol_multiplier = st.sidebar.slider(
    "盤中突破爆量倍數",
    min_value=1.1,
    max_value=3.0,
    value=1.5,
    step=0.1,
)


# ==================== 主頁面 ====================
st.title("📱 台股 60m 均線糾結與突破監控")

tab1, tab2 = st.tabs(["📌 盤前觀察名單", "🚨 盤中帶量突破"])

# ----------------- TAB 1: 盤前選股 -----------------
with tab1:
    st.caption(
        "條件：日線 20MA/60MA 雙多頭 + 60m 35/200MA 糾結 + 布林壓縮"
    )

    if st.button(
        "🚀 開始盤前選股 (掃描全台股)",
        key="btn_premarket",
        use_container_width=True,
    ):
        all_stocks = get_all_taiwan_stock_symbols()
        progress_bar = st.progress(0)
        status_text = st.empty()

        # 第一階段
        status_text.text("進行階段 1/2: 日線雙多頭過濾...")
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
                        if (
                            len(df_s) < 65
                            or df_s["Volume"].tail(5).mean() / 1000.0 < 1000
                        ):
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

        # 第二階段
        status_text.text(
            f"階段 1 符合 {len(qualified_stocks)} 檔。進行階段 2/2: 60m 糾結壓縮..."
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

                df_60m["MA35"] = df_60m["Close"].rolling(35).mean()
                df_60m["MA200"] = df_60m["Close"].rolling(200).mean()
                df_60m["BB_Mid"] = df_60m["Close"].rolling(20).mean()
                std = df_60m["Close"].rolling(20).std()
                df_60m["BB_Upper"] = df_60m["BB_Mid"] + 2 * std
                df_60m["BB_Lower"] = df_60m["BB_Mid"] - 2 * std
                df_60m["BB_BW"] = (
                    (df_60m["BB_Upper"] - df_60m["BB_Lower"])
                    / df_60m["BB_Mid"]
                    * 100.0
                )

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
                f"✅ 選股完成！找到 {len(df_watch)} 檔個股並更新名單。"
            )
            st.dataframe(df_watch, use_container_width=True)
        else:
            st.warning("❌ 今日未篩選出符合條件之個股。")

    # 展示目前的觀察名單
    if os.path.exists(WATCHLIST_FILE):
        st.subheader("📋 當前觀察名單")
        df_current = pd.read_csv(WATCHLIST_FILE)
        st.dataframe(df_current, use_container_width=True)
    else:
        st.info("尚無觀察名單，請先執行盤前選股。")

# ----------------- TAB 2: 盤中監控 -----------------
with tab2:
    st.caption("條件：紅棒 + 帶量（>均量 1.5 倍）+ 突破布林上軌或糾結區")

    if st.button(
        "🔍 立即掃描盤中突破", key="btn_intraday", use_container_width=True
    ):
        if not os.path.exists(WATCHLIST_FILE):
            st.error("❌ 請先在【盤前觀察名單】分頁執行選股！")
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

                    df["MA35"] = df["Close"].rolling(35).mean()
                    df["Vol_MA20"] = df["Volume"].rolling(20).mean()
                    df["BB_Mid"] = df["Close"].rolling(20).mean()
                    std = df["Close"].rolling(20).std()
                    df["BB_Upper"] = df["BB_Mid"] + 2 * std

                    latest = df.iloc[-1]
                    prev = df.iloc[-2]

                    close_price = latest["Close"]
                    open_price = latest["Open"]
                    volume = latest["Volume"]
                    vol_ma20 = latest["Vol_MA20"]
                    bb_upper = latest["BB_Upper"]
                    ma35 = latest["MA35"]

                    cond_red = close_price > open_price
                    cond_vol = volume > (vol_ma20 * vol_multiplier)
                    cond_break = (close_price >= bb_upper) or (
                        prev["Close"] < prev["MA35"] and close_price > ma35
                    )

                    if cond_red and cond_vol and cond_break:
                        breakout_results.append(
                            {
                                "股票代碼": sym,
                                "現價": round(close_price, 2),
                                "爆量倍數": round(volume / vol_ma20, 2),
                                "突破布林上軌": (
                                    "是" if close_price >= bb_upper else "否"
                                ),
                            }
                        )
                except Exception:
                    pass

            monitor_bar.empty()

            if breakout_results:
                st.balloons()
                st.success(
                    f"🚨 發現 {len(breakout_results)} 檔股票觸發突破訊號！"
                )
                df_breakout = pd.DataFrame(breakout_results)
                st.dataframe(df_breakout, use_container_width=True)

                st.markdown("---")
                st.subheader("📊 突破股票走勢圖")
                selected_symbol = st.selectbox(
                    "選擇查看 K 線圖：",
                    [item["股票代碼"] for item in breakout_results],
                )
                if selected_symbol:
                    plot_stock_chart(selected_symbol)
            else:
                st.info("⌛ 目前無股票觸發帶量突破訊號。")
