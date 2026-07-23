from app.dao.mysql.operation_repository import InMemoryOperationRepository
from app.dao.redis.event_publisher import InMemoryEventPublisher
from app.dao.redis.state_store import InMemoryStateStore
from app.service.nl2api.operation_service import OperationService
from app.tool.operation.registry import OperationToolRegistry


def build_test_service() -> tuple[
    OperationService,
    InMemoryOperationRepository,
    InMemoryEventPublisher,
]:
    repository = InMemoryOperationRepository()
    publisher = InMemoryEventPublisher()
    service = OperationService(
        repository,
        InMemoryStateStore(),
        publisher,
        OperationToolRegistry(),
        risk_review_ttl_seconds=300,
        confirmation_ttl_seconds=900,
        idempotency_ttl_seconds=3600,
    )
    return service, repository, publisher

