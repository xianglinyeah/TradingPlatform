using ExecutionService.Models;

namespace ExecutionService.Models;

/// <summary>
/// Single fill detail (added in P0.3)
///
/// Semantics: an order can be split into multiple fills, each producing 1 Trade row.
/// The old implementation aggregated all fills into a single Trade, losing per-fill details; this type fills that gap.
/// </summary>
public record Fill
{
    /// <summary>Quantity of this fill</summary>
    public decimal Quantity { get; init; }

    /// <summary>Price of this fill</summary>
    public decimal Price { get; init; }

    /// <summary>Timestamp of this fill</summary>
    public DateTime FillTime { get; init; }

    /// <summary>Execution id returned by the broker (GM/live); null for simulated matching</summary>
    public string? BrokerFillId { get; init; }

    /// <summary>Commission allocated to this fill</summary>
    public decimal Commission { get; init; }
}

/// <summary>
/// Adapter execution result (added in P0.3)
///
/// Terminal order + list of fill details:
///   - Filled     -> Fills contains >=1 entry, the order Quantity is fully filled
///   - Partial    -> Fills contains >=1 entry, but Sum(Quantity) < order.Quantity
///   - Rejected   -> Fills is empty
///   - Cancelled  -> Fills contains the portion filled before cancel order (may be empty)
/// </summary>
public record ExecutionResult
{
    public required Order Order { get; init; }

    public IReadOnlyList<Fill> Fills { get; init; } = Array.Empty<Fill>();
}
