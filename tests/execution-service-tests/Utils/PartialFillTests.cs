using ExecutionService.Models;
using ExecutionService.Core.Utils;
using Xunit;

namespace ExecutionService.Tests.Utils;

/// <summary>
/// Partial fill split algorithm unit test (P1.1)
///
/// Covers:
///   - Threshold boundary (ratio < / == / > largeOrderVolumeRatio)
///   - Fill count decision (ratio -> 2/3/5/N fills)
///   - Invariants: total quantity conservation, price monotonicity, timestamp increment
///   - Boundaries: enabled=false, ADV=0, qty=0, maxPartialFills limit
/// </summary>
public class PartialFillTests
{
    private const decimal Adv = 1_000_000m;
    private const double Threshold = 0.001; // 0.1%
    private const int MaxFills = 5;

    private static Order MakeOrder(int qty, OrderSide side = OrderSide.Buy) => new()
    {
        Symbol = "600000.SH",
        Side = side,
        Quantity = qty,
        Price = 10m
    };

    private static MarketData MakeMarketData() => new()
    {
        Symbol = "600000.SH",
        Close = 10m,
        Timestamp = new DateTime(2023, 1, 3, 9, 30, 0, DateTimeKind.Utc)
    };

    // ===== Toggle and boundaries =====

    [Fact]
    public void Disabled_ReturnsNull()
    {
        var order = MakeOrder(50_000); // large order would normally split
        var fills = ExecutionHelper.GeneratePartialFills(
            order, MakeMarketData(), baseExecutionPrice: 10m,
            avgDailyVolume: Adv, enabled: false,
            maxPartialFills: MaxFills, largeOrderVolumeRatio: Threshold);
        Assert.Null(fills);
    }

    [Fact]
    public void ZeroAvgDailyVolume_ReturnsNull()
    {
        var order = MakeOrder(50_000);
        var fills = ExecutionHelper.GeneratePartialFills(
            order, MakeMarketData(), baseExecutionPrice: 10m,
            avgDailyVolume: 0m, enabled: true,
            maxPartialFills: MaxFills, largeOrderVolumeRatio: Threshold);
        Assert.Null(fills);
    }

    [Fact]
    public void ZeroQuantity_ReturnsNull()
    {
        var order = MakeOrder(0);
        var fills = ExecutionHelper.GeneratePartialFills(
            order, MakeMarketData(), baseExecutionPrice: 10m,
            avgDailyVolume: Adv, enabled: true,
            maxPartialFills: MaxFills, largeOrderVolumeRatio: Threshold);
        Assert.Null(fills);
    }

    // ===== Threshold boundary =====

    [Fact]
    public void RatioBelowThreshold_ReturnsNull_NoSplit()
    {
        // 500 shares / 1M = 0.05% < 0.1% -> single fill
        var order = MakeOrder(500);
        var fills = ExecutionHelper.GeneratePartialFills(
            order, MakeMarketData(), baseExecutionPrice: 10m,
            avgDailyVolume: Adv, enabled: true,
            maxPartialFills: MaxFills, largeOrderVolumeRatio: Threshold);
        Assert.Null(fills);
    }

    [Fact]
    public void RatioAtThreshold_TriggersSplit()
    {
        // 1000 shares / 1M = 0.1% = threshold. Condition is ratio < threshold returns null,
        // equal to threshold does not count as "less than", so should trigger split
        var order = MakeOrder(1000);
        var fills = ExecutionHelper.GeneratePartialFills(
            order, MakeMarketData(), baseExecutionPrice: 10m,
            avgDailyVolume: Adv, enabled: true,
            maxPartialFills: MaxFills, largeOrderVolumeRatio: Threshold);
        Assert.NotNull(fills);
        Assert.True(fills.Count >= 2);
    }

    // ===== Fill count decision =====

    [Theory]
    [InlineData(1000, 2)]    // 0.1% -> 2 fills
    [InlineData(5000, 2)]    // 0.5% -> 2 fills (< 1%)
    [InlineData(10_000, 3)]  // 1%   -> 3 fills (< 5%)
    [InlineData(40_000, 3)]  // 4%   -> 3 fills (< 5%)
    [InlineData(50_000, 5)]  // 5%   -> 5 fills (< 10%)
    [InlineData(90_000, 5)]  // 9%   -> 5 fills (< 10%)
    public void SplitCount_FollowsRatioBands(int qty, int expectedFills)
    {
        var order = MakeOrder(qty);
        var fills = ExecutionHelper.GeneratePartialFills(
            order, MakeMarketData(), baseExecutionPrice: 10m,
            avgDailyVolume: Adv, enabled: true,
            maxPartialFills: MaxFills, largeOrderVolumeRatio: Threshold);

        Assert.NotNull(fills);
        Assert.Equal(expectedFills, fills.Count);
    }

    [Fact]
    public void VeryLargeRatio_CappedToMaxFills()
    {
        // 200,000 / 1M = 20%, should use maxPartialFills
        var order = MakeOrder(200_000);
        var fills = ExecutionHelper.GeneratePartialFills(
            order, MakeMarketData(), baseExecutionPrice: 10m,
            avgDailyVolume: Adv, enabled: true,
            maxPartialFills: 3, // intentionally reduced
            largeOrderVolumeRatio: Threshold);

        Assert.NotNull(fills);
        Assert.Equal(3, fills.Count); // does not exceed maxPartialFills
    }

    [Fact]
    public void MaxFillsOne_LargeOrder_ReturnsSingleFill()
    {
        // maxPartialFills=1 forces single fill, equivalent to no split
        // Note: function still returns non-null list (because ratio > threshold), but only 1 fill
        var order = MakeOrder(50_000);
        var fills = ExecutionHelper.GeneratePartialFills(
            order, MakeMarketData(), baseExecutionPrice: 10m,
            avgDailyVolume: Adv, enabled: true,
            maxPartialFills: 1,
            largeOrderVolumeRatio: Threshold);

        Assert.NotNull(fills);
        Assert.Single(fills);
        Assert.Equal(50_000, fills[0].Quantity);
    }

    // ===== Invariant: total quantity conservation =====

    [Theory]
    [InlineData(1000)]
    [InlineData(5000)]
    [InlineData(50_000)]
    [InlineData(5500)]    // not a multiple of 100
    [InlineData(3333)]    // odd number, triggers split (0.33% -> 2 fills)
    public void TotalQuantityAlwaysConserved(int qty)
    {
        var order = MakeOrder(qty);
        var fills = ExecutionHelper.GeneratePartialFills(
            order, MakeMarketData(), baseExecutionPrice: 10m,
            avgDailyVolume: Adv, enabled: true,
            maxPartialFills: MaxFills, largeOrderVolumeRatio: Threshold);

        Assert.NotNull(fills);
        var sum = fills.Sum(f => f.Quantity);
        Assert.Equal(qty, sum);
    }

    // ===== Invariant: price monotonicity =====

    [Fact]
    public void BuyOrder_PricesMonotonicallyIncreasing()
    {
        // Note: algorithm uses Round(price, 2), small impact at base=10 may round to same value
        // Algorithm guarantees "non-strictly increasing" (>=), not "strictly increasing" (>)
        // Use base=100 to make impact visible, verify strictly increasing
        const decimal basePrice = 100m;
        var order = MakeOrder(50_000, OrderSide.Buy);
        var fills = ExecutionHelper.GeneratePartialFills(
            order, MakeMarketData(), baseExecutionPrice: basePrice,
            avgDailyVolume: Adv, enabled: true,
            maxPartialFills: MaxFills, largeOrderVolumeRatio: Threshold);

        Assert.NotNull(fills);
        for (int i = 1; i < fills.Count; i++)
        {
            Assert.True(fills[i].Price > fills[i - 1].Price,
                $"Buy prices should be strictly increasing: fill[{i - 1}]={fills[i - 1].Price} >= fill[{i}]={fills[i].Price}");
        }
    }

    [Fact]
    public void SellOrder_PricesMonotonicallyDecreasing()
    {
        const decimal basePrice = 100m;
        var order = MakeOrder(50_000, OrderSide.Sell);
        var fills = ExecutionHelper.GeneratePartialFills(
            order, MakeMarketData(), baseExecutionPrice: basePrice,
            avgDailyVolume: Adv, enabled: true,
            maxPartialFills: MaxFills, largeOrderVolumeRatio: Threshold);

        Assert.NotNull(fills);
        for (int i = 1; i < fills.Count; i++)
        {
            Assert.True(fills[i].Price < fills[i - 1].Price,
                $"Sell prices should be strictly decreasing: fill[{i - 1}]={fills[i - 1].Price} <= fill[{i}]={fills[i].Price}");
        }
    }

    [Fact]
    public void Prices_StaysWithinReasonableImpactBound()
    {
        // Single fill price impact cap is 0.5%, last fill cumulative may reach N * 0.5%
        // Overall should stay within base ±10% (safety threshold, much larger than actual algorithm impact)
        const decimal basePrice = 10m;
        var order = MakeOrder(50_000);
        var fills = ExecutionHelper.GeneratePartialFills(
            order, MakeMarketData(), baseExecutionPrice: basePrice,
            avgDailyVolume: Adv, enabled: true,
            maxPartialFills: MaxFills, largeOrderVolumeRatio: Threshold);

        Assert.NotNull(fills);
        foreach (var f in fills)
        {
            var deviation = Math.Abs(f.Price - basePrice) / basePrice;
            Assert.True(deviation < 0.10m,
                $"Single fill price deviation too large: {f.Price} vs base {basePrice}, deviation {deviation:P}");
        }
    }

    // ===== Invariant: timestamp increment =====

    [Fact]
    public void FillTimes_StrictlyIncreasing()
    {
        var order = MakeOrder(50_000);
        var md = MakeMarketData();
        var fills = ExecutionHelper.GeneratePartialFills(
            order, md, baseExecutionPrice: 10m,
            avgDailyVolume: Adv, enabled: true,
            maxPartialFills: MaxFills, largeOrderVolumeRatio: Threshold);

        Assert.NotNull(fills);
        for (int i = 1; i < fills.Count; i++)
        {
            Assert.True(fills[i].FillTime > fills[i - 1].FillTime,
                $"Timestamps should be increasing: fill[{i - 1}]={fills[i - 1].FillTime:o} >= fill[{i}]={fills[i].FillTime:o}");
        }
    }

    [Fact]
    public void FillTimes_AllWithinBarWindow()
    {
        // Split fill timestamps should be within [marketData.Timestamp, Timestamp + 60s]
        var order = MakeOrder(50_000);
        var md = MakeMarketData();
        var fills = ExecutionHelper.GeneratePartialFills(
            order, md, baseExecutionPrice: 10m,
            avgDailyVolume: Adv, enabled: true,
            maxPartialFills: MaxFills, largeOrderVolumeRatio: Threshold);

        Assert.NotNull(fills);
        var barEnd = md.Timestamp.AddSeconds(60);
        foreach (var f in fills)
        {
            Assert.True(f.FillTime >= md.Timestamp && f.FillTime <= barEnd,
                $"Timestamp {f.FillTime:o} should be within bar window [{md.Timestamp:o}, {barEnd:o}]");
        }
    }

    // ===== Invariant: A-share minimum trading unit =====

    [Fact]
    public void NonLastFills_AreMultiplesOf100()
    {
        // A-share minimum trading unit is 100 shares. Except the last fill (fallback absorbs remainder), each fill must be a multiple of 100
        var order = MakeOrder(50_000);
        var fills = ExecutionHelper.GeneratePartialFills(
            order, MakeMarketData(), baseExecutionPrice: 10m,
            avgDailyVolume: Adv, enabled: true,
            maxPartialFills: MaxFills, largeOrderVolumeRatio: Threshold);

        Assert.NotNull(fills);
        for (int i = 0; i < fills.Count - 1; i++)
        {
            Assert.True(fills[i].Quantity % 100 == 0,
                $"Non-last fill[{i}] quantity {fills[i].Quantity} must be a multiple of 100");
            Assert.True(fills[i].Quantity >= 100,
                $"Non-last fill[{i}] quantity {fills[i].Quantity} must be >= 100");
        }
    }

    [Fact]
    public void LastFill_AbsorbsRemainder()
    {
        // Order quantity must be large enough to trigger split, but not a multiple of 100
        // 10500 / 1M = 1.05% -> 3 fills; 10500 is not a multiple of 100
        var order = MakeOrder(10_500);
        var fills = ExecutionHelper.GeneratePartialFills(
            order, MakeMarketData(), baseExecutionPrice: 10m,
            avgDailyVolume: Adv, enabled: true,
            maxPartialFills: MaxFills, largeOrderVolumeRatio: Threshold);

        Assert.NotNull(fills);
        Assert.True(fills.Count >= 2);
        var nonLastSum = fills.Take(fills.Count - 1).Sum(f => f.Quantity);
        Assert.Equal(10_500, nonLastSum + fills[^1].Quantity);
        // Last fill absorbs all remainder as fallback
        Assert.True(fills[^1].Quantity > 0);
    }

    // ===== Comprehensive: large buy order full flow =====

    [Fact]
    public void BuyLargeOrder_AllInvariantsHold()
    {
        // Comprehensive test: 50000 shares buy, should satisfy all invariants
        // Use base=100 to make price impact visible, avoid rounding to same value
        const int qty = 50_000;
        const decimal basePrice = 100m;
        var order = MakeOrder(qty, OrderSide.Buy);
        var fills = ExecutionHelper.GeneratePartialFills(
            order, MakeMarketData(), baseExecutionPrice: basePrice,
            avgDailyVolume: Adv, enabled: true,
            maxPartialFills: MaxFills, largeOrderVolumeRatio: Threshold);

        Assert.NotNull(fills);

        // 1. Total quantity conservation
        Assert.Equal(qty, fills.Sum(f => f.Quantity));

        // 2. Fill count matches expectation (5% -> 5 fills)
        Assert.Equal(5, fills.Count);

        // 3. Prices strictly increasing (buy market impact)
        for (int i = 1; i < fills.Count; i++)
            Assert.True(fills[i].Price > fills[i - 1].Price);

        // 4. First fill price closest to base, last fill has largest deviation
        Assert.True(Math.Abs(fills[0].Price - basePrice) <= Math.Abs(fills[^1].Price - basePrice));

        // 5. Weighted average price >= base (buy impact should push average up)
        var weightedAvg = fills.Sum(f => f.Price * f.Quantity) / fills.Sum(f => f.Quantity);
        Assert.True(weightedAvg >= basePrice,
            $"Buy weighted average price {weightedAvg} should be >= base {basePrice}");

        // 6. Timestamps strictly increasing, all within bar
        var md = MakeMarketData();
        var barEnd = md.Timestamp.AddSeconds(60);
        for (int i = 1; i < fills.Count; i++)
        {
            Assert.True(fills[i].FillTime > fills[i - 1].FillTime);
            Assert.InRange(fills[i].FillTime, md.Timestamp, barEnd);
        }
    }
}
