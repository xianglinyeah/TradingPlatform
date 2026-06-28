using ExecutionService.Core.MarketRules;
using ExecutionService.Data.IRepositories;
using ExecutionService.Models;
using Microsoft.Extensions.Logging.Abstractions;
using Moq;
using Xunit;

namespace ExecutionService.Tests.MarketRules;

public class MarketRuleFactoryTests
{
    private readonly Mock<ITradeRepository> _tradeRepo = new();
    private readonly Mock<ISecMasterRepository> _secMaster = new();

    private SecMasterEntry Entry(string secType, string? board = null, bool isSt = false) => new()
    {
        Symbol = "600000.SH",
        SecType = secType,
        Board = board,
        IsSt = isSt
    };

    [Fact]
    public async Task GetRuleAsync_ConvertibleBondEntry_ReturnsCnConvertibleBondRules()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("113038.SH"))
                  .ReturnsAsync(Entry("convertible_bond"));

        var rule = await MarketRuleFactory.GetRuleAsync(
            "113038.SH", _tradeRepo.Object, _secMaster.Object, NullLogger.Instance);

        Assert.IsType<CnConvertibleBondRules>(rule);
    }

    [Fact]
    public async Task GetRuleAsync_StockEntry_ReturnsCnEquityRules()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("600000.SH"))
                  .ReturnsAsync(Entry("stock", "main"));

        var rule = await MarketRuleFactory.GetRuleAsync(
            "600000.SH", _tradeRepo.Object, _secMaster.Object, NullLogger.Instance);

        Assert.IsType<CnEquityRules>(rule);
    }

    [Fact]
    public async Task GetRuleAsync_EtfEntry_ReturnsCnETFRules()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("510300.SH"))
                  .ReturnsAsync(Entry("etf"));

        var rule = await MarketRuleFactory.GetRuleAsync(
            "510300.SH", _tradeRepo.Object, _secMaster.Object, NullLogger.Instance);

        Assert.IsType<CnETFRules>(rule);
    }

    [Fact]
    public async Task GetRuleAsync_UnknownSecType_ReturnsNoRestrictionRules()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("X.Y"))
                  .ReturnsAsync(Entry("some_future_type"));

        var rule = await MarketRuleFactory.GetRuleAsync(
            "X.Y", _tradeRepo.Object, _secMaster.Object, NullLogger.Instance);

        Assert.Equal("UNKNOWN", rule.MarketType);
    }

    [Fact]
    public async Task GetRuleAsync_NoEntry_FallsBackToSuffix()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("600000.SH"))
                  .ReturnsAsync((SecMasterEntry?)null);

        var rule = await MarketRuleFactory.GetRuleAsync(
            "600000.SH", _tradeRepo.Object, _secMaster.Object, NullLogger.Instance);

        // Suffix fallback maps .SH / .SZ to CN_EQUITY → CnEquityRules.
        Assert.IsType<CnEquityRules>(rule);
    }

    [Fact]
    public async Task GetRuleAsync_RepositoryThrows_FallsBackToSuffix()
    {
        _secMaster.Setup(r => r.GetBySymbolAsync("600000.SH"))
                  .ThrowsAsync(new InvalidOperationException("db down"));

        var rule = await MarketRuleFactory.GetRuleAsync(
            "600000.SH", _tradeRepo.Object, _secMaster.Object, NullLogger.Instance);

        Assert.IsType<CnEquityRules>(rule);
    }

    [Fact]
    public async Task GetRuleAsync_NullSecMaster_FallsBackToSuffix()
    {
        var rule = await MarketRuleFactory.GetRuleAsync(
            "000001.SZ", _tradeRepo.Object, secMaster: null, NullLogger.Instance);

        Assert.IsType<CnEquityRules>(rule);
    }
}
