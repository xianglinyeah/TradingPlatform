using ExecutionService.Core.MarketFeed;
using ExecutionService.Models;
using Xunit;

namespace ExecutionService.Tests.MarketFeed;

public class MarketDataCacheTests
{
    private static MarketData Bar(string symbol, decimal close) => new()
    {
        Symbol = symbol,
        Close = close,
        Timestamp = new DateTime(2023, 1, 3, 9, 30, 0, DateTimeKind.Utc)
    };

    [Fact]
    public void GetLatest_UnknownSymbol_ReturnsNull()
    {
        var cache = new MarketDataCache();
        Assert.Null(cache.GetLatest("600000.SH"));
    }

    [Fact]
    public void Update_ThenGetLatest_ReturnsTheSameBar()
    {
        var cache = new MarketDataCache();
        var bar = Bar("600000.SH", 12.5m);

        cache.Update(bar);

        var latest = cache.GetLatest("600000.SH");
        Assert.NotNull(latest);
        Assert.Equal(12.5m, latest!.Close);
    }

    [Fact]
    public void Update_ReplacesExistingBar()
    {
        var cache = new MarketDataCache();

        cache.Update(Bar("600000.SH", 10m));
        cache.Update(Bar("600000.SH", 11m));
        cache.Update(Bar("600000.SH", 12m));

        var latest = cache.GetLatest("600000.SH");
        Assert.NotNull(latest);
        Assert.Equal(12m, latest!.Close);
    }

    [Fact]
    public void Update_NullBarOrEmptySymbol_IsIgnored()
    {
        var cache = new MarketDataCache();

        cache.Update(null!);
        cache.Update(new MarketData { Symbol = "", Close = 1m });

        Assert.Equal(0, cache.Count);
    }

    [Fact]
    public void Update_TracksDistinctSymbols()
    {
        var cache = new MarketDataCache();

        cache.Update(Bar("600000.SH", 1m));
        cache.Update(Bar("000001.SZ", 2m));
        cache.Update(Bar("600519.SH", 3m));

        Assert.Equal(3, cache.Count);
        Assert.Equal(1m, cache.GetLatest("600000.SH")!.Close);
        Assert.Equal(2m, cache.GetLatest("000001.SZ")!.Close);
        Assert.Equal(3m, cache.GetLatest("600519.SH")!.Close);
    }
}
