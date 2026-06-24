# Simple Dockerfile for Execution.Service - uses pre-built binaries
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS base
WORKDIR /app
EXPOSE 8084

# Copy the built application
COPY artifacts/execution-service/ .

# Create logs directory
RUN mkdir -p /app/logs

# Set environment variables
ENV ASPNETCORE_URLS=http://+:8084

ENTRYPOINT ["dotnet", "Execution.Service.dll"]
