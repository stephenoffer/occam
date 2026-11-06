import re
from pathlib import Path

import click

from .nightly import run_nightly, run_partner


@click.group()
def cli():
    """meterhub batch jobs."""


@cli.command()
@click.option("--date", required=True, help="Label for this run, YYYY-MM-DD.")
@click.option("--data-dir", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def nightly(date, data_dir, archive):
    """Roll up one day's collector archive and push it."""
    run_nightly(archive, data_dir, date)
    click.echo("status=ok")


@cli.command()
@click.option("--partner", required=True)
@click.option("--period", required=True, type=click.Choice(["hour", "day", "month"]))
@click.option("--data-dir", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def backfill(partner, period, data_dir, archive):
    """Roll up a partner's export and push it."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", partner):
        raise click.BadParameter(f"not an account name: {partner!r}", param_hint="--partner")
    if archive.suffix != ".npz":
        raise click.BadParameter("partner archives are .npz", param_hint="ARCHIVE")
    run_partner(archive, data_dir, partner, period)
    click.echo("status=ok")


if __name__ == "__main__":
    cli()
