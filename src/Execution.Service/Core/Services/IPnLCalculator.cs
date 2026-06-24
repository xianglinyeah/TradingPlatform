using ExecutionService.Models;

namespace ExecutionService.Core.Services;

public interface IPnLCalculator
{
    Task<Dictionary<string, decimal>> CalculateUnrealizedPnLAsync(
        IEnumerable<Position> positions,
        Dictionary<string, decimal> currentPrices);

    Task<decimal> CalculateRealizedPnLAsync(Position position, Trade trade);

    PerformanceMetrics CalculatePerformanceMetrics(List<Trade> trades);
}

public record PerformanceMetrics(
    decimal TotalReturn,
    double SharpeRatio,
    double MaxDrawdown,
    double WinRate,
    int TotalTrades
);