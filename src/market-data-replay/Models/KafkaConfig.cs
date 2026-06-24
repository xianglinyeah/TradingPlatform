namespace MarketData.Replay.Models;

/// <summary>
/// Kafka configuration (backward compatible alias)
/// It is recommended to use KafkaSettings for more complete configuration options
/// </summary>
public class KafkaConfig : KafkaSettings
{
    // Maintain backward compatibility, inherit all properties from KafkaSettings
}
