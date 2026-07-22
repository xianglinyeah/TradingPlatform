using ExecutionService.Data.IRepositories;
using ExecutionService.Models;
using Microsoft.Extensions.Logging;

namespace ExecutionService.Core.MarketRules;

/// <summary>
/// Market rule factory.
///
/// Resolves the correct <see cref="IMarketRule"/> for a symbol by consulting
/// the <c>market_ref.sec_master</c> reference table (populated by
/// data-ingestion's <c>sec_master_sync</c> mode). Falls back to a
/// suffix-based heuristic when the table has no entry, so the service still
/// functions during the boot window before the first sec_master_sync run.
/// </summary>
public static class MarketRuleFactory
{
    /// <summary>
    /// Resolve a rule via sec_master, falling back to the suffix heuristic.
    /// </summary>
    /// <param name="symbol">Stock symbol (TS format, e.g. 600000.SH)</param>
    /// <param name="tradeRepo">Trade repository (T+1 enforcement needs it).</param>
    /// <param name="secMaster">sec_master repository; null triggers suffix fallback.</param>
    /// <param name="logger">Optional logger for classification misses.</param>
    public static async Task<IMarketRule> GetRuleAsync(
        string symbol,
        ITradeRepository? tradeRepo = null,
        ISecMasterRepository? secMaster = null,
        ILogger? logger = null)
    {
        if (secMaster is not null)
        {
            try
            {
                var entry = await secMaster.GetBySymbolAsync(symbol);
                if (entry != null)
                {
                    return entry.SecType switch
                    {
                        "stock"            => new CnEquityRules(tradeRepo!),
                        "convertible_bond" => new CnConvertibleBondRules(),
                        "etf"              => new CnETFRules(tradeRepo!),
                        "reit"             => new NoRestrictionRules(),
                        _                  => new NoRestrictionRules(),
                    };
                }
                logger?.LogWarning(
                    "sec_master has no entry for {Symbol}; falling back to suffix classification",
                    symbol);
            }
            catch (Exception ex)
            {
                // Never let a classification failure abort order validation —
                // fall through to the conservative suffix-based rule.
                logger?.LogError(ex, "sec_master lookup failed for {Symbol}; falling back", symbol);
            }
        }

        return GetRuleSuffixFallback(symbol, tradeRepo);
    }

    /// <summary>
    /// Synchronous legacy entry point. Used by tests that do not mock
    /// <see cref="ISecMasterRepository"/>. Always takes the suffix fallback.
    /// Marked obsolete to discourage new call sites.
    /// </summary>
    [Obsolete("Prefer the async GetRuleAsync overload that consults sec_master.")]
    public static IMarketRule GetRule(string symbol, ITradeRepository? tradeRepo = null)
        => GetRuleSuffixFallback(symbol, tradeRepo);

    private static IMarketRule GetRuleSuffixFallback(string symbol, ITradeRepository? tradeRepo)
    {
        var marketType = IdentifyMarketBySuffix(symbol);
        return marketType switch
        {
            "CN_EQUITY" => new CnEquityRules(tradeRepo!),
            "US_EQUITY" => new NoRestrictionRules(),
            "HK_EQUITY" => new NoRestrictionRules(),
            _ => new NoRestrictionRules()
        };
    }

    /// <summary>
    /// Identify market type from the stock symbol suffix only. Conservative
    /// last-resort when sec_master is unavailable or empty.
    /// </summary>
    private static string IdentifyMarketBySuffix(string symbol)
    {
        if (string.IsNullOrWhiteSpace(symbol))
            return "UNKNOWN";

        if (symbol.EndsWith(".SH", StringComparison.OrdinalIgnoreCase) ||
            symbol.EndsWith(".SZ", StringComparison.OrdinalIgnoreCase))
        {
            return "CN_EQUITY";
        }

        return "UNKNOWN";
    }
}

/// <summary>
/// No-restriction rule (default implementation for unsupported markets).
/// </summary>
internal class NoRestrictionRules : IMarketRule
{
    public string MarketType => "UNKNOWN";

    public Task<MarketRuleResult> ValidateAsync(Order order, Position? currentPosition, DateOnly tradeDate)
    {
        return Task.FromResult(MarketRuleResult.Pass());
    }
}
