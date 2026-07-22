using ExecutionService.Models;
using ExecutionService.Core.Services;
using ExecutionService.Data.IRepositories;
using ExecutionService.Core.Utils;

namespace ExecutionService.Core.Services;

public class AccountManager : IAccountManager
{
    private readonly ILogger<AccountManager> _logger;
    private readonly IAccountRepository _accountRepository;

    public AccountManager(ILogger<AccountManager> logger, IAccountRepository accountRepository)
    {
        _logger = logger;
        _accountRepository = accountRepository;
    }

    public async Task<Account> GetAccountAsync(string sessionId)
    {
        var account = await _accountRepository.GetAccountAsync(sessionId);
        if (account == null)
        {
            _logger.LogInformation("Creating new account: {SessionId}, Initial capital: {InitialCapital}", sessionId, AccountConstants.DEFAULT_INITIAL_CAPITAL);
            account = await _accountRepository.GetOrCreateAccountAsync(sessionId, AccountConstants.DEFAULT_INITIAL_CAPITAL);
        }

        return account;
    }

    public async Task UpdateCashAsync(string sessionId, decimal amount)
    {
        var account = await _accountRepository.GetAccountAsync(sessionId);
        if (account != null)
        {
            account.Cash += amount;
            await _accountRepository.UpdateAccountAsync(account);
            _logger.LogDebug("Updating cash: {SessionId}, Amount: {Amount}, Current cash: {Cash}", sessionId, amount, account.Cash);
        }
    }

    public async Task UpdateEquityAsync(string sessionId)
    {
        var account = await _accountRepository.GetAccountAsync(sessionId);
        if (account != null)
        {
            account.Equity = account.Cash + account.MarketValue;
            account.TotalPnL = account.Equity - account.InitialCapital;
            await _accountRepository.UpdateAccountAsync(account);
        }
    }

    public async Task AddCommissionAsync(string sessionId, decimal commission)
    {
        var account = await _accountRepository.GetAccountAsync(sessionId);
        if (account != null)
        {
            account.TotalCommission += commission;
            await _accountRepository.UpdateAccountAsync(account);
        }
    }

    public async Task<int> IncrementTradeCountAsync(string sessionId)
    {
        var account = await _accountRepository.GetAccountAsync(sessionId);
        if (account != null)
        {
            account.TotalTrades++;
            await _accountRepository.UpdateAccountAsync(account);
            return account.TotalTrades;
        }
        return 0;
    }
}