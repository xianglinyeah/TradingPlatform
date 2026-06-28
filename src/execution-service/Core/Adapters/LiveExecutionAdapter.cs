using ExecutionService.Models;
using ExecutionService.Core.Services;

namespace ExecutionService.Core.Adapters;

/// <summary>
/// Live execution adapter — placeholder for direct-broker-API integration.
///
/// **NOT IMPLEMENTED.** All operations throw <see cref="NotImplementedException"/>.
/// This is intentional: a stub that silently simulated fills (the previous
/// behavior) would let a misconfigured <c>Mode: LIVE_BROKER</c> deployment
/// appear to trade successfully while no real orders ever reached the broker.
/// Real live trading currently routes through <c>PaperExecutionAdapter</c>
/// → execution-adapter-gm → GM SDK; this class exists only so the factory's
/// switch can name a third mode without recompiling later.
/// </summary>
public class LiveExecutionAdapter : ExecutionAdapterBase
{
    private readonly ILogger<LiveExecutionAdapter> _logger;

    public LiveExecutionAdapter(ILogger<LiveExecutionAdapter> logger)
    {
        _logger = logger;
        _logger.LogError(
            "[LIVE_ADAPTER] LiveExecutionAdapter instantiated — this class is NOT implemented. " +
            "Real live trading must route through PaperExecutionAdapter → execution-adapter-gm. " +
            "If you see this in production, Mode is misconfigured to LIVE_BROKER.");
    }

    private static Exception NotSupported() => new NotSupportedException(
        "LiveExecutionAdapter is not implemented. Use SIMULATION or PAPER_BROKER mode, " +
        "or route live traffic through execution-adapter-gm.");

    public override Task<ExecutionResult> ExecuteOrderAsync(Order order, MarketData marketData)
        => throw NotSupported();

    public override Task<RiskCheckResult> CheckOrderRiskAsync(Order order)
        => throw NotSupported();

    public override Task<bool> CancelOrderAsync(string orderId, string sessionId)
        => throw NotSupported();

    public override string GetAdapterType() => "LIVE_BROKER (NOT IMPLEMENTED)";
}
