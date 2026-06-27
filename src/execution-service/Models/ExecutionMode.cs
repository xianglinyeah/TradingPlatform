namespace ExecutionService.Models;

/// <summary>
/// Execution mode
/// Used to distinguish different trading execution methods, avoiding confusion between simulated PnL and live PnL
/// </summary>
public enum ExecutionMode
{
    /// <summary>
    /// Simulation execution (backtest/simulation trading)
    /// </summary>
    SIMULATION,

    /// <summary>
    /// Paper Trading (using demo account)
    /// </summary>
    PAPER_BROKER,

    /// <summary>
    /// Live trading (real account)
    /// </summary>
    LIVE_BROKER
}
