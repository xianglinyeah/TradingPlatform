# Grafana Configuration Backup

This directory contains the complete backup of Grafana dashboards, datasources, and configurations from the running Kubernetes deployment.

## 📋 Backup Contents

### Dashboards (2)
- **dashboard-log.json** - Log monitoring dashboard with Loki integration
  - Tracks log volumes over time
  - Displays all logs with filtering capabilities
  - Shows error logs separately
  - Container and stream-based log analysis

- **dashboard-message-flow.json** - Message flow monitoring dashboard
  - Tracks gRPC and Kafka message flow
  - Trading system message visualization

### Datasources (6)
- **datasources.json** - All configured datasources:
  1. **Loki** (efoeexvwey5tsa) - Default datasource for logs
  2. **Postgres** (P44368ADAD746BC27) - Read-only Postgres access
  3. **PostgreSQL** (efof4kmn99szkf) - Execution service database
  4. **PostgreSQL-Backtesting** (ffof5w53rq1a8b) - Backtesting database
  5. **PostgreSQL-Execution** (dfof4vfjrnr40d) - Execution specific database
  6. **PostgreSQL-Final** (afof5zwhulerka) - Final Postgres datasource

### Organization
- **folders.json** - Grafana folder structure (currently empty)

## 🚀 Restore Instructions

### Prerequisites
- Grafana must be running and accessible
- Admin credentials (default: admin/admin)
- For K8s deployment: `kubectl port-forward svc/grafana -n infrastructure 30100:3000`

### Restore Dashboards

#### Method 1: Using Grafana UI
1. Open Grafana at `http://localhost:30100` (or your Grafana URL)
2. Navigate to **Dashboards** → **Import**
3. Upload each dashboard JSON file:
   - `dashboard-log.json`
   - `dashboard-message-flow.json`
4. Configure datasource mappings if needed
5. Click **Import**

#### Method 2: Using Grafana API
```bash
# For each dashboard file:
curl -X POST -u "admin:admin" \
  "http://localhost:30100/api/dashboards/db" \
  -H "Content-Type: application/json" \
  -d @dashboard-log.json

curl -X POST -u "admin:admin" \
  "http://localhost:30100/api/dashboards/db" \
  -H "Content-Type: application/json" \
  -d @dashboard-message-flow.json
```

### Restore Datasources

#### Method 1: Using Grafana UI
1. Navigate to **Configuration** → **Data Sources**
2. Add each datasource from the JSON file manually
3. Use the configurations from `datasources.json`

#### Method 2: Using Grafana API
```bash
# Restore all datasources at once
curl -X POST -u "admin:admin" \
  "http://localhost:30100/api/datasources" \
  -H "Content-Type: application/json" \
  -d @datasources.json
```

### Important Notes for Restoration

1. **UID Conflicts**: If dashboards/datasources with same UIDs exist, you may need to:
   - Delete existing ones first, or
   - Update the UIDs in the JSON files before importing

2. **Datasource Mapping**: When importing dashboards, verify that:
   - Loki datasource UID matches: `efoeexvwey5tsa`
   - Postgres datasource UIDs are correctly mapped

3. **Credentials**: The datasources in this backup use:
   - Postgres user: `dev_user`
   - Postgres databases: `execution_service`, `dev`
   - No password authentication (K8s internal service communication)

## 🔧 Configuration Details

### Loki Datasource
- **URL**: `http://loki:3100` (internal K8s service)
- **Type**: Loki
- **Access**: Proxy
- **Max Lines**: 1000

### PostgreSQL Datasources
- **URL Pattern**: `postgres.infrastructure.svc.cluster.local:5432` or `postgres.infrastructure:5432`
- **User**: `dev_user`
- **SSL Mode**: disable
- **Databases**: `execution_service`, `dev`

### Dashboard Settings
- **Refresh Interval**: 30 seconds (default)
- **Time Range**: Last 6 hours
- **Timezone**: Browser
- **Tags**: logs, loki, trading, grpc, kafka, messages

## 📅 Backup Information

- **Backup Date**: 2025-06-08
- **Grafana Version**: 13.0.2
- **Source**: Kubernetes (k3s) deployment
- **Namespace**: infrastructure
- **Service**: grafana (NodePort 30100)

## 🔍 Dashboard Features

### Log Dashboard
- **Panels**:
  - Log Volume Over Time (time series)
  - All Logs viewer (with filtering)
  - Log Volume by Container (bar gauge)
  - Log Volume by Stream (bar gauge)
  - Error Logs Only (filtered viewer)

- **Variables**:
  - `container`: Multi-select for services (execution-service, market-data-replay, strategy-engine)
  - `stream`: Auto-populated from Loki labels

- **Queries**: Uses Loki query syntax for log aggregation and filtering

### Message Flow Dashboard
- Monitors gRPC and Kafka message patterns
- Trading system message tracking
- Integration with market data and execution services

## 🛠️ Maintenance

### Regular Backup Schedule
This backup should be updated whenever:
- New dashboards are created
- Dashboard configurations are modified
- Datasources are added or changed
- Before major Grafana upgrades

### Automated Backup
Consider implementing automated backup scripts that:
1. Export dashboards via Grafana API
2. Commit changes to this directory
3. Push to version control
4. Create tags for major configuration milestones

## 🚨 Troubleshooting

### Common Issues

1. **Dashboard Not Loading**
   - Check datasource UIDs match in both dashboard and datasources.json
   - Verify datasource connections in Grafana UI

2. **Datasource Connection Errors**
   - Ensure K8s services are running: `kubectl get svc -n infrastructure`
   - Check service names match: `postgres.infrastructure.svc.cluster.local`

3. **Import Failures**
   - Verify JSON file integrity
   - Check for duplicate UIDs
   - Ensure admin credentials are correct

### Recovery from Backup
If Grafana deployment fails completely:
1. Deploy new Grafana instance
2. Restore datasources first
3. Import dashboards
4. Verify all connections and queries work

## 📝 Version Control

This directory should be committed to version control to track:
- Dashboard evolution
- Datasource configuration changes
- Configuration rollback capabilities

**Commit Message Format**:
```
feat: update Grafana backup - dashboard description
fix: correct datasource configuration in backup
docs: update restore instructions
```

---

**Note**: This backup contains sensitive infrastructure service endpoints. Ensure proper access controls when storing in shared repositories.