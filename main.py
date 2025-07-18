from binance.client import Client
from binance import ThreadedWebsocketManager
from dotenv import load_dotenv
import os
import logging
import signal
import time
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

load_dotenv()
api_key = os.getenv('TEST_API_KEY')
api_secret = os.getenv('TEST_API_SECRET')

proxies = {
    'http': 'http://127.0.0.1:7890',
    'https': 'http://127.0.0.1:7890'
}



# 初始化变量
twm=None # websocket
client=None # 客户端

def handle_socket_message(msg):
    print(f"message type: {msg['e']}")
    print(msg)
def createWebSocket():
    global twm
    symbol = 'BNBBTC'
    twm = ThreadedWebsocketManager(api_key=api_key, api_secret=api_secret,  testnet=True,https_proxy='http://127.0.0.1:7890')
    # start is required to initialise its internal loop
    twm.start()



    twm.start_kline_socket(callback=handle_socket_message, symbol=symbol)

    # multiple sockets can be started
    twm.start_depth_socket(callback=handle_socket_message, symbol=symbol)

    # or a multiplex socket can be started like this
    # see Binance docs for stream names
    streams = ['bnbbtc@kline']
    twm.start_multiplex_socket(callback=handle_socket_message, streams=streams)

    return twm

def closeWebSocket():
    global twm
    if twm is not None:
        twm.stop()
        logging.info("WebSocket连接已关闭")
        twm = None
    else:
        logging.warning("没有活动的WebSocket连接")

# 定义信号处理函数，用于优雅退出
def signal_handler(sig, frame):
    logging.info('收到退出信号，正在关闭WebSocket...')
    closeWebSocket()
    logging.info('程序已退出')
    exit(0)
def main():

    # 解决时间戳不同步问题：启用自动时间同步
    client = Client(api_key, api_secret, {'proxies': proxies}, testnet=True)
    client.ping()  # 测试连接并自动同步时间

    # 启动WebSocket
    createWebSocket()



    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 保持程序运行
    logging.info('程序正在运行，按Ctrl+C退出...')
    while True:
        time.sleep(1)

if __name__ == '__main__':
    main()
