namespace MarketData.Replay.Models;

public enum ControlMessageType
{
    Heartbeat,
    StatusChange,
    TimeSeek,
    SpeedChange
}

public class ControlMessage
{
    public ControlMessageType Type { get; set; }
    public string SessionId { get; set; } = string.Empty;
    public DateTime Timestamp { get; set; } = DateTime.Now;
    public DateTime? CurrentVirtualTime { get; set; }
    public long? EventsSent { get; set; }
    public long? EventsTotal { get; set; }
    public double? SpeedFactor { get; set; }
    public ReplayStatus? OldStatus { get; set; }
    public ReplayStatus? NewStatus { get; set; }
}
