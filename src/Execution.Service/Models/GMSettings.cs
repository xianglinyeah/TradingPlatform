namespace Execution.Service.Models;

/// <summary>
/// GM configuration settings
/// Note: This class should be kept in sync with GMSettings in execution_adapter_gm (Python)
/// </summary>
public class GMSettings
{
    public const string SectionName = "GM";

    /// <summary>
    /// GM API Token
    /// </summary>
    public string GmToken { get; set; } = string.Empty;

    /// <summary>
    /// GM service address (for GM API calls)
    /// </summary>
    public string GmAddress { get; set; } = "127.0.0.1:7001";

    /// <summary>
    /// gRPC server address (for Execution.Service calls)
    /// </summary>
    public string GrpcServerAddress { get; set; } = "http://localhost:5005";

    /// <summary>
    /// Paper trading account ID
    /// </summary>
    public string PaperAccountId { get; set; } = string.Empty;

    /// <summary>
    /// Live trading account ID (reserved for future use)
    /// </summary>
    public string LiveAccountId { get; set; } = string.Empty;
}
