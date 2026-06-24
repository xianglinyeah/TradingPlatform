using Confluent.Kafka;

namespace MarketData.Replay.Utils;

/// <summary>
/// Kafka configuration constant definitions
/// Unified management of all Kafka-related hard-coded values
/// </summary>
public static class KafkaConstants
{
    // ===== Producer Configuration =====

    /// <summary>Linger time: 10 milliseconds</summary>
    public const int LINGER_MS = 10;

    /// <summary>Batch size: 100000 bytes</summary>
    public const int BATCH_SIZE = 100000;

    /// <summary>Maximum message send retry count: 2 times</summary>
    public const int MESSAGE_SEND_MAX_RETRIES = 2;

    /// <summary>Request timeout: 3000 milliseconds (3 seconds)</summary>
    public const int REQUEST_TIMEOUT_MS = 3000;

    /// <summary>Socket timeout: 1000 milliseconds (1 second)</summary>
    public const int SOCKET_TIMEOUT_MS = 1000;

    // ===== Flush and Timeout Configuration =====

    /// <summary>Producer Flush timeout: 5 seconds</summary>
    public const int PRODUCER_FLUSH_TIMEOUT_SECONDS = 5;

    /// <summary>Dispose Flush timeout: 10 seconds</summary>
    public const int DISPOSE_FLUSH_TIMEOUT_SECONDS = 10;

    // ===== ACK and Compression Configuration =====

    /// <summary>ACK configuration: Only wait for Leader confirmation</summary>
    public const Acks ACKS_CONFIG = Acks.Leader;

    // ===== Idempotency Configuration =====

    /// <summary>Enable idempotency: Disabled (to avoid PID acquisition issues)</summary>
    public const bool ENABLE_IDEMPOTENCE = false;
}
