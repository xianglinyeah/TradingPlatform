using MarketData.Replay.Core;
using MarketData.Replay.Data.Loaders;
using MarketData.Replay.Data.Messaging;
using MarketData.Replay.Models;
using MarketData.Replay.Data.Repositories;
using Microsoft.Extensions.Logging;
using Moq;
using FluentAssertions;
using Xunit;

namespace MarketData.Replay.Tests.Core;

public class ReplayEngineTests
{
    private readonly Mock<IReplayDataLoader> _dataLoaderMock;
    private readonly Mock<ISessionRepository> _sessionRepoMock;
    private readonly Mock<IReplayEventPublisher> _publisherMock;
    private readonly Mock<ILogger<ReplayEngine>> _loggerMock;
    private readonly ReplayEngine _sut;

    public ReplayEngineTests()
    {
        _dataLoaderMock = new Mock<IReplayDataLoader>();
        _sessionRepoMock = new Mock<ISessionRepository>();
        _publisherMock = new Mock<IReplayEventPublisher>();
        _loggerMock = new Mock<ILogger<ReplayEngine>>();

        _sut = new ReplayEngine(
            _dataLoaderMock.Object,
            _sessionRepoMock.Object,
            _publisherMock.Object,
            _loggerMock.Object
        );
    }

    [Fact]
    public async Task StartAsync_ShouldCreateSessionAndReturnSessionId()
    {
        // Arrange
        var config = new ReplayConfig
        {
            Symbols = new List<string> { "600000.SH" },
            StartTime = new DateTime(2023, 1, 1),
            EndTime = new DateTime(2023, 1, 15),
            SpeedFactor = 10000
        };
        var expectedSessionId = "test-session-123";

        _sessionRepoMock
            .Setup(x => x.CreateSessionAsync(config))
            .ReturnsAsync(expectedSessionId);

        // Act
        var result = await _sut.StartAsync(config);

        // Assert
        result.Should().Be(expectedSessionId);
        _sessionRepoMock.Verify(x => x.CreateSessionAsync(config), Times.Once);
    }

    [Fact]
    public async Task StopAsync_WhenSessionExists_ShouldCancelSession()
    {
        // Arrange
        var config = new ReplayConfig
        {
            Symbols = new List<string> { "600000.SH" },
            StartTime = new DateTime(2023, 1, 1),
            EndTime = new DateTime(2023, 1, 15),
            SpeedFactor = 10000
        };

        var session = new ReplaySession
        {
            SessionId = "test-session-123",
            Status = ReplayStatus.Running,
            Symbols = new List<string> { "600000.SH" }
        };

        _sessionRepoMock.Setup(x => x.GetSessionAsync("test-session-123")).ReturnsAsync(session);

        // Act
        await _sut.StopAsync("test-session-123");

        // Assert
        _sessionRepoMock.Verify(x => x.UpdateSessionAsync(
            It.Is<ReplaySession>(s => s.Status == ReplayStatus.Stopped)),
            Times.Once);
    }

    [Fact]
    public async Task GetStatusAsync_WhenSessionExists_ShouldReturnSession()
    {
        // Arrange
        var sessionId = "test-session-123";
        var expectedSession = new ReplaySession
        {
            SessionId = sessionId,
            Status = ReplayStatus.Running,
            Symbols = new List<string> { "600000.SH" }
        };

        _sessionRepoMock
            .Setup(x => x.GetSessionAsync(sessionId))
            .ReturnsAsync(expectedSession);

        // Act
        var result = await _sut.GetStatusAsync(sessionId);

        // Assert
        result.Should().NotBeNull();
        result!.Status.Should().Be(ReplayStatus.Running);
        result!.Symbols.Should().Contain("600000.SH");
    }
}
