using System.Collections.Concurrent;
using ExecutionService.Models;

namespace ExecutionService.Core.MarketFeed;

/// <summary>
/// Process-local cache of the latest market bar per symbol.
///
/// Populated by <see cref="KafkaMarketDataConsumer"/> which subscribes to the
/// <c>market.data</c> Kafka topic. Read at SubmitOrder time by
/// <c>ExecutionGrpcService</c> to obtain an execution-time price reference
/// that is independent of the order's signal-time price (which previously
/// fed <c>Close = order.Price</c>, creating a circular dependency that made
/// time-delay slippage structurally impossible to model).
///
/// Thread-safe via <see cref="ConcurrentDictionary{TKey,TValue}"/>. Single-writer
/// (the consumer) and many-readers (concurrent gRPC calls). The latest bar
/// per symbol wins; stale bars are simply overwritten.
/// </summary>
public sealed class MarketDataCache
{
    private readonly ConcurrentDictionary<string, MarketData> _latest =
        new(StringComparer.Ordinal);

    /// <summary>Insert or replace the cached bar for <paramref name="data"/>'s symbol.</summary>
    public void Update(MarketData data)
    {
        if (data == null || string.IsNullOrEmpty(data.Symbol))
            return;
        _latest[data.Symbol] = data;
    }

    /// <summary>Return the latest bar for <paramref name="symbol"/>, or null if none cached.</summary>
    public MarketData? GetLatest(string symbol)
        => _latest.TryGetValue(symbol ?? string.Empty, out var d) ? d : null;

    /// <summary>Number of symbols currently cached (diagnostics / metrics only).</summary>
    public int Count => _latest.Count;
}
