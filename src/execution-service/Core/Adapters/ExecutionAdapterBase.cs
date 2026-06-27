using ExecutionService.Models;

namespace ExecutionService.Core.Adapters;

/// <summary>
/// Base class for execution adapters providing shared validation logic.
/// Concrete adapters (Sim/Paper/Live) override ExecuteOrderAsync and other
/// methods that differ in behaviour.
/// </summary>
public abstract class ExecutionAdapterBase : IExecutionAdapter
{
    public abstract Task<ExecutionResult> ExecuteOrderAsync(Order order, MarketData marketData);

    /// <summary>
    /// Basic structural validation shared by all adapters:
    /// - Quantity must be positive
    /// - Symbol must not be empty
    /// </summary>
    public virtual Task<bool> ValidateOrderAsync(Order order)
    {
        if (order.Quantity <= 0)
        {
            return Task.FromResult(false);
        }

        if (string.IsNullOrEmpty(order.Symbol))
        {
            return Task.FromResult(false);
        }

        return Task.FromResult(true);
    }

    public abstract Task<RiskCheckResult> CheckOrderRiskAsync(Order order);

    public abstract Task<bool> CancelOrderAsync(string orderId, string sessionId);

    public abstract string GetAdapterType();
}
