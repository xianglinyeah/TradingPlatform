using ExecutionService.Models;
using ExecutionService.Data.IRepositories;

namespace ExecutionService.Core.MarketRules;

/// <summary>
/// Market rule factory
/// Identifies the market type from the stock symbol and returns the corresponding rule instance.
/// </summary>
public static class MarketRuleFactory
{
    /// <summary>
    /// Get the market rule for the given stock symbol (with dependency injection)
    /// </summary>
    /// <param name="symbol">Stock symbol (standard format, e.g. 600000.SH)</param>
    /// <param name="tradeRepo">Trade data repository (used for T+1 settlement checks)</param>
    /// <returns>Market rule instance</returns>
    public static IMarketRule GetRule(string symbol, ITradeRepository? tradeRepo = null)
    {
        var marketType = IdentifyMarket(symbol);

        return marketType switch
        {
            "CN_EQUITY" => new CnEquityRules(tradeRepo!), // A-share rules require TradeRepository
            "US_EQUITY" => new NoRestrictionRules(), // US stocks: no restrictions for now
            "HK_EQUITY" => new NoRestrictionRules(), // HK stocks: no restrictions for now
            _ => new NoRestrictionRules() // Default: no restrictions
        };
    }

    /// <summary>
    /// Identify the market type from the stock symbol
    /// </summary>
    private static string IdentifyMarket(string symbol)
    {
        if (string.IsNullOrWhiteSpace(symbol))
            return "UNKNOWN";

        // A-share identification: ends with .SH or .SZ
        // Examples: 600000.SH (Shanghai), 000001.SZ (Shenzhen)
        if (symbol.EndsWith(".SH", StringComparison.OrdinalIgnoreCase) ||
            symbol.EndsWith(".SZ", StringComparison.OrdinalIgnoreCase))
        {
            return "CN_EQUITY";
        }

        // Extensible for US stocks, HK stocks, etc.
        // US stocks: no suffix or specific format
        // HK stocks: .HK or specific numeric format

        return "UNKNOWN";
    }
}

/// <summary>
/// No-restriction rule (default implementation for unsupported markets)
/// </summary>
internal class NoRestrictionRules : IMarketRule
{
    public string MarketType => "UNKNOWN";

    public Task<MarketRuleResult> ValidateAsync(Order order, Position? currentPosition, DateOnly tradeDate)
    {
        return Task.FromResult(MarketRuleResult.Pass());
    }
}
