using ExecutionService.Core.Risk;
using ExecutionService.Data.ClickHouse;
using ExecutionService.Data.IRepositories;
using ExecutionService.Models;
using Microsoft.Extensions.Logging.Abstractions;
using Moq;
using Xunit;

namespace ExecutionService.Tests.Risk;

public class PriceLimitCheckerTests
{
    private readonly Mock<ISecMasterRepository> _secMaster = new();
    private readonly Mock<IClickHouseClient> _clickhouse = new();
    private readonly PriceLimitChecker _checker;

    public PriceLimitCheckerTests()
    {
        _checker = new PriceLimitChecker(_secMaster.Object, _clickhouse.Object, NullLogger<PriceLimitChecker>.Instance);
    }

    private static Order BuyOrder(string symbol, DateTime createdAt) => new()
    {
        Symbol = symbol,
        Side = OrderSide.Buy,
        CreatedAt = createdAt
    };

    private static Order SellOrder(string symbol, DateTime createdAt) => new()
    {
        Symbol = symbol,
        Side = OrderSide.Sell,
        CreatedAt = createdAt
    };

    private static MarketData Md(decimal close) => new() { Close = close };

    [Fact]
    public async Task Check_NoSecMasterEntry_Skips()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("600000.SH"))
                  .ReturnsAsync((SecMasterEntry?)null);

        var result = await _checker.CheckAsync(BuyOrder("600000.SH", DateTime.UtcNow), Md(11m));

        Assert.True(result.Allowed);
        Assert.Contains("sec_master", result.Reason ?? "");
    }

    [Fact]
    public async Task Check_NoPriorClose_Skips()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("600000.SH"))
                  .ReturnsAsync(new SecMasterEntry { Symbol = "600000.SH", SecType = "stock", Board = "main" });
        _clickhouse.Setup(c => c.GetPriorCloseAsync("600000.SH", It.IsAny<DateTime>()))
                   .ReturnsAsync((decimal?)null);

        var result = await _checker.CheckAsync(BuyOrder("600000.SH", DateTime.UtcNow), Md(11m));

        Assert.True(result.Allowed);
        Assert.Contains("prior close", result.Reason ?? "");
    }

    [Fact]
    public async Task Check_BuyAtLimitUp_MainBoard_Rejects()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("600000.SH"))
                  .ReturnsAsync(new SecMasterEntry { Symbol = "600000.SH", SecType = "stock", Board = "main" });
        _clickhouse.Setup(c => c.GetPriorCloseAsync("600000.SH", It.IsAny<DateTime>()))
                   .ReturnsAsync(10m);

        var order = BuyOrder("600000.SH", DateTime.UtcNow);
        var result = await _checker.CheckAsync(order, Md(11m));  // 10 * 1.10 = 11.0

        Assert.False(result.Allowed);
        Assert.Contains("limit-up", result.Reason ?? "");
    }

    [Fact]
    public async Task Check_BuyInsideBand_MainBoard_Allows()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("600000.SH"))
                  .ReturnsAsync(new SecMasterEntry { Symbol = "600000.SH", SecType = "stock", Board = "main" });
        _clickhouse.Setup(c => c.GetPriorCloseAsync("600000.SH", It.IsAny<DateTime>()))
                   .ReturnsAsync(10m);

        var result = await _checker.CheckAsync(
            BuyOrder("600000.SH", DateTime.UtcNow), Md(10.5m));

        Assert.True(result.Allowed);
        Assert.Equal(11m, result.LimitUp);
        Assert.Equal(9m, result.LimitDown);
    }

    [Fact]
    public async Task Check_SellAtLimitDown_MainBoard_Rejects()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("600000.SH"))
                  .ReturnsAsync(new SecMasterEntry { Symbol = "600000.SH", SecType = "stock", Board = "main" });
        _clickhouse.Setup(c => c.GetPriorCloseAsync("600000.SH", It.IsAny<DateTime>()))
                   .ReturnsAsync(10m);

        var result = await _checker.CheckAsync(
            SellOrder("600000.SH", DateTime.UtcNow), Md(9m));  // 10 * 0.90 = 9.0

        Assert.False(result.Allowed);
        Assert.Contains("limit-down", result.Reason ?? "");
    }

    [Fact]
    public async Task Check_ChiNext_Uses20PercentBand()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("300750.SZ"))
                  .ReturnsAsync(new SecMasterEntry { Symbol = "300750.SZ", SecType = "stock", Board = "chinext" });
        _clickhouse.Setup(c => c.GetPriorCloseAsync("300750.SZ", It.IsAny<DateTime>()))
                   .ReturnsAsync(100m);

        // 100 * 1.20 = 120 — buy at exactly 120 hits limit.
        var atLimit = await _checker.CheckAsync(
            BuyOrder("300750.SZ", DateTime.UtcNow), Md(120m));
        Assert.False(atLimit.Allowed);

        // Buy at 119.99 inside the band.
        var inside = await _checker.CheckAsync(
            BuyOrder("300750.SZ", DateTime.UtcNow), Md(119m));
        Assert.True(inside.Allowed);
        Assert.Equal(120m, inside.LimitUp);
    }

    [Fact]
    public async Task Check_StarBoard_Uses20PercentBand()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("688981.SH"))
                  .ReturnsAsync(new SecMasterEntry { Symbol = "688981.SH", SecType = "stock", Board = "star" });
        _clickhouse.Setup(c => c.GetPriorCloseAsync("688981.SH", It.IsAny<DateTime>()))
                   .ReturnsAsync(50m);

        var result = await _checker.CheckAsync(
            BuyOrder("688981.SH", DateTime.UtcNow), Md(60m));  // 50 * 1.20 = 60

        Assert.False(result.Allowed);
    }

    [Fact]
    public async Task Check_BSE_Uses30PercentBand()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("830799.BJ"))
                  .ReturnsAsync(new SecMasterEntry { Symbol = "830799.BJ", SecType = "stock", Board = "beijing" });
        _clickhouse.Setup(c => c.GetPriorCloseAsync("830799.BJ", It.IsAny<DateTime>()))
                   .ReturnsAsync(10m);

        // 10 * 1.30 = 13 — buy at 12.5 inside, buy at 13 hits limit.
        var inside = await _checker.CheckAsync(
            BuyOrder("830799.BJ", DateTime.UtcNow), Md(12.5m));
        Assert.True(inside.Allowed);
        Assert.Equal(13m, inside.LimitUp);

        var atLimit = await _checker.CheckAsync(
            BuyOrder("830799.BJ", DateTime.UtcNow), Md(13m));
        Assert.False(atLimit.Allowed);
    }

    [Fact]
    public async Task Check_StStock_Uses5PercentBand()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("600000.SH"))
                  .ReturnsAsync(new SecMasterEntry { Symbol = "600000.SH", SecType = "stock", Board = "main", IsSt = true });
        _clickhouse.Setup(c => c.GetPriorCloseAsync("600000.SH", It.IsAny<DateTime>()))
                   .ReturnsAsync(10m);

        // ST band: 10 * 1.05 = 10.5 — buy at 10.5 hits limit (main would have been 11).
        var stHit = await _checker.CheckAsync(
            BuyOrder("600000.SH", DateTime.UtcNow), Md(10.5m));
        Assert.False(stHit.Allowed);
        Assert.Equal(10.5m, stHit.LimitUp);
    }

    [Fact]
    public async Task Check_NonStMainBoard_10_5_IsInsideBand()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("600000.SH"))
                  .ReturnsAsync(new SecMasterEntry { Symbol = "600000.SH", SecType = "stock", Board = "main", IsSt = false });
        _clickhouse.Setup(c => c.GetPriorCloseAsync("600000.SH", It.IsAny<DateTime>()))
                   .ReturnsAsync(10m);

        // 10.5 is below the 10% limit-up (11) for non-ST main board.
        var result = await _checker.CheckAsync(
            BuyOrder("600000.SH", DateTime.UtcNow), Md(10.5m));
        Assert.True(result.Allowed);
        Assert.Equal(11m, result.LimitUp);
    }
}
