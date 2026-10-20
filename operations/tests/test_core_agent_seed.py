from django.core.management import call_command

import pytest

from governance.models import AuditEvent
from operations.models import AgentDefinition
from operations.services import seed_core_agents


pytestmark = pytest.mark.django_db


def test_seed_core_agents_creates_requested_roles():
    agents = seed_core_agents(actor_id="chief_of_staff", correlation_id="corr-agents-1")

    assert [agent.agent_id for agent in agents] == [
        "product_manager",
        "project_manager",
        "executive_assistant",
        "developer",
        "marketing",
    ]
    assert AgentDefinition.objects.count() == 5
    assert AgentDefinition.objects.get(agent_id="developer").capabilities == [
        "engineering",
        "implementation",
        "testing",
        "documentation",
        "code_review",
    ]
    assert "external_publish" in AgentDefinition.objects.get(agent_id="marketing").forbidden_actions
    assert AuditEvent.objects.filter(action="operations.core_agents.seeded").exists()


def test_seed_core_agents_is_idempotent_and_updates_existing_records():
    AgentDefinition.objects.create(
        agent_id="marketing",
        role="Old Marketing",
        capabilities=["old"],
        allowed_data_classes=["PUBLIC"],
        max_concurrent_tasks=1,
    )

    seed_core_agents(actor_id="chief_of_staff", correlation_id="corr-agents-1")
    seed_core_agents(actor_id="chief_of_staff", correlation_id="corr-agents-2")

    assert AgentDefinition.objects.count() == 5
    marketing = AgentDefinition.objects.get(agent_id="marketing")
    assert marketing.role == "Marketing"
    assert marketing.capabilities == ["marketing", "positioning", "copywriting", "campaign_planning", "audience_research"]
    assert AuditEvent.objects.filter(action="operations.core_agents.seeded").count() == 2


def test_seed_core_agents_command():
    call_command("seed_core_agents", correlation_id="corr-command", actor_id="chief_of_staff")

    assert AgentDefinition.objects.filter(agent_id="product_manager").exists()
    assert AgentDefinition.objects.filter(agent_id="project_manager").exists()


def test_seeded_agents_are_available_through_agent_registry(client):
    seed_core_agents(actor_id="chief_of_staff", correlation_id="corr-agents-api")

    response = client.get("/api/v1/agents/", {"capability": "engineering", "data_class": "CONFIDENTIAL"})

    assert response.status_code == 200
    body = response.json()
    assert [agent["agent_id"] for agent in body["agents"]] == ["developer"]
