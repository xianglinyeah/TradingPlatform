namespace MarketData.Replay.Models;

public class ReplaySession
{
    public string SessionId { get; set; } = string.Empty;
    public ReplayStatus Status { get; set; }
    public DateTime StartTime { get; set; }
    public DateTime EndTime { get; set; }
    public DateTime CurrentVirtualTime { get; set; }
    public List<string> Symbols { get; set; } = new();
    public double SpeedFactor { get; set; }
    public long EventsSent { get; set; }
    public long EventsTotal { get; set; }
    public double ProgressPercentage { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime? StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
    public string? ErrorMessage { get; set; }
    public string? ConfigJson { get; set; }
}
