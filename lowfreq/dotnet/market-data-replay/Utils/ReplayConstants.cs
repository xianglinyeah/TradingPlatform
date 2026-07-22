namespace MarketData.Replay.Utils;

/// <summary>
/// Replay service constants definition
/// Unified management of all replay-related hardcoded values
/// </summary>
public static class ReplayConstants
{
    // ===== Status check and update frequency =====

    /// <summary>Status check frequency: check every 100 event groups</summary>
    public const int STATUS_CHECK_INTERVAL = 100;

    /// <summary>Pause loop check interval: 100 milliseconds</summary>
    public const int PAUSE_LOOP_CHECK_INTERVAL_MS = 100;

    /// <summary>Log output frequency: output every 1000 event groups</summary>
    public const int LOG_OUTPUT_INTERVAL = 1000;

    /// <summary>Database update frequency: update every 1000 event groups</summary>
    public const int DATABASE_UPDATE_INTERVAL = 1000;

    // ===== Speed and time control =====

    /// <summary>Low speed mode threshold: <= 1.0x speed</summary>
    public const double LOW_SPEED_THRESHOLD = 1.0;

    /// <summary>Minimum delay time: 1 millisecond</summary>
    public const int MIN_DELAY_MS = 1;

    /// <summary>Maximum delay time: 60000 milliseconds (1 minute)</summary>
    public const int MAX_DELAY_MS = 60000;

    // ===== Kafka and messages =====

    /// <summary>Market data topic name</summary>
    public const string MARKET_DATA_TOPIC = "market.data";

    /// <summary>RESET message type (emitted once at session start)</summary>
    public const string MESSAGE_TYPE_RESET = "RESET";

    /// <summary>DAY_BOUNDARY message type (emitted before the first bar of each
    /// new trading day so consumers can run per-day lifecycle hooks such as
    /// clearing daily state without waiting for the next RESET).</summary>
    public const string MESSAGE_TYPE_DAY_BOUNDARY = "DAY_BOUNDARY";

    // ===== Data source identifiers =====

    /// <summary>Simulation data source identifier</summary>
    public const string SOURCE_SIMULATION = "Simulation";

    /// <summary>GM real-time data source identifier</summary>
    public const string SOURCE_GM = "GM";
}

/// <summary>
/// API error message constants
/// </summary>
public static class ReplayErrorMessages
{
    /// <summary>Session not found error</summary>
    public const string SESSION_NOT_FOUND = "Session not found";

    /// <summary>Session not found or not running error</summary>
    public const string SESSION_NOT_RUNNING = "Session not found or not running";

    /// <summary>Session not found or not paused error</summary>
    public const string SESSION_NOT_PAUSED = "Session not found or not paused";

    /// <summary>Replay stopped message</summary>
    public const string REPLAY_STOPPED = "Replay stopped";

    /// <summary>Replay paused message</summary>
    public const string REPLAY_PAUSED = "Replay paused";

    /// <summary>Replay resumed message</summary>
    public const string REPLAY_RESUMED = "Replay resumed";

    /// <summary>Replay started message</summary>
    public const string REPLAY_STARTED = "Replay started";

    /// <summary>Replay start failed error</summary>
    public const string REPLAY_START_FAILED = "Failed to start replay";

    /// <summary>Get status failed error</summary>
    public const string GET_STATUS_FAILED = "Failed to get status";

    /// <summary>Stop replay failed error</summary>
    public const string STOP_FAILED = "Failed to stop replay";

    /// <summary>Pause replay failed error</summary>
    public const string PAUSE_FAILED = "Failed to pause replay";

    /// <summary>Resume replay failed error</summary>
    public const string RESUME_FAILED = "Failed to resume replay";
}
