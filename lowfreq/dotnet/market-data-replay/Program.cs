using Serilog;
using Serilog.Events;
using MarketData.Replay.Core;
using MarketData.Replay.Data.Repositories;
using MarketData.Replay.Data.Loaders;
using MarketData.Replay.Data.Messaging;
using MarketData.Replay.Models;
using Microsoft.Extensions.Options;

var builder = WebApplication.CreateBuilder(args);

Log.Logger = new LoggerConfiguration()
    .MinimumLevel.Information()
    .WriteTo.Console()  // Only write to Console, let K8s automatically collect to /var/log/pods/
    .CreateLogger();

builder.Host.UseSerilog();

builder.Services.Configure<KafkaConfig>(builder.Configuration.GetSection("Kafka"));

// Add CORS support
builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
    {
        policy.AllowAnyOrigin()
              .AllowAnyMethod()
              .AllowAnyHeader();
    });
});

// Add REST API services
builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new Microsoft.OpenApi.Models.OpenApiInfo
    {
        Title = "Replay Service API",
        Version = "v1",
        Description = "Stock data replay service API"
    });
});

var dataPath = builder.Configuration.GetValue<string>("DataPath")
    ?? @"/data/minute/1min";

// Loader selection: ClickHouse is the default; Parquet stays available as a
// config-driven fallback so we can roll back without redeploying reads.
// Parquet writes continue in data-ingestion either way (double-write backup).
var dataSource = (builder.Configuration.GetValue<string>("DataSource") ?? "ClickHouse")
    .Trim().Equals("Parquet", StringComparison.OrdinalIgnoreCase)
        ? "Parquet" : "ClickHouse";

builder.Services.AddSingleton<IReplayDataLoader>(sp =>
{
    var factory = sp.GetRequiredService<ILoggerFactory>();
    if (dataSource == "Parquet")
    {
        Log.Information("IReplayDataLoader: using Parquet (DataSource=Parquet)");
        return new ParquetDataLoader(dataPath, factory.CreateLogger<ParquetDataLoader>());
    }

    var ch = builder.Configuration.GetSection("ClickHouse");
    var host = ch["Host"] ?? "clickhouse.infrastructure";
    var port = ch.GetValue<int?>("Port") ?? 8123;
    var db = ch["Database"] ?? "market_data";
    var user = ch["Username"] ?? "dev_user";
    var pwd = ch["Password"] ?? "dev_pass";
    // ClickHouse.Client accepts a Npgsql-style connection string.
    var connStr = $"Host={host};Port={port};Database={db};Username={user};Password={pwd}";
    Log.Information("IReplayDataLoader: using ClickHouse (DataSource=ClickHouse, {Host}:{Port}/{Database})", host, port, db);
    return new ClickHouseDataLoader(connStr, db, factory.CreateLogger<ClickHouseDataLoader>());
});

// Get connection string from configuration
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection")
    ?? "Host=postgres;Port=5432;Database=dev;Username=dev_user;Password=dev_pass;Search Path=market_data,public";

builder.Services.AddSingleton<ISessionRepository>(sp =>
{
    var logger = sp.GetRequiredService<Microsoft.Extensions.Logging.ILogger<SessionRepository>>();
    return new SessionRepository(connectionString, logger);
});

builder.Services.AddSingleton<IReplayEventPublisher>(sp =>
{
    var logger = sp.GetRequiredService<Microsoft.Extensions.Logging.ILogger<KafkaReplayEventPublisher>>();
    return new KafkaReplayEventPublisher(sp.GetRequiredService<IOptions<KafkaConfig>>(), logger);
});

builder.Services.AddSingleton<IReplayEngine, ReplayEngine>();

Log.Information("Starting Simulation mode (default)");

var app = builder.Build();

// Configure HTTP request pipeline
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.UseCors();

app.UseAuthorization();

app.MapControllers();

// Simple root path
app.MapGet("/", () => "ReplayService REST API is running. Access /swagger for API documentation.");

try
{
    Log.Information("Starting MarketData.Replay on http://localhost:5000");
    app.Run();
}
catch (Exception ex)
{
    Log.Fatal(ex, "Application start-up failed");
}
finally
{
    Log.CloseAndFlush();
}
