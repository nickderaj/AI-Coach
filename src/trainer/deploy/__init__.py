"""Deployment support: validated host configuration, systemd units and backups.

Everything host-specific arrives through ``deploy/local.env`` (git-ignored) and is
validated here once, so the root-run shell scripts only ever see checked values.
"""
