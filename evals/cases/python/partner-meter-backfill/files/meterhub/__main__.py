from pathlib import Path

import click

from .nightly import run_nightly


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


if __name__ == "__main__":
    cli()
