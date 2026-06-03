from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any
from jinja2 import Environment, FileSystemLoader, select_autoescape
from .config import settings

try:
    from weasyprint import HTML
    HAS_WEASYPRINT = True
except (ImportError, OSError):
    HAS_WEASYPRINT = False

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html", "xml"]))


def slugify(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|\s]+", "_", value or "report")
    return value[:60]


def ensure_report_dir() -> None:
    os.makedirs(settings.report_storage_path, exist_ok=True)


def render_pdf(report_type: str, store_info: dict[str, Any], score_payload: dict[str, Any], ai_content: dict[str, Any]) -> str:
    ensure_report_dir()
    template_name = "diagnosis_report.html" if report_type == "diagnosis" else "monthly_report.html"
    template = env.get_template(template_name)
    html_str = template.render(
        report_type=report_type,
        store=store_info,
        score=score_payload,
        ai=ai_content,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    store_slug = slugify(store_info.get('store_name', '门店'))
    ts = datetime.now().strftime('%Y%m%d%H%M%S')

    if HAS_WEASYPRINT:
        filename = f"{report_type}_{store_slug}_{ts}.pdf"
        output_path = os.path.join(settings.report_storage_path, filename)
        HTML(string=html_str, base_url=TEMPLATE_DIR).write_pdf(output_path)
    else:
        filename = f"{report_type}_{store_slug}_{ts}.html"
        output_path = os.path.join(settings.report_storage_path, filename)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_str)

    return f"{settings.public_base_url.rstrip('/')}/reports/{filename}"
