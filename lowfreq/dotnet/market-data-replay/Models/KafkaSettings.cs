namespace MarketData.Replay.Models;

/// <summary>
/// Unified Kafka configuration shared by all services. Each service's
/// configuration file must match this structure.
/// </summary>
public class KafkaSettings
{
    /// <summary>
    /// Kafka server addresses (comma-separated for multiple addresses)
    /// Example: "localhost:9092" or "kafka.infrastructure:9092"
    /// </summary>
    public string BootstrapServers { get; set; } = "localhost:9092";

    /// <summary>
    /// Market data topic
    /// </summary>
    public string MarketDataTopic { get; set; } = "market.data";

    /// <summary>
    /// Control topic (for replay control signals)
    /// </summary>
    public string ControlTopic { get; set; } = "replay.control";

    /// <summary>
    /// Consumer group ID
    /// </summary>
    public string? GroupId { get; set; }

    /// <summary>
    /// Enable auto commit
    /// </summary>
    public bool EnableAutoCommit { get; set; } = true;

    /// <summary>
    /// Session timeout (milliseconds)
    /// </summary>
    public int SessionTimeoutMs { get; set; } = 30000;

    /// <summary>
    /// Heartbeat interval (milliseconds)
    /// </summary>
    public int HeartbeatIntervalMs { get; set; } = 10000;
}
