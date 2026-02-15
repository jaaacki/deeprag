"""CLI for queue management.

Provides commands to inspect, retry, and clean up the processing queue.

Usage:
    python -m src status
    python -m src list --status pending
    python -m src retry 42
    python -m src retry-all
    python -m src cleanup --days 30
    python -m src reset 42
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg2
from dotenv import load_dotenv


def get_db_connection():
    """Create a database connection from environment variables."""
    load_dotenv()

    database_url = os.getenv('DATABASE_URL')
    if database_url:
        return psycopg2.connect(database_url)

    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=int(os.getenv('DB_PORT', '5432')),
        dbname=os.getenv('DB_NAME', 'emby_processor'),
        user=os.getenv('DB_USER', 'emby'),
        password=os.getenv('DB_PASSWORD', ''),
    )


def cmd_status(args):
    """Show queue statistics."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()

        # Count by status
        cur.execute("""
            SELECT status, COUNT(*)
            FROM processing_queue
            GROUP BY status
            ORDER BY status
        """)
        rows = cur.fetchall()

        total = sum(count for _, count in rows)
        print(f"Queue Status ({total} total)")
        print("=" * 40)

        if not rows:
            print("  (empty queue)")
            return

        for status, count in rows:
            print(f"  {status:<20} {count:>5}")

        print("-" * 40)
        print(f"  {'total':<20} {total:>5}")

        # Show oldest pending
        cur.execute("""
            SELECT created_at FROM processing_queue
            WHERE status = 'pending'
            ORDER BY created_at ASC LIMIT 1
        """)
        row = cur.fetchone()
        if row:
            age = datetime.now(timezone.utc) - row[0]
            print(f"\n  Oldest pending: {_format_age(age)} ago")

        # Show items ready for retry
        cur.execute("""
            SELECT COUNT(*) FROM processing_queue
            WHERE status = 'error'
            AND (next_retry_at IS NULL OR next_retry_at <= NOW())
        """)
        retryable = cur.fetchone()[0]
        if retryable > 0:
            print(f"  Retryable errors: {retryable}")

    finally:
        conn.close()


def cmd_list(args):
    """List queue items filtered by status."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()

        query = """
            SELECT id, file_path, movie_code, actress, status,
                   error_message, retry_count, created_at
            FROM processing_queue
        """
        params = []

        if args.status:
            query += " WHERE status = %s"
            params.append(args.status)

        query += " ORDER BY created_at DESC"

        if args.limit:
            query += " LIMIT %s"
            params.append(args.limit)

        cur.execute(query, params)
        rows = cur.fetchall()

        if not rows:
            status_filter = f" with status '{args.status}'" if args.status else ""
            print(f"No items found{status_filter}.")
            return

        print(f"{'ID':<6} {'Status':<14} {'Code':<12} {'Actress':<20} {'Retries':<8} {'File'}")
        print("-" * 90)

        for row in rows:
            item_id, file_path, movie_code, actress, status, error_msg, retry_count, created_at = row
            filename = os.path.basename(file_path) if file_path else ""
            # Truncate filename if too long
            if len(filename) > 40:
                filename = filename[:37] + "..."
            print(
                f"{item_id:<6} "
                f"{status:<14} "
                f"{(movie_code or '-'):<12} "
                f"{(actress or '-'):<20} "
                f"{retry_count:<8} "
                f"{filename}"
            )

            if args.verbose and error_msg:
                print(f"       Error: {error_msg}")

        print(f"\n{len(rows)} item(s) shown.")

    finally:
        conn.close()


def cmd_retry(args):
    """Retry a specific error item by resetting it to pending."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()

        # Check current status
        cur.execute(
            "SELECT id, file_path, status FROM processing_queue WHERE id = %s",
            (args.id,)
        )
        row = cur.fetchone()

        if not row:
            print(f"Error: Item {args.id} not found.")
            sys.exit(1)

        item_id, file_path, status = row

        if status != 'error':
            print(f"Error: Item {item_id} has status '{status}', not 'error'. Use 'reset' to force.")
            sys.exit(1)

        cur.execute(
            """UPDATE processing_queue
               SET status = 'pending', error_message = NULL, next_retry_at = NULL
               WHERE id = %s""",
            (item_id,)
        )
        conn.commit()
        print(f"Item {item_id} reset to 'pending' for retry.")
        print(f"  File: {file_path}")

    finally:
        conn.close()


def cmd_retry_all(args):
    """Retry all error items by resetting them to pending."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()

        cur.execute(
            """UPDATE processing_queue
               SET status = 'pending', error_message = NULL, next_retry_at = NULL
               WHERE status = 'error'
               RETURNING id"""
        )
        updated_ids = [row[0] for row in cur.fetchall()]
        conn.commit()

        count = len(updated_ids)
        if count == 0:
            print("No error items to retry.")
        else:
            print(f"{count} item(s) reset to 'pending' for retry.")

    finally:
        conn.close()


def cmd_cleanup(args):
    """Remove old completed items from the queue."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()

        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

        # Show what will be deleted
        cur.execute(
            """SELECT COUNT(*) FROM processing_queue
               WHERE status = 'completed' AND updated_at < %s""",
            (cutoff,)
        )
        count = cur.fetchone()[0]

        if count == 0:
            print(f"No completed items older than {args.days} days.")
            return

        if not args.yes:
            response = input(f"Delete {count} completed item(s) older than {args.days} days? [y/N] ")
            if response.lower() != 'y':
                print("Cancelled.")
                return

        cur.execute(
            """DELETE FROM processing_queue
               WHERE status = 'completed' AND updated_at < %s""",
            (cutoff,)
        )
        conn.commit()
        print(f"Deleted {count} completed item(s).")

    finally:
        conn.close()


def cmd_reset(args):
    """Reset an item to pending status regardless of current status."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT id, file_path, status FROM processing_queue WHERE id = %s",
            (args.id,)
        )
        row = cur.fetchone()

        if not row:
            print(f"Error: Item {args.id} not found.")
            sys.exit(1)

        item_id, file_path, current_status = row

        if current_status == 'pending':
            print(f"Item {item_id} is already 'pending'.")
            return

        cur.execute(
            """UPDATE processing_queue
               SET status = 'pending', error_message = NULL,
                   retry_count = 0, next_retry_at = NULL
               WHERE id = %s""",
            (item_id,)
        )
        conn.commit()
        print(f"Item {item_id} reset from '{current_status}' to 'pending'.")
        print(f"  File: {file_path}")

    finally:
        conn.close()


def _format_age(delta: timedelta) -> str:
    """Format a timedelta as a human-readable age string."""
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h {minutes % 60}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the queue CLI."""
    parser = argparse.ArgumentParser(
        prog='python -m src',
        description='Emby Processor Queue Management CLI',
        epilog=(
            'Examples:\n'
            '  python -m src status                  Show queue statistics\n'
            '  python -m src list                    List all items\n'
            '  python -m src list --status error     List error items\n'
            '  python -m src list --status error -v  List errors with messages\n'
            '  python -m src retry 42                Retry failed item #42\n'
            '  python -m src retry-all               Retry all failed items\n'
            '  python -m src cleanup --days 30       Remove completed items older than 30 days\n'
            '  python -m src reset 42                Force-reset item #42 to pending\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(
        dest='command',
        title='commands',
        description='Available queue management commands',
    )

    # status
    subparsers.add_parser(
        'status',
        help='Show queue statistics (counts by status, oldest pending, retryable errors)',
    )

    # list
    list_parser = subparsers.add_parser(
        'list',
        help='List queue items, optionally filtered by status',
    )
    list_parser.add_argument(
        '--status', '-s',
        choices=['pending', 'processing', 'moved', 'emby_pending', 'completed', 'error'],
        help='Filter items by status',
    )
    list_parser.add_argument(
        '--limit', '-n',
        type=int,
        default=None,
        help='Maximum number of items to show',
    )
    list_parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show error messages for failed items',
    )

    # retry
    retry_parser = subparsers.add_parser(
        'retry',
        help='Retry a specific failed item (must have status "error")',
    )
    retry_parser.add_argument(
        'id',
        type=int,
        help='ID of the item to retry',
    )

    # retry-all
    subparsers.add_parser(
        'retry-all',
        help='Retry all failed items (resets all "error" items to "pending")',
    )

    # cleanup
    cleanup_parser = subparsers.add_parser(
        'cleanup',
        help='Remove old completed items from the queue',
    )
    cleanup_parser.add_argument(
        '--days', '-d',
        type=int,
        required=True,
        help='Remove completed items older than this many days',
    )
    cleanup_parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Skip confirmation prompt',
    )

    # reset
    reset_parser = subparsers.add_parser(
        'reset',
        help='Force-reset an item to pending (works on any status)',
    )
    reset_parser.add_argument(
        'id',
        type=int,
        help='ID of the item to reset',
    )

    return parser


def main(argv=None):
    """Main entry point for the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        'status': cmd_status,
        'list': cmd_list,
        'retry': cmd_retry,
        'retry-all': cmd_retry_all,
        'cleanup': cmd_cleanup,
        'reset': cmd_reset,
    }

    try:
        commands[args.command](args)
    except psycopg2.OperationalError as e:
        print(f"Database connection error: {e}", file=sys.stderr)
        print("Check DATABASE_URL or DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD environment variables.",
              file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
