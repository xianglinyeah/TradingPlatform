namespace MarketData.Replay.Utils;

/// <summary>
/// Parquet data file constants definition
/// Unified management of all Parquet file related hardcoded values
/// </summary>
public static class ParquetConstants
{
    // ===== File path structure =====

    /// <summary>Minute data directory name</summary>
    public const string MINUTE_DATA_DIR = "minute";

    /// <summary>1-minute K-line data directory name</summary>
    public const string ONE_MIN_DIR = "1min";

    /// <summary>Parquet file extension</summary>
    public const string PARQUET_EXTENSION = "*.parquet";

    // ===== Parquet field names =====

    /// <summary>Trade time field name</summary>
    public const string FIELD_TRADE_TIME = "trade_time";

    /// <summary>Open price field name</summary>
    public const string FIELD_OPEN = "open";

    /// <summary>High price field name</summary>
    public const string FIELD_HIGH = "high";

    /// <summary>Low price field name</summary>
    public const string FIELD_LOW = "low";

    /// <summary>Close price field name</summary>
    public const string FIELD_CLOSE = "close";

    /// <summary>Volume field name</summary>
    public const string FIELD_VOLUME = "volume";

    /// <summary>Amount field name</summary>
    public const string FIELD_AMOUNT = "amount";

    // ===== File naming =====

    /// <summary>Parquet file naming separator</summary>
    public const string FILE_NAME_SEPARATOR = "_";

    /// <summary>File name suffix format (year)</summary>
    public const string FILE_YEAR_FORMAT = "{0}_{1}.parquet";

    // ===== Data processing =====

    /// <summary>Initial field index (not found)</summary>
    public const int INVALID_FIELD_INDEX = -1;

    /// <summary>Exchange code length</summary>
    public const int EXCHANGE_CODE_LENGTH = 2;

    /// <summary>Minimum symbol length</summary>
    public const int MIN_SYMBOL_LENGTH = 3;
}

/// <summary>
/// Exchange code constants
/// </summary>
public static class ExchangeCodes
{
    /// <summary>Shanghai Stock Exchange code</summary>
    public const string SHANGHAI = "SH";

    /// <summary>Shanghai Stock Exchange full code</summary>
    public const string SHANGHAI_FULL = "SHSE";

    /// <summary>Shenzhen Stock Exchange code</summary>
    public const string SHENZHEN = "SZ";

    /// <summary>Shenzhen Stock Exchange full code</summary>
    public const string SHENZHEN_FULL = "SZSE";
}
