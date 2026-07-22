using MarketData.Replay.Models;

namespace MarketData.Replay.Core;

public interface IReplayEngine
{
    Task<string> StartAsync(ReplayConfig config, CancellationToken cancellationToken = default);
    Task PauseAsync(string sessionId);
    Task ResumeAsync(string sessionId);
    Task StopAsync(string sessionId);
    Task<ReplaySession?> GetStatusAsync(string sessionId);
}
