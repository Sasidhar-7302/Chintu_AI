"""
DashboardGenerator: Creates interactive HTML reports for research data.
Now supports UNIVERSAL data types (Stocks, Products, General Research).
"""

import logging
import os
import json
import webbrowser
from typing import List, Dict, Any, Union

logger = logging.getLogger(__name__)

class DashboardGenerator:
    """Generates HTML dashboards for any data type."""
    
    def __init__(self):
        self.output_dir = os.path.join(os.getcwd(), "generated_reports")
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_universal_report(self, title: str, summary: str, data_blocks: List[Dict[str, Any]]) -> str:
        """
        Create a generic dashboard for ANY topic.
        
        Args:
            title: Report Title (e.g. "Stock Analysis: AAPL")
            summary: Brief text summary.
            data_blocks: List of data items to render. Each dict must have 'type' and 'content'.
                - type='table': content=List[Dict] (Rendered as sortable table)
                - type='cards': content=List[Dict] (Rendered as grid cards)
                - type='chart': content={labels:[], datasets:[{label, data}]} (Rendered via Chart.js)
                - type='metrics': content=List[{label, value}] (Rendered as big stats)
        """
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Chintu Report</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
    <style>body {{ font-family: 'Inter', sans-serif; }}</style>
</head>
<body class="bg-slate-900 text-white min-h-screen p-8">
    <div class="max-w-7xl mx-auto space-y-8">
        <!-- Header -->
        <header class="flex justify-between items-center bg-slate-800 p-6 rounded-2xl shadow-lg border border-slate-700">
            <div>
                <h1 class="text-4xl font-extrabold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-teal-400">{title}</h1>
                <p class="text-slate-400 mt-2 text-lg">{summary}</p>
            </div>
            <div class="space-x-4">
                <button onclick="window.print()" class="bg-slate-700 hover:bg-slate-600 px-4 py-2 rounded-lg font-semibold transition">🖨️ PDF</button>
            </div>
        </header>

        <!-- Dynamic Content Blocks -->
        {self._render_blocks(data_blocks)}
        
    </div>
</body>
</html>
        """
        prefix = title.lower().replace(" ", "_")[:20]
        return self._save_and_open(html, prefix)

    def _render_blocks(self, blocks: List[Dict]) -> str:
        html = ""
        for i, block in enumerate(blocks):
            b_type = block.get("type", "text")
            b_title = block.get("title", "")
            content = block.get("content")
            
            section_html = f'<section class="bg-slate-800 p-6 rounded-2xl shadow-md border border-slate-700"><h2 class="text-2xl font-bold mb-6 text-white border-b border-slate-600 pb-2">{b_title}</h2>'
            
            if b_type == 'metrics':
                section_html += self._render_metrics(content)
            elif b_type == 'table':
                section_html += self._render_table(content)
            elif b_type == 'cards':
                section_html += self._render_generic_cards(content)
            elif b_type == 'chart':
                chart_id = f"chart_{i}"
                section_html += self._render_chart(chart_id, content)
            
            section_html += '</section>'
            html += section_html
        return html

    def _render_metrics(self, metrics: List[Dict]) -> str:
        html = '<div class="grid grid-cols-2 md:grid-cols-4 gap-4">'
        for m in metrics:
            html += f"""
            <div class="bg-slate-700 p-4 rounded-xl text-center">
                <p class="text-slate-400 text-sm uppercase tracking-wider">{m.get('label')}</p>
                <p class="text-3xl font-bold text-white mt-1">{m.get('value')}</p>
            </div>
            """
        html += '</div>'
        return html

    def _render_table(self, data: List[Dict]) -> str:
        if not data: return "<p>No data available.</p>"
        headers = list(data[0].keys())
        
        html = '<div class="overflow-x-auto"><table class="w-full text-left border-collapse">'
        
        # Headers
        html += '<thead class="bg-slate-700 text-slate-300"><tr>'
        for h in headers:
            html += f'<th class="p-3 font-semibold capitalize">{h.replace("_", " ")}</th>'
        html += '</tr></thead>'
        
        # Rows
        html += '<tbody class="divide-y divide-slate-700">'
        for row in data:
            html += '<tr class="hover:bg-slate-700/50 transition">'
            for h in headers:
                val = row.get(h, "-")
                html += f'<td class="p-3 text-slate-300">{val}</td>'
            html += '</tr>'
        html += '</tbody></table></div>'
        return html

    def _render_generic_cards(self, items: List[Dict]) -> str:
        html = '<div class="grid grid-cols-1 md:grid-cols-3 gap-6">'
        for item in items:
            title = item.get("name") or item.get("title") or "Item"
            sub = item.get("description") or item.get("desc") or ""
            features = [v for k,v in item.items() if k not in ['name', 'title', 'description', 'desc', 'image']]
            
            html += f"""
            <div class="bg-slate-700 rounded-xl p-5 hover:bg-slate-600 transition shadow-lg border border-slate-600">
                <h3 class="text-xl font-bold text-white mb-2">{title}</h3>
                <p class="text-slate-400 text-sm mb-4">{sub}</p>
                <div class="space-y-1 text-sm text-slate-300">
            """
            for i, feat in enumerate(features[:4]): # Limit to 4 lines
                html += f'<div class="flex justify-between items-center"><span class="text-slate-500">•</span> <span>{feat}</span></div>'
            html += '</div></div>'
        html += '</div>'
        return html

    def _render_chart(self, chart_id: str, data: Dict) -> str:
        # data = { type: 'line', labels: [], datasets: [] }
        labels = json.dumps(data.get('labels', []))
        datasets = json.dumps(data.get('datasets', []))
        chart_type = data.get('type', 'line')
        
        return f"""
        <div class="relative h-72 w-full">
            <canvas id="{chart_id}"></canvas>
        </div>
        <script>
            new Chart(document.getElementById('{chart_id}'), {{
                type: '{chart_type}',
                data: {{
                    labels: {labels},
                    datasets: {datasets}
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{ legend: {{ labels: {{ color: 'white' }} }} }},
                    scales: {{
                        y: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }},
                        x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }}
                    }}
                }}
            }});
        </script>
        """

    def _save_and_open(self, html_content: str, prefix: str) -> str:
        filename = f"{prefix}_{int(os.times().elapsed)}.html"
        path = os.path.join(self.output_dir, filename)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_content)
            
        url = f"file://{path}"
        webbrowser.open(url)
        logger.info(f"Generated Dashboard: {path}")
        return path

# Global
_generator = None

def get_dashboard_generator() -> DashboardGenerator:
    global _generator
    if not _generator:
        _generator = DashboardGenerator()
    return _generator
