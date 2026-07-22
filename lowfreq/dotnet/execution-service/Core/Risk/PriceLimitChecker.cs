using ExecutionService.Data.ClickHouse;
using ExecutionService.Data.IRepositories;
using ExecutionService.Models;
using Microsoft.Extensions.Logging;

namespace ExecutionService.Core.Risk;

/// <summary>
/// Outcome of a price-limit check.
/// </summary>
public sealed class LimitCheckResult
{
    public bool Allowed { get; private init; }
    public string? Reason { get; private init; }
    public decimal? LimitUp { get; private init; }
    public decimal? LimitDown { get; private init; }

    public static LimitCheckResult Allow(decimal limitUp, decimal limitDown) => new()
    {
        Allowed = true, LimitUp = limitUp, LimitDown = limitDown
    };

    /// <summary>Skip the check entirely (no data to evaluate against).</summary>
    public static LimitCheckResult Skip(string reason) => new()
    {
        Allowed = true, Reason = reason
    };

    public static LimitCheckResult Reject(string reason, decimal? limitUp = null, decimal? limitDown = null) => new()
    {
        Allowed = false, Reason = reason, LimitUp = limitUp, LimitDown = limitDown
    };
}

/// <summary>
/// A-share daily price-limit (涨跌停) check for the SimExecutionAdapter.
///
/// Real exchanges reject orders that would cross the daily price-limit band;
/// the simulator historically filled them anyway, producing optimistic PnL.
/// This checker mirrors the exchange behavior using (a) the prior-day close
/// from ClickHouse <c>kline_daily</c> and (b) board + ST classification from
/// <c>market_ref.sec_master</c>.
///
/// Limit bands:
///   main board (主板)    ±10%
///   ChiNext (创业板)     ±20%
///   STAR (科创板)        ±20%
///   BSE (北交所)         ±30%
///   ST / *ST             ±5%
///
/// IPO-first-day handling is intentionally out of scope — see the plan's
/// "Out of scope" section.
/// </summary>
public sealed class PriceLimitChecker
{
    private readonly ISecMasterRepository _secMaster;
    private readonly IClickHouseClient _clickhouse;
    private readonly ILogger<PriceLimitChecker> _logger;

    public PriceLimitChecker(
        ISecMasterRepository secMaster,
        IClickHouseClient clickhouse,
        ILogger<PriceLimitChecker> logger)
    {
        _secMaster = secMaster;
        _clickhouse = clickhouse;
        _logger = logger;
    }

    public async Task<LimitCheckResult> CheckAsync(Order order, MarketData marketData)
    {
        var entry = await _secMaster.GetBySymbolAsync(order.Symbol);
        if (entry == null)
        {
            // sec_master_sync has not run yet, or symbol is genuinely unknown.
            // Fail open — the suffix-based rule still applies T+1 etc.
            return LimitCheckResult.Skip("No sec_master entry for symbol");
        }

        var prevClose = await _clickhouse.GetPriorCloseAsync(order.Symbol, order.CreatedAt);
        if (prevClose == null || prevClose.Value <= 0)
        {
            // Brand-new listing, suspended, or CH unreachable — do not reject
            // based on missing data.
            return LimitCheckResult.Skip("No prior close available");
        }

        decimal pct = entry.IsSt ? 0.05m : entry.Board switch
        {
            "chinext" => 0.20m,
            "star"    => 0.20m,
            "beijing" => 0.30m,
            _         => 0.10m,   // main board and unknowns: conservative 10%
        };

        decimal limitUp = prevClose.Value * (1 + pct);
        decimal limitDown = prevClose.Value * (1 - pct);

        // Conservative rejection model: if the execution reference price is
        // at or beyond the band, the order would not have been matched on
        // the real exchange. Buy at/above limit-up = no seller; sell at/below
        // limit-down = no buyer.
        bool blocked = order.Side == OrderSide.Buy
            ? marketData.Close >= limitUp
            : marketData.Close <= limitDown;

        if (blocked)
        {
            var dir = order.Side == OrderSide.Buy ? "limit-up" : "limit-down";
            var reason = $"At {dir} ({pct:P1} band): close={marketData.Close:F2}, " +
                         $"prevClose={prevClose.Value:F2}, limitUp={limitUp:F2}, limitDown={limitDown:F2}, " +
                         $"board={entry.Board ?? "?"}, isSt={entry.IsSt}";
            _logger.LogInformation("Price-limit reject: {Symbol} {Side} {Reason}",
                order.Symbol, order.Side, reason);
            return LimitCheckResult.Reject(reason, limitUp, limitDown);
        }

        return LimitCheckResult.Allow(limitUp, limitDown);
    }
}
