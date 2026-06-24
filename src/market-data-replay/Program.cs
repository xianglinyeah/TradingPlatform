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
    ?? @"D:\BackTesting\data\minute\1min";

builder.Services.AddSingleton<IReplayDataLoader>(sp =>
{
    var logger = sp.GetRequiredService<Microsoft.Extensions.Logging.ILogger<ParquetDataLoader>>();
    return new ParquetDataLoader(dataPath, logger);
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
