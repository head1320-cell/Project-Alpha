"""
KIS Strategy YAML I/O
======================
.kis.yaml 파일 로드/저장/검증.

원본:
  backtester/kis_backtest/file/loader.py  → StrategyFileLoader
  backtester/kis_backtest/file/saver.py   → StrategyFileSaver

변경:
  - kis_backtest.* → src.* import 경로
  - StrategyFileLoader.load_schema_* 는 우리 converters 사용
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

if TYPE_CHECKING:
    from src.kis_schema import StrategySchema

import yaml

from src.kis_yaml_schema import (
    ConditionConfig,
    ConditionGroupConfig,
    IndicatorConfig,
    KisStrategyFile,
    RiskConfig,
    StrategyConfig,
    StrategyMetadata,
)

logger = logging.getLogger(__name__)

PRICE_FIELDS = frozenset({"close", "open", "high", "low", "volume", "price"})


# ═══════════════════════════════════════════════════════════════════════════════
# StrategyFileLoader — 원본 그대로
# ═══════════════════════════════════════════════════════════════════════════════

class StrategyFileLoader:
    """전략 파일 로더"""

    @staticmethod
    def load(path: Union[str, Path]) -> KisStrategyFile:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Strategy file not found: {path}")
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML format: {e}")
        if not data:
            raise ValueError(f"Empty strategy file: {path}")
        try:
            return KisStrategyFile.model_validate(data)
        except Exception as e:
            raise ValueError(f"Invalid strategy file format: {e}")

    @staticmethod
    def load_from_string(content: str) -> KisStrategyFile:
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML format: {e}")
        if not data:
            raise ValueError("Empty strategy content")
        try:
            return KisStrategyFile.model_validate(data)
        except Exception as e:
            raise ValueError(f"Invalid strategy format: {e}")

    @staticmethod
    def load_as_schema(path: Union[str, Path]) -> StrategySchema:
        from src.kis_converters import from_yaml_file
        return from_yaml_file(StrategyFileLoader.load(path))

    @staticmethod
    def load_schema_from_string(content: str) -> StrategySchema:
        from src.kis_converters import from_yaml_file
        return from_yaml_file(StrategyFileLoader.load_from_string(content))

    @staticmethod
    def load_schema_with_params(
        path_or_content: Union[str, Path],
        param_overrides: dict[str, Any] | None = None,
    ) -> StrategySchema:
        from src.kis_converters import from_yaml_file
        if isinstance(path_or_content, Path):
            sf = StrategyFileLoader.load(path_or_content)
        elif isinstance(path_or_content, str):
            if path_or_content.strip().startswith("version"):
                sf = StrategyFileLoader.load_from_string(path_or_content)
            else:
                p = Path(path_or_content)
                try:
                    exists = p.exists()
                except OSError:
                    exists = False
                sf = StrategyFileLoader.load(p) if exists \
                    else StrategyFileLoader.load_from_string(path_or_content)
        else:
            raise ValueError(f"Invalid type: {type(path_or_content)}")
        return from_yaml_file(sf, param_overrides=param_overrides)

    @staticmethod
    def _validate_strategy_file(sf: KisStrategyFile) -> list[str]:
        errors: list[str] = []
        if not sf.strategy.indicators:
            errors.append("No indicators defined")
        if not sf.strategy.entry.conditions:
            errors.append("No entry conditions defined")
        if not sf.strategy.exit.conditions:
            errors.append("No exit conditions defined")

        indicator_aliases = {ind.alias or ind.id for ind in sf.strategy.indicators}
        valid_aliases = indicator_aliases | PRICE_FIELDS

        for cond in sf.strategy.entry.conditions:
            if cond.indicator and cond.indicator not in valid_aliases:
                errors.append(f"Unknown indicator alias in entry: {cond.indicator}")
            if isinstance(cond.compare_to, str) and cond.compare_to not in valid_aliases:
                errors.append(f"Unknown compare_to alias in entry: {cond.compare_to}")
        for cond in sf.strategy.exit.conditions:
            if cond.indicator and cond.indicator not in valid_aliases:
                errors.append(f"Unknown indicator alias in exit: {cond.indicator}")
            if isinstance(cond.compare_to, str) and cond.compare_to not in valid_aliases:
                errors.append(f"Unknown compare_to alias in exit: {cond.compare_to}")
        return errors

    @staticmethod
    def validate(path: Union[str, Path]) -> list[str]:
        try:
            sf = StrategyFileLoader.load(path)
        except (FileNotFoundError, ValueError) as e:
            return [str(e)]
        return StrategyFileLoader._validate_strategy_file(sf)

    @staticmethod
    def validate_content(content: str) -> list[str]:
        try:
            sf = StrategyFileLoader.load_from_string(content)
        except ValueError as e:
            return [str(e)]
        return StrategyFileLoader._validate_strategy_file(sf)


# ═══════════════════════════════════════════════════════════════════════════════
# StrategyFileSaver — 원본 그대로
# ═══════════════════════════════════════════════════════════════════════════════

class StrategyFileSaver:
    """전략 파일 저장기"""

    @staticmethod
    def to_yaml_string(schema_or_file, indent: int = 2) -> str:
        """StrategySchema 또는 KisStrategyFile → YAML 문자열."""
        from src.kis_schema import StrategySchema

        if isinstance(schema_or_file, StrategySchema):
            data = _schema_to_kis_file_dict(schema_or_file)
        elif isinstance(schema_or_file, KisStrategyFile):
            data = schema_or_file.model_dump(exclude_none=True)
        else:
            raise TypeError(f"Unsupported type: {type(schema_or_file)}")

        return yaml.dump(
            data,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            indent=indent,
        )

    @staticmethod
    def save(
        strategy_file: KisStrategyFile,
        path: Union[str, Path],
        update_timestamp: bool = True,
    ) -> Path:
        path = Path(path)
        if not path.name.endswith(".kis.yaml"):
            if path.suffix in (".yaml", ".yml"):
                path = path.with_suffix(".kis.yaml")
            else:
                path = Path(str(path) + ".kis.yaml")

        data = strategy_file.model_dump(exclude_none=True)

        if update_timestamp:
            now_iso = datetime.now().isoformat()
            data.setdefault("metadata", {})
            data["metadata"]["updated_at"] = now_iso
            if not data["metadata"].get("created_at"):
                data["metadata"]["created_at"] = now_iso

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False, indent=2)
        logger.info(f"Strategy saved to {path}")
        return path

    @staticmethod
    def save_schema(schema: StrategySchema, path: Union[str, Path]) -> Path:
        """StrategySchema → .kis.yaml 파일 저장."""
        sf = _schema_to_kis_file(schema)
        return StrategyFileSaver.save(sf, path)


# ═══════════════════════════════════════════════════════════════════════════════
# 내부 헬퍼
# ═══════════════════════════════════════════════════════════════════════════════

def _schema_to_kis_file(schema: StrategySchema) -> KisStrategyFile:
    """StrategySchema → KisStrategyFile 역변환."""
    from src.kis_schema import CompositeConditionSchema

    def cond_to_config(c) -> ConditionConfig:
        if isinstance(c, CompositeConditionSchema):
            # Flatten first condition as representative (nested not in YAML flat model)
            inner = c.conditions[0] if c.conditions else None
            return cond_to_config(inner) if inner else ConditionConfig()
        return ConditionConfig(
            indicator=c.indicator or None,
            operator=c.operator.value if c.operator else None,
            compare_to=c.compare_to,
            value=c.value,
            output=c.indicator_output if c.indicator_output != "value" else None,
            compare_output=c.compare_output if c.compare_output != "value" else None,
            candlestick=c.candlestick,
            signal=c.signal,
        )

    def cond_group(node) -> ConditionGroupConfig:
        if isinstance(node, CompositeConditionSchema):
            return ConditionGroupConfig(
                logic=node.logic,
                conditions=[cond_to_config(c) for c in node.conditions],
            )
        return ConditionGroupConfig(logic="AND", conditions=[cond_to_config(node)])

    indicators = [
        IndicatorConfig(
            id=ind.id, alias=ind.alias, name=ind.name,
            params=ind.params, output=ind.output,
        )
        for ind in schema.indicators
    ]

    risk = None
    if schema.risk:
        risk = RiskConfig(
            stop_loss={"enabled": True, "percent": schema.risk.stop_loss_pct}
                if schema.risk.stop_loss_pct else None,
            take_profit={"enabled": True, "percent": schema.risk.take_profit_pct}
                if schema.risk.take_profit_pct else None,
            trailing_stop={"enabled": True, "percent": schema.risk.trailing_stop_pct}
                if schema.risk.trailing_stop_pct else None,
        )

    meta_tags = schema.metadata.get("tags", []) if schema.metadata else []
    meta_author = schema.metadata.get("author", "user") if schema.metadata else "user"

    return KisStrategyFile(
        version=schema.version,
        metadata=StrategyMetadata(
            name=schema.name,
            description=schema.description,
            author=meta_author,
            tags=meta_tags,
        ),
        strategy=StrategyConfig(
            id=schema.id,
            category=schema.category,
            indicators=indicators,
            entry=cond_group(schema.entry),
            exit=cond_group(schema.exit),
            params=schema.params,
        ),
        risk=risk,
    )


def _schema_to_kis_file_dict(schema: StrategySchema) -> dict:
    return _schema_to_kis_file(schema).model_dump(exclude_none=True)
