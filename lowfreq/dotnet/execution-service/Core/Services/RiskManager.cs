using ExecutionService.Models;
using ExecutionService.Core.Services;
using ExecutionService.Core.Utils;

namespace ExecutionService.Core.Services;

public class RiskManager : IRiskManager
{
    private readonly IAccountManager _accountManager;
    private readonly ILogger<RiskManager> _logger;
    // Toggle via env var RISK_CHECK_ENABLED="true" to enforce risk checks.
    // Defaults to "false" (skip) until account fund sync is implemented,
    // but now it's an explicit opt-out rather than always-off.
    private static readonly bool RiskCheckEnabled =
        string.Equals(Environment.GetEnvironmentVariable("RISK_CHECK_ENABLED"), "true", StringComparison.OrdinalIgnoreCase);

    public RiskManager(IAccountManager accountManager, ILogger<RiskManager> logger)
    {
        _accountManager = accountManager;
        _logger = logger;
        if (!RiskCheckEnabled)
        {
            _logger.LogWarning("Risk check is DISABLED (set RISK_CHECK_ENABLED=true to enforce). All orders will bypass risk validation.");
        }
    }

    public async Task<RiskCheckResult> CheckOrderRiskAsync(Order order)
    {
        try
        {
            if (!RiskCheckEnabled)
            {
                return new RiskCheckResult(true);
            }

            // Sanity guards (always run even when detailed checks are off).
            if (order.Quantity <= 0)
            {
                return new RiskCheckResult(false, "Order quantity must be positive");
            }
            if (string.IsNullOrEmpty(order.Symbol))
            {
                return new RiskCheckResult(false, "Order symbol is required");
            }
            if (order.Quantity * order.Price > RiskConstants.MAX_POSITION_VALUE)
            {
                return new RiskCheckResult(false, $"Order value exceeds max single position value {RiskConstants.MAX_POSITION_VALUE}");
            }

            // Per-account fund check (delegated to AccountManager).
            // TODO: enable once account fund synchronisation is wired up.
            return new RiskCheckResult(true);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Risk check failed");
            return new RiskCheckResult(false, ex.Message);
        }
    }

    public Task<bool> CheckPositionRiskAsync(Position position)
    {
        // Check single position risk
        var positionValue = position.CalculateMarketValue();
        return Task.FromResult(positionValue < RiskConstants.MAX_POSITION_VALUE);
    }

    public bool WithinRiskLimits(Account account)
    {
        // Check overall risk limits
        return account.TotalPnL > -account.InitialCapital * RiskConstants.MAX_LOSS_PERCENTAGE;
    }

    public async Task MonitorPositionsAsync(IEnumerable<Position> positions)
    {
        // Monitor all position risks
        foreach (var position in positions)
        {
            var risk = await CheckPositionRiskAsync(position);
            if (!risk)
            {
                _logger.LogWarning("Position risk exceeds limit: {Symbol} MarketValue{MarketValue}", position.Symbol, position.MarketValue);
            }
        }
    }
}