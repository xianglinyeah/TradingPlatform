namespace MarketData.Replay.Models;

public enum ReplayStatus
{
    Created = 0,
    Running = 1,
    Paused = 2,
    Completed = 3,
    Failed = 4,
    Stopped = 5
}
