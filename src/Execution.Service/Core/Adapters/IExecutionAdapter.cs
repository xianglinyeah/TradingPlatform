using ExecutionService.Models;
using ExecutionService.Core.Services;

namespace ExecutionService.Core.Adapters;

/// <summary>
/// Order execution adapter interface
/// Define unified interface for different execution methods
/// </summary>
public interface IExecutionAdapter
{
    /// <summary>
    /// Execute order (P0.3: returns ExecutionResult containing terminal order state + fill details)
    /// </summary>
    Task<ExecutionResult> ExecuteOrderAsync(Order order, MarketData marketData);

    /// <summary>
    /// Cancel order
    /// </summary>
    Task<bool> CancelOrderAsync(string orderId, string sessionId);

    /// <summary>
    /// Validate order
    /// </summary>
    Task<bool> ValidateOrderAsync(Order order);

    /// <summary>
    /// Risk check
    /// </summary>
    Task<RiskCheckResult> CheckOrderRiskAsync(Order order);

    /// <summary>
    /// Get adapter type (for logging/audit)
    /// </summary>
    string GetAdapterType();
}
