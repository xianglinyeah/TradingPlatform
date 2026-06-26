# Simple Dockerfile for Execution.Service - uses pre-built binaries
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS base
WORKDIR /app
EXPOSE 8084

# Copy the pre-built application (output of `dotnet publish`)
COPY bin/Release/net8.0/publish/ .

# Create logs directory
RUN mkdir -p /app/logs

# Set environment variables
ENV ASPNETCORE_URLS=http://+:8084

ENTRYPOINT ["dotnet", "Execution.Service.dll"]
