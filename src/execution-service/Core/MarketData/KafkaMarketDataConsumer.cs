using System.Text.Json;
using System.Text.Json.Serialization;
using Confluent.Kafka;
using ExecutionService.Models;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace ExecutionService.Core.MarketFeed;

/// <summary>
/// Settings for the market-data Kafka consumer. Bound from the "Kafka" section
/// of appsettings.json (override via Kafka__* environment variables in K8s).
/// </summary>
public sealed class KafkaConsumerSettings
{
    public const string SectionName = "Kafka";

    public string BootstrapServers { get; set; } = "kafka.infrastructure:9092";
    public string MarketDataTopic { get; set; } = "market.data";
    public string GroupId { get; set; } = "execution_service";

    /// <summary>
    /// Where to begin consuming when the group has no committed offset.
    /// Defaults to "earliest" so that, in replay/backtest mode, the cache is
    /// populated from the first bar the replay ever published and is ready by
    /// the time the strategy's gRPC order arrives. In live GM mode the topic
    /// is long-lived so this only affects the very first deployment.
    /// </summary>
    public string AutoOffsetReset { get; set; } = "earliest";
}

/// <summary>
/// Wire schema for messages on the <c>market.data</c> Kafka topic.
///
/// Matches <c>MarketDataEvent</c> emitted by market-data-replay and
/// market-data-gm. Property names are PascalCase to match the producer's
/// <c>System.Text.Json</c> default serialization. Source values are
/// <c>"Simulation"</c> or <c>"GM"</c>.
/// </summary>
internal sealed class MarketDataKafkaMessage
{
    [JsonPropertyName("Symbol")]
    public string Symbol { get; set; } = string.Empty;

    [JsonPropertyName("EventTime")]
    public DateTime EventTime { get; set; }

    [JsonPropertyName("Open")]
    public decimal Open { get; set; }

    [JsonPropertyName("High")]
    public decimal High { get; set; }

    [JsonPropertyName("Low")]
    public decimal Low { get; set; }

    [JsonPropertyName("Close")]
    public decimal Close { get; set; }

    [JsonPropertyName("Volume")]
    public decimal Volume { get; set; }

    [JsonPropertyName("Amount")]
    public decimal Amount { get; set; }

    [JsonPropertyName("SessionId")]
    public string SessionId { get; set; } = string.Empty;

    [JsonPropertyName("Source")]
    public string Source { get; set; } = string.Empty;
}

/// <summary>
/// Background Kafka consumer that subscribes to <c>market.data</c> and feeds
/// every new bar into a singleton <see cref="MarketDataCache"/>. Independent
/// consumer group (<c>execution_service</c>) so offsets are tracked
/// separately from <c>strategy_engine</c>.
/// </summary>
public sealed class KafkaMarketDataConsumer : BackgroundService
{
    private readonly MarketDataCache _cache;
    private readonly IOptions<KafkaConsumerSettings> _options;
    private readonly ILogger<KafkaMarketDataConsumer> _logger;
    private IConsumer<Ignore, string>? _consumer;

    // Source-generated or hand-rolled, both fine. Reusing the same options the
    // publisher uses keeps PropertyNameCaseInsensitive from accidentally picking
    // up camelCase fields emitted by other producers on the same topic.
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    public KafkaMarketDataConsumer(
        MarketDataCache cache,
        IOptions<KafkaConsumerSettings> options,
        ILogger<KafkaMarketDataConsumer> logger)
    {
        _cache = cache;
        _options = options;
        _logger = logger;
    }

    protected override Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var cfg = _options.Value;

        // Map "earliest"/"latest" strings to the Confluent enum.
        var autoReset = cfg.AutoOffsetReset?.ToLowerInvariant() switch
        {
            "latest" or "end" => AutoOffsetReset.Latest,
            _ => AutoOffsetReset.Earliest,
        };

        var consumerConfig = new ConsumerConfig
        {
            BootstrapServers = cfg.BootstrapServers,
            GroupId = cfg.GroupId,
            AutoOffsetReset = autoReset,
            EnableAutoCommit = true,
            // Refresh topic metadata periodically so the consumer tracks
            // partition leadership changes promptly.
            TopicMetadataRefreshIntervalMs = 30000,
        };

        _consumer = new ConsumerBuilder<Ignore, string>(consumerConfig)
            .SetErrorHandler((_, e) =>
                _logger.LogError("Kafka consumer error: Code={Code} Reason={Reason} Fatal={Fatal}",
                    e.Code, e.Reason, e.IsFatal))
            .SetPartitionsAssignedHandler((_, partitions) =>
                _logger.LogInformation("Kafka consumer assigned partitions: {Partitions}",
                    string.Join(", ", partitions)))
            .SetPartitionsRevokedHandler((_, partitions) =>
                _logger.LogInformation("Kafka consumer revoked partitions: {Partitions}",
                    string.Join(", ", partitions)))
            .Build();

        _consumer.Subscribe(cfg.MarketDataTopic);
        _logger.LogInformation(
            "Kafka market-data consumer started: bootstrap={Bootstrap}, topic={Topic}, group={Group}, autoOffsetReset={Reset}",
            cfg.BootstrapServers, cfg.MarketDataTopic, cfg.GroupId, autoReset);

        // Run on a background thread so the host startup pipeline is not blocked.
        _ = Task.Run(() => ConsumeLoop(stoppingToken), stoppingToken);
        return Task.CompletedTask;
    }

    private async Task ConsumeLoop(CancellationToken stoppingToken)
    {
        if (_consumer == null)
            return;

        try
        {
            while (!stoppingToken.IsCancellationRequested)
            {
                ConsumeResult<Ignore, string> result;
                try
                {
                    result = _consumer.Consume(stoppingToken);
                }
                catch (ConsumeException ex)
                {
                    _logger.LogWarning("Kafka Consume error: {Reason}", ex.Error.Reason);
                    continue;
                }
                catch (OperationCanceledException)
                {
                    break;
                }

                if (string.IsNullOrEmpty(result.Message.Value))
                    continue;

                MarketDataKafkaMessage? msg;
                try
                {
                    msg = JsonSerializer.Deserialize<MarketDataKafkaMessage>(
                        result.Message.Value, JsonOptions);
                }
                catch (JsonException ex)
                {
                    _logger.LogWarning("Failed to parse market.data JSON: {Error} payload={Payload}",
                        ex.Message, result.Message.Value);
                    continue;
                }

                if (msg == null || string.IsNullOrEmpty(msg.Symbol))
                    continue;

                // Use EventTime (market time) as the cache timestamp; this
                // matches the T+1 / market-hours semantics already established
                // in ExecutionGrpcService.
                _cache.Update(new MarketData
                {
                    Symbol = msg.Symbol,
                    Open = msg.Open,
                    High = msg.High,
                    Low = msg.Low,
                    Close = msg.Close,
                    Volume = msg.Volume,
                    Timestamp = msg.EventTime,
                });
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Kafka consumer loop crashed");
        }
        finally
        {
            try
            {
                _consumer.Close();
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Error closing Kafka consumer");
            }
            await Task.CompletedTask;
        }
    }

    public override void Dispose()
    {
        _consumer?.Dispose();
        base.Dispose();
    }
}
