using ExecutionService.Models;
using Xunit;

namespace ExecutionService.Tests.Models;

/// <summary>
/// Unit tests for Position.Add / Position.Reduce commission handling.
///
/// Regression coverage for the short-position commission sign bug:
///   Previously, short positions added commission into the effective sale
///   proceeds, inflating AvgPrice and overstating close PnL. The fix
///   subtracts commission because shorts are net-cash sales.
/// </summary>
public class PositionTests
{
    // ===== Long position: commission increases cost basis =====

    [Fact]
    public void LongPosition_Add_WithCommission_IncreasesCostBasis()
    {
        // Long 100 @ 10, then long 100 @ 12 with 2 yuan commission.
        // Total cost = (10*100) + (12*100) + 2 = 2202 -> AvgPrice = 11.01
        var pos = new Position { Side = PositionSide.Long, Quantity = 100, AvgPrice = 10m };
        pos.Add(100, 12m, 2m);

        Assert.Equal(200, pos.Quantity);
        Assert.True(pos.AvgPrice > 11m,
            $"Long commission should increase cost basis, got AvgPrice={pos.AvgPrice}");
        Assert.Equal(11.01m, pos.AvgPrice);
    }

    [Fact]
    public void LongPosition_Add_WithoutCommission_UsesPlainWeightedAverage()
    {
        var pos = new Position { Side = PositionSide.Long, Quantity = 100, AvgPrice = 10m };
        pos.Add(100, 12m, 0m);

        Assert.Equal(200, pos.Quantity);
        Assert.Equal(11m, pos.AvgPrice); // (1000 + 1200) / 200
    }

    // ===== Short position: commission reduces effective sale price =====

    [Fact]
    public void ShortPosition_Add_WithCommission_ReducesEffectiveSalePrice()
    {
        // Short 100 @ 10, then short 100 @ 12 with 2 yuan commission.
        // Effective sale proceeds = (10*100) + (12*100) - 2 = 2198 -> AvgPrice = 10.99
        var pos = new Position { Side = PositionSide.Short, Quantity = 100, AvgPrice = 10m };
        pos.Add(100, 12m, 2m);

        Assert.Equal(200, pos.Quantity);
        Assert.True(pos.AvgPrice < 11m,
            $"Short commission should reduce effective sale price (not increase), got AvgPrice={pos.AvgPrice}");
        Assert.Equal(10.99m, pos.AvgPrice);
    }

    /// <summary>
    /// Regression: the original bug added commission for shorts, producing 11.01 instead of 10.99.
    /// This test fails if the sign is flipped back to addition.
    /// </summary>
    [Fact]
    public void ShortPosition_Add_WithCommission_DoesNotProduceBugValue()
    {
        var pos = new Position { Side = PositionSide.Short, Quantity = 100, AvgPrice = 10m };
        pos.Add(100, 12m, 2m);

        // The buggy value (commission added) would be 11.01
        Assert.NotEqual(11.01m, pos.AvgPrice);
    }

    [Fact]
    public void ShortPosition_Add_WithoutCommission_UsesPlainWeightedAverage()
    {
        var pos = new Position { Side = PositionSide.Short, Quantity = 100, AvgPrice = 10m };
        pos.Add(100, 12m, 0m);

        Assert.Equal(200, pos.Quantity);
        Assert.Equal(11m, pos.AvgPrice);
    }

    // ===== Directional asymmetry =====

    /// <summary>
    /// Long vs short with identical inputs must produce different AvgPrice when commission > 0.
    /// This is the clearest expression of the fix: same numbers, opposite sign on commission.
    /// </summary>
    [Fact]
    public void LongAndShort_Add_WithSameCommission_ProduceMirrorAvgPrices()
    {
        var longPos = new Position { Side = PositionSide.Long, Quantity = 100, AvgPrice = 10m };
        var shortPos = new Position { Side = PositionSide.Short, Quantity = 100, AvgPrice = 10m };

        longPos.Add(100, 12m, 2m);
        shortPos.Add(100, 12m, 2m);

        Assert.True(longPos.AvgPrice > shortPos.AvgPrice,
            $"Long cost basis {longPos.AvgPrice} should exceed short effective sale {shortPos.AvgPrice}");
        Assert.Equal(11.01m, longPos.AvgPrice);
        Assert.Equal(10.99m, shortPos.AvgPrice);
    }

    // ===== Reduce: realized PnL commission handling =====

    [Fact]
    public void LongPosition_Reduce_WithCommission_ReducesRealizedPnL()
    {
        // Buy 200 @ 10, sell 100 @ 12 with 5 yuan commission.
        // saleValue = 12*100 - 5 = 1195; costBasis = 10*100 = 1000
        // RealizedPnL = 1195 - 1000 = 195
        var pos = new Position
        {
            Side = PositionSide.Long,
            Quantity = 200,
            AvgPrice = 10m,
            RealizedPnL = 0m
        };

        pos.Reduce(100, 12m, 5m);

        Assert.Equal(100, pos.Quantity);
        Assert.Equal(195m, pos.RealizedPnL);
    }

    [Fact]
    public void ShortPosition_Reduce_WithCommission_ReducesRealizedPnL()
    {
        // Short 200 @ 10 (effective sale @ 10), cover 100 @ 8 with 5 yuan commission.
        // For short: costBasis (effective sale value held) = 10*100 = 1000
        // buyback cost = 8*100 + 5 = 805
        // RealizedPnL += costBasis - buyback = 1000 - 805 = 195
        var pos = new Position
        {
            Side = PositionSide.Short,
            Quantity = 200,
            AvgPrice = 10m,
            RealizedPnL = 0m
        };

        pos.Reduce(100, 8m, 5m);

        Assert.Equal(100, pos.Quantity);
        Assert.Equal(195m, pos.RealizedPnL);
    }

    [Fact]
    public void Reduce_MoreThanHeld_ClampsToAvailable()
    {
        var pos = new Position
        {
            Side = PositionSide.Long,
            Quantity = 100,
            AvgPrice = 10m,
            RealizedPnL = 0m
        };

        pos.Reduce(150, 12m, 0m);

        Assert.Equal(0, pos.Quantity);
        // Only 100 shares realize PnL: (12*100) - (10*100) = 200
        Assert.Equal(200m, pos.RealizedPnL);
    }
}
