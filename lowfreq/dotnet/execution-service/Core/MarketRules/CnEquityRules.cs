using ExecutionService.Models;
using ExecutionService.Data.IRepositories;

namespace ExecutionService.Core.MarketRules;

/// <summary>
/// A-share market rules implementation
/// Includes T+1 settlement rule and exchange mandatory rules such as no naked short selling
/// </summary>
public class CnEquityRules : IMarketRule
{
    public string MarketType => "CN_EQUITY";
    private readonly ITradeRepository _tradeRepo;

    public CnEquityRules(ITradeRepository tradeRepo)
    {
        _tradeRepo = tradeRepo;
    }

    /// <summary>
    /// Validate order against A-share market rules
    /// </summary>
    public async Task<MarketRuleResult> ValidateAsync(Order order, Position? currentPosition, DateOnly tradeDate)
    {
        // Check all rules in order
        var checks = new List<MarketRuleResult>
        {
            CheckNoShort(order, currentPosition),
            await CheckT1(order, currentPosition, tradeDate)
        };

        // Return the first failure, or Pass if none failed
        var failedCheck = checks.FirstOrDefault(r => !r.Passed);
        return failedCheck ?? MarketRuleResult.Pass();
    }

    /// <summary>
    /// T+1 settlement rule check: stocks bought today cannot be sold today
    /// </summary>
    private async Task<MarketRuleResult> CheckT1(Order order, Position? currentPosition, DateOnly tradeDate)
    {
        // Only check sell orders
        if (order.Side != OrderSide.Sell)
            return MarketRuleResult.Pass();

        // Query today's bought quantity
        var todayBoughtQty = await _tradeRepo.GetTodayBoughtQuantityAsync(
            order.SessionId, order.Symbol, tradeDate);

        var totalQty = currentPosition?.Quantity ?? 0;
        var sellableQty = totalQty - todayBoughtQty;

        if (order.Quantity > sellableQty)
        {
            return MarketRuleResult.Fail(
                $"T+1 restriction: can sell {sellableQty} shares ({todayBoughtQty} shares bought today are not sellable), requested to sell {order.Quantity} shares",
                "T+1 settlement rule");
        }

        return MarketRuleResult.Pass();
    }

    /// <summary>
    /// No naked short selling rule check: sell quantity cannot exceed position quantity
    /// </summary>
    private MarketRuleResult CheckNoShort(Order order, Position? currentPosition)
    {
        // Only check sell orders
        if (order.Side != OrderSide.Sell)
            return MarketRuleResult.Pass();

        var totalQty = currentPosition?.Quantity ?? 0;

        if (order.Quantity > totalQty)
        {
            return MarketRuleResult.Fail(
                $"Naked short selling forbidden: position {totalQty} shares, requested to sell {order.Quantity} shares",
                "No naked short selling");
        }

        return MarketRuleResult.Pass();
    }
}
