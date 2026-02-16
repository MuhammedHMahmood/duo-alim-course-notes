"""Shared utilities for the DUO Class Notes pipeline."""

import os
import argparse
import yaml
import keyring
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
SUBJECTS_DIR = PROJECT_ROOT / "subjects"
DOCS_DIR = PROJECT_ROOT / "docs"

VALID_SUBJECTS = ["tfs", "hadith", "nahw", "sarf"]


def load_config():
    """Load classes.yaml configuration."""
    config_path = CONFIG_DIR / "classes.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_active_classes():
    """Return list of class configs where active=true."""
    config = load_config()
    return [c for c in config["classes"] if c.get("active", False)]


def get_class_config(subject, course):
    """Return config for a specific subject/course."""
    config = load_config()
    for c in config["classes"]:
        if c["subject"] == subject and c["course"] == str(course):
            return c
    return None


def course_dir(subject, course, subfolder=None):
    """Return path to subjects/{subject}/{course}/{subfolder}/, creating if needed."""
    path = SUBJECTS_DIR / subject / str(course)
    if subfolder:
        path = path / subfolder
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_template(subject):
    """Load the note generation template for a subject."""
    template_path = CONFIG_DIR / "templates" / f"{subject}.md"
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"No template found for subject: {subject}")


def get_settings():
    """Return pipeline settings from config."""
    config = load_config()
    return config.get("settings", {})


def make_parser(description):
    """Create an argument parser with common --subject/--course arguments."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--subject", choices=VALID_SUBJECTS,
        help="Subject to process (tfs, hadith, nahw, sarf)"
    )
    parser.add_argument(
        "--course",
        help="Course number (e.g., 101, 102)"
    )
    parser.add_argument(
        "--active-only", action="store_true",
        help="Process only active classes (for cron use)"
    )
    return parser


def resolve_classes(args):
    """Given parsed args, return list of (subject, course, config) tuples to process."""
    if args.active_only:
        classes = get_active_classes()
        return [(c["subject"], c["course"], c) for c in classes]
    elif args.subject and args.course:
        config = get_class_config(args.subject, args.course)
        return [(args.subject, args.course, config)]
    else:
        raise ValueError("Provide either --subject and --course, or --active-only")


SERVICE_NAME = "duo-class-notes"


def get_api_key(key_name):
    """Retrieve an API key from Windows Credential Manager."""
    value = keyring.get_password(SERVICE_NAME, key_name)
    if not value:
        raise RuntimeError(
            f"No credential found for '{key_name}' in Windows Credential Manager.\n"
            f"Store it with: python -c \"import keyring; keyring.set_password('{SERVICE_NAME}', '{key_name}', 'your-key-here')\""
        )
    return value
