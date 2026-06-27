namespace ExecutionService.Core.MarketRules;

/// <summary>
/// Market rule check result
/// </summary>
public class MarketRuleResult
{
    /// <summary>
    /// Whether the check passed
    /// </summary>
    public bool Passed { get; set; }

    /// <summary>
    /// Reason for rejection (valid when Passed=false)
    /// </summary>
    public string Reason { get; set; } = string.Empty;

    /// <summary>
    /// Rule name (used for logging and debugging)
    /// </summary>
    public string RuleName { get; set; } = string.Empty;

    /// <summary>
    /// Create a pass result
    /// </summary>
    public static MarketRuleResult Pass() => new() { Passed = true };

    /// <summary>
    /// Create a fail result
    /// </summary>
    public static MarketRuleResult Fail(string reason, string ruleName)
        => new() { Passed = false, Reason = reason, RuleName = ruleName };
}
