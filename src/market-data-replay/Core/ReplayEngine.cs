using MarketData.Replay.Data.Loaders;
using MarketData.Replay.Data.Repositories;
using MarketData.Replay.Data.Messaging;
using MarketData.Replay.Models;
using MarketData.Replay.Utils;
using Microsoft.Extensions.Logging;
using System.Collections.Concurrent;

namespace MarketData.Replay.Core;

public class ReplayEngine : IReplayEngine
{
    private readonly IReplayDataLoader _dataLoader;
    private readonly ISessionRepository _sessionRepo;
    private readonly IReplayEventPublisher _publisher;
    private readonly ILogger<ReplayEngine> _logger;
    private readonly ConcurrentDictionary<string, CancellationTokenSource> _runningSessions = new();

    public ReplayEngine(
        IReplayDataLoader dataLoader,
        ISessionRepository sessionRepo,
        IReplayEventPublisher publisher,
        ILogger<ReplayEngine> logger)
    {
        _dataLoader = dataLoader;
        _sessionRepo = sessionRepo;
        _publisher = publisher;
        _logger = logger;
    }

    public async Task<string> StartAsync(ReplayConfig config, CancellationToken cancellationToken = default)
    {
        var sessionId = await _sessionRepo.CreateSessionAsync(config);

        var cts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        _runningSessions.TryAdd(sessionId, cts);

        _ = Task.Run(() => RunReplayAsync(sessionId, config, cts.Token));

        _logger.LogInformation("Starting replay session: {SessionId}", sessionId);
        return sessionId;
    }

    private async Task RunReplayAsync(string sessionId, ReplayConfig config, CancellationToken cancellationToken)
    {
        ReplaySession? session = null;

        try
        {
            session = await _sessionRepo.GetSessionAsync(sessionId);
            if (session == null)
            {
                _logger.LogError("Session does not exist: {SessionId}", sessionId);
                return;
            }

            session.Status = ReplayStatus.Running;
            session.StartedAt = DateTime.UtcNow;
            await _sessionRepo.UpdateSessionAsync(session);

            _logger.LogInformation(
                "Starting replay: {SessionId}, {SymbolCount} symbols, {Start} to {End}",
                sessionId, config.Symbols.Count, config.StartTime, config.EndTime);

            await _publisher.PublishControlMessageAsync(new ControlMessage
            {
                Type = ControlMessageType.StatusChange,
                SessionId = sessionId,
                NewStatus = ReplayStatus.Running,
                Timestamp = DateTime.UtcNow
            });

            // Clear Kafka topic to avoid duplicate consumption
            _logger.LogInformation("Clearing Kafka topic to avoid duplicate consumption, SessionID: {SessionId}", sessionId);
            await _publisher.ClearTopicAsync(ReplayConstants.MARKET_DATA_TOPIC, sessionId);

            var events = await _dataLoader.LoadDataAsync(
                config.StartTime,
                config.EndTime,
                config.Symbols,
                cancellationToken);

            if (events.Count == 0)
            {
                _logger.LogWarning("No data loaded");
                session.Status = ReplayStatus.Completed;
                session.CompletedAt = DateTime.UtcNow;
                await _sessionRepo.UpdateSessionAsync(session);
                return;
            }

            session.EventsTotal = events.Count;
            await _sessionRepo.UpdateSessionAsync(session);

            var groupedEvents = events
                .GroupBy(e => e.EventTime)
                .OrderBy(g => g.Key);

            long sequenceNumber = 0;
            long processedGroups = 0;
            var speedCalculator = new SpeedCalculator(config.SpeedFactor);

            foreach (var timeGroup in groupedEvents)
            {
                cancellationToken.ThrowIfCancellationRequested();

                try
                {
                    // Periodically check status to avoid frequent database queries
                    if (processedGroups % ReplayConstants.STATUS_CHECK_INTERVAL == 0)
                    {
                        var freshSession = await _sessionRepo.GetSessionAsync(sessionId);
                        if (freshSession is null)
                        {
                            _logger.LogWarning("Session {SessionId} disappeared during replay; aborting", sessionId);
                            break;
                        }

                        if (freshSession.Status == ReplayStatus.Paused)
                        {
                            _logger.LogInformation("Replay paused: {SessionId}", sessionId);

                            while (freshSession.Status == ReplayStatus.Paused && !cancellationToken.IsCancellationRequested)
                            {
                                await Task.Delay(ReplayConstants.PAUSE_LOOP_CHECK_INTERVAL_MS, cancellationToken);
                                freshSession = await _sessionRepo.GetSessionAsync(sessionId);
                                if (freshSession is null) break;
                            }

                            if (freshSession is null)
                            {
                                _logger.LogWarning("Session {SessionId} disappeared while paused; aborting", sessionId);
                                break;
                            }

                            // Update local session object
                            session = freshSession;
                            _logger.LogInformation("Replay resumed: {SessionId}", sessionId);
                        }

                        if (freshSession.Status == ReplayStatus.Stopped)
                        {
                            _logger.LogInformation("Replay stopped: {SessionId}", sessionId);
                            break;
                        }
                    }

                    var eventTime = timeGroup.Key;
                    var delay = speedCalculator.GetDelay(eventTime, session.CurrentVirtualTime);

                    // Only apply delay at low speed, zero delay processing at high speed mode
                    if (delay > TimeSpan.Zero && config.SpeedFactor <= ReplayConstants.LOW_SPEED_THRESHOLD)
                    {
                        await Task.Delay(delay, cancellationToken);
                    }
                    // High speed mode: no delay, full speed processing

                    // Reduce log output, only record key information
                    if (processedGroups % ReplayConstants.LOG_OUTPUT_INTERVAL == 0)
                    {
                        _logger.LogInformation("Sending event group: {Time}, Event count: {Count}", eventTime, timeGroup.Count());
                    }

                    var sendTasks = timeGroup.Select(async evt =>
                    {
                        try
                        {
                            evt.SessionId = sessionId;
                            evt.ReplayTime = DateTime.UtcNow;
                            evt.SequenceNumber = Interlocked.Increment(ref sequenceNumber);
                            await _publisher.PublishMarketDataAsync(evt);
                            _logger.LogDebug("✓ Send success: {Symbol} @ {Time}", evt.Symbol, evt.EventTime);
                        }
                        catch (Exception ex)
                        {
                            _logger.LogError(ex, "✗ Send failed: {Symbol} @ {Time}", evt.Symbol, evt.EventTime);
                            throw;
                        }
                    });

                    await Task.WhenAll(sendTasks);

                    // Update local session object
                    session.EventsSent += timeGroup.Count();
                    session.CurrentVirtualTime = eventTime;
                    session.ProgressPercentage = (double)session.EventsSent / session.EventsTotal * 100;
                    processedGroups++;

                    // Reduce log and database update frequency
                    if (processedGroups % ReplayConstants.DATABASE_UPDATE_INTERVAL == 0)
                    {
                        _logger.LogInformation("Replay progress: {SessionId}, {EventsSent}/{EventsTotal} ({Progress:F1}%)",
                            sessionId, session.EventsSent, session.EventsTotal, session.ProgressPercentage);

                        await _sessionRepo.UpdateSessionAsync(session);

                        await _publisher.PublishControlMessageAsync(new ControlMessage
                        {
                            Type = ControlMessageType.Heartbeat,
                            SessionId = sessionId,
                            CurrentVirtualTime = eventTime,
                            EventsSent = session.EventsSent,
                            EventsTotal = session.EventsTotal,
                            SpeedFactor = config.SpeedFactor
                        });
                    }
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Error processing event group: {SessionId}, Current progress: {EventsSent}/{EventsTotal}",
                        sessionId, session.EventsSent, session.EventsTotal);
                    throw;
                }
            }

            // Final status update before completion
            await _sessionRepo.UpdateSessionAsync(session);

            session.Status = ReplayStatus.Completed;
            session.CompletedAt = DateTime.UtcNow;
            await _sessionRepo.UpdateSessionAsync(session);

            await _publisher.FlushAsync();

            _logger.LogInformation(
                "Replay completed: {SessionId}, Sent {EventsSent}/{EventsTotal} messages",
                sessionId, session.EventsSent, session.EventsTotal);
        }
        catch (OperationCanceledException)
        {
            _logger.LogInformation("Replay cancelled: {SessionId}", sessionId);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Replay failed: {SessionId}, Error: {ErrorMessage}", sessionId, ex.Message);

            if (session != null)
            {
                session.Status = ReplayStatus.Failed;
                session.ErrorMessage = $"{ex.Message}\n{ex.StackTrace}";
                try
                {
                    await _sessionRepo.UpdateSessionAsync(session);
                }
                catch (Exception updateEx)
                {
                    _logger.LogError(updateEx, "Error updating failed status to database: {SessionId}", sessionId);
                }
            }
        }
        finally
        {
            _runningSessions.TryRemove(sessionId, out _);
        }
    }

    public async Task PauseAsync(string sessionId)
    {
        var session = await _sessionRepo.GetSessionAsync(sessionId);
        if (session == null || session.Status != ReplayStatus.Running)
            throw new InvalidOperationException("Session does not exist or not running");

        session.Status = ReplayStatus.Paused;
        await _sessionRepo.UpdateSessionAsync(session);

        _logger.LogInformation("Pausing replay: {SessionId}", sessionId);
    }

    public async Task ResumeAsync(string sessionId)
    {
        var session = await _sessionRepo.GetSessionAsync(sessionId);
        if (session == null || session.Status != ReplayStatus.Paused)
            throw new InvalidOperationException("Session does not exist or not paused");

        session.Status = ReplayStatus.Running;
        await _sessionRepo.UpdateSessionAsync(session);

        _logger.LogInformation("Resuming replay: {SessionId}", sessionId);
    }

    public async Task StopAsync(string sessionId)
    {
        var session = await _sessionRepo.GetSessionAsync(sessionId);
        if (session == null)
            throw new InvalidOperationException("Session does not exist");

        session.Status = ReplayStatus.Stopped;
        await _sessionRepo.UpdateSessionAsync(session);

        if (_runningSessions.TryGetValue(sessionId, out var cts))
        {
            cts.Cancel();
        }

        _logger.LogInformation("Stopping replay: {SessionId}", sessionId);
    }

    public async Task<ReplaySession?> GetStatusAsync(string sessionId)
    {
        return await _sessionRepo.GetSessionAsync(sessionId);
    }
}

internal class SpeedCalculator
{
    private readonly double _speedFactor;

    public SpeedCalculator(double speedFactor)
    {
        _speedFactor = speedFactor;
    }

    public TimeSpan GetDelay(DateTime currentEventTime, DateTime lastEventTime)
    {
        if (lastEventTime == DateTime.MinValue)
        {
            return TimeSpan.Zero;
        }

        var timeDiff = currentEventTime - lastEventTime;
        var actualDelay = timeDiff.TotalMilliseconds / _speedFactor;

        // Prevent overflow and cap at reasonable maximum
        if (actualDelay < 0 || actualDelay > ReplayConstants.MAX_DELAY_MS)
        {
            actualDelay = ReplayConstants.MIN_DELAY_MS; // Use minimal delay for large gaps
        }

        return TimeSpan.FromMilliseconds(actualDelay);
    }
}
