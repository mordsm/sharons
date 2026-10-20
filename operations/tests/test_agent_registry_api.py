import pytest

from operations.models import AgentDefinition


@pytest.mark.django_db
def test_agents_list_returns_active_available_agents(client):
    AgentDefinition.objects.create(
        agent_id="chief_of_staff",
        role="Chief of Staff",
        capabilities=["planning", "prioritization"],
        allowed_data_classes=["INTERNAL", "CONFIDENTIAL"],
        max_risk_level=AgentDefinition.RiskLevel.MEDIUM,
        max_concurrent_tasks=3,
        current_task_count=1,
    )
    AgentDefinition.objects.create(
        agent_id="busy_agent",
        role="Busy Agent",
        capabilities=["planning"],
        allowed_data_classes=["INTERNAL"],
        max_risk_level=AgentDefinition.RiskLevel.MEDIUM,
        max_concurrent_tasks=1,
        current_task_count=1,
    )
    AgentDefinition.objects.create(
        agent_id="inactive_agent",
        role="Inactive Agent",
        capabilities=["planning"],
        allowed_data_classes=["INTERNAL"],
        active=False,
    )

    response = client.get("/api/v1/agents/")

    assert response.status_code == 200
    body = response.json()
    assert [agent["agent_id"] for agent in body["agents"]] == ["chief_of_staff"]
    assert body["agents"][0]["available_capacity"] == 2


@pytest.mark.django_db
def test_agents_list_filters_by_capability_data_class_and_risk(client):
    AgentDefinition.objects.create(
        agent_id="research_manager",
        role="Research Manager",
        capabilities=["research", "evidence_synthesis"],
        allowed_data_classes=["PUBLIC", "INTERNAL"],
        max_risk_level=AgentDefinition.RiskLevel.LOW,
        max_concurrent_tasks=2,
    )
    AgentDefinition.objects.create(
        agent_id="finance_agent",
        role="Finance Agent",
        capabilities=["finance", "reconciliation"],
        allowed_data_classes=["CONFIDENTIAL"],
        max_risk_level=AgentDefinition.RiskLevel.HIGH,
        max_concurrent_tasks=2,
    )

    response = client.get(
        "/api/v1/agents/",
        {"capability": "finance", "data_class": "CONFIDENTIAL", "max_risk_level": AgentDefinition.RiskLevel.MEDIUM},
    )

    assert response.status_code == 200
    assert [agent["agent_id"] for agent in response.json()["agents"]] == ["finance_agent"]


@pytest.mark.django_db
def test_agents_list_rejects_invalid_risk_filter(client):
    response = client.get("/api/v1/agents/", {"max_risk_level": "high"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_AGENT_FILTER"
