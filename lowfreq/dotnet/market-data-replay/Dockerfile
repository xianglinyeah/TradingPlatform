# Simple Dockerfile for MarketData.Replay - uses pre-built binaries
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS base
WORKDIR /app
EXPOSE 8080

# Copy the built application
COPY artifacts/market-data-replay/ .

# Create data directory
RUN mkdir -p /data

ENTRYPOINT ["dotnet", "MarketData.Replay.dll"]
