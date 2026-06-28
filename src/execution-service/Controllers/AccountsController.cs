using ExecutionService.Data.IRepositories;
using ExecutionService.Models;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;

namespace Execution.Service.Controllers;

/// <summary>
/// Read-only REST query API for the live account state of a trading session.
/// Reads from <see cref="IAccountRepository"/> (PostgreSQL) to bypass the
/// in-memory <c>AccountManager</c> row-lock contention.
/// </summary>
[ApiController]
[Route("api/[controller]")]
public class AccountsController : ControllerBase
{
    private readonly IAccountRepository _accountRepo;
    private readonly ILogger<AccountsController> _logger;

    public AccountsController(IAccountRepository accountRepo, ILogger<AccountsController> logger)
    {
        _accountRepo = accountRepo;
        _logger = logger;
    }

    /// <summary>Get the account snapshot (cash, equity, PnL) for a session.</summary>
    [HttpGet("{sessionId}")]
    public async Task<ActionResult<Account>> GetAccount(string sessionId)
    {
        try
        {
            var account = await _accountRepo.GetAccountAsync(sessionId);
            if (account == null)
                return NotFound(new { error = $"No account for session {sessionId}" });
            return Ok(account);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to query account for session {SessionId}", sessionId);
            return BadRequest(new { error = ex.Message });
        }
    }
}
