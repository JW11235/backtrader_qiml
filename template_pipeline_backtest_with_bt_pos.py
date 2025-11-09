"""
根据输入仓位数据回测
注: 需要考虑停牌、涨跌停等信息
"""

import os
import sys
import datetime
import argparse
import numpy as np
import pandas as pd
import backtrader as bt
from loguru import logger


def setup_logger(log_dir: str=None, level: str='INFO'):
    """
    设置日志记录器
    """
    logger.remove()

    if log_dir:
        logger.add(
            log_dir, 
            level=level,
            format='{time:HH:mm:ss} | {level} | {message}',
            rotation='20 MB', 
            # retention='14 days', 
            encoding='utf-8', 
            enqueue=True
        )


def load_price_info(args, cerebro_):
    """
    加载价格数据
    注: 采用后复权数据
    """
    # 读取行情数据，并转换为 backtrader 可识别的格式
    # sec_code, datetime, open, high, low, close, volume, openinterest
    daily_price = pd.read_csv('./data/daily_price.csv', parse_dates=['datetime'])
    daily_price = daily_price.sort_values(['sec_code','datetime'])
    daily_price.set_index('datetime', inplace=True)
    
    # 按股票代码，依次循环传入数据
    for stock in daily_price['sec_code'].unique():
        # 日期对齐
        data = pd.DataFrame(index=daily_price.index.unique()) # 获取回测区间内所有交易日
        df = daily_price.query(f'sec_code==\'{stock}\'')[['open','high','low','close','volume','openinterest']]
        data_ = pd.merge(data, df, left_index=True, right_index=True, how='left')
        # 缺失值处理：日期对齐时会使得有些交易日的数据为空，所以需要对缺失数据进行填充
        data_.loc[:,['volume','openinterest']] = data_.loc[:,['volume','openinterest']].fillna(0)
        data_.loc[:,['open','high','low','close']] = data_.loc[:,['open','high','low','close']].ffill() # fillna(method='pad')
        data_.loc[:,['open','high','low','close']] = data_.loc[:,['open','high','low','close']].fillna(0)
        # 导入数据
        datafeed = bt.feeds.PandasData(dataname=data_, 
                                       fromdate=datetime.datetime(2019,1,2), 
                                       todate=datetime.datetime(2021,1,28))
        cerebro_.adddata(datafeed, name=stock) # 通过 name 实现数据集与股票的一一对应

    return cerebro_


class PositionRebalanceStrategy(bt.Strategy):
    """
    基于调仓表的策略
    """
    def __init__(self, position_file):
        # 读取调仓表，表结构如下所示：
        #       trade_date  stock_code    weight
        # 0     2019-01-31  000006.SZ   0.007282
        # 1     2019-01-31  000008.SZ   0.009783
        # ...   ...         ...         ...
        # 2494  2021-01-28  688088.SH   0.007600
        self.buy_stock = position_file
        self.trade_dates = pd.to_datetime(self.buy_stock['trade_date'].unique()).tolist()
        self.trade_dates = [d.date() for d in self.trade_dates]
        self.order_list = []        # 记录以往订单，方便调仓日对未完成订单做处理
        self.buy_stocks_pre = []    # 记录上一期持仓
    
    def log(self, txt, dt=None):
        ''' 策略日志打印函数'''
        dt = dt or self.datas[0].datetime.date(0)
        print('%s, %s' % (dt.isoformat(), txt))

    def next(self):
        dt = self.datas[0].datetime.date(0) # 获取当前的回测时间点
        # 如果是调仓日，则进行调仓操作
        if dt in self.trade_dates:
            print("--------------{} 为调仓日----------".format(dt))
            # 在调仓之前，取消之前所下的没成交也未到期的订单
            if len(self.order_list) > 0:
                for od in self.order_list:
                    self.cancel(od)     # 如果订单未完成，则撤销订单
                self.order_list = []    #重置订单列表

            # 提取当前调仓日的持仓列表
            buy_stocks_data = self.buy_stock.query(f"trade_date=='{dt}'")
            long_list = buy_stocks_data['sec_code'].tolist()
            print('long_list', long_list)   # 打印持仓列表
            # 对现有持仓中，调仓后不再继续持有的股票进行卖出平仓
            sell_stock = [i for i in self.buy_stocks_pre if i not in long_list]
            print('sell_stock', sell_stock) # 打印平仓列表
            if len(sell_stock) > 0:
                print("-----------对不再持有的股票进行平仓--------------")
                for stock in sell_stock:
                    data = self.getdatabyname(stock)
                    if self.getposition(data).size > 0 :
                        od = self.close(data=data)  
                        self.order_list.append(od) # 记录卖出订单

            # 买入此次调仓的股票：多退少补原则
            print("-----------买入此次调仓期的股票--------------")
            for stock in long_list:
                w = buy_stocks_data.query(f"sec_code=='{stock}'")['weight'].iloc[0] # 提取持仓权重
                data = self.getdatabyname(stock)
                order = self.order_target_percent(data=data, target=w*0.95) # 为减少可用资金不足的情况，留 5% 的现金做备用
                self.order_list.append(order)
       
            self.buy_stocks_pre = long_list  # 保存此次调仓的股票列表
        
    def notify_order(self, order):
        # 未被处理的订单
        if order.status in [order.Submitted, order.Accepted]:
            return
        # 已经处理的订单
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            if order.isbuy():
                self.log(
                        'BUY EXECUTED, ref:%.0f, Price: %.2f, Cost: %.2f, Comm %.2f, Size: %.2f, Stock: %s' %
                        (order.ref, # 订单编号
                         order.executed.price, # 成交价
                         order.executed.value, # 成交额
                         order.executed.comm, # 佣金
                         order.executed.size, # 成交量
                         order.data._name))  # 股票名称
            else:  # Sell
                self.log('SELL EXECUTED, ref:%.0f, Price: %.2f, Cost: %.2f, Comm %.2f, Size: %.2f, Stock: %s' %
                            (order.ref,
                             order.executed.price,
                             order.executed.value,
                             order.executed.comm,
                             order.executed.size,
                             order.data._name))


def run_backtest(args, positions):
    """
    通过 backtrader 回测策略
    """
    cerebro = bt.Cerebro()

    daily_price = pd.read_csv("./data/daily_price.csv", parse_dates=['datetime'])   # 
    # daily_price['datetime'] = pd.to_datetime(daily_price['datetime'], format='%Y-%m-%d')
    daily_price = daily_price.set_index(['datetime'])  # 将datetime设置成index
    
    # 实例化 cerebro
    cerebro = bt.Cerebro()

    # 加载行情数据
    cerebro = load_price_info(args, cerebro)

    # 初始资金 100,000,000    
    cerebro.broker.setcash(args.initial_cash) 

    # 佣金，双边各 0.0003
    cerebro.broker.setcommission(commission=args.commission_perc) 
    
    # 滑点：双边各 0.0001
    cerebro.broker.set_slippage_perc(perc=args.slippage_perc) 
    
    # 将编写的策略添加给大脑，别忘了 ！
    cerebro.addstrategy(PositionRebalanceStrategy, position_file=positions)
    
    # 回测时需要添加 PyFolio 分析器
    cerebro.addanalyzer(bt.analyzers.PyFolio, _name='pyfolio')
    results = cerebro.run()

    print('开始分析')
    # 借助 pyfolio 进一步做回测结果分析
    pyfolio = results[0].analyzers.pyfolio  # 注意：后面不要调用 .get_analysis() 方法
    # 或者是 result[0].analyzers.getbyname('pyfolio')
    returns, positions, transactions, gross_lev = pyfolio.get_pf_items()

    return returns, positions, transactions, gross_lev


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Backtest a strategy with backtrader.')
    parser.add_argument('--start_date', type=str, default='2019-01-01', help='Start date of the backtest in YYYY-MM-DD format.')
    parser.add_argument('--end_date', type=str, default='2021-12-31', help='End date of the backtest in YYYY-MM-DD format.')
    parser.add_argument('--log_dir', type=str, default='./logs', help='Directory to save logs.')
    parser.add_argument('--initial_cash', type=float, default=10000000, help='Initial cash for the backtest.')
    parser.add_argument('--commission_perc', type=float, default=0.0003, help='Commission percentage per trade side.')
    parser.add_argument('--slippage_perc', type=float, default=0.0001, help='Slippage percentage per trade side.')
    args = parser.parse_args()

    if not os.path.exists(args.log_dir):
        os.makedirs(args.log_dir, exist_ok=True)

    setup_logger(log_dir=os.path.join(args.log_dir, f'backtest_{args.start_date}_to_{args.end_date}.log'), 
                 level='INFO')

    logger.info('Starting backtest...')
    positions = pd.read_csv('./data/trade_info.csv', parse_dates=['trade_date']) 
    returns, positions, transactions, gross_lev = run_backtest(args, positions)

    print(returns)
    print(positions)
    print(transactions)
