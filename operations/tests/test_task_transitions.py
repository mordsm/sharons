import pytest
from django.utils import timezone

from governance.models import AuditEvent
from operations.models import AcceptanceCriterion, AgentDefinition, Task
from operations.services import (
    ALLOWED_TRANSITIONS,
    InvalidTaskTransitionError,
    TaskVerificationIncompleteError,
    TaskVersionConflictError,
    transition_task,
)
from portfolio.models import Objective, StrategyVersion


@pytest.fixture
def active_objective():
    strategy = StrategyVersion.objects.create(
        version=1,
        title="Initial strategy",
        content={"horizon": "90 days"},
        status=StrategyVersion.Status.ACTIVE,
        valid_from=timezone.now(),
    )
    return Objective.objects.create(
        code="O1",
        strategy_version=strategy,
        name="Mental Trainer commercial readiness",
        business_outcome="Ready for beta",
        status=Objective.Status.ACTIVE,
        owner_agent_id="chief_of_staff",
    )


@pytest.fixture
def task(active_objective):
    return Task.objects.create(
        objective=active_objective,
        title="Prepare beta checklist",
        business_outcome="Ready for beta",
        created_by="test",
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [(from_status, to_status) for from_status, next_statuses in ALLOWED_TRANSITIONS.items() for to_status in next_statuses],
)
def test_allowed_task_transitions_are_applied(task, from_status, to_status):
    task.status = from_status
    task.save()
    if to_status == Task.Status.COMPLETED:
        AcceptanceCriterion.objects.create(
            task=task,
            description="Completion evidence was verified.",
            status=AcceptanceCriterion.Status.PASSED,
        )

    transitioned = transition_task(
        str(task.id),
        to_status=to_status,
        expected_version=task.version,
        actor_id="chief_of_staff",
        correlation_id="corr-transition",
    )

    assert transitioned.status == to_status
    assert transitioned.version == 2
    assert AuditEvent.objects.filter(
        object_id=str(task.id),
        action="operations.task.transitioned",
        metadata__from_status=from_status,
        metadata__to_status=to_status,
    ).exists()


@pytest.mark.django_db
def test_forbidden_task_transition_is_rejected_without_audit(task):
    with pytest.raises(InvalidTaskTransitionError):
        transition_task(
            str(task.id),
            to_status=Task.Status.COMPLETED,
            expected_version=task.version,
            actor_id="chief_of_staff",
            correlation_id="corr-transition",
        )

    task.refresh_from_db()
    assert task.status == Task.Status.DRAFT
    assert task.version == 1
    assert AuditEvent.objects.count() == 0


@pytest.mark.django_db
def test_completed_transition_requires_acceptance_criteria(task):
    task.status = Task.Status.VERIFYING
    task.save()

    with pytest.raises(TaskVerificationIncompleteError):
        transition_task(
            str(task.id),
            to_status=Task.Status.COMPLETED,
            expected_version=task.version,
            actor_id="chief_of_staff",
            correlation_id="corr-transition",
        )

    task.refresh_from_db()
    assert task.status == Task.Status.VERIFYING
    assert task.version == 1
    assert AuditEvent.objects.count() == 0


@pytest.mark.django_db
def test_completed_transition_requires_all_required_criteria_to_pass(task):
    task.status = Task.Status.VERIFYING
    task.save()
    AcceptanceCriterion.objects.create(
        task=task,
        description="Completion evidence was verified.",
        status=AcceptanceCriterion.Status.PENDING,
    )

    with pytest.raises(TaskVerificationIncompleteError):
        transition_task(
            str(task.id),
            to_status=Task.Status.COMPLETED,
            expected_version=task.version,
            actor_id="chief_of_staff",
            correlation_id="corr-transition",
        )

    task.refresh_from_db()
    assert task.status == Task.Status.VERIFYING
    assert task.version == 1
    assert AuditEvent.objects.count() == 0


@pytest.mark.django_db
def test_stale_task_version_is_rejected(task):
    task.version = 3
    task.save()

    with pytest.raises(TaskVersionConflictError):
        transition_task(
            str(task.id),
            to_status=Task.Status.PLANNED,
            expected_version=1,
            actor_id="chief_of_staff",
            correlation_id="corr-transition",
        )

    task.refresh_from_db()
    assert task.status == Task.Status.DRAFT
    assert task.version == 3
    assert AuditEvent.objects.count() == 0


@pytest.mark.django_db
def test_terminal_transition_releases_assigned_agent_capacity(task):
    agent = AgentDefinition.objects.create(
        agent_id="developer",
        role="Developer",
        max_concurrent_tasks=2,
        current_task_count=1,
    )
    task.status = Task.Status.VERIFYING
    task.owner_agent_id = agent.agent_id
    task.save()
    AcceptanceCriterion.objects.create(
        task=task,
        description="Completion evidence was verified.",
        status=AcceptanceCriterion.Status.PASSED,
    )

    transitioned = transition_task(
        str(task.id),
        to_status=Task.Status.COMPLETED,
        expected_version=task.version,
        actor_id="chief_of_staff",
        correlation_id="corr-transition-complete",
    )

    agent.refresh_from_db()
    assert transitioned.status == Task.Status.COMPLETED
    assert agent.current_task_count == 0
    assert AuditEvent.objects.filter(
        object_id=str(task.id),
        action="operations.task.transitioned",
        metadata__released_agent_id="developer",
    ).exists()
