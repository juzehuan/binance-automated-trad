import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Config:

    REFRESH_INTERVAL = 2  # REST API刷新间隔(秒)

    # 交易对配置
    SYMBOLS = ["ACHUSDT"]
    INTERVAL = '15m'  # K线周期

    # RSI指标配置
    RSI_PERIOD = 6
    OVERBOUGHT = 30
    OVERSOLD = 25

    # 交易配置
    TESTNET = False
    LEVERAGE = 10
    TAKE_PROFIT_PERCENT = 5

    # API配置
    API_KEY = os.getenv('TEST_API_KEY' if TESTNET else 'ROOT_API_KEY')
    API_SECRET = os.getenv('TEST_API_SECRET' if TESTNET else 'ROOT_API_SECRET')

    # 代理配置
    PROXIES = {
        'http': 'http://127.0.0.1:7890',
        'https': 'http://127.0.0.1:7890'
    }

    # 日志配置
    LOG_FILE = 'trading.log'
    LOG_LEVEL = 'INFO'