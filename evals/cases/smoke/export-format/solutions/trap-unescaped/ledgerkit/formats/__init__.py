from .csv_format import export_csv
from .json_format import export_json
from .markdown_format import export_markdown

REGISTRY = {"csv": export_csv, "json": export_json, "markdown": export_markdown}
