"""集电线路业务规则：字段口径、筛选去重、状态流转与调度台账回写都收在这里。"""
from __future__ import annotations

import threading
from datetime import date
from typing import Any

from app.store import store

MODULE = "collector"
LEDGER_MODULE = "dispatch_ledger"
REQUIRED_FIELDS = ["线路编号", "电压等级", "起止杆塔"]
LIST_FIELDS = ["线路编号", "电压等级", "起止杆塔", "线路长度", "所属场站", "上次巡视日", "缺陷数量", "线路状态"]
# 支持的三个过滤条件，顺序就是逐步缩小结果集的顺序，命不中时按这个顺序说明卡在哪一步。
FILTER_FIELDS = ["线路编号", "电压等级", "起止杆塔"]
STATUS_ORDER = ["待巡视", "运行正常", "存在缺陷", "已停运"]
ACTION_RULES = {"提交巡视": "运行正常", "登记缺陷": "存在缺陷", "停运线路": "已停运"}

# 同一线路编号并发提交时，靠它保证只落一条。
_create_lock = threading.Lock()


def normalize_keyword(value: Any) -> str:
    """过滤值统一去首尾空白；空白条件视为未填写。"""
    return str(value or "").strip()


def serialize(row: dict[str, Any]) -> dict[str, Any]:
    """列表与详情共用的取值口径：线路状态一律以内部 status 为准，线路长度原样透传。

    种子数据里的「线路状态」列是占位文本，不能直接展示；线路长度则沿用登记值，
    两处取同一个序列化结果，避免列表与详情各说各话。
    """
    return {
        "id": row.get("id"),
        "线路编号": row.get("线路编号"),
        "电压等级": row.get("电压等级"),
        "起止杆塔": row.get("起止杆塔"),
        "线路长度": row.get("线路长度"),
        "所属场站": row.get("所属场站"),
        "上次巡视日": row.get("上次巡视日"),
        "缺陷数量": row.get("缺陷数量"),
        "线路状态": row.get("status"),
    }


class CollectorService:
    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
        """按线路编号、电压等级、起止杆塔逐步过滤，返回 (当前页, 去重后总数, 每步命中情况)。

        结果集先按登记次序（id 升序）排稳，再按线路编号去重（同编号保留最先登记的一条），
        然后逐个过滤条件缩小范围，每一步记录剩余条数，命不中时前端可据此说明卡在哪一步。
        """
        filters = {field: normalize_keyword(filters.get(field)) for field in FILTER_FIELDS} if filters else {}

        rows = sorted(store.rows(MODULE), key=lambda row: int(row.get("id", 0)))
        seen: set[str] = set()
        unique_rows: list[dict[str, Any]] = []
        for row in rows:
            line_no = str(row.get("线路编号") or "").strip()
            if line_no in seen:
                continue
            seen.add(line_no)
            unique_rows.append(row)

        steps: list[dict[str, Any]] = []
        remaining = unique_rows
        for field in FILTER_FIELDS:
            keyword = filters.get(field, "")
            if keyword:
                remaining = [row for row in remaining if keyword in str(row.get(field, ""))]
            steps.append({
                "field": field,
                "keyword": keyword or None,
                "matched": len(remaining),
                "applied": bool(keyword),
            })

        total = len(remaining)
        page = max(page, 1)
        start = (page - 1) * size
        page_rows = [serialize(row) for row in remaining[start:start + size]]
        return page_rows, total, steps

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        """详情与列表走同一个 serialize，线路长度、线路状态必然是同一份值。"""
        row = store.find(MODULE, entry_id)
        return serialize(row) if row is not None else None

    def find_by_line_no(self, line_no: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("线路编号") or "").strip() == line_no.strip():
                return row
        return None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], bool]:
        """登记一条集电线路。

        返回 (记录, 缺失字段, 是否命中了已存在的编号)。同一线路编号并发提交时加锁判定，
        后到的请求不再新增，直接返回既有那条，保证一张编号只留一条。
        """
        missing = [field for field in REQUIRED_FIELDS if not normalize_keyword(values.get(field))]
        if missing:
            return None, missing, False

        line_no = normalize_keyword(values["线路编号"])
        with _create_lock:
            existing = self.find_by_line_no(line_no)
            if existing is not None:
                return serialize(existing), [], True
            rows = store.rows(MODULE)
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
            # 选填字段随登记表一并存下，线路长度等在列表与详情共用同一份。
            for field in ("线路长度", "所属场站"):
                if normalize_keyword(values.get(field)):
                    entry[field] = values.get(field)
            entry["上次巡视日"] = None
            entry["缺陷数量"] = 0
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            rows.append(entry)
            return serialize(entry), [], False

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"集电线路 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于集电线路可执行范围"
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        if action == "提交巡视":
            entry["上次巡视日"] = date.today().isoformat()
        # 处置结果按线路编号回写调度台账，编号沿用台账既有的「线路编号」字段。
        ledger_no = self._write_back_ledger(entry, target)
        message = f"集电线路已{action}，处置结果已回写调度台账（台账编号 {ledger_no}）"
        return serialize(entry), message

    def _write_back_ledger(self, entry: dict[str, Any], result: str) -> int:
        """按线路编号 upsert 调度台账：已存在则更新处置结果，不存在则新建。"""
        ledger_rows = store.rows(LEDGER_MODULE)
        line_no = str(entry.get("线路编号") or "").strip()
        for ledger in ledger_rows:
            if str(ledger.get("线路编号") or "").strip() == line_no:
                ledger["处置结果"] = result
                ledger["更新日期"] = date.today().isoformat()
                return int(ledger["id"])
        ledger = {
            "id": max((int(row.get("id", 0)) for row in ledger_rows), default=0) + 1,
            "线路编号": line_no,
            "电压等级": entry.get("电压等级"),
            "起止杆塔": entry.get("起止杆塔"),
            "处置结果": result,
            "更新日期": date.today().isoformat(),
        }
        ledger_rows.append(ledger)
        return int(ledger["id"])

    def list_ledger(self) -> list[dict[str, Any]]:
        """调度台账按更新次序（id 升序）给出，便于核对回写结果。"""
        return [dict(row) for row in sorted(store.rows(LEDGER_MODULE), key=lambda row: int(row.get("id", 0)))]
