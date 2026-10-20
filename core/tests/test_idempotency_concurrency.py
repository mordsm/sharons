import threading

import pytest
from django.db import IntegrityError, close_old_connections, transaction

from core.models import IdempotencyRecord


@pytest.mark.django_db(transaction=True)
def test_duplicate_idempotency_key_cannot_commit_concurrently():
    barrier = threading.Barrier(2)
    results: list[str] = []

    def create_record(label: str) -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                barrier.wait(timeout=5)
                IdempotencyRecord.objects.create(
                    key="same-concurrent-key",
                    request_hash=f"hash-{label}",
                    response_payload={"label": label},
                    status_code=201,
                )
            results.append("created")
        except IntegrityError:
            results.append("integrity-error")
        finally:
            close_old_connections()

    threads = [threading.Thread(target=create_record, args=(str(index),)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert sorted(results) == ["created", "integrity-error"]
    assert IdempotencyRecord.objects.filter(key="same-concurrent-key").count() == 1
