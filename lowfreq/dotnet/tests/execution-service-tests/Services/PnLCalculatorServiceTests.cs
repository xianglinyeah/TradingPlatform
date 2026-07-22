using ExecutionService.Core.Services;
using ExecutionService.Models;
using FluentAssertions;
using Microsoft.Extensions.Logging;
using Moq;
using Xunit;

namespace Execution.Service.Tests.Services;

public class PnLCalculatorServiceTests
{
    private readonly PnLCalculatorService _sut;
    private readonly Mock<ILogger<PnLCalculatorService>> _loggerMock;

    public PnLCalculatorServiceTests()
    {
        _loggerMock = new Mock<ILogger<PnLCalculatorService>>();
        _sut = new PnLCalculatorService(_loggerMock.Object);
    }

    [Fact]
    public async Task CalculateUnrealizedPnLAsync_WhenPositionExists_ShouldReturnCorrectPnL()
    {
        // Arrange
        var positions = new List<Position>
        {
            new() { Symbol = "600000.SH", Quantity = 100, AvgPrice = 10.0m }
        };
        var currentPrices = new Dictionary<string, decimal>
        {
            { "600000.SH", 12.0m }
        };

        // Act
        var result = await _sut.CalculateUnrealizedPnLAsync(positions, currentPrices);

        // Assert
        result.Should().ContainKey("600000.SH");
        result["600000.SH"].Should().Be(200m); // (12 - 10) * 100
    }

    [Fact]
    public async Task CalculateUnrealizedPnLAsync_WhenPriceMissing_ShouldNotCalculatePnL()
    {
        // Arrange
        var positions = new List<Position>
        {
            new() { Symbol = "600000.SH", Quantity = 100, AvgPrice = 10.0m }
        };
        var currentPrices = new Dictionary<string, decimal>
        {
            { "600519.SH", 12.0m }
        };

        // Act
        var result = await _sut.CalculateUnrealizedPnLAsync(positions, currentPrices);

        // Assert
        result.Should().BeEmpty();
    }

    [Fact]
    public async Task CalculateRealizedPnLAsync_NotImplemented_Throws()
    {
        // Arrange
        var position = new Position { Symbol = "600000.SH" };
        var trade = new Trade { Commission = 5.5m };

        // Act + Assert: stub throws so any future caller fails loudly rather
        // than silently receiving just the commission (the old behavior was
        // not actual realized PnL). Realized PnL lives on Position.RealizedPnL.
        var act = async () => await _sut.CalculateRealizedPnLAsync(position, trade);
        await act.Should().ThrowAsync<NotSupportedException>();
    }

    [Fact]
    public void CalculatePerformanceMetrics_NotImplemented_Throws()
    {
        // Arrange
        var trades = new List<Trade>();

        // Act + Assert: Sharpe / MaxDrawdown require a return time-series that
        // the per-trade list does not provide. Throwing prevents silent
        // zero-return / zero-volatility output.
        var act = () => _sut.CalculatePerformanceMetrics(trades);
        act.Should().Throw<NotSupportedException>();
    }
}
