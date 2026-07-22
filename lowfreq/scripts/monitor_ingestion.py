#!/usr/bin/env python3
"""
data_ingestion progress monitoring tool
Displays data ingestion progress and statistics in real time
"""
import psycopg2
import time
import sys
from datetime import datetime

def get_progress_stats():
    """Get progress statistics"""
    try:
        conn = psycopg2.connect(
            host='localhost',
            port=5432,
            database='dev',
            user='dev_user',
            password='dev_pass'
        )
        cursor = conn.cursor()

        # Get progress statistics
        cursor.execute('''
            SELECT status, COUNT(*) as count
            FROM ingestion_progress
            GROUP BY status
            ORDER BY status
        ''')
        progress_stats = dict(cursor.fetchall())

        # Get completed stock count
        cursor.execute('SELECT COUNT(*) FROM kline_min_metadata')
        completed_count = cursor.fetchone()[0]

        # Get most recent processing time
        cursor.execute('''
            SELECT MAX(updated_at) FROM ingestion_progress
            WHERE status = 'completed'
        ''')
        last_update = cursor.fetchone()[0]

        cursor.close()
        conn.close()

        return {
            'progress_stats': progress_stats,
            'completed_count': completed_count,
            'last_update': last_update
        }
    except Exception as e:
        print(f"Error: {e}")
        return None

def display_progress():
    """Display progress information"""
    stats = get_progress_stats()
    if not stats:
        print("Unable to get progress information")
        return

    print("\n" + "="*60)
    print(f"Monitor time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    # Show overall progress
    completed = stats['progress_stats'].get('completed', 0)
    processing = stats['progress_stats'].get('processing', 0)
    pending = stats['progress_stats'].get('pending', 0)
    error = stats['progress_stats'].get('error', 0)

    print(f"\nOverall progress:")
    print(f"  Completed: {stats['completed_count']} stocks")
    print(f"  Processing: {processing}")
    print(f"  Pending: {pending}")
    print(f"  Errors: {error}")

    # Show progress percentage
    total = completed + processing + pending + error
    if total > 0:
        percent = (completed * 100.0) / total
        print(f"  Completion rate: {percent:.1f}%")

    # Show last update time
    if stats['last_update']:
        print(f"\nLast update: {stats['last_update']}")
    else:
        print(f"\nLast update: None")

    # Show data file statistics
    try:
        conn = psycopg2.connect(
            host='localhost',
            port=5432,
            database='dev',
            user='dev_user',
            password='dev_pass'
        )
        cursor = conn.cursor()

        # Get total data volume
        cursor.execute('SELECT SUM(row_count) FROM kline_min_metadata')
        total_bars = cursor.fetchone()[0] or 0

        print(f"\nData statistics:")
        print(f"  Total K-line data: {total_bars:,} records")

        # Calculate data size
        cursor.execute('''
            SELECT SUM(file_size) FROM kline_min_metadata
            WHERE file_size IS NOT NULL
        ''')
        total_size = cursor.fetchone()[0] or 0
        size_mb = total_size / (1024 * 1024)
        print(f"  Total file size: {size_mb:.1f} MB")

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"\nData statistics error: {e}")

    print("="*60)

def main():
    """Main function"""
    print("data_ingestion Progress Monitor")
    print("Press Ctrl+C to exit\n")

    try:
        if len(sys.argv) > 1 and sys.argv[1] == '--once':
            # Single display mode
            display_progress()
        else:
            # Continuous monitoring mode
            while True:
                display_progress()
                time.sleep(10)  # Refresh every 10 seconds
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped")

if __name__ == "__main__":
    main()
