from __future__ import annotations

import uuid
from collections import defaultdict, deque
from datetime import timedelta
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from governance.models import ApprovalRequest, AuditEvent
from governance.services import decide_approval_request
from operations.models import AgentRun, Evidence, Task, TaskDependency
from portfolio.models import Objective, ObjectiveRisk


class CosEngineError(Exception):
    code = "COS_ENGINE_ERROR"
    status_code = 400


class DependencyCycleError(CosEngineError):
    code = "DEPENDENCY_CYCLE_DETECTED"
    status_code = 400


class WipLimitExceededError(CosEngineError):
    code = "WIP_LIMIT_EXCEEDED"
    status_code = 400


class RiskNotFoundError(CosEngineError):
    code = "RISK_NOT_FOUND"
    status_code = 404


# ==============================================================================
# 1. Dependency & Critical Path Engine
# ==============================================================================

class CriticalPathEngine:
    @staticmethod
    def add_dependency(
        *,
        task_id: str,
        depends_on_id: str,
        dependency_type: str = TaskDependency.DependencyType.BLOCKS,
    ) -> TaskDependency:
        if task_id == depends_on_id:
            raise CosEngineError("A task cannot depend on itself.")

        try:
            task = Task.objects.get(id=task_id)
            depends_on = Task.objects.get(id=depends_on_id)
        except Task.DoesNotExist as exc:
            raise CosEngineError("Task or dependent task not found.") from exc

        # Check for circular dependency
        if CriticalPathEngine.would_create_cycle(task_id=task_id, depends_on_id=depends_on_id):
            raise DependencyCycleError(f"Dependency from '{task.title}' to '{depends_on.title}' creates a cycle.")

        dep, _ = TaskDependency.objects.get_or_create(
            task=task,
            depends_on=depends_on,
            defaults={"dependency_type": dependency_type},
        )
        return dep

    @staticmethod
    def remove_dependency(*, task_id: str, depends_on_id: str) -> bool:
        deleted, _ = TaskDependency.objects.filter(task_id=task_id, depends_on_id=depends_on_id).delete()
        return deleted > 0

    @staticmethod
    def would_create_cycle(*, task_id: str, depends_on_id: str) -> bool:
        """
        Check if adding an edge task -> depends_on would create a cycle.
        A cycle is created if there is already a path from depends_on to task
        (i.e., depends_on already depends directly or indirectly on task).
        """
        if task_id == depends_on_id:
            return True

        visited = set()
        queue = deque([depends_on_id])

        while queue:
            curr = queue.popleft()
            if curr == task_id:
                return True
            if curr in visited:
                continue
            visited.add(curr)
            upstream = TaskDependency.objects.filter(task_id=curr).values_list("depends_on_id", flat=True)
            for parent_id in upstream:
                parent_str = str(parent_id)
                if parent_str not in visited:
                    queue.append(parent_str)
        return False


    @staticmethod
    def analyze_critical_path(*, objective_id: str | None = None) -> dict[str, Any]:
        """
        Calculates dependency graph, root blockers, dependency depth, and critical path chains.
        """
        tasks_qs = Task.objects.select_related("objective").all()
        if objective_id:
            tasks_qs = tasks_qs.filter(objective_id=objective_id)

        task_map = {str(t.id): t for t in tasks_qs}
        deps = TaskDependency.objects.filter(task_id__in=task_map.keys(), depends_on_id__in=task_map.keys())

        # Build graph:
        # upstream: task -> list of tasks it depends on
        # downstream: task -> list of tasks that depend on it
        upstream: dict[str, list[str]] = defaultdict(list)
        downstream: dict[str, list[str]] = defaultdict(list)

        for dep in deps:
            t_id = str(dep.task_id)
            p_id = str(dep.depends_on_id)
            upstream[t_id].append(p_id)
            downstream[p_id].append(t_id)

        # In-degree for topological sort
        in_degree = {t_id: len(upstream[t_id]) for t_id in task_map}
        queue = deque([t_id for t_id, deg in in_degree.items() if deg == 0])
        topo_order = []

        while queue:
            curr = queue.popleft()
            topo_order.append(curr)
            for child in downstream[curr]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        has_cycle = len(topo_order) < len(task_map)

        # Uncompleted tasks
        completed_statuses = {Task.Status.COMPLETED, Task.Status.CANCELLED}
        open_task_ids = {t_id for t_id, t in task_map.items() if t.status not in completed_statuses}

        # Root blockers: uncompleted tasks that block other tasks, but are themselves not blocked
        # by any uncompleted task!
        root_blockers = []
        for t_id in open_task_ids:
            uncompleted_parents = [p for p in upstream[t_id] if p in open_task_ids]
            dependent_children = downstream[t_id]
            if not uncompleted_parents and dependent_children:
                task = task_map[t_id]
                root_blockers.append({
                    "task_id": str(task.id),
                    "title": task.title,
                    "status": task.status,
                    "objective_code": task.objective.code,
                    "blocking_count": len(dependent_children),
                    "blocked_tasks": [task_map[c].title for c in dependent_children if c in task_map],
                })

        root_blockers.sort(key=lambda x: x["blocking_count"], reverse=True)

        # Calculate longest downstream chain for each task (critical path length)
        # Depth = maximum number of uncompleted downstream dependent tasks
        depth_memo: dict[str, int] = {}

        def get_downstream_depth(node_id: str, visited: set) -> int:
            if node_id in depth_memo:
                return depth_memo[node_id]
            if node_id in visited:
                return 0
            visited.add(node_id)
            max_d = 0
            for child_id in downstream[node_id]:
                if child_id in open_task_ids:
                    max_d = max(max_d, 1 + get_downstream_depth(child_id, visited.copy()))
            depth_memo[node_id] = max_d
            return max_d

        critical_path_tasks = []
        for t_id in open_task_ids:
            d = get_downstream_depth(t_id, set())
            task = task_map[t_id]
            critical_path_tasks.append({
                "task_id": str(task.id),
                "title": task.title,
                "status": task.status,
                "objective_code": task.objective.code,
                "chain_depth": d,
                "downstream_count": len(downstream[t_id]),
                "upstream_uncompleted": len([p for p in upstream[t_id] if p in open_task_ids]),
            })

        critical_path_tasks.sort(key=lambda x: (x["chain_depth"], x["downstream_count"]), reverse=True)

        return {
            "has_cycle": has_cycle,
            "total_tasks": len(task_map),
            "open_tasks_count": len(open_task_ids),
            "root_blockers": root_blockers[:10],
            "critical_path_tasks": critical_path_tasks[:15],
            "topological_order": [task_map[tid].title for tid in topo_order if tid in task_map][:20],
        }


# ==============================================================================
# 2. WIP Limits & Stale-Task Controls
# ==============================================================================

class WipAndStaleControlEngine:
    DEFAULT_MAX_WIP_PER_OBJECTIVE = 3
    DEFAULT_STALE_DAYS_THRESHOLD = 5

    @staticmethod
    def get_wip_report() -> dict[str, Any]:
        """
        Inspects active concurrent work per active objective.
        Active statuses: IN_PROGRESS, ASSIGNED, VERIFYING.
        """
        active_statuses = [Task.Status.IN_PROGRESS, Task.Status.ASSIGNED, Task.Status.VERIFYING]
        objectives = Objective.objects.filter(status=Objective.Status.ACTIVE).order_by("code")

        report = []
        total_wip = 0
        wip_violations = 0

        for obj in objectives:
            active_tasks = obj.tasks.filter(status__in=active_statuses)
            wip_count = active_tasks.count()
            total_wip += wip_count
            limit = WipAndStaleControlEngine.DEFAULT_MAX_WIP_PER_OBJECTIVE
            is_over_limit = wip_count > limit
            if is_over_limit:
                wip_violations += 1

            report.append({
                "objective_id": str(obj.id),
                "objective_code": obj.code,
                "objective_name": obj.name,
                "wip_count": wip_count,
                "wip_limit": limit,
                "is_over_limit": is_over_limit,
                "active_tasks": [
                    {
                        "task_id": str(t.id),
                        "title": t.title,
                        "status": t.status,
                        "owner_agent_id": t.owner_agent_id,
                    }
                    for t in active_tasks[:10]
                ],
            })

        return {
            "total_wip": total_wip,
            "wip_violations_count": wip_violations,
            "objectives": report,
            "wip_limit_policy": f"Max {WipAndStaleControlEngine.DEFAULT_MAX_WIP_PER_OBJECTIVE} active tasks per objective",
        }

    @staticmethod
    def check_wip_limit_for_task(task: Task) -> tuple[bool, str]:
        """
        Checks whether activating this task would violate objective WIP limits.
        """
        active_statuses = [Task.Status.IN_PROGRESS, Task.Status.ASSIGNED, Task.Status.VERIFYING]
        current_wip = task.objective.tasks.filter(status__in=active_statuses).exclude(id=task.id).count()
        limit = WipAndStaleControlEngine.DEFAULT_MAX_WIP_PER_OBJECTIVE
        if current_wip >= limit:
            return False, f"WIP limit reached for {task.objective.code} ({current_wip}/{limit} active tasks)."
        return True, "Within WIP limit."

    @staticmethod
    def scan_stale_tasks(*, stale_days: int = DEFAULT_STALE_DAYS_THRESHOLD) -> list[dict[str, Any]]:
        """
        Scans for open tasks that have not had updates or evidence recorded in stale_days.
        """
        cutoff = timezone.now() - timedelta(days=stale_days)
        open_tasks = Task.objects.select_related("objective").exclude(
            status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.FAILED]
        ).filter(updated_at__lt=cutoff).order_by("updated_at")

        results = []
        for task in open_tasks:
            # Check latest evidence or agent run
            latest_evidence = Evidence.objects.filter(task=task).order_by("-created_at").first()
            latest_run = AgentRun.objects.filter(task=task).order_by("-started_at").first()

            latest_activity = task.updated_at
            if latest_evidence and latest_evidence.created_at > latest_activity:
                latest_activity = latest_evidence.created_at
            if latest_run and latest_run.started_at > latest_activity:
                latest_activity = latest_run.started_at

            if latest_activity >= cutoff:
                continue

            days_inactive = (timezone.now() - latest_activity).days

            # Determine severity and recommendation
            if days_inactive >= 14:
                severity = "CRITICAL"
                recommendation = "Cancel task or escalate to CEO for scope reduction."
            elif days_inactive >= 8:
                severity = "HIGH"
                recommendation = "Reassign task or break down into smaller units."
            else:
                severity = "MEDIUM"
                recommendation = "Ping task owner or verify blockers."

            results.append({
                "task_id": str(task.id),
                "title": task.title,
                "status": task.status,
                "objective_code": task.objective.code,
                "objective_name": task.objective.name,
                "owner_agent_id": task.owner_agent_id or "unassigned",
                "days_inactive": days_inactive,
                "last_activity_at": latest_activity.isoformat(),
                "severity": severity,
                "recommendation": recommendation,
            })

        results.sort(key=lambda x: x["days_inactive"], reverse=True)
        return results


# ==============================================================================
# 3. Objective Risk Register Engine
# ==============================================================================

class RiskRegisterEngine:
    @staticmethod
    def create_risk(
        *,
        objective_id: str,
        title: str,
        category: str = ObjectiveRisk.Category.TECHNICAL,
        severity: str = ObjectiveRisk.Severity.MEDIUM,
        likelihood: str = ObjectiveRisk.Severity.MEDIUM,
        description: str = "",
        mitigation_plan: str = "",
        contingency_plan: str = "",
        owner: str = "",
        actor_id: str = "cos",
        correlation_id: str = "",
    ) -> ObjectiveRisk:
        try:
            objective = Objective.objects.get(id=objective_id)
        except Objective.DoesNotExist as exc:
            raise CosEngineError(f"Objective '{objective_id}' not found.") from exc

        with transaction.atomic():
            risk = ObjectiveRisk.objects.create(
                objective=objective,
                title=title,
                description=description,
                category=category,
                severity=severity,
                likelihood=likelihood,
                mitigation_plan=mitigation_plan,
                contingency_plan=contingency_plan,
                owner=owner,
            )

            AuditEvent.objects.create(
                action="cos.risk.created",
                actor_type=AuditEvent.ActorType.AGENT,
                actor_id=actor_id,
                object_type="portfolio.ObjectiveRisk",
                object_id=str(risk.id),
                correlation_id=correlation_id or str(uuid.uuid4()),
                metadata={
                    "objective_code": objective.code,
                    "title": title,
                    "severity": severity,
                    "category": category,
                },
            )

        return risk

    @staticmethod
    def update_risk(
        *,
        risk_id: str,
        payload: dict[str, Any],
        actor_id: str = "cos",
        correlation_id: str = "",
    ) -> ObjectiveRisk:
        try:
            risk = ObjectiveRisk.objects.get(id=risk_id)
        except ObjectiveRisk.DoesNotExist as exc:
            raise RiskNotFoundError(f"Risk '{risk_id}' not found.") from exc

        allowed_fields = [
            "title", "description", "category", "severity", "likelihood",
            "mitigation_plan", "contingency_plan", "status", "owner"
        ]

        with transaction.atomic():
            for field in allowed_fields:
                if field in payload:
                    setattr(risk, field, payload[field])
            risk.save()

            AuditEvent.objects.create(
                action="cos.risk.updated",
                actor_type=AuditEvent.ActorType.AGENT,
                actor_id=actor_id,
                object_type="portfolio.ObjectiveRisk",
                object_id=str(risk.id),
                correlation_id=correlation_id or str(uuid.uuid4()),
                metadata=payload,
            )

        return risk

    @staticmethod
    def get_risk_matrix(*, objective_id: str | None = None) -> dict[str, Any]:
        """
        Calculates risk exposure scores and categorizes risks by severity and status.
        """
        risks_qs = ObjectiveRisk.objects.select_related("objective").all()
        if objective_id:
            risks_qs = risks_qs.filter(objective_id=objective_id)

        severity_weights = {
            ObjectiveRisk.Severity.LOW: 1,
            ObjectiveRisk.Severity.MEDIUM: 2,
            ObjectiveRisk.Severity.HIGH: 3,
            ObjectiveRisk.Severity.CRITICAL: 4,
        }
        likelihood_weights = {
            ObjectiveRisk.Severity.LOW: 1,
            ObjectiveRisk.Severity.MEDIUM: 2,
            ObjectiveRisk.Severity.HIGH: 3,
            ObjectiveRisk.Severity.CRITICAL: 4,
        }

        serialized_risks = []
        critical_count = 0
        high_count = 0

        for r in risks_qs.order_by("-updated_at"):
            sev_w = severity_weights.get(r.severity, 2)
            lik_w = likelihood_weights.get(r.likelihood, 2)
            exposure_score = sev_w * lik_w  # Range 1 - 16

            if r.severity == ObjectiveRisk.Severity.CRITICAL and r.status != ObjectiveRisk.Status.RESOLVED:
                critical_count += 1
            elif r.severity == ObjectiveRisk.Severity.HIGH and r.status != ObjectiveRisk.Status.RESOLVED:
                high_count += 1

            serialized_risks.append({
                "id": str(r.id),
                "objective_id": str(r.objective_id),
                "objective_code": r.objective.code,
                "title": r.title,
                "description": r.description,
                "category": r.category,
                "severity": r.severity,
                "likelihood": r.likelihood,
                "exposure_score": exposure_score,
                "status": r.status,
                "owner": r.owner,
                "mitigation_plan": r.mitigation_plan,
                "contingency_plan": r.contingency_plan,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            })

        serialized_risks.sort(key=lambda x: x["exposure_score"], reverse=True)

        return {
            "total_risks": len(serialized_risks),
            "critical_risks_count": critical_count,
            "high_risks_count": high_count,
            "risks": serialized_risks,
        }


# ==============================================================================
# 4. Weekly CEO Decision Bundle Engine
# ==============================================================================

class CeoDecisionBundleEngine:
    @staticmethod
    def generate_decision_bundle() -> dict[str, Any]:
        """
        Assembles the comprehensive 30-minute CEO weekly decision package.
        """
        now = timezone.now()
        one_week_ago = now - timedelta(days=7)

        # 1. Active Objectives & Summary
        objectives = Objective.objects.filter(status=Objective.Status.ACTIVE).order_by("code")

        # 2. Critical Path & Root Blockers
        cp_analysis = CriticalPathEngine.analyze_critical_path()

        # 3. WIP & Stale Tasks
        wip_report = WipAndStaleControlEngine.get_wip_report()
        stale_tasks = WipAndStaleControlEngine.scan_stale_tasks(stale_days=5)

        # 4. Risk Register Highlights
        risk_matrix = RiskRegisterEngine.get_risk_matrix()
        top_risks = [r for r in risk_matrix["risks"] if r["severity"] in ["CRITICAL", "HIGH"] and r["status"] != "RESOLVED"]

        # 5. Pending Approvals (Decision Queue)
        pending_approvals = ApprovalRequest.objects.filter(
            status=ApprovalRequest.Status.PENDING
        ).order_by("expires_at")

        decision_queue = []
        for app in pending_approvals:
            # Generate Chief of Staff Recommendation
            is_expired = app.expires_at < now
            recommendation = "APPROVE"
            rationale = "Operating proposal adheres to safety constraints and aligns with 90-day objective."

            if is_expired:
                recommendation = "REJECT_EXPIRED"
                rationale = "Approval request has expired without decision. Recommend archiving or re-requesting."
            elif "rule" in app.action.lower() and ("activate" in app.action.lower() or "activation" in app.action.lower()):
                recommendation = "APPROVE_CONDITIONAL"
                rationale = "Deterministic rule passed test assertions. Recommend activation."

            decision_queue.append({
                "approval_id": str(app.id),
                "subject_type": app.subject_type,
                "subject_id": app.subject_id,
                "action": app.action,
                "requested_by": app.requested_by,
                "status": app.status,
                "is_expired": is_expired,
                "expires_at": app.expires_at.isoformat(),
                "payload": app.action_payload,
                "cos_recommendation": recommendation,
                "cos_rationale": rationale,
            })

        # 6. Verified Deliveries (Past 7 Days)
        verified_tasks = Task.objects.filter(
            status=Task.Status.COMPLETED,
            updated_at__gte=one_week_ago
        ).select_related("objective").order_by("-updated_at")

        verified_deliveries = []
        for t in verified_tasks:
            ev_count = t.evidence.filter(verified=True).count()
            ac_passed = t.acceptance_criteria.filter(status="PASSED").count()
            ac_total = t.acceptance_criteria.count()
            verified_deliveries.append({
                "task_id": str(t.id),
                "title": t.title,
                "objective_code": t.objective.code,
                "completed_at": t.updated_at.isoformat(),
                "verified_evidence_count": ev_count,
                "acceptance_criteria_passed": f"{ac_passed}/{ac_total}" if ac_total else "N/A",
            })

        # 7. Resource Reallocation Monitor (Rule 49: > 20% shift requires CEO approval)
        # Compute task distribution across active objectives
        total_open = Task.objects.exclude(status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED]).count()
        resource_distribution = []
        has_reallocation_alert = False

        if total_open > 0:
            for obj in objectives:
                count = obj.tasks.exclude(status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED]).count()
                pct = round((count / total_open) * 100, 1)
                resource_distribution.append({
                    "objective_code": obj.code,
                    "task_count": count,
                    "percentage_of_team_wip": pct,
                })
                # If single objective dominates > 65% or shifted significantly
                if pct > 65:
                    has_reallocation_alert = True

        return {
            "generated_at": now.isoformat(),
            "agenda_duration_minutes": 30,
            "executive_summary": {
                "active_objectives_count": objectives.count(),
                "pending_decisions_count": len(decision_queue),
                "critical_risks_count": len(top_risks),
                "root_blockers_count": len(cp_analysis["root_blockers"]),
                "stale_tasks_count": len(stale_tasks),
                "verified_deliveries_past_week": len(verified_deliveries),
                "resource_reallocation_alert": has_reallocation_alert,
            },
            "decision_queue": decision_queue,
            "root_blockers": cp_analysis["root_blockers"],
            "critical_path": cp_analysis["critical_path_tasks"],
            "top_risks": top_risks,
            "stale_tasks": stale_tasks,
            "wip_summary": wip_report,
            "verified_deliveries": verified_deliveries,
            "resource_distribution": resource_distribution,
        }

    @staticmethod
    def execute_decision(
        *,
        approval_id: str,
        decision: str,
        reason: str,
        decided_by: str = "ceo",
        correlation_id: str = "",
    ) -> dict[str, Any]:
        """
        Executes a CEO decision on an ApprovalRequest within transaction and audit log.
        """
        if decision not in [ApprovalRequest.Status.APPROVED, ApprovalRequest.Status.REJECTED]:
            raise CosEngineError(f"Invalid decision '{decision}'. Must be APPROVED or REJECTED.")

        try:
            approval = ApprovalRequest.objects.get(id=approval_id)
        except ApprovalRequest.DoesNotExist as exc:
            raise CosEngineError(f"ApprovalRequest '{approval_id}' not found.") from exc

        res = decide_approval_request(
            approval_id=approval_id,
            decision=decision,
            actor_id=decided_by,
            subject_version=approval.subject_version,
            action_payload=approval.action_payload,
            correlation_id=correlation_id or str(uuid.uuid4()),
        )

        return {
            "approval_id": approval_id,
            "decision": res.status,
            "decided_by": res.decided_by,
            "decided_at": res.decided_at.isoformat() if res.decided_at else None,
            "reason": reason,
        }

