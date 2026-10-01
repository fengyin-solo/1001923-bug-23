"""集电线路接口：维护集电线路，覆盖提交巡视、登记缺陷、停运线路等动作。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.collector import CollectorService

router = APIRouter(prefix="/api/collector", tags=["集电线路"])

service = CollectorService()


@router.get("", response_model=PageResult[dict])
def list_entries(
    line_no: str | None = Query(default=None, description="按线路编号检索"),
    voltage: str | None = Query(default=None, description="按电压等级检索"),
    towers: str | None = Query(default=None, description="按起止杆塔检索"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按线路编号、电压等级、起止杆塔逐步过滤；没有命中时返回空页并说明是哪一步对不上。"""
    items, total, notice = service.list_entries(
        line_no=line_no, voltage=voltage, towers=towers, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size, notice=notice)


@router.get("/dispatch-ledger")
def list_dispatch_ledger() -> dict[str, object]:
    """调度台账：查看线路编号的建档与处置结果回写情况。"""
    return {"items": service.list_ledger()}


@router.get("/export")
def export_entries(
    line_no: str | None = None,
    voltage: str | None = None,
    towers: str | None = None,
) -> dict[str, object]:
    """导出集电线路清单：返回当前过滤条件下的全量数据（与列表同一排序、同一字段口径）。"""
    items, total, _ = service.list_entries(
        line_no=line_no, voltage=voltage, towers=towers, page=1, size=10000
    )
    return {"module": "collector", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条集电线路明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"集电线路 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条集电线路，缺字段、编号不在台账、重复提交都会说明原因而不是静默丢弃。"""
    entry, missing, message = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if entry is None:
        return ActionResult(ok=False, message=message)
    if message:
        # 同编号并发/重复提交：幂等返回既有记录。
        return ActionResult(ok=True, message=message, entry=entry)
    return ActionResult(ok=True, message="集电线路已登记，线路编号已同步到调度台账", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条集电线路执行提交巡视、登记缺陷、停运线路；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
