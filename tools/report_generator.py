import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
    import matplotlib.pyplot as plt  # type: ignore
except Exception:  # pragma: no cover
    plt = None  # type: ignore

try:
    from reportlab.lib.pagesizes import A4  # type: ignore
    from reportlab.pdfgen import canvas  # type: ignore
except Exception:
    A4 = None  # type: ignore
    canvas = None  # type: ignore

try:
    from openpyxl import Workbook  # type: ignore
except Exception:
    Workbook = None  # type: ignore


class ReportGenerator:
    def __init__(self, output_dir: str, templates_dir: str, logger) -> None:
        self.output_dir = Path(output_dir)
        self.templates_dir = Path(templates_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self.logger = logger

    async def create_visualizations(self, data: Dict[str, Any]) -> Dict[str, str]:
        charts: Dict[str, str] = {}
        try:
            if plt is None:
                self.logger.warning("matplotlib not available; skipping charts")
                return charts
            # Example chart: top technologies by mentions
            techs = data.get("top_technologies", [])
            if not techs:
                return charts
            names = [t.get("technology") for t in techs[:15]]
            values = [t.get("mentions", 0) for t in techs[:15]]
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.bar(names, values, color="#4C78A8")
            ax.set_title("Top technologies by mentions")
            ax.set_ylabel("Mentions")
            ax.set_xticklabels(names, rotation=45, ha="right")
            fig.tight_layout()
            out_path = self.output_dir / f"chart_top_mentions_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.png"
            fig.savefig(out_path, dpi=150)
            plt.close(fig)
            charts["top_mentions"] = str(out_path)
        except Exception as e:  # pragma: no cover
            self.logger.warning("Failed to create charts: %s", e)
        return charts

    async def generate_pdf(self, data: Dict[str, Any], charts: Optional[Dict[str, str]] = None) -> str:
        if canvas is None or A4 is None:
            self.logger.warning("reportlab not available; falling back to HTML")
            return await self.generate_html(data, charts)
        out_path = self.output_dir / f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        await asyncio.to_thread(self._write_pdf, data, charts or {}, out_path)
        return str(out_path)

    def _write_pdf(self, data: Dict[str, Any], charts: Dict[str, str], out_path: Path) -> None:
        c = canvas.Canvas(str(out_path), pagesize=A4)
        width, height = A4
        c.setTitle("IT Trends Report")
        c.setFont("Helvetica-Bold", 16)
        c.drawString(40, height - 40, "IT Trends Report")
        c.setFont("Helvetica", 10)
        c.drawString(40, height - 60, f"Generated: {datetime.utcnow().isoformat()}Z")

        y = height - 90
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, "Top Technologies:")
        y -= 20
        c.setFont("Helvetica", 10)
        for item in (data.get("top_technologies") or [])[:25]:
            line = f"- {item.get('technology')}: {item.get('mentions', 0)} mentions"
            c.drawString(50, y, line)
            y -= 14
            if y < 100:
                c.showPage()
                y = height - 40
        # embed chart if present
        if "top_mentions" in charts:
            try:
                c.showPage()
                c.drawImage(charts["top_mentions"], 40, 150, width=width - 80, preserveAspectRatio=True, mask='auto')
            except Exception:
                pass
        c.showPage()
        c.save()

    async def generate_excel(self, data: Dict[str, Any]) -> str:
        if Workbook is None:
            self.logger.warning("openpyxl not available; falling back to HTML")
            return await self.generate_html(data, charts=None)
        wb = Workbook()
        ws = wb.active
        ws.title = "Top Technologies"
        ws.append(["Technology", "Mentions"])
        for item in data.get("top_technologies", []):
            ws.append([item.get("technology"), item.get("mentions", 0)])
        out_path = self.output_dir / f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
        await asyncio.to_thread(wb.save, str(out_path))
        return str(out_path)

    async def generate_html(self, data: Dict[str, Any], charts: Optional[Dict[str, str]] = None) -> str:
        template = self.env.get_template("report_template.html")
        html = template.render(
            generated_at=datetime.utcnow().isoformat() + "Z",
            data=data,
            charts=charts or {},
            title="IT Trends Report",
        )
        out_path = self.output_dir / f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.html"
        await asyncio.to_thread(out_path.write_text, html, "utf-8")
        return str(out_path)
