namespace ExecutionService.Core.Utils;

/// <summary>
/// Trading constants definition
/// Unified management of trading-related constants to avoid magic numbers
/// </summary>
public static class TradingConstants
{
    /// <summary>A-share commission rate: 0.025% (2.5 per 10,000)</summary>
    public const decimal COMMISSION_RATE = 0.00025m;

    /// <summary>Minimum commission: 5 yuan</summary>
    public const decimal MIN_COMMISSION = 5m;

    /// <summary>Order fund check buffer: 0.1%</summary>
    public const decimal CASH_BUFFER_PERCENTAGE = 0.001m;

    // ===== Slippage constants =====

    /// <summary>Market order base slippage: 0.03%</summary>
    public const decimal MARKET_ORDER_SLIPPAGE = 0.0003m;

    /// <summary>Limit order base slippage: 0.01%</summary>
    public const decimal LIMIT_ORDER_SLIPPAGE = 0.0001m;

    /// <summary>Large order slippage factor: for every 1% volume, add 0.01% slippage</summary>
    public const decimal LARGE_ORDER_SLIPPAGE_FACTOR = 0.01m;

    /// <summary>Maximum extra slippage: 0.2%</summary>
    public const decimal MAX_EXTRA_SLIPPAGE = 0.002m;

    /// <summary>Large order threshold: Exceeds 0.1% of average daily volume</summary>
    public const decimal LARGE_ORDER_THRESHOLD = 0.001m;

    /// <summary>Limit order reasonable price range: ±1%</summary>
    public const decimal LIMIT_ORDER_PRICE_TOLERANCE = 0.01m;

    // ===== Partial fill constants =====

    /// <summary>Default average daily volume assumption when no volume data is available.</summary>
    public const decimal DEFAULT_AVG_DAILY_VOLUME = 1000000m;

    /// <summary>Volume ratio threshold at which partial-fill splitting begins.</summary>
    public const decimal PARTIAL_FILL_RATIO_THRESHOLD_MIN = 0.001m;

    /// <summary>Volume ratio below which we split into 2 fills.</summary>
    public const decimal PARTIAL_FILL_RATIO_TWO_FILLS = 0.01m;

    /// <summary>Volume ratio below which we split into 3 fills.</summary>
    public const decimal PARTIAL_FILL_RATIO_THREE_FILLS = 0.05m;

    /// <summary>Volume ratio below which we split into 5 fills.</summary>
    public const decimal PARTIAL_FILL_RATIO_FIVE_FILLS = 0.1m;

    /// <summary>Price impact per 1% of daily volume (linear).</summary>
    public const decimal PARTIAL_FILL_PRICE_IMPACT_FACTOR = 0.05m;

    /// <summary>Cap on per-fill price impact (0.5%).</summary>
    public const decimal PARTIAL_FILL_MAX_PER_FILL_IMPACT = 0.005m;

    /// <summary>Weight of the final "tail" partial fill (minimum portion left after geometric decay).</summary>
    public const decimal PARTIAL_FILL_TAIL_WEIGHT_MIN = 0.1m;

    /// <summary>A-share minimum trade unit (board lot size).</summary>
    public const decimal ASHARE_MIN_TRADE_UNIT = 100m;

    /// <summary>Default bar period in seconds (1-minute bars).</summary>
    public const int DEFAULT_BAR_PERIOD_SECONDS = 60;
}

/// <summary>
/// Account constants definition
/// </summary>
public static class AccountConstants
{
    /// <summary>Default initial capital: 1 million</summary>
    public const decimal DEFAULT_INITIAL_CAPITAL = 1000000m;
}

/// <summary>
/// Risk control constants definition
/// </summary>
public static class RiskConstants
{
    /// <summary>Maximum value per position: 100,000</summary>
    public const decimal MAX_POSITION_VALUE = 100000m;

    /// <summary>Maximum percentage per position: 20%</summary>
    public const decimal MAX_POSITION_PERCENTAGE = 0.2m;

    /// <summary>Maximum loss percentage: 20%</summary>
    public const decimal MAX_LOSS_PERCENTAGE = 0.2m;
}
