from math import sqrt
from typing import Any, Dict, List, Tuple


class DataProcessor:
    def __init__(self, analysis_cfg: Dict[str, Any]) -> None:
        self.cfg = analysis_cfg or {}
        self.min_mentions = int(self.cfg.get("min_mentions", 3))

    # - normalize_technology_names() - нормализация названий технологий
    def normalize_technology_names(self, names: List[str]) -> List[str]:
        mapping = {
            "js": "javascript",
            "nodejs": "node.js",
            "rb": "ruby",
            "py": "python",
            "ts": "typescript",
        }
        out: List[str] = []
        for n in names:
            key = (n or "").strip().lower()
            out.append(mapping.get(key, key))
        return out

    # - calculate_growth_rate() - расчет темпа роста
    def calculate_growth_rate(self, series: List[Tuple[str, float]]) -> float:
        """Calculate simple growth rate based on first and last values.
        series: list of (date_str, value)
        """
        if not series or len(series) < 2:
            return 0.0
        start = series[0][1]
        end = series[-1][1]
        if start == 0:
            return 0.0
        return (end - start) / abs(start)

    # - detect_anomalies() - обнаружение аномалий в данных
    def detect_anomalies(self, values: List[float], z_thresh: float = 3.0) -> List[int]:
        if not values:
            return []
        mean = sum(values) / len(values)
        var = sum((v - mean) ** 2 for v in values) / max(1, len(values) - 1)
        std = sqrt(var)
        if std == 0:
            return []
        anomalies = [i for i, v in enumerate(values) if abs(v - mean) / std >= z_thresh]
        return anomalies

    # - aggregate_multi_source() - объединение данных из разных источников
    def aggregate_multi_source(self, sources: List[Dict[str, Any]], weights: Dict[str, float] | None = None) -> Dict[str, Any]:
        agg_counts: Dict[str, float] = {}
        weights = weights or {}
        for src in sources:
            items = src.get("top_technologies", [])
            src_name = src.get("source", "unknown")
            w = float(weights.get(src_name, 1.0))
            for it in items:
                tech = (it.get("technology") or "").strip().lower()
                m = float(it.get("mentions", 0)) * w
                agg_counts[tech] = agg_counts.get(tech, 0.0) + m
        ranked = sorted(
            ({"technology": k, "mentions": v} for k, v in agg_counts.items()),
            key=lambda x: x["mentions"],
            reverse=True,
        )
        return {"top_technologies": ranked}

    # - apply_weights() - применение весов к разным источникам
    def apply_weights(self, data: Dict[str, Any], weights: Dict[str, float]) -> Dict[str, Any]:
        items = data.get("top_technologies", [])
        out = []
        for it in items:
            tech = it.get("technology")
            mentions = float(it.get("mentions", 0))
            w = float(weights.get(tech, 1.0))
            out.append({"technology": tech, "mentions": mentions * w})
        out.sort(key=lambda x: x["mentions"], reverse=True)
        return {"top_technologies": out}
