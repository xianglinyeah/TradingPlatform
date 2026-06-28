using ExecutionService.Models;
using ExecutionService.Core.Services;

namespace ExecutionService.Core.Services;

public class PnLCalculatorService : IPnLCalculator
{
    private readonly ILogger<PnLCalculatorService> _logger;

    public PnLCalculatorService(ILogger<PnLCalculatorService> logger)
    {
        _logger = logger;
    }

    public Task<Dictionary<string, decimal>> CalculateUnrealizedPnLAsync(
        IEnumerable<Position> positions,
        Dictionary<string, decimal> currentPrices)
    {
        var unrealizedPnL = new Dictionary<string, decimal>();

        foreach (var position in positions)
        {
            if (currentPrices.TryGetValue(position.Symbol, out var currentPrice))
            {
                var pnl = position.UpdateUnrealizedPnL(currentPrice);
                unrealizedPnL[position.Symbol] = pnl;
            }
        }

        return Task.FromResult(unrealizedPnL);
    }

    public Task<decimal> CalculateRealizedPnLAsync(Position position, Trade trade)
    {
        // NOT IMPLEMENTED. Realized PnL is computed inline by Position.Reduce
        // and persisted on Position.RealizedPnL — this method exists only to
        // satisfy IPnLCalculator and is not called by any code path or test.
        // Throwing rather than returning a wrong value (the previous behavior
        // returned just the commission, which is not PnL at all) so any future
        // caller sees an explicit failure instead of silently wrong data.
        throw new NotSupportedException(
            "CalculateRealizedPnLAsync is not implemented. Read Position.RealizedPnL instead.");
    }

    public PerformanceMetrics CalculatePerformanceMetrics(List<Trade> trades)
    {
        // NOT IMPLEMENTED. Sharpe ratio and max drawdown require a return
        // series over time, which is not tracked per-trade. Returning zeroes
        // silently (the previous behavior) would mislead any caller into
        // thinking the strategy had zero volatility / zero drawdown.
        throw new NotSupportedException(
            "CalculatePerformanceMetrics is not implemented. Sharpe / MaxDrawdown require a time-series of returns, not a trade list.");
    }
}