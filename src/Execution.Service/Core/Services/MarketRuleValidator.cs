using ExecutionService.Core.MarketRules;
using ExecutionService.Data.IRepositories;
using ExecutionService.Models;
using Microsoft.Extensions.Logging;

namespace ExecutionService.Core.Services;

/// <summary>
/// Market rule validator implementation
/// Responsible for validating that orders comply with exchange-enforced market rules (e.g. T+1 settlement, no naked short selling).
/// These rules are hard constraints that can never be turned off or bypassed.
/// </summary>
public class MarketRuleValidator : IMarketRuleValidator
{
    private readonly IPositionRepository _positionRepo;
    private readonly ITradeRepository _tradeRepo;
    private readonly ILogger<MarketRuleValidator> _logger;

    public MarketRuleValidator(
        IPositionRepository positionRepo,
        ITradeRepository tradeRepo,
        ILogger<MarketRuleValidator> logger)
    {
        _positionRepo = positionRepo;
        _tradeRepo = tradeRepo;
        _logger = logger;
    }

    /// <summary>
    /// Validate whether the order complies with market rules
    /// </summary>
    public async Task<MarketRuleResult> ValidateOrderAsync(Order order, DateOnly tradeDate)
    {
        try
        {
            _logger.LogDebug(
                "Starting market rule validation: SessionId={SessionId}, Symbol={Symbol}, Side={Side}, Quantity={Quantity}, Date={Date}",
                order.SessionId, order.Symbol, order.Side, order.Quantity, tradeDate);

            // 1. Identify the market type and get the corresponding rule
            var rule = MarketRuleFactory.GetRule(order.Symbol, _tradeRepo);

            // 2. Get the current position
            var position = await _positionRepo.GetPositionAsync(order.SessionId, order.Symbol);

            // 3. Execute rule validation
            var result = await rule.ValidateAsync(order, position, tradeDate);

            if (result.Passed)
            {
                _logger.LogDebug("Market rule validation passed: Symbol={Symbol}", order.Symbol);
            }
            else
            {
                _logger.LogWarning(
                    "Market rule validation failed: Symbol={Symbol}, Rule={Rule}, Reason={Reason}",
                    order.Symbol, result.RuleName, result.Reason);
            }

            return result;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Market rule validation exception: Symbol={Symbol}", order.Symbol);
            return MarketRuleResult.Fail($"Rule validation exception: {ex.Message}", "System error");
        }
    }
}
