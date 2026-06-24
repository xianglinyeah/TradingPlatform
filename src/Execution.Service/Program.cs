using Execution.Service.Models;
using Execution.Service.Services;
using ExecutionService.Core.Adapters;
using ExecutionService.Core.Services;
using ExecutionService.Core.MarketRules;
using ExecutionService.Core.Events;
using ExecutionService.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Serilog;
using Serilog.Events;

var builder = WebApplication.CreateBuilder(args);

// Fix PostgreSQL DateTime timezone issue - must be set early in application startup
AppContext.SetSwitch("Npgsql.EnableLegacyTimestampBehavior", true);

// Add gRPC services
builder.Services.AddGrpc();

// Add gRPC reflection service
builder.Services.AddGrpcReflection();

// Add database
builder.Services.AddDbContext<ExecutionDbContext>(options =>
    options.UseNpgsql(builder.Configuration.GetConnectionString("DefaultConnection")));

// Register repositories
builder.Services.AddRepositories();

// Register database migrator (added in P0.5)
builder.Services.AddScoped<IDatabaseMigrator, DatabaseMigrator>();

// Register core services
builder.Services.AddScoped<IPositionManager, PositionManager>(); // Change to Scoped to use database
builder.Services.AddScoped<IAccountManager, AccountManager>();     // Change to Scoped to use database
builder.Services.AddScoped<IPnLCalculator, PnLCalculatorService>();
builder.Services.AddScoped<IRiskManager, RiskManager>();
builder.Services.AddScoped<IMarketRuleValidator, MarketRuleValidator>();

// P1.2: OrderUpdate event bus (Singleton — shared across gRPC calls)
builder.Services.AddSingleton<OrderUpdateChannel>();

// Add ExecutionSettings configuration
builder.Services.Configure<ExecutionSettings>(
    builder.Configuration.GetSection(ExecutionSettings.SectionName));

// Add GM configuration
builder.Services.Configure<GMSettings>(
    builder.Configuration.GetSection(GMSettings.SectionName));

// Register ExecutionAdapter (select implementation based on configuration)
// Scoped lifetime: adapter depends on scoped services (IPnLCalculator, IRiskManager, etc.)
// and is consumed by ExecutionGrpcService which itself is scoped per-gRPC-call.
builder.Services.AddScoped<IExecutionAdapter>(serviceProvider =>
{
    var config = serviceProvider.GetRequiredService<IOptions<ExecutionSettings>>();
    var gmSettings = serviceProvider.GetRequiredService<IOptions<GMSettings>>();
    var pnlCalculator = serviceProvider.GetRequiredService<IPnLCalculator>();
    var riskManager = serviceProvider.GetRequiredService<IRiskManager>();
    var accountManager = serviceProvider.GetRequiredService<IAccountManager>();
    var loggerFactory = serviceProvider.GetRequiredService<ILoggerFactory>();

    return ExecutionAdapterFactory.CreateAdapter(config, gmSettings, pnlCalculator, riskManager, accountManager, serviceProvider, loggerFactory);
});

// Add CORS
builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
        policy.AllowAnyOrigin()
              .AllowAnyMethod()
              .AllowAnyHeader());
});

// Add logging - only write to Console, let K8s automatically collect to /var/log/pods/
builder.Logging.AddConsole();
builder.Logging.SetMinimumLevel(LogLevel.Trace); // Set to most verbose level
builder.Logging.AddFilter("Microsoft", LogLevel.Warning); // Reduce framework logs
builder.Logging.AddFilter("Grpc", LogLevel.Information); // Show gRPC related logs
builder.Logging.AddFilter("ExecutionService", LogLevel.Trace); // Show all our service logs

// Add Serilog - only write to Console, not files (K8s will automatically collect stdout)
builder.Host.UseSerilog((context, configuration) =>
{
    configuration.WriteTo.Console(restrictedToMinimumLevel: LogEventLevel.Information);
});

var app = builder.Build();

// P0.5: Run database migration on startup (TRUNCATE + ALTER, deduplicated via schema_version single-row table)
try
{
    using (var scope = app.Services.CreateScope())
    {
        var migrator = scope.ServiceProvider.GetRequiredService<IDatabaseMigrator>();
        await migrator.MigrateAsync();
    }
}
catch (Exception ex)
{
    var bootLogger = app.Services.GetRequiredService<ILogger<Program>>();
    bootLogger.LogError(ex, "Database migration failed on startup; continuing startup but OMS state may be inconsistent");
}

// Configure HTTP request pipeline
app.UseCors();

if (app.Environment.IsDevelopment())
{
    app.MapGrpcReflectionService();
}

// Map gRPC services
app.MapGrpcService<ExecutionGrpcService>();

// Health check endpoint
app.MapGet("/", () => "ExecutionService gRPC Server is running!");

app.MapGet("/health", () => new
{
    Status = "Healthy",
    Timestamp = DateTime.UtcNow,
    Service = "ExecutionService"
});

app.Run();
