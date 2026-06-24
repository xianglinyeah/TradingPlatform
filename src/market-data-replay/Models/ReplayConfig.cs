namespace MarketData.Replay.Models;

public class ReplayConfig
{
    public DateTime StartTime { get; set; }
    public DateTime EndTime { get; set; }
    public List<string> Symbols { get; set; } = new();
    public double SpeedFactor { get; set; } = 1000.0;
    public Dictionary<string, string> Options { get; set; } = new();
}
