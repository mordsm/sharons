import uuid

from django.core.exceptions import ValidationError
from django.db import models

from operations.models import Task
from portfolio.models import Objective, Project, ProjectConnection


class ProductSpecContract(models.Model):
    class Status(models.TextChoices):
        READY = "READY"
        IN_PROGRESS = "IN_PROGRESS"
        COMPLETED = "COMPLETED"
        CANCELLED = "CANCELLED"

    class SpecType(models.TextChoices):
        PRD = "PRD"
        USER_STORY = "USER_STORY"
        ROADMAP = "ROADMAP"
        RELEASE_SCOPE = "RELEASE_SCOPE"
        DISCOVERY_BRIEF = "DISCOVERY_BRIEF"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="product_spec_contracts")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="product_spec_contracts")
    project_connection = models.ForeignKey(ProjectConnection, on_delete=models.PROTECT, related_name="product_spec_contracts")
    title = models.CharField(max_length=200)
    spec_type = models.CharField(max_length=32, choices=SpecType.choices, default=SpecType.PRD)
    objective = models.TextField()
    target_users = models.JSONField(default=list, blank=True)
    problem_statement = models.TextField()
    success_metrics = models.JSONField(default=list, blank=True)
    requirements = models.JSONField(default=list, blank=True)
    constraints = models.JSONField(default=dict, blank=True)
    open_questions = models.JSONField(default=list, blank=True)
    deliverables = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.READY)
    no_external_write = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Title cannot be empty."})
        if not self.objective or not self.objective.strip():
            raise ValidationError({"objective": "Objective cannot be empty."})
        if not self.problem_statement or not self.problem_statement.strip():
            raise ValidationError({"problem_statement": "Problem statement cannot be empty."})
        if not isinstance(self.target_users, list):
            raise ValidationError({"target_users": "Target users must be a list."})
        if not isinstance(self.success_metrics, list):
            raise ValidationError({"success_metrics": "Success metrics must be a list."})
        if not isinstance(self.requirements, list):
            raise ValidationError({"requirements": "Requirements must be a list."})
        if not isinstance(self.constraints, dict):
            raise ValidationError({"constraints": "Constraints must be an object."})
        if not isinstance(self.open_questions, list):
            raise ValidationError({"open_questions": "Open questions must be a list."})
        if not isinstance(self.deliverables, list):
            raise ValidationError({"deliverables": "Deliverables must be a list."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        self.objective = self.objective.strip()
        self.problem_statement = self.problem_statement.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)


class ProductSpecDraft(models.Model):
    class ReviewStatus(models.TextChoices):
        NEEDS_REVIEW = "NEEDS_REVIEW"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(ProductSpecContract, on_delete=models.PROTECT, related_name="drafts")
    title = models.CharField(max_length=200)
    content = models.JSONField(default=dict)
    assumptions = models.JSONField(default=list, blank=True)
    risks = models.JSONField(default=list, blank=True)
    review_status = models.CharField(max_length=16, choices=ReviewStatus.choices, default=ReviewStatus.NEEDS_REVIEW)
    no_external_write = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Title cannot be empty."})
        if not isinstance(self.content, dict):
            raise ValidationError({"content": "Content must be an object."})
        if not isinstance(self.assumptions, list):
            raise ValidationError({"assumptions": "Assumptions must be a list."})
        if not isinstance(self.risks, list):
            raise ValidationError({"risks": "Risks must be a list."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        self.created_by = self.created_by.strip() or "api"
        super().save(*args, **kwargs)


class ProductMilestone(models.Model):
    class Status(models.TextChoices):
        PLANNED = "PLANNED"
        ACTIVE = "ACTIVE"
        COMPLETED = "COMPLETED"
        DELAYED = "DELAYED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    objective = models.ForeignKey(Objective, on_delete=models.PROTECT, null=True, blank=True, related_name="product_milestones")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    target_date = models.DateField()
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PLANNED)
    release_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["target_date", "created_at"]

    def clean(self) -> None:
        if not self.name or not self.name.strip():
            raise ValidationError({"name": "Milestone name cannot be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.name = self.name.strip()
        self.description = self.description.strip()
        self.release_notes = self.release_notes.strip()
        super().save(*args, **kwargs)


class ProductFeature(models.Model):
    class Status(models.TextChoices):
        BACKLOG = "BACKLOG"
        PLANNED = "PLANNED"
        IN_PROGRESS = "IN_PROGRESS"
        COMPLETED = "COMPLETED"
        ARCHIVED = "ARCHIVED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="features")
    milestone = models.ForeignKey(ProductMilestone, on_delete=models.SET_NULL, null=True, blank=True, related_name="features")
    title = models.CharField(max_length=200)
    user_story = models.TextField(blank=True)
    acceptance_criteria = models.JSONField(default=list, blank=True)
    reach = models.PositiveIntegerField(default=100)
    impact = models.FloatField(default=1.0)
    confidence = models.FloatField(default=0.8)
    effort = models.FloatField(default=1.0)
    rice_score = models.FloatField(default=80.0)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.BACKLOG)
    created_by = models.CharField(max_length=128, default="product_manager")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-rice_score", "created_at"]

    def calculate_rice(self) -> float:
        eff = max(0.1, float(self.effort))
        score = (float(self.reach) * float(self.impact) * float(self.confidence)) / eff
        return round(score, 2)

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Feature title cannot be empty."})
        if self.effort <= 0:
            raise ValidationError({"effort": "Effort must be greater than 0."})

    def save(self, *args, **kwargs):
        self.rice_score = self.calculate_rice()
        self.full_clean()
        self.title = self.title.strip()
        self.user_story = self.user_story.strip()
        super().save(*args, **kwargs)


class ProductFeedback(models.Model):
    class Sentiment(models.TextChoices):
        POSITIVE = "POSITIVE"
        NEUTRAL = "NEUTRAL"
        NEGATIVE = "NEGATIVE"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="feedbacks")
    feature = models.ForeignKey(ProductFeature, on_delete=models.SET_NULL, null=True, blank=True, related_name="feedbacks")
    source = models.CharField(max_length=128)
    user_segment = models.CharField(max_length=64, default="General")
    content = models.TextField()
    sentiment = models.CharField(max_length=16, choices=Sentiment.choices, default=Sentiment.NEUTRAL)
    action_item = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.source or not self.source.strip():
            raise ValidationError({"source": "Source cannot be empty."})
        if not self.content or not self.content.strip():
            raise ValidationError({"content": "Content cannot be empty."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.source = self.source.strip()
        self.content = self.content.strip()
        self.action_item = self.action_item.strip()
        super().save(*args, **kwargs)


class UserResearchContract(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN"
        IN_REVIEW = "IN_REVIEW"
        CLOSED = "CLOSED"

    class Method(models.TextChoices):
        INTERVIEW_NOTES = "INTERVIEW_NOTES"
        USABILITY_NOTES = "USABILITY_NOTES"
        SUPPORT_NOTES = "SUPPORT_NOTES"
        INTERNAL_SYNTHESIS = "INTERNAL_SYNTHESIS"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    spec_contract = models.ForeignKey(ProductSpecContract, on_delete=models.PROTECT, related_name="user_research_contracts")
    title = models.CharField(max_length=200)
    research_question = models.TextField()
    method = models.CharField(max_length=32, choices=Method.choices, default=Method.INTERVIEW_NOTES)
    participant_segment = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    no_customer_contact = models.BooleanField(default=True)
    no_external_write = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Title cannot be empty."})
        if not self.research_question or not self.research_question.strip():
            raise ValidationError({"research_question": "Research question cannot be empty."})
        if self.method not in self.Method.values:
            raise ValidationError({"method": "Method is not allowed."})
        if self.no_customer_contact is not True or self.no_external_write is not True:
            raise ValidationError("User research artifacts cannot contact a customer or write outside Sharons.")

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        self.research_question = self.research_question.strip()
        self.participant_segment = self.participant_segment.strip()
        self.created_by = self.created_by.strip() or "api"
        self.no_customer_contact = True
        self.no_external_write = True
        super().save(*args, **kwargs)


class UserResearchInterview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(UserResearchContract, on_delete=models.PROTECT, related_name="interviews")
    label = models.CharField(max_length=160)
    segment = models.CharField(max_length=120, blank=True)
    summary = models.TextField()
    observations = models.JSONField(default=list, blank=True)
    no_customer_contact = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def clean(self) -> None:
        if not self.label or not self.label.strip():
            raise ValidationError({"label": "Interview label cannot be empty."})
        if not self.summary or not self.summary.strip():
            raise ValidationError({"summary": "Interview summary cannot be empty."})
        if not isinstance(self.observations, list):
            raise ValidationError({"observations": "Observations must be a list."})
        if self.no_customer_contact is not True:
            raise ValidationError("User research interviews cannot contact a customer.")

    def save(self, *args, **kwargs):
        self.full_clean()
        self.label = self.label.strip()
        self.segment = self.segment.strip()
        self.summary = self.summary.strip()
        self.created_by = self.created_by.strip() or "api"
        self.no_customer_contact = True
        super().save(*args, **kwargs)


class UserResearchFinding(models.Model):
    class Confidence(models.TextChoices):
        LOW = "LOW"
        MEDIUM = "MEDIUM"
        HIGH = "HIGH"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(UserResearchContract, on_delete=models.PROTECT, related_name="findings")
    interview = models.ForeignKey(UserResearchInterview, on_delete=models.PROTECT, null=True, blank=True, related_name="findings")
    statement = models.TextField()
    evidence_note = models.TextField(blank=True)
    confidence = models.CharField(max_length=16, choices=Confidence.choices, default=Confidence.LOW)
    related_requirement_id = models.CharField(max_length=64, blank=True)
    no_customer_contact = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def clean(self) -> None:
        if not self.statement or not self.statement.strip():
            raise ValidationError({"statement": "Finding statement cannot be empty."})
        if self.confidence not in self.Confidence.values:
            raise ValidationError({"confidence": "Confidence must be LOW, MEDIUM or HIGH."})
        if self.interview_id and self.interview.contract_id != self.contract_id:
            raise ValidationError({"interview": "Finding interview must belong to the same research contract."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.statement = self.statement.strip()
        self.evidence_note = self.evidence_note.strip()
        self.related_requirement_id = self.related_requirement_id.strip()
        self.created_by = self.created_by.strip() or "api"
        self.no_customer_contact = True
        super().save(*args, **kwargs)


class UserResearchQuestion(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN"
        DEFERRED = "DEFERRED"
        RESOLVED = "RESOLVED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(UserResearchContract, on_delete=models.PROTECT, related_name="questions")
    question = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    resolution_note = models.TextField(blank=True)
    no_customer_contact = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def clean(self) -> None:
        if not self.question or not self.question.strip():
            raise ValidationError({"question": "Open question cannot be empty."})
        if self.status in {self.Status.DEFERRED, self.Status.RESOLVED} and not self.resolution_note.strip():
            raise ValidationError({"resolution_note": "Deferred or resolved questions require a resolution note."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.question = self.question.strip()
        self.resolution_note = self.resolution_note.strip()
        self.created_by = self.created_by.strip() or "api"
        self.no_customer_contact = True
        super().save(*args, **kwargs)


class CompetitiveAnalysisDraft(models.Model):
    class ReviewStatus(models.TextChoices):
        NEEDS_REVIEW = "NEEDS_REVIEW"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    spec_contract = models.ForeignKey(ProductSpecContract, on_delete=models.PROTECT, related_name="competitive_analyses")
    title = models.CharField(max_length=200)
    competitor_label = models.CharField(max_length=160)
    comparison_points = models.JSONField(default=list, blank=True)
    implications = models.TextField()
    review_status = models.CharField(max_length=16, choices=ReviewStatus.choices, default=ReviewStatus.NEEDS_REVIEW)
    no_customer_contact = models.BooleanField(default=True)
    no_external_write = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Title cannot be empty."})
        if not self.competitor_label or not self.competitor_label.strip():
            raise ValidationError({"competitor_label": "Competitor label cannot be empty."})
        if not self.implications or not self.implications.strip():
            raise ValidationError({"implications": "Implications cannot be empty."})
        if not isinstance(self.comparison_points, list) or not self.comparison_points:
            raise ValidationError({"comparison_points": "At least one comparison point is required."})
        if self.no_customer_contact is not True or self.no_external_write is not True:
            raise ValidationError("Competitive analysis stays internal and does not contact anyone.")

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        self.competitor_label = self.competitor_label.strip()
        self.implications = self.implications.strip()
        self.created_by = self.created_by.strip() or "api"
        self.no_customer_contact = True
        self.no_external_write = True
        super().save(*args, **kwargs)


class PricingExperimentBrief(models.Model):
    class ReviewStatus(models.TextChoices):
        NEEDS_REVIEW = "NEEDS_REVIEW"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    spec_contract = models.ForeignKey(ProductSpecContract, on_delete=models.PROTECT, related_name="pricing_experiments")
    title = models.CharField(max_length=200)
    hypothesis = models.TextField()
    success_metric = models.CharField(max_length=160)
    currency = models.CharField(max_length=3, default="ILS")
    variants = models.JSONField(default=list)
    success_criterion = models.TextField()
    stop_condition = models.TextField()
    review_status = models.CharField(max_length=16, choices=ReviewStatus.choices, default=ReviewStatus.NEEDS_REVIEW)
    no_customer_contact = models.BooleanField(default=True)
    no_external_write = models.BooleanField(default=True)
    no_payment = models.BooleanField(default=True)
    no_spend = models.BooleanField(default=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Title cannot be empty."})
        if not self.hypothesis or not self.hypothesis.strip():
            raise ValidationError({"hypothesis": "Hypothesis cannot be empty."})
        if not self.success_metric or not self.success_metric.strip():
            raise ValidationError({"success_metric": "Success metric cannot be empty."})
        if self.currency != "ILS":
            raise ValidationError({"currency": "Pricing experiment briefs use ILS."})
        if not self.success_criterion or not self.success_criterion.strip():
            raise ValidationError({"success_criterion": "Success criterion cannot be empty."})
        if not self.stop_condition or not self.stop_condition.strip():
            raise ValidationError({"stop_condition": "Stop condition cannot be empty."})
        if not isinstance(self.variants, list) or not 2 <= len(self.variants) <= 4:
            raise ValidationError({"variants": "A pricing experiment brief needs two to four variants."})
        labels = []
        for item in self.variants:
            if not isinstance(item, dict):
                raise ValidationError({"variants": "Each variant must be an object."})
            label = str(item.get("label", "")).strip()
            amount = str(item.get("amount", "")).strip()
            if not label or not amount:
                raise ValidationError({"variants": "Each variant requires label and amount."})
            labels.append(label)
        if len(set(labels)) != len(labels):
            raise ValidationError({"variants": "Variant labels must be unique."})
        if any(flag is not True for flag in (self.no_customer_contact, self.no_external_write, self.no_payment, self.no_spend)):
            raise ValidationError("A pricing experiment brief cannot contact, charge, spend, or write externally.")

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        self.hypothesis = self.hypothesis.strip()
        self.success_metric = self.success_metric.strip()
        self.currency = "ILS"
        self.success_criterion = self.success_criterion.strip()
        self.stop_condition = self.stop_condition.strip()
        self.created_by = self.created_by.strip() or "api"
        self.no_customer_contact = True
        self.no_external_write = True
        self.no_payment = True
        self.no_spend = True
        super().save(*args, **kwargs)


class GithubIssueRequest(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PENDING_APPROVAL = "PENDING_APPROVAL"
        CREATED = "CREATED"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="github_issue_requests")
    project_connection = models.ForeignKey(ProjectConnection, on_delete=models.PROTECT, related_name="github_issue_requests")
    title = models.CharField(max_length=200)
    body = models.TextField()
    repository_owner = models.CharField(max_length=128)
    repository_name = models.CharField(max_length=128)
    secret_reference_name = models.CharField(max_length=128)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    version = models.PositiveIntegerField(default=1)
    allowed_action = models.CharField(max_length=32, default="create_issue")
    approval_request_id = models.UUIDField(null=True, blank=True)
    issue_number = models.PositiveIntegerField(null=True, blank=True)
    issue_url = models.CharField(max_length=300, blank=True)
    created_by = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if not self.title or not self.title.strip():
            raise ValidationError({"title": "Title cannot be empty."})
        if not self.body or not self.body.strip():
            raise ValidationError({"body": "Body cannot be empty."})
        if self.allowed_action != "create_issue":
            raise ValidationError({"allowed_action": "The only approved GitHub action is create_issue."})

    def save(self, *args, **kwargs):
        self.full_clean()
        self.title = self.title.strip()
        self.body = self.body.strip()
        self.repository_owner = self.repository_owner.strip()
        self.repository_name = self.repository_name.strip()
        self.secret_reference_name = self.secret_reference_name.strip()
        self.created_by = self.created_by.strip() or "api"
        self.allowed_action = "create_issue"
        super().save(*args, **kwargs)

