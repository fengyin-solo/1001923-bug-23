"""集电线路接口：维护集电线路，覆盖提交巡视、登记缺陷、停运线路等动作。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, CollectorPageResult, EntryPayload
from app.services.collector import FILTER_FIELDS, CollectorService

router = APIRouter(prefix="/api/collector", tags=["集电线路"])

service = CollectorService()


@router.get("", response_model=CollectorPageResult)
def list_entries(
    线路编号: str | None = Query(default=None, description="按线路编号过滤"),
    电压等级: str | None = Query(default=None, description="按电压等级过滤"),
    起止杆塔: str | None = Query(default=None, description="按起止杆塔过滤"),
    page: int = 1,
    size: int = 20,
) -> CollectorPageResult:
    """按线路编号、电压等级、起止杆塔逐步过滤；只返回真正命中的记录，空结果不报错。

    参数名沿用台账中文字段，前端筛选框直接以字段名提交。
    """
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    filters = {field: value for field, value in (
        ("线路编号", 线路编号),
        ("电压等级", 电压等级),
        ("起止杆塔", 起止杆塔),
    ) if value}
    items, total, steps = service.list_entries(filters=filters, page=page, size=size)
    return CollectorPageResult(items=items, total=total, page=page, size=size, steps=steps)


@router.get("/dispatch-ledger")
def list_dispatch_ledger() -> dict[str, object]:
    """调度台账：查看集电线路处置结果的回写情况。"""
    return {"items": service.list_ledger()}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条集电线路明细；不存在时给出可读的错误说明。

    明细与列表共用同一取值口径，线路长度、线路状态两处一致。
    """
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"集电线路 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条集电线路，缺字段时说明原因而不是静默丢弃。

    同一线路编号并发提交只保留一条：后到的请求返回既有记录并说明编号已存在。
    """
    entry, missing, duplicated = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if duplicated:
        return ActionResult(ok=True, message="线路编号已存在，沿用既有登记，未重复新增", entry=entry)
    return ActionResult(ok=True, message="集电线路已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条集电线路执行提交巡视、登记缺陷、停运线路；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export/all")
def export_entries(
    线路编号: str | None = None,
    电压等级: str | None = None,
    起止杆塔: str | None = None,
) -> dict[str, object]:
    """导出集电线路清单：返回当前过滤条件下去重后的全量数据。"""
    filters = {field: value for field, value in (
        ("线路编号", 线路编号),
        ("电压等级", 电压等级),
        ("起止杆塔", 起止杆塔),
    ) if value}
    items, total, _ = service.list_entries(filters=filters, page=1, size=10000)
    return {"module": "collector", "total": total, "items": items}
