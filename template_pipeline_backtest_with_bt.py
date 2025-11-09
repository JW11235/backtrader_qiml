import os
import sys
import argparse
import numpy as np
import pandas as pd
import backtrader as bt
from datetime import datetime


def run_backtest(args):
    pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Backtest a strategy with backtrader.')
    parser.add_argument('--start_date', type=str, default='2019-01-01', help='Start date of the backtest in YYYY-MM-DD format.')
    parser.add_argument('--end_date', type=str, default='2021-12-31', help='End date of the backtest in YYYY-MM-DD format.')
    parser.add_argument('--initial_cash', type=float, default=1000000, help='Initial cash for the backtest.')
    args = parser.parse_args()

    start_date = pd.to_datetime(args.start_date)
    end_date = pd.to_datetime(args.end_date)
    initial_cash = args.initial_cash

    # Initialize Cerebro engine
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(initial_cash)

    # Add your data feeds and strategy here
    # Example:
    # data = bt.feeds.PandasData(dataname=your_dataframe, fromdate=start_date, todate=end_date)
    # cerebro.adddata(data)
    # cerebro.addstrategy(StockSelectStrategy, position_file='path_to_your_position_file.csv')

    print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())
    cerebro.run()
    print('Final Portfolio Value: %.2f' % cerebro.broker.getvalue())