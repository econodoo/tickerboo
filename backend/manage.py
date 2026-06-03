#!/usr/bin/env python3
"""
TickerBoo CLI — manage the server from the command line.

Usage:
  python manage.py serve                    # start the server
  python manage.py seed                     # load mock data
  python manage.py sync                     # sync from CafeF
  python manage.py stats                    # show DB stats
  python manage.py functions                # list all functions
  python manage.py test                     # run regression test
  python manage.py call PRICE ticker=VNM    # call a function
"""
import sys
import os
import asyncio
import argparse

# Ensure backend is in path
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("TICKERBOO_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "tickerboo.db"))
os.environ.setdefault("TICKERBOO_LOG_PATH", os.path.join(os.path.dirname(__file__), "..", "logs", "tickerboo.log"))


def cmd_serve(args):
    """Start the TickerBoo server."""
    import uvicorn
    print(f"🫣 Starting TickerBoo on port {args.port}...")
    uvicorn.run(
        "tickerboo.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


def cmd_seed(args):
    """Load mock data (15 tickers × 500 days)."""
    async def _seed():
        from tickerboo.db.session import init_db, close_db
        from tickerboo.sources.seeder import MockSeeder
        await init_db()
        seeder = MockSeeder()
        result = await seeder.seed()
        print(f"✓ Seeded {result['tickers']} tickers, {result['records']} bars")
        await close_db()
    asyncio.run(_seed())


def cmd_sync(args):
    """Sync real data from CafeF."""
    async def _sync():
        from tickerboo.db.session import init_db, close_db
        from tickerboo.sources.cafef import CafeF
        await init_db()
        cafef = CafeF()
        result = await cafef.sync_full()
        print(f"✓ Synced: {result}")
        await close_db()
    asyncio.run(_sync())


def cmd_stats(args):
    """Show database statistics."""
    async def _stats():
        from tickerboo.db.session import init_db, close_db, fetch_one, fetch_all
        await init_db()

        overview = await fetch_one(
            "SELECT COUNT(DISTINCT symbol) as tickers, COUNT(*) as bars, "
            "MIN(date) as earliest, MAX(date) as latest FROM daily_ohlcv"
        )
        print("─── Database Stats ───")
        if overview:
            print(f"  Tickers:  {overview['tickers']}")
            print(f"  Bars:     {overview['bars']:,}")
            print(f"  Range:    {overview['earliest']} → {overview['latest']}")

        # Top tickers
        top = await fetch_all(
            "SELECT symbol, total_bars, last_date FROM stocks ORDER BY total_bars DESC LIMIT 10"
        )
        if top:
            print("\n  Top tickers:")
            for r in top:
                print(f"    {r['symbol']:6s}  {r['total_bars']:5d} bars  → {r['last_date']}")

        # Analytics
        calls = await fetch_one("SELECT COUNT(*) as n FROM function_calls")
        if calls and calls['n'] > 0:
            print(f"\n  API calls: {calls['n']:,}")

        await close_db()
    asyncio.run(_stats())


def cmd_functions(args):
    """List all registered functions."""
    from tickerboo.functions.registry import registry
    registry.discover()

    fns = registry.list_all()
    by_cat = {}
    for f in fns:
        by_cat.setdefault(f['category'], []).append(f)

    print(f"─── {len(fns)} Functions ───\n")
    for cat in sorted(by_cat.keys()):
        cfns = by_cat[cat]
        print(f"  {cat} ({len(cfns)}):")
        for fn in cfns:
            req = [p['name'] for p in fn['params'] if p.get('required')]
            opt = [p['name'] for p in fn['params'] if not p.get('required')]
            sig = ", ".join(req + [f"[{o}]" for o in opt])
            print(f"    TB.{fn['name']:20s}  ({sig})")
        print()


def cmd_test(args):
    """Run regression test on all functions."""
    async def _test():
        import time
        from tickerboo.db.session import init_db, close_db
        from tickerboo.functions.registry import registry
        from tickerboo.functions.context import ComputeContext

        await init_db()
        registry.discover()
        ctx = ComputeContext(registry=registry)

        fns = registry.list_all()
        ok = fail = 0
        t0 = time.perf_counter()

        for fn in fns:
            args_dict = {}
            for p in fn['params']:
                if p.get('required'):
                    if p['name'] == 'ticker':
                        args_dict['ticker'] = 'VNM'
                    elif p['name'] == 'expr':
                        args_dict['expr'] = 'RSI<50'
                    elif p['name'] == 'tickers':
                        args_dict['tickers'] = 'VNM,FPT'
                    elif p['name'] == 'period':
                        args_dict['period'] = 14
                    elif p['type'] in ('number', 'integer'):
                        args_dict[p['name']] = p.get('default', 14)
                    else:
                        args_dict[p['name']] = p.get('default', '')

            try:
                result = await registry.call(fn['name'], args_dict, ctx=ctx)
                if result.get('status') == 'ok':
                    ok += 1
                else:
                    fail += 1
                    print(f"  ✗ TB.{fn['name']}: {result.get('message','?')[:60]}")
            except Exception as e:
                fail += 1
                print(f"  ✗ TB.{fn['name']}: {e}")

        elapsed = time.perf_counter() - t0
        print(f"\n{ok} ✓  {fail} ✗  ({elapsed:.1f}s, {elapsed/len(fns)*1000:.0f}ms avg)")
        await close_db()

    asyncio.run(_test())


def cmd_call(args):
    """Call a single function."""
    async def _call():
        from tickerboo.db.session import init_db, close_db
        from tickerboo.functions.registry import registry
        from tickerboo.functions.context import ComputeContext

        await init_db()
        registry.discover()
        ctx = ComputeContext(registry=registry)

        # Parse key=value pairs
        params = {}
        for kv in args.params:
            if '=' in kv:
                k, v = kv.split('=', 1)
                try:
                    v = float(v) if '.' in v else int(v)
                except ValueError:
                    pass
                params[k] = v

        result = await registry.call(args.function.upper(), params, ctx=ctx)
        if result.get('status') == 'ok':
            v = result['value']
            if isinstance(v, list) and v and isinstance(v[0], list):
                for row in v:
                    print('\t'.join(str(c) for c in row))
            elif isinstance(v, list):
                print('\t'.join(str(c) for c in v))
            else:
                print(v)
        else:
            print(f"Error: {result.get('message','?')}", file=sys.stderr)

        await close_db()
    asyncio.run(_call())


def main():
    parser = argparse.ArgumentParser(
        description="🫣 TickerBoo CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # serve
    p = sub.add_parser("serve", help="Start the server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8688)
    p.add_argument("--reload", action="store_true")

    # seed
    sub.add_parser("seed", help="Load mock data")

    # sync
    sub.add_parser("sync", help="Sync from CafeF")

    # stats
    sub.add_parser("stats", help="Show DB stats")

    # functions
    sub.add_parser("functions", help="List all functions")

    # test
    sub.add_parser("test", help="Regression test")

    # call
    p = sub.add_parser("call", help="Call a function: call PRICE ticker=VNM")
    p.add_argument("function", help="Function name (e.g., PRICE, RSI)")
    p.add_argument("params", nargs="*", help="key=value pairs")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    handlers = {
        "serve": cmd_serve,
        "seed": cmd_seed,
        "sync": cmd_sync,
        "stats": cmd_stats,
        "functions": cmd_functions,
        "test": cmd_test,
        "call": cmd_call,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
