using Execution.Service.Models;
using ExecutionService.Core.Services;
using Microsoft.Extensions.Options;

namespace ExecutionService.Core.Adapters;

/// <summary>
/// Execution adapter factory
/// Create corresponding ExecutionAdapter based on configuration
/// </summary>
public static class ExecutionAdapterFactory
{
    public static IExecutionAdapter CreateAdapter(
        IOptions<ExecutionSettings> config,
        IOptions<GMSettings> gmSettings,
        IPnLCalculator pnlCalculator,
        IRiskManager riskManager,
        IAccountManager accountManager,
        IServiceProvider serviceProvider,
        ILoggerFactory loggerFactory)
    {
        var mode = config.Value.Mode.ToUpperInvariant();

        var logger = loggerFactory.CreateLogger(nameof(ExecutionAdapterFactory));
        logger.LogInformation("Creating ExecutionAdapter: {Mode}", mode);

        return mode switch
        {
            "SIMULATION" => new SimExecutionAdapter(
                pnlCalculator,
                riskManager,
                accountManager,
                config,
                loggerFactory.CreateLogger<SimExecutionAdapter>()),
            "PAPER_BROKER" => new PaperExecutionAdapter(
                loggerFactory.CreateLogger<PaperExecutionAdapter>(),
                gmSettings),
            "LIVE_BROKER" => new LiveExecutionAdapter(
                loggerFactory.CreateLogger<LiveExecutionAdapter>()),
            _ => throw new InvalidOperationException($"Unsupported execution mode: {mode}")
        };
    }
}

/// <summary>
/// Execution mode configuration
/// </summary>
public class ExecutionSettings
{
    public const string SectionName = "ExecutionSettings";

    /// <summary>
    /// Execution mode
    /// SIMULATION - Simulated execution (backtesting/simulation)
    /// PAPER_BROKER - Paper trading (using simulated account)
    /// LIVE_BROKER - Live trading (real account)
    /// </summary>
    public string Mode { get; set; } = "SIMULATION";

    // ===== Sim partial fill configuration (added in P1.1) =====

    /// <summary>Enable partial fill simulation (large orders with low liquidity will be split into multiple fills)</summary>
    public bool SimEnablePartialFill { get; set; } = true;

    /// <summary>Maximum number of fill splits per order</summary>
    public int SimMaxPartialFills { get; set; } = 5;

    /// <summary>Large order threshold ratio to average daily volume (splitting starts above this ratio)</summary>
    public double SimLargeOrderVolumeRatio { get; set; } = 0.001; // 0.1%

    /// <summary>Placeholder "average daily volume" for estimating market depth (used when MarketData does not provide ADV)</summary>
    public double SimDefaultAvgDailyVolume { get; set; } = 1_000_000;
}
