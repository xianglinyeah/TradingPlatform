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
        return Task.FromResult(trade.Commission); // Simplified version, should actually be calculated in Position
    }

    public PerformanceMetrics CalculatePerformanceMetrics(List<Trade> trades)
    {
        if (!trades.Any())
        {
            return new PerformanceMetrics(0, 0, 0, 0, 0);
        }

        var totalPnL = trades.Sum(t => t.Price * t.Quantity);
        var totalTrades = trades.Count;

        // Simplified performance metrics calculation
        var winningTrades = trades.Count(t => t.Side == "sell" && t.Price > 0); // Simplified
        var winRate = totalTrades > 0 ? (double)winningTrades / totalTrades : 0.0;

        return new PerformanceMetrics(
            totalPnL,
            0.0, // SharpeRatio requires more complex calculation
            0.0, // MaxDrawdown requires historical data
            winRate,
            totalTrades
        );
    }
}