"""Optional YAML settings with explicit CLI overrides and portable YAML snapshots."""

import argparse
import json
from pathlib import Path


def read_config(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise ValueError("YAML config requires PyYAML: pip install -r requirements.txt") from exc
        try:
            value = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Config must be a mapping")
    return value


def parse_config_args(parser, argv=None):
    """Validate settings with argparse converters; explicit flags take precedence."""
    probe = argparse.ArgumentParser(add_help=False)
    probe.add_argument("--config", type=Path)
    known, _ = probe.parse_known_args(argv)
    if not any(a.dest == "config" for a in parser._actions):
        parser.add_argument("--config", type=Path, help="YAML config; explicit CLI flags override it")
    if known.config:
        try:
            settings = read_config(known.config)
            actions = {a.dest: a for a in parser._actions}
            unknown = set(settings) - (set(actions) - {"help", "config"})
            if unknown:
                raise ValueError(f"Unknown config keys: {sorted(unknown)}")
            for key, value in settings.items():
                action = actions[key]
                if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
                    if type(value) is not bool:
                        raise ValueError(f"{key} must be boolean")
                elif value is not None:
                    many = action.nargs in ("+", "*")
                    if many and not isinstance(value, list):
                        raise ValueError(f"{key} must be a list")
                    values = value if many else [value]
                    if any(isinstance(v, bool) for v in values):
                        raise ValueError(f"{key} must not be boolean")
                    converted = [(action.type(v) if action.type else v) for v in values]
                    if action.choices and any(v not in action.choices for v in converted):
                        raise ValueError(f"Invalid choice for {key}")
                    value = converted if many else converted[0]
                parser.set_defaults(**{key: value})
                if value is not None:
                    action.required = False
        except (ValueError, OSError, TypeError, argparse.ArgumentTypeError) as exc:
            parser.error(str(exc))
    args = parser.parse_args(argv)
    for group in parser._mutually_exclusive_groups:
        active = [a.dest for a in group._group_actions
                  if getattr(args, a.dest) is not None and getattr(args, a.dest) is not False]
        if len(active) > 1:
            parser.error(f"Mutually exclusive settings: {', '.join(active)}")
    return args


def snapshot(path, settings):
    """JSON is valid YAML 1.2 and needs no additional package to write/read."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
