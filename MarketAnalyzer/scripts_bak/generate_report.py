#!/usr/bin/env python3
"""CLI entry point for PDF report generation — zero AI dependency.

Usage:
  python scripts/generate_report.py HPQ
  python scripts/generate_report.py HPQ --strategy "Synthetic Long 2:1" --strikes 27 30 --premiums 2.65 1.29 --sides "sell put" "buy call" --expiry 2026-12-18
  python scripts/generate_report.py HPQ --output reports/
  python scripts/generate_report.py --help
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from agents.report_agent import ReportAgent


def main():
    parser = argparse.ArgumentParser(description='Generate MarketAnalyzer PDF report for any ticker')
    parser.add_argument('ticker', help='Stock ticker symbol (e.g. HPQ, AAPL, IGV)')
    parser.add_argument('--output', '-o', default='reports', help='Output directory for PDF')
    parser.add_argument('--strategy', '-s', help='Strategy name (optional, for strategy report)')
    parser.add_argument('--strikes', '-k', nargs='+', type=float, help='Option strikes for strategy')
    parser.add_argument('--premiums', '-p', nargs='+', type=float, help='Option premiums for strategy')
    parser.add_argument('--sides', nargs='+', help='Option sides (buy call, sell put, etc.)')
    parser.add_argument('--expiry', '-e', help='Option expiry date (YYYY-MM-DD)')
    args = parser.parse_args()

    agent = ReportAgent()

    try:
        if args.strategy and args.strikes and args.premiums and args.sides:
            path = agent.generate_strategy_report(
                args.ticker, args.strategy, args.strikes,
                args.premiums, args.sides, args.expiry or 'N/A',
                output_dir=args.output,
            )
            report_type = 'strategy'
        else:
            path = agent.generate_verdict_report(args.ticker, output_dir=args.output)
            report_type = 'verdict'

        print(f'✅ {report_type.upper()} report generated: {path}')
    except (ValueError, IOError, ImportError) as e:
        print(f'❌ Error: {e}', file=sys.stderr)
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
