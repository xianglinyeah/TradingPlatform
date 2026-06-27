namespace ExecutionService.Models;

/// <summary>
/// Risk check result
/// </summary>
/// <param name="IsAllowed">Whether trading is allowed</param>
/// <param name="Reason">Rejection reason (if rejected)</param>
public record RiskCheckResult(
    bool IsAllowed,
    string Reason = ""
);
