using ExecutionService.Models;
using ExecutionService.Core.Utils;
using Xunit;

namespace ExecutionService.Tests.Utils;

public class ExecutionHelperTests
{
    [Fact]
    public void CalculateCommission_SmallOrder_AppliesMinCommission()
    {
        // Arrange
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 100,    // 100 shares
            Price = 5m          // 5 yuan/share, total 500 yuan
        };

        // Act
        var commission = ExecutionHelper.CalculateCommission(order);

        // Assert
        // Normal commission = 100 * 5 * 0.00025 = 0.125 yuan
        // But minimum commission is 5 yuan
        Assert.Equal(5m, commission);
    }

    [Fact]
    public void CalculateCommission_MediumOrder_AppliesRateCommission()
    {
        // Arrange
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 1000,   // 1000 shares
            Price = 10m        // 10 yuan/share, total 10000 yuan
        };

        // Act
        var commission = ExecutionHelper.CalculateCommission(order);

        // Assert
        // Commission = 1000 * 10 * 0.00025 = 2.5 yuan
        // Below minimum 5 yuan, should charge 5 yuan
        Assert.Equal(5m, commission);
    }

    [Fact]
    public void CalculateCommission_LargeOrder_AppliesRateCommission()
    {
        // Arrange
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 10000,  // 10000 shares
            Price = 10m       // 10 yuan/share, total 100000 yuan
        };

        // Act
        var commission = ExecutionHelper.CalculateCommission(order);

        // Assert
        // Commission = 10000 * 10 * 0.00025 = 25 yuan
        // Exceeds minimum 5 yuan, calculated at actual rate
        Assert.Equal(25m, commission);
    }

    [Fact]
    public void CalculateCommission_VeryLargeOrder_AppliesRateCommission()
    {
        // Arrange
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Sell,
            Quantity = 50000,  // 50000 shares
            Price = 20m       // 20 yuan/share, total 1000000 yuan
        };

        // Act
        var commission = ExecutionHelper.CalculateCommission(order);

        // Assert
        // Commission = 50000 * 20 * 0.00025 = 250 yuan
        Assert.Equal(250m, commission);
    }

    [Fact]
    public void CalculateCommission_ExactMinThreshold_AppliesMinCommission()
    {
        // Arrange
        // Calculate the trade volume that exactly reaches 5 yuan
        // 5 = quantity * price * 0.00025
        // quantity * price = 20000
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 2000,   // 2000 shares
            Price = 10m       // 10 yuan/share, total 20000 yuan
        };

        // Act
        var commission = ExecutionHelper.CalculateCommission(order);

        // Assert
        // Commission = 2000 * 10 * 0.00025 = 5 yuan
        // Exactly equals minimum commission
        Assert.Equal(5m, commission);
    }

    [Fact]
    public void CalculateCommission_JustAboveMinThreshold_AppliesCalculatedCommission()
    {
        // Arrange
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 2001,   // slightly above threshold
            Price = 10m
        };

        // Act
        var commission = ExecutionHelper.CalculateCommission(order);

        // Assert
        // Commission = 2001 * 10 * 0.00025 = 5.0025 yuan
        // Should calculate at actual rate, not 5 yuan
        Assert.Equal(5.0025m, commission);
    }

    [Fact]
    public void FillSimulatedOrder_SetsOrderStatusToFilled()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 1000,
            Price = 10m,
            Status = OrderStatus.Pending
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 10m
        };

        // Act
        ExecutionHelper.FillSimulatedOrder(order, marketData);

        // Assert
        Assert.Equal(OrderStatus.Filled, order.Status);
        Assert.Equal(1000, order.FilledQuantity);
        Assert.Equal(10m, order.FillPrice);
        Assert.NotNull(order.FilledAt);
    }

    [Fact]
    public void FillSimulatedOrder_WithCustomCommission_UsesCustomCommission()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 10000,
            Price = 10m
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 10m
        };

        // Act
        ExecutionHelper.FillSimulatedOrder(order, marketData, commission: 15m);

        // Assert
        Assert.Equal(15m, order.Commission);
    }

    [Fact]
    public void FillSimulatedOrder_WithoutCustomCommission_CalculatesCommission()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 10000,
            Price = 10m
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 10m
        };

        // Act
        ExecutionHelper.FillSimulatedOrder(order, marketData);

        // Assert
        // Should auto-calculate commission: 10000 * 10 * 0.00025 = 25 yuan
        Assert.Equal(25m, order.Commission);
    }

    [Fact]
    public void FillSimulatedOrder_SetsFilledAtToCurrentTime()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 1000,
            Price = 10m
        };

        var expectedTime = DateTime.UtcNow;
        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 10m,
            Timestamp = expectedTime  
        };

        // Act
        ExecutionHelper.FillSimulatedOrder(order, marketData);

        // Assert
        Assert.NotNull(order.FilledAt);
        var timeDiff = (order.FilledAt.Value - expectedTime).Duration();
        Assert.True(timeDiff < TimeSpan.FromMilliseconds(100),
            $"Expected time: {expectedTime:yyyy-MM-dd HH:mm:ss.fff}, Actual: {order.FilledAt:yyyy-MM-dd HH:mm:ss.fff}");
    }

    [Fact]
    public void FillSimulatedOrder_UsesOrderPriceAsFillPrice()
    {
        // Arrange
        var order = new Order
        {
            OrderId = "test-order",
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 1000,
            Price = 12.50m  
        };

        var marketData = new MarketData
        {
            Symbol = "600000.SH",
            Close = 10m  
        };

        // Act
        ExecutionHelper.FillSimulatedOrder(order, marketData);

        // Assert
        Assert.Equal(12.50m, order.FillPrice);
    }

    [Fact]
    public void CalculateCommission_LargeOrder_CalculatesCorrectCommission()
    {
        // Arrange
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 5000,
            Price = 10m
        };

        // Act
        var commission = ExecutionHelper.CalculateCommission(order);

        // Assert
        Assert.Equal(12.5m, commission);
    }

    [Fact]
    public void CalculateCommission_VeryLargeOrder_CalculatesCorrectCommission()
    {
        // Arrange
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 10000,
            Price = 20m
        };

        // Act
        var commission = ExecutionHelper.CalculateCommission(order);

        // Assert
        Assert.Equal(50m, commission);
    }

    // ====================================================================
    // Partial fill regression tests (P1.1)
    // ====================================================================

    private static MarketData MakeMarketData(decimal close = 10m) => new()
    {
        Symbol = "600000.SH",
        Close = close,
        Timestamp = new DateTime(2023, 1, 3, 9, 30, 0, DateTimeKind.Utc)
    };

    /// <summary>
    /// Property test: the sum of partial fill quantities must equal the original
    /// order quantity. This is the core conservation invariant — if any fill is
    /// dropped or double-counted, the executed quantity will not match the order.
    /// </summary>
    [Theory]
    [InlineData(10000, OrderSide.Buy)]
    [InlineData(50000, OrderSide.Buy)]
    [InlineData(10000, OrderSide.Sell)]
    [InlineData(3333, OrderSide.Buy)]   // odd, triggers split
    [InlineData(10500, OrderSide.Buy)]  // not a multiple of 100
    public void GeneratePartialFills_SumOfFills_EqualsOrderQuantity(int qty, OrderSide side)
    {
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = side,
            Quantity = qty,
            Price = 10m
        };
        var md = MakeMarketData();

        var fills = ExecutionHelper.GeneratePartialFills(
            order, md, baseExecutionPrice: 10m,
            avgDailyVolume: 1_000_000m, enabled: true,
            maxPartialFills: 10, largeOrderVolumeRatio: 0.001);

        Assert.NotNull(fills);
        var totalQty = fills.Sum(f => f.Quantity);
        Assert.Equal(order.Quantity, totalQty);
    }

    /// <summary>
    /// Small orders below the largeOrderVolumeRatio threshold must not be split.
    /// Returning null is the contract signal to the caller to use single-fill logic.
    /// </summary>
    [Fact]
    public void GeneratePartialFills_SmallOrder_ReturnsNull()
    {
        // 100 shares / 1M = 0.01% < 0.1% threshold -> no split
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 100,
            Price = 10m
        };
        var md = MakeMarketData();

        var fills = ExecutionHelper.GeneratePartialFills(
            order, md, baseExecutionPrice: 10m,
            avgDailyVolume: 1_000_000m, enabled: true,
            maxPartialFills: 10, largeOrderVolumeRatio: 0.001);

        Assert.Null(fills);
    }

    /// <summary>
    /// Disabled flag must short-circuit to null regardless of order size.
    /// </summary>
    [Fact]
    public void GeneratePartialFills_Disabled_ReturnsNull()
    {
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 50000, // would normally split
            Price = 10m
        };
        var md = MakeMarketData();

        var fills = ExecutionHelper.GeneratePartialFills(
            order, md, baseExecutionPrice: 10m,
            avgDailyVolume: 1_000_000m, enabled: false,
            maxPartialFills: 10, largeOrderVolumeRatio: 0.001);

        Assert.Null(fills);
    }

    /// <summary>
    /// Zero average daily volume must not throw DivideByZeroException; it should
    /// fall back to null (single fill).
    /// </summary>
    [Fact]
    public void GeneratePartialFills_ZeroAvgDailyVolume_ReturnsNull()
    {
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 50000,
            Price = 10m
        };
        var md = MakeMarketData();

        var fills = ExecutionHelper.GeneratePartialFills(
            order, md, baseExecutionPrice: 10m,
            avgDailyVolume: 0m, enabled: true,
            maxPartialFills: 10, largeOrderVolumeRatio: 0.001);

        Assert.Null(fills);
    }

    /// <summary>
    /// Regression: quantity must be strictly positive to produce fills.
    /// </summary>
    [Fact]
    public void GeneratePartialFills_ZeroQuantity_ReturnsNull()
    {
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 0,
            Price = 10m
        };
        var md = MakeMarketData();

        var fills = ExecutionHelper.GeneratePartialFills(
            order, md, baseExecutionPrice: 10m,
            avgDailyVolume: 1_000_000m, enabled: true,
            maxPartialFills: 10, largeOrderVolumeRatio: 0.001);

        Assert.Null(fills);
    }

    /// <summary>
    /// Boundary: at exactly the threshold ratio (0.1% of ADV), splitting must trigger.
    /// The condition is ratio &lt; threshold returns null; equal does not.
    /// </summary>
    [Fact]
    public void GeneratePartialFills_AtThreshold_TriggersSplit()
    {
        // 1000 / 1M = 0.1% = threshold
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 1000,
            Price = 10m
        };
        var md = MakeMarketData();

        var fills = ExecutionHelper.GeneratePartialFills(
            order, md, baseExecutionPrice: 10m,
            avgDailyVolume: 1_000_000m, enabled: true,
            maxPartialFills: 10, largeOrderVolumeRatio: 0.001);

        Assert.NotNull(fills);
        Assert.True(fills.Count >= 2);
    }

    /// <summary>
    /// Buy orders: each successive fill should have price >= the previous one
    /// (non-strictly increasing, since small impact at base=10 may round to the
    /// same value). Using base=100 makes the impact visible and strict.
    /// </summary>
    [Fact]
    public void GeneratePartialFills_BuyOrder_PricesMonotonicallyIncreasing()
    {
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 50000,
            Price = 10m
        };
        var md = MakeMarketData(close: 100m);

        var fills = ExecutionHelper.GeneratePartialFills(
            order, md, baseExecutionPrice: 100m,
            avgDailyVolume: 1_000_000m, enabled: true,
            maxPartialFills: 10, largeOrderVolumeRatio: 0.001);

        Assert.NotNull(fills);
        for (int i = 1; i < fills.Count; i++)
        {
            Assert.True(fills[i].Price >= fills[i - 1].Price,
                $"Buy prices should be non-decreasing: fill[{i - 1}]={fills[i - 1].Price} > fill[{i}]={fills[i].Price}");
        }
    }

    /// <summary>
    /// Sell orders: each successive fill should have price <= the previous one.
    /// </summary>
    [Fact]
    public void GeneratePartialFills_SellOrder_PricesMonotonicallyDecreasing()
    {
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Sell,
            Quantity = 50000,
            Price = 10m
        };
        var md = MakeMarketData(close: 100m);

        var fills = ExecutionHelper.GeneratePartialFills(
            order, md, baseExecutionPrice: 100m,
            avgDailyVolume: 1_000_000m, enabled: true,
            maxPartialFills: 10, largeOrderVolumeRatio: 0.001);

        Assert.NotNull(fills);
        for (int i = 1; i < fills.Count; i++)
        {
            Assert.True(fills[i].Price <= fills[i - 1].Price,
                $"Sell prices should be non-increasing: fill[{i - 1}]={fills[i - 1].Price} < fill[{i}]={fills[i].Price}");
        }
    }

    /// <summary>
    /// Fill timestamps must be strictly increasing and lie within the bar window
    /// [marketData.Timestamp, Timestamp + 60s].
    /// </summary>
    [Fact]
    public void GeneratePartialFills_TimestampsStrictlyIncreasingWithinBar()
    {
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 50000,
            Price = 10m
        };
        var md = MakeMarketData();

        var fills = ExecutionHelper.GeneratePartialFills(
            order, md, baseExecutionPrice: 10m,
            avgDailyVolume: 1_000_000m, enabled: true,
            maxPartialFills: 10, largeOrderVolumeRatio: 0.001);

        Assert.NotNull(fills);
        var barEnd = md.Timestamp.AddSeconds(60);
        for (int i = 0; i < fills.Count; i++)
        {
            Assert.InRange(fills[i].FillTime, md.Timestamp, barEnd);
            if (i > 0)
            {
                Assert.True(fills[i].FillTime > fills[i - 1].FillTime,
                    $"Timestamps must be strictly increasing: fill[{i - 1}]={fills[i - 1].FillTime:o} >= fill[{i}]={fills[i].FillTime:o}");
            }
        }
    }

    /// <summary>
    /// maxPartialFills must cap the number of generated fills, even when the
    /// volume ratio would otherwise produce more splits.
    /// </summary>
    [Fact]
    public void GeneratePartialFills_RespectsMaxPartialFillsCap()
    {
        // 200000 / 1M = 20% would normally produce max(5, maxPartialFills) fills.
        var order = new Order
        {
            Symbol = "600000.SH",
            Side = OrderSide.Buy,
            Quantity = 200000,
            Price = 10m
        };
        var md = MakeMarketData();

        var fills = ExecutionHelper.GeneratePartialFills(
            order, md, baseExecutionPrice: 10m,
            avgDailyVolume: 1_000_000m, enabled: true,
            maxPartialFills: 3, largeOrderVolumeRatio: 0.001);

        Assert.NotNull(fills);
        Assert.Equal(3, fills.Count);

        // Quantity must still be conserved despite the cap.
        Assert.Equal(order.Quantity, fills.Sum(f => f.Quantity));
    }
}
