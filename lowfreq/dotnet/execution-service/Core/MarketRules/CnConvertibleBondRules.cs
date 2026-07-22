using ExecutionService.Models;

namespace ExecutionService.Core.MarketRules;

/// <summary>
/// Convertible bond (可转债) market rules.
///
/// Convertible bonds are T+0 — same-day buy then sell is permitted — and have
/// no naked-short restriction in the retail sense (the simulator's risk
/// manager enforces its own position limits separately). The exchange does
/// enforce price-limit bands and a 20% threshold circuit-breaker, but those
/// are modeled by <c>PriceLimitChecker</c>, not by <c>IMarketRule</c>.
/// </summary>
public class CnConvertibleBondRules : IMarketRule
{
    public string MarketType => "CN_CONVERTIBLE_BOND";

    public Task<MarketRuleResult> ValidateAsync(Order order, Position? currentPosition, DateOnly tradeDate)
    {
        // T+0: no settlement restriction. No position checks — convertible
        // bonds can be day-traded and shorting rules are enforced elsewhere.
        return Task.FromResult(MarketRuleResult.Pass());
    }
}
