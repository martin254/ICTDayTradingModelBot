from AlgorithmImports import *

class ICTDayTradingModel(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 6, 30)
        self.SetCash(100000)
        self.symbol = self.AddForex("EURUSD", Resolution.Minute).Symbol
        self.stopLossPercentage = 0.01  # Risk 1% per trade
        self.riskRewardRatio = 2  # Minimum 1:2 risk-to-reward ratio

        # Session and key level trackers
        self.asianHigh = None
        self.asianLow = None
        self.bias = None
        self.liquidityGrabbed = False
        self.secondaryRallyConfirmed = False
        self.fvgZone = None
        self.oteZone = None
        self.previousDayHigh = None
        self.previousDayLow = None
        self.previousWeekHigh = None
        self.previousWeekLow = None

        # ATR for dynamic stop loss
        self.atr = self.ATR(self.symbol, 14, Resolution.Hour)

        # Session timing
        self.asianSessionEnd = time(5, 0)  # End of Asian session
        self.londonSessionEnd = time(12, 0)  # End of London session
        self.nyKillZoneStart = time(13, 0)  # NY Killzone start
        self.nyKillZoneEnd = time(16, 0)  # NY Killzone end

        # Order tracking
        self.activeOrderTicket = None
        self.stopLossTicket = None
        self.takeProfitTicket = None

    def OnData(self, data):
        if not data.ContainsKey(self.symbol):
            return

        current_time = self.Time.time()
        price = data[self.symbol].Close

        # Update higher-timeframe levels
        self.UpdateHigherTimeframeLevels()

        # Track Asian session high/low
        if current_time < self.asianSessionEnd:
            self.TrackAsianSessionHighLow(price)
            return

        # Determine bias based on which side of the Asian range is taken out first
        if not self.liquidityGrabbed and self.asianHigh and self.asianLow and time(6, 0) <= current_time < self.londonSessionEnd:
            if price < self.asianLow:
                self.bias = "bearish"
                self.liquidityGrabbed = True
                self.Debug(f"Turtle Soup below Asian low at {price}. Bias set to bearish.")
            elif price > self.asianHigh:
                self.bias = "bullish"
                self.liquidityGrabbed = True
                self.Debug(f"Turtle Soup above Asian high at {price}. Bias set to bullish.")

        # Confirm secondary rally in London session
        if self.liquidityGrabbed and not self.secondaryRallyConfirmed and time(6, 0) <= current_time < self.londonSessionEnd:
            if self.ConfirmSecondaryRally(price) and self.CheckLondonSessionHighLow(price):
                self.secondaryRallyConfirmed = True
                self.Debug(f"Secondary rally confirmed at {price}. Important level targeted.")

        # Detect FVG and OTE zones after secondary rally
        if self.secondaryRallyConfirmed and not self.fvgZone:
            candles = self.History(self.symbol, 10, Resolution.Minute)
            self.fvgZone = self.DetectFairValueGap(candles)
            if self.fvgZone:
                self.Debug(f"FVG detected: {self.fvgZone}")
            if self.bias == "bullish":
                self.oteZone = self.CalculateOTEZone(max(candles["high"]), self.asianLow)
            elif self.bias == "bearish":
                self.oteZone = self.CalculateOTEZone(self.asianHigh, min(candles["low"]))

        # Execute trades during NY Killzone
        if self.nyKillZoneStart <= current_time <= self.nyKillZoneEnd and not self.Portfolio.Invested:
            candles = self.History(self.symbol, 10, Resolution.Minute)
            if self.ConfluenceCheck(price, candles):
                self.PlaceTrade(price)

    def TrackAsianSessionHighLow(self, price):
        # Track high and low during Asian session
        if self.asianHigh is None or price > self.asianHigh:
            self.asianHigh = price
        if self.asianLow is None or price < self.asianLow:
            self.asianLow = price

    def UpdateHigherTimeframeLevels(self):
        # Update daily and weekly high/low levels
        daily_history = self.History(self.symbol, 1, Resolution.Daily)
        if not daily_history.empty:
            self.previousDayHigh = daily_history["high"].iloc[-1]
            self.previousDayLow = daily_history["low"].iloc[-1]

        weekly_history = self.History(self.symbol, 5, Resolution.Daily)
        if not weekly_history.empty:
            self.previousWeekHigh = weekly_history["high"].max()
            self.previousWeekLow = weekly_history["low"].min()

    def DetectFairValueGap(self, candles):
        # Detect Fair Value Gaps using three-candle logic
        for i in range(len(candles) - 2):
            if candles.iloc[i]["high"] < candles.iloc[i + 1]["low"]:  # Bullish FVG
                if candles.iloc[i + 2]["low"] > candles.iloc[i]["high"]:  # Gap remains unfilled
                    return (candles.iloc[i]["high"], candles.iloc[i + 1]["low"])
            elif candles.iloc[i]["low"] > candles.iloc[i + 1]["high"]:  # Bearish FVG
                if candles.iloc[i + 2]["high"] < candles.iloc[i]["low"]:  # Gap remains unfilled
                    return (candles.iloc[i + 1]["high"], candles.iloc[i]["low"])
        return None

    def CalculateOTEZone(self, swing_high, swing_low):
        # Calculate Optimal Trade Entry zone
        fib_62 = swing_high - (0.62 * (swing_high - swing_low))
        fib_79 = swing_high - (0.79 * (swing_high - swing_low))
        return (fib_62, fib_79)

    def ConfirmSecondaryRally(self, price):
        # Confirm price moves to the opposite side of the Asian range
        if self.bias == "bullish":
            return price < self.asianLow
        elif self.bias == "bearish":
            return price > self.asianHigh
        return False

    def CheckLondonSessionHighLow(self, price):
        # Confirm price targets important levels in London session
        if self.bias == "bullish":
            return price < self.previousDayLow or price < self.previousWeekLow
        elif self.bias == "bearish":
            return price > self.previousDayHigh or price > self.previousWeekHigh
        return False

    def ConfluenceCheck(self, price, candles):
        # Ensure all conditions align before taking a trade
        return (
            self.liquidityGrabbed and
            self.secondaryRallyConfirmed and
            self.CheckLondonSessionHighLow(price) and
            self.CheckMarketStructureShift()
        )

    def CheckMarketStructureShift(self):
        # Confirm market structure shift after liquidity grab
        recent_candles = self.History(self.symbol, 10, Resolution.Minute)
        if self.bias == "bullish":
            return recent_candles["low"].iloc[-2] > recent_candles["low"].iloc[-3] and \
                   recent_candles["high"].iloc[-1] > recent_candles["high"].iloc[-2]
        elif self.bias == "bearish":
            return recent_candles["high"].iloc[-2] < recent_candles["high"].iloc[-3] and \
                   recent_candles["low"].iloc[-1] < recent_candles["low"].iloc[-2]
        return False

    def PlaceTrade(self, price):
        atr_value = self.atr.Current.Value
        if atr_value <= 0:
            self.Debug("ATR value is invalid or zero. Skipping trade.")
            return

        # Calculate stop-loss and take-profit
        stop_loss = self.oteZone[0] if self.bias == "bullish" else self.oteZone[1]
        take_profit = price + (atr_value * self.riskRewardRatio) if self.bias == "bullish" else price - (atr_value * self.riskRewardRatio)

        # Calculate order quantity
        quantity = round(self.Portfolio.TotalPortfolioValue * self.stopLossPercentage / abs(price - stop_loss), 2)
        if quantity <= 0:
            self.Debug("Order quantity is zero. Skipping trade.")
            return

        # Place market order and attach stop-loss and take-profit
        self.activeOrderTicket = self.MarketOrder(self.symbol, quantity if self.bias == "bullish" else -quantity)
        self.stopLossTicket = self.StopMarketOrder(self.symbol, -quantity if self.bias == "bullish" else quantity, stop_loss)
        self.takeProfitTicket = self.LimitOrder(self.symbol, -quantity if self.bias == "bearish" else quantity, take_profit)

        self.Debug(f"Placed trade: Entry at {price}, Stop Loss at {stop_loss}, Take Profit at {take_profit}.")
