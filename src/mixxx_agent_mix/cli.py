import argparse
import json
import sys

from .api import analyze, mix, plan


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mixxx-aware offline 2 MP3 -> 1 MP3")
    commands = parser.add_subparsers(dest="command", required=True)
    analysis = commands.add_parser("analyze", help="Print one track's features as JSON")
    analysis.add_argument("track")
    analysis.add_argument("--mixxx-db")
    analysis.add_argument("--features")
    for name in ("plan", "mix"):
        command = commands.add_parser(name)
        command.add_argument("track_a")
        command.add_argument("track_b")
        command.add_argument("--mixxx-db")
        command.add_argument("--features-a")
        command.add_argument("--features-b")
        command.add_argument("--bars", type=int, choices=(4, 8, 16, 32), default=8)
        command.add_argument("--max-rate-change", type=float, default=0.08)
        command.add_argument("--strict", action="store_true")
        if name == "mix":
            command.add_argument("-o", "--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "analyze":
            result = analyze(args.track, mixxx_db=args.mixxx_db, features=args.features)
        else:
            settings = {"bars": args.bars, "strict": args.strict,
                        "max_rate_change": args.max_rate_change}
            if args.command == "mix":
                result = mix(args.track_a, args.track_b, args.output, mixxx_db=args.mixxx_db,
                             features_a=args.features_a, features_b=args.features_b, **settings)
                result = {k: result[k] for k in ("output", "report", "plan", "validation")}
            else:
                a = analyze(args.track_a, mixxx_db=args.mixxx_db, features=args.features_a)
                b = analyze(args.track_b, mixxx_db=args.mixxx_db, features=args.features_b)
                result = plan(a, b, **settings)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
