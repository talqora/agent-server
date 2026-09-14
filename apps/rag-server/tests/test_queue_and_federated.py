"""队列载荷与联邦身份单测。"""

from agent_core.federated import FederatedIdentity
from agent_core.queue import RunJob
from sqlalchemy.exc import IntegrityError


def test_run_job_roundtrip() -> None:
    job = RunJob(run_id="run-1", user_id=7, kind="ingestion")
    data = job.to_bytes()
    assert b"runId" in data and b"ingestion" in data  # 线格式与 Node 版 RunJobData 对齐
    assert RunJob.from_bytes(data) == job


class FakeUserStore:
    def __init__(self) -> None:
        self.by_key: dict[tuple[str, str], int] = {}
        self.raise_conflict_once = False
        self.created = 0

    async def find_by_issuer_subject(self, issuer: str, subject: str) -> int | None:
        return self.by_key.get((issuer, subject))

    async def create_federated_user(
        self,
        *,
        issuer: str,
        subject: str,
        username: str,
        display_name: str,
        role_code: str,
    ) -> int:
        self.created += 1
        if self.raise_conflict_once:
            self.raise_conflict_once = False
            # 模拟并发首见:另一请求已抢先建好 → 唯一约束冲突
            self.by_key[(issuer, subject)] = 999
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        self.by_key[(issuer, subject)] = 42
        return 42


async def test_federated_resolve_and_cache() -> None:
    store = FakeUserStore()
    identity = FederatedIdentity(store)

    uid = await identity.resolve_local_user_id(issuer="https://idp", subject="u1")
    assert uid == 42 and store.created == 1
    # 二次命中进程内缓存,不再查存储
    uid2 = await identity.resolve_local_user_id(issuer="https://idp", subject="u1")
    assert uid2 == 42 and store.created == 1


async def test_federated_conflict_converges() -> None:
    store = FakeUserStore()
    store.raise_conflict_once = True
    identity = FederatedIdentity(store)

    uid = await identity.resolve_local_user_id(issuer="https://idp", subject="u2")
    assert uid == 999  # 冲突后回查收敛到已存在的本地 id
