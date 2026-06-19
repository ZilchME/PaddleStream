import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException
from pydantic import BaseModel


class CorrectionConfig(BaseModel):
    homophoneCorrections: Dict[str, List[str]]
    domainKeywords: List[str]
    updatedAt: Optional[str] = None


DEFAULT_CORRECTION_CONFIG = {
    "homophoneCorrections": {
        "石化地图": ["实话地图", "是画地图"],
        "北斗中心": ["北斗重新"],
    },
    "domainKeywords": ["北斗", "基站", "终端", "定位", "导航", "卫星", "石化地图"],
}


def load_correction_config(config_file: Path, logger, default_config=None) -> dict:
    """从文件加载纠错配置,如果文件不存在则返回默认配置。"""
    fallback = default_config or DEFAULT_CORRECTION_CONFIG
    if config_file.exists():
        try:
            return json.loads(config_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("读取纠错配置文件失败: %s", e)
            return fallback
    return fallback


def save_correction_config(config_file: Path, config: dict, logger) -> bool:
    """保存纠错配置到文件。"""
    try:
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except Exception as e:
        logger.error("保存纠错配置文件失败: %s", e)
        return False


def register_correction_config_routes(
    app: FastAPI,
    config_file: Path,
    logger,
    default_config=None,
) -> None:
    """注册纠错配置相关 HTTP 接口。"""
    fallback = default_config or DEFAULT_CORRECTION_CONFIG

    @app.get("/api/correction-config")
    async def get_correction_config():
        return load_correction_config(config_file, logger, fallback)

    @app.post("/api/correction-config")
    async def update_correction_config(config: CorrectionConfig):
        config_dict = config.dict()
        config_dict["updatedAt"] = datetime.now().isoformat()

        if save_correction_config(config_file, config_dict, logger):
            return {"success": True, "message": "配置保存成功", "data": config_dict}
        raise HTTPException(status_code=500, detail="保存配置失败")

    @app.delete("/api/correction-config")
    async def delete_correction_config():
        try:
            if config_file.exists():
                config_file.unlink()
            return {"success": True, "message": "已重置为默认配置"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"删除配置失败: {str(e)}")
