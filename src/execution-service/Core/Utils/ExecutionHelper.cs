using ExecutionService.Models;

namespace ExecutionService.Core.Utils;

/// <summary>
/// Execution helper utility class
/// Contains shared order processing logic
/// </summary>
public static class ExecutionHelper
{
    /// <summary>
    /// Fill simulated order (execute immediately at current market price)
    /// </summary>
    /// <param name="order">Order object</param>
    /// <param name="marketData">Market data</param>
    /// <param name="commission">Commission (optional, calculated by default)</param>
    public static void FillSimulatedOrder(Order order, MarketData marketData, decimal? commission = null)
    {
        order.Status = OrderStatus.Filled;
        order.FillPrice = order.Price; // Use price after slippage
        order.FilledQuantity = order.Quantity;
        order.FilledAt = marketData.Timestamp; // Use historical market time for T+1 validation
        order.Commission = commission ?? CalculateCommission(order);
    }

    /// <summary>
    /// Calculate A-share commission (0.025%, minimum 5 yuan)
    /// </summary>
    /// <param name="order">Order object</param>
    /// <returns>Commission amount</returns>
    public static decimal CalculateCommission(Order order)
    {
        var commission = order.Quantity * order.Price * TradingConstants.COMMISSION_RATE;
        return Math.Max(commission, TradingConstants.MIN_COMMISSION);
    }

    /// <summary>
    /// Calculate execution price with slippage
    /// </summary>
    /// <param name="order">Order object</param>
    /// <param name="marketData">Market data</param>
    /// <param name="avgDailyVolume">Average daily volume (optional, default 1 million)</param>
    /// <returns>Execution price</returns>
    public static decimal CalculateExecutionPriceWithSlippage(
        Order order,
        MarketData marketData,
        decimal avgDailyVolume = TradingConstants.DEFAULT_AVG_DAILY_VOLUME)
    {
        decimal basePrice = marketData.Close;
        decimal executionPrice;

        switch (order.OrderType)
        {
            case OrderType.Market:
                executionPrice = CalculateMarketOrderWithSlippage(order, basePrice, avgDailyVolume);
                break;

            case OrderType.Limit:
                executionPrice = CalculateLimitOrderWithSlippage(order, basePrice);
                break;

            case OrderType.Stop:
                executionPrice = CalculateStopOrderWithSlippage(order, marketData);
                break;

            default:
                throw new NotSupportedException(
                    $"OrderType {order.OrderType} is not implemented in slippage calculation. " +
                    "Only Market, Limit, and Stop are supported.");
        }

        return executionPrice;
    }

    /// <summary>
    /// Calculate market order price with slippage (considering order size)
    /// </summary>
    private static decimal CalculateMarketOrderWithSlippage(
        Order order,
        decimal basePrice,
        decimal avgDailyVolume)
    {
        // Base slippage: 0.03%
        decimal slippagePercent = TradingConstants.MARKET_ORDER_SLIPPAGE;

        // Order size adjustment
        decimal volumeRatio = order.Quantity / avgDailyVolume;
        if (volumeRatio > TradingConstants.LARGE_ORDER_THRESHOLD)
        {
            // Extra slippage: for every 1% increase in volume, slippage increases by 0.01%
            decimal extraSlippage = Math.Min(
                volumeRatio * TradingConstants.LARGE_ORDER_SLIPPAGE_FACTOR,
                TradingConstants.MAX_EXTRA_SLIPPAGE
            );
            slippagePercent += extraSlippage;
        }

        decimal slippage = basePrice * slippagePercent;

        // Buy orders slip upward, sell orders slip downward
        return order.Side == OrderSide.Buy
            ? basePrice + slippage
            : basePrice - slippage;
    }

    /// <summary>
    /// Calculate limit order price with slippage
    /// </summary>
    private static decimal CalculateLimitOrderWithSlippage(Order order, decimal basePrice)
    {
        // Limit order: check if price is reasonable
        decimal priceDiff = (order.Price - basePrice) / basePrice;

        // If limit price deviates more than 1%, order may not execute
        if (Math.Abs(priceDiff) > TradingConstants.LIMIT_ORDER_PRICE_TOLERANCE)
        {
            // No execution, return original price (or consider throwing exception)
            return order.Price;
        }

        // Limit price within reasonable range, small slippage
        decimal slippagePercent = TradingConstants.LIMIT_ORDER_SLIPPAGE;
        decimal slippage = order.Price * slippagePercent;

        return order.Side == OrderSide.Buy
            ? order.Price + slippage
            : order.Price - slippage;
    }

    /// <summary>
    /// Calculate stop order price with slippage
    /// </summary>
    private static decimal CalculateStopOrderWithSlippage(Order order, MarketData marketData)
    {
        // Stop order: becomes market order after trigger, use market order logic
        decimal slippagePercent = TradingConstants.MARKET_ORDER_SLIPPAGE;
        decimal slippage = marketData.Close * slippagePercent;

        return order.Side == OrderSide.Buy
            ? marketData.Close + slippage
            : marketData.Close - slippage;
    }

    /// <summary>
    /// Whether a Stop order's trigger price has been crossed by the latest bar.
    ///
    /// Buy stops trigger when the market trades at or above the stop (typical
    /// use: stop-loss for a short, or breakout entry). Sell stops trigger when
    /// the market trades at or below the stop (typical use: stop-loss for a
    /// long, or breakdown entry). Symmetric and unambiguous.
    /// </summary>
    public static bool IsStopTriggered(Order order, MarketData marketData)
        => order.Side == OrderSide.Buy
            ? marketData.Close >= order.StopPrice
            : marketData.Close <= order.StopPrice;

    // ====================================================================
    // P1.1: Partial fill splitting
    // ====================================================================

    /// <summary>
    /// Generate a partial fill sequence based on the order-size-to-average-daily-volume ratio
    /// Rules:
    ///   ratio &lt; SimLargeOrderVolumeRatio: 1 full fill (return null, caller uses original FillSimulatedOrder)
    ///   medium ratio: split into 2-3 fills, prices slightly increase (simulate matching pressure)
    ///   large ratio: split into 5-N fills, significant price impact
    /// Each fill timestamp is evenly distributed within the bar period.
    /// </summary>
    /// <returns>List of fills, or null to indicate no splitting (use single-fill logic)</returns>
    public static List<PartialFillInfo>? GeneratePartialFills(
        Order order,
        MarketData marketData,
        decimal baseExecutionPrice,
        decimal avgDailyVolume,
        bool enabled,
        int maxPartialFills,
        double largeOrderVolumeRatio)
    {
        if (!enabled) return null;
        if (avgDailyVolume <= 0) return null;
        if (order.Quantity <= 0) return null;

        decimal ratio = order.Quantity / avgDailyVolume;
        if (ratio < (decimal)largeOrderVolumeRatio)
        {
            return null; // Single fill path
        }

        // Determine number of fills based on volume ratio
        int fills;
        if (ratio < TradingConstants.PARTIAL_FILL_RATIO_TWO_FILLS) fills = 2;
        else if (ratio < TradingConstants.PARTIAL_FILL_RATIO_THREE_FILLS) fills = 3;
        else if (ratio < TradingConstants.PARTIAL_FILL_RATIO_FIVE_FILLS) fills = 5;
        else fills = Math.Max(5, maxPartialFills);

        fills = Math.Min(fills, maxPartialFills);

        // Price impact: each 1% of daily volume adds 0.05% price impact
        // (buy: pushes up, sell: pushes down). Spread across fills to model
        // consumption of the order book.
        decimal perFillImpactPercent = Math.Min(
            ratio * TradingConstants.PARTIAL_FILL_PRICE_IMPACT_FACTOR / fills,
            TradingConstants.PARTIAL_FILL_MAX_PER_FILL_IMPACT);

        // Split quantity: first fill is largest (takes out the floating best ask), subsequent fills decrease
        // Simple allocation: weights 1/2, 1/4, 1/8, ..., last fill takes the remainder
        var weights = new decimal[fills];
        decimal totalWeight = 0;
        for (int i = 0; i < fills; i++)
        {
            weights[i] = i == fills - 1 ? 0 : (decimal)(1.0 / Math.Pow(2, i + 1));
            totalWeight += weights[i];
        }
        // Tail fill takes whatever remains
        weights[fills - 1] = Math.Max(TradingConstants.PARTIAL_FILL_TAIL_WEIGHT_MIN, 1 - totalWeight);

        var result = new List<PartialFillInfo>(fills);
        decimal accumulatedQty = 0;
        for (int i = 0; i < fills; i++)
        {
            decimal qty;
            if (i == fills - 1)
            {
                qty = order.Quantity - accumulatedQty;
            }
            else
            {
                qty = decimal.Round(order.Quantity * weights[i], 0, MidpointRounding.ToZero);
                // Round to board lot (100 shares minimum per A-share rules)
                qty = Math.Max(TradingConstants.ASHARE_MIN_TRADE_UNIT, decimal.Floor(qty / TradingConstants.ASHARE_MIN_TRADE_UNIT) * TradingConstants.ASHARE_MIN_TRADE_UNIT);
            }
            if (qty <= 0) continue;

            // Price increases per fill (buy) / decreases per fill (sell)
            decimal priceImpact = perFillImpactPercent * (i + 1) * baseExecutionPrice;
            decimal fillPrice = order.Side == OrderSide.Buy
                ? baseExecutionPrice + priceImpact
                : baseExecutionPrice - priceImpact;
            fillPrice = decimal.Round(fillPrice, 2, MidpointRounding.AwayFromZero);

            // Timestamps: evenly distributed within the bar period
            var fillTime = marketData.Timestamp.AddSeconds(TradingConstants.DEFAULT_BAR_PERIOD_SECONDS * (i + 1.0) / (fills + 1));

            accumulatedQty += qty;
            result.Add(new PartialFillInfo { Quantity = qty, Price = fillPrice, FillTime = fillTime });
        }

        return result;
    }

    /// <summary>Partial fill split result</summary>
    public class PartialFillInfo
    {
        public decimal Quantity { get; set; }
        public decimal Price { get; set; }
        public DateTime FillTime { get; set; }
    }
}
