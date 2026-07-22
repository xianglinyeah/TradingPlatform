using ExecutionService.Models;
using ExecutionService.Core.Utils;
using Xunit;

namespace ExecutionService.Tests.Utils;

public class SlippageCalculatorTests
{
    [Fact]
    public void CalculateMarketOrderSlippage_Buy100_ReturnsCorrectSlippage()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            OrderType = OrderType.Market,
            Quantity = 1000,
            Price = 100m
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 100m
        };

        // Act
        var executionPrice = ExecutionHelper.CalculateExecutionPriceWithSlippage(order, marketData);

        // Assert - buy at 100 yuan, should slip up by 0.03% = 0.03 yuan
        var expectedPrice = 100m + (100m * 0.0003m);
        Assert.Equal(expectedPrice, executionPrice);
    }

    [Fact]
    public void CalculateMarketOrderSlippage_Sell100_ReturnsCorrectSlippage()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test",
            Symbol = "600000.SH",
            Side = OrderSide.Sell,
            OrderType = OrderType.Market,
            Quantity = 1000,
            Price = 100m
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 100m
        };

        // Act
        var executionPrice = ExecutionHelper.CalculateExecutionPriceWithSlippage(order, marketData);

        // Assert - sell at 100 yuan, should slip down by 0.03% = 0.03 yuan
        var expectedPrice = 100m - (100m * 0.0003m);
        Assert.Equal(expectedPrice, executionPrice);
    }

    [Fact]
    public void LargeOrder_Buy_ReturnsHigherSlippage()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            OrderType = OrderType.Market,
            Quantity = 15000, // large order: 1.5% of average daily volume
            Price = 100m
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 100m
        };

        // Act
        var executionPrice = ExecutionHelper.CalculateExecutionPriceWithSlippage(
            order, marketData, avgDailyVolume: 1000000m);

        // Assert - should have small slippage + additional slippage
        Assert.True(executionPrice > 100m);
        Assert.True(executionPrice < 100.05m); // should not exceed maximum additional slippage
    }

    [Fact]
    public void LimitOrder_WithinTolerance_ReturnsSmallSlippage()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            OrderType = OrderType.Limit,
            Quantity = 1000,
            Price = 100.05m // limit price 100.05, market price 100.00, deviation 0.05% < 1%
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 100m
        };

        // Act
        var executionPrice = ExecutionHelper.CalculateExecutionPriceWithSlippage(order, marketData);

        // Assert
        var expectedSlippage = 100.05m * TradingConstants.LIMIT_ORDER_SLIPPAGE;
        Assert.Equal(100.05m + expectedSlippage, executionPrice);
    }

    [Fact]
    public void LimitOrder_OutsideTolerance_NoSlippage()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            OrderType = OrderType.Limit,
            Quantity = 1000,
            Price = 102m // limit price 102, market price 100, deviation 2% > 1%
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 100m
        };

        // Act
        var executionPrice = ExecutionHelper.CalculateExecutionPriceWithSlippage(order, marketData);

        // Assert - price deviation too large, do not apply slippage
        Assert.Equal(102m, executionPrice);
    }

    [Fact]
    public void Commission_CalculatedWithSlippagedPrice_ReturnsCorrectCommission()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            OrderType = OrderType.Market,
            Quantity = 10000, // 10,000 shares
            Price = 10m
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 10m
        };

        // Act - apply slippage
        order.Price = ExecutionHelper.CalculateExecutionPriceWithSlippage(order, marketData);

        // Assert - commission should be calculated based on post-slippage price
        var commission = ExecutionHelper.CalculateCommission(order);
        var expectedCommission = 10000 * order.Price * TradingConstants.COMMISSION_RATE;

        Assert.Equal(expectedCommission, commission);
    }
}
