using ExecutionService.Data.IRepositories;
using ExecutionService.Models;

namespace ExecutionService.Core.MarketRules;

/// <summary>
/// A-share ETF market rules.
///
/// Most domestic A-share ETFs settle T+1. Cross-border ETFs (QDII) and a
/// handful of bond ETFs are T+0; the sec_master pipeline does not currently
/// distinguish them, so the conservative T+1 default is applied uniformly.
/// When sec_master grows a T+0 flag for cross-border ETFs, branch here on
/// that attribute.
/// </summary>
public class CnETFRules : IMarketRule
{
    public string MarketType => "CN_ETF";
    private readonly ITradeRepository _tradeRepo;

    public CnETFRules(ITradeRepository tradeRepo)
    {
        _tradeRepo = tradeRepo;
    }

    public async Task<MarketRuleResult> ValidateAsync(Order order, Position? currentPosition, DateOnly tradeDate)
    {
        var checks = new List<MarketRuleResult>
        {
            CheckNoShort(order, currentPosition),
            await CheckT1(order, currentPosition, tradeDate)
        };
        var failedCheck = checks.FirstOrDefault(r => !r.Passed);
        return failedCheck ?? MarketRuleResult.Pass();
    }

    private async Task<MarketRuleResult> CheckT1(Order order, Position? currentPosition, DateOnly tradeDate)
    {
        if (order.Side != OrderSide.Sell)
            return MarketRuleResult.Pass();

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

    private static MarketRuleResult CheckNoShort(Order order, Position? currentPosition)
    {
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
