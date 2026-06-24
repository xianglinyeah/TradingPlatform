using ExecutionService.Models;

namespace ExecutionService.Core.MarketRules;

/// <summary>
/// Market rule interface
/// Defines trading rules for different markets (e.g. T+1 settlement, no naked short selling).
/// These rules are enforced by the exchange; they cannot be configured or disabled.
/// </summary>
public interface IMarketRule
{
    /// <summary>
    /// Market type identifier
    /// </summary>
    string MarketType { get; }

    /// <summary>
    /// Validate whether the order complies with market rules
    /// </summary>
    /// <param name="order">The order to validate</param>
    /// <param name="currentPosition">Current position (may be null)</param>
    /// <param name="tradeDate">Trade date (used for T+1 settlement and other rule checks)</param>
    /// <returns>Validation result</returns>
    Task<MarketRuleResult> ValidateAsync(Order order, Position? currentPosition, DateOnly tradeDate);
}
