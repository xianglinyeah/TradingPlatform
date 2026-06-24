using ExecutionService.Core.MarketRules;
using ExecutionService.Models;

namespace ExecutionService.Core.Services;

/// <summary>
/// Market rule validator interface
/// Responsible for validating that orders comply with exchange-enforced market rules.
/// </summary>
public interface IMarketRuleValidator
{
    /// <summary>
    /// Validate whether the order complies with market rules
    /// </summary>
    /// <param name="order">The order to validate</param>
    /// <param name="tradeDate">Trade date (used for T+1 settlement and other time-related rules)</param>
    /// <returns>Validation result</returns>
    Task<MarketRuleResult> ValidateOrderAsync(Order order, DateOnly tradeDate);
}
