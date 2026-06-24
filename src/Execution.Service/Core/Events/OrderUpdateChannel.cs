using System.Threading.Channels;

namespace ExecutionService.Core.Events;

/// <summary>
/// Order status update event bus (added in P1.2)
///
/// Written by PositionManager/ExecutionGrpcService; read out by the gRPC SubscribeOrderUpdates stream.
/// Uses a Bounded Channel to guarantee backpressure (when writes are too fast, WriteAsync blocks instead of dropping messages).
/// </summary>
public sealed class OrderUpdateChannel : IDisposable
{
    private readonly Channel<OrderUpdateEvent> _channel =
        Channel.CreateBounded<OrderUpdateEvent>(
            new BoundedChannelOptions(1000)
            {
                FullMode = BoundedChannelFullMode.Wait,
                SingleReader = false,
                SingleWriter = false
            });

    public ValueTask WriteAsync(OrderUpdateEvent update, CancellationToken ct = default)
        => _channel.Writer.WriteAsync(update, ct);

    public IAsyncEnumerable<OrderUpdateEvent> ReadAllAsync(CancellationToken ct = default)
        => _channel.Reader.ReadAllAsync(ct);

    public bool TryComplete() => _channel.Writer.TryComplete();

    public void Dispose()
    {
        _channel.Writer.TryComplete();
    }
}

/// <summary>
/// Order status update event (internal C# model, corresponds to proto OrderUpdate)
/// </summary>
public sealed record OrderUpdateEvent
{
    public required string SessionId { get; init; }
    public required string OrderId { get; init; }

    /// <summary>0=Pending, 1=Filled, 2=Partial, 3=Cancelled, 4=Rejected, 5=Expired</summary>
    public required int Status { get; init; }

    public double FilledQuantity { get; init; }
    public double RemainingQuantity { get; init; }
    public double AvgFillPrice { get; init; }

    public FillDetailEvent? LastFill { get; init; }

    public string? Message { get; init; }

    public required string Timestamp { get; init; }
}

public sealed record FillDetailEvent
{
    public double Quantity { get; init; }
    public double Price { get; init; }
    public string? BrokerFillId { get; init; }
}
