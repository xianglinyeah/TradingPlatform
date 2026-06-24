using ExecutionService.Models;
using ExecutionService.Core.Adapters;
using Xunit;

namespace ExecutionService.Tests.Adapters;

/// <summary>
/// Unit tests for ExecutionAdapterBase.ValidateOrderAsync.
///
/// Regression coverage for the shared validation guard:
///   - Negative or zero quantity must be rejected before reaching any adapter.
///   - Empty/whitespace symbol must be rejected.
///   - Valid orders must pass.
/// </summary>
public class ExecutionAdapterBaseTests
{
    /// <summary>
    /// Minimal concrete adapter that exposes the base-class validation
    /// without requiring any external dependencies. The abstract members
    /// are stubbed with NotImplementedException because ValidateOrderAsync
    /// does not delegate to them.
    /// </summary>
    private sealed class TestAdapter : ExecutionAdapterBase
    {
        public override Task<ExecutionResult> ExecuteOrderAsync(Order order, MarketData marketData)
            => throw new NotImplementedException();

        public override Task<RiskCheckResult> CheckOrderRiskAsync(Order order)
            => throw new NotImplementedException();

        public override Task<bool> CancelOrderAsync(string orderId, string sessionId)
            => throw new NotImplementedException();

        public override string GetAdapterType() => "Test";
    }

    private static Order MakeOrder(decimal quantity, string symbol = "600000.SH") => new()
    {
        Symbol = symbol,
        Side = OrderSide.Buy,
        Quantity = quantity,
        Price = 10m
    };

    // ===== Quantity validation =====

    [Fact]
    public async Task ValidateOrderAsync_NegativeQuantity_ReturnsFalse()
    {
        var adapter = new TestAdapter();
        var order = MakeOrder(-100);

        var result = await adapter.ValidateOrderAsync(order);

        Assert.False(result);
    }

    [Fact]
    public async Task ValidateOrderAsync_ZeroQuantity_ReturnsFalse()
    {
        // Boundary: quantity == 0 must be rejected (Quantity <= 0).
        var adapter = new TestAdapter();
        var order = MakeOrder(0);

        var result = await adapter.ValidateOrderAsync(order);

        Assert.False(result);
    }

    [Theory]
    [InlineData(-1)]
    [InlineData(-1000)]
    public async Task ValidateOrderAsync_NegativeQuantities_ReturnsFalse(int qty)
    {
        var adapter = new TestAdapter();
        var order = MakeOrder(qty);

        var result = await adapter.ValidateOrderAsync(order);

        Assert.False(result);
    }

    // ===== Symbol validation =====

    [Fact]
    public async Task ValidateOrderAsync_EmptySymbol_ReturnsFalse()
    {
        var adapter = new TestAdapter();
        var order = MakeOrder(100, symbol: "");

        var result = await adapter.ValidateOrderAsync(order);

        Assert.False(result);
    }

    [Fact]
    public async Task ValidateOrderAsync_NullSymbol_ReturnsFalse()
    {
        var adapter = new TestAdapter();
        var order = MakeOrder(100);
        order.Symbol = null!;

        var result = await adapter.ValidateOrderAsync(order);

        Assert.False(result);
    }

    // ===== Valid orders =====

    [Fact]
    public async Task ValidateOrderAsync_ValidOrder_ReturnsTrue()
    {
        var adapter = new TestAdapter();
        var order = MakeOrder(100, symbol: "600000.SH");

        var result = await adapter.ValidateOrderAsync(order);

        Assert.True(result);
    }

    [Fact]
    public async Task ValidateOrderAsync_BoardLotQuantity_ReturnsTrue()
    {
        // A-share minimum trade unit is 100 shares.
        var adapter = new TestAdapter();
        var order = MakeOrder(100);

        var result = await adapter.ValidateOrderAsync(order);

        Assert.True(result);
    }

    [Fact]
    public async Task ValidateOrderAsync_LargeQuantity_ReturnsTrue()
    {
        // Validation is structural, not risk-based; large size is allowed here.
        var adapter = new TestAdapter();
        var order = MakeOrder(1_000_000);

        var result = await adapter.ValidateOrderAsync(order);

        Assert.True(result);
    }

    /// <summary>
    /// Regression: the validation contract must check BOTH conditions independently.
    /// An order with valid symbol but bad quantity, and vice versa, must both fail.
    /// </summary>
    [Fact]
    public async Task ValidateOrderAsync_BadQuantityGoodSymbol_StillFails()
    {
        var adapter = new TestAdapter();
        var order = MakeOrder(-100, symbol: "600000.SH");

        var result = await adapter.ValidateOrderAsync(order);

        Assert.False(result);
    }

    [Fact]
    public async Task ValidateOrderAsync_GoodQuantityBadSymbol_StillFails()
    {
        var adapter = new TestAdapter();
        var order = MakeOrder(100, symbol: "");

        var result = await adapter.ValidateOrderAsync(order);

        Assert.False(result);
    }
}
