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
    public async Task CalculateRealizedPnLAsync_ShouldReturnCommission()
    {
        // Arrange
        var position = new Position { Symbol = "600000.SH" };
        var trade = new Trade { Commission = 5.5m };

        // Act
        var result = await _sut.CalculateRealizedPnLAsync(position, trade);

        // Assert
        result.Should().Be(5.5m);
    }

    [Fact]
    public void CalculatePerformanceMetrics_WhenNoTrades_ShouldReturnZeroMetrics()
    {
        // Arrange
        var trades = new List<Trade>();

        // Act
        var result = _sut.CalculatePerformanceMetrics(trades);

        // Assert
        result.TotalReturn.Should().Be(0);
        result.TotalTrades.Should().Be(0);
        result.WinRate.Should().Be(0);
    }

    [Fact]
    public void CalculatePerformanceMetrics_WhenTradesExist_ShouldCalculateMetrics()
    {
        // Arrange
        var trades = new List<Trade>
        {
            new() { Price = 10.0m, Quantity = 100, Side = "sell" },
            new() { Price = 12.0m, Quantity = 50, Side = "sell" }
        };

        // Act
        var result = _sut.CalculatePerformanceMetrics(trades);

        // Assert
        result.TotalTrades.Should().Be(2);
        result.TotalReturn.Should().BeGreaterThan(0);
    }
}
