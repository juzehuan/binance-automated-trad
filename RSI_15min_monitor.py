import requests
import pandas as pd
import time
import datetime
import numpy as np
import logging
import threading
from retry import retry

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("../perpetual_rsi_monitor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("PerpetualRSIMonitor")


# 配置参数 - 永续合约版本
class Config:
    SYMBOL = ["PUMPUSDT", "CRVUSDT", "FARTCOINUSDT", "ACHUSDT", "ONDOUSDT"]  # 交易对（永续合约）
    INTERVAL = "15m"  # K线周期
    RSI_PERIOD = 6  # RSI计算周期
    OVERBOUGHT = 50  # 超买阈值
    OVERSOLD = 40  # 超卖阈值
    CHECK_INTERVAL = 5  # 检查间隔(秒)
    DINGDING_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=b8547d280dbe99c9845b95f726e2c3c82e1b9749540e5cb1b91ae5e9884ffa70"
    API_RETRY_TIMES = 3  # API请求重试次数
    API_RETRY_DELAY = 5  # API请求重试延迟(秒)
    ALERT_COOLDOWN = 5  # 警报冷却时间(秒)
    # 永续合约API端点
    FUTURES_BASE_URL = "https://fapi.binance.com"
    KLINE_URL = "/fapi/v1/klines"
    MARK_PRICE_URL = "/fapi/v1/premiumIndex"
    CURRENT_PRICE_URL = "/fapi/v1/ticker/price"


# 状态跟踪
class MonitorState:
    def __init__(self):
        self.in_overbought = False
        self.in_oversold = False
        self.last_overbought_alert = 0
        self.last_oversold_alert = 0
        self.last_enter_overbought = 0
        self.last_enter_oversold = 0


state = MonitorState()


@retry(tries=Config.API_RETRY_TIMES, delay=Config.API_RETRY_DELAY)
def get_binance_futures_klines(symbol, interval, limit=300):
    """获取永续合约K线数据，带重试机制"""
    url = f"{Config.FUTURES_BASE_URL}{Config.KLINE_URL}"
    params = {"symbol": symbol, "interval": interval, "limit": limit}

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # 检查请求是否成功
    except requests.exceptions.RequestException as e:
        logger.error(f"API请求异常: {e}")
        raise

    data = response.json()
    df = pd.DataFrame(data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])

    # 时间转换
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')

    # 数据类型转换
    numeric_cols = ['open', 'high', 'low', 'close', 'volume']
    df[numeric_cols] = df[numeric_cols].astype(float)

    return df


@retry(tries=Config.API_RETRY_TIMES, delay=Config.API_RETRY_DELAY)
def get_binance_futures_current_price(symbol):
    """获取永续合约当前最新价格"""
    url = f"{Config.FUTURES_BASE_URL}{Config.CURRENT_PRICE_URL}"
    params = {"symbol": symbol}
    response = requests.get(url, params=params)
    data = response.json()
    return float(data['price'])


@retry(tries=Config.API_RETRY_TIMES, delay=Config.API_RETRY_DELAY)
def get_binance_futures_mark_price(symbol):
    """获取永续合约标记价格（用于合约交易和计算资金费率）"""
    url = f"{Config.FUTURES_BASE_URL}{Config.MARK_PRICE_URL}"
    params = {"symbol": symbol}
    response = requests.get(url, params=params)
    data = response.json()
    return float(data['markPrice'])


@retry(tries=Config.API_RETRY_TIMES, delay=Config.API_RETRY_DELAY)
def get_binance_funding_rate(symbol):
    """获取永续合约资金费率"""
    url = f"{Config.FUTURES_BASE_URL}/fapi/v1/fundingRate"
    params = {"symbol": symbol, "limit": 1}
    response = requests.get(url, params=params)
    data = response.json()
    return {
        'fundingRate': float(data[0]['fundingRate']),
        'fundingTime': pd.to_datetime(int(data[0]['fundingTime']), unit='ms')
    }


def calculate_rsi(data, period=14):
    """使用Wilder's Smoothing方法计算RSI，返回包含RSI列的DataFrame"""
    close_prices = data['close']
    deltas = close_prices.diff()

    # 分离涨跌幅
    gains = deltas.where(deltas > 0, 0)
    losses = -deltas.where(deltas < 0, 0)

    # 计算平均收益和损失
    avg_gain = gains.rolling(window=period, min_periods=period).mean()
    avg_loss = losses.rolling(window=period, min_periods=period).mean()

    # 处理前n个数据点后的平均收益和损失
    for i in range(period, len(avg_gain)):
        avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gains.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + losses.iloc[i]) / period

    # 计算RSI
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    # 添加RSI列到原始DataFrame
    data['rsi'] = rsi
    return data


def send_dingding_alert(message):
    """发送钉钉警报"""
    headers = {"Content-Type": "application/json"}
    payload = {
        "msgtype": "text",
        "text": {
            "content": f"币安永续合约15m监控警报\n{message}"
        }
    }

    try:
        response = requests.post(Config.DINGDING_WEBHOOK, json=payload, headers=headers)
        response.raise_for_status()
        logger.info(f"钉钉通知发送成功")
    except Exception as e:
        logger.error(f"发送钉钉通知失败: {e}")


def check_rsi(symbol, state):
    try:
        # 获取K线数据
        klines = get_binance_futures_klines(symbol, Config.INTERVAL, Config.RSI_PERIOD + 100)

        # 获取当前价格和标记价格
        current_price = get_binance_futures_current_price(symbol)
        mark_price = get_binance_futures_mark_price(symbol=symbol)

        # 获取资金费率信息
        funding_rate_info = get_binance_funding_rate(symbol)
        next_funding_time = funding_rate_info['fundingTime']
        funding_rate = funding_rate_info['fundingRate'] * 100  # 转换为百分比

        # 计算RSI
        klines_with_rsi = calculate_rsi(klines, Config.RSI_PERIOD)
        current_rsi = klines_with_rsi['rsi'].iloc[-1]
        latest_price = klines_with_rsi['close'].iloc[-1]
        current_time = time.time()

        # 价格差异分析
        price_diff_percent = ((current_price - latest_price) / latest_price) * 100
        mark_diff_percent = ((mark_price - latest_price) / latest_price) * 100

        # 记录并打印
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(
            f"{timestamp} - {symbol} 价格对比: K线收盘价={latest_price:.8f}, 当前最新价={current_price:.8f}({price_diff_percent:+.4f}%), 标记价={mark_price:.8f}({mark_diff_percent:+.4f}%) RSI: {current_rsi:.2f}"
        )
        logger.info(f"{timestamp} - 资金费率: {funding_rate:.4f}% 下次更新: {next_funding_time}")

        # 检查超买情况
        if current_rsi > Config.OVERBOUGHT:
            if not state.in_overbought:
                # 刚进入超买区域
                state.in_overbought = True
                state.last_enter_overbought = current_time
                message = f"[WARNING] 进入超买区域! {symbol} RSI = {current_rsi:.2f} (>={Config.OVERBOUGHT})\n当前最新价: {current_price:.8f}\n标记价: {mark_price:.8f}\n资金费率: {funding_rate:.4f}%\n下次更新: {next_funding_time}"
                logger.warning(message)
                send_dingding_alert(message)
            else:
                # 检查是否超过冷却时间
                if current_time - state.last_overbought_alert > Config.ALERT_COOLDOWN:
                    state.last_overbought_alert = current_time
                    duration = int(current_time - state.last_enter_overbought)
                    message = f"[WARNING] 持续超买! {symbol} RSI = {current_rsi:.2f} (>{Config.OVERBOUGHT})\n当前最新价: {current_price:.8f}\n标记价: {mark_price:.8f}\n资金费率: {funding_rate:.4f}%\n下次更新: {next_funding_time}\n已持续: {duration}秒"
                    logger.warning(message)
                    send_dingding_alert(message)
        else:
            if state.in_overbought:
                # 刚离开超买区域
                duration = int(current_time - state.last_enter_overbought)
                state.in_overbought = False
                message = f"[INFO] 退出超买区域! {symbol} RSI = {current_rsi:.2f} (<={Config.OVERBOUGHT})\n当前最新价: {current_price:.8f}\n标记价: {mark_price:.8f}\n资金费率: {funding_rate:.4f}%\n下次更新: {next_funding_time}\n持续时间: {duration}秒"
                logger.info(message)
                send_dingding_alert(message)

        # 检查超卖情况
        if current_rsi < Config.OVERSOLD:
            if not state.in_oversold:
                # 刚进入超卖区域
                state.in_oversold = True
                state.last_enter_oversold = current_time
                message = f"[WARNING] 进入超卖区域! {symbol} RSI = {current_rsi:.2f} (<{Config.OVERSOLD})\n当前最新价: {current_price:.8f}\n标记价: {mark_price:.8f}\n资金费率: {funding_rate:.4f}%\n下次更新: {next_funding_time}"
                logger.warning(message)
                send_dingding_alert(message)
            else:
                # 检查是否超过冷却时间
                if current_time - state.last_oversold_alert > Config.ALERT_COOLDOWN:
                    state.last_oversold_alert = current_time
                    duration = int(current_time - state.last_enter_oversold)
                    message = f"[WARNING] 持续超卖! {symbol} RSI = {current_rsi:.2f} (<{Config.OVERSOLD})\n当前最新价: {current_price:.8f}\n标记价: {mark_price:.8f}\n资金费率: {funding_rate:.4f}%\n下次更新: {next_funding_time}\n已持续: {duration}秒"
                    logger.warning(message)
                    send_dingding_alert(message)
        else:
            if state.in_oversold:
                # 刚离开超卖区域
                duration = int(current_time - state.last_enter_oversold)
                state.in_oversold = False
                message = f"[INFO] 退出超卖区域! {symbol} RSI = {current_rsi:.2f} (>={Config.OVERSOLD})\n当前最新价: {current_price:.8f}\n标记价: {mark_price:.8f}\n资金费率: {funding_rate:.4f}%\n下次更新: {next_funding_time}\n持续时间: {duration}秒"
                logger.info(message)
                send_dingding_alert(message)

    except Exception as e:
        logger.error(f"监控出错: {e}")
        send_dingding_alert(f"监控脚本异常: {str(e)}")


def monitor_symbol(symbol):
    state = MonitorState()
    logger.info(f"开始监控 {symbol} 永续合约 RSI 指标...")
    while True:
        try:
            check_rsi(symbol, state)
        except Exception as e:
            logger.error(f"{symbol} 监控循环错误: {e}")
        time.sleep(Config.CHECK_INTERVAL)


if __name__ == "__main__":
    # 去重交易对列表
    unique_symbols = list(set(Config.SYMBOL))
    logger.info(f"开始监控多个交易对: {unique_symbols} 永续合约 RSI 指标...")
    logger.info(
        f"配置参数: 周期={Config.RSI_PERIOD}, 超买={Config.OVERBOUGHT}, 超卖={Config.OVERSOLD}, 检查间隔={Config.CHECK_INTERVAL}秒"
    )
    logger.info(f"警报模式: 超买/超卖区域状态变化提醒及持续状态提醒")

    # 创建并启动线程
    threads = []
    for symbol in unique_symbols:
        thread = threading.Thread(target=monitor_symbol, args=(symbol,))
        threads.append(thread)
        thread.start()
        logger.info(f"已启动 {symbol} 的监控线程")

    # 等待所有线程完成
    for thread in threads:
        thread.join()